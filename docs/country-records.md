# Official country records: discovery, refresh and delivery

National **rankings** list performances; official **record lists** define record holders and age bounds. The homepage's National Rankings country links can lead to a country's record catalogue. The refresher follows only those published navigation links (two levels, at most 100 pages), extracts record-list IDs, and downloads the LENEX lists. It does not turn the fastest ranking row into an official record or invent country list IDs.

`refresh_country_records.py` reuses `swimrankings_http.py` and the established `import_Swiss_NationalRecords.py` parser/downloader. Known DB list IDs remain refreshable when catalogue HTML fails. Each list/course is validated and replaced atomically; identical semantic content retains record IDs. Empty, malformed or mismatched responses leave the previous snapshot intact. Regional, club and disability-specific lists are excluded from these general comparisons. Source nationality, supplied age bounds, status, provenance and measured splits are retained. No-time records are not published as performance benchmarks.

## Run and verify

```bash
python3 scripts/refresh_country_records.py --dry-run \
  --save-dir data/records --report reports/records-preview.json
# Optional --record-list-id 50017 (repeatable), --catalogue-url <published-page>,
# or --catalogue-html <saved-catalogue.html> for links from a normal browser session.
python3 scripts/refresh_country_records.py --config .secrets/localserver.json \
  --save-dir data/records --report reports/records-refresh.json
```

The private JSON uses psycopg2 connection keys (`host`, `port`, `dbname`, `user`, `password`). Never commit it. `--dry-run` does not mutate database tables, even when a connection is supplied. Downloaded source files and reports are local artifacts. A session lock prevents overlapping refreshes. Requests are paced and downloads stop on access/quota failures. Catalogue failure does not stop the separate known-list RecordLenex service; the run still exits nonzero and records incomplete discovery.

Inspect `swimrankings_record_refresh` for list/course success, check time, last success, content hash and errors. A corrected list replaces its previous rows, including records removed by the provider. Failed refreshes retain the last successful hash and counts. The catalogue has its own status row; successful known-list downloads do not imply successful discovery of every country.

After source refresh, SwimProfiles runs `pnpm import:records` and `pnpm audit:records`. It uses a SELECT-only source role and writes app-owned tables in a transaction. The normal swimmer import also includes these records. Unknown/missing country coverage is explicit; no Swiss fallback. Both scripts require the race-analysis release and migration `004-records.sql`.

## Weekly refresh

`ops/refresh-records.sh` runs source refresh, app publication and coverage reporting. It publishes freshness metadata after partial failures, then returns failure for monitoring. Run it after normal meet imports too. The user timer template runs Monday at 05:00 Europe/Zurich (up to 15 minutes jitter), with missed runs caught up when the machine starts.

Create `~/.config/swimrankings-records/environment` privately with absolute installation paths:

```text
ETL_ROOT=/path/to/SwimRankingsETL
RECORD_DB_CONFIG=/private/localserver.json
RECORD_STATE_DIR=/path/to/record-refresh-state
SWIMPROFILES_ROOT=/path/to/SwimProfiles
RECORD_PYTHON=/path/to/python3
RECORD_PNPM=/path/to/pnpm
```

Copy `ops/swimrankings-records.{service,timer}` to `~/.config/systemd/user/`, run `systemctl --user daemon-reload`, then `systemctl --user enable --now swimrankings-records.timer`. Check `systemctl --user list-timers` and `journalctl --user -u swimrankings-records.service`. Do not enable against an old consumer release. A template is not evidence of an installed timer.

## AWS delivery

Meet-delivery packages do **not** transport official record tables. Copy a validated record-file bundle through the existing SSH delivery channel, then run the same script against AWS's private source writer config:

```bash
python3 scripts/refresh_country_records.py --config /private/aws-writer.json \
  --input-directory /path/to/validated-record-bundle \
  --save-dir /path/to/records --report /path/to/records-refresh.json
```

Offline mode imports only list IDs present in the bundle and never accesses the network. It reports `provided_files_only`, not freshly discovered catalogue coverage. Keep failed/stale download files out of a delivery bundle: select the successful `files` entries from the download report. Back up the two existing record tables before the first rollout. Grant the consumer source reader SELECT on records, splits and refresh metadata; apply the new app migration and run the records-only consumer import using maintenance credentials. Verify source and app counts and a zero-change replay. Do not reset shared databases or run a full profile import merely to update records.

## Verified coverage / remaining discovery

On 28 September 2026 the established downloader fetched all 12 known list/course files: World 50001, World Junior 50008, Europe 50009, European Junior 50010, Switzerland 50017 and Swiss age groups 50018. These contain **1,142 records and 6,020 split rows**, imported into the local and AWS canonical sources. Only Swiss national/age lists are currently confirmed; this is not worldwide national coverage. The main site's HTML catalogue still returned HTTP 403, consistent with the ETL's previous access reports. Automated navigation is covered by fixtures, not yet a successful live country-directory crawl. A browser-accessible country's page/list URL or restored catalogue access is needed to validate broader discovery. File downloads themselves are working.

## Direct weekly AWS refresh

The public RecordLenex service can also refresh known lists directly on AWS through the same HTTP client (no browser cookies are copied). `ops/refresh-records-aws.sh` runs source refresh and the records-only SwimProfiles maintenance script. Configure `ETL_ROOT`, `RECORD_DB_CONFIG`, `RECORD_STATE_DIR`, `RECORD_PYTHON`, and `RECORD_CONSUMER_SCRIPT` in `/etc/swimrankings-records/environment`. Install the `swimrankings-records-aws.service` and timer under `/etc/systemd/system`. The timer runs Monday 05:30 Europe/Zurich plus up to 15 minutes jitter. Shared operation locks prevent collision with website deployment/import. Downloads or catalogue discovery failures retain prior data and make the service fail visibly, while successful lists and their health are published.

For first rollout before the UI image, the consumer supports `SWIMPROFILES_RECORD_CODE_DIR`, a pinned copy of the tested maintenance scripts/library. After the normal release contains these scripts, omit the override. This does not replace the website image. Check the installed timer and a real run before claiming automation is active.
