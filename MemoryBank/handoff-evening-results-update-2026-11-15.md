# Evening weekend-results update, 15 November 2026

## Request and scope

Refresh the Swiss short-course championship and other available weekend meets, locally and on AWS; measure the complete path through publication and verify both swimmer and club pages. This is a one-shot operator run, not a scheduled importer. The end-to-end clock started at 17:57:52 UTC (18:57:52 CET).

Private evidence, retained source files, reviewed identity decisions, receipts and executable operational drivers are in `reports/evening-update-2026-11-15/` in the canonical ETL checkout. Do not copy source PDF/LXF files to AWS. AWS receives normalized immutable packages only.

## Canonical results

48 overlapping weekend live-index meets were examined. 32 supplied populated LENEX exports. Bounded PDF observations also ran; no additional PDF-only meet passed the acceptance gates in this run. This is not complete coverage of every published PDF. All 14 changed, accepted meets used LENEX, including official/enriched data; this workload must not be presented as a small live-PDF-delta benchmark.

Accepted changes: 11,846 new performances, 3,083 updated/enriched performances, and 1,786 provenance-only updates. Local canonical mutation time summed to 67.733 seconds. Points preparation/export took another 6.482 seconds; package/evidence preparation 4.698 seconds; unchanged local replay 13.516 seconds. These are stage timings, not end-to-end duration. AWS delivery took 109.598 seconds and independent revision/hash/count verification passed for all 14 meets.

Swiss Nationals source: 2,837 rows, 2,825 accepted canonical results. Allschwil source: 3,331 rows, 3,314 accepted. Colin now has five Nationals races, including 200 m medley on 15 November in 2:09.81. Sophia has seven accepted Allschwil races, with no additional Sunday race in this collected snapshot.

Limmat Sharks: Allschwil has 19 individual results including Sophia's seven. Nationals has 270 individual records (257 starts and 13 non-starts) and eight relay team performances; the complete overlay totals 278. Do not confuse the 32 athlete relay records with eight team performances.

## Safety decisions and retained limitations

Four nationality/alias conflicts were resolved against exact prior accepted race evidence and name/year/gender. The reviewed decisions are source-hash scoped and do not rewrite a conflicting alias. Three entire meets (10748, 10877, 11106) remain held by duplicate-source guards. Finswimming meet 11601 remains excluded as an unsupported discipline. Other row-level ambiguity holds remain; do not describe all source rows as imported.

Belgian meet 11666 omitted four previously accepted Julie Lamaire results. Events 1, 9, 11 and 15 on 14 November (TIM) were withheld from the new snapshot, retaining prior canonical results. Its mixed source revisions also mean the new file cannot certify whole-meet competition totals. Individual results remain publishable; aggregate LENEX evidence was withheld. The first local publication correctly rejected the mismatched aggregate evidence and rolled back; it was retried with 13 compatible evidence records. No validation or SQL timeout was disabled.

PDF collector setup attempts failed on explicit budget/cohort limits and then a missing multiprocessing main guard. Their logs were retained; they made no database changes. Those operator/setup delays belong to the end-to-end measurement. The ad hoc operational wrappers are evidence, not a certified unattended five-minute pipeline.

## Local completion

SwimProfiles publication 67 completed at 18:20:21.976 UTC: 195.579 seconds inside the importer, 198.554 seconds including monitoring. 13 changed meets transferred 16,277 results; the remaining selected meet was already unchanged. The independent verifier checked all 16,805 selected results, 35,702 splits and 5,939 reaction times, 3,545 athletes, 24 ranking groups and 40 sampled affected-profile requests with zero differences. Club verification covered 15,346 resolved attributions across 224 stored club/meet pairs, sampled eight public pairs, and reported 1,459 unresolved club strings explicitly.

Both Limmat competition cards and all three overlay views passed browser checks; full pagination was checked for duplicate performance keys and Sophia/Colin's exact times. Shared source summary preparation took 148.772 seconds. Companion refreshes: Sophia 8.474 seconds, Colin 167.231 seconds, Sharks 116.660 seconds. Four-application data audit and selected owner-content/frozen-archive preservation checks passed. Browser checks for Sophia, Colin and Sharks passed as well.

The first targeted overlay check incorrectly expected only 270 individual records; source relay evidence established the additional eight team performances. The corrected 278-performance check passed. The independent all-facts verifier passed unchanged.

## AWS completion

The first 14-meet AWS SwimProfiles publication hit the existing 1,080-second job limit (exit 124) and rolled back. Canonical imported results remain committed. The last visible SwimProfiles publication remained 66, and no import session/container remained active. Its 651 sampled requests all returned HTTP 200, but two page requests exceeded two seconds (2,097/2,188 ms); targeted rechecks passed in 171–315 ms. Logs and failed attempt timings are retained.

