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


def insert_message(text: str, channel_id: str, message_id: int, text_col: str, provider_col: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row = {
        text_col: text,
        provider_col: f"telegram:{channel_id}",
        "created_at": now,
        "ingested_at": now,
    }
    try:
        # dedupe preko cursora
        existing = (
            sb().table("external_signal_cursors").select("*")
            .eq("source", f"telegram:{channel_id}").eq("last_message_id", message_id).execute().data
        )
        if existing:
            return
    except Exception:
        pass  # cursor tabela drugacije strukture — nastavi bez dedupe

    try:
        sb().table("external_signals").insert(row).execute()
        try:
            sb().table("external_signal_cursors").upsert(
                {"source": f"telegram:{channel_id}", "last_message_id": message_id},
                on_conflict="source",
            ).execute()
        except Exception:
            pass
        log(f"Nova poruka sa kanala ({len(text)} znakova)", category="listener")
    except Exception as e:
        log(f"Insert u external_signals nije uspio: {e} — provjeri text_column u Postavkama.",
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

    @client.on(events.NewMessage(chats=channel_id))
    async def on_message(event):  # noqa: ANN001
        text = event.message.message or ""
        if text.strip():
            insert_message(text, str(channel_id), event.message.id, cols["text_column"], cols["provider_column"])

    @client.on(events.MessageEdited(chats=channel_id))
    async def on_edit(event):  # noqa: ANN001
        text = event.message.message or ""
        if text.strip():
            # editovane poruke tretiramo kao nove (signal se cesto edituje sa TP-ovima)
            insert_message(f"[EDIT] {text}", str(channel_id), event.message.id * 1000 + 1,
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
