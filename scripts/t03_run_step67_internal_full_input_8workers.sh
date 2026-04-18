#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_step67_full_input_internal}"
RUN_ID="${RUN_ID:-t03_step67_full_input_internal_$(date +%Y%m%d_%H%M%S)}"
WORKERS="${WORKERS:-8}"
MAX_CASES="${MAX_CASES:-}"
BUFFER_M="${BUFFER_M:-100.0}"
PATCH_SIZE_M="${PATCH_SIZE_M:-200.0}"
RESOLUTION_M="${RESOLUTION_M:-0.2}"
DEBUG_FLAG="${DEBUG_FLAG:---debug}"
VISUAL_CHECK_DIR="${VISUAL_CHECK_DIR:-$OUT_ROOT/$RUN_ID/visual_checks}"
REVIEW_MODE="${REVIEW_MODE:-0}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

if [[ "$DEBUG_FLAG" == "--debug" ]]; then
  DEBUG_ENABLED="1"
elif [[ "$DEBUG_FLAG" == "--no-debug" ]]; then
  DEBUG_ENABLED="0"
else
  echo "[BLOCK] DEBUG_FLAG must be --debug or --no-debug. Actual: $DEBUG_FLAG" >&2
  exit 2
fi

if [[ "$REVIEW_MODE" != "0" && "$REVIEW_MODE" != "1" ]]; then
  echo "[BLOCK] REVIEW_MODE must be 0 or 1. Actual: $REVIEW_MODE" >&2
  exit 2
fi

mkdir -p "$OUT_ROOT"
mkdir -p "$VISUAL_CHECK_DIR"
cd "$REPO_DIR"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"
echo "[RUN] WORKERS=$WORKERS"
echo "[RUN] MAX_CASES=${MAX_CASES:-<all eligible cases>}"
echo "[RUN] DEBUG_FLAG=$DEBUG_FLAG"
echo "[RUN] REVIEW_MODE=$REVIEW_MODE"
echo "[RUN] VISUAL_CHECK_DIR=$VISUAL_CHECK_DIR"
echo "[RUN] Eligible cases are auto-discovered from nodes where has_evd=yes, is_anchor=no, kind_2 in {4, 2048}; T03 default full-batch excluded cases remain excluded."

if [[ "$REVIEW_MODE" == "1" ]]; then
  echo "[WARN] REVIEW_MODE=1 is accepted for parameter compatibility only; T03 internal full-input runner does not change Step67 formal semantics." >&2
fi

export REPO_DIR PYTHON_BIN NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH
export OUT_ROOT RUN_ID WORKERS MAX_CASES BUFFER_M PATCH_SIZE_M RESOLUTION_M
export DEBUG_ENABLED VISUAL_CHECK_DIR REVIEW_MODE

PYTHONPATH=src "$PYTHON_BIN" - <<'PY'
import os

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.internal_full_input_runner import (
    run_t03_step67_internal_full_input,
)


def _optional_int(value: str) -> int | None:
    text = value.strip()
    return int(text) if text else None


artifacts = run_t03_step67_internal_full_input(
    nodes_path=os.environ["NODES_PATH"],
    roads_path=os.environ["ROADS_PATH"],
    drivezone_path=os.environ["DRIVEZONE_PATH"],
    rcsdroad_path=os.environ["RCSDROAD_PATH"],
    rcsdnode_path=os.environ["RCSDNODE_PATH"],
    out_root=os.environ["OUT_ROOT"],
    run_id=os.environ["RUN_ID"],
    workers=int(os.environ["WORKERS"]),
    max_cases=_optional_int(os.environ.get("MAX_CASES", "")),
    buffer_m=float(os.environ["BUFFER_M"]),
    patch_size_m=float(os.environ["PATCH_SIZE_M"]),
    resolution_m=float(os.environ["RESOLUTION_M"]),
    debug=os.environ["DEBUG_ENABLED"] == "1",
    review_mode=os.environ.get("REVIEW_MODE", "0") == "1",
    visual_check_dir=os.environ["VISUAL_CHECK_DIR"],
)
print(f"[PY] Prepared internal case root: {artifacts.case_root}")
print(f"[PY] Prepared Step3 run root: {artifacts.step3_run_root}")
print(f"[PY] Final Step67 run root: {artifacts.run_root}")
print(f"[PY] Selected case count: {len(artifacts.selected_case_ids)}")
PY

echo "[DONE] Full-input outputs: $OUT_ROOT/$RUN_ID"
echo "[DONE] Visual checks directory: $VISUAL_CHECK_DIR"
