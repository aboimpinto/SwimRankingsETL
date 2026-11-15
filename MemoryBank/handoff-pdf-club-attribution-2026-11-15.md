# Handoff: missing club competition coverage repaired, 15 November 2026

The user reported that Sophia/Colin's new races were visible in swimmer profiles but Allschwil and the Swiss short-course championship were absent from the Limmat Sharks club's Competitions tab.

## Outcome verified locally and on AWS

Both cards and their All results, Event rankings and FINA rankings overlays now work. Allschwil has 19 Limmat performances from three swimmers, including Sophia's seven accepted races. The Swiss short-course championship has 152 from 40 swimmers, including Colin's four accepted races. Exact expected times and complete paginated overlay uniqueness passed. These counts describe the already accepted partial snapshot; this operation did not collect newer results.

The importer had explicitly omitted `club_name`/`club_source` for PDF results. The club publication stage did run, but lacked race-level attribution. The organizer's EntryStatistics PDF identifies LIMM as Limmat Sharks Zürich; a reviewed, meet-scoped mapping now resolves this code without inferring race membership from the swimmer's current club.

## Code and integration state

- Bug: https://github.com/aboimpinto/SwimRankingsETL/issues/49
- Fix PR: https://github.com/aboimpinto/SwimRankingsETL/pull/50
- Branch: `fix/pdf-race-club-attribution`, implementation commit `374d451`, CI follow-up/head `a88015f`.
- Checkout used: `../SwimRankingsETL-worktrees/pdf-club-attribution`, relative to the canonical ETL checkout.
- Dependency chain: PR50 targets `fix/splash-pdf-layouts` (PR48), which targets `feat/nrt-manual-batch` (PR43), which targets `main`.
- **These code PRs remain separate from the completed database repair. Do not say the fix is merged into main. For further PDF imports use the reviewed fix checkout, not an older importer that omits PDF club evidence.** No scheduler was installed or left running.
- `docs/pdf-club-attribution.md` on the fix branch documents the importer, attribution-only receiver and deterministic club verifier.

The importer supports attribution repair on unchanged PDF replay, protects independently changed/official evidence, and preserves race/split IDs. The new `deliver_club_attribution.py` requires consecutive immutable packages and rejects any non-attribution change or destination drift. It leaves athlete summary state alone and explicitly requires subsequent club publication. Normal future race updates still use normal delivery/publication.

The existing NRT verifier bundle now checks all resolved race projections and stored club/meet cards, plus a bounded public card/overlay sample. This supplements swimmer/ranking verification. Unresolved club names are counted explicitly.

## Evidence and timings

Private evidence remains in the canonical ETL checkout at `reports/club-attribution-repair-2026-11-15/`, especially `FINAL-RESULT.json`, `local-applied.json`, `aws-applied.json`, `*-club-coverage.json`, `*-athlete-club-results.json`, `*-browser.json` and `*-profiles.json`. Raw files and before-state backups stay local. No raw PDF/LXF was sent to AWS.

- Attribution repaired: 2,990 existing PDF races across Allschwil, Swiss short-course nationals and Belgian nationals; no new races imported.
- Each application published 1,601 club races across 53 club/meet pairs; no projected rows deleted.
- Local club refresh: 95.129 s. AWS: 252.946 s. These are full one-off club repair timings, not live delta benchmarks.
- Local/AWS race fields and split IDs preserved; repeated canonical import/delivery unchanged.
- All 53 stored club/meet pairs verified. Eight public club/meet pairs sampled per environment; maximum request 60 ms local / 77 ms AWS.
- Browser checks passed both competitions and three views in each environment.
- Random swimmer verification: 25 requests per environment, zero failures; maximum 160 ms local / 525 ms AWS.
- Full new verifier bundle passed locally: 2,990 races, 5,723 splits, 1,410 reaction times, 804 athletes, zero best-time differences, 24 ranking groups, 40 affected-profile requests.
- Tests: 25 live-import tests, 20 delivery tests, six club-verifier tests (nine Node tests including existing concurrency checks), four publication-adapter tests. The new checks are wired into CI, with attribution helper/config changes included in workflow triggers. Dedicated temporary delivery test database and credential file removed after success.
- One-shot local/AWS publication services finished successfully. No persistent importer/cron was started. No application deployment or timeout change was needed.

## Remaining coverage and next work

1,389 race club strings across 68 meet/name variants still do not resolve uniquely to a canonical club. Examples include abbreviations and alternate full names beyond the reviewed LIMM identity. This does not affect the two now-verified Limmat cards, but means **not every club is fully covered**. The raw strings and provenance are now preserved; expand reviewed source identity mappings rather than guessing through current membership or fuzzy names. Details: private `unresolved-clubs.json`.

The fourth reviewed PDF meet (Invitation régionale SLSJ-CC #1) contained no additional club evidence and remained unchanged. Previously held athlete/source cases remain held. Medal and relay completeness is not implied by provisional individual results.

When merging the code dependency chain, verify all required checks, sync main, and only remove worktrees after their branches are safely integrated. Keep this handoff in canonical main so the recovery context survives cleanup.
