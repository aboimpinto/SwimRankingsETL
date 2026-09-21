# Desktop import and incremental delivery

The desktop downloads LENEX and imports it into the canonical localServer database.
`scripts/meet_delivery.py` exports compressed, versioned competition snapshots and
uploads only revisions missing at the destination. AWS needs Python, PostgreSQL
access and SSH; it never needs SwimRankings cookies or a browser.

This replaces full database transport with complete **per-competition updates**.
It does not require PostgreSQL partitioning. Partitioning/retention can be added
separately without changing the transfer contract.

## Scope and season boundary

Each package contains the canonical meet, participating athletes and aliases,
clubs/countries, events, results, original points and splits. Numeric database IDs
are mapped to destination IDs using stable keys. No application archive, database
credentials, browser state, raw-import staging, record tables or points-summary
tables are included. The source result ID is scoped to a persistent publisher.

Race **session dates** are preserved. For a September–August season, August 2026
races belong to 2025/2026 and September races to 2026/2027, including a meet that
crosses that boundary. Closed website archives remain immutable: late source
results do not reopen or rewrite their prepared snapshots.

Packages represent all rows currently in the canonical meet. They do not prove
complete provider coverage. Validate LENEX ingestion first; do not export a
partially imported meet as a correction. Missing rows in a later revision are
intentional deletions from that meet at the destination.

## Setup

Use Python 3.10+ on Linux and PostgreSQL 16 with the current canonical schema.
Install `python3 -m pip install -r requirements-delivery.txt` on both machines.
The receiver requires canonical tables/columns matching
`tests/fixtures/delivery_schema.sql`; that fixture is for isolated tests, not a
production migration. Missing columns/constraints cause a transaction rollback.

Store connection parameters in private, untracked JSON files, mode `0600`:

```json
{
  "host": "localServer",
  "port": 5433,
  "dbname": "swimrankings",
  "user": "configured_writer",
  "password": "configured_password"
}
```

The export connection can be read-only. Applying packages requires write access
and permission to create the `swimrankings_delivery` receipt/audit schema.
Keep the AWS connection file on AWS; `push` never uploads a connection file.
Use an existing verified SSH alias and host key. No SSH key contents are needed
in this repository. Take a destination backup before the first adoption/update.

## Export on the desktop

Use the integer canonical `meets.id`, not the live website identifier. Repeat
`--meet-id` to include every newly imported or corrected competition:

```bash
python3 scripts/meet_delivery.py export \
  --config .secrets/localserver.json \
  --expect-host 10.88.30.124 --expect-database swimrankings \
  --publisher desktop-canonical --meet-id 123 --meet-id 124 \
  --directory data/export/desktop-canonical
```

The actual host/name must equal the explicit expected values. Export uses a
consistent read-only database snapshot. Unchanged meets produce no new file;
changes create the next numbered revision linked to the previous SHA-256.
Keep the package directory as the publisher history and back it up. Do not reset
it to revision 1, edit immutable files, or reuse the publisher after source IDs
have been rebuilt/reassigned. History gaps/conflicts stop export.

## Preview and apply on a destination

First verify the destination database and preview a package:

```bash
python3 scripts/meet_delivery.py apply \
  --config /srv/private/swimrankings.json \
  --expect-host localhost --expect-database swimrankings \
  --package /srv/incoming/competition.json.gz
```

Without `--commit`, validation and database operations run in a transaction that
is rolled back, including receipt creation. PostgreSQL sequences can advance
during a preview. A successful preview reports result/split/deletion counts.
For an existing meet not previously managed by this publisher, add
`--adopt-existing` to the preview, inspect the report, then repeat with `--commit`
only after verifying that the desktop snapshot is authoritative. Adoption tries
to preserve existing result IDs; ambiguous identities and alias conflicts stop it.

## Push missing revisions from the desktop

```bash
python3 scripts/meet_delivery.py push \
  --directory data/export/desktop-canonical \
  --ssh-host aws-swimming \
  --remote-dir /srv/incoming/swimrankings \
  --remote-config /srv/private/swimrankings.json \
  --expect-host localhost --expect-database swimrankings
```

This prints a local plan without network activity. Add `--commit` to upload and
apply. The tool installs its content-addressed Python receiver, checks destination
receipts, skips received revisions, uploads to `.part`, then renames and applies.
The receiver configuration path is supplied explicitly and is not uploaded.
An existing untracked meet stops the transfer until explicitly adopted as above.

Each competition is atomic; the whole batch is **not** one transaction. If a
connection fails, rerun the same push: receipts determine what actually committed.
Previously committed competitions remain applied. The command exits nonzero on
failure. Use `status` with the same connection arguments to inspect receipts.

## Corrections, consistency and recovery

- Corrections update mapped results while retaining destination IDs. Removed
  results/splits are deleted only within the delivered meet. An empty complete
  snapshot removes that meet's results, but retains the meet itself.
- Countries, clubs and athlete metadata are shared canonical dependencies and
  are updated from the source. No automatic athlete identity merge occurs.
- Checksums detect corruption, not authenticity. SSH and trusted publisher files
  establish the transport trust boundary.
- Revision gaps, conflicting checksums, another publisher owning a meet,
  duplicated meet identities, and destination edits outside delivery are rejected.
- A transaction locks the canonical meet/result/split tables against concurrent
  writes. Reads remain available. Lock timeout is 10 seconds; statement timeout
  is 10 minutes. Run alongside quiescent importers and retry lock failures.
- A failed competition rolls back its data and receipt. Revert a committed
  mistake by correcting the desktop and exporting a new revision, or restore a
  verified backup. Do not edit receipts or replay an older revision as rollback.

## Derived summaries and website refresh are separate

Successful raw-data delivery records `needs_summary_refresh=true`. It is not a
claim that website caches or comparison summaries are refreshed. The existing
`rebuild_points_summary.py` globally rebuilds tables and derives seasons from
meet start dates. Do not automatically run it for this delivery: boundary-spanning
meets require session-date handling and consumers need coordinated refresh.

Before publishing the new data to websites, implement/verify the summary refresh
for affected seasons, then refresh **active** application caches. Preserve closed
archive rows. This transport intentionally has no command to clear the pending
flag without such verified work. AWS deployment/first real upload remains a
separate run with its actual endpoint, schema, backup and refresh path verified.
Tracked in [issue #2](https://github.com/aboimpinto/SwimRankingsETL/issues/2).

## Tests

```bash
DELIVERY_TEST_CONFIG=/private/delivery-test.json \
  python3 -m unittest discover -s tests -p test_meet_delivery.py -v
```

Integration tests refuse hosts other than localhost/127.0.0.1 and databases whose
name does not start with `swimrankings_delivery_test`. They reset only the isolated
test schema. CI runs the same contract against PostgreSQL 16. Transport tests mock
SSH; the real AWS transport has not yet been exercised.
