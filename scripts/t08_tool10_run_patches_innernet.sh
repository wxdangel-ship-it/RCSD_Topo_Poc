#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
PYTHON="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
TOOL="${REPO_ROOT}/scripts/t08_tool10_trajectory_aggregation.py"
OVERWRITE="${OVERWRITE:-0}"
DEFAULT_CRS="${DEFAULT_CRS:-}"
MAX_DISTANCE_GAP_M="${MAX_DISTANCE_GAP_M:-10.0}"
MAX_TIME_GAP_S="${MAX_TIME_GAP_S:-1.0}"
MAX_SEQ_GAP="${MAX_SEQ_GAP:-20000000}"
PROGRESS_INTERVAL="${PROGRESS_INTERVAL:-10000}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_ROOT="${LOG_ROOT:-${REPO_ROOT}/outputs/_work/t08_tool10_batch_logs/${RUN_ID}}"

usage() {
  echo "Usage: $(basename "$0") PATCH_DIR [PATCH_DIR ...]" >&2
  echo "PATCH_DIR may be a WSL path or a single-quoted Windows path." >&2
  echo "Set OVERWRITE=1 to replace existing Tool10 outputs." >&2
}

to_wsl_path() {
  local value="$1"
  case "${value}" in
    [A-Za-z]:\\*)
      if ! command -v wslpath >/dev/null 2>&1; then
        echo "ERROR: wslpath is required for Windows input paths: ${value}" >&2
        return 1
      fi
      wslpath -u "${value}"
      ;;
    *)
      printf '%s\n' "${value}"
      ;;
  esac
}

if (( $# == 0 )); then
  usage
  exit 2
fi
PATCHES=("$@")

if [[ ! -x "${PYTHON}" ]]; then
  echo "ERROR: Python executable not found: ${PYTHON}" >&2
  exit 2
fi
if [[ ! -f "${TOOL}" ]]; then
  echo "ERROR: Tool10 entrypoint not found: ${TOOL}" >&2
  exit 2
fi
if [[ "${OVERWRITE}" != "0" && "${OVERWRITE}" != "1" ]]; then
  echo "ERROR: OVERWRITE must be 0 or 1; current value: ${OVERWRITE}" >&2
  exit 2
fi
if ! mkdir -p "${LOG_ROOT}"; then
  echo "ERROR: Cannot create log directory: ${LOG_ROOT}" >&2
  exit 2
fi

echo "T08 Tool10 Patch batch"
echo "repo_root=${REPO_ROOT}"
echo "log_root=${LOG_ROOT}"
echo "overwrite=${OVERWRITE}"
echo "patch_count=${#PATCHES[@]}"

successes=()
failures=()
shopt -s nullglob

for raw_patch_dir in "${PATCHES[@]}"; do
  if ! patch_dir="$(to_wsl_path "${raw_patch_dir}")"; then
    failures+=("${raw_patch_dir}:path_conversion_failed")
    continue
  fi
  patch_dir="${patch_dir%/}"
  patch_id="$(basename "${patch_dir}")"
  log_path="${LOG_ROOT}/${patch_id}.log"
  echo
  echo "===== START ${patch_id} ====="

  if [[ ! -d "${patch_dir}/Traj" ]]; then
    echo "ERROR: Traj directory not found: ${patch_dir}/Traj" | tee "${log_path}" >&2
    failures+=("${patch_id}:missing_traj_directory")
    continue
  fi

  sources=("${patch_dir}"/Traj/*/raw_dat_pose.geojson)
  if (( ${#sources[@]} == 0 )); then
    echo "ERROR: No Traj/*/raw_dat_pose.geojson found: ${patch_dir}" | tee "${log_path}" >&2
    failures+=("${patch_id}:no_trajectory_source")
    continue
  fi

  args=(
    "${PYTHON}"
    "${TOOL}"
    --patch-dir "${patch_dir}"
    --max-distance-gap-m "${MAX_DISTANCE_GAP_M}"
    --max-time-gap-s "${MAX_TIME_GAP_S}"
    --max-seq-gap "${MAX_SEQ_GAP}"
    --progress-interval "${PROGRESS_INTERVAL}"
  )
  if [[ -n "${DEFAULT_CRS}" ]]; then
    args+=(--default-crs "${DEFAULT_CRS}")
  fi
  if [[ "${OVERWRITE}" == "1" ]]; then
    args+=(--overwrite)
  fi

  echo "source_count=${#sources[@]}" | tee "${log_path}"
  if "${args[@]}" 2>&1 | tee -a "${log_path}"; then
    successes+=("${patch_id}")
    echo "output_gpkg=${patch_dir}/Traj/raw_dat_pose.gpkg" | tee -a "${log_path}"
    echo "summary_json=${patch_dir}/Traj/raw_dat_pose_summary_tool10.json" | tee -a "${log_path}"
    echo "===== PASS ${patch_id} ====="
  else
    failures+=("${patch_id}:tool10_failed")
    echo "===== FAIL ${patch_id} =====" >&2
  fi
done

echo
echo "===== BATCH SUMMARY ====="
echo "success_count=${#successes[@]}"
for item in "${successes[@]}"; do
  echo "PASS ${item}"
done
echo "failure_count=${#failures[@]}"
for item in "${failures[@]}"; do
  echo "FAIL ${item}"
done
echo "logs=${LOG_ROOT}"

if (( ${#failures[@]} > 0 )); then
  exit 1
fi
