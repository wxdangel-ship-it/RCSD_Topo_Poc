#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DEBUG_FLAG="${DEBUG_FLAG:---no-debug}"
export RESUME="${RESUME:-1}"
export RETRY_FAILED="${RETRY_FAILED:-1}"
export PERF_AUDIT="${PERF_AUDIT:-1}"
export LOCAL_CONTEXT_SNAPSHOT_MODE="${LOCAL_CONTEXT_SNAPSHOT_MODE:-failed_only}"

exec "$SCRIPT_DIR/t04_run_internal_full_input_8workers.sh" "$@"
