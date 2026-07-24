from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from shapely.geometry import shape

from rcsd_topo_poc.modules.p05_neural_road_generation.pto_candidates import canonical_edit_payload
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import (
    materialize_edit_payloads,
    semantic_node_candidate_ids,
)


def _id_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _property(properties: dict[str, Any], name: str) -> Any:
    folded = name.casefold()
    for key, value in properties.items():
        if str(key).casefold() == folded:
            return value
    return None


def truth_group_id(stage: str, edit: dict[str, Any]) -> str:
    base_id = str(edit.get("base_object_id") or "")
    if base_id:
        return f"{stage}:BASE:{base_id}"
    output_ids = [str(value) for value in list(edit.get("output_object_ids") or [])]
    if not output_ids:
        raise ValueError(f"truth edit without base or outputs: {edit}")
    return f"{stage}:CREATE:{','.join(output_ids)}"


def truth_signature(stage: str, edit: dict[str, Any], *, pointer_value: str = "") -> str:
    import hashlib
    import json

    group_id = truth_group_id(stage, edit) if stage != "T05_POINTER" else f"T05_POINTER:TARGET:{edit['base_object_id']}"
    canonical = canonical_edit_payload(
        stage=stage,
        object_kind=str(edit["object_kind"]),
        group_id=group_id,
        action=str(edit["action"]),
        base_object_id=str(edit.get("base_object_id") or ""),
        output_payloads=list(edit.get("output_payloads") or []),
        pointer_value=pointer_value,
    )
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def pointer_truth_edit(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    target_id = str(row.get("target_id") or "")
    selected = str(row.get("selected_base_id") or "")
    edit = {
        "object_kind": "Pointer",
        "action": "SELECT" if selected else "NO_MATCH",
        "base_object_id": target_id,
        "output_object_ids": [],
        "output_payloads": [],
        "lineage_kind": "oracle_pointer",
        "label_only": True,
    }
    return edit, selected


def _validate_geometry(payloads: dict[str, dict[str, Any]], *, kind: str) -> list[str]:
    failures: list[str] = []
    for identifier, payload in payloads.items():
        raw = payload.get("geometry")
        if raw is None:
            failures.append(f"{kind} {identifier} has empty geometry")
            continue
        geometry = shape(raw)
        if geometry.is_empty:
            failures.append(f"{kind} {identifier} has empty geometry")
            continue
        if not all(math.isfinite(value) for value in geometry.bounds):
            failures.append(f"{kind} {identifier} has non-finite geometry")
        if kind == "Road" and geometry.length <= 0:
            failures.append(f"Road {identifier} has zero-length geometry")
    return failures


def validate_selected_graph(
    road_edits: list[dict[str, Any]],
    node_edits: list[dict[str, Any]],
    t05_node_edits: list[dict[str, Any]],
    pointer_values: list[tuple[str, str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    failures: list[str] = []
    try:
        roads, nodes = materialize_edit_payloads(road_edits, node_edits)
        _, t05_nodes = materialize_edit_payloads([], t05_node_edits)
    except ValueError as exc:
        return {}, {}, [str(exc)]
    failures.extend(_validate_geometry(roads, kind="Road"))
    failures.extend(_validate_geometry(nodes, kind="Node"))
    failures.extend(_validate_geometry(t05_nodes, kind="Node"))
    node_ids = set(nodes)
    for road_id, road in roads.items():
        properties = dict(road.get("properties") or {})
        for field in ("snodeid", "enodeid"):
            endpoint = _id_text(_property(properties, field))
            if endpoint and endpoint not in node_ids:
                failures.append(f"Road {road_id} references missing {field}={endpoint}")
    semantic_ids = semantic_node_candidate_ids(t05_nodes)
    seen_targets: set[str] = set()
    for target_id, selected in pointer_values:
        if target_id in seen_targets:
            failures.append(f"duplicate T05 pointer target: {target_id}")
        seen_targets.add(target_id)
        if selected and selected not in semantic_ids:
            failures.append(f"T05 pointer {target_id} references missing base {selected}")
    return roads, nodes, failures


def solve_oracle_case(
    candidates: list[dict[str, Any]],
    truth_by_stage: dict[str, list[dict[str, Any]]],
    pointer_truth_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    truth_records: dict[str, tuple[str, dict[str, Any], str]] = {}
    truth_action_counts: Counter[str] = Counter()
    truth_output_counts: Counter[str] = Counter()
    for stage, edits in truth_by_stage.items():
        for edit in edits:
            group_id = truth_group_id(stage, edit)
            signature = truth_signature(stage, edit)
            if group_id in truth_records:
                raise ValueError(f"duplicate oracle truth group: {group_id}")
            truth_records[group_id] = (signature, edit, "")
            truth_action_counts[f"{stage}:{edit['action']}"] += 1
            truth_output_counts[stage] += len(list(edit.get("output_payloads") or []))
    for row in pointer_truth_rows:
        edit, selected = pointer_truth_edit(row)
        group_id = f"T05_POINTER:TARGET:{edit['base_object_id']}"
        signature = truth_signature("T05_POINTER", edit, pointer_value=selected)
        if group_id in truth_records:
            raise ValueError(f"duplicate oracle pointer group: {group_id}")
        truth_records[group_id] = (signature, edit, selected)
        truth_action_counts[f"T05_POINTER:{edit['action']}"] += 1
        truth_output_counts["T05_POINTER"] += 1

    candidates_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("label_only") is not False or candidate.get("truth_derived") is not False:
            raise ValueError(f"candidate leakage flag is invalid: {candidate.get('candidate_id')}")
        candidates_by_group[str(candidate["group_id"])].append(candidate)

    missing_groups: list[str] = []
    unmatched_exact: list[str] = []
    selected: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []
    represented_actions: Counter[str] = Counter()
    represented_outputs: Counter[str] = Counter()
    for group_id, (truth_sha, truth_edit, pointer_value) in sorted(truth_records.items()):
        options = candidates_by_group.get(group_id, [])
        if not options:
            missing_groups.append(group_id)
            continue
        exact = [item for item in options if item["canonical_payload_sha256"] == truth_sha]
        for option in options:
            costs.append(
                {
                    "candidate_id": option["candidate_id"],
                    "group_id": group_id,
                    "cost": 0 if option["canonical_payload_sha256"] == truth_sha else 1,
                    "truth_equivalent": option["canonical_payload_sha256"] == truth_sha,
                    "label_only": True,
                }
            )
        if not exact:
            unmatched_exact.append(group_id)
            continue
        choice = min(exact, key=lambda item: str(item["candidate_id"]))
        selected.append(choice)
        stage = str(choice["stage"])
        represented_actions[f"{stage}:{truth_edit['action']}"] += 1
        represented_outputs[stage] += 1 if stage == "T05_POINTER" else len(list(truth_edit.get("output_payloads") or []))

    extra_exactly_one = sorted(
        group_id
        for group_id, options in candidates_by_group.items()
        if options and options[0].get("group_mode") == "EXACTLY_ONE" and group_id not in truth_records
    )
    costed_candidate_ids = {str(row["candidate_id"]) for row in costs}
    for candidate in candidates:
        if str(candidate["candidate_id"]) not in costed_candidate_ids:
            costs.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "group_id": candidate["group_id"],
                    "cost": 1,
                    "truth_equivalent": False,
                    "label_only": True,
                }
            )
    costs.sort(key=lambda item: (str(item["group_id"]), str(item["candidate_id"])))
    coverage_failures = missing_groups + unmatched_exact + extra_exactly_one
    road_edits = [item for item in selected if item["stage"] == "FINAL_ROAD"]
    node_edits = [item for item in selected if item["stage"] == "FINAL_NODE"]
    t05_node_edits = [item for item in selected if item["stage"] == "T05_NODE"]
    pointer_values = [
        (str(item["base_object_id"]), str(item.get("pointer_value") or ""))
        for item in selected
        if item["stage"] == "T05_POINTER"
    ]
    roads: dict[str, dict[str, Any]] = {}
    nodes: dict[str, dict[str, Any]] = {}
    hard_failures: list[str] = []
    if not coverage_failures:
        roads, nodes, hard_failures = validate_selected_graph(road_edits, node_edits, t05_node_edits, pointer_values)
    status = "OPTIMAL" if not coverage_failures and not hard_failures else "INFEASIBLE"
    objective = 0.0 if status == "OPTIMAL" else None
    lower_bound = 0.0 if status == "OPTIMAL" else None
    coverage_by_action = {
        action: represented_actions[action] / count if count else 1.0
        for action, count in sorted(truth_action_counts.items())
    }
    coverage_by_stage = {
        stage: represented_outputs[stage] / count if count else 1.0
        for stage, count in sorted(truth_output_counts.items())
    }
    return {
        "status": status,
        "objective": objective,
        "lower_bound": lower_bound,
        "optimality_gap": 0.0 if status == "OPTIMAL" else None,
        "selected": selected,
        "costs": costs,
        "roads": roads,
        "nodes": nodes,
        "truth_action_counts": dict(sorted(truth_action_counts.items())),
        "represented_action_counts": dict(sorted(represented_actions.items())),
        "coverage_by_action": coverage_by_action,
        "truth_output_counts": dict(sorted(truth_output_counts.items())),
        "represented_output_counts": dict(sorted(represented_outputs.items())),
        "coverage_by_stage": coverage_by_stage,
        "missing_groups": missing_groups,
        "unmatched_exact_groups": unmatched_exact,
        "extra_exactly_one_groups": extra_exactly_one,
        "hard_failures": hard_failures,
        "selected_candidate_count": len(selected),
        "candidate_count": len(candidates),
        "variable_count": len(candidates),
        "constraint_count": len(candidates_by_group) + len(roads) * 2,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }


__all__ = [
    "pointer_truth_edit",
    "solve_oracle_case",
    "truth_group_id",
    "truth_signature",
    "validate_selected_graph",
]
