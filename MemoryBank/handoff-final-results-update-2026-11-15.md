# End-of-weekend final-source update — 15 November 2026

This operation is explicitly authorized for local and AWS databases. It follows
`handoff-evening-results-update-2026-11-15.md`; do not lose the earlier interruption
and pending-consumer evidence. This is a supervised one-shot run, not a scheduler.

## Evidence and code

Private evidence/drivers: `reports/final-update-2026-11-15/`. Raw downloaded LXF
files stay local. AWS receives normalized delivery packages, not LXF/PDF files.
Canonical source uses the reviewed `pdf-club-attribution` worktree importer.
SwimProfiles maintenance source is pinned to
`20b8e28da9c8aae201f9aa887ab7a7ec0866e790` (draft PR306, issue305).
This does not merge that PR or release the public frontend. Its tested changes
are population deltas, persistent unfinished-meet comparison and scoped audit
JIT suppression. See SwimProfiles' import optimization working record.

## Source reconciliation

Fresh discovery/download covered 48 weekend live-directory meets. 38 LXF files
parsed; eight returned HTTP404 and two failed meet metadata matching. Three
existing whole-meet duplicate holds, unsupported finswimming, Belgium's missing
previously imported races and row-level identity ambiguities remain held. The
weekend ending does not prove every final file has been published or resolved.
See `collection.json`, `plan-summary.json`, `lenex-completeness.json` and the
per-source plans for exact coverage. No absent race was silently withdrawn.

Five newly available competitions added 5,910 accepted results locally:
2,761 Bosnia and Herzegovina; 1,255 Portugal; 163 Netherlands; 1,351 Belgium;
380 Canada. The local source insert transactions total about 22 seconds; use the
individual `import-summary.json` receipts for precise values. Replay had no new
inserts/updates/provenance changes. Existing Swiss Nationals and Allschwil LXF
hashes were unchanged. Ambiguous/unsupported rows were not forced into identities.

Local canonical backup was verified before writes. Selected owner-content and
frozen-archive hashes were captured in both environments before application work.

## Local verification so far

Migrations033/034 applied to the populated local SwimProfiles database. An initial
unchanged 14-meet replay took13.239 seconds including the wrapper. The five new
meets then published generation69: importer126.291 seconds, monitored wrapper
130.111 seconds, 5,910 changed results, zero removals. All118 sampled reader
requests passed; maximum176ms. Independent source/fact/best/club/public-reader
verification passed for5,910 results,9,859 splits and1,011 athletes, with zero
best differences. This is new-competition publication, not a20-result warm delta.
Local shared summaries committed in149.655 seconds. Local companion refreshes
completed sequentially: Sophia8.557s, Colin179.345s, Sharks122.058s. All237
sampled requests passed during companion refreshes (maximum286ms). The final
four-application data audit, selected owner-content hashes and frozen-archive
hashes passed.

## AWS progress (not yet complete)

Five normalized packages applied in36.446 seconds. Canonical hashes/revisions and
all5,910 results/9,859 splits verified independently. During source delivery all45
sampled requests passed, maximum1,214ms.

Immutable maintenance source installed under
`/opt/swimprofiles/maintenance/20b8e28da9c8aae201f9aa887ab7a7ec0866e790`.
Migration checksum inspection found only new029–034; no old migration changed.
Required compatible migrations applied in36.833 seconds. One sampled ranking
request returned503 after2,039ms during migration; subsequent sample passed and
three exact-path rechecks returned200 in503/291/313ms. Preserve this failure:
`aws-migrations/`, `aws-migration-targeted-recheck.json`. The web container emitted
no corresponding log lines in the captured migration interval.

AWS five-meet SwimProfiles publication failed at the existing1080-second limit
(exit137 after the30-second termination allowance;1110.933 seconds wrapper).
The container was removed and its transaction rolled back; publication73 stayed
visible. No new source packages were rolled back. During this attempt670 sampled
requests returned successful HTTP status; four successful responses exceeded2s
(maximum2834ms). Post-stop sample passed (maximum983ms). See
`aws-new-results/summary.json`, `aws-import-timing.json` and SQL timings.

Slow SQL statements alone accounted for876.570 seconds. Ranking membership writes
were304.349s; best summaries106.839s; population/prefix refresh185.332s; the audit
with scoped JIT disabled11.418s. Cold/growing historical reads and prefix rebuilding
remain expensive. The fixture benchmark does not certify these production stages.

Recovery is running as two smaller publications: one2,761-result competition, then
four competitions totaling3,149 results. See `aws-recovery-batches.json` and sibling
`reports/final-update-2026-11-15-batch-01/` / `...-batch-02/` directories. Do not rerun
the failed combined publication or increase its timeout.

Pinned maintenance source is used for this operational run. Public frontend remainsv0.1.45. Existing timeout values are
unchanged. One sampled page returned200 in2,834ms during import; following samples
passed. Capture final receipt, independent verification and recovery samples
before reporting completion. Current receipt/control files identify the exact
maintenance container; do not kill unrelated processes.

## Remaining work

1. Finish/verify current AWS SwimProfiles publication and evaluate its real timings.
2. Refresh AWS shared summaries and finish all durable pending consumer deliveries,
   including the earlier interrupted Colin delivery and pending Sophia/Sharks.
   Record each consumer's duration and batch; never mark complete without proof.
3. Check all four applications' actual results, representative profiles/rankings
   and club competition cards; compare owner-content/archive hashes after work.
4. Record final durations, failures and remaining source holds here and in the
   SwimProfiles working record. Clarify operational maintenance installation
   separately from PR merge/frontend release/default-runner deployment.


## Explicit owner stop

The owner requested stopping during the first smaller recovery batch. The exact
labeled maintenance container was stopped and the transaction rolled back. AWS
publication remains73; web container healthy; no maintenance containers or
long-running import transactions remain. No second recovery batch or AWS companion
publisher was started. Local four-application updates and preservation checks are
complete. AWS canonical five-meet source delivery and migrations are committed;
AWS application publication/consumer deliveries remain pending. Resume only on a
new owner instruction. Exact stop receipt: `reports/final-update-2026-11-15/user-stop.json`.

The full stage-by-stage measurements, failed-test interpretation and next investigation
for every expensive stage have been appended to the canonical SwimProfiles document
`docs/import-optimization-working-record.md`. That is the main optimization record;
this document is the operational recovery handoff. Preserve both documents and the
private evidence. Do not claim that all AWS databases were updated.
