#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/t04_fallback_postprocess_existing.sh <T04_RUN_ROOT>

Examples:
  scripts/t04_fallback_postprocess_existing.sh \
    /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t04_internal_full_input/t04_internal_full_release_20260520_111042

  scripts/t04_fallback_postprocess_existing.sh \
    'D:\Work\RCSD_Topo_Poc\outputs\_work\t04_internal_full_input\t04_internal_full_release_20260520_111042'

Environment overrides:
  PY             Python interpreter. Defaults to <repo>/.venv/bin/python.
  NODES_LAYER    Optional GeoPackage layer for existing T04 nodes.gpkg.
  RCSDNODE_LAYER Optional GeoPackage layer for RCSDNode from preflight.json.
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

normalize_path() {
  local input_path="$1"
  if [[ "$input_path" =~ ^([A-Za-z]):[\\\/](.*)$ ]]; then
    local drive="${BASH_REMATCH[1],,}"
    local rest="${BASH_REMATCH[2]//\\//}"
    printf '/mnt/%s/%s\n' "$drive" "$rest"
  else
    printf '%s\n' "$input_path"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_ROOT="$(normalize_path "$1")"
PY="${PY:-$REPO_ROOT/.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "[T04-FALLBACK] Python interpreter is not executable: $PY" >&2
  exit 2
fi

export RUN_ROOT
export NODES_LAYER="${NODES_LAYER:-}"
export RCSDNODE_LAYER="${RCSDNODE_LAYER:-}"

cd "$REPO_ROOT"

"$PY" - <<'PY'
import csv
import json
import os
import shutil
from pathlib import Path

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import (
    enrich_t04_relation_evidence_with_fallback,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.nodes_publish import (
    write_t04_nodes_outputs,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _add_case(
    *,
    selected_by_case: dict[str, dict],
    failure_status_by_case: dict[str, dict],
    case_id,
    mainnodeid=None,
    kind_2=None,
    reason=None,
    state=None,
) -> None:
    if case_id in (None, ""):
        return
    normalized_case_id = str(case_id).strip()
    if not normalized_case_id:
        return
    normalized_mainnodeid = str(mainnodeid if mainnodeid not in (None, "") else normalized_case_id)
    selected_by_case[normalized_case_id] = {
        "case_id": normalized_case_id,
        "mainnodeid": normalized_mainnodeid,
        "kind_2": kind_2,
    }
    failure_status_by_case[normalized_case_id] = {
        "step7_state": str(state or "rejected"),
        "reason": str(reason or "fallback_postprocess"),
    }


run_root = Path(os.environ["RUN_ROOT"])
preflight_path = run_root / "preflight.json"
summary_path = run_root / "summary.json"
surface_summary_csv = run_root / "divmerge_virtual_anchor_surface_summary.csv"
nodes_path = run_root / "nodes.gpkg"

if not run_root.exists():
    raise SystemExit(f"RUN_ROOT not found: {run_root}")
if not preflight_path.exists():
    raise SystemExit(f"preflight.json not found: {preflight_path}")
if not summary_path.exists():
    raise SystemExit(f"summary.json not found: {summary_path}")
if not nodes_path.exists():
    raise SystemExit(f"existing T04 nodes.gpkg not found: {nodes_path}")

preflight = _load_json(preflight_path)
summary = _load_json(summary_path)

input_paths = preflight.get("input_paths") or {}
rcsdnode_path = Path(input_paths.get("rcsdnode_path") or "")
if not rcsdnode_path.exists():
    raise SystemExit(f"RCSDNode path not found from preflight.json: {rcsdnode_path}")

nodes_source_path = run_root / "_fallback_existing_nodes_source.gpkg"
shutil.copy2(nodes_path, nodes_source_path)

selected_by_case: dict[str, dict] = {}
failure_status_by_case: dict[str, dict] = {}

if surface_summary_csv.exists():
    with surface_summary_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            final_state = str(row.get("final_state") or row.get("step7_state") or "").strip()
            if final_state == "accepted":
                continue
            _add_case(
                selected_by_case=selected_by_case,
                failure_status_by_case=failure_status_by_case,
                case_id=row.get("case_id") or row.get("mainnodeid"),
                mainnodeid=row.get("mainnodeid"),
                kind_2=row.get("kind_2"),
                reason=(
                    row.get("reject_reason_detail")
                    or row.get("reject_reason")
                    or row.get("reason")
                    or "rejected"
                ),
                state=final_state or "rejected",
            )

for case_id in summary.get("runtime_failed_case_ids") or []:
    _add_case(
        selected_by_case=selected_by_case,
        failure_status_by_case=failure_status_by_case,
        case_id=case_id,
        reason="runtime_failed",
        state="runtime_failed",
    )

for case_id in summary.get("missing_status_case_ids") or []:
    _add_case(
        selected_by_case=selected_by_case,
        failure_status_by_case=failure_status_by_case,
        case_id=case_id,
        reason="missing_status",
        state="formal_result_missing",
    )

for record in summary.get("guard_failure_records") or []:
    _add_case(
        selected_by_case=selected_by_case,
        failure_status_by_case=failure_status_by_case,
        case_id=record.get("case_id") or record.get("mainnodeid"),
        mainnodeid=record.get("mainnodeid"),
        kind_2=record.get("kind_2"),
        reason=record.get("reason") or record.get("guard_type") or "formal_result_missing",
        state="formal_result_missing",
    )

selected_cases = list(selected_by_case.values())
print(f"[T04-FALLBACK] selected_failed_cases={len(selected_cases)}")

source_nodes = read_vector_layer(
    nodes_source_path,
    layer_name=os.environ.get("NODES_LAYER") or None,
).features
rcsdnodes = read_vector_layer(
    rcsdnode_path,
    layer_name=os.environ.get("RCSDNODE_LAYER") or None,
).features

fallback = enrich_t04_relation_evidence_with_fallback(
    run_root=run_root,
    selected_cases=selected_cases,
    source_node_features=source_nodes,
    rcsdnode_features=rcsdnodes,
    failure_status_by_case=failure_status_by_case,
    input_dataset_id=str(preflight.get("input_dataset_id") or ""),
)

write_t04_nodes_outputs(
    run_root=run_root,
    source_node_features=source_nodes,
    selected_cases=selected_cases,
    artifacts=[],
    failure_status_by_case=failure_status_by_case,
    input_dataset_id=str(preflight.get("input_dataset_id") or ""),
    input_nodes_path=nodes_source_path,
    fallback_success_case_ids=fallback.get("fallback_success_case_ids") or [],
    fallback_reason_by_case=fallback.get("fallback_reason_by_case") or {},
    fallback_base_id_by_case=fallback.get("fallback_base_id_by_case") or {},
)

print("[T04-FALLBACK] fallback_success_count=", fallback.get("fallback_success_count"))
print("[T04-FALLBACK] evidence_csv=", run_root / "t04_swsd_rcsd_relation_evidence.csv")
print("[T04-FALLBACK] evidence_json=", run_root / "t04_swsd_rcsd_relation_evidence.json")
print("[T04-FALLBACK] nodes_gpkg=", run_root / "nodes.gpkg")
print("[T04-FALLBACK] audit_csv=", run_root / "t04_relation_fallback_audit.csv")
print("[T04-FALLBACK] summary_json=", run_root / "t04_relation_fallback_summary.json")
PY
