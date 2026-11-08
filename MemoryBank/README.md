# MemoryBank

Latest owner gate and expansion evidence: [8 November bounded expansion](../docs/nrt-expansion-2026-11-08.md). Under 60 s ideal, 60–180 s acceptable; stop expansion and request direction above 180 s.

This folder captures durable context for `SwimRankingsETL`.

Latest checkpoint: [full-cohort small-delta trial](../docs/nrt-delta-cohort-2026-11-08.md).
Four new results published local 51 / AWS 46 with passing checks. Processing took
209.675 seconds plus a separate 39.794-second manual handoff; expansion stopped
and direction was requested. All-source parsing/capacity remains unproven.

Start with the [project overview](../README.md) and [desktop-to-AWS delivery runbook](../docs/desktop-incremental-delivery.md). They describe localServer imports, incremental AWS delivery and required refresh acknowledgements from SophiaWalker, Colin and LimmatSharks. Older individual notes may describe earlier repository snapshots.

Important repo boundary:
- Most historical scripts start from already-downloaded files stored under paths such as `/workspace/data/lenex` and `/workspace/data/processed`.
- The newer `import_live_swimrankings_meet.py` and `import_live_swimrankings_month.py` scripts can download public LENEX result files from SwimRankings live endpoints before importing them.

Official national/age-group records now have a separate [refresh/delivery runbook](../docs/country-records.md). These are distinct from meet and club-record snapshots. Read its verified coverage before claiming country completeness.

Files in this folder:
- `club-rankings.md`: complete all-time Open rankings, pagination and per-performance club evidence.
- `club-record-baselines.md`: desktop collection, validation and incremental publication of official club-record baselines.
- `projectbrief.md`: high-level project description and scope.
- `productContext.md`: why the project exists and what it needs to achieve.
- `systemPatterns.md`: the main ETL flow and recurring implementation patterns.
- `techContext.md`: runtime, dependencies, paths, environment variables, and database touchpoints.
- `scriptInventory.md`: grouped overview of the Python scripts currently in the repo.
- `activeContext.md`: current repository state, risks, and observed gaps.
- `progress.md`: what is already understood and the most useful next steps.

## 2026-09-28 — continental record fallback and country discovery

Owner permits missing national lists: disable that comparison while retaining
applicable continental and World records. The 54 supplied country URLs are
ranking navigation seeds; do not infer official national records from them.
World Aquatics' public records feed supplies verified Americas/Africa/Asia/Oceania
records, with no manufactured splits. Europe/World retain their LENEX sources.
Read the country-records runbook for source mapping, preview evidence and actual
local/AWS publication state. No scheduler is to be configured.

For each weekly records refresh, follow the [manual operator checklist](../docs/weekly-record-refresh.md). It documents the installed entry points, preview review, matching local/AWS delivery, receipt verification and retries; scheduling remains disabled.

## Near-real-time implementation — 8 November 2026

Start with the [program](../docs/near-real-time-results-program.md),
[manual batch commands](../docs/nrt-manual-batches.md) and
[milestone evidence](../docs/nrt-implementation-milestone-1.md).
The collector, recoverable batch runner and SwimProfiles adapters are implemented
on `feat/nrt-manual-batch`. The initial local trial accepted 77 new results at
generation 46 and initially deferred AWS delivery. That historical deferral was
subsequently reconciled; use the latest checkpoint above for current receipts.
No unattended runner/container is installed. Historical context files below may
predate the repository's tests and documented runtime.
