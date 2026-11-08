#!/usr/bin/env bash
# Manual/cron-ready entry point. This script never installs a scheduler.
set -euo pipefail
if [[ ${1:-} == --env ]]; then
  [[ -n ${2:-} && -r $2 ]] || { echo 'Usage: refresh-records.sh --env /private/environment [--dry-run] [source options]' >&2; exit 2; }
  set -a
  # This is a trusted, private Bash configuration, not downloaded data.
  source "$2"
  set +a
  shift 2
fi
: "${ETL_ROOT:?Set the installed SwimRankingsETL directory}"
: "${RECORD_DB_CONFIG:?Set the private source writer configuration path}"
: "${RECORD_STATE_DIR:?Set the writable state directory}"
remove_imported_sources=false
preview=false
discovery_only=false
skip_continental=false
input_directory=
source_args=()
while (($#)); do
  case "$1" in
    --remove-imported-source-files) remove_imported_sources=true; shift ;;
    --skip-continental) skip_continental=true; shift ;;
    --input-directory) input_directory=${2:?Missing input directory}; source_args+=("$1" "$2"); shift 2 ;;
    --input-directory=*) input_directory=${1#*=}; source_args+=("$1"); shift ;;
    *) source_args+=("$1"); shift ;;
  esac
done
set -- "${source_args[@]}"
for arg in "$@"; do
  case "$arg" in --dry-run) preview=true ;; --discover-only) preview=true; discovery_only=true ;; esac
  case "$arg" in
    --report|--report=*|--save-dir|--save-dir=*|--inventory|--inventory=*|--config|--config=*)
      echo 'Set paths through the environment; pipeline report paths cannot be overridden.' >&2; exit 2 ;;
  esac
done
if ! "$preview" && [[ -z ${RECORD_CONSUMER_SCRIPT:-} && -z ${SWIMPROFILES_ROOT:-} ]]; then
  echo 'Set RECORD_CONSUMER_SCRIPT or SWIMPROFILES_ROOT for application publication.' >&2; exit 2
fi
umask 077
mkdir -p "$RECORD_STATE_DIR/runs"
exec 9>"$RECORD_STATE_DIR/pipeline.lock"
flock -n 9 || { echo 'A record refresh pipeline is already running.' >&2; exit 1; }
run_dir=$(mktemp -d "$RECORD_STATE_DIR/runs/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
# Keep output as well as machine-readable receipts, including failed runs.
exec > >(tee "$run_dir/run.log") 2>&1
printf 'Record refresh evidence: %s\n' "$run_dir"
source_status=0
continental_status=0
consumer_status=0
audit_status=0
audit_ran=false
"${RECORD_PYTHON:-python3}" "$ETL_ROOT/scripts/refresh_country_records.py" \
  --config "$RECORD_DB_CONFIG" --save-dir "$run_dir/files" \
  --inventory "$RECORD_STATE_DIR/catalogue.json" --report "$run_dir/source.json" "$@" || source_status=$?
if ! "$discovery_only" && ! "$skip_continental"; then
  continental_args=()
  "$preview" && continental_args+=(--dry-run)
  [[ -z $input_directory ]] || continental_args+=(--input-directory "$input_directory")
  "${RECORD_PYTHON:-python3}" "$ETL_ROOT/scripts/refresh_continental_records.py" \
    --config "$RECORD_DB_CONFIG" --save-dir "$run_dir/files" \
    --report "$run_dir/continental.json" "${continental_args[@]}" || continental_status=$?
fi
if ! "$preview"; then
  # Publish successful lists and health even if the catalogue or another list failed.
  if [[ -n ${RECORD_CONSUMER_SCRIPT:-} ]]; then
    /bin/bash "$RECORD_CONSUMER_SCRIPT" || consumer_status=$?
  else
    (cd "$SWIMPROFILES_ROOT" && "${RECORD_PNPM:-pnpm}" import:records) || consumer_status=$?
    audit_ran=true
    (cd "$SWIMPROFILES_ROOT" && "${RECORD_PNPM:-pnpm}" audit:records > "$run_dir/coverage.json") || audit_status=$?
  fi
fi
"${RECORD_PYTHON:-python3}" - "$run_dir" "$source_status" "$consumer_status" "$audit_status" "$preview" "$audit_ran" "$continental_status" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
run = Path(sys.argv[1])
result = dict(finished_at=datetime.now(timezone.utc).isoformat(),
              source_exit=int(sys.argv[2]), consumer_exit=int(sys.argv[3]),
              audit_exit=int(sys.argv[4]), dry_run=sys.argv[5] == 'true', run=str(run))
result['continental_exit'] = int(sys.argv[7])
result['continental_ran'] = (run / 'continental.json').exists()
result['consumer_ran'] = not result['dry_run']
result['audit_ran'] = sys.argv[6] == 'true'
source = json.loads((run / 'source.json').read_text()) if (run / 'source.json').exists() else {}
result['catalogue'] = source.get('catalogue', 'unavailable')
result['complete_published_catalogue'] = source.get('complete_published_catalogue', False)
result['status'] = 'failed' if any(result[k] for k in ('source_exit','continental_exit','consumer_exit','audit_exit')) else 'ok'
(run / 'pipeline.json').write_text(json.dumps(result, indent=2) + '\n')
latest = run.parent.parent / 'latest.json'
tmp = latest.with_suffix('.part')
tmp.write_text(json.dumps(result, indent=2) + '\n')
tmp.replace(latest)
print(json.dumps(result))
PY
[[ $source_status == 0 && $continental_status == 0 && $consumer_status == 0 && $audit_status == 0 ]]

# Local entry point retains raw files; the AWS entry point opts into cleanup.
# Never clean failed/dry-run inputs. Transfer copies must match imported bytes.
if "$remove_imported_sources" && ! "$preview"; then
  "${RECORD_PYTHON:-python3}" - "$run_dir" "$input_directory" <<'PY_CLEANUP'
import hashlib, json, sys
from pathlib import Path
run = Path(sys.argv[1])
files = run / 'files'
receipt = run / 'source-cleanup.json'
items = []
if files.is_dir() and not files.is_symlink():
    for path in sorted(files.iterdir()):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in ('.lxf', '.pdf'):
            items.append(dict(name=path.name, bytes=path.stat().st_size,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
# Delete only matching copies of files consumed by this successful run.
transfer = Path(sys.argv[2]) if sys.argv[2] else None
if transfer is not None:
    if transfer.is_symlink():
        raise RuntimeError('Refusing symlink transfer directory')
    for item in items:
        path = transfer / item['name']
        if path.exists() or path.is_symlink():
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Transfer differs from imported source: ' + item['name'])
            item['transfer_copy'] = str(path)
def save(status):
    tmp = receipt.with_suffix('.part')
    tmp.write_text(json.dumps(dict(status=status, files=items), indent=2) + '\n')
    tmp.replace(receipt)
save('pending')
for item in items:
    path = files / item['name']
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError('Source changed before cleanup: ' + item['name'])
    path.unlink()
    if 'transfer_copy' in item:
        Path(item['transfer_copy']).unlink()
save('complete')
PY_CLEANUP
fi
