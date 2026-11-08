# Manual multi competition PDF batches

Canonical resume context: [weekend handoff](../MemoryBank/handoff-nrt-unattended-weekend-2026-11-08.md) on `main`. Historical worktree report paths below have a verified copy under `reports/nrt-worktree-archive-2026-11-08/` in this checkout.

Raw source policy: [local retention / AWS cleanup](source-file-retention.md). Keep local replay files; AWS raw inputs are temporary.

Latest owner gate and expansion evidence: [8 November bounded expansion](nrt-expansion-2026-11-08.md). Under 60 s ideal, 60–180 s acceptable; stop expansion and request direction above 180 s.

This milestone provides reusable code for collection, canonical import, one
combined SwimProfiles publication, and independent verification. It is a manual
runner, not a continuously running orchestrator. The [implementation record](nrt-implementation-milestone-1.md)
and [program](near-real-time-results-program.md) distinguish later work.

## Installation and configuration

Use Python 3.10+ on Linux, existing PostgreSQL, `requirements-delivery.txt` and
Poppler `pdftotext` for real PDFs. The actual app adapter also needs a configured
SwimProfiles checkout with pnpm/tsx, the existing `run-import-job.sh` and public
profile checker, and a running website. It uses that checkout's environment
loader and database roles. No dated trial-directory code is needed.

Copy `config/nrt-local.example.json` to a private configuration path. Adjust its
relative paths for that location: `canonical.configFile` and adapter `cwd` are
relative to the configuration file; adapter arguments are relative to `cwd`.
Set the explicit canonical host, port, database/schema, application checkout and
website URL. The canonical credential file is a psycopg2 connection-parameter
JSON. Application credentials stay in the app's configured environment. Never
commit real credentials or private batch files.

The default example accepts at most five competition reports and 5,000 parsed
rows. These are conservative experiment bounds, not demonstrated capacity. The
collector accepts 1–8 explicitly selected PDFs per competition, downloads with
bounded time/size and checks that each URL is actually published by that meet.

## Collect and preview

### Measure the actual multi-meet delta first

`nrt_delta_observe.py` performs one read-only observation of all linked event PDFs
in a saved cohort (the JSON list returned by `live_result_sources.discover`,
filtered to the relevant dates). It uses at most four collection processes,
one request start per second per process, bounded downloads/parsing and a shared
time budget. It does not import results or install a scheduler.

```bash
python3 scripts/nrt_delta_observe.py --meets reports/cohort.json \
  --output reports/delta/baseline --workers 4
python3 scripts/nrt_delta_observe.py --meets reports/cohort.json \
  --previous reports/delta/baseline/observation.json \
  --output reports/delta/next --delta-output reports/delta/next-sources --workers 4
```

Each output directory is new and private. The first pass establishes observation
state; its rows are not evidence of a live delta and may be unimported backlog.
The next pass separates unchanged bytes, footer-only changes, added/corrected
results, disappeared rows, first observations and held/failed documents. A
disappeared row never authorizes deletion. First observations must be reviewed
against previous link coverage before treating them as newly published results.
Unsupported documents are coverage gaps, not zero-result competitions.

The optional `--delta-output` stages only added/corrected rows with their checked
raw evidence. A newly linked PDF is eligible for staging only when the previous
competition page was successfully observed and did not link it. Recovered or newly
supported baseline documents stay excluded from live-delta staging. Cross-document
identity overlap is held. The emitted `delta.json` is **not** a database receipt:
preview its sources with `nrt_batch.py plan` before using the existing monitored
local/AWS execution path. Persist delivery receipts independently of observation
state; a later unchanged source does not acknowledge earlier pending delivery.

For a changed import trial, canonical preview still determines the actual
database delta and protects stronger evidence/identity rules. Record full
collection + preview + publication + verification time. Do not import unobserved
baseline rows as though they arrived in this interval, and do not present an
unchanged observation as proof of changed-import throughput. A 22-meet cohort
with twenty new swims is a different workload from initializing 22 meets.

### Selected-document import

First discover current published live IDs/links using the existing source tools.
Use actual source URLs; the examples below use placeholders intentionally.

```bash
python3 scripts/nrt_pdf_collect.py \
  --live-id LIVE_ID_A --pdf-url PUBLISHED_PDF_URL_A \
  --output reports/nrt-test/source-a
python3 scripts/nrt_pdf_collect.py \
  --live-id LIVE_ID_B --pdf-url PUBLISHED_PDF_URL_B \
  --output reports/nrt-test/source-b

python3 scripts/nrt_batch.py plan \
  --config .secrets/nrt.json --state-dir reports/nrt-test/state \
  --source reports/nrt-test/source-a/source.json \
  --source reports/nrt-test/source-b/source.json
```

`plan` reads canonical data and writes a private immutable manifest; it does not
create canonical tables or import races. Inspect counts, holds and eligibility.
Without `--allow-identity-holds`, any identity hold prevents that competition
from being applied while an unrelated eligible competition may proceed. With
that explicit option, only known identity-hold classes can be excluded while
eligible rows import. Structural conflicts never become automatically eligible.
Each competition appears once per batch. To select multiple distinct events,
repeat `--pdf-url` at collection; overlapping same-event PDFs are held rather
than choosing an arbitrary winner. Unknown/ambiguous PDF swimmers are not created.

The archived source bytes, row provenance, normalized report, configuration and
read-only plans bind the batch. Raw hashes can differ when only a footer changes;
the semantic digest and canonical plan distinguish this from changed swim data.
Malformed/unsupported documents remain explicit holds. An exit code of zero from
a collector does not establish complete meet coverage or resolved identities.

## Execute and inspect

