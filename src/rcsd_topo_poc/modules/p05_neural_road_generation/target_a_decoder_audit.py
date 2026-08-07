from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_decoder import (
    StructuredRoadGraphDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorDecision,
    AnchorStatus,
    FallbackScope,
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    ScoredPlan,
    SegmentDecision,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_DECISION = {
    "KEEP_SWSD": SegmentDecision.KEEP_SWSD,
    "USE_RCSD": SegmentDecision.USE_RCSD,
}
_SOURCE = {
    "SWSD": RoadSource.SWSD,
    "RCSD": RoadSource.RCSD,
}
_ROLE = {
    "MAIN": RoadRole.MAIN,
    "INTERNAL_CONNECTOR": RoadRole.INTERNAL_CONNECTOR,
    "ATTACHED_SWSD": RoadRole.ATTACHED_SWSD,
}


def run_target_a_structured_decoder_audit(
    *,
    ordinary_state_root: Path,
    ordinary_candidate_store_root: Path,
    ordinary_label_root: Path,
    advance_right_prediction_root: Path,
    output_root: Path,
) -> Path:
    """Run the real finite-scope decoder on currently releasable plans."""
    started = time.perf_counter()
    state_root = normalize_runtime_path(ordinary_state_root).resolve(
        strict=True
    )
    candidate_root = normalize_runtime_path(
        ordinary_candidate_store_root
    ).resolve(strict=True)
    label_root = normalize_runtime_path(ordinary_label_root).resolve(
        strict=True
    )
    ar_root = normalize_runtime_path(
        advance_right_prediction_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    states = _read_jsonl(
        state_root / "ordinary_hierarchical_states.jsonl"
    )
    state_by_key = {
        _segment_key(row): row for row in states
    }
    releasable = {
        key: row
        for key, row in state_by_key.items()
        if bool(row["hierarchical_release_ready"])
    }
    labels = {
        _segment_key(row): row
        for row in _read_jsonl(
            label_root / "training_plan_labels.jsonl"
        )
    }
    candidates, candidate_failures = _read_releasable_candidates(
        candidate_root / "inference_plan_groups.jsonl",
        releasable,
    )
    components = dependency_conflict_components(candidates)
    decoder = StructuredRoadGraphDecoder()
    decoded_by_key: dict[tuple[str, str], Any] = {}
    component_rows = []
    for component_id, keys in enumerate(components):
        case_keys = {key[0] for key in keys}
        if len(case_keys) != 1:
            raise ValueError("decoder ownership component crosses Cases")
        component_candidates = {
            segment_id: [candidates[(case_key, segment_id)]]
            for case_key, segment_id in keys
        }
        anchors = _locked_anchor_decisions(component_candidates)
        decoded = decoder.decode(
            ordinary_candidates=component_candidates,
            advance_right_candidates={},
            anchor_decisions=anchors,
        )
        case_key = next(iter(case_keys))
        component_rows.append(
            {
                "component_id": component_id,
                "case_key": case_key,
                "segment_ids": sorted(segment_id for _, segment_id in keys),
                "candidate_count": len(keys),
                "selected_count": sum(
                    decision.automatic for decision in decoded.ordinary
                ),
                "fallback_count": len(decoded.fallback_segment_ids),
                "owned_road_ids": list(decoded.used_ownership_keys),
            }
        )
        for decision in decoded.ordinary:
            decoded_by_key[(case_key, decision.segment_id)] = decision
    ordinary_ledger = []
    for key, state in sorted(state_by_key.items()):
        decision = decoded_by_key.get(key)
        if decision is None:
            reason = (
                candidate_failures.get(key)
                or (
                    "MODEL_RELEASE_NOT_READY"
                    if not state["hierarchical_release_ready"]
                    else "MODEL_COMPLETE_PLAN_NOT_IN_CANDIDATE_SET"
                )
            )
            ordinary_ledger.append(
                _fallback_ledger_row(state, reason=reason)
            )
            continue
        label = labels.get(key)
        business_exact = ordinary_business_exact(state, label)
        ordinary_ledger.append(
            {
                "case_key": key[0],
                "segment_id": key[1],
                "segment_type": "STANDARD",
                "automatic_decision": bool(decision.automatic),
                "effective_decision": decision.selected_plan.decision.value,
                "selected_plan_id": decision.selected_plan.plan_id,
                "selected_road_ids": sorted(
                    road.source_road_id
                    for road in decision.selected_plan.roads
                ),
                "fallback_scope": decision.fallback_scope.value,
                "fallback_reason": decision.reason,
                "label_evaluable": bool(
                    label and label.get("training_task_mask")
                ),
                "business_exact": business_exact,
                "unsafe_automatic": bool(
                    decision.automatic and business_exact is False
                ),
                "feature_uses_truth": False,
                "terminal_input_count": 0,
            }
        )
    ar_predictions = _read_jsonl(ar_root / "oof_predictions.jsonl")
    ar_ledger = [
        {
            "case_key": str(row["case_key"]),
            "segment_id": str(row["object_id"]),
            "segment_type": "ADVANCE_RIGHT",
            "automatic_decision": False,
            "effective_decision": "ABSTAIN",
            "selected_plan_id": "",
            "selected_road_ids": [],
            "fallback_scope": FallbackScope.SEGMENT.value,
            "fallback_reason": (
                "MODEL_RELEASE_NOT_READY"
                if not row["automatic_decision"]
                else "ORDINARY_ACCESS_OR_COMPLETE_PLAN_NOT_DECODER_READY"
            ),
            "label_evaluable": True,
            "business_exact": None,
            "unsafe_automatic": False,
            "feature_uses_truth": False,
            "terminal_input_count": 0,
        }
        for row in ar_predictions
    ]
    ownership_counts = Counter(
        (str(row["case_key"]), road_id)
        for row in ordinary_ledger
        if row["automatic_decision"]
        for road_id in row["selected_road_ids"]
    )
    duplicate_ownership = sorted(
        [
            {"case_key": case_key, "road_id": road_id}
            for (case_key, road_id), count in ownership_counts.items()
            if count > 1
        ],
        key=lambda row: (row["case_key"], row["road_id"]),
    )
    ledger = sorted(
        [*ordinary_ledger, *ar_ledger],
        key=lambda row: (
            row["case_key"],
            row["segment_type"],
            row["segment_id"],
        ),
    )
    ledger_path = root / "decision_ledger.jsonl"
    component_path = root / "decoder_components.jsonl"
    _write_jsonl(ledger_path, ledger)
    _write_jsonl(component_path, component_rows)
    automatic = [row for row in ledger if row["automatic_decision"]]
    evaluable = [row for row in automatic if row["label_evaluable"]]
    unsafe = [row for row in evaluable if row["business_exact"] is False]
    cases = defaultdict(list)
    for row in evaluable:
        cases[str(row["case_key"])].append(row)
    summary = {
        "schema_version": "p05-target-a-joint-roadgraph-v1",
        "stage": "TARGET_A_STRUCTURED_DECODER_AUDIT",
        "scope": (
            "Candidate ownership and bounded fallback audit; final geometry, "
            "Node write-out, direction inheritance and RoadGraph "
            "materialization are not executed"
        ),
        "ordinary_segment_count": len(states),
        "advance_right_segment_count": len(ar_predictions),
        "total_segment_count": len(ledger),
        "ordinary_model_release_ready_count": len(releasable),
        "ordinary_candidate_adapted_count": len(candidates),
        "ordinary_candidate_adapter_fallback_count": len(
            candidate_failures
        ),
        "decoder_component_count": len(components),
        "decoder_max_component_size": max(
            (len(component) for component in components),
            default=0,
        ),
        "automatic_count": len(automatic),
        "ordinary_automatic_count": sum(
            row["automatic_decision"] for row in ordinary_ledger
        ),
        "advance_right_automatic_count": 0,
        "fallback_count": len(ledger) - len(automatic),
        "positive_keep_swsd_count": sum(
            row["automatic_decision"]
            and row["effective_decision"] == "KEEP_SWSD"
            for row in ordinary_ledger
        ),
        "label_evaluable_automatic_count": len(evaluable),
        "label_evaluable_automatic_exact_count": sum(
            row["business_exact"] is True for row in evaluable
        ),
        "unsafe_automatic_count": len(unsafe),
        "unevaluable_automatic_count": len(automatic) - len(evaluable),
        "case_automatic_exact": {
            case_key: all(row["business_exact"] is True for row in rows)
            for case_key, rows in sorted(cases.items())
        },
        "duplicate_road_ownership_count": len(duplicate_ownership),
        "duplicate_road_ownership_ids": duplicate_ownership,
        "fallback_scope_counts": dict(
            sorted(
                Counter(
                    row["fallback_scope"]
                    for row in ledger
                    if not row["automatic_decision"]
                ).items()
            )
        ),
        "skeleton_mutation_count": 0,
        "silent_fix": False,
        "final_roadgraph_materialized": False,
        "fallback_after_final_roadgraph_exact": None,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "strong-scope unsafe automatic ordinary plans remain"
            if unsafe
            else "final RoadGraph materialization and exact validation remain pending"
        ),
        "gate_pass": not duplicate_ownership,
        "inputs": {
            "ordinary_state_summary": _input_record(
                state_root / "summary.json"
            ),
            "ordinary_candidate_manifest": _input_record(
                candidate_root / "manifest.json"
            ),
            "ordinary_label_summary": _input_record(
                label_root / "summary.json"
            ),
            "advance_right_summary": _input_record(
                ar_root / "summary.json"
            ),
        },
        "outputs": {
            "decision_ledger": _input_record(ledger_path),
            "decoder_components": _input_record(component_path),
        },
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def dependency_conflict_components(
    candidates: Mapping[tuple[str, str], ScoredPlan],
) -> list[tuple[tuple[str, str], ...]]:
    parent = {key: key for key in candidates}

    def find(key: tuple[str, str]) -> tuple[str, str]:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        parent[max(left_root, right_root)] = min(left_root, right_root)

    road_owners: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(
        list
    )
    for key, scored in candidates.items():
        for road in scored.plan.roads:
            if road.owner_segment_id:
                road_owners[(key[0], road.ownership_key)].append(key)
    for owners in road_owners.values():
        for owner in owners[1:]:
            union(owners[0], owner)
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for key in candidates:
        groups[find(key)].append(key)
    return [
        tuple(sorted(values))
        for _, values in sorted(groups.items())
    ]


def ordinary_business_exact(
    state: Mapping[str, Any],
    label: Mapping[str, Any] | None,
) -> bool | None:
    if not label or not bool(label.get("training_task_mask")):
        return None
    selected_roads = {
        str(value) for value in state["complete_road_ids"]
    }
    selected_decision = str(state["raw_carrier_decision"])
    return any(
        str(target["decision"]) == selected_decision
        and {str(value) for value in target["road_ids"]}
        == selected_roads
        for target in label["acceptable_complete_road_targets"]
    )


def _read_releasable_candidates(
    path: Path,
    states: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, str], ScoredPlan],
    dict[tuple[str, str], str],
]:
    candidates = {}
    failures = {}
    remaining = set(states)
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            group = json.loads(line)
            key = _segment_key(group)
            if key not in remaining:
                continue
            state = states[key]
            matches = [
                candidate
                for candidate in group["candidates"]
                if (
                    str(candidate["decision"])
                    == str(state["raw_carrier_decision"])
                    and {
                        str(value) for value in candidate["road_ids"]
                    }
                    == {
                        str(value)
                        for value in state["complete_road_ids"]
                    }
                )
            ]
            if not matches:
                failures[key] = "MODEL_COMPLETE_PLAN_NOT_IN_CANDIDATE_SET"
                remaining.remove(key)
                continue
            candidate = min(matches, key=lambda row: str(row["plan_id"]))
            try:
                candidates[key] = ScoredPlan(
                    _plan_from_candidate(group, candidate),
                    float(state["raw_carrier_probability"]),
                )
            except ValueError as exc:
                failures[key] = f"CANDIDATE_ADAPTER_INVALID:{exc}"
            remaining.remove(key)
    for key in remaining:
        failures[key] = "CANDIDATE_GROUP_MISSING"
    return candidates, failures


