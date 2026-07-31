#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/t12_rerun_frcsd_junction_quality_innernet.sh

Purpose:
  Re-run T12 only from existing formal upstream artifacts.
  The run keeps Segment LineString outputs and adds independent Junction Point
  outputs from T03 rejected re-verification and optional T07 1:N/N:1 failures.

Required environment variables:
  SWSD_SEGMENT_PATH          Formal T01 Segment GPKG
  SWSD_ROADS_PATH            Final SWSD Road dataset
  SWSD_NODES_PATH            Final SWSD Node dataset
  FRCSD_1V1_ROADS_PATH       Original 1V1 FRCSD Road dataset
  FRCSD_1V1_NODES_PATH       Original 1V1 FRCSD Node dataset
  T05_ANCHOR_AUDIT_PATH      Formal T05 intersection_match_all audit CSV
  RCSD_INTERSECTION_PATH     Formal RCSDIntersection dataset
  T06_RUN_ROOT               Formal T06 Step1/2 run root
  T03_RUN_ROOT               Formal T03 run root with rejected audit chains

Optional environment variables:
  T07_STEP3_RUN_ROOT         T07 Step3 root with relation_cardinality_errors
  DRIVEZONE_PATH             DriveZone dataset; evidence only
  T12_CASE_MANIFEST          T10 Case manifest for explicit crop-edge audit
  T12_REVIEW_DECISIONS       Segment review override CSV
  T12_PROCESSING_CRS         Explicit projected metre CRS for mixed inputs
  T12_ALLOW_UNVERIFIED_T06_EVIDENCE
                              1 only for explicitly audited historical evidence
  PYTHON_BIN                 Default: <repo>/.venv/bin/python, then python3
  OUT_ROOT                   Default: <repo>/outputs/_work/t12_innernet_rerun
  RUN_ID                     Default: t12_innernet_rerun_<timestamp>

Outputs:
  <OUT_ROOT>/<RUN_ID>/
  The script never overwrites an existing run root.
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
  SWSD_SEGMENT_PATH \
  SWSD_ROADS_PATH \
  SWSD_NODES_PATH \
  FRCSD_1V1_ROADS_PATH \
  FRCSD_1V1_NODES_PATH \
  T05_ANCHOR_AUDIT_PATH \
  RCSD_INTERSECTION_PATH \
  T06_RUN_ROOT \
  T03_RUN_ROOT
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
require_dir T06_RUN_ROOT
require_dir T03_RUN_ROOT

for name in DRIVEZONE_PATH T12_CASE_MANIFEST T12_REVIEW_DECISIONS; do
  if [[ -n "${!name:-}" ]]; then
    require_file "$name"
  fi
done
if [[ -n "${T07_STEP3_RUN_ROOT:-}" ]]; then
  require_dir T07_STEP3_RUN_ROOT
fi

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t12_innernet_rerun}"
RUN_ID="${RUN_ID:-t12_innernet_rerun_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="$OUT_ROOT/$RUN_ID"
if [[ -e "$RUN_ROOT" ]]; then
  echo "[BLOCK] Run root already exists; choose a new RUN_ID: $RUN_ROOT" >&2
  exit 2
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
  --out-root "$OUT_ROOT"
  --run-id "$RUN_ID"
  --progress
)

if [[ -n "${T07_STEP3_RUN_ROOT:-}" ]]; then
  command+=(--t07-step3-run-root "$T07_STEP3_RUN_ROOT")
fi
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
echo "[T12-RERUN] run_root=$RUN_ROOT"
echo "[T12-RERUN] t03_run_root=$T03_RUN_ROOT"
echo "[T12-RERUN] t07_step3_run_root=${T07_STEP3_RUN_ROOT:-not_provided}"
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

echo "[T12-RERUN] status=passed"
