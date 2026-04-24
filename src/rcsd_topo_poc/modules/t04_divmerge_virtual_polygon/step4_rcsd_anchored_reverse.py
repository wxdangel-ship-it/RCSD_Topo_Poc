from __future__ import annotations

from dataclasses import replace
from statistics import median
from typing import Any, Iterable, Sequence

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, unary_union

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from .event_interpretation_selection import (
    EVENT_REFERENCE_CONFLICT_TOL_M,
    SHARED_EVIDENCE_OVERLAP_AREA_M2,
    SHARED_EVIDENCE_OVERLAP_RATIO,
)


MIN_RCSD_ANCHOR_SAMPLE_COUNT = 3
RCSD_ANCHORED_EVIDENCE_RECOVERY_WINDOW_M = 20.0
RCSD_ANCHORED_FALLBACK_PATCH_RADIUS_M = 4.0
RCSD_CLAIM_ROAD_OVERLAP_RATIO = 0.5
RCSD_REFERENCE_SAMPLE_ENDPOINT_TOL_M = 1.0
RCSD_TERMINAL_CONTINUATION_AXIS_TOL_M = 0.75
RCSD_ANCHORED_REVIEW_REASON = "rcsd_anchored_reverse_used"
RCSD_ANCHORED_RISK_SIGNAL = "rcsd_anchored_reverse"
RELAXED_AGGREGATED_RCSD_REASONS = {
    "role_mapping_partial_relaxed_aggregated",
}

_EVIDENCE_MISSING_REASONS = {
    "no_selected_evidence_after_reselection",
    "layer3_candidate_not_primary_eligible",
    "node_fallback_candidate_not_primary_eligible",
}


def _dedupe(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _normalize_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    try:
        normalized = geometry.buffer(0) if str(getattr(geometry, "geom_type", "")) in {"Polygon", "MultiPolygon"} else geometry
    except Exception:
        normalized = geometry
    return None if normalized is None or normalized.is_empty else normalized


def _union_geometry(geometries: Iterable[BaseGeometry | None]) -> BaseGeometry | None:
    valid = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not valid:
        return None
    return _normalize_geometry(unary_union(valid))


def _as_point(geometry: BaseGeometry | None) -> Point | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, Point):
        return geometry
    try:
        point = geometry.representative_point()
    except Exception:
        return None
    return None if point is None or point.is_empty else point


def _line_parts(geometry: BaseGeometry | None) -> tuple[LineString, ...]:
    if geometry is None or geometry.is_empty:
        return ()
    if isinstance(geometry, LineString):
        return (geometry,)
    if isinstance(geometry, MultiLineString):
        return tuple(part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty)
    geoms = getattr(geometry, "geoms", None)
    if geoms is not None:
        parts: list[LineString] = []
        for part in geoms:
            parts.extend(_line_parts(part))
        return tuple(parts)
    return ()


def _polygon_parts(geometry: BaseGeometry | None) -> tuple[Polygon, ...]:
    if geometry is None or geometry.is_empty:
        return ()
    if isinstance(geometry, Polygon):
        return (geometry,)
    if isinstance(geometry, MultiPolygon):
        return tuple(part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty)
    geoms = getattr(geometry, "geoms", None)
    if geoms is not None:
        parts: list[Polygon] = []
        for part in geoms:
            parts.extend(_polygon_parts(part))
        return tuple(parts)
    return ()


def _merge_lines(lines: Sequence[LineString]) -> LineString | None:
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    try:
        merged = linemerge(unary_union(lines))
    except Exception:
        merged = unary_union(lines)
    parts = _line_parts(merged)
    if not parts:
        return max(lines, key=lambda item: float(item.length))
    return max(parts, key=lambda item: float(item.length))


def _road_lookup(case_result: T04CaseResult):
    return {str(road.road_id): road for road in (*case_result.case_bundle.roads, *case_result.case_bundle.rcsd_roads)}


def _rcsd_road_lookup(case_result: T04CaseResult):
    return {str(road.road_id): road for road in case_result.case_bundle.rcsd_roads}


def _rcsd_node_lookup(case_result: T04CaseResult):
    return {str(node.node_id): node for node in case_result.case_bundle.rcsd_nodes}


def _rcsd_road_geometry(case_result: T04CaseResult, road_ids: Iterable[str]) -> BaseGeometry | None:
    roads_by_id = _rcsd_road_lookup(case_result)
    return _union_geometry(
        roads_by_id[str(road_id)].geometry
        for road_id in road_ids
        if str(road_id) in roads_by_id
    )


def _rcsd_node_geometry(case_result: T04CaseResult, node_ids: Iterable[str]) -> BaseGeometry | None:
    nodes_by_id = _rcsd_node_lookup(case_result)
    return _union_geometry(
        nodes_by_id[str(node_id)].geometry
        for node_id in node_ids
        if str(node_id) in nodes_by_id
    )


def _stable_axis_signature(event_unit: T04EventUnitResult, axis_branch_id: str | None) -> str:
    selected_signature = str(event_unit.selected_candidate_summary.get("axis_signature") or "").strip()
    if selected_signature:
        return selected_signature
    for entry in event_unit.candidate_audit_entries:
        entry_signature = str(entry.candidate_summary.get("axis_signature") or "").strip()
        if entry_signature:
            return entry_signature
    if axis_branch_id:
        road_ids = tuple(str(item) for item in event_unit.unit_envelope.branch_road_memberships.get(str(axis_branch_id), ()))
        if len(road_ids) == 1:
            return road_ids[0]
        if road_ids:
            return "+".join(sorted(road_ids))
    return str(axis_branch_id or "")


