# Published country record refresh

For the weekly operator procedure, use the [manual weekly runbook](weekly-record-refresh.md): preview, review, publish locally, transfer the same files to AWS, and verify receipts. No scheduler setup is required.

The **Records catalogue** is distinct from the National Rankings country menu.
Not every country with rankings has a published official record list. Import
published record lists; do not infer official records from ranking results.
The catalogue also contains Masters, regional, club, championship, para and
archived lists. Preserve their provenance and exact age bounds, and keep their
comparison scope separate.

## Manual process, ready for a later crontab

No cron entry or timer is installed by these scripts. The owner will configure
scheduling later. Both previously enabled local/AWS record timers were disabled
on 28 September 2026.

Create a private Bash environment file with absolute paths (quote paths that
contain spaces):

```bash
ETL_ROOT=/path/to/SwimRankingsETL
RECORD_DB_CONFIG=/private/localserver.json
RECORD_STATE_DIR=/path/to/record-refresh-state
RECORD_PYTHON=/path/to/python3
SWIMPROFILES_ROOT=/path/to/SwimProfiles
RECORD_PNPM=/path/to/pnpm
```

The database JSON contains psycopg2 connection keys (`host`, `port`, `dbname`,
`user`, `password`). Keep both configuration files outside Git. This is a trusted
shell configuration, not a file received from SwimRankings.

```bash
# Inspect discovery/downloads and validate all available files, without DB writes
# or application publication. Files and reports are written as evidence.
bash ops/refresh-records.sh --env /private/environment --dry-run

# Refresh source records, publish to the application, audit coverage.
bash ops/refresh-records.sh --env /private/environment
```

This exact command can later be used by cron with absolute paths. It requires no
interactive prompt or browser. Do not enable it on a machine without configured
credentials, dependencies and application maintenance code.

Each invocation has a private `RECORD_STATE_DIR/runs/<UTC-time>-<unique>/` folder:

- `run.log`: source/consumer output, including failed runs.
- `source.json`: requested list IDs, catalogue status, file hashes, counts and
  each imported definition's nation, gender, age bounds, type and scope.
- `files/`: only validated files downloaded in this run; no previous-run files.
- `coverage.json`: the local application's coverage audit, when using the local
  SwimProfiles consumer.
- `pipeline.json`: source, consumer and audit exit codes. `latest.json` is an
  atomically replaced pointer receipt containing the run path.

A pipeline lock rejects overlap. The source also holds a PostgreSQL advisory
lock. Requests use the existing `SwimRankingsHttpClient`, with bounded retries,
request pacing and a stop on authorization/rate-limit failures. Run the process
after meet imports too if updated benchmarks are needed.

Every run downloads each known list again, even when an earlier copy exists.
Identical semantic content keeps row IDs; corrections replace a list/course in
one transaction. Empty, malformed, mismatched or failed downloads preserve the
last good snapshot. Successful lists and refresh health are still published
after partial failure, but the command returns nonzero. There is no all-country
success claim merely because the known files downloaded.

## Discovery and coverage

The default discovery URL is
<https://www.swimrankings.net/index.php?page=recordSelect>. Only published
SwimRankings navigation links are followed, within bounded depth/page limits.
No guessed numeric list-ID sweep is used. `catalogue.json` persists discovered
IDs and labels for future retries when catalogue access fails. Existing database
list IDs are refreshed as well.

If the catalogue requires a normal browser challenge, save its HTML from that
browser and run:

```bash
bash ops/refresh-records.sh --env /private/environment --dry-run \
  --catalogue-html /path/to/saved-record-catalogue.html
```

Repeat without `--dry-run` to import. Saved HTML is explicitly reported as
`saved_html`, with its hash; it is not proof of a fresh online catalogue crawl.
Screenshots supply names but do not contain the linked IDs needed for downloads.
An old saved catalogue allows known-list refresh but cannot reveal new lists
added since it was saved. Normal weekly runs attempt fresh discovery again.

`complete_published_catalogue` means live catalogue discovery and every requested
file succeeded, **not** that every country in the world publishes records.
`unmapped_definitions` identifies source types requiring scope review. Missing
source lists, missing age groups and unavailable countries must remain visible in
the app audit; do not substitute another country's records.

`comparison_scope` is conservative. World/European and verified national/age
record types can become benchmarks; explicit regional/club/para restrictions,
championship lists and archived lists are excluded. Swiss Masters (`SUI.MS`) and
the published Faroese alias (`FAR`, nation `FRO`) are recognized. Unknown federation
extensions are retained as `unmapped`, not treated as national merely because
they start with a country code. Preserve source age bounds instead of imposing a
universal youth/Masters category. SwimProfiles must consume the scope metadata
before broader lists are enabled in comparisons.

## AWS and application publication

The same process works on AWS. Set `RECORD_CONSUMER_SCRIPT` to the existing
records-only maintenance script instead of `SWIMPROFILES_ROOT`. The compatibility
entry point `ops/refresh-records-aws.sh` invokes the same implementation. It does
not install anything in crontab or systemd.

For delivery of exactly the validated desktop files, copy one run's `files/`
folder and source report through the established SSH channel, then use:

```bash
bash ops/refresh-records-aws.sh --env /private/aws-environment \
  --input-directory /path/to/validated-run/files
```

