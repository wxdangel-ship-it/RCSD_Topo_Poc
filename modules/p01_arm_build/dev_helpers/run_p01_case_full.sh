#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="${REPO_ROOT:-$(cd "$script_dir/../../.." && pwd)}"
python_bin="${PYTHON:-$repo_root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  python_bin="${PYTHON:-python}"
fi
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

bundle_txt="${BUNDLE_TXT:-}"
case_root="${CASE_ROOT:-}"

if [[ -n "$bundle_txt" ]]; then
  if [[ -z "$case_root" ]]; then
    bundle_dir="$(cd "$(dirname "$bundle_txt")" && pwd)"
    bundle_name="$(basename "$bundle_txt")"
    case_root="$bundle_dir/${CASE_ID:-${bundle_name%.*}}"
  fi
  "$python_bin" -c "import sys; from rcsd_topo_poc.modules.p01_arm_build.text_bundle import run_p01_decode_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
    --bundle-txt "$bundle_txt" \
    --out-dir "$case_root"
fi

if [[ -z "$case_root" ]]; then
  echo "CASE_ROOT or BUNDLE_TXT is required." >&2
  exit 2
fi

if [[ ! -d "$case_root" ]]; then
  echo "CASE_ROOT does not exist: $case_root" >&2
  exit 2
fi

manifest_path="$case_root/manifest.json"
junction_groups_raw="${JUNCTION_GROUPS:-${JUNCTION_GROUP:-}}"
if [[ -z "$junction_groups_raw" && -f "$manifest_path" ]]; then
  junction_groups_raw="$("$python_bin" - "$manifest_path" <<'PY'
import json
import sys
manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
group = manifest.get("junction_group") or {}
if all(group.get(key) for key in ("SWSD", "RCSD", "FRCSD")):
    print(",".join(str(group[key]) for key in ("SWSD", "RCSD", "FRCSD")))
PY
)"
fi

if [[ -z "$junction_groups_raw" ]]; then
  echo "JUNCTION_GROUP or JUNCTION_GROUPS is required when manifest.json has no junction_group." >&2
  exit 2
fi

out_root="${OUT_ROOT:-$repo_root/outputs/_work/p01_case_full}"
run_id="${RUN_ID:-p01_case_full_$(date +%Y%m%d_%H%M%S)}"

swsd_nodes="${SWSD_NODES:-$case_root/SWSD/nodes.gpkg}"
swsd_roads="${SWSD_ROADS:-$case_root/SWSD/roads.gpkg}"
rcsd_nodes="${RCSD_NODES:-$case_root/RCSD/nodes.gpkg}"
rcsd_roads="${RCSD_ROADS:-$case_root/RCSD/roads.gpkg}"
frcsd_nodes="${FRCSD_NODES:-$case_root/FRCSD/nodes.gpkg}"
frcsd_roads="${FRCSD_ROADS:-$case_root/FRCSD/roads.gpkg}"

for required_path in "$swsd_nodes" "$swsd_roads" "$rcsd_nodes" "$rcsd_roads" "$frcsd_nodes" "$frcsd_roads"; do
  if [[ ! -f "$required_path" ]]; then
    echo "Required case file is missing: $required_path" >&2
    exit 2
  fi
done

pick_existing() {
  local path
  for path in "$@"; do
    if [[ -n "$path" && -f "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

swsd_rnr="${SWSD_ROAD_NEXT_ROAD:-${SWSD_ROAD_NODE_ROAD:-}}"
if [[ -z "$swsd_rnr" ]]; then
  swsd_rnr="$(pick_existing \
    "$case_root/SWSD/RoadNextRoad.json" \
    "$case_root/SWSD/RoadNextRoad.geojson" \
    "$case_root/SWSD/RoadNodeRoad.json" \
    "$case_root/SWSD/RoadNodeRoad.geojson" || true)"
fi

rcsd_rnr="${RCSD_ROAD_NEXT_ROAD:-}"
if [[ -z "$rcsd_rnr" ]]; then
  rcsd_rnr="$(pick_existing \
    "$case_root/RCSD/RoadNextRoad.geojson" \
    "$case_root/RCSD/RoadNextRoad.json" || true)"
fi

frcsd_rnr="${FRCSD_ROAD_NEXT_ROAD:-}"
if [[ -z "$frcsd_rnr" ]]; then
  frcsd_rnr="$(pick_existing \
    "$case_root/FRCSD/RoadNextRoad.geojson" \
    "$case_root/FRCSD/RoadNextRoad.json" || true)"
fi

args=(
  --swsd-nodes "$swsd_nodes"
  --swsd-roads "$swsd_roads"
  --rcsd-nodes "$rcsd_nodes"
  --rcsd-roads "$rcsd_roads"
  --frcsd-nodes "$frcsd_nodes"
  --frcsd-roads "$frcsd_roads"
  --out-root "$out_root"
  --run-id "$run_id"
)

while IFS= read -r group; do
  [[ -z "$group" ]] && continue
  args+=(--junction-group "$group")
done < <(printf '%s\n' "$junction_groups_raw" | tr ';' '\n')

if [[ -n "$swsd_rnr" ]]; then
  args+=(--swsd-road-next-road "$swsd_rnr")
fi
if [[ -n "$rcsd_rnr" ]]; then
  args+=(--rcsd-road-next-road "$rcsd_rnr")
fi
if [[ -n "$frcsd_rnr" ]]; then
  args+=(--frcsd-road-next-road "$frcsd_rnr")
fi

if [[ -n "${RIGHT_TURN_FORMWAY_VALUE:-}" ]]; then
  IFS=',' read -r -a right_turn_values <<< "$RIGHT_TURN_FORMWAY_VALUE"
  for value in "${right_turn_values[@]}"; do
    [[ -z "$value" ]] && continue
    args+=(--right-turn-formway-value "$value")
  done
fi

echo "[p01-case-full] case_root=$case_root" >&2
echo "[p01-case-full] run_root=$out_root/$run_id" >&2
"$python_bin" - "${args[@]}" <<'PY'
import sys
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args

raise SystemExit(run_p01_arm_build_from_args(sys.argv[1:]))
PY
