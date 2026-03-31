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

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_virtual_intersection_full_input_internal}"
RUN_ID="${RUN_ID:-t02_virtual_intersection_full_input_internal_$(date +%Y%m%d_%H%M%S)}"
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

mkdir -p "$OUT_ROOT"
mkdir -p "$VISUAL_CHECK_DIR"
cd "$REPO_DIR"

cmd=(
  "$PYTHON_BIN" -m rcsd_topo_poc t02-virtual-intersection-poc
  --input-mode full-input
  --nodes-path "$NODES_PATH"
  --roads-path "$ROADS_PATH"
  --drivezone-path "$DRIVEZONE_PATH"
  --rcsdroad-path "$RCSDROAD_PATH"
  --rcsdnode-path "$RCSDNODE_PATH"
  --workers "$WORKERS"
  --buffer-m "$BUFFER_M"
  --patch-size-m "$PATCH_SIZE_M"
  --resolution-m "$RESOLUTION_M"
  --out-root "$OUT_ROOT"
  --run-id "$RUN_ID"
  --debug-render-root "$VISUAL_CHECK_DIR"
  "$DEBUG_FLAG"
)

if [[ -n "$MAX_CASES" ]]; then
  cmd+=(--max-cases "$MAX_CASES")
fi

if [[ "$REVIEW_MODE" == "1" ]]; then
  cmd+=(--review-mode)
fi

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
echo "[RUN] VISUAL_CHECK_DIR=$VISUAL_CHECK_DIR"
echo "[RUN] Eligible cases are auto-discovered from nodes where has_evd=yes, is_anchor=no, kind_2 in {4, 2048}."

PYTHONPATH=src "${cmd[@]}"

echo "[DONE] Full-input outputs: $OUT_ROOT/$RUN_ID"
echo "[DONE] Visual checks directory: $VISUAL_CHECK_DIR"
