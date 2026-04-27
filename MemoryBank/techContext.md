# Tech Context

## Stack

- Python 3 scripts
- PostgreSQL as the target database
- `psycopg2` for database access
- `lxml.etree` for XML parsing
- standard library modules such as `zipfile`, `hashlib`, `json`, `subprocess`, and `pathlib`

## Runtime assumptions

Most historical scripts assume a Linux-like runtime layout even though this checkout is on Windows:
- raw data: `/workspace/data/lenex`
- processed data: `/workspace/data/processed`
- temporary manifest example: `/tmp/q1_refined_deduped_manifest.json`

This suggests the scripts were originally run in a container, WSL, or another `/workspace`-based environment.

The live import scripts also support Windows-local operation through explicit command-line arguments such as `--db-url` and `--save-dir`.

## Database connection defaults

The shared `db()` helper uses environment variables with these defaults:
- `PGHOST=172.17.0.1`
- `PGPORT=5433`
- `PGUSER=hushuser`
- `PGDATABASE=swimrankings`
- `PGPASSWORD` must be supplied

## File formats

The scripts handle:
- `.lxf`
- `.lef`
- `.xml`

LENEX files may be zipped containers, so the loader first tries `zipfile.ZipFile` and falls back to plain XML parsing.

## Main database entities touched

- `countries`
- `meets`
- `events`
- `swimmers`
- `swimmer_aliases`
- `results`
- `raw_import_files`
- `raw_results`
- `processing_log`
- `splits` appears in table truncation logic

## Notable implementation details

- Pool length is inferred from the meet `course` field and reduced to `25` or `50`.
- Swim times are converted into seconds for storage and matching.
- Some scripts preserve extra result metadata such as status, points, qualification, entry time, reaction time, rank, and comments.
- Some flows recompute age-group rankings after import.

## Current technical gaps

- `scripts/lenex_import_utils.py` is referenced but not present in this checkout.
- `scripts/recompute_age_group_rankings.py` is referenced but not present in this checkout.
- `docs/ETL_AGE_GROUP_RANKING_RULES.md` is referenced but not present in this checkout.
- There is no dependency manifest, root README, or automated test suite in the current repo.
