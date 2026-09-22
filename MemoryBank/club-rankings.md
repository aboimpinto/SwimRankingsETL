# Full Sharks rankings and performance provenance

Companion changes: LimmatSharks issue 32 and SwimRankingsETL issue 9.

`club_rankings.py` collects the complete **all-time Open and exact-age** individual lists for
club 65634: both genders and both courses, all published individual events.
The site's Excel exports stop at 50 swimmers per event and cannot establish
lower ranks. Each HTML list is paginated in 25-row windows. The last window
can overlap the preceding one: verify identical overlap and count each athlete
once. Manual-timing annotations and split markers remain explicit.

These are one-best-per-athlete lists, not every historical swim by an athlete.
Keep source pages and versioned packages to preserve every published performance
and later revisions. Meet imports remain the source of full race histories.
Coverage separates missing downloads from events not published in a validated
category catalog. Never claim a partial package complete. Source categories are
Open, 11-and-under and exact ages 12–18, evaluated in the performance year.
Filtering Open personal bests cannot reconstruct these separate age lists.

## Collection and publication

Install `requirements-delivery.txt` and Playwright in the desktop environment.
Use the same normal Chromium loopback debugging session as documented in
`club-record-baselines.md`. Sign in if the source reports a page-view limit.
Collection stops on that response. Resume only after source access is restored;
a sign-in alone may not resolve a quota or account-entitlement denial. Do not work around access limits or export browser cookies.

```bash
# Defaults to all 36 course/gender/age combinations.
python3 scripts/club_rankings.py collect --output data/export/club-rankings-YYYY-MM-DD
# Prioritise an exact-age category; previously saved categories are preserved.
python3 scripts/club_rankings.py collect --output data/export/club-rankings-YYYY-MM-DD --age-group 15_15
python3 scripts/club_rankings.py apply \
  --package data/export/club-rankings-YYYY-MM-DD/rankings.json \
  --db-config .secrets/localserver.json
# Repeat with --commit after successful validation and dry run.
```

Apply the same package with AWS's existing private writer configuration after
PR/CI. It adds `club_ranking_populations` (current per-event source) and
`club_ranking_imports` (immutable package history). No full database replacement.
Version 2 uses `requested_age_groups`, validated catalog provenance and separate
age population keys (`200:BREAST:SCM:M:15_15`). Open keeps its original key and
version 1 packages remain valid and idempotent. Missing and unpublished events
have distinct coverage entries; unrequested/mixed-age data is rejected.
The receiver verifies page totals, stable athlete identities, exact times,
competition ties, provenance and package hash; stale/truncated/slower revisions
require source correction review. Grant the website source reader SELECT on
these tables and the club-record baseline tables. Source `Last built` and
collection timestamps are distinct; an export downloaded today may contain an
older source ranking.

## New competitions

`import_live_swimrankings_meet.py` and the monthly meet importer retain per-performance `club_name` from
the LENEX athlete's parent club and `club_source`, the source file SHA-256.
Individual result dates use their session date, including meets spanning New
Year when the age category changes. The monthly importer also retains result
status so a disqualified swim cannot become a club-record candidate. Existing raw-file tracking
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

The existing protected website refresh invalidates its club-data cache at
start and completion. The
current club comparison is separate from frozen season CH/SR snapshots. New
club performances join the baseline population; saved record achievements and
source-package history remain available when later performances improve them.

## Current source-access limitation

58 Open event populations / 14,502 performances have been saved and imported
locally. The remaining Open lists and full age-group lists are not published to
AWS. On 22 September the operator confirmed ordinary navigation to the age-15
category also returned an access denial (reference `2026-09-22/13-03-45-000`).
Collection is stopped; retain the saved files and resume once access is restored.
Do not use the complete **record-holder** baseline as a complete **ranking** list.
