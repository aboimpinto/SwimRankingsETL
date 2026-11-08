# Manual live-result import and profile verification

For the packaged multi-competition implementation, use
[Manual multi competition PDF batches](nrt-manual-batches.md). This document
preserves the earlier single-meet trial; its private wrapper is historical.

For requirements, architecture concerns and the multi-weekend plan, start with
[Near real time swimming results](near-real-time-results-program.md). This runbook
contains the dated executable trial and measured evidence.

Owner decision, 8 November 2026: run one selected competition manually. Do not
install cron, resume an interval runner or infer scheduling permission from a
successful test.

Owner clarification: the timing thresholds apply to **live partial-result updates,
particularly PDFs**, so swimmers, coaches, parents and fans can see results and
rankings near real time:

- Under one minute: ideal.
- One through five minutes: acceptable.
- Over five through ten minutes: investigate and improve.
- Over ten minutes: unacceptable.

Measure the live import through publication and verification, not just download
or parsing. Separately record polling/discovery delay: fast processing after a
long wait does not deliver near-real-time results. Where the actual publication
time is unknown, label it unknown; document generation time is not upload time.
An unchanged download is not evidence of changed-result delivery speed.

**Final official LENEX imports are a separate workload.** They can contain the
whole competition plus richer details such as reactions, splits and relay/team
results. The owner has not assigned these live-update thresholds to final-file
imports. Continue measuring their performance and verifying correctness and
profile availability, but do not classify Malta's final-file import against the
PDF/live-update thresholds. Reconcile final-file detail with existing provisional
results without duplication or losing stronger evidence.

## Current executable

From the ETL checkout, preview the selected source:

```bash
python3 scripts/manual_live_import_test.py \
  --trial-dir reports/live-trial-2026-11-08 \
  --live-id 10783 \
  --pdf-url https://live.swimrankings.net/10783/ResultList_406.pdf
```

Add `--execute` for one authorized import-and-test. Omit `--pdf-url` to use the
normal LENEX collection path and configured bounded PDF fallback. Use a live ID
from the reviewed discovery file; do not guess source URLs. Explicit PDF URLs
must appear in the meet's published links. The collector refuses to silently
substitute LENEX when the selected PDF cannot be parsed.

This is an **operational trial wrapper**, not a portable installed ETL service.
It requires the existing private trial directory, reviewed `control.json`,
`discovered-all.json`, identity/source ledger, delivery scripts, configured SSH
alias, local pnpm/TypeScript app and current AWS import runner. Its configuration
has a same-day cutoff. Reuse on another date requires fresh discovery and an
explicit review of dates, parser coverage, runtime versions and delivery state.
The source tree and working files have not been packaged into a new release.

The trial directory contains these supporting implementations:

- `run-cycle.py`: canonical plan/apply, local cache, independent data/ranking
  checks, complete-meet AWS delivery, AWS cache and checks.
- `collect-lxf.py` / `pdf_fallback.py`: selected-only collection in manual mode;
  source archives and explicit PDF selection, including a PDF newer than a
  nonempty LENEX export.
- `french_pdf.py`: deterministic adapter for verified French Splash individual
  result layouts. German parsing is retained. Italian/other layouts are not
  automatically supported. No LLM extracts recurring results.
- `live-reader-verifier.ts`: fact/best/ranking comparison plus direct page,
  profile, current-season and archive checks for at most ten affected swimmers.

These supporting trial files and private evidence live under ignored `reports/`;
the wrapper alone is insufficient on a fresh checkout. Preserve that directory
until the tested components are deliberately integrated into the ETL package.

## Safety and evidence

The wrapper previews by default. Execution takes a manual lock, refuses an active
cycle/enabled controller or pending delivery, then performs baseline reader checks.
A bounded random sample is checked during and after the cycle. Every new sample
uses a recorded seed. It never enumerates all profiles. The web SQL timeout stays
at two seconds; an HTTP request over two seconds fails the trial even when it
ultimately returns data.

A reader failure prevents subsequent cycles. It does not kill an unrelated
process or discard a committed canonical import. Inspect the active transaction
and retained pending queues before recovery. `finally` disables the controller;
there is no scheduler. On abrupt termination, inspect locks/processes and control
state before reuse. Do not blindly restart or clear delivery state.

Store source, plan, canonical receipt, local cache publication, AWS publication,
reader comparisons and timing evidence separately. Unknown PDF identities remain
held; they are not guessed or created. PDF-only medal coverage remains explicitly
unverified. Partial sources do not remove unreported races or replace stronger
LENEX fields. AWS delivery uses the complete current canonical meet.

Output is under `<trial-dir>/manual-tests/<UTC timestamp>/`. `summary.json`
distinguishes `changed-publication`, `unchanged-replay`, `held-or-incomplete` and
`failed`. A successful exit means correctness/availability checks passed; inspect
`changedPublicationUnderOneMinute` for the separate speed target. An unchanged
replay must never be counted as a fast changed publication.

The collector and parser tests are currently in the private trial directory;
the wrapper outcome tests are in `tests/test_manual_live_import_test.py`.

## Measured Sunday trials

Both hosts used SwimProfiles v0.1.42 code. AWS is the existing 4 GB / 2 vCPU
Lightsail host with a 64 GB database disk reporting 192 IOPS. These were live
changed-data trials under reader load, not controlled cold-cache benchmarks or
proof of a steady-state cadence. Local hardware differs; compare each host's
measurements separately.

