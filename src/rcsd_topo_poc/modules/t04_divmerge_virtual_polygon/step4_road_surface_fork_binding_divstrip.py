from __future__ import annotations

from dataclasses import replace
from typing import Any

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .case_models import T04CaseResult, T04EventUnitResult
from .step4_road_surface_fork_binding_shared import (
    DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_LENGTH_M,
    DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_WIDTH_M,
    DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_BRANCH_SEPARATION_M,
    DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
    _candidate_entries_with_selection,
    _degraded_divstrip_entry,
)
from .step4_road_surface_fork_geometry import _as_float, _clean_surface_review_reasons, _dedupe, _union_geometries


def _surface_fork_branch_separation_m(
    replacement: T04EventUnitResult,
    detail: dict[str, Any] | None,
) -> float | None:
    details: list[dict[str, Any]] = []
    if isinstance(detail, dict):
        details.append(detail)
    summary_detail = replacement.selected_evidence_summary.get("road_surface_fork_binding")
    if isinstance(summary_detail, dict):
        details.append(summary_detail)
    candidate_detail = replacement.selected_candidate_summary.get("road_surface_fork_binding")
    if isinstance(candidate_detail, dict):
        details.append(candidate_detail)
    for item in details:
        reference = item.get("reference_point")
        if isinstance(reference, dict):
            value = _as_float(reference.get("road_surface_fork_branch_separation_m"))
            if value is not None:
                return value
        value = _as_float(item.get("road_surface_fork_branch_separation_m"))
        if value is not None:
            return value
    return None

def _reference_axis_vector(event_unit: T04EventUnitResult) -> tuple[float, float] | None:
    bridge = event_unit.interpretation.legacy_step5_bridge
    vector = getattr(bridge, "event_axis_unit_vector", None)
    if vector and len(vector) >= 2:
        vx = float(vector[0])
        vy = float(vector[1])
        length = (vx * vx + vy * vy) ** 0.5
        if length > 1e-6:
            return (vx / length, vy / length)
    axis_line = getattr(bridge, "event_axis_centerline", None)
    geometry = getattr(axis_line, "geometry", axis_line)
    coords = list(getattr(geometry, "coords", []) or [])
    if len(coords) >= 2:
        vx = float(coords[-1][0]) - float(coords[0][0])
        vy = float(coords[-1][1]) - float(coords[0][1])
        length = (vx * vx + vy * vy) ** 0.5
        if length > 1e-6:
            return (vx / length, vy / length)
    return None

