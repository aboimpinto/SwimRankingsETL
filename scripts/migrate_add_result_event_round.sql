-- Preserve the LENEX EVENT/@round token (for example PRE, FIN, TIM).
-- Medal presentation must use final/timed-final standings only.
ALTER TABLE results
  ADD COLUMN IF NOT EXISTS event_round varchar(8);

COMMENT ON COLUMN results.event_round IS
  'LENEX event round token, e.g. PRE (preliminary), FIN (final), TIM (timed final).';
