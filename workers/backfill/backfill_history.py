"""
Povlaci CIJELU istoriju kanala u external_signals (za backtest provajdera).
Pokreni jednom:  python -m backfill.backfill_history
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

from common.db import sb
from common.log import log
from common.settings import get_settings

load_dotenv()

BATCH = 200


async def run() -> None:
    settings = get_settings()
    tg = settings["telegram"]
    cols = settings["external_signals"]
    text_col, provider_col = cols["text_column"], cols["provider_column"]

    api_id, api_hash = int(tg["api_id"]), tg["api_hash"]
    channel_id = int(tg["channel_id"])
    session_string = os.environ.get("TELEGRAM_SESSION_STRING", "")
    if not session_string:
        raise SystemExit("TELEGRAM_SESSION_STRING nije postavljen.")

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.start()

    total = 0
    rows: list[dict] = []
    async for msg in client.iter_messages(channel_id, reverse=True):
        text = (msg.message or "").strip()
        if not text:
            continue
        rows.append({
            text_col: text,
            provider_col: f"telegram:{channel_id}",
            "created_at": msg.date.isoformat(),
            "ingested_at": msg.date.isoformat(),
        })
        if len(rows) >= BATCH:
            sb().table("external_signals").insert(rows).execute()
            total += len(rows)
            print(f"  ubaceno {total} poruka...")
            rows = []
            await asyncio.sleep(1)  # ne guraj rate limit
    if rows:
        sb().table("external_signals").insert(rows).execute()
        total += len(rows)

    log(f"Backfill zavrsen: {total} poruka iz istorije kanala", category="listener")
    print(f"\nGOTOVO: {total} poruka. Sada pusti parser da ih obradi (traje, kosta ~$0.002/poruci).")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
