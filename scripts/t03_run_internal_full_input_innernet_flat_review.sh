#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_SCRIPT="$SCRIPT_DIR/t03_run_internal_full_input_8workers.sh"

if [[ ! -f "$TARGET_SCRIPT" ]]; then
  echo "[BLOCK] missing target script: $TARGET_SCRIPT" >&2
  exit 2
fi

REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_internal_full_input}"

export OUT_ROOT
export WORKERS="${WORKERS:-8}"
export DEBUG_FLAG="--debug"
export REVIEW_MODE="${REVIEW_MODE:-0}"
export PERF_AUDIT="${PERF_AUDIT:-0}"
export PERF_AUDIT_INTERVAL_SEC="${PERF_AUDIT_INTERVAL_SEC:-30}"
export PERF_AUDIT_MAX_SAMPLES="${PERF_AUDIT_MAX_SAMPLES:-64}"
export PERF_AUDIT_MAX_BYTES="${PERF_AUDIT_MAX_BYTES:-100000}"
export PROGRESS_FLUSH_INTERVAL_SEC="${PROGRESS_FLUSH_INTERVAL_SEC:-5}"
export PROGRESS_FLUSH_INTERVAL_CASES="${PROGRESS_FLUSH_INTERVAL_CASES:-5}"
export LOCAL_CONTEXT_SNAPSHOT_MODE="${LOCAL_CONTEXT_SNAPSHOT_MODE:-failed_only}"
export RESUME="${RESUME:-0}"
export RETRY_FAILED="${RETRY_FAILED:-0}"
export RUN_ID="${RUN_ID:-t03_internal_full_input_innernet_flat_review_$(date +%Y%m%d_%H%M%S)}"
export RUN_ID_FILE="${RUN_ID_FILE:-$OUT_ROOT/latest_flat_review_run_id.txt}"

mkdir -p "$OUT_ROOT"
printf '%s\n' "$RUN_ID" > "$RUN_ID_FILE"

echo "[INNERNET-FLAT] T03 internal full-input full-batch wrapper" >&2
echo "[INNERNET-FLAT] RUN_ID=$RUN_ID" >&2
echo "[INNERNET-FLAT] OUT_ROOT=$OUT_ROOT" >&2
echo "[INNERNET-FLAT] WORKERS=$WORKERS DEBUG_FLAG=$DEBUG_FLAG PERF_AUDIT=$PERF_AUDIT" >&2
echo "[INNERNET-FLAT] RESUME=$RESUME RETRY_FAILED=$RETRY_FAILED LOCAL_CONTEXT_SNAPSHOT_MODE=$LOCAL_CONTEXT_SNAPSHOT_MODE" >&2
echo "[INNERNET-FLAT] FINAL_FLAT_DIR=$OUT_ROOT/$RUN_ID/t03_review_flat" >&2
echo "[INNERNET-FLAT] RUN_ID_FILE=$RUN_ID_FILE" >&2

exec "$TARGET_SCRIPT"