def _axis_context(case_result: T04CaseResult, event_unit: T04EventUnitResult) -> dict[str, Any]:
    bridge = event_unit.interpretation.legacy_step5_bridge
    axis_branch_id = (
        str(event_unit.event_axis_branch_id or "").strip()
        or str(getattr(bridge, "event_axis_branch_id", "") or "").strip()
        or str(event_unit.unit_envelope.preferred_axis_branch_id or "").strip()
        or None
    )
    axis_line = _merge_lines(_line_parts(getattr(bridge, "event_axis_centerline", None)))
    if axis_line is None and axis_branch_id:
        roads_by_id = _road_lookup(case_result)
        lines: list[LineString] = []
        for road_id in event_unit.unit_envelope.branch_road_memberships.get(str(axis_branch_id), ()):
            road = roads_by_id.get(str(road_id))
            lines.extend(_line_parts(None if road is None else road.geometry))
        axis_line = _merge_lines(lines)
    origin_point = _as_point(getattr(bridge, "event_origin_point", None)) or event_unit.unit_context.representative_node.geometry
    if axis_line is not None and not axis_line.is_empty:
        try:
            origin_point = nearest_points(axis_line, origin_point)[0]
        except Exception:
            pass
    origin_s = None if axis_line is None else float(axis_line.project(origin_point))
    return {
        "axis_branch_id": axis_branch_id,
        "axis_signature": _stable_axis_signature(event_unit, axis_branch_id),
        "axis_line": axis_line,
        "origin_point": origin_point,
        "origin_s": origin_s,
    }


def _project_point_to_axis(point: Point, axis_context: dict[str, Any]) -> float | None:
    axis_line = axis_context.get("axis_line")
    origin_s = axis_context.get("origin_s")
    if axis_line is None or origin_s is None:
        return None
    try:
        axis_point = nearest_points(axis_line, point)[0]
        return float(axis_line.project(axis_point)) - float(origin_s)
    except Exception:
        return None


def _axis_point_at_s(axis_context: dict[str, Any], s_value: float) -> Point | None:
    axis_line = axis_context.get("axis_line")
    origin_s = axis_context.get("origin_s")
    if axis_line is None or origin_s is None:
        return None
    try:
        raw_s = max(0.0, min(float(axis_line.length), float(origin_s) + float(s_value)))
        point = axis_line.interpolate(raw_s)
    except Exception:
        return None
    return None if point is None or point.is_empty else point


def _road_endpoint_ids(road: Any) -> tuple[str | None, str | None]:
    start = str(getattr(road, "snodeid", "") or "").strip() or None
    end = str(getattr(road, "enodeid", "") or "").strip() or None
    return start, end


