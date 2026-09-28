#!/usr/bin/env bash
# Compatibility entry point: same tested process and receipts on AWS.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /bin/bash "$script_dir/refresh-records.sh" "$@"
