from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Callable

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import nearest_points

from .segment_first_skeleton import canonical_id
from .segment_first_surface_routing import interior_surface_target


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessMembershipPolicy:
    """Geometry and Junction policy supplied by the Node compilation layer."""

    junction_surfaces: Callable[[gpd.GeoDataFrame], dict[str, object]]
    junction_context: Callable[[str, gpd.GeoDataFrame], dict[str, str]]
    physical_portal_supported: Callable[[object, object | None], bool]
    target_on_existing_endpoint_segment: Callable[
        [dict[str, object], object], bool
    ]
    completion_extends_outward: Callable[[dict[str, object], object], bool]
    smooth_surface_completion_supported: Callable[..., bool]
    surface_coverage: Callable[[LineString, object | None], float]


def _is_usable_geometry(geometry: object | None) -> bool:
    return bool(
        geometry is not None
        and hasattr(geometry, "is_empty")
        and not geometry.is_empty
    )


def _optional_distance(geometry: object | None, point: object) -> float:
    if not _is_usable_geometry(geometry):
        return float("inf")
    return float(geometry.distance(point))


def _sample_ids(values: list[str], *, limit: int = 10) -> str:
    visible = values[:limit]
    if len(values) > limit:
        visible.append(f"...(+{len(values) - limit})")
    return ",".join(visible) if visible else "none"


def _split_keys(value: object) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    ]


def _completion_access_ids(endpoint: dict[str, object]) -> set[str]:
    value = endpoint.get("constrained_completion_access_ids", "")
    if value is None or bool(pd.isna(value)):
        return set()
    return set(_split_keys(value))


def _observed_support_access_ids(endpoint: dict[str, object]) -> set[str]:
    value = endpoint.get("access_support_access_ids", "")
    if value is None or bool(pd.isna(value)):
        return set()
    return set(_split_keys(value))


