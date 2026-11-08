# First unattended weekend: local runner, AWS publication

Planning decision: 8 November 2026. Owner leaves Friday 13 November and confirms
this computer will remain at home, powered on and connected. Prepare for the
14–15 November competition weekend. Sophia's Bern meet name/link will be supplied
before departure; its absence does not block general preparation.

Status: implementation and readiness plan, not an enabled schedule. The previous
one-hour timer finished. No new imports, scheduler, Codex job or notifications
were started by writing this plan. The owner requested unattended preparation;
older manual-only notes describe earlier trials, not a prohibition on this work.

## Evidence and gaps

The [one-hour trial](nrt-hour-trial-results-2026-11-08.md) published 108 new results.
Changed cycles averaged 229 seconds and peaked at 239 seconds. Eleven starts
executed; one slot was skipped for manual recovery after a valid page took
2.382 seconds. There were no functional failures in 2,080 sampled requests.

Coverage is the main qualification: 23 competitions were observed, final sweep
477 PDFs, 384 held and 93 parsed. Actual new accepted results came from two meets.
This does not prove that all European competitions can be imported every five
minutes. Unsupported layouts and unresolved identities must stay visible.

Current finite timer stops after errors/overruns and needs explicit recovery.
Private cycle/AWS adapters still live under ignored reports with installation
paths. Neither is a complete unattended service. Package them into versioned,
tested entry points; do not install a cron command pointing at a disposable worktree.

## Proposed runtime

Use a pinned installation on the local computer, independent of this chat.
One systemd service owns a cycle; a five-minute calendar timer triggers it. This
is the proposed Linux supervision choice, not an installed unit. A service plus
timer provides lifecycle/logging; application receipts still determine success.

- A global lock prevents overlap across timer, manual runs and restart recovery.
  If a cycle crosses the next start, record a skipped slot, finish/reconcile its
  owned work, and take a fresh snapshot on a later tick. No catch-up process storm.
- Four bounded source collectors remain the initial local setting, with existing
  request throttles. One publisher per database preserves existing write locks.
  Do not scale writer count without correctness and reader-availability evidence.
- Persist per-meet discovery state, raw/semantic hashes, pending event versions,
  publication stages, retries and holds outside the install directory. Source
  fetch is not acknowledgement of publication. Reconcile uncertain commits first.
- Each cycle covers local SwimRankings, local SwimProfiles, AWS SwimRankings and
  AWS SwimProfiles, with independent receipts. Include other consumers only if
  explicitly added to the weekend scope; do not imply they were verified.
- Keep partial events additive; preserve corrections and authoritative LENEX
  provenance. Never delete absent swimmers from a partial PDF or guess identity.
- Use content-addressed local raw storage so unchanged PDFs are not copied again
  for every cycle. Retain replay files locally. Follow [AWS retention](source-file-retention.md).
- A separate deterministic watchdog checks heartbeat, last progress, pending age,
  stage state, space and sampled website reads. Process existence is insufficient.
  No model request when healthy.

## Discovery and coverage

Refresh calendar/live-index discovery at startup and periodically (proposed every
30 minutes), not from the fixed 8 November cohort. Poll active meet sources every
five minutes, including existing URLs whose PDF contents can change in place.
Use meet/session dates and timezones; include multi-day meets crossing midnight.

Discover all accessible competitions in the configured country/calendar coverage.
Report discovered, supported, unsupported, source-unavailable and identity-held
counts separately. A missing/blocked calendar is an incident, not an empty day.
A known unsupported PDF should not be reparsed every five minutes unless its bytes
or parser version changed. One bad source should not block healthy competitions.

Proposed finalization: scheduled end is not proof of final results. Continue active
checks until official final evidence is published, then reconcile the final LENEX
in a separate workload queue. Poll unresolved completed meets less often after an
explicit grace period; retain late-correction follow-ups. Exact grace/follow-up
windows must be set in configuration and tested before enabling the weekend.
Large final-file imports must not silently monopolize the live-results queue.

When supplied, verify Sophia's Bern meet is discovered, its available result
format parses, athlete matching is unambiguous, and local/AWS fact and ranking
checks pass. If no live sample exists before Friday, record coverage as unproven
and test the closest same-provider sample; do not call that live verification.

## Recovery policy to implement and test

These are proposed unattended rules. The earlier trial's manual stop/restart gate
must not be silently removed. Make the operational policy explicit before enabling.

