# One-hour live-delta trial results — 8 November 2026

Window: **15:41:54–16:41:54 Europe/Zurich**. The timer exited automatically after
one hour. No permanent cron/service was installed. Final status:
**completed with incidents**, not an entirely passing run.

## Outcome

- **108 new results** published to local and AWS: Cossonay 86, Petit-Lancy 22.
- **0 corrections** and 0 provenance-only updates; already imported results were skipped.
- Local SwimProfiles generation **58**; AWS generation **53**. Both delivery queues clear.
- **11 executed cycles**, seven with changes and four unchanged. Slot 6 was skipped during reader-incident recovery.
- **All 11 executed cycles below five minutes**; no overlapping cycles or database publishers.
- **2,080 sampled profile requests**, zero functional failures, one response over two seconds.
- Coverage remains partial: all 23 saved competitions checked, but not all PDFs could be parsed safely.

## Every scheduled slot

| Slot | Start (Zurich) | New results | Total time | Outcome |
| --- | --- | ---: | ---: | --- |
| 1 | 15:41:54 | 22 | 3m46s | Published and verified |
| 2 | 15:46:54 | 1 | 3m42s | Published and verified |
| 3 | 15:51:54 | 0 | 2m06s | Unchanged; readers passed |
| 4 | 15:56:54 | 7 | 3m43s | Published and verified |
| 5 | 16:01:54 | 48 | 3m56s | Published; one 2.382 s response |
| 6 | 16:06:54 | — | — | Skipped during recovery |
| 7 | 16:11:54 | 1 | 3m47s | Published and verified |
| 8 | 16:16:54 | 27 | 3m59s | Published and verified |
| 9 | 16:21:54 | 0 | 2m13s | Unchanged; readers passed |
| 10 | 16:26:54 | 0 | 2m13s | Unchanged; readers passed |
| 11 | 16:31:54 | 2 | 3m51s | Published and verified |
| 12 | 16:36:54 | 0 | 2m14s | Unchanged; readers passed |

First-cycle inserts include catch-up since the preceding observation. Subsequent
cycles represent later changes. Candidate rows were cumulative against a fixed
pre-trial anchor; totals above count actual canonical inserts, not candidates.
One source document can change only its footer; that is not a new swim.

## Timing and public readers

- Mean changed cycle: **3m49s**; slowest: **3m59s**.
- Mean unchanged cycle: **2m12s**; all-cycle mean: **3m14s**.
- Collection: 118.173–124.272 seconds per cycle, mean 121.221 seconds.
- AWS cache invocation on changed cycles: 39.378–51.023 seconds.
- AWS independent reader stage: 14.904–19.577 seconds.
- Nested stage times are already included in cycle totals. Do not add them twice.
- These are processing times, not source-upload-to-visible guarantees. Upload time is unknown; polling can add waiting before observation.

| Sampled target | Requests | Median | p95 | p99 | Maximum | Functional failures | >2 seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local | 1042 | 23 ms | 107 ms | 139 ms | 169 ms | 0 | 0 |
| aws | 1038 | 74 ms | 558 ms | 992 ms | 2382 ms | 0 | 1 |
| combined | 2080 | 44 ms | 427 ms | 806 ms | 2382 ms | 0 | 1 |

Cycle 5 returned valid HTTP 200 profile content in 2,382 ms during import. The
same sample later passed at a maximum 1,520 ms; a fresh sample passed at 258 ms.
These extra 29 diagnostic requests are outside the 2,080 trial count. The timer
resumed after positive rechecks, preserving the original window, limits, failure
and skipped slot. No web SQL timeout or reader latency limit was increased.

Host samples around the slow response recorded increased disk activity, I/O wait
and CPU steal while the cache import was running. This supports investigating
contention; it does not prove the exact cause. No application error log appeared
for that interval. The responsible web SQL statement was not captured. Import
query timings are retained, including a 6.730 s best-summary refresh in cycle 5;
some source query labels are generic and need better observability.

## Coverage: timing success is not complete ingestion

