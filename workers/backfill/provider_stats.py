"""
Racuna statistiku provajdera iz parsed_signals + trade_executions.
Za istorijske signale (bez izvrsenja) koristi tp_hit/close follow-up poruke kao proxy ishoda.
Pokreni:  python -m backfill.provider_stats   (moze i na cronu, npr. svakih sat)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from common.db import sb
from common.log import log


def main() -> None:
    signals = sb().table("parsed_signals").select("*").order("created_at").execute().data or []
    execs = sb().table("trade_executions").select("parsed_signal_id,profit,pips,status").execute().data or []

    exec_by_signal: dict[str, list[dict]] = defaultdict(list)
    for e in execs:
        if e.get("parsed_signal_id"):
            exec_by_signal[e["parsed_signal_id"]].append(e)

    stats: dict[str, dict] = defaultdict(lambda: {
        "signals_total": 0, "wins": 0, "losses": 0, "total_pips": 0.0, "pips_list": [], "last": None,
    })

    for s in signals:
        provider = s.get("provider") or "nepoznat"
        st = stats[provider]
        if s["message_type"] == "new_signal":
            st["signals_total"] += 1
            st["last"] = s["created_at"]

            legs = [e for e in exec_by_signal.get(s["id"], []) if e.get("status") == "closed"]
            if legs:  # stvarni ishod sa MT5
                pnl_pips = sum(e.get("pips") or 0 for e in legs)
                st["total_pips"] += pnl_pips
                st["pips_list"].append(pnl_pips)
                if pnl_pips > 0:
                    st["wins"] += 1
                elif pnl_pips < 0:
                    st["losses"] += 1
        elif s["message_type"] == "tp_hit" and s.get("references_signal_id"):
            # istorijski proxy: tp_hit poruka = provajder tvrdi pobjedu (koristi se samo bez izvrsenja)
            ref_execs = exec_by_signal.get(s["references_signal_id"], [])
            if not ref_execs:
                st["wins"] += 1
                st["total_pips"] += 30  # konzervativna procjena kad nema stvarnih brojeva

    for provider, st in stats.items():
        decided = st["wins"] + st["losses"]
        win_rate = (st["wins"] / decided * 100) if decided else None
        avg_pips = (sum(st["pips_list"]) / len(st["pips_list"])) if st["pips_list"] else None
        sb().table("provider_stats").upsert({
            "provider": provider,
            "signals_total": st["signals_total"],
            "wins": st["wins"],
            "losses": st["losses"],
            "win_rate": win_rate,
            "avg_pips": avg_pips,
            "total_pips": st["total_pips"],
            "last_signal_at": st["last"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

    log(f"Provider statistika osvježena za {len(stats)} provajdera", category="system")
    print(f"GOTOVO: {len(stats)} provajdera. NAPOMENA: istorijski 'tp_hit' ishodi su tvrdnje provajdera, ne verifikovani rezultati — pravu sliku daje tek demo trgovanje.")


if __name__ == "__main__":
    main()
