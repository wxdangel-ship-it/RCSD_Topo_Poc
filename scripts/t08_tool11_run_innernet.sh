#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_SOURCE_ROOT='D:\TestData\数据整理\20260715\20260715\rcsd_tar_gz'
DEFAULT_OUTPUT_ROOT='D:\TestData\POC_QA\Patch_all'
EXPERIMENT_PATCH_IDS=(
  5524185996921171
  5724833136255764
  5524185996921755
  5724833136255765
  5724833136255763
  5524185996921337
)

usage() {
  cat <<'EOF'
Usage:
  bash scripts/t08_tool11_run_innernet.sh

Default innernet paths:
  source:     D:\TestData\数据整理\20260715\20260715\rcsd_tar_gz
  all output: D:\TestData\POC_QA\Patch_all

Default mode:
  Full Patch organization only. No experiment output is created or validated.

Set T08_TOOL11_EXPERIMENT_OUTPUT_ROOT to explicitly enable the optional
experiment output with these pinned PatchIDs:
  5524185996921171 5724833136255764 5524185996921755
  5724833136255765 5724833136255763 5524185996921337

Optional environment overrides:
  T08_TOOL11_SOURCE_ROOT             Source root; Windows or WSL path.
  T08_TOOL11_OUTPUT_ROOT             Full Patch output root; Windows or WSL path.
  T08_TOOL11_EXPERIMENT_OUTPUT_ROOT  Optional experiment output root; unset by default.
  T08_TOOL11_REPO_ROOT               Repository root; defaults to the script parent.
  T08_TOOL11_PYTHON                  Python; defaults to <repo>/.venv/bin/python.
  T08_TOOL11_SUMMARY_OUTPUT          Explicit _tool11.json audit path.
  T08_TOOL11_LOG_FILE                Persistent console log path.
  OVERWRITE                          0 by default; set to 1 to replace requested output roots.
  PROGRESS_INTERVAL_FILES            Progress interval; defaults to 100 files.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if (( $# != 0 )); then
  usage >&2
  exit 2
fi

export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1

to_wsl_path() {
  local value="$1"
  case "$value" in
    [A-Za-z]:\\*|[A-Za-z]:/*)
      if ! command -v wslpath >/dev/null 2>&1; then
        echo "[BLOCK] wslpath is required for Windows path: $value" >&2
        return 1
      fi
      wslpath -u "$value"
      ;;
    *)
      printf '%s\n' "$value"
      ;;
  esac
}

to_windows_path() {
  local value="$1"
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$value" 2>/dev/null || printf '%s\n' "$value"
  else
    printf '%s\n' "$value"
  fi
}

repo_root_raw="${T08_TOOL11_REPO_ROOT:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
source_root_raw="${T08_TOOL11_SOURCE_ROOT:-$DEFAULT_SOURCE_ROOT}"
output_root_raw="${T08_TOOL11_OUTPUT_ROOT:-$DEFAULT_OUTPUT_ROOT}"
experiment_output_root_raw="${T08_TOOL11_EXPERIMENT_OUTPUT_ROOT:-}"

repo_root="$(to_wsl_path "$repo_root_raw")"
source_root="$(to_wsl_path "$source_root_raw")"
output_root="$(to_wsl_path "$output_root_raw")"
experiment_output_root=""
if [[ -n "$experiment_output_root_raw" ]]; then
  experiment_output_root="$(to_wsl_path "$experiment_output_root_raw")"
fi
python_bin_raw="${T08_TOOL11_PYTHON:-$repo_root/.venv/bin/python}"
python_bin="$(to_wsl_path "$python_bin_raw")"
tool="$repo_root/scripts/t08_tool11_patch_data_organization.py"
overwrite="${OVERWRITE:-0}"
progress_interval_files="${PROGRESS_INTERVAL_FILES:-100}"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
log_file_raw="${T08_TOOL11_LOG_FILE:-$repo_root/outputs/_work/t08_tool11_innernet_logs/$run_id.console.log}"
log_file="$(to_wsl_path "$log_file_raw")"

if [[ -n "${T08_TOOL11_SUMMARY_OUTPUT:-}" ]]; then
  summary_output="$(to_wsl_path "$T08_TOOL11_SUMMARY_OUTPUT")"
else
  summary_output="$(dirname "$output_root")/t08_tool11_innernet_${run_id}_tool11.json"
fi

if ! mkdir -p "$(dirname "$log_file")"; then
  echo "[BLOCK] Cannot create log directory: $(dirname "$log_file")" >&2
  exit 2
fi
exec > >(tee -a "$log_file") 2>&1

on_exit() {
  local exit_code=$?
  if (( exit_code == 0 )); then
    echo "[DONE] T08 Tool11 innernet organization passed."
  else
    echo "[FAILED] T08 Tool11 innernet organization exited with code $exit_code."
  fi
  echo "[RESULT] Full Patch root: $(to_windows_path "$output_root")"
  if [[ -n "$experiment_output_root" ]]; then
    echo "[RESULT] Experiment root: $(to_windows_path "$experiment_output_root")"
  else
    echo "[RESULT] Experiment output: disabled"
  fi
  echo "[RESULT] Audit summary: $(to_windows_path "$summary_output")"
  echo "[RESULT] Console log: $(to_windows_path "$log_file")"
}
trap on_exit EXIT

if [[ "$overwrite" != "0" && "$overwrite" != "1" ]]; then
  echo "[BLOCK] OVERWRITE must be 0 or 1; current value: $overwrite" >&2
  exit 2
fi
if [[ ! "$progress_interval_files" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] PROGRESS_INTERVAL_FILES must be a positive integer: $progress_interval_files" >&2
  exit 2
fi
if [[ ! -d "$repo_root" ]]; then
  echo "[BLOCK] Repository root does not exist: $repo_root" >&2
  exit 2
fi
if [[ ! -x "$python_bin" ]]; then
  echo "[BLOCK] Repository Python is not executable: $python_bin" >&2
  exit 2
fi
if [[ ! -f "$tool" ]]; then
  echo "[BLOCK] Formal Tool11 entry is missing: $tool" >&2
  exit 2
fi
if [[ ! -d "$source_root" ]]; then
  echo "[BLOCK] Source root does not exist: $source_root" >&2
  exit 2
fi

echo "[T08 Tool11] Starting innernet Patch organization"
echo "[CHECK] Repository: $repo_root"
echo "[CHECK] Python: $python_bin"
echo "[CHECK] Source: $source_root"
echo "[CHECK] Full output: $output_root"
if [[ -n "$experiment_output_root" ]]; then
  echo "[CHECK] Experiment output: $experiment_output_root"
  echo "[CHECK] Experiment Patch count: ${#EXPERIMENT_PATCH_IDS[@]}"
else
  echo "[CHECK] Experiment output: disabled (full-only mode)"
fi
echo "[CHECK] Overwrite: $overwrite"
echo "[CHECK] Audit summary: $summary_output"
echo "[CHECK] Console log: $log_file"
echo "[RUN] Executing formal Tool11 entry"

args=(
  "$python_bin"
  -u
  "$tool"
  --source-root "$source_root"
  --output-root "$output_root"
  --summary-output "$summary_output"
  --progress-interval-files "$progress_interval_files"
)
if [[ -n "$experiment_output_root" ]]; then
  args+=(--experiment-output-root "$experiment_output_root")
  for patch_id in "${EXPERIMENT_PATCH_IDS[@]}"; do
    args+=(--experiment-patch-id "$patch_id")
  done
fi
if [[ "$overwrite" == "1" ]]; then
  args+=(--overwrite)
fi

cd "$repo_root"
"${args[@]}"

if [[ ! -d "$output_root" ]]; then
  echo "[VERIFY] Tool11 returned success but the full output root is missing." >&2
  exit 1
fi
if [[ -n "$experiment_output_root" && ! -d "$experiment_output_root" ]]; then
  echo "[VERIFY] Tool11 returned success but the experiment output root is missing." >&2
  exit 1
fi
if [[ ! -f "$summary_output" ]]; then
  echo "[VERIFY] Tool11 returned success but the audit summary is missing: $summary_output" >&2
  exit 1
fi

echo "[VERIFY] Requested output roots and the Tool11 audit summary exist."
