#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="${REPO_ROOT:-$(cd "$script_dir/.." && pwd)}"
python_bin="${PYTHON:-$repo_root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  python_bin="${PYTHON:-python3}"
fi
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -n "${BUNDLE_TXT:-}" || -n "${BUNDLE_DIR:-}" || -n "${CASE_ROOT:-}" ]]; then
  echo "[BLOCK] p01_run_innernet_case.sh consumes full SH inputs directly; BUNDLE_* and CASE_ROOT are not supported." >&2
  exit 2
fi

junction_group="${JUNCTION_GROUP:-}"
if [[ -z "$junction_group" ]]; then
  case_id_required="${CASE_ID:-}"
  rcsd_junction_id="${RCSD_JUNCTION_ID:-}"
  frcsd_junction_id="${FRCSD_JUNCTION_ID:-}"
  if [[ -z "$case_id_required" || -z "$rcsd_junction_id" || -z "$frcsd_junction_id" ]]; then
    echo "[BLOCK] Provide JUNCTION_GROUP or CASE_ID + RCSD_JUNCTION_ID + FRCSD_JUNCTION_ID." >&2
    exit 2
  fi
  junction_group="${case_id_required},${rcsd_junction_id},${frcsd_junction_id}"
fi
if [[ "$junction_group" == *";"* ]]; then
  echo "[BLOCK] This is a case-level runner; provide exactly one JUNCTION_GROUP, not a semicolon list." >&2
  exit 2
fi

case_id="${CASE_ID:-${junction_group%%,*}}"
out_root="${OUT_ROOT:-${E2E_ROOT:-$repo_root/outputs/_work/p01_case_e2e}}"
run_id="${RUN_ID:-p01_${case_id}_e2e_$(date +%Y%m%d_%H%M%S)}"
align_run_id="${A2_RUN_ID:-${ALIGN_RUN_ID:-${run_id}_a2}}"
case_scope_bfs_depth="${CASE_SCOPE_BFS_DEPTH:-8}"
run_a2="${RUN_A2:-1}"
right_turn_values="${RIGHT_TURN_FORMWAY_VALUE-128}"

swsd_nodes="${SWSD_NODES:-/mnt/d/TestData/SH/SWSD/node.gpkg}"
swsd_roads="${SWSD_ROADS:-/mnt/d/TestData/SH/SWSD/road.gpkg}"
rcsd_nodes="${RCSD_NODES:-/mnt/d/TestData/SH/RCSD/RCSDNode.gpkg}"
rcsd_roads="${RCSD_ROADS:-/mnt/d/TestData/SH/RCSD/RCSDRoad.gpkg}"
frcsd_nodes="${FRCSD_NODES:-/mnt/d/TestData/SH/FRCSD/RCSDNode.gpkg}"
frcsd_roads="${FRCSD_ROADS:-/mnt/d/TestData/SH/FRCSD/RCSDRoad.gpkg}"
swsd_rnr="${SWSD_ROAD_NEXT_ROAD:-/mnt/d/TestData/SH/SWSD/road_topo.json}"
rcsd_rnr="${RCSD_ROAD_NEXT_ROAD:-/mnt/d/TestData/SH/RCSD/RCSDRoadNextRoad.geojson}"
frcsd_rnr="${FRCSD_ROAD_NEXT_ROAD:-}"

case_dir="$out_root/$case_id"
raw_a1_out_root="$case_dir/_raw/p01_final_runner"
raw_a2_out_root="$case_dir/_raw/p01_alignment_runner"
raw_a1_run_root="$raw_a1_out_root/$run_id"
raw_a2_run_root="$raw_a2_out_root/$align_run_id"

mkdir -p "$case_dir" "$raw_a1_out_root" "$raw_a2_out_root"
case_dir_abs="$(cd "$case_dir" && pwd)"

for required_path in "$swsd_nodes" "$swsd_roads" "$rcsd_nodes" "$rcsd_roads" "$frcsd_nodes" "$frcsd_roads"; do
  if [[ ! -f "$required_path" ]]; then
    echo "[BLOCK] Required input file is missing: $required_path" >&2
    exit 2
  fi
done
for optional_rnr in "$swsd_rnr" "$rcsd_rnr" "$frcsd_rnr"; do
  if [[ -n "$optional_rnr" && ! -f "$optional_rnr" ]]; then
    echo "[BLOCK] RoadNextRoad input is configured but missing: $optional_rnr" >&2
    exit 2
  fi
done

