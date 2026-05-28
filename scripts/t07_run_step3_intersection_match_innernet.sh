#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t07_step3_intersection_match_innernet}"
RUN_ID="${RUN_ID:-t07_step3_intersection_match_innernet_$(date +%Y%m%d_%H%M%S)}"

T07_SOURCE_RUN_ROOT="${T07_SOURCE_RUN_ROOT:-$REPO_DIR/outputs/_work/t07_semantic_junction_anchor_innernet}"
T07_SOURCE_RUN_ID="${T07_SOURCE_RUN_ID:-}"
NODES_PATH="${NODES_PATH:-}"
NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"

T05_PHASE2_ROOT="${T05_PHASE2_ROOT:-/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet}"
INTERSECTION_MATCH_ALL_PATH="${INTERSECTION_MATCH_ALL_PATH:-$T05_PHASE2_ROOT/intersection_match_all.geojson}"
INTERSECTION_MATCH_ALL_CRS="${INTERSECTION_MATCH_ALL_CRS:-}"

RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"
RCSDNODE_LAYER="${RCSDNODE_LAYER:-}"
RCSDNODE_CRS="${RCSDNODE_CRS:-}"

export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export OUT_ROOT
export RUN_ID
export T07_SOURCE_RUN_ROOT
export T07_SOURCE_RUN_ID
export NODES_PATH
export NODES_LAYER
export NODES_CRS
export INTERSECTION_MATCH_ALL_PATH
export INTERSECTION_MATCH_ALL_CRS
export RCSDNODE_PATH
export RCSDNODE_LAYER
export RCSDNODE_CRS

echo "[RUN] T07 Step3 intersection-match backfill"
echo "[RUN] repo: $REPO_DIR"
echo "[RUN] out_root: $OUT_ROOT"
echo "[RUN] run_id: $RUN_ID"
echo "[RUN] intersection_match_all: $INTERSECTION_MATCH_ALL_PATH"
echo "[RUN] rcsdnode: $RCSDNODE_PATH"

"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from rcsd_topo_poc.modules.t07_semantic_junction_anchor import run_t07_step3_intersection_match


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def resolve_nodes_path() -> Path:
    explicit_path = empty_to_none(os.environ.get("NODES_PATH"))
    if explicit_path:
        return Path(explicit_path)

    source_root = Path(os.environ["T07_SOURCE_RUN_ROOT"])
    source_run_id = empty_to_none(os.environ.get("T07_SOURCE_RUN_ID"))
    if source_run_id:
        return source_root / source_run_id / "step2_anchor_recognition" / "nodes.gpkg"

    if not source_root.is_dir():
        raise SystemExit(
            f"NODES_PATH is empty and T07_SOURCE_RUN_ROOT does not exist: {source_root}"
        )
    candidates = [
        child / "step2_anchor_recognition" / "nodes.gpkg"
        for child in source_root.iterdir()
        if (child / "step2_anchor_recognition" / "nodes.gpkg").is_file()
    ]
    if not candidates:
        raise SystemExit(
            f"NODES_PATH is empty and no Step2 nodes.gpkg was found under {source_root}"
        )
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


nodes_path = resolve_nodes_path()
print(f"[RUN] nodes: {nodes_path}", flush=True)

artifacts = run_t07_step3_intersection_match(
    nodes_path=nodes_path,
    intersection_match_all_path=Path(os.environ["INTERSECTION_MATCH_ALL_PATH"]),
    rcsdnode_path=Path(os.environ["RCSDNODE_PATH"]),
    out_root=Path(os.environ["OUT_ROOT"]),
    run_id=os.environ["RUN_ID"],
    nodes_layer=empty_to_none(os.environ.get("NODES_LAYER")),
    rcsdnode_layer=empty_to_none(os.environ.get("RCSDNODE_LAYER")),
    nodes_crs=empty_to_none(os.environ.get("NODES_CRS")),
    intersection_match_all_crs=empty_to_none(os.environ.get("INTERSECTION_MATCH_ALL_CRS")),
    rcsdnode_crs=empty_to_none(os.environ.get("RCSDNODE_CRS")),
)

summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
print(
    json.dumps(
        {
            "run_root": str(artifacts.run_root),
            "nodes": str(artifacts.nodes_path),
            "intersection_match_tool7": str(artifacts.intersection_match_tool7_path),
            "candidate_count": summary.get("candidate_count"),
            "accepted_count": summary.get("accepted_count"),
            "relation_missing_count": summary.get("relation_missing_count"),
            "relation_failure_count": summary.get("relation_failure_count"),
            "rcsd_missing_count": summary.get("rcsd_missing_count"),
        },
        ensure_ascii=False,
        indent=2,
    ),
    flush=True,
)
PY

echo "[DONE] T07 Step3 outputs: $OUT_ROOT/$RUN_ID"
