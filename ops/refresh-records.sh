#!/usr/bin/env bash
# Run after normal meet delivery or from the weekly user timer. No web-request work.
set -euo pipefail
: "${ETL_ROOT:?Set the installed SwimRankingsETL directory}"
: "${RECORD_DB_CONFIG:?Set the private source writer configuration path}"
: "${RECORD_STATE_DIR:?Set the writable state directory}"
: "${SWIMPROFILES_ROOT:?Set the SwimProfiles checkout directory}"
mkdir -p "$RECORD_STATE_DIR"
exec 9>"$RECORD_STATE_DIR/pipeline.lock"
flock -n 9 || { echo 'A record refresh pipeline is already running.' >&2; exit 1; }
status=0
"${RECORD_PYTHON:-python3}" "$ETL_ROOT/scripts/refresh_country_records.py" \
  --config "$RECORD_DB_CONFIG" --save-dir "$RECORD_STATE_DIR/files" \
  --report "$RECORD_STATE_DIR/latest.json" || status=$?
# Publish refresh health and all successful lists, even after a partial download failure.
(cd "$SWIMPROFILES_ROOT" && "${RECORD_PNPM:-pnpm}" import:records) || status=$?
(cd "$SWIMPROFILES_ROOT" && "${RECORD_PNPM:-pnpm}" audit:records > "$RECORD_STATE_DIR/coverage.json") || status=$?
exit "$status"
