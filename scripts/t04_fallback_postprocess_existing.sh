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
  RCSDNODE_LAYER Optional GeoPackage layer for RCSDNode from preflight.json or case-package dirs.
  RCSD_INTERSECTION_PATH  Optional RCSDIntersection GeoPackage/GeoJSON/Shapefile.
  RCSD_INTERSECTION_LAYER Optional RCSDIntersection layer name.
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
export RCSD_INTERSECTION_PATH="${RCSD_INTERSECTION_PATH:-}"
export RCSD_INTERSECTION_LAYER="${RCSD_INTERSECTION_LAYER:-}"

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


def _read_case_package_rcsdnodes(case_root: Path, selected_cases: list[dict]) -> list:
    features = []
    for case_doc in selected_cases:
        case_id = str(case_doc.get("case_id") or "").strip()
        if not case_id:
            continue
        rcsdnode_path = case_root / case_id / "rcsdnode.gpkg"
        if not rcsdnode_path.exists():
            continue
        features.extend(
            read_vector_layer(
                rcsdnode_path,
                layer_name=os.environ.get("RCSDNODE_LAYER") or None,
            ).features
        )
    return features


def _read_case_package_rcsdintersections(case_root: Path, selected_cases: list[dict]) -> list:
    features = []
    for case_doc in selected_cases:
        case_id = str(case_doc.get("case_id") or "").strip()
        if not case_id:
            continue
        intersection_path = case_root / case_id / "external_inputs" / "rcsd_intersection" / "rcsd_intersection_slice.gpkg"
        if not intersection_path.exists():
            intersection_path = case_root / case_id / "rcsd_intersection.gpkg"
        if not intersection_path.exists():
            continue
        features.extend(
            read_vector_layer(
                intersection_path,
                layer_name=os.environ.get("RCSD_INTERSECTION_LAYER") or None,
            ).features
        )
    return features


def _infer_rcsdintersection_path(rcsdnode_path: Path) -> Path:
    if not rcsdnode_path:
        return Path("")
    candidate = rcsdnode_path.parent.parent / "rcsd_intersection" / "rcsd_intersection_slice.gpkg"
    return candidate if candidate.is_file() else Path("")


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _postprocess_audit_patch(
    *,
    document: dict,
    batch_summary: dict,
    nodes_outputs: dict,
    fallback: dict,
) -> dict:
    batch_yes = _int_or_zero(batch_summary.get("step7_accepted_count"))
    batch_selected = _int_or_zero(batch_summary.get("selected_case_count"))
    if batch_selected <= 0:
        batch_selected = batch_yes + _int_or_zero(batch_summary.get("step7_rejected_count"))
        batch_selected += len(batch_summary.get("failed_case_ids") or [])
        batch_selected += len(batch_summary.get("runtime_failed_case_ids") or [])
    batch_fail4 = max(batch_selected - batch_yes, 0)
    post_fail4 = _int_or_zero(nodes_outputs.get("nodes_updated_to_fail4_count"))
    post_fallback = _int_or_zero(nodes_outputs.get("nodes_updated_to_fail4_fallback_count"))
    post_no = _int_or_zero(nodes_outputs.get("nodes_updated_to_no_count"))
    post_total = _int_or_zero(nodes_outputs.get("nodes_total_update_count"))
    final_total = batch_yes + post_fail4 + post_fallback + post_no
    postprocess_passed = bool(nodes_outputs.get("nodes_consistency_passed"))
    final_passed = postprocess_passed and (batch_selected <= 0 or final_total == batch_selected)

    patched = dict(document)
    patched.update(
        {
            "nodes_gpkg": nodes_outputs.get("nodes_path"),
            "nodes_anchor_update_audit_csv": nodes_outputs.get("nodes_anchor_update_audit_csv_path"),
            "nodes_anchor_update_audit_json": nodes_outputs.get("nodes_anchor_update_audit_json_path"),
            "nodes_total_update_count": final_total,
            "nodes_updated_to_yes_count": batch_yes,
            "nodes_updated_to_fail4_count": post_fail4,
            "nodes_updated_to_fail4_fallback_count": post_fallback,
            "nodes_updated_to_no_count": post_no,
            "nodes_consistency_passed": final_passed,
            "relation_fallback": fallback,
            "relation_fallback_success_count": fallback.get("fallback_success_count"),
            "relation_fallback_failed_count": fallback.get("fallback_failed_count"),
            "relation_fallback_audit_csv": str(run_root / "t04_relation_fallback_audit.csv"),
            "relation_fallback_summary_json": str(run_root / "t04_relation_fallback_summary.json"),
            "batch_nodes_total_update_count": batch_selected,
            "batch_nodes_updated_to_yes_count": batch_yes,
            "batch_nodes_updated_to_fail4_count": batch_fail4,
            "batch_nodes_updated_to_fail4_fallback_count": 0,
            "batch_nodes_updated_to_no_count": 0,
            "postprocess_nodes_path": nodes_outputs.get("nodes_path"),
            "postprocess_nodes_anchor_update_audit_csv": nodes_outputs.get("nodes_anchor_update_audit_csv_path"),
            "postprocess_nodes_anchor_update_audit_json": nodes_outputs.get("nodes_anchor_update_audit_json_path"),
            "postprocess_nodes_total_update_count": post_total,
            "postprocess_nodes_updated_to_fail4_count": post_fail4,
            "postprocess_nodes_updated_to_fail4_fallback_count": post_fallback,
            "postprocess_nodes_updated_to_no_count": post_no,
            "postprocess_nodes_consistency_passed": postprocess_passed,
            "final_nodes_updated_to_yes_count": batch_yes,
            "final_nodes_updated_to_fail4_count": post_fail4,
            "final_nodes_updated_to_fail4_fallback_count": post_fallback,
            "final_nodes_updated_to_no_count": post_no,
            "final_nodes_total_update_count": final_total,
            "final_nodes_consistency_passed": final_passed,
        }
    )
    if "passed" in patched:
        patched["passed"] = bool(patched.get("passed")) and final_passed
    return patched


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
rcsdintersection_path = Path(
    os.environ.get("RCSD_INTERSECTION_PATH")
    or input_paths.get("rcsdintersection_path")
    or ""
)
if not rcsdintersection_path.is_file():
    rcsdintersection_path = _infer_rcsdintersection_path(rcsdnode_path)
