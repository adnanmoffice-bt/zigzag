-- ============================================================
-- ZigZag — XAUUSD Signal Autotrader — schema v1
-- Pokreni u Supabase SQL Editoru (Dashboard -> SQL Editor -> New query)
-- Sigurno za ponovno pokretanje (IF NOT EXISTS svugdje).
-- NE dira postojece tabele (external_signals, agent_knowledge, ...).
-- ============================================================

-- 1) SETTINGS (key/value; dashboard pise, workeri citaju)
create table if not exists public.bot_settings (
  key         text primary key,
  value       jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);

-- 2) PARSIRANI SIGNALI (izlaz Claude parsera)
create table if not exists public.parsed_signals (
  id                   uuid primary key default gen_random_uuid(),
  external_signal_id   uuid,                       -- FK na external_signals.id (bez constrainta, defenzivno)
  provider             text,                       -- ime kanala/provajdera
  message_type         text not null,              -- new_signal | update_sl | tp_hit | move_to_be | close | partial_close | noise
  symbol               text,
  direction            text,                       -- buy | sell
  entry_low            numeric,
  entry_high           numeric,
  sl                   numeric,
  tps                  jsonb not null default '[]'::jsonb,  -- [4064, 4058, 4050, 4040]
  confidence           numeric,                    -- 0..1
  references_signal_id uuid,                       -- za update/tp_hit poruke: na koji signal se odnosi
  decision             text not null default 'pending',     -- pending | execute | skip | manual
  decision_reason      text,
  raw_text             text,
  telegram_message_id  bigint,
  created_at           timestamptz not null default now()
);
create index if not exists idx_parsed_signals_created on public.parsed_signals (created_at desc);
create index if not exists idx_parsed_signals_decision on public.parsed_signals (decision);
create index if not exists idx_parsed_signals_extid on public.parsed_signals (external_signal_id);

-- 3) IZVRSENJA (MT5 trejdovi)
create table if not exists public.trade_executions (
  id                uuid primary key default gen_random_uuid(),
  parsed_signal_id  uuid references public.parsed_signals(id),
  mt5_ticket        bigint,
  magic             bigint,
  symbol            text,
  direction         text,
  lot               numeric,
  entry_price       numeric,
  sl                numeric,
  tp                numeric,
  tp_index          int,                            -- 1..4 (koja TP "noga")
  status            text not null default 'pending',-- pending | open | closed | cancelled | error
  opened_at         timestamptz,
  closed_at         timestamptz,
  close_price       numeric,
  profit            numeric,
  pips              numeric,
  notes             text,
  created_at        timestamptz not null default now()
);
create index if not exists idx_exec_status on public.trade_executions (status);
create index if not exists idx_exec_signal on public.trade_executions (parsed_signal_id);

-- 4) STATISTIKA PROVAJDERA
create table if not exists public.provider_stats (
  provider        text primary key,
  signals_total   int not null default 0,
  wins            int not null default 0,
  losses          int not null default 0,
  win_rate        numeric,
  avg_pips        numeric,
  total_pips      numeric not null default 0,
  last_signal_at  timestamptz,
  enabled         boolean not null default true,   -- iskljuci lose provajdere ovdje
  risk_multiplier numeric not null default 1.0,    -- skaliranje lota po provajderu (0.5 = pola rizika)
  updated_at      timestamptz not null default now()
);

-- 5) ACTIVITY LOG ("signal journey" — svaka akcija i razlog)
create table if not exists public.activity_log (
  id          uuid primary key default gen_random_uuid(),
  level       text not null default 'info',   -- info | warn | error | trade
  category    text not null default 'system', -- listener | parser | executor | risk | system
  message     text not null,
  meta        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists idx_activity_created on public.activity_log (created_at desc);

-- 6) HEARTBEAT (zivost komponenti)
create table if not exists public.bot_heartbeat (
  component  text primary key,               -- listener | parser | executor
  status     text not null default 'ok',     -- ok | degraded | down
  last_seen  timestamptz not null default now(),
  meta       jsonb not null default '{}'::jsonb
);

