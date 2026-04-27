# Script Inventory

## Rebuild and bulk import

- `scripts/rebuild_q1_2026_from_files.py`
  Main shared import pattern. Loads files from `/workspace/data/lenex`, truncates import tables, rebuilds meets/events/swimmers/results, and logs progress.
- `scripts/rebuild_q1_2026_from_manifest.py`
  Rebuilds from a manifest-defined subset of files.
- `scripts/rebuild_q1_2026_with_aliases.py`
  Similar rebuild flow, but adds alias-aware swimmer resolution through `swimmer_aliases`.

## Batch imports

- `scripts/import_live_swimrankings_meet.py`
  Imports one local or live SwimRankings LENEX result file into the canonical and raw staging tables.
- `scripts/import_live_swimrankings_month.py`
  Reads the live SwimRankings calendar, downloads public result LENEX files for a target month, and imports only meets that are not already loaded.
- `scripts/import_sui_bel_batch.py`
  Imports a hardcoded Switzerland/Belgium subset directly into canonical tables.
- `scripts/import_sui_bel_batch_with_raw_staging.py`
  Same general scope, but also writes raw staging rows.
- `scripts/import_validation_batch.py`
  Imports a small validation subset.
- `scripts/import_validation_batch_with_raw_staging.py`
  Validation subset with raw staging and table reset for raw import tables.
- `scripts/import_ned_esp_por_batch_with_raw_staging.py`
  Imports a Netherlands, Spain, and Portugal subset with raw staging.
- `scripts/import_remaining_2026_batch_with_raw_staging.py`
  Imports an additional 2026 subset with raw staging.
- `scripts/import_2025_aug_dec_with_raw_staging.py`
  Imports a 2025 historical subset with raw staging.
- `scripts/import_browser_downloads_2026_q1.py`
  Appears intended to import browser-downloaded Q1 2026 files from the raw data folder.
- `scripts/import_remaining_janfeb_raw.py`
  Imports a remaining January and February subset from the processed folder.

## Repairs and backfills

- `scripts/repair_janfeb_2026.py`
  Repairs missing January and February 2026 data.
- `scripts/repair_missing_results_only.py`
  Adds missing `results` rows without rebuilding everything.
- `scripts/backfill_meet_city_from_lenex.py`
  Scans LENEX files to update missing meet cities.
- `scripts/backfill_lenex_status_comment.py`
  Backfills raw and final result metadata such as status and comments.
- `scripts/backfill_lenex_agegroups.py`
  Backfills age-group ranking metadata from LENEX `AGEGROUPS` and `RANKINGS`.

## Schema support

- `scripts/migrate_add_raw_import_file_city.sql`
  Adds `meet_city` to `raw_import_files` if it does not exist.

## General observations

- The repository is organized around one-off and targeted operational scripts rather than one reusable CLI.
- Several scripts share large blocks of similar logic.
- Many scripts are optimized for selective reruns by hardcoding file lists or manifests.
