#!/usr/bin/env bash
set -euo pipefail
: "${ETL_ROOT:?Set the installed ETL directory}"
: "${RECORD_DB_CONFIG:?Set the private source writer configuration path}"
: "${RECORD_STATE_DIR:?Set the writable state directory}"
: "${RECORD_CONSUMER_SCRIPT:?Set the records-only application import script}"
mkdir -p "$RECORD_STATE_DIR"
exec 8>"$RECORD_STATE_DIR/pipeline.lock"
flock -n 8 || { echo 'A record refresh pipeline is already running.' >&2; exit 1; }
status=0
"${RECORD_PYTHON:-python3}" "$ETL_ROOT/scripts/refresh_country_records.py" \
  --config "$RECORD_DB_CONFIG" --save-dir "$RECORD_STATE_DIR/files" \
  --report "$RECORD_STATE_DIR/latest.json" || status=$?
# Publish successes and failure health without rebuilding unrelated profile rankings.
/bin/bash "$RECORD_CONSUMER_SCRIPT" || status=$?
exit "$status"
