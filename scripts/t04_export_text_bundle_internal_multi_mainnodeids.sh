#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$REPO_DIR"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ "$PYTHON_BIN" != "$REPO_DIR/.venv/bin/python" && "$PYTHON_BIN" != ".venv/bin/python" ]]; then
  echo "[BLOCK] PYTHON_BIN must point to repo .venv/bin/python: $REPO_DIR/.venv/bin/python" >&2
  exit 2
fi
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Missing repo python: $PYTHON_BIN" >&2
  echo "[TIP] Run: make env-sync && make doctor" >&2
  exit 2
fi

usage() {
  cat <<'EOF'
Usage:
  scripts/t04_export_text_bundle_internal_multi_mainnodeids.sh [options] <mainnodeid>...

Options:
  --nodes-path PATH             SWSD nodes.gpkg
  --roads-path PATH             SWSD roads.gpkg
  --drivezone-path PATH         DriveZone.gpkg
  --divstripzone-path PATH      DivStripZone.gpkg
  --rcsdroad-path PATH          RCSDRoad.gpkg
  --rcsdnode-path PATH          RCSDNode.gpkg
  --mainnodeid ID [ID ...]      SWSD semantic junction IDs
  --mainnodeids-text TEXT       Comma/space/newline separated IDs
  --out-root DIR                Output root
  --run-id ID                   Run ID
  --out-txt PATH                Output bundle txt path
  --decode-dir DIR              Decode output dir when enabled
  --decode-after-export 0|1     Decode immediately after export
  --max-text-size-bytes N       Split threshold, default 256000
  -h, --help                    Show this help
EOF
}

require_arg() {
  local option="$1"
  if (( $# < 2 )) || [[ "$2" == --* ]]; then
    echo "[BLOCK] $option requires a value" >&2
    exit 2
  fi
}

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t04_text_bundle_internal}"
RUN_ID="${RUN_ID:-t04_text_bundle_$(date +%Y%m%d_%H%M%S)}"
OUT_TXT="${OUT_TXT:-}"
DECODE_DIR="${DECODE_DIR:-}"
DECODE_AFTER_EXPORT="${DECODE_AFTER_EXPORT:-0}"
MAX_TEXT_SIZE_BYTES="${MAX_TEXT_SIZE_BYTES:-256000}"
MAINNODEIDS_TEXT="${MAINNODEIDS_TEXT:-}"

MAINNODEIDS=()
while (( $# > 0 )); do
  case "$1" in
    --nodes-path) require_arg "$@"; NODES_PATH="$2"; shift 2 ;;
    --roads-path) require_arg "$@"; ROADS_PATH="$2"; shift 2 ;;
    --drivezone-path) require_arg "$@"; DRIVEZONE_PATH="$2"; shift 2 ;;
    --divstripzone-path) require_arg "$@"; DIVSTRIPZONE_PATH="$2"; shift 2 ;;
    --rcsdroad-path) require_arg "$@"; RCSDROAD_PATH="$2"; shift 2 ;;
    --rcsdnode-path) require_arg "$@"; RCSDNODE_PATH="$2"; shift 2 ;;
    --mainnodeids-text) require_arg "$@"; MAINNODEIDS_TEXT="$2"; shift 2 ;;
    --out-root) require_arg "$@"; OUT_ROOT="$2"; shift 2 ;;
    --run-id) require_arg "$@"; RUN_ID="$2"; shift 2 ;;
    --out-txt) require_arg "$@"; OUT_TXT="$2"; shift 2 ;;
    --decode-dir) require_arg "$@"; DECODE_DIR="$2"; shift 2 ;;
    --decode-after-export) require_arg "$@"; DECODE_AFTER_EXPORT="$2"; shift 2 ;;
    --max-text-size-bytes) require_arg "$@"; MAX_TEXT_SIZE_BYTES="$2"; shift 2 ;;
    --mainnodeid|--mainnodeids)
      shift
      while (( $# > 0 )) && [[ "$1" != --* ]]; do
        MAINNODEIDS+=("$1")
        shift
      done
      ;;
    -h|--help) usage; exit 0 ;;
    --) shift; MAINNODEIDS+=("$@"); break ;;
    --*) echo "[BLOCK] Unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) MAINNODEIDS+=("$1"); shift ;;
  esac
done

OUT_TXT="${OUT_TXT:-$OUT_ROOT/$RUN_ID/t04_bundle.txt}"
DECODE_DIR="${DECODE_DIR:-$OUT_ROOT/$RUN_ID/decoded}"

if (( ${#MAINNODEIDS[@]} == 0 )) && [[ -n "$MAINNODEIDS_TEXT" ]]; then
  read -r -a MAINNODEIDS <<< "$(printf '%s' "$MAINNODEIDS_TEXT" | tr ',\n\r\t' '    ')"
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

mkdir -p "$(dirname "$OUT_TXT")"

echo "[RUN] module=T04"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] DIVSTRIPZONE_PATH=$DIVSTRIPZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] OUT_TXT=$OUT_TXT"
echo "[RUN] MAX_TEXT_SIZE_BYTES=$MAX_TEXT_SIZE_BYTES"
echo "[RUN] MAINNODEIDS=${MAINNODEIDS[*]}"

"$PYTHON_BIN" -m rcsd_topo_poc t04-export-text-bundle \
  --nodes-path "$NODES_PATH" \
  --roads-path "$ROADS_PATH" \
  --drivezone-path "$DRIVEZONE_PATH" \
  --divstripzone-path "$DIVSTRIPZONE_PATH" \
  --rcsdroad-path "$RCSDROAD_PATH" \
  --rcsdnode-path "$RCSDNODE_PATH" \
  --mainnodeid "${MAINNODEIDS[@]}" \
  --out-txt "$OUT_TXT" \
  --max-text-size-bytes "$MAX_TEXT_SIZE_BYTES"

if [[ "$DECODE_AFTER_EXPORT" == "1" ]]; then
  "$PYTHON_BIN" -m rcsd_topo_poc t04-decode-text-bundle \
    --bundle-txt "$OUT_TXT" \
    --out-dir "$DECODE_DIR"
  echo "[DONE] decoded_dir=$DECODE_DIR"
fi

echo "[DONE] bundle_txt=$OUT_TXT"
