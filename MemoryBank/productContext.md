# Product Context

## Why this project exists

Swim meet data arrives in LENEX/XML files that are not directly usable for application queries, rankings, or database joins. This project exists to turn those source files into structured relational data.

## Problem it solves

Without this ETL layer, the team would need to manually:
- Parse LENEX files.
- Normalize inconsistent metadata.
- Match swimmers across files and countries.
- Deduplicate results.
- Preserve raw source lineage for debugging.
- Repair incomplete historical imports.

## Intended outcome

After running these scripts, the database should contain:
- One normalized representation of each meet.
- Standardized events by distance, stroke, gender, and pool length.
- Canonical swimmer records, with alias tracking when source IDs vary.
- Final result rows ready for downstream ranking logic.
- Raw staging records when auditability is needed.

## Likely operator workflow

1. Obtain meet files from SwimRankings or another upstream source.
2. Place them in the expected data directory.
3. Run the appropriate import, rebuild, repair, or backfill script.
4. Review `processing_log` and downstream database state.
5. Recompute rankings when the import flow requires it.

## Quality goals

The code consistently aims for:
- repeatable imports
- minimal duplicate results
- recoverable raw lineage
- better swimmer identity resolution over time
- targeted repair scripts instead of always rebuilding everything
