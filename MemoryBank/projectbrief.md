# Project Brief

## Project

`SwimRankingsETL` is a small Python ETL repository focused on importing swim meet result data into a PostgreSQL database.

## What the code currently does

The scripts in this repository:
- Read LENEX-style meet files (`.lxf`, `.lef`, `.xml`), including zipped LENEX payloads.
- Extract meet metadata such as name, date, country, city, and course length.
- Extract athlete, event, and result records from each meet file.
- Normalize fields like gender, pool length, and swim times.
- Resolve swimmers into canonical database records, sometimes using alias tables.
- Optionally stage raw source rows before writing final normalized results.
- Repair or backfill missing metadata after imports.
- Download and import public live SwimRankings LENEX result files for specific meets or a whole calendar month.

## Primary goal

Convert swim meet files into database records that are usable for downstream ranking, analytics, validation, and reporting workflows.

## Main outputs

The scripts write into database tables including:
- `countries`
- `meets`
- `events`
- `swimmers`
- `swimmer_aliases`
- `results`
- `raw_import_files`
- `raw_results`
- `processing_log`

## Scope limits visible in this checkout

The current repository does not show:
- A packaged application or service layer.
- Automated scheduling or orchestration.
- Tests or formal runbooks.

Based on the checked-in code, this repo is primarily the import and cleanup layer. A small live-import path now covers public SwimRankings LENEX downloads, but there is still no scheduled acquisition service.
