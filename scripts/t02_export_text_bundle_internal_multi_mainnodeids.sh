#!/usr/bin/env bash
set -euo pipefail

cd /mnt/d/Work/RCSD_Topo_Poc

PY_BIN="${PY_BIN:-.venv/bin/python}"
_probe_python() {
  local candidate="$1"
  [[ -x "$candidate" ]] || return 1
  PYTHONPATH=src "$candidate" - <<'PY' >/dev/null 2>&1
import fiona  # noqa: F401
import shapely  # noqa: F401
import rcsd_topo_poc.cli  # noqa: F401
PY
}

if ! _probe_python "$PY_BIN"; then
  if _probe_python "python3"; then
    echo "[INFO] Fallback to python3 because '$PY_BIN' cannot import required modules." >&2
    PY_BIN="python3"
  else
    echo "[BLOCK] Neither '$PY_BIN' nor 'python3' can import required modules (fiona/shapely/rcsd_topo_poc)." >&2
    echo "[TIP] Try: PYTHONPATH=src .venv/bin/python -m rcsd_topo_poc t02-export-text-bundle --help" >&2
    echo "[TIP] Or:   PYTHONPATH=src python3 -m rcsd_topo_poc t02-export-text-bundle --help" >&2
    exit 2
  fi
fi

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"

OUT_ROOT="${OUT_ROOT:-/mnt/d/TestData/POC_Data/T02/Anchor_2}"
RUN_ID="${RUN_ID:-t02_text_bundle_$(date +%Y%m%d_%H%M%S)}"
OUT_TXT="${OUT_TXT:-$OUT_ROOT/${RUN_ID}.txt}"
DECODE_DIR="${DECODE_DIR:-$OUT_ROOT/${RUN_ID}_decoded}"
DECODE_AFTER_EXPORT="${DECODE_AFTER_EXPORT:-1}"
MAINNODEIDS_TEXT="${MAINNODEIDS_TEXT:-}"

MAINNODEIDS=()
if (( $# > 0 )); then
  MAINNODEIDS=("$@")
elif [[ -n "$MAINNODEIDS_TEXT" ]]; then
  read -r -a MAINNODEIDS <<< "$(printf '%s' "$MAINNODEIDS_TEXT" | tr ',\n\r\t' '    ')"
else
  MAINNODEIDS=("30434673" "987998" "760213")
fi

if (( ${#MAINNODEIDS[@]} == 0 )); then
  echo "[BLOCK] No mainnodeids were provided. Pass positional args or set MAINNODEIDS_TEXT." >&2
  exit 2
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH DIVSTRIPZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$OUT_ROOT"

echo "[RUN] PY_BIN=$PY_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] DIVSTRIPZONE_PATH=$DIVSTRIPZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] OUT_TXT=$OUT_TXT"
echo "[RUN] DECODE_DIR=$DECODE_DIR"
echo "[RUN] DECODE_AFTER_EXPORT=$DECODE_AFTER_EXPORT"
echo "[RUN] MAINNODEIDS=${MAINNODEIDS[*]}"

PYTHONPATH=src "$PY_BIN" -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path "$NODES_PATH" \
  --roads-path "$ROADS_PATH" \
  --drivezone-path "$DRIVEZONE_PATH" \
  --divstripzone-path "$DIVSTRIPZONE_PATH" \
  --rcsdroad-path "$RCSDROAD_PATH" \
  --rcsdnode-path "$RCSDNODE_PATH" \
  --mainnodeid "${MAINNODEIDS[@]}" \
  --out-txt "$OUT_TXT"

if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
  PYTHONPATH=src "$PY_BIN" -m rcsd_topo_poc t02-decode-text-bundle \
    --bundle-txt "$OUT_TXT" \
    --out-dir "$DECODE_DIR"
fi

echo "[DONE] bundle_txt=$OUT_TXT"
if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
  echo "[DONE] decoded_dir=$DECODE_DIR"
else
  echo "[TIP] decode_cmd=PYTHONPATH=src $PY_BIN -m rcsd_topo_poc t02-decode-text-bundle --bundle-txt $OUT_TXT --out-dir $DECODE_DIR"
fi
