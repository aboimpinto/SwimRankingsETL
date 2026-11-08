# Raw source retention

Canonical resume context: [weekend handoff](../MemoryBank/handoff-nrt-unattended-weekend-2026-11-08.md) on `main`. Historical worktree report paths below have a verified copy under `reports/nrt-worktree-archive-2026-11-08/` in this checkout.

Owner decision, 8 November 2026: retain local `.lxf` and PDF sources for replay,
parser tests and investigation. AWS is not a raw-source archive.

## Current operation

- The near-real-time PDF collector and batch evidence run locally. AWS receives
  normalized database packages and publication evidence, not raw PDFs or LENEX.
  The one-hour trial's approximately 888 MiB archive was **local**, not AWS.
- Local files have no automatic expiry yet. Keep checksums, source URLs and run
  references. Define a separate age/space policy before deleting local archives.
- The AWS records entry point `ops/refresh-records-aws.sh` enables
  `--remove-imported-source-files`. After source, continental, consumer and audit
  commands succeed on a real apply, it deletes run-owned raw `.lxf`/PDF copies
  and matching copies in the supplied input directory. It preserves JSON, logs,
  database rows and other files. The local entry point retains sources by default.
- `source-cleanup.json` records filenames, SHA-256 hashes, sizes and cleanup
  status. Cleanup failure returns nonzero even if database publication succeeded;
  check this receipt as well as `pipeline.json`. Replay from the local archive.
- Previews, failed imports and failed publication retain temporary inputs for
  recovery. Resolve them promptly; they are not permanent AWS archives. Do not
  use a blanket `find / -delete` or remove website uploads/media PDFs.

## Future AWS collector/container requirement

Use a bounded per-job temporary source directory. Keep inputs until the canonical
transaction, downstream publication and verification have durable acknowledgements.
Then remove raw files, keeping source hashes/URLs, counts, revision receipts and
errors. Keep any needed replay archive locally, before AWS deletion. Recovery must
be receipt-driven and must not require raw bytes after successful cleanup.

This container lifecycle is a requirement, not a deployed continuous service.
The current NRT batch loader validates source files even for a terminal batch;
therefore do not delete its local batch sources or move it to an ephemeral AWS
workspace without implementing and testing receipt-only terminal replay first.
Normalized delivery packages have a separate retention/revision-chain policy and
are not covered by this raw `.lxf`/PDF cleanup decision.

## 8 November cleanup evidence

The inspected AWS delivery/review roots contained 65 legacy `.lxf` files,
808,904 bytes (about 790 KiB), and no raw PDF files. Successful record pipeline
receipts, the original record import report and the identity-review completion
receipt were inspected. All 65 files were copied locally, SHA-256 verified and
removed from AWS. No database data was deleted. The records and identity-review
paths were checked again: no `.lxf` or PDF remained. SwimProfiles health was OK.
The inspected user's `record-transfers` folder contained no raw source files.
This is a scoped source-directory audit, not a claim about every file on AWS.

Private local backup and manifest:
`~/myWork/SwimRankingsETL/reports/aws-source-retention-2026-11-08/`.
AWS cleanup receipt:
`/opt/swimrankings-delivery/records/source-cleanup-20261108.json`.
The updated records shell entry points were installed on AWS; no import or
scheduler was started. Twelve pipeline tests cover successful cleanup, local
retention, failed/preview retention, matched transfers and changed-file refusal.
