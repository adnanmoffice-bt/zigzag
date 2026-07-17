-- ============================================================
-- ZigZag — migration 004: dedicated "seen" marker on external_signals
-- Run in the Supabase SQL Editor (after 001, 002, 003).
-- Safe to re-run (IF NOT EXISTS everywhere).
-- ============================================================

-- external_signals.parse_status is OWNED by a different, older pipeline (has
-- its own CHECK constraint: pending/parsed/unparseable) and is left untouched
-- by ZigZag on purpose. That means "pending" rows stay pending forever even
-- after ZigZag processes them, so the parser's candidate query kept re-fetching
-- the same oldest already-done rows and could never reach genuinely new
-- messages once the backlog passed the query's fetch window (found 17.7.2026,
-- ~148 real new messages stuck unprocessed for 20+ hours as a result).
--
-- zz_seen_at is a column ZigZag fully owns — no shared constraint, no risk of
-- collision — and lets get_unparsed() run a plain "IS NULL" filter that stays
-- fast and correct forever, independent of external_signals table size.
alter table if exists public.external_signals
  add column if not exists zz_seen_at timestamptz;

create index if not exists idx_external_signals_zz_unseen
  on public.external_signals (created_at)
  where zz_seen_at is null;
