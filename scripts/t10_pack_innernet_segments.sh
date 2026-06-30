#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/t10_pack_innernet_segments.sh <segment_id> [segment_id ...]
  SEGMENT_IDS="1534342_62397379,504116202_603116901" bash scripts/t10_pack_innernet_segments.sh

Purpose:
  Build a T10 multi-Segment evidence package and export it as split text bundle files.
  SegmentID means SWSD Segment id from the T01 Segment layer. Each Segment becomes one local T10 case directory.

Required runtime:
  Run from a repo with .venv already prepared.
  T10_RUN_ROOT must point to an existing T10 E2E or full-pipeline run root used as evidence source.

Common env:
  T10_RUN_ROOT              Required T10 run root for evidence lookup
  T01_SEGMENT               Optional explicit T01 segment.gpkg; otherwise discovered from T10_RUN_ROOT
  TESTDATA_ROOT             Default: /mnt/d/TestData/POC_Data
  PREPARED_SWSD_NODES       Default: $TESTDATA_ROOT/first_layer_road_net_v0/nodes.gpkg
  PREPARED_SWSD_ROADS       Default: $TESTDATA_ROOT/first_layer_road_net_v0/roads.gpkg
  DRIVEZONE                 Default: $TESTDATA_ROOT/DriveZone.gpkg
  DIVSTRIPZONE              Default: $TESTDATA_ROOT/DivStripZone.gpkg
  RCSD_INTERSECTION         Default: $TESTDATA_ROOT/RCSDIntersection.gpkg
  RCSDROAD                  Default: $TESTDATA_ROOT/RC4/RCSDRoad.gpkg
  RCSDNODE                  Default: $TESTDATA_ROOT/RC4/RCSDNode.gpkg
  SW_RESTRICTION_TOOL7      Default: auto-detect t08/T08 sw_restriction_tool7.gpkg
  SW_ARROW_TOOL8            Default: auto-detect t08/T08 sw_arrow_tool8.gpkg
  RADIUS_M                  Default: 250
  INCLUDE_FILES             Default: 1
  MATERIALIZATION_MODE      Default: spatial_slice when INCLUDE_FILES=1; values: spatial_slice, manifest_only
  OUT_ROOT                  Default: outputs/_work/t10_segment_evidence
  BUNDLE_ROOT               Default: outputs/_work/t10_segment_evidence_bundles
  PACKAGE_ID                Optional fixed package id
  MAX_TEXT_SIZE_BYTES       Default: 256000
  DECODE_AFTER_EXPORT       Default: 0
  DECODE_ROOT               Default: outputs/_work/t10_segment_evidence_decoded
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

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

segment_ids=()
append_segment_ids() {
  local raw="$1"
  local normalized="${raw//,/ }"
  local part
  read -r -a parts <<< "$normalized"
  for part in "${parts[@]}"; do
    if [[ -n "$part" ]]; then
      segment_ids+=("$part")
    fi
  done
}