-- 7) EQUITY SNAPSHOTS (za equity krivu)
create table if not exists public.equity_snapshots (
  id          uuid primary key default gen_random_uuid(),
  balance     numeric,
  equity      numeric,
  open_pnl    numeric,
  created_at  timestamptz not null default now()
);
create index if not exists idx_equity_created on public.equity_snapshots (created_at);

-- ============================================================
-- RLS: dashboard koristi ANON kljuc + Supabase Auth login.
-- Samo prijavljeni korisnik (authenticated) moze citati; pisati
-- moze samo u bot_settings i provider_stats (toggle/riziko).
-- Workeri koriste SERVICE ROLE kljuc (zaobilazi RLS).
-- ============================================================
alter table public.bot_settings      enable row level security;
alter table public.parsed_signals    enable row level security;
alter table public.trade_executions  enable row level security;
alter table public.provider_stats    enable row level security;
alter table public.activity_log      enable row level security;
alter table public.bot_heartbeat     enable row level security;
alter table public.equity_snapshots  enable row level security;

do $$ begin
  -- read-all za prijavljene
  create policy "auth read settings"   on public.bot_settings     for select to authenticated using (true);
  create policy "auth read signals"    on public.parsed_signals   for select to authenticated using (true);
  create policy "auth read execs"      on public.trade_executions for select to authenticated using (true);
  create policy "auth read providers"  on public.provider_stats   for select to authenticated using (true);
  create policy "auth read activity"   on public.activity_log     for select to authenticated using (true);
  create policy "auth read heartbeat"  on public.bot_heartbeat    for select to authenticated using (true);
  create policy "auth read equity"     on public.equity_snapshots for select to authenticated using (true);
  -- write samo gdje dashboard treba
  create policy "auth write settings"  on public.bot_settings     for insert to authenticated with check (true);
  create policy "auth update settings" on public.bot_settings     for update to authenticated using (true);
  create policy "auth update providers" on public.provider_stats  for update to authenticated using (true);
exception when duplicate_object then null;
end $$;

-- Realtime za live dashboard
do $$ begin
  alter publication supabase_realtime add table public.parsed_signals;
  alter publication supabase_realtime add table public.trade_executions;
  alter publication supabase_realtime add table public.activity_log;
  alter publication supabase_realtime add table public.bot_heartbeat;
exception when duplicate_object then null;
end $$;

-- ============================================================
-- DEFAULT SETTINGS (seed — dashboard Settings stranica ovo ureduje)
-- ============================================================
insert into public.bot_settings (key, value) values
  ('kill_switch',      '{"enabled": false}'),
  ('mode',             '{"mode": "demo"}'),  -- demo | live
  ('risk',             '{"risk_percent": 0.5, "daily_max_loss_percent": 3.0, "max_open_positions": 4, "min_confidence": 0.75, "slippage_max_usd": 1.0, "entry_mode": "smart", "breakeven_after_tp1": true, "split_equal_per_tp": true, "lot_floor": 0.01, "lot_cap": 1.0}'),
  ('mt5',              '{"login": "", "server": "IG-Live2", "symbol": "XAUUSD", "symbol_suffix": ""}'),
  ('telegram',         '{"api_id": "", "api_hash": "", "channel_id": "-1003910126970", "bot_token": "", "notify_chat_id": ""}'),
  ('anthropic',        '{"model": "claude-sonnet-4-6", "max_tokens": 1024}'),
  ('external_signals', '{"text_column": "content", "provider_column": "source"}')
on conflict (key) do nothing;

-- Kolona za vezu parser <-> external_signals (ako ne postoji)
do $$ begin
  alter table public.external_signals add column if not exists parsed boolean default false;
exception when undefined_table then null;
end $$;