```bash
python3 scripts/nrt_batch.py run \
  --config .secrets/nrt.json --state-dir reports/nrt-test/state \
  --batch BATCH_ID --execute
python3 scripts/nrt_batch.py status \
  --state-dir reports/nrt-test/state --batch BATCH_ID
```

Without `--execute`, `run` only reports existing state. Execution holds the runner
lock and canonical advisory lock, verifies the preview and applies eligible
competitions in one canonical transaction. `live_result_batches` is created
idempotently from the migration SQL inside this explicit write transaction; its
receipt commits alongside the results. No new database server is created.

The application adapter receives the union of changed canonical meet IDs once.
It invokes the existing SwimProfiles importer and validates its commit receipt
and selected-meet scope. This first milestone accepts PDFs only; final LENEX
continues through its existing workflow. PDF-only whole-meet medal evidence is
explicitly unavailable rather than fabricated.

A separate verifier compares canonical facts, best summaries and sampled ranking
groups to app data, checks up to ten affected profile page/data sets and samples
five unrelated profiles. Public HTTP requests over two seconds fail verification;
the web SQL timeout is unchanged. The broader experiment can add an external
before/during monitor; the adapter itself performs post-publication verification.

Statuses:

| Status | Meaning |
| --- | --- |
| `planned` | Preview only; no canonical commit |
| `canonical-running` | Canonical operation started or outcome needs recovery |
| `canonical-committed` | Durable source commit; app still pending |
| `publication-running` | App attempt started; missing receipt means uncertain outcome |
| `published` / `verification-running` | App receipt exists; checks still pending or failed |
| `verified` / `verified-with-holds` | Accepted publication passed checks; coverage explicitly reports excluded holds |
| `unchanged` / `unchanged-with-holds` | No canonical semantic changes, no app publication; not a fresh website acceptance run |
| `held` | No publishable changes; inspect source/identity evidence |
| `abandoned` | Canonical non-commit was checked and the stale uncommitted plan retired |

The CLI reports `coverage`, stages, publication and last error. Full private
receipts are in `state/batches/BATCH_ID/`. A successful partial publication is not
proof that held identities or unsupported documents were resolved.

## Recovery

Run the same batch again after resolving the cause. Canonical recovery reads the
same-transaction batch receipt, so a crash after commit cannot duplicate races.
A failed verifier retries verification without reimporting/republishing. A newer
batch cannot run while another executable batch remains unfinished in that state
directory. Do not run parallel state directories against the same logical feed
as a way to bypass this ordering; DB locks serialize writes but are not a global
cross-runner source-version queue. That queue is later work.

A missing/invalid publisher receipt leaves `publication-running`. The next run
calls the configured reconciliation adapter. The included app adapter checks
that its job lock is free and looks for a committed publication receipt in this
batch's own job directory. If none exists it refuses to guess rollback. Inspect
owned processes, logs and database/app receipts; do not blindly clear state or
start another import. A future reconciliation implementation may return explicit
`not-published`/`safeToRetry` proof; elapsed silence is never that proof.

If canonical data changed after preview and **no canonical commit occurred**,
retire the stale plan explicitly and create a fresh preview:

```bash
python3 scripts/nrt_batch.py abandon \
  --config .secrets/nrt.json --state-dir reports/nrt-test/state \
  --batch BATCH_ID --execute
```

The command takes the canonical lock and checks the database receipt. It refuses
to abandon committed work, including a commit whose local acknowledgment was
lost. It is not a rollback or a way to bypass failed verification.

Adapter processes have time bounds and owned process-group termination. The
runner is not yet a complete process supervisor: SIGKILL/host crashes require
receipt/lock reconciliation, and hung grandchildren or remote work must never
be assumed stopped merely because the parent exited. Keep a durable state volume
when containerizing this contract.

## Verified local experiment on 8 November

Two freshly collected Sunday event PDFs: Cossonay 10783 event 407 and Petit-Lancy
11365 event 15. Parsed 89 rows, accepted 77 new results, held twelve unresolved
identities. Local canonical and app only; AWS was not written by this exercise.

| Stage | Elapsed |
| --- | ---: |
| PDF collection per source, excluding index discovery | 1.087 s / 1.073 s |
| Canonical transaction including durable batch receipt | 3.225 s |
| Combined app publication adapter | 13.487 s |
| Independent verification adapter | 6.430 s |
| Batch execution | 23.152 s |
| External baseline/during/final monitoring envelope | 26.706 s |

Collection and preview were separate manual operations, so 23.152 s is not a
source-upload-to-visible latency. It is also not an AWS result or a matched
standalone-vs-batched speedup. One local publication (46) covered both meets.
Independent verification matched all 85 stored races across them, including eight
previously stored races, with zero best/ranking mismatches. The verifier checked
89 page/ranking requests; the external random monitor made another 89 requests,
zero failures, maximum 536 ms. Repeat planning/execution yielded
`unchanged-with-holds`, zero changed meets, twelve retained holds and no publication.

Private evidence in the implementation worktree: `reports/nrt-milestone1/`, first
batch `e9ea643ae2c8408ea17e7a6f76590f5c`, replay
`cb1d54826fdf41b6a0a998cc702c03cd`. Logs preserve failed development checks as well
as passing runs. The isolated-schema test suite does not modify shared fixture
or user data.

**AWS is intentionally behind this local-only experiment.** The last verified AWS
publication remains 40. `deferred-aws-delivery.json` records complete canonical
meets 2218/2219 for later explicit reconciliation. An unchanged future PDF poll
must not be mistaken for proof of AWS delivery. Do not claim all databases synced.

The new runner/adapter are worktree implementation until PR integration/release
is recorded. Continuous orchestration, a Docker image, durable scheduling,
multilingual expansion and sustained capacity evidence remain later milestones.
