# Full-cohort observation and small-delta trial — 8 November

Canonical resume context: [weekend handoff](../MemoryBank/handoff-nrt-unattended-weekend-2026-11-08.md) on `main`. Historical worktree report paths below have a verified copy under `reports/nrt-worktree-archive-2026-11-08/` in this checkout.

The owner clarified that capacity must be tested with changes arriving between
checks across active competitions, rather than multiplying an initial-load time
by meet count. Twenty additional swimmers in an existing race can be a much
smaller workload than initializing five competitions. The saved cohort contained
23 date-relevant competitions; the earlier discussion used 22.

## Method and coverage

`scripts/nrt_delta_observe.py` took two bounded read-only observations of every
linked event PDF in that cohort. Four collection processes each start at most
one request per second. Fetches/parsing are bounded, source bytes are archived
privately, and each observation has a shared 175-second budget. No scheduler or
service was installed.

Baseline: **114.209 seconds**, 23 pages checked, 435 PDFs fetched, 101 supported
documents and 334 held documents. Two competitions exposed no PDF links.
Baseline rows were not imported as a supposed live delta.

Comparison: **114.202 seconds**, 437 PDFs, zero page/download errors. There were
100 unchanged supported documents, one newly linked supported document, and 335
held documents. Two PDFs were newly linked; two existing PDFs changed bytes.
New Petit-Lancy event 27 supplied five rows. The other changed/new documents were
held. Unsupported coverage is not evidence of zero new swims.

Delta staging keeps only observed additions/corrections with checked raw evidence.
It excludes unimported baseline rows and recovered parser coverage. Missing rows
never authorize deletion. Canonical preview and identity/evidence rules still
apply. Observation state is not a database delivery acknowledgment.

## Local/AWS publication

Batch `3446899250eb49b8973702abdfb063a1` accepted **four new results**, held one
unresolved identity, and published local SwimProfiles **51** and AWS **46**.
The AWS receipt confirms four changed results, eight affected best keys, sixty
refreshed ranking groups and four refreshed profiles. Canonical transfer preserved
the whole meet while the app importer detected its delta. All **268 monitored
requests passed**, maximum **868 ms**. Both delivery queues were clear afterward.

| Measurement | Seconds |
| --- | ---: |
| Comparison collection | 114.202 |
| Canonical preview | 0.779 |
| Local import/publication/verification phase | 19.672 |
| AWS delivery/publication/verification phase | 64.972 |
| Total processing, including surrounding monitoring | **209.675** |
| Separate manual handoff gap | **39.794** |
| Comparison-start to final verification, including handoff | **249.469** |

Nested AWS timings: source delivery 1.748 seconds, cache invocation 40.599
seconds, independent reader check 14.782 seconds. The app's own import timer is
33.898 seconds. Do not add nested values to their enclosing totals. Actual
publisher upload time is unknown; these are not source-upload latency measures.

AWS cache work was smaller than the earlier 140-result batch (40.599 versus
78.942 seconds). These are different workloads, not a paired speedup benchmark.
Fetching every historical PDF dominated this trial. All-competition capacity
remains unproven: held changes were not imported and processing exceeded 180 s.

## Gate and next direction

The trial finished committed work and verification, then stopped further batches
under the owner's three-minute rule. Direction was requested: optimize source
checking and retest (recommended), optimize AWS publication first, or expand
support for held layouts first. No next batch is authorized by an unanswered
question or elapsed silence.

Source-check improvements must retain a defined correction-recheck policy,
detect additions to an existing PDF, preserve fair coverage and expose held or
unobserved work. An unchanged meet page alone does not prove linked PDFs are
unchanged. Never discard older pending changes. Database writes stay serialized.

## Tests and retained evidence

Nine focused tests cover twenty new swimmers in an existing race, corrections,
footer-only changes, distinct rounds, ambiguous identities, new links versus
baseline documents, archive checksums and no-delete behavior. Local NRT suite:
30 passed, 12 fixture-database cases skipped. PDF suite: 31 passed, 49 fixture-DB
cases skipped. CI provides disposable PostgreSQL; skipped local cases are not
claimed as executed.

Private observations/staging: worktree `reports/nrt-delta-cohort-2026-11-08/`.
Publication/website evidence: canonical ETL
`reports/nrt-expansion-2026-11-08/cohort-delta-02/`. The preparation receipt records
the handoff gap separately. Raw swimmer rows and credentials remain private.
Code belongs to PR #43; integration/release is separate from manual DB publication.
