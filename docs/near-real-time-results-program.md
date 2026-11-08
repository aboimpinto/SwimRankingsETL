# Near real time swimming results

Raw source policy: [local retention / AWS cleanup](source-file-retention.md). Keep local replay files; AWS raw inputs are temporary.

Latest outcome: [completed one-hour five-minute-cadence trial](nrt-hour-trial-results-2026-11-08.md).
108 new results published at local 58 / AWS 53; 11 cycles under five minutes,
one skipped recovery slot and one reader-latency incident. Source coverage is
incomplete. The finite timer exited; there is no continuing authorization to
schedule new runs from that expired one-hour window.

Latest measured delta: [23-competition observation and four-result publication](nrt-delta-cohort-2026-11-08.md).
Local 51 / AWS 46 verified; 209.675 seconds processing exceeded the owner gate.
Further batches await direction. Initial-load and observed-delta workloads must
be reported separately; held layouts still prevent full competition coverage.

Latest owner gate and expansion evidence: [8 November bounded expansion](nrt-expansion-2026-11-08.md). Under 60 s ideal, 60–180 s acceptable; stop expansion and request direction above 180 s.

Updated 8 November 2026. This is the central engineering record for the recurring
weekend trials: owner requirements, measured evidence, design options, operational
concerns and next experiments. Start here when resuming work; do not reconstruct
the design from chat or treat a historical runbook as current operating state.

## Implementation checkpoint — 8 November, after the initial trials

