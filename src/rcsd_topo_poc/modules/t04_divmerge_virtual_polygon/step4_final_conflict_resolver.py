from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from typing import Any, Iterable

from ._rcsd_selection_support import _trace_path_to_node
from .case_models import T04CaseResult, T04EventUnitResult
from .event_interpretation_selection import (
    EVENT_REFERENCE_CONFLICT_TOL_M,
    SHARED_EVIDENCE_OVERLAP_AREA_M2,
    SHARED_EVIDENCE_OVERLAP_RATIO,
    _candidate_axis_position,
    _event_axis_signature,
)
from .event_interpretation_shared import _geometry_present, _safe_normalize_geometry


@dataclass(frozen=True)
class _ClaimOption:
    node_id: str | None
    node_source: str | None
    clear_claim: bool
    traced_first_hit_count: int
    incident_road_count: int
    direct_first_hit_count: int
    primary_match: int
    current_match: int
    distance_dm: int
    reason: str

    @property
    def strength(self) -> tuple[int, int, int, int, int, int, int, str]:
        return (
            0 if self.clear_claim else 1,
            self.traced_first_hit_count,
            self.incident_road_count,
            self.direct_first_hit_count,
            self.primary_match,
            self.current_match,
            -self.distance_dm,
            "" if self.node_id is None else self.node_id,
        )


def _unit_key(case_id: str, unit_id: str) -> str:
    return f"{case_id}/{unit_id}"


def _selected_candidate_id(event_unit: T04EventUnitResult) -> str:
    return str(event_unit.selected_evidence_summary.get("candidate_id") or "")


def _upper_evidence_object_id(event_unit: T04EventUnitResult) -> str:
    return str(event_unit.selected_evidence_summary.get("upper_evidence_object_id") or "")


def _local_region_id(event_unit: T04EventUnitResult) -> str:
    return str(event_unit.selected_evidence_summary.get("local_region_id") or "")


def _point_signature(event_unit: T04EventUnitResult) -> str:
    return str(event_unit.selected_evidence_summary.get("point_signature") or "")


def _role_signature(event_unit: T04EventUnitResult) -> str:
    role_map = event_unit.positive_rcsd_audit.get("rcsd_role_map") or {}
    event_side_role = str(role_map.get("event_side_role") or "")
    event_side_labels = ",".join(sorted(str(label) for label in role_map.get("event_side_labels") or ()))
    local_kind = str(event_unit.local_rcsd_unit_kind or "")
    return "|".join(item for item in (event_side_role, event_side_labels, local_kind) if item)