At the last observation, 22 of 23 competitions exposed PDFs: **477 documents**,
of which **384 were held** and 93 parsed. During the trial six competitions had
supported documents; the last snapshot had five. Bratislava became held because
its PDF meet name did not match the saved discovery metadata. Do not reinterpret
held documents as empty results or infer completeness from their downloads.

The last canonical preview retained eight unresolved result-identity holds.
These recur across cycles and must not be summed as different swimmers. Accepted
new data came from two Swiss competitions. No claim is made that all live deltas
from all 23 competitions were imported.

| Competition location | Live ID | Last PDFs | Parsed | Held | New imported results |
| --- | --- | ---: | ---: | ---: | ---: |
| Минск (BLR) | 11623 | 73 | 0 | 73 | 0 |
| Burgas (BUL) | 11077 | 21 | 0 | 21 | 0 |
| Plovdiv (BUL) | 11415 | 28 | 26 | 2 | 0 |
| Cospicua (MLT) | 11448 | 38 | 0 | 38 | 0 |
| Abrantes (POR) | 11510 | 6 | 0 | 6 | 0 |
| Abrantes (POR) | 11511 | 2 | 0 | 2 | 0 |
| Lagos (POR) | 11133 | 14 | 0 | 14 | 0 |
| Leiria (POR) | 11115 | 45 | 0 | 45 | 0 |
| Chiasso (SUI) | 11188 | 32 | 8 | 24 | 0 |
| Cossonay (SUI) | 10783 | 32 | 18 | 14 | 86 |
| Aarschot (BEL) | 11484 | 10 | 0 | 10 | 0 |
| Meise (BEL) | 11099 | 4 | 0 | 4 | 0 |
| Vilvoorde (BEL) | 10886 | 0 | 0 | 0 | 0 |
| Sant Feliu de Llobregat (ESP) | 11230 | 23 | 0 | 23 | 0 |
| Incukalns (LAT) | 11607 | 13 | 12 | 1 | 0 |
| Den Helder (NED) | 11216 | 21 | 0 | 21 | 0 |
| Enschede (NED) | 11665 | 7 | 0 | 7 | 0 |
| Kerkrade (NED) | 11660 | 14 | 0 | 14 | 0 |
| Stein (NED) | 11126 | 17 | 0 | 17 | 0 |
| Coimbra (POR) | 11344 | 9 | 0 | 9 | 0 |
| Bečej (SRB) | 11410 | 20 | 0 | 20 | 0 |
| Petit-Lancy (SUI) | 11365 | 32 | 29 | 3 | 22 |
| Bratislava (SVK) | 10705 | 16 | 0 | 16 | 0 |

## Storage and next improvements

- Retained local run evidence: **888.1 MiB**.
- 5,174 archived PDF files total 869.6 MiB; 535 distinct hash names account for 94.3 MiB. Shared content-addressed storage could avoid most duplicate bytes; no evidence was deleted.
- AWS database volume ended with about **14.69 GiB available**. Its host-level used space decreased during the sample window; that is not an import-size estimate.
- AWS root volume was already **95% used** before the trial and remained at 95%, with about **4.47 GiB available** afterward. Root usage grew about 11.35 MiB. These filesystem samples include other host activity.

Next work: expand safe parser/metadata coverage; reduce repeated checks/downloads
of old PDFs while retaining correction detection; reduce publication fixed costs;
capture identifiable web-query timings; and deduplicate/retain archives. A
permanent AWS container still needs the documented supervision/recovery contract.

## Reproducibility and delivery

Timer and recovery code: ETL PR #43, commits `0f47784` and `853886f`.
All three CI jobs passed at `853886f`. The private reviewed adapter bridges the
existing configured local/AWS tools; it is not a fresh-checkout production image.

Private ledger: `reports/nrt-hour-trial-2026-11-08/run-02/trial.json`.
Derived per-cycle/coverage/latency analysis: `analysis.json` beside that ledger.
Publication receipts: canonical ETL
`reports/nrt-expansion-2026-11-08/hour-run-02-cycle-NN/`.
Incident evidence: `hour-reader-incident-05/` in the same canonical folder.
The separately preserved `run-01` failed at startup before any database writes;
it is excluded from trial capacity figures. Raw PDFs and swimmer rows stay private.
Code integration/release remains separate from these verified database updates.
