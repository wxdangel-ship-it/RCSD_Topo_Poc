#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"
NODES_PATH="${NODES_PATH:-}"
ROADS_PATH="${ROADS_PATH:-}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-}"
RCSDROAD_PATH="${RCSDROAD_PATH:-}"
RCSDNODE_PATH="${RCSDNODE_PATH:-}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_virtual_intersection_full_input}"
RUN_ID="${RUN_ID:-t02_virtual_intersection_full_input_$(date +%Y%m%d_%H%M%S)}"
WORKERS="${WORKERS:-8}"
MAX_CASES="${MAX_CASES:-}"
BUFFER_M="${BUFFER_M:-100.0}"
PATCH_SIZE_M="${PATCH_SIZE_M:-200.0}"
RESOLUTION_M="${RESOLUTION_M:-0.2}"
DEBUG_FLAG="${DEBUG_FLAG:---no-debug}"
DEBUG_RENDER_ROOT="${DEBUG_RENDER_ROOT:-}"
REVIEW_MODE="${REVIEW_MODE:-0}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ -z "$NODES_PATH" || -z "$ROADS_PATH" || -z "$DRIVEZONE_PATH" || -z "$RCSDROAD_PATH" || -z "$RCSDNODE_PATH" ]]; then
  echo "[BLOCK] NODES_PATH / ROADS_PATH / DRIVEZONE_PATH / RCSDROAD_PATH / RCSDNODE_PATH are required." >&2
  echo "Example (WSL, external local):" >&2
  echo "  NODES_PATH=/mnt/e/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.gpkg \\" >&2
  echo "  ROADS_PATH=/mnt/e/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \\" >&2
  echo "  DRIVEZONE_PATH=/mnt/e/TestData/POC_Data/patch_all/DriveZone.gpkg \\" >&2
  echo "  RCSDROAD_PATH=/mnt/e/TestData/POC_Data/RC4/RCSDRoad.gpkg \\" >&2
  echo "  RCSDNODE_PATH=/mnt/e/TestData/POC_Data/RC4/RCSDNode.gpkg \\" >&2
  echo "  $0" >&2
  exit 2
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$OUT_ROOT"
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
  "$DEBUG_FLAG"
)

if [[ -n "$MAX_CASES" ]]; then
  cmd+=(--max-cases "$MAX_CASES")
fi

if [[ -n "$DEBUG_RENDER_ROOT" ]]; then
  cmd+=(--debug-render-root "$DEBUG_RENDER_ROOT")
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
echo "[RUN] Eligible cases are auto-discovered from nodes where has_evd=yes, is_anchor=no, kind_2 in {4, 2048}."
PYTHONPATH=src "${cmd[@]}"
