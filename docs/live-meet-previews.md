# Preview a multi-day meet before importing

Use this on the desktop from the ETL checkout. It is a **database-free preview**:
no credentials, SQL connection, race import, AWS delivery or website publication.
It reuses the existing live-meet LENEX parser, but does not call its importer.
Python 3.10+ on Linux is sufficient; no pip dependencies are needed.

## Saved preview workspace

```bash
python3 scripts/preview_live_meet.py \
  --live-id 10928 --start 2026-09-26 --end 2026-09-27

# Revisit every saved meet, even if earlier previews already contained results.
python3 scripts/preview_live_meet.py --recheck

# Explicit offline inspection (never automatically reused by --recheck).
python3 scripts/preview_live_meet.py \
  --live-id 10928 --start 2026-09-26 --end 2026-09-27 \
  --lxf-file /path/to/results.lxf
```

The default workspace is `reports/live-previews/`, relative to the current
working directory. Use `--output /path/to/private/previews` to keep it elsewhere.
The reports folder is ignored by Git. Each live ID has:

- `latest.md`: readable summary of readiness, missing days and source changes.
- `latest.json` and `reports/*.json`: latest and historical reports, with source
  URL, UTC check time, SHA-256, fallback errors, event/day counts and deltas.
- `watch.json`: persistent live ID and scheduled dates used by `--recheck`.
- `baseline.json`: last accepted nonempty preview, **not an import receipt**.
- `<sha256>.lxf`: private source evidence for successfully parsed downloads.

New workspace directories are private (0700); saved reports and raw files are
0600. Do not put them in a public web directory or commit swimmer records.
Concurrent checks for the same meet are serialized with a local file lock.

Every online run makes a fresh request. It tries the live `results.lxf` endpoint,
then the calendar fallback if unavailable. Authentication and rate-limit errors
(401/403/429) stop the attempt; it does not bypass them. Existing files are used
only when explicitly supplied with `--lxf-file`.

## Reading a preview

| Status | Meaning | Action |
| --- | --- | --- |
| `waiting_for_results` | Valid schedule, zero RESULT elements | Hold; check again later |
| `new_results_observed` | First usable nonempty snapshot | Review a partial-import plan |
| `changed_results_observed` | Added results or changed performances/metadata | Review a new revision |
| `unchanged` | Same source results as last accepted preview | Keep watching for later publication |
| `held_for_review` | Removed results, ambiguous keys or missing dates | Preserve baseline; investigate |
| `unavailable` | Download/parser failure or different meet/schedule | Preserve baseline; retry/review |

`candidate_for_import_review` means the preview found usable source records; it
is **not permission or proof of safe import**. All results are counted without
an age filter. These are raw LENEX RESULT elements; relay expansion and canonical
normalization can yield different database row counts. Deltas compare saved
source observations, not localServer or AWS database contents. Source IDs that
are renumbered may appear as removals/additions and are conservatively held.

Scheduled days/events without results remain visible, even when only the first
day is present in the file. A day with one result is not necessarily finished.
An event without results may also be cancelled or have no finishers. Once the
end date passes, the status is `ended_unverified`, never automatically complete.
Every watched meet remains eligible for recheck, including meets with both days
represented, so late corrections can still be found. There is no scheduler:
run `--recheck` on the next manual import cycle. To stop watching a meet after
manual verification, move its `watch.json` outside this workspace; preserve its
reports and baseline as evidence.

Exit code 0 means the preview was produced, **including a held/empty source**;
inspect `import_readiness`. Exit code 1 means at least one source was unavailable.
Invalid command arguments return 2. Never use exit code 0 to trigger an import.

## What remains before importing partial meets

The existing monthly writer is unchanged: it prefers cached downloads and skips
meets with existing result rows. It cannot currently be relied upon to resume a
partial meet. Do not work around that by deleting rows or import receipts.

Before enabling actual day-one/day-two imports, separately verify a reconciliation
path that fetches the latest complete available snapshot, preserves source
identity mappings, applies additions/corrections transactionally and prevents
accidental deletion from truncated files. Test repeated day-one imports, day-two
additions, corrections, splits and relay results against a disposable fixture
schema in the existing database infrastructure. Preview result fingerprints are
not database primary keys and must not be used as such.

The subsequent chain remains desktop → localServer canonical database → AWS
canonical database → consumer refresh. SwimProfiles detects changed source meet
fingerprints when it imports from AWS; it cannot obtain day two if the upstream
ETL skipped it. This command neither changes that publication chain nor runs it.

## 47. Meilemer Meeting observation

Checked on **26 September 2026 at 20:01 UTC**:

- [Organizer schedule](https://scmeilen.clubdesk.com/club/anlaesse/meilemer_meeting):
  26–27 September in Meilen.
- [Live meet 10928](https://live.swimrankings.net/10928/) listed day-one result PDF
  links. The PDF contents were not imported or used to reconstruct race data.
- The direct live `results.lxf` returned HTTP 404.
- The calendar fallback returned a valid LENEX schedule with both dates and
  26 scheduled event elements, **zero athletes and zero RESULT elements**.
- Read-only AWS checks found the previous 46th meeting, but no 47th meeting in
  either canonical SwimRankings or SwimProfiles data.

Thus the currently available LENEX export is **not ready for a race import**.
The private preview workspace retains the source file and reports and watches
both scheduled days. A later check can discover a populated export without
mistaking today's empty file for completed results. No race data was imported.

## Verification

```bash
python3 -m unittest discover -s tests -p test_live_meet_preview.py -v
```

Synthetic fixtures exercise day one, unchanged recheck, day-two additions,
corrections, regressions, empty exports, download failures, invalid schedules,
ambiguous keys, ZIP parsing and authentication/rate-limit behavior. The offline
CLI test runs with Python site packages disabled to prove no database driver is
required. Live source evidence stays in the ignored private reports workspace.
