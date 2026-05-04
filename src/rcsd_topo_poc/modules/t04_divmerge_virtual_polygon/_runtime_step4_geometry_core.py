from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations, permutations
from typing import Any, Optional, Sequence

import numpy as np
from shapely.geometry import GeometryCollection, LineString, Point
from shapely.ops import linemerge, nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, T02RunError, normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    BRANCH_MATCH_TOLERANCE_DEG,
    DEFAULT_PATCH_SIZE_M,
    DEFAULT_RESOLUTION_M,
    MAIN_AXIS_ANGLE_TOLERANCE_DEG,
    NODE_SEED_RADIUS_M,
    RC_NODE_SEED_RADIUS_M,
    RC_ROAD_BUFFER_M,
    ROAD_BUFFER_M,
    ParsedNode,
    ParsedRoad,
    _binary_close,
    _branch_candidate_from_center_proximity,
    _branch_candidate_from_road,
    _build_grid,
    _cluster_branch_candidates,
    _extract_seed_component,
    _mask_to_geometry,
    _rasterize_geometries,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_polygon_cleanup import (
    _regularize_virtual_polygon_geometry,
)
from ._runtime_step4_geometry_constants import *

def _analyze_divstrip_context(
    *,
    local_divstrip_features: list[Any],
    seed_union,
    road_branches,
    local_roads: list[ParsedRoad],
    main_branch_ids: set[str],
    drivezone_union,
    event_branch_ids: set[str] | None = None,
    allow_compound_pair_merge: bool = False,
    excluded_component_geometries: list[Any] | None = None,
) -> dict[str, Any]:
    event_anchor_geometry = _estimate_event_anchor_geometry(
        local_roads=local_roads,
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        drivezone_union=drivezone_union,
        event_branch_ids=event_branch_ids,
    )
    if not local_divstrip_features:
        return {
            "present": False,
            "nearby": False,
            "component_count": 0,
            "selected_component_ids": [],
            "constraint_geometry": GeometryCollection(),
            "preferred_branch_ids": [],
            "ambiguous": False,
            "selection_mode": "roads_fallback",
            "evidence_source": "drivezone+roads+rcsd+seed",
            "event_anchor_geometry": event_anchor_geometry,
        }

    union_geometry = unary_union(
        [feature.geometry for feature in local_divstrip_features if feature.geometry is not None and not feature.geometry.is_empty]
    )
    components = _explode_component_geometries(union_geometry)
    non_main_branches = [branch for branch in road_branches if branch.branch_id not in main_branch_ids]
    candidate_branch_ids = set(event_branch_ids or ())
    candidate_branches = [
        branch
        for branch in (non_main_branches or list(road_branches))
        if not candidate_branch_ids or branch.branch_id in candidate_branch_ids
    ] or (non_main_branches or list(road_branches))
    branch_geometry_lookup = {
        branch.branch_id: unary_union([road.geometry for road in local_roads if road.road_id in branch.road_ids])
        for branch in candidate_branches
    }
    all_branch_geometry_lookup = {
        branch.branch_id: unary_union([road.geometry for road in local_roads if road.road_id in branch.road_ids])
        for branch in road_branches
    }
    road_union = unary_union([road.geometry for road in local_roads if road.geometry is not None and not road.geometry.is_empty])
    road_lookup = {road.road_id: road for road in local_roads}
    reference_point = (
        event_anchor_geometry.representative_point()
        if event_anchor_geometry is not None and not event_anchor_geometry.is_empty
        else seed_union.representative_point()
    )
    component_reference_segment = None
    reference_branch_candidates: list[tuple[float, int, Any]] = []
    for branch in road_branches:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        if centerline is None or centerline.is_empty:
            continue
        reference_branch_candidates.append(
            (
                float(centerline.distance(reference_point)),
                1 if branch.branch_id in candidate_branch_ids else 0,
                branch,
            )
        )
    reference_branch_candidates.sort(key=lambda item: (float(item[0]), -int(item[1]), -_selected_branch_score(item[2])))
    reference_branches = [item[2] for item in reference_branch_candidates[:2]]
    reference_branch_a = reference_branches[0] if len(reference_branches) >= 1 else None
    reference_branch_b = reference_branches[1] if len(reference_branches) >= 2 else None
    if reference_branch_a is not None and reference_branch_b is not None:
        reference_centerline_a = _resolve_branch_centerline(
            branch=reference_branch_a,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        reference_centerline_b = _resolve_branch_centerline(
            branch=reference_branch_b,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        if (
            reference_centerline_a is not None
            and not reference_centerline_a.is_empty
            and reference_centerline_b is not None
            and not reference_centerline_b.is_empty
        ):
            point_a = nearest_points(reference_centerline_a, reference_point)[0]
            point_b = nearest_points(reference_centerline_b, reference_point)[0]
            if float(point_a.distance(point_b)) > 1e-6:
                component_reference_segment = LineString(
                    [
                        (float(point_a.x), float(point_a.y)),
                        (float(point_b.x), float(point_b.y)),
                    ]
                )

    valid_excluded_geometries = [
        geometry
        for geometry in (excluded_component_geometries or [])
        if geometry is not None and not geometry.is_empty
    ]

    def _component_is_excluded_by_prior_unit(component_geometry) -> bool:
        if not valid_excluded_geometries:
            return False
        component_area = float(getattr(component_geometry, "area", 0.0) or 0.0)
        for excluded_geometry in valid_excluded_geometries:
            try:
                overlap = component_geometry.intersection(excluded_geometry)
            except Exception:
                continue
            overlap_area = float(getattr(overlap, "area", 0.0) or 0.0)
            if overlap_area <= 1e-6:
                if float(component_geometry.distance(excluded_geometry)) > 0.5:
                    continue
            excluded_area = float(getattr(excluded_geometry, "area", 0.0) or 0.0)
            smaller_area = min(component_area, excluded_area)
            if smaller_area <= 1e-6:
                if float(component_geometry.distance(excluded_geometry)) <= 0.5:
                    return True
                continue
            overlap_ratio = overlap_area / smaller_area if smaller_area > 1e-6 else 0.0
            if overlap_area >= 4.0 or overlap_ratio >= 0.15:
                return True
            if (
                float(component_geometry.distance(excluded_geometry)) <= 0.25
                and overlap_ratio >= 0.05
            ):
                return True
        return False

    nearby_components: list[dict[str, Any]] = []
    for component_index, component_geometry in enumerate(components):
        matched_branch_ids = sorted(
            branch_id
            for branch_id, branch_geometry in branch_geometry_lookup.items()
            if branch_geometry is not None
            and not branch_geometry.is_empty
            and branch_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2).intersects(component_geometry)
        )
        matched_all_branch_ids = sorted(
            branch_id
            for branch_id, branch_geometry in all_branch_geometry_lookup.items()
            if branch_geometry is not None
            and not branch_geometry.is_empty
            and branch_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2).intersects(component_geometry)
        )
        distance_to_seed = float(component_geometry.distance(seed_union))
        distance_to_roads = (
            math.inf
            if road_union is None or road_union.is_empty
            else float(component_geometry.distance(road_union))
        )
        distance_to_event_anchor = (
            math.inf
            if event_anchor_geometry is None or event_anchor_geometry.is_empty
            else float(component_geometry.distance(event_anchor_geometry))
        )
        related_to_branch_middle, distance_to_branch_middle, branch_middle_overlap = _component_reference_overlap_metrics(
            component_geometry=component_geometry,
            reference_geometry=component_reference_segment,
            reference_buffer_m=max(float(DIVSTRIP_BRANCH_BUFFER_M), 2.0),
        )
        if (
            matched_branch_ids
            or matched_all_branch_ids
            or distance_to_seed <= DIVSTRIP_NEARBY_DISTANCE_M
            or distance_to_event_anchor <= DIVSTRIP_NEARBY_DISTANCE_M
            or distance_to_roads <= DIVSTRIP_CONTEXT_ROAD_DISTANCE_M
            or (
                distance_to_roads <= DIVSTRIP_ROAD_NEARBY_DISTANCE_M
                and distance_to_seed <= DIVSTRIP_SEED_FALLBACK_DISTANCE_M
            )
        ):
            nearby_components.append(
                {
                    "component_id": f"divstrip_component_{component_index}",
                    "geometry": component_geometry,
                    "matched_branch_ids": matched_branch_ids,
                    "matched_all_branch_ids": matched_all_branch_ids,
                    "distance_to_seed": distance_to_seed,
                    "distance_to_roads": distance_to_roads,
                    "distance_to_event_anchor": distance_to_event_anchor,
                    "distance_to_branch_middle": distance_to_branch_middle,
                    "related_to_branch_middle": related_to_branch_middle,
                    "branch_middle_overlap": branch_middle_overlap,
                    "component_area": float(getattr(component_geometry, "area", 0.0) or 0.0),
                    "is_excluded_by_prior_unit": _component_is_excluded_by_prior_unit(component_geometry),
                }
            )

    if not nearby_components:
        return {
            "present": True,
            "nearby": False,
            "component_count": len(components),
            "selected_component_ids": [],
            "constraint_geometry": GeometryCollection(),
            "preferred_branch_ids": [],
            "ambiguous": False,
            "selection_mode": "roads_fallback",
            "evidence_source": "drivezone+roads+rcsd+seed",
            "event_anchor_geometry": event_anchor_geometry,
        }

    matched_components = [
        component
        for component in nearby_components
        if component["matched_branch_ids"] or component["matched_all_branch_ids"]
    ]
    anchor_preferred_components = [
        component
        for component in nearby_components
        if float(component["distance_to_event_anchor"])
        <= max(DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.65, EVENT_ANCHOR_BUFFER_M * 3.0)
    ]
    road_nearby_components = [
        component
        for component in nearby_components
        if component["distance_to_roads"] <= DIVSTRIP_ROAD_NEARBY_DISTANCE_M
    ]
    if allow_compound_pair_merge:
        branch_middle_components = [
            component
            for component in nearby_components
            if bool(component["related_to_branch_middle"]) or float(component["branch_middle_overlap"]) > 1e-6
        ]
        if branch_middle_components:
            candidate_components = branch_middle_components
        else:
            candidate_components = matched_components or road_nearby_components or nearby_components
        if valid_excluded_geometries and candidate_components and all(
            bool(component.get("is_excluded_by_prior_unit"))
            for component in candidate_components
        ):
            seen_candidate_ids: set[str] = {
                str(component["component_id"]) for component in candidate_components
            }
            broader_pool: list[dict[str, Any]] = []
            for component in [*matched_components, *road_nearby_components, *nearby_components]:
                cid = str(component["component_id"])
                if cid in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(cid)
                broader_pool.append(component)
            broader_non_excluded = [
                component
                for component in broader_pool
                if not bool(component.get("is_excluded_by_prior_unit"))
            ]
            if broader_non_excluded:
                candidate_components = broader_non_excluded
    else:
        candidate_components = []
        seen_candidate_component_ids: set[str] = set()
        for component in [*matched_components, *anchor_preferred_components, *road_nearby_components, *nearby_components]:
            component_id = str(component["component_id"])
            if component_id in seen_candidate_component_ids:
                continue
            seen_candidate_component_ids.add(component_id)
            candidate_components.append(component)
    if valid_excluded_geometries and candidate_components:
        non_excluded_candidates = [
            component
            for component in candidate_components
            if not bool(component.get("is_excluded_by_prior_unit"))
        ]
        if non_excluded_candidates:
            candidate_components = non_excluded_candidates
    if allow_compound_pair_merge:
        has_branch_middle_signal = any(
            bool(component["related_to_branch_middle"]) or float(component["branch_middle_overlap"]) > 1e-6
            for component in candidate_components
        )
        large_component_area_threshold = max(
            80.0,
            0.35 * max(float(component["component_area"]) for component in candidate_components),
        )
        if has_branch_middle_signal:
            candidate_components.sort(
                key=lambda component: (
                    0 if component["related_to_branch_middle"] else 1,
                    float(component["distance_to_branch_middle"]),
                    -float(component["branch_middle_overlap"]),
                    0 if float(component["component_area"]) >= large_component_area_threshold else 1,
                    -float(component["component_area"]),
                    float(component["distance_to_event_anchor"]),
                    -len(component["matched_branch_ids"]),
                    -len(component["matched_all_branch_ids"]),
                    float(component["distance_to_roads"]),
                    float(component["distance_to_seed"]),
                ),
            )
        else:
            candidate_components.sort(
                key=lambda component: (
                    -len(component["matched_branch_ids"]),
                    -len(component["matched_all_branch_ids"]),
                    0 if float(component["component_area"]) >= large_component_area_threshold else 1,
                    -float(component["component_area"]),
                    float(component["distance_to_event_anchor"]),
                    float(component["distance_to_seed"]),
                    float(component["distance_to_roads"]),
                ),
            )
    else:
        large_component_area_threshold = max(
            80.0,
            0.35 * max(float(component["component_area"]) for component in candidate_components),
        )
        candidate_components.sort(
            key=lambda component: (
                0 if component["related_to_branch_middle"] else 1,
                float(component["distance_to_branch_middle"]),
                -float(component["branch_middle_overlap"]),
                -len(component["matched_branch_ids"]),
                -len(component["matched_all_branch_ids"]),
                0 if float(component["component_area"]) >= large_component_area_threshold else 1,
                -float(component["component_area"]),
                float(component["distance_to_event_anchor"]),
                float(component["distance_to_seed"]),
                float(component["distance_to_roads"]),
            ),
        )

    def _component_branch_ids(component: dict[str, Any]) -> set[str]:
        return set(component["matched_branch_ids"] or component["matched_all_branch_ids"])

    def _components_share_corridor(
        base_component: dict[str, Any],
        candidate_component: dict[str, Any],
    ) -> bool:
        base_branch_ids = _component_branch_ids(base_component)
        candidate_branch_ids = _component_branch_ids(candidate_component)
        base_corridor_geometry = unary_union(
            [
                geometry
                for branch_id, geometry in all_branch_geometry_lookup.items()
                if branch_id in base_branch_ids and geometry is not None and not geometry.is_empty
            ]
        )
        same_branch_corridor = bool(
            base_branch_ids
            and not base_corridor_geometry.is_empty
            and base_corridor_geometry.buffer(
                max(DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.6, DIVSTRIP_BRANCH_BUFFER_M * 2.5),
                cap_style=2,
                join_style=2,
            ).intersects(candidate_component["geometry"])
            and float(candidate_component["distance_to_seed"]) <= float(DIVSTRIP_SEED_FALLBACK_DISTANCE_M)
        )
        same_corridor = (
            (
                base_branch_ids
                and candidate_branch_ids
                and bool(base_branch_ids & candidate_branch_ids)
            )
            or same_branch_corridor
            or (
                not base_branch_ids
                and float(candidate_component["distance_to_roads"]) <= DIVSTRIP_CONTEXT_ROAD_DISTANCE_M
            )
        )
        if not same_corridor:
            return False
        return float(candidate_component["geometry"].distance(base_component["geometry"])) <= float(
            DIVSTRIP_REFERENCE_ROAD_BUFFER_M + 6.0
        )

    compound_pair_components: list[dict[str, Any]] = []
    if allow_compound_pair_merge:
        best_compound_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
        best_compound_pair_key: tuple[int, float, float, float] | None = None
        for first_component, second_component in combinations(candidate_components, 2):
            first_branch_ids = _component_branch_ids(first_component)
            second_branch_ids = _component_branch_ids(second_component)
            if not first_branch_ids or not second_branch_ids:
                continue
            if first_branch_ids & second_branch_ids:
                continue
            geometry_distance = float(first_component["geometry"].distance(second_component["geometry"]))
            if geometry_distance > float(DIVSTRIP_COMPLEX_PAIR_DISTANCE_M):
                continue
            if (
                float(first_component["distance_to_seed"]) > float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
                or float(second_component["distance_to_seed"]) > float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
            ):
                continue
            if (
                float(first_component["distance_to_roads"]) > float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
                or float(second_component["distance_to_roads"]) > float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
            ):
                continue
            pair_key = (
                len(first_branch_ids) + len(second_branch_ids),
                -float(first_component["distance_to_event_anchor"] + second_component["distance_to_event_anchor"]),
                -float(first_component["distance_to_roads"] + second_component["distance_to_roads"]),
                -geometry_distance,
            )
            if best_compound_pair_key is None or pair_key > best_compound_pair_key:
                best_compound_pair_key = pair_key
                best_compound_pair = (first_component, second_component)
        if best_compound_pair is not None:
            compound_pair_components = [best_compound_pair[0], best_compound_pair[1]]

    selected_components = list(compound_pair_components or [candidate_components[0]])
    ambiguous = False
    if len(candidate_components) > 1 and not compound_pair_components:
        first_component = candidate_components[0]
        second_component = candidate_components[1]
        first_branch_ids = _component_branch_ids(first_component)
        second_branch_ids = _component_branch_ids(second_component)
        same_corridor_pair = _components_share_corridor(first_component, second_component)
        opposite_compound_pair = (
            allow_compound_pair_merge
            and first_branch_ids
            and second_branch_ids
            and not bool(first_branch_ids & second_branch_ids)
            and float(first_component["distance_to_seed"]) <= float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
            and float(second_component["distance_to_seed"]) <= float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
            and float(first_component["distance_to_roads"]) <= float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
            and float(second_component["distance_to_roads"]) <= float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
            and float(first_component["geometry"].distance(second_component["geometry"])) <= float(
                DIVSTRIP_COMPLEX_PAIR_DISTANCE_M
            )
        )
        if opposite_compound_pair or (allow_compound_pair_merge and same_corridor_pair):
            selected_components = [first_component, second_component]
            ambiguous = False
        else:
            ambiguous = (
                len(first_component["matched_branch_ids"]) == len(second_component["matched_branch_ids"])
                and len(first_component["matched_all_branch_ids"]) == len(second_component["matched_all_branch_ids"])
                and abs(float(first_component["distance_to_event_anchor"]) - float(second_component["distance_to_event_anchor"])) <= 3.0
                and abs(float(first_component["distance_to_roads"]) - float(second_component["distance_to_roads"])) <= 1.0
                and abs(float(first_component["distance_to_seed"]) - float(second_component["distance_to_seed"])) <= 6.0
                and first_component["component_id"] != second_component["component_id"]
            )
            if (
                not ambiguous
                and len(matched_components) > 1
                and abs(float(first_component["distance_to_event_anchor"]) - float(second_component["distance_to_event_anchor"])) <= 8.0
                and abs(float(first_component["distance_to_roads"]) - float(second_component["distance_to_roads"])) <= 3.0
                and abs(float(first_component["distance_to_seed"]) - float(second_component["distance_to_seed"])) <= 12.0
            ):
                ambiguous = True
            if ambiguous:
                if allow_compound_pair_merge:
                    selected_components = [first_component, second_component]
                else:
                    selected_components = [first_component]
                    ambiguous = False
    if not ambiguous and selected_components and allow_compound_pair_merge:
        merged_components = list(selected_components)
        merged_component_ids = {component["component_id"] for component in merged_components}
        for component in candidate_components:
            if component["component_id"] in merged_component_ids:
                continue
            if not any(
                _components_share_corridor(base_component, component)
                for base_component in merged_components
            ):
                continue
            merged_components.append(component)
            merged_component_ids.add(component["component_id"])
        selected_components = merged_components
    selected_geometry = unary_union([component["geometry"] for component in selected_components])
    preferred_branch_ids = sorted(
        {
            branch_id
            for component in selected_components
            for branch_id in (component["matched_branch_ids"] or component["matched_all_branch_ids"])
        }
    )
    return {
        "present": True,
        "nearby": True,
        "component_count": len(components),
        "selected_component_ids": [component["component_id"] for component in selected_components],
        "constraint_geometry": GeometryCollection() if ambiguous else selected_geometry,
        "preferred_branch_ids": preferred_branch_ids,
        "ambiguous": ambiguous,
        "selection_mode": "divstrip_primary" if not ambiguous and not selected_geometry.is_empty else "roads_fallback",
        "evidence_source": "drivezone+divstrip+roads+rcsd+seed" if not ambiguous and not selected_geometry.is_empty else "drivezone+roads+rcsd+seed",
        "event_anchor_geometry": event_anchor_geometry,
    }


