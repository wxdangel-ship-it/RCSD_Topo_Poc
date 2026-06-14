#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/t10_run_innernet_full_pipeline.sh

Purpose:
  Run the innernet full-data pipeline, not a Case package replay.
  The pipeline writes all outputs under:
    outputs/_work/t10_innernet_full_pipeline/<RUN_ID>/

Main stages:
  T08 -> T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T07 Step3 -> T06 Step1/2 -> T06 Step3 -> T09

Common env:
  TESTDATA_ROOT        Default: /mnt/d/TestData/POC_Data
  RUN_ID               Default: t10_innernet_full_pipeline_<timestamp>
  OUT_ROOT             Default: outputs/_work/t10_innernet_full_pipeline
  RUN_T08              1 or 0. Default: 1
  RUN_T08_TOOL7        1, 0 or auto. Default: auto
  RUN_T08_TOOL8        1, 0 or auto. Default: auto
  RUN_T08_TOOL9        1, 0 or auto. Default: 0
  T03_WORKERS          Default: 8
  T04_WORKERS          Default: 8
  T05_READONLY_WORKERS Default: 4

Input override env:
  SWSD_INPUT_NODES, SWSD_INPUT_ROADS
  DRIVEZONE_PATH, DIVSTRIPZONE_PATH, RCSD_INTERSECTION_PATH
  RCSDROAD_PATH, RCSDNODE_PATH
  SW_CONDITION_GPKG, SW_LANE_GPKG, SW_NODE_GPKG, SW_ROAD_GPKG
  ROAD_SURFACE_GPKG
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Missing repo python: $PYTHON_BIN" >&2
  echo "[TIP] Run: make env-sync && make doctor" >&2
  exit 2
fi

TESTDATA_ROOT="${TESTDATA_ROOT:-/mnt/d/TestData/POC_Data}"
FIRST_LAYER_ROOT="${FIRST_LAYER_ROOT:-$TESTDATA_ROOT/first_layer_road_net_v0}"
RC4_ROOT="${RC4_ROOT:-$TESTDATA_ROOT/RC4}"

RUN_ID="${RUN_ID:-t10_innernet_full_pipeline_$(date +%Y%m%d_%H%M%S)}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t10_innernet_full_pipeline}"
RUN_ROOT="$OUT_ROOT/$RUN_ID"
LOG_ROOT="$RUN_ROOT/logs"
MANIFEST_PATH="$RUN_ROOT/t10_innernet_full_pipeline_manifest.json"

mkdir -p "$RUN_ROOT" "$LOG_ROOT"
cd "$REPO_DIR"

first_existing() {
  local fallback="$1"
  local candidate
  shift || true
  for candidate in "$fallback" "$@"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf '%s\n' "$fallback"
}

require_file() {
  local name="$1"
  local path="$2"
  if [[ ! -f "$path" ]]; then
    echo "[BLOCK] $name does not exist: $path" >&2
    exit 2
  fi
}

run_logged() {
  local stage="$1"
  shift
  echo
  echo "[STAGE] $stage"
  echo "[CMD] $*"
  "$@" 2>&1 | tee "$LOG_ROOT/${stage}.log"
}

optional_mode_should_run() {
  local mode="$1"
  shift
  case "$mode" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    0|false|FALSE|no|NO|off|OFF)
      return 1
      ;;
    auto|AUTO)
      local path
      for path in "$@"; do
        [[ -f "$path" ]] || return 1
      done
      return 0
      ;;
    *)
      echo "[BLOCK] optional run mode must be 1, 0 or auto: $mode" >&2
      exit 2
      ;;
  esac
}

write_manifest() {
  "$PYTHON_BIN" - "$MANIFEST_PATH" <<'PY'
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "run_id": os.environ["RUN_ID"],
    "run_root": os.environ["RUN_ROOT"],
    "repo_dir": os.environ["REPO_DIR"],
    "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "pipeline": [
        "T08",
        "T01",
        "T07 Step1/2",
        "T03",
        "T04",
        "T05",
        "T07 Step3",
        "T06 Step1/2",
        "T06 Step3",
        "T09",
    ],
    "inputs": {},
    "outputs": {},
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

