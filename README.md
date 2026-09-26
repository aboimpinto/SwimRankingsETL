# SwimRankingsETL

Python tools for collecting swimming results on the desktop, importing them into
PostgreSQL on **localServer**, and delivering incremental competition updates to
AWS for **SophiaWalker, Colin and LimmatSharks**.

## Complete production workflow

```text
Desktop: SwimRankings downloads / saved LENEX files
    ↓ Python import and validation
localServer: canonical SwimRankings PostgreSQL database
    ↓ export competition revisions and push over SSH
AWS: canonical SwimRankings PostgreSQL database
    ↓ rebuild summaries and publish the batch
    ├─ SophiaWalker application database and ranking caches
    ├─ Colin application database and ranking caches
    └─ LimmatSharks application database and ranking caches
```

1. **Download and import on the desktop.** Keep browser authentication, cookies
   and interactive login there. The ETL writes canonical meets, swimmers, results
   and splits to localServer. Validate imports before exporting a competition.
2. **Export and deliver revisions.** `scripts/meet_delivery.py` transfers new or
   corrected competition snapshots to AWS. It maps canonical identities and
   applies each competition transactionally; unchanged revisions are skipped.
   This does not replace an entire database or transfer a website's local roster.
3. **Publish on AWS.** Run the delivery command with **`--publish-config`** and
   `--commit` after reviewing its plan. The publisher rebuilds shared summaries
   and calls each site's protected `POST /api/integrations/swimrankings/refresh`.
4. **Verify all three receipts.** Each application imports/reconciles its own data
   and prepares current/career rankings and caches. A batch is complete only when
   SophiaWalker, Colin and LimmatSharks have all acknowledged it. Failed or busy
   consumers remain retryable; rerunning skips completed revisions/consumers.

**Uploading raw data alone is not completion.** Omitting `--publish-config`
performs raw delivery without the three website refreshes. AWS consumes the
exported data and does not need a SwimRankings browser session.

## Ranking and season behavior

Every published batch refreshes all three consumers, **even when none of their
athletes competed**. New competitors' times can change Swiss (CH) and
SwimRankings (SR) positions, so current/career comparison populations must be
rebuilt independently of own-athlete participation.

LimmatSharks incorporates all eligible imported club performances, including
swimmers without website profiles, into its shared rankings. Race history is
retained; leaderboards show one best per swimmer, with tied positions and a
separate selected slower swim when appropriate. Repeated imports/refreshes do
not add duplicate leaderboard swimmers. Competitor-only meets can change CH/SR
positions while leaving Sharks positions and own PBs unchanged.

The Sharks profile Age Group filter uses the selected view's comparison year,
matching CH/SR, even for older PBs. Historical club-record eligibility still uses
age at the swim. Source export categories retain their original definitions.

Race session dates determine seasons. Closed application archives remain
immutable; importing an older meet does not reopen a season. Indexing prepares
the current website views before publication. Sharks profile reads use a durable
PostgreSQL cache; browser requests do not rebuild rankings.

## Operational documentation

- [Multi-day live meet previews](docs/live-meet-previews.md): database-free dry runs, saved reports and fresh rechecks before importing partial meets.

- [Desktop import, incremental delivery and all three website refreshes](docs/desktop-incremental-delivery.md): setup, export/push commands, private configuration, receipts, retries and recovery.
- [Importing data for SophiaWalker](docs/import-to-sophia-website-db.md): local import context; use the delivery runbook above for production distribution.
- [Additive Sharks meet performances](docs/club-meet-performances.md): recover saved LENEX evidence and preserve the club performance log.
- [Club ranking collection](MemoryBank/club-rankings.md) and [record baselines](MemoryBank/club-record-baselines.md): desktop collection and retained historical evidence.
- [Project brief](MemoryBank/projectbrief.md) and [MemoryBank index](MemoryBank/README.md).

Connection files, tokens, browser sessions and local exports belong outside Git.
Use the explicit host/database checks and private configuration described in the
runbook. Keep the export revision history: it is required for safe incremental
updates and retries. A publishing push installs a content-addressed receiver
bundle from the desktop code version, so use the reviewed current version.

## Validation

Install delivery dependencies with `python3 -m pip install -r requirements-delivery.txt`.
The [Meet delivery workflow](.github/workflows/meet-delivery.yml) tests package
validation, PostgreSQL transactions, summaries, consumer acknowledgements and
retry behavior against an isolated PostgreSQL database. Local database tests
require the guarded test configuration documented in the delivery runbook.
Website repositories test their refresh endpoints, ranking rules, cache
publication and archive preservation separately.
