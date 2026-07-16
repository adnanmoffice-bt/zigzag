-- ============================================================
-- ZigZag — migration 003: unique guard on parsed_signals.external_signal_id
-- Run in the Supabase SQL Editor (after 001 and 002).
-- Safe to re-run (IF NOT EXISTS everywhere).
-- ============================================================

-- Each external_signals row must map to exactly ONE parsed_signals row.
-- A parser bug (silently-swallowed write to a foreign parse_status CHECK
-- constraint) caused the same ~16 messages to be re-sent to Claude and
-- re-inserted thousands of times, burning through the Anthropic budget.
-- The application-level anti-join fix (parser/claude_parser.py) is the
-- primary defense; this unique index is the hard backstop so a duplicate
-- can never be persisted again even if application logic regresses.
create unique index if not exists parsed_signals_external_signal_id_uniq
  on public.parsed_signals (external_signal_id);