def _build_divstrip_event_window(
    *,
    divstrip_constraint_geometry,
    selected_roads: list[ParsedRoad],
    selected_rcsd_roads: list[ParsedRoad],
    seed_union,
    event_anchor_geometry,
    drivezone_union,
):
    if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty:
        return GeometryCollection()

    selected_component_count = len(_collect_polygon_components(divstrip_constraint_geometry))
    seed_link_distance_m = (
        DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M
        if selected_component_count > 1
        else DIVSTRIP_SEED_FALLBACK_DISTANCE_M
    )
    event_parts = [divstrip_constraint_geometry.buffer(DIVSTRIP_EVENT_BUFFER_M, join_style=2)]
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        event_parts.append(event_anchor_geometry.buffer(EVENT_ANCHOR_BUFFER_M, join_style=2))
    linked_road_geometries = [
        road.geometry.buffer(max(ROAD_BUFFER_M, 1.75), cap_style=2, join_style=2)
        for road in [*selected_roads, *selected_rcsd_roads]
        if road.geometry is not None
        and not road.geometry.is_empty
        and road.geometry.distance(divstrip_constraint_geometry) <= DIVSTRIP_EVENT_ROAD_LINK_DISTANCE_M
    ]
    event_parts.extend(linked_road_geometries)
    if seed_union is not None and not seed_union.is_empty and seed_union.distance(divstrip_constraint_geometry) <= float(seed_link_distance_m):
        event_parts.append(seed_union.buffer(max(NODE_SEED_RADIUS_M * 1.5, RC_NODE_SEED_RADIUS_M * 1.2, 3.0)))
    event_window = unary_union(event_parts).intersection(drivezone_union).buffer(0)
    return event_window if not event_window.is_empty else GeometryCollection()


