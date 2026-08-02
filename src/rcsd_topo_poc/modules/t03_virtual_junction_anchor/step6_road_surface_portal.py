from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from .step6_business_connectivity import build_business_connectivity_audit


def _polygon_components(geometry: BaseGeometry | None) -> list[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if hasattr(geometry, "geoms"):
        return [
            part
            for item in geometry.geoms
            for part in _polygon_components(item)
        ]
    return []


def _clean_polygonal(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    polygons = _polygon_components(geometry)
    if not polygons:
        return None
    merged = unary_union(polygons)
    return None if merged.is_empty else merged


def _nearest_component_pair(
    components: list[BaseGeometry],
    left_ids: list[int],
    right_ids: list[int],
) -> tuple[BaseGeometry, BaseGeometry] | None:
    candidates = [
        (components[left_id].distance(components[right_id]), components[left_id], components[right_id])
        for left_id in left_ids
        for right_id in right_ids
        if left_id != right_id
    ]
    if not candidates:
        return None
    _distance, left, right = min(candidates, key=lambda item: item[0])
    return left, right


def build_road_surface_portal_boundary(
    *,
    allowed_surface: BaseGeometry | None,
    direction_boundary: BaseGeometry | None,
    terminals: dict[str, BaseGeometry],
    bridge_half_width_m: float,
    seed_missing_terminals: bool = True,
    allow_geodesic_growth: bool = False,
    geodesic_step_m: float = 2.0,
    geodesic_max_iterations: int = 25,
) -> tuple[BaseGeometry | None, BaseGeometry | None, dict[str, Any]]:
    allowed = _clean_polygonal(allowed_surface)
    boundary = _clean_polygonal(direction_boundary)
    before = build_business_connectivity_audit(
        source_surface=allowed,
        output_surface=boundary,
        terminals=terminals,
    )
    base_audit = {
        "mode": "road_surface_portal_boundary",
        "bridge_half_width_m": bridge_half_width_m,
        "seed_missing_terminals": seed_missing_terminals,
        "allow_geodesic_growth": allow_geodesic_growth,
        "before": before,
        "methods_attempted": [],
        "direct_bridge_count": 0,
        "envelope_fallback_applied": False,
        "source_geometry_modified": False,
        "silent_fix": False,
    }
    if (
        allowed is None
        or boundary is None
        or not before["comparable"]
        or before["equivalent"]
    ):
        return boundary, None, {
            **base_audit,
            "applied": False,
            "reason": (
                "connectivity_already_equivalent"
                if before["equivalent"]
                else "connectivity_not_comparable"
            ),
            "after": before,
            "added_area_m2": 0.0,
        }

    augmented = boundary
    added_geometries: list[BaseGeometry] = []
    missing_terminal_seed_geometries: list[BaseGeometry] = []
    for terminal_id in (
        before["output_missing_terminal_ids"] if seed_missing_terminals else []
    ):
        terminal = terminals.get(terminal_id)
        if terminal is None or terminal.is_empty:
            continue
        seed = _clean_polygonal(
            allowed.intersection(
                terminal.buffer(bridge_half_width_m)
            )
        )
        if seed is not None:
            missing_terminal_seed_geometries.append(seed)
    if missing_terminal_seed_geometries:
        augmented = _clean_polygonal(
            unary_union([augmented, *missing_terminal_seed_geometries])
        )
        added_geometries.extend(missing_terminal_seed_geometries)
    bridge_input_audit = build_business_connectivity_audit(
        source_surface=allowed,
        output_surface=augmented,
        terminals=terminals,
    )
    direct_bridge_count = 0
    for mismatch in bridge_input_audit["mismatches"]:
        if mismatch["mismatch_type"] != "source_connected_output_split":
            continue
        left_id = mismatch["left_terminal_id"]
        right_id = mismatch["right_terminal_id"]
        components = _polygon_components(augmented)
        current = build_business_connectivity_audit(
            source_surface=allowed,
            output_surface=augmented,
            terminals=terminals,
        )
        pair = _nearest_component_pair(
            components,
            current["output_terminal_component_ids"].get(left_id, []),
            current["output_terminal_component_ids"].get(right_id, []),
        )
        if pair is None:
            continue
        left_point, right_point = nearest_points(pair[0], pair[1])
        if left_point.equals(right_point):
            continue
        connector = LineString([left_point, right_point])
        bridge = _clean_polygonal(
            allowed.intersection(
                connector.buffer(
                    bridge_half_width_m,
                    cap_style=2,
                    join_style=2,
                )
            )
        )
        if bridge is None:
            continue
        candidate = _clean_polygonal(unary_union([augmented, bridge]))
        if candidate is None:
            continue
        augmented = candidate
        added_geometries.append(bridge)
        direct_bridge_count += 1

    direct_audit = build_business_connectivity_audit(
        source_surface=allowed,
        output_surface=augmented,
        terminals=terminals,
    )
    methods_attempted = []
    if missing_terminal_seed_geometries:
        methods_attempted.append("allowed_surface_constrained_missing_terminal_seed")
    methods_attempted.append("allowed_surface_constrained_nearest_bridge")
    envelope_applied = False
    if direct_audit["comparable"] and not direct_audit["equivalent"]:
        relevant_components: list[BaseGeometry] = []
        current_components = _polygon_components(augmented)
        relevant_component_ids = {
            component_id
            for mismatch in direct_audit["mismatches"]
            if mismatch["mismatch_type"] == "source_connected_output_split"
            for terminal_id in (
                mismatch["left_terminal_id"],
                mismatch["right_terminal_id"],
            )
            for component_id in direct_audit["output_terminal_component_ids"].get(
                terminal_id, []
            )
        }
        relevant_components.extend(
            current_components[component_id]
            for component_id in sorted(relevant_component_ids)
        )
        if relevant_components:
            envelope = unary_union(relevant_components).convex_hull
            envelope_bridge = _clean_polygonal(allowed.intersection(envelope))
            if envelope_bridge is not None:
                candidate = _clean_polygonal(unary_union([augmented, envelope_bridge]))
                if candidate is not None:
                    augmented = candidate
                    added_geometries.append(envelope_bridge)
                    envelope_applied = True
        methods_attempted.append("allowed_surface_constrained_business_envelope")

    post_envelope_audit = build_business_connectivity_audit(
        source_surface=allowed,
        output_surface=augmented,
        terminals=terminals,
    )
    geodesic_growth_applied = False
    geodesic_growth_iterations = 0
    allowed_component_fallback_applied = False
    allowed_component_fallback_audit: dict[str, Any] = {
        "attempted": False,
        "relevant_allowed_component_ids": [],
        "candidate_equivalent": None,
        "candidate_mismatch_count": None,
        "candidate_output_missing_terminal_ids": [],
        "candidate_area_m2": None,
        "relevant_allowed_component_area_m2": None,
        "relevant_component_missing_area_m2": None,
        "candidate_basis": None,
    }
    if (
        allow_geodesic_growth
        and post_envelope_audit["comparable"]
        and not post_envelope_audit["equivalent"]
    ):
        current_components = _polygon_components(augmented)
        relevant_component_ids = {
            component_id
            for mismatch in post_envelope_audit["mismatches"]
            if mismatch["mismatch_type"] == "source_connected_output_split"
            for terminal_id in (
                mismatch["left_terminal_id"],
                mismatch["right_terminal_id"],
            )
            for component_id in post_envelope_audit[
                "output_terminal_component_ids"
            ].get(terminal_id, [])
        }
        growth = _clean_polygonal(
            unary_union(
                [
                    current_components[component_id]
                    for component_id in sorted(relevant_component_ids)
                ]
            )
            if relevant_component_ids
            else None
        )
        if growth is not None:
            for iteration in range(1, geodesic_max_iterations + 1):
                growth = _clean_polygonal(
                    allowed.intersection(growth.buffer(geodesic_step_m))
                )
                if growth is None:
                    break
                candidate = _clean_polygonal(unary_union([augmented, growth]))
                candidate_audit = build_business_connectivity_audit(
                    source_surface=allowed,
                    output_surface=candidate,
                    terminals=terminals,
                )
                if candidate_audit["equivalent"]:
                    augmented = candidate
                    added_geometries.append(growth)
                    geodesic_growth_applied = True
                    geodesic_growth_iterations = iteration
                    break
        methods_attempted.append("allowed_surface_constrained_geodesic_growth")

    post_geodesic_audit = build_business_connectivity_audit(
        source_surface=allowed,
        output_surface=augmented,
        terminals=terminals,
    )
    if (
        allow_geodesic_growth
        and post_geodesic_audit["comparable"]
        and not post_geodesic_audit["equivalent"]
    ):
        allowed_components = _polygon_components(allowed)
        relevant_allowed_component_ids = {
            component_id
            for mismatch in post_geodesic_audit["mismatches"]
            if mismatch["mismatch_type"] == "source_connected_output_split"
            for terminal_id in (
                mismatch["left_terminal_id"],
                mismatch["right_terminal_id"],
            )
            for component_id in post_geodesic_audit[
                "source_terminal_component_ids"
            ].get(terminal_id, [])
        }
        relevant_allowed_components = [
            allowed_components[component_id]
            for component_id in sorted(relevant_allowed_component_ids)
        ]
        allowed_component_fallback_audit = {
            **allowed_component_fallback_audit,
            "attempted": True,
            "relevant_allowed_component_ids": sorted(
                relevant_allowed_component_ids
            ),
        }
        if relevant_allowed_components:
            relevant_allowed_geometry = _clean_polygonal(
                unary_union(relevant_allowed_components)
            )
            candidate = relevant_allowed_geometry
            candidate_audit = build_business_connectivity_audit(
                source_surface=allowed,
                output_surface=candidate,
                terminals=terminals,
            )
            relevant_component_missing_area_m2 = (
                relevant_allowed_geometry.difference(candidate).area
                if relevant_allowed_geometry is not None and candidate is not None
                else None
            )
            allowed_component_fallback_audit = {
                **allowed_component_fallback_audit,
                "candidate_equivalent": candidate_audit["equivalent"],
                "candidate_mismatch_count": candidate_audit["mismatch_count"],
                "candidate_output_missing_terminal_ids": candidate_audit[
                    "output_missing_terminal_ids"
                ],
                "candidate_area_m2": (
                    round(candidate.area, 6) if candidate is not None else None
                ),
                "relevant_allowed_component_area_m2": (
                    round(relevant_allowed_geometry.area, 6)
                    if relevant_allowed_geometry is not None
                    else None
                ),
                "relevant_component_missing_area_m2": (
                    round(relevant_component_missing_area_m2, 9)
                    if relevant_component_missing_area_m2 is not None
                    else None
                ),
                "candidate_basis": (
                    "complete_constrained_allowed_components_for_"
                    "mismatched_business_terminals"
                ),
            }
            if candidate_audit["equivalent"]:
                augmented = candidate
                added_geometries.extend(relevant_allowed_components)
                allowed_component_fallback_applied = True
        methods_attempted.append(
            "allowed_surface_relevant_component_edge_trace"
        )

    after = build_business_connectivity_audit(
        source_surface=allowed,
        output_surface=augmented,
        terminals=terminals,
    )
    portal_geometry = _clean_polygonal(
        unary_union(added_geometries).difference(boundary)
        if added_geometries
        else None
    )
    return augmented, portal_geometry, {
        **base_audit,
        "applied": portal_geometry is not None,
        "reason": (
            "connectivity_restored"
            if after["equivalent"]
            else "legal_surface_portal_not_found"
        ),
        "methods_attempted": methods_attempted,
        "missing_terminal_seed_count": len(missing_terminal_seed_geometries),
        "direct_bridge_count": direct_bridge_count,
        "envelope_fallback_applied": envelope_applied,
        "geodesic_growth_applied": geodesic_growth_applied,
        "geodesic_growth_iterations": geodesic_growth_iterations,
        "geodesic_growth_distance_m": round(
            geodesic_growth_iterations * geodesic_step_m,
            6,
        ),
        "allowed_component_fallback_applied": (
            allowed_component_fallback_applied
        ),
        "allowed_component_fallback_audit": allowed_component_fallback_audit,
        "after": after,
        "added_area_m2": round(portal_geometry.area, 6) if portal_geometry is not None else 0.0,
    }