def _road_endpoint_node_ids(road_ids: Iterable[str], roads_by_id: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for road_id in road_ids:
        road = roads_by_id.get(str(road_id))
        if road is None:
            continue
        for node_id in _road_endpoint_ids(road):
            if node_id:
                result.add(node_id)
    return result


def _candidate_axis_position(entry: T04CandidateAuditEntry) -> float | None:
    value = entry.candidate_summary.get("axis_position_m")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _relaxed_aggregated_rcsd(summary: dict[str, Any]) -> bool:
    return str(summary.get("rcsd_decision_reason") or "").strip() in RELAXED_AGGREGATED_RCSD_REASONS


def _trigger_candidate(entry: T04CandidateAuditEntry) -> bool:
    summary = entry.candidate_summary
    return bool(
        summary.get("positive_rcsd_present") is True
        and str(summary.get("aggregated_rcsd_unit_id") or "").strip()
        and list(summary.get("first_hit_rcsdroad_ids") or ())
        and not _relaxed_aggregated_rcsd(summary)
    )


def _rank_mother_candidates(entries: Sequence[T04CandidateAuditEntry]) -> list[T04CandidateAuditEntry]:
    candidates = [entry for entry in entries if _trigger_candidate(entry)]
    return sorted(
        candidates,
        key=lambda entry: (
            int(entry.pool_rank or 9999),
            bool(entry.candidate_summary.get("node_fallback_only")),
            -len(list(entry.candidate_summary.get("first_hit_rcsdroad_ids") or ())),
            -float(entry.candidate_summary.get("pair_middle_overlap_ratio") or 0.0),
            str(entry.candidate_id),
        ),
    )


def _cluster_doc_from_mother(mother: T04CandidateAuditEntry) -> dict[str, Any]:
    aggregate_id = str(mother.candidate_summary.get("aggregated_rcsd_unit_id") or mother.aggregated_rcsd_unit_id or "")
    aggregates = list(mother.positive_rcsd_audit.get("aggregated_rcsd_units") or ())
    for item in aggregates:
        if str(item.get("unit_id") or "") == aggregate_id:
            return dict(item)
    return {
        "unit_id": aggregate_id,
        "road_ids": list(mother.selected_rcsdroad_ids),
        "node_ids": list(mother.selected_rcsdnode_ids),
        "required_node_id": mother.required_rcsd_node,
        "member_unit_kinds": [mother.local_rcsd_unit_kind] if mother.local_rcsd_unit_kind else [],
    }


def _cluster_ids(mother: T04CandidateAuditEntry) -> tuple[str, set[str], set[str]]:
    doc = _cluster_doc_from_mother(mother)
    road_ids = {str(item) for item in doc.get("road_ids") or () if str(item)}
    road_ids.update(str(item) for item in mother.selected_rcsdroad_ids if str(item))
    node_ids = {str(item) for item in doc.get("node_ids") or () if str(item)}
    node_ids.update(str(item) for item in mother.selected_rcsdnode_ids if str(item))
    required = str(doc.get("required_node_id") or mother.required_rcsd_node or "").strip()
    if required:
        node_ids.add(required)
    aggregate_id = str(doc.get("unit_id") or mother.aggregated_rcsd_unit_id or "").strip()
    return aggregate_id, road_ids, node_ids


def _rcsd_anchor_samples(
    case_result: T04CaseResult,
    *,
    road_ids: set[str],
    node_ids: set[str],
    axis_context: dict[str, Any],
) -> tuple[list[float], list[float]]:
    nodes_by_id = _rcsd_node_lookup(case_result)
    roads_by_id = _rcsd_road_lookup(case_result)
    node_samples: list[float] = []
    road_samples: list[float] = []
    for node_id in sorted(node_ids):
        node = nodes_by_id.get(node_id)
        point = None if node is None else _as_point(node.geometry)
        if point is None:
            continue
        sample = _project_point_to_axis(point, axis_context)
        if sample is not None:
            node_samples.append(round(float(sample), 3))
    axis_line = axis_context.get("axis_line")
    if axis_line is not None:
        for road_id in sorted(road_ids):
            road = roads_by_id.get(road_id)
            geometry = None if road is None else road.geometry
            if geometry is None or geometry.is_empty:
                continue
            try:
                axis_point = nearest_points(axis_line, geometry)[0]
            except Exception:
                continue
            sample = _project_point_to_axis(axis_point, axis_context)
            if sample is not None:
                road_samples.append(round(float(sample), 3))
    return node_samples, road_samples


def _road_axis_sample_points(
    case_result: T04CaseResult,
    *,
    road_ids: set[str],
    axis_context: dict[str, Any],
) -> list[tuple[str, float, Point]]:
    axis_line = axis_context.get("axis_line")
    if axis_line is None:
        return []
    roads_by_id = _rcsd_road_lookup(case_result)
    samples: list[tuple[str, float, Point]] = []
    for road_id in sorted(road_ids):
        road = roads_by_id.get(road_id)
        geometry = None if road is None else road.geometry
        if geometry is None or geometry.is_empty:
            continue
        try:
            axis_point = nearest_points(axis_line, geometry)[0]
        except Exception:
            continue
        sample = _project_point_to_axis(axis_point, axis_context)
        if sample is None:
            continue
        samples.append((road_id, float(sample), axis_point))
    return samples


def _selected_divstrip_component_geometry(
    event_unit: T04EventUnitResult,
    *,
    component_ids: Sequence[str],
) -> BaseGeometry | None:
    selected_indices: list[int] = []
    for component_id in component_ids:
        text = str(component_id or "").strip()
        if not text.startswith("divstrip_component_"):
            continue
        try:
            selected_indices.append(int(text.rsplit("_", 1)[-1]))
        except ValueError:
            continue
    if not selected_indices:
        return None
    divstrip_union = _union_geometry(
        feature.geometry
        for feature in event_unit.unit_context.local_context.patch_divstrip_features
        if feature.geometry is not None and not feature.geometry.is_empty
    )
    components = _polygon_parts(divstrip_union)
    if not components:
        return None
    picked = [
        components[index]
        for index in sorted(set(selected_indices))
        if 0 <= int(index) < len(components)
    ]
    return _union_geometry(picked)


def _divstrip_reference_vertices(component_geometry: BaseGeometry | None) -> list[Point]:
    vertices: list[Point] = []
    for polygon in _polygon_parts(component_geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            for coord in ring.coords:
                vertices.append(Point(float(coord[0]), float(coord[1])))
    return vertices


def _reverse_divstrip_reference_point(
    event_unit: T04EventUnitResult,
    *,
    component_ids: Sequence[str],
    required_point: Point,
    axis_context: dict[str, Any],
    s_rcsd_anchored: float,
    required_s: float,
) -> tuple[Point, float, str] | None:
    component_geometry = _selected_divstrip_component_geometry(
        event_unit,
        component_ids=component_ids,
    )
    if component_geometry is None:
        return None
    boundary = getattr(component_geometry, "boundary", None)
    if boundary is not None and not boundary.is_empty:
        boundary_point = nearest_points(boundary, required_point)[0]
        boundary_s = _project_point_to_axis(boundary_point, axis_context)
        if boundary_s is not None:
            lower = min(float(s_rcsd_anchored), float(required_s)) - 1e-6
            upper = max(float(s_rcsd_anchored), float(required_s)) + 1e-6
            if lower <= float(boundary_s) <= upper:
                return boundary_point, float(boundary_s), "selected_divstrip_branch_tip"

    lower = min(float(s_rcsd_anchored), float(required_s)) + RCSD_REFERENCE_SAMPLE_ENDPOINT_TOL_M
    upper = max(float(s_rcsd_anchored), float(required_s)) - RCSD_REFERENCE_SAMPLE_ENDPOINT_TOL_M
    projected_vertices: list[tuple[float, Point]] = []
    for vertex in _divstrip_reference_vertices(component_geometry):
        sample_s = _project_point_to_axis(vertex, axis_context)
        if sample_s is None or not (lower <= float(sample_s) <= upper):
            continue
        projected_vertices.append((float(sample_s), vertex))
    if not projected_vertices:
        return None
    if float(required_s) >= float(s_rcsd_anchored):
        sample_s, reference_point = max(projected_vertices, key=lambda item: item[0])
    else:
        sample_s, reference_point = min(projected_vertices, key=lambda item: item[0])
    return reference_point, float(sample_s), "selected_divstrip_branch_tip"


def _reverse_reference_point(
    case_result: T04CaseResult,
    *,
    event_unit: T04EventUnitResult,
    mother: T04CandidateAuditEntry,
    road_ids: set[str],
    axis_context: dict[str, Any],
    s_rcsd_anchored: float,
    anchor_point: Point | None,
) -> tuple[Point | None, float, str]:
    required_point = _as_point(mother.required_rcsd_node_geometry)
    if required_point is None:
        return anchor_point, float(s_rcsd_anchored), "axis_anchor"
    required_s = _project_point_to_axis(required_point, axis_context)
    if required_s is None:
        return anchor_point, float(s_rcsd_anchored), "axis_anchor"

    divstrip_reference = _reverse_divstrip_reference_point(
        event_unit,
        component_ids=mother.selected_component_ids or event_unit.selected_component_ids,
        required_point=required_point,
        axis_context=axis_context,
        s_rcsd_anchored=s_rcsd_anchored,
        required_s=float(required_s),
    )
    if divstrip_reference is not None:
        return divstrip_reference

    lower = min(float(s_rcsd_anchored), float(required_s)) + RCSD_REFERENCE_SAMPLE_ENDPOINT_TOL_M
    upper = max(float(s_rcsd_anchored), float(required_s)) - RCSD_REFERENCE_SAMPLE_ENDPOINT_TOL_M
    if upper <= lower:
        return anchor_point, float(s_rcsd_anchored), "axis_anchor"

    interior_samples: list[tuple[float, float, str, Point]] = []
    for road_id, sample_s, axis_point in _road_axis_sample_points(
        case_result,
        road_ids=road_ids,
        axis_context=axis_context,
    ):
        if sample_s <= lower or sample_s >= upper:
            continue
        interior_samples.append(
            (
                abs(float(required_s) - float(sample_s)),
                abs(float(s_rcsd_anchored) - float(sample_s)),
                road_id,
                axis_point,
            )
        )
    if not interior_samples:
        return anchor_point, float(s_rcsd_anchored), "axis_anchor"

    interior_samples.sort(key=lambda item: (item[0], item[1], item[2]))
    _distance_to_required, _distance_to_anchor, road_id, reference_point = interior_samples[0]
    reference_s = _project_point_to_axis(reference_point, axis_context)
    if reference_s is None:
        return anchor_point, float(s_rcsd_anchored), "axis_anchor"
    return reference_point, float(reference_s), f"intermediate_rcsd_road_axis_sample:{road_id}"


def _drivezone_union(case_result: T04CaseResult) -> BaseGeometry | None:
    return _union_geometry(feature.geometry for feature in case_result.case_bundle.drivezone_features)


def _clip_to_drivezone(geometry: BaseGeometry | None, drivezone: BaseGeometry | None) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None or drivezone is None or drivezone.is_empty:
        return normalized
    try:
        clipped = normalized.intersection(drivezone)
    except Exception:
        clipped = normalized
    return _normalize_geometry(clipped)


def _recover_evidence(
    entries: Sequence[T04CandidateAuditEntry],
    *,
    s_rcsd_anchored: float,
) -> T04CandidateAuditEntry | None:
    candidates: list[tuple[tuple[Any, ...], T04CandidateAuditEntry]] = []
    for entry in entries:
        summary = entry.candidate_summary
        axis_position = _candidate_axis_position(entry)
        if axis_position is None:
            continue
        if abs(float(axis_position) - float(s_rcsd_anchored)) > RCSD_ANCHORED_EVIDENCE_RECOVERY_WINDOW_M:
            continue
        if entry.candidate_region_geometry is None or entry.candidate_region_geometry.is_empty:
            continue
        evidence_kind = str(summary.get("upper_evidence_kind") or "")
        if evidence_kind not in {"divstrip", "structure_face"}:
            continue
        key = (
            0 if evidence_kind == "divstrip" else 1,
            bool(summary.get("node_fallback_only")),
            int(summary.get("layer") or 9),
            abs(float(axis_position) - float(s_rcsd_anchored)),
            int(entry.pool_rank or 9999),
            str(entry.candidate_id),
        )
        candidates.append((key, entry))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else None


def _overlap_metrics(lhs: BaseGeometry | None, rhs: BaseGeometry | None) -> tuple[float, float]:
    lhs = _normalize_geometry(lhs)
    rhs = _normalize_geometry(rhs)
    if lhs is None or rhs is None:
        return 0.0, 0.0
    try:
        overlap = _normalize_geometry(lhs.intersection(rhs))
    except Exception:
        return 0.0, 0.0
    overlap_area = 0.0 if overlap is None else float(getattr(overlap, "area", 0.0) or 0.0)
    smaller = min(float(getattr(lhs, "area", 0.0) or 0.0), float(getattr(rhs, "area", 0.0) or 0.0))
    return overlap_area, 0.0 if smaller <= 1e-6 else overlap_area / smaller


def _has_evidence_overlap(lhs: BaseGeometry | None, rhs: BaseGeometry | None) -> bool:
    overlap_area, overlap_ratio = _overlap_metrics(lhs, rhs)
    return overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2 or overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO


def _road_overlap_ratio(lhs: Iterable[str], rhs: Iterable[str]) -> float:
    lhs_set = {str(item) for item in lhs if str(item)}
    rhs_set = {str(item) for item in rhs if str(item)}
    if not lhs_set or not rhs_set:
        return 0.0
    return len(lhs_set & rhs_set) / min(len(lhs_set), len(rhs_set))


def _operation_type(event_unit: T04EventUnitResult, mother: T04CandidateAuditEntry) -> str:
    audit_type = str(mother.positive_rcsd_audit.get("operational_event_type") or "").strip()
    if audit_type in {"merge", "diverge"}:
        return audit_type
    try:
        kind_2 = int(event_unit.interpretation.kind_resolution.operational_kind_2 or 0)
    except (TypeError, ValueError):
        kind_2 = 0
    if kind_2 == 8:
        return "merge"
    if kind_2 == 16:
        return "diverge"
    return str(event_unit.spec.event_type or "").strip()


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


def _summary_with_anchor(
    base_summary: dict[str, Any],
    *,
    state: str,
    evidence_source: str,
    position_source: str,
    s_rcsd_anchored: float,
    axis_context: dict[str, Any],
    aggregate_id: str,
    mother: T04CandidateAuditEntry,
    recovered: T04CandidateAuditEntry | None,
) -> dict[str, Any]:
    summary = dict(base_summary)
    if not str(summary.get("candidate_id") or "").strip():
        summary.update(
            {
                "candidate_id": f"{mother.candidate_id}:rcsd_anchored",
                "source_mode": "rcsd_anchored_reverse",
                "upper_evidence_kind": "rcsd_anchor",
                "upper_evidence_object_id": aggregate_id,
                "candidate_scope": "rcsd_anchored_axis_projection",
                "local_region_id": f"{mother.candidate_id}:rcsd_anchored",
                "ownership_signature": f"rcsd_anchor:{aggregate_id}:{mother.candidate_id}",
                "layer": 2,
                "layer_label": "Layer 2",
                "layer_reason": "rcsd_anchored_fallback",
            }
        )
    axis_signature = str(axis_context.get("axis_signature") or axis_context.get("axis_branch_id") or "")
    summary.update(
        {
            "selected_evidence_state": state,
            "evidence_source": evidence_source,
            "position_source": position_source,
            "axis_signature": axis_signature,
            "axis_position_basis": axis_signature,
            "axis_position_m": round(float(s_rcsd_anchored), 3),
            "point_signature": f"{axis_signature}:{round(float(s_rcsd_anchored), 1)}" if axis_signature else "",
            "aggregated_rcsd_unit_id": aggregate_id,
            "positive_rcsd_present": True,
            "positive_rcsd_support_level": mother.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": mother.positive_rcsd_consistency_level,
            "first_hit_rcsdroad_ids": list(mother.first_hit_rcsdroad_ids),
            "required_rcsd_node": mother.required_rcsd_node,
            "required_rcsd_node_source": mother.required_rcsd_node_source,
            "rcsd_anchored_reverse_recovered_evidence": recovered is not None,
        }
    )
    return summary


def _update_interpretation(
    event_unit: T04EventUnitResult,
    *,
    axis_branch_id: str,
    s_rcsd_anchored: float,
    anchor_point: Point | None,
    reference_point: Point | None,
    reference_origin_point: Point | None,
    reference_mode: str,
    fallback_used: bool,
) -> Any:
    interpretation = event_unit.interpretation
    event_reference = replace(
        interpretation.event_reference,
        event_axis_branch_id=axis_branch_id,
        event_origin_source="rcsd_anchored_axis_projection",
        event_position_source="rcsd_anchored_axis_projection",
        event_split_pick_source="rcsd_anchored_reverse",
        event_chosen_s_m=round(float(s_rcsd_anchored), 3),
        raw={
            **dict(interpretation.event_reference.raw),
            "event_axis_branch_id": axis_branch_id,
            "event_origin_source": "rcsd_anchored_axis_projection",
            "position_source": "rcsd_anchored_axis_projection",
            "chosen_s_m": round(float(s_rcsd_anchored), 3),
            "reference_point_mode": reference_mode,
        },
    )
    evidence_decision = replace(
        interpretation.evidence_decision,
        primary_source="rcsd_anchored_reverse",
        selection_mode="rcsd_anchored_reverse",
        fallback_used=fallback_used,
        fallback_mode="rcsd_anchored" if fallback_used else interpretation.evidence_decision.fallback_mode,
        risk_signals=_dedupe([*interpretation.evidence_decision.risk_signals, RCSD_ANCHORED_RISK_SIGNAL]),
    )
    bridge = replace(
        interpretation.legacy_step5_bridge,
        event_axis_branch_id=axis_branch_id,
        event_reference_raw={
            **dict(interpretation.legacy_step5_bridge.event_reference_raw),
            "event_axis_branch_id": axis_branch_id,
            "event_origin_source": "rcsd_anchored_axis_projection",
            "position_source": "rcsd_anchored_axis_projection",
            "chosen_s_m": round(float(s_rcsd_anchored), 3),
            "reference_point_mode": reference_mode,
        },
        event_origin_point=reference_origin_point or anchor_point or interpretation.legacy_step5_bridge.event_origin_point,
        event_origin_source="rcsd_anchored_axis_projection",
    )
    return replace(
        interpretation,
        evidence_decision=evidence_decision,
        event_reference=event_reference,
        legacy_step5_bridge=bridge,
        risk_signals=_dedupe([*interpretation.risk_signals, RCSD_ANCHORED_RISK_SIGNAL]),
    )


def _apply_reverse_to_unit(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    mother: T04CandidateAuditEntry,
    aggregate_id: str,
    road_ids: set[str],
    node_ids: set[str],
    axis_context: dict[str, Any],
    node_samples_s: list[float],
    road_samples_s: list[float],
) -> tuple[T04EventUnitResult, dict[str, Any]]:
    samples = [*node_samples_s, *road_samples_s]
    s_rcsd_anchored = round(float(median(samples)), 3)
    anchor_point = _axis_point_at_s(axis_context, s_rcsd_anchored)
    reference_point, reference_s, reference_mode = _reverse_reference_point(
        case_result,
        event_unit=event_unit,
        mother=mother,
        road_ids=road_ids,
        axis_context=axis_context,
        s_rcsd_anchored=s_rcsd_anchored,
        anchor_point=anchor_point,
    )
    reference_origin_point = _axis_point_at_s(axis_context, reference_s) or reference_point
    drivezone = _drivezone_union(case_result)
    continuation = _terminal_continuation_expansion(
        case_result,
        event_unit,
        mother=mother,
        axis_context=axis_context,
        drivezone=drivezone,
    )
    selected_rcsdroad_ids = _dedupe([*mother.selected_rcsdroad_ids, *continuation.get("road_ids", [])])
    selected_rcsdnode_ids = _dedupe([*mother.selected_rcsdnode_ids, *continuation.get("node_ids", [])])
    continuation_road_geometry = _rcsd_road_geometry(case_result, continuation.get("road_ids", []))
    continuation_node_geometry = _rcsd_node_geometry(case_result, continuation.get("node_ids", []))
    positive_rcsd_road_geometry = _union_geometry([mother.positive_rcsd_road_geometry, continuation_road_geometry])
    positive_rcsd_node_geometry = _union_geometry([mother.positive_rcsd_node_geometry, continuation_node_geometry])
    positive_rcsd_geometry = _union_geometry([positive_rcsd_road_geometry, positive_rcsd_node_geometry])
    recovered = _recover_evidence(event_unit.candidate_audit_entries, s_rcsd_anchored=s_rcsd_anchored)
    fallback_used = recovered is None
    if recovered is None:
        evidence_patch = _clip_to_drivezone(
            None if anchor_point is None else anchor_point.buffer(RCSD_ANCHORED_FALLBACK_PATCH_RADIUS_M, join_style=2),
            drivezone,
        )
        component_geometry = evidence_patch
        core_geometry = evidence_patch
        evidence_region_geometry = evidence_patch
        base_summary: dict[str, Any] = {}
        post_state = "rcsd_anchored"
    else:
        component_geometry = recovered.selected_component_union_geometry or recovered.candidate_region_geometry
        core_geometry = recovered.localized_evidence_core_geometry or recovered.candidate_region_geometry
        evidence_region_geometry = recovered.selected_evidence_region_geometry or recovered.candidate_region_geometry
        base_summary = dict(recovered.candidate_summary)
        post_state = "found"

    summary = _summary_with_anchor(
        base_summary,
        state=post_state,
        evidence_source="rcsd_anchored_reverse",
        position_source="rcsd_anchored_axis_projection",
        s_rcsd_anchored=s_rcsd_anchored,
        axis_context=axis_context,
        aggregate_id=aggregate_id,
        mother=mother,
        recovered=recovered,
    )
    summary.update(
        {
            "selected_rcsdroad_ids": list(selected_rcsdroad_ids),
            "selected_rcsdnode_ids": list(selected_rcsdnode_ids),
            "terminal_continuation_expansion": continuation,
        }
    )
    updated_interpretation = _update_interpretation(
        event_unit,
        axis_branch_id=str(axis_context["axis_branch_id"]),
        s_rcsd_anchored=s_rcsd_anchored,
        anchor_point=anchor_point,
        reference_point=reference_point,
        reference_origin_point=reference_origin_point,
        reference_mode=reference_mode,
        fallback_used=fallback_used,
    )
    review_reasons = _dedupe(
        [
            reason
            for reason in event_unit.all_review_reasons()
            if str(reason) not in _EVIDENCE_MISSING_REASONS
        ]
        + [RCSD_ANCHORED_REVIEW_REASON]
    )
    updated_positive_audit = {
        **dict(mother.positive_rcsd_audit),
        "published_rcsdroad_ids": list(selected_rcsdroad_ids),
        "published_rcsdnode_ids": list(selected_rcsdnode_ids),
        "terminal_continuation_expansion": continuation,
        "rcsd_anchored_reverse": {
            "used": True,
            "s_rcsd_anchored": s_rcsd_anchored,
            "sample_count": len(samples),
            "evidence_recovered": recovered is not None,
            "recovered_candidate_id": None if recovered is None else recovered.candidate_id,
            "reference_point_mode": reference_mode,
            "reference_point_axis_s": round(float(reference_s), 3),
            "terminal_continuation_expansion": continuation,
        },
    }
    updated = replace(
        event_unit,
        interpretation=updated_interpretation,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        extra_review_notes=(),
        evidence_source="rcsd_anchored_reverse",
        position_source="rcsd_anchored_axis_projection",
        reverse_tip_used=False,
        rcsd_consistency_result=mother.rcsd_consistency_result,
        selected_component_union_geometry=component_geometry,
        localized_evidence_core_geometry=core_geometry,
        coarse_anchor_zone_geometry=_clip_to_drivezone(
            None if anchor_point is None else anchor_point.buffer(max(RCSD_ANCHORED_FALLBACK_PATCH_RADIUS_M, 6.0), join_style=2),
            drivezone,
        ),
        selected_evidence_region_geometry=evidence_region_geometry,
        fact_reference_point=reference_point,
        review_materialized_point=reference_point,
        pair_local_rcsd_scope_geometry=mother.pair_local_rcsd_scope_geometry,
        first_hit_rcsd_road_geometry=mother.first_hit_rcsd_road_geometry,
        local_rcsd_unit_geometry=mother.local_rcsd_unit_geometry,
        positive_rcsd_geometry=positive_rcsd_geometry,
        positive_rcsd_road_geometry=positive_rcsd_road_geometry,
        positive_rcsd_node_geometry=positive_rcsd_node_geometry,
        primary_main_rc_node_geometry=mother.primary_main_rc_node_geometry,
        required_rcsd_node_geometry=mother.required_rcsd_node_geometry,
        selected_branch_ids=mother.selected_branch_ids,
        selected_event_branch_ids=mother.selected_event_branch_ids,
        selected_component_ids=mother.selected_component_ids,
        pair_local_rcsd_road_ids=mother.pair_local_rcsd_road_ids,
        pair_local_rcsd_node_ids=mother.pair_local_rcsd_node_ids,
        first_hit_rcsdroad_ids=mother.first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=selected_rcsdroad_ids,
        selected_rcsdnode_ids=selected_rcsdnode_ids,
        primary_main_rc_node_id=mother.primary_main_rc_node_id,
        local_rcsd_unit_id=mother.local_rcsd_unit_id,
        local_rcsd_unit_kind=mother.local_rcsd_unit_kind,
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=mother.aggregated_rcsd_unit_ids,
        positive_rcsd_present=True,
        positive_rcsd_present_reason=mother.positive_rcsd_present_reason,
        axis_polarity_inverted=mother.axis_polarity_inverted,
        rcsd_selection_mode=f"rcsd_anchored_reverse:{mother.rcsd_selection_mode}",
        pair_local_rcsd_empty=False,
        positive_rcsd_support_level=mother.positive_rcsd_support_level,
        positive_rcsd_consistency_level=mother.positive_rcsd_consistency_level,
        required_rcsd_node=mother.required_rcsd_node,
        required_rcsd_node_source=mother.required_rcsd_node_source,
        event_axis_branch_id=str(axis_context["axis_branch_id"]),
        event_chosen_s_m=s_rcsd_anchored,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_positive_audit,
        conflict_resolution_action="rcsd_anchored_reverse",
        post_resolution_candidate_id=str(summary.get("candidate_id") or ""),
        post_required_rcsd_node=str(mother.required_rcsd_node or ""),
        resolution_reason=RCSD_ANCHORED_REVIEW_REASON,
    )
    detail = {
        "s_rcsd_anchored": s_rcsd_anchored,
        "evidence_recovered": recovered is not None,
        "recovered_candidate_id": None if recovered is None else recovered.candidate_id,
        "post_selected_evidence_state": updated.selected_evidence_state,
        "reference_point_mode": reference_mode,
        "reference_point_axis_s": round(float(reference_s), 3),
        "terminal_continuation_expansion": continuation,
    }
    return updated, detail


def _record_base(case_result: T04CaseResult, event_unit: T04EventUnitResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_spec.case_id,
        "unit_id": event_unit.spec.event_unit_id,
        "mother_candidate_id": None,
        "mother_candidate_node_fallback_only": None,
        "mother_candidate_pool_rank": None,
        "mother_axis_position_m": None,
        "axis_branch_id": None,
        "node_samples_s": [],
        "road_samples_s": [],
        "sample_count": 0,
        "sample_kind_counts": {"node": 0, "road": 0},
        "aggregated_rcsd_unit_id": None,
        "pre_state": event_unit.selected_evidence_state,
        "post_state": event_unit.selected_evidence_state,
        "skip_reason": None,
    }


def _replace_unit(case_result: T04CaseResult, unit_id: str, replacement: T04EventUnitResult) -> T04CaseResult:
    units = [replacement if unit.spec.event_unit_id == unit_id else unit for unit in case_result.event_units]
    state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in units):
        state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in units):
        state = "STEP4_REVIEW"
    reasons = _dedupe(reason for unit in units for reason in unit.all_review_reasons())
    return replace(case_result, event_units=units, case_review_state=state, case_review_reasons=reasons)