The first implementation milestone is on branch `feat/nrt-manual-batch`, tracked
by [ETL issue 42](https://github.com/aboimpinto/SwimRankingsETL/issues/42).
Read the [delivery evidence](nrt-implementation-milestone-1.md) and
[executable manual batch runbook](nrt-manual-batches.md) before using the older
trial wrapper below. Reusable collector, canonical receipts, application adapters
and independent verifier now live under `scripts/` with focused CI tests.

A real two-meet local batch imported 77 results, held 12 unresolved identities and
published generation 46 in 23.152 seconds including verification. Replay did not
republish. AWS remains at last verified generation 40: this new local batch was
**not delivered to AWS**. Its explicit deferred-delivery marker must be reconciled;
the earlier trial's empty queue is not evidence of current synchronization.

This establishes a manual executable foundation, not sustained capacity or a
finished orchestrator. No cron, worker service or AWS container was installed.
Cross-repository relative links later in this document assume the canonical
workspace layout; from an isolated worktree use the named canonical checkout.

## Purpose and decisions

Swimmers, coaches, parents and fans should see newly published results and their
ranking implications within a few minutes. The source may publish an unfinished
event repeatedly as more swimmers finish. We must support that without duplicates,
missing updates or making existing profiles unavailable.

Owner requirements:

- Prioritize live partial results, especially PDFs. Improve official final LENEX
  imports too, but measure the two workloads separately.
- For live updates: under one minute is ideal; one through five minutes is
  acceptable; over five through ten minutes needs investigation/improvement;
  over ten minutes is unacceptable. Faster collection alone is not success.
- Expose discovery delay and queue age alongside processing time. A fast import
  after a long wait does not provide near-real-time results. The operational
  interpretation of the thresholds should cover the delay users experience;
  record processing and observed end-to-end latency separately.
- Continue testing across dozens of European competitions on successive weekends.
  Do not infer a safe capacity from a single small PDF or a single country.
- Use deterministic programs for discovery, parsing, import and verification.
  An LLM can assist engineering; it must not be a recurring runtime dependency.
- Keep the current work manual and bounded. No cron, service installation or
  unattended continuous operation has been authorized by these discussions.
- Run locally for development/testing now. The future production runtime is a
  **container on AWS that updates AWS SwimRankings and AWS SwimProfiles**.
  Production must not depend on the local machine or an open assistant session.
- Record concerns, solutions, timings, failed attempts and next steps here and in
  the linked runbooks. Local, tested, merged and deployed are different states.

No orchestrator implementation, durable queue schema, worker count, retry policy,
batch-size limit or automatic competition-finalization rule has been accepted as
finished. The following design is a proposal to test, not an installed service.

## Current evidence and limits

The detailed [manual trial runbook](manual-live-import-test.md) owns command lines,
source semantics, exact receipts and stage timings. The 8 November measurements
used existing infrastructure and SwimProfiles v0.1.42, with live reader traffic.
They are not controlled cold-cache benchmarks or proof of sustained capacity.

| Workload | Accepted new results | Measured pipeline | Interpretation |
| --- | ---: | ---: | --- |
| Malta official final LENEX | 1,090 of 1,102 parsed rows | 327.411 s | Initial full-meet workload; twelve parsed rows held; live PDF thresholds do not apply |
| Cossonay Sunday event 406 PDF | 8 of 9 parsed rows | 88.790 s | Partial event; one ambiguous identity held; acceptable live processing time |
| PDF plus extra monitor baseline/final checks | Same 8 | 99.782 s | Broader trial wall time; not an additional import |
| Identical PDF replay | 0 | 1.317 s; 15.306 s including checks | Deduplication evidence, not a changed-import speed benchmark |
| Discovery/observation sweep | 22 meet pages and 17 sampled PDFs | Approximately 39 s | Sequential read-only collection; no parsing/import/cache publication |

Malta's file marks the meet and both sessions OFFICIAL; every Sunday event has
results. The owner clarified that it is a final official export. The earlier
“partial LENEX” description was wrong: provisional handling by our pipeline does
not establish that the source file is incomplete. A final export may supply
reactions, splits, relays/team results and corrections beyond provisional PDFs.

Cossonay stage breakdown:

| Stage | Time |
| --- | ---: |
| Fresh collection | 1.416 s |
| Canonical plan and apply | 1.380 s |
| Local cache including its availability hook | 14.789 s |
| Independent local data/ranking verifier | 2.518 s |
| AWS package export | 3.801 s |
| AWS canonical delivery | 5.566 s |
| AWS cache including its availability hook | 39.890 s |
| AWS importer inside that cache stage | 34.211 s |
| Best-summary refresh inside AWS importer | 2.151 s |
| Ranking-population refresh inside AWS importer | 1.270 s |

Nested timings overlap; never add them all. Setup, source/cache work and remote
verification account for the remainder. The PDF batch affected 16 best keys,
changed twelve best summaries and refreshed 65 ranking groups. Metadata refresh
flags were all false. Malta's initial metadata adoption flags were true; its
larger membership, best-summary and population operations have separate timings.

Availability evidence: Malta monitor 565 requests, zero failures, maximum
1,361 ms; PDF monitor 239/0/604 ms; replay 89/0/699 ms. Eight affected PDF swimmers
were subsequently checked on each host across page/profile/season/archive paths
(64 additional requests), all passed; maximum local 162 ms, AWS 746 ms. The
independent fact/best/ranking checks had zero mismatches. Affected-page checks
were added after the changed PDF measurement and now run in future verification.
Sampling does not establish every profile's availability or cold-load behavior.

At this checkpoint local publication was 45, AWS 40; replay changed neither;
pending queues were empty and controllers disabled. These are dated observations,
not values to hardcode in a future trial.

### Actual live arrivals

Between approximately 12:05 and 12:07 Zurich on 8 November, 22 date-relevant meets
across eleven countries were observed. Seventeen linked 341 accumulated PDFs.
Two page sweeps started two minutes apart; no new PDF links appeared. Of seventeen
fixed existing-PDF samples:

- Incukalns, Latvia: six new provisional result rows appeared inside event 2's
  existing PDF.
- Lagos, Portugal: only generation timestamps changed; result content did not.

The other 324 PDFs were not sampled for revisions. This is evidence of live
within-event updates, not a site-wide arrivals-per-second estimate. “Every second”
was the owner's expression for independently arriving updates, not a numerical
requirement. Event PDFs can contain many swimmer results, so report documents,
semantic changes, swimmer results and database publications separately.

## Deployment path and system boundary

**Now:** run bounded tests locally. The existing test pipeline collects sources,
updates local canonical SwimRankings, publishes local SwimProfiles, then delivers
to AWS and verifies AWS publication when that test includes AWS. Its transfer and
SSH overhead must remain visible in measurements.

**Future:** an AWS container discovers/downloads public sources, updates the AWS
canonical SwimRankings database through the ETL writer, and publishes AWS
SwimProfiles through its application writer. Reuse existing PostgreSQL
infrastructure; do not add another database server. Public web requests continue
to read app-owned data and never perform canonical imports or ranking rebuilds.

The future host-local production path need not send data from the local machine
or make an SSH round trip per batch. That may reduce overhead, but savings must
be measured on AWS rather than subtracted speculatively from today's timings.
Source and app credentials stay separate and out of images/logs. Queue state,
checkpoints and required evidence must survive container replacement; neither
container memory nor its disposable filesystem is durable state.

A host container manager/restart policy is the proposed outer supervisor. An
internal coordinator would own scheduling and job state. The earlier systemd
suggestion referred to process supervision; a separate systemd service per
competition is unnecessary. Exact Docker/Compose/restart/healthcheck integration
remains to be designed against the existing deployment baseline. A healthy
process alone is not proof that jobs are progressing.

[SwimProfiles integration](../../AboimPintoConsulting/SwimProfiles/docs/near-real-time-results-integration.md)
records the application-side boundary. This workspace link assumes the documented
sibling checkout layout; production must not use local checkout paths.

## Scheduling options considered

| Option | Benefit | Concern | Disposition |
| --- | --- | --- | --- |
| Dedicated worker/process per competition | Independent ownership and timing | Process growth, lifecycle, supervision and recovery complexity; does not remove shared database locks | Not selected as the starting design |
| Import all competitions sequentially, then restart the sweep | Simple control flow | One slow import delays discovery for everyone; long sweeps produce unfair waiting | Keep only as a baseline comparison |
| One coordinator with per-competition scheduling records and bounded shared publication | Independent due times, few processes, shared publication overhead | Still needs durable progress, timeouts and replay-safe recovery | Current proposal to test |
| Small collection pool plus one publisher per database | Overlap network waits and collection with publication | More moving parts and resource contention | Add only after evidence shows collection blocks freshness |
| Established queue/workflow framework | Existing leases, retries and monitoring capabilities | Dependency and operating cost | Evaluate if reliability needs exceed the simple design; no product selected |

Twenty-two competitions need twenty-two durable scheduling records, not
necessarily twenty-two processes. Sequential collection already observed the
22 pages/17 PDFs in about 39 seconds. This does not prove every future sweep will
fit; download failures, document growth and parsing costs remain to measure.

SwimProfiles uses advisory lock 734340 for publication/maintenance. Canonical
`import_live_results.py` uses the shared `live_results_import` transaction lock.
The current safe model is one writer per database. More publishers can reject or
wait on locks and compete for disk; do not bypass locks for apparent parallelism.
Local and AWS are separate systems, but current trials deliberately verify local
publication before AWS delivery. Pipeline overlap is not implemented proof.

### Proposed bounded cycle

1. Select the next due competition fairly. Keep per-source timeouts so one slow
   source does not monopolize a sequential collector.
2. Fetch published result links and recheck existing documents. Discover sources
   from actual links; do not infer freshness solely from LENEX being nonempty.
3. Compare raw hashes, then deterministic normalized results. A changed PDF hash
   can reflect only a footer timestamp and must not force a ranking publication.
4. Persist the pending changes and their source versions. Coalesce only when a
   newer snapshot is known to cover the older one; different event PDFs must not
   overwrite each other in a single “latest competition” slot.
5. Assemble a bounded batch from several competitions, subject to oldest waiting
   age, row/group limits and available resources. No concrete limits yet chosen.
6. Apply canonical changes, publish affected app data/ranking groups atomically,
   then verify facts and sampled public reads. Union dirty groups across the batch
   so shared groups are refreshed once where the existing design allows it.
7. Acknowledge each stage durably. Updates arriving meanwhile remain pending for
   the next publication; never clear them with an older batch's success receipt.

This loop is a design target. Collecting while publishing requires explicit
concurrency or an asynchronous mechanism; a blocking single-process loop does
not gain that behavior merely by keeping a queue. First benchmark combined
publication without building a full scheduler.

## Required state and visibility

The coordinator must answer: which competitions are due, what each is doing,
which source version is queued, what reached each database, and how old the
unpublished work is. Proposed logical records, not an approved schema:

| Record | Required information |
| --- | --- |
| Competition | Stable live ID, canonical meet mapping, source URLs, country/timezone, scheduled sessions, lifecycle state, next check and last successful check |
| Source document | Event/source identity, raw hash, semantic version, parser version, first/last observed time, source publication time when actually known, coverage and holds |
| Job | Job/batch ID, stage, owner/lease if concurrent, start/progress/deadline, attempt count, retry time, error classification, dependency and source version |
| Publication | Canonical receipt, local/AWS target as applicable, app generation, fact/best/ranking checks, profile checks, acknowledgment time |
| Backlog | Pending competitions/documents/results, oldest unpublished first-observed time, estimated drain time and held work counted separately |

At-least-once retries with idempotent writes are the intended reliability model;
do not claim distributed exactly-once execution. A crash can occur after commit
but before acknowledgment. Reconcile durable receipts before replaying. Record
source import, app publication and website verification as separate facts.

## Failure and recovery concerns

| Concern | Required behavior to design/test |
| --- | --- |
| Coordinator/container crash or host reboot | Resume durable work; reconcile commit receipts; do not reset source ledgers or duplicate results |
| Worker hangs or stops reporting progress | Bounded deadline; capture stage/query/wait details; terminate only an owned operation when appropriate; recover before retrying |
| Database commit outcome uncertain | Inspect receipt/generation and lock ownership before retry; silence is not success or proof of rollback |
| One unavailable or malformed source | Record failure/hold and retry time; let unrelated competitions proceed |
| Authentication/rate-limit response | Respect source restrictions; classify separately from transient errors; no bypass or tight retries |
| Repeated permanent parser/identity error | Hold with evidence, avoid infinite retries and retry storms; allow manual review/requeue |
| Two jobs for the same event/version | Enforce idempotency and ownership; stale completion cannot overwrite a newer checkpoint |
| Correction or out-of-order snapshot | Preserve revisions/provenance; reconcile against newer accepted evidence instead of overwriting blindly |
| One source fails inside a combined batch | Do not discard healthy queued work; isolate validation failures before publication; transactional failure remains retryable |
| Queue grows faster than publication | Track oldest age and throughput; bound work fairly; adjust batch/collection policy from measurements rather than spawning unlimited writers |
| Profile errors during/after import | Save failing requests and relevant query diagnostics; block further unattended publication, investigate shared cause; preserve last good data where possible |
| Competition ends while work remains | Stop frequent checks only through explicit lifecycle policy; drain or reconcile queued work; do not kill a valid publication by wall-clock end time |
| Container restart while competition appears finished | Finalization state/late-correction window survives restart; no forgotten or endlessly running competition |
| Disk or memory pressure | Bound archives and batch sizes; record free space, I/O and memory; retain required provenance and unacknowledged work |

Heartbeat frequency, deadline values, retry/backoff limits, alert routing and
operator override mechanisms are open design questions. Reading a successful
heartbeat does not prove a transaction is making useful progress. Long final-file
imports need a distinct workload/deadline policy from live partial batches.

## Competition lifecycle proposal

`Upcoming → Active → Awaiting final results → Final reconciliation → Completed`

Per-source holds/retries should not falsely mark the entire competition complete.
Scheduled end time is a clue, not finality proof. Multi-day meets can have completed
sessions while later events are still pending. After the final official export is
reconciled, reduced-frequency follow-ups can catch corrections before retirement.
The observation window and finality evidence rules remain undecided.

Shared workers do not need to be killed when one competition ends. Its frequent
scheduling stops; workers return to the pool. On service shutdown, stop assigning
new work, record owned in-flight operations and drain/recover according to stage.

## Data and reader correctness

- Stable result identity must not depend on changing rank, time, PDF row position
  or page number. Preserve heats/finals, course, gender/category, race date and
  club-at-race evidence. Distinguish corrections from new swims.
- Repeated partial documents must not duplicate rows. Absence in a partial file
  is not a deletion. Later authoritative corrections need explicit semantics.
- Never guess an ambiguous swimmer or infer nationality from club country.
  Keep unknown reaction/split fields unknown. Hold unsupported relay identities.
- Source observation does not imply parser support: the Latvian/Portuguese live
  examples were inspected, not imported by a universal multilingual parser.
- Final LENEX should enrich provisional facts without duplicating them or being
  downgraded by later partial PDFs. Club participation/medal caches, records and
  ranking implications must remain consistent with the source's coverage.
- Rank summaries are shared between swimmers. Refresh affected event/course/
  gender/season/category/club/national/European scopes and resulting profile
  dependencies. Avoid rebuilding unchanged history or every swimmer on each PDF.
- Readers should keep seeing a coherent published generation during writes.
  Sample random and affected profiles before/during/after real changed batches;
  compare facts, bests and rankings to an independent reference. Include error
  pages that return HTTP 200 and stale-generation responses in failure detection.
- Do not raise the web SQL timeout to hide import-related unavailability. Retain
  failures, operation IDs, query labels/full safe SQL when possible and timings;
  exclude credentials and sensitive bound values. Fix shared causes, not one slug.

## Performance and capacity measurements

Track `first_observed → parsed → canonical_commit → cache_publish → reader_verified`
for each version and target. If actual source upload time is reliable, retain it
separately. Race time, document generation time and first observation are not
interchangeable. Report polling gap, queue wait, processing and verification;
state the latency origin explicitly.

Record changed rows, corrections, held rows, document count, affected athletes,
best keys and ranking groups; stage/query elapsed time, lock waits, CPU, memory,
disk I/O, free space and archive growth. Retain slow SQL and bounded EXPLAIN
investigations on safe representative workloads before attributing a cause.
Do not double-count nested timers. Report maxima and distributions over repeated
cycles, not just a mean or one warm sample; do not claim a meaningful p95 from a
single batch.

A two-minute poll plus ninety-second processing can mean approximately 3m30s
before visibility with no backlog. A serial ninety-second standalone pipeline
can serve approximately forty batches/hour. Those are arithmetic illustrations,
not measured capacity guarantees. Multiple event documents should share bounded
publication overhead where correctness permits. Batch size, latency and memory
must be balanced: batching must not wait indefinitely for all competitions.

AWS observations use the existing 4 GB / 2 vCPU Lightsail host and 64 GB database
disk reporting 192 IOPS. Local hardware is faster; local speedup percentages do
not establish equivalent AWS gains. Database storage, source archives, temporary
work and container images all contribute to growth. Review storage by the end of
November after successive weekend imports; no automated reminder is installed.
Forecast reserve exhaustion from measured daily/weekend growth, state confidence
and include backups/retention requirements before deleting anything.

## Next experiments in order

| Step | Experiment | Evidence required before moving on |
| --- | --- | --- |
| 1 | Preserve and package reusable trial code | Extract tested adapters from ignored operational folders, keep private evidence separate; runnable fresh-checkout setup and regression fixtures |
| 2 | Observe representative simultaneous competitions | Repeated bounded sweeps; semantic new/corrected rows per interval, unsupported coverage, fair document sampling; no count of timestamp-only changes as arrivals |
| 3 | Manually combine two changed competition batches, then several | Compare matched standalone vs combined work, dirty-group union, full timings, source/app parity, dedup replay and profile checks |
| 4 | Sustained bounded local rehearsal | Several cycles with arrivals during publication; queue age/backlog, slow-source fairness, shutdown and restart after commit-before-ack |
| 5 | Test the minimal durable scheduler locally | Per-competition due times, retry/error records, multi-day/finalization behavior; prove recovery before adding workers |
| 6 | Add only justified concurrency | Compare sequential collection against a small bounded pool; no extra database writers without a design/benchmark proving correctness |
| 7 | Run the production-shaped container locally | Same executable/config contract, persistent state, restart/health behavior, secrets and resource bounds; no dependence on a conversation |
| 8 | Rehearse that container on AWS in a bounded test | Existing database infrastructure, actual contention/reader load, host-local stage timings, recovery and disk forecast |
| 9 | Decide unattended operation separately | Explicit go/no-go evidence, rollback/recovery instructions, monitoring ownership, supported-source coverage and startup/shutdown procedure |

These are experiment proposals and sequencing, not implementation promises or
automatic permission to install continuous services. If a defect appears, retain
its failed evidence, stop the affected publication path when necessary, implement
and test the fix, then resume deliberately. Do not pause healthy work merely
because a speculative optimization might help.

## Knowledge maintenance and handoff

Use the [weekend experiment template](near-real-time-weekend-template.md) for each
new trial. Append dated observations; update this decision record only when the
owner changes requirements or evidence changes the design. Keep alternatives and
rejected assumptions concise but traceable. Every experiment ends with:

1. Commands/config/runtime versions and workload bounds.
2. Successful and failed stage receipts, raw evidence locations and timings.
3. Correctness/availability outcome, holds and unverified coverage.
4. Pending queues, active processes, enabled schedulers and final generations.
5. What changed in source, what was tested, what merged and what deployed.
6. The next smallest useful experiment and its unanswered question.

Private evidence remains under `reports/live-trial-2026-11-08/` for this Sunday;
never commit raw swimmer reports, credentials or database dumps into this record.
The [manual runbook](manual-live-import-test.md) indexes exact receipt filenames.
The wrapper and adapter changes are local working files, not a released service;
part of their support code remains in ignored reports and needs deliberate
packaging. Preserve those files during worktree/repository cleanup.

Related work: [Sunday trial issue 242](https://github.com/aboimpinto/SwimProfiles/issues/242),
[performance issue 66](https://github.com/aboimpinto/SwimProfiles/issues/66), and
[deferred retry UX issue 235](https://github.com/aboimpinto/SwimProfiles/issues/235).
The UX proposal is not permission to change timeouts or implement it now.
