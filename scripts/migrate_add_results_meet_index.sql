-- Apply with psql ON_ERROR_STOP=1, outside a transaction, as the table owner.
-- Inspect existing valid non-partial indexes first; see docs/live-meet-index.md.
-- Does not change the result identity/uniqueness constraint.
SET lock_timeout = '5s';
SET statement_timeout = '15min';
CREATE INDEX CONCURRENTLY IF NOT EXISTS results_meet_id_id_idx
  ON public.results (meet_id, id);
