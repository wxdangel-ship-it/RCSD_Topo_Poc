from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult

ROAD_SURFACE_FORK_BINDING_REASON = "road_surface_fork_binding_used"
UNBOUND_ROAD_SURFACE_FORK_REASON = "unbound_road_surface_fork_without_bifurcation_rcsd"
STRUCTURE_ONLY_SURFACE_REASON = "road_surface_fork_structure_only_used"
SWSD_JUNCTION_WINDOW_REASON = "swsd_junction_window_no_rcsd_used"
RCSD_JUNCTION_WINDOW_REASON = "rcsd_junction_window_used"
ROAD_SURFACE_FORK_SCOPE = "road_surface_fork"
THROAT_CORE_SCOPE = "throat_core"
SWSD_JUNCTION_WINDOW_SOURCE = "swsd_junction_window"
RCSD_JUNCTION_WINDOW_SOURCE = "rcsd_junction_window"
SWSD_JUNCTION_WINDOW_POSITION_SOURCE = "swsd_junction_window_axis_projection"
RCSD_JUNCTION_WINDOW_POSITION_SOURCE = "rcsd_junction_window_axis_projection"
JUNCTION_WINDOW_HALF_LENGTH_M = 20.0
RELAXED_AGGREGATED_RCSD_REASONS = {
    "role_mapping_partial_relaxed_aggregated",
}
RELAXED_PRIMARY_BINDING_MODE = "road_surface_fork_relaxed_primary_rcsd_binding"
RELAXED_PRIMARY_NODE_SOURCE = "road_surface_fork_relaxed_primary_rcsd"
RELAXED_PRIMARY_MAX_REPRESENTATIVE_DISTANCE_M = 20.0
SURFACE_RECOVERY_MIN_THROAT_RATIO = 0.8
SURFACE_RECOVERY_MAX_REFERENCE_DISTANCE_M = 10.0
SURFACE_RECOVERY_THROAT_EXCLUSION_M = 0.0
STRUCTURE_ONLY_SURFACE_MIN_AXIS_POSITION_M = 12.0
STRUCTURE_ONLY_SURFACE_MIN_PAIR_MIDDLE_RATIO = 0.05
STRUCTURE_ONLY_SURFACE_WINDOW_MAX_PAIR_MIDDLE_RATIO = 0.10
SAME_CASE_RCSD_ROAD_OVERLAP_MIN_COUNT = 2
SAME_CASE_RCSD_ROAD_OVERLAP_MIN_RATIO = 0.5
SURFACE_FORK_REFERENCE_SURFACE_TOLERANCE_M = 3.0
SURFACE_FORK_APEX_MIN_ORIGIN_DISTANCE_M = 25.0
SURFACE_FORK_APEX_MIN_BRANCH_SEPARATION_M = 10.0
SURFACE_FORK_APEX_MAX_MIDLINE_DISTANCE_M = 6.0
SURFACE_FORK_APEX_MAX_MIDLINE_SEPARATION_RATIO = 0.5
SURFACE_FORK_APEX_MIN_TRANSVERSE_ALIGNMENT = 0.7