if (( $# > 0 )); then
  for arg in "$@"; do
    append_segment_ids "$arg"
  done
elif [[ -n "${SEGMENT_IDS:-}" ]]; then
  append_segment_ids "$SEGMENT_IDS"
fi

if [[ ${#segment_ids[@]} -eq 0 ]]; then
  echo "[BLOCK] Provide SegmentIDs as positional args or SEGMENT_IDS='id1,id2'." >&2
  usage >&2
  exit 2
fi

resolve_input_path() {
  local env_name="$1"
  shift
  local configured="${!env_name:-}"
  local candidate
  if [[ -n "$configured" ]]; then
    printf '%s\n' "$configured"
    return 0
  fi
  for candidate in "$@"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf '%s\n' "$1"
}

T10_RUN_ROOT="${T10_RUN_ROOT:-}"
if [[ -z "$T10_RUN_ROOT" || ! -d "$T10_RUN_ROOT" ]]; then
  echo "[BLOCK] T10_RUN_ROOT must point to an existing T10 run root." >&2
  exit 2
fi

TESTDATA_ROOT="${TESTDATA_ROOT:-/mnt/d/TestData/POC_Data}"
FIRST_LAYER_ROOT="${FIRST_LAYER_ROOT:-$TESTDATA_ROOT/first_layer_road_net_v0}"
RC4_ROOT="${RC4_ROOT:-$TESTDATA_ROOT/RC4}"

T01_SEGMENT="${T01_SEGMENT:-}"
PREPARED_SWSD_NODES="$(resolve_input_path PREPARED_SWSD_NODES "$FIRST_LAYER_ROOT/nodes.gpkg")"
PREPARED_SWSD_ROADS="$(resolve_input_path PREPARED_SWSD_ROADS "$FIRST_LAYER_ROOT/roads.gpkg")"
DRIVEZONE="$(resolve_input_path DRIVEZONE "$TESTDATA_ROOT/DriveZone.gpkg")"
DIVSTRIPZONE="$(resolve_input_path DIVSTRIPZONE "$TESTDATA_ROOT/DivStripZone.gpkg")"
RCSD_INTERSECTION="$(resolve_input_path RCSD_INTERSECTION "$TESTDATA_ROOT/RCSDIntersection.gpkg")"
RCSDROAD="$(resolve_input_path RCSDROAD "$RC4_ROOT/RCSDRoad.gpkg")"
RCSDNODE="$(resolve_input_path RCSDNODE "$RC4_ROOT/RCSDNode.gpkg")"
SW_RESTRICTION_TOOL7="$(resolve_input_path SW_RESTRICTION_TOOL7 "$FIRST_LAYER_ROOT/t08/sw_restriction_tool7.gpkg" "$FIRST_LAYER_ROOT/T08/sw_restriction_tool7.gpkg")"
SW_ARROW_TOOL8="$(resolve_input_path SW_ARROW_TOOL8 "$FIRST_LAYER_ROOT/t08/sw_arrow_tool8.gpkg" "$FIRST_LAYER_ROOT/T08/sw_arrow_tool8.gpkg")"

RADIUS_M="${RADIUS_M:-250}"
INCLUDE_FILES="${INCLUDE_FILES:-1}"
MATERIALIZATION_MODE="${MATERIALIZATION_MODE:-}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t10_segment_evidence}"
BUNDLE_ROOT="${BUNDLE_ROOT:-$REPO_DIR/outputs/_work/t10_segment_evidence_bundles}"
PACKAGE_ID="${PACKAGE_ID:-}"
MAX_TEXT_SIZE_BYTES="${MAX_TEXT_SIZE_BYTES:-256000}"
DECODE_AFTER_EXPORT="${DECODE_AFTER_EXPORT:-0}"
DECODE_ROOT="${DECODE_ROOT:-$REPO_DIR/outputs/_work/t10_segment_evidence_decoded}"
STRICT_INPUT_EXISTS="${STRICT_INPUT_EXISTS:-1}"

required_paths=(
  PREPARED_SWSD_NODES
  PREPARED_SWSD_ROADS
  DRIVEZONE
  DIVSTRIPZONE
  RCSD_INTERSECTION
  RCSDROAD
  RCSDNODE
  SW_RESTRICTION_TOOL7
  SW_ARROW_TOOL8
)

if [[ "$STRICT_INPUT_EXISTS" == "1" ]]; then
  for key in "${required_paths[@]}"; do
    value="${!key}"
    if [[ ! -f "$value" ]]; then
      echo "[BLOCK] $key does not exist: $value" >&2
      exit 2
    fi
  done
  if [[ -n "$T01_SEGMENT" && ! -f "$T01_SEGMENT" ]]; then
    echo "[BLOCK] T01_SEGMENT does not exist: $T01_SEGMENT" >&2
    exit 2
  fi
fi

mkdir -p "$OUT_ROOT" "$BUNDLE_ROOT"
cd "$REPO_DIR"

echo "[RUN] T10 Segment evidence package export"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] SEGMENT_IDS=${segment_ids[*]}"
echo "[RUN] T10_RUN_ROOT=$T10_RUN_ROOT"
echo "[RUN] T01_SEGMENT=${T01_SEGMENT:-<auto>}"
echo "[RUN] RADIUS_M=$RADIUS_M"
echo "[RUN] INCLUDE_FILES=$INCLUDE_FILES"
echo "[RUN] MATERIALIZATION_MODE=${MATERIALIZATION_MODE:-<auto>}"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] BUNDLE_ROOT=$BUNDLE_ROOT"

export T10_RUN_ROOT T01_SEGMENT
export PREPARED_SWSD_NODES PREPARED_SWSD_ROADS DRIVEZONE DIVSTRIPZONE RCSD_INTERSECTION
export RCSDROAD RCSDNODE SW_RESTRICTION_TOOL7 SW_ARROW_TOOL8
export OUT_ROOT BUNDLE_ROOT RADIUS_M INCLUDE_FILES MATERIALIZATION_MODE PACKAGE_ID MAX_TEXT_SIZE_BYTES
export DECODE_AFTER_EXPORT DECODE_ROOT

PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" - "${segment_ids[@]}" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    build_multi_segment_evidence_package,
    decode_t10_case_evidence_text_bundle,
    export_t10_case_evidence_text_bundle,
)


def truthy(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


segment_ids = [item.strip() for item in sys.argv[1:] if item.strip()]
manifest = {
    "external_inputs": {
        "prepared_swsd_nodes": os.environ["PREPARED_SWSD_NODES"],
        "prepared_swsd_roads": os.environ["PREPARED_SWSD_ROADS"],
        "drivezone": os.environ["DRIVEZONE"],
        "divstripzone": os.environ["DIVSTRIPZONE"],
        "rcsd_intersection": os.environ["RCSD_INTERSECTION"],
        "rcsdroad": os.environ["RCSDROAD"],
        "rcsdnode": os.environ["RCSDNODE"],
        "sw_restriction_tool7": os.environ["SW_RESTRICTION_TOOL7"],
        "sw_arrow_tool8": os.environ["SW_ARROW_TOOL8"],
    },
    "handoffs": {},
}

package = build_multi_segment_evidence_package(
    manifest=manifest,
    out_root=Path(os.environ["OUT_ROOT"]),
    swsd_segment_ids=segment_ids,
    t10_run_root=Path(os.environ["T10_RUN_ROOT"]),
    t01_segment_path=os.environ.get("T01_SEGMENT") or None,
    radius_m=float(os.environ["RADIUS_M"]),
    package_id=os.environ.get("PACKAGE_ID") or None,
    include_files=truthy(os.environ["INCLUDE_FILES"]),
    materialization_mode=os.environ.get("MATERIALIZATION_MODE") or None,
)

bundle_txt = Path(os.environ["BUNDLE_ROOT"]) / f"{package.package_dir.name}.txt"
bundle = export_t10_case_evidence_text_bundle(
    package_dir=package.package_dir,
    out_txt=bundle_txt,
    max_text_size_bytes=int(os.environ["MAX_TEXT_SIZE_BYTES"]),
)

decoded = None
if truthy(os.environ["DECODE_AFTER_EXPORT"]):
    decoded = decode_t10_case_evidence_text_bundle(
        bundle_txt=bundle.bundle_txt_path,
        out_dir=Path(os.environ["DECODE_ROOT"]) / package.package_dir.name,
    )

print(
    json.dumps(
        {
            "success": True,
            "package_dir": str(package.package_dir),
            "manifest": str(package.manifest_json),
            "summary": str(package.summary_json),
            "bundle_first_part": str(bundle.bundle_txt_path),
            "bundle_parts": [str(path) for path in bundle.part_txt_paths],
            "bundle_size_bytes": bundle.bundle_size_bytes,
            "max_part_size_bytes": bundle.max_part_size_bytes,
            "decoded_dir": str(decoded.out_dir) if decoded is not None else None,
            "decoded_manifest": str(decoded.manifest_path) if decoded is not None else None,
            "segment_ids": segment_ids,
        },
        ensure_ascii=False,
        indent=2,
    )
)
PY
