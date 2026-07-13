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
  T08 -> T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 Step1/2 -> T06 Step3 -> T11 -> T09

Common env:
  TESTDATA_ROOT        Default: /mnt/d/TestData/POC_Data
  RUN_ID               Default: t10_innernet_full_pipeline_<timestamp>
  OUT_ROOT             Default: outputs/_work/t10_innernet_full_pipeline
  RUN_T08              1 or 0. Default: 1
  RUN_T08_TOOL7        1, 0 or auto. Default: auto
  RUN_T08_TOOL8        1, 0 or auto. Default: auto
  RUN_T08_TOOL9        1, 0 or auto. Default: 0
  RUN_T07_STEP3        1, 0 or auto. Default: 0. Optional legacy relation-backfill compatibility stage.
  T07_STEP3_INTERSECTION_MATCH_ALL_PATH
                       Optional Step3 compatible relation input. Required when RUN_T07_STEP3=1.
  T07_STEP3_RCSDNODE_PATH
                       Optional Step3 RCSDNode input. Default: downstream RCSDNode.
  T03_WORKERS          Default: 8
  T04_WORKERS          Default: 8
  T05_READONLY_WORKERS Default: 4
  FINALIZE_EXISTING    1 or 0. Default: 0. When 1, only finalize an existing RUN_ID or RESUME_RUN_ROOT.
  RESUME_RUN_ROOT      Existing T10 full-pipeline run root to resume from.
  RESUME_FROM_STAGE    First stage to rerun. Example: t06_step3.
  RUN_STAGES           Optional comma list of exact stages to run.

Input override env:
  SWSD_INPUT_NODES   Prepared SWSD nodes input for T01
  SWSD_INPUT_ROADS   Prepared SWSD roads input for T01
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
RESUME_RUN_ROOT="${RESUME_RUN_ROOT:-}"
if [[ -n "$RESUME_RUN_ROOT" ]]; then
  if [[ -d "$RESUME_RUN_ROOT" ]]; then
    RUN_ROOT="$(cd "$RESUME_RUN_ROOT" && pwd)"
  else
    RUN_ROOT="$RESUME_RUN_ROOT"
  fi
  RUN_ID="$(basename "$RUN_ROOT")"
  OUT_ROOT="$(cd "$(dirname "$RUN_ROOT")" && pwd)"
fi
LOG_ROOT="$RUN_ROOT/logs"
MANIFEST_PATH="$RUN_ROOT/t10_innernet_full_pipeline_manifest.json"
SUMMARY_PATH="$RUN_ROOT/t10_innernet_full_pipeline_summary.json"
PIPELINE_STARTED_EPOCH="$(date +%s)"
RESUME_FROM_STAGE="${RESUME_FROM_STAGE:-}"
RUN_STAGES="${RUN_STAGES:-}"
RUN_T07_STEP3="${RUN_T07_STEP3:-0}"
T07_STEP3_INTERSECTION_MATCH_ALL_PATH="${T07_STEP3_INTERSECTION_MATCH_ALL_PATH:-}"
T07_STEP3_RCSDNODE_PATH="${T07_STEP3_RCSDNODE_PATH:-}"
RESUME_MODE=0
if [[ -n "$RESUME_RUN_ROOT" || -n "$RESUME_FROM_STAGE" || -n "$RUN_STAGES" ]]; then
  RESUME_MODE=1
fi
REQUESTED_STAGES_CSV=""
REQUESTED_STAGES_TEXT=""

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
  set +e
  "$@" 2>&1 | tee "$LOG_ROOT/${stage}.log"
  local status=${PIPESTATUS[0]}
  set -e
  if [[ "$status" -ne 0 ]]; then
    manifest_stage_record "$stage" "" "failed" "$LOG_ROOT/${stage}.log"
    return "$status"
  fi
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

normalize_stage_id() {
  case "$1" in
    t08|t08_preprocess) printf '%s\n' "t08_preprocess" ;;
    t01) printf '%s\n' "t01" ;;
    t07|t07_step12) printf '%s\n' "t07_step12" ;;
    t03) printf '%s\n' "t03" ;;
    t04) printf '%s\n' "t04" ;;
    t05) printf '%s\n' "t05" ;;
    t07_step3) printf '%s\n' "t07_step3" ;;
    t06|t06_step12) printf '%s\n' "t06_step12" ;;
    t06_step3) printf '%s\n' "t06_step3" ;;
    t11|t11_candidates) printf '%s\n' "t11" ;;
    t09) printf '%s\n' "t09" ;;
    *)
      echo "[BLOCK] Unknown T10 full-pipeline stage: $1" >&2
      echo "[TIP] Supported stages: t08_preprocess,t01,t07_step12,t03,t04,t05,t07_step3,t06_step12,t06_step3,t11,t09" >&2
      exit 2
      ;;
  esac
}

stage_index() {
  case "$1" in
    t08_preprocess) printf '%s\n' 0 ;;
    t01) printf '%s\n' 1 ;;
    t07_step12) printf '%s\n' 2 ;;
    t03) printf '%s\n' 3 ;;
    t04) printf '%s\n' 4 ;;
    t05) printf '%s\n' 5 ;;
    t06_step12) printf '%s\n' 6 ;;
    t06_step3) printf '%s\n' 7 ;;
    t11) printf '%s\n' 8 ;;
    t09) printf '%s\n' 9 ;;
    *) printf '%s\n' 99 ;;
  esac
}

