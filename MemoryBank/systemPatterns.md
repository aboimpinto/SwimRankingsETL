# System Patterns

## Core ETL flow

Most scripts follow the same pattern:

1. Open LENEX/XML input files from a raw or processed data directory.
2. Parse the XML tree, including zipped LENEX payloads.
3. Extract meet-level metadata with helpers such as `extract_meet_metadata()`.
4. Normalize event definitions into `(distance, stroke, gender, pool_length)`.
5. Resolve swimmers from source athlete records into canonical rows.
6. Extract result metadata, convert times to seconds, and drop unusable rows.
7. Insert raw staging rows when the script uses `raw_import_files` and `raw_results`.
8. Upsert final rows into `results`.
9. Record status in `processing_log`.
10. In some flows, trigger age-group ranking recomputation afterward.

## Main implementation patterns

### Shared utility pattern

`scripts/rebuild_q1_2026_from_files.py` acts like the main utility module. Other scripts import helpers from it for:
- database connection
- file parsing
- gender normalization
- time parsing
- country creation
- meet metadata extraction

### Canonical swimmer resolution

There are two visible approaches:
- Basic matching by source swimmer ID or by `(first_name, last_name, birth_year, country_code, gender)`.
- Alias-aware matching using `swimmer_aliases`, with fallback creation of a hashed canonical swimmer ID.

### Raw staging plus final import

The `*_with_raw_staging.py` scripts preserve source-level traceability by writing:
- one row per imported file into `raw_import_files`
- one row per parsed result into `raw_results`

They then deduplicate and upsert the canonical `results` rows.

### Repair and backfill pattern

Repair scripts avoid full rebuilds. Instead, they scan files again and patch specific gaps such as:
- missing meet city values
- missing results
- status, comment, or ranking metadata
- age-group ranking fields

## Script families

- Rebuild scripts: re-import broad datasets from folders or a manifest.
- Batch import scripts: import selected country/date subsets.
- Validation scripts: compare or re-run controlled subsets.
- Repair scripts: patch missing records after earlier imports.
- Backfill scripts: enrich already-imported rows with additional metadata.

## Design tradeoffs visible in the repo

- Fast iteration over strict structure: many scripts duplicate logic instead of sharing one framework.
- Operational pragmatism: hardcoded file lists and manifests are used for targeted reruns.
- Idempotency where possible: many writes use `ON CONFLICT`, but some rebuild flows truncate tables first.
