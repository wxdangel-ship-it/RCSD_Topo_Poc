#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_SCRIPT="$SCRIPT_DIR/t03_watch_internal_full_input.sh"

if [[ ! -f "$TARGET_SCRIPT" ]]; then
  echo "[BLOCK] missing target script: $TARGET_SCRIPT" >&2
  exit 2
fi

export INTERVAL_SEC="${INTERVAL_SEC:-15}"
export RECENT_CASES="${RECENT_CASES:-12}"
export CASE_SCAN="${CASE_SCAN:-auto}"
export CASE_SCAN_THRESHOLD="${CASE_SCAN_THRESHOLD:-1000}"
export DEBUG_VISUAL="${DEBUG_VISUAL:-0}"
export CLEAR_SCREEN="${CLEAR_SCREEN:-1}"
export ONCE="${ONCE:-0}"

echo "[INNERNET] T03 internal full-input monitor wrapper" >&2
if [[ -n "${RUN_ID:-}" ]]; then
  echo "[INNERNET] RUN_ID=$RUN_ID" >&2
fi
if [[ -n "${RUN_ROOT:-}" ]]; then
  echo "[INNERNET] RUN_ROOT=$RUN_ROOT" >&2
fi
echo "[INNERNET] INTERVAL_SEC=$INTERVAL_SEC RECENT_CASES=$RECENT_CASES CASE_SCAN=$CASE_SCAN" >&2

exec "$TARGET_SCRIPT"
