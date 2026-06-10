#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/t10_run_e2e_cases.sh --package-dir DIR [--case-id ID ...]

Environment variables:
  OUT_ROOT                 Default: outputs/_work/t10_e2e_case_runs
  RUN_ID                   Optional explicit run id
  STOP_AFTER               Optional stage: t01/t07/t03/t04/t05/t06_step12/t06_step3/t09_step12/t09_step3
  CONTINUE_ON_ERROR        1 or 0. Default: 1
  EXIT_ZERO                1 or 0. Default: 0
  T10_T03_WORKERS          Default: 1
  T10_T04_WORKERS          Default: 1
  T10_T05_READONLY_WORKERS Default: 1
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

if [[ "$CONTINUE_ON_ERROR" != "0" && "$CONTINUE_ON_ERROR" != "1" ]]; then
  echo "[BLOCK] CONTINUE_ON_ERROR must be 0 or 1: $CONTINUE_ON_ERROR" >&2
  exit 2
fi
if [[ "$EXIT_ZERO" != "0" && "$EXIT_ZERO" != "1" ]]; then
  echo "[BLOCK] EXIT_ZERO must be 0 or 1: $EXIT_ZERO" >&2
  exit 2
fi

ARGS=(
  --package-dir "$PACKAGE_DIR"
  --out-root "$OUT_ROOT"
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
for case_id in "${CASE_IDS[@]}"; do
  ARGS+=(--case-id "$case_id")
done

echo "[RUN] T10 E2E case runner"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] PACKAGE_DIR=$PACKAGE_DIR"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=${RUN_ID:-<auto>}"
echo "[RUN] STOP_AFTER=${STOP_AFTER:-<full>}"
echo "[RUN] CONTINUE_ON_ERROR=$CONTINUE_ON_ERROR EXIT_ZERO=$EXIT_ZERO"
if ((${#CASE_IDS[@]})); then
  echo "[RUN] CASE_IDS=${CASE_IDS[*]}"
else
  echo "[RUN] CASE_IDS=<all package cases>"
fi

cd "$REPO_DIR"
PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -c 'from rcsd_topo_poc.modules.t10_e2e_orchestration.case_runner import main; raise SystemExit(main())' "${ARGS[@]}"