init_resume_plan() {
  if [[ "$RESUME_MODE" != "1" ]]; then
    return 0
  fi
  if [[ ! -f "$MANIFEST_PATH" ]]; then
    echo "[BLOCK] Existing manifest does not exist: $MANIFEST_PATH" >&2
    echo "[TIP] Set RESUME_RUN_ROOT to an existing T10 full-pipeline run root, or set RUN_ID/OUT_ROOT to locate it." >&2
    exit 2
  fi
  local token stage start_stage start_index index
  if [[ -n "$RUN_STAGES" ]]; then
    REQUESTED_STAGES_CSV=","
    REQUESTED_STAGES_TEXT=""
    for token in ${RUN_STAGES//,/ }; do
      [[ -n "$token" ]] || continue
      stage="$(normalize_stage_id "$token")"
      if [[ "$REQUESTED_STAGES_CSV" != *",$stage,"* ]]; then
        REQUESTED_STAGES_CSV+="$stage,"
        if [[ -n "$REQUESTED_STAGES_TEXT" ]]; then
          REQUESTED_STAGES_TEXT+=","
        fi
        REQUESTED_STAGES_TEXT+="$stage"
      fi
    done
  else
    if [[ -z "$RESUME_FROM_STAGE" ]]; then
      echo "[BLOCK] Resume mode requires RESUME_FROM_STAGE or RUN_STAGES." >&2
      exit 2
    fi
    start_stage="$(normalize_stage_id "$RESUME_FROM_STAGE")"
    REQUESTED_STAGES_CSV=","
    REQUESTED_STAGES_TEXT=""
    local ordered
    if [[ "$start_stage" == "t07_step3" ]]; then
      ordered=(t07_step3 t06_step12 t06_step3 t11 t09)
      start_index=0
    else
      ordered=(t08_preprocess t01 t07_step12 t03 t04 t05 t06_step12 t06_step3 t11 t09)
      start_index="$(stage_index "$start_stage")"
    fi
    for index in "${!ordered[@]}"; do
      if (( index >= start_index )); then
        stage="${ordered[$index]}"
        REQUESTED_STAGES_CSV+="$stage,"
        if [[ -n "$REQUESTED_STAGES_TEXT" ]]; then
          REQUESTED_STAGES_TEXT+=","
        fi
        REQUESTED_STAGES_TEXT+="$stage"
      fi
    done
  fi
  if [[ "$REQUESTED_STAGES_CSV" == "," ]]; then
    echo "[BLOCK] Resume mode selected no stages." >&2
    exit 2
  fi
  echo "[RESUME] RUN_ROOT=$RUN_ROOT"
  echo "[RESUME] RUN_STAGES=$REQUESTED_STAGES_TEXT"
}

should_run_stage() {
  if [[ "$RESUME_MODE" != "1" ]]; then
    return 0
  fi
  [[ "$REQUESTED_STAGES_CSV" == *",$1,"* ]]
}

should_run_t07_step3() {
  if [[ "$RESUME_MODE" == "1" ]]; then
    if [[ "$REQUESTED_STAGES_CSV" != *",t07_step3,"* ]]; then
      return 1
    fi
    if [[ -z "$T07_STEP3_INTERSECTION_MATCH_ALL_PATH" ]]; then
      echo "[BLOCK] Resuming t07_step3 requires explicit T07_STEP3_INTERSECTION_MATCH_ALL_PATH." >&2
      echo "[TIP] T07 Step3 is an optional compatibility backfill; it is not the default post-T05 stage." >&2
      exit 2
    fi
    return 0
  fi
  if optional_mode_should_run "$RUN_T07_STEP3" "$T07_STEP3_INTERSECTION_MATCH_ALL_PATH" "${T07_STEP3_RCSDNODE_PATH:-$RCSDNODE_FOR_DOWNSTREAM}"; then
    if [[ -z "$T07_STEP3_INTERSECTION_MATCH_ALL_PATH" ]]; then
      echo "[BLOCK] RUN_T07_STEP3=1 requires explicit T07_STEP3_INTERSECTION_MATCH_ALL_PATH." >&2
      echo "[TIP] T07 Step3 is an optional compatibility backfill; it is not the default post-T05 stage." >&2
      exit 2
    fi
    return 0
  fi
  return 1
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
    "status": "running",
    "passed": False,
    "pipeline": [
        "T08",
        "T01",
        "T07 Step1/2",
        "T03",
        "T04",
        "T05",
        "T06 Step1/2",
        "T06 Step3",
        "T11",
        "T09",
    ],
    "inputs": {},
    "outputs": {},
    "stage_order": [],
    "stages": {},
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

manifest_get() {
  local section="$1"
  local key="$2"
  local fallback="$3"
  if [[ ! -f "$MANIFEST_PATH" ]]; then
    printf '%s\n' "$fallback"
    return 0
  fi
  "$PYTHON_BIN" - "$MANIFEST_PATH" "$section" "$key" "$fallback" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
section = sys.argv[2]
key = sys.argv[3]
fallback = sys.argv[4]
payload = json.loads(path.read_text(encoding="utf-8"))
value = (payload.get(section) or {}).get(key)
if section == "outputs" and value in (None, ""):
    stage_output_keys = {
        "swsd_nodes_after_t08": ("t08_preprocess", "swsd_nodes_for_t01"),
        "swsd_roads_after_t08": ("t08_preprocess", "swsd_roads_for_t01"),
        "rcsdroad_after_t08": ("t08_preprocess", "rcsdroad_for_downstream"),
        "rcsdnode_after_t08": ("t08_preprocess", "rcsdnode_for_downstream"),
        "sw_restriction_tool7": ("t08_preprocess", "sw_restriction_tool7"),
        "sw_arrow_tool8": ("t08_preprocess", "sw_arrow_tool8"),
        "t01_nodes": ("t01", "nodes"),
        "t01_roads": ("t01", "roads"),
        "t01_segment": ("t01", "segment"),
        "t07_step2_nodes": ("t07_step12", "nodes"),
        "t07_step2_surface": ("t07_step12", "anchor_surface"),
        "t07_step2_relation_evidence": ("t07_step12", "relation_evidence"),
        "t03_nodes": ("t03", "nodes"),
        "t03_surface": ("t03", "surface"),
        "t03_relation_evidence": ("t03", "relation_evidence"),
        "t03_intersection_match": ("t03", "intersection_match"),
        "t04_nodes": ("t04", "nodes"),
        "final_swsd_nodes": ("t04", "nodes"),
        "t04_surface": ("t04", "surface"),
        "t04_relation_evidence": ("t04", "relation_evidence"),
        "t04_summary": ("t04", "summary"),
        "t04_audit": ("t04", "audit"),
        "t05_junction_surface": ("t05", "junction_surface"),
        "t05_intersection_match_all": ("t05", "intersection_match_all"),
        "t05_rcsdroad_out": ("t05", "rcsdroad_out"),
        "t05_rcsdnode_out": ("t05", "rcsdnode_out"),
        "t07_final_nodes": ("t07_step3", "nodes"),
        "t07_intersection_match": ("t07_step3", "intersection_match"),
        "t06_step2_replaceable": ("t06_step12", "replaceable"),
        "t06_frcsd_road": ("t06_step3", "frcsd_road"),
        "t06_frcsd_node": ("t06_step3", "frcsd_node"),
        "t06_segment_relation": ("t06_step3", "segment_relation"),
        "t06_surface_topology_audit": ("t06_step3", "surface_topology_audit"),
        "t11_run_root": ("t11", "run_root"),
        "t11_candidates_csv": ("t11", "candidates_csv"),
        "t11_summary_json": ("t11", "summary_json"),
        "t09_frcsd_restriction": ("t09", "frcsd_restriction"),
    }
    stage_key = stage_output_keys.get(key)
    if stage_key:
        stage_id, output_key = stage_key
        value = ((payload.get("stages") or {}).get(stage_id) or {}).get("outputs", {}).get(output_key)
print(value if value not in (None, "") else fallback)
PY
}

manifest_stage_record() {
  local stage_id="$1"
  local module_id="$2"
  local status="$3"
  local log_path="$4"
  shift 4
  "$PYTHON_BIN" - "$MANIFEST_PATH" "$stage_id" "$module_id" "$status" "$log_path" "$@" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
stage_id = sys.argv[2]
module_id = sys.argv[3]
status = sys.argv[4]
log_path = sys.argv[5]
payload = json.loads(path.read_text(encoding="utf-8"))
record = {
    "stage_id": stage_id,
    "module_id": module_id,
    "status": status,
    "stdout_log": log_path,
    "inputs": {},
    "outputs": {},
    "params": {},
    "execution_context": {},
}
for item in sys.argv[6:]:
    if "=" not in item or "." not in item.split("=", 1)[0]:
        continue
    section_key, value = item.split("=", 1)
    section, key = section_key.split(".", 1)
    if section not in {"inputs", "outputs", "params", "execution_context"}:
        continue
    record.setdefault(section, {})[key] = value
stages = payload.setdefault("stages", {})
existing = stages.get(stage_id)
if isinstance(existing, dict):
    merged = dict(existing)
    for key, value in record.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            child = dict(merged[key])
            child.update(value)
            merged[key] = child
        elif value not in ("", {}, []):
            merged[key] = value
    record = merged
stages[stage_id] = record
order = payload.setdefault("stage_order", [])
if stage_id not in order:
    if stage_id == "t11" and "t09" in order:
        order.insert(order.index("t09"), stage_id)
    else:
        order.append(stage_id)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

manifest_finalize() {
  local status="$1"
  local exit_code="$2"
  "$PYTHON_BIN" - "$MANIFEST_PATH" "$SUMMARY_PATH" "$status" "$exit_code" "$PIPELINE_STARTED_EPOCH" <<'PY'
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

manifest_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
status = sys.argv[3]
exit_code = int(sys.argv[4])
started_epoch = float(sys.argv[5])

payload = json.loads(manifest_path.read_text(encoding="utf-8"))
finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
duration_seconds = round(time.time() - started_epoch, 6)
stages = payload.get("stages") or {}
outputs = payload.setdefault("outputs", {})
run_root = Path(payload.get("run_root") or manifest_path.parent)


def _existing_output(flat_key: str, stage_id: str, stage_key: str, fallback: str) -> str:
    value = outputs.get(flat_key) or (stages.get(stage_id) or {}).get("outputs", {}).get(stage_key) or ""
    if not value:
        value = str(run_root / fallback)
    if value and Path(value).is_file():
        outputs[flat_key] = value
    return value


def _existing_t11_output(flat_key: str, stage_key: str, filename: str) -> str:
    value = outputs.get(flat_key) or (stages.get("t11") or {}).get("outputs", {}).get(stage_key) or ""
    if not value:
        matches = sorted(run_root.glob(f"t11_manual_relation_review/run_*/{filename}"))
        value = str(matches[-1]) if matches else ""
    if value and Path(value).is_file():
        outputs[flat_key] = value
    return value


t06_frcsd_road = _existing_output(
    "t06_frcsd_road",
    "t06_step3",
    "frcsd_road",
    "t06_segment_fusion_precheck/t06_innernet_precheck/step3_segment_replacement/t06_frcsd_road.gpkg",
)
t06_frcsd_node = _existing_output(
    "t06_frcsd_node",
    "t06_step3",
    "frcsd_node",
    "t06_segment_fusion_precheck/t06_innernet_precheck/step3_segment_replacement/t06_frcsd_node.gpkg",
)
t11_candidates_csv = _existing_t11_output(
    "t11_candidates_csv",
    "candidates_csv",
    "t11_relation_repair_candidates.csv",
)
t11_summary_json = _existing_t11_output(
    "t11_summary_json",
    "summary_json",
    "t11_relation_repair_candidate_summary.json",
)
t09_frcsd_restriction = _existing_output(
    "t09_frcsd_restriction",
    "t09",
    "frcsd_restriction",
    "t09_swsd_field_rule_restoration/t09_step3/frcsd_restriction.gpkg",
)
missing_final_outputs = [
    key
    for key, value in {
        "t06_frcsd_road": t06_frcsd_road,
        "t06_frcsd_node": t06_frcsd_node,
        "t11_candidates_csv": t11_candidates_csv,
        "t11_summary_json": t11_summary_json,
        "t09_frcsd_restriction": t09_frcsd_restriction,
    }.items()
    if not value or not Path(value).is_file()
]
if (stages.get("t11") or {}).get("status") != "passed":
    missing_final_outputs.append("t11_stage")
passed = status == "passed" and exit_code == 0 and not missing_final_outputs
final_status = "passed" if passed else "failed"
final_exit_code = exit_code if not (status == "passed" and missing_final_outputs) else 2
payload["status"] = final_status
payload["passed"] = passed
payload["exit_code"] = final_exit_code
payload["finished_at_utc"] = finished_at
payload["duration_seconds"] = duration_seconds
payload["summary_path"] = str(summary_path)
stage_statuses = {
    stage_id: (record or {}).get("status", "missing")
    for stage_id, record in stages.items()
}
summary = {
    "module_id": "t10_e2e_orchestration",
    "run_id": payload.get("run_id"),
    "run_root": payload.get("run_root"),
    "repo_dir": payload.get("repo_dir"),
    "status": payload["status"],
    "passed": passed,
    "exit_code": final_exit_code,
    "created_at_utc": payload.get("created_at_utc"),
    "finished_at_utc": finished_at,
    "duration_seconds": duration_seconds,
    "stage_count": len(stages),
    "stage_order": payload.get("stage_order", []),
    "stage_statuses": stage_statuses,
    "missing_final_outputs": missing_final_outputs,
    "t06_frcsd_road": t06_frcsd_road,
    "t06_frcsd_node": t06_frcsd_node,
    "t11_candidates_csv": t11_candidates_csv,
    "t11_summary_json": t11_summary_json,
    "t09_frcsd_restriction": t09_frcsd_restriction,
    "manifest": str(manifest_path),
}
manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

finalize_existing_run() {
  if [[ ! -f "$MANIFEST_PATH" ]]; then
    echo "[BLOCK] Existing manifest does not exist: $MANIFEST_PATH" >&2
    exit 2
  fi
  manifest_finalize passed 0
  local finalized_status
  finalized_status="$("$PYTHON_BIN" - "$SUMMARY_PATH" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(summary.get("status") or "")
PY
)"
  echo "[DONE] Finalized existing innernet full pipeline run."
  echo "[DONE] run_root=$RUN_ROOT"
  echo "[DONE] manifest=$MANIFEST_PATH"
  echo "[DONE] summary=$SUMMARY_PATH"
  echo "[DONE] status=$finalized_status"
  if [[ "$finalized_status" != "passed" ]]; then
    exit 2
  fi
}

pipeline_exit_trap() {
  local exit_code=$?
  if [[ "$exit_code" -ne 0 && -f "$MANIFEST_PATH" ]]; then
    manifest_finalize failed "$exit_code" || true
  fi
}

validate_swsd_t01_inputs() {
  local nodes_path="$1"
  local roads_path="$2"
  "$PYTHON_BIN" - "$nodes_path" "$roads_path" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import fiona


def _schema(path: Path) -> tuple[str, set[str], str]:
    try:
        layers = list(fiona.listlayers(str(path)))
        if not layers:
            raise ValueError("GeoPackage has no layers.")
        layer = layers[0]
        with fiona.open(str(path), layer=layer) as source:
            schema = source.schema or {}
            fields = {str(key).lower() for key in (schema.get("properties") or {}).keys()}
            geometry = str(schema.get("geometry") or "")
        return layer, fields, geometry
    except Exception as exc:  # noqa: BLE001 - shell preflight should surface the original path.
        print(f"[BLOCK] cannot inspect vector schema: {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


nodes_path = Path(sys.argv[1])
roads_path = Path(sys.argv[2])
node_layer, node_fields, node_geometry = _schema(nodes_path)
road_layer, road_fields, road_geometry = _schema(roads_path)
road_required = {"snodeid", "enodeid"}
errors: list[str] = []

if nodes_path.resolve() == roads_path.resolve():
    errors.append("SWSD_INPUT_NODES and SWSD_INPUT_ROADS point to the same file.")
if "id" not in node_fields:
    errors.append("SWSD_INPUT_NODES is missing required node field 'id'.")
if road_required.issubset(node_fields):
    errors.append("SWSD_INPUT_NODES looks like a road layer because it has snodeid/enodeid.")
missing_road_fields = sorted(road_required - road_fields)
if missing_road_fields:
    errors.append(f"SWSD_INPUT_ROADS is missing required road fields: {', '.join(missing_road_fields)}.")

if errors:
    print("[BLOCK] T01 SWSD input role validation failed.", file=sys.stderr)
    print(
        f"[BLOCK] nodes={nodes_path} layer={node_layer} geometry={node_geometry} "
        f"fields={','.join(sorted(node_fields))}",
        file=sys.stderr,
    )
    print(
        f"[BLOCK] roads={roads_path} layer={road_layer} geometry={road_geometry} "
        f"fields={','.join(sorted(road_fields))}",
        file=sys.stderr,
    )
    for error in errors:
        print(f"[BLOCK] {error}", file=sys.stderr)
    if road_required.issubset(node_fields) and not road_required.issubset(road_fields):
        print(
            "[TIP] SWSD_INPUT_NODES and SWSD_INPUT_ROADS appear to be swapped.",
            file=sys.stderr,
        )
    raise SystemExit(2)

print(
    f"[INFO] T01 input role validation passed: "
    f"nodes_layer={node_layer} roads_layer={road_layer}"
)
PY
}

export REPO_DIR RUN_ID RUN_ROOT
FINALIZE_EXISTING="${FINALIZE_EXISTING:-0}"
if [[ "$FINALIZE_EXISTING" == "1" ]]; then
  finalize_existing_run
  exit 0
fi

if [[ "$RESUME_MODE" == "1" ]]; then
  init_resume_plan
  trap pipeline_exit_trap EXIT
  manifest_set resume mode "stage_resume"
  manifest_set resume requested_stages "$REQUESTED_STAGES_TEXT"
  manifest_set resume updated_at_utc "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
else
  write_manifest
  trap pipeline_exit_trap EXIT
fi

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

if [[ "$RESUME_MODE" == "1" ]]; then
  DRIVEZONE_PATH="$(manifest_get inputs drivezone "$DRIVEZONE_PATH")"
  DIVSTRIPZONE_PATH="$(manifest_get inputs divstripzone "$DIVSTRIPZONE_PATH")"
  RCSD_INTERSECTION_PATH="$(manifest_get inputs rcsd_intersection "$RCSD_INTERSECTION_PATH")"
  RCSDROAD_PATH="$(manifest_get inputs rcsdroad "$RCSDROAD_PATH")"
  RCSDNODE_PATH="$(manifest_get inputs rcsdnode "$RCSDNODE_PATH")"
  SWSD_INPUT_NODES="$(manifest_get inputs swsd_input_nodes "$SWSD_INPUT_NODES")"
  SWSD_INPUT_ROADS="$(manifest_get inputs swsd_input_roads "$SWSD_INPUT_ROADS")"
else
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
fi

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

if [[ "$RESUME_MODE" == "1" ]]; then
  SWSD_NODES_FOR_T01="$(manifest_get outputs swsd_nodes_after_t08 "$SWSD_NODES_FOR_T01")"
  SWSD_ROADS_FOR_T01="$(manifest_get outputs swsd_roads_after_t08 "$SWSD_ROADS_FOR_T01")"
  RCSDROAD_FOR_DOWNSTREAM="$(manifest_get outputs rcsdroad_after_t08 "$RCSDROAD_FOR_DOWNSTREAM")"
  RCSDNODE_FOR_DOWNSTREAM="$(manifest_get outputs rcsdnode_after_t08 "$RCSDNODE_FOR_DOWNSTREAM")"
  SW_RESTRICTION_TOOL7="$(manifest_get outputs sw_restriction_tool7 "$SW_RESTRICTION_TOOL7")"
  SW_ARROW_TOOL8="$(manifest_get outputs sw_arrow_tool8 "$SW_ARROW_TOOL8")"
fi

if [[ "$RUN_T08" == "1" ]] && should_run_stage t08_preprocess; then
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

if [[ "$RESUME_MODE" != "1" ]] || should_run_stage t09; then
  require_file SW_RESTRICTION_TOOL7 "$SW_RESTRICTION_TOOL7"
  require_file SW_ARROW_TOOL8 "$SW_ARROW_TOOL8"
fi
if [[ "$RESUME_MODE" != "1" ]] || should_run_stage t08_preprocess || should_run_stage t01; then
  validate_swsd_t01_inputs "$SWSD_NODES_FOR_T01" "$SWSD_ROADS_FOR_T01"
fi

if [[ "$RESUME_MODE" != "1" ]] || should_run_stage t08_preprocess; then
  manifest_set outputs swsd_nodes_after_t08 "$SWSD_NODES_FOR_T01"
  manifest_set outputs swsd_roads_after_t08 "$SWSD_ROADS_FOR_T01"
  manifest_set outputs rcsdroad_after_t08 "$RCSDROAD_FOR_DOWNSTREAM"
  manifest_set outputs rcsdnode_after_t08 "$RCSDNODE_FOR_DOWNSTREAM"
  manifest_set outputs sw_restriction_tool7 "$SW_RESTRICTION_TOOL7"
  manifest_set outputs sw_arrow_tool8 "$SW_ARROW_TOOL8"
  T08_STAGE_STATUS="skipped"
  T08_STAGE_LOG=""
  if [[ "$RUN_T08" == "1" ]] && should_run_stage t08_preprocess; then
    T08_STAGE_STATUS="passed"
    T08_STAGE_LOG="$LOG_ROOT/t08_tool6_final.log"
  fi
  manifest_stage_record t08_preprocess T08 "$T08_STAGE_STATUS" "$T08_STAGE_LOG" \
    "inputs.swsd_nodes=$SWSD_INPUT_NODES" \
    "inputs.swsd_roads=$SWSD_INPUT_ROADS" \
    "inputs.rcsdroad=$RCSDROAD_PATH" \
    "inputs.rcsdnode=$RCSDNODE_PATH" \
    "outputs.swsd_nodes_for_t01=$SWSD_NODES_FOR_T01" \
    "outputs.swsd_roads_for_t01=$SWSD_ROADS_FOR_T01" \
    "outputs.rcsdroad_for_downstream=$RCSDROAD_FOR_DOWNSTREAM" \
    "outputs.rcsdnode_for_downstream=$RCSDNODE_FOR_DOWNSTREAM" \
    "outputs.sw_restriction_tool7=$SW_RESTRICTION_TOOL7" \
    "outputs.sw_arrow_tool8=$SW_ARROW_TOOL8" \
    "execution_context.run_t08=$RUN_T08"
fi

T01_ROOT="$RUN_ROOT/t01_full_data"
if should_run_stage t01; then
  run_logged t01 \
    bash scripts/t01_run_full_data.sh "$SWSD_ROADS_FOR_T01" "$SWSD_NODES_FOR_T01" "$T01_ROOT"
fi
T01_NODES="$(manifest_get outputs t01_nodes "$T01_ROOT/nodes.gpkg")"
T01_ROADS="$(manifest_get outputs t01_roads "$T01_ROOT/roads.gpkg")"
T01_SEGMENT="$(manifest_get outputs t01_segment "$T01_ROOT/segment.gpkg")"
require_file T01_NODES "$T01_NODES"
require_file T01_ROADS "$T01_ROADS"
require_file T01_SEGMENT "$T01_SEGMENT"
if should_run_stage t01; then
  manifest_set outputs t01_nodes "$T01_NODES"
  manifest_set outputs t01_roads "$T01_ROADS"
  manifest_set outputs t01_segment "$T01_SEGMENT"
  manifest_stage_record t01 T01 passed "$LOG_ROOT/t01.log" \
    "inputs.roads=$SWSD_ROADS_FOR_T01" \
    "inputs.nodes=$SWSD_NODES_FOR_T01" \
    "outputs.nodes=$T01_NODES" \
    "outputs.roads=$T01_ROADS" \
    "outputs.segment=$T01_SEGMENT" \
    "execution_context.run_root=$T01_ROOT"
fi

T07_OUT_ROOT="$RUN_ROOT/t07_semantic_junction_anchor"
T07_RUN_ID="t07_step12"
if should_run_stage t07_step12; then
  run_logged t07_step12 \
    env NODES_PATH="$T01_NODES" DRIVEZONE_PATH="$DRIVEZONE_PATH" INTERSECTION_PATH="$RCSD_INTERSECTION_PATH" RCSDNODE_PATH="$RCSDNODE_FOR_DOWNSTREAM" OUT_ROOT="$T07_OUT_ROOT" RUN_ID="$T07_RUN_ID" \
    bash scripts/t07_run_semantic_junction_anchor_innernet.sh
fi
T07_RUN_ROOT="$T07_OUT_ROOT/$T07_RUN_ID"
T07_STEP2_NODES="$(manifest_get outputs t07_step2_nodes "$T07_RUN_ROOT/step2_anchor_recognition/nodes.gpkg")"
T07_STEP2_SURFACE="$(manifest_get outputs t07_step2_surface "$T07_RUN_ROOT/step2_anchor_recognition/t07_rcsdintersection_anchor_surface.gpkg")"
T07_STEP2_EVIDENCE="$(manifest_get outputs t07_step2_relation_evidence "$T07_RUN_ROOT/step2_anchor_recognition/t07_swsd_rcsd_relation_evidence.csv")"
require_file T07_STEP2_NODES "$T07_STEP2_NODES"
require_file T07_STEP2_SURFACE "$T07_STEP2_SURFACE"
require_file T07_STEP2_EVIDENCE "$T07_STEP2_EVIDENCE"
if should_run_stage t07_step12; then
  manifest_set outputs t07_step2_nodes "$T07_STEP2_NODES"
  manifest_set outputs t07_step2_surface "$T07_STEP2_SURFACE"
  manifest_set outputs t07_step2_relation_evidence "$T07_STEP2_EVIDENCE"
  manifest_stage_record t07_step12 T07 passed "$LOG_ROOT/t07_step12.log" \
    "inputs.nodes=$T01_NODES" \
    "inputs.drivezone=$DRIVEZONE_PATH" \
    "inputs.rcsd_intersection=$RCSD_INTERSECTION_PATH" \
    "outputs.nodes=$T07_STEP2_NODES" \
    "outputs.anchor_surface=$T07_STEP2_SURFACE" \
    "outputs.relation_evidence=$T07_STEP2_EVIDENCE" \
    "execution_context.run_root=$T07_RUN_ROOT"
fi

T03_OUT_ROOT="$RUN_ROOT/t03_internal_full_input"
T03_RUN_ID="t03_full"
if should_run_stage t03; then
  run_logged t03 \
    env NODES_PATH="$T07_STEP2_NODES" ROADS_PATH="$T01_ROADS" DRIVEZONE_PATH="$DRIVEZONE_PATH" \
      RCSDROAD_PATH="$RCSDROAD_FOR_DOWNSTREAM" RCSDNODE_PATH="$RCSDNODE_FOR_DOWNSTREAM" \
      OUT_ROOT="$T03_OUT_ROOT" RUN_ID="$T03_RUN_ID" WORKERS="${T03_WORKERS:-8}" \
    bash scripts/t03_run_internal_full_input_innernet_flat_review.sh
fi
T03_RUN_ROOT="$T03_OUT_ROOT/$T03_RUN_ID"
T03_NODES="$(manifest_get outputs t03_nodes "$T03_RUN_ROOT/nodes.gpkg")"
T03_SURFACE="$(manifest_get outputs t03_surface "$T03_RUN_ROOT/virtual_intersection_polygons.gpkg")"
T03_EVIDENCE="$(manifest_get outputs t03_relation_evidence "$T03_RUN_ROOT/t03_swsd_rcsd_relation_evidence.csv")"
T03_INTERSECTION_MATCH="$(manifest_get outputs t03_intersection_match "$T03_RUN_ROOT/intersection_match_t03.geojson")"
require_file T03_NODES "$T03_NODES"
require_file T03_SURFACE "$T03_SURFACE"
require_file T03_EVIDENCE "$T03_EVIDENCE"
require_file T03_INTERSECTION_MATCH "$T03_INTERSECTION_MATCH"
if should_run_stage t03; then
  manifest_set outputs t03_nodes "$T03_NODES"
  manifest_set outputs t03_surface "$T03_SURFACE"
  manifest_set outputs t03_relation_evidence "$T03_EVIDENCE"
  manifest_set outputs t03_intersection_match "$T03_INTERSECTION_MATCH"
  manifest_stage_record t03 T03 passed "$LOG_ROOT/t03.log" \
    "inputs.nodes=$T07_STEP2_NODES" \
    "inputs.roads=$T01_ROADS" \
    "inputs.drivezone=$DRIVEZONE_PATH" \
    "inputs.rcsdroad=$RCSDROAD_FOR_DOWNSTREAM" \
    "inputs.rcsdnode=$RCSDNODE_FOR_DOWNSTREAM" \
    "outputs.nodes=$T03_NODES" \
    "outputs.surface=$T03_SURFACE" \
    "outputs.relation_evidence=$T03_EVIDENCE" \
    "outputs.intersection_match=$T03_INTERSECTION_MATCH" \
    "params.workers=${T03_WORKERS:-8}" \
    "execution_context.run_root=$T03_RUN_ROOT"
fi

T04_OUT_ROOT="$RUN_ROOT/t04_internal_full_input"
T04_RUN_ID="t04_full"
if should_run_stage t04; then
  run_logged t04 \
    env NODES_PATH="$T03_NODES" ROADS_PATH="$T01_ROADS" DRIVEZONE_PATH="$DRIVEZONE_PATH" DIVSTRIPZONE_PATH="$DIVSTRIPZONE_PATH" \
      RCSDROAD_PATH="$RCSDROAD_FOR_DOWNSTREAM" RCSDNODE_PATH="$RCSDNODE_FOR_DOWNSTREAM" \
      INTERSECTION_MATCH_T07_PATH="$T07_STEP2_EVIDENCE" INTERSECTION_MATCH_T03_PATH="$T03_INTERSECTION_MATCH" \
      OUT_ROOT="$T04_OUT_ROOT" RUN_ID="$T04_RUN_ID" WORKERS="${T04_WORKERS:-8}" \
    bash scripts/t04_run_internal_full_input_innernet_flat_review.sh
fi
T04_RUN_ROOT="$T04_OUT_ROOT/$T04_RUN_ID"
T04_NODES="$(manifest_get outputs t04_nodes "$T04_RUN_ROOT/nodes.gpkg")"
T04_SURFACE="$(manifest_get outputs t04_surface "$T04_RUN_ROOT/divmerge_virtual_anchor_surface.gpkg")"
T04_EVIDENCE="$(manifest_get outputs t04_relation_evidence "$T04_RUN_ROOT/t04_swsd_rcsd_relation_evidence.csv")"
T04_SUMMARY="$(manifest_get outputs t04_summary "$T04_RUN_ROOT/divmerge_virtual_anchor_surface_summary.json")"
T04_AUDIT="$(manifest_get outputs t04_audit "$T04_RUN_ROOT/divmerge_virtual_anchor_surface_audit.gpkg")"
require_file T04_NODES "$T04_NODES"
require_file T04_SURFACE "$T04_SURFACE"
require_file T04_EVIDENCE "$T04_EVIDENCE"
require_file T04_SUMMARY "$T04_SUMMARY"
require_file T04_AUDIT "$T04_AUDIT"
if should_run_stage t04; then
  manifest_set outputs t04_nodes "$T04_NODES"
  manifest_set outputs t04_surface "$T04_SURFACE"
  manifest_set outputs t04_relation_evidence "$T04_EVIDENCE"
  manifest_set outputs t04_summary "$T04_SUMMARY"
  manifest_set outputs t04_audit "$T04_AUDIT"
  manifest_stage_record t04 T04 passed "$LOG_ROOT/t04.log" \
    "inputs.nodes=$T03_NODES" \
    "inputs.roads=$T01_ROADS" \
    "inputs.drivezone=$DRIVEZONE_PATH" \
    "inputs.divstripzone=$DIVSTRIPZONE_PATH" \
    "inputs.rcsdroad=$RCSDROAD_FOR_DOWNSTREAM" \
    "inputs.rcsdnode=$RCSDNODE_FOR_DOWNSTREAM" \
    "inputs.t07_relation_evidence=$T07_STEP2_EVIDENCE" \
    "inputs.t03_intersection_match=$T03_INTERSECTION_MATCH" \
    "outputs.nodes=$T04_NODES" \
    "outputs.surface=$T04_SURFACE" \
    "outputs.relation_evidence=$T04_EVIDENCE" \
    "outputs.summary=$T04_SUMMARY" \
    "outputs.audit=$T04_AUDIT" \
    "params.workers=${T04_WORKERS:-8}" \
    "execution_context.run_root=$T04_RUN_ROOT"
fi

T05_OUT_ROOT="$RUN_ROOT/t05_innernet_experiment"
if should_run_stage t05; then
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
fi
T05_PHASE2_ROOT="$T05_OUT_ROOT/t05_phase2_innernet"
T05_PHASE1_ROOT="$T05_OUT_ROOT/t05_phase1_innernet"
T05_JUNCTION_SURFACE="$(manifest_get outputs t05_junction_surface "$T05_PHASE1_ROOT/junction_anchor_surface.gpkg")"
T05_INTERSECTION_MATCH_ALL="$(manifest_get outputs t05_intersection_match_all "$T05_PHASE2_ROOT/intersection_match_all.geojson")"
T05_RCSDROAD_OUT="$(manifest_get outputs t05_rcsdroad_out "$T05_PHASE2_ROOT/rcsdroad_out.gpkg")"
T05_RCSDNODE_OUT="$(manifest_get outputs t05_rcsdnode_out "$T05_PHASE2_ROOT/rcsdnode_out.gpkg")"
require_file T05_JUNCTION_SURFACE "$T05_JUNCTION_SURFACE"
require_file T05_INTERSECTION_MATCH_ALL "$T05_INTERSECTION_MATCH_ALL"
require_file T05_RCSDROAD_OUT "$T05_RCSDROAD_OUT"
require_file T05_RCSDNODE_OUT "$T05_RCSDNODE_OUT"
if should_run_stage t05; then
  manifest_set outputs t05_junction_surface "$T05_JUNCTION_SURFACE"
  manifest_set outputs t05_intersection_match_all "$T05_INTERSECTION_MATCH_ALL"
  manifest_set outputs t05_rcsdroad_out "$T05_RCSDROAD_OUT"
  manifest_set outputs t05_rcsdnode_out "$T05_RCSDNODE_OUT"
  manifest_stage_record t05 T05 passed "$LOG_ROOT/t05.log" \
    "inputs.t07_run_root=$T07_RUN_ROOT" \
    "inputs.t03_run_root=$T03_RUN_ROOT" \
    "inputs.t04_run_root=$T04_RUN_ROOT" \
    "inputs.nodes=$T04_NODES" \
    "inputs.rcsdroad=$RCSDROAD_FOR_DOWNSTREAM" \
    "inputs.rcsdnode=$RCSDNODE_FOR_DOWNSTREAM" \
    "inputs.t07_surface=$T07_STEP2_SURFACE" \
    "inputs.t07_evidence=$T07_STEP2_EVIDENCE" \
    "inputs.t03_surface=$T03_SURFACE" \
    "inputs.t03_evidence=$T03_EVIDENCE" \
    "inputs.t04_surface=$T04_SURFACE" \
    "inputs.t04_evidence=$T04_EVIDENCE" \
    "inputs.t04_summary=$T04_SUMMARY" \
    "inputs.t04_audit=$T04_AUDIT" \
    "outputs.junction_surface=$T05_JUNCTION_SURFACE" \
    "outputs.intersection_match_all=$T05_INTERSECTION_MATCH_ALL" \
    "outputs.rcsdroad_out=$T05_RCSDROAD_OUT" \
    "outputs.rcsdnode_out=$T05_RCSDNODE_OUT" \
    "params.readonly_workers=${T05_READONLY_WORKERS:-4}" \
    "execution_context.run_root=$T05_PHASE2_ROOT"
fi

T07_STEP3_OUT_ROOT="$RUN_ROOT/t07_step3_intersection_match"
T07_STEP3_RUN_ID="t07_step3"
T07_STEP3_RCSDNODE_INPUT="${T07_STEP3_RCSDNODE_PATH:-$RCSDNODE_FOR_DOWNSTREAM}"
if should_run_t07_step3; then
  require_file T07_STEP3_INTERSECTION_MATCH_ALL_PATH "$T07_STEP3_INTERSECTION_MATCH_ALL_PATH"
  require_file T07_STEP3_RCSDNODE_INPUT "$T07_STEP3_RCSDNODE_INPUT"
  run_logged t07_step3 \
    env T07_SOURCE_RUN_ROOT="$T07_OUT_ROOT" T07_SOURCE_RUN_ID="$T07_RUN_ID" \
      NODES_PATH="$T07_STEP2_NODES" \
      INTERSECTION_MATCH_ALL_PATH="$T07_STEP3_INTERSECTION_MATCH_ALL_PATH" RCSDNODE_PATH="$T07_STEP3_RCSDNODE_INPUT" \
      OUT_ROOT="$T07_STEP3_OUT_ROOT" RUN_ID="$T07_STEP3_RUN_ID" \
    bash scripts/t07_run_step3_intersection_match_innernet.sh
fi
T07_STEP3_ROOT="$T07_STEP3_OUT_ROOT/$T07_STEP3_RUN_ID/step3_intersection_match"
T07_FINAL_NODES="$(manifest_get outputs t07_final_nodes "$T07_STEP2_NODES")"
T07_INTERSECTION_MATCH="$(manifest_get outputs t07_intersection_match "$T07_STEP3_ROOT/intersection_match_t07.geojson")"
if should_run_t07_step3; then
  T07_FINAL_NODES="$T07_STEP3_ROOT/nodes.gpkg"
fi
require_file T07_FINAL_NODES "$T07_FINAL_NODES"
if should_run_t07_step3; then
  require_file T07_INTERSECTION_MATCH "$T07_INTERSECTION_MATCH"
  manifest_set outputs t07_final_nodes "$T07_FINAL_NODES"
  manifest_set outputs t07_intersection_match "$T07_INTERSECTION_MATCH"
  manifest_stage_record t07_step3 T07 passed "$LOG_ROOT/t07_step3.log" \
    "inputs.nodes=$T07_STEP2_NODES" \
    "inputs.intersection_match_all=$T07_STEP3_INTERSECTION_MATCH_ALL_PATH" \
    "inputs.rcsdnode=$T07_STEP3_RCSDNODE_INPUT" \
    "outputs.nodes=$T07_FINAL_NODES" \
    "outputs.intersection_match=$T07_INTERSECTION_MATCH" \
    "execution_context.run_root=$T07_STEP3_ROOT"
else
  manifest_set outputs t07_final_nodes "$T07_FINAL_NODES"
fi
FINAL_SWSD_NODES="$(manifest_get outputs final_swsd_nodes "$T04_NODES")"
require_file FINAL_SWSD_NODES "$FINAL_SWSD_NODES"
manifest_set outputs final_swsd_nodes "$FINAL_SWSD_NODES"

T06_OUT_ROOT="$RUN_ROOT/t06_segment_fusion_precheck"
T06_RUN_ID="t06_innernet_precheck"
if should_run_stage t06_step12; then
  run_logged t06_step12 \
    "$PYTHON_BIN" scripts/t06_run_innernet_precheck.py \
      --swsd-segment "$T01_SEGMENT" \
      --swsd-roads "$T01_ROADS" \
      --swsd-nodes "$FINAL_SWSD_NODES" \
      --t05-phase2-root "$T05_PHASE2_ROOT" \
      --intersection-match "$T05_INTERSECTION_MATCH_ALL" \
      --rcsdroad "$T05_RCSDROAD_OUT" \
      --rcsdnode "$T05_RCSDNODE_OUT" \
      --out-root "$T06_OUT_ROOT" \
      --run-id "$T06_RUN_ID"
fi
T06_RUN_ROOT="$T06_OUT_ROOT/$T06_RUN_ID"
T06_REPLACEABLE="$(manifest_get outputs t06_step2_replaceable "$T06_RUN_ROOT/step2_extract_rcsd_segments/t06_rcsd_segment_replaceable.gpkg")"
require_file T06_REPLACEABLE "$T06_REPLACEABLE"
if should_run_stage t06_step12; then
  manifest_set outputs t06_step2_replaceable "$T06_REPLACEABLE"
  manifest_stage_record t06_step12 T06 passed "$LOG_ROOT/t06_step12.log" \
    "inputs.swsd_segment=$T01_SEGMENT" \
    "inputs.swsd_roads=$T01_ROADS" \
    "inputs.swsd_nodes=$FINAL_SWSD_NODES" \
    "inputs.t05_phase2_root=$T05_PHASE2_ROOT" \
    "inputs.intersection_match=$T05_INTERSECTION_MATCH_ALL" \
    "inputs.rcsdroad=$T05_RCSDROAD_OUT" \
    "inputs.rcsdnode=$T05_RCSDNODE_OUT" \
    "outputs.final_fusion_units=$T06_RUN_ROOT/step1_identify_fusion_units/t06_swsd_segment_final_fusion_units.gpkg" \
    "outputs.replaceable=$T06_REPLACEABLE" \
    "outputs.rejected=$T06_RUN_ROOT/step2_extract_rcsd_segments/t06_rcsd_segment_rejected.gpkg" \
    "outputs.failure_business_audit=$T06_RUN_ROOT/step2_extract_rcsd_segments/t06_rcsd_segment_failure_business_audit.gpkg" \
    "outputs.summary=$T06_RUN_ROOT/step2_extract_rcsd_segments/t06_step2_summary.json" \
    "execution_context.run_root=$T06_RUN_ROOT"
fi

if should_run_stage t06_step3; then
  run_logged t06_step3 \
    "$PYTHON_BIN" scripts/t06_run_step3_segment_replacement.py \
      --t06-run-root "$T06_RUN_ROOT" \
      --swsd-segment "$T01_SEGMENT" \
      --swsd-roads "$T01_ROADS" \
      --swsd-nodes "$FINAL_SWSD_NODES" \
      --t05-phase2-root "$T05_PHASE2_ROOT" \
      --rcsdroad "$T05_RCSDROAD_OUT" \
      --rcsdnode "$T05_RCSDNODE_OUT" \
      --t07-surface "$T07_STEP2_SURFACE" \
      --t03-surface "$T03_SURFACE" \
      --t04-surface "$T04_SURFACE" \
      --t04-audit "$T04_AUDIT" \
      --t05-surface "$T05_JUNCTION_SURFACE" \
      --surface-topology-closure \
      --out-root "$T06_OUT_ROOT" \
      --run-id "$T06_RUN_ID"
fi
T06_STEP3_ROOT="$T06_RUN_ROOT/step3_segment_replacement"
T06_FRCSD_ROAD="$(manifest_get outputs t06_frcsd_road "$T06_STEP3_ROOT/t06_frcsd_road.gpkg")"
T06_FRCSD_NODE="$(manifest_get outputs t06_frcsd_node "$T06_STEP3_ROOT/t06_frcsd_node.gpkg")"
T06_SEGMENT_RELATION="$(manifest_get outputs t06_segment_relation "$T06_STEP3_ROOT/t06_step3_swsd_frcsd_segment_relation.gpkg")"
T06_SURFACE_TOPOLOGY_AUDIT="$(manifest_get outputs t06_surface_topology_audit "$T06_STEP3_ROOT/t06_step3_surface_topology_audit.gpkg")"
require_file T06_FRCSD_ROAD "$T06_FRCSD_ROAD"
require_file T06_FRCSD_NODE "$T06_FRCSD_NODE"
require_file T06_SEGMENT_RELATION "$T06_SEGMENT_RELATION"
if should_run_stage t06_step3; then
  require_file T06_SURFACE_TOPOLOGY_AUDIT "$T06_SURFACE_TOPOLOGY_AUDIT"
fi
if should_run_stage t06_step3; then
  manifest_set outputs t06_frcsd_road "$T06_FRCSD_ROAD"
  manifest_set outputs t06_frcsd_node "$T06_FRCSD_NODE"
  manifest_set outputs t06_segment_relation "$T06_SEGMENT_RELATION"
  manifest_set outputs t06_surface_topology_audit "$T06_SURFACE_TOPOLOGY_AUDIT"
  manifest_stage_record t06_step3 T06 passed "$LOG_ROOT/t06_step3.log" \
    "inputs.t06_run_root=$T06_RUN_ROOT" \
    "inputs.swsd_segment=$T01_SEGMENT" \
    "inputs.swsd_roads=$T01_ROADS" \
    "inputs.swsd_nodes=$FINAL_SWSD_NODES" \
    "inputs.t05_phase2_root=$T05_PHASE2_ROOT" \
    "inputs.rcsdroad=$T05_RCSDROAD_OUT" \
    "inputs.rcsdnode=$T05_RCSDNODE_OUT" \
    "inputs.t07_surface=$T07_STEP2_SURFACE" \
    "inputs.t03_surface=$T03_SURFACE" \
    "inputs.t04_surface=$T04_SURFACE" \
    "inputs.t04_audit=$T04_AUDIT" \
    "inputs.t05_surface=$T05_JUNCTION_SURFACE" \
    "outputs.frcsd_road=$T06_FRCSD_ROAD" \
    "outputs.frcsd_node=$T06_FRCSD_NODE" \
    "outputs.segment_relation=$T06_SEGMENT_RELATION" \
    "outputs.surface_topology_audit=$T06_SURFACE_TOPOLOGY_AUDIT" \
    "outputs.summary=$T06_STEP3_ROOT/t06_step3_summary.json" \
    "execution_context.run_root=$T06_STEP3_ROOT"
fi

T11_OUT_ROOT="$RUN_ROOT/t11_manual_relation_review"
if should_run_stage t11; then
  run_logged t11 \
    "$PYTHON_BIN" scripts/t11_extract_relation_repair_candidates.py \
      --t10-case-root "$RUN_ROOT" \
      --out-root "$T11_OUT_ROOT" \
      --case-id "$RUN_ID"
fi
T11_RUN_ROOT="$(manifest_get outputs t11_run_root "")"
if should_run_stage t11; then
  T11_RUN_ROOT="$("$PYTHON_BIN" - "$LOG_ROOT/t11.log" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
start = text.find("{")
if start < 0:
    print("")
else:
    try:
        print(json.loads(text[start:]).get("run_root") or "")
    except json.JSONDecodeError:
        print("")
PY
)"
fi
if [[ -z "$T11_RUN_ROOT" && -d "$T11_OUT_ROOT" ]]; then
  T11_RUN_ROOT="$(find "$T11_OUT_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'run_*' -print | sort | tail -n 1)"
fi
if [[ -z "$T11_RUN_ROOT" ]]; then
  T11_RUN_ROOT="$T11_OUT_ROOT/run_missing"
fi
T11_CANDIDATES_CSV="$(manifest_get outputs t11_candidates_csv "$T11_RUN_ROOT/t11_relation_repair_candidates.csv")"
T11_SUMMARY_JSON="$(manifest_get outputs t11_summary_json "$T11_RUN_ROOT/t11_relation_repair_candidate_summary.json")"
require_file T11_CANDIDATES_CSV "$T11_CANDIDATES_CSV"
require_file T11_SUMMARY_JSON "$T11_SUMMARY_JSON"
if should_run_stage t11; then
  manifest_set outputs t11_run_root "$T11_RUN_ROOT"
  manifest_set outputs t11_candidates_csv "$T11_CANDIDATES_CSV"
  manifest_set outputs t11_summary_json "$T11_SUMMARY_JSON"
  manifest_stage_record t11 T11 passed "$LOG_ROOT/t11.log" \
    "inputs.t10_run_root=$RUN_ROOT" \
    "inputs.t06_step3_root=$T06_STEP3_ROOT" \
    "outputs.run_root=$T11_RUN_ROOT" \
    "outputs.candidates_csv=$T11_CANDIDATES_CSV" \
    "outputs.summary_json=$T11_SUMMARY_JSON" \
    "execution_context.run_root=$T11_RUN_ROOT"
fi

T09_OUT_ROOT="$RUN_ROOT/t09_swsd_field_rule_restoration"
if should_run_stage t09; then
  run_logged t09 \
    "$PYTHON_BIN" - "$T09_OUT_ROOT" t09_step12 t09_step3 "$FINAL_SWSD_NODES" "$T01_ROADS" "$T01_SEGMENT" "$SW_RESTRICTION_TOOL7" "$SW_ARROW_TOOL8" "$T06_FRCSD_ROAD" "$T06_FRCSD_NODE" "$T06_SEGMENT_RELATION" <<'PY'
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
fi
T09_STEP12_ROOT="$T09_OUT_ROOT/t09_step12"
T09_STEP3_ROOT="$T09_OUT_ROOT/t09_step3"
T09_RESTRICTION="$(manifest_get outputs t09_frcsd_restriction "$T09_STEP3_ROOT/frcsd_restriction.gpkg")"
require_file T09_RESTRICTION "$T09_RESTRICTION"
if should_run_stage t09; then
  manifest_set outputs t09_step12_root "$T09_STEP12_ROOT"
  manifest_set outputs t09_frcsd_restriction "$T09_RESTRICTION"
  manifest_stage_record t09 T09 passed "$LOG_ROOT/t09.log" \
    "inputs.swnode=$FINAL_SWSD_NODES" \
    "inputs.swroad=$T01_ROADS" \
    "inputs.segment=$T01_SEGMENT" \
    "inputs.sw_restriction_tool7=$SW_RESTRICTION_TOOL7" \
    "inputs.sw_arrow_tool8=$SW_ARROW_TOOL8" \
    "inputs.frcsd_road=$T06_FRCSD_ROAD" \
    "inputs.frcsd_node=$T06_FRCSD_NODE" \
    "inputs.segment_relation=$T06_SEGMENT_RELATION" \
    "outputs.step12_root=$T09_STEP12_ROOT" \
    "outputs.frcsd_restriction=$T09_RESTRICTION" \
    "outputs.summary=$T09_STEP3_ROOT/t09_step3_frcsd_restriction_summary.json" \
    "execution_context.run_root=$T09_OUT_ROOT"
fi

manifest_finalize passed 0
trap - EXIT

echo
echo "[DONE] Innernet full pipeline completed."
echo "[DONE] run_root=$RUN_ROOT"
echo "[DONE] manifest=$MANIFEST_PATH"
echo "[DONE] summary=$SUMMARY_PATH"
echo "[DONE] final_frcsd_road=$T06_FRCSD_ROAD"
echo "[DONE] final_frcsd_node=$T06_FRCSD_NODE"
echo "[DONE] t11_candidates=$T11_CANDIDATES_CSV"
echo "[DONE] final_restriction=$T09_RESTRICTION"
