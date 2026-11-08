# Five-meet latency gate and optimization

The 8 November five-meet changed batch `4cb7eae481214bb2864a8ce4bdfa7349`
accepted 121 new rows, held 14 identity rows and two unsupported documents, and
published local 49 / AWS 44. All 284 stored race facts, best summaries and sampled
rankings matched. All 445 monitored requests passed (maximum 1.499 seconds).
Collection, planning, local/AWS publication and verification took **189.848 s**,
so expansion stopped at the owner's 180-second gate. Both delivery queues were
clear after this completed batch.

The owner selected optimization followed by another changed five-meet test and
suggested parallel workers. [Issue 45](https://github.com/aboimpinto/SwimRankingsETL/issues/45)
tracks this work. No new unattended scheduling is implied.

## Recorded costs

Preparation took about 14 seconds, local monitored phase 34.288 seconds and AWS
monitored phase 132.089 seconds. Within AWS: canonical export 4.334 seconds,
transfer 17.318 seconds, cache stage 73.617 seconds, independent reader adapter
27.541 seconds. These nested timers overlap. Cache query timings include best
summary refresh 11.130 seconds and population refresh 6.932 seconds; SQL timing
labels and private reports are preserved.

Reader group discovery took 8.760 seconds under the changed-import workload.
A later read-only EXPLAIN showed it already used index-only scans. Its much
faster warm run is not evidence that an index scan rewrite removes 8.760 seconds.
The alternative per-athlete group probe touched essentially the same buffers,
so the existing group discovery is retained.

The independent best-time oracle's equivalent per-athlete lateral access reduced
buffer accesses from about 25,060 to 14,030 on the same 274 athletes. Repeated
read-only comparisons returned identical results, zero differences from stored
bests. Warm execution in alternating order was 659–748 ms for the original and
376–382 ms for the candidate. These are warm paired query measurements, not a
cold-host or whole-import speedup. It still verifies all accepted athletes against
raw history and the released independent best policy.

## Implemented changes

- The verifier runs at most two independent ranking/profile checks concurrently.
  SQL pool concurrency stays bounded; publication remains serialized. Every
  original fact/best/top-ranking/affected-profile assertion remains. If a check
  fails, new checks stop and owned in-flight checks drain before failure returns.
- The tracked concurrency helper is bundled with the verifier for both local and
  remote execution. No dated untracked helper is needed for the verifier itself.
- `meet_delivery.py push --ssh-control-path /absolute/socket` can reuse an
  operator-owned connection for SSH and SCP. It retains remote revision checks,
  package ordering and receiver receipts. Preview still performs no network work.
- `nrt_ssh_session.ssh_session(alias)` owns a short-lived connection and private
  socket, and closes only its own child on success/error. It installs no daemon
  or persistent host configuration. The bounded trial adapter reuses it through
  canonical delivery, cache invocation and reader verification.

Read-only transport probes: fresh connections took 515–1,115 ms; shared connection
commands took 64–164 ms, plus one initial connection setup. This is four commands
per mode and does not predict all remote operation durations.

Tests: 33 focused Python batch/adapter/lifecycle tests pass; three Node concurrency
checks pass; eight delivery unit tests pass (nine separate fixture-DB integration
tests skipped). Real read-only verification passed locally in 2.111 seconds and
on AWS in 6.174 seconds with the same 284 facts, 274 athletes and 24 groups, zero
mismatches; AWS maximum checked HTTP latency 520 ms. Cache state was warm, so
these numbers alone do not establish changed-import improvement.

## Next acceptance run and retained evidence

Collect new published PDFs from the same five competitions and run a changed
batch through local/AWS with the existing monitoring and 180-second gate. Record
workload differences rather than claiming a matched speedup. Public timeouts and
correctness assertions stay unchanged. A breach again stops expansion for owner
direction.

Private evidence: canonical ETL `reports/nrt-optimization-2026-11-08/` contains
paired query plans/equality; `reports/nrt-expansion-2026-11-08/` contains delivery
receipts and optimized reader checks. The feature worktree's expansion reports
contain the SSH probe and source/batch manifests. A first five-meet driver attempt
incorrectly compared milliseconds to a seconds value, refused before writes after
13.996 seconds, and was corrected before the actual 189.848-second run; retain
that failed preflight rather than confusing it with a genuine timing breach.
