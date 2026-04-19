#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

STAGE2_RUN_ROOT="${STAGE2_RUN_ROOT:-/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage2_anchor_recognition_internal/t02_stage2_internal_20260404_170228}"
NODES_PATH="${NODES_PATH:-$STAGE2_RUN_ROOT/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"

NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"
ROADS_LAYER="${ROADS_LAYER:-}"
ROADS_CRS="${ROADS_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_aggregate_continuous_divmerge_internal}"
RUN_ID="${RUN_ID:-t02_aggregate_continuous_divmerge_internal_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="$OUT_ROOT/$RUN_ID"
NODES_FIX_PATH="${NODES_FIX_PATH:-$RUN_ROOT/nodes_fix.gpkg}"
ROADS_FIX_PATH="${ROADS_FIX_PATH:-$RUN_ROOT/roads_fix.gpkg}"
REPORT_PATH="${REPORT_PATH:-$RUN_ROOT/continuous_divmerge_report.json}"

if [[ -n "$PYTHON_BIN" && "$PYTHON_BIN" != "$REPO_DIR/.venv/bin/python" && "$PYTHON_BIN" != ".venv/bin/python" ]]; then
  echo "[BLOCK] PYTHON_BIN must point to repo .venv/bin/python: $REPO_DIR/.venv/bin/python" >&2
  exit 2
fi
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Missing repo python: $PYTHON_BIN" >&2
  echo "[TIP] Run: make env-sync && make doctor" >&2
  exit 2
fi

for path_var in NODES_PATH ROADS_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$RUN_ROOT"
cd "$REPO_DIR"

cmd=(
  "$PYTHON_BIN" -m rcsd_topo_poc t02-aggregate-continuous-divmerge
  --nodes-path "$NODES_PATH"
  --roads-path "$ROADS_PATH"
  --nodes-fix-path "$NODES_FIX_PATH"
  --roads-fix-path "$ROADS_FIX_PATH"
  --report-path "$REPORT_PATH"
)

if [[ -n "$NODES_LAYER" ]]; then
  cmd+=(--nodes-layer "$NODES_LAYER")
fi
if [[ -n "$NODES_CRS" ]]; then
  cmd+=(--nodes-crs "$NODES_CRS")
fi
if [[ -n "$ROADS_LAYER" ]]; then
  cmd+=(--roads-layer "$ROADS_LAYER")
fi
if [[ -n "$ROADS_CRS" ]]; then
  cmd+=(--roads-crs "$ROADS_CRS")
fi

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] STAGE2_RUN_ROOT=$STAGE2_RUN_ROOT"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"
echo "[RUN] RUN_ROOT=$RUN_ROOT"
echo "[RUN] NODES_FIX_PATH=$NODES_FIX_PATH"
echo "[RUN] ROADS_FIX_PATH=$ROADS_FIX_PATH"
echo "[RUN] REPORT_PATH=$REPORT_PATH"

"${cmd[@]}"

echo "[DONE] continuous-divmerge outputs: $RUN_ROOT"
