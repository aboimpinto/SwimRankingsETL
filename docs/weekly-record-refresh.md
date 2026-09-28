# Weekly manual record refresh

Repeat this procedure each week. **No crontab entry or timer is needed or enabled.**
It refreshes official record benchmarks, not competition results. It updates the
canonical SwimRankings databases on localServer and AWS, and publishes records
into both SwimProfiles application databases. It does not deploy website code or
run Sophia/Colin/LimmatSharks meet imports.

## 1. Use the installed process

Run the local blocks in the same Bash terminal. These are the installations
verified on 28 September 2026; adjust paths only if the installation moves.
The primary ETL development checkout may have unrelated changes, so use the
pinned installation below rather than switching its branch.

```bash
record_tool="$HOME/.local/lib/swimrankings-record-refresh"
record_env="$HOME/.config/swimrankings-records/environment"
record_state="$HOME/.local/state/swimrankings-record-refresh"
test -r "$record_tool/ops/refresh-records.sh" && test -r "$record_env"
cat "$record_tool/REVISION"
ssh aws-swimming-delivery 'test -r /opt/swimrankings-delivery/record-refresh/ops/refresh-records-aws.sh'
```

Stop if a prerequisite fails. LocalServer, local app PostgreSQL and SSH access
must be available. The trusted private environment configures the Python
runtime, source writer and app consumer. AWS uses
`/etc/swimrankings-records/environment` and its records-only maintenance consumer.
Do not print, transfer or commit either environment or database credential file.
For a fresh installation, see [configuration and source details](country-records.md).

## 2. Gather and preview this week's files

```bash
bash "$record_tool/ops/refresh-records.sh" --env "$record_env" --dry-run
```

This attempts fresh catalogue/country discovery, downloads every known LENEX
list again for both courses, and gathers Americas, Africa, Asia and Oceania
records from World Aquatics. World and European lists use SwimRankings LENEX.
It validates the files and writes reports without changing database records or
publishing to the app. Discovery inventory and run evidence are saved locally.

The command prints `Record refresh evidence: ...`. After it finishes, capture
that run immediately:

```bash
record_preview=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"])' "$record_state/latest.json")
cat "$record_preview/pipeline.json"
python3 - "$record_preview" <<'PY'
import json, pathlib, sys
run = pathlib.Path(sys.argv[1])
for name in ("source.json", "continental.json"):
    report = json.loads((run / name).read_text())
    print(name, "catalogue:", report.get("catalogue", "not applicable"))
    for item in report.get("files", []):
        print(item["list"], item["course"], item["records"], "records,",
              item["splits"], "splits")
    print("ERRORS:", json.dumps(report.get("errors", []), indent=2))
PY
```

Confirm the receipt's `run` matches the path just printed and `dry_run` is true.
If the command fails before creating a new run, `latest.json` may still refer to
an older run: stop rather than using it. Every subsequent invocation replaces
`latest.json`; keep `record_preview` pointing to the reviewed download.

Review before continuing:

- Inspect both reports and `run.log`. Check list/course counts and unexpected
  losses against the previous week's evidence; totals may legitimately change.
- A catalogue Cloudflare 403 can cause a nonzero exit while known record files
  validate successfully. This is incomplete discovery, not all-country success.
  Proceed with those available files only after confirming the errors are
  discovery-only and all intended file validations succeeded.
- A failed/missing record download, parser error, missing report or incomplete
  continental bundle needs investigation/retry before the normal delivery below.
  Do not turn every nonzero exit into an accepted warning.
- A fresh browser-saved catalogue can supply additional published IDs with
  `--catalogue-html /path/to/saved.html` on a new preview. Saved HTML is explicitly
  not live discovery. Country ranking URLs alone are not record list IDs.

## 3. Publish the reviewed bundle locally

Use the same preview files, without downloading a different snapshot:

```bash
bash "$record_tool/ops/refresh-records.sh" --env "$record_env" \
  --input-directory "$record_preview/files"
```

After successful completion, capture and inspect the local apply receipt:

```bash
record_local=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"])' "$record_state/latest.json")
cat "$record_local/pipeline.json"
cat "$record_local/coverage.json"
```

Require `status: ok`, `dry_run: false`, `consumer_ran: true`,
`continental_ran: true`, and local `audit_ran: true`. All four exit fields must
be zero. Check the records-only consumer output in `run.log`; a successful
source import alone is not successful app publication.

Offline receipts correctly say `catalogue: provided_files_only` and
`complete_published_catalogue: false`. They do not carry the online discovery
failure as their own failure. **Retain the preview reports alongside the apply
receipt** so offline success never hides discovery gaps.

## 4. Transfer exactly those files to AWS

Create a checksum manifest of the reviewed files. Keep the generated batch name
unchanged; it contains only safe date/time characters for the SSH commands.

