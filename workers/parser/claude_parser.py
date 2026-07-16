"""
ZigZag — Claude parser worker
=============================
Cita neobradene redove iz external_signals, salje Claude-u, upisuje
strukturirani rezultat u parsed_signals i donosi odluku (execute/skip).

Pokretanje:  python -m parser.claude_parser        (iz workers/ direktorija)
Radi na bilo kom Linux/Windows hostu (Railway, Fly.io, VPS...).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import anthropic
from dotenv import load_dotenv

from common.db import sb
from common.log import heartbeat, log
from common.notify import notify
from common.settings import get_settings, kill_switch_on

load_dotenv()

POLL_SECONDS = 5

# ---------------------------------------------------------------- Claude tool
PARSE_TOOL = {
    "name": "record_signal",
    "description": "Zapisi strukturirani rezultat parsiranja trading poruke.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message_type": {
                "type": "string",
                "enum": ["new_signal", "update_sl", "tp_hit", "move_to_be", "close", "partial_close", "noise"],
                "description": (
                    "new_signal: kompletan novi trejd (smjer + entry + SL/TP). "
                    "update_sl: promjena SL postojeceg. tp_hit: javlja da je TP pogoden. "
                    "move_to_be: instrukcija da se SL pomjeri na entry/breakeven. "
                    "close/partial_close: zatvori sve/dio. noise: sve ostalo (analize, pozdravi, reklame)."
                ),
            },
            "symbol": {"type": ["string", "null"], "description": "Normalizovan simbol, npr. XAUUSD. GOLD -> XAUUSD."},
            "direction": {"type": ["string", "null"], "enum": ["buy", "sell", None]},
            "entry_low": {"type": ["number", "null"], "description": "Donja granica entry raspona (ili jedina cijena)."},
            "entry_high": {"type": ["number", "null"], "description": "Gornja granica entry raspona (ista kao entry_low ako nema raspona)."},
            "sl": {"type": ["number", "null"]},
            "tps": {"type": "array", "items": {"type": "number"}, "description": "TP nivoi po redu (TP1 prvi)."},
            "tp_index": {"type": ["integer", "null"], "description": "Za tp_hit: koji TP je pogoden (1-based)."},
            "confidence": {"type": "number", "description": "0..1 — koliko si siguran u parsiranje."},
            "caution_flags": {
                "type": "array", "items": {"type": "string"},
                "description": "Upozorenja iz teksta: npr. 'chasing', 'small_lots', 'risky', 'not_ideal_entry'.",
            },
            "notes": {"type": "string", "description": "Kratko objasnjenje (1 recenica)."},
        },
        "required": ["message_type", "confidence"],
    },
}

SYSTEM_PROMPT = """Ti si parser trading signala za XAUUSD (zlato). Dobijas sirove poruke sa Telegram \
kanala koji agregira signale vise provajdera. Poruke su na engleskom, arapskom ili BHS jezicima, \
razlicitih formata.

