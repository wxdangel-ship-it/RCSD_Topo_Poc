#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/t10_run_frcsd_quality_pipeline.sh

Purpose:
  Run the dedicated 1V1 FRCSD quality profile:
    T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T11 -> T12 -> T09

Required for a fresh run:
  FRCSD_1V1_ROADS_PATH  Original 1V1 FRCSD road dataset
  FRCSD_1V1_NODES_PATH  Original 1V1 FRCSD node dataset

Optional test-case boundary input:
  T12_CASE_MANIFEST     T10 Case manifest used to exclude explicit crop edges.
                        Leave empty for full-city data.

Optional CRS input:
  T12_PROCESSING_CRS    Explicit projected metre CRS for mixed-CRS T12 inputs.
                        Example: EPSG:3857

Optional reviewed publication input:
  T12_RUN_ID            T12 sub-run ID. Use a new value when resuming reviewed output.
  T12_REVIEW_DECISIONS  Review-decision CSV whose run_id matches T12_RUN_ID.

T12-only resume after an existing T06/T10 run:
  RESUME_RUN_ROOT       Existing T10 full-pipeline run root.
  RUN_STAGES=t12        Run only T12; do not rerun T01-T11 or T09.
  T12_RUN_ID            Optional. Defaults to a new timestamped T12 sub-run ID.
  FRCSD_1V1_ROADS_PATH / FRCSD_1V1_NODES_PATH
                        Optional overrides; otherwise reuse manifest inputs.

Profile invariants:
  RUN_T08=0
  RUN_T12=1
  T11 and T12 are audit-only; T09 continues to consume T06 outputs.

All other input, resume, manifest and summary settings are inherited from:
  scripts/t10_run_innernet_full_pipeline.sh
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

if [[ -n "${RUN_T08+x}" && "$RUN_T08" != "0" ]]; then
  echo "[BLOCK] FRCSD quality profile requires RUN_T08=0; received: $RUN_T08" >&2
  exit 2
fi
if [[ -n "${RUN_T12+x}" && "$RUN_T12" != "1" ]]; then
  echo "[BLOCK] FRCSD quality profile requires RUN_T12=1; received: $RUN_T12" >&2
  exit 2
fi

export RUN_T08=0
export RUN_T12=1
export RUN_ID="${RUN_ID:-t10_frcsd_quality_pipeline_$(date +%Y%m%d_%H%M%S)}"
export OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t10_frcsd_quality_pipeline}"

FINALIZE_EXISTING="${FINALIZE_EXISTING:-0}"
RESUME_RUN_ROOT="${RESUME_RUN_ROOT:-}"
RESUME_FROM_STAGE="${RESUME_FROM_STAGE:-}"
RUN_STAGES="${RUN_STAGES:-}"
if [[ "$RUN_STAGES" == "t12" ]]; then
  if [[ -z "$RESUME_RUN_ROOT" ]]; then
    echo "[BLOCK] RUN_STAGES=t12 requires RESUME_RUN_ROOT for an existing T10 run." >&2
    exit 2
  fi
  export T12_RUN_ID="${T12_RUN_ID:-t12_frcsd_quality_$(date +%Y%m%d_%H%M%S)}"
fi
if [[ "$FINALIZE_EXISTING" != "1" && -z "$RESUME_RUN_ROOT" && -z "$RESUME_FROM_STAGE" && -z "$RUN_STAGES" ]]; then
  if [[ -z "${FRCSD_1V1_ROADS_PATH:-}" || -z "${FRCSD_1V1_NODES_PATH:-}" ]]; then
    echo "[BLOCK] Fresh FRCSD quality run requires FRCSD_1V1_ROADS_PATH and FRCSD_1V1_NODES_PATH." >&2
    exit 2
  fi
fi

echo "[PROFILE] id=frcsd_quality"
echo "[PROFILE] stages=t01,t07_step12,t03,t04,t05,t06_step12,t06_step3,t11,t12,t09"
echo "[PROFILE] RUN_T08=$RUN_T08 RUN_T12=$RUN_T12"
if [[ "$RUN_STAGES" == "t12" ]]; then
  echo "[PROFILE] mode=t12_only_resume RESUME_RUN_ROOT=$RESUME_RUN_ROOT T12_RUN_ID=$T12_RUN_ID"
fi

exec bash "$REPO_DIR/scripts/t10_run_innernet_full_pipeline.sh"
