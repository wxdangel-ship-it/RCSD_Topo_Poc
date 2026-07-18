#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/t10_run_e2e_cases.sh --package-dir DIR [--case-id ID ...]

Environment variables:
  OUT_ROOT                 Default: outputs/_work/t10_e2e_case_runs
  RUN_ID                   Optional explicit run id
  STOP_AFTER               Optional stage: t01/t07/t03/t04/t05/t06_step12/t06_step3/t11/t12/t09_step12/t09_step3
  CONTINUE_ON_ERROR        1 or 0. Default: 1
  EXIT_ZERO                1 or 0. Default: 0
  T10_T03_WORKERS          Default: detected CPU count, capped at 16
  T10_T04_WORKERS          Default: 1
  T10_T05_READONLY_WORKERS Default: 1
  T10_FEEDBACK_ITERATIONS  Default: 0. When >0, rerun T10 with prior pass endpoint feedback.
  T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS Optional CSV to feed pair-anchor endpoint clusters into T05.
  RUN_T12                  1 enables audit-only T12 after T11. Default: 0.
  T12_REVIEW_DECISIONS     Optional review CSV applied when RUN_T12=1.
  T10_SCRATCH_ROOT         Optional persistent WSL/Linux scratch root; RUN_ID is required.
  T10_KEEP_SCRATCH         1 keeps a successful scratch run; default 0 removes it after publish.
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Missing repo python: $PYTHON_BIN" >&2
  echo "[TIP] Run: make env-sync && make doctor" >&2
  exit 2
fi

PACKAGE_DIR="${PACKAGE_DIR:-}"
CASE_IDS=()

