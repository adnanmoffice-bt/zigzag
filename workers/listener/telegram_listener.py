"""
ZigZag — Telegram listener (Telethon)
=====================================
Slusa privatni kanal i upisuje svaku poruku u external_signals.
Radi na Linux hostu (Railway/Fly.io) ili istom VPS-u.

Prvi put:  python -m listener.make_session   (generise TELEGRAM_SESSION_STRING)
Zatim:     python -m listener.telegram_listener

VAZNO: koristi STARIJI, ustaljen Telegram nalog — novi nalozi bivaju banovani.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from common.db import sb
from common.log import heartbeat, log
from common.settings import get_settings

load_dotenv()


def insert_message(text: str, channel_id: str, message_id: int, sender: str | None,
                   msg_date: str | None, text_col: str, provider_col: str) -> None:
    source = f"telegram:{channel_id}"
    try:
        # dedupe: ista poruka (source + external_message_id) se ne ubacuje dvaput
        existing = (
            sb().table("external_signals").select("id")
            .eq("source", source).eq("external_message_id", message_id)
            .limit(1).execute().data
        )
        if existing:
            return
    except Exception:
        pass

    now = datetime.now(timezone.utc).isoformat()
    row = {
        text_col: text,
        "source": source,
        "external_message_id": message_id,
        "message_date": msg_date or now,
        "ingested_at": now,
        "parse_status": "pending",
    }
    if provider_col not in ("source",):  # npr. sender
        row[provider_col] = sender or source
    try:
        sb().table("external_signals").insert(row).execute()
        log(f"Nova poruka sa kanala ({len(text)} znakova)", category="listener")
    except Exception as e:
        log(f"Insert u external_signals nije uspio: {e} — provjeri mapiranje kolona u Postavkama.",
            level="error", category="listener")


async def run() -> None:
    settings = get_settings()
    tg = settings["telegram"]
    cols = settings["external_signals"]

    api_id = int(tg["api_id"])
    api_hash = tg["api_hash"]
    channel_id = int(tg["channel_id"])
    session_string = os.environ.get("TELEGRAM_SESSION_STRING", "")
    if not session_string:
        raise SystemExit("TELEGRAM_SESSION_STRING nije postavljen — pokreni: python -m listener.make_session")

    client = TelegramClient(StringSession(session_string), api_id, api_hash)

    async def sender_name(event) -> str | None:
        try:
            s = await event.get_sender()
            return getattr(s, "title", None) or getattr(s, "username", None) or getattr(s, "first_name", None)
        except Exception:
            return None

    @client.on(events.NewMessage(chats=channel_id))
    async def on_message(event):  # noqa: ANN001
        text = event.message.message or ""
        if text.strip():
            insert_message(text, str(channel_id), event.message.id, await sender_name(event),
                           event.message.date.isoformat() if event.message.date else None,
                           cols["text_column"], cols["provider_column"])

    @client.on(events.MessageEdited(chats=channel_id))
    async def on_edit(event):  # noqa: ANN001
        text = event.message.message or ""
        if text.strip():
            # editovane poruke tretiramo kao nove (signal se cesto edituje sa TP-ovima)
            insert_message(f"[EDIT] {text}", str(channel_id), event.message.id * 1000 + 1,
                           await sender_name(event),
                           event.message.date.isoformat() if event.message.date else None,
                           cols["text_column"], cols["provider_column"])

    async def beat() -> None:
        while True:
            heartbeat("listener")
            await asyncio.sleep(30)

    await client.start()
    log("Listener spojen na Telegram", category="listener")
    asyncio.create_task(beat())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run())
