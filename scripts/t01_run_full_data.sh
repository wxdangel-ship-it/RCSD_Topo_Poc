#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/t01_run_full_data.sh <roads_path> <nodes_path> [out_root]

Optional environment variables:
  PYTHON_BIN          Optional override, but only repo .venv/bin/python is accepted
  FORMWAY_MODE        strict | audit_only | off. Default: strict
  STRATEGY_CONFIG     Override strategy config path
  COMPARE_FREEZE_DIR  Optional freeze compare dir
  RUN_ID              Optional explicit run_id
  DEBUG               1 -> --debug, else --no-debug
USAGE
}

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage
  exit 2
fi

ROAD_PATH="$1"
NODE_PATH="$2"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"

if [ -z "$ROOT" ]; then
  echo "[BLOCK] Not inside a git repository."
  exit 2
fi

if [ ! -f "$ROAD_PATH" ]; then
  echo "[BLOCK] road input not found: $ROAD_PATH"
  exit 2
fi

if [ ! -f "$NODE_PATH" ]; then
  echo "[BLOCK] node input not found: $NODE_PATH"
  exit 2
fi

if [ -n "${PYTHON_BIN:-}" ] && [ "${PYTHON_BIN}" != "$ROOT/.venv/bin/python" ] && [ "${PYTHON_BIN}" != ".venv/bin/python" ]; then
  echo "[BLOCK] PYTHON_BIN must point to repo .venv/bin/python: $ROOT/.venv/bin/python"
  exit 2
fi

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[BLOCK] Missing repo python: $PY"
  echo "[TIP] Run: make env-sync && make doctor"
  exit 2
fi

validate_input_roles() {
  "$PY" - "$ROAD_PATH" "$NODE_PATH" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import fiona


def _schema(path: Path) -> tuple[str, set[str], str]:
    try:
        layers = list(fiona.listlayers(str(path)))
        if not layers:
            raise ValueError("GeoPackage has no layers.")
        layer = layers[0]
        with fiona.open(str(path), layer=layer) as source:
            schema = source.schema or {}
            fields = {str(key).lower() for key in (schema.get("properties") or {}).keys()}
            geometry = str(schema.get("geometry") or "")
        return layer, fields, geometry
    except Exception as exc:  # noqa: BLE001 - shell preflight should surface the path.
        print(f"[BLOCK] cannot inspect vector schema: {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


road_path = Path(sys.argv[1])
node_path = Path(sys.argv[2])
road_layer, road_fields, road_geometry = _schema(road_path)
node_layer, node_fields, node_geometry = _schema(node_path)
road_required = {"snodeid", "enodeid"}
errors: list[str] = []

if road_path.resolve() == node_path.resolve():
    errors.append("roads_path and nodes_path point to the same file.")
missing_road_fields = sorted(road_required - road_fields)
if missing_road_fields:
    errors.append(f"roads_path is missing required road fields: {', '.join(missing_road_fields)}.")
if "id" not in node_fields:
    errors.append("nodes_path is missing required node field 'id'.")
if road_required.issubset(node_fields):
    errors.append("nodes_path looks like a road layer because it has snodeid/enodeid.")

if errors:
    print("[BLOCK] T01 input role validation failed.", file=sys.stderr)
    print(
        f"[BLOCK] roads={road_path} layer={road_layer} geometry={road_geometry} "
        f"fields={','.join(sorted(road_fields))}",
        file=sys.stderr,
    )
    print(
        f"[BLOCK] nodes={node_path} layer={node_layer} geometry={node_geometry} "
        f"fields={','.join(sorted(node_fields))}",
        file=sys.stderr,
    )
    for error in errors:
        print(f"[BLOCK] {error}", file=sys.stderr)
    if road_required.issubset(node_fields) and not road_required.issubset(road_fields):
        print("[TIP] roads_path and nodes_path appear to be swapped.", file=sys.stderr)
    raise SystemExit(2)

print(f"[INFO] T01 input role validation passed: roads_layer={road_layer} nodes_layer={node_layer}")
PY
}

validate_input_roles

OUT_ROOT="${3:-$ROOT/outputs/_work/t01_full_data_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT_ROOT"

CMD=(
  "$PY"
  -m
  rcsd_topo_poc
  t01-run-skill-v1
  --road-path "$ROAD_PATH"
  --node-path "$NODE_PATH"
  --out-root "$OUT_ROOT"
  --formway-mode "${FORMWAY_MODE:-strict}"
)

if [ -n "${STRATEGY_CONFIG:-}" ]; then
  CMD+=(--strategy-config "$STRATEGY_CONFIG")
fi

if [ -n "${COMPARE_FREEZE_DIR:-}" ]; then
  CMD+=(--compare-freeze-dir "$COMPARE_FREEZE_DIR")
fi

if [ -n "${RUN_ID:-}" ]; then
  CMD+=(--run-id "$RUN_ID")
fi

if [ "${DEBUG:-0}" = "1" ]; then
  CMD+=(--debug)
else
  CMD+=(--no-debug)
fi

echo "[INFO] repo_root=$ROOT"
echo "[INFO] out_root=$OUT_ROOT"
echo "[INFO] python=$PY"
echo "[INFO] command=${CMD[*]}"

(
  cd "$ROOT"
  "${CMD[@]}" | tee "$OUT_ROOT/cli_stdout.json"
)

"$PY" - <<PY
from pathlib import Path
import json
out = Path(r"$OUT_ROOT")
summary_path = out / "t01_skill_v1_summary.json"
report_path = out / "freeze_compare_report.json"
if summary_path.is_file():
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print("[INFO] freeze_compare_status=", summary.get("freeze_compare_status"))
    print("[INFO] segment_path=", summary.get("segment_path"))
if report_path.is_file():
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print("[INFO] freeze_compare_report_status=", report.get("status"))
PY
