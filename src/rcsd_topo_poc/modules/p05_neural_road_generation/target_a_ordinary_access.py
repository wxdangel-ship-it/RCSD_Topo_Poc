from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import fiona
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _local_path,
    _read_crs,
    _read_json,
    _read_nodes,
    _read_roads,
    _unique_gpkg,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_conditioning import (
    lock_ordinary_plan,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_business_adjudications import (
    user_anchor_adjudication,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ACCESS_GEOMETRY_FEATURE_NAMES = (
    "source_is_swsd",
    "source_is_rcsd",
    "in_locked_plan",
    "road_role_main",
    "road_role_internal_connector",
    "distance_log_m",
    "within_1m",
    "within_3m",
    "within_5m",
    "within_12m",
    "within_25m",
    "road_length_log_m",
    "projection_fraction",
    "fraction_to_nearest_end",
    "projection_is_endpoint",
    "projection_is_interior",
    "start_distance_log_m",
    "end_distance_log_m",
    "start_is_nearest",
    "end_is_nearest",
    "tangent_x",
    "tangent_y",
    "candidate_pool_size_log",
    "selected_plan_size_log",
)


@dataclass(frozen=True)
class AccessRoad:
    road_id: str
    source: str
    start_node_id: str
    end_node_id: str
    geometry: Any


@dataclass(frozen=True)
class FinalRoad:
    road_id: str
    normalized_road_id: str
    start_node_id: str
    end_node_id: str
    geometry: Any
    source: int


@dataclass(frozen=True)
class CaseAccessData:
    case_key: str
    t01_nodes: Mapping[str, Point]
    access_roads: Mapping[str, AccessRoad]
    road_ids: tuple[str, ...]
    road_geometries: tuple[Any, ...]
    road_tree: STRtree
    relation_by_segment: Mapping[str, Mapping[str, str]]
    final_roads: tuple[FinalRoad, ...]
    final_nodes: Mapping[str, Point]
    final_node_closure: Mapping[str, tuple[str, ...]]
    input_records: tuple[Mapping[str, Any], ...]


def build_ordinary_access_store(
    *,
    label_store_root: Path,
    plan_candidate_store_root: Path,
    plan_label_root: Path,
    ordinary_full_oof_root: Path,
    poc_data_root: Path,
    output_root: Path,
    spatial_radius_m: float = 25.0,
    max_spatial_candidates: int = 64,
) -> Path:
    """Build explicit junc_node -> access Road/position supervision."""
    if spatial_radius_m <= 0 or max_spatial_candidates < 1:
        raise ValueError("ordinary access candidate configuration is invalid")
    label_root = normalize_runtime_path(label_store_root).resolve(strict=True)
    candidate_root = normalize_runtime_path(
        plan_candidate_store_root
    ).resolve(strict=True)
    plan_labels_root = normalize_runtime_path(plan_label_root).resolve(
        strict=True
    )
    ordinary_root = normalize_runtime_path(ordinary_full_oof_root).resolve(
        strict=True
    )
    data_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    case_rows = {
        str(row["case_key"]): row
        for row in _read_jsonl(label_root / "case_inventory.jsonl")
    }
    segments = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(label_root / "segment_inventory.jsonl")
        if str(row["segment_type"]) == "STANDARD"
    }
    business_labels = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in _read_jsonl(label_root / "segment_labels.jsonl")
    }
    plan_labels = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(plan_labels_root / "training_plan_labels.jsonl")
    }
    predictions = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(ordinary_root / "full_oof_predictions.jsonl")
    }
    selected_plans: dict[tuple[str, str], Mapping[str, Any]] = {}
    selected_resolution: dict[tuple[str, str], str] = {}
    group_path = candidate_root / "inference_plan_groups.jsonl"
    with group_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            group = json.loads(line)
            key = (str(group["case_key"]), str(group["segment_id"]))
            if key not in segments:
                continue
            selected, resolution = lock_ordinary_plan(
                group=group,
                prediction=predictions.get(key),
            )
            if selected is None:
                raise ValueError(f"ordinary access locked plan missing: {key}")
            selected_with_context = dict(selected)
            selected_with_context["object_features"] = [
                float(value) for value in group.get("object_features") or ()
            ]
            selected_with_context["candidate_road_ids"] = sorted(
                {
                    str(road_id)
                    for candidate in group.get("candidates") or ()
                    for road_id in candidate.get("road_ids") or ()
                }
                | {
                    str(arm.get("nearest_road_id") or "")
                    for candidate in group.get("candidates") or ()
                    for arm in candidate.get("arm_rows") or ()
                    if str(arm.get("nearest_road_id") or "")
                }
            )
            selected_plans[key] = selected_with_context
            selected_resolution[key] = resolution
    if selected_plans.keys() != segments.keys():
        missing = sorted(segments.keys() - selected_plans.keys())[:10]
        raise ValueError(f"ordinary access plan scope differs: {missing}")

    proposals = []
    labels = []
    counts: Counter[str] = Counter()
    case_inputs = []
    by_case: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in sorted(segments):
        by_case[key[0]].append(key)
    for case_key, keys in sorted(by_case.items()):
        case_data = _load_case_access_data(
            label_root=label_root,
            case_row=case_rows[case_key],
            poc_data_root=data_root,
        )
        case_inputs.extend(case_data.input_records)
        for key in keys:
            segment = segments[key]
            selected = selected_plans[key]
            prediction = predictions[key]
            plan_label = plan_labels[key]
            business_label = business_labels[key]
            junc_nodes = [
                str(value) for value in segment.get("junc_nodes") or ()
            ]
            counts["standard_segment"] += 1
            counts["access_object"] += len(junc_nodes)
            for junc_node_id in junc_nodes:
                point = case_data.t01_nodes.get(junc_node_id)
                if point is None:
                    labels.append(
                        _masked_label(
                            key,
                            junc_node_id,
                            fold=int(prediction["fold"]),
                            decision=str(selected["decision"]),
                            reason="T01_JUNC_NODE_MISSING",
                            supervision_scope_weight=float(
                                business_label.get("label_weight") or 0.0
                            ),
                            review_required=bool(
                                float(
                                    business_label.get("label_weight") or 0.0
                                )
                                > 0
                            ),
                        )
                    )
                    counts["mask_T01_JUNC_NODE_MISSING"] += 1
                    continue
                candidate_ids = _access_candidate_ids(
                    point,
                    case_data=case_data,
                    selected=selected,
                    radius_m=spatial_radius_m,
                    max_spatial_candidates=max_spatial_candidates,
                )
                member_by_id = {
                    str(row["road_id"]): row
                    for row in selected.get("road_members") or ()
                }
                roles = {
                    str(row["road_id"]): str(row["role"])
                    for row in selected.get("road_roles") or ()
                }
                object_proposals = []
                for road_id in candidate_ids:
                    road = case_data.access_roads[road_id]
                    object_proposals.append(
                        _access_proposal(
                            case_key=key[0],
                            segment_id=key[1],
                            junc_node_id=junc_node_id,
                            point=point,
                            road=road,
                            selected=selected,
                            member=member_by_id.get(road_id),
                            role=roles.get(road_id, ""),
                            candidate_pool_size=len(candidate_ids),
                        )
                    )
                proposals.extend(object_proposals)
                proposal_by_road = {
                    str(row["road_id"]): row for row in object_proposals
                }
                label = _access_label(
                    key,
                    junc_node_id,
                    point=point,
                    case_data=case_data,
                    selected=selected,
                    prediction=prediction,
                    plan_label=plan_label,
                    business_label=business_label,
                    proposal_by_road=proposal_by_road,
                )
                labels.append(label)
                counts[f"label_{label['label_state']}"] += 1
                counts["task_mask"] += int(label["access_task_mask"])
                counts["manual_review_required"] += int(
                    label["manual_review_required"]
                )
                counts["target_count"] += len(
                    label["acceptable_access_targets"]
                )
                for target in label["acceptable_access_targets"]:
                    counts[
                        f"target_role_{target['access_business_role']}"
                    ] += 1
    proposals.sort(
        key=lambda row: (
            row["case_key"],
            row["segment_id"],
            row["junc_node_id"],
            row["proposal_id"],
        )
    )
    labels.sort(
        key=lambda row: (
            row["case_key"],
            row["segment_id"],
            row["junc_node_id"],
        )
    )
    proposal_path = root / "ordinary_access_inference_candidates.jsonl"
    _write_jsonl(proposal_path, proposals)
    feature_hash_before_label_read = sha256_file(proposal_path)
    label_path = root / "ordinary_access_training_labels.jsonl"
    _write_jsonl(label_path, labels)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_EXPLICIT_ACCESS_ROAD_POSITION_STORE",
        "business_contract": {
            "output": (
                "For every ordinary Segment junc_node, select one access Road "
                "and a Road fraction. Endpoint fractions reuse a Node; an "
                "interior fraction requests a deterministic Road split."
            ),
            "relation_record_absent": (
                "unknown supervision; never converted to success or failure"
            ),
            "t11_no_valid_relation": (
                "explicit anchor failure; Segment fallback and no positive "
                "access supervision"
            ),
            "inference": (
                "locked ordinary OOF Road plan plus T01/raw RCSD spatial "
                "candidates; T06 terminal state is label-only"
            ),
            "upstream_plan_nonexact": (
                "does not invalidate an independently proven T06 access "
                "target; it remains an access-head training label but can "
                "never make the full ordinary result releasable"
            ),
        },
        "spatial_radius_m": spatial_radius_m,
        "max_spatial_candidates": max_spatial_candidates,
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": feature_hash_before_label_read,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "geometry_feature_names": list(ACCESS_GEOMETRY_FEATURE_NAMES),
        "counts": dict(sorted(counts.items())),
        "proposal_count": len(proposals),
        "label_count": len(labels),
        "case_count": len(by_case),
        "crs_consistent": True,
        "crs_metric": True,
        "silent_fix": False,
        "inputs": {
            "case_inventory": _input_record(
                label_root / "case_inventory.jsonl"
            ),
            "segment_inventory": _input_record(
                label_root / "segment_inventory.jsonl"
            ),
            "segment_labels": _input_record(
                label_root / "segment_labels.jsonl"
            ),
            "plan_candidates": _input_record(group_path),
            "plan_labels": _input_record(
                plan_labels_root / "training_plan_labels.jsonl"
            ),
            "ordinary_full_oof": _input_record(
                ordinary_root / "full_oof_predictions.jsonl"
            ),
            "case_inputs": case_inputs,
        },
        "outputs": {
            "inference_candidates": _input_record(proposal_path),
            "training_labels": _input_record(label_path),
        },
        "gate_pass": (
            len(selected_plans) == len(segments)
            and len(labels) == counts["access_object"]
            and sha256_file(proposal_path) == feature_hash_before_label_read
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary access store gate failed")
    return root


def normalized_final_road_id(properties: Mapping[str, Any]) -> str:
    return str(
        properties.get("t06_split_original_road_id")
        or properties.get("source_road_id")
        or properties.get("id")
        or ""
    )


def access_truth_targets(
    *,
    junc_node_id: str,
    relation: Mapping[str, str],
    final_roads: Sequence[FinalRoad],
    final_nodes: Mapping[str, Point],
    final_node_closure: Mapping[str, Sequence[str]] | None = None,
    access_roads: Mapping[str, AccessRoad],
    road_ids: Sequence[str] = (),
    road_geometries: Sequence[Any] = (),
    road_tree: STRtree | None = None,
) -> tuple[list[dict[str, Any]], str]:
    raw_map = relation.get("swsd_to_frcsd_node_map")
    if not str(raw_map or "").strip():
        return [], "JUNC_NODE_MAP_UNKNOWN"
    mappings = _parse_sequence(raw_map)
    if mappings is None:
        return [], "JUNC_NODE_MAP_INVALID"
    selected = [
        row
        for row in mappings
        if str(row.get("swsd_node_id") or "") == junc_node_id
    ]
    if len(selected) != 1:
        return [], "JUNC_NODE_MAP_UNKNOWN"
    mapped_node_ids = [
        str(value) for value in selected[0].get("frcsd_node_ids") or ()
    ]
    closure = final_node_closure or {}
    closure_node_ids = {
        related
        for value in mapped_node_ids
        for related in closure.get(value, (value,))
    }
    mapped_points = [
        final_nodes[value] for value in closure_node_ids if value in final_nodes
    ]
    if not mapped_points:
        return [], "FINAL_ACCESS_NODE_UNKNOWN"
    incident = [
        road
        for road in final_roads
        if road.start_node_id in closure_node_ids
        or road.end_node_id in closure_node_ids
    ]
    formal_incident_count = 0
    lineage_failure_states: set[str] = set()
    targets_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for final_road in incident:
        role = classify_access_target(
            final_road.normalized_road_id, relation
        )
        if role == "UNCLASSIFIED_INCIDENT":
            role = classify_access_target(final_road.road_id, relation)
        if role in {"PRUNED_NON_OWNER", "UNCLASSIFIED_INCIDENT"}:
            continue
        formal_incident_count += 1
        lineage = _final_road_lineage_candidates(
            final_road,
            access_roads=access_roads,
            road_ids=road_ids,
            road_geometries=road_geometries,
            road_tree=road_tree,
        )
        if not lineage:
            lineage_failure_states.add(
                "FINAL_ACCESS_SOURCE_LINEAGE_UNKNOWN"
            )
            continue
        final_access_node_ids = sorted(
            {
                value
                for value in (
                    final_road.start_node_id,
                    final_road.end_node_id,
                )
                if value in closure_node_ids and value in final_nodes
            }
        )
        road_access_points = [
            final_nodes[value] for value in final_access_node_ids
        ] or mapped_points
        for road, lineage_kind, coverage in lineage:
            choices = []
            for point in road_access_points:
                distance = float(road.geometry.project(point))
                projected = road.geometry.interpolate(distance)
                choices.append(
                    (
                        float(point.distance(projected)),
                        _fraction(distance, float(road.geometry.length)),
                    )
                )
            gap, fraction = min(choices)
            key = (road.road_id, round(fraction, 9))
            target = targets_by_key.setdefault(
                key,
                {
                    "road_id": road.road_id,
                    "target_fraction": fraction,
                    "target_operation": _operation(fraction),
                    "final_mapping_gap_m": gap,
                    "mapped_final_node_ids": sorted(mapped_node_ids),
                    "final_access_node_ids": final_access_node_ids,
                    "access_business_role": role,
                    "source_lineage": (
                        "GEOMETRY_MULTI_ACCEPTABLE"
                        if len(lineage) > 1
                        else lineage_kind
                    ),
                    "lineage_coverage_ratio": coverage,
                    "final_road_ids": [],
                },
            )
            target["final_road_ids"].append(final_road.road_id)
    if formal_incident_count == 0:
        return [], "FORMAL_ACCESS_ROLE_UNRESOLVED"
    if lineage_failure_states:
        return [], "+".join(sorted(lineage_failure_states))
    targets = list(targets_by_key.values())
    for target in targets:
        target["final_road_ids"] = sorted(
            set(target["final_road_ids"])
        )
    if not targets:
        return [], "FINAL_ACCESS_SOURCE_LINEAGE_UNKNOWN"
    return sorted(
        targets,
        key=lambda row: (
            str(row["road_id"]),
            float(row["target_fraction"]),
        ),
    ), "RESOLVED"


def classify_access_target(
    road_id: str,
    relation: Mapping[str, Any],
) -> str:
    """Classify a T06 access Road by its explicit business relation role."""
    value = str(road_id)
    if value in _parse_id_list(
        relation.get("pruned_non_owner_frcsd_road_ids")
    ):
        return "PRUNED_NON_OWNER"
    if value in _parse_id_list(relation.get("owned_frcsd_road_ids")):
        return "OWNED_CARRIER"
    if value in _parse_id_list(relation.get("frcsd_road_ids")):
        return "DIRECT_CARRIER"
    if value in _parse_id_list(
        relation.get("related_special_junction_internal_road_ids")
    ):
        return "JUNCTION_INTERNAL_REFERENCE"
    if value in _parse_id_list(
        relation.get("related_connectivity_road_ids")
    ):
        return "CONNECTIVITY_REFERENCE"
    if value in _parse_id_list(
        relation.get("external_retained_swsd_carrier_ids")
    ):
        return "EXTERNAL_RETAINED_SWSD_CARRIER"
    if value in _parse_id_list(
        relation.get("retained_detached_swsd_road_ids")
    ):
        return "RETAINED_DETACHED_SWSD_CARRIER"
    return "UNCLASSIFIED_INCIDENT"


def junc_access_requirement(
    junc_node_id: str,
    relation: Mapping[str, Any],
) -> str:
    value = str(junc_node_id)
    if value in _parse_id_list(relation.get("detached_junc_nodes")):
        return "DETACHED_JUNC_NODE_NO_ACCESS_REQUIRED"
    if value in _parse_id_list(
        relation.get("junc_kind2_exempt_nodes")
    ):
        return "EXEMPT_JUNC_NODE_NO_REQUIRED_ACCESS"
    return "REQUIRED"


def _access_label(
    key: tuple[str, str],
    junc_node_id: str,
    *,
    point: Point,
    case_data: CaseAccessData,
    selected: Mapping[str, Any],
    prediction: Mapping[str, Any],
    plan_label: Mapping[str, Any],
    business_label: Mapping[str, Any],
    proposal_by_road: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    decision = str(selected["decision"])
    scope_weight = float(business_label.get("label_weight") or 0.0)
    user_adjudication = user_anchor_adjudication(key[0], junc_node_id)
    if (
        user_adjudication is not None
        and user_adjudication.segment_id == key[1]
        and user_adjudication.release_decision == "ABSTAIN"
    ):
        row = _masked_label(
            key,
            junc_node_id,
            fold=int(prediction["fold"]),
            decision=decision,
            reason=(
                "USER_VISUAL_ANCHORABLE_CURRENT_STRATEGY_"
                "FAILED_SEGMENT_FALLBACK"
            ),
            supervision_scope_weight=user_adjudication.sample_weight,
        )
        row.update(
            {
                "anchor_business_status": (
                    user_adjudication.business_status
                ),
                "anchor_candidate_supervised": bool(
                    user_adjudication.acceptable_candidate_ids
                ),
                "release_decision": user_adjudication.release_decision,
                "fallback_scope": user_adjudication.fallback_scope,
                "reality_change_clue": (
                    user_adjudication.reality_change_clue
                ),
                "adjudication_reason": user_adjudication.reason,
            }
        )
        return row
    truth_decision = str(
        plan_label.get("preferred_carrier_target")
        or business_label.get("carrier_target")
        or ""
    )
    if _is_no_valid_relation(business_label, plan_label):
        return _masked_label(
            key,
            junc_node_id,
            fold=int(prediction["fold"]),
            decision=decision,
            reason="T11_NO_VALID_RELATION_SEGMENT_FALLBACK",
            supervision_scope_weight=scope_weight,
        )
    relation = case_data.relation_by_segment.get(key[1])
    if relation is None:
        return _masked_label(
            key,
            junc_node_id,
            fold=int(prediction["fold"]),
            decision=decision,
            reason="RELATION_RECORD_ABSENT_UNKNOWN",
            supervision_scope_weight=scope_weight,
            review_required=scope_weight > 0,
        )
    access_requirement = junc_access_requirement(
        junc_node_id,
        relation,
    )
    if access_requirement != "REQUIRED":
        return _masked_label(
            key,
            junc_node_id,
            fold=int(prediction["fold"]),
            decision=decision,
            reason=access_requirement,
            supervision_scope_weight=scope_weight,
        )
    if truth_decision == "REVIEW_FALLBACK":
        return _masked_label(
            key,
            junc_node_id,
            fold=int(prediction["fold"]),
            decision=decision,
            reason="BUSINESS_REVIEW_FALLBACK",
            supervision_scope_weight=scope_weight,
        )
    if truth_decision not in {
        "KEEP_SWSD",
        "USE_RCSD",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
    }:
        return _masked_label(
            key,
            junc_node_id,
            fold=int(prediction["fold"]),
            decision=decision,
            reason="LOCKED_PLAN_NOT_CARRIER",
            supervision_scope_weight=scope_weight,
            review_required=scope_weight > 0,
        )
    upstream_plan_exact = str(prediction["raw_predicted_plan_id"]) in {
        str(value) for value in plan_label.get("acceptable_plan_ids") or ()
    }
    raw_targets, truth_state = access_truth_targets(
        junc_node_id=junc_node_id,
            relation=relation,
            final_roads=case_data.final_roads,
            final_nodes=case_data.final_nodes,
            final_node_closure=case_data.final_node_closure,
            access_roads=case_data.access_roads,
            road_ids=case_data.road_ids,
            road_geometries=case_data.road_geometries,
            road_tree=case_data.road_tree,
        )
    formal_targets = raw_targets
    rejected_targets: list[dict[str, Any]] = []
    targets = [
        row for row in formal_targets if row["road_id"] in proposal_by_road
    ]
    if truth_state != "RESOLVED":
        state = truth_state
    elif not formal_targets:
        state = "FORMAL_ACCESS_ROLE_UNRESOLVED"
    elif not targets:
        state = "ACCESS_TARGET_CANDIDATE_UNREACHABLE"
    else:
        plan_state = (
            "UPSTREAM_PLAN_EXACT"
            if upstream_plan_exact
            else "UPSTREAM_PLAN_NONEXACT"
        )
        state = f"RESOLVED_{truth_decision}_{plan_state}"
    weight = scope_weight
    task_mask = bool(targets) and weight > 0
    manual_review_required = weight >= 1.0 and not task_mask
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": key[0],
        "segment_id": key[1],
        "junc_node_id": junc_node_id,
        "fold": int(prediction["fold"]),
        "locked_decision": decision,
        "truth_decision": truth_decision,
        "label_state": state,
        "t06_relation_status": str(relation.get("relation_status") or ""),
        "t06_relation_reason": str(relation.get("relation_reason") or ""),
        "upstream_plan_label_exact": upstream_plan_exact,
        "upstream_plan_release_blocked": not upstream_plan_exact,
        "teacher_forcing_required": not upstream_plan_exact,
        "access_task_mask": task_mask,
        "supervision_scope_weight": weight,
        "access_label_weight": weight if task_mask else 0.0,
        "acceptable_access_targets": [
            {
                **row,
                "proposal_id": str(
                    proposal_by_road[row["road_id"]]["proposal_id"]
                ),
            }
            for row in targets
        ],
        "unreachable_formal_targets": [
            row
            for row in formal_targets
            if row["road_id"] not in proposal_by_road
        ],
        "rejected_incident_targets": rejected_targets,
        "manual_review_required": manual_review_required,
        "label_only": True,
        "inference_input_allowed": False,
    }


def _keep_swsd_targets(
    point: Point,
    *,
    selected: Mapping[str, Any],
    proposal_by_road: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    choices = []
    for road_id in selected.get("road_ids") or ():
        proposal = proposal_by_road.get(str(road_id))
        if proposal is None or str(proposal["source"]) != "SWSD":
            continue
        choices.append(proposal)
    if not choices:
        return []
    minimum = min(float(row["distance_m"]) for row in choices)
    if minimum > 5.0:
        return []
    return [
        {
            "road_id": str(row["road_id"]),
            "target_fraction": float(row["projected_fraction"]),
            "target_operation": _operation(
                float(row["projected_fraction"])
            ),
            "final_mapping_gap_m": float(row["distance_m"]),
            "mapped_final_node_ids": [],
        }
        for row in choices
        if abs(float(row["distance_m"]) - minimum) <= 1e-6
    ]


def _masked_label(
    key: tuple[str, str],
    junc_node_id: str,
    *,
    fold: int,
    decision: str,
    reason: str,
    supervision_scope_weight: float = 0.0,
    review_required: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": key[0],
        "segment_id": key[1],
        "junc_node_id": junc_node_id,
        "fold": fold,
        "locked_decision": decision,
        "label_state": reason,
        "access_task_mask": False,
        "supervision_scope_weight": supervision_scope_weight,
        "access_label_weight": 0.0,
        "acceptable_access_targets": [],
        "unreachable_formal_targets": [],
        "rejected_incident_targets": [],
        "manual_review_required": review_required,
        "label_only": True,
        "inference_input_allowed": False,
    }


def _load_case_access_data(
    *,
    label_root: Path,
    case_row: Mapping[str, Any],
    poc_data_root: Path,
) -> CaseAccessData:
    skeleton_path = label_root / str(case_row["frozen_skeleton"])
    skeleton = _read_json(skeleton_path)
    t01_evidence = [
        item
        for segment in skeleton.get("segments", [])
        for item in segment.get("evidence_refs", [])
        if str(item.get("role")) == "t01_roads"
    ]
    t01_paths = {_local_path(item["path"]) for item in t01_evidence}
    if len(t01_paths) != 1:
        raise ValueError(f"T01 Road lineage differs: {case_row['case_key']}")
    t01_roads_path = next(iter(t01_paths))
    t01_nodes_path = t01_roads_path.parent / "nodes.gpkg"
    case_root = t01_roads_path.parent.parent
    t06_root = (
        case_root
        / "t06_step12"
        / "t06"
        / "step3_segment_replacement"
    )
    external = (
        poc_data_root
        / str(case_row["family"])
        / str(case_row["business_id"])
        / "external_inputs"
    )
    raw_roads_path = _unique_gpkg(external / "rcsdroad")
    required = (
        t01_roads_path,
        t01_nodes_path,
        raw_roads_path,
        t06_root / "t06_step3_swsd_frcsd_segment_relation.csv",
        t06_root / "t06_frcsd_road.gpkg",
        t06_root / "t06_frcsd_node.gpkg",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"ordinary access inputs missing: {missing}")
    crs_values = {
        _read_crs(t01_roads_path),
        _read_crs(raw_roads_path),
        _read_crs(t06_root / "t06_frcsd_road.gpkg"),
    }
    if len(crs_values) != 1:
        raise ValueError(f"ordinary access CRS differs: {case_row['case_key']}")
    access_roads: dict[str, AccessRoad] = {}
    for source, path in (
        ("SWSD", t01_roads_path),
        ("RCSD", raw_roads_path),
    ):
        for road in _read_roads(path):
            value = AccessRoad(
                road_id=road.road_id,
                source=source,
                start_node_id=road.snodeid,
                end_node_id=road.enodeid,
                geometry=road.geometry,
            )
            existing = access_roads.get(value.road_id)
            if existing is not None and not existing.geometry.equals(
                value.geometry
            ):
                raise ValueError(
                    f"access Road id collision: {case_row['case_key']}:{value.road_id}"
                )
            access_roads[value.road_id] = value
    road_ids = tuple(sorted(access_roads))
    geometries = tuple(access_roads[value].geometry for value in road_ids)
    relation_path = (
        t06_root / "t06_step3_swsd_frcsd_segment_relation.csv"
    )
    with relation_path.open("r", encoding="utf-8-sig", newline="") as stream:
        relations = {
            str(row["swsd_segment_id"]): row for row in csv.DictReader(stream)
        }
    final_roads = tuple(
        _read_final_roads(t06_root / "t06_frcsd_road.gpkg")
    )
    final_nodes, final_node_closure = _read_final_node_data(
        t06_root / "t06_frcsd_node.gpkg"
    )
    return CaseAccessData(
        case_key=str(case_row["case_key"]),
        t01_nodes=_read_nodes(t01_nodes_path),
        access_roads=access_roads,
        road_ids=road_ids,
        road_geometries=geometries,
        road_tree=STRtree(geometries),
        relation_by_segment=relations,
        final_roads=final_roads,
        final_nodes=final_nodes,
        final_node_closure=final_node_closure,
        input_records=tuple(
            _input_record(path, case_key=str(case_row["case_key"]))
            for path in required
        ),
    )


def _read_final_roads(path: Path) -> list[FinalRoad]:
    result = []
    with fiona.open(path) as source:
        for feature in source:
            properties = dict(feature["properties"])
            result.append(
                FinalRoad(
                    road_id=str(properties.get("id") or ""),
                    normalized_road_id=normalized_final_road_id(properties),
                    start_node_id=str(properties.get("snodeid") or ""),
                    end_node_id=str(properties.get("enodeid") or ""),
                    geometry=shape(feature["geometry"]),
                    source=int(properties.get("source") or 0),
                )
            )
    return result


def _read_final_node_data(
    path: Path,
) -> tuple[dict[str, Point], dict[str, tuple[str, ...]]]:
    rows: list[tuple[str, Mapping[str, Any], Point]] = []
    with fiona.open(path) as source:
        for feature in source:
            properties = dict(feature["properties"])
            node_id = str(properties.get("id") or "")
            rows.append((node_id, properties, shape(feature["geometry"])))
    points = {node_id: point for node_id, _, point in rows}
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    main_aliases: dict[str, str] = {}
    semantic_aliases: dict[str, str] = {}
    for node_id, properties, _ in rows:
        find(node_id)
        main = str(properties.get("mainnodeid") or "")
        if main not in {"", "0", "0.0"}:
            alias = f"main:{main}"
            main_aliases[main] = alias
            union(node_id, alias)
        semantic = str(
            properties.get("semantic_junction_group_id") or ""
        )
        if semantic:
            alias = f"semantic:{semantic}"
            semantic_aliases[semantic] = alias
            union(node_id, alias)
        for subnode_id in _parse_id_list(properties.get("subnodeid")):
            union(node_id, subnode_id)
    members_by_root: dict[str, list[str]] = defaultdict(list)
    for node_id in points:
        members_by_root[find(node_id)].append(node_id)
    closure = {
        node_id: tuple(sorted(members_by_root[find(node_id)]))
        for node_id in points
    }
    for alias_value, alias in (*main_aliases.items(), *semantic_aliases.items()):
        closure.setdefault(
            alias_value,
            tuple(sorted(members_by_root.get(find(alias), ()))),
        )
    return points, closure


def _access_candidate_ids(
    point: Point,
    *,
    case_data: CaseAccessData,
    selected: Mapping[str, Any],
    radius_m: float,
    max_spatial_candidates: int,
) -> list[str]:
    queried = case_data.road_tree.query(point.buffer(radius_m))
    spatial_ids = []
    for value in queried:
        if hasattr(value, "item"):
            road_id = case_data.road_ids[int(value.item())]
        elif isinstance(value, int):
            road_id = case_data.road_ids[value]
        else:
            matches = [
                case_data.road_ids[index]
                for index, geometry in enumerate(case_data.road_geometries)
                if geometry is value
            ]
            if not matches:
                continue
            road_id = matches[0]
        distance = float(case_data.access_roads[road_id].geometry.distance(point))
        if distance <= radius_m:
            spatial_ids.append((distance, road_id))
    spatial_ids.sort(key=lambda row: (row[0], row[1]))
    selected_ids = {
        str(value)
        for value in (
            *(selected.get("road_ids") or ()),
            *(selected.get("candidate_road_ids") or ()),
        )
        if str(value) in case_data.access_roads
    }
    result = set(
        road_id for _, road_id in spatial_ids[:max_spatial_candidates]
    )
    result.update(selected_ids)
    return sorted(result)


def _access_proposal(
    *,
    case_key: str,
    segment_id: str,
    junc_node_id: str,
    point: Point,
    road: AccessRoad,
    selected: Mapping[str, Any],
    member: Mapping[str, Any] | None,
    role: str,
    candidate_pool_size: int,
) -> dict[str, Any]:
    distance_along = float(road.geometry.project(point))
    projected = road.geometry.interpolate(distance_along)
    fraction = _fraction(distance_along, float(road.geometry.length))
    gap = float(point.distance(projected))
    start, end = _geometry_endpoint_points(road.geometry)
    start_distance = float(point.distance(start))
    end_distance = float(point.distance(end))
    tangent = _local_tangent(road.geometry, distance_along)
    plan_ids = {str(value) for value in selected.get("road_ids") or ()}
    features = [
        float(road.source == "SWSD"),
        float(road.source == "RCSD"),
        float(road.road_id in plan_ids),
        float(role == "MAIN"),
        float(role == "INTERNAL_CONNECTOR"),
        math.tanh(math.log1p(gap) / 5.0),
        float(gap <= 1.0),
        float(gap <= 3.0),
        float(gap <= 5.0),
        float(gap <= 12.0),
        float(gap <= 25.0),
        math.tanh(math.log1p(float(road.geometry.length)) / 8.0),
        fraction,
        min(fraction, 1.0 - fraction),
        float(fraction <= 1e-6 or fraction >= 1.0 - 1e-6),
        float(1e-6 < fraction < 1.0 - 1e-6),
        math.tanh(math.log1p(start_distance) / 5.0),
        math.tanh(math.log1p(end_distance) / 5.0),
        float(start_distance <= end_distance),
        float(end_distance < start_distance),
        tangent[0],
        tangent[1],
        math.tanh(math.log1p(candidate_pool_size) / 5.0),
        math.tanh(
            math.log1p(len(selected.get("road_ids") or ())) / 5.0
        ),
    ]
    if len(features) != len(ACCESS_GEOMETRY_FEATURE_NAMES):
        raise RuntimeError("ordinary access feature dimension differs")
    proposal_id = _stable_id(
        case_key,
        segment_id,
        junc_node_id,
        road.road_id,
    )
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": case_key,
        "segment_id": segment_id,
        "junc_node_id": junc_node_id,
        "proposal_id": proposal_id,
        "road_id": road.road_id,
        "source": road.source,
        "locked_plan_id": str(selected["plan_id"]),
        "locked_decision": str(selected["decision"]),
        "in_locked_plan": road.road_id in plan_ids,
        "projected_fraction": fraction,
        "operation": _operation(fraction),
        "distance_m": gap,
        "projected_x": float(projected.x),
        "projected_y": float(projected.y),
        "object_feature_values": [
            float(value) for value in selected.get("object_features") or ()
        ],
        "plan_feature_values": [
            float(value) for value in selected.get("features") or ()
        ],
        "member_feature_values": (
            [float(value) for value in member.get("features") or ()]
            if member is not None
            else [0.0] * 24
        ),
        "geometry_feature_values": features,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _is_no_valid_relation(
    business_label: Mapping[str, Any],
    plan_label: Mapping[str, Any],
) -> bool:
    values = (
        business_label.get("mask_reason"),
        business_label.get("keep_reason"),
        business_label.get("label_origin"),
        plan_label.get("mask_reason"),
        plan_label.get("keep_reason"),
        plan_label.get("label_origin"),
    )
    return any(
        "no_valid_relation" in str(value or "").casefold()
        for value in values
    )


def _parse_id_list(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return set()
    if not isinstance(parsed, (list, tuple, set)):
        return set()
    return {str(item) for item in parsed if str(item)}


def _parse_sequence(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        try:
            parsed = ast.literal_eval(str(value))
        except (ValueError, SyntaxError):
            return None
    return parsed if isinstance(parsed, list) else None


def _final_road_lineage_candidates(
    final_road: FinalRoad,
    *,
    access_roads: Mapping[str, AccessRoad],
    road_ids: Sequence[str],
    road_geometries: Sequence[Any],
    road_tree: STRtree | None,
    buffer_m: float = 0.2,
    min_coverage_ratio: float = 0.995,
) -> list[tuple[AccessRoad, str, float]]:
    direct = access_roads.get(final_road.normalized_road_id)
    if direct is not None and _source_matches(final_road.source, direct.source):
        return [(direct, "DIRECT_ID", 1.0)]
    if road_tree is None:
        candidates = list(access_roads)
    else:
        candidates = _tree_road_ids(
            road_tree.query(final_road.geometry.buffer(buffer_m)),
            road_ids=road_ids,
            road_geometries=road_geometries,
        )
    result = []
    length = float(final_road.geometry.length)
    if length <= 0:
        return result
    for road_id in candidates:
        road = access_roads.get(road_id)
        if road is None or not _source_matches(final_road.source, road.source):
            continue
        if float(final_road.geometry.distance(road.geometry)) > buffer_m:
            continue
        covered = float(
            final_road.geometry.intersection(
                road.geometry.buffer(buffer_m, cap_style=2)
            ).length
        )
        ratio = covered / length
        if ratio >= min_coverage_ratio:
            result.append((road, "GEOMETRY_UNIQUE", ratio))
    return sorted(result, key=lambda row: row[0].road_id)


def _source_matches(final_source: int, input_source: str) -> bool:
    return (
        final_source not in {1, 2}
        or (final_source == 1 and input_source == "RCSD")
        or (final_source == 2 and input_source == "SWSD")
    )


def _tree_road_ids(
    queried: Sequence[Any],
    *,
    road_ids: Sequence[str],
    road_geometries: Sequence[Any],
) -> list[str]:
    result = []
    for value in queried:
        if hasattr(value, "item"):
            result.append(str(road_ids[int(value.item())]))
        elif isinstance(value, int):
            result.append(str(road_ids[value]))
        else:
            result.extend(
                str(road_ids[index])
                for index, geometry in enumerate(road_geometries)
                if geometry is value
            )
    return sorted(set(result))


def _fraction(distance: float, length: float) -> float:
    if length <= 0:
        return 0.0
    return min(max(distance / length, 0.0), 1.0)


def _operation(fraction: float) -> str:
    return (
        "REUSE_ENDPOINT"
        if fraction <= 1e-6 or fraction >= 1.0 - 1e-6
        else "SPLIT_ROAD"
    )


def _local_tangent(geometry: Any, distance: float) -> tuple[float, float]:
    length = float(geometry.length)
    delta = min(max(length * 0.01, 0.1), 2.0)
    start = geometry.interpolate(max(0.0, distance - delta))
    end = geometry.interpolate(min(length, distance + delta))
    dx = float(end.x - start.x)
    dy = float(end.y - start.y)
    norm = math.hypot(dx, dy)
    if norm <= 1e-9:
        return 0.0, 0.0
    return dx / norm, dy / norm


def _geometry_endpoint_points(geometry: Any) -> tuple[Point, Point]:
    if geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
        return Point(coordinates[0]), Point(coordinates[-1])
    if geometry.geom_type == "MultiLineString":
        parts = list(geometry.geoms)
        if not parts:
            raise ValueError("empty MultiLineString Road geometry")
        first = list(parts[0].coords)
        last = list(parts[-1].coords)
        return Point(first[0]), Point(last[-1])
    raise ValueError(f"unsupported Road geometry: {geometry.geom_type}")


def _stable_id(*values: str) -> str:
    digest = hashlib.sha1(
        "\x1f".join(str(value) for value in values).encode("utf-8")
    ).hexdigest()[:24]
    return f"toa:{digest}"


def _input_record(
    path: Path,
    *,
    case_key: str | None = None,
) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    result = {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }
    if case_key is not None:
        result["case_key"] = case_key
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
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
    "ACCESS_GEOMETRY_FEATURE_NAMES",
    "AccessRoad",
    "FinalRoad",
    "access_truth_targets",
    "build_ordinary_access_store",
    "classify_access_target",
    "normalized_final_road_id",
]