copy_tree_contents() {
  local src="$1"
  local dst="$2"
  [[ -d "$src" ]] || return 0
  mkdir -p "$dst"
  cp -a "$src"/. "$dst"/
}

copy_file_if_exists() {
  local src="$1"
  local dst="$2"
  [[ -f "$src" ]] || return 0
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
}

clean_case_outputs() {
  rm -rf \
    "$case_dir/SWSD" \
    "$case_dir/RCSD" \
    "$case_dir/FRCSD" \
    "$case_dir/compare" \
    "$case_dir/alignment" \
    "$case_dir/review" \
    "$case_dir/summary" \
    "$case_dir/case_input.json" \
    "$case_dir/case_scope.json" \
    "$case_dir/latest_run_id.txt" \
    "$case_dir/latest_raw_a1_run_root.txt" \
    "$case_dir/latest_raw_a2_run_root.txt"
}

run_a1_final() {
  local args=(
    --swsd-nodes "$swsd_nodes"
    --swsd-roads "$swsd_roads"
    --rcsd-nodes "$rcsd_nodes"
    --rcsd-roads "$rcsd_roads"
    --frcsd-nodes "$frcsd_nodes"
    --frcsd-roads "$frcsd_roads"
    --junction-group "$junction_group"
    --out-root "$raw_a1_out_root"
    --run-id "$run_id"
    --case-scope-bfs-depth "$case_scope_bfs_depth"
  )

  if [[ -n "$swsd_rnr" ]]; then
    args+=(--swsd-road-next-road "$swsd_rnr")
  fi
  if [[ -n "$rcsd_rnr" ]]; then
    args+=(--rcsd-road-next-road "$rcsd_rnr")
  fi
  if [[ -n "$frcsd_rnr" ]]; then
    args+=(--frcsd-road-next-road "$frcsd_rnr")
  fi
  if [[ -n "$right_turn_values" ]]; then
    IFS=',' read -r -a values <<< "$right_turn_values"
    for value in "${values[@]}"; do
      [[ -z "$value" ]] && continue
      args+=(--right-turn-formway-value "$value")
    done
  fi

  "$python_bin" - "${args[@]}" <<'PY'
import sys
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args

raise SystemExit(run_p01_arm_build_from_args(sys.argv[1:]))
PY
}

run_alignment() {
  [[ "$run_a2" == "0" || "$run_a2" == "false" || "$run_a2" == "FALSE" ]] && return 0
  "$python_bin" - "$raw_a1_run_root" "$raw_a2_out_root" "$align_run_id" <<'PY'
import sys
from rcsd_topo_poc.modules.p01_arm_build.alignment_runner import run_p01_arm_alignment_from_args

raise SystemExit(
    run_p01_arm_alignment_from_args(
        [
            "--arm-build-run-root",
            sys.argv[1],
            "--out-root",
            sys.argv[2],
            "--run-id",
            sys.argv[3],
        ]
    )
)
PY
}

publish_review_aliases() {
  local review_dir="$case_dir/review"
  mkdir -p "$review_dir"
  copy_file_if_exists \
    "$case_dir/FRCSD/p01_arm_movement_turn_audit.png" \
    "$review_dir/visual_1_frcsd_arm_movement_turn_audit.png"
  copy_file_if_exists \
    "$case_dir/FRCSD/frcsd_pass_capability_audit.png" \
    "$review_dir/visual_2_frcsd_pass_capability_audit.png"
}

