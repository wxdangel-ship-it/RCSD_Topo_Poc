#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"

MAINNODEID="${MAINNODEID:-${1:-}}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage4_divmerge_virtual_polygon_internal}"
RUN_ID="${RUN_ID:-t02_stage4_divmerge_internal_${MAINNODEID:-unknown}_$(date +%Y%m%d_%H%M%S)}"
DEBUG_FLAG="${DEBUG_FLAG:---debug}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ -z "$MAINNODEID" ]]; then
  echo "[BLOCK] MAINNODEID is required. Pass it as env MAINNODEID or the first positional arg." >&2
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
  "$PYTHON_BIN" -m rcsd_topo_poc t02-stage4-divmerge-virtual-polygon
  --nodes-path "$NODES_PATH"
  --roads-path "$ROADS_PATH"
  --drivezone-path "$DRIVEZONE_PATH"
  --rcsdroad-path "$RCSDROAD_PATH"
  --rcsdnode-path "$RCSDNODE_PATH"
  --mainnodeid "$MAINNODEID"
  --out-root "$OUT_ROOT"
  --run-id "$RUN_ID"
  "$DEBUG_FLAG"
)

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] MAINNODEID=$MAINNODEID"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] DIVSTRIPZONE_PATH=$DIVSTRIPZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"
echo "[INFO] DIVSTRIPZONE_PATH is frozen for internal Stage4 context, but the current Stage4 baseline does not consume it yet."

PYTHONPATH=src "${cmd[@]}"

echo "[DONE] Stage4 outputs: $OUT_ROOT/$RUN_ID"