def _build_local_surface_clip_geometry(
    *,
    cross_section_surface_geometry,
    divstrip_event_window,
    divstrip_constraint_geometry,
    axis_window_geometry,
    drivezone_union,
    is_complex_junction: bool,
    multibranch_enabled: bool,
    selected_component_count: int,
    allow_full_axis_drivezone_fill: bool,
):
    if bool(allow_full_axis_drivezone_fill):
        clip_geometry = (
            axis_window_geometry
            if axis_window_geometry is not None and not axis_window_geometry.is_empty
            else GeometryCollection()
        )
        if not clip_geometry.is_empty and drivezone_union is not None and not drivezone_union.is_empty:
            clip_geometry = clip_geometry.intersection(drivezone_union).buffer(0)
        return clip_geometry if not clip_geometry.is_empty else GeometryCollection()

    prefer_divstrip_local_window = (
        bool(is_complex_junction)
        or bool(multibranch_enabled)
        or int(selected_component_count) > 1
    )
    source_geometries = (
        [divstrip_event_window, cross_section_surface_geometry]
        if prefer_divstrip_local_window
        else [cross_section_surface_geometry, divstrip_event_window]
    )
    if prefer_divstrip_local_window:
        localized_divstrip_clip = GeometryCollection()
        localized_intersection = GeometryCollection()
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            localized_divstrip_clip = divstrip_constraint_geometry.buffer(
                max(float(DIVSTRIP_EVENT_BUFFER_M), float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M)),
                cap_style=2,
                join_style=2,
            )
            if divstrip_event_window is not None and not divstrip_event_window.is_empty:
                localized_divstrip_clip = localized_divstrip_clip.intersection(divstrip_event_window).buffer(0)
        localized_surface_clip = GeometryCollection()
        if cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
            localized_surface_clip = cross_section_surface_geometry.buffer(
                max(1.5, min(float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M) * 0.25, 3.0)),
                cap_style=2,
                join_style=2,
            )
            if drivezone_union is not None and not drivezone_union.is_empty:
                localized_surface_clip = localized_surface_clip.intersection(drivezone_union).buffer(0)
        if (
            localized_divstrip_clip is not None
            and not localized_divstrip_clip.is_empty
            and localized_surface_clip is not None
            and not localized_surface_clip.is_empty
        ):
            localized_intersection = localized_divstrip_clip.intersection(localized_surface_clip).buffer(0)
            if int(selected_component_count) > 1:
                if not localized_intersection.is_empty:
                    clip_parts = [localized_intersection]
                else:
                    clip_parts = [localized_divstrip_clip]
            elif not localized_intersection.is_empty:
                clip_parts = [localized_intersection]
            else:
                clip_parts = [localized_divstrip_clip]
        else:
            clip_parts = [
                geometry
                for geometry in [localized_divstrip_clip, localized_surface_clip]
                if geometry is not None and not geometry.is_empty
            ]
        if not clip_parts:
            clip_parts = [
                geometry for geometry in [axis_window_geometry, cross_section_surface_geometry]
                if geometry is not None and not geometry.is_empty
            ]
    else:
        clip_parts = [
            geometry
            for geometry in source_geometries
            if geometry is not None and not geometry.is_empty
        ]
    if not clip_parts:
        return GeometryCollection()

    clip_geometry = unary_union(clip_parts)
    if drivezone_union is not None and not drivezone_union.is_empty:
        clip_geometry = clip_geometry.intersection(drivezone_union).buffer(0)
    if clip_geometry.is_empty:
        return GeometryCollection()

    clip_buffer_m = 0.0
    if not is_complex_junction and not multibranch_enabled and int(selected_component_count) <= 1:
        clip_buffer_m = max(float(EVENT_ANCHOR_BUFFER_M), float(ROAD_BUFFER_M), 2.5)
    elif is_complex_junction or multibranch_enabled or int(selected_component_count) > 1:
        clip_buffer_m = max(1.5, min(float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M) * 0.35, 3.0))

    if clip_buffer_m > 1e-6:
        buffered_geometry = clip_geometry.buffer(
            clip_buffer_m,
            cap_style=2,
            join_style=2,
        )
        if drivezone_union is not None and not drivezone_union.is_empty:
            buffered_geometry = buffered_geometry.intersection(drivezone_union).buffer(0)
        if not buffered_geometry.is_empty:
            clip_geometry = buffered_geometry
    return clip_geometry if not clip_geometry.is_empty else GeometryCollection()


