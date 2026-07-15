"""
Generise TELEGRAM_SESSION_STRING (jednokratno, interaktivno).
Pokreni LOKALNO (treba ti telefon za kod): python -m listener.make_session
Rezultat zalijepi u .env kao TELEGRAM_SESSION_STRING=...
"""
from dotenv import load_dotenv
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

from common.settings import get_settings

load_dotenv()

tg = get_settings()["telegram"]
api_id, api_hash = int(tg["api_id"]), tg["api_hash"]

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\n=== TELEGRAM_SESSION_STRING (zalijepi u .env) ===\n")
    print(client.session.save())
    print("\n=== CUVAJ OVO KAO LOZINKU — daje pun pristup nalogu ===")
