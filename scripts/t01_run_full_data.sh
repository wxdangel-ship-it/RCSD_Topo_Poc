#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/t01_run_full_data.sh <roads_path> <nodes_path> [out_root]

Optional environment variables:
  PYTHON_BIN          Python executable. Default: .venv/bin/python then python3
  FORMWAY_MODE        strict | audit_only | off. Default: strict
  STRATEGY_CONFIG     Override strategy config path
  COMPARE_FREEZE_DIR  Optional freeze compare dir
  RUN_ID              Optional explicit run_id
  DEBUG               1 -> --debug, else --no-debug
USAGE
}

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage
  exit 2
fi

ROAD_PATH="$1"
NODE_PATH="$2"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"

if [ -z "$ROOT" ]; then
  echo "[BLOCK] Not inside a git repository."
  exit 2
fi

if [ ! -f "$ROAD_PATH" ]; then
  echo "[BLOCK] road input not found: $ROAD_PATH"
  exit 2
fi

if [ ! -f "$NODE_PATH" ]; then
  echo "[BLOCK] node input not found: $NODE_PATH"
  exit 2
fi

if [ -n "${PYTHON_BIN:-}" ]; then
  PY="$PYTHON_BIN"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

OUT_ROOT="${3:-$ROOT/outputs/_work/t01_full_data_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT_ROOT"

CMD=(
  "$PY"
  -m
  rcsd_topo_poc
  t01-run-skill-v1
  --road-path "$ROAD_PATH"
  --node-path "$NODE_PATH"
  --out-root "$OUT_ROOT"
  --formway-mode "${FORMWAY_MODE:-strict}"
)

if [ -n "${STRATEGY_CONFIG:-}" ]; then
  CMD+=(--strategy-config "$STRATEGY_CONFIG")
fi

if [ -n "${COMPARE_FREEZE_DIR:-}" ]; then
  CMD+=(--compare-freeze-dir "$COMPARE_FREEZE_DIR")
fi

if [ -n "${RUN_ID:-}" ]; then
  CMD+=(--run-id "$RUN_ID")
fi

if [ "${DEBUG:-0}" = "1" ]; then
  CMD+=(--debug)
else
  CMD+=(--no-debug)
fi

echo "[INFO] repo_root=$ROOT"
echo "[INFO] out_root=$OUT_ROOT"
echo "[INFO] python=$PY"
echo "[INFO] command=${CMD[*]}"

(
  cd "$ROOT"
  PYTHONPATH=src "${CMD[@]}" | tee "$OUT_ROOT/cli_stdout.json"
)

"$PY" - <<PY
from pathlib import Path
import json
out = Path(r"$OUT_ROOT")
summary_path = out / "t01_skill_v1_summary.json"
report_path = out / "freeze_compare_report.json"
if summary_path.is_file():
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print("[INFO] freeze_compare_status=", summary.get("freeze_compare_status"))
    print("[INFO] segment_path=", summary.get("segment_path"))
if report_path.is_file():
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print("[INFO] freeze_compare_report_status=", report.get("status"))
PY