def _divstrip_reference_window_surface(
    event_unit: T04EventUnitResult,
    reference_point: Point,
    surface_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    if surface_geometry is None or surface_geometry.is_empty:
        return None
    vector = _reference_axis_vector(event_unit)
    if vector is None:
        return surface_geometry.intersection(
            reference_point.buffer(DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_LENGTH_M, cap_style=1, join_style=2)
        )
    vx, vy = vector
    nx, ny = -vy, vx
    x = float(reference_point.x)
    y = float(reference_point.y)
    length = DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_LENGTH_M
    width = DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_WIDTH_M
    window = Polygon(
        [
            (x - vx * length - nx * width, y - vy * length - ny * width),
            (x + vx * length - nx * width, y + vy * length - ny * width),
            (x + vx * length + nx * width, y + vy * length + ny * width),
            (x - vx * length + nx * width, y - vy * length + ny * width),
            (x - vx * length - nx * width, y - vy * length - ny * width),
        ]
    )
    clipped = surface_geometry.intersection(window)
    return clipped if not clipped.is_empty else None

def _polygon_parts(geometry: BaseGeometry | None) -> tuple[Polygon, ...]:
    if geometry is None or geometry.is_empty:
        return ()
    if isinstance(geometry, Polygon):
        return (geometry,)
    if isinstance(geometry, MultiPolygon):
        return tuple(part for part in geometry.geoms if isinstance(part, Polygon) and not part.is_empty)
    return ()

def _divstrip_disambiguation_anchor(
    event_unit: T04EventUnitResult,
    replacement: T04EventUnitResult,
    fallback_point: Point,
) -> Point:
    representative_node = getattr(event_unit.unit_context, "representative_node", None)
    for geometry in (
        getattr(representative_node, "geometry", None),
        replacement.required_rcsd_node_geometry,
        replacement.primary_main_rc_node_geometry,
        replacement.review_materialized_point,
    ):
        if isinstance(geometry, Point) and not geometry.is_empty:
            return geometry
    return fallback_point

def _nearest_boundary_point(polygon: Polygon, anchor: Point) -> Point:
    boundary = polygon.boundary
    if boundary is None or boundary.is_empty:
        return polygon.representative_point()
    point, _anchor = nearest_points(boundary, anchor)
    return point if isinstance(point, Point) else polygon.representative_point()

def _best_divstrip_component(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    replacement: T04EventUnitResult,
    fallback_point: Point,
) -> tuple[Polygon | None, Point, int | None]:
    anchor = _divstrip_disambiguation_anchor(event_unit, replacement, fallback_point)
    candidates: list[tuple[float, float, int, Polygon]] = []
    for feature in case_result.case_bundle.divstrip_features:
        for index, polygon in enumerate(_polygon_parts(getattr(feature, "geometry", None))):
            candidates.append((float(polygon.distance(anchor)), -float(polygon.area), index, polygon))
    if not candidates:
        return (None, fallback_point, None)
    candidates.sort(key=lambda item: item[:3])
    _distance, _area, index, polygon = candidates[0]
    return (polygon, _nearest_boundary_point(polygon, anchor), index)

def _restore_divstrip_primary_for_wide_surface_fork(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    replacement: T04EventUnitResult,
    detail: dict[str, Any] | None,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state != "none":
        return None, None
    if replacement.evidence_source != "road_surface_fork":
        return None, None
    if str(event_unit.spec.event_type or "") != "simple":
        return None, None
    divstrip_entry = _degraded_divstrip_entry(event_unit)
    if divstrip_entry is None:
        return None, None
    branch_separation = _surface_fork_branch_separation_m(replacement, detail)
    if (
        branch_separation is None
        or branch_separation < DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_BRANCH_SEPARATION_M
    ):
        return None, None
    fact_reference_point = divstrip_entry.fact_reference_point
    if not isinstance(fact_reference_point, Point):
        fact_reference_point = divstrip_entry.review_materialized_point
    if not isinstance(fact_reference_point, Point):
        return None, None
    divstrip_component, component_reference_point, component_index = _best_divstrip_component(
        case_result,
        event_unit,
        replacement,
        fact_reference_point,
    )
    fact_reference_point = component_reference_point

    evidence_source = str(divstrip_entry.evidence_source or divstrip_entry.candidate_summary.get("evidence_source") or "reverse_tip_retry")
    position_source = str(divstrip_entry.position_source or divstrip_entry.candidate_summary.get("position_source") or "divstrip_ref")
    review_reasons = _dedupe(
        [
            *_clean_surface_review_reasons(divstrip_entry.review_reasons),
            DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
        ]
    )
    summary = dict(divstrip_entry.candidate_summary)
    candidate_id = divstrip_entry.candidate_id
    if component_index is not None:
        candidate_id = f"{event_unit.spec.event_unit_id}:divstrip:{component_index}:01"
        summary.update(
            {
                "candidate_id": candidate_id,
                "upper_evidence_object_id": str(component_index),
                "local_region_id": candidate_id,
                "ownership_signature": f"divstrip:{component_index}:{candidate_id}",
                "point_signature": (
                    f"divstrip:{component_index}:"
                    f"{float(fact_reference_point.x):.3f}:"
                    f"{float(fact_reference_point.y):.3f}"
                ),
                "component_disambiguated_reference_point_xy": [
                    round(float(fact_reference_point.x), 3),
                    round(float(fact_reference_point.y), 3),
                ],
            }
        )
    bind_detail = {
        "action": DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
        "candidate_id": candidate_id,
        "original_candidate_id": divstrip_entry.candidate_id,
        "selected_divstrip_component_index": component_index,
        "suppressed_road_surface_fork_branch_separation_m": round(float(branch_separation), 3),
        "suppressed_road_surface_fork_binding": dict(detail or {}),
    }
    summary.update(
        {
            "primary_eligible": True,
            "selection_status": "selected",
            "selected_evidence_state": "found",
            "decision_reason": DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
            "review_state": "STEP4_REVIEW",
            "review_reasons": list(review_reasons),
            "evidence_source": evidence_source,
            "position_source": position_source,
            "rcsd_consistency_result": replacement.rcsd_consistency_result,
            "positive_rcsd_present": bool(replacement.positive_rcsd_present),
            "positive_rcsd_present_reason": replacement.positive_rcsd_present_reason,
            "positive_rcsd_support_level": replacement.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": replacement.positive_rcsd_consistency_level,
            "required_rcsd_node": replacement.required_rcsd_node,
            "required_rcsd_node_source": replacement.required_rcsd_node_source,
            "rcsd_selection_mode": replacement.rcsd_selection_mode,
            "rcsd_decision_reason": replacement.positive_rcsd_audit.get("rcsd_decision_reason"),
            "divstrip_primary_over_wide_road_surface_fork": True,
            "selected_divstrip_component_index": component_index,
            "suppressed_road_surface_fork_branch_separation_m": round(float(branch_separation), 3),
        }
    )
    updated_entry = replace(
        divstrip_entry,
        selection_status="selected",
        decision_reason=DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=evidence_source,
        position_source=position_source,
        rcsd_consistency_result=replacement.rcsd_consistency_result,
        positive_rcsd_support_level=replacement.positive_rcsd_support_level,
        positive_rcsd_consistency_level=replacement.positive_rcsd_consistency_level,
        required_rcsd_node=replacement.required_rcsd_node,
        fact_reference_point=fact_reference_point,
        review_materialized_point=fact_reference_point,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        updated_entry,
        summary,
    )
    updated_audit = dict(replacement.positive_rcsd_audit)
    updated_audit.update(
        {
            "divstrip_primary_over_wide_road_surface_fork": True,
            "selected_divstrip_component_index": component_index,
            "suppressed_road_surface_fork_branch_separation_m": round(float(branch_separation), 3),
            "suppressed_road_surface_fork_binding": dict(detail or {}),
        }
    )
    source_surface = (
        replacement.selected_candidate_region_geometry
        or replacement.selected_component_union_geometry
        or replacement.pair_local_structure_face_geometry
    )
    window_surface = _divstrip_reference_window_surface(
        replacement,
        fact_reference_point,
        source_surface,
    )
    localized_core = (
        divstrip_component
        or
        divstrip_entry.localized_evidence_core_geometry
        or divstrip_entry.selected_evidence_region_geometry
        or divstrip_entry.candidate_region_geometry
        or divstrip_entry.selected_component_union_geometry
    )
    selected_region = _union_geometries([window_surface, localized_core]) or localized_core
    selected_component = selected_region
    updated = replace(
        replacement,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=evidence_source,
        position_source=position_source,
        reverse_tip_used=bool(divstrip_entry.reverse_tip_used),
        selected_component_union_geometry=selected_component,
        localized_evidence_core_geometry=localized_core,
        pair_local_structure_face_geometry=selected_region,
        pair_local_middle_geometry=selected_region,
        selected_candidate_region_geometry=selected_region,
        selected_evidence_region_geometry=selected_region,
        selected_candidate_region=divstrip_entry.selected_candidate_region or replacement.selected_candidate_region,
        fact_reference_point=fact_reference_point,
        review_materialized_point=fact_reference_point,
        selected_branch_ids=divstrip_entry.selected_branch_ids,
        selected_event_branch_ids=divstrip_entry.selected_event_branch_ids,
        selected_component_ids=divstrip_entry.selected_component_ids,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        required_rcsd_node_geometry=None,
        conflict_resolution_action=DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
        post_resolution_candidate_id=candidate_id,
        resolution_reason=DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON,
    )
    return updated, bind_detail
