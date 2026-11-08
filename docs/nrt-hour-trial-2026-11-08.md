# Five-minute cadence trial — 8 November 2026

The owner explicitly authorized a one-hour run, starting an import every five
minutes and evaluating whether the active-cohort deltas fit within five minutes.
This supersedes the previous three-minute stop gate for this bounded experiment.
No permanent cron, service or recurring schedule is installed.

## Running contract

- Window: 14:41:54–15:41:54 UTC (15:41:54–16:41:54 Zurich).
- Twelve planned starts at offsets 0, 300, …, 3300 seconds. No thirteenth start.
- Cohort: all 23 saved date-relevant competitions (earlier discussion used 22).
- Four source-collection processes, one request start/second/process; one
  database publisher. Entire cycles are serialized; no overlapping writes.
- A five-minute overrun finishes its owned operation/verification, then stops
  further starts for direction. Profile failures or uncertain delivery also stop
  further starts; committed results are never called rolled back without proof.
- Every changed cycle executes local canonical import, local SwimProfiles
  publication/checks, AWS canonical delivery, AWS publication/checks. Unchanged
  cycles skip publication and still sample local/AWS public profiles.
- Existing two-second reader checks remain unchanged. Parser/identity holds are
  reported and excluded, not silently treated as complete competition coverage.

The observer compares against a **fixed pre-trial source anchor**. This avoids
acknowledging pending data merely because another observation completed. Candidate
rows are cumulative since that anchor; the canonical preview determines what is
actually new/corrected each cycle and skips already imported facts. Report these
different counts separately. A future rolling acknowledged cursor must preserve
the same delivery/hold semantics; it is not implied by this experiment.

## Scripts and operation

`scripts/nrt_timed_trial.py` provides the finite cadence, exclusive trial lock,
serialized command invocation, durable progress, per-cycle receipts, timing gate
and aggregate report. It requires an explicit `--execute`. The command JSON is an
argv array containing `{cycle_dir}` and optionally `{index}` placeholders.

```bash
python3 scripts/nrt_timed_trial.py \
  --command-json reports/nrt-hour-trial-2026-11-08/command.json \
  --output reports/nrt-hour-trial-2026-11-08/NEW_RUN_DIRECTORY \
  --duration-seconds 3600 --interval-seconds 300 --gate-seconds 300 --execute
```

The reviewed private cycle adapter is
`reports/nrt-hour-trial-2026-11-08/cycle.py`; its config increases only the meet
limit to 25. The existing local/AWS adapter accepts explicit `NRT_CONFIG` and
`NRT_MAX_CYCLE_SECONDS=300`; its default remains 180. These private adapters still
depend on the configured operational host and paths. A generic timer is not a
deployable AWS orchestrator or a fresh-checkout production integration.

Private state: worktree `reports/nrt-hour-trial-2026-11-08/run-02/trial.json`;
per-cycle observations, staged deltas, plans, logs and receipts below that run.
Publication evidence remains in canonical ETL
`reports/nrt-expansion-2026-11-08/hour-run-02-cycle-NN/`. Pending deliveries remain
in that canonical operational folder's `state.json`, independently of the timer.

The first startup attempt (`run-01`) stopped before database writes: Python's
worker startup re-executed the unguarded private entry point. Adding its main
guard fixed initialization; preserve the failed attempt separately from the
one-hour trial. Do not count its 123 ms as a successful no-change cycle.

## Final report requirements

Report each cycle's actual start, start lag, collection time, changed rows,
corrections, already-imported rows, held identities/documents, local/AWS stages,
published generations, verification counts/failures and total elapsed time.
Separate changed and unchanged timing distributions. Give total actual inserts
and corrections, not sums of cumulative candidates. Report unique held documents
separately from repeated observations of the same hold. State pending delivery,
coverage gaps, skipped starts, disk growth and the explicit end of the timer.

The completed outcome is pending while the trial runs. Do not infer success from
a live process, an unchanged source or an unfinished `trial.json`.

## Response-time incident during cycle 5

Cycle 5 published 48 new results at local 55 / AWS 50 in 235.676 seconds. One
random AWS profile page returned valid HTTP 200 content in 2,382 ms. This was a
response-time violation, not a missing profile or failed SQL response. The other
requests passed functional checks. The monitor retained the violation and the
timer stopped new starts; both delivery queues were already clear.

A repeat of the same three-profile sample passed (14 requests, maximum 1,520 ms),
and a fresh sample passed (15 requests, maximum 258 ms). Application container
logs for the incident interval were empty. The exact responsible SQL statement
is therefore not established; successful warm rechecks do not prove a root-cause
fix. Private evidence: canonical ETL
`reports/nrt-expansion-2026-11-08/hour-reader-incident-05/`.

The bounded trial resumed only after these checks, retaining the original start,
end, limits and failed cycle. Slot 6 was skipped, rather than starting overlapping
catch-up work. `--resume-after-checks` requires two positive reader receipts and
rejects attempts to change the cadence/duration/threshold. The final trial status
must distinguish completion with incidents from an entirely passing run. The
application and import algorithms were unchanged; only finite-timer recovery was
added, with a regression check preserving the original failure. No claim is made
that the transient latency cause has been fixed.
