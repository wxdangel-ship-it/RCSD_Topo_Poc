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

NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"
ROADS_LAYER="${ROADS_LAYER:-}"
ROADS_CRS="${ROADS_CRS:-}"
DRIVEZONE_LAYER="${DRIVEZONE_LAYER:-}"
DRIVEZONE_CRS="${DRIVEZONE_CRS:-}"
DIVSTRIPZONE_LAYER="${DIVSTRIPZONE_LAYER:-}"
DIVSTRIPZONE_CRS="${DIVSTRIPZONE_CRS:-}"
RCSDROAD_LAYER="${RCSDROAD_LAYER:-}"
RCSDROAD_CRS="${RCSDROAD_CRS:-}"
RCSDNODE_LAYER="${RCSDNODE_LAYER:-}"
RCSDNODE_CRS="${RCSDNODE_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t04_internal_full_input}"
RUN_ID="${RUN_ID:-t04_internal_full_input_$(date +%Y%m%d_%H%M%S)}"
WORKERS="${WORKERS:-8}"
MAX_CASES="${MAX_CASES:-}"
DEBUG_FLAG="${DEBUG_FLAG:---no-debug}"
VISUAL_CHECK_DIR="${VISUAL_CHECK_DIR:-$OUT_ROOT/$RUN_ID/visual_checks}"
RESUME="${RESUME:-1}"
RETRY_FAILED="${RETRY_FAILED:-1}"
PERF_AUDIT="${PERF_AUDIT:-1}"
PERF_AUDIT_INTERVAL_SEC="${PERF_AUDIT_INTERVAL_SEC:-30}"
PERF_AUDIT_MAX_SAMPLES="${PERF_AUDIT_MAX_SAMPLES:-64}"
PERF_AUDIT_MAX_BYTES="${PERF_AUDIT_MAX_BYTES:-100000}"
PROGRESS_FLUSH_INTERVAL_SEC="${PROGRESS_FLUSH_INTERVAL_SEC:-5}"
PROGRESS_FLUSH_INTERVAL_CASES="${PROGRESS_FLUSH_INTERVAL_CASES:-5}"
LOCAL_CONTEXT_SNAPSHOT_MODE="${LOCAL_CONTEXT_SNAPSHOT_MODE:-failed_only}"
CASE_SCAN="${CASE_SCAN:-auto}"
CASE_SCAN_THRESHOLD="${CASE_SCAN_THRESHOLD:-1000}"
LOCAL_QUERY_BUFFER_M="${LOCAL_QUERY_BUFFER_M:-360.0}"

choose_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_DIR/.venv/bin/python"
    return 0
  fi
  printf '%s\n' "python3"
}

PYTHON_BIN="$(choose_python)"

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "[BLOCK] PYTHON_BIN must use Python >= 3.10: $PYTHON_BIN" >&2
  exit 2
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH DIVSTRIPZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

if [[ "$DEBUG_FLAG" != "--debug" && "$DEBUG_FLAG" != "--no-debug" ]]; then
  echo "[BLOCK] DEBUG_FLAG must be --debug or --no-debug: $DEBUG_FLAG" >&2
  exit 2
fi

for bool_var in RESUME RETRY_FAILED PERF_AUDIT; do
  if [[ "${!bool_var}" != "0" && "${!bool_var}" != "1" ]]; then
    echo "[BLOCK] $bool_var must be 0 or 1: ${!bool_var}" >&2
    exit 2
  fi
done

