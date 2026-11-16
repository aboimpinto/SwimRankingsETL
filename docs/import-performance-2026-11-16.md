# Local source import optimization — 16 November 2026

Tracking: issues [51](https://github.com/aboimpinto/SwimRankingsETL/issues/51)
and [52](https://github.com/aboimpinto/SwimRankingsETL/issues/52), alongside
[SwimProfiles 305](https://github.com/aboimpinto/SwimProfiles/issues/305).

## Scope and implementation

These experiments use disposable local PostgreSQL schemas. Shared source and
application data are untouched; AWS imports and deployment remain stopped.
The implementation is stacked on `fix/pdf-race-club-attribution` / PR 50;
that branch itself depends on the pending PDF-layout and NRT work. Preserve
those prerequisites when integrating. Implemented and tested does not mean released.

- `5aa73cc`: insert splits in batches of at most 100 **within each race** using
  `execute_values`. Skip split deletion only when inserting a new result ID.
  Existing results still replace their splits; provenance-only updates preserve
  them. No competition-sized split buffer or source schema change.
- `9832741`: build one lookup of prior PDF identities for official incoming rows.
  The key preserves the existing normalized name, birth year, gender, event
  number/date/round contract; its value is the set of prior race keys. Any
  different key still causes `lenex_identity_needs_review`, even when another key
  matches. Pure PDF imports do not build this unused lookup.
- The transaction lock, reviewed plan hash and locked revalidation remain.
  Eliminating the second plan would weaken the existing stale-preview protection.

The old identity guard visited every ledger entry for every official row. An
unchanged 2,833-result replay made 16,057,444 generator visits across the two
plans, even with no PDF entries. The replacement builds in O(ledger rows) and
uses expected O(1) dictionary/set lookups per incoming row. It does not claim
that all other planner work is bounded: swimmer/alias reads remain global.

## Fixture correction before comparison

The historical `delivery_schema.sql` test fixture omitted the existing
`splits_result_order_idx`. The normal delivery schema already creates it, and a
read-only check confirmed it on the documented localServer. This is **not a new
production index or an optimization delivered by this branch**.

The replay now includes that index by default. `REPLAY_SOURCE_INDEXES=0` can
reproduce older experiments. An earlier 1.734-second split-delete observation
was from the unindexed fixture; with the index it was about 0.167 seconds.
Earlier SwimProfiles paired application comparisons still share identical
sources, but their complete stage totals must retain this qualification.

## Diagnostic evidence

Saved complete Swiss LXF: 2,833 accepted results, 17,134 splits. Four rows with
ambiguous race keys remain quarantined, and 27 parser exclusions remain excluded.
Both variants use identical controlled earlier history (same swims 5% slower);
this is not a full production history. Local PostgreSQL 16.14, Intel i7-14700F,
28 logical CPUs, approximately 92 GiB RAM; warm/mixed caches, sequential jobs.

| Profiled source stage | Indexed original | Split batches only | Batches + identity lookup |
| --- | ---: | ---: | ---: |
| New final: apply, including locked replan | 2,735 ms | 2,180 ms | 2,121 ms |
| Final after 93 PDF results: initial plan | 841 ms | 846 ms | 128 ms |
| Final after 93 PDF results: apply | 3,276 ms | 2,720 ms | 2,049 ms |
| Unchanged final: initial plan | 1,247–1,275 ms | 1,229–1,248 ms | 319 ms |
| Unchanged final: apply/revalidation | 1,239–1,269 ms | 1,240–1,247 ms | 320 ms |

Split INSERT calls fell from 17,134 to 2,697 (races with splits in this file),
with measured query time falling from about 921 ms to 367 ms in the isolated
batching probe. New results made no split DELETE calls. Result and receipt
writes are still per race. These are profiled diagnostic samples, **not clean
throughput claims**; process startup, parsing and SwimProfiles publication are
separate. The identity change's full-file run retained the same final facts and
ordered splits on both acquisition paths.

## Clean before/after measurement

Two sequential non-profiled replays used the same eight saved PDF documents,
including simulated within-event arrivals: 11 changing updates / 265 partial
results. Source baseline `a88015f` and candidate `9832741` used identical indexed
fixtures and the same application code. Both acquisition paths passed; every
stage's action counts and semantic fact/split digest matched across source versions.

| Source-only subprocess wall time | Original | Optimized |
| --- | ---: | ---: |
| Whole official LXF | 2.513 s | 1.934 s |
| Final LXF after 265 partial results | 3.116 s | 1.968 s |
| Unchanged final replay, direct path | 0.988 s | 0.608 s |
| Unchanged final replay, PDF-first path | 0.956 s | 0.628 s |

Source apply (including guarded replan) improved 2.335→1.715 s for the direct
final and 2.613→1.754 s for reconciliation. Initial reconciliation planning fell
398→96 ms. Source subprocess wall time also includes interpreter/module startup
and commit; it excludes saved-file parsing and app publication.

The complete parse + source + optimized-application stage sums were
10.945→10.443 s for direct final and 9.839→9.353 s for reconciliation. Application
publication itself varied 8.256→8.344 s and 6.547→7.221 s with identical code, so
**do not attribute all total variation to these source changes**. Eleven partial
updates were 0.486–0.783 s before and 0.505–0.760 s after; individual deltas moved
in both directions. Pure PDF paths do not exercise the official identity guard,
and these PDF sheets contain no split detail to batch. This is not evidence of
a general partial-import speedup.

These are single paired local samples, not p95/SLA estimates, production hardware,
full-history migration or AWS results. No downloads or concurrent browser load.
Private clean artifacts: `sui-etl-clean-baseline` and `sui-etl-clean-candidate`.
All disposable schemas were removed by the harness. The larger three-column
profile table above uses only three PDF documents / 93 partial results and must
not be compared directly with this eight-document workload.

## Verification

`LIVE_IMPORT_TEST_CONFIG=<private local test config> python3 -m unittest discover -s tests -v`
ran 323 tests: 293 passed and 30 unrelated database-configured tests were skipped.
The live-import family contains 27 passing tests. Unique transactional schemas
are rolled back by test teardown; no production data is reset.

New regression cases cover 120 ordered splits across two batches, no split
DELETE for a new result, unchanged replay preserving split IDs, correction from
120 to three splits, and an injected failure in the second batch restoring the
prior result/splits/receipts on rollback. The identity case covers two conflicting
prior keys with one matching official key, plus separate event number/date/round.
Existing protected official detail, ambiguity, nationality-change, provenance
and stale-plan checks remain in the suite.

The cross-project replay also checks independent personal/season bests, every
ranking position and population, final semantic facts including reaction times
and splits, zero-change replays, empty archive/club/coach work queues, and final
provisional-state removal. Its SQL reader checks are not browser/concurrent HTTP
availability certification.

## Evidence and remaining work

Private artifacts live under the canonical SwimProfiles checkout at
`artifacts/issue-305/competition-replay/`; normalized athlete data must not be
committed. Diagnostic runs are `sui-etl-profile-indexed`,
`sui-etl-profile-batched` and `sui-etl-profile-indexed-identity`. Source commit IDs
and file hashes are recorded in `timings.json` for reproducibility.

Remaining costs include global swimmer/alias materialization, per-race result/
receipt writes, and repeated JSON hashing/serialization during guarded planning.
The application also exports all source club attributions to detect corrections
outside selected meets. That needs a complete change journal/checkpoint contract;
simply filtering selected meets would lose required corrections. Keep those
problems open instead of claiming the entire import path now scales only with
new results. Redis is available for evaluation, but the existing local
fingerprint trial saved only about 0.025 ms per 20-key batch; it does not justify
moving transactional comparison state out of PostgreSQL on present evidence.
