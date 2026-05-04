from __future__ import annotations

import heapq
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




__all__ = [name for name in globals() if not name.startswith("__")]
