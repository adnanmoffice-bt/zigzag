"""
ZigZag — MT5 executor (SAMO Windows VPS)
========================================
Cita parsed_signals sa decision='execute', otvara/azurira pozicije na MT5 (IG),
primjenjuje risk pravila i upisuje sve nazad u Supabase.

Pokretanje:  python -m executor.mt5_executor      (iz workers/ direktorija)

Preduslovi na VPS-u:
  pip install MetaTrader5
  MT5 terminal instaliran, prijavljen na IG-Demo/IG-Live2,
  Tools -> Options -> Expert Advisors -> "Allow automated trading" ukljuceno.

XAUUSD matematika (IG): 1 lot = 100 oz; kretanje $1.00 = $100 po lotu.
  lot = rizik_$ / (SL_distance_$ * 100)
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from common.db import sb
from common.log import heartbeat, log
from common.notify import notify
from common.settings import get_settings, kill_switch_on

load_dotenv()

try:
    import MetaTrader5 as mt5  # type: ignore
except ImportError:  # omoguci import/test na Linuxu
    mt5 = None

POLL_SECONDS = 3
EQUITY_SNAPSHOT_EVERY = 300  # 5 min
MAGIC_BASE = 777000  # magic = MAGIC_BASE + tp_index


# ---------------------------------------------------------------- MT5 osnove
def mt5_connect(settings: dict) -> bool:
    cfg = settings["mt5"]
    password = os.environ.get("MT5_PASSWORD", "")
    if not mt5.initialize(login=int(cfg["login"]), server=cfg["server"], password=password):
        log(f"MT5 initialize neuspješan: {mt5.last_error()}", level="error", category="executor")
        return False
    return True


def full_symbol(settings: dict) -> str:
    cfg = settings["mt5"]
    return f"{cfg['symbol']}{cfg.get('symbol_suffix', '')}"


def current_price(symbol: str) -> tuple[float, float] | None:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return tick.bid, tick.ask


def account_equity() -> tuple[float, float]:
    info = mt5.account_info()
    return (info.balance, info.equity) if info else (0.0, 0.0)


# ---------------------------------------------------------------- risk
def compute_lot(equity: float, sl_distance: float, risk: dict, multiplier: float) -> float:
    """lot = rizik_$ / (SL_distance_$ * 100) za XAUUSD."""
    if sl_distance <= 0:
        return 0.0
    risk_usd = equity * float(risk["risk_percent"]) / 100.0 * multiplier
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
def open_new_signal(signal: dict, settings: dict) -> None:
    risk = settings["risk"]
    symbol = full_symbol(settings)
    mt5.symbol_select(symbol, True)

    prices = current_price(symbol)
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
    balance, equity = account_equity()
    if daily_loss_exceeded(risk, balance):
        skip(signal, "Dnevni max gubitak dosegnut — bot pauziran do sutra.")
        notify("🛑 <b>Dnevni limit gubitka dosegnut.</b> Bot ne otvara nove pozicije do sutra.")
        return
    open_now = len([p for p in (mt5.positions_get(symbol=symbol) or [])])
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

    # --- 5) posalji ordere (jedna "noga" po TP-u)
    opened = []
    for i, tp in enumerate(tps or [0], start=1):
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": per_leg,
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": market_price,
            "sl": sl,
            "tp": tp if tp else 0.0,
            "deviation": 30,
            "magic": MAGIC_BASE + i,
            "comment": f"zz:{signal['id'][:8]}:tp{i}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        sb().table("trade_executions").insert({
            "parsed_signal_id": signal["id"],
            "mt5_ticket": getattr(result, "order", None) if ok else None,
            "magic": MAGIC_BASE + i,
            "symbol": symbol,
            "direction": direction,
            "lot": per_leg,
            "entry_price": getattr(result, "price", market_price) if ok else None,
            "sl": sl,
            "tp": tp or None,
            "tp_index": i,
            "status": "open" if ok else "error",
            "opened_at": datetime.now(timezone.utc).isoformat() if ok else None,
            "notes": None if ok else f"retcode={getattr(result, 'retcode', 'None')} {mt5.last_error()}",
        }).execute()
        if ok:
            opened.append((i, tp))
        else:
            log(f"Order TP{i} odbijen: {getattr(result, 'retcode', None)}", level="error", category="executor")

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


def positions_for_signal(ref_id: str) -> list:
    """MT5 pozicije vezane za signal preko comment taga zz:<id8>."""
    tag = f"zz:{ref_id[:8]}"
    return [p for p in (mt5.positions_get() or []) if tag in (p.comment or "")]


def handle_followup(signal: dict, settings: dict) -> None:
    ref_id = signal.get("references_signal_id")
    if not ref_id:
        sb().table("parsed_signals").update({"decision_reason": "Nema referentnog signala — ništa za ažurirati."}).eq("id", signal["id"]).execute()
        return
    positions = positions_for_signal(ref_id)
    if not positions:
        sb().table("parsed_signals").update({"decision_reason": "Nema otvorenih pozicija za taj signal."}).eq("id", signal["id"]).execute()
        return

    mtype = signal["message_type"]
    symbol = positions[0].symbol

    if mtype in ("move_to_be", "tp_hit"):
        # SL -> entry za sve preostale noge (nakon TP1 po defaultu)
        if mtype == "tp_hit" and not settings["risk"].get("breakeven_after_tp1", True):
            return
        for p in positions:
            mt5.order_send({
                "action": mt5.TRADE_ACTION_SLTP,
                "position": p.ticket,
                "symbol": symbol,
                "sl": p.price_open,
                "tp": p.tp,
            })
        log(f"SL → breakeven za {len(positions)} pozicija ({mtype})", level="trade", category="executor",
            meta={"ref": ref_id})
        notify(f"🔒 <b>Breakeven</b> — SL pomjeren na entry za {len(positions)} pozicija.")

    elif mtype == "update_sl" and signal.get("sl") is not None:
        new_sl = float(signal["sl"])
        for p in positions:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket, "symbol": symbol, "sl": new_sl, "tp": p.tp})
        log(f"SL ažuriran na {new_sl} za {len(positions)} pozicija", level="trade", category="executor", meta={"ref": ref_id})
        notify(f"✏️ <b>SL ažuriran</b> na {new_sl} ({len(positions)} pozicija).")

    elif mtype in ("close", "partial_close"):
        to_close = positions if mtype == "close" else positions[: max(len(positions) // 2, 1)]
        for p in to_close:
            tick = mt5.symbol_info_tick(symbol)
            price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
            mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": symbol,
                "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "price": price,
                "deviation": 30,
                "magic": p.magic,
                "comment": p.comment,
                "type_filling": mt5.ORDER_FILLING_FOK,
            })
        log(f"Zatvoreno {len(to_close)} pozicija ({mtype})", level="trade", category="executor", meta={"ref": ref_id})
        notify(f"📕 <b>Zatvoreno</b> {len(to_close)} pozicija po instrukciji sa kanala.")


def sync_closed_positions(settings: dict) -> None:
    """Oznaci u bazi pozicije koje je MT5 zatvorio (TP/SL) i upisi profit."""
    open_rows = sb().table("trade_executions").select("*").eq("status", "open").execute().data or []
    if not open_rows:
        return
    live_tickets = {p.ticket for p in (mt5.positions_get() or [])}
    for row in open_rows:
        ticket = row.get("mt5_ticket")
        if ticket in live_tickets or ticket is None:
            continue
        # pozicija vise nije ziva -> nadji deal u istoriji
        deals = mt5.history_deals_get(position=ticket) or []
        close_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        profit = sum(d.profit + d.swap + d.commission for d in close_deals) if close_deals else None
        close_price = close_deals[-1].price if close_deals else None
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


# ---------------------------------------------------------------- main loop
def main() -> None:
    if mt5 is None:
        raise SystemExit("MetaTrader5 paket nije instaliran — executor radi samo na Windows VPS-u (pip install MetaTrader5).")

    settings = get_settings()
    if not mt5_connect(settings):
        raise SystemExit("MT5 konekcija neuspješna — provjeri login/server u Postavkama i MT5_PASSWORD u .env.")

    mode = settings["mode"]["mode"]
    log(f"Executor pokrenut — mod: {mode}, server: {settings['mt5']['server']}", category="executor")
    notify(f"🤖 <b>Executor pokrenut</b> ({mode} · {settings['mt5']['server']})")

    last_snapshot = 0.0
    while True:
        try:
            settings = get_settings()

            if kill_switch_on():
                heartbeat("executor", status="degraded", meta={"kill_switch": True})
                time.sleep(POLL_SECONDS)
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
                open_new_signal(signal, settings)

            # 2) follow-up poruke (BE, update SL, close)
            followups = (
                sb().table("parsed_signals").select("*")
                .eq("decision", "execute")
                .neq("message_type", "new_signal")
                .is_("decision_reason", "null")  # jos neobradene... fallback nize
                .order("created_at", desc=False).limit(5).execute().data
            ) or []
            if not followups:
                followups = (
                    sb().table("parsed_signals").select("*")
                    .eq("decision", "execute")
                    .neq("message_type", "new_signal")
                    .like("decision_reason", "Follow-up%")
                    .order("created_at", desc=False).limit(5).execute().data
                ) or []
            for signal in followups:
                handle_followup(signal, settings)
                sb().table("parsed_signals").update(
                    {"decision_reason": f"Obrađeno: {signal['message_type']}"}
                ).eq("id", signal["id"]).execute()

            # 3) sync zatvorenih pozicija
            sync_closed_positions(settings)

            # 4) equity snapshot
            if time.time() - last_snapshot > EQUITY_SNAPSHOT_EVERY:
                balance, equity = account_equity()
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
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
