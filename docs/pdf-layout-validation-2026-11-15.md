# Splash PDF layout validation — 15 November 2026

The 14 November coverage audit found published individual-result PDFs held by
strict layout rules. This change adapts those observed layouts; it does not establish
when the provider changed them. Validation uses retained original PDF bytes and
live-page schedules, not reconstructed race data or LLM extraction.

## Behavior

- Shared club-before-time row parsing supports wrapped/adjacent name, year and
  club columns, raw names, qualification markers and declared reaction columns.
- Explicit provisional lists can contain completed swims without placements.
  Keep placements null. Unnumbered equal-time ties in ordinary ranked lists keep
  the preceding placement only when the times match.
- French preliminary, final and swim-off headers are matched to schedule rounds.
  Regional date punctuation and date-only headers are accepted within meet dates.
- Inline lap intervals must reconcile with the finish before conversion to
  cumulative splits. Labelled splits must be increasing, within the race distance,
  and consistent with the finish and supplied lap segments.
- Record/qualifying headings, footer dates, LENEX `ENTRIES`, zero times and
  incomplete/contradictory splits do not become completed race results.
- Identity matching still requires a unique canonical swimmer. No inferred
  nationality, guessed surname or century, invented heat/lane or profile merge.
- PDF-owned reaction/split details survive replay and can be corrected under the
  same race ID. Official LENEX and externally enriched data remain protected;
  loss of prior PDF details blocks application, including `--allow-held`.
- Both the normal collector and NRT collector use the language-adapter chain.
  Parser version `splash-layouts-v8` rechecks unchanged previously held bytes.

## Captured corpus results

This is an **offline parser evaluation**, not an import or a current live snapshot.
The original corpus contains 403 PDFs from 22 meets, captured on 14 November.

| Captured source | PDFs with accepted individual rows | Explicitly excluded PDFs | Held PDFs | Parsed rows in accepted PDFs |
| --- | ---: | ---: | ---: | ---: |
| Allschwil, live 47433 | 28 | 2 | 0 | 1,445 |
| Lausanne/Prilly short-course nationals, live 49229 | 44 | 2 | 0 | 1,459 |
| Entire captured corpus | 114 | 19 | 270 | 4,711 |

78 previously held documents now parse. One previously accepted document is now
held: Slovak live 11154, `ResultList_4.pdf`, contains a 100m result whose displayed
finish is 37.72, with only a 50m split of 37.72 and 2,229 points. The parser cannot
verify a completed 100m swim from that evidence. Do not bypass this hold or claim
it is simply a performance regression.

Remaining holds include other language/column layouts, meet-name mismatches,
ambiguous rounds, multi-event documents and incomplete split evidence. This is
not universal support for every Splash export. Excluded relays still require
verified participant identities. Counts are source rows, not deduplicated imports,
confirmed canonical identities, or proof that the competitions are complete.

Private spot checks confirmed all seven captured swims for the swimmer whose
Allschwil profile originally showed three, including the four missing 200m/100m
performances. A national 400m freestyle result retained its published 223.38s,
857 points, 0.66s reaction and all eight cumulative splits. No personal source
fixtures are committed; regression fixtures use synthetic identities.

Local evidence is retained under `reports/pdf-layouts-2026-11-15/` in the canonical
ETL checkout: `evaluation.json`, `evaluation.log`, the evaluator and parsed
per-document evidence. Original observations remain under
`reports/update-2026-11-14/`. These private reports are intentionally untracked.

## Verification and operation

- Full Python discovery: 288 tests, successful, 27 environment-dependent skips.
  `LIVE_IMPORT_TEST_CONFIG` was supplied for transactional live-import tests.
- Layout regression suite: 16 tests, successful (including cache-upgrade replay).
- NRT concurrency Node suite: 3 tests, successful.
- Database tests used temporary schemas on the existing local PostgreSQL server
  and rolled back; no live result data was changed and no new database was created.
- No schema migration is required. No AWS import or application publication was
  performed as part of this parser validation.

Before applying recovered documents, rerun collection with this parser version,
review canonical identity/conflict holds, and apply through the existing receipt
and incremental-publication workflow. `newly-supported-or-recovered` is deliberately
not an automatically acknowledged delta baseline: recovery needs an explicit
preview/apply. Verify affected profiles and unchanged replay before reporting
publication success. Preserve local original PDFs for replay; AWS must not retain
raw source files after import, following `source-file-retention.md`.

## Recovery preview caught continuation-page row loss

The canonical replay guard found 103 stored Allschwil races absent from the v7
parse, although their documents had no parse holds. Those pages repeat the event
heading but omit the column headings. Version v8 resumes only a matching explicit
continuation event and tests both retained rows and conflicting event refusal.
The v7 corpus evidence remains archived privately; the table above is the corrected
v8 evaluation. Successful document parsing alone did not establish row completeness.

On the fresh 15 November recovery snapshot, all 720 previously imported Allschwil
races remain represented; replay after the accepted import proposes no mutations.
New Sunday documents repeating performances across age lists remain explicitly
held rather than generating duplicate races. The operational recovery receipt is
separate from this parser validation and must establish downstream publication.