Recovery committed as three batches: Swiss Nationals + Allschwil (6,139 source records), six other meets (5,372), and six other meets (5,294). Each publication retains the existing 18-minute limit, requires a fresh reader baseline, and is followed by independent fact/ranking/club verification. The committed publications are 69, 71 and 73 respectively, with importer times of 930.339, 831.378 and 647.171 seconds. All three passed independent per-batch fact/ranking/club verification. Their monitoring windows sampled 561, 504 and 414 requests; each window retained latency violations (maxima 5,667, 2,072 and 2,541 ms). Targeted and fresh random readiness rechecks passed before continuing. This is not a successful two-second availability certification.

AWS companion publication is still running under `swim-evening-aws-after04-20261115.service`; driver `reports/evening-update-2026-11-15/aws-after-04.py`. It proceeds through shared summaries, Sophia, Colin and Sharks, then preservation and application-data checks. Final combined/browser verification remains pending. Do not interpret source delivery or the per-batch receipts as final four-site completion.

## Performance observations and next work

One baseline AWS page request (`/swimmers/lena-stevcic-lukic`) returned HTTP 200 in 2,522 ms, before the SwimProfiles writer began. Three targeted rechecks returned HTTP 200 in 206/284/213 ms. Preserve this latency violation even if later checks pass. Maintenance query observations are in `query-observations.jsonl`; these do not prove the slow page was caused by a specific SQL statement.

AWS best-summary refresh took 298.218 seconds versus 9.443 seconds locally; the first eight observed ranking partitions each required approximately 27–32 seconds on AWS. Investigate these measured stages and the full companion-site rebuilds before treating this as an unattended NRT cycle. Public request timeouts remain unchanged.

The implementation used the reviewed `fix/pdf-race-club-attribution` worktree (head a88015f; PR50 stacked on PR48 and PR43), not canonical main's older PDF importer. See the preceding `handoff-pdf-club-attribution-2026-11-15.md` for integration status. No feature worktree was removed or merged during this operational update.

## Owner-directed architectural follow-up

Tracked in https://github.com/aboimpinto/SwimProfiles/issues/305 (created during this run). The owner explicitly requires fair treatment of every competition/country; Swiss Nationals and Allschwil are test examples only. Existing summaries/rankings across athlete, club, country, Europe, dataset and age groups are the normal calculation inputs. For every large-table scan, ask what fact is needed and whether it can already be read or incrementally maintained in a summary. Full scans belong to explicit rebuild/audit operations, not silent normal-import fallback. Stored procedures may implement bounded operations; increasing partition count or timeouts is not the solution.

Wiring plan: accepted canonical change + durable change record in one transaction; per-consumer revision acknowledgments; fair work queue; old/new contribution updates to existing summaries; bounded atomic work/checkpoint commits; coherent publication and dependent cache refresh; deterministic sampled swimmer/club checks. Preserve partial-source semantics, ties, source identities, late results, historical race-date rankings, corrections and withdrawals. Inventory current summaries and benchmark before adding new storage. Stage/version only computations that cannot fit safely in a bounded atomic delta update. Do not claim the architectural fix is implemented or released: #305 contains the delivery phases and acceptance evidence.


## Local summary-delta experiment

Owner requested a local test before deploying architectural changes. Draft SwimProfiles PR https://github.com/aboimpinto/SwimProfiles/pull/306 (branch `perf/305-summary-delta-local`, commit `01c4bd5`) contains migration 033, importer baseline capture, correctness tests and repeatable benchmarks. The active unmerged worktree is `SwimProfiles-worktrees/summary-delta-local` under the consulting workspace; do not delete it as completed work. Its aggregate report is `docs/summary-delta-local-experiment.md`. The canonical SwimProfiles code and shared database functions were not persistently changed by this experiment.

On the populated local PostgreSQL 16.14 database, 343 ranking-group population/prefix refreshes measured 50.57 to 4.39 ms for a time correction, 43.60 to 23.86 ms for withdrawal, and 57.63 to 30.89 ms for a group move. This is a mixed/warm component probe, with exact restoration after rollback, not a full-import or AWS speed claim. The actual inner delta plan uses temporary delta tables and indexed ranking-group rows; no raw-result/membership/bucket read occurs in that population statement.

The complete local importer was also tested with a fixed 140-result live competition and twenty-result deltas while total history grew from 3,250 to 52,000 rows. Five scenarios (faster, slower, correction, withdrawal, unchanged replay) passed independent full-history correctness checks in both variants at three sizes. At 52,000 rows full import stayed approximately 1.68 versus 1.66 seconds: the wider speed/scale goal is NOT achieved. Global club attribution staging and competition summaries remain. A source change journal/per-meet revision signal is needed: current tests explicitly require detection of club-attribution corrections outside the selected meet.

140 unit tests, 105 integration tests, typecheck, formatting and production build passed. Legacy BDD: 83/89 passed, with six explicitly documented configuration/real-data expectation/step-budget failures, including a club step reproduced against unchanged main. New population coverage is in deployment-only LongRunning CI. PR306 is a draft; #228's AWS/rollout evidence and #305's bounded/resumable publication remain outstanding. No experimental migration, merge or deployment was made on AWS.