manifest_set() {
  local section="$1"
  local key="$2"
  local value="$3"
  "$PYTHON_BIN" - "$MANIFEST_PATH" "$section" "$key" "$value" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
section = sys.argv[2]
key = sys.argv[3]
value = sys.argv[4]
payload = json.loads(path.read_text(encoding="utf-8"))
payload.setdefault(section, {})[key] = value
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

export REPO_DIR RUN_ID RUN_ROOT
write_manifest

DRIVEZONE_PATH="${DRIVEZONE_PATH:-$(first_existing "$TESTDATA_ROOT/patch_all/DriveZone.gpkg" "$TESTDATA_ROOT/DriveZone.gpkg")}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-$(first_existing "$TESTDATA_ROOT/patch_all/DivStripZone.gpkg" "$TESTDATA_ROOT/DivStripZone.gpkg")}"
RCSD_INTERSECTION_PATH="${RCSD_INTERSECTION_PATH:-$(first_existing "$TESTDATA_ROOT/patch_all/RCSDIntersection.gpkg" "$TESTDATA_ROOT/RCSDIntersection.gpkg")}"
RCSDROAD_PATH="${RCSDROAD_PATH:-$RC4_ROOT/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-$RC4_ROOT/RCSDNode.gpkg}"
SWSD_INPUT_NODES="${SWSD_INPUT_NODES:-$FIRST_LAYER_ROOT/nodes.gpkg}"
SWSD_INPUT_ROADS="${SWSD_INPUT_ROADS:-$FIRST_LAYER_ROOT/roads.gpkg}"

SW_CONDITION_GPKG="${SW_CONDITION_GPKG:-$FIRST_LAYER_ROOT/SW/MIF/Cguangdong1.gpkg}"
SW_LANE_GPKG="${SW_LANE_GPKG:-$FIRST_LAYER_ROOT/SW/MIF/Laneguangdong1.gpkg}"
SW_NODE_GPKG="${SW_NODE_GPKG:-$FIRST_LAYER_ROOT/SW/A200-2025M12-node.gpkg}"
SW_ROAD_GPKG="${SW_ROAD_GPKG:-$FIRST_LAYER_ROOT/SW/A200-2025M12-road.gpkg}"
ROAD_SURFACE_GPKG="${ROAD_SURFACE_GPKG:-$TESTDATA_ROOT/road_surface.gpkg}"

for pair in \
  "DRIVEZONE_PATH:$DRIVEZONE_PATH" \
  "DIVSTRIPZONE_PATH:$DIVSTRIPZONE_PATH" \
  "RCSD_INTERSECTION_PATH:$RCSD_INTERSECTION_PATH" \
  "RCSDROAD_PATH:$RCSDROAD_PATH" \
  "RCSDNODE_PATH:$RCSDNODE_PATH" \
  "SWSD_INPUT_NODES:$SWSD_INPUT_NODES" \
  "SWSD_INPUT_ROADS:$SWSD_INPUT_ROADS"; do
  require_file "${pair%%:*}" "${pair#*:}"
done

manifest_set inputs drivezone "$DRIVEZONE_PATH"
manifest_set inputs divstripzone "$DIVSTRIPZONE_PATH"
manifest_set inputs rcsd_intersection "$RCSD_INTERSECTION_PATH"
manifest_set inputs rcsdroad "$RCSDROAD_PATH"
manifest_set inputs rcsdnode "$RCSDNODE_PATH"
manifest_set inputs swsd_input_nodes "$SWSD_INPUT_NODES"
manifest_set inputs swsd_input_roads "$SWSD_INPUT_ROADS"

RUN_T08="${RUN_T08:-1}"
RUN_T08_TOOL7="${RUN_T08_TOOL7:-auto}"
RUN_T08_TOOL8="${RUN_T08_TOOL8:-auto}"
RUN_T08_TOOL9="${RUN_T08_TOOL9:-0}"

SWSD_NODES_FOR_T01="$SWSD_INPUT_NODES"
SWSD_ROADS_FOR_T01="$SWSD_INPUT_ROADS"
RCSDROAD_FOR_DOWNSTREAM="$RCSDROAD_PATH"
RCSDNODE_FOR_DOWNSTREAM="$RCSDNODE_PATH"
SW_RESTRICTION_TOOL7="${SW_RESTRICTION_TOOL7:-$(first_existing "$FIRST_LAYER_ROOT/t08/sw_restriction_tool7.gpkg" "$FIRST_LAYER_ROOT/T08/sw_restriction_tool7.gpkg")}"
SW_ARROW_TOOL8="${SW_ARROW_TOOL8:-$(first_existing "$FIRST_LAYER_ROOT/t08/sw_arrow_tool8.gpkg" "$FIRST_LAYER_ROOT/T08/sw_arrow_tool8.gpkg")}"

if [[ "$RUN_T08" == "1" ]]; then
  T08_DIR="$RUN_ROOT/t08_preprocess"
  mkdir -p "$T08_DIR"

  T08_TOOL3_NODES="$T08_DIR/t08_nodes_type_aggregation_tool3.gpkg"
  run_logged t08_tool3 \
    "$PYTHON_BIN" scripts/t08_tool3_nodes_type_aggregation.py \
      --nodes-gpkg "$SWSD_INPUT_NODES" \
      --roads-gpkg "$SWSD_INPUT_ROADS" \
      --nodes-output "$T08_TOOL3_NODES" \
      --summary-output "$T08_DIR/t08_nodes_type_aggregation_summary_tool3.json"

  T08_PRE_TOOL6_CSV="$T08_DIR/node_error_pre_tool4_tool6.csv"
  run_logged t08_tool6_pre_tool4 \
    "$PYTHON_BIN" scripts/t08_tool6_nodes_type_qc.py \
      --nodes-gpkg "$T08_TOOL3_NODES" \
      --roads-gpkg "$SWSD_INPUT_ROADS" \
      --csv-output "$T08_PRE_TOOL6_CSV" \
      --error-nodes-output "$T08_DIR/node_error_pre_tool4_tool6.gpkg" \
      --summary-output "$T08_DIR/node_error_pre_tool4_summary_tool6.json"

  T08_TOOL4_NODES="$T08_DIR/t08_junction_type_repair_nodes_tool4.gpkg"
  T08_TOOL4_ROADS="$T08_DIR/t08_junction_type_repair_roads_tool4.gpkg"
  run_logged t08_tool4 \
    "$PYTHON_BIN" scripts/t08_tool4_junction_type_repair.py \
      --nodes-gpkg "$T08_TOOL3_NODES" \
      --roads-gpkg "$SWSD_INPUT_ROADS" \
      --tool6-node-error-csv "$T08_PRE_TOOL6_CSV" \
      --nodes-output "$T08_TOOL4_NODES" \
      --roads-output "$T08_TOOL4_ROADS" \
      --audit-nodes-output "$T08_DIR/t08_junction_type_repair_audit_nodes_tool4.gpkg" \
      --summary-output "$T08_DIR/t08_junction_type_repair_summary_tool4.json"

  T08_TOOL5_NODES="$T08_DIR/t08_complex_junction_nodes_tool5.gpkg"
  T08_TOOL5_ROADS="$T08_DIR/t08_complex_junction_roads_tool5.gpkg"
  run_logged t08_tool5 \
    "$PYTHON_BIN" scripts/t08_tool5_complex_junction_preprocess.py \
      --nodes-gpkg "$T08_TOOL4_NODES" \
      --roads-gpkg "$T08_TOOL4_ROADS" \
      --intersection-gpkg "$RCSD_INTERSECTION_PATH" \
      --nodes-output "$T08_TOOL5_NODES" \
      --roads-output "$T08_TOOL5_ROADS" \
      --audit-nodes-output "$T08_DIR/t08_complex_junction_audit_nodes_tool5.gpkg" \
      --summary-output "$T08_DIR/t08_complex_junction_preprocess_summary_tool5.json"

  run_logged t08_tool6_final \
    "$PYTHON_BIN" scripts/t08_tool6_nodes_type_qc.py \
      --nodes-gpkg "$T08_TOOL5_NODES" \
      --roads-gpkg "$T08_TOOL5_ROADS" \
      --csv-output "$T08_DIR/node_error_final_tool6.csv" \
      --error-nodes-output "$T08_DIR/node_error_final_tool6.gpkg" \
      --summary-output "$T08_DIR/node_error_final_summary_tool6.json"

  SWSD_NODES_FOR_T01="$T08_TOOL5_NODES"
  SWSD_ROADS_FOR_T01="$T08_TOOL5_ROADS"

  if optional_mode_should_run "$RUN_T08_TOOL7" "$SW_CONDITION_GPKG" "$SW_NODE_GPKG" "$SW_ROAD_GPKG"; then
    SW_RESTRICTION_TOOL7="$T08_DIR/sw_restriction_tool7.gpkg"
    run_logged t08_tool7 \
      "$PYTHON_BIN" scripts/t08_tool7_traffic_restriction.py \
        --condition-gpkg "$SW_CONDITION_GPKG" \
        --swnode-gpkg "$SW_NODE_GPKG" \
        --swroad-gpkg "$SW_ROAD_GPKG" \
        --restriction-output "$SW_RESTRICTION_TOOL7" \
        --summary-output "$T08_DIR/sw_restriction_summary_tool7.json"
  fi

  if optional_mode_should_run "$RUN_T08_TOOL8" "$SW_LANE_GPKG" "$SW_NODE_GPKG" "$SW_ROAD_GPKG"; then
    SW_ARROW_TOOL8="$T08_DIR/sw_arrow_tool8.gpkg"
    run_logged t08_tool8 \
      "$PYTHON_BIN" scripts/t08_tool8_lane_arrow.py \
        --lane-gpkg "$SW_LANE_GPKG" \
        --swnode-gpkg "$SW_NODE_GPKG" \
        --swroad-gpkg "$SW_ROAD_GPKG" \
        --arrow-output "$SW_ARROW_TOOL8" \
        --summary-output "$T08_DIR/sw_arrow_summary_tool8.json"
  fi

  if optional_mode_should_run "$RUN_T08_TOOL9" "$RCSDNODE_PATH" "$RCSDROAD_PATH" "$ROAD_SURFACE_GPKG"; then
    RCSDNODE_FOR_DOWNSTREAM="$T08_DIR/rcsdnode_clean_tool9.gpkg"
    RCSDROAD_FOR_DOWNSTREAM="$T08_DIR/rcsdroad_clean_tool9.gpkg"
    run_logged t08_tool9 \
      "$PYTHON_BIN" scripts/t08_tool9_rcsd_cleaning.py \
        --rcsdnode-gpkg "$RCSDNODE_PATH" \
        --rcsdroad-gpkg "$RCSDROAD_PATH" \
        --road-surface-gpkg "$ROAD_SURFACE_GPKG" \
        --nodes-output "$RCSDNODE_FOR_DOWNSTREAM" \
        --roads-output "$RCSDROAD_FOR_DOWNSTREAM" \
        --summary-output "$T08_DIR/rcsd_clean_summary_tool9.json"
  fi
fi

require_file SW_RESTRICTION_TOOL7 "$SW_RESTRICTION_TOOL7"
require_file SW_ARROW_TOOL8 "$SW_ARROW_TOOL8"

manifest_set outputs swsd_nodes_after_t08 "$SWSD_NODES_FOR_T01"
manifest_set outputs swsd_roads_after_t08 "$SWSD_ROADS_FOR_T01"
manifest_set outputs rcsdroad_after_t08 "$RCSDROAD_FOR_DOWNSTREAM"
manifest_set outputs rcsdnode_after_t08 "$RCSDNODE_FOR_DOWNSTREAM"
manifest_set outputs sw_restriction_tool7 "$SW_RESTRICTION_TOOL7"
manifest_set outputs sw_arrow_tool8 "$SW_ARROW_TOOL8"

T01_ROOT="$RUN_ROOT/t01_full_data"
run_logged t01 \
  bash scripts/t01_run_full_data.sh "$SWSD_ROADS_FOR_T01" "$SWSD_NODES_FOR_T01" "$T01_ROOT"
T01_NODES="$T01_ROOT/nodes.gpkg"
T01_ROADS="$T01_ROOT/roads.gpkg"
T01_SEGMENT="$T01_ROOT/segment.gpkg"
require_file T01_NODES "$T01_NODES"
require_file T01_ROADS "$T01_ROADS"
require_file T01_SEGMENT "$T01_SEGMENT"
manifest_set outputs t01_nodes "$T01_NODES"
manifest_set outputs t01_roads "$T01_ROADS"
manifest_set outputs t01_segment "$T01_SEGMENT"

T07_OUT_ROOT="$RUN_ROOT/t07_semantic_junction_anchor"
T07_RUN_ID="t07_step12"
run_logged t07_step12 \
  env NODES_PATH="$T01_NODES" DRIVEZONE_PATH="$DRIVEZONE_PATH" INTERSECTION_PATH="$RCSD_INTERSECTION_PATH" OUT_ROOT="$T07_OUT_ROOT" RUN_ID="$T07_RUN_ID" \
  bash scripts/t07_run_semantic_junction_anchor_innernet.sh
T07_RUN_ROOT="$T07_OUT_ROOT/$T07_RUN_ID"
T07_STEP2_NODES="$T07_RUN_ROOT/step2_anchor_recognition/nodes.gpkg"
T07_STEP2_SURFACE="$T07_RUN_ROOT/step2_anchor_recognition/t07_rcsdintersection_anchor_surface.gpkg"
T07_STEP2_EVIDENCE="$T07_RUN_ROOT/step2_anchor_recognition/t07_swsd_rcsd_relation_evidence.csv"
require_file T07_STEP2_NODES "$T07_STEP2_NODES"
require_file T07_STEP2_SURFACE "$T07_STEP2_SURFACE"
require_file T07_STEP2_EVIDENCE "$T07_STEP2_EVIDENCE"
manifest_set outputs t07_step2_nodes "$T07_STEP2_NODES"
manifest_set outputs t07_step2_surface "$T07_STEP2_SURFACE"
manifest_set outputs t07_step2_relation_evidence "$T07_STEP2_EVIDENCE"

T03_OUT_ROOT="$RUN_ROOT/t03_internal_full_input"
T03_RUN_ID="t03_full"
run_logged t03 \
  env NODES_PATH="$T07_STEP2_NODES" ROADS_PATH="$T01_ROADS" DRIVEZONE_PATH="$DRIVEZONE_PATH" \
    RCSDROAD_PATH="$RCSDROAD_FOR_DOWNSTREAM" RCSDNODE_PATH="$RCSDNODE_FOR_DOWNSTREAM" \
    OUT_ROOT="$T03_OUT_ROOT" RUN_ID="$T03_RUN_ID" WORKERS="${T03_WORKERS:-8}" \
  bash scripts/t03_run_internal_full_input_innernet_flat_review.sh
T03_RUN_ROOT="$T03_OUT_ROOT/$T03_RUN_ID"
T03_NODES="$T03_RUN_ROOT/nodes.gpkg"
T03_SURFACE="$T03_RUN_ROOT/virtual_intersection_polygons.gpkg"
T03_EVIDENCE="$T03_RUN_ROOT/t03_swsd_rcsd_relation_evidence.csv"
T03_INTERSECTION_MATCH="$T03_RUN_ROOT/intersection_match_t03.geojson"
require_file T03_NODES "$T03_NODES"
require_file T03_SURFACE "$T03_SURFACE"
require_file T03_EVIDENCE "$T03_EVIDENCE"
require_file T03_INTERSECTION_MATCH "$T03_INTERSECTION_MATCH"
manifest_set outputs t03_nodes "$T03_NODES"
manifest_set outputs t03_surface "$T03_SURFACE"
manifest_set outputs t03_relation_evidence "$T03_EVIDENCE"
manifest_set outputs t03_intersection_match "$T03_INTERSECTION_MATCH"

T04_OUT_ROOT="$RUN_ROOT/t04_internal_full_input"
T04_RUN_ID="t04_full"
run_logged t04 \
  env NODES_PATH="$T03_NODES" ROADS_PATH="$T01_ROADS" DRIVEZONE_PATH="$DRIVEZONE_PATH" DIVSTRIPZONE_PATH="$DIVSTRIPZONE_PATH" \
    RCSDROAD_PATH="$RCSDROAD_FOR_DOWNSTREAM" RCSDNODE_PATH="$RCSDNODE_FOR_DOWNSTREAM" \
    INTERSECTION_MATCH_T07_PATH="$T07_STEP2_EVIDENCE" INTERSECTION_MATCH_T03_PATH="$T03_INTERSECTION_MATCH" \
    OUT_ROOT="$T04_OUT_ROOT" RUN_ID="$T04_RUN_ID" WORKERS="${T04_WORKERS:-8}" \
  bash scripts/t04_run_internal_full_input_innernet_flat_review.sh
T04_RUN_ROOT="$T04_OUT_ROOT/$T04_RUN_ID"
T04_NODES="$T04_RUN_ROOT/nodes.gpkg"
T04_SURFACE="$T04_RUN_ROOT/divmerge_virtual_anchor_surface.gpkg"
T04_EVIDENCE="$T04_RUN_ROOT/t04_swsd_rcsd_relation_evidence.csv"
T04_SUMMARY="$T04_RUN_ROOT/divmerge_virtual_anchor_surface_summary.json"
T04_AUDIT="$T04_RUN_ROOT/divmerge_virtual_anchor_surface_audit.gpkg"
require_file T04_NODES "$T04_NODES"
require_file T04_SURFACE "$T04_SURFACE"
require_file T04_EVIDENCE "$T04_EVIDENCE"
require_file T04_SUMMARY "$T04_SUMMARY"
require_file T04_AUDIT "$T04_AUDIT"
manifest_set outputs t04_nodes "$T04_NODES"
manifest_set outputs t04_surface "$T04_SURFACE"
manifest_set outputs t04_relation_evidence "$T04_EVIDENCE"
manifest_set outputs t04_summary "$T04_SUMMARY"
manifest_set outputs t04_audit "$T04_AUDIT"

T05_OUT_ROOT="$RUN_ROOT/t05_innernet_experiment"
run_logged t05 \
  "$PYTHON_BIN" scripts/t05_innernet_experiment.py \
    --t07-dir "$T07_RUN_ROOT" \
    --t03-dir "$T03_RUN_ROOT" \
    --t04-dir "$T04_RUN_ROOT" \
    --rcsdroad "$RCSDROAD_FOR_DOWNSTREAM" \
    --rcsdnode "$RCSDNODE_FOR_DOWNSTREAM" \
    --nodes "$T04_NODES" \
    --t07-input "$T07_STEP2_SURFACE" \
    --t07-evidence "$T07_STEP2_EVIDENCE" \
    --t03-surface "$T03_SURFACE" \
    --t03-evidence "$T03_EVIDENCE" \
    --t04-surface "$T04_SURFACE" \
    --t04-evidence "$T04_EVIDENCE" \
    --t04-summary "$T04_SUMMARY" \
    --t04-audit "$T04_AUDIT" \
    --out-root "$T05_OUT_ROOT" \
    --phase1-run-id t05_phase1_innernet \
    --phase2-run-id t05_phase2_innernet \
    --readonly-workers "${T05_READONLY_WORKERS:-4}"
T05_PHASE2_ROOT="$T05_OUT_ROOT/t05_phase2_innernet"
T05_INTERSECTION_MATCH_ALL="$T05_PHASE2_ROOT/intersection_match_all.geojson"
T05_RCSDROAD_OUT="$T05_PHASE2_ROOT/rcsdroad_out.gpkg"
T05_RCSDNODE_OUT="$T05_PHASE2_ROOT/rcsdnode_out.gpkg"
require_file T05_INTERSECTION_MATCH_ALL "$T05_INTERSECTION_MATCH_ALL"
require_file T05_RCSDROAD_OUT "$T05_RCSDROAD_OUT"
require_file T05_RCSDNODE_OUT "$T05_RCSDNODE_OUT"
manifest_set outputs t05_intersection_match_all "$T05_INTERSECTION_MATCH_ALL"
manifest_set outputs t05_rcsdroad_out "$T05_RCSDROAD_OUT"
manifest_set outputs t05_rcsdnode_out "$T05_RCSDNODE_OUT"

T07_STEP3_OUT_ROOT="$RUN_ROOT/t07_step3_intersection_match"
T07_STEP3_RUN_ID="t07_step3"
run_logged t07_step3 \
  env T07_SOURCE_RUN_ROOT="$T07_OUT_ROOT" T07_SOURCE_RUN_ID="$T07_RUN_ID" \
    NODES_PATH="$T07_STEP2_NODES" T05_PHASE2_ROOT="$T05_PHASE2_ROOT" \
    INTERSECTION_MATCH_ALL_PATH="$T05_INTERSECTION_MATCH_ALL" RCSDNODE_PATH="$T05_RCSDNODE_OUT" \
    OUT_ROOT="$T07_STEP3_OUT_ROOT" RUN_ID="$T07_STEP3_RUN_ID" \
  bash scripts/t07_run_step3_intersection_match_innernet.sh
T07_STEP3_ROOT="$T07_STEP3_OUT_ROOT/$T07_STEP3_RUN_ID/step3_intersection_match"
T07_FINAL_NODES="$T07_STEP3_ROOT/nodes.gpkg"
T07_INTERSECTION_MATCH="$T07_STEP3_ROOT/intersection_match_t07.geojson"
require_file T07_FINAL_NODES "$T07_FINAL_NODES"
require_file T07_INTERSECTION_MATCH "$T07_INTERSECTION_MATCH"
manifest_set outputs t07_final_nodes "$T07_FINAL_NODES"
manifest_set outputs t07_intersection_match "$T07_INTERSECTION_MATCH"

T06_OUT_ROOT="$RUN_ROOT/t06_segment_fusion_precheck"
T06_RUN_ID="t06_innernet_precheck"
run_logged t06_step12 \
  "$PYTHON_BIN" scripts/t06_run_innernet_precheck.py \
    --swsd-segment "$T01_SEGMENT" \
    --swsd-roads "$T01_ROADS" \
    --swsd-nodes "$T07_FINAL_NODES" \
    --t05-phase2-root "$T05_PHASE2_ROOT" \
    --intersection-match "$T05_INTERSECTION_MATCH_ALL" \
    --rcsdroad "$T05_RCSDROAD_OUT" \
    --rcsdnode "$T05_RCSDNODE_OUT" \
    --out-root "$T06_OUT_ROOT" \
    --run-id "$T06_RUN_ID"
T06_RUN_ROOT="$T06_OUT_ROOT/$T06_RUN_ID"
T06_REPLACEABLE="$T06_RUN_ROOT/step2_extract_rcsd_segments/t06_rcsd_segment_replaceable.gpkg"
require_file T06_REPLACEABLE "$T06_REPLACEABLE"
manifest_set outputs t06_step2_replaceable "$T06_REPLACEABLE"

run_logged t06_step3 \
  "$PYTHON_BIN" scripts/t06_run_step3_segment_replacement.py \
    --t06-run-root "$T06_RUN_ROOT" \
    --swsd-segment "$T01_SEGMENT" \
    --swsd-roads "$T01_ROADS" \
    --swsd-nodes "$T07_FINAL_NODES" \
    --t05-phase2-root "$T05_PHASE2_ROOT" \
    --rcsdroad "$T05_RCSDROAD_OUT" \
    --rcsdnode "$T05_RCSDNODE_OUT" \
    --out-root "$T06_OUT_ROOT" \
    --run-id "$T06_RUN_ID"
T06_STEP3_ROOT="$T06_RUN_ROOT/step3_segment_replacement"
T06_FRCSD_ROAD="$T06_STEP3_ROOT/t06_frcsd_road.gpkg"
T06_FRCSD_NODE="$T06_STEP3_ROOT/t06_frcsd_node.gpkg"
T06_SEGMENT_RELATION="$T06_STEP3_ROOT/t06_step3_swsd_frcsd_segment_relation.gpkg"
require_file T06_FRCSD_ROAD "$T06_FRCSD_ROAD"
require_file T06_FRCSD_NODE "$T06_FRCSD_NODE"
require_file T06_SEGMENT_RELATION "$T06_SEGMENT_RELATION"
manifest_set outputs t06_frcsd_road "$T06_FRCSD_ROAD"
manifest_set outputs t06_frcsd_node "$T06_FRCSD_NODE"
manifest_set outputs t06_segment_relation "$T06_SEGMENT_RELATION"

T09_OUT_ROOT="$RUN_ROOT/t09_swsd_field_rule_restoration"
run_logged t09 \
  "$PYTHON_BIN" - "$T09_OUT_ROOT" t09_step12 t09_step3 "$T07_FINAL_NODES" "$T01_ROADS" "$T01_SEGMENT" "$SW_RESTRICTION_TOOL7" "$SW_ARROW_TOOL8" "$T06_FRCSD_ROAD" "$T06_FRCSD_NODE" "$T06_SEGMENT_RELATION" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    run_t09_frcsd_restriction_modeling,
    run_t09_swsd_field_rule_restoration,
)