| Condition | Proposed action |
| --- | --- |
| Temporary source/network failure | Bounded retry/backoff, record next retry, continue other meets; respect rate limits |
| Unsupported PDF or uncertain identity | Hold that document/result with reason; continue verified data; report coverage loss |
| AWS outage after local commit | Keep AWS delivery pending; reconcile/retry without reimporting or losing revision order |
| Single valid response above 2 s | Retain incident; automatically run the two independent rechecks previously done manually; resume only on passing checks |
| Functional profile failure, mismatch, repeated slow checks | Stop new publication to affected target; preserve evidence; diagnose and alert; never bypass failed checks |
| Cycle above 5 minutes | Finish/reconcile owned transaction; skip overlap; report breach and evaluate recovery gate before more publication |
| Repeated overrun or growing backlog | Alert and enter a bounded degraded state; do not spawn extra database writers |
| Hung worker or lost process | Verify ownership/leases and transaction state; terminate only owned work when safe, then reconcile receipts |
| Disk pressure | Stop adding raw work before exhaustion; alert; keep local replay archive and pending state intact |
| Restart/reboot | Reacquire lock, reconcile in-flight receipts, resume pending stages; no duplicate inserts or forgotten deliveries |

A watchdog should measure time since progress, not just process age. Configure
stage deadlines separately; five minutes is the cycle target, not an arbitrary
SQL kill timer. Retain the two-second web SQL limit and existing error evidence.

## Optional Codex incident investigator

Installed CLI exposes `codex exec`, read-only sandbox, JSON/schema output and
noninteractive operation. Official reference:
https://learn.chatgpt.com/docs/non-interactive-mode

Proposed flow: watchdog emits a compact incident bundle -> one bounded Codex exec
job diagnoses -> stores a structured report -> exits. Healthy runs use no LLM.
Deduplicate by incident fingerprint, impose a cooldown and a wall-time/run-count
budget; avoid launching another job while one is active. Authentication and
unattended execution must be tested under the actual service account.

Initially provide only sanitized logs/metrics/receipts, no production writer
credentials. Codex diagnosis must not be required for import or known recovery.
Automatic code edits, deployments, schema changes, raised timeouts or identity
merges are outside the initial investigator design. Tested deterministic recovery
handles known cases. If Codex is unavailable, the watchdog still records/alerts.

## Before-Friday sequence and acceptance evidence

1. Package current operational cycle/AWS/verification adapters into repository
   scripts, with explicit configuration, version pin and durable state paths.
2. Implement discovery refresh, pending-stage recovery, locking, watchdog and
   source/coverage accounting. Add service/timer templates and status/stop/replay
   commands. Keep an explicit emergency disable switch.
3. Test replay, corrections, mid-stage process failure, uncertain commit, SSH loss,
   malformed sources, low disk, overrun, stale heartbeat and safe recovery.
4. Run a multi-hour accelerated replay using saved PDFs, including changed results
   and multiple simultaneous meets. Clearly label synthetic arrivals; unchanged
   replay is not load proof. Measure complete local-to-AWS publication and readers.
5. Install on a stable path; test service-account credentials, unattended startup,
   host reboot, sleep prevention and restart recovery without an interactive login.
   Reboot/sleep changes must be coordinated with other work on this computer.
6. Verify alert delivery and an independent heartbeat observer before departure.
   A dead local machine cannot alert about its own failure; use a small independent
   AWS check/external observer, with no second importer. Choose phone-accessible
   alert/status route with the owner; none is configured or authorized to send yet.
7. Confirm Sophia's meet when supplied, inspect Friday capacity/space, review the
   exact runtime window/timezone/recovery policy, then enable the bounded weekend
   schedule. Freeze tested code for the weekend. Keep remote stop/status access.

Go/no-go: no data mismatches/duplicates or functional reader failures, tested
restart/replay recovery, sustained backlog that drains within available capacity,
five-minute changed-cycle target demonstrated for the supported workload, explicit
coverage holds, working notification route and adequate measured free-space
headroom. A failure means a documented limitation or smaller supported cohort,
not a promise to import all formats safely. No zero-incident guarantee.

Report per cycle: discovery/collection/import/publication/check timings; new and
corrected results; source holds; local/AWS generations and pending age; reader
failures/latency; disk growth; retry/recovery; next scheduled start. Distinguish
polling cadence, processing time and observed publication delay (potentially near
nine minutes with five-minute polling plus four-minute processing).

## Later AWS container

Reuse the same versioned runner/state contracts in a container after host-specific
capacity tests. AWS has constrained I/O and web traffic; local timing cannot prove
cloud capacity. Persistent receipts/queue survive container replacement; raw files
are temporary after successful verification. Prevent dual local/AWS ownership at
cutover. Keep local replay archival explicit. Containerization is a deployment
step, not a performance guarantee or a prerequisite for the first local weekend.
