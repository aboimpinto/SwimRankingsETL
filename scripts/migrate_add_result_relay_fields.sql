-- Preserve LENEX team-relay metadata on canonical athlete result rows.
-- Each selected relay member receives the team performance, flagged as a relay.
ALTER TABLE results
  ADD COLUMN IF NOT EXISTS is_relay boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS relay_count integer;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'results_relay_count_check'
      AND conrelid = 'results'::regclass
  ) THEN
    ALTER TABLE results
      ADD CONSTRAINT results_relay_count_check
      CHECK (relay_count IS NULL OR relay_count > 1) NOT VALID;
  END IF;
END $$;

ALTER TABLE results
  VALIDATE CONSTRAINT results_relay_count_check;

COMMENT ON COLUMN results.is_relay IS
  'True when this athlete result represents a LENEX team relay performance.';

COMMENT ON COLUMN results.relay_count IS
  'Number of legs for a relay result, for example 4 for a 4 x 100 relay.';
