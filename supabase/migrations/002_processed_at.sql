-- ============================================================
-- ZigZag — migracija 002: processed_at queue marker
-- Pokreni u Supabase SQL Editoru (nakon 001_zigzag_schema.sql).
-- Sigurno za ponovno pokretanje (IF NOT EXISTS svugdje).
-- ============================================================

-- Zamjenjuje stari poll obrazac na decision_reason (null / "Follow-up%")
-- jasnim, nedvosmislenim timestamp poljem: executor upisuje processed_at
-- kad zavrsi obradu follow-up poruke (update_sl/tp_hit/move_to_be/close/
-- partial_close). decision_reason ostaje samo za citljivo objasnjenje na
-- dashboardu i vise ga queue logika ne dira.
alter table if exists public.parsed_signals
  add column if not exists processed_at timestamptz;

-- Brz upit za "neobradeni follow-upovi" u executoru.
create index if not exists idx_parsed_signals_unprocessed_followups
  on public.parsed_signals (created_at)
  where processed_at is null and message_type <> 'new_signal';
