#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

STAGE1_OUT_ROOT="${STAGE1_OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage1_drivezone_gate_internal}"
STAGE1_RUN_ID="${STAGE1_RUN_ID:-}"
STAGE1_RUN_ROOT="${STAGE1_RUN_ROOT:-}"

INTERSECTION_PATH="${INTERSECTION_PATH:-/mnt/d/TestData/POC_Data/patch_all/RCSDIntersection.gpkg}"
INTERSECTION_LAYER="${INTERSECTION_LAYER:-}"
INTERSECTION_CRS="${INTERSECTION_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage2_anchor_recognition_internal}"
RUN_ID="${RUN_ID:-t02_stage2_internal_$(date +%Y%m%d_%H%M%S)}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

resolve_stage1_run_root() {
  if [[ -n "$STAGE1_RUN_ROOT" ]]; then
    printf '%s\n' "$STAGE1_RUN_ROOT"
    return 0
  fi
  if [[ -n "$STAGE1_RUN_ID" ]]; then
    printf '%s\n' "$STAGE1_OUT_ROOT/$STAGE1_RUN_ID"
    return 0
  fi

  STAGE1_OUT_ROOT="$STAGE1_OUT_ROOT" "$PYTHON_BIN" - <<'PY'
import os
import sys
from pathlib import Path

out_root = Path(os.environ["STAGE1_OUT_ROOT"])
if not out_root.is_dir():
    sys.exit(1)

dirs = [path for path in out_root.iterdir() if path.is_dir()]
if not dirs:
    sys.exit(2)

latest = max(dirs, key=lambda path: path.stat().st_mtime)
print(latest)
PY
}

RESOLVED_STAGE1_RUN_ROOT="$(resolve_stage1_run_root || true)"
if [[ -z "$RESOLVED_STAGE1_RUN_ROOT" ]]; then
  echo "[BLOCK] Cannot resolve STAGE1_RUN_ROOT. Pass STAGE1_RUN_ROOT or STAGE1_RUN_ID, or ensure STAGE1_OUT_ROOT has at least one run." >&2
  exit 2
fi

SEGMENT_PATH="${SEGMENT_PATH:-$RESOLVED_STAGE1_RUN_ROOT/segment.gpkg}"
NODES_PATH="${NODES_PATH:-$RESOLVED_STAGE1_RUN_ROOT/nodes.gpkg}"

for path_var in SEGMENT_PATH NODES_PATH INTERSECTION_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$OUT_ROOT"
cd "$REPO_DIR"

cmd=(
  "$PYTHON_BIN" -m rcsd_topo_poc t02-stage2-anchor-recognition
  --segment-path "$SEGMENT_PATH"
  --nodes-path "$NODES_PATH"
  --intersection-path "$INTERSECTION_PATH"
  --out-root "$OUT_ROOT"
  --run-id "$RUN_ID"
)

if [[ -n "${SEGMENT_CRS:-}" ]]; then
  cmd+=(--segment-crs "$SEGMENT_CRS")
fi
if [[ -n "${NODES_LAYER:-}" ]]; then
  cmd+=(--nodes-layer "$NODES_LAYER")
fi
if [[ -n "${NODES_CRS:-}" ]]; then
  cmd+=(--nodes-crs "$NODES_CRS")
fi
if [[ -n "$INTERSECTION_LAYER" ]]; then
  cmd+=(--intersection-layer "$INTERSECTION_LAYER")
fi
if [[ -n "$INTERSECTION_CRS" ]]; then
  cmd+=(--intersection-crs "$INTERSECTION_CRS")
fi

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] STAGE1_OUT_ROOT=$STAGE1_OUT_ROOT"
echo "[RUN] RESOLVED_STAGE1_RUN_ROOT=$RESOLVED_STAGE1_RUN_ROOT"
echo "[RUN] SEGMENT_PATH=$SEGMENT_PATH"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] INTERSECTION_PATH=$INTERSECTION_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"

PYTHONPATH=src "${cmd[@]}"

echo "[DONE] Stage2 outputs: $OUT_ROOT/$RUN_ID"