(
    out_root,
    step12_run_id,
    step3_run_id,
    swnode,
    swroad,
    segment,
    restriction,
    arrow,
    frcsd_road,
    frcsd_node,
    segment_relation,
) = sys.argv[1:]

step12 = run_t09_swsd_field_rule_restoration(
    swnode_gpkg=swnode,
    swroad_gpkg=swroad,
    segment_gpkg=segment,
    restriction_gpkg=restriction,
    arrow_gpkg=arrow,
    output_dir=out_root,
    run_id=step12_run_id,
)
step12_root = Path(out_root) / step12_run_id
step3 = run_t09_frcsd_restriction_modeling(
    arms_path=step12.artifacts.arms_gpkg,
    movements_path=step12.artifacts.movements_gpkg,
    restored_rules_path=step12.artifacts.rules_gpkg,
    frcsd_road_path=frcsd_road,
    frcsd_node_path=frcsd_node,
    segment_relation_path=segment_relation,
    output_dir=out_root,
    run_id=step3_run_id,
)

print(
    json.dumps(
        {
            "step12": {
                "run_root": str(step12_root),
                "arms": str(step12.artifacts.arms_gpkg),
                "movements": str(step12.artifacts.movements_gpkg),
                "restored_rules": str(step12.artifacts.rules_gpkg),
                "summary": str(step12.artifacts.summary_json),
                "arm_count": len(step12.result.arms),
                "movement_count": len(step12.result.movements),
                "restored_rule_count": len(step12.result.restored_rules),
            },
            "step3": {
                "run_root": str(step3.artifacts.output_dir),
                "frcsd_restriction_gpkg": str(step3.artifacts.frcsd_restriction_gpkg),
                "summary": str(step3.artifacts.summary_json),
                "restriction_count": step3.restriction_count,
            },
        },
        ensure_ascii=False,
        indent=2,
    )
)
PY
T09_STEP12_ROOT="$T09_OUT_ROOT/t09_step12"
T09_STEP3_ROOT="$T09_OUT_ROOT/t09_step3"
T09_RESTRICTION="$T09_STEP3_ROOT/frcsd_restriction.gpkg"
require_file T09_RESTRICTION "$T09_RESTRICTION"
manifest_set outputs t09_step12_root "$T09_STEP12_ROOT"
manifest_set outputs t09_frcsd_restriction "$T09_RESTRICTION"

echo
echo "[DONE] Innernet full pipeline completed."
echo "[DONE] run_root=$RUN_ROOT"
echo "[DONE] manifest=$MANIFEST_PATH"
echo "[DONE] final_frcsd_road=$T06_FRCSD_ROAD"
echo "[DONE] final_frcsd_node=$T06_FRCSD_NODE"
echo "[DONE] final_restriction=$T09_RESTRICTION"
