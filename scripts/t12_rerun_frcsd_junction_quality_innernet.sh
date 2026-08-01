#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/t12_rerun_frcsd_junction_quality_innernet.sh

Purpose:
  Re-run T12 in an existing T10 full-pipeline run root.
  An existing standard T12 run is moved to T10 history, then the new result is
  written back to the standard T10 location for continuous T09/finalize runs.

Required environment variables:
  T10_RUN_ROOT              Existing formal T10 full-pipeline run root
  SWSD_SEGMENT_PATH          Formal T01 Segment GPKG
  SWSD_ROADS_PATH            Final SWSD Road dataset
  SWSD_NODES_PATH            Final SWSD Node dataset
  FRCSD_1V1_ROADS_PATH       Original 1V1 FRCSD Road dataset
  FRCSD_1V1_NODES_PATH       Original 1V1 FRCSD Node dataset
  T05_ANCHOR_AUDIT_PATH      Formal T05 intersection_match_all audit CSV
  RCSD_INTERSECTION_PATH     Formal RCSDIntersection dataset
  T06_RUN_ROOT               Formal T06 Step1/2 run root
  T03_RUN_ROOT               Formal T03 run root with rejected audit chains
  T07_RUN_ROOT               Formal T07 Step1/2 run root

Optional environment variables:
  DRIVEZONE_PATH             DriveZone dataset; evidence only
  T12_CASE_MANIFEST          T10 Case manifest for explicit crop-edge audit
  T12_REVIEW_DECISIONS       Segment review override CSV
  T12_PROCESSING_CRS         Explicit projected metre CRS for mixed inputs
  T12_ALLOW_UNVERIFIED_T06_EVIDENCE
                              1 only for explicitly audited historical evidence
  PYTHON_BIN                 Default: <repo>/.venv/bin/python, then python3
  RUN_ID                     Default: t12_full

