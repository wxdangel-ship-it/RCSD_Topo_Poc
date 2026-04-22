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

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_internal_full_input}"
RUN_ID="${RUN_ID:-t03_internal_full_input_$(date +%Y%m%d_%H%M%S)}"
WORKERS="${WORKERS:-8}"
MAX_CASES="${MAX_CASES:-}"
BUFFER_M="${BUFFER_M:-100.0}"
PATCH_SIZE_M="${PATCH_SIZE_M:-200.0}"
RESOLUTION_M="${RESOLUTION_M:-0.2}"
DEBUG_FLAG="${DEBUG_FLAG:---no-debug}"
VISUAL_CHECK_DIR="${VISUAL_CHECK_DIR:-$OUT_ROOT/$RUN_ID/visual_checks}"
REVIEW_MODE="${REVIEW_MODE:-0}"
RESUME="${RESUME:-0}"
RETRY_FAILED="${RETRY_FAILED:-0}"
PERF_AUDIT="${PERF_AUDIT:-0}"
PERF_AUDIT_INTERVAL_SEC="${PERF_AUDIT_INTERVAL_SEC:-30}"
PERF_AUDIT_MAX_SAMPLES="${PERF_AUDIT_MAX_SAMPLES:-64}"
PERF_AUDIT_MAX_BYTES="${PERF_AUDIT_MAX_BYTES:-100000}"
PROGRESS_FLUSH_INTERVAL_SEC="${PROGRESS_FLUSH_INTERVAL_SEC:-5}"
PROGRESS_FLUSH_INTERVAL_CASES="${PROGRESS_FLUSH_INTERVAL_CASES:-5}"
LOCAL_CONTEXT_SNAPSHOT_MODE="${LOCAL_CONTEXT_SNAPSHOT_MODE:-failed_only}"

choose_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  local candidate
  for candidate in "$REPO_DIR/.venv/bin/python" python3; do
    if ! command -v "$candidate" >/dev/null 2>&1 && [[ ! -x "$candidate" ]]; then
      continue
    fi
    if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
import shapely
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_DIR/.venv/bin/python"
    return 0
  fi
  printf '%s\n' "python3"
}

PYTHON_BIN="$(choose_python)"

if [[ "$PYTHON_BIN" == "python3" && -x "$REPO_DIR/.venv/bin/python" ]]; then
  echo "[INFO] .venv/bin/python is unavailable for required T03 runtime deps; fallback to python3." >&2
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "[BLOCK] PYTHON_BIN must use Python >= 3.10: $PYTHON_BIN" >&2
  echo "[HINT] Recreate .venv with python3.10, then install: $PYTHON_BIN -m pip install -e \".[dev]\"" >&2
  exit 2
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
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

if [[ "$REVIEW_MODE" != "0" && "$REVIEW_MODE" != "1" ]]; then
  echo "[BLOCK] REVIEW_MODE must be 0 or 1: $REVIEW_MODE" >&2
  exit 2
fi

if [[ "$RESUME" != "0" && "$RESUME" != "1" ]]; then
  echo "[BLOCK] RESUME must be 0 or 1: $RESUME" >&2
  exit 2
fi

if [[ "$RETRY_FAILED" != "0" && "$RETRY_FAILED" != "1" ]]; then
  echo "[BLOCK] RETRY_FAILED must be 0 or 1: $RETRY_FAILED" >&2
  exit 2
fi

if [[ "$PERF_AUDIT" != "0" && "$PERF_AUDIT" != "1" ]]; then
  echo "[BLOCK] PERF_AUDIT must be 0 or 1: $PERF_AUDIT" >&2
  exit 2
fi

