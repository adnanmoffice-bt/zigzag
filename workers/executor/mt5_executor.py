"""
ZigZag — MT5 executor (MetaApi.cloud bridge — radi na bilo kom hostu)
======================================================================
Cita parsed_signals sa decision='execute', otvara/azurira pozicije preko
MetaApi.cloud (koji hostuje MT5 terminal konekciju ka IG brokeru), primjenjuje
risk pravila i upisuje sve nazad u Supabase.

Pokretanje:  python -m executor.mt5_executor      (iz workers/ direktorija)

Preduslovi:
  1) python -m executor.metaapi_provision   (jednokratno — kreira MetaApi nalog)
  2) .env: METAAPI_TOKEN (app.metaapi.cloud/token), MT5_PASSWORD
  3) bot_settings.mt5: login, server, metaapi_account_id (popuni provisioning skript)

XAUUSD matematika (IG): 1 lot = 100 oz; kretanje $1.00 = $100 po lotu.
  lot = rizik_$ / (SL_distance_$ * 100)
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from metaapi_cloud_sdk import MetaApi

from common.db import sb
from common.log import heartbeat, log
from common.notify import notify
from common.settings import get_settings, kill_switch_on

load_dotenv()

POLL_SECONDS = 3
EQUITY_SNAPSHOT_EVERY = 300  # 5 min
MAGIC_BASE = 777000  # magic = MAGIC_BASE + tp_index

# stringCode vrijednosti koje MetaApi smatra uspjehom (vidi MetatraderTradeResponse)
TRADE_SUCCESS_CODES = {"ERR_NO_ERROR", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE",
                       "TRADE_RETCODE_DONE_PARTIAL", "TRADE_RETCODE_NO_CHANGES"}


# ---------------------------------------------------------------- MetaApi osnove
async def mt5_connect(settings: dict) -> Any | None:
    """Poveze se na MetaApi.cloud (cloud-hosted MT5 terminal) — vraca streaming
    connection ili None. Za razliku od lokalnog MetaTrader5 paketa, ovo radi na
    bilo kom hostu (Linux, Windows, Mac) — MetaApi izvodi stvarnu konekciju ka
    IG brokeru u svojoj infrastrukturi.
    """
    cfg = settings["mt5"]
    token = os.environ.get("METAAPI_TOKEN", "")
    account_id = cfg.get("metaapi_account_id")
    if not token:
        log("METAAPI_TOKEN nije postavljen u .env (app.metaapi.cloud/token).", level="error", category="executor")
        return None
    if not account_id:
        log("bot_settings.mt5.metaapi_account_id nije postavljen — pokreni python -m executor.metaapi_provision",
            level="error", category="executor")
        return None

    api = MetaApi(token=token)
    account = await api.metatrader_account_api.get_account(account_id)
    if account.state != "DEPLOYED":
        log(f"MetaApi nalog nije deploy-ovan (stanje: {account.state}) — deploy-ujem...", category="executor")
        await account.deploy()
    await account.wait_connected()

    connection = account.get_streaming_connection()
    await connection.connect()
    await connection.wait_synchronized()
    await connection.subscribe_to_market_data(symbol=full_symbol(settings))
    return connection


def full_symbol(settings: dict) -> str:
    cfg = settings["mt5"]
    return f"{cfg['symbol']}{cfg.get('symbol_suffix', '')}"


def current_price(connection: Any, symbol: str) -> tuple[float, float] | None:
    """Cijena iz lokalnog sync-ovanog terminal_state — ne kosta dodatni API poziv."""
    price = connection.terminal_state.price(symbol=symbol)
    if not price:
        return None
    return float(price["bid"]), float(price["ask"])


def account_equity(connection: Any) -> tuple[float, float] | None:
    """Vraca None ako terminal_state cache nije (jos) popunjen — desync/reconnect
    hiccup daje account_information=None, sto NE znaci balance 0; nikad ne pisi
    lazan nula-snapshot u equity_snapshots."""
    info = connection.terminal_state.account_information
    if not info or info.get("balance") is None:
        return None
    return float(info["balance"]), float(info.get("equity", info["balance"]))


def positions_for_symbol(connection: Any, symbol: str) -> list[dict]:
    return [p for p in connection.terminal_state.positions if p.get("symbol") == symbol]


def positions_for_signal(connection: Any, ref_id: str) -> list[dict]:
    """Pozicije vezane za signal preko comment taga zz:<id8>."""
    tag = f"zz:{ref_id[:8]}"
    return [p for p in connection.terminal_state.positions if tag in (p.get("comment") or "")]


# ---------------------------------------------------------------- risk (nepromijenjeno — MetaApi ne dira ovu logiku)
def compute_lot(equity: float, sl_distance: float, risk: dict, multiplier: float) -> float:
    """lot = rizik_$ / (SL_distance_$ * 100) za XAUUSD.

    Rizik po signalu = manji od (equity x risk_percent) i max_risk_usd caps.
    max_risk_usd je tvrdi $ cap: koliko se najvise gubi ako SL udari — stiti
    budzet nezavisno od velicine racuna (0 = cap iskljucen).
    """
    if sl_distance <= 0:
        return 0.0
    risk_usd = equity * float(risk["risk_percent"]) / 100.0
    max_risk = float(risk.get("max_risk_usd", 0) or 0)
    if max_risk > 0:
        risk_usd = min(risk_usd, max_risk)
    risk_usd *= multiplier
    lot = risk_usd / (sl_distance * 100.0)
    lot = math.floor(lot * 100) / 100.0  # floor na 0.01 — nikad round-up
    return max(min(lot, float(risk["lot_cap"])), 0.0)


def daily_loss_exceeded(risk: dict, balance: float) -> bool:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = (
        sb().table("trade_executions").select("profit")
        .eq("status", "closed").gte("closed_at", today).execute().data
    ) or []
    pnl = sum(r.get("profit") or 0 for r in rows)
    limit = -balance * float(risk["daily_max_loss_percent"]) / 100.0
    return pnl <= limit


def provider_multiplier(provider: str | None) -> float:
    if not provider:
        return 1.0
    try:
        row = sb().table("provider_stats").select("risk_multiplier,enabled").eq("provider", provider).single().execute().data
        if row and not row.get("enabled", True):
            return 0.0
        return float(row.get("risk_multiplier", 1.0)) if row else 1.0
    except Exception:
        return 1.0


# ---------------------------------------------------------------- izvrsenje
async def open_new_signal(connection: Any, signal: dict, settings: dict) -> None:
    risk = settings["risk"]
    symbol = full_symbol(settings)

    prices = current_price(connection, symbol)
    if not prices:
        log(f"Nema cijene za {symbol}", level="error", category="executor")
        return
    bid, ask = prices

    direction = signal["direction"]
    is_buy = direction == "buy"
    market_price = ask if is_buy else bid
    e_low = float(signal["entry_low"] or signal["entry_high"] or 0)
    e_high = float(signal["entry_high"] or signal["entry_low"] or 0)
    sl = float(signal["sl"])
    tps = [float(t) for t in (signal.get("tps") or [])][:4]

    # --- 1) je li SL vec probijen?
    if (is_buy and market_price <= sl) or (not is_buy and market_price >= sl):
        skip(signal, f"Cijena {market_price:.2f} je već iza SL {sl:.2f} — signal mrtav.")
        return

    # --- 2) slippage / chasing zastita
    slippage_max = float(risk["slippage_max_usd"])
    in_range = e_low - 0.01 <= market_price <= e_high + 0.01
    dist_from_range = 0.0 if in_range else min(abs(market_price - e_low), abs(market_price - e_high))
    caution_cut = 1.0
    if not in_range:
        # udaljenost u "dobrom" smjeru (bolja cijena) je OK; u losem smjeru je chasing
        chasing = (is_buy and market_price > e_high) or (not is_buy and market_price < e_low)
        if chasing and dist_from_range > slippage_max:
            skip(signal, f"Cijena {market_price:.2f} je {dist_from_range:.2f}$ iza entry raspona (max {slippage_max}$) — chasing, preskačem.")
            return
        if chasing:
            caution_cut = 0.5  # u rasponu tolerancije, ali smanji lot

    # --- 3) daily loss limit + max positions
    eq = account_equity(connection)
    if eq is None:
        skip(signal, "Terminal state nije sinhronizovan (nema account_information) — preskačem dok se ne stabilizuje.")
        return
    balance, equity = eq
    if daily_loss_exceeded(risk, balance):
        skip(signal, "Dnevni max gubitak dosegnut — bot pauziran do sutra.")
        notify("🛑 <b>Dnevni limit gubitka dosegnut.</b> Bot ne otvara nove pozicije do sutra.")
        return
    open_now = len(positions_for_symbol(connection, symbol))
    if open_now >= int(risk["max_open_positions"]):
        skip(signal, f"Već {open_now} otvorenih pozicija (max {risk['max_open_positions']}).")
        return

    # --- 4) lot
    mult = provider_multiplier(signal.get("provider")) * caution_cut
    if mult == 0.0:
        skip(signal, "Provajder isključen.")
        return
    sl_distance = abs(market_price - sl)
    total_lot = compute_lot(equity, sl_distance, risk, mult)
    lot_floor = float(risk["lot_floor"])
    if total_lot < lot_floor:
        skip(signal, f"Izračunati lot {total_lot:.2f} ispod minimuma {lot_floor} — rizik premali za SL distancu {sl_distance:.2f}$.")
        return

    n_legs = max(len(tps), 1)
    per_leg = math.floor(total_lot / n_legs * 100) / 100.0
    if per_leg < lot_floor:
        n_legs = max(int(total_lot / lot_floor), 1)
        per_leg = lot_floor
        tps = tps[:n_legs]

    # --- 5) posalji ordere (jedna "noga" po TP-u) — MetaApi trade pozivi bacaju
    # exception na gresku (umjesto retcode-a kao lokalni MetaTrader5 paket).
    opened = []
    for i, tp in enumerate(tps or [0], start=1):
        magic = MAGIC_BASE + i
        comment = f"zz:{signal['id'][:8]}:tp{i}"  # format se ne mijenja — executor/dashboard se oslanjaju na njega
        options = {"magic": magic, "comment": comment}
        ok, position_id, error_msg = True, None, None
        try:
            if is_buy:
                result = await connection.create_market_buy_order(
                    symbol=symbol, volume=per_leg, stop_loss=sl, take_profit=(tp or None), options=options)
            else:
                result = await connection.create_market_sell_order(
                    symbol=symbol, volume=per_leg, stop_loss=sl, take_profit=(tp or None), options=options)
            code = result.get("stringCode") if isinstance(result, dict) else None
            ok = code is None or code in TRADE_SUCCESS_CODES
            position_id = result.get("positionId") if isinstance(result, dict) else None
            if not ok:
                error_msg = f"{code}: {result.get('message')}"
        except Exception as e:
            ok = False
            error_msg = str(e)

        sb().table("trade_executions").insert({
            "parsed_signal_id": signal["id"],
            "mt5_ticket": int(position_id) if position_id else None,
            "magic": magic,
            "symbol": symbol,
            "direction": direction,
            "lot": per_leg,
            "entry_price": market_price if ok else None,
            "sl": sl,
            "tp": tp or None,
            "tp_index": i,
            "status": "open" if ok else "error",
            "opened_at": datetime.now(timezone.utc).isoformat() if ok else None,
            "notes": None if ok else error_msg,
        }).execute()
        if ok:
            opened.append((i, tp))
        else:
            log(f"Order TP{i} odbijen: {error_msg}", level="error", category="executor")

    if opened:
        sb().table("parsed_signals").update({"decision_reason": f"Izvršeno: {len(opened)} nogu × {per_leg} lot."}).eq("id", signal["id"]).execute()
        log(f"Otvoreno {len(opened)}×{per_leg} {symbol} {direction.upper()} @ {market_price:.2f}",
            level="trade", category="executor", meta={"signal_id": signal["id"]})
        tps_txt = " / ".join(str(t) for _, t in opened)
        notify(
            f"✅ <b>Otvoreno</b> {symbol} {direction.upper()}\n"
            f"{len(opened)} nogu × {per_leg} lot @ {market_price:.2f}\n"
            f"SL: {sl}  |  TP: {tps_txt}"
        )
    else:
        notify(f"❌ <b>Izvršenje nije uspjelo</b> za {symbol} {direction.upper()} — vidi Aktivnost log.")


def skip(signal: dict, reason: str) -> None:
    sb().table("parsed_signals").update({"decision": "skip", "decision_reason": reason}).eq("id", signal["id"]).execute()
    log(f"Preskočen signal: {reason}", level="warn", category="risk", meta={"signal_id": signal["id"]})
    notify(f"⏭ <b>Preskočeno</b>\n{reason}")


async def handle_followup(connection: Any, signal: dict, settings: dict) -> None:
    ref_id = signal.get("references_signal_id")
    if not ref_id:
        sb().table("parsed_signals").update({"decision_reason": "Nema referentnog signala — ništa za ažurirati."}).eq("id", signal["id"]).execute()
        return
    positions = positions_for_signal(connection, ref_id)
    if not positions:
        sb().table("parsed_signals").update({"decision_reason": "Nema otvorenih pozicija za taj signal."}).eq("id", signal["id"]).execute()
        return
    # napomena: processed_at se postavlja centralno u main loopu nakon poziva
    # ove funkcije (i za ove rane return-ove i za akcione granice ispod) —
    # decision_reason ovdje ostaje samo citljivo objasnjenje za dashboard.

    mtype = signal["message_type"]

    if mtype in ("move_to_be", "tp_hit"):
        # SL -> entry za sve preostale noge (nakon TP1 po defaultu)
        if mtype == "tp_hit" and not settings["risk"].get("breakeven_after_tp1", True):
            return
        for p in positions:
            try:
                await connection.modify_position(
                    position_id=p["id"], stop_loss=p["openPrice"], take_profit=p.get("takeProfit"))
            except Exception as e:
                log(f"Breakeven na poziciji {p['id']} neuspio: {e}", level="error", category="executor")
        log(f"SL → breakeven za {len(positions)} pozicija ({mtype})", level="trade", category="executor",
            meta={"ref": ref_id})
        notify(f"🔒 <b>Breakeven</b> — SL pomjeren na entry za {len(positions)} pozicija.")

    elif mtype == "update_sl" and signal.get("sl") is not None:
        new_sl = float(signal["sl"])
        for p in positions:
            try:
                await connection.modify_position(position_id=p["id"], stop_loss=new_sl, take_profit=p.get("takeProfit"))
            except Exception as e:
                log(f"SL update na poziciji {p['id']} neuspio: {e}", level="error", category="executor")
        log(f"SL ažuriran na {new_sl} za {len(positions)} pozicija", level="trade", category="executor", meta={"ref": ref_id})
        notify(f"✏️ <b>SL ažuriran</b> na {new_sl} ({len(positions)} pozicija).")

    elif mtype in ("close", "partial_close"):
        # close: cijela noga se zatvara. partial_close: POLA VOLUMENA svake noge
        # (ne pola broja nogu) — kanal cesto trazi "close half" na SVAKOJ otvorenoj
        # poziciji, ne da se ostavi cijela noga otvorena a druga potpuno zatvorena.
        # MetaApi ima namjenske close pozive — ne treba rucno slati suprotan order.
        lot_floor = float(settings["risk"]["lot_floor"])
        closed_count = 0
        for p in positions:
            try:
                if mtype == "close":
                    await connection.close_position(position_id=p["id"])
                    closed_count += 1
                else:
                    half = math.floor((float(p["volume"]) / 2) * 100) / 100.0  # floor na 0.01 — nikad round-up
                    if half >= lot_floor:
                        await connection.close_position_partially(position_id=p["id"], volume=half)
                        closed_count += 1
                    # ako je pola ispod minimalnog lota, ta noga se ne dijeli — ostaje puna dalje
            except Exception as e:
                log(f"Zatvaranje pozicije {p['id']} ({mtype}) neuspjelo: {e}", level="error", category="executor")

        if mtype == "close":
            log(f"Zatvoreno {closed_count} pozicija (close)", level="trade", category="executor", meta={"ref": ref_id})
            notify(f"📕 <b>Zatvoreno</b> {closed_count} pozicija po instrukciji sa kanala.")
        else:
            log(f"Djelimicno zatvoreno (pola volumena) na {closed_count}/{len(positions)} pozicija",
                level="trade", category="executor", meta={"ref": ref_id})
            notify(f"📕 <b>Djelimično zatvoreno</b> — pola volumena na {closed_count} od {len(positions)} pozicija.")


async def sync_closed_positions(connection: Any, settings: dict) -> None:
    """Oznaci u bazi pozicije koje je broker zatvorio (TP/SL) i upisi profit."""
    open_rows = sb().table("trade_executions").select("*").eq("status", "open").execute().data or []
    if not open_rows:
        return
    live_ids = {int(p["id"]) for p in connection.terminal_state.positions}
    for row in open_rows:
        ticket = row.get("mt5_ticket")
        if ticket in live_ids or ticket is None:
            continue
        # pozicija vise nije ziva -> nadji deal u istoriji
        try:
            deals = connection.history_storage.get_deals_by_position(str(ticket)) or []
        except Exception as e:
            log(f"Ne mogu procitati istoriju za poziciju {ticket}: {e}", level="error", category="executor")
            continue
        close_deals = [d for d in deals if d.get("entryType") == "DEAL_ENTRY_OUT"]
        profit = sum((d.get("profit") or 0) + (d.get("swap") or 0) + (d.get("commission") or 0) for d in close_deals) if close_deals else None
        close_price = close_deals[-1].get("price") if close_deals else None
        pips = None
        if close_price and row.get("entry_price"):
            diff = close_price - row["entry_price"]
            pips = (diff if row["direction"] == "buy" else -diff) * 100  # $0.01 = 1 pip
        sb().table("trade_executions").update({
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "close_price": close_price,
            "profit": profit,
            "pips": pips,
        }).eq("id", row["id"]).execute()
        if profit is not None:
            emoji = "🟢" if profit >= 0 else "🔴"
            notify(f"{emoji} <b>Zatvoreno</b> TP{row.get('tp_index')} — profit {profit:+.2f}$ ({(pips or 0):+.0f} pips)")
            log(f"Pozicija #{ticket} zatvorena: {profit:+.2f}$", level="trade", category="executor")


RESYNC_AFTER_SECONDS = 60  # koliko dugo tolerisemo unsynced terminal_state prije forsiranog reconnect-a


async def reconnect(settings: dict, old_connection: Any | None) -> Any | None:
    """MetaApi streaming websocket povremeno puca (ConnectionTerminated) i SDK ga
    ne sinhronizuje uvijek nazad sam od sebe — terminal_state ostane zauvijek
    prazan (account_equity/positions/current_price vracaju None), sto tiho
    zaustavi sve nove trejdove i azuriranje pozicija bez pravog crasha. Zato
    pravimo potpuno novu konekciju umjesto da cekamo SDK da se sam oporavi."""
    if old_connection is not None:
        try:
            await old_connection.close()
        except Exception:
            pass
    new_connection = await mt5_connect(settings)
    if new_connection is not None:
        log("MetaApi konekcija ponovo uspostavljena.", category="executor")
        notify("🔄 <b>MetaApi konekcija ponovo uspostavljena</b> nakon desync-a.")
    else:
        log("Reconnect na MetaApi nije uspio — pokusavam opet sljedeci ciklus.", level="error", category="executor")
    return new_connection


# ---------------------------------------------------------------- main loop
async def main() -> None:
    settings = get_settings()
    connection = await mt5_connect(settings)
    if connection is None:
        raise SystemExit("MetaApi konekcija neuspješna — provjeri METAAPI_TOKEN, metaapi_account_id, MT5_PASSWORD.")

    mode = settings["mode"]["mode"]
    log(f"Executor pokrenut — mod: {mode}, server: {settings['mt5']['server']}", category="executor")
    notify(f"🤖 <b>Executor pokrenut</b> ({mode} · {settings['mt5']['server']})")

    last_snapshot = 0.0
    unsynced_since: float | None = None
    while True:
        try:
            settings = get_settings()

            if not connection.synchronized:
                if unsynced_since is None:
                    unsynced_since = time.time()
                    log("Terminal state je nesinhronizovan — cekam da se SDK sam oporavi.",
                        level="warn", category="executor")
                elif time.time() - unsynced_since > RESYNC_AFTER_SECONDS:
                    new_connection = await reconnect(settings, connection)
                    if new_connection is not None:
                        connection = new_connection
                    unsynced_since = None if new_connection is not None else time.time()
            else:
                unsynced_since = None

            if kill_switch_on():
                heartbeat("executor", status="degraded", meta={"kill_switch": True})
                await asyncio.sleep(POLL_SECONDS)
                continue

            # 1) novi signali za izvrsenje
            pending = (
                sb().table("parsed_signals").select("*")
                .eq("decision", "execute")
                .eq("message_type", "new_signal")
                .not_.in_("id", [r["parsed_signal_id"] for r in
                                 (sb().table("trade_executions").select("parsed_signal_id").execute().data or [])
                                 if r.get("parsed_signal_id")] or ["00000000-0000-0000-0000-000000000000"])
                .order("created_at", desc=False).limit(3).execute().data
            ) or []
            for signal in pending:
                await open_new_signal(connection, signal, settings)

            # 2) follow-up poruke (BE, update SL, close) — cist queue marker,
            #    umjesto starog poll obrazca na decision_reason (null/"Follow-up%").
            followups = (
                sb().table("parsed_signals").select("*")
                .eq("decision", "execute")
                .neq("message_type", "new_signal")
                .is_("processed_at", "null")
                .order("created_at", desc=False).limit(5).execute().data
            ) or []
            for signal in followups:
                await handle_followup(connection, signal, settings)
                sb().table("parsed_signals").update(
                    {"processed_at": datetime.now(timezone.utc).isoformat()}
                ).eq("id", signal["id"]).execute()

            # 3) sync zatvorenih pozicija
            await sync_closed_positions(connection, settings)

            # 4) equity snapshot
            if time.time() - last_snapshot > EQUITY_SNAPSHOT_EVERY:
                eq = account_equity(connection)
                if eq is None:
                    log("Terminal state nije sinhronizovan — snapshot preskocen (ne pisem lazan 0).",
                        level="warn", category="executor")
                else:
                    balance, equity = eq
                    sb().table("equity_snapshots").insert({
                        "balance": balance, "equity": equity, "open_pnl": equity - balance,
                    }).execute()
                last_snapshot = time.time()

            heartbeat("executor")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"Executor greška: {e}", level="error", category="executor")
            heartbeat("executor", status="degraded")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