def materialize_missing_built_access_memberships(
    endpoint_rows: list[dict[str, object]],
    endpoint_memberships: dict[int, dict[str, object]],
    accesses: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    *,
    max_distance_m: float,
    semantic_endpoint_segment_ids: set[str],
    completion_surface: object | None,
    endpoint_buffer_m: float,
    minimum_surface_coverage: float,
    maximum_turn_deg: float,
    road_geometry_by_id: dict[str, LineString],
    policy: AccessMembershipPolicy,
) -> int:
    """Bind every uncovered built Road handoff for a Segment access.

    This is relation-scoped handoff against the accepted JunctionUnit surface,
    not a global distance search for a junction. Existing memberships are never
    reassigned, so an ambiguous candidate remains a hard-gate failure.
    """

    started_at = time.perf_counter()
    if accesses.empty:
        LOGGER.info("Endpoint access membership skipped: no SegmentAccess rows.")
        return 0
    endpoints_by_segment: dict[str, list[int]] = {}
    for index, endpoint in enumerate(endpoint_rows):
        endpoints_by_segment.setdefault(str(endpoint["segment_id"]), []).append(index)
    surface_by_group = policy.junction_surfaces(junction_units)
    count = 0
    ordered_accesses = accesses.sort_values(
        ["segment_id", "access_type", "access_ordinal", "access_id"]
    )
    missing_access_geometry_ids = [
        str(access.access_id)
        for access in ordered_accesses.itertuples()
        if not _is_usable_geometry(access.geometry)
    ]
    missing_access_geometry_count = len(missing_access_geometry_ids)
    unresolved_target_ids: list[str] = []
    LOGGER.info(
        "Endpoint access membership started: accesses=%d, endpoints=%d, "
        "missing_access_geometry=%d, missing_access_sample=%s.",
        len(ordered_accesses),
        len(endpoint_rows),
        missing_access_geometry_count,
        _sample_ids(missing_access_geometry_ids),
    )
    for access in ordered_accesses.itertuples():
        segment_id = str(access.segment_id)
        access_id = str(access.access_id)
        group = canonical_id(access.junction_group_id)
        indexes = endpoints_by_segment.get(segment_id, [])
        target = surface_by_group.get(group)
        if not _is_usable_geometry(target):
            target = access.geometry
        if not _is_usable_geometry(target):
            unresolved_target_ids.append(access_id)
            continue
        represented_roads = {
            str(endpoint_rows[index]["road_id"])
            for index in indexes
            if index in endpoint_memberships
            and canonical_id(endpoint_memberships[index]["junction_group_id"])
            == group
        }
        semantic_endpoint = (
            str(access.access_type) == "ENDPOINT"
            and any(
                str(endpoint_rows[index]["segment_type"]) == "advance_right"
                or segment_id in semantic_endpoint_segment_ids
                for index in indexes
            )
        )
        represented_main_roles = {
            str(endpoint_rows[index]["carrier_role"])
            for index in indexes
            if index in endpoint_memberships
            and canonical_id(endpoint_memberships[index]["junction_group_id"])
            == group
            and str(endpoint_rows[index]["carrier_role"]).startswith("main_")
        }
        represented_roles = {
            str(endpoint_rows[index]["carrier_role"])
            for index in indexes
            if index in endpoint_memberships
            and canonical_id(endpoint_memberships[index]["junction_group_id"])
            == group
        }
        if semantic_endpoint:
            candidates_by_role: dict[
                str, list[tuple[float, float, str, int]]
            ] = {}
            for index in indexes:
                endpoint = endpoint_rows[index]
                role = str(endpoint["carrier_role"])
                current_source = (
                    str(endpoint_memberships[index]["junction_source"])
                    if index in endpoint_memberships
                    else ""
                )
                current_group = (
                    canonical_id(endpoint_memberships[index]["junction_group_id"])
                    if index in endpoint_memberships
                    else ""
                )
                if (
                    endpoint["realization"] != "built"
                    or current_group == group
                    or current_source
                    in {
                        "segment_access_surface_handoff",
                        "segment_endpoint_access_lineage_override",
                        "segment_endpoint_surface_constrained_completion",
                    }
                    or not role.startswith("main_")
                    or role in represented_main_roles
                ):
                    continue
                point = endpoint["geometry"]
                candidates_by_role.setdefault(role, []).append(
                    (
                        float(target.distance(point)),
                        _optional_distance(access.geometry, point),
                        str(endpoint["endpoint"]),
                        index,
                    )
                )
            context = policy.junction_context(group, junction_units)
            for candidates in candidates_by_role.values():
                surface_distance, _, _, index = min(candidates)
                if surface_distance > max_distance_m:
                    continue
                if (
                    context["junction_source"] == "swsd_retained"
                    and not policy.physical_portal_supported(
                        endpoint_rows[index]["geometry"],
                        completion_surface,
                    )
                ):
                    continue
                membership_source = ""
                if (
                    segment_id in semantic_endpoint_segment_ids
                    and context["junction_source"] != "swsd_retained"
                    and completion_surface is not None
                    and not target.contains(
                        endpoint_rows[index]["geometry"]
                    )
                ):
                    point = endpoint_rows[index]["geometry"]
                    target_point = nearest_points(
                        point,
                        interior_surface_target(
                            target,
                            inset_m=endpoint_buffer_m,
                        ),
                    )[1]
                    existing_trim = policy.target_on_existing_endpoint_segment(
                        endpoint_rows[index],
                        target_point,
                    )
                    outward_completion = policy.completion_extends_outward(
                        endpoint_rows[index],
                        target_point,
                    )
                    smooth_lateral = (
                        not existing_trim
                        and not outward_completion
                        and policy.smooth_surface_completion_supported(
                            road_geometry_by_id.get(
                                str(endpoint_rows[index]["road_id"])
                            ),
                            str(endpoint_rows[index]["endpoint"]),
                            target_point,
                            completion_surface,
                            maximum_distance_m=max_distance_m,
                            minimum_surface_coverage=minimum_surface_coverage,
                            maximum_turn_deg=maximum_turn_deg,
                        )
                    )
                    if (
                        not existing_trim
                        and not outward_completion
                        and not smooth_lateral
                    ):
                        continue
                    connector = LineString([point, target_point])
                    coverage = policy.surface_coverage(
                        connector,
                        completion_surface,
                    )
                    if (
                        connector.length <= 1e-9
                        or coverage + 1e-9 < minimum_surface_coverage
                    ):
                        continue
                    endpoint_rows[index]["geometry"] = target_point
                    membership_source = (
                        "segment_endpoint_surface_existing_road_trim"
                        if existing_trim
                        else
                        "segment_endpoint_surface_smooth_lateral_completion"
                        if smooth_lateral
                        else
                        "segment_endpoint_surface_constrained_completion"
                    )
                    endpoint_rows[index][
                        "junction_interior_completion_source"
                    ] = membership_source
                overrides_surface = index in endpoint_memberships
                endpoint_memberships[index] = {
                    "junction_group_id": group,
                    "junction_kind": context["junction_kind"],
                    "junction_source": membership_source or (
                        "segment_endpoint_access_lineage_override"
                        if overrides_surface
                        else "segment_access_surface_handoff"
                    ),
                }
                count += 1
        candidates_by_road: dict[str, list[tuple[float, float, str, int]]] = {}
        for index in indexes:
            endpoint = endpoint_rows[index]
            road_id = str(endpoint["road_id"])
            completion_access_ids = _completion_access_ids(endpoint)
            observed_access_ids = _observed_support_access_ids(endpoint)
            declared_for_access = (
                str(endpoint["carrier_role"]) == "access_support"
                and (
                    access_id in completion_access_ids
                    or access_id in observed_access_ids
                )
            )
            lineage_for_access = (
                canonical_id(endpoint["source_node_id"])
                == canonical_id(access.source_node_id)
                or canonical_id(
                    endpoint.get("source_node_mainnode_group_id", "")
                )
                == group
            )
            if (
                endpoint["realization"] != "built"
                or (
                    semantic_endpoint
                    and str(endpoint["carrier_role"]) != "access_support"
                )
                or (index in endpoint_memberships and not declared_for_access)
                or road_id in represented_roads
                or (
                    str(access.access_type) == "THROUGH"
                    and not declared_for_access
                    and not lineage_for_access
                )
                or (
                    not declared_for_access
                    and str(endpoint["carrier_role"]) in represented_roles
                )
            ):
                continue
            point = endpoint["geometry"]
            candidate_group = (
                road_id
                if declared_for_access or lineage_for_access
                else f"role:{endpoint['carrier_role']}"
            )
            candidates_by_road.setdefault(candidate_group, []).append(
                (
                    float(target.distance(point)),
                    _optional_distance(access.geometry, point),
                    str(endpoint["endpoint"]),
                    index,
                )
            )
        context = policy.junction_context(group, junction_units)
        for candidates in candidates_by_road.values():
            distance, _, _, index = min(candidates)
            if distance > max_distance_m:
                continue
            if (
                context["junction_source"] == "swsd_retained"
                and not policy.physical_portal_supported(
                    endpoint_rows[index]["geometry"],
                    completion_surface,
                )
            ):
                continue
            previous = endpoint_memberships.get(index)
            completion_access_ids = _completion_access_ids(endpoint_rows[index])
            observed_access_ids = _observed_support_access_ids(
                endpoint_rows[index]
            )
            completion_declared = access_id in completion_access_ids
            observed_declared = access_id in observed_access_ids
            declared_for_access = completion_declared or observed_declared
            lineage_for_access = (
                canonical_id(endpoint_rows[index]["source_node_id"])
                == canonical_id(access.source_node_id)
                or canonical_id(
                    endpoint_rows[index].get(
                        "source_node_mainnode_group_id",
                        "",
                    )
                )
                == group
            )
            if (
                str(access.access_type) == "THROUGH"
                and not declared_for_access
                and not lineage_for_access
            ):
                continue
            membership_source = ""
            if (
                context["junction_source"] != "swsd_retained"
                and completion_surface is not None
                and not target.contains(
                    endpoint_rows[index]["geometry"]
                )
            ):
                point = endpoint_rows[index]["geometry"]
                target_point = nearest_points(
                    point,
                    interior_surface_target(
                        target,
                        inset_m=endpoint_buffer_m,
                    ),
                )[1]
                existing_trim = policy.target_on_existing_endpoint_segment(
                    endpoint_rows[index],
                    target_point,
                )
                outward_completion = policy.completion_extends_outward(
                    endpoint_rows[index],
                    target_point,
                )
                smooth_lateral = (
                    not existing_trim
                    and not outward_completion
                    and (
                        str(access.access_type) == "ENDPOINT"
                        or lineage_for_access
                    )
                    and policy.smooth_surface_completion_supported(
                        road_geometry_by_id.get(
                            str(endpoint_rows[index]["road_id"])
                        ),
                        str(endpoint_rows[index]["endpoint"]),
                        target_point,
                        completion_surface,
                        maximum_distance_m=max_distance_m,
                        minimum_surface_coverage=minimum_surface_coverage,
                        maximum_turn_deg=maximum_turn_deg,
                    )
                )
                if (
                    not existing_trim
                    and not outward_completion
                    and not smooth_lateral
                ):
                    continue
                connector = LineString([point, target_point])
                coverage = policy.surface_coverage(
                    connector,
                    completion_surface,
                )
                if (
                    connector.length <= 1e-9
                    or coverage + 1e-9 < minimum_surface_coverage
                ):
                    continue
                endpoint_rows[index]["geometry"] = target_point
                membership_source = (
                    "segment_access_surface_existing_road_trim"
                    if existing_trim
                    else
                    "segment_access_surface_smooth_lateral_completion"
                    if smooth_lateral
                    else
                    "segment_access_surface_constrained_completion"
                )
                endpoint_rows[index][
                    "junction_interior_completion_source"
                ] = membership_source
            endpoint_memberships[index] = {
                "junction_group_id": group,
                "junction_kind": context["junction_kind"],
                "junction_source": membership_source or (
                    "declared_access_support_observed_override"
                    if observed_declared and previous is not None
                    else "declared_access_support_observed_handoff"
                    if observed_declared
                    else "declared_access_support_override"
                    if completion_declared and previous is not None
                    else "declared_access_support_handoff"
                    if completion_declared
                    else "segment_access_surface_handoff"
                ),
            }
            count += 1
    elapsed_seconds = time.perf_counter() - started_at
    LOGGER.info(
        "Endpoint access membership completed: materialized=%d, "
        "missing_access_geometry=%d, unresolved_target=%d, "
        "unresolved_target_sample=%s, elapsed=%.3fs.",
        count,
        missing_access_geometry_count,
        len(unresolved_target_ids),
        _sample_ids(unresolved_target_ids),
        elapsed_seconds,
    )
    return count


__all__ = [
    "AccessMembershipPolicy",
    "materialize_missing_built_access_memberships",
]
