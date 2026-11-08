# Weekend live results experiment template

Copy this into a dated experiment note. Keep private source files and detailed
swimmer reports outside Git. Link the note from the [central program record](near-real-time-results-program.md)
and MemoryBank. Fill unknown values as unknown; never substitute estimates for
measurements. No field in this template enables a scheduler or authorizes writes.

## Scope and operating state

- Date, local timezone and UTC observation window:
- Question this experiment answers:
- Workload: live partial PDF / partial LENEX / final official LENEX / unchanged replay:
- Runtime: local direct / local container / bounded AWS container:
- Targets authorized for mutation:
- Source competitions, event coverage, parser/layout versions and exclusions:
- Supported PDF languages/layouts; unresolved identities:
- Baseline runtime versions, Git commits, migrations, backend and publication IDs:
- Existing jobs, locks, pending queues, cron/services and free disk reserve:
- Maximum duration, competitions, documents, rows, concurrency and batch bounds:
- Stop conditions and recovery owner:

## Hypothesis and comparison

- Expected improvement or correctness property:
- Baseline and candidate, with the same workload where possible:
- Variables changed; variables held fixed:
- Warm/cold state, profile traffic and other host activity:
- Local CPU/RAM/storage; AWS host/container limits and disk characteristics:
- Required semantic/source checks:
- Required random and affected-profile checks:

For live work, under one minute is ideal; up to five minutes acceptable; over five
through ten minutes requires improvement; over ten minutes unacceptable. Record
both processing time and first-observed-to-visible latency, with polling gaps.
Final official exports remain optimization targets but have a separate budget.

## Source and arrival evidence

| Competition/event | Source version/hash | First observed UTC | Known upload UTC | New/corrected/held rows | Coverage |
| --- | --- | --- | --- | --- | --- |
| | | | Unknown unless verified | | |

- Date-relevant competitions versus competitions observed publishing:
- Linked documents versus newly published documents versus same-URL revisions:
- Timestamp-only changes filtered out:
- Sampling coverage and unobserved documents:
- PDF generation time kept separate from upload/race/observation time:
- Raw/normalized evidence location and retention requirements:

## Timing ledger

| Run/batch | Download/parse | Queue wait | Canonical commit | App cache/rankings | Verification | Complete elapsed | Oldest unpublished age |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

- Results/documents/athletes/best keys/ranking groups changed:
- Metadata adoption or repair versus steady-state fast path:
- Local-to-AWS transfer costs, if applicable:
- Nested timers identified and excluded from additive totals:
- Slow statements, lock waits, safe query text/plans and evidence paths:
- CPU/memory/I/O/free-space/temporary/archive growth:
- Sample size, median/max and percentiles only when the sample supports them:
- Source upload time unknown: state first-observed latency rather than inventing NRT lag:

## Correctness and availability

- Canonical parity and identity/provenance:
- Partial absence/corrections/final enrichment behavior:
- Independent best/ranking comparisons, scopes and mismatches:
- Replay: zero duplicate inserts and expected publication behavior:
- Before/during/after random-profile observations:
- Affected-profile page, bests, season, archive and ranking observations:
- Failures including HTTP 200 error pages/stale data, timings and diagnostics:
- Source holds and valid data deliberately not imported:
- SQL timeout unchanged:

## Failure and recovery rehearsal

Choose cases appropriate to this experiment; do not inject faults into unrelated
production traffic merely to complete this section.

| Case exercised | Expected behavior | Observed behavior | Evidence | Follow-up |
| --- | --- | --- | --- | --- |
| Slow/unavailable source | Other competitions progress | | | |
| Duplicate/out-of-order source | No duplicate or stale overwrite | | | |
| Restart after canonical commit | Resume app publication safely | | | |
| Restart after app commit before acknowledgment | Reconcile receipt | | | |
| New results arrive during publication | Remain queued for next batch | | | |
| Competition ends with pending work | Reconcile, do not discard | | | |

## End state and decision

- Outcome: passed / failed / incomplete / held; speed outcome separate:
- Actual local and AWS publications and verification receipts:
- Pending jobs and unresolved holds:
- Owned processes stopped/running; controller flags; cron/service state:
- Code/config changed; tests run; merged/released status:
- Evidence archived, failures preserved, secrets/raw records excluded from Git:
- Central program/runbook/MemoryBank links updated:
- Next smallest experiment and the question it answers:
- Unattended operation remains disabled unless separately authorized:
