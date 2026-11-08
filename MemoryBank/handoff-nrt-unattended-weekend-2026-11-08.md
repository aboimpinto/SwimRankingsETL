# Handoff: unattended five-minute live-result imports

Written 8 November 2026, Europe/Zurich. Read this first when Paulo returns before
Friday. This records the end of this conversation; it does not start any work in
the background. Dates, generations and availability below are dated evidence,
not guarantees about the system at the next session.

## Owner request and confirmed decisions

Paulo is taking Sophia to a competition in Kanton Bern and leaves Friday
13 November. Prepare imports for the 14–15 November weekend while he is away.

- **Confirmed:** this computer remains at home, powered on and connected. First
  unattended weekend runs locally and publishes to AWS. AWS-container operation
  is a later stage, after its own capacity test.
- Refresh active competitions every **five minutes**, discover the day's meets
  rather than reuse Sunday's saved list, import only genuine changes, update
  SwimRankings and SwimProfiles rankings, and verify the websites still work.
- Bern meet name/live-results link is not known yet. Paulo will provide it before
  leaving. Do not repeatedly ask now or block general preparation on it.
- Raw `.lxf`/PDF files stay **locally** for replay/tests. AWS raw sources are
  temporary and removed after successful import/publication. Local expiry is
  not decided; do not delete local archives to save space without that decision.
- Avoid LLM-driven parsing/imports and token-heavy monitoring. Paulo suggested a
  scheduled Codex check that exits when done. Proposed design: deterministic
  watchdog, no LLM when healthy, bounded Codex diagnosis only for persistent
  incidents. This is not an installed or accepted autonomous repair system.
- No duplicate swims; partial PDFs can update an event in place. Keep ambiguous
  identities/unsupported sources held. Never downgrade richer final LENEX data.
- Do not raise the two-second web SQL timeout to mask publication problems.
- No subagents. Preserve unrelated work and private credentials.

Paulo explicitly said he will return before Friday and requested this handoff.
Do not interpret the handoff as a request to run new imports or leave a job running
until his return. The next session should resume preparation from the plan.

## Read in this order

1. This handoff.
2. [First unattended weekend plan](../docs/nrt-unattended-weekend-plan.md): proposed
   runtime, recovery rules, preflight gates and sequence before Friday.
3. [Completed one-hour report](../docs/nrt-hour-trial-results-2026-11-08.md).
4. [Trial contract and incident](../docs/nrt-hour-trial-2026-11-08.md).
5. [Raw-source retention](../docs/source-file-retention.md).
6. [Central engineering record](../docs/near-real-time-results-program.md) and
   [manual batch runbook](../docs/nrt-manual-batches.md).

Older blocks saying AWS 40/local 46 or work awaiting a three-minute gate are
historical. Use the completed trial and this handoff for the latest checkpoint.

## Checkouts, commits and PR

| Location | State/purpose at handoff |
| --- | --- |
| `~/myWork/SwimRankingsETL-worktrees/nrt-manual-batch` | Implementation worktree, branch `feat/nrt-manual-batch`, based on ETL `main` |
| `~/myWork/SwimRankingsETL` | Canonical operational checkout, branch `feat/split-history-index`, many unrelated dirty files; do not reset/switch/blanket-commit |
| `~/myWork/AboimPintoConsulting/SwimProfiles` | App checkout, unrelated local changes; deployed app last checked as `SwimProfiles-v0.1.42` |

