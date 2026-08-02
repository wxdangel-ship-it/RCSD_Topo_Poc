from __future__ import annotations

from typing import Any, Iterable

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .step6_business_connectivity import (
    BusinessConnectivityCache,
    build_business_connectivity_audit,
)


COMPACT_SEMANTIC_TARGET_MAX_SPAN_M = 12.0


def _clean_polygonal(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    # 本步骤只消费上游已验证的派生面；无效几何必须显式拒绝，不能在此
    # 通过 buffer(0) 静默改变拓扑语义。
    if not geometry.is_valid:
        return None
    cleaned = geometry
    if cleaned.is_empty:
        return None
    if cleaned.geom_type in {"Polygon", "MultiPolygon"}:
        return cleaned
    polygons = [
        part
        for part in getattr(cleaned, "geoms", ())
        if part.geom_type in {"Polygon", "MultiPolygon"} and not part.is_empty
    ]
    if not polygons:
        return None
    merged = unary_union(polygons)
    return None if merged.is_empty else merged


def _target_points(
    target_geometries: Iterable[BaseGeometry],
) -> list[BaseGeometry]:
    return [
        geometry
        if geometry.geom_type == "Point"
        else geometry.representative_point()
        for geometry in target_geometries
        if geometry is not None and not geometry.is_empty
    ]


def _minimum_spanning_lines(points: list[BaseGeometry]) -> list[LineString]:
    if len(points) < 2:
        return []
    connected = {0}
    remaining = set(range(1, len(points)))
    lines: list[LineString] = []
    while remaining:
        _distance, left_index, right_index = min(
            (
                points[left].distance(points[right]),
                left,
                right,
            )
            for left in connected
            for right in remaining
        )
        lines.append(
            LineString(
                [
                    points[left_index].coords[0],
                    points[right_index].coords[0],
                ]
            )
        )
        connected.add(right_index)
        remaining.remove(right_index)
    return lines


def restore_compact_semantic_target_connectivity(
    *,
    surface: BaseGeometry | None,
    raw_road_surface: BaseGeometry | None,
    allowed_surface: BaseGeometry | None,
    target_geometries: Iterable[BaseGeometry],
    terminals: dict[str, BaseGeometry],
    association_reason: str,
    input_geometry_invalid_feature_count: int,
    bridge_half_width_m: float,
    max_target_span_m: float = COMPACT_SEMANTIC_TARGET_MAX_SPAN_M,
    connectivity_cache: BusinessConnectivityCache | None = None,
) -> tuple[BaseGeometry | None, BaseGeometry | None, dict[str, Any]]:
    """Restore a compact mainNode alias portal inside frozen legal space.

    Raw Road-surface is the connectivity oracle. The source is never changed,
    and a candidate is published only when its terminal partition is exactly
    equivalent to that oracle.
    """

    current = _clean_polygonal(surface)
    raw = _clean_polygonal(raw_road_surface)
    allowed = _clean_polygonal(allowed_surface)
    points = _target_points(target_geometries)
    target_span_m = max(
        (left.distance(right) for left in points for right in points),
        default=0.0,
    )
    before = build_business_connectivity_audit(
        source_surface=raw,
        output_surface=current,
        terminals=terminals,
        cache=connectivity_cache,
    )
    base_audit = {
        "mode": "compact_semantic_target_road_surface_portal",
        "association_reason": association_reason,
        "target_count": len(points),
        "target_span_m": round(float(target_span_m), 6),
        "max_target_span_m": max_target_span_m,
        "bridge_half_width_m": bridge_half_width_m,
        "input_geometry_invalid_feature_count": int(
            input_geometry_invalid_feature_count
        ),
        "source_surface_role": "raw_drivezone_connectivity_oracle",
        "permitted_surface_role": "step3_frozen_allowed_road_surface",
        "before": before,
        "source_geometry_modified": False,
        "silent_fix": False,
    }
    eligibility_failures: list[str] = []
    if association_reason != "association_support_only":
        eligibility_failures.append("association_not_support_only")
    if len(points) < 2:
        eligibility_failures.append("semantic_target_count_below_two")
    if target_span_m > max_target_span_m:
        eligibility_failures.append("semantic_target_span_above_gate")
    if input_geometry_invalid_feature_count > 0:
        eligibility_failures.append("input_geometry_invalid")
    if current is None or raw is None or allowed is None:
        eligibility_failures.append("surface_missing")
    if not before["comparable"]:
        eligibility_failures.append("raw_connectivity_not_comparable")
    if before["equivalent"]:
        eligibility_failures.append("raw_connectivity_already_equivalent")
    if eligibility_failures:
        return current, None, {
            **base_audit,
            "applied": False,
            "reason": eligibility_failures[0],
            "eligibility_failures": eligibility_failures,
            "after": before,
            "added_area_m2": 0.0,
        }

    target_lines = _minimum_spanning_lines(points)
    portal_candidate = _clean_polygonal(
        allowed.intersection(
            unary_union(target_lines).buffer(
                bridge_half_width_m,
                cap_style=2,
                join_style=2,
            )
        )
        if target_lines
        else None
    )
    candidate = _clean_polygonal(
        unary_union([current, portal_candidate])
        if portal_candidate is not None
        else current
    )
    after = build_business_connectivity_audit(
        source_surface=raw,
        output_surface=candidate,
        terminals=terminals,
        cache=connectivity_cache,
    )
    if not after["equivalent"]:
        return current, None, {
            **base_audit,
            "applied": False,
            "reason": "compact_legal_portal_did_not_restore_connectivity",
            "eligibility_failures": [],
            "after": after,
            "added_area_m2": 0.0,
        }
    added = _clean_polygonal(candidate.difference(current))
    return candidate, added, {
        **base_audit,
        "applied": added is not None,
        "reason": "compact_semantic_target_connectivity_restored",
        "eligibility_failures": [],
        "after": after,
        "added_area_m2": round(added.area, 6) if added is not None else 0.0,
    }
