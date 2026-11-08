# Recoverable manual batch milestone

Issue [42](https://github.com/aboimpinto/SwimRankingsETL/issues/42), branch
`feat/nrt-manual-batch`, based on current `origin/main` (76f320d). The historical
working checkout has unrelated changes and remains intact. This milestone starts
implementation of the [program](near-real-time-results-program.md); it does not
install a scheduler or deploy a container.

## Implementation decisions

- Package the reviewed modern live-index, full-club/two-digit-year PDF and French
  Splash support with synthetic fixtures. Keep unknown identities/layouts held.
- Provide a database-free, explicit PDF collector and a separate manual batch
  CLI. Selection is bounded and explicit; one normalized source per competition
  per batch. The collector can combine distinct event PDFs for that competition;
  conflicting same-event snapshots are held, never arbitrarily overwritten.
- Preview creates an immutable batch manifest and read-only canonical plans.
  Execution requires the batch ID plus `--execute`. Source reports and config
  hashes are bound to the manifest; no password is written into it.
- A PostgreSQL receipt keyed by batch ID and input digest commits in the same
  transaction as the canonical changes. It enables recovery after commit but
  before a local receipt was written. Canonical writes remain serialized by the
  existing advisory lock. All eligible meet applies in a batch commit together.
- Publish the union of changed canonical meet IDs once, then independently verify
  the resulting application publication. Required command adapters exchange
  batch-bound JSON receipts; zero exit code alone cannot acknowledge success.
- Local durable JSON stage state records canonical, publication and verification
  separately. Only one unfinished executable batch per state directory; a file
  lock plus canonical DB lock excludes duplicate execution. No general queue or
  extra database service is introduced yet.
- A publication attempt that exits/gets interrupted without a valid receipt is
  uncertain. Resume uses an explicit reconciliation adapter rather than blindly
  repeating an unknown publication. Verified negative proof can permit retry;
  otherwise leave it pending for inspection. Verification failures preserve the
  successful publication and retry verification only.
- Commands use argument arrays, bounded subprocess groups, private files and
  target-specific configuration. The later AWS container can run the same
  contract against host-local databases; no SSH dependency in the generic runner.

## Work units and acceptance

| Unit | Deliverable | Verification |
| --- | --- | --- |
| A | Reviewed parser/collector packaging | Synthetic labels, malformed/ambiguous rows, required published links, size/time bounds, no database calls |
| B | Batch planning and canonical transaction receipt | Two-meet atomic apply, identity holds, changed-plan refusal, replay, rollback and commit-before-local-ack recovery in isolated PostgreSQL schemas |
| C | Publication/verification adapter contract | Combined IDs once; wrong/stale/missing receipt rejection; failed verifier retry; uncertain publisher reconciliation; owned-process timeout |
| D | Actual local SwimProfiles adapter and bounded exercise | Local reader checks, publication scope and evidence binding; run supported archived/fresh batches with accurate changed-vs-replay classification |
| E | Reproducibility and handoff | CI path filters, fresh worktree tests, code/document links, tested/merged/deployed status and next combined-load benchmark |

Milestone limitations: no continuous scheduling, worker leases/pool, automatic
retirement/final-file rules, universal PDF parser, automatic AWS deployment or
capacity guarantee. Those remain later experiments after this executable
foundation passes. Do not mistake a synthetic adapter test or unchanged real
replay for a live changed multi-competition publication benchmark.

## Delivery evidence — 8 November 2026

Implemented units A–D and local verification for E on the feature branch. The
[manual batch runbook](nrt-manual-batches.md) contains commands and recovery rules.
The real two-competition trial accepted 77 new PDF results with 12 identity holds,
published local generation 46 once, and passed independent facts/bests/rankings
and public-reader checks. Execution took 23.152 seconds; the external monitoring
envelope took 26.706 seconds. Replay changed nothing and did not republish.

The focused suite passes 29 tests, including isolated PostgreSQL transactions,
commit-before-ack recovery, publisher reconciliation, failed verification retries,
target/scope rejection and parser/collector boundaries. The earlier full suite
ran 188 tests: 161 passed and 27 unrelated database tests were skipped because
their separate fixture configuration was absent. Six focused tests were added
subsequently and passed. Synthetic test adapters do not prove AWS performance.
Development failures (file opener usage and a test-held relation lock) were fixed
and retained in local logs; database or website timeout limits were not raised.

The trial is local-only. AWS remains at last verified generation 40; canonical
meets 2218/2219 require explicit later AWS delivery. The private
`reports/nrt-milestone1/deferred-aws-delivery.json` records that obligation.
An unchanged subsequent PDF must not erase it. No cron or container was started.

Next milestones: establish a durable per-feed version/queue contract; test bounded
polling, recovery and queue age across several active competitions; benchmark a
matched standalone/combined workload; package and test the production-shaped
container locally before an explicitly bounded AWS rehearsal. Continuous
scheduling and automatic meet retirement are not implemented in this milestone.
