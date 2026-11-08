-- Canonical commit and its batch receipt must be one transaction.
CREATE TABLE IF NOT EXISTS live_result_batches (
  batch_id text PRIMARY KEY,
  input_hash text NOT NULL,
  receipt jsonb NOT NULL,
  committed_at timestamptz NOT NULL DEFAULT now()
);
