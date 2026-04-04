#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg}"
NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
ROADS_LAYER="${ROADS_LAYER:-}"
ROADS_CRS="${ROADS_CRS:-}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DRIVEZONE_LAYER="${DRIVEZONE_LAYER:-}"
DRIVEZONE_CRS="${DRIVEZONE_CRS:-}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg}"
DIVSTRIPZONE_LAYER="${DIVSTRIPZONE_LAYER:-}"
DIVSTRIPZONE_CRS="${DIVSTRIPZONE_CRS:-}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDROAD_LAYER="${RCSDROAD_LAYER:-}"
RCSDROAD_CRS="${RCSDROAD_CRS:-}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"
RCSDNODE_LAYER="${RCSDNODE_LAYER:-}"
RCSDNODE_CRS="${RCSDNODE_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_text_bundle_internal_divmerge_focus}"
RUN_ID="${RUN_ID:-t02_text_bundle_divmerge_focus_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="${RUN_ROOT:-$OUT_ROOT/$RUN_ID}"
OUT_TXT="${OUT_TXT:-$RUN_ROOT/t02_divmerge_focus_bundle.txt}"
BUNDLE_DIR="${BUNDLE_DIR:-$RUN_ROOT/bundles}"
DECODE_ROOT="${DECODE_ROOT:-$RUN_ROOT/decoded}"
SUCCESS_LIST_PATH="${SUCCESS_LIST_PATH:-$RUN_ROOT/success_mainnodeids.txt}"
FAILED_LIST_PATH="${FAILED_LIST_PATH:-$RUN_ROOT/failed_mainnodeids.txt}"
ALLOW_PARTIAL="${ALLOW_PARTIAL:-0}"
BUNDLE_MODE="${BUNDLE_MODE:-per_case}"
DECODE_AFTER_EXPORT="${DECODE_AFTER_EXPORT:-0}"
MAINNODEIDS_TEXT="${MAINNODEIDS_TEXT:-}"

# 直接改这里即可；也可用 MAINNODEID_1..MAINNODEID_4 或 MAINNODEIDS_TEXT 覆盖。
DEFAULT_MAINNODEIDS=(
  "${MAINNODEID_1:-13460276}"
  "${MAINNODEID_2:-13460274}"
  "${MAINNODEID_3:-765592}"
  "${MAINNODEID_4:-13460256}"
)
MAINNODEIDS=()
if [[ -n "$MAINNODEIDS_TEXT" ]]; then
  # 支持空格 / 逗号 / 换行混合输入。
  read -r -a MAINNODEIDS <<< "$(printf '%s' "$MAINNODEIDS_TEXT" | tr ',\n\r\t' '    ')"
else
  MAINNODEIDS=("${DEFAULT_MAINNODEIDS[@]}")
fi

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

if [[ -n "$DIVSTRIPZONE_PATH" && ! -f "$DIVSTRIPZONE_PATH" ]]; then
  echo "[BLOCK] DIVSTRIPZONE_PATH does not exist: $DIVSTRIPZONE_PATH" >&2
  exit 2
fi

if [[ "${#MAINNODEIDS[@]}" -eq 0 ]]; then
  echo "[BLOCK] No mainnodeids were provided. Set MAINNODEIDS_TEXT or MAINNODEID_1..MAINNODEID_4." >&2
  exit 2
fi

if [[ "$BUNDLE_MODE" != "per_case" && "$BUNDLE_MODE" != "multi_case" ]]; then
  echo "[BLOCK] Unsupported BUNDLE_MODE='$BUNDLE_MODE'. Expected 'per_case' or 'multi_case'." >&2
  exit 2
fi

mkdir -p "$RUN_ROOT"
cd "$REPO_DIR"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] DIVSTRIPZONE_PATH=$DIVSTRIPZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] RUN_ROOT=$RUN_ROOT"
echo "[RUN] OUT_TXT=$OUT_TXT"
echo "[RUN] ALLOW_PARTIAL=$ALLOW_PARTIAL"
echo "[RUN] BUNDLE_MODE=$BUNDLE_MODE"
echo "[RUN] DECODE_AFTER_EXPORT=$DECODE_AFTER_EXPORT"
echo "[RUN] MAINNODEIDS_REQUESTED=${MAINNODEIDS[*]}"

REQUESTED_MAINNODEIDS_TEXT="$(printf '%s\n' "${MAINNODEIDS[@]}")"
PREFLIGHT_JSON="$(
  REQUESTED_MAINNODEIDS_TEXT="$REQUESTED_MAINNODEIDS_TEXT" \
  NODES_PATH="$NODES_PATH" \
  NODES_LAYER="$NODES_LAYER" \
  "$PYTHON_BIN" - <<'PY'