def _same_axis_close(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> bool:
    lhs_axis = _event_axis_signature(lhs)
    rhs_axis = _event_axis_signature(rhs)
    lhs_basis, lhs_position = _candidate_axis_position(lhs)
    rhs_basis, rhs_position = _candidate_axis_position(rhs)
    lhs_s = lhs_position if lhs_position is not None else (None if lhs.event_chosen_s_m is None else float(lhs.event_chosen_s_m))
    rhs_s = rhs_position if rhs_position is not None else (None if rhs.event_chosen_s_m is None else float(rhs.event_chosen_s_m))
    return bool(
        lhs_axis is not None
        and rhs_axis is not None
        and lhs_axis == rhs_axis
        and lhs_s is not None
        and rhs_s is not None
        and (lhs_basis is None or rhs_basis is None or lhs_basis == rhs_basis)
        and abs(lhs_s - rhs_s) <= EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9
    )


def _overlap_metrics(lhs_geometry, rhs_geometry) -> tuple[float, float]:
    if not _geometry_present(lhs_geometry) or not _geometry_present(rhs_geometry):
        return 0.0, 0.0
    overlap = _safe_normalize_geometry(lhs_geometry.intersection(rhs_geometry))
    overlap_area = float(getattr(overlap, "area", 0.0) or 0.0) if overlap is not None else 0.0
    lhs_area = float(getattr(lhs_geometry, "area", 0.0) or 0.0)
    rhs_area = float(getattr(rhs_geometry, "area", 0.0) or 0.0)
    smaller_area = min(lhs_area, rhs_area)
    overlap_ratio = 0.0 if smaller_area <= 1e-6 else overlap_area / smaller_area
    return overlap_area, overlap_ratio


def _has_evidence_overlap(lhs_geometry, rhs_geometry) -> bool:
    overlap_area, overlap_ratio = _overlap_metrics(lhs_geometry, rhs_geometry)
    return overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2 or overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO


def _classify_evidence_relation(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> str:
    lhs_region_id = _local_region_id(lhs)
    rhs_region_id = _local_region_id(rhs)
    if lhs_region_id and rhs_region_id and lhs_region_id == rhs_region_id:
        return "hard_same_local_region"
    lhs_point_signature = _point_signature(lhs)
    rhs_point_signature = _point_signature(rhs)
    if lhs_point_signature and rhs_point_signature and lhs_point_signature == rhs_point_signature:
        return "hard_same_point_signature"
    if _same_axis_close(lhs, rhs):
        return "hard_same_axis_close"
    if _has_evidence_overlap(lhs.localized_evidence_core_geometry, rhs.localized_evidence_core_geometry):
        return "hard_core_overlap"
    if _has_evidence_overlap(lhs.selected_component_union_geometry, rhs.selected_component_union_geometry):
        return "hard_component_overlap"
    lhs_object_id = _upper_evidence_object_id(lhs)
    rhs_object_id = _upper_evidence_object_id(rhs)
    if lhs_object_id and rhs_object_id and lhs_object_id == rhs_object_id:
        return "soft_shared_upper_object"
    return "none"


def _claim_road_overlap_ratio(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> float:
    lhs_roads = set(lhs.selected_rcsdroad_ids)
    rhs_roads = set(rhs.selected_rcsdroad_ids)
    if not lhs_roads or not rhs_roads:
        return 0.0
    overlap = len(lhs_roads & rhs_roads)
    smaller = min(len(lhs_roads), len(rhs_roads))
    return overlap / smaller if smaller else 0.0


def _classify_rcsd_relation(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> str:
    lhs_required = str(lhs.required_rcsd_node or "")
    rhs_required = str(rhs.required_rcsd_node or "")
    role_mismatch = bool(_role_signature(lhs) and _role_signature(rhs) and _role_signature(lhs) != _role_signature(rhs))
    if lhs_required and rhs_required and lhs_required == rhs_required:
        if _classify_evidence_relation(lhs, rhs).startswith("hard_") and role_mismatch:
            return "hard_same_required_rcsd_node"
        return "soft_same_required_rcsd_node"
    lhs_aggregated = str(lhs.aggregated_rcsd_unit_id or "")
    rhs_aggregated = str(rhs.aggregated_rcsd_unit_id or "")
    if lhs_aggregated and rhs_aggregated and lhs_aggregated == rhs_aggregated:
        return "soft_same_aggregated_unit"
    if _claim_road_overlap_ratio(lhs, rhs) >= 0.5:
        return "soft_high_rcsd_road_overlap"
    return "none"


def _classify_cross_case_relation(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> str:
    lhs_point_signature = _point_signature(lhs)
    rhs_point_signature = _point_signature(rhs)
    if lhs_point_signature and rhs_point_signature and lhs_point_signature == rhs_point_signature:
        return "cross_hard_same_point_signature"
    if _same_axis_close(lhs, rhs):
        return "cross_hard_same_axis_close"
    if _has_evidence_overlap(lhs.localized_evidence_core_geometry, rhs.localized_evidence_core_geometry):
        return "cross_hard_core_overlap"
    if _has_evidence_overlap(lhs.selected_component_union_geometry, rhs.selected_component_union_geometry):
        return "cross_hard_component_overlap"
    lhs_required = str(lhs.required_rcsd_node or "")
    rhs_required = str(rhs.required_rcsd_node or "")
    if lhs_required and rhs_required and lhs_required == rhs_required:
        return "cross_soft_same_required_rcsd_node"
    if (
        set(lhs.selected_rcsdroad_ids)
        and set(rhs.selected_rcsdroad_ids)
        and _claim_road_overlap_ratio(lhs, rhs) >= 0.5
    ):
        return "cross_soft_high_rcsd_road_overlap"
    return "none"


def _build_components(keys: list[str], edges: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    adjacency: dict[str, set[str]] = {key: set() for key in keys}
    edge_types: dict[tuple[str, str], list[str]] = defaultdict(list)
    for lhs_key, rhs_key, relation in edges:
        adjacency.setdefault(lhs_key, set()).add(rhs_key)
        adjacency.setdefault(rhs_key, set()).add(lhs_key)
        edge_key = tuple(sorted((lhs_key, rhs_key)))
        edge_types[edge_key].append(relation)

    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for start_key in keys:
        if start_key in seen or not adjacency.get(start_key):
            continue
        queue = deque([start_key])
        seen.add(start_key)
        component_keys: list[str] = []
        while queue:
            current = queue.popleft()
            component_keys.append(current)
            for next_key in sorted(adjacency.get(current, set())):
                if next_key in seen:
                    continue
                seen.add(next_key)
                queue.append(next_key)
        component_edge_details = []
        relation_types: set[str] = set()
        for lhs_key in component_keys:
            for rhs_key in component_keys:
                if lhs_key >= rhs_key:
                    continue
                key = tuple(sorted((lhs_key, rhs_key)))
                relations = edge_types.get(key, [])
                if not relations:
                    continue
                component_edge_details.append(
                    {
                        "lhs": lhs_key,
                        "rhs": rhs_key,
                        "relations": sorted(set(relations)),
                    }
                )
                relation_types.update(relations)
        components.append(
            {
                "unit_keys": sorted(component_keys),
                "relations": sorted(relation_types),
                "edge_details": component_edge_details,
            }
        )
    return components


def _initialize_conflict_fields(case_result: T04CaseResult) -> T04CaseResult:
    initialized_units: list[T04EventUnitResult] = []
    for event_unit in case_result.event_units:
        candidate_id = _selected_candidate_id(event_unit)
        required_rcsd_node = str(event_unit.required_rcsd_node or "")
        initialized_units.append(
            replace(
                event_unit,
                evidence_conflict_component_id="",
                rcsd_conflict_component_id="",
                evidence_conflict_type="none",
                rcsd_conflict_type="none",
                conflict_resolution_action="kept",
                pre_resolution_candidate_id=candidate_id,
                post_resolution_candidate_id=candidate_id,
                pre_required_rcsd_node=required_rcsd_node,
                post_required_rcsd_node=required_rcsd_node,
                resolution_reason="non_conflict_frozen",
                kept_by_baseline_guard=False,
                conflict_audit={},
            )
        )
    return replace(case_result, event_units=initialized_units)


def _annotate_same_case_evidence(case_result: T04CaseResult) -> tuple[T04CaseResult, list[dict[str, Any]]]:
    units_by_key = {
        _unit_key(case_result.case_spec.case_id, event_unit.spec.event_unit_id): event_unit
        for event_unit in case_result.event_units
    }
    keys = list(units_by_key)
    edges: list[tuple[str, str, str]] = []
    ordered_keys = list(keys)
    for left_index, lhs_key in enumerate(ordered_keys):
        lhs = units_by_key[lhs_key]
        for rhs_key in ordered_keys[left_index + 1 :]:
            rhs = units_by_key[rhs_key]
            relation = _classify_evidence_relation(lhs, rhs)
            if relation != "none":
                edges.append((lhs_key, rhs_key, relation))

    components = _build_components(keys, edges)
    updated_units = dict(units_by_key)
    component_docs: list[dict[str, Any]] = []
    for component_index, component in enumerate(components, start=1):
        component_id = f"same_case_evidence:{case_result.case_spec.case_id}:{component_index:02d}"
        component_type = (
            next((relation for relation in component["relations"] if relation.startswith("hard_")), "")
            or next(iter(component["relations"]), "soft_shared_upper_object")
        )
        component_doc = {
            "component_id": component_id,
            "scope": "same_case",
            "kind": "evidence",
            "case_id": case_result.case_spec.case_id,
            "unit_keys": component["unit_keys"],
            "component_type": component_type,
            "relations": component["relations"],
            "edge_details": component["edge_details"],
            "resolution_action": "kept",
            "resolution_reason": (
                "soft_evidence_shared_object_only"
                if not component_type.startswith("hard_")
                else "hard_evidence_conflict_detected_no_reopen_without_dual_conflict"
            ),
        }
        component_docs.append(component_doc)
        for unit_key in component["unit_keys"]:
            event_unit = updated_units[unit_key]
            updated_units[unit_key] = replace(
                event_unit,
                evidence_conflict_component_id=component_id,
                evidence_conflict_type=component_type,
                resolution_reason=(
                    component_doc["resolution_reason"]
                    if event_unit.resolution_reason == "non_conflict_frozen"
                    else event_unit.resolution_reason
                ),
                kept_by_baseline_guard=bool(component_type.startswith("hard_")),
                conflict_audit={
                    **dict(event_unit.conflict_audit),
                    "same_case_evidence_component": component_doc,
                },
            )
    return (
        replace(
            case_result,
            event_units=[
                updated_units[_unit_key(case_result.case_spec.case_id, event_unit.spec.event_unit_id)]
                for event_unit in case_result.event_units
            ],
        ),
        component_docs,
    )


def _roads_by_node(case_result: T04CaseResult) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for road in case_result.case_bundle.rcsd_roads:
        result[str(road.snodeid)].add(str(road.road_id))
        result[str(road.enodeid)].add(str(road.road_id))
    return result


def _rank_required_node_options(case_result: T04CaseResult, event_unit: T04EventUnitResult) -> list[_ClaimOption]:
    roads_by_id = {str(road.road_id): road for road in case_result.case_bundle.rcsd_roads}
    roads_by_node = _roads_by_node(case_result)
    node_by_id = {str(node.node_id): node for node in case_result.case_bundle.rcsd_nodes}
    selected_road_ids = {str(road_id) for road_id in event_unit.selected_rcsdroad_ids if str(road_id)}
    candidate_node_ids = sorted({str(node_id) for node_id in event_unit.selected_rcsdnode_ids if str(node_id)})
    if not candidate_node_ids:
        return (
            [
                _ClaimOption(
                    node_id=None,
                    node_source=None,
                    clear_claim=True,
                    traced_first_hit_count=0,
                    incident_road_count=0,
                    direct_first_hit_count=0,
                    primary_match=0,
                    current_match=0,
                    distance_dm=0,
                    reason="clear_claim_keep_support",
                )
            ]
            if event_unit.positive_rcsd_present
            else []
        )
    anchor_point = event_unit.fact_reference_point or event_unit.unit_context.representative_node.geometry
    first_hit_road_ids = [str(road_id) for road_id in event_unit.first_hit_rcsdroad_ids if str(road_id)]
    ranked: list[_ClaimOption] = []
    for node_id in candidate_node_ids:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        incident_road_ids = set(roads_by_node.get(node_id, set())) & selected_road_ids
        direct_first_hit_count = len(incident_road_ids & set(first_hit_road_ids))
        traced_first_hit_count = 0
        for first_hit_road_id in first_hit_road_ids:
            traced = _trace_path_to_node(
                start_road_id=first_hit_road_id,
                target_node_id=node_id,
                roads_by_id=roads_by_id,
                roads_by_node_id=roads_by_node,
            )
            if traced:
                traced_first_hit_count += 1
        distance_dm = int(round(float(node.geometry.distance(anchor_point)) * 10.0))
        ranked.append(
            _ClaimOption(
                node_id=node_id,
                node_source=(
                    "second_pass_preserve_current"
                    if node_id == str(event_unit.required_rcsd_node or "")
                    else "second_pass_unique_required_candidate"
                ),
                clear_claim=False,
                traced_first_hit_count=traced_first_hit_count,
                incident_road_count=len(incident_road_ids),
                direct_first_hit_count=direct_first_hit_count,
                primary_match=1 if node_id == str(event_unit.primary_main_rc_node_id or "") else 0,
                current_match=1 if node_id == str(event_unit.required_rcsd_node or "") else 0,
                distance_dm=distance_dm,
                reason="ranked_within_selected_aggregated_support",
            )
        )
    ranked.sort(key=lambda option: option.strength, reverse=True)
    ranked = ranked[:4]
    if event_unit.positive_rcsd_present:
        ranked.append(
            _ClaimOption(
                node_id=None,
                node_source=None,
                clear_claim=True,
                traced_first_hit_count=0,
                incident_road_count=0,
                direct_first_hit_count=0,
                primary_match=0,
                current_match=0,
                distance_dm=0,
                reason="clear_claim_keep_support",
            )
        )
    return ranked


def _claim_assignment_objective(
    units: list[T04EventUnitResult],
    options: list[_ClaimOption],
) -> tuple[Any, ...]:
    nodes = [option.node_id for option in options if option.node_id]
    unique_nonempty = len(set(nodes))
    collisions = len(nodes) - unique_nonempty
    clear_count = sum(1 for option in options if option.clear_claim)
    change_count = sum(
        1
        for event_unit, option in zip(units, options)
        if (option.node_id or "") != str(event_unit.required_rcsd_node or "")
    )
    sorted_strengths = tuple(sorted((option.strength for option in options), reverse=True))
    return (
        unique_nonempty,
        -collisions,
        -clear_count,
        -change_count,
        sorted_strengths,
    )


def _search_claim_component(
    units: list[T04EventUnitResult],
    options_by_unit: list[list[_ClaimOption]],
) -> list[_ClaimOption]:
    best_options: list[_ClaimOption] | None = None
    best_objective: tuple[Any, ...] | None = None
    ordered_indices = sorted(range(len(units)), key=lambda index: len(options_by_unit[index]))

    def _search(order_pos: int, chosen: dict[int, _ClaimOption]) -> None:
        nonlocal best_options, best_objective
        if order_pos >= len(ordered_indices):
            ordered_options = [chosen[index] for index in range(len(units))]
            objective = _claim_assignment_objective(units, ordered_options)
            if best_objective is None or objective > best_objective:
                best_objective = objective
                best_options = ordered_options
            return
        unit_index = ordered_indices[order_pos]
        for option in options_by_unit[unit_index]:
            chosen[unit_index] = option
            _search(order_pos + 1, chosen)
            chosen.pop(unit_index, None)

    _search(0, {})
    return [] if best_options is None else best_options


def _apply_required_node_claim(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    option: _ClaimOption,
    *,
    component_id: str,
    component_type: str,
    resolution_action: str,
    resolution_reason: str,
) -> T04EventUnitResult:
    node_by_id = {str(node.node_id): node for node in case_result.case_bundle.rcsd_nodes}
    required_node_geometry = (
        None
        if option.node_id is None
        else node_by_id.get(str(option.node_id), None).geometry
        if str(option.node_id) in node_by_id
        else None
    )
    updated_selected_candidate_summary = dict(event_unit.selected_candidate_summary)
    updated_selected_evidence_summary = dict(event_unit.selected_evidence_summary)
    updated_selected_candidate_summary["required_rcsd_node"] = option.node_id
    updated_selected_candidate_summary["required_rcsd_node_source"] = option.node_source
    updated_selected_evidence_summary["required_rcsd_node"] = option.node_id
    updated_selected_evidence_summary["required_rcsd_node_source"] = option.node_source
    updated_positive_rcsd_audit = dict(event_unit.positive_rcsd_audit)
    updated_positive_rcsd_audit["pre_resolution_required_rcsd_node"] = str(event_unit.required_rcsd_node or "")
    updated_positive_rcsd_audit["post_resolution_required_rcsd_node"] = option.node_id
    updated_positive_rcsd_audit["second_pass_resolution_action"] = resolution_action
    updated_positive_rcsd_audit["second_pass_resolution_reason"] = resolution_reason
    updated_positive_rcsd_audit["required_rcsd_node_source"] = option.node_source
    return replace(
        event_unit,
        required_rcsd_node=option.node_id,
        required_rcsd_node_source=option.node_source,
        required_rcsd_node_geometry=required_node_geometry,
        selected_candidate_summary=updated_selected_candidate_summary,
        selected_evidence_summary=updated_selected_evidence_summary,
        positive_rcsd_audit=updated_positive_rcsd_audit,
        rcsd_conflict_component_id=component_id,
        rcsd_conflict_type=component_type,
        conflict_resolution_action=resolution_action,
        post_required_rcsd_node="" if option.node_id is None else option.node_id,
        resolution_reason=resolution_reason,
        kept_by_baseline_guard=False,
        conflict_audit={
            **dict(event_unit.conflict_audit),
            "selected_claim_option": {
                "node_id": option.node_id,
                "node_source": option.node_source,
                "clear_claim": option.clear_claim,
                "reason": option.reason,
                "strength": list(option.strength),
            },
        },
    )


def _resolve_same_case_rcsd_claims(case_result: T04CaseResult) -> tuple[T04CaseResult, list[dict[str, Any]]]:
    units_by_key = {
        _unit_key(case_result.case_spec.case_id, event_unit.spec.event_unit_id): event_unit
        for event_unit in case_result.event_units
    }
    keys = list(units_by_key)
    edges: list[tuple[str, str, str]] = []
    ordered_keys = list(keys)
    for left_index, lhs_key in enumerate(ordered_keys):
        lhs = units_by_key[lhs_key]
        for rhs_key in ordered_keys[left_index + 1 :]:
            rhs = units_by_key[rhs_key]
            relation = _classify_rcsd_relation(lhs, rhs)
            if relation != "none":
                edges.append((lhs_key, rhs_key, relation))

    components = _build_components(keys, edges)
    updated_units = dict(units_by_key)
    component_docs: list[dict[str, Any]] = []
    for component_index, component in enumerate(components, start=1):
        component_id = f"same_case_rcsd:{case_result.case_spec.case_id}:{component_index:02d}"
        component_type = (
            next((relation for relation in component["relations"] if relation.startswith("hard_")), "")
            or next(iter(component["relations"]), "soft_same_required_rcsd_node")
        )
        component_units = [updated_units[unit_key] for unit_key in component["unit_keys"]]
        current_required_nodes = [str(unit.required_rcsd_node or "") for unit in component_units]
        options_by_unit = [_rank_required_node_options(case_result, unit) for unit in component_units]
        best_options = _search_claim_component(component_units, options_by_unit)
        current_options = [
            next(
                (
                    option
                    for option in options
                    if (option.node_id or "") == str(unit.required_rcsd_node or "")
                ),
                options[0],
            )
            for unit, options in zip(component_units, options_by_unit)
            if options
        ]
        current_objective = _claim_assignment_objective(component_units, current_options) if current_options else (0,)
        best_objective = _claim_assignment_objective(component_units, best_options) if best_options else (0,)
        current_unique_nonempty = len({node_id for node_id in current_required_nodes if node_id})
        best_unique_nonempty = len({option.node_id for option in best_options if option.node_id}) if best_options else 0
        apply_best = bool(best_options) and best_objective > current_objective and best_unique_nonempty > current_unique_nonempty
        resolution_action = "kept"
        resolution_reason = "same_case_claim_component_kept"
        if apply_best:
            resolution_action = "reassigned_required_rcsd_node"
            resolution_reason = "same_case_unique_required_rcsd_node"
            for unit_key, event_unit, option in zip(component["unit_keys"], component_units, best_options):
                if (option.node_id or "") != str(event_unit.required_rcsd_node or ""):
                    updated_units[unit_key] = _apply_required_node_claim(
                        case_result,
                        event_unit,
                        option,
                        component_id=component_id,
                        component_type=component_type,
                        resolution_action=resolution_action,
                        resolution_reason=resolution_reason,
                    )
                else:
                    updated_units[unit_key] = replace(
                        event_unit,
                        rcsd_conflict_component_id=component_id,
                        rcsd_conflict_type=component_type,
                        conflict_resolution_action="kept",
                        resolution_reason="same_case_claim_component_preserved",
                        kept_by_baseline_guard=False,
                        conflict_audit={
                            **dict(event_unit.conflict_audit),
                            "selected_claim_option": {
                                "node_id": option.node_id,
                                "node_source": option.node_source,
                                "clear_claim": option.clear_claim,
                                "reason": option.reason,
                                "strength": list(option.strength),
                            },
                        },
                    )
        else:
            resolution_action = "kept"
            current_nodes_nonempty = [node_id for node_id in current_required_nodes if node_id]
            current_is_already_unique = len(set(current_nodes_nonempty)) == len(current_nodes_nonempty)
            resolution_reason = (
                "same_case_claim_component_already_unique"
                if current_is_already_unique
                else "kept_by_baseline_guard_no_safer_unique_claim"
            )
            for unit_key in component["unit_keys"]:
                event_unit = updated_units[unit_key]
                updated_units[unit_key] = replace(
                    event_unit,
                    rcsd_conflict_component_id=component_id,
                    rcsd_conflict_type=component_type,
                    conflict_resolution_action=(
                        "kept_by_baseline_guard"
                        if "baseline_guard" in resolution_reason
                        else "kept"
                    ),
                    resolution_reason=resolution_reason,
                    kept_by_baseline_guard="baseline_guard" in resolution_reason,
                    conflict_audit={
                        **dict(event_unit.conflict_audit),
                        "same_case_rcsd_component": {
                            "component_id": component_id,
                            "component_type": component_type,
                            "current_required_nodes": current_required_nodes,
                        },
                    },
                )
        component_docs.append(
            {
                "component_id": component_id,
                "scope": "same_case",
                "kind": "rcsd_claim",
                "case_id": case_result.case_spec.case_id,
                "unit_keys": component["unit_keys"],
                "component_type": component_type,
                "relations": component["relations"],
                "edge_details": component["edge_details"],
                "current_required_nodes": current_required_nodes,
                "resolved_required_nodes": [
                    str(updated_units[unit_key].required_rcsd_node or "")
                    for unit_key in component["unit_keys"]
                ],
                "resolution_action": resolution_action,
                "resolution_reason": resolution_reason,
            }
        )
    return (
        replace(
            case_result,
            event_units=[
                updated_units[_unit_key(case_result.case_spec.case_id, event_unit.spec.event_unit_id)]
                for event_unit in case_result.event_units
            ],
        ),
        component_docs,
    )


def _annotate_cross_case_conflicts(case_results: list[T04CaseResult]) -> tuple[list[T04CaseResult], list[dict[str, Any]]]:
    units_by_key: dict[str, T04EventUnitResult] = {}
    for case_result in case_results:
        for event_unit in case_result.event_units:
            units_by_key[_unit_key(case_result.case_spec.case_id, event_unit.spec.event_unit_id)] = event_unit
    keys = list(units_by_key)
    edges: list[tuple[str, str, str]] = []
    for left_index, lhs_key in enumerate(keys):
        lhs_case_id = lhs_key.split("/", 1)[0]
        lhs = units_by_key[lhs_key]
        for rhs_key in keys[left_index + 1 :]:
            rhs_case_id = rhs_key.split("/", 1)[0]
            if lhs_case_id == rhs_case_id:
                continue
            rhs = units_by_key[rhs_key]
            relation = _classify_cross_case_relation(lhs, rhs)
            if relation != "none":
                edges.append((lhs_key, rhs_key, relation))

    components = _build_components(keys, edges)
    case_units: dict[str, dict[str, T04EventUnitResult]] = {
        case_result.case_spec.case_id: {
            event_unit.spec.event_unit_id: event_unit
            for event_unit in case_result.event_units
        }
        for case_result in case_results
    }
    component_docs: list[dict[str, Any]] = []
    for component_index, component in enumerate(components, start=1):
        component_id = f"cross_case:{component_index:02d}"
        component_type = next(iter(component["relations"]), "cross_soft")
        for unit_key in component["unit_keys"]:
            case_id, event_unit_id = unit_key.split("/", 1)
            event_unit = case_units[case_id][event_unit_id]
            case_units[case_id][event_unit_id] = replace(
                event_unit,
                evidence_conflict_component_id=(
                    component_id
                    if component_type.startswith("cross_hard_") and not event_unit.evidence_conflict_component_id
                    else event_unit.evidence_conflict_component_id
                ),
                rcsd_conflict_component_id=(
                    component_id
                    if component_type.startswith("cross_soft_") and not event_unit.rcsd_conflict_component_id
                    else event_unit.rcsd_conflict_component_id
                ),
                resolution_reason=(
                    event_unit.resolution_reason
                    if event_unit.resolution_reason != "non_conflict_frozen"
                    else "cross_case_conflict_inventory_only"
                ),
                kept_by_baseline_guard=True,
                conflict_audit={
                    **dict(event_unit.conflict_audit),
                    "cross_case_component": {
                        "component_id": component_id,
                        "component_type": component_type,
                        "unit_keys": component["unit_keys"],
                    },
                },
            )
        component_docs.append(
            {
                "component_id": component_id,
                "scope": "cross_case",
                "kind": "mixed",
                "unit_keys": component["unit_keys"],
                "component_type": component_type,
                "relations": component["relations"],
                "edge_details": component["edge_details"],
                "resolution_action": "inventory_only",
                "resolution_reason": "cross_case_inventory_no_selected_hard_cleanup",
            }
        )

    resolved_case_results = [
        replace(
            case_result,
            event_units=[
                case_units[case_result.case_spec.case_id][event_unit.spec.event_unit_id]
                for event_unit in case_result.event_units
            ],
        )
        for case_result in case_results
    ]
    return resolved_case_results, component_docs


def resolve_step4_final_conflicts(
    case_results: list[T04CaseResult],
) -> tuple[list[T04CaseResult], dict[str, Any]]:
    initialized_case_results = [_initialize_conflict_fields(case_result) for case_result in case_results]
    same_case_evidence_components: list[dict[str, Any]] = []
    same_case_rcsd_components: list[dict[str, Any]] = []
    resolved_same_case: list[T04CaseResult] = []
    for case_result in initialized_case_results:
        evidence_resolved, evidence_components = _annotate_same_case_evidence(case_result)
        claim_resolved, claim_components = _resolve_same_case_rcsd_claims(evidence_resolved)
        same_case_evidence_components.extend(evidence_components)
        same_case_rcsd_components.extend(claim_components)
        resolved_same_case.append(claim_resolved)

    resolved_case_results, cross_case_components = _annotate_cross_case_conflicts(resolved_same_case)
    resolution_doc = {
        "same_case_evidence_components": same_case_evidence_components,
        "same_case_rcsd_components": same_case_rcsd_components,
        "cross_case_components": cross_case_components,
    }
    return resolved_case_results, resolution_doc
