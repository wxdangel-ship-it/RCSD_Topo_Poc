#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
NODE_PATH="${NODE_PATH:-}"
ROAD_PATH="${ROAD_PATH:-}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t01_full_data_skill_v1_$(date +%Y%m%d_%H%M%S)}"
STRATEGY_CONFIG="${STRATEGY_CONFIG:-$REPO_DIR/configs/t01_data_preprocess/step1_pair_s2.json}"
FORMWAY_MODE="${FORMWAY_MODE:-strict}"
LEFT_TURN_FORMWAY_BIT="${LEFT_TURN_FORMWAY_BIT:-8}"
COMPARE_FREEZE_DIR="${COMPARE_FREEZE_DIR:-}"
DEBUG_FLAG="${DEBUG_FLAG:---no-debug}"

if [[ -n "${PYTHON_BIN:-}" && "$PYTHON_BIN" != "$REPO_DIR/.venv/bin/python" && "$PYTHON_BIN" != ".venv/bin/python" ]]; then
  echo "[BLOCK] PYTHON_BIN must point to repo .venv/bin/python: $REPO_DIR/.venv/bin/python" >&2
  exit 2
fi
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Missing repo python: $PYTHON_BIN" >&2
  echo "[TIP] Run: make env-sync && make doctor" >&2
  exit 2
fi

if [[ -z "$NODE_PATH" || -z "$ROAD_PATH" ]]; then
  echo "[BLOCK] NODE_PATH and ROAD_PATH are required." >&2
  echo "Example:" >&2
  echo "  NODE_PATH=/path/to/nodes.gpkg ROAD_PATH=/path/to/roads.gpkg $0" >&2
  exit 2
fi

mkdir -p "$OUT_ROOT"
cd "$REPO_DIR"

cmd=(
  "$PYTHON_BIN" -m rcsd_topo_poc t01-run-skill-v1
  --road-path "$ROAD_PATH"
  --node-path "$NODE_PATH"
  --strategy-config "$STRATEGY_CONFIG"
  --formway-mode "$FORMWAY_MODE"
  --left-turn-formway-bit "$LEFT_TURN_FORMWAY_BIT"
  --out-root "$OUT_ROOT"
)

if [[ -n "$COMPARE_FREEZE_DIR" ]]; then
  cmd+=(--compare-freeze-dir "$COMPARE_FREEZE_DIR")
fi

cmd+=("$DEBUG_FLAG")

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] NODE_PATH=$NODE_PATH"
echo "[RUN] ROAD_PATH=$ROAD_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
"${cmd[@]}"
