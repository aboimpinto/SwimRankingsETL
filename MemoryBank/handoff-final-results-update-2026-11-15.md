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
Local companion refreshes are being completed sequentially after shared summaries.

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

AWS five-meet SwimProfiles publication is currently running under the pinned
maintenance source. Public frontend remainsv0.1.45. Existing timeout values are
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
