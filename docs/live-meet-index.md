# Canonical meet lookup index

Issue #34: scoped live snapshots filter `results.meet_id` both for result hashes
and split joins. The existing uniqueness key starts with swimmer ID and cannot
bound those meet-only lookups. A selected-meet plan on 7 November still scanned
the historical results table in its split join (45,530 shared blocks read).

Apply `scripts/migrate_add_results_meet_index.sql` using the existing canonical
writer/table-owner connection, after verifying the intended host and database.
Use `psql --set=ON_ERROR_STOP=1 --file=...`; do not use `--single-transaction`.
The migration creates `(meet_id,id)` concurrently, preserving writes and identities.
Pause scheduled imports for the controlled before/after measurement. No new
PostgreSQL instance, source-data deletion or result replacement is required.

Before execution, inspect `pg_indexes` and `pg_index` for public.results. Reuse an
equivalent valid, non-partial meet-leading index rather than create a duplicate.
Check disk headroom and existing index builds. After execution, verify
`pg_index.indisvalid` and `indisready`, the exact indexed columns, index size,
and `EXPLAIN (ANALYZE,BUFFERS)` for the actual selected-meet manifest. Confirm
manifest hashes/counts agree before/after. An exit code alone is insufficient:
`IF NOT EXISTS` does not validate a same-named existing object's definition.

A timeout/interruption can leave an invalid concurrent index. Inspect its state
and dependencies before retrying; do not blindly report success or drop another
index. Only the newly created index may be removed as rollback, with
`DROP INDEX CONCURRENTLY public.results_meet_id_id_idx`, outside a transaction.
Removing it affects performance only; it does not change records or uniqueness.

Apply and measure locally first, then repeat the same checks on AWS. Keep private
plans, migration duration and manifest comparisons with the 7 November live-trial
receipts. Do not infer AWS performance from local disk/cache behavior.

## Local verification, 7 November 2026

The existing local canonical database had no equivalent meet-leading index.
Concurrent creation took1.105s; the index is valid/ready and32,333,824bytes.
The selected3,103-result meet fingerprint matches the pre-index published manifest.
Before/after execution plans were401.728ms/305.345ms on the local source server;
these warm/cold mixes are not a controlled speedup percentage. The after plan
uses the new index for results and removes its full historical scan. PostgreSQL
still chooses a parallel scan of the smaller splits table (2,564blocks read).
Evaluate that choice on AWS instead of globally disabling sequential scans.
Private artifacts: SwimProfiles trial `source-plans-before-index.json`,
`source-plans.json`, `source-index-manifest.json`; ETL daily trial
`local-source-index.json`. AWS application remains pending.