def _find_unit(case_result: T04CaseResult, unit_id: str) -> T04EventUnitResult:
    for unit in case_result.event_units:
        if unit.spec.event_unit_id == unit_id:
            return unit
    raise KeyError(unit_id)


def _post_conflict_recheck(
    case_results: list[T04CaseResult],
    records: list[dict[str, Any]],
    originals: dict[tuple[str, str], T04EventUnitResult],
) -> list[T04CaseResult]:
    case_by_id = {case.case_spec.case_id: case for case in case_results}
    for record in records:
        original_key = (str(record["case_id"]), str(record["unit_id"]))
        if original_key not in originals or record.get("post_state") not in {"found", "rcsd_anchored"}:
            continue
        case_id = str(record["case_id"])
        unit_id = str(record["unit_id"])
        current = _find_unit(case_by_id[case_id], unit_id)
        conflict_detail = None
        current_summary = current.selected_evidence_summary
        for other_case in case_results:
            for other in other_case.event_units:
                if other_case.case_spec.case_id == case_id and other.spec.event_unit_id == unit_id:
                    continue
                if other_case.case_spec.case_id == case_id:
                    continue
                if _rcsd_claim_conflicts(
                    current,
                    other,
                    aggregate_id=str(current.aggregated_rcsd_unit_id or ""),
                    road_ids=set(current.selected_rcsdroad_ids),
                    node_ids=set(current.selected_rcsdnode_ids),
                    same_case=False,
                ):
                    conflict_detail = {
                        "scope": "cross_case_rcsd_claim",
                        "other_case_id": other_case.case_spec.case_id,
                        "other_unit_id": other.spec.event_unit_id,
                    }
                    break
                if _evidence_conflicts(
                    other,
                    summary=current_summary,
                    component_geometry=current.selected_component_union_geometry,
                    core_geometry=current.localized_evidence_core_geometry,
                    same_case=False,
                ):
                    conflict_detail = {
                        "scope": "cross_case_evidence",
                        "other_case_id": other_case.case_spec.case_id,
                        "other_unit_id": other.spec.event_unit_id,
                    }
                    break
            if conflict_detail is not None:
                break
        if conflict_detail is None:
            record["post_reverse_conflict_recheck"] = "passed"
            continue
        original = originals[(case_id, unit_id)]
        case_by_id[case_id] = _replace_unit(case_by_id[case_id], unit_id, original)
        record["post_reverse_conflict_recheck"] = "failed"
        record["post_reverse_conflict_detail"] = conflict_detail
        record["skip_reason"] = "skipped_post_reverse_conflict_recheck"
        record["post_state"] = original.selected_evidence_state
    return [case_by_id[case.case_spec.case_id] for case in case_results]