case_package_root = Path(preflight.get("case_root") or "")
if not rcsdnode_path.is_file() and not case_package_root.is_dir():
    raise SystemExit(
        "RCSDNode source not found: preflight.input_paths.rcsdnode_path is missing "
        f"and case_root is not a directory: {case_package_root}"
    )

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

failed_case_reason_by_id = {
    str(item.get("case_id")): str(item.get("message") or item.get("exception_type") or "runtime_failed")
    for item in summary.get("failed_cases") or []
    if str(item.get("case_id") or "").strip()
}
for case_id in summary.get("failed_case_ids") or []:
    if str(case_id) in selected_by_case:
        continue
    _add_case(
        selected_by_case=selected_by_case,
        failure_status_by_case=failure_status_by_case,
        case_id=case_id,
        reason=failed_case_reason_by_id.get(str(case_id), "runtime_failed"),
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
if rcsdnode_path.is_file():
    rcsdnodes = read_vector_layer(
        rcsdnode_path,
        layer_name=os.environ.get("RCSDNODE_LAYER") or None,
    ).features
else:
    rcsdnodes = _read_case_package_rcsdnodes(case_package_root, selected_cases)
    if not rcsdnodes:
        raise SystemExit(f"No RCSDNode features found under case-package root: {case_package_root}")
if rcsdintersection_path.is_file():
    rcsdintersections = read_vector_layer(
        rcsdintersection_path,
        layer_name=os.environ.get("RCSD_INTERSECTION_LAYER") or None,
    ).features
else:
    rcsdintersections = _read_case_package_rcsdintersections(case_package_root, selected_cases)

fallback = enrich_t04_relation_evidence_with_fallback(
    run_root=run_root,
    selected_cases=selected_cases,
    source_node_features=source_nodes,
    rcsdnode_features=rcsdnodes,
    rcsdintersection_features=rcsdintersections,
    failure_status_by_case=failure_status_by_case,
    input_dataset_id=str(preflight.get("input_dataset_id") or ""),
)

nodes_outputs = write_t04_nodes_outputs(
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

consistency_report_path = run_root / "step7_consistency_report.json"
if consistency_report_path.exists():
    consistency_report = _load_json(consistency_report_path)
    consistency_report = _postprocess_audit_patch(
        document=consistency_report,
        batch_summary=summary,
        nodes_outputs=nodes_outputs,
        fallback=fallback,
    )
    with consistency_report_path.open("w", encoding="utf-8") as handle:
        json.dump(consistency_report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

if summary_path.exists():
    refreshed_summary = _load_json(summary_path)
    refreshed_summary = _postprocess_audit_patch(
        document=refreshed_summary,
        batch_summary=summary,
        nodes_outputs=nodes_outputs,
        fallback=fallback,
    )
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(refreshed_summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

print("[T04-FALLBACK] fallback_success_count=", fallback.get("fallback_success_count"))
print("[T04-FALLBACK] evidence_csv=", run_root / "t04_swsd_rcsd_relation_evidence.csv")
print("[T04-FALLBACK] evidence_json=", run_root / "t04_swsd_rcsd_relation_evidence.json")
print("[T04-FALLBACK] nodes_gpkg=", run_root / "nodes.gpkg")
print("[T04-FALLBACK] audit_csv=", run_root / "t04_relation_fallback_audit.csv")
print("[T04-FALLBACK] summary_json=", run_root / "t04_relation_fallback_summary.json")
PY