for numeric_var in PERF_AUDIT_INTERVAL_SEC PERF_AUDIT_MAX_SAMPLES PERF_AUDIT_MAX_BYTES PROGRESS_FLUSH_INTERVAL_CASES; do
  if ! [[ "${!numeric_var}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[BLOCK] $numeric_var must be a positive integer: ${!numeric_var}" >&2
    exit 2
  fi
done

if ! [[ "$PROGRESS_FLUSH_INTERVAL_SEC" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "[BLOCK] PROGRESS_FLUSH_INTERVAL_SEC must be a non-negative number: $PROGRESS_FLUSH_INTERVAL_SEC" >&2
  exit 2
fi

if [[ "$LOCAL_CONTEXT_SNAPSHOT_MODE" != "all" && "$LOCAL_CONTEXT_SNAPSHOT_MODE" != "failed_only" && "$LOCAL_CONTEXT_SNAPSHOT_MODE" != "off" ]]; then
  echo "[BLOCK] LOCAL_CONTEXT_SNAPSHOT_MODE must be all, failed_only or off: $LOCAL_CONTEXT_SNAPSHOT_MODE" >&2
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
echo "[RUN] VISUAL_CHECK_DIR=$VISUAL_CHECK_DIR"
echo "[RUN] DEBUG_FLAG=$DEBUG_FLAG"
echo "[RUN] RESUME=$RESUME"
echo "[RUN] RETRY_FAILED=$RETRY_FAILED"
echo "[RUN] PERF_AUDIT=$PERF_AUDIT"
echo "[RUN] PROGRESS_FLUSH_INTERVAL_SEC=$PROGRESS_FLUSH_INTERVAL_SEC"
echo "[RUN] PROGRESS_FLUSH_INTERVAL_CASES=$PROGRESS_FLUSH_INTERVAL_CASES"
echo "[RUN] LOCAL_CONTEXT_SNAPSHOT_MODE=$LOCAL_CONTEXT_SNAPSHOT_MODE"
if [[ "$PERF_AUDIT" == "1" ]]; then
  echo "[RUN] PERF_AUDIT_INTERVAL_SEC=$PERF_AUDIT_INTERVAL_SEC"
  echo "[RUN] PERF_AUDIT_MAX_SAMPLES=$PERF_AUDIT_MAX_SAMPLES"
  echo "[RUN] PERF_AUDIT_MAX_BYTES=$PERF_AUDIT_MAX_BYTES"
  echo "[RUN] PERF_AUDIT_* controls sampling only; it does not auto-stop the batch."
fi
echo "[RUN] Eligible cases are auto-discovered from nodes where has_evd=yes, is_anchor=no, kind_2 in {4, 2048}; T03 default full-batch excluded cases remain excluded."

export NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH
export OUT_ROOT RUN_ID WORKERS MAX_CASES BUFFER_M PATCH_SIZE_M RESOLUTION_M
export DEBUG_FLAG VISUAL_CHECK_DIR REVIEW_MODE RESUME RETRY_FAILED
export PERF_AUDIT PERF_AUDIT_INTERVAL_SEC PERF_AUDIT_MAX_SAMPLES PERF_AUDIT_MAX_BYTES
export PROGRESS_FLUSH_INTERVAL_SEC PROGRESS_FLUSH_INTERVAL_CASES
export LOCAL_CONTEXT_SNAPSHOT_MODE

PYTHONUNBUFFERED=1 PYTHONPATH=src "$PYTHON_BIN" - <<'PY'
import json
import os
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_int(value: str) -> int | None:
    text = value.strip()
    return int(text) if text else None


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _write_internal_bootstrap_failure(stage: str, exc: BaseException) -> None:
    out_root = Path(os.environ["OUT_ROOT"])
    run_id = os.environ["RUN_ID"]
    run_root = out_root / run_id
    internal_root = out_root / "_internal" / run_id
    internal_root.mkdir(parents=True, exist_ok=True)

    progress = {
        "updated_at": _now_text(),
        "phase": stage,
        "status": "failed",
        "message": "T03 internal full-input bootstrap failed before runner completion.",
        "run_root": str(run_root),
        "internal_root": str(internal_root),
        "selected_case_count": 0,
        "selected_case_ids": [],
        "discovered_case_count": 0,
        "discovered_case_ids": [],
        "default_full_batch_excluded_case_count": 0,
        "default_full_batch_excluded_case_ids": [],
        "prepared_case_count": 0,
        "prepared_case_ids": [],
        "step3_run_root": None,
        "failure": f"{type(exc).__name__}: {exc}",
    }
    failure = {
        "updated_at": _now_text(),
        "phase": stage,
        "failure": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
        "run_root": str(run_root),
        "internal_root": str(internal_root),
    }
    _write_json_atomic(internal_root / "t03_internal_full_input_progress.json", progress)
    _write_json_atomic(internal_root / "t03_internal_full_input_failure.json", failure)
    _write_json_atomic(internal_root / "bootstrap_failure.json", failure)


try:
    from rcsd_topo_poc.modules.t03_virtual_junction_anchor.internal_full_input_runner import (
        run_t03_internal_full_input,
    )

    artifacts = run_t03_internal_full_input(
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
        debug=os.environ["DEBUG_FLAG"] == "--debug",
        render_review_png=os.environ["DEBUG_FLAG"] == "--debug",
        review_mode=os.environ["REVIEW_MODE"] == "1",
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
    )
except Exception as exc:
    _write_internal_bootstrap_failure("bootstrap", exc)
    raise

print(f"[PY] Prepared internal case root: {artifacts.case_root}")
print(f"[PY] Prepared Step3 run root: {artifacts.step3_run_root}")
print(f"[PY] Final T03 run root: {artifacts.run_root}")
print(f"[PY] Selected case count: {len(artifacts.selected_case_ids)}")
PY

echo "[DONE] Full-input outputs: $OUT_ROOT/$RUN_ID"
echo "[DONE] Visual checks directory: $VISUAL_CHECK_DIR"
