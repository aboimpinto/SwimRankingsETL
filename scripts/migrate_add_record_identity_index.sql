-- Apply with psql ON_ERROR_STOP=1, outside a transaction, as the table owner.
-- Inspect equivalent valid indexes first; see docs/record-identity-index.md.
-- This is deliberately non-unique: names/year are matching candidates, not identity authority.
SET lock_timeout = '5s';
SET statement_timeout = '15min';
CREATE INDEX CONCURRENTLY IF NOT EXISTS swimmers_record_identity_idx
  ON public.swimmers (birth_year, lower(btrim(first_name)), lower(btrim(last_name)))
  INCLUDE (id, country_code);