def _resolve_selected_component_connector_span_limit_m(
    *,
    allow_extended_connector_span: bool,
) -> float:
    base_limit_m = float(MULTIBRANCH_LOCAL_CONTEXT_WINDOW_M) * 2.0
    if not bool(allow_extended_connector_span):
        return base_limit_m
    return max(base_limit_m, float(EVENT_REFERENCE_SCAN_MAX_M))


def _should_apply_selected_support_corridor(
    *,
    allow_full_axis_drivezone_fill: bool,
    parallel_competitor_present: bool,
    parallel_side_geometry,
    local_surface_clip_geometry,
) -> bool:
    if not bool(allow_full_axis_drivezone_fill) or bool(parallel_competitor_present):
        return False
    if (
        parallel_side_geometry is None
        or parallel_side_geometry.is_empty
        or local_surface_clip_geometry is None
        or local_surface_clip_geometry.is_empty
    ):
        return False
    local_surface_clip_area_m2 = float(local_surface_clip_geometry.area)
    if local_surface_clip_area_m2 <= 0.0:
        return False
    return (
        float(parallel_side_geometry.area) / local_surface_clip_area_m2
        >= SELECTED_SUPPORT_CORRIDOR_PARALLEL_RATIO_MIN
    )


def _build_selected_support_corridor_geometry(
    *,
    drivezone_union,
    clip_geometry,
    selected_support_union,
    event_anchor_geometry,
    support_buffer_m: float,
):
    if selected_support_union is None or selected_support_union.is_empty:
        return GeometryCollection()
    corridor_geometry = selected_support_union.buffer(
        support_buffer_m,
        cap_style=2,
        join_style=2,
    )
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        corridor_geometry = corridor_geometry.union(
            event_anchor_geometry.buffer(
                max(EVENT_ANCHOR_BUFFER_M, ROAD_BUFFER_M),
                cap_style=2,
                join_style=2,
            )
        ).buffer(0)
    corridor_geometry = corridor_geometry.intersection(drivezone_union).buffer(0)
    if clip_geometry is not None and not clip_geometry.is_empty:
        corridor_geometry = corridor_geometry.intersection(clip_geometry).buffer(0)
    return corridor_geometry