[ETL PR 43](https://github.com/aboimpinto/SwimRankingsETL/pull/43) is OPEN,
non-draft and not merged at handoff. Head before this handoff: `d92e863`.
All four checks on that head passed: records, database-free-preview,
postgres-contract, canonical-and-adapter-contract. Recheck after any new commit.
Do not describe a pushed PR as merged or all its code as deployed.

Relevant commits:
- `8eca397`: completed one-hour report.
- `a4c1ff0`: source-retention policy, tested AWS records cleanup.
- `d92e863`: unattended-weekend plan, MemoryBank context correction.

Changes to the AWS records shell entry points were installed directly and verified
against `a4c1ff0`. The NRT orchestrator/container has not been deployed. Preserve
this distinction when merging/releasing PR 43. Repo workflow is Linux/bash; use
GitHub CLI and sign public GitHub messages with Paulo Aboim Pinto.

## Measured trial, not a promise of full coverage

Window: 8 November **14:41:54–15:41:54 UTC**, 15:41:54–16:41:54 Zurich.

| Metric | Outcome |
| --- | --- |
| Planned / executed starts | 12 / 11; slot 6 skipped during recovery |
| Changed / unchanged cycles | 7 / 4 |
| New results | 108: Cossonay live10783 = 86; Petit-Lancy live11365 = 22 |
| Corrections | 0 |
| Changed-cycle mean / max | 229.152 s / 238.728 s |
| Unchanged-cycle mean | 131.626 s |
| Collection | 118.173–124.272 s; about two minutes before publication work |
| Public checks | 2,080 requests; zero functional failures, one 2.382 s valid response |
| Final publication | local 58 / AWS 53; pending local false, pending AWS empty |
| Trial status | `completed-with-incidents`; timer exited |

23 date-relevant competitions were observed (earlier chat said 22). Last sweep:
477 PDFs, 384 held, 93 parsed; 22 meets had PDFs, one did not. New results were
accepted from only two meets. Bratislava live10705 ended with 16 held PDFs due to
meet-name mismatch. Final preview had eight unresolved result identity holds.
Repeated holds do not imply distinct swimmers. Capacity for all competitions
publishing supported changes simultaneously remains unproven.

A five-minute polling interval plus four-minute processing can mean roughly nine
minutes from source publication to visibility. Report cadence, processing time,
queue age and end-to-end freshness separately. Final official LENEX imports are
a separate, potentially heavier workload than partial PDFs.

## Incident and recovery lessons

Cycle 5 committed 48 new results, then one sampled AWS page returned valid HTTP
200 content in 2.382 s. It was a latency violation, not missing data or proof of
SQL failure. The strict monitor stopped further starts. A same-seed 14-request
recheck (max 1.520 s) and fresh 15-request recheck (max 0.258 s) passed; the finite
timer resumed within its original hour and skipped slot 6. No rollback occurred.

The exact slow page SQL was not captured; app logs for that interval were empty.
Host samples showed disk busy 80.5%, iowait 30.5% and CPU steal 13.2–25.5% around
that period. These suggest contention but do not prove the root cause. Slow import
queries have timings, sometimes generic labels; do not claim full SQL diagnosis.
The finite timer's tested resume is not yet an automatic unattended recovery loop.

## Existing code and private operational evidence

Worktree paths, relative to `SwimRankingsETL-worktrees/nrt-manual-batch/`:
- `scripts/nrt_timed_trial.py`: finite timer, lock, receipt, gate and explicit
  resume-after-checks. Not a continuous discovery/orchestration service.
- `scripts/nrt_delta_observe.py`, `scripts/nrt_batch.py`: observation, staging,
  idempotent manual batch foundation. See runbook for adapters and config.
- `reports/nrt-hour-trial-2026-11-08/run-02/trial.json`: definitive hour ledger.
- Same directory `analysis.json`, per-cycle data, disk first/last samples.
- `reports/nrt-hour-trial-2026-11-08/cycle.py`, `command.json`, `config.json`:
  private trial adapter/config. Startup needs a Python main guard; run-01 failed
  before writes without it. Do not count that startup as a successful cycle.

Canonical ETL paths, relative to `SwimRankingsETL/`:
- `reports/nrt-expansion-2026-11-08/run-selected-batch.py`: operational local/AWS
  wrapper; `NRT_MAX_CYCLE_SECONDS` defaults to 180, trial explicitly used 300.
- Same directory `deliver-aws.py`, `verify-readers.py`, `sample-aws.py` and
  `live-reader-verifier.ts`: private delivery/check/measurement adapters.
- Same directory `state.json`: pending and applied delivery state. Do not reset.
- Same directory `control.json`: checked at handoff, `enabled=false`,
  `manualOnly=true`, old `intervalSeconds=1200`. It is NOT an enabled five-minute
  schedule; do not enable it blindly to satisfy the new plan.
- Same directory `hour-run-02-cycle-NN/`: AWS stage receipts and monitor evidence.
- Same directory `hour-reader-incident-05/rechecks.json`: actual recovery checks.
- `reports/aws-source-retention-2026-11-08/`: local backups, SHA manifest and
  cleanup result/scripts for legacy AWS sources.

`reports/` content is private/ignored, not shipped by the PR. Preserve it and the
worktree until the adapters are packaged and evidence has a durable home. Do not
copy raw swimmer reports or credentials into Git. The trial observer uses a fixed
pre-trial anchor (observation-02 in the delta-cohort evidence), yielding cumulative
candidates. Canonical planning filters genuine new facts. A rolling cursor must
acknowledge successful publication, never merely successful observation.

## AWS and storage

SSH alias: `aws-swimming-delivery`. Delivery root `/opt/swimrankings-delivery`;
app/job root `/opt/swimprofiles`; app import runner
`/opt/swimprofiles/scripts/run-import-job.sh`. Private credentials are configured
on host; use those paths without printing environment/config contents.

Last infrastructure evidence: 4 GB RAM, two vCPUs, 64 GB DB disk with allocated
192 IOPS. End-of-hour free space: root about 4.47 GiB (95% used), DB volume about
14.69 GiB, media about 1.64 GiB. Refresh these numbers before scheduling. Root
space was already tight before the trial; this was not 888 MiB of new AWS PDFs.

Approximately 888 MiB trial evidence was LOCAL, with 5,174 archived PDF copies
and 535 distinct hash filenames (~94.3 MiB unique PDF bytes). This motivates
content-addressed local archival; no local deletion was authorized or performed.

Current NRT sends normalized `.json.gz` packages and JSON evidence to AWS, not
raw PDF/LXF. Raw cleanup does not authorize deletion of normalized revision chains.
65 legacy AWS LXF files (808,904 bytes) were archived locally, hash-verified and
removed from inspected records/review roots. AWS cleanup receipt:
`/opt/swimrankings-delivery/records/source-cleanup-20261108.json`.
No raw files remained in the audited paths; this was not a whole-host file audit.

Installed records entry points under
`/opt/swimrankings-delivery/record-refresh/ops/` remove successful run-owned raw
sources and matching input-directory copies. JSON/hashes/receipts stay. Failed
runs/previews keep temporary inputs for recovery. Twelve pipeline tests passed;
all four PR CI checks subsequently passed. NRT's current batch loader requires
raw files even for terminal replay: implement receipt-only terminal recovery
before moving it to an ephemeral AWS raw-source directory.

## Resume actions in order

1. Re-read this handoff and weekend plan; inspect branches/dirty state/PR checks,
   current pending receipts and processes. Do not rerun the expired hour command.
2. Package private operational adapters into tested repository entry points with
   explicit config and durable state. Select a stable installation outside a
   temporary worktree. Resolve merge/release state deliberately.
3. Implement fresh daily discovery, per-meet holds/retries, durable stage recovery,
   one-writer locks, overrun handling, watchdog, status report and emergency stop.
4. Prepare systemd service/timer templates (five-minute cadence) and test startup
   credentials, noninteractive operation, reboot/restart and sleep prevention.
   Coordinate host reboot/power changes; do not disrupt unrelated work casually.
5. Implement safe automatic rechecks/recovery for known incidents. Do not silently
   disable the earlier stop gates: agree the unattended policy before enabling.
6. Exercise saved-PDF synthetic arrival/replay, corrections, process death,
   uncertain commit, SSH outage, malformed PDF, low disk, stale heartbeat,
   concurrent launch and overrun. Run several hours with local/AWS reader checks.
7. Configure and test an owner-selected phone alert/status route and an independent
   heartbeat observer (AWS/external) for local power/network loss. No messages or
   notification integration has been configured/sent/authorized yet.
8. Verify Bern meet coverage when supplied. Set explicit operating dates/hours,
   timezone, final-results grace/follow-up windows and resource thresholds.
9. Enable only the tested weekend configuration, record installed commit/config,
   verify first real cycle and leave rollback/stop instructions and visible status.

Proposed Codex support: `codex exec` is available locally and supports bounded
noninteractive diagnosis with structured output. Healthy watchdog checks need no
LLM. Deduplicate incidents, cap run duration/count and avoid overlapping agents.
Initially consume sanitized evidence without database writer credentials; no
automatic deployments, schema changes, identity guesses or timeout increases.
Account/service authentication still needs testing. Reference:
https://learn.chatgpt.com/docs/non-interactive-mode

## Still needed from Paulo / not yet decided

- Bern competition name or URL: promised before departure; do not ask repeatedly.
- Notification destination/channel and remote status access.
- Exact schedule window and unattended recovery/overrun escalation policy.
- Whether optional Codex incident diagnosis is wanted for the first weekend.

The plan is to reduce dependence on Paulo being available, not to promise that
all source formats work or that failures cannot occur. Safe recovery, clear
coverage and reliable alerts are the readiness criteria. No continuous import,
watchdog, external heartbeat or Codex schedule was installed in this session.
