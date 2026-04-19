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
echo "[RUN] Eligible cases are auto-discovered from nodes where has_evd=yes, is_anchor=no, kind_2 in {4, 2048}; T03 default full-batch excluded cases remain excluded."

export NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH
export OUT_ROOT RUN_ID WORKERS MAX_CASES BUFFER_M PATCH_SIZE_M RESOLUTION_M
export DEBUG_FLAG VISUAL_CHECK_DIR REVIEW_MODE

PYTHONPATH=src "$PYTHON_BIN" - <<'PY'
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_int(value: str) -> int | None:
    text = value.strip()
    return int(text) if text else None


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
    (internal_root / "internal_full_input_progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (internal_root / "bootstrap_failure.json").write_text(
        json.dumps(failure, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


try:
    from rcsd_topo_poc.modules.t03_virtual_junction_anchor.internal_full_input_runner import (
        run_t03_step67_internal_full_input,
    )

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
        debug=os.environ["DEBUG_FLAG"] == "--debug",
        review_mode=os.environ["REVIEW_MODE"] == "1",
        visual_check_dir=os.environ["VISUAL_CHECK_DIR"],
    )
except Exception as exc:
    _write_internal_bootstrap_failure("bootstrap", exc)
    raise

print(f"[PY] Prepared internal case root: {artifacts.case_root}")
print(f"[PY] Prepared Step3 run root: {artifacts.step3_run_root}")
print(f"[PY] Final Step67 run root: {artifacts.run_root}")
print(f"[PY] Selected case count: {len(artifacts.selected_case_ids)}")
PY

echo "[DONE] Full-input outputs: $OUT_ROOT/$RUN_ID"
echo "[DONE] Visual checks directory: $VISUAL_CHECK_DIR"
