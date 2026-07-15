# SETUP — korak po korak

Redoslijed: **Supabase → Dashboard → Telegram → Parser → VPS/MT5 → Vercel**.
Sve tajne idu u `.env` fajlove; dashboard Postavke čuvaju samo konfiguraciju (ID-jeve, pragove).

---

## 1. Supabase (10 min)

1. Otvori [supabase.com/dashboard](https://supabase.com/dashboard) → projekat `thuamsmvqdngemdkrftk`.
2. **SQL Editor → New query** → zalijepi kompletan `supabase/migrations/001_zigzag_schema.sql` → **Run**.
   - Skripta je idempotentna — smiješ je pokrenuti više puta.
   - Ne dira postojeće tabele (`external_signals` itd.), samo dodaje nove + kolonu `parsed`.
3. **Authentication → Users → Add user** → tvoj email + jaka lozinka. To je login za dashboard.
4. **Settings → API** → kopiraj:
   - `anon / publishable` ključ → već je u `dashboard/.env.example`
   - `service_role` ključ → ide u `workers/.env` kao `SUPABASE_SERVICE_KEY`. **Čuvaj ga kao lozinku.**

### Provjeri naziv kolone sa tekstom poruke
Tabela `external_signals` već postoji od ranije. Otvori je u Table Editoru i vidi kako se zove
kolona u kojoj je **tekst poruke** (npr. `content`, `raw_text`, `message`...).
Upiši taj naziv u dashboard **Postavke → Ingestija → text_column** (default je `content`).

---

## 2. Dashboard lokalno (5 min)

```bash
cd dashboard
cp .env.example .env        # vrijednosti su vec upisane
npm install
npm run dev                 # http://localhost:5173
```

Prijavi se korisnikom iz koraka 1.3, otvori **Postavke** i popuni:
- **Telegram**: api_id, api_hash (korak 3), channel_id `-1003910126970`, bot_token + chat_id (korak 3.3)
- **MT5**: login (broj naloga), server (`IG-Demo` za početak!), symbol `XAUUSD`
- **Rizik**: ostavi defaulte za start (0.5% / 3% dnevno / max 4 pozicije)

---

## 3. Telegram (15 min)

### 3.1 API kredencijali (user nalog — za čitanje kanala)
1. [my.telegram.org](https://my.telegram.org) → prijavi se **starim, ustaljenim nalogom** (novi nalozi + Telethon = ban rizik).
2. *API development tools* → kreiraj app → zapiši `api_id` i `api_hash` → unesi u dashboard Postavke.

### 3.2 Session string
```bash
cd workers
cp .env.example .env        # popuni SUPABASE_SERVICE_KEY prije ovoga
pip install -r requirements.txt
python -m listener.make_session
```
Unesi broj telefona + kod iz Telegrama. Ispisani string zalijepi u `workers/.env`:
```
TELEGRAM_SESSION_STRING=1BVtsOK4Bu...
```
**Ovaj string = pun pristup tvom Telegram nalogu. Nikad u git.**

### 3.3 Bot za notifikacije
1. U Telegramu otvori **@BotFather** → `/newbot` → ime npr. `ZigZag Alerts` → username `zigzag_alerts_bot`.
2. Dobijeni token → dashboard Postavke → `bot_token`.
3. Pošalji svom botu `/start`, pa otvori u browseru:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → nađi `"chat":{"id":123456789}` → taj broj u `notify_chat_id`.

---

## 4. Parser + Listener (Linux OK — Railway, Fly.io, ili isti Windows VPS)

```bash
cd workers
# .env mora imati: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY, TELEGRAM_SESSION_STRING
python -m listener.telegram_listener    # proces 1 — drži upaljen 24/7
python -m parser.claude_parser          # proces 2 — drži upaljen 24/7
```

Za 24/7 rad koristi `systemd`, `pm2`, ili Railway/Fly.io worker. Primjer systemd unita:
```ini
[Unit]
Description=ZigZag parser
After=network.target

[Service]
WorkingDirectory=/opt/zigzag/workers
ExecStart=/usr/bin/python3 -m parser.claude_parser
Restart=always
EnvironmentFile=/opt/zigzag/workers/.env

[Install]
WantedBy=multi-user.target
```

### 4.1 Backfill istorije (jednokratno — preporučeno!)
```bash
python -m backfill.backfill_history     # povuce cijelu istoriju kanala
# pusti parser da sve obradi (Claude trosak ~$0.002/poruci), zatim:
python -m backfill.provider_stats       # izracuna leaderboard provajdera
```
Ovo ti prije prvog trejda kaže **koji provajderi istorijski valjaju**. Napomena: istorijski
"TP HIT" ishodi su tvrdnje provajdera — pravu sliku daje tek demo trgovanje.

---

## 5. Windows VPS + MT5 + Executor (30 min)

1. Zakupi Windows VPS blizu IG servera (ForexVPS.net ili FXVM, **London** lokacija, ~$25–40/mj).
2. Instaliraj [MT5 sa IG stranice](https://www.ig.com) → prijavi se sa **IG-Demo** kredencijalima.
   - MY IG → dodaj MT5 nalog ako ga nemaš. Prvo **demo**, live tek nakon validacije.
3. MT5 → *Tools → Options → Expert Advisors* → uključi **Allow automated trading**.
4. Instaliraj Python 3.11+ (python.org, "Add to PATH").
5. ```bash
   git clone https://github.com/adnanmoffice-bt/zigzag && cd zigzag/workers
   pip install -r requirements.txt MetaTrader5
   copy .env.example .env    # popuni SUPABASE_*, MT5_PASSWORD
   python -m executor.mt5_executor
   ```
6. Trebao bi stići Telegram: `🤖 Executor pokrenut (demo · IG-Demo)`.
7. Auto-start nakon reboota: Task Scheduler → *At startup* → `python -m executor.mt5_executor`
   (Start in: `C:\...\zigzag\workers`).

Greška `10027` = automated trading nije uključen u MT5 (korak 3).

---

## 6. Vercel deploy dashboarda (10 min)

1. Pushaj repo na GitHub (vidi dole).
2. [vercel.com](https://vercel.com) → *Add New Project* → importuj `adnanmoffice-bt/zigzag`.
3. **Root Directory: `dashboard`** (bitno!). Framework: Vite (auto).
4. Environment Variables → dodaj obje iz `dashboard/.env.example`.
5. Deploy → dobijaš `https://zigzag-xxx.vercel.app` → prijavi se svojim Supabase userom.

`vercel.json` u `dashboard/` već rješava SPA rute (refresh na /signals ne daje 404).

---

## 7. Push na GitHub

```bash
cd zigzag
git init
git add .
git commit -m "ZigZag v0.1 — listener, parser, executor, dashboard"
git branch -M main
git remote add origin https://github.com/adnanmoffice-bt/zigzag.git
git push -u origin main
```

Prije pusha provjeri: `git status` **ne smije** pokazivati `.env` ni `*.session` fajlove.

---

## Redoslijed prvog pokretanja (checklist)

- [ ] SQL migracija pokrenuta
- [ ] Auth korisnik kreiran, login na dashboard radi
- [ ] Postavke popunjene (Telegram, MT5 demo, rizik)
- [ ] `text_column` provjeren prema stvarnoj šemi `external_signals`
- [ ] Session string generisan, listener upisuje poruke (vidi Aktivnost)
- [ ] Parser obrađuje poruke (Signali stranica se puni)
- [ ] Backfill + provider stats (leaderboard popunjen)
- [ ] Executor na VPS-u spojen na **IG-Demo**, stigla notifikacija
- [ ] Prvi demo trejd prošao cijeli tok: signal → parse → izvršenje → notifikacija
- [ ] 4 sedmice / 50+ signala demo statistike → tek onda razmišljaj o `live`