```bash
record_batch="records-$(date -u +%Y%m%dT%H%M%SZ)"
(
set -e
(cd "$record_preview" && sha256sum files/* > SHA256SUMS)
ssh aws-swimming-delivery "umask 077; mkdir -p \"\$HOME/record-transfers/$record_batch\""
scp -r "$record_preview/files" "$record_preview/source.json" \
  "$record_preview/continental.json" "$record_preview/pipeline.json" \
  "$record_preview/SHA256SUMS" \
  "aws-swimming-delivery:record-transfers/$record_batch/"
ssh aws-swimming-delivery "cd \"\$HOME/record-transfers/$record_batch\" && sha256sum -c SHA256SUMS"
)
```

Stop on any transfer/checksum failure; every file must say `OK`. This bundle
contains public source data and reports, never private configuration. Do not
combine `files/` folders from different weeks or omit the continental JSON files.

## 5. Publish on AWS and retain the receipts

```bash
ssh aws-swimming-delivery "sudo bash /opt/swimrankings-delivery/record-refresh/ops/refresh-records-aws.sh --env /etc/swimrankings-records/environment --input-directory \"\$HOME/record-transfers/$record_batch/files\""
```

Require a successful exit. Retrieve its receipt immediately; verify its timestamp
and printed run path belong to this invocation, not a previous run:

```bash
ssh aws-swimming-delivery 'sudo cat /opt/swimrankings-delivery/records/weekly/latest.json' \
  > "$record_local/aws-pipeline.json"
cat "$record_local/aws-pipeline.json"
record_aws=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"])' "$record_local/aws-pipeline.json")
# Only use the trusted pipeline-generated run path, never a downloaded source URL.
(
set -e
[[ "$record_aws" =~ ^/opt/swimrankings-delivery/records/weekly/runs/[A-Za-z0-9-]+$ ]]
ssh aws-swimming-delivery "sudo cat '$record_aws/source.json'" > "$record_local/aws-source.json"
ssh aws-swimming-delivery "sudo cat '$record_aws/continental.json'" > "$record_local/aws-continental.json"
ssh aws-swimming-delivery "sudo cat '$record_aws/run.log'" > "$record_local/aws-run.log"
)
```

Stop if the path check fails. Require `status: ok`, `dry_run: false`,
`consumer_ran: true`, `continental_ran: true`, and zero exit codes. AWS currently
uses an external maintenance consumer, so `audit_ran: false` is expected; it
means the separate app coverage audit was **not** run, not that coverage passed.
Inspect `aws-run.log` for successful SwimProfiles records-only publication.

Compare source snapshots from the local and AWS apply reports:

```bash
python3 - "$record_local" <<'PY'
import json, pathlib, sys
run = pathlib.Path(sys.argv[1])
def snapshots(path):
    fields = ("sha256", "content_hash", "records", "splits")
    return {(f["list"], f["course"]): tuple(f[k] for k in fields)
            for f in json.loads(path.read_text())["files"]}
for name in ("source.json", "continental.json"):
    local = snapshots(run / name)
    remote = snapshots(run / ("aws-" + name))
    assert local and local == remote, f"Snapshot mismatch: {name}"
    print(name, len(local), "matching list/course snapshots")
PY
```

Finish only when the checksum checks, source snapshot comparisons and both app
publication receipts succeed. Keep the preview, local apply and AWS run folders;
record their paths with any discovery limitations for that week's handoff.
An app UI release is separate from this data-only operation.

## Failures, retries and next week

- An overlapping run is rejected by a lock. Wait for the active process; do not
  remove locks or start competing imports.
- Failed/empty/malformed downloads retain the last good snapshot. Successful
  lists can publish even when another provider fails, so an error is not an
  automatic rollback of the whole week. Read each provider and consumer result.
- Retry a transport/discovery problem with a **new online preview**, then review
  its new evidence. For app-publication or SSH problems, reuse the already
  validated bundle and retry the relevant apply/transfer step.
- Identical semantic content is skipped; corrected list/course snapshots replace
  their previous version transactionally. Reapplying the same bundle is safe
  and should show `changed: false` for unchanged source snapshots. Do not reset
  databases or run a full swimmer/ranking rebuild to retry this process.
- Missing national/age-group lists disable only those comparisons. Never use
  Swiss national records for another nationality. Continental comparison uses
  the swimmer's selected nationality: Canada uses Americas, not Europe. World
  comparison remains independent. No source splits means no invented splits.
- Next week start again at step 1, gathering fresh files. Do not reuse this
  week's bundle as next week's refresh or treat historic record totals as fixed
  acceptance targets. Newly discoverable lists are included by the online run.

As of 28 September 2026, verified national/age coverage is SUI, NED and FRO;
this is not all-country coverage. See [source coverage and limitations](country-records.md).
Scheduling remains a separate future decision: **do not run `crontab -e` or
`systemctl enable` as part of this runbook**.