while (($#)); do
  case "$1" in
    --package-dir)
      if (($# < 2)); then
        echo "[BLOCK] --package-dir requires an argument." >&2
        exit 2
      fi
      PACKAGE_DIR="$2"
      shift 2
      ;;
    --case-id)
      if (($# < 2)); then
        echo "[BLOCK] --case-id requires an argument." >&2
        exit 2
      fi
      CASE_IDS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[BLOCK] Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$PACKAGE_DIR" ]]; then
  echo "[BLOCK] --package-dir or PACKAGE_DIR is required." >&2
  usage
  exit 2
fi
if [[ ! -d "$PACKAGE_DIR" ]]; then
  echo "[BLOCK] PACKAGE_DIR does not exist: $PACKAGE_DIR" >&2
  exit 2
fi

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t10_e2e_case_runs}"
RUN_ID="${RUN_ID:-}"
STOP_AFTER="${STOP_AFTER:-}"
CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-1}"
EXIT_ZERO="${EXIT_ZERO:-0}"
T10_FEEDBACK_ITERATIONS="${T10_FEEDBACK_ITERATIONS:-0}"
T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS="${T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS:-}"
RUN_T12="${RUN_T12:-0}"
T12_REVIEW_DECISIONS="${T12_REVIEW_DECISIONS:-}"
T10_SCRATCH_ROOT="${T10_SCRATCH_ROOT:-}"
T10_KEEP_SCRATCH="${T10_KEEP_SCRATCH:-0}"

if [[ "$T10_KEEP_SCRATCH" != "0" && "$T10_KEEP_SCRATCH" != "1" ]]; then
  echo "[BLOCK] T10_KEEP_SCRATCH must be 0 or 1: $T10_KEEP_SCRATCH" >&2
  exit 2
fi
if [[ -n "$T10_SCRATCH_ROOT" && -z "$RUN_ID" ]]; then
  echo "[BLOCK] T10_SCRATCH_ROOT requires an explicit RUN_ID." >&2
  exit 2
fi
if [[ -n "$T10_SCRATCH_ROOT" && "$T10_FEEDBACK_ITERATIONS" != "0" ]]; then
  echo "[BLOCK] T10_SCRATCH_ROOT does not support feedback iterations." >&2
  exit 2
fi

EXEC_OUT_ROOT="$OUT_ROOT"
if [[ -n "$T10_SCRATCH_ROOT" ]]; then
  EXEC_OUT_ROOT="$T10_SCRATCH_ROOT"
  if [[ -e "$EXEC_OUT_ROOT/$RUN_ID" ]]; then
    echo "[BLOCK] Scratch run root already exists: $EXEC_OUT_ROOT/$RUN_ID" >&2
    exit 2
  fi
  if [[ -e "$OUT_ROOT/$RUN_ID" ]]; then
    echo "[BLOCK] Final run root already exists: $OUT_ROOT/$RUN_ID" >&2
    exit 2
  fi
  export STRATEGY_CONFIG="${STRATEGY_CONFIG:-$REPO_DIR/configs/t01_data_preprocess/step1_pair_s2.json}"
fi

if [[ "$CONTINUE_ON_ERROR" != "0" && "$CONTINUE_ON_ERROR" != "1" ]]; then
  echo "[BLOCK] CONTINUE_ON_ERROR must be 0 or 1: $CONTINUE_ON_ERROR" >&2
  exit 2
fi
if [[ "$EXIT_ZERO" != "0" && "$EXIT_ZERO" != "1" ]]; then
  echo "[BLOCK] EXIT_ZERO must be 0 or 1: $EXIT_ZERO" >&2
  exit 2
fi
if [[ "$RUN_T12" != "0" && "$RUN_T12" != "1" ]]; then
  echo "[BLOCK] RUN_T12 must be 0 or 1: $RUN_T12" >&2
  exit 2
fi
if [[ -n "$T12_REVIEW_DECISIONS" && "$RUN_T12" != "1" ]]; then
  echo "[BLOCK] T12_REVIEW_DECISIONS requires RUN_T12=1." >&2
  exit 2
fi
if [[ -n "$T12_REVIEW_DECISIONS" && ! -f "$T12_REVIEW_DECISIONS" ]]; then
  echo "[BLOCK] T12_REVIEW_DECISIONS does not exist: $T12_REVIEW_DECISIONS" >&2
  exit 2
fi
if ! [[ "$T10_FEEDBACK_ITERATIONS" =~ ^[0-9]+$ ]]; then
  echo "[BLOCK] T10_FEEDBACK_ITERATIONS must be a non-negative integer: $T10_FEEDBACK_ITERATIONS" >&2
  exit 2
fi

ARGS=(
  --package-dir "$PACKAGE_DIR"
  --out-root "$EXEC_OUT_ROOT"
)

if [[ -n "$RUN_ID" ]]; then
  ARGS+=(--run-id "$RUN_ID")
fi
if [[ -n "$STOP_AFTER" ]]; then
  ARGS+=(--stop-after "$STOP_AFTER")
fi
if [[ "$CONTINUE_ON_ERROR" == "1" ]]; then
  ARGS+=(--continue-on-error)
else
  ARGS+=(--no-continue-on-error)
fi
if [[ "$EXIT_ZERO" == "1" ]]; then
  ARGS+=(--exit-zero)
fi
if [[ "$T10_FEEDBACK_ITERATIONS" != "0" ]]; then
  ARGS+=(--feedback-iterations "$T10_FEEDBACK_ITERATIONS")
fi
if [[ -n "$T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS" ]]; then
  ARGS+=(--t10-pair-anchor-endpoint-clusters "$T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS")
fi
if [[ "$RUN_T12" == "1" ]]; then
  ARGS+=(--run-t12)
fi
if [[ -n "$T12_REVIEW_DECISIONS" ]]; then
  ARGS+=(--t12-review-decisions "$T12_REVIEW_DECISIONS")
fi
for case_id in "${CASE_IDS[@]}"; do
  ARGS+=(--case-id "$case_id")
done

echo "[RUN] T10 E2E case runner"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] PACKAGE_DIR=$PACKAGE_DIR"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] EXEC_OUT_ROOT=$EXEC_OUT_ROOT"
echo "[RUN] RUN_ID=${RUN_ID:-<auto>}"
echo "[RUN] STOP_AFTER=${STOP_AFTER:-<full>}"
echo "[RUN] CONTINUE_ON_ERROR=$CONTINUE_ON_ERROR EXIT_ZERO=$EXIT_ZERO"
echo "[RUN] T10_FEEDBACK_ITERATIONS=$T10_FEEDBACK_ITERATIONS"
echo "[RUN] T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS=${T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS:-<none>}"
echo "[RUN] RUN_T12=$RUN_T12"
echo "[RUN] T12_REVIEW_DECISIONS=${T12_REVIEW_DECISIONS:-<none>}"
echo "[RUN] T10_SCRATCH_ROOT=${T10_SCRATCH_ROOT:-<disabled>}"
if ((${#CASE_IDS[@]})); then
  echo "[RUN] CASE_IDS=${CASE_IDS[*]}"
else
  echo "[RUN] CASE_IDS=<all package cases>"
fi

cd "$REPO_DIR"
export REPO_DIR
PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -c 'from rcsd_topo_poc.modules.t10_e2e_orchestration.case_runner import main; raise SystemExit(main())' "${ARGS[@]}"

if [[ -n "$T10_SCRATCH_ROOT" ]]; then
  PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" - "$EXEC_OUT_ROOT" "$OUT_ROOT" "$RUN_ID" "$T10_KEEP_SCRATCH" <<'PY'
from __future__ import annotations

import json
import sys

from rcsd_topo_poc.modules.t10_e2e_orchestration.scratch_publish import publish_t10_scratch_run


result = publish_t10_scratch_run(
    scratch_out_root=sys.argv[1],
    final_out_root=sys.argv[2],
    run_id=sys.argv[3],
    keep_scratch=sys.argv[4] == "1",
)
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
fi
