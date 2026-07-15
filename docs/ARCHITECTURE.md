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
mt5_executor.py (Windows VPS) ── poll (3s) na decision='execute'
   │  live provjere: SL vec probijen? chasing (slippage_max_usd)?
   │  dnevni limit? max pozicija? → lot formula → split po TP nogama
   ▼
MT5 / IG ──ishodi──▶ trade_executions ──▶ provider_stats
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
- Tajne NIKAD u bazi ni u git-u: MT5_PASSWORD, ANTHROPIC_API_KEY, SUPABASE_SERVICE_KEY,
  TELEGRAM_SESSION_STRING.

## Zasto ovakav stack (odluke iz researcha)

- **Telethon user sesija** jer Bot API ne moze citati kanale gdje bot nije admin.
- **MetaTrader5 Python paket** je Windows-only → executor mora na Windows VPS.
  Backup staze ako MT5 zapne: MetaApi cloud ili IG REST API (vidi ROADMAP).
- **Claude parser umjesto regexa** jer kanal agregira vise provajdera razlicitih formata
  i jezika; regex bi pukao na prvoj promjeni formata.
- **Supabase kao hub** — vec postoji, ima realtime za dashboard, i razdvaja workere
  (svaki moze pasti nezavisno bez gubitka podataka).
