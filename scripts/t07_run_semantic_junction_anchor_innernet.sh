#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.gpkg}"
NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DRIVEZONE_LAYER="${DRIVEZONE_LAYER:-}"
DRIVEZONE_CRS="${DRIVEZONE_CRS:-}"
INTERSECTION_PATH="${INTERSECTION_PATH:-/mnt/d/TestData/POC_Data/patch_all/RCSDIntersection.gpkg}"
INTERSECTION_LAYER="${INTERSECTION_LAYER:-}"
INTERSECTION_CRS="${INTERSECTION_CRS:-}"
RCSDNODE_PATH="${RCSDNODE_PATH:-}"
RCSDNODE_LAYER="${RCSDNODE_LAYER:-}"
RCSDNODE_CRS="${RCSDNODE_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t07_semantic_junction_anchor_innernet}"
RUN_ID="${RUN_ID:-t07_semantic_junction_anchor_innernet_$(date +%Y%m%d_%H%M%S)}"

path_compare_key() {
  local value
  value="$(realpath -sm "$1")"
  if [[ "$value" == /mnt/[A-Za-z]/* ]]; then
    printf '%s' "$value" | tr '[:upper:]' '[:lower:]'
  else
    printf '%s' "$value"
  fi
}

EXPECTED_PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [[ -n "$PYTHON_BIN" && "$PYTHON_BIN" != ".venv/bin/python" && "$(path_compare_key "$PYTHON_BIN")" != "$(path_compare_key "$EXPECTED_PYTHON_BIN")" ]]; then
  echo "[BLOCK] PYTHON_BIN must point to repo .venv/bin/python: $REPO_DIR/.venv/bin/python" >&2
  exit 2
fi
PYTHON_BIN="$EXPECTED_PYTHON_BIN"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Missing repo python: $PYTHON_BIN" >&2
  echo "[TIP] Run: make env-sync && make doctor" >&2
  exit 2
fi

for path_var in NODES_PATH DRIVEZONE_PATH INTERSECTION_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done
if [[ -n "$RCSDNODE_PATH" && ! -f "$RCSDNODE_PATH" ]]; then
  echo "[BLOCK] RCSDNODE_PATH does not exist: $RCSDNODE_PATH" >&2
  exit 2
fi

export NODES_PATH NODES_LAYER NODES_CRS
export DRIVEZONE_PATH DRIVEZONE_LAYER DRIVEZONE_CRS
export INTERSECTION_PATH INTERSECTION_LAYER INTERSECTION_CRS
export RCSDNODE_PATH RCSDNODE_LAYER RCSDNODE_CRS
export OUT_ROOT RUN_ID

mkdir -p "$OUT_ROOT"
cd "$REPO_DIR"

echo "[RUN] T07 semantic-junction Step1 + Step2"
echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] INTERSECTION_PATH=$INTERSECTION_PATH"
echo "[RUN] RCSDNODE_PATH=${RCSDNODE_PATH:-<disabled>}"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"
echo "[RUN] Segment input is intentionally unsupported."

PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from rcsd_topo_poc.modules.t07_semantic_junction_anchor import run_t07_semantic_junction_anchor


def optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


artifacts = run_t07_semantic_junction_anchor(
    nodes_path=os.environ["NODES_PATH"],
    drivezone_path=os.environ["DRIVEZONE_PATH"],
    intersection_path=os.environ["INTERSECTION_PATH"],
    out_root=os.environ["OUT_ROOT"],
    rcsdnode_path=optional_env("RCSDNODE_PATH"),
    run_id=os.environ["RUN_ID"],
    nodes_layer=optional_env("NODES_LAYER"),
    drivezone_layer=optional_env("DRIVEZONE_LAYER"),
    intersection_layer=optional_env("INTERSECTION_LAYER"),
    rcsdnode_layer=optional_env("RCSDNODE_LAYER"),
    nodes_crs=optional_env("NODES_CRS"),
    drivezone_crs=optional_env("DRIVEZONE_CRS"),
    intersection_crs=optional_env("INTERSECTION_CRS"),
    rcsdnode_crs=optional_env("RCSDNODE_CRS"),
)

step1_summary = read_json(artifacts.step1.summary_path)
step2_summary = read_json(artifacts.step2.summary_path)
print(
    json.dumps(
        {
            "run_id": os.environ["RUN_ID"],
            "run_root": str(artifacts.run_root),
            "inputs": {
                "nodes": os.environ["NODES_PATH"],
                "drivezone": os.environ["DRIVEZONE_PATH"],
                "intersection": os.environ["INTERSECTION_PATH"],
                "rcsdnode": optional_env("RCSDNODE_PATH"),
            },
            "step1": {
                "stage_root": str(artifacts.step1.stage_root),
                "nodes": str(artifacts.step1.nodes_path),
                "summary": str(artifacts.step1.summary_path),
                "processed_kind2_count": step1_summary.get("processed_kind2_count"),
                "skipped_kind2_count": step1_summary.get("skipped_kind2_count"),
                "has_evd_yes_count": step1_summary.get("has_evd_yes_count"),
                "has_evd_no_count": step1_summary.get("has_evd_no_count"),
                "has_evd_null_count": step1_summary.get("has_evd_null_count"),
            },
            "step2": {
                "stage_root": str(artifacts.step2.stage_root),
                "nodes": str(artifacts.step2.nodes_path),
                "summary": str(artifacts.step2.summary_path),
                "stage2_candidate_count": step2_summary.get("stage2_candidate_count"),
                "anchor_yes_count": step2_summary.get("anchor_yes_count"),
                "anchor_no_count": step2_summary.get("anchor_no_count"),
                "anchor_fail1_count": step2_summary.get("anchor_fail1_count"),
                "anchor_fail2_count": step2_summary.get("anchor_fail2_count"),
                "anchor_null_count": step2_summary.get("anchor_null_count"),
                "rcsdintersection_no_rcsdnode_count": step2_summary.get("rcsdintersection_no_rcsdnode_count"),
            },
        },
        ensure_ascii=False,
        indent=2,
    ),
    flush=True,
)
PY

echo "[DONE] T07 outputs: $OUT_ROOT/$RUN_ID"