| Trial | Accepted new results | Pipeline including internal checks | Extra monitor baseline/final checks | Result |
| --- | ---: | ---: | ---: | --- |
| Malta 11448 official LENEX | 1,090 | 327.411 s | Separately recorded | Correct; separate final-file workload |
| Cossonay 10783, Sunday PDF event 406 | 8 | 88.790 s | 99.782 s total with wrapper checks | Correct; acceptable, above ideal |
| Same PDF replay | 0 | 1.317 s | 15.306 s total | No publication; not a speed benchmark |

Malta's 1,102 parsed rows included twelve held parsed rows. Cossonay had nine
parsed rows: eight accepted and one ambiguous identity held. The PDF is a partial source. A subsequent audit of the exact Malta file found
the meet and both sessions marked OFFICIAL, all 20 Sunday events with results,
and 18 Saturday events with results; the other two Saturday events had no
entries or results. The owner clarified that this is the official final export; the stored file
coverage supports that classification. No separate organizer confirmation was
fetched during the audit. The earlier
“partial LENEX” description confused our provisional import policy with source
completeness. Treat its timing as an initial whole-meet import benchmark, not a
small live-delta benchmark. Evidence: `malta-completeness-audit.json` in the
private trial directory.

Malta first-adoption metadata refresh flags were all true. AWS cache stage took
244.714 s; ranking membership insert statements totalled approximately 82 s,
best summaries 22.223 s and population/prefix refresh 51.177 s. SQL timings are
retained, but first-line query labels are insufficient to establish every query
plan. Do not present the bottleneck hypotheses as an EXPLAIN-verified fix.

Cossonay used the metadata fast path (all three refresh flags false):

- collection: 1.416 s; canonical plan/apply: 1.380 s;
- local cache plus its check hook: 14.789 s; independent local verifier: 2.518 s;
- AWS export: 3.801 s; canonical delivery: 5.566 s;
- AWS cache plus its check hook: 39.890 s; importer report: 34.211 s;
- within that importer, best summaries: 2.151 s; ranking populations: 1.270 s;
- other source/cache work, remote setup and independent verification account
  for the remaining time. Nested timers overlap; do not add them to totals.

The small changed batch refreshed 16 best-summary keys, changed twelve best
summaries and refreshed 65 ranking groups. It did not rebuild every swimmer.
Source metadata queries and club-attribution copying remain measurable fixed
costs. Optimize and benchmark those paths and delivery/verification overhead
before claiming a one-minute complete pipeline. Large changed-meet membership
and population costs require their own workload, not extrapolation from eight
races.

Reader evidence:

- Malta monitor: 565 requests, zero failures, maximum 1,361 ms. AWS publication
  overlap was observed; do not claim complete local-import overlap.
- PDF wrapper: 239 requests before/during/after, zero failures, maximum 604 ms.
- Replay wrapper: 89 requests, zero failures, maximum 699 ms.
- Additional affected-swimmer audit: all eight swimmers on each host, four
  page/data requests each (64 total), all passed. Both hosts also verified the
  eight facts, exact best summaries and 24 sampled national/European/dataset
  ranking groups without mismatches.

The direct affected-profile page checks were added after the changed PDF cycle
and executed separately after replay. They are now in the verifier for future
cycles; the 88.790 s measurement does not include this later addition.

Final checked publications: local 45 and AWS 40. Replay left both unchanged.
Pending local/AWS queues are empty; control is disabled; no cron was installed.
Sampling is evidence of observed availability, not proof for every profile.

Private receipt anchors under `reports/live-trial-2026-11-08/`:

- `cycles/20261108T102744Z/receipt.json` (LENEX).
- `cycles/20261108T104208Z/receipt.json` (PDF).
- `manual-tests/20261108T104202Z/summary.json` (PDF monitor).
- `manual-tests/20261108T104436Z/summary.json` (replay).
- `post-replay-affected-checks/` (affected-profile checks).

Follow-up: SwimProfiles issue #242 records this manual trial; #66 retains the
performance work. Neither scheduling nor a universal sub-minute guarantee is
accepted by these results.

## Sunday live publication observation, 12:05–12:07 Zurich

A separate manual read-only observation found 22 date-relevant competitions in
11 countries. Seventeen meet pages linked 341 result PDFs in total; this is
accumulated coverage, not an arrival rate. Two sweeps started two minutes apart.
No new PDF URLs appeared. Among seventeen fixed PDF samples (one highest-numbered
linked event per meet), two files changed bytes:

- Incukalns, Latvia, event 2: six new result rows appeared in the **same** PDF,
  explicitly labelled provisional results.
- Lagos, Portugal, event 7: only footer generation timestamps changed; extracted
  result content was unchanged.

This demonstrates active within-event publication and why link discovery alone
misses updates, while binary hashes alone can trigger unnecessary imports.
The existing semantic plan/dedup check must remain before database/cache work.
This limited two-minute sample is not an estimate of the entire site's arrivals
per second: 324 other linked PDFs were not checked for content revisions, and
individual upload timestamps were not observed. It also does not establish parser
support for the Latvian or Portuguese layouts. No imports or scheduler ran.

Private evidence and executable observer:
`reports/live-trial-2026-11-08/publication-observation/`.
At a hypothetical ninety seconds per standalone PDF publication, a serial worker
serves approximately forty batches per hour. Aggregate incoming changes must be
measured against that service rate; two-minute polling alone does not demonstrate
sufficient capacity. Bounded combined publications require their own benchmark.
