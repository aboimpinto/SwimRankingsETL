# Live competition discovery and basic PDF imports

The live directory at <https://live.swimrankings.net/> links each competition to
`https://live.swimrankings.net/<live-id>/`. This is a **live website ID**, not the
integer primary key of our canonical meet and not necessarily its archived
SwimRankings ID. Discover the published link; never derive it from a meet name
or guess sequential IDs. The directory has a limited publication window and
only covers competitions published there, not every swimming competition.

`live_result_sources.py` discovers those links and reads the actual linked
`ResultList_*.pdf` files. It does not import start lists or guess PDF filenames.
LENEX is preferred when a populated, consistent export is available. A valid
schedule-only LENEX can supply event metadata for PDF results; the live event
table also supplies explicit round, distance, stroke and competition category.

## Supported data and review holds

The initial PDF adapter supports the verified **German Splash individual-result
layout**, including category placements, four-digit birth years, recorded DSQ
times, FINA points and club codes. Relays without verified athlete identities,
non-finishes without a recorded time, and unsupported layouts are reported
explicitly. PDF swimmer nationality, reaction time, heat, lane and splits remain
unknown. Club country is never substituted for nationality. PDF club codes stay
in the source receipt and do not replace an established full club name.

Only a unique existing name + birth year + competition-category identity can be
linked automatically from a PDF. Duplicate/unknown identities are held. A private
reviewed mapping from the report's `identity_key` to a canonical swimmer integer
ID can resolve duplicate candidates; name, year and category must still match.
The command does not merge profiles or automatically create PDF-only swimmers.
Authoritative LENEX identities can create swimmers using existing canonical-key
conventions. Alias matches are checked against name/year/category/country.

PDF age-category place is stored as `age_group_rank`, not an invented overall
meet rank. No missing time is replaced with zero. Unsupported nationality,
age-only/two-digit-birth-year or unverified category fields must be reviewed
before expanding support to another PDF layout.

## Preview before commit

Use Python 3.10+, Poppler `pdftotext`, and `requirements-delivery.txt`. Keep the
connection JSON and reports private and outside Git. From the ETL checkout:

```bash
python3 scripts/import_live_results.py discover \
  --since 2026-09-21 --until 2026-09-26 --output reports/live-imports/discovered.json
python3 scripts/import_live_results.py collect \
  --live-id 10928 --output reports/live-imports
python3 scripts/import_live_results.py plan \
  --source reports/live-imports/10928/source.json \
  --config .secrets/localserver.json --expect-host 10.88.30.124 \
  --expect-database swimrankings --output reports/live-imports/10928/plan.json
```

The plan command uses a read-only database transaction, with no schema creation
or sequence changes. Review its `entries`, `counts`, `holds`, `excluded` and
`plan_hash`. `collect` retains source files by SHA-256 and URL, and saves parsed
rows. A PDF's successful parse does not imply every swimmer identity is resolved.
These raw reports contain swimmer data and must not be publicly served.

```bash
python3 scripts/import_live_results.py apply \
  --source reports/live-imports/10928/source.json \
  --config .secrets/localserver.json --expect-host 10.88.30.124 \
  --expect-database swimrankings --expect-plan-sha <reviewed-plan-hash> \
  --output reports/live-imports/10928/receipt.json --commit
```

Without `--commit`, `apply` only produces another read-only plan. Add `--day
YYYY-MM-DD` to both planning and applying to select one or more session dates.
Add `--identities path/to/reviewed-map.json` to both commands when needed.
`--allow-held` explicitly applies only eligible rows while retaining identity or
unsupported-document holds. It cannot bypass regressed exports or conflicting
previously imported race identities. Review what will remain missing first.

Applying replans under a transaction lock and rejects a stale plan hash. Database
changes, source receipts and the run receipt commit together. No races from other
days are deleted. Repeated documents are unchanged; corrected results update the
same row. Removed previously accepted results are held, not silently deleted.
The `live_result_imports` table preserves per-race provenance; `live_result_import_runs`
preserves run receipts. Download failures never delete canonical data.

## Later days and LENEX enrichment

```bash
# Fetch fresh sources for every previously collected meet, including older watches.
python3 scripts/import_live_results.py collect --recheck --output reports/live-imports
```

Then plan/apply changed meets again. Also discover new meets since the last
successful collection period. New importer runs are recorded in
`live_result_import_runs`; the older `processing_log` only records legacy runs. Retain watches independently of the cutoff; late
results may appear after a meet has ended. These are manual commands, not a cron
job. All collected meets remain `recheck_required` until independently verified;
calendar dates and one result per day do not prove completion.

Use **this same importer** when LENEX arrives. It matches an existing PDF race by
canonical swimmer and source event number/session date/round, updates the same
result ID, replaces the missing details with source values, and adds splits.
PDFs cannot downgrade LENEX results. A changed swimmer/event identity is held.
The older monthly writer still has its cache/skip behavior and does not use this
new receipt system; do not use it to resume PDF-derived or partial meets.

## Publication

Import first into localServer. Validate counts, repeat plans and held rows, then
use [incremental delivery](desktop-incremental-delivery.md) to export **all current
canonical rows of each affected meet**, including previously imported days.
Never deliver a day-filtered snapshot as a full meet replacement. Keep the same
publisher/revision history. Deliver to AWS and publish all existing consumer
refreshes. Run the SwimProfiles maintenance importer afterward so it sees the
new canonical data and atomically publishes its changed-meet generation.

Receipts describe the subset actually imported, not full provider coverage.
Schema setup is committed before the shared summary rebuild, releasing its
otherwise long-lived lock on canonical race results. The session advisory lock
still serializes delivery and publication. Summary-table reads may still wait
for the existing TRUNCATE-based rebuild; this does not make that rebuild fully
nonblocking.

No destructive database reset or bulk refresh of unrelated archives is needed.
Before an operational batch, retain its plans and a database backup. Preserve
source FINA points; any separate local score calculation needs its own receipt.
A corrected finish time invalidates the previously calculated Rudolph score
until that calculation is rerun; it must not display the old score for a new time.

## Tests

```bash
python3 -m unittest discover -s tests -p test_live_results.py -v
LIVE_IMPORT_TEST_CONFIG=/private/connection.json \
  python3 -m unittest discover -s tests -p test_live_results.py -v
```

Database tests create random `live_import_test_*` schemas inside a transaction and
roll everything back. They never truncate shared tables, commit fixtures or
create PostgreSQL containers. CI uses the existing delivery test service.
