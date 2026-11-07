# Official record candidate lookup index

Issue #36 addresses SwimProfiles' official NR, age-group NR, ER and WR matching.
Its existing query compares birth year, `lower(trim(first_name))` and
`lower(trim(last_name))`, then checks the race date, event, time and nationality.
The populated local plan performed 4,582 birth-year lookups and filtered names,
causing about 2.49 million swimmer buffer hits for 2,285 record candidates.

The proposed non-unique index matches those three existing predicates and includes
canonical ID/country for the next joins. It changes access cost only. Duplicate
names remain legal; it does not establish identity, merge swimmers or alter record
matching, ambiguity handling, nationality checks or badge publication.

## Controlled installation

Pause scheduled imports for the before/after experiment. Verify the intended
canonical host/database, existing index definitions, free disk space and active
index builds. Reuse an equivalent valid index rather than create a duplicate.
Run `scripts/migrate_add_record_identity_index.sql` with the canonical table-owner
connection using `psql --set=ON_ERROR_STOP=1 --file=...`, outside a transaction.
The application consumer retains read-only source access.

Verify `pg_index.indisvalid` and `indisready`, `pg_get_indexdef`, index size and the
actual consumer query's EXPLAIN ANALYZE/BUFFERS plan. Compare complete candidate
matches and accepted badge payloads, not just counts. `IF NOT EXISTS` alone does
not prove that an existing same-named object has the right definition.

A failed concurrent build may leave an invalid index. Inspect it and dependencies
before retrying. Only this newly created index may be rolled back with
`DROP INDEX CONCURRENTLY public.swimmers_record_identity_idx`, outside a
transaction. Keep existing indexes and all source records unchanged.

Measure locally first, then repeat the checks on AWS. Retain private raw evidence
with the daily trial and summarize hardware, cache conditions and query outcomes
here. No source or deployment performance improvement is asserted before evidence.

## Local evidence, 7 November 2026

The existing canonical source server (10.88.30.124, PostgreSQL; hardware not
independently inspected) had no equivalent index. Concurrent creation took298ms;
index size6,422,528bytes, valid/ready/non-unique. SSH was unavailable, so filesystem
headroom was not independently measured; do not substitute client-host capacity.

The actual consumer query with2,285 official-record candidates took4,812.146ms
before and62.107ms after. Swimmer lookup shared hits fell2,491,319 to16,400 over
4,582 loops. The plan uses swimmers_record_identity_idx. This is an immediate
before/after sample with warm buffers, not a guaranteed production speedup.
Complete63 candidate matches and57 accepted badge payloads are identical after
sorting; matching semantics, IDs and source records were unchanged. Private
artifacts are record-match-before-index.json / record-match-after-index.json in
SwimProfiles/artifacts and local-record-identity-index.json in the daily ETL trial.
AWS installation and measurement are separate and remain pending.
