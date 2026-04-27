# Active Context

## Current repository state

This checkout is a small, script-only ETL repository with no root documentation, no tests, and no packaging metadata. The code is operationally focused and appears to be used for manual or semi-manual data imports.

## What is clearly implemented

- LENEX/XML parsing
- meet, event, swimmer, and result normalization
- PostgreSQL writes
- raw staging in several import paths
- repair and backfill workflows for historical data quality issues

## Recently added

- Direct public SwimRankings live import scripts:
  - `scripts/import_live_swimrankings_meet.py`
  - `scripts/import_live_swimrankings_month.py`
- A SophiaWalkerSwim-specific runbook:
  - `docs/import-to-sophia-website-db.md`

## What is still not present in this checkout

- the shared helper file `scripts/lenex_import_utils.py`
- the ranking recomputation script `scripts/recompute_age_group_rankings.py`
- the referenced document `docs/ETL_AGE_GROUP_RANKING_RULES.md`

## Observed risks and rough edges

- Several scripts still reference `meet_city` without defining it locally, so not every script appears runnable as-is.
- The repo mixes import logic, repair logic, and shared helper logic without a central command surface.
- Hardcoded file lists make targeted reruns easy, but they also make the process harder to generalize.
- Most historical scripts assume `/workspace/...` paths, which do not match this Windows checkout directly.

## Practical interpretation

The repository looks like a working ETL toolbox extracted from a larger operating environment. It likely depends on:
- an external file acquisition step
- a PostgreSQL schema that already exists
- missing helper files that are present elsewhere in the original environment

## What this MemoryBank should help with

- quickly explain the purpose of the repo
- document the real ETL flow
- make the current boundaries and missing pieces explicit
- reduce re-discovery time before future cleanup or refactoring work
