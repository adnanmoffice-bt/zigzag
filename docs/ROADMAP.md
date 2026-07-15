# ROADMAP — nastavak u Cursoru

## Trenutno stanje (v0.1)

Kompletan skeleton radi end-to-end: listener → parser → executor → dashboard + notifikacije.
Executor koristi MetaApi.cloud (async), ne lokalni MetaTrader5 paket — radi na bilo kom hostu.
Sve dole je POSLIJE prvog uspjesnog demo trejda.

## Poznata ogranicenja / prvo za popraviti

1. **`external_signals` mapiranje kolona** — potvrdjeno: stvarna sema koristi `raw_text`/`sender`/
   `parse_status` (ne `content`), vec podeseno u `common/settings.py` defaultima.
2. ~~**Follow-up queue u executoru** je poll na `decision_reason` obrazac~~ — **URADJENO**:
   zamijenjeno cistim `processed_at` timestamp poljem na parsed_signals (migracija 002).
3. ~~**partial_close** zatvara pola "nogu", ne pola volumena~~ — **URADJENO**: sada zatvara
   pola volumena svake noge (floor na 0.01), preko MetaApi `close_position_partially`.
4. ~~**find_referenced_signal** uzima zadnji new_signal provajdera~~ — **URADJENO**: dodat
   simbol match i vremenski prozor (24h) kao dodatni uslovi.
5. **Vikend/sesija filter** — ne otvarati pozicije van London–NY overlapa (13–17 GMT)
   kao opcija u risk postavkama.
6. **Executor prebacen na MetaApi.cloud** (vidi ARCHITECTURE.md) — lokalni `MetaTrader5` paket je
   Windows-only i trazio desktop terminal; MetaApi hostuje konekciju u cloudu, radi sa bilo kog
   hosta. Treba live-testirati `sync_closed_positions` (history_storage deal polja) i
   `close_position`/`close_position_partially` na stvarnom nalogu prije prvog demo trejda.

## Feature backlog (redom vrijednosti)

- [ ] **Trailing stop** nakon TP2 (ATR-based ili fiksni $)
- [ ] **News filter** — pauza oko high-impact USD/gold vijesti (ForexFactory kalendar scrape)
- [ ] **Auto risk skaliranje po provajderu** — multiplier iz zadnjih 20 trejdova umjesto rucnog
- [ ] **Prompt caching** za Claude (system prompt je fiksan → -90% input troska)
- [ ] **IG REST API backup staza** ako MetaApi.cloud padne (izvrsenje preko web API-ja direktno)
- [ ] **Ekvivalent Strategy Testera**: replay istorije kroz decision engine sa razlicitim
      risk parametrima (backtest bez Claude poziva — koristi vec parsirane signale)
- [ ] **PWA / mobilni layout** za dashboard (sidebar → bottom tabs)
- [ ] **Dnevni report** u Telegram (PnL, trejdovi, najbolji/najgori provajder)

## Konvencije koda

- Python 3.11+, bez frameworka — cisti workeri sa poll petljama, sve preko common/ modula.
- Svaki dogadaj → `common.log.log()` (upisuje u activity_log + stdout).
- Svaka nova tabela → nova migracija `supabase/migrations/00X_*.sql`, idempotentna.
- Dashboard: TypeScript strict, stranica po fajlu u src/pages, dijeljene komponente u ui.tsx.
- Stil: bijelo + #635BFF akcenat + zlatna za XAUUSD; font Inter + JetBrains Mono za brojeve.

## Nepregovorljiva pravila (ne mijenjati u kodu bez razloga)

1. Demo → live tek nakon 4+ sedmice i 50+ signala sa pozitivnim ocekivanjem.
2. Lot se NIKAD ne zaokruzuje navise (floor).
3. Dnevni max gubitak zaustavlja bota — bez izuzetaka, bez "revenge" logike.
4. Chasing zastita ostaje — kanal sam priznaje lose ulaze ("we are chasing!").
5. Tajne samo u .env.