Outputs:
  <T10_RUN_ROOT>/t12_frcsd_quality_audit/<RUN_ID>/
  Existing standard output is retained under:
  <T10_RUN_ROOT>/history/t12_frcsd_quality_audit/
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if (( $# > 0 )); then
  echo "[BLOCK] Unsupported positional arguments: $*" >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "[BLOCK] Required environment variable is empty: $name" >&2
    exit 2
  fi
}

require_file() {
  local name="$1"
  local value="${!name}"
  if [[ ! -f "$value" ]]; then
    echo "[BLOCK] Required file does not exist: $name=$value" >&2
    exit 2
  fi
}

require_dir() {
  local name="$1"
  local value="${!name}"
  if [[ ! -d "$value" ]]; then
    echo "[BLOCK] Required directory does not exist: $name=$value" >&2
    exit 2
  fi
}

for name in \
  T10_RUN_ROOT \
  SWSD_SEGMENT_PATH \
  SWSD_ROADS_PATH \
  SWSD_NODES_PATH \
  FRCSD_1V1_ROADS_PATH \
  FRCSD_1V1_NODES_PATH \
  T05_ANCHOR_AUDIT_PATH \
  RCSD_INTERSECTION_PATH \
  T06_RUN_ROOT \
  T03_RUN_ROOT \
  T07_RUN_ROOT
do
  require_env "$name"
done

for name in \
  SWSD_SEGMENT_PATH \
  SWSD_ROADS_PATH \
  SWSD_NODES_PATH \
  FRCSD_1V1_ROADS_PATH \
  FRCSD_1V1_NODES_PATH \
  T05_ANCHOR_AUDIT_PATH \
  RCSD_INTERSECTION_PATH
do
  require_file "$name"
done
require_dir T10_RUN_ROOT
require_dir T06_RUN_ROOT
require_dir T03_RUN_ROOT
require_dir T07_RUN_ROOT

for name in DRIVEZONE_PATH T12_CASE_MANIFEST T12_REVIEW_DECISIONS; do
  if [[ -n "${!name:-}" ]]; then
    require_file "$name"
  fi
done
T10_RUN_ROOT="$(cd "$T10_RUN_ROOT" && pwd)"
OUT_ROOT="$T10_RUN_ROOT/t12_frcsd_quality_audit"
HISTORY_ROOT="$T10_RUN_ROOT/history/t12_frcsd_quality_audit"
RUN_ID="${RUN_ID:-t12_full}"
RUN_ROOT="$OUT_ROOT/$RUN_ID"
ARCHIVE_RUN_ROOT=""
restore_archived_run_on_failure() {
  local exit_code=$?
  if [[ "$exit_code" -eq 0 || -z "$ARCHIVE_RUN_ROOT" || ! -d "$ARCHIVE_RUN_ROOT" ]]; then
    return 0
  fi
  if [[ -e "$RUN_ROOT" ]]; then
    local failed_stamp failed_run_root
    failed_stamp="$(date +%Y%m%d_%H%M%S)"
    failed_run_root="$HISTORY_ROOT/${RUN_ID}_failed_${failed_stamp}_$$"
    if [[ ! -e "$failed_run_root" ]]; then
      mv -- "$RUN_ROOT" "$failed_run_root"
      echo "[T12-RERUN] retained_failed_run_root=$failed_run_root" >&2
    else
      echo "[WARN] Cannot retain failed T12 run because history target exists: $failed_run_root" >&2
      return 0
    fi
  fi
  if [[ ! -e "$RUN_ROOT" ]]; then
    mv -- "$ARCHIVE_RUN_ROOT" "$RUN_ROOT"
    echo "[T12-RERUN] restored_previous_run_root=$RUN_ROOT" >&2
  fi
}
trap restore_archived_run_on_failure EXIT
if [[ -e "$RUN_ROOT" ]]; then
  if [[ ! -d "$RUN_ROOT" ]]; then
    echo "[BLOCK] Existing T12 run root is not a directory: $RUN_ROOT" >&2
    exit 2
  fi
  mkdir -p "$HISTORY_ROOT"
  ARCHIVE_STAMP="$(date +%Y%m%d_%H%M%S)"
  ARCHIVE_RUN_ROOT="$HISTORY_ROOT/${RUN_ID}_$ARCHIVE_STAMP"
  if [[ -e "$ARCHIVE_RUN_ROOT" ]]; then
    echo "[BLOCK] T12 history target already exists: $ARCHIVE_RUN_ROOT" >&2
    exit 2
  fi
  mv -- "$RUN_ROOT" "$ARCHIVE_RUN_ROOT"
  echo "[T12-RERUN] archived_run_root=$ARCHIVE_RUN_ROOT"
fi

command=(
  "$PYTHON_BIN"
  "$REPO_DIR/scripts/t12_run_frcsd_quality_audit.py"
  --swsd-segment "$SWSD_SEGMENT_PATH"
  --swsd-roads "$SWSD_ROADS_PATH"
  --swsd-nodes "$SWSD_NODES_PATH"
  --frcsd-roads "$FRCSD_1V1_ROADS_PATH"
  --frcsd-nodes "$FRCSD_1V1_NODES_PATH"
  --t05-anchor-audit "$T05_ANCHOR_AUDIT_PATH"
  --rcsd-intersection "$RCSD_INTERSECTION_PATH"
  --t06-run-root "$T06_RUN_ROOT"
  --t03-run-root "$T03_RUN_ROOT"
  --t07-run-root "$T07_RUN_ROOT"
  --out-root "$OUT_ROOT"
  --run-id "$RUN_ID"
  --progress
)

if [[ -n "${DRIVEZONE_PATH:-}" ]]; then
  command+=(--drivezone "$DRIVEZONE_PATH")
fi
if [[ -n "${T12_CASE_MANIFEST:-}" ]]; then
  command+=(--case-manifest "$T12_CASE_MANIFEST")
fi
if [[ -n "${T12_REVIEW_DECISIONS:-}" ]]; then
  command+=(--review-decisions "$T12_REVIEW_DECISIONS")
fi
if [[ -n "${T12_PROCESSING_CRS:-}" ]]; then
  command+=(--processing-crs "$T12_PROCESSING_CRS")
fi
if [[ "${T12_ALLOW_UNVERIFIED_T06_EVIDENCE:-0}" == "1" ]]; then
  command+=(--allow-unverified-t06-evidence)
elif [[ "${T12_ALLOW_UNVERIFIED_T06_EVIDENCE:-0}" != "0" ]]; then
  echo "[BLOCK] T12_ALLOW_UNVERIFIED_T06_EVIDENCE must be 0 or 1." >&2
  exit 2
fi

echo "[T12-RERUN] repo=$REPO_DIR"
echo "[T12-RERUN] t10_run_root=$T10_RUN_ROOT"
echo "[T12-RERUN] run_root=$RUN_ROOT"
echo "[T12-RERUN] t03_run_root=$T03_RUN_ROOT"
echo "[T12-RERUN] t07_run_root=$T07_RUN_ROOT"
echo "[T12-RERUN] stage=execute"
"${command[@]}"

required_outputs=(
  t12_frcsd_quality_audit_manifest.json
  t12_frcsd_quality_audit_summary.json
  t12_frcsd_confirmed_quality_issues.csv
  t12_frcsd_confirmed_quality_issues.gpkg
  t12_frcsd_confirmed_junction_quality_issues.csv
  t12_frcsd_confirmed_junction_quality_issues.gpkg
  t12_frcsd_junction_quality_candidates.csv
  t12_frcsd_junction_quality_candidates.gpkg
  t12_frcsd_junction_quality_exclusions.csv
  t12_frcsd_junction_carrier_evidence.gpkg
)
for name in "${required_outputs[@]}"; do
  if [[ ! -f "$RUN_ROOT/$name" ]]; then
    echo "[BLOCK] T12 returned success but required output is missing: $RUN_ROOT/$name" >&2
    exit 2
  fi
done

echo "[T12-RERUN] stage=summary"
"$PYTHON_BIN" - "$RUN_ROOT/t12_frcsd_quality_audit_summary.json" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
summary = json.loads(summary_path.read_text(encoding="utf-8"))
segment = summary["counts"]
junction = summary["junction"]["counts"]
runtime = summary["runtime"]
print(
    "[T12-RERUN] segment="
    f"{segment['candidate_count']}/"
    f"{segment['confirmed_quality_issue_count']}/"
    f"{segment['review_exclusion_count']}/"
    f"{segment['manual_review_required_count']}"
)
print(
    "[T12-RERUN] junction="
    f"{junction['candidate_count']}/"
    f"{junction['confirmed_count']}/"
    f"{junction['exclusion_count']}"
)
print(f"[T12-RERUN] elapsed_seconds={runtime['elapsed_seconds']}")
print(f"[T12-RERUN] summary={summary_path.resolve()}")
PY

trap - EXIT
echo "[T12-RERUN] status=passed"