Offline mode never discovers fresh lists; it reports `provided_files_only`.
Only copy files from a successful/current run, not a cache mixing old and new
files. Compare report hashes and record/split totals between source and target.
An offline replay should report `changed: false` for all unchanged files.

Apply source additive columns and the app record migration before publication;
grant the app source reader SELECT on records, splits and refresh metadata.
`pnpm import:records` publishes only record tables, using the app writer role;
`pnpm audit:records` checks coverage for active profile countries. Do not run a
full swimmer/ranking rebuild solely to refresh records. Shared DBs must never be
reset. The web application reads only its own tables.

## Verified coverage and open work — 28 September 2026

Before this follow-up, both canonical and app databases contained **1,142 records
and 6,020 splits** from 12 files: World 50001, World Junior 50008, European 50009,
European Junior 50010, Swiss National 50017 and Swiss Age-group 50018, both courses.
That was partial coverage, not completion of all-country discovery.

Additional LENEX downloads have been verified against links published by the
[KNZB](https://www.knzb.nl/wedstrijdzwemmen/records-ranglijsten-klassementen)
(Netherlands 50030/50031 and archived 50032),
[the Faroese federation](https://ssf.fo/kapping/met/foroysk-met-25m/) (50057), and
[Swiss Aquatics](https://www.swiss-aquatics.ch/masters-schweizerrekorde-masters-kurzbahnschweizerrekorde/)
(Masters 50069). These 10 additional files were subsequently imported into both
canonical databases and both SwimProfiles app databases: **3,374 total records /
13,031 splits**. This includes 201 archived Dutch rows, retained for provenance
and excluded from current comparisons. The remaining new rows add Netherlands,
Faroe Islands and Swiss Masters coverage. Raw file hashes were verified after
SSH transfer; local replay changed zero source snapshots and zero app rows.
Run evidence is retained under each configured state directory. Full published
catalogue enumeration is still unfinished.

The main catalogue currently returns a Cloudflare browser challenge (403) to the
ETL, while RecordLenex downloads work. The owner's screenshots confirm more lists
exist, including countries not yet configured. The complete saved HTML or a
successful live catalogue crawl is still needed to enumerate all published IDs.
The owner subsequently accepted unavailable national lists: those comparisons
remain unavailable while verified continental/World comparisons work. Broader
national catalogue coverage remains a documented limitation, not a claim of
completion. Website release state is separate from source-data refresh state.

## Country navigation and continental fallback — owner clarification

`config/record-country-pages.json` retains the owner's 54 country navigation URLs.
These are ranking pages, not official record-list IDs. Normal online discovery
checks these alongside the record catalogue, records each outcome, and skips
remaining pages on a host after access rejection. The separately hosted Slovak
URL currently returns a page-not-found message with HTTP 200. Neither an access
failure nor a page without record links proves the country has no records.

For a read-only link audit without record downloads or database access:

```bash
python3 scripts/refresh_country_records.py --discover-only \
  --report /path/to/country-navigation.json
```

Missing national/age coverage disables only that comparison. Continental and
World records remain independent. The country comparison follows the selected
swimmer nationality, using World Aquatics' continental federation mapping; it is
not based on the competition venue or club. Canada uses **Americas**, not Europe.
"American records" meaning USA national records, Pan-American Games records and
Pan-Pacific championship records must not be substituted for Americas records.

The manual pipeline now also runs `refresh_continental_records.py`. It uses the
public JSON service backing the official
[World Aquatics Records page](https://www.worldaquatics.com/swimming/records) for
Americas (AM), Africa (AF), Asia (AS) and Oceania (OC). European and World records
continue through their existing SwimRankings LENEX lists. Sources retain distinct
`WA-<code>` list IDs; the LENEX updater ignores these IDs when building download
URLs. The app uses the reviewed `comparison_scope`.

The World Aquatics page's published JavaScript maps continent names to these
codes and sends `recordCode`, `gender` and **`pool`** to
`https://api.worldaquatics.com/fina/records/SW`. `poolConfiguration` is not the
correct request parameter for this endpoint: it silently returns LCM. Responses
are validated against expected pool, gender, record code, pagination count and
unique provider IDs. `=AM` and equivalent markers mean tied records and are
retained; only approved source status 2 is used in comparisons. Other statuses
are retained as excluded/pending. The importer does not manufacture split times
from final times. These records currently supply final time and average speed;
intermediate split comparisons remain unavailable where measurements are absent.

A run retains `continental.json` and eight `worldaquatics_records_*.json` bundles
alongside its LENEX files. Both source adapters publish before the application
import. Failed continental refreshes preserve their last good snapshot, and
successful national lists still publish. The exit status and receipt expose each
provider's failure separately. Offline delivery must include both providers'
files from the validated run. `--skip-continental` explicitly supports a legacy
LENEX-only bundle; it is not the normal weekly refresh.

The read-only continental preview on 28 September validated **378 records** across
all eight list/course bundles. Those records were then published into both local and AWS canonical/app
databases, bringing each snapshot to **3,752 records / 13,031 measured splits**.
All eight continental bundle hashes were checked after SSH transfer. Local
source/app replay changed zero records. Run receipts retain per-provider hashes,
counts and outcomes; this data publication does not deploy the website UI.
