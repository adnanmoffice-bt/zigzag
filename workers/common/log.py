"""Activity log + heartbeat u Supabase."""
from datetime import datetime, timezone
from typing import Any
from .db import sb


def log(message: str, level: str = "info", category: str = "system", meta: dict[str, Any] | None = None) -> None:
    line = f"[{level}] {category}: {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        # Windows konzola (cp1250/cp1252) ne moze ispisati npr. '→' — ispis ne
        # smije srusiti workera niti preskociti upis u activity_log ispod.
        print(line.encode("ascii", "replace").decode())
    try:
        sb().table("activity_log").insert({
            "level": level, "category": category, "message": message, "meta": meta or {},
        }).execute()
    except Exception as e:  # log ne smije srusiti workera
        print(f"  ! activity_log insert failed: {e}")


def heartbeat(component: str, status: str = "ok", meta: dict[str, Any] | None = None) -> None:
    try:
        sb().table("bot_heartbeat").upsert({
            "component": component, "status": status,
            "last_seen": datetime.now(timezone.utc).isoformat(), "meta": meta or {},
        }).execute()
    except Exception as e:
        print(f"  ! heartbeat failed: {e}")
