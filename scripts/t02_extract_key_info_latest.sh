#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/outputs/_work/t02_key_info_latest}"
RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_PATH="$OUT_DIR/$RUN_STAMP.json"

resolve_latest_run_dir() {
  local summary_name="$1"
  local preferred_root="$2"
  local latest_summary=""

  if [[ -d "$preferred_root" ]]; then
    latest_summary="$(find "$preferred_root" -type f -name "$summary_name" | sort | tail -n 1 || true)"
  fi
  if [[ -z "$latest_summary" && -d "$REPO_ROOT/outputs/_work" ]]; then
    latest_summary="$(find "$REPO_ROOT/outputs/_work" -type f -name "$summary_name" | sort | tail -n 1 || true)"
  fi
  if [[ -n "$latest_summary" ]]; then
    dirname "$latest_summary"
  fi
}

STAGE1_RUN_DIR="$(resolve_latest_run_dir t02_stage1_summary.json "$REPO_ROOT/outputs/_work/t02_stage1_drivezone_gate")"
STAGE2_RUN_DIR="$(resolve_latest_run_dir t02_stage2_summary.json "$REPO_ROOT/outputs/_work/t02_stage2_anchor_recognition")"

mkdir -p "$OUT_DIR"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}"

ARGS=("$REPO_ROOT/scripts/t02_extract_key_info.py" "--json-out" "$OUT_PATH")
if [[ -n "$STAGE1_RUN_DIR" ]]; then
  ARGS+=("--stage1-run-dir" "$STAGE1_RUN_DIR")
fi
if [[ -n "$STAGE2_RUN_DIR" ]]; then
  ARGS+=("--stage2-run-dir" "$STAGE2_RUN_DIR")
fi

if [[ -z "$STAGE1_RUN_DIR" && -z "$STAGE2_RUN_DIR" ]]; then
  echo "[FATAL] No stage1/stage2 run directory found under $REPO_ROOT/outputs/_work" >&2
  exit 2
fi

echo "[INFO] stage1_run_dir=${STAGE1_RUN_DIR:-NONE}"
echo "[INFO] stage2_run_dir=${STAGE2_RUN_DIR:-NONE}"
"$PYTHON_BIN" "${ARGS[@]}"
echo
echo "[INFO] key_info_json=$OUT_PATH"
