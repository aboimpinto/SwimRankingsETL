# Bounded PDF expansion — 8 November 2026

Owner instruction: continue adding competitions while updates remain within the
agreed latency gate. The latest gate supersedes earlier five-minute acceptance:
**under 60 seconds ideal, 60–180 seconds acceptable; above 180 seconds stop
expansion and request direction.** Reader correctness/availability failures also
block further batches. Preserve/reconcile any already committed operation.

## Delivered support

[Issue 44](https://github.com/aboimpinto/SwimRankingsETL/issues/44) extends
[PR 43](https://github.com/aboimpinto/SwimRankingsETL/pull/43):

- Italian Splash individual results with exact observed event/round/column labels,
  including timed disqualifications. Wrapped and unknown status layouts remain held.
- Observed English and Latvian Splash individual columns. Age-only masters
  columns are unsupported. Recorded birth years/suffixes are required.
- Unsplit names are retained as source evidence. The importer resolves the full
  name in either displayed order against existing canonical name/year/gender,
  accepting only one candidate. It never guesses surname boundaries or creates
  swimmers from PDFs. Explicit comma names retain their stated surname order.
- Parser versions distinguish the extended collector. Raw files remain archived;
  repeated/corrected results retain race identity. Unknown points scales do not
  become AQUA points. Non-finish rows with no time are explicitly excluded.

76 PDF/layout/identity regression tests passed against disposable schemas;
29 batch/collector/recovery tests passed separately. The tests include unknown
and ambiguous full names, century ambiguity, corrections/replay, wrong event/date,
missing rounds, disqualifications and unsupported columns. No shared data reset.
The first AWS monitor attempt refused an invalid sample seed before any import;
the harness was corrected and the failed attempt retained. A numbered Latvian
meet heading initially caused a conservative document hold; a regression test
now distinguishes the exact heading from a result row.

## Measured batches

| Batch | New results | Identity holds | Elapsed with monitoring | Sampled requests / failures |
| --- | ---: | ---: | ---: | ---: |
| Deferred Cossonay/Petit-Lancy AWS delivery | 77 already local | 12 retained | 103.396 s, AWS catch-up only | 266 / 0 |
| Chiasso event 32 | 9 | 2 | 109.001 s, local + AWS | 295 / 0 |
| Inčukalns event 9 + Plovdiv event 28 | 69 | 1 | 131.476 s, local + AWS | 328 / 0 |

Collection and preview preceded the three runs above and are separately retained;
these elapsed values do not measure source upload-to-visible latency. No organizer
upload timestamp is known. Chiasso collection took 1.074 s; the two English/Latvian
PDF collections took 1.069 and 1.085 s. Do not include engineering/manual idle time
as processing or silently equate final PDFs with final whole-meet completeness.

Chiasso local batch took 22.041 s including its monitor; AWS phase 76.377 s,
including a 38.744 s cache stage. Latvia/Bulgaria local phase took 24.826 s; AWS
phase 92.781 s, including a 54.382 s cache stage. These nested timers overlap.
All imported facts, bests and sampled rankings were independently checked.
The maximum sampled public request was 1.223 s across these runs. Website SQL
limits were not raised. Local generation 48 / AWS 43 is the checkpoint after
these batches; the earlier deferred delivery marker is now acknowledged.

The experiments use the existing populated local databases and local development
website, and the existing AWS 4 GB/2-vCPU host with its 192-IOPS database disk.
Natural cache state and sampled reader load were retained; no cold-cache or
exclusive-host performance experiment was conducted. No matched speedup or
sustained capacity is claimed. The source identities selected by a PDF are a
subset of a competition; five accepted competitions does not mean all their
results, relays or medals are complete.

## Expansion and evidence

Fresh discovery found 23 date-relevant competitions. Twenty-one had result PDF
links; initial probes sampled one document each, not every language/event layout.
Two sites had no linked result PDFs at that observation. Unsupported Dutch,
Portuguese, Catalan, Serbian, Slovak and other layouts remain explicit gaps.
Numeric event selection is a candidate heuristic, not proof of latest upload.

The next bounded trial combines fresh documents from the five accepted meets,
including collection and planning in its timer. No continuous service or cron is
installed. Operational monitoring and AWS delivery reuse the reviewed Sunday
adapters in private `SwimRankingsETL/reports/nrt-expansion-2026-11-08/`; the durable
local batch runner/parser/verifier is tracked in PR 43. The AWS trial wrapper is
not yet a packaged container orchestrator. Keep that boundary explicit.

Raw sources, immutable batches and preparation receipts are under the feature
worktree's `reports/nrt-expansion-2026-11-08/` and `reports/nrt-milestone1/state/`.
Private delivery receipts, per-stage timings, host metrics and before/during/after
reader logs are under the canonical ETL expansion report directory. Do not commit
PDFs, swimmer rows, credentials or private deployment configuration.
