# Swimmer identity and club history

Owner clarification, 28 September 2026: a club is an affiliation, not a person's
identity. A swimmer can change clubs during a season or represent another team
or school at a particular event. Different clubs alone must not cause creation
of another person or prevent results being assigned to an established swimmer.

## Evidence and decisions

- Compare names without capitalization differences. Keep the original display
  spelling and source identity for provenance. Case-only differences do not
  establish distinct people.
- A matching full birthdate is stronger evidence than a matching birth year.
  The canonical swimmer table currently stores the year, while retained LENEX
  and raw staging can contain a full date. Inspect that evidence when available.
- Matching name, birth year and competition category is strong duplicate
  evidence, not a universal guarantee. Examine source identifiers, known dates,
  race history and actual contradictions before combining existing people.
- A recorded January 1 can be a genuine birthday or a reduced-precision source
  date. Do not automatically discard it or assert it equals another full date.
  Preserve the source values and state the precision uncertainty in the decision.
- Source IDs need their correct scope. A LENEX `athleteid` can change between
  meets; do not treat it as a globally stable person identifier. Federation
  licenses and provider `swrid` fields are useful corroboration where present.
- Missing club information is not a contradiction. Different clubs or countries
  alone do not establish different people. Do not infer nationality from the
  club's country.

## Importing a result versus combining profiles

These are separate operations. If a new performance can be attributed to an
existing swimmer using the source evidence, it can be imported without waiting
for all historical profile duplicates to be combined. Creating a third person
is not a resolution when two plausible existing source identities are present.

The current live importer holds multiple normalized-name candidates. A reviewed
`identity_key` mapping resolves attribution through the existing plan/apply
workflow. Retain it with both the operational watch and dated batch evidence and
pass it to later rechecks. It is not automatically loaded from SwimProfiles.
Its key includes source club text: a new club spelling requires a new checked
mapping, even when the person was already reviewed.

Use SwimProfiles' existing audited, reversible identity review to combine
confirmed source profiles. The next successful app import combines histories,
search results and rankings while retaining original source identities and old
profile redirects. Do not delete or rewrite canonical source identities merely
to make the app show one person. Integer database IDs differ between local and
AWS; use stable source keys when applying the same decision to both.

## Affiliation chronology

Keep the club explicitly reported for each performance. Do not rewrite old swims
with the current club, and never use import arrival order to infer a transfer.
The latest dated, explicitly reported affiliation supplies the latest reported
club; retain previous affiliations. Equally recent conflicting affiliations need
an explicit unresolved state. Missing affiliation must not erase a known one.
A school/team entry does not by itself prove the swimmer left their usual club.

Current storage supports race-level `club_name` and `club_source` for new LENEX
imports. Older results often lack them. SwimProfiles currently derives its club
observations from the source swimmer's club and latest recorded activity, not
those race-level fields. Do not describe that fallback as a verified membership
start/end timeline. Prefer explicit source evidence during operational review.

## September weekend reconciliation

The owner authorized automatic correction of the nine individually audited
candidate pairs and their 25 held results locally and on AWS. This does not
approve every unrelated candidate in the existing review queue.

All nine pairs share birth year, category and nationality and differ only in
name capitalization. The historical `canonical_swimmer_id` implementation hashes
case-sensitive names; the live importer compares normalized names, so it sees
both older IDs as candidates. Clubs are not in the canonical-ID hash. Changing
that hash now would break stable source keys; reconcile existing keys through
audited mappings instead.

Seven pairs have matching full birthdate evidence. The remaining two have a
specific birthdate versus January 1 in an older source; the current LENEX agrees
with the selected existing specific-date record. Their combination records that
uncertainty and the owner's instruction rather than claiming identical full
dates. Source facts are retained.

The other four holds are four unnamed positions in **one DNS relay**. The LENEX
contains no athlete references for those positions. There are no four measured
swims and no four people to invent. Retain the team-level DNS in the original
source and record this athlete-attribution limitation separately from duplicate
identity cases. The current canonical result schema requires an athlete.

Private evidence is retained in
`reports/import-2026-09-27/identity-recheck/`: candidate histories, source
birthdates, decisions, mappings, import/replay receipts and publication checks.
Do not commit these files or serve them publicly. Prepared plans are not proof
of completed publication; consult the execution receipts.
