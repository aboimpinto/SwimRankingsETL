# Full Sharks rankings and performance provenance

Companion changes: LimmatSharks issue 32 and SwimRankingsETL issue 9.

`club_rankings.py` collects the complete **all-time Open** individual lists for
club 65634: both genders and both courses, all published individual events.
The site's Excel exports stop at 50 swimmers per event and cannot establish
lower ranks. Each HTML list is paginated in 25-row windows. The last window
can overlap the preceding one: verify identical overlap and count each athlete
once. Manual-timing annotations and split markers remain explicit.

These are one-best-per-athlete lists, not every historical swim by an athlete.
Keep source pages and versioned packages to preserve every published performance
and later revisions. Meet imports remain the source of full race histories.
Coverage lists any absent standard event; never claim a partial package complete.

## Collection and publication

Install `requirements-delivery.txt` and Playwright in the desktop environment.
Use the same normal Chromium loopback debugging session as documented in
`club-record-baselines.md`. Sign in if the source reports a page-view limit.
Collection stops on that response and resumes its validated local pages after
operator sign-in. Do not work around access limits or export browser cookies.

```bash
python3 scripts/club_rankings.py collect --output data/export/club-rankings-YYYY-MM-DD
python3 scripts/club_rankings.py apply \
  --package data/export/club-rankings-YYYY-MM-DD/rankings.json \
  --db-config .secrets/localserver.json
# Repeat with --commit after successful validation and dry run.
```

Apply the same package with AWS's existing private writer configuration after
PR/CI. It adds `club_ranking_populations` (current per-event source) and
`club_ranking_imports` (immutable package history). No full database replacement.
The receiver verifies page totals, stable athlete identities, exact times,
competition ties, provenance and package hash; stale/truncated/slower revisions
require source correction review. Grant the website source reader SELECT on
these tables and the club-record baseline tables. Source `Last built` and
collection timestamps are distinct; an export downloaded today may contain an
older source ranking.

## New competitions

`import_live_swimrankings_meet.py` now retains per-performance `club_name` from
the LENEX athlete's parent club and `club_source`, the source file SHA-256.
Individual result dates use their session date. Existing raw-file tracking
retains its original hash algorithm. Relay rows do not inherit an individual
athlete's club evidence.

`meet_delivery.py` carries this optional evidence to AWS. Existing v1 packets
remain valid and retain their hashes. A later replacement without proof clears
old proof instead of associating it with potentially changed results. The
website only accepts this per-performance proof for new club ranking/record
candidates; it does not infer historical eligibility from `swimmers.club_id`.

Legacy importers and old results lack this evidence. Re-import their original
LENEX files through the updated importer when club-at-swim evidence is needed;
do not backfill it from today's club. Imported official club ranking/record rows
provide independent evidence for exact matching historical performances.

The existing protected website refresh invalidates its club-data cache. The
current club comparison is separate from frozen season CH/SR snapshots. New
club performances join the baseline population; saved record achievements and
source-package history remain available when later performances improve them.
