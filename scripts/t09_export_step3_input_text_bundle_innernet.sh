#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

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

if (( $# >= 1 )); then
  CENTER_X="$1"
else
  CENTER_X="${CENTER_X:-}"
fi
if (( $# >= 2 )); then
  CENTER_Y="$2"
else
  CENTER_Y="${CENTER_Y:-}"
fi
if (( $# >= 3 )); then
  SIZE_M="$3"
else
  SIZE_M="${SIZE_M:-}"
fi
if (( $# > 3 )); then
  echo "[BLOCK] Too many positional arguments. Usage: $0 <center_x> <center_y> <size_m>" >&2
  exit 2
fi
if [[ -z "$CENTER_X" || -z "$CENTER_Y" ]]; then
  echo "[BLOCK] CENTER_X and CENTER_Y are required. Pass positional args or env vars." >&2
  exit 2
fi
if [[ -z "${SIZE_M:-}" && -z "${RADIUS_M:-}" ]]; then
  echo "[BLOCK] SIZE_M or RADIUS_M is required. SIZE_M is the full square side length." >&2
  exit 2
fi

SWNODE_PATH="${SWNODE_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg}"
SWROAD_PATH="${SWROAD_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg}"
SEGMENT_PATH="${SEGMENT_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg}"
T08_ROOT="${T08_ROOT:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T08}"
RESTRICTION_PATH="${RESTRICTION_PATH:-}"
ARROW_PATH="${ARROW_PATH:-}"
if [[ -z "$RESTRICTION_PATH" && -f "$T08_ROOT/sw_restriction_tool7.gpkg" ]]; then
  RESTRICTION_PATH="$T08_ROOT/sw_restriction_tool7.gpkg"
fi
if [[ -z "$ARROW_PATH" && -f "$T08_ROOT/sw_arrow_tool8.gpkg" ]]; then
  ARROW_PATH="$T08_ROOT/sw_arrow_tool8.gpkg"
fi

T06_STEP3_ROOT="${T06_STEP3_ROOT:-/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck/step3_segment_replacement}"
FRCSD_ROAD_PATH="${FRCSD_ROAD_PATH:-}"
FRCSD_NODE_PATH="${FRCSD_NODE_PATH:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t09_step3_input_text_bundle_innernet}"
RUN_ID="${RUN_ID:-t09_step3_input_bundle_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-$OUT_ROOT/$RUN_ID}"
OUT_TXT="${OUT_TXT:-$OUT_DIR/t09_step3_input_slice_bundle.txt}"
DECODE_AFTER_EXPORT="${DECODE_AFTER_EXPORT:-1}"
DECODE_DIR="${DECODE_DIR:-$OUT_DIR/decoded}"
MAX_TEXT_SIZE_BYTES="${MAX_TEXT_SIZE_BYTES:-256000}"
TARGET_EPSG="${TARGET_EPSG:-3857}"
INCLUDE_RAW_INPUTS="${INCLUDE_RAW_INPUTS:-0}"

SWNODE_LAYER="${SWNODE_LAYER:-}"
SWROAD_LAYER="${SWROAD_LAYER:-}"
SEGMENT_LAYER="${SEGMENT_LAYER:-}"
RESTRICTION_LAYER="${RESTRICTION_LAYER:-}"
ARROW_LAYER="${ARROW_LAYER:-}"
FRCSD_ROAD_LAYER="${FRCSD_ROAD_LAYER:-}"
FRCSD_NODE_LAYER="${FRCSD_NODE_LAYER:-}"

for path_var in SWNODE_PATH SWROAD_PATH SEGMENT_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done
for path_var in RESTRICTION_PATH ARROW_PATH FRCSD_ROAD_PATH FRCSD_NODE_PATH; do
  path_value="${!path_var:-}"
  if [[ -n "$path_value" && ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done
if [[ -z "$FRCSD_ROAD_PATH" || -z "$FRCSD_NODE_PATH" ]]; then
  if [[ ! -d "$T06_STEP3_ROOT" ]]; then
    echo "[BLOCK] T06_STEP3_ROOT does not exist and FRCSD paths were not provided: $T06_STEP3_ROOT" >&2
    exit 2
  fi
fi

export CENTER_X CENTER_Y SIZE_M RADIUS_M="${RADIUS_M:-}"
export SWNODE_PATH SWROAD_PATH SEGMENT_PATH RESTRICTION_PATH ARROW_PATH
export T06_STEP3_ROOT FRCSD_ROAD_PATH FRCSD_NODE_PATH
export OUT_TXT DECODE_AFTER_EXPORT DECODE_DIR MAX_TEXT_SIZE_BYTES TARGET_EPSG INCLUDE_RAW_INPUTS
export SWNODE_LAYER SWROAD_LAYER SEGMENT_LAYER RESTRICTION_LAYER ARROW_LAYER FRCSD_ROAD_LAYER FRCSD_NODE_LAYER

mkdir -p "$OUT_DIR"
cd "$REPO_DIR"

echo "[RUN] T09 Step3 input text bundle export"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] CENTER_X=$CENTER_X"
echo "[RUN] CENTER_Y=$CENTER_Y"
echo "[RUN] SIZE_M=${SIZE_M:-<none>}"
echo "[RUN] RADIUS_M=${RADIUS_M:-<none>}"
echo "[RUN] SWNODE_PATH=$SWNODE_PATH"
echo "[RUN] SWROAD_PATH=$SWROAD_PATH"
echo "[RUN] SEGMENT_PATH=$SEGMENT_PATH"
echo "[RUN] RESTRICTION_PATH=${RESTRICTION_PATH:-<none>}"
echo "[RUN] ARROW_PATH=${ARROW_PATH:-<none>}"
echo "[RUN] T06_STEP3_ROOT=$T06_STEP3_ROOT"
echo "[RUN] FRCSD_ROAD_PATH=${FRCSD_ROAD_PATH:-<auto>}"
echo "[RUN] FRCSD_NODE_PATH=${FRCSD_NODE_PATH:-<auto>}"
echo "[RUN] OUT_TXT=$OUT_TXT"
echo "[RUN] MAX_TEXT_SIZE_BYTES=$MAX_TEXT_SIZE_BYTES"

PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    run_t09_decode_text_bundle,
    run_t09_export_step3_input_text_bundle,
)


def optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def optional_float(name: str) -> float | None:
    value = optional_env(name)
    return float(value) if value is not None else None


artifacts = run_t09_export_step3_input_text_bundle(
    swnode_path=os.environ["SWNODE_PATH"],
    swroad_path=os.environ["SWROAD_PATH"],
    segment_path=os.environ["SEGMENT_PATH"],
    restriction_path=optional_env("RESTRICTION_PATH"),
    arrow_path=optional_env("ARROW_PATH"),
    t06_step3_root=optional_env("T06_STEP3_ROOT"),
    frcsd_road_path=optional_env("FRCSD_ROAD_PATH"),
    frcsd_node_path=optional_env("FRCSD_NODE_PATH"),
    out_txt=os.environ["OUT_TXT"],
    center_x=float(os.environ["CENTER_X"]),
    center_y=float(os.environ["CENTER_Y"]),
    size_m=optional_float("SIZE_M"),
    radius_m=optional_float("RADIUS_M"),
    swnode_layer=optional_env("SWNODE_LAYER"),
    swroad_layer=optional_env("SWROAD_LAYER"),
    segment_layer=optional_env("SEGMENT_LAYER"),
    restriction_layer=optional_env("RESTRICTION_LAYER"),
    arrow_layer=optional_env("ARROW_LAYER"),
    frcsd_road_layer=optional_env("FRCSD_ROAD_LAYER"),
    frcsd_node_layer=optional_env("FRCSD_NODE_LAYER"),
    target_epsg=int(os.environ["TARGET_EPSG"]),
    include_raw_inputs=os.environ["INCLUDE_RAW_INPUTS"] == "1",
    max_text_size_bytes=int(os.environ["MAX_TEXT_SIZE_BYTES"]),
)
if not artifacts.success:
    print(
        json.dumps(
            {
                "success": False,
                "failure_reason": artifacts.failure_reason,
                "failure_detail": artifacts.failure_detail,
                "bundle_txt": str(artifacts.bundle_txt_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)

decoded = None
decoded_input_manifest = None
decoded_testcase_manifest = None
if os.environ["DECODE_AFTER_EXPORT"] == "1":
    decoded = run_t09_decode_text_bundle(
        bundle_txt=artifacts.part_txt_paths[-1],
        out_dir=os.environ["DECODE_DIR"],
    )
    input_manifest_path = decoded.out_dir / "audit" / "t09_step3_input_manifest.json"
    testcase_manifest_path = decoded.out_dir / "audit" / "t09_local_testcase_manifest.json"
    decoded_input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    decoded_testcase_manifest = json.loads(testcase_manifest_path.read_text(encoding="utf-8"))

print(
    json.dumps(
        {
            "success": True,
            "bundle_txt": str(artifacts.bundle_txt_path),
            "size_report": str(artifacts.size_report_path) if artifacts.size_report_path else None,
            "bundle_size_bytes": artifacts.bundle_size_bytes,
            "included_file_count": artifacts.included_file_count,
            "part_count": len(artifacts.part_txt_paths),
            "max_part_size_bytes": artifacts.max_part_size_bytes,
            "part_txt_paths": [str(path) for path in artifacts.part_txt_paths],
            "decoded_dir": str(decoded.out_dir) if decoded is not None else None,
            "decoded_manifest": str(decoded.manifest_path) if decoded is not None else None,
            "decoded_input_manifest": (
                str(decoded.out_dir / "audit" / "t09_step3_input_manifest.json") if decoded is not None else None
            ),
            "decoded_local_testcase_manifest": (
                str(decoded.out_dir / "audit" / "t09_local_testcase_manifest.json") if decoded is not None else None
            ),
            "source_input_paths": (
                decoded_input_manifest.get("input_paths") if decoded_input_manifest is not None else None
            ),
            "local_fixture_paths": (
                decoded_testcase_manifest.get("fixture_paths") if decoded_testcase_manifest is not None else None
            ),
            "pytest_command_from_repo_root": (
                decoded_testcase_manifest.get("pytest_command_from_repo_root")
                if decoded_testcase_manifest is not None
                else None
            ),
            "recommended_t09_step1_step2_kwargs": (
                decoded_testcase_manifest.get("recommended_t09_step1_step2_kwargs")
                if decoded_testcase_manifest is not None
                else None
            ),
            "recommended_t09_step3_inputs": (
                decoded_testcase_manifest.get("recommended_t09_step3_inputs")
                if decoded_testcase_manifest is not None
                else None
            ),
        },
        ensure_ascii=False,
        indent=2,
    ),
    flush=True,
)
PY

echo "[DONE] bundle_txt=$OUT_TXT"
if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
  echo "[DONE] decoded_dir=$DECODE_DIR"
fi