def _dedupe(items: Iterable[Any]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return tuple(values)


def _clean_surface_review_reasons(items: Iterable[Any]) -> tuple[str, ...]:
    dropped = {
        "event_reference_outside_branch_middle",
        "fallback_to_weak_evidence",
        "node_fallback_candidate_not_primary_eligible",
        "no_selected_evidence_after_reselection",
        "missing_positive_rcsd",
    }
    return _dedupe(reason for reason in items if str(reason or "") not in dropped)


def _feature_geometry_by_id(features: Iterable[Any], feature_id: str, id_attr: str) -> BaseGeometry | None:
    text = str(feature_id or "").strip()
    if not text:
        return None
    for feature in features:
        if str(getattr(feature, id_attr, "") or "") == text:
            geometry = getattr(feature, "geometry", None)
            if geometry is not None and not geometry.is_empty:
                return geometry
    return None


def _union_geometries(geometries: Iterable[BaseGeometry | None]) -> BaseGeometry | None:
    parts = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not parts:
        return None
    try:
        merged = unary_union(parts)
    except Exception:
        merged = parts[0]
    if merged is None or merged.is_empty:
        return None
    return merged


def _polygon_parts(geometry: BaseGeometry | None) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    return []


def _seed_component_geometry(
    geometry: BaseGeometry | None,
    seed_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    parts = _polygon_parts(geometry)
    if not parts:
        return geometry
    if seed_geometry is None or seed_geometry.is_empty:
        return max(parts, key=lambda part: float(part.area))
    touching = [part for part in parts if part.buffer(1e-6).intersects(seed_geometry)]
    if touching:
        return max(touching, key=lambda part: float(part.area))
    return min(parts, key=lambda part: (float(part.distance(seed_geometry)), -float(part.area)))


def _largest_polygon_component(geometry: BaseGeometry | None) -> BaseGeometry | None:
    parts = _polygon_parts(geometry)
    if not parts:
        return geometry
    return max(parts, key=lambda part: float(part.area))


def _road_geometries(case_result: T04CaseResult, road_ids: Iterable[str]) -> BaseGeometry | None:
    return _union_geometries(
        _feature_geometry_by_id(case_result.case_bundle.rcsd_roads, road_id, "road_id")
        for road_id in road_ids
    )


def _node_geometries(case_result: T04CaseResult, node_ids: Iterable[str]) -> BaseGeometry | None:
    return _union_geometries(
        _feature_geometry_by_id(case_result.case_bundle.rcsd_nodes, node_id, "node_id")
        for node_id in node_ids
    )


def _swsd_road_line(case_result: T04CaseResult, road_id: str) -> LineString | None:
    geometry = _feature_geometry_by_id(case_result.case_bundle.roads, road_id, "road_id")
    if isinstance(geometry, LineString) and not geometry.is_empty and geometry.length > 1e-6:
        return geometry
    return None


def _ordered_line_from_point(line: LineString, origin: Point) -> LineString:
    coords = list(line.coords)
    if not coords:
        return line
    first = Point(coords[0])
    last = Point(coords[-1])
    if last.distance(origin) < first.distance(origin):
        coords = list(reversed(coords))
    return LineString(coords)


def _boundary_pair_road_ids(event_unit: T04EventUnitResult) -> tuple[str, str] | None:
    summaries = (
        event_unit.selected_candidate_summary,
        event_unit.selected_evidence_summary,
        event_unit.pair_local_summary,
    )
    for summary in summaries:
        signature = str((summary or {}).get("boundary_pair_signature") or "").strip()
        if not signature:
            continue
        parts = tuple(part.strip() for part in signature.split("__") if part.strip())
        if len(parts) == 2:
            return parts[0], parts[1]
    return None


def _road_surface_reference_domain(event_unit: T04EventUnitResult) -> BaseGeometry | None:
    return (
        event_unit.selected_candidate_region_geometry
        or event_unit.pair_local_region_geometry
        or event_unit.pair_local_structure_face_geometry
        or event_unit.selected_evidence_region_geometry
    )


def _surface_fork_boundary_apex_point(
    surface_domain: BaseGeometry,
    *,
    ordered_a: LineString,
    ordered_b: LineString,
    origin: Point,
) -> tuple[Point | None, dict[str, Any]]:
    candidates: list[tuple[tuple[float, float, float], Point, dict[str, Any]]] = []
    for polygon_index, polygon in enumerate(_polygon_parts(surface_domain)):
        coords = list(polygon.exterior.coords)
        if len(coords) < 2:
            continue
        for segment_index, (start, end) in enumerate(zip(coords[:-1], coords[1:])):
            seg_x = float(end[0]) - float(start[0])
            seg_y = float(end[1]) - float(start[1])
            seg_len = (seg_x * seg_x + seg_y * seg_y) ** 0.5
            if seg_len <= 1e-6:
                continue
            midpoint = Point(
                (float(start[0]) + float(end[0])) / 2.0,
                (float(start[1]) + float(end[1])) / 2.0,
            )
            origin_distance = float(midpoint.distance(origin))
            if origin_distance < SURFACE_FORK_APEX_MIN_ORIGIN_DISTANCE_M:
                continue
            sample_distance = min(
                max(0.0, (float(ordered_a.project(midpoint)) + float(ordered_b.project(midpoint))) / 2.0),
                float(ordered_a.length),
                float(ordered_b.length),
            )
            point_a = ordered_a.interpolate(sample_distance)
            point_b = ordered_b.interpolate(sample_distance)
            branch_separation = float(point_a.distance(point_b))
            if branch_separation < SURFACE_FORK_APEX_MIN_BRANCH_SEPARATION_M:
                continue
            pair_midpoint = Point(
                (float(point_a.x) + float(point_b.x)) / 2.0,
                (float(point_a.y) + float(point_b.y)) / 2.0,
            )
            midline_distance = float(midpoint.distance(pair_midpoint))
            max_midline_distance = max(
                SURFACE_FORK_APEX_MAX_MIDLINE_DISTANCE_M,
                branch_separation * SURFACE_FORK_APEX_MAX_MIDLINE_SEPARATION_RATIO,
            )
            if midline_distance > max_midline_distance:
                continue
            sep_x = float(point_b.x) - float(point_a.x)
            sep_y = float(point_b.y) - float(point_a.y)
            sep_len = (sep_x * sep_x + sep_y * sep_y) ** 0.5
            if sep_len <= 1e-6:
                continue
            transverse_alignment = abs((seg_x * sep_x + seg_y * sep_y) / (seg_len * sep_len))
            if transverse_alignment < SURFACE_FORK_APEX_MIN_TRANSVERSE_ALIGNMENT:
                continue
            detail = {
                "road_surface_fork_reference_point_mode": "road_surface_fork_boundary_apex",
                "road_surface_fork_reference_distance_m": round(origin_distance, 3),
                "road_surface_fork_reference_sample_s_m": round(sample_distance, 3),
                "road_surface_fork_branch_separation_m": round(branch_separation, 3),
                "road_surface_fork_apex_midline_distance_m": round(midline_distance, 3),
                "road_surface_fork_apex_transverse_alignment": round(transverse_alignment, 3),
                "road_surface_fork_apex_polygon_index": polygon_index,
                "road_surface_fork_apex_segment_index": segment_index,
            }
            score = (sample_distance, midline_distance, -transverse_alignment)
            candidates.append((score, midpoint, detail))
    if not candidates:
        return None, {"road_surface_fork_reference_point_mode": "boundary_apex_unavailable"}
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], candidates[0][2]


def _road_surface_fork_reference_point(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[Point | None, dict[str, Any]]:
    surface_domain = _road_surface_reference_domain(event_unit)
    origin = event_unit.fact_reference_point or getattr(event_unit.unit_context.representative_node, "geometry", None)
    if surface_domain is None or surface_domain.is_empty or not isinstance(origin, Point):
        return None, {"road_surface_fork_reference_point_mode": "unavailable"}
    seed_point = surface_domain.representative_point()
    boundary_pair = _boundary_pair_road_ids(event_unit)
    if boundary_pair is None:
        return seed_point, {
            "road_surface_fork_reference_point_mode": "surface_representative_point",
            "road_surface_fork_reference_distance_m": round(float(seed_point.distance(origin)), 3),
        }

    line_a = _swsd_road_line(case_result, boundary_pair[0])
    line_b = _swsd_road_line(case_result, boundary_pair[1])
    if line_a is None or line_b is None:
        return seed_point, {
            "road_surface_fork_reference_point_mode": "surface_representative_point",
            "road_surface_fork_reference_distance_m": round(float(seed_point.distance(origin)), 3),
            "boundary_pair_road_ids": list(boundary_pair),
        }

    ordered_a = _ordered_line_from_point(line_a, origin)
    ordered_b = _ordered_line_from_point(line_b, origin)
    apex_point, apex_detail = _surface_fork_boundary_apex_point(
        surface_domain,
        ordered_a=ordered_a,
        ordered_b=ordered_b,
        origin=origin,
    )
    if apex_point is not None:
        apex_detail["boundary_pair_road_ids"] = list(boundary_pair)
        apex_detail["road_surface_fork_seed_point_xy"] = [
            round(float(seed_point.x), 3),
            round(float(seed_point.y), 3),
        ]
        return apex_point, apex_detail

    sample_distance = min(
        max(0.0, (float(ordered_a.project(seed_point)) + float(ordered_b.project(seed_point))) / 2.0),
        float(ordered_a.length),
        float(ordered_b.length),
    )
    point_a = ordered_a.interpolate(sample_distance)
    point_b = ordered_b.interpolate(sample_distance)
    midpoint = Point((float(point_a.x) + float(point_b.x)) / 2.0, (float(point_a.y) + float(point_b.y)) / 2.0)
    if not surface_domain.buffer(SURFACE_FORK_REFERENCE_SURFACE_TOLERANCE_M, join_style=2).covers(midpoint):
        midpoint = seed_point
    return midpoint, {
        "road_surface_fork_reference_point_mode": "boundary_pair_surface_midpoint_fallback",
        "boundary_pair_road_ids": list(boundary_pair),
        "road_surface_fork_reference_distance_m": round(float(midpoint.distance(origin)), 3),
        "road_surface_fork_reference_sample_s_m": round(sample_distance, 3),
        "road_surface_fork_branch_separation_m": round(float(point_a.distance(point_b)), 3),
        "road_surface_fork_seed_point_xy": [round(float(seed_point.x), 3), round(float(seed_point.y), 3)],
    }


def _point_geometry(case_result: T04CaseResult, node_id: str | None) -> Point | None:
    geometry = _feature_geometry_by_id(case_result.case_bundle.rcsd_nodes, str(node_id or ""), "node_id")
    return geometry if isinstance(geometry, Point) else None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strong_aggregated_unit(audit: dict[str, Any]) -> dict[str, Any] | None:
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        decision_reason = str(aggregate.get("decision_reason") or "").strip()
        if decision_reason in RELAXED_AGGREGATED_RCSD_REASONS:
            continue
        if decision_reason and decision_reason != "role_mapping_exact_aggregated":
            continue
        if str(aggregate.get("consistency_level") or "") != "A":
            continue
        if not str(aggregate.get("required_node_id") or "").strip():
            continue
        if not _has_bifurcation_role_support(aggregate):
            continue
        return aggregate
    return None


def _has_bifurcation_role_support(aggregate: dict[str, Any]) -> bool:
    labels = {
        str(label or "").strip()
        for label in aggregate.get("normalized_event_side_labels") or aggregate.get("event_side_labels") or ()
        if str(label or "").strip()
    }
    if len(labels) < 2:
        return False
    first_hit_count = len(
        {
            str(item or "").strip()
            for item in aggregate.get("first_hit_rcsdroad_ids") or ()
            if str(item or "").strip()
        }
    )
    if first_hit_count >= 2:
        return True
    return len(
        {
            str(assignment.get("road_id") or "").strip()
            for assignment in aggregate.get("role_assignments") or ()
            if isinstance(assignment, dict)
            and bool(assignment.get("first_hit"))
            and str(assignment.get("road_id") or "").strip()
        }
    ) >= 2


def _entry_uses_relaxed_rcsd(entry: T04CandidateAuditEntry) -> bool:
    summary = entry.candidate_summary
    return str(summary.get("rcsd_decision_reason") or "").strip() in RELAXED_AGGREGATED_RCSD_REASONS


def _first_hit_ids(audit: dict[str, Any]) -> tuple[str, ...]:
    return _dedupe(audit.get("first_hit_rcsdroad_ids") or ())


def _aggregate_ids(aggregate: dict[str, Any], key: str) -> tuple[str, ...]:
    return _dedupe(aggregate.get(key) or ())


def _aggregate_labels(aggregate: dict[str, Any]) -> set[str]:
    return {
        str(label or "").strip()
        for label in aggregate.get("normalized_event_side_labels") or aggregate.get("event_side_labels") or ()
        if str(label or "").strip()
    }


def _local_unit_id_for_node(aggregate: dict[str, Any], node_id: str) -> str | None:
    expected = f":node:{node_id}"
    for unit_id in aggregate.get("member_unit_ids") or ():
        text = str(unit_id or "").strip()
        if text.endswith(expected):
            return text
    return None


def _relaxed_primary_aggregate(
    audit: dict[str, Any],
    *,
    allow_exact_primary_fallback: bool = False,
) -> dict[str, Any] | None:
    first_hit_ids = set(_first_hit_ids(audit))
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        decision_reason = str(aggregate.get("decision_reason") or "").strip()
        primary_node = str(aggregate.get("primary_node_id") or "").strip()
        if not primary_node:
            continue
        aggregate_road_ids = set(_aggregate_ids(aggregate, "road_ids"))
        if first_hit_ids and not (first_hit_ids & aggregate_road_ids):
            continue
        consistency_level = str(aggregate.get("consistency_level") or "").strip()
        if decision_reason in RELAXED_AGGREGATED_RCSD_REASONS:
            if consistency_level != "B":
                continue
            if len(_aggregate_labels(aggregate)) < 2:
                continue
            return aggregate
        if (
            allow_exact_primary_fallback
            and decision_reason == "role_mapping_exact_aggregated"
            and consistency_level == "A"
        ):
            return aggregate
    return None


def _junction_window_aggregate(audit: dict[str, Any]) -> dict[str, Any] | None:
    aggregate = _strong_aggregated_unit(audit)
    if aggregate is not None:
        return aggregate
    aggregate = _relaxed_primary_aggregate(audit, allow_exact_primary_fallback=True)
    if aggregate is not None:
        return aggregate
    first_hit_ids = set(_first_hit_ids(audit))
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        primary_node = str(aggregate.get("primary_node_id") or "").strip()
        if not primary_node:
            continue
        consistency_level = str(aggregate.get("consistency_level") or "").strip()
        if consistency_level not in {"A", "B"}:
            continue
        aggregate_road_ids = set(_aggregate_ids(aggregate, "road_ids"))
        if first_hit_ids and not (first_hit_ids & aggregate_road_ids):
            continue
        return aggregate
    return None


def _selected_surface_summary(event_unit: T04EventUnitResult) -> dict[str, Any]:
    return dict(event_unit.selected_evidence_summary or event_unit.selected_candidate_summary or {})


def _weak_structure_surface_window_candidate(summary: dict[str, Any]) -> bool:
    if str(summary.get("candidate_scope") or "") != ROAD_SURFACE_FORK_SCOPE:
        return False
    pair_middle_ratio = _as_float(summary.get("pair_middle_overlap_ratio")) or 0.0
    return pair_middle_ratio <= STRUCTURE_ONLY_SURFACE_WINDOW_MAX_PAIR_MIDDLE_RATIO


def _same_case_rcsd_claim_conflict(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    aggregate_id: str,
    required_node: str,
    primary_node: str,
    selected_roads: Iterable[Any],
    selected_nodes: Iterable[Any],
) -> dict[str, Any] | None:
    candidate_roads = set(_dedupe(selected_roads))
    candidate_nodes = set(_dedupe([required_node, primary_node, *list(selected_nodes)]))
    candidate_aggregate_ids = set(_dedupe([aggregate_id]))
    current_unit_id = event_unit.spec.event_unit_id
    for other in case_result.event_units:
        if other.spec.event_unit_id == current_unit_id:
            continue
        other_required = str(other.required_rcsd_node or "").strip()
        other_nodes = set(_dedupe([other_required, *list(other.selected_rcsdnode_ids or ())]))
        node_overlap = candidate_nodes & other_nodes
        if other_required and node_overlap:
            return {
                "skip_reason": "skipped_same_case_rcsd_claim_conflict",
                "conflict_type": "rcsd_node_claim",
                "conflict_unit_id": other.spec.event_unit_id,
                "conflict_required_rcsd_node": other_required,
                "overlap_rcsdnode_ids": sorted(node_overlap),
            }
        other_aggregate_ids = set(
            _dedupe([other.aggregated_rcsd_unit_id, *list(other.aggregated_rcsd_unit_ids or ())])
        )
        aggregate_overlap = candidate_aggregate_ids & other_aggregate_ids
        if aggregate_overlap:
            return {
                "skip_reason": "skipped_same_case_rcsd_claim_conflict",
                "conflict_type": "aggregated_rcsd_unit",
                "conflict_unit_id": other.spec.event_unit_id,
                "overlap_aggregated_rcsd_unit_ids": sorted(aggregate_overlap),
            }
        other_roads = set(_dedupe(other.selected_rcsdroad_ids or ()))
        road_overlap = candidate_roads & other_roads
        if road_overlap:
            overlap_ratio = len(road_overlap) / max(1, min(len(candidate_roads), len(other_roads)))
            if (
                len(road_overlap) >= SAME_CASE_RCSD_ROAD_OVERLAP_MIN_COUNT
                and overlap_ratio >= SAME_CASE_RCSD_ROAD_OVERLAP_MIN_RATIO
            ):
                return {
                    "skip_reason": "skipped_same_case_rcsd_claim_conflict",
                    "conflict_type": "selected_rcsdroad_overlap",
                    "conflict_unit_id": other.spec.event_unit_id,
                    "overlap_ratio": round(overlap_ratio, 3),
                    "overlap_rcsdroad_ids": sorted(road_overlap),
                }
    return None


def _build_surface_summary(
    entry: T04CandidateAuditEntry,
    *,
    evidence_source: str,
    position_source: str,
    bind_detail: dict[str, Any],
) -> dict[str, Any]:
    summary = dict(entry.candidate_summary)
    summary.update(
        {
            "candidate_scope": ROAD_SURFACE_FORK_SCOPE,
            "selected_evidence_state": "found",
            "evidence_source": evidence_source,
            "position_source": position_source,
            "primary_eligible": True,
            "selection_status": "selected",
            "decision_reason": ROAD_SURFACE_FORK_BINDING_REASON,
            "road_surface_fork_binding": dict(bind_detail),
        }
    )
    return summary


def _candidate_entries_with_selection(
    entries: tuple[T04CandidateAuditEntry, ...],
    selected_entry: T04CandidateAuditEntry,
    selected_summary: dict[str, Any],
) -> tuple[T04CandidateAuditEntry, ...]:
    updated: list[T04CandidateAuditEntry] = []
    matched = False
    for entry in entries:
        if entry.candidate_id == selected_entry.candidate_id:
            matched = True
            updated.append(
                replace(
                    selected_entry,
                    selection_status="selected",
                    decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
                    candidate_summary=dict(selected_summary),
                    evidence_source=str(selected_summary.get("evidence_source") or entry.evidence_source),
                    position_source=str(selected_summary.get("position_source") or entry.position_source),
                    review_state="STEP4_REVIEW",
                    review_reasons=tuple(selected_summary.get("review_reasons") or entry.review_reasons),
                )
            )
        else:
            updated.append(entry)
    if not matched:
        updated.append(
            replace(
                selected_entry,
                selection_status="selected",
                decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
                candidate_summary=dict(selected_summary),
                evidence_source=str(selected_summary.get("evidence_source") or selected_entry.evidence_source),
                position_source=str(selected_summary.get("position_source") or selected_entry.position_source),
                review_state="STEP4_REVIEW",
                review_reasons=tuple(selected_summary.get("review_reasons") or selected_entry.review_reasons),
            )
        )
    return tuple(updated)


def _bind_strong_rcsd_to_surface(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    aggregate = _strong_aggregated_unit(event_unit.positive_rcsd_audit)
    if aggregate is None:
        return None, None

    required_node = str(aggregate.get("required_node_id") or "").strip()
    primary_node = str(aggregate.get("primary_node_id") or "").strip() or None
    road_ids = tuple(str(item) for item in aggregate.get("road_ids") or () if str(item))
    node_ids = tuple(str(item) for item in aggregate.get("node_ids") or () if str(item))
    selected_roads = tuple(str(item) for item in event_unit.positive_rcsd_audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = tuple(str(item) for item in event_unit.positive_rcsd_audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = tuple(str(item) for item in event_unit.positive_rcsd_audit.get("first_hit_rcsdroad_ids") or ())
    required_geometry = _point_geometry(case_result, required_node)
    if required_geometry is None:
        return None, None
    reference_point, reference_detail = _road_surface_fork_reference_point(case_result, event_unit)
    if reference_point is None:
        reference_point = event_unit.fact_reference_point if isinstance(event_unit.fact_reference_point, Point) else None
    review_point = reference_point if reference_point is not None else event_unit.review_materialized_point

    support_level = str(aggregate.get("support_level") or "primary_support")
    consistency_level = str(aggregate.get("consistency_level") or "A")
    bind_detail = {
        "action": "bound_forward_rcsd_to_road_surface_fork",
        "aggregated_rcsd_unit_id": str(aggregate.get("unit_id") or ""),
        "required_rcsd_node": required_node,
        "rcsd_decision_reason": str(aggregate.get("decision_reason") or ""),
        "reference_point": dict(reference_detail),
    }
    summary = _build_surface_summary(
        T04CandidateAuditEntry(
            candidate_id=str(event_unit.selected_candidate_summary.get("candidate_id") or ""),
            pool_rank=int(event_unit.selected_candidate_summary.get("pool_rank") or 0),
            priority_score=int(event_unit.selected_candidate_summary.get("priority_score") or 0),
            selection_status="selected",
            decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
            candidate_summary=dict(event_unit.selected_candidate_summary),
            review_state=event_unit.review_state,
            review_reasons=event_unit.all_review_reasons(),
            evidence_source=event_unit.evidence_source,
            position_source=event_unit.position_source,
            reverse_tip_used=False,
            rcsd_consistency_result=event_unit.rcsd_consistency_result,
            positive_rcsd_support_level=support_level,
            positive_rcsd_consistency_level=consistency_level,
            required_rcsd_node=required_node,
            candidate_region_geometry=event_unit.selected_evidence_region_geometry,
            fact_reference_point=reference_point,
            review_materialized_point=review_point,
            localized_evidence_core_geometry=event_unit.localized_evidence_core_geometry,
            selected_component_union_geometry=event_unit.selected_component_union_geometry,
        ),
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        bind_detail=bind_detail,
    )
    if isinstance(reference_point, Point):
        summary.update(
            {
                **reference_detail,
                "point_signature": f"road_surface_fork:{float(reference_point.x):.3f}:{float(reference_point.y):.3f}",
                "reference_distance_to_origin_m": reference_detail.get("road_surface_fork_reference_distance_m"),
            }
        )
    summary.update(
        {
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_forward_rcsd_present",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": required_node,
            "required_rcsd_node_source": "road_surface_fork_forward_rcsd",
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "rcsd_selection_mode": "road_surface_fork_forward_rcsd_binding",
            "rcsd_decision_reason": str(aggregate.get("decision_reason") or ""),
        }
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "road_surface_fork_binding": bind_detail,
            "road_surface_fork_reference_point": dict(reference_detail),
            "rcsd_decision_reason": str(aggregate.get("decision_reason") or ""),
            "required_rcsd_node_source": "road_surface_fork_forward_rcsd",
        }
    )
    review_reasons = _dedupe([*event_unit.all_review_reasons(), ROAD_SURFACE_FORK_BINDING_REASON])
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_strong_consistent",
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
        required_rcsd_node_geometry=required_geometry,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=str(event_unit.positive_rcsd_audit.get("local_rcsd_unit_id") or aggregate.get("unit_id") or ""),
        local_rcsd_unit_kind="node_centric",
        aggregated_rcsd_unit_id=str(aggregate.get("unit_id") or event_unit.positive_rcsd_audit.get("aggregated_rcsd_unit_id") or ""),
        aggregated_rcsd_unit_ids=tuple(str(item) for item in event_unit.positive_rcsd_audit.get("aggregated_rcsd_unit_ids") or ()),
        fact_reference_point=reference_point,
        review_materialized_point=review_point,
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_forward_rcsd_present",
        rcsd_selection_mode="road_surface_fork_forward_rcsd_binding",
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=required_node,
        required_rcsd_node_source="road_surface_fork_forward_rcsd",
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=str(summary.get("candidate_id") or ""),
        post_required_rcsd_node=required_node,
        resolution_reason=ROAD_SURFACE_FORK_BINDING_REASON,
    )
    return updated, bind_detail


def _invalid_divstrip_removed(event_unit: T04EventUnitResult) -> bool:
    return any(
        entry.candidate_summary.get("degraded_reverse_divstrip_far_from_throat") is True
        for entry in event_unit.candidate_audit_entries
    )


def _has_partial_rcsd_signal(event_unit: T04EventUnitResult) -> bool:
    return any(
        "positive_rcsd_partial_consistent" in str(reason or "")
        for reason in event_unit.all_review_reasons()
    )


def _recoverable_surface_candidate(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    if event_unit.selected_evidence_state != "none":
        return None
    if not _invalid_divstrip_removed(event_unit):
        return None
    candidates: list[tuple[tuple[float, int, str], T04CandidateAuditEntry]] = []
    for entry in event_unit.candidate_audit_entries:
        summary = entry.candidate_summary
        if str(summary.get("upper_evidence_kind") or "") != "structure_face":
            continue
        scope = str(summary.get("candidate_scope") or "")
        if scope != ROAD_SURFACE_FORK_SCOPE:
            continue
        throat_ratio = _as_float(summary.get("throat_overlap_ratio")) or 0.0
        reference_distance = _as_float(summary.get("reference_distance_to_origin_m")) or 0.0
        if throat_ratio < SURFACE_RECOVERY_MIN_THROAT_RATIO:
            continue
        if reference_distance > SURFACE_RECOVERY_MAX_REFERENCE_DISTANCE_M:
            continue
        if entry.candidate_region_geometry is None or entry.candidate_region_geometry.is_empty:
            continue
        axis_position = _as_float(summary.get("axis_position_m")) or 0.0
        candidates.append(((reference_distance, entry.pool_rank, f"{axis_position:.3f}:{entry.candidate_id}"), entry))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else None


def _structure_base_entry(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    for entry in event_unit.candidate_audit_entries:
        if str(entry.candidate_summary.get("upper_evidence_kind") or "") == "structure_face":
            return entry
    return None


def _derived_road_surface_geometry(event_unit: T04EventUnitResult) -> BaseGeometry | None:
    base_geometry = event_unit.pair_local_middle_geometry or event_unit.pair_local_structure_face_geometry
    if base_geometry is None or base_geometry.is_empty:
        return None
    surface_geometry = base_geometry
    throat_core = event_unit.pair_local_throat_core_geometry
    if throat_core is not None and not throat_core.is_empty:
        surface_geometry = surface_geometry.difference(
            throat_core.buffer(SURFACE_RECOVERY_THROAT_EXCLUSION_M, join_style=2)
        )
    surface_geometry = _largest_polygon_component(surface_geometry)
    if surface_geometry is None or surface_geometry.is_empty:
        surface_geometry = _largest_polygon_component(base_geometry)
    return surface_geometry if surface_geometry is not None and not surface_geometry.is_empty else None


def _recovered_surface_entry_from_domain(
    event_unit: T04EventUnitResult,
) -> T04CandidateAuditEntry | None:
    if event_unit.selected_evidence_state != "none":
        return None
    if not _invalid_divstrip_removed(event_unit):
        return None
    base_entry = _structure_base_entry(event_unit)
    if base_entry is None:
        return None
    surface_geometry = _derived_road_surface_geometry(event_unit)
    if surface_geometry is None:
        return None

    reference_point = surface_geometry.representative_point()
    base_summary = dict(base_entry.candidate_summary)
    event_unit_id = event_unit.spec.event_unit_id
    upper_id = str(
        base_summary.get("upper_evidence_object_id")
        or event_unit.pair_local_summary.get("region_id")
        or "pair_local_structure_face"
    )
    axis_signature = str(base_summary.get("axis_signature") or base_summary.get("axis_position_basis") or "")
    axis_position = _as_float(base_summary.get("axis_position_m"))
    point_signature = (
        f"{axis_signature}:surface:{axis_position:.1f}"
        if axis_signature and axis_position is not None
        else f"surface:{round(float(reference_point.x), 3)}:{round(float(reference_point.y), 3)}"
    )
    candidate_id = f"{event_unit_id}:structure:road_surface_fork:recovered"
    bind_detail = {
        "action": "recovered_road_surface_fork_from_pair_local_surface",
        "source_candidate_id": base_entry.candidate_id,
        "source_candidate_scope": str(base_summary.get("candidate_scope") or ""),
        "source_node_fallback_only": bool(base_summary.get("node_fallback_only")),
        "relaxed_rcsd_dropped": _entry_uses_relaxed_rcsd(base_entry),
    }
    summary = dict(base_summary)
    summary.update(
        {
            "candidate_id": candidate_id,
            "source_mode": "pair_local_structure_mode",
            "upper_evidence_kind": "structure_face",
            "upper_evidence_object_id": upper_id,
            "candidate_scope": ROAD_SURFACE_FORK_SCOPE,
            "local_region_id": f"{event_unit_id}:structure_face:{upper_id}:road_surface_fork_recovered",
            "ownership_signature": f"structure_face:{upper_id}:{event_unit_id}:road_surface_fork_recovered",
            "point_signature": point_signature,
            "axis_signature": axis_signature,
            "axis_position_basis": str(base_summary.get("axis_position_basis") or axis_signature),
            "axis_position_m": axis_position,
            "reference_distance_to_origin_m": None,
            "node_fallback_only": False,
            "primary_eligible": True,
            "selected_after_reselection": False,
            "review_state": "STEP4_REVIEW",
            "review_reasons": list(
                _dedupe(
                    [
                        *_clean_surface_review_reasons(base_entry.review_reasons),
                        ROAD_SURFACE_FORK_BINDING_REASON,
                    ]
                )
            ),
            "evidence_source": "road_surface_fork",
            "position_source": "road_surface_fork",
            "reverse_tip_used": False,
            "rcsd_consistency_result": "road_surface_fork_without_bound_target_rcsd",
            "positive_rcsd_present": False,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "rcsd_selection_mode": "road_surface_fork_without_bound_target_rcsd",
            "rcsd_decision_reason": "road_surface_fork_without_bound_target_rcsd",
            "selected_evidence_state": "found",
            "decision_reason": ROAD_SURFACE_FORK_BINDING_REASON,
            "road_surface_fork_binding": bind_detail,
        }
    )
    return replace(
        base_entry,
        candidate_id=candidate_id,
        pool_rank=max(1, int(base_entry.pool_rank or 1)),
        priority_score=max(1000, int(base_entry.priority_score or 0)),
        selection_status="selected",
        decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
        candidate_summary=summary,
        review_state="STEP4_REVIEW",
        review_reasons=tuple(summary["review_reasons"]),
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        reverse_tip_used=False,
        rcsd_consistency_result="road_surface_fork_without_bound_target_rcsd",
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        candidate_region_geometry=surface_geometry,
        fact_reference_point=reference_point,
        review_materialized_point=reference_point,
        localized_evidence_core_geometry=surface_geometry,
        selected_component_union_geometry=surface_geometry,
        selected_evidence_region_geometry=surface_geometry,
        first_hit_rcsdroad_ids=(),
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason="road_surface_fork_without_bound_target_rcsd",
        rcsd_selection_mode="road_surface_fork_without_bound_target_rcsd",
        required_rcsd_node_source=None,
        event_axis_branch_id=base_entry.event_axis_branch_id or event_unit.event_axis_branch_id,
        event_chosen_s_m=axis_position,
        positive_rcsd_audit={
            **dict(base_entry.positive_rcsd_audit),
            "road_surface_fork_binding": bind_detail,
            "road_surface_fork_without_bound_target_rcsd": True,
            "rcsd_decision_reason": "road_surface_fork_without_bound_target_rcsd",
        },
        pair_local_rcsd_scope_geometry=None,
        first_hit_rcsd_road_geometry=None,
        local_rcsd_unit_geometry=None,
        positive_rcsd_geometry=None,
        positive_rcsd_road_geometry=None,
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
    )


def _recover_surface_from_candidate(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    entry = _recoverable_surface_candidate(event_unit)
    if entry is None:
        entry = _recovered_surface_entry_from_domain(event_unit)
    if entry is None:
        return None, None
    existing_detail = entry.candidate_summary.get("road_surface_fork_binding")
    relaxed_rcsd = _entry_uses_relaxed_rcsd(entry) or (
        isinstance(existing_detail, dict)
        and bool(existing_detail.get("relaxed_rcsd_dropped"))
    )
    bind_detail = (
        dict(existing_detail)
        if isinstance(existing_detail, dict)
        else {
            "action": "recovered_road_surface_fork_after_invalid_divstrip",
            "candidate_id": entry.candidate_id,
            "relaxed_rcsd_dropped": relaxed_rcsd,
        }
    )
    review_reasons = _dedupe(
        [
            *_clean_surface_review_reasons(entry.review_reasons),
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = _build_surface_summary(
        entry,
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        bind_detail=bind_detail,
    )
    summary["review_reasons"] = list(review_reasons)
    summary["rcsd_decision_reason"] = (
        "road_surface_fork_without_bound_target_rcsd"
        if relaxed_rcsd
        else str(summary.get("rcsd_decision_reason") or "")
    )
    summary["positive_rcsd_present"] = False if relaxed_rcsd else bool(entry.positive_rcsd_present)
    summary["positive_rcsd_support_level"] = "no_support" if relaxed_rcsd else entry.positive_rcsd_support_level
    summary["positive_rcsd_consistency_level"] = "C" if relaxed_rcsd else entry.positive_rcsd_consistency_level
    summary["required_rcsd_node"] = None if relaxed_rcsd else entry.required_rcsd_node
    summary["required_rcsd_node_source"] = None if relaxed_rcsd else entry.required_rcsd_node_source

    updated_entries = _candidate_entries_with_selection(event_unit.candidate_audit_entries, entry, summary)
    updated_audit = dict(entry.positive_rcsd_audit)
    updated_audit["road_surface_fork_binding"] = bind_detail
    if relaxed_rcsd:
        updated_audit["road_surface_fork_without_bound_target_rcsd"] = True
        updated_audit["rcsd_decision_reason"] = "road_surface_fork_without_bound_target_rcsd"

    seed_geometry = entry.fact_reference_point or entry.review_materialized_point
    surface_geometry = _seed_component_geometry(
        entry.selected_evidence_region_geometry or entry.candidate_region_geometry,
        seed_geometry,
    )
    component_geometry = _seed_component_geometry(
        entry.selected_component_union_geometry or surface_geometry,
        seed_geometry,
    )
    core_geometry = _seed_component_geometry(
        entry.localized_evidence_core_geometry or surface_geometry,
        seed_geometry,
    )

    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        reverse_tip_used=False,
        rcsd_consistency_result=(
            "road_surface_fork_without_bound_target_rcsd"
            if relaxed_rcsd
            else entry.rcsd_consistency_result
        ),
        selected_component_union_geometry=component_geometry,
        localized_evidence_core_geometry=core_geometry,
        selected_evidence_region_geometry=surface_geometry,
        selected_candidate_region=entry.selected_candidate_region or event_unit.selected_candidate_region,
        fact_reference_point=entry.fact_reference_point or event_unit.fact_reference_point,
        review_materialized_point=entry.review_materialized_point or entry.fact_reference_point or event_unit.review_materialized_point,
        selected_branch_ids=entry.selected_branch_ids,
        selected_event_branch_ids=entry.selected_event_branch_ids,
        selected_component_ids=entry.selected_component_ids,
        first_hit_rcsdroad_ids=() if relaxed_rcsd else entry.first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=() if relaxed_rcsd else entry.selected_rcsdroad_ids,
        selected_rcsdnode_ids=() if relaxed_rcsd else entry.selected_rcsdnode_ids,
        primary_main_rc_node_id=None if relaxed_rcsd else entry.primary_main_rc_node_id,
        local_rcsd_unit_id=None if relaxed_rcsd else entry.local_rcsd_unit_id,
        local_rcsd_unit_kind=None if relaxed_rcsd else entry.local_rcsd_unit_kind,
        aggregated_rcsd_unit_id=None if relaxed_rcsd else entry.aggregated_rcsd_unit_id,
        aggregated_rcsd_unit_ids=() if relaxed_rcsd else entry.aggregated_rcsd_unit_ids,
        positive_rcsd_present=False if relaxed_rcsd else entry.positive_rcsd_present,
        positive_rcsd_present_reason=(
            "road_surface_fork_without_bound_target_rcsd"
            if relaxed_rcsd
            else entry.positive_rcsd_present_reason
        ),
        rcsd_selection_mode=(
            "road_surface_fork_without_bound_target_rcsd"
            if relaxed_rcsd
            else entry.rcsd_selection_mode
        ),
        positive_rcsd_support_level="no_support" if relaxed_rcsd else entry.positive_rcsd_support_level,
        positive_rcsd_consistency_level="C" if relaxed_rcsd else entry.positive_rcsd_consistency_level,
        required_rcsd_node=None if relaxed_rcsd else entry.required_rcsd_node,
        required_rcsd_node_source=None if relaxed_rcsd else entry.required_rcsd_node_source,
        event_axis_branch_id=entry.event_axis_branch_id or event_unit.event_axis_branch_id,
        event_chosen_s_m=entry.event_chosen_s_m or _as_float(summary.get("axis_position_m")),
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        extra_review_notes=(),
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        resolution_reason=ROAD_SURFACE_FORK_BINDING_REASON,
    )
    promoted, promoted_detail = _bind_strong_rcsd_to_surface(case_result, updated)
    if promoted is not None:
        return promoted, promoted_detail
    allow_exact_primary_fallback = bool(
        bind_detail.get("source_node_fallback_only")
        or (
            isinstance(existing_detail, dict)
            and bool(existing_detail.get("source_node_fallback_only"))
        )
    )
    if relaxed_rcsd or allow_exact_primary_fallback:
        promoted, promoted_detail = _promote_relaxed_primary_rcsd_binding(
            case_result,
            updated,
            entry,
            bind_detail,
            allow_exact_primary_fallback=allow_exact_primary_fallback,
        )
        if promoted is not None:
            return promoted, promoted_detail
    return updated, bind_detail


def _promote_relaxed_primary_rcsd_binding(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    entry: T04CandidateAuditEntry,
    bind_detail: dict[str, Any],
    *,
    allow_exact_primary_fallback: bool = False,
    prefer_required_node: bool = False,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    audit = dict(entry.positive_rcsd_audit)
    aggregate = _relaxed_primary_aggregate(
        audit,
        allow_exact_primary_fallback=allow_exact_primary_fallback,
    )
    if aggregate is None:
        return None, None

    primary_node = str(aggregate.get("primary_node_id") or "").strip()
    aggregate_required_node = str(aggregate.get("required_node_id") or "").strip() or primary_node
    bound_node = aggregate_required_node if prefer_required_node else primary_node
    required_geometry = _point_geometry(case_result, bound_node)
    representative_geometry = getattr(event_unit.unit_context.representative_node, "geometry", None)
    if not isinstance(required_geometry, Point) or not isinstance(representative_geometry, Point):
        return None, None
    representative_distance = float(required_geometry.distance(representative_geometry))
    if representative_distance > RELAXED_PRIMARY_MAX_REPRESENTATIVE_DISTANCE_M:
        return None, None

    road_ids = _aggregate_ids(aggregate, "road_ids")
    node_ids = _aggregate_ids(aggregate, "node_ids")
    selected_roads = _dedupe(audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = _dedupe(audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = _first_hit_ids(audit)
    support_level = str(aggregate.get("support_level") or "secondary_support")
    consistency_level = str(aggregate.get("consistency_level") or "B")
    decision_reason = str(aggregate.get("decision_reason") or "")
    if allow_exact_primary_fallback and decision_reason == "role_mapping_exact_aggregated":
        consistency_level = "B"
        if support_level == "primary_support":
            support_level = "secondary_support"
    aggregate_id = str(aggregate.get("unit_id") or "").strip()
    local_unit_id = _local_unit_id_for_node(aggregate, bound_node)
    promoted_detail = dict(bind_detail)
    promoted_detail.update(
        {
            "action": str(
                bind_detail.get("promoted_action") or "recovered_road_surface_fork_with_relaxed_primary_rcsd"
            ),
            "relaxed_rcsd_dropped": False,
            "relaxed_primary_rcsd_promoted": True,
            "aggregated_rcsd_unit_id": aggregate_id,
            "required_rcsd_node": bound_node,
            "primary_node_id": primary_node,
            "original_required_node_id": aggregate_required_node or None,
            "required_node_source": RELAXED_PRIMARY_NODE_SOURCE,
            "bound_node_strategy": "aggregate_required_node" if prefer_required_node else "aggregate_primary_node",
            "representative_distance_m": round(representative_distance, 3),
            "rcsd_decision_reason": decision_reason,
        }
    )
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            "positive_rcsd_partial_consistent",
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = dict(event_unit.selected_candidate_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": promoted_detail,
            "rcsd_consistency_result": "positive_rcsd_partial_consistent",
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_relaxed_primary_rcsd_present",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": bound_node,
            "required_rcsd_node_source": RELAXED_PRIMARY_NODE_SOURCE,
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "local_rcsd_unit_id": local_unit_id,
            "local_rcsd_unit_kind": "node_centric",
            "aggregated_rcsd_unit_id": aggregate_id,
            "aggregated_rcsd_unit_ids": list(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            "primary_main_rc_node": primary_node,
            "primary_main_rc_node_id": primary_node,
            "rcsd_selection_mode": RELAXED_PRIMARY_BINDING_MODE,
            "rcsd_decision_reason": decision_reason,
        }
    )
    promoted_entry = replace(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_partial_consistent",
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=bound_node,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric",
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_relaxed_primary_rcsd_present",
        rcsd_selection_mode=RELAXED_PRIMARY_BINDING_MODE,
        required_rcsd_node_source=RELAXED_PRIMARY_NODE_SOURCE,
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=required_geometry,
        required_rcsd_node_geometry=required_geometry,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        promoted_entry,
        summary,
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": promoted_detail,
            "road_surface_fork_relaxed_primary_rcsd_binding": promoted_detail,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_relaxed_primary_rcsd_present",
            "required_rcsd_node_source": RELAXED_PRIMARY_NODE_SOURCE,
            "required_rcsd_node": bound_node,
            "rcsd_selection_mode": RELAXED_PRIMARY_BINDING_MODE,
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated = replace(
        event_unit,
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_partial_consistent",
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=required_geometry,
        required_rcsd_node_geometry=required_geometry,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric",
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_relaxed_primary_rcsd_present",
        rcsd_selection_mode=RELAXED_PRIMARY_BINDING_MODE,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=bound_node,
        required_rcsd_node_source=RELAXED_PRIMARY_NODE_SOURCE,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        post_required_rcsd_node=bound_node,
    )
    return updated, promoted_detail


def _promote_selected_surface_rcsd_junction_window(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    entry = _selected_surface_entry(event_unit)
    if entry is None:
        return None, None
    audit = dict(event_unit.positive_rcsd_audit)
    aggregate = _junction_window_aggregate(audit)
    if aggregate is None:
        return None, None
    selected_summary = _selected_surface_summary(event_unit)
    first_hit = _first_hit_ids(audit)
    if (
        str(aggregate.get("consistency_level") or "").strip() == "A"
        and len(first_hit) < 2
        and not _weak_structure_surface_window_candidate(selected_summary)
    ):
        return None, None
    primary_node = str(aggregate.get("primary_node_id") or "").strip()
    required_node = str(aggregate.get("required_node_id") or "").strip() or primary_node
    if not required_node:
        return None, None
    required_geometry = _point_geometry(case_result, required_node)
    if required_geometry is None:
        return None, None

    road_ids = _aggregate_ids(aggregate, "road_ids")
    node_ids = _aggregate_ids(aggregate, "node_ids")
    selected_roads = _dedupe(audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = _dedupe(audit.get("published_rcsdnode_ids") or node_ids)
    aggregate_id = str(aggregate.get("unit_id") or audit.get("aggregated_rcsd_unit_id") or "").strip()
    if _same_case_rcsd_claim_conflict(
        case_result,
        event_unit,
        aggregate_id=aggregate_id,
        required_node=required_node,
        primary_node=primary_node,
        selected_roads=selected_roads,
        selected_nodes=selected_nodes,
    ):
        return None, None
    support_level = str(aggregate.get("support_level") or event_unit.positive_rcsd_support_level or "secondary_support")
    consistency_level = str(aggregate.get("consistency_level") or event_unit.positive_rcsd_consistency_level or "B")
    decision_reason = str(aggregate.get("decision_reason") or audit.get("rcsd_decision_reason") or "")
    local_unit_id = _local_unit_id_for_node(aggregate, required_node) or _local_unit_id_for_node(aggregate, primary_node)
    detail = {
        "action": "bound_selected_surface_to_rcsd_junction_window",
        "candidate_id": entry.candidate_id,
        "aggregated_rcsd_unit_id": aggregate_id,
        "required_rcsd_node": required_node,
        "primary_node_id": primary_node,
        "selected_rcsdroad_ids": list(selected_roads),
        "selected_rcsdnode_ids": list(selected_nodes),
        "first_hit_rcsdroad_ids": list(first_hit),
        "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        "rcsd_decision_reason": decision_reason,
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            "positive_rcsd_partial_consistent",
            RCSD_JUNCTION_WINDOW_REASON,
        ]
    )
    summary = dict(selected_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "selected_evidence_state": "found",
            "evidence_source": RCSD_JUNCTION_WINDOW_SOURCE,
            "position_source": RCSD_JUNCTION_WINDOW_POSITION_SOURCE,
            "source_mode": RCSD_JUNCTION_WINDOW_SOURCE,
            "road_surface_fork_binding": detail,
            "rcsd_consistency_result": RCSD_JUNCTION_WINDOW_SOURCE,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "rcsd_junction_window_forward_rcsd_present",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": required_node,
            "required_rcsd_node_source": RCSD_JUNCTION_WINDOW_SOURCE,
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "local_rcsd_unit_id": local_unit_id,
            "local_rcsd_unit_kind": "node_centric" if local_unit_id else None,
            "aggregated_rcsd_unit_id": aggregate_id,
            "aggregated_rcsd_unit_ids": list(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            "primary_main_rc_node": primary_node,
            "primary_main_rc_node_id": primary_node,
            "rcsd_selection_mode": RCSD_JUNCTION_WINDOW_SOURCE,
            "rcsd_decision_reason": decision_reason,
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        }
    )
    updated_audit = dict(audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": detail,
            "rcsd_junction_window": detail,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "rcsd_junction_window_forward_rcsd_present",
            "required_rcsd_node": required_node,
            "required_rcsd_node_source": RCSD_JUNCTION_WINDOW_SOURCE,
            "rcsd_selection_mode": RCSD_JUNCTION_WINDOW_SOURCE,
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated_entry = replace(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=RCSD_JUNCTION_WINDOW_SOURCE,
        position_source=RCSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result=RCSD_JUNCTION_WINDOW_SOURCE,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=required_node,
        fact_reference_point=required_geometry,
        review_materialized_point=required_geometry,
        localized_evidence_core_geometry=None,
        selected_component_union_geometry=None,
        selected_evidence_region_geometry=None,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric" if local_unit_id else None,
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="rcsd_junction_window_forward_rcsd_present",
        rcsd_selection_mode=RCSD_JUNCTION_WINDOW_SOURCE,
        required_rcsd_node_source=RCSD_JUNCTION_WINDOW_SOURCE,
        positive_rcsd_audit=updated_audit,
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
        required_rcsd_node_geometry=required_geometry,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        updated_entry,
        summary,
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=RCSD_JUNCTION_WINDOW_SOURCE,
        position_source=RCSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result=RCSD_JUNCTION_WINDOW_SOURCE,
        selected_component_union_geometry=None,
        localized_evidence_core_geometry=None,
        selected_evidence_region_geometry=None,
        fact_reference_point=required_geometry,
        review_materialized_point=required_geometry,
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
        required_rcsd_node_geometry=required_geometry,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric" if local_unit_id else None,
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="rcsd_junction_window_forward_rcsd_present",
        rcsd_selection_mode=RCSD_JUNCTION_WINDOW_SOURCE,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=required_node,
        required_rcsd_node_source=RCSD_JUNCTION_WINDOW_SOURCE,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        post_required_rcsd_node=required_node,
        resolution_reason=RCSD_JUNCTION_WINDOW_REASON,
    )
    return updated, detail


def _selected_surface_entry(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    if event_unit.selected_evidence_state == "none":
        return None
    if event_unit.evidence_source != "road_surface_fork":
        return None
    selected_id = str(
        event_unit.selected_candidate_summary.get("candidate_id")
        or event_unit.selected_evidence_summary.get("candidate_id")
        or ""
    ).strip()
    if not selected_id:
        return None
    for entry in event_unit.candidate_audit_entries:
        if entry.candidate_id == selected_id:
            return entry
    return None


def _promote_selected_surface_partial_rcsd(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    if not _has_partial_rcsd_signal(event_unit):
        return None, None
    entry = _selected_surface_entry(event_unit)
    if entry is None:
        return None, None
    bind_detail = {
        "action": "bound_selected_road_surface_fork_with_relaxed_required_rcsd",
        "promoted_action": "bound_selected_road_surface_fork_with_relaxed_required_rcsd",
        "candidate_id": entry.candidate_id,
        "candidate_scope": str(entry.candidate_summary.get("candidate_scope") or ""),
        "selected_surface_existing": True,
        "relaxed_rcsd_dropped": False,
    }
    promoted, promoted_detail = _promote_relaxed_primary_rcsd_binding(
        case_result,
        event_unit,
        entry,
        bind_detail,
        prefer_required_node=True,
    )
    if promoted is not None:
        return promoted, promoted_detail

    audit = dict(entry.positive_rcsd_audit)
    aggregate = _relaxed_primary_aggregate(audit)
    if aggregate is None:
        return None, None
    primary_node = str(aggregate.get("primary_node_id") or "").strip() or None
    road_ids = _aggregate_ids(aggregate, "road_ids")
    node_ids = _aggregate_ids(aggregate, "node_ids")
    selected_roads = _dedupe(audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = _dedupe(audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = _first_hit_ids(audit)
    support_level = str(aggregate.get("support_level") or "secondary_support")
    consistency_level = str(aggregate.get("consistency_level") or "B")
    decision_reason = str(aggregate.get("decision_reason") or "")
    aggregate_id = str(aggregate.get("unit_id") or "").strip()
    local_unit_id = _local_unit_id_for_node(aggregate, primary_node or "")
    support_detail = dict(bind_detail)
    support_detail.update(
        {
            "action": "bound_selected_road_surface_fork_partial_rcsd_support_only",
            "partial_rcsd_support_only": True,
            "aggregated_rcsd_unit_id": aggregate_id,
            "primary_node_id": primary_node,
            "required_rcsd_node": None,
            "rcsd_decision_reason": decision_reason,
        }
    )
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            "positive_rcsd_partial_consistent",
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = dict(event_unit.selected_candidate_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": support_detail,
            "rcsd_consistency_result": "positive_rcsd_partial_consistent",
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_partial_rcsd_support_only",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "local_rcsd_unit_id": local_unit_id,
            "local_rcsd_unit_kind": "node_centric" if local_unit_id else None,
            "aggregated_rcsd_unit_id": aggregate_id,
            "aggregated_rcsd_unit_ids": list(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            "primary_main_rc_node": primary_node,
            "primary_main_rc_node_id": primary_node,
            "rcsd_selection_mode": "road_surface_fork_partial_rcsd_support_only",
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        replace(
            entry,
            candidate_summary=dict(summary),
            review_state="STEP4_REVIEW",
            review_reasons=review_reasons,
            rcsd_consistency_result="positive_rcsd_partial_consistent",
            positive_rcsd_support_level=support_level,
            positive_rcsd_consistency_level=consistency_level,
            required_rcsd_node=None,
            first_hit_rcsdroad_ids=first_hit,
            selected_rcsdroad_ids=selected_roads,
            selected_rcsdnode_ids=selected_nodes,
            primary_main_rc_node_id=primary_node,
            local_rcsd_unit_id=local_unit_id,
            local_rcsd_unit_kind="node_centric" if local_unit_id else None,
            aggregated_rcsd_unit_id=aggregate_id,
            aggregated_rcsd_unit_ids=tuple(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            positive_rcsd_present=True,
            positive_rcsd_present_reason="road_surface_fork_partial_rcsd_support_only",
            rcsd_selection_mode="road_surface_fork_partial_rcsd_support_only",
            required_rcsd_node_source=None,
            pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
            first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
            local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
            positive_rcsd_geometry=_union_geometries(
                [
                    _road_geometries(case_result, selected_roads),
                    _node_geometries(case_result, selected_nodes),
                ]
            ),
            positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
            positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
            primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
            required_rcsd_node_geometry=None,
        ),
        summary,
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": support_detail,
            "road_surface_fork_partial_rcsd_support_only": support_detail,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_partial_rcsd_support_only",
            "required_rcsd_node_source": None,
            "required_rcsd_node": None,
            "rcsd_selection_mode": "road_surface_fork_partial_rcsd_support_only",
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated = replace(
        event_unit,
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_partial_consistent",
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
        required_rcsd_node_geometry=None,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric" if local_unit_id else None,
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_partial_rcsd_support_only",
        rcsd_selection_mode="road_surface_fork_partial_rcsd_support_only",
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
    )
    return updated, support_detail


def _stable_structure_only_surface_summary(summary: dict[str, Any]) -> bool:
    if str(summary.get("candidate_scope") or "") != ROAD_SURFACE_FORK_SCOPE:
        return False
    if not bool(summary.get("primary_eligible")):
        return False
    if bool(summary.get("node_fallback_only")):
        return False
    axis_position = abs(_as_float(summary.get("axis_position_m")) or 0.0)
    if axis_position < STRUCTURE_ONLY_SURFACE_MIN_AXIS_POSITION_M:
        return False
    throat_ratio = _as_float(summary.get("throat_overlap_ratio")) or 0.0
    pair_middle_ratio = _as_float(summary.get("pair_middle_overlap_ratio")) or 0.0
    return (
        throat_ratio >= SURFACE_RECOVERY_MIN_THROAT_RATIO
        and pair_middle_ratio >= STRUCTURE_ONLY_SURFACE_MIN_PAIR_MIDDLE_RATIO
    )


def _retain_structure_only_surface_candidate(
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    if event_unit.positive_rcsd_present:
        return None, None
    if _has_partial_rcsd_signal(event_unit):
        return None, None
    selected_summary = dict(event_unit.selected_evidence_summary or event_unit.selected_candidate_summary or {})
    if selected_summary.get("road_surface_fork_binding"):
        return None, None
    if not _stable_structure_only_surface_summary(selected_summary):
        return None, None
    entry = _selected_surface_entry(event_unit)
    if entry is None:
        return None, None

    use_swsd_window = _weak_structure_surface_window_candidate(selected_summary)
    evidence_source = SWSD_JUNCTION_WINDOW_SOURCE if use_swsd_window else "road_surface_fork"
    position_source = (
        SWSD_JUNCTION_WINDOW_POSITION_SOURCE
        if use_swsd_window
        else str(event_unit.position_source or "road_surface_fork")
    )
    rcsd_mode = (
        "swsd_junction_window_no_rcsd"
        if use_swsd_window
        else "road_surface_fork_structure_only_no_rcsd"
    )
    reason = SWSD_JUNCTION_WINDOW_REASON if use_swsd_window else STRUCTURE_ONLY_SURFACE_REASON
    detail = {
        "action": (
            "kept_swsd_junction_window_no_rcsd"
            if use_swsd_window
            else "kept_structure_only_road_surface_fork"
        ),
        "reason": reason,
        "candidate_id": entry.candidate_id,
        "axis_position_m": _as_float(selected_summary.get("axis_position_m")),
        "pair_middle_overlap_ratio": _as_float(selected_summary.get("pair_middle_overlap_ratio")),
        "throat_overlap_ratio": _as_float(selected_summary.get("throat_overlap_ratio")),
        "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M if use_swsd_window else None,
    }
    review_reasons = _dedupe([*event_unit.all_review_reasons(), reason])
    summary = dict(selected_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": detail,
            "selected_evidence_state": "found",
            "evidence_source": evidence_source,
            "position_source": position_source,
            "source_mode": evidence_source,
            "rcsd_consistency_result": rcsd_mode,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
            "decision_reason": reason,
            "selection_status": "selected",
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M if use_swsd_window else None,
        }
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        replace(
            entry,
            candidate_summary=dict(summary),
            review_state="STEP4_REVIEW",
            review_reasons=review_reasons,
            evidence_source=evidence_source,
            position_source=position_source,
            rcsd_consistency_result=rcsd_mode,
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            required_rcsd_node=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason=rcsd_mode,
            rcsd_selection_mode=rcsd_mode,
            required_rcsd_node_source=None,
            localized_evidence_core_geometry=None if use_swsd_window else entry.localized_evidence_core_geometry,
            selected_component_union_geometry=None if use_swsd_window else entry.selected_component_union_geometry,
            selected_evidence_region_geometry=None if use_swsd_window else entry.selected_evidence_region_geometry,
        ),
        summary,
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "road_surface_fork_binding": detail,
            "road_surface_fork_structure_only_no_rcsd": True,
            "swsd_junction_window_no_rcsd": use_swsd_window,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
        }
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=evidence_source,
        position_source=position_source,
        rcsd_consistency_result=rcsd_mode,
        selected_component_union_geometry=None if use_swsd_window else event_unit.selected_component_union_geometry,
        localized_evidence_core_geometry=None if use_swsd_window else event_unit.localized_evidence_core_geometry,
        selected_evidence_region_geometry=None if use_swsd_window else event_unit.selected_evidence_region_geometry,
        positive_rcsd_present=False,
        positive_rcsd_present_reason=rcsd_mode,
        rcsd_selection_mode=rcsd_mode,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        resolution_reason=reason,
    )
    return updated, detail


def _clear_unbound_surface_candidate(
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    selected_summary = dict(event_unit.selected_evidence_summary or {})
    if selected_summary.get("road_surface_fork_binding"):
        return None, None
    if bool(selected_summary.get("node_fallback_only")):
        return None, None
    if any(
        "pair_local_scope_rcsdnode_outside_drivezone_filtered" in str(reason or "")
        for reason in event_unit.all_review_reasons()
    ):
        return None, None
    if _has_partial_rcsd_signal(event_unit):
        return None, None

    detail = {
        "action": "cleared_unbound_road_surface_fork",
        "reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
        "candidate_id": str(selected_summary.get("candidate_id") or ""),
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            UNBOUND_ROAD_SURFACE_FORK_REASON,
            "no_selected_evidence_after_reselection",
        ]
    )
    empty_summary = {
        "candidate_id": "",
        "selected_evidence_state": "none",
        "evidence_source": "none",
        "position_source": "none",
        "selection_status": "rejected",
        "decision_reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
        "review_state": "STEP4_REVIEW",
        "review_reasons": list(review_reasons),
    }
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
            "rcsd_decision_reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
            "unbound_road_surface_fork_without_bifurcation_rcsd": True,
        }
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="none",
        position_source="none",
        reverse_tip_used=False,
        rcsd_consistency_result=UNBOUND_ROAD_SURFACE_FORK_REASON,
        selected_component_union_geometry=None,
        localized_evidence_core_geometry=None,
        coarse_anchor_zone_geometry=None,
        selected_evidence_region_geometry=None,
        fact_reference_point=None,
        review_materialized_point=None,
        pair_local_rcsd_scope_geometry=None,
        first_hit_rcsd_road_geometry=None,
        local_rcsd_unit_geometry=None,
        positive_rcsd_geometry=None,
        positive_rcsd_road_geometry=None,
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
        selected_branch_ids=(),
        selected_event_branch_ids=(),
        selected_component_ids=(),
        first_hit_rcsdroad_ids=(),
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason=UNBOUND_ROAD_SURFACE_FORK_REASON,
        axis_polarity_inverted=False,
        rcsd_selection_mode=UNBOUND_ROAD_SURFACE_FORK_REASON,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        event_axis_branch_id=None,
        event_chosen_s_m=None,
        selected_candidate_summary=dict(empty_summary),
        selected_evidence_summary=dict(empty_summary),
        positive_rcsd_audit=updated_audit,
        extra_review_notes=(),
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id="",
        resolution_reason=UNBOUND_ROAD_SURFACE_FORK_REASON,
    )
    return updated, detail


def _replace_unit(case_result: T04CaseResult, unit_id: str, replacement: T04EventUnitResult) -> T04CaseResult:
    units = [replacement if unit.spec.event_unit_id == unit_id else unit for unit in case_result.event_units]
    state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in units):
        state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in units):
        state = "STEP4_REVIEW"
    reasons = _dedupe(reason for unit in units for reason in unit.all_review_reasons())
    return replace(case_result, event_units=units, case_review_state=state, case_review_reasons=reasons)


def _base_record(case_result: T04CaseResult, event_unit: T04EventUnitResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_spec.case_id,
        "unit_id": event_unit.spec.event_unit_id,
        "pre_state": event_unit.selected_evidence_state,
        "post_state": event_unit.selected_evidence_state,
        "pre_evidence_source": event_unit.evidence_source,
        "post_evidence_source": event_unit.evidence_source,
        "action": "skipped",
        "skip_reason": None,
        "required_rcsd_node": event_unit.required_rcsd_node,
        "positive_rcsd_consistency_level": event_unit.positive_rcsd_consistency_level,
    }


def apply_road_surface_fork_binding(
    case_results: list[T04CaseResult],
) -> tuple[list[T04CaseResult], dict[str, Any]]:
    updated_results = list(case_results)
    records: list[dict[str, Any]] = []
    applied_count = 0
    skipped_count = 0
    for case_index, case_result in enumerate(updated_results):
        current_case = case_result
        for event_unit in list(current_case.event_units):
            record = _base_record(current_case, event_unit)
            replacement, detail = _bind_strong_rcsd_to_surface(current_case, event_unit)
            if replacement is None:
                replacement, detail = _promote_selected_surface_rcsd_junction_window(
                    current_case,
                    event_unit,
                )
            if replacement is None:
                replacement, detail = _promote_selected_surface_partial_rcsd(current_case, event_unit)
            if replacement is None:
                replacement, detail = _recover_surface_from_candidate(current_case, event_unit)
            if replacement is None:
                replacement, detail = _retain_structure_only_surface_candidate(event_unit)
            if replacement is None:
                replacement, detail = _clear_unbound_surface_candidate(event_unit)
            if replacement is None:
                skipped_count += 1
                record["skip_reason"] = "skipped_no_surface_binding_candidate"
                records.append(record)
                continue
            applied_count += 1
            current_case = _replace_unit(current_case, event_unit.spec.event_unit_id, replacement)
            record.update(
                {
                    "post_state": replacement.selected_evidence_state,
                    "post_evidence_source": replacement.evidence_source,
                    "action": str(detail.get("action") if detail else "road_surface_fork_binding"),
                    "skip_reason": None,
                    "required_rcsd_node": replacement.required_rcsd_node,
                    "positive_rcsd_consistency_level": replacement.positive_rcsd_consistency_level,
                    "detail": dict(detail or {}),
                }
            )
            records.append(record)
        updated_results[case_index] = current_case
    return updated_results, {
        "scope": "t04_step4_road_surface_fork_binding",
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "records": records,
    }


__all__ = ["apply_road_surface_fork_binding"]
