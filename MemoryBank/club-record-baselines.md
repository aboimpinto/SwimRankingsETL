# Club-record baselines

Limmat Sharks source club ID: `65634`. Import the official **Alltime** exports
before evaluating newly imported performances. The meet database is incomplete
historically and is not a reliable starting point for all-time club records.

## Coverage and meaning

The official lists have 36 combinations: SCM/LCM × women/men × Open,
11-and-under, and exact ages 12 through 18. Each Excel export contains all
published strokes and distances for that combination. Never infer age-group
records from the Open top-50 list. These categories are independent of the
website's ranking comparison groups and its September–August seasons.

Individual swims, relay splits (`Lap`) and relay teams are separate event keys.
Tied best performances are retained. A missing sheet is recorded in
`unlisted_individual_events`; it does not mean a zero-time record. Coverage
`complete` means all 36 category exports are present, not that every possible
event has a published record or that complete record progression is available.

The `Top Results` sheet duplicates points-sorted performances and is not imported.
Full birth dates remain in the private raw exports; the portable baseline keeps
only birth years. Source URL, export timestamp and SHA-256 accompany every
category. The package has a content digest and format version.

## Desktop collection

Use Python 3 with Playwright installed for the optional collector. Browser
authentication and any verification are completed by the operator. For example,
launch normal Chromium with a dedicated profile and loopback debugging port:

```bash
chromium --user-data-dir="$HOME/snap/chromium/common/sharks-club-records" \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9334 \
  'https://www.swimrankings.net/index.php?page=rankingDetail&clubId=65634&season=-1&course=LCM&agegroup=X_X&stroke=0&gender=2'

python3 scripts/collect_club_records.py \
  --output data/export/club-records-YYYY-MM-DD
python3 scripts/club_record_baselines.py export \
  --manifest data/export/club-records-YYYY-MM-DD/manifest.json \
  --output data/export/club-records-YYYY-MM-DD/baseline.json
```

Adjust the browser executable/profile location for the installed browser. The
collector attaches to this existing browser; it does not launch an automated
profile, disable the sandbox or bypass verification. Fetching the linked XLSX
inside the browser avoids Snap download-path restrictions. It stops on access
failures, pauses between exports and resumes from already validated files.
No cookies or passwords are exported. Keep profiles and `data/export` private.
Close the dedicated browser after collection if it is no longer needed.

## Database publication

Install `requirements-delivery.txt`. The writer config is an existing private
JSON file of psycopg2 connection arguments. Never commit it or pass passwords
on the command line.

```bash
# Dry run: all SQL, including first-time table creation, is rolled back.
python3 scripts/club_record_baselines.py apply \
  --package data/export/club-records-YYYY-MM-DD/baseline.json \
  --db-config .secrets/localserver.json

# Publish atomically after successful validation and dry run.
python3 scripts/club_record_baselines.py apply \
  --package data/export/club-records-YYYY-MM-DD/baseline.json \
  --db-config .secrets/localserver.json --commit
```

The canonical SwimRankings database gains two independent tables:

- `club_record_baseline_categories`: latest validated source per category.
- `club_record_baseline_imports`: immutable package history keyed by digest.

Neither meet/result tables nor website season archives are updated. The import
uses a transaction and advisory lock. Repeating a package is idempotent. Older
exports, changed content under the same source hash, missing established records
and slower replacements are rejected; source corrections require separate review.

The same small `baseline.json` and importer can be transferred to AWS, validated
and applied with AWS's own writer config. Do not copy the desktop credential
file or replace the full database. Grant the website's source reader SELECT on
these two tables when integrating the consumer. Package hashes verify transfer
integrity; authenticity depends on the trusted desktop collection process.

## Website consumer boundary

This importer establishes the source baseline. Automatic evaluation of later
club swims, a maintained website record list and Club Record badges are a
separate website integration. Consumers must require evidence of the club
represented at the swim, match holder identity and performance age, distinguish
equalled from improved times, and preserve closed season snapshots. Current
club membership alone is not enough. Do not infer historical record progression
before the baseline from an incomplete meet history.

## Verification

```bash
DELIVERY_TEST_CONFIG=/path/to/isolated-test-config.json \
  python3 -m unittest discover -s tests -p 'test_*delivery*.py' -v
```

The integration tests refuse databases without a `swimrankings_delivery_test`
prefix. CI runs the same contract suite against an isolated PostgreSQL service.
Fixtures contain synthetic identities only; raw exports and portable packages
are local delivery artifacts, not repository fixtures.