Pravila:
1. UVIJEK pozovi record_signal alat, nikad ne odgovaraj tekstom.
2. "GOLD", "XAU", "XAU/USD" -> symbol "XAUUSD". Druge simbole (EURUSD, BTC...) parsiraj normalno.
3. Entry moze biti raspon ("OPEN: 4068-4070") ili jedna cijena. Ako je jedna cijena, entry_low = entry_high.
4. "TP1 HIT +60 PIPS" -> message_type tp_hit, tp_index 1.
5. "secure some profits and BE" / "move SL to entry" -> move_to_be.
6. "close now" / "close half" -> close / partial_close.
7. Fraze poput "small lots", "we are chasing", "not ideal entry", "risky" -> dodaj u caution_flags.
8. Analize trzista, screenshotovi bez brojeva, pozdravi, reklame -> noise sa confidence koliko si siguran da JESTE noise.
9. confidence < 0.6 znaci da nisi siguran sta poruka znaci.
10. Ne izmisljaj brojeve koji nisu u poruci. Ako SL/TP fali, ostavi null/prazno."""


# ---------------------------------------------------------------- helpers
def get_unparsed(text_col: str, provider_col: str, status_col: str, limit: int = 10) -> list[dict]:
    """Redovi iz external_signals koje ZigZag jos nije obradio.

    external_signals je tabela DIJELJENA sa drugim (stariji) pipelineom koji
    ima CHECK constraint na parse_status (dozvoljava samo pending/parsed/
    unparseable) — pisanje 'zz_parsed'/'zz_error' tamo UVIJEK puca (23514) i
    bilo je silent-swallowed, sto je izazvalo beskonacnu re-obradu istih redova
    i spaljivanje Anthropic budzeta. Zato je ZigZag "obradio ovo" sad utvrdjeno
    iskljucivo kroz postojanje reda u parsed_signals.external_signal_id — ne
    diramo tudju parse_status kolonu nikako.
    """
    try:
        candidates = (
            sb().table("external_signals")
            .select(f"id,{text_col},{provider_col},created_at")
            .or_(f"{status_col}.is.null,{status_col}.eq.pending,{status_col}.eq.new")
            .order("created_at", desc=False)
            .limit(limit * 5)
            .execute()
            .data
        ) or []
        if not candidates:
            return []
        ids = [r["id"] for r in candidates]
        done_rows = (
            sb().table("parsed_signals").select("external_signal_id")
            .in_("external_signal_id", ids)
            .execute().data
        ) or []
        done_ids = {d["external_signal_id"] for d in done_rows}
        fresh = [r for r in candidates if r["id"] not in done_ids]
        return fresh[:limit]
    except Exception as e:
        log(f"Ne mogu citati external_signals ({e}). Provjeri mapiranje kolona u Postavkama.",
            level="error", category="parser")
        return []


def call_claude(client: anthropic.Anthropic, model: str, max_tokens: int, raw_text: str) -> dict | None:
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        tools=[PARSE_TOOL],
        tool_choice={"type": "tool", "name": "record_signal"},
        messages=[{"role": "user", "content": f"Parsiraj ovu poruku:\n\n{raw_text}"}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_signal":
            return dict(block.input)
    return None


def find_referenced_signal(provider: str | None, symbol: str | None) -> dict | None:
    """Za update/tp_hit poruke: zadnji new_signal istog provajdera, ISTOG simbola,
    u zadnjih 24h. Bez ovoga bi follow-up poruka mogla zakaciti pogresan (drugi
    simbol) ili prestar signal — executor bi onda azurirao/zatvorio pogresnu poziciju.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    q = (
        sb().table("parsed_signals")
        .select("id,decision,tps,entry_low,entry_high,direction,symbol")
        .eq("message_type", "new_signal")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(1)
    )
    if provider:
        q = q.eq("provider", provider)
    if symbol:
        q = q.eq("symbol", symbol)
    rows = q.execute().data or []
    return rows[0] if rows else None


def decide(parsed: dict, settings: dict, provider: str | None) -> tuple[str, str]:
    """Odluka execute/skip + razlog. Executor dodatno provjerava cijenu uzivo."""
    risk = settings["risk"]
    mt5 = settings["mt5"]

    if parsed["message_type"] == "noise":
        return "skip", "Poruka nije trading signal."

    if parsed["message_type"] != "new_signal":
        # follow-up poruke uvijek prosljedujemo executoru da azurira poziciju
        return "execute", f"Follow-up ({parsed['message_type']}) — executor ažurira postojeću poziciju."

    if kill_switch_on():
        return "skip", "Kill switch je uključen."

    conf = float(parsed.get("confidence") or 0)
    if conf < float(risk["min_confidence"]):
        return "skip", f"Confidence {conf:.2f} ispod praga {risk['min_confidence']}."

    symbol = (parsed.get("symbol") or "").upper()
    if symbol != str(mt5.get("symbol", "XAUUSD")).upper():
        return "skip", f"Simbol {symbol or '?'} nije {mt5.get('symbol')} — trgujemo samo zlato."

    if not parsed.get("direction") or parsed.get("sl") is None or not parsed.get("tps"):
        return "skip", "Nedostaje smjer, SL ili TP — nekompletan signal."

    if provider:
        try:
            ps = sb().table("provider_stats").select("enabled").eq("provider", provider).single().execute().data
            if ps and not ps.get("enabled", True):
                return "skip", f"Provajder '{provider}' je isključen na dashboardu."
        except Exception:
            pass  # nema statistike jos — pusti

    flags = parsed.get("caution_flags") or []
    if flags:
        return "execute", f"Signal OK uz oprez ({', '.join(flags)}) — executor smanjuje lot."

    return "execute", "Signal kompletan i prošao sve filtere."