def apply_rcsd_anchored_reverse_lookup(
    case_results: list[T04CaseResult],
) -> tuple[list[T04CaseResult], dict[str, Any]]:
    updated_cases: list[T04CaseResult] = []
    records: list[dict[str, Any]] = []
    originals: dict[tuple[str, str], T04EventUnitResult] = {}

    for case_result in case_results:
        updated_case = case_result
        for event_unit in case_result.event_units:
            record = _record_base(case_result, event_unit)
            records.append(record)
            if event_unit.selected_evidence_state != "none":
                record["skip_reason"] = "skipped_selected_evidence_present"
                continue
            mother_candidates = _rank_mother_candidates(event_unit.candidate_audit_entries)
            if not mother_candidates:
                record["skip_reason"] = "skipped_missing_aggregated_rcsd_unit"
                continue
            axis = _axis_context(case_result, event_unit)
            if not axis.get("axis_branch_id") or axis.get("axis_line") is None:
                record["skip_reason"] = "skipped_missing_axis_branch"
                continue
            mother = mother_candidates[0]
            aggregate_id, road_ids, node_ids = _cluster_ids(mother)
            record.update(
                {
                    "mother_candidate_id": mother.candidate_id,
                    "mother_candidate_node_fallback_only": bool(mother.candidate_summary.get("node_fallback_only")),
                    "mother_candidate_pool_rank": mother.pool_rank,
                    "mother_axis_position_m": _candidate_axis_position(mother),
                    "axis_branch_id": axis.get("axis_branch_id"),
                    "aggregated_rcsd_unit_id": aggregate_id,
                    "reverse_search_domain": {
                        "domain_type": "axis_driven_reverse_search_domain",
                        "event_type": event_unit.spec.event_type,
                        "axis_branch_id": axis.get("axis_branch_id"),
                        "unit_population_node_ids": list(event_unit.unit_envelope.unit_population_node_ids),
                        "step2_local_rcsdroad_count": len(case_result.case_bundle.rcsd_roads),
                        "step2_local_rcsdnode_count": len(case_result.case_bundle.rcsd_nodes),
                    },
                }
            )
            if not aggregate_id:
                record["skip_reason"] = "skipped_missing_aggregated_rcsd_unit"
                continue
            same_case_rcsd_conflict = any(
                _rcsd_claim_conflicts(
                    event_unit,
                    other,
                    aggregate_id=aggregate_id,
                    road_ids=road_ids,
                    node_ids=node_ids,
                    same_case=True,
                )
                for other in updated_case.event_units
                if other.spec.event_unit_id != event_unit.spec.event_unit_id
            )
            if same_case_rcsd_conflict:
                record["skip_reason"] = "skipped_same_case_rcsd_claim_conflict"
                continue
            node_samples, road_samples = _rcsd_anchor_samples(
                case_result,
                road_ids=road_ids,
                node_ids=node_ids,
                axis_context=axis,
            )
            sample_count = len(node_samples) + len(road_samples)
            record.update(
                {
                    "node_samples_s": node_samples,
                    "road_samples_s": road_samples,
                    "sample_count": sample_count,
                    "sample_kind_counts": {"node": len(node_samples), "road": len(road_samples)},
                }
            )
            if sample_count < MIN_RCSD_ANCHOR_SAMPLE_COUNT:
                record["skip_reason"] = "skipped_insufficient_rcsd_samples"
                continue
            updated_unit, detail = _apply_reverse_to_unit(
                case_result,
                event_unit,
                mother=mother,
                aggregate_id=aggregate_id,
                road_ids=road_ids,
                node_ids=node_ids,
                axis_context=axis,
                node_samples_s=node_samples,
                road_samples_s=road_samples,
            )
            same_case_evidence_conflict = any(
                _evidence_conflicts(
                    other,
                    summary=updated_unit.selected_evidence_summary,
                    component_geometry=updated_unit.selected_component_union_geometry,
                    core_geometry=updated_unit.localized_evidence_core_geometry,
                    same_case=True,
                )
                for other in updated_case.event_units
                if other.spec.event_unit_id != updated_unit.spec.event_unit_id
            )
            if same_case_evidence_conflict:
                record["skip_reason"] = "skipped_same_case_evidence_conflict"
                continue
            originals[(case_result.case_spec.case_id, event_unit.spec.event_unit_id)] = event_unit
            updated_case = _replace_unit(updated_case, event_unit.spec.event_unit_id, updated_unit)
            record.update(detail)
            record["post_state"] = updated_unit.selected_evidence_state
            record["skip_reason"] = None
        updated_cases.append(updated_case)

    updated_cases = _post_conflict_recheck(updated_cases, records, originals)
    applied_records = [item for item in records if item.get("skip_reason") is None and item.get("post_state") != item.get("pre_state")]
    return (
        updated_cases,
        {
            "scope": "t04_step4_rcsd_anchored_reverse",
            "triggered_count": len(applied_records),
            "skipped_count": len(records) - len(applied_records),
            "records": records,
        },
    )


__all__ = ["apply_rcsd_anchored_reverse_lookup"]
