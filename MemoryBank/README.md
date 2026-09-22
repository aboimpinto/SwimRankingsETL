# MemoryBank

This folder captures durable context for `SwimRankingsETL`.

Start with the [project overview](../README.md) and [desktop-to-AWS delivery runbook](../docs/desktop-incremental-delivery.md). They describe localServer imports, incremental AWS delivery and required refresh acknowledgements from SophiaWalker, Colin and LimmatSharks. Older individual notes may describe earlier repository snapshots.

Important repo boundary:
- Most historical scripts start from already-downloaded files stored under paths such as `/workspace/data/lenex` and `/workspace/data/processed`.
- The newer `import_live_swimrankings_meet.py` and `import_live_swimrankings_month.py` scripts can download public LENEX result files from SwimRankings live endpoints before importing them.

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
