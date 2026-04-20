#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_SCRIPT="$SCRIPT_DIR/t03_watch_internal_full_input.sh"

if [[ ! -f "$TARGET_SCRIPT" ]]; then
  echo "[BLOCK] missing target script: $TARGET_SCRIPT" >&2
  exit 2
fi

REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_internal_full_input}"
RUN_ID_FILE="${RUN_ID_FILE:-$OUT_ROOT/latest_flat_review_run_id.txt}"

if [[ -z "${RUN_ID:-}" && -f "$RUN_ID_FILE" ]]; then
  RUN_ID="$(tr -d '\r\n' < "$RUN_ID_FILE")"
fi

if [[ -z "${RUN_ID:-}" ]]; then
  echo "[BLOCK] RUN_ID is empty and RUN_ID_FILE not found: $RUN_ID_FILE" >&2
  exit 2
fi

export OUT_ROOT
export RUN_ID
export INTERVAL_SEC="${INTERVAL_SEC:-15}"
export RECENT_CASES="${RECENT_CASES:-12}"
export CASE_SCAN="${CASE_SCAN:-auto}"
export CASE_SCAN_THRESHOLD="${CASE_SCAN_THRESHOLD:-1000}"
export DEBUG_VISUAL="${DEBUG_VISUAL:-1}"
export CLEAR_SCREEN="${CLEAR_SCREEN:-1}"
export ONCE="${ONCE:-0}"

echo "[INNERNET-FLAT] monitor wrapper" >&2
echo "[INNERNET-FLAT] OUT_ROOT=$OUT_ROOT" >&2
echo "[INNERNET-FLAT] RUN_ID=$RUN_ID" >&2
echo "[INNERNET-FLAT] INTERVAL_SEC=$INTERVAL_SEC RECENT_CASES=$RECENT_CASES CASE_SCAN=$CASE_SCAN" >&2

exec "$TARGET_SCRIPT"
