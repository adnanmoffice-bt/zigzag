"""Telegram notifikacije Adnanu preko Bot API-ja."""
import requests
from .settings import get_settings


def notify(text: str) -> None:
    tg = get_settings().get("telegram", {})
    token, chat_id = tg.get("bot_token"), tg.get("notify_chat_id")
    if not token or not chat_id:
        print(f"[notify skipped — bot_token/notify_chat_id nisu podeseni] {text}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        print(f"  ! telegram notify failed: {e}")
