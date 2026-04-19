#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

SEGMENT_PATH="${SEGMENT_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg}"
SEGMENT_LAYER="${SEGMENT_LAYER:-}"
SEGMENT_CRS="${SEGMENT_CRS:-}"
NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.gpkg}"
NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DRIVEZONE_LAYER="${DRIVEZONE_LAYER:-}"
DRIVEZONE_CRS="${DRIVEZONE_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage1_drivezone_gate_internal}"
RUN_ID="${RUN_ID:-t02_stage1_internal_$(date +%Y%m%d_%H%M%S)}"

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

for path_var in SEGMENT_PATH NODES_PATH DRIVEZONE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$OUT_ROOT"
cd "$REPO_DIR"

cmd=(
  "$PYTHON_BIN" -m rcsd_topo_poc t02-stage1-drivezone-gate
  --segment-path "$SEGMENT_PATH"
  --nodes-path "$NODES_PATH"
  --drivezone-path "$DRIVEZONE_PATH"
  --out-root "$OUT_ROOT"
  --run-id "$RUN_ID"
)

if [[ -n "$SEGMENT_LAYER" ]]; then
  cmd+=(--segment-layer "$SEGMENT_LAYER")
fi
if [[ -n "$SEGMENT_CRS" ]]; then
  cmd+=(--segment-crs "$SEGMENT_CRS")
fi
if [[ -n "$NODES_LAYER" ]]; then
  cmd+=(--nodes-layer "$NODES_LAYER")
fi
if [[ -n "$NODES_CRS" ]]; then
  cmd+=(--nodes-crs "$NODES_CRS")
fi
if [[ -n "$DRIVEZONE_LAYER" ]]; then
  cmd+=(--drivezone-layer "$DRIVEZONE_LAYER")
fi
if [[ -n "$DRIVEZONE_CRS" ]]; then
  cmd+=(--drivezone-crs "$DRIVEZONE_CRS")
fi

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] SEGMENT_PATH=$SEGMENT_PATH"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"

"${cmd[@]}"

echo "[DONE] Stage1 outputs: $OUT_ROOT/$RUN_ID"
