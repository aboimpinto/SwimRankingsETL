# MemoryBank

This folder captures durable context for `SwimRankingsETL`.

These notes are based on the repository contents inspected on 2026-04-12. They document the ETL/import side of the project that reads LENEX/XML meet files, transforms them into canonical data, and imports them into PostgreSQL.

Important repo boundary:
- Most historical scripts start from already-downloaded files stored under paths such as `/workspace/data/lenex` and `/workspace/data/processed`.
- The newer `import_live_swimrankings_meet.py` and `import_live_swimrankings_month.py` scripts can download public LENEX result files from SwimRankings live endpoints before importing them.

Files in this folder:
- `projectbrief.md`: high-level project description and scope.
- `productContext.md`: why the project exists and what it needs to achieve.
- `systemPatterns.md`: the main ETL flow and recurring implementation patterns.
- `techContext.md`: runtime, dependencies, paths, environment variables, and database touchpoints.
- `scriptInventory.md`: grouped overview of the Python scripts currently in the repo.
- `activeContext.md`: current repository state, risks, and observed gaps.
- `progress.md`: what is already understood and the most useful next steps.