import json
import os

import fiona


def normalize_id(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except Exception:
            return text
    return text


requested = []
seen = set()
for raw_line in os.environ.get("REQUESTED_MAINNODEIDS_TEXT", "").splitlines():
    normalized = normalize_id(raw_line)
    if normalized is None or normalized in seen:
        continue
    seen.add(normalized)
    requested.append(normalized)

path = os.environ["NODES_PATH"]
layer = os.environ.get("NODES_LAYER") or None

matched = set()
with fiona.open(path, layer=layer) as src:
    for feature in src:
        properties = dict(feature.get("properties") or {})
        node_id = normalize_id(properties.get("id"))
        group_id = normalize_id(properties.get("mainnodeid"))
        for mainnodeid in requested:
            if group_id == mainnodeid or (group_id is None and node_id == mainnodeid):
                matched.add(mainnodeid)

valid = [mainnodeid for mainnodeid in requested if mainnodeid in matched]
missing = [mainnodeid for mainnodeid in requested if mainnodeid not in matched]
print(json.dumps({"requested": requested, "valid": valid, "missing": missing}, ensure_ascii=False))
PY
)"

mapfile -t VALID_MAINNODEIDS < <(
  PREFLIGHT_JSON="$PREFLIGHT_JSON" "$PYTHON_BIN" - <<'PY'
import json
import os

for value in json.loads(os.environ["PREFLIGHT_JSON"]).get("valid", []):
    print(value)
PY
)
mapfile -t MISSING_MAINNODEIDS < <(
  PREFLIGHT_JSON="$PREFLIGHT_JSON" "$PYTHON_BIN" - <<'PY'
import json
import os

for value in json.loads(os.environ["PREFLIGHT_JSON"]).get("missing", []):
    print(value)
PY
)

if [[ "${#MISSING_MAINNODEIDS[@]}" -gt 0 ]]; then
  if [[ "$ALLOW_PARTIAL" == "1" ]]; then
    echo "[WARN] Skip unresolved mainnodeids: ${MISSING_MAINNODEIDS[*]}"
  else
    echo "[BLOCK] Unresolved mainnodeids in nodes: ${MISSING_MAINNODEIDS[*]}" >&2
    echo "[TIP] If you want to export only valid cases, rerun with ALLOW_PARTIAL=1." >&2
    exit 2
  fi
fi

if [[ "${#VALID_MAINNODEIDS[@]}" -eq 0 ]]; then
  echo "[BLOCK] No valid mainnodeids remain after preflight." >&2
  exit 2
fi

echo "[RUN] MAINNODEIDS_VALID=${VALID_MAINNODEIDS[*]}"

COMMON_ARGS=(
  --nodes-path "$NODES_PATH"
  --roads-path "$ROADS_PATH"
  --drivezone-path "$DRIVEZONE_PATH"
  --rcsdroad-path "$RCSDROAD_PATH"
  --rcsdnode-path "$RCSDNODE_PATH"
)

if [[ -n "$NODES_LAYER" ]]; then
  COMMON_ARGS+=(--nodes-layer "$NODES_LAYER")
fi
if [[ -n "$NODES_CRS" ]]; then
  COMMON_ARGS+=(--nodes-crs "$NODES_CRS")
fi
if [[ -n "$ROADS_LAYER" ]]; then
  COMMON_ARGS+=(--roads-layer "$ROADS_LAYER")
fi
if [[ -n "$ROADS_CRS" ]]; then
  COMMON_ARGS+=(--roads-crs "$ROADS_CRS")
fi
if [[ -n "$DRIVEZONE_LAYER" ]]; then
  COMMON_ARGS+=(--drivezone-layer "$DRIVEZONE_LAYER")
fi
if [[ -n "$DRIVEZONE_CRS" ]]; then
  COMMON_ARGS+=(--drivezone-crs "$DRIVEZONE_CRS")
fi
if [[ -n "$DIVSTRIPZONE_PATH" ]]; then
  COMMON_ARGS+=(--divstripzone-path "$DIVSTRIPZONE_PATH")
fi
if [[ -n "$DIVSTRIPZONE_LAYER" ]]; then
  COMMON_ARGS+=(--divstripzone-layer "$DIVSTRIPZONE_LAYER")
fi
if [[ -n "$DIVSTRIPZONE_CRS" ]]; then
  COMMON_ARGS+=(--divstripzone-crs "$DIVSTRIPZONE_CRS")
fi
if [[ -n "$RCSDROAD_LAYER" ]]; then
  COMMON_ARGS+=(--rcsdroad-layer "$RCSDROAD_LAYER")
