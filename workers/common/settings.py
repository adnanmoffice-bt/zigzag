"""Ucitava postavke iz bot_settings tabele (dashboard ih ureduje)."""
from typing import Any
from .db import sb

_DEFAULTS: dict[str, dict[str, Any]] = {
    "kill_switch": {"enabled": False},
    "mode": {"mode": "demo"},
    "risk": {
        "risk_percent": 0.5, "daily_max_loss_percent": 3.0, "max_open_positions": 4,
        "min_confidence": 0.75, "slippage_max_usd": 1.0, "entry_mode": "smart",
        "breakeven_after_tp1": True, "split_equal_per_tp": True,
        "lot_floor": 0.01, "lot_cap": 1.0,
    },
    "mt5": {
        "login": "", "server": "IG-Live2", "symbol": "XAUUSD", "symbol_suffix": "",
        "metaapi_account_id": "",  # popunjava metaapi_provision.py, veza ka MetaApi.cloud resursu
    },
    "telegram": {"api_id": "", "api_hash": "", "channel_id": "", "bot_token": "", "notify_chat_id": ""},
    "anthropic": {"model": "claude-sonnet-4-6", "max_tokens": 1024},
    "external_signals": {"text_column": "raw_text", "provider_column": "sender", "status_column": "parse_status"},
}


def get_settings() -> dict[str, dict[str, Any]]:
    rows = sb().table("bot_settings").select("key,value").execute().data or []
    merged = {k: dict(v) for k, v in _DEFAULTS.items()}
    for row in rows:
        merged.setdefault(row["key"], {})
        if isinstance(row.get("value"), dict):
            merged[row["key"]].update(row["value"])
    return merged


def kill_switch_on() -> bool:
    try:
        row = sb().table("bot_settings").select("value").eq("key", "kill_switch").single().execute()
        return bool((row.data or {}).get("value", {}).get("enabled"))
    except Exception:
        return False