def _localize_divstrip_reference_geometry(
    *,
    divstrip_constraint_geometry,
    selected_roads: list[ParsedRoad],
    event_anchor_geometry,
    representative_node: ParsedNode,
    drivezone_union,
):
    if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty:
        return GeometryCollection()

    focus_geometries = [
        road.geometry.buffer(DIVSTRIP_REFERENCE_ROAD_BUFFER_M, cap_style=2, join_style=2)
        for road in selected_roads
        if road.geometry is not None and not road.geometry.is_empty
    ]
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        focus_geometries.append(
            event_anchor_geometry.buffer(max(EVENT_ANCHOR_BUFFER_M * 2.0, DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.6), join_style=2)
        )
    focus_geometries.append(
        representative_node.geometry.buffer(max(EVENT_ANCHOR_BUFFER_M * 2.0, DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.5))
    )
    focus_geometry = unary_union(focus_geometries).buffer(0)
    if drivezone_union is not None and not drivezone_union.is_empty:
        focus_geometry = focus_geometry.intersection(
            drivezone_union.buffer(max(EVENT_ANCHOR_BUFFER_M, ROAD_BUFFER_M), join_style=2)
        ).buffer(0)
    if focus_geometry.is_empty:
        return divstrip_constraint_geometry
    localized_geometry = divstrip_constraint_geometry.intersection(focus_geometry).buffer(0)
    if localized_geometry.is_empty:
        return divstrip_constraint_geometry
    return localized_geometry



__all__ = [name for name in globals() if not name.startswith("__")]
