# ARHITEKTURA

## Tok podataka

```
Telegram kanal (Signal Feed, -1003910126970)
   │  Telethon user sesija (MTProto — Bot API ne moze citati tude kanale)
   ▼
telegram_listener.py ──insert──▶ external_signals (postojeca tabela)
                                      │ poll (5s), parsed=false
                                      ▼
claude_parser.py ──Claude API (tool use, forsiran record_signal)──▶ parsed_signals
   │                                                                   decision: execute|skip + razlog
   │  decision engine: kill switch, confidence prag, samo XAUUSD,
   │  provajder enabled, kompletnost (SL+TP)
   ▼
mt5_executor.py (bilo koji host — async, MetaApi.cloud SDK) ── poll (3s) na decision='execute'
   │  live provjere: SL vec probijen? chasing (slippage_max_usd)?
   │  dnevni limit? max pozicija? → lot formula → split po TP nogama
   ▼
MetaApi.cloud (hostuje MT5 terminal konekciju) ──▶ MT5 / IG ──ishodi──▶ trade_executions ──▶ provider_stats
                          │
                          ▼
              React dashboard (Supabase realtime)  +  Telegram notifikacije
```

## Tabele (nove — vidi 001_zigzag_schema.sql)

| Tabela | Ko pise | Ko cita | Svrha |
|---|---|---|---|
| bot_settings | dashboard | workeri | sva konfiguracija (key/value jsonb) |
| parsed_signals | parser, executor | dashboard | strukturirani signali + odluke |
| trade_executions | executor | dashboard, stats | svaka MT5 "noga" (1 red = 1 TP leg) |
| provider_stats | stats skripta, dashboard | executor | leaderboard + enabled + risk_multiplier |
| activity_log | svi workeri | dashboard | "signal journey" — svaki dogadaj i razlog |
| bot_heartbeat | svi workeri | dashboard | zivost (sidebar tackice; stale nakon 120s) |
| equity_snapshots | executor (5 min) | dashboard | equity kriva |

## Kljucne konvencije

- **Jedan signal = vise MT5 pozicija** (jedna po TP-u). Vezane preko
  `comment = "zz:<signal_id[:8]>:tpN"` i `magic = 777000 + N`.
- **Follow-up poruke** (`tp_hit`, `move_to_be`, `update_sl`, `close`) se vezu na zadnji
  `new_signal` istog provajdera (`references_signal_id`) i executor ih primjenjuje na
  zive pozicije preko comment taga.
- **Idempotentnost**: listener dedupe preko `external_signal_cursors`; parser oznacava
  `external_signals.parsed=true`; executor ne izvrsava signal koji vec ima red u `trade_executions`.
- **XAUUSD matematika (IG)**: 1 lot = 100 oz → $1 kretanja = $100/lot; $0.01 = 1 pip.
  `lot = rizik_$ / (SL_distance_$ × 100)`, floor na 0.01, cap iz postavki.
- **Editovane poruke** kanal cesto edituje (dodaje TP-ove) → listener ih ubacuje kao
  novu poruku sa `[EDIT]` prefiksom; parser odlucuje sta znace.

## Sigurnosni model

- Dashboard: anon kljuc + Supabase Auth login; RLS = authenticated read-all,
  write samo bot_settings + provider_stats.
- Workeri: service_role kljuc (zaobilazi RLS) — zato zivi SAMO u .env na serverima.
- Tajne NIKAD u bazi ni u git-u: MT5_PASSWORD, METAAPI_TOKEN, ANTHROPIC_API_KEY, SUPABASE_SERVICE_KEY,
  TELEGRAM_SESSION_STRING.
- MetaApi.cloud token daje pristup tvom MT5 nalogu (deploy/trade) — tretira se kao MT5_PASSWORD:
  samo u .env, nikad u kod/bazu/dashboard.

## MetaApi.cloud bridge (executor)

Executor koristi `metaapi-cloud-sdk` (async) umjesto lokalnog `MetaTrader5` Python paketa.
MetaApi hostuje samu MT5-terminal-ka-broker konekciju u svojoj infrastrukturi i izlaze je kao
REST/WebSocket API — executor se spaja preko **streaming connection** (`get_streaming_connection()`)
koja drzi lokalno sinhronizovanu kopiju pozicija/racuna/cijena (`connection.terminal_state`), tako
da citanje stanja ne kosta dodatni API poziv (bitno jer se poll petlja vrti svake 3s). Stvarne trade
akcije (otvori/modifikuj/zatvori) idu preko istog connection objekta i placene su po MetaApi planu.

Jednokratni setup: `python -m executor.metaapi_provision` — kreira MetaApi "trading account" resurs
iz `bot_settings.mt5.login/server` + `.env MT5_PASSWORD`, deploy-uje ga, upisuje `metaapi_account_id`
nazad u `bot_settings.mt5`.

Prednost nad lokalnim MetaTrader5 paketom: executor radi na **bilo kom hostu** (Linux, isti host
kao listener/parser) — ne treba desktop MT5 instalacija ni Windows VPS.

## Zasto ovakav stack (odluke iz researcha)

- **Telethon user sesija** jer Bot API ne moze citati kanale gdje bot nije admin.
- **MetaApi.cloud umjesto lokalnog MetaTrader5 paketa** — taj paket je Windows-only i trazi desktop
  terminal na istoj masini; MetaApi hostuje konekciju u cloudu i radi sa bilo kog hosta. IG REST API
  ostaje backup staza ako MetaApi ikad zapne (vidi ROADMAP).
- **Claude parser umjesto regexa** jer kanal agregira vise provajdera razlicitih formata
  i jezika; regex bi pukao na prvoj promjeni formata.
- **Supabase kao hub** — vec postoji, ima realtime za dashboard, i razdvaja workere
  (svaki moze pasti nezavisno bez gubitka podataka).