# ---------------------------------------------------------------- main loop
def process_row(client: anthropic.Anthropic, row: dict, settings: dict, text_col: str, provider_col: str, status_col: str) -> None:
    raw_text = (row.get(text_col) or "").strip()
    provider = row.get(provider_col)
    if not raw_text:
        # prazan tekst: nema sta parsirati, ali JOS upisujemo placeholder parsed_signals
        # red (message_type=noise) da get_unparsed() vise ne vraca ovaj id (anti-join).
        sb().table("parsed_signals").insert({
            "id": str(uuid.uuid4()), "external_signal_id": row["id"], "provider": provider,
            "message_type": "noise", "decision": "skip", "decision_reason": "Prazan tekst poruke.",
            "raw_text": "", "tps": [], "confidence": 1.0, "processed_at": None,
        }).execute()
        return

    model = settings["anthropic"]["model"]
    max_tokens = int(settings["anthropic"].get("max_tokens", 1024))

    parsed = call_claude(client, model, max_tokens, raw_text)
    if not parsed:
        log("Claude nije vratio tool poziv", level="error", category="parser", meta={"external_id": row["id"]})
        sb().table("parsed_signals").insert({
            "id": str(uuid.uuid4()), "external_signal_id": row["id"], "provider": provider,
            "message_type": "noise", "decision": "skip", "decision_reason": "Claude parse greska — vidi activity log.",
            "raw_text": raw_text[:4000], "tps": [], "confidence": 0.0, "processed_at": None,
        }).execute()
        return

    ref = None
    if parsed["message_type"] in ("update_sl", "tp_hit", "move_to_be", "close", "partial_close"):
        ref = find_referenced_signal(provider, parsed.get("symbol"))

    decision, reason = decide(parsed, settings, provider)

    record = {
        "id": str(uuid.uuid4()),
        "external_signal_id": row["id"],
        "provider": provider,
        "message_type": parsed["message_type"],
        "symbol": parsed.get("symbol"),
        "direction": parsed.get("direction"),
        "entry_low": parsed.get("entry_low"),
        "entry_high": parsed.get("entry_high"),
        "sl": parsed.get("sl"),
        "tps": parsed.get("tps") or [],
        "confidence": parsed.get("confidence"),
        "references_signal_id": ref["id"] if ref else None,
        "decision": decision,
        "decision_reason": reason,
        "raw_text": raw_text[:4000],
        "processed_at": None,  # executor upisuje kad obradi follow-up (queue marker, vidi migraciju 002)
    }
    sb().table("parsed_signals").insert(record).execute()

    if parsed["message_type"] == "new_signal":
        log(
            f"{parsed.get('symbol')} {str(parsed.get('direction')).upper()} → {decision} ({reason})",
            level="trade" if decision == "execute" else "warn",
            category="parser",
            meta={"signal_id": record["id"], "confidence": parsed.get("confidence")},
        )
        if decision == "execute":
            tps = " / ".join(str(t) for t in (parsed.get("tps") or []))
            notify(
                f"📡 <b>Novi signal</b> — {parsed.get('symbol')} {str(parsed.get('direction')).upper()}\n"
                f"Entry: {parsed.get('entry_low')}–{parsed.get('entry_high')}\n"
                f"SL: {parsed.get('sl')}  |  TP: {tps}\n"
                f"➡️ Šaljem executoru."
            )
        else:
            notify(f"⏭ <b>Preskočen signal</b>\n{reason}")
    elif parsed["message_type"] != "noise":
        log(f"Follow-up: {parsed['message_type']}", category="parser",
            meta={"signal_id": record["id"], "ref": record["references_signal_id"]})


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY nije postavljen u .env")
    client = anthropic.Anthropic()
    log("Parser pokrenut", category="parser")

    while True:
        try:
            settings = get_settings()
            cols = settings["external_signals"]
            text_col = cols["text_column"]
            provider_col = cols["provider_column"]
            status_col = cols.get("status_column", "parse_status")

            rows = get_unparsed(text_col, provider_col, status_col)
            for row in rows:
                process_row(client, row, settings, text_col, provider_col, status_col)

            heartbeat("parser", meta={"queue": len(rows)})
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"Parser greška: {e}", level="error", category="parser")
            heartbeat("parser", status="degraded")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