fi
if [[ -n "$RCSDROAD_CRS" ]]; then
  COMMON_ARGS+=(--rcsdroad-crs "$RCSDROAD_CRS")
fi
if [[ -n "$RCSDNODE_LAYER" ]]; then
  COMMON_ARGS+=(--rcsdnode-layer "$RCSDNODE_LAYER")
fi
if [[ -n "$RCSDNODE_CRS" ]]; then
  COMMON_ARGS+=(--rcsdnode-crs "$RCSDNODE_CRS")
fi

: > "$SUCCESS_LIST_PATH"
: > "$FAILED_LIST_PATH"

run_decode() {
  local bundle_txt="$1"
  local decode_dir="$2"
  mkdir -p "$decode_dir"
  PYTHONPATH=src "$PYTHON_BIN" -m rcsd_topo_poc t02-decode-text-bundle \
    --bundle-txt "$bundle_txt" \
    --out-dir "$decode_dir"
}

if [[ "$BUNDLE_MODE" == "multi_case" ]]; then
  CMD=(
    "$PYTHON_BIN" -m rcsd_topo_poc t02-export-text-bundle
    "${COMMON_ARGS[@]}"
    --mainnodeid "${VALID_MAINNODEIDS[@]}"
    --out-txt "$OUT_TXT"
  )
  PYTHONPATH=src "${CMD[@]}"
  printf '%s\n' "${VALID_MAINNODEIDS[@]}" > "$SUCCESS_LIST_PATH"
  echo "[DONE] BUNDLE_TXT=$OUT_TXT"
  if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
    run_decode "$OUT_TXT" "$DECODE_ROOT"
    echo "[DONE] DECODE_DIR=$DECODE_ROOT"
  else
    echo "[TIP] Decode with:"
    echo "cd $(dirname "$OUT_TXT") && PYTHONPATH=$REPO_DIR/src $PYTHON_BIN -m rcsd_topo_poc t02-decode-text-bundle --bundle-txt $OUT_TXT --out-dir $DECODE_ROOT"
  fi
  exit 0
fi

mkdir -p "$BUNDLE_DIR"
success_count=0
failure_count=0
for mainnodeid in "${VALID_MAINNODEIDS[@]}"; do
  case_bundle_txt="$BUNDLE_DIR/${mainnodeid}.txt"
  echo "[CASE] Export mainnodeid=$mainnodeid -> $case_bundle_txt"
  export_cmd=(
    "$PYTHON_BIN" -m rcsd_topo_poc t02-export-text-bundle
    "${COMMON_ARGS[@]}"
    --mainnodeid "$mainnodeid"
    --out-txt "$case_bundle_txt"
  )
  set +e
  PYTHONPATH=src "${export_cmd[@]}"
  status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "$mainnodeid" >> "$FAILED_LIST_PATH"
    failure_count=$((failure_count + 1))
    if [[ "$ALLOW_PARTIAL" == "1" ]]; then
      echo "[WARN] Export failed for mainnodeid=$mainnodeid; continue because ALLOW_PARTIAL=1"
      continue
    fi
    echo "[BLOCK] Export failed for mainnodeid=$mainnodeid" >&2
    exit "$status"
  fi
  echo "$mainnodeid" >> "$SUCCESS_LIST_PATH"
  success_count=$((success_count + 1))
  echo "[DONE] BUNDLE_TXT=$case_bundle_txt"
  if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
    case_decode_dir="$DECODE_ROOT/$mainnodeid"
    run_decode "$case_bundle_txt" "$case_decode_dir"
    echo "[DONE] DECODE_DIR=$case_decode_dir"
  fi
done

if [[ "$success_count" -eq 0 ]]; then
  echo "[BLOCK] No bundle was exported successfully." >&2
  exit 2
fi

echo "[DONE] SUCCESS_COUNT=$success_count"
echo "[DONE] FAILURE_COUNT=$failure_count"
echo "[DONE] BUNDLE_DIR=$BUNDLE_DIR"
echo "[DONE] SUCCESS_LIST_PATH=$SUCCESS_LIST_PATH"
if [[ "$failure_count" -gt 0 ]]; then
  echo "[DONE] FAILED_LIST_PATH=$FAILED_LIST_PATH"
fi
if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
  echo "[DONE] DECODE_ROOT=$DECODE_ROOT"
else
  echo "[TIP] Decode a single case with:"
  echo "PYTHONPATH=$REPO_DIR/src $PYTHON_BIN -m rcsd_topo_poc t02-decode-text-bundle --bundle-txt $BUNDLE_DIR/<mainnodeid>.txt --out-dir $DECODE_ROOT/<mainnodeid>"
fi