for numeric_var in WORKERS PERF_AUDIT_INTERVAL_SEC PERF_AUDIT_MAX_SAMPLES PERF_AUDIT_MAX_BYTES PROGRESS_FLUSH_INTERVAL_CASES CASE_SCAN_THRESHOLD; do
  if ! [[ "${!numeric_var}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[BLOCK] $numeric_var must be a positive integer: ${!numeric_var}" >&2
    exit 2
  fi
done

if [[ -n "$MAX_CASES" ]] && ! [[ "$MAX_CASES" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] MAX_CASES must be empty or a positive integer: $MAX_CASES" >&2
  exit 2
fi

if ! [[ "$PROGRESS_FLUSH_INTERVAL_SEC" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "[BLOCK] PROGRESS_FLUSH_INTERVAL_SEC must be a non-negative number: $PROGRESS_FLUSH_INTERVAL_SEC" >&2
  exit 2
fi

if [[ "$LOCAL_CONTEXT_SNAPSHOT_MODE" != "all" && "$LOCAL_CONTEXT_SNAPSHOT_MODE" != "failed_only" && "$LOCAL_CONTEXT_SNAPSHOT_MODE" != "off" ]]; then
  echo "[BLOCK] LOCAL_CONTEXT_SNAPSHOT_MODE must be all, failed_only or off: $LOCAL_CONTEXT_SNAPSHOT_MODE" >&2
  exit 2
fi

if [[ "$CASE_SCAN" != "auto" && "$CASE_SCAN" != "on" && "$CASE_SCAN" != "off" ]]; then
  echo "[BLOCK] CASE_SCAN must be auto, on or off: $CASE_SCAN" >&2
  exit 2
fi

mkdir -p "$OUT_ROOT" "$VISUAL_CHECK_DIR"
cd "$REPO_DIR"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] RUN_ROOT=$OUT_ROOT/$RUN_ID"
echo "[RUN] WORKERS=$WORKERS MAX_CASES=${MAX_CASES:-<all eligible cases>}"
echo "[RUN] DEBUG_FLAG=$DEBUG_FLAG RESUME=$RESUME RETRY_FAILED=$RETRY_FAILED PERF_AUDIT=$PERF_AUDIT"
echo "[RUN] VISUAL_CHECK_DIR=$VISUAL_CHECK_DIR"
echo "[RUN] CASE_SCAN=$CASE_SCAN CASE_SCAN_THRESHOLD=$CASE_SCAN_THRESHOLD"
echo "[RUN] Candidate discovery: representative node, has_evd=yes, is_anchor=no, kind_2 in {8,16,128} or kind=128."

export NODES_PATH ROADS_PATH DRIVEZONE_PATH DIVSTRIPZONE_PATH RCSDROAD_PATH RCSDNODE_PATH
export NODES_LAYER NODES_CRS ROADS_LAYER ROADS_CRS DRIVEZONE_LAYER DRIVEZONE_CRS
export DIVSTRIPZONE_LAYER DIVSTRIPZONE_CRS RCSDROAD_LAYER RCSDROAD_CRS RCSDNODE_LAYER RCSDNODE_CRS
export OUT_ROOT RUN_ID WORKERS MAX_CASES DEBUG_FLAG VISUAL_CHECK_DIR
export RESUME RETRY_FAILED PERF_AUDIT PERF_AUDIT_INTERVAL_SEC PERF_AUDIT_MAX_SAMPLES PERF_AUDIT_MAX_BYTES
export PROGRESS_FLUSH_INTERVAL_SEC PROGRESS_FLUSH_INTERVAL_CASES LOCAL_CONTEXT_SNAPSHOT_MODE LOCAL_QUERY_BUFFER_M

PYTHONUNBUFFERED=1 PYTHONPATH=src "$PYTHON_BIN" - <<'PY'
import os

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.internal_full_input_runner import (
    run_t04_internal_full_input,
)


def optional_int(value: str) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None


artifacts = run_t04_internal_full_input(
    nodes_path=os.environ["NODES_PATH"],
    roads_path=os.environ["ROADS_PATH"],
    drivezone_path=os.environ["DRIVEZONE_PATH"],
    divstripzone_path=os.environ["DIVSTRIPZONE_PATH"],
    rcsdroad_path=os.environ["RCSDROAD_PATH"],
    rcsdnode_path=os.environ["RCSDNODE_PATH"],
    out_root=os.environ["OUT_ROOT"],
    run_id=os.environ["RUN_ID"],
    workers=int(os.environ["WORKERS"]),
    max_cases=optional_int(os.environ.get("MAX_CASES", "")),
    debug=os.environ["DEBUG_FLAG"] == "--debug",
    visual_check_dir=os.environ["VISUAL_CHECK_DIR"],
    resume=os.environ["RESUME"] == "1",
    retry_failed=os.environ["RETRY_FAILED"] == "1",
    perf_audit=os.environ["PERF_AUDIT"] == "1",
    perf_audit_interval_sec=int(os.environ["PERF_AUDIT_INTERVAL_SEC"]),
    perf_audit_max_samples=int(os.environ["PERF_AUDIT_MAX_SAMPLES"]),
    perf_audit_max_bytes=int(os.environ["PERF_AUDIT_MAX_BYTES"]),
    progress_flush_interval_sec=float(os.environ["PROGRESS_FLUSH_INTERVAL_SEC"]),
    progress_flush_interval_cases=int(os.environ["PROGRESS_FLUSH_INTERVAL_CASES"]),
    local_context_snapshot_mode=os.environ["LOCAL_CONTEXT_SNAPSHOT_MODE"],
    local_query_buffer_m=float(os.environ["LOCAL_QUERY_BUFFER_M"]),
    nodes_layer=os.environ.get("NODES_LAYER") or None,
    roads_layer=os.environ.get("ROADS_LAYER") or None,
    drivezone_layer=os.environ.get("DRIVEZONE_LAYER") or None,
    divstripzone_layer=os.environ.get("DIVSTRIPZONE_LAYER") or None,
    rcsdroad_layer=os.environ.get("RCSDROAD_LAYER") or None,
    rcsdnode_layer=os.environ.get("RCSDNODE_LAYER") or None,
    nodes_crs=os.environ.get("NODES_CRS") or None,
    roads_crs=os.environ.get("ROADS_CRS") or None,
    drivezone_crs=os.environ.get("DRIVEZONE_CRS") or None,
    divstripzone_crs=os.environ.get("DIVSTRIPZONE_CRS") or None,
    rcsdroad_crs=os.environ.get("RCSDROAD_CRS") or None,
    rcsdnode_crs=os.environ.get("RCSDNODE_CRS") or None,
)
print(f"[PY] T04 run root: {artifacts.run_root}")
print(f"[PY] Selected case count: {len(artifacts.selected_case_ids)}")
print(f"[PY] accepted={artifacts.accepted_count} rejected={artifacts.rejected_count} runtime_failed={artifacts.runtime_failed_count}")
print(f"[PY] Final visual checks: {artifacts.visual_check_dir}")
print(f"[PY] Summary: {artifacts.summary_path}")
PY

echo "[DONE] T04 internal full-input outputs: $OUT_ROOT/$RUN_ID"
echo "[DONE] Final visual checks directory: $VISUAL_CHECK_DIR"