def _plan_from_candidate(
    group: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> PlanCandidate:
    decision_name = str(candidate["decision"])
    if decision_name not in _DECISION:
        raise ValueError(f"unsupported decision {decision_name}")
    source = (
        RoadSource.SWSD
        if decision_name == "KEEP_SWSD"
        else RoadSource.RCSD
    )
    role_by_road = {
        str(row["road_id"]): str(row["role"])
        for row in candidate["road_roles"]
    }
    roads = []
    for road_id in candidate["road_ids"]:
        key = str(road_id)
        role_name = role_by_road.get(key)
        if role_name not in _ROLE:
            raise ValueError(f"Road {key} lacks a formal role")
        roads.append(
            RoadUse(
                source_kind=source,
                source_road_id=key,
                role=_ROLE[role_name],
                owner_segment_id=str(group["segment_id"]),
                direction=0,
            )
        )
    pair_nodes = [str(value) for value in group["pair_node_ids"]]
    source_access = (
        _unique_incident_road(candidate["road_members"], pair_nodes[0])
        if pair_nodes
        else ""
    )
    target_access = (
        _unique_incident_road(candidate["road_members"], pair_nodes[-1])
        if pair_nodes
        else ""
    )
    return PlanCandidate(
        plan_id=str(candidate["plan_id"]),
        segment_id=str(group["segment_id"]),
        decision=_DECISION[decision_name],
        roads=tuple(roads),
        source_access_road_id=source_access,
        target_access_road_id=target_access,
        required_anchor_ids=tuple(
            str(value) for value in group["required_anchor_ids"]
        ),
        hard_valid=bool(candidate["hard_valid"]),
    )


def _unique_incident_road(
    members: Sequence[Mapping[str, Any]],
    node_id: str,
) -> str:
    roads = {
        str(member["road_id"])
        for member in members
        if node_id
        in {
            str(member["start_node_id"]),
            str(member["end_node_id"]),
        }
    }
    return next(iter(roads)) if len(roads) == 1 else ""


def _locked_anchor_decisions(
    candidates: Mapping[str, Sequence[ScoredPlan]],
) -> dict[str, AnchorDecision]:
    return {
        anchor_id: AnchorDecision(
            anchor_id=anchor_id,
            status=AnchorStatus.SUCCESS,
            selected_candidate_id=f"locked-oof:{anchor_id}",
        )
        for rows in candidates.values()
        for scored in rows
        for anchor_id in scored.plan.required_anchor_ids
    }


def _fallback_ledger_row(
    state: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "case_key": str(state["case_key"]),
        "segment_id": str(state["segment_id"]),
        "segment_type": "STANDARD",
        "automatic_decision": False,
        "effective_decision": "ABSTAIN",
        "selected_plan_id": "",
        "selected_road_ids": [],
        "fallback_scope": FallbackScope.SEGMENT.value,
        "fallback_reason": reason,
        "label_evaluable": False,
        "business_exact": None,
        "unsafe_automatic": False,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _segment_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["segment_id"])


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "dependency_conflict_components",
    "ordinary_business_exact",
    "run_target_a_structured_decoder_audit",
]
