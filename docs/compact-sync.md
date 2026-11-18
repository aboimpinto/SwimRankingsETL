# Compact fingerprint contract for downstream synchronization

ETL issue #54 / SwimProfiles issue #341. The canonical PostgreSQL results and
splits remain authoritative. This opt-in projection lets downstream consumers
compare compact fingerprints and transfer only changed result payloads.

## Install and maintain

Use the canonical writer connection, never the SwimProfiles source reader:

```bash
python3 scripts/compact_sync.py --config <writer.json> \
  --expect-host <host> --expect-database <database> --install
# On later runs, drain remaining work without requeuing history:
python3 scripts/compact_sync.py --config <writer.json> \
  --expect-host <host> --expect-database <database>
```

Installation queues existing canonical result IDs once. `--batch-size` defaults to
500 and is limited to 5,000; each CLI batch commits separately. Do not repeatedly
use `--install` for normal imports. An explicit reinstall/rebuild can reconstruct
the projection from canonical facts. Do not truncate or edit projection tables.

After installing, grant SELECT on the three contract tables to the existing
consumer role (substitute real schema/role names):

```sql
GRANT SELECT ON public.swim_sync_contract, public.swim_sync_result,
  public.swim_sync_dirty TO source_reader;
```

The reader needs no refresh/write privileges. Functions pin their owning schema.
Installation and CLI are writer operations; the ordinary website never reads this
source database. Keep writer configuration outside tracked files.

## Producer contract v1

- `swim_sync_contract`: version, installation epoch and completed-seed state.
- `swim_sync_result`: result ID, canonical meet ID, namespaced source key and MD5
  of the exact normalized JSONB payload consumed by SwimProfiles. One compact row
  per result, with primary/result and meet/result indexes; no duplicated splits
  or full result payloads. Rows remain for final meets to support corrections.
- `swim_sync_dirty`: deduplicated result IDs awaiting refresh, including deleted
  rows. Triggers enqueue result/split changes, relevant identity changes and
  meet/event metadata updates. An identical row update is ignored.
- `swim_sync_refresh(batch_size)`: updates only queued IDs and removes deleted
  results. It serializes refreshes and refuses incomplete source dependencies.
  Result and split modifications, dirty state and refresh roll back together.

Consumers must read contract readiness and fingerprints in the same repeatable-read
snapshot as payloads. Require version 1, seeded state and **no pending dirty IDs**.
Otherwise use the existing canonical export. Do not interpret an unavailable
projection as an empty competition. Source raw payload changes outside the
normalization are still covered by the existing meet manifest/other consumers.

## Writer integration and pending stack

The stable `import_live_results.apply_plan`,
`import_live_swimrankings_meet` save path, and `meet_delivery.apply_package` call
`refresh_if_installed` before commit. An absent installation is a no-op. Each call
is capped at ten 500-ID batches; large metadata updates/rebuilds remain dirty and
must be drained by the CLI before an optimized downstream sync. This bound avoids
extending an ETL transaction by an unlimited projection rebuild.

Other existing writers automatically enqueue through triggers. Until their queue
is drained, consumers fall back safely. Run the refresh CLI between canonical
import and downstream publication when using such a writer. Existing live PDFs
remain additive, LENEX enrichment retains identities, and authoritative package
deletions remove fingerprints; the projection introduces no new withdrawal rule.

At development time PRs #43 → #48 → #50 → #53 form an unmerged NRT stack. This
provider targets **main** independently. Integrate the main provider changes into
that stack/runtime checkout before enabling its optimized sync; merging this PR
alone does not update an already-running old worktree. Preserve those pending PRs
and their PDF/parser/split optimizations. Local contract tests additionally cover
partial PDF replay/omissions and LENEX enrichment through `apply_plan`.

## Redis responsibilities

ETL does not require Redis credentials. SwimProfiles manages its disposable Redis
partial-comparison index, with committed SQL receipts, identity context, expiry,
final-evidence cleanup and selected-meet reconciliation on misses. Its public
response cache has separate generation-based invalidation. See the consumer's
`docs/compact-sync-redis.md`. No network file retention policy changes here.

## Tests and activation boundary

`tests/test_compact_sync_delivery.py` uses a unique owned schema on the configured
existing PostgreSQL service. `tests/test_live_results.py` also uses isolated
transactional schemas. Do not run older public-schema reset tests against a shared
populated database; their full suite belongs to the disposable CI database.

```bash
DELIVERY_TEST_CONFIG=<test-writer.json> python3 -m unittest discover \
  -s tests -p test_compact_sync_delivery.py -v
LIVE_IMPORT_TEST_CONFIG=<test-writer.json> python3 -m unittest discover \
  -s tests -p test_live_results.py -v
```

The consumer carries an exact test-only SQL mirror; its PostgreSQL test proves
fingerprints match the released normalized result export. Change both copies when
changing contract normalization, and bump the contract/version for incompatible
changes. Installation, data preparation, local activation and AWS activation are
separate from source merge; none is performed automatically by deployment.
