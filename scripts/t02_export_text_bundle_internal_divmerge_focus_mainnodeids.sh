#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_text_bundle_internal_divmerge_focus}"
RUN_ID="${RUN_ID:-t02_text_bundle_divmerge_focus_$(date +%Y%m%d_%H%M%S)}"
OUT_TXT="${OUT_TXT:-$OUT_ROOT/$RUN_ID/t02_divmerge_focus_bundle.txt}"

# 直接改这里即可；也可用环境变量 MAINNODEID_1..MAINNODEID_4 覆盖。
MAINNODEIDS=(
  "${MAINNODEID_1:-13460276}"
  "${MAINNODEID_2:-13460274}"
  "${MAINNODEID_3:-765592}"
  "${MAINNODEID_4:-13460256}"
)

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH DIVSTRIPZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$(dirname "$OUT_TXT")"
cd "$REPO_DIR"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] DIVSTRIPZONE_PATH=$DIVSTRIPZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] OUT_TXT=$OUT_TXT"
echo "[RUN] MAINNODEIDS=${MAINNODEIDS[*]}"

PYTHONPATH=src "$PYTHON_BIN" -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path "$NODES_PATH" \
  --roads-path "$ROADS_PATH" \
  --drivezone-path "$DRIVEZONE_PATH" \
  --divstripzone-path "$DIVSTRIPZONE_PATH" \
  --rcsdroad-path "$RCSDROAD_PATH" \
  --rcsdnode-path "$RCSDNODE_PATH" \
  --mainnodeid "${MAINNODEIDS[@]}" \
  --out-txt "$OUT_TXT"

echo "[DONE] BUNDLE_TXT=$OUT_TXT"
echo "[TIP] Decode in current directory with:"
echo "cd $(dirname "$OUT_TXT") && PYTHONPATH=$REPO_DIR/src $PYTHON_BIN -m rcsd_topo_poc t02-decode-text-bundle --bundle-txt $OUT_TXT"
