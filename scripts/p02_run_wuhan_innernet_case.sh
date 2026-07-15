#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/p02_run_wuhan_innernet_case.sh [raw-input-dir]

Default innernet paths:
  repository: /mnt/d/Work/RCSD_Topo_Poc
  input:      /mnt/d/TestData/数据整理/result/result/5524176501019109_5524182406597110

Optional environment overrides:
  P02_REPO_DIR        Repository root.
  P02_INPUT_DIR       Raw input directory; positional argument takes precedence.
  P02_OUT_ROOT        Output parent directory.
  P02_RUN_ID          Run id using only letters, digits, dot, underscore and hyphen.
  P02_PYTHON_BIN      Repository Python; defaults to <repo>/.venv/bin/python.
  QGIS_PYTHON_BIN     PyQGIS Python; defaults to /usr/bin/python3.
  P02_LOG_FILE        Console log path.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if (( $# > 1 )); then
  usage >&2
  exit 2
fi

export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

repo_dir="${P02_REPO_DIR:-/mnt/d/Work/RCSD_Topo_Poc}"
input_dir="${1:-${P02_INPUT_DIR:-/mnt/d/TestData/数据整理/result/result/5524176501019109_5524182406597110}}"
out_root="${P02_OUT_ROOT:-$repo_dir/outputs/_work/p02_wuhan_local_experiment}"
run_id="${P02_RUN_ID:-p02_wuhan_innernet_$(date +%Y%m%d_%H%M%S)}"
python_bin="${P02_PYTHON_BIN:-$repo_dir/.venv/bin/python}"
qgis_python_bin="${QGIS_PYTHON_BIN:-/usr/bin/python3}"
run_root="$out_root/$run_id"
log_file="${P02_LOG_FILE:-$out_root/$run_id.console.log}"

if [[ ! "$run_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "[BLOCK] P02_RUN_ID contains unsupported characters: $run_id" >&2
  exit 2
fi
if [[ ! -d "$repo_dir" ]]; then
  echo "[BLOCK] Repository directory does not exist: $repo_dir" >&2
  exit 2
fi
if [[ ! -f "$repo_dir/scripts/p02_run_wuhan_internal_case.py" ]]; then
  echo "[BLOCK] Formal P02 Python entry is missing under repository: $repo_dir" >&2
  exit 2
fi

mkdir -p "$out_root" "$(dirname "$log_file")"
exec > >(tee -a "$log_file") 2>&1

on_exit() {
  local exit_code=$?
  if (( exit_code == 0 )); then
    echo "[DONE] P02 innernet Case passed."
    echo "[DONE] Run root: $run_root"
    echo "[DONE] Console log: $log_file"
  else
    echo "[FAILED] P02 innernet Case exited with code $exit_code."
    echo "[FAILED] Run root: $run_root"
    echo "[FAILED] Console log: $log_file"
  fi
}
trap on_exit EXIT

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "[BLOCK] Required file is missing: $path" >&2
    exit 2
  fi
}

echo "[P02] Starting Wuhan innernet Case"
echo "[P02] Repository: $repo_dir"
echo "[P02] Input: $input_dir"
echo "[P02] Output root: $out_root"
echo "[P02] Run id: $run_id"

if [[ ! -x "$python_bin" ]]; then
  echo "[BLOCK] Repository Python is not executable: $python_bin" >&2
  exit 2
fi
if [[ ! -x "$qgis_python_bin" ]]; then
  echo "[BLOCK] QGIS Python is not executable: $qgis_python_bin" >&2
  exit 2
fi
if [[ -e "$run_root" ]]; then
  echo "[BLOCK] Run root already exists; refusing overwrite: $run_root" >&2
  exit 2
fi
if [[ ! -d "$input_dir" ]]; then
  echo "[BLOCK] Input directory does not exist: $input_dir" >&2
  exit 2
fi

for input_name in node.geojson road.geojson RCSDNode.geojson RCSDRoad.geojson; do
  require_file "$input_dir/$input_name"
done

cd "$repo_dir"
echo "[CHECK] Repository Python: $($python_bin --version 2>&1)"
qgis_version="$($qgis_python_bin -c 'from qgis.core import Qgis; print(Qgis.QGIS_VERSION)')"
echo "[CHECK] QGIS: $qgis_version"
echo "[RUN] Executing formal P02 entry with required QGIS QA"

"$python_bin" -u scripts/p02_run_wuhan_internal_case.py \
  --input-dir "$input_dir" \
  --out-root "$out_root" \
  --run-id "$run_id" \
  --qgis-mode required \
  --qgis-python "$qgis_python_bin"

manifest_path="$run_root/p02_run_manifest.json"
validation_path="$run_root/13_qa/p02_current_result_validation.json"
qgis_project_path="$run_root/14_qgis/p02_wuhan_local_analysis.qgz"
qgis_qa_path="$run_root/14_qgis/p02_qgis_project_qa.json"

require_file "$manifest_path"
require_file "$validation_path"
require_file "$qgis_project_path"
require_file "$qgis_qa_path"

"$python_bin" - "$manifest_path" "$validation_path" "$qgis_qa_path" <<'PY'
import json
import sys
from pathlib import Path

manifest_path, validation_path, qgis_qa_path = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
validation = json.loads(validation_path.read_text(encoding="utf-8"))
qgis_qa = json.loads(qgis_qa_path.read_text(encoding="utf-8"))

stages = manifest.get("stages") or []
failed_stages = [
    f"{stage.get('name')}={stage.get('status')}"
    for stage in stages
    if stage.get("status") != "passed"
]
errors = []
if manifest.get("status") != "passed":
    errors.append(f"manifest status={manifest.get('status')}")
if len(stages) != 17:
    errors.append(f"stage count={len(stages)}, expected=17")
if failed_stages:
    errors.append("non-passed stages: " + ", ".join(failed_stages))
if validation.get("status") != "passed" or validation.get("failure_count") != 0:
    errors.append(
        f"result validation status={validation.get('status')} "
        f"failure_count={validation.get('failure_count')}"
    )
if qgis_qa.get("status") not in {"passed", "passed_with_known_limitation"}:
    errors.append(f"QGIS QA status={qgis_qa.get('status')}")
if not qgis_qa.get("project_write_ok") or not qgis_qa.get("project_readback_ok"):
    errors.append("QGIS project write/readback check failed")
if qgis_qa.get("missing_readback_sources"):
    errors.append("QGIS project has missing datasource references")
if qgis_qa.get("absolute_datasource_reference_count") != 0:
    errors.append("QGIS project contains absolute datasource references")
if not qgis_qa.get("preview_render_ok"):
    errors.append("QGIS preview render failed")

if errors:
    raise SystemExit("[VERIFY] " + "; ".join(errors))

print(f"[VERIFY] Manifest passed: {len(stages)}/{len(stages)} stages")
print(f"[VERIFY] Business/GIS validation passed: {len(validation.get('checks') or [])} checks")
print(
    "[VERIFY] QGIS passed: "
    f"{qgis_qa.get('layer_count_loaded')}/{qgis_qa.get('layer_count_expected')} layers, "
    f"version={qgis_qa.get('qgis_version')}"
)
PY

if command -v wslpath >/dev/null 2>&1; then
  echo "[RESULT] Windows run root: $(wslpath -w "$run_root")"
  echo "[RESULT] Windows QGIS project: $(wslpath -w "$qgis_project_path")"
  echo "[RESULT] Windows log: $(wslpath -w "$log_file")"
else
  echo "[RESULT] QGIS project: $qgis_project_path"
fi
