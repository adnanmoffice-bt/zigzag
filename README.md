# ZigZag — XAUUSD Signal Autotrader

Automatizovani sistem koji čita trading signale sa privatnog Telegram kanala, parsira ih Claude-om,
izvršava na MetaTrader 5 (IG broker) i sve prikazuje na live dashboardu — uz Telegram notifikacije
o svakoj akciji.

```
[Telegram kanal] → [Listener] → [Supabase] → [Claude parser] → [MT5 Executor (Windows VPS)]
                                     │
                                     ├──→ [React dashboard @ Vercel]
                                     └──→ [Telegram notifikacije tebi]
```

## Struktura repozitorija

| Direktorij | Šta je | Gdje se vrti |
|---|---|---|
| `dashboard/` | React + Vite + Tailwind dashboard (Stripe stil) | Vercel |
| `workers/listener/` | Telethon listener — čita kanal → `external_signals` | Railway / Fly.io / VPS (Linux OK) |
| `workers/parser/` | Claude parser — `external_signals` → `parsed_signals` + odluka | Isti host kao listener |
| `workers/executor/` | MT5 izvršenje — otvara/ažurira pozicije, risk pravila | **SAMO Windows VPS** |
| `workers/backfill/` | Istorija kanala + statistika provajdera | Jednokratno / cron |
| `supabase/migrations/` | SQL schema (tabele, RLS, realtime, default postavke) | Supabase SQL Editor |
| `docs/` | Setup, arhitektura, roadmap za nastavak razvoja | — |

## Quickstart (redoslijed je bitan)

1. **Baza:** otvori Supabase → SQL Editor → zalijepi i pokreni `supabase/migrations/001_zigzag_schema.sql`.
2. **Auth korisnik:** Supabase → Authentication → Users → *Add user* (tvoj email + lozinka). Time se prijavljuješ na dashboard.
3. **Dashboard lokalno:**
   ```bash
   cd dashboard && cp .env.example .env && npm install && npm run dev
   ```
   Prijavi se, otvori **Postavke**, popuni Telegram/MT5/rizik sekcije, snimi.
4. **Workeri:**
   ```bash
   cd workers && cp .env.example .env   # popuni tajne (vidi docs/SETUP.md)
   pip install -r requirements.txt
   python -m listener.make_session       # jednokratno, lokalno (treba SMS kod)
   python -m listener.telegram_listener  # proces 1
   python -m parser.claude_parser        # proces 2
   ```
5. **Executor (Windows VPS):** instaliraj MT5, prijavi se na **IG-Demo** nalog, uključi
   *Allow automated trading*, pa:
   ```bash
   pip install -r requirements.txt MetaTrader5
   python -m executor.mt5_executor
   ```
6. **Deploy dashboarda:** pushaj repo na GitHub → Vercel → *Import project* → root `dashboard/` →
   dodaj env varijable iz `.env.example`.

Detaljne upute korak-po-korak: **`docs/SETUP.md`**.

## Ključna sigurnosna pravila

- `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `MT5_PASSWORD`, `TELEGRAM_SESSION_STRING` žive **samo u `.env` na serverima** — nikad u git, nikad u dashboard.
- Dashboard koristi **anon (publishable) ključ + login** — RLS u bazi štiti podatke.
- `.session` fajlovi i `.env` su u `.gitignore` — ne diraj to.

## Pravila rada (nepregovorljivo)

2. **Kill switch** (lijevi sidebar) trenutno zaustavlja otvaranje novih pozicija.
3. Dnevni max gubitak (default 3%) automatski pauzira bota do sutra.
4. Signali sa "chasing" upozorenjima dobijaju pola lota ili se preskaču — kanal sam priznaje loše ulaze.
5. Provajder koji vuče minus se **isključuje na Provajderi stranici**, ne gasi se cijeli bot.

## Nastavak razvoja (Cursor)

Otvori repo u Cursoru i kreni od **`docs/ROADMAP.md`** — tamo je lista sljedećih featura,
poznata ograničenja i konvencije koda. `docs/ARCHITECTURE.md` objašnjava svaki tok podataka.
