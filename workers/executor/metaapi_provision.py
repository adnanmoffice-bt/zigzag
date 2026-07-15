"""
ZigZag — MetaApi.cloud provisioning (jednokratno)
==================================================
Kreira (ili ponovo koristi) MetaApi "trading account" resurs koji povezuje
MT5 login/lozinku/server (bot_settings.mt5 + .env MT5_PASSWORD) na MetaApi.cloud,
i deploy-uje ga (pokrece cloud terminal konekciju ka brokeru).

Pokretanje (iz workers/ direktorija):  python -m executor.metaapi_provision

Nakon uspjesnog provisioning-a, account_id se automatski upisuje u
bot_settings.mt5.metaapi_account_id — executor ga odatle cita.

Preduslovi u .env: METAAPI_TOKEN (app.metaapi.cloud/token), MT5_PASSWORD.
Preduslovi u bot_settings.mt5: login, server (popuni kroz dashboard Postavke
ili direktno u bazi).
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from metaapi_cloud_sdk import MetaApi

from common.db import sb
from common.settings import get_settings

load_dotenv()


def guard_against_accidental_live(server: str) -> None:
    """Sigurnosna kocnica: MetaApi provisioning na LIVE nalog zahtijeva
    eksplicitnu potvrdu — sprecava da se ovaj skript nehotice pokrene
    protiv naloga sa pravim novcem (isto pravilo kao demo-first u README-u).
    """
    looks_live = "live" in server.lower() and "demo" not in server.lower()
    if looks_live and os.environ.get("METAAPI_ALLOW_LIVE") != "yes":
        raise SystemExit(
            f"Server '{server}' izgleda kao LIVE nalog (ne demo).\n"
            "ZigZag pravilo: mod 'live' se ne aktivira dok demo ne prodje 4+ sedmice i 50+ signala.\n"
            "Ako namjerno provisionišeš live nalog, postavi METAAPI_ALLOW_LIVE=yes u .env i pokreni ponovo."
        )


async def provision() -> None:
    token = os.environ.get("METAAPI_TOKEN", "")
    if not token:
        raise SystemExit("METAAPI_TOKEN nije postavljen u .env — dobij ga na app.metaapi.cloud/token")

    settings = get_settings()
    mt5 = settings["mt5"]
    login = mt5.get("login")
    server = mt5.get("server")
    password = os.environ.get("MT5_PASSWORD", "")
    if not login or not server:
        raise SystemExit("bot_settings.mt5.login/server nisu popunjeni — postavi ih prije provisioning-a.")
    if not password:
        raise SystemExit("MT5_PASSWORD nije postavljen u .env.")

    guard_against_accidental_live(server)

    api = MetaApi(token=token)
    existing_id = mt5.get("metaapi_account_id")

    if existing_id:
        print(f"Postojeci metaapi_account_id ({existing_id}) — provjeravam status umjesto kreiranja novog.")
        account = await api.metatrader_account_api.get_account(existing_id)
    else:
        print(f"Kreiram MetaApi nalog za login={login}, server={server}...")
        account = await api.metatrader_account_api.create_account(account={
            "name": "ZigZag XAUUSD",
            "type": "cloud",
            "login": str(login),
            "password": password,
            "server": server,
            "platform": "mt5",
            "magic": 777000,  # bazni magic; pojedinacne noge i dalje koriste 777000+N
            "quoteStreamingIntervalInSeconds": 1.0,
        })
        print(f"Nalog kreiran: account_id={account.id}")
        sb().table("bot_settings").update(
            {"value": {**mt5, "metaapi_account_id": account.id}}
        ).eq("key", "mt5").execute()
        print("account_id upisan u bot_settings.mt5.metaapi_account_id")

    if account.state != "DEPLOYED":
        print(f"Deploy-ujem nalog (trenutno stanje: {account.state})...")
        await account.deploy()

    print("Cekam konekciju ka brokeru (moze potrajati do minut)...")
    await account.wait_connected()
    print(f"Povezano! Stanje: {account.state}, connection_status: {account.connection_status}")
    print(f"account_id: {account.id}")


if __name__ == "__main__":
    asyncio.run(provision())