mirror_outputs() {
  local group_dir="$raw_a1_run_root/cases/group_0001"

  clean_case_outputs
  mkdir -p "$case_dir/summary"
  copy_file_if_exists "$raw_a1_run_root/preflight.json" "$case_dir/summary/preflight.json"
  copy_file_if_exists "$raw_a1_run_root/case_results.json" "$case_dir/summary/case_results.json"
  copy_file_if_exists "$raw_a1_run_root/p01_arm_build_summary.json" "$case_dir/summary/p01_arm_build_summary.json"
  copy_file_if_exists "$raw_a1_run_root/p01_arm_build_review_index.csv" "$case_dir/summary/p01_arm_build_review_index.csv"
  copy_file_if_exists "$group_dir/case_input.json" "$case_dir/case_input.json"
  copy_file_if_exists "$group_dir/case_scope.json" "$case_dir/case_scope.json"
  copy_tree_contents "$group_dir/SWSD" "$case_dir/SWSD"
  copy_tree_contents "$group_dir/RCSD" "$case_dir/RCSD"
  copy_tree_contents "$group_dir/FRCSD" "$case_dir/FRCSD"
  copy_tree_contents "$group_dir/compare" "$case_dir/compare"
  publish_review_aliases

  if [[ ! "$run_a2" == "0" && ! "$run_a2" == "false" && ! "$run_a2" == "FALSE" && -d "$raw_a2_run_root" ]]; then
    copy_file_if_exists "$raw_a2_run_root/preflight.json" "$case_dir/alignment/preflight.json"
    copy_file_if_exists "$raw_a2_run_root/p01_arm_alignment_summary.json" "$case_dir/alignment/p01_arm_alignment_summary.json"
    copy_file_if_exists "$raw_a2_run_root/p01_arm_alignment_review_index.csv" "$case_dir/alignment/p01_arm_alignment_review_index.csv"
    copy_tree_contents "$raw_a2_run_root/cases/group_0001/SWSD" "$case_dir/alignment/SWSD"
    copy_tree_contents "$raw_a2_run_root/cases/group_0001/RCSD" "$case_dir/alignment/RCSD"
    copy_tree_contents "$raw_a2_run_root/cases/group_0001/compare" "$case_dir/alignment/compare"
    copy_file_if_exists "$raw_a2_run_root/cases/group_0001/alignment_summary.json" "$case_dir/alignment/alignment_summary.json"
    copy_file_if_exists "$raw_a2_run_root/cases/group_0001/logical_arm_groups.json" "$case_dir/alignment/logical_arm_groups.json"
    copy_file_if_exists "$raw_a2_run_root/cases/group_0001/arm_build_feedback.json" "$case_dir/alignment/arm_build_feedback.json"
    copy_file_if_exists "$raw_a2_run_root/cases/group_0001/source_extra_arms.json" "$case_dir/alignment/source_extra_arms.json"
    copy_file_if_exists "$raw_a2_run_root/cases/group_0001/arm_alignment_candidates.json" "$case_dir/alignment/arm_alignment_candidates.json"
    printf '%s\n' "$raw_a2_run_root" > "$case_dir/latest_raw_a2_run_root.txt"
  fi

  printf '%s\n' "$run_id" > "$case_dir/latest_run_id.txt"
  printf '%s\n' "$raw_a1_run_root" > "$case_dir/latest_raw_a1_run_root.txt"
}

feature_count() {
  local final_geojson="$1"
  "$python_bin" - "$final_geojson" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    print(len((json.load(fh).get("features") or [])))
PY
}

echo "[p01-innernet-case] case_id=$case_id" >&2
echo "[p01-innernet-case] case_dir=$case_dir_abs" >&2
echo "[p01-innernet-case] junction_group=$junction_group" >&2
echo "[p01-innernet-case] run_id=$run_id" >&2
echo "[p01-innernet-case] case_scope_bfs_depth=$case_scope_bfs_depth" >&2
echo "[p01-innernet-case] right_turn_values=${right_turn_values:-<none>}" >&2

run_a1_final
run_alignment
mirror_outputs

final_geojson="$case_dir/FRCSD/frcsd_road_next_road.geojson"
visual_1="$case_dir/review/visual_1_frcsd_arm_movement_turn_audit.png"
visual_2="$case_dir/review/visual_2_frcsd_pass_capability_audit.png"
count="missing"
if [[ -f "$final_geojson" ]]; then
  count="$(feature_count "$final_geojson")"
fi
for visual_path in "$visual_1" "$visual_2"; do
  if [[ ! -f "$visual_path" ]]; then
    echo "[p01-innernet-case][WARN] expected visual output is missing: $visual_path" >&2
  fi
done

echo "[p01-innernet-case] case_dir=$case_dir" >&2
echo "[p01-innernet-case] final_geojson=$final_geojson" >&2
echo "[p01-innernet-case] final_feature_count=$count" >&2
echo "[p01-innernet-case] final_audit=$case_dir/FRCSD/frcsd_road_next_road_audit.json" >&2
echo "[p01-innernet-case] visual_1=$visual_1" >&2
echo "[p01-innernet-case] visual_2=$visual_2" >&2
echo "[p01-innernet-case] alignment_dir=$case_dir/alignment" >&2
echo "[p01-innernet-case] raw_a1_run_root=$raw_a1_run_root" >&2
if [[ ! "$run_a2" == "0" && ! "$run_a2" == "false" && ! "$run_a2" == "FALSE" ]]; then
  echo "[p01-innernet-case] raw_a2_run_root=$raw_a2_run_root" >&2
fi
