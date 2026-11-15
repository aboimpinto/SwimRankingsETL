# PDF race club attribution and publication

PDF race evidence must populate `results.club_name` and `results.club_source`, just as LENEX evidence does. Updating swimmer results alone does not give SwimProfiles enough evidence to list a club's competitions. Never infer a historical race club from a swimmer's current membership.

`import_live_results.py` now preserves the printed club and source hash. Full names are used directly. Reviewed abbreviations can be resolved through `config/pdf-club-identities.json`: every entry requires explicit meet IDs, the printed code, the full name, an organizer evidence URL and its SHA-256. The raw printed club and reviewed proof remain in the import ledger. Ambiguous mappings fail; dropping previously reviewed identity evidence is treated as detail loss. Independently changed or official club evidence is protected from PDF replacement.

An unchanged accepted PDF can now repair missing attribution using the `provenance` action. This updates only club fields and the import receipt: it does not recreate results or splits or change current swimmer membership. Subsequent identical replay is unchanged. Existing normal publication adapters already treat provenance changes as publishable work.

## Attribution-only recovery

1. Use saved accepted reports and reviewed athlete identities, preview under the normal import lock, and save before-state evidence locally. Require zero race inserts/updates when doing an attribution-only recovery.
2. Apply the reviewed plan. Compare complete race data (excluding the two club fields), split data **including IDs**, and meet snapshots before and after.
3. Export through the existing immutable meet revision history.
4. For an already published remote meet, `scripts/deliver_club_attribution.py` can apply a consecutive attribution-only revision. It requires both previous and new packages, matching destination receipts and unchanged destination data. All fields except result club attribution must be identical between the packages. Dry-run is the default. Pending normal summary publication blocks the patch. Replay is a no-op.
5. After the canonical patch, run SwimProfiles `pnpm import:clubs` locally and the equivalent deployed `scripts/import-clubs.ts` maintenance job on AWS under the operation lock. The patch receipt explicitly requires club publication; its own success is **not** a complete application update. It preserves the existing shared summary-refresh state because athlete timings and scores did not change.
6. Verify actual club cards and result overlays. Preserve provisional results and unavailable medal/relay evidence honestly. Keep raw PDFs/LXF and recovery backups locally; do not upload them to AWS.

Example receiver invocation (use the configured paths/host/database for the destination):

```bash
python3 scripts/deliver_club_attribution.py \
  --previous <previous-package.json.gz> --package <new-package.json.gz> \
  --config <private-writer-config.json> \
  --expect-host <host> --expect-database <database>
# Add --commit only after inspecting the preview and saving the before-state backup.
```

## Deterministic verification

`nrt_verify_clubs.mjs` is included in the existing tracked NRT verifier bundle. It checks source club evidence against application attribution and resolved race projections, then checks stored competition cards for every resolved club/meet pair. Public card and overlay requests use a bounded sample (eight pairs by default, spread across meets), retaining the two-second reader requirement. It checks a real overlay has the expected individual-performance coverage and is not pending.

Unresolved or ambiguous source club names are reported separately; they are not evidence that every club is published. Resolve these through documented source identities, not fuzzy guesses or current membership. The verifier does not claim medal completeness, official finality, or complete import coverage.

## 15 November recovery evidence

Bug: #49. The local and AWS repair changed attribution for 2,990 already accepted PDF races across Allschwil, the Swiss short-course championship and the Belgian championship. It did not import additional races. The fourth reviewed PDF meet had no additional club evidence and remained unchanged.

Each application published 1,601 newly resolved club races across 53 club/meet pairs. Another 1,389 race club strings (68 meet/name variants) remain unresolved; this is a separate source-identity coverage limitation, explicitly retained in the report. The reviewed LIMM mapping fixes both reported Limmat Sharks competitions.

- Allschwil: 19 club performances, three swimmers, including all seven accepted Sophia races.
- Swiss short-course championship: 152 club performances, 40 swimmers, including all four accepted Colin races.
- Local club refresh: 95.129 seconds. AWS: 252.946 seconds. These are one-off full club repair timings, not incremental live-import benchmarks.
- Both browsers opened the cards and all three views (All results, Event rankings, FINA rankings). Paginated public APIs contained the exact expected Sophia/Colin times with no duplicate performance keys.
- All 53 stored club/meet pairs and eight sampled public pairs per environment passed; maximum sampled public club latency was 60 ms locally / 77 ms on AWS.
- Local/AWS canonical replay was unchanged; race fields and split IDs were preserved.
- Random swimmer checks: 25 requests in each environment, zero failures, maximum 160 ms locally / 525 ms on AWS.
- The complete bundled verifier also passed locally: 2,990 races, 5,723 splits, 1,410 reaction times, 804 athletes, zero best-time differences, 24 ranking groups and 40 affected-profile requests.

Private raw files, before-state backups, receipts, unresolved-name counts, browser screenshots and timing logs are under the canonical checkout's ignored `reports/club-attribution-repair-2026-11-15/`. Do not commit those private artifacts. The upstream dependency chain remains separate from the operational repair: this fix builds on the PDF-layout branch and the NRT publication branch.
