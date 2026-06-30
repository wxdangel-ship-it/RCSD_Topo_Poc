from __future__ import annotations

from .step4_rcsd_anchored_reverse_policy import *

def _terminal_continuation_axis_ok(
    road: Any,
    *,
    required_node_id: str,
    operation_type: str,
    axis_context: dict[str, Any],
    nodes_by_id: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    required_node = nodes_by_id.get(required_node_id)
    required_point = None if required_node is None else _as_point(required_node.geometry)
    start_node_id, end_node_id = _road_endpoint_ids(road)
    far_node_id = end_node_id if operation_type == "merge" else start_node_id
    far_node = nodes_by_id.get(str(far_node_id or ""))
    far_point = None if far_node is None else _as_point(far_node.geometry)
    required_s = None if required_point is None else _project_point_to_axis(required_point, axis_context)
    far_s = None if far_point is None else _project_point_to_axis(far_point, axis_context)
    detail = {
        "required_axis_s": None if required_s is None else round(float(required_s), 3),
        "far_node_id": far_node_id,
        "far_axis_s": None if far_s is None else round(float(far_s), 3),
    }
    if required_s is None or far_s is None:
        return True, detail
    if operation_type == "merge":
        return (
            float(far_s) >= float(required_s) + RCSD_TERMINAL_CONTINUATION_AXIS_TOL_M,
            detail,
        )
    if operation_type == "diverge":
        return (
            float(far_s) <= float(required_s) - RCSD_TERMINAL_CONTINUATION_AXIS_TOL_M,
            detail,
        )
    return False, detail


def _same_case_claims_terminal_continuation(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    road_ids: set[str],
    node_ids: set[str],
) -> bool:
    for other in case_result.event_units:
        if other is event_unit or other.spec.event_unit_id == event_unit.spec.event_unit_id:
            continue
        if other.selected_evidence_state == "none":
            continue
        if set(other.selected_rcsdroad_ids) & road_ids:
            return True
        if str(other.required_rcsd_node or "").strip() in node_ids:
            return True
    return False


def _terminal_continuation_expansion(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    mother: T04CandidateAuditEntry,
    axis_context: dict[str, Any],
    drivezone: BaseGeometry | None,
) -> dict[str, Any]:
    operation_type = _operation_type(event_unit, mother)
    required_node_id = str(mother.required_rcsd_node or "").strip()
    if operation_type not in {"merge", "diverge"} or not required_node_id:
        return {
            "used": False,
            "operation_type": operation_type,
            "required_rcsd_node": required_node_id or None,
            "road_ids": [],
            "node_ids": [],
            "skip_reason": "not_applicable",
        }
    roads_by_id = _rcsd_road_lookup(case_result)
    nodes_by_id = _rcsd_node_lookup(case_result)
    already_selected = {str(item) for item in mother.selected_rcsdroad_ids if str(item)}
    accepted_road_ids: list[str] = []
    accepted_node_ids: set[str] = set()
    skipped: list[dict[str, Any]] = []
    drivezone_cover = None if drivezone is None or drivezone.is_empty else drivezone.buffer(0)
    for road_id, road in sorted(roads_by_id.items()):
        if road_id in already_selected:
            continue
        start_node_id, end_node_id = _road_endpoint_ids(road)
        direction_ok = (
            start_node_id == required_node_id
            if operation_type == "merge"
            else end_node_id == required_node_id
        )
        if not direction_ok:
            continue
        geometry = getattr(road, "geometry", None)
        if geometry is None or geometry.is_empty:
            skipped.append({"road_id": road_id, "skip_reason": "empty_geometry"})
            continue
        if drivezone_cover is not None and not drivezone_cover.covers(geometry):
            skipped.append({"road_id": road_id, "skip_reason": "outside_drivezone"})
            continue
        axis_ok, axis_detail = _terminal_continuation_axis_ok(
            road,
            required_node_id=required_node_id,
            operation_type=operation_type,
            axis_context=axis_context,
            nodes_by_id=nodes_by_id,
        )
        if not axis_ok:
            skipped.append({"road_id": road_id, "skip_reason": "axis_direction_mismatch", **axis_detail})
            continue
        road_node_ids = {node_id for node_id in _road_endpoint_ids(road) if node_id}
        if _same_case_claims_terminal_continuation(
            case_result,
            event_unit,
            road_ids={road_id},
            node_ids=road_node_ids,
        ):
            skipped.append({"road_id": road_id, "skip_reason": "same_case_claim_conflict", **axis_detail})
            continue
        accepted_road_ids.append(road_id)
        accepted_node_ids.update(road_node_ids)
    accepted_node_ids.update(_road_endpoint_node_ids(accepted_road_ids, roads_by_id))
    return {
        "used": bool(accepted_road_ids),
        "operation_type": operation_type,
        "required_rcsd_node": required_node_id,
        "road_ids": accepted_road_ids,
        "node_ids": sorted(accepted_node_ids),
        "skip_reason": None if accepted_road_ids else "no_directional_terminal_continuation",
        "skipped": skipped,
    }


def _selected_directional_roads_at_node(
    *,
    node_id: str,
    operation_type: str,
    selected_rcsdroad_ids: Sequence[str],
    roads_by_id: dict[str, Any],
    nodes_by_id: dict[str, Any],
    axis_context: dict[str, Any],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for road_id in selected_rcsdroad_ids:
        road = roads_by_id.get(str(road_id))
        if road is None:
            continue
        start_node_id, end_node_id = _road_endpoint_ids(road)
        direction_ok = (
            start_node_id == node_id
            if operation_type == "merge"
            else end_node_id == node_id
        )
        if not direction_ok:
            continue
        axis_ok, axis_detail = _terminal_continuation_axis_ok(
            road,
            required_node_id=node_id,
            operation_type=operation_type,
            axis_context=axis_context,
            nodes_by_id=nodes_by_id,
        )
        if not axis_ok:
            continue
        matches.append({"road_id": str(road_id), **axis_detail})
    return matches


def _representative_distance_to_rcsd_node(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    node_id: str,
    nodes_by_id: dict[str, Any],
) -> float | None:
    node = nodes_by_id.get(node_id)
    point = None if node is None else _as_point(node.geometry)
    representative = _as_point(getattr(event_unit.unit_context.representative_node, "geometry", None))
    if point is None or representative is None:
        return None
    return float(point.distance(representative))


def _directional_required_node_recovery(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    mother: T04CandidateAuditEntry,
    axis_context: dict[str, Any],
    initial_continuation: dict[str, Any],
) -> dict[str, Any]:
    operation_type = _operation_type(event_unit, mother)
    required_node_id = str(mother.required_rcsd_node or "").strip()
    if (
        operation_type not in {"merge", "diverge"}
        or not required_node_id
        or initial_continuation.get("used")
        or initial_continuation.get("skip_reason") != "no_directional_terminal_continuation"
        or str(mother.required_rcsd_node_source or "").strip() != "aggregated_structural_required"
    ):
        return {"used": False, "skip_reason": "not_applicable"}
    roads_by_id = _rcsd_road_lookup(case_result)
    nodes_by_id = _rcsd_node_lookup(case_result)
    original_matches = _selected_directional_roads_at_node(
        node_id=required_node_id,
        operation_type=operation_type,
        selected_rcsdroad_ids=mother.selected_rcsdroad_ids,
        roads_by_id=roads_by_id,
        nodes_by_id=nodes_by_id,
        axis_context=axis_context,
    )
    candidate_node_ids = _dedupe(mother.selected_rcsdnode_ids)
    candidates: list[dict[str, Any]] = []
    for node_id in candidate_node_ids:
        if node_id == required_node_id:
            continue
        matches = _selected_directional_roads_at_node(
            node_id=node_id,
            operation_type=operation_type,
            selected_rcsdroad_ids=mother.selected_rcsdroad_ids,
            roads_by_id=roads_by_id,
            nodes_by_id=nodes_by_id,
            axis_context=axis_context,
        )
        if not matches:
            continue
        distance_m = _representative_distance_to_rcsd_node(case_result, event_unit, node_id, nodes_by_id)
        candidates.append(
            {
                "required_rcsd_node": node_id,
                "selected_directional_roads": matches,
                "distance_to_representative_m": None if distance_m is None else round(float(distance_m), 3),
            }
        )
    if len(candidates) != 1:
        return {
            "used": False,
            "skip_reason": "ambiguous_directional_required_node" if candidates else "no_directional_required_node_candidate",
            "candidates": candidates,
        }
    original_distance = _representative_distance_to_rcsd_node(case_result, event_unit, required_node_id, nodes_by_id)
    candidate = candidates[0]
    candidate_distance = candidate.get("distance_to_representative_m")
    if original_distance is not None and candidate_distance is not None and float(candidate_distance) > float(original_distance) + 1e-9:
        return {
            "used": False,
            "skip_reason": "candidate_farther_than_original_required_node",
            "original_distance_to_representative_m": round(float(original_distance), 3),
            "candidate": candidate,
        }
    if (
        original_matches
        and original_distance is not None
        and candidate_distance is not None
        and float(candidate_distance) >= float(original_distance) - 1e-9
    ):
        return {
            "used": False,
            "skip_reason": "candidate_not_closer_than_original_required_node",
            "required_rcsd_node": required_node_id,
            "original_selected_directional_roads": original_matches,
            "original_distance_to_representative_m": round(float(original_distance), 3),
            "candidate": candidate,
        }
    return {
        "used": True,
        "previous_required_rcsd_node": required_node_id,
        "required_rcsd_node": str(candidate["required_rcsd_node"]),
        "required_rcsd_node_source": "anchored_reverse_directional_selected_road",
        "operation_type": operation_type,
        "original_selected_directional_roads": original_matches,
        "original_distance_to_representative_m": None if original_distance is None else round(float(original_distance), 3),
        **candidate,
    }


def _shortest_selected_rcsd_path(
    *,
    roads_by_id: dict[str, Any],
    selected_road_ids: set[str],
    start_node_id: str,
    target_node_id: str,
) -> tuple[str, ...]:
    if start_node_id == target_node_id:
        return ()
    adjacency: dict[str, list[tuple[float, str, str]]] = {}
    for road_id in selected_road_ids:
        road = roads_by_id.get(road_id)
        if road is None:
            continue
        start_id, end_id = _road_endpoint_ids(road)
        if not start_id or not end_id:
            continue
        length = max(0.001, float(getattr(getattr(road, "geometry", None), "length", 1.0) or 1.0))
        adjacency.setdefault(start_id, []).append((length, end_id, road_id))
        adjacency.setdefault(end_id, []).append((length, start_id, road_id))
    queue: list[tuple[float, str, tuple[str, ...]]] = [(0.0, start_node_id, ())]
    seen: dict[str, float] = {}
    while queue:
        cost, node_id, path = heapq.heappop(queue)
        if node_id in seen and seen[node_id] <= cost:
            continue
        seen[node_id] = cost
        if node_id == target_node_id:
            return path
        for length, next_node_id, road_id in adjacency.get(node_id, []):
            if next_node_id in seen and seen[next_node_id] <= cost + length:
                continue
            heapq.heappush(queue, (cost + length, next_node_id, (*path, road_id)))
    return ()


def _direct_selected_rcsd_roads_at_node(
    *,
    roads_by_id: dict[str, Any],
    selected_rcsdroad_ids: Sequence[str],
    node_id: str,
) -> tuple[str, ...]:
    direct_road_ids: list[str] = []
    for road_id in selected_rcsdroad_ids:
        road = roads_by_id.get(str(road_id))
        if road is None:
            continue
        if node_id in {endpoint for endpoint in _road_endpoint_ids(road) if endpoint}:
            direct_road_ids.append(str(road_id))
    return _dedupe(direct_road_ids)


def _pruned_rcsd_node_ids_for_roads(
    *,
    required_node_id: str,
    selected_rcsdnode_ids: Sequence[str],
    kept_road_ids: Sequence[str],
    roads_by_id: dict[str, Any],
) -> tuple[str, ...]:
    kept_endpoint_node_ids = _road_endpoint_node_ids(kept_road_ids, roads_by_id)
    return _dedupe(
        [
            required_node_id,
            *(
                node_id
                for node_id in selected_rcsdnode_ids
                if node_id in kept_endpoint_node_ids
            ),
        ]
    )


def _prune_aggregated_node_centric_reverse_roads(
    case_result: T04CaseResult,
    mother: T04CandidateAuditEntry,
    selected_rcsdroad_ids: Sequence[str],
    selected_rcsdnode_ids: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, Any]]:
    required_node_id = str(mother.required_rcsd_node or "").strip()
    first_hit_ids = _dedupe(mother.first_hit_rcsdroad_ids)
    if (
        str(mother.required_rcsd_node_source or "").strip() != "aggregated_node_centric"
        or str(mother.positive_rcsd_support_level or "").strip() != "primary_support"
        or str(mother.positive_rcsd_consistency_level or "").strip() != "A"
        or not required_node_id
        or not first_hit_ids
    ):
        return tuple(selected_rcsdroad_ids), tuple(selected_rcsdnode_ids), {"used": False, "skip_reason": "not_applicable"}
    roads_by_id = _rcsd_road_lookup(case_result)
    selected_set = {str(item) for item in selected_rcsdroad_ids if str(item) in roads_by_id}
    if not selected_set:
        return tuple(selected_rcsdroad_ids), tuple(selected_rcsdnode_ids), {"used": False, "skip_reason": "empty_selection"}
    direct_required_road_ids = _direct_selected_rcsd_roads_at_node(
        roads_by_id=roads_by_id,
        selected_rcsdroad_ids=selected_rcsdroad_ids,
        node_id=required_node_id,
    )
    if len(direct_required_road_ids) >= 3:
        direct_required_set = set(direct_required_road_ids)
        pruned_road_ids = _dedupe(
            road_id for road_id in selected_rcsdroad_ids if road_id in direct_required_set
        )
        pruned_node_ids = _pruned_rcsd_node_ids_for_roads(
            required_node_id=required_node_id,
            selected_rcsdnode_ids=selected_rcsdnode_ids,
            kept_road_ids=pruned_road_ids,
            roads_by_id=roads_by_id,
        )
        return (
            pruned_road_ids,
            pruned_node_ids,
            {
                "used": set(pruned_road_ids) != set(selected_rcsdroad_ids),
                "mode": "required_node_semantic_junction_direct_arms",
                "required_rcsd_node": required_node_id,
                "first_hit_rcsdroad_ids": list(first_hit_ids),
                "direct_required_rcsdroad_ids": list(direct_required_road_ids),
                "pre_prune_road_ids": list(selected_rcsdroad_ids),
                "post_prune_road_ids": list(pruned_road_ids),
                "post_prune_node_ids": list(pruned_node_ids),
            },
        )
    kept_ids: set[str] = set()
    for road_id in first_hit_ids:
        road = roads_by_id.get(road_id)
        if road is None:
            continue
        kept_ids.add(road_id)
        endpoints = [node_id for node_id in _road_endpoint_ids(road) if node_id]
        if required_node_id in endpoints:
            continue
        candidate_paths = [
            _shortest_selected_rcsd_path(
                roads_by_id=roads_by_id,
                selected_road_ids=selected_set,
                start_node_id=node_id,
                target_node_id=required_node_id,
            )
            for node_id in endpoints
        ]
        candidate_paths = [path for path in candidate_paths if path]
        if candidate_paths:
            kept_ids.update(min(candidate_paths, key=len))
    if not kept_ids:
        return tuple(selected_rcsdroad_ids), tuple(selected_rcsdnode_ids), {"used": False, "skip_reason": "no_path"}
    pruned_road_ids = _dedupe(road_id for road_id in selected_rcsdroad_ids if road_id in kept_ids)
    pruned_node_ids = _pruned_rcsd_node_ids_for_roads(
        required_node_id=required_node_id,
        selected_rcsdnode_ids=selected_rcsdnode_ids,
        kept_road_ids=pruned_road_ids,
        roads_by_id=roads_by_id,
    )
    return (
        pruned_road_ids,
        pruned_node_ids,
        {
            "used": set(pruned_road_ids) != set(selected_rcsdroad_ids),
            "mode": "first_hit_shortest_path_to_required_node",
            "required_rcsd_node": required_node_id,
            "first_hit_rcsdroad_ids": list(first_hit_ids),
            "pre_prune_road_ids": list(selected_rcsdroad_ids),
            "post_prune_road_ids": list(pruned_road_ids),
            "post_prune_node_ids": list(pruned_node_ids),
        },
    )


def _aggregate_id_conflicts(lhs: str, rhs: str, *, same_case: bool) -> bool:
    if not lhs or not rhs or lhs != rhs:
        return False
    if same_case:
        return True
    case_local_markers = (":aggregated:", "event_unit_", "node_")
    return not any(lhs.startswith(marker) or marker in lhs for marker in case_local_markers)


def _rcsd_claim_conflicts(
    event_unit: T04EventUnitResult,
    other: T04EventUnitResult,
    *,
    aggregate_id: str,
    road_ids: set[str],
    node_ids: set[str],
    same_case: bool,
) -> bool:
    if other is event_unit or other.selected_evidence_state == "none":
        return False
    other_required = str(other.required_rcsd_node or "").strip()
    if other_required and other_required in node_ids:
        return True
    other_aggregate = str(other.aggregated_rcsd_unit_id or "").strip()
    if _aggregate_id_conflicts(str(aggregate_id or "").strip(), other_aggregate, same_case=same_case):
        return True
    return _road_overlap_ratio(road_ids, other.selected_rcsdroad_ids) >= RCSD_CLAIM_ROAD_OVERLAP_RATIO


def _same_axis_close(
    lhs_summary: dict[str, Any],
    rhs_summary: dict[str, Any],
) -> bool:
    lhs_axis = str(lhs_summary.get("axis_signature") or "").strip()
    rhs_axis = str(rhs_summary.get("axis_signature") or "").strip()
    if not lhs_axis or lhs_axis != rhs_axis:
        return False
    lhs_basis = str(lhs_summary.get("axis_position_basis") or "").strip()
    rhs_basis = str(rhs_summary.get("axis_position_basis") or "").strip()
    if lhs_basis and rhs_basis and lhs_basis != rhs_basis:
        return False
    try:
        lhs_s = float(lhs_summary.get("axis_position_m"))
        rhs_s = float(rhs_summary.get("axis_position_m"))
    except (TypeError, ValueError):
        return False
    return abs(lhs_s - rhs_s) <= EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9


def _evidence_identifier_conflicts(key: str, lhs: str, rhs: str, *, same_case: bool) -> bool:
    if not lhs or not rhs or lhs != rhs:
        return False
    if same_case:
        return True
    return key == "point_signature"


def _evidence_conflicts(
    other: T04EventUnitResult,
    *,
    summary: dict[str, Any],
    component_geometry: BaseGeometry | None,
    core_geometry: BaseGeometry | None,
    same_case: bool,
) -> bool:
    if other.selected_evidence_state == "none":
        return False
    other_summary = other.selected_evidence_summary
    for key in ("upper_evidence_object_id", "local_region_id", "point_signature"):
        lhs = str(summary.get(key) or "").strip()
        rhs = str(other_summary.get(key) or "").strip()
        if _evidence_identifier_conflicts(key, lhs, rhs, same_case=same_case):
            return True
    if _same_axis_close(summary, other_summary):
        return True
    return _has_evidence_overlap(core_geometry, other.localized_evidence_core_geometry) or _has_evidence_overlap(
        component_geometry,
        other.selected_component_union_geometry,
    )




__all__ = [name for name in globals() if not name.startswith("__")]
