from __future__ import annotations

from dataclasses import dataclass
import heapq
import hashlib
from statistics import median

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union

from .segment_first_config import SegmentFirstConfig
from .segment_first_geometry_cache import buffered_union
from .segment_first_lane_topo import LANE_TOPO_PAIR_SOURCES
from .segment_first_nodes import resolve_road_endpoint_junctions


@dataclass(frozen=True)
class JunctionCarrierResult:
    roads: gpd.GeoDataFrame
    geometry_sources: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    materialized_group_ids: frozenset[str]
    fallback_segment_ids: frozenset[str]
    summary: dict[str, object]


def materialize_ordinary_junction_carriers(
    segment_roads: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    t01_nodes: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
    semantic_endpoint_segment_ids: set[str] | None = None,
    full_rcsd_roads: gpd.GeoDataFrame | None = None,
    explicit_pairs: pd.DataFrame | None = None,
) -> JunctionCarrierResult:
    """Audit distributed ordinary Junction portals without inventing star Roads.

    SWSD and full-RCSD ordinary Junctions retain several physical portal Nodes
    under one semantic mainnode.  P04 therefore validates each portal against
    the accepted Junction surface or DriveZone and publishes no default
    ``JUNCTION_UNIT`` Road.  The ordinary semantic RoadNextRoad relations are
    compiled later from the classified Junction membership.
    """

    ordinary = junction_units[
        junction_units["junction_kind"].eq("ordinary")
        & junction_units["junction_source"].isin(
            {"t03_accepted", "t07_accepted"}
        )
    ].copy()
    if segment_roads.empty or ordinary.empty:
        return _empty_result(segment_roads, ordinary.crs or segment_roads.crs)

    resolution = resolve_road_endpoint_junctions(
        segment_roads,
        junction_units,
        segment_accesses,
        t01_nodes,
        config=config,
        semantic_endpoint_segment_ids=semantic_endpoint_segment_ids,
    )
    surface_by_group = {
        str(group): frame.geometry.union_all().buffer(
            config.completion_surface_buffer_m
        )
        for group, frame in ordinary.groupby(
            ordinary["junction_group_id"].astype(str)
        )
    }
    endpoints_by_group: dict[str, list[int]] = {}
    for index, membership in resolution.memberships.items():
        group_id = str(membership["junction_group_id"])
        if (
            str(membership["junction_kind"]) == "ordinary"
            and group_id in surface_by_group
        ):
            endpoints_by_group.setdefault(group_id, []).append(index)

    forced_portal_evidence = _lane_topo_portal_requirements(
        explicit_pairs,
        resolution.endpoint_rows,
        resolution.memberships,
        set(surface_by_group),
    )
    drivezone_surface = (
        buffered_union(drivezones, config.completion_surface_buffer_m)
        if not drivezones.empty
        else None
    )
    audit_rows: list[dict[str, object]] = []
    materialized_groups: set[str] = set()
    fallback_segments: set[str] = set()
    rejected_groups = 0

    for group_id, endpoint_indexes in sorted(endpoints_by_group.items()):
        clusters = _portal_clusters(
            endpoint_indexes,
            resolution.endpoint_rows,
            config.endpoint_snap_distance_m,
        )
        group_rejected = False
        for cluster in clusters:
            portal = _cluster_point(cluster, resolution.endpoint_rows)
            surface_supported = bool(
                surface_by_group[group_id].covers(portal)
            )
            drivezone_supported = bool(
                drivezone_surface is not None
                and drivezone_surface.covers(portal)
            )
            supported = surface_supported or drivezone_supported
            built_segments = _built_segment_ids(
                cluster,
                resolution.endpoint_rows,
            )
            if not supported:
                group_rejected = True
                fallback_segments.update(built_segments)
            audit_rows.append(
                {
                    "run_id": config.run_id,
                    "junction_group_id": group_id,
                    "portal_signature": _portal_signature(
                        cluster,
                        resolution.endpoint_rows,
                    ),
                    "portal_endpoint_count": len(cluster),
                    "surface_coverage": 1.0 if surface_supported else 0.0,
                    "drivezone_coverage": 1.0 if drivezone_supported else 0.0,
                    "support_coverage": 1.0 if supported else 0.0,
                    "routing_state": "distributed_portal",
                    "detour_ratio": 1.0,
                    "carrier_evidence_ids": ",".join(
                        sorted(
                            {
                                evidence_id
                                for index in cluster
                                for evidence_id in forced_portal_evidence.get(
                                    index,
                                    set(),
                                )
                            }
                        )
                    ),
                    "length_m": 0.0,
                    "carrier_decision": (
                        "accepted" if supported else "rejected"
                    ),
                    "fallback_segment_ids": (
                        ""
                        if supported
                        else ",".join(sorted(built_segments))
                    ),
                    "review_required": False,
                    "reason_codes": (
                        "accepted_junction_surface_portal"
                        if surface_supported
                        else "drivezone_supported_portal"
                        if drivezone_supported
                        else "insufficient_physical_surface"
                    ),
                    "geometry": portal,
                }
            )
        if group_rejected:
            rejected_groups += 1
        else:
            materialized_groups.add(group_id)

    roads = _records_like([], segment_roads)
    sources = _records([], segment_roads.crs, ())
    audit = _records(
        audit_rows,
        segment_roads.crs,
        (
            "run_id",
            "junction_group_id",
            "portal_signature",
            "portal_endpoint_count",
            "surface_coverage",
            "drivezone_coverage",
            "support_coverage",
            "routing_state",
            "detour_ratio",
            "carrier_evidence_ids",
            "length_m",
            "carrier_decision",
            "fallback_segment_ids",
            "review_required",
            "reason_codes",
        ),
    )
    accepted_portals = int(
        audit["carrier_decision"].eq("accepted").sum()
    ) if not audit.empty else 0
    rejected_portals = int(
        audit["carrier_decision"].eq("rejected").sum()
    ) if not audit.empty else 0
    summary = {
        "topology_model": "distributed_portal_mainnode",
        "eligible_group_count": int(len(endpoints_by_group)),
        "materialized_group_count": int(len(materialized_groups)),
        "snap_only_group_count": 0,
        "rejected_group_count": int(rejected_groups),
        "junction_carrier_road_count": 0,
        "accepted_portal_count": accepted_portals,
        "rejected_portal_count": rejected_portals,
        "accepted_spoke_count": accepted_portals,
        "rejected_spoke_count": rejected_portals,
        "drivezone_supported_count": int(
            audit["reason_codes"].eq("drivezone_supported_portal").sum()
        )
        if not audit.empty
        else 0,
        "routed_spoke_count": 0,
        "full_rcsd_candidate_count": 0,
        "fallback_segment_count": int(len(fallback_segments)),
    }
    return JunctionCarrierResult(
        roads,
        sources,
        audit,
        frozenset(materialized_groups),
        frozenset(fallback_segments),
        summary,
    )


def _materialize_ordinary_junction_carriers_legacy(
    segment_roads: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    t01_nodes: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
    semantic_endpoint_segment_ids: set[str] | None = None,
    full_rcsd_roads: gpd.GeoDataFrame | None = None,
    explicit_pairs: pd.DataFrame | None = None,
) -> JunctionCarrierResult:
    """Materialize physical Roads inside accepted ordinary JunctionUnits.

    Segment Roads keep their evidence-derived endpoints.  A short bidirectional
    Road connects each distinct portal cluster to one point inside the accepted
    junction surface.  The connector is published only when its complete
    geometry is supported by that surface or by DriveZone; raw SWSD coordinates
    are never used.
    """

    ordinary = junction_units[
        junction_units["junction_kind"].eq("ordinary")
        & junction_units["junction_source"].isin(
            {"t03_accepted", "t07_accepted"}
        )
    ].copy()
    if segment_roads.empty or ordinary.empty:
        return _empty_result(segment_roads, ordinary.crs or segment_roads.crs)

    resolution = resolve_road_endpoint_junctions(
        segment_roads,
        junction_units,
        segment_accesses,
        t01_nodes,
        config=config,
        semantic_endpoint_segment_ids=semantic_endpoint_segment_ids,
    )
    surface_by_group = {
        str(group): frame.geometry.union_all()
        for group, frame in ordinary.groupby(ordinary["junction_group_id"].astype(str))
    }
    source_by_group = {
        str(row.junction_group_id): str(row.source_object_id)
        for row in ordinary.sort_values(
            ["source_priority", "source_object_id"],
            ascending=[False, True],
            kind="stable",
        ).itertuples()
    }
    source_kind_by_group = {
        str(row.junction_group_id): str(row.junction_source)
        for row in ordinary.sort_values(
            ["source_priority", "source_object_id"],
            ascending=[False, True],
            kind="stable",
        ).itertuples()
    }
    endpoints_by_group: dict[str, list[int]] = {}
    for index, membership in resolution.memberships.items():
        group_id = str(membership["junction_group_id"])
        if (
            str(membership["junction_kind"]) == "ordinary"
            and group_id in surface_by_group
        ):
            endpoints_by_group.setdefault(group_id, []).append(index)
    forced_portal_evidence = _lane_topo_portal_requirements(
        explicit_pairs,
        resolution.endpoint_rows,
        resolution.memberships,
        set(surface_by_group),
    )
    global_clusters = _portal_clusters(
        list(range(len(resolution.endpoint_rows))),
        resolution.endpoint_rows,
        config.endpoint_snap_distance_m,
    )
    global_cluster_by_index = {
        index: ordinal
        for ordinal, cluster in enumerate(global_clusters)
        for index in cluster
    }

    drivezone_surface = (
        buffered_union(drivezones, config.completion_surface_buffer_m)
        if not drivezones.empty
        else None
    )
    road_rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    materialized_groups: set[str] = set()
    fallback_segments: set[str] = set()
    snap_only_groups = 0
    rejected_groups = 0

    for group_id, endpoint_indexes in sorted(endpoints_by_group.items()):
        eligible = _eligible_portal_indexes(
            endpoint_indexes,
            resolution.endpoint_rows,
            set(forced_portal_evidence),
        )
        clusters_by_global_component: dict[int, list[int]] = {}
        for index in eligible:
            clusters_by_global_component.setdefault(
                global_cluster_by_index[index], []
            ).append(index)
        clusters = [
            sorted(cluster)
            for _, cluster in sorted(clusters_by_global_component.items())
        ]
        if not clusters:
            continue
        if len(clusters) == 1:
            materialized_groups.add(group_id)
            snap_only_groups += 1
            continue

        surface = surface_by_group[group_id]
        support_surface = surface.buffer(config.completion_surface_buffer_m)
        combined_support_surface = (
            support_surface.union(drivezone_surface)
            if drivezone_surface is not None
            else support_surface
        )
        portal_points = [
            _cluster_point(cluster, resolution.endpoint_rows)
            for cluster in clusters
        ]
        center = _junction_center(portal_points, support_surface)
        candidates: list[dict[str, object]] = []
        group_rejected = False
        for cluster, portal in zip(clusters, portal_points):
            direct_line = LineString([portal, center])
            line, routing_state = _route_inside_support(
                portal,
                center,
                support_surface,
                drivezone_surface,
                minimum_coverage=config.completion_surface_min_coverage,
                scope_buffer_m=config.endpoint_snap_distance_m,
            )
            carrier_evidence_ids = ",".join(
                sorted(
                    {
                        evidence_id
                        for index in cluster
                        for evidence_id in forced_portal_evidence.get(index, set())
                    }
                )
            )
            if (
                routing_state == "direct"
                and _coverage(line, combined_support_surface)
                < config.completion_surface_min_coverage
                and source_kind_by_group.get(group_id) == "t07_accepted"
                and full_rcsd_roads is not None
                and not full_rcsd_roads.empty
            ):
                weak_candidate = _full_rcsd_junction_candidate(
                    portal,
                    center,
                    full_rcsd_roads,
                    combined_support_surface,
                    maximum_endpoint_distance_m=(
                        config.relation_endpoint_max_distance_m
                    ),
                    minimum_coverage=config.completion_surface_min_coverage,
                )
                if weak_candidate is not None:
                    line, weak_evidence_id = weak_candidate
                    carrier_evidence_ids = ",".join(
                        value
                        for value in (carrier_evidence_ids, weak_evidence_id)
                        if value
                    )
                    routing_state = "full_rcsd_junction_candidate"
            detour_ratio = (
                float(line.length / direct_line.length)
                if direct_line.length > 1e-9
                else 1.0
            )
            portal_signature = _portal_signature(
                cluster,
                resolution.endpoint_rows,
            )
            if line.length <= config.endpoint_snap_distance_m:
                audit_rows.append(
                    {
                        "run_id": config.run_id,
                        "junction_group_id": group_id,
                        "portal_signature": portal_signature,
                        "portal_endpoint_count": len(cluster),
                        "surface_coverage": 1.0,
                        "drivezone_coverage": 1.0,
                        "support_coverage": 1.0,
                        "routing_state": routing_state,
                        "detour_ratio": detour_ratio,
                        "carrier_evidence_ids": carrier_evidence_ids,
                        "length_m": float(line.length),
                        "carrier_decision": "accepted",
                        "fallback_segment_ids": "",
                        "review_required": False,
                        "reason_codes": "portal_center_snap",
                        "geometry": line,
                    }
                )
                continue
            surface_coverage = _coverage(line, support_surface)
            drivezone_coverage = _coverage(line, drivezone_surface)
            support_coverage = _coverage(line, combined_support_surface)
            supported = support_coverage >= config.completion_surface_min_coverage
            support_source = (
                "full_rcsd_junction_candidate"
                if routing_state == "full_rcsd_junction_candidate"
                else "accepted_junction_surface"
                if surface_coverage >= config.completion_surface_min_coverage
                else "drivezone_constrained_completion"
                if drivezone_coverage >= config.completion_surface_min_coverage
                else "accepted_surface_drivezone_union"
                if supported
                else "insufficient_physical_surface"
            )
            built_segments = _built_segment_ids(
                cluster, resolution.endpoint_rows
            )
            audit_rows.append(
                {
                    "run_id": config.run_id,
                    "junction_group_id": group_id,
                    "portal_signature": portal_signature,
                    "portal_endpoint_count": len(cluster),
                    "surface_coverage": surface_coverage,
                    "drivezone_coverage": drivezone_coverage,
                    "support_coverage": support_coverage,
                    "routing_state": routing_state,
                    "detour_ratio": detour_ratio,
                    "carrier_evidence_ids": carrier_evidence_ids,
                    "length_m": float(line.length),
                    "carrier_decision": "accepted" if supported else "rejected",
                    "fallback_segment_ids": (
                        "" if supported else ",".join(sorted(built_segments))
                    ),
                    "review_required": bool(
                        supported
                        and (
                            routing_state
                            in {
                                "support_constrained_path",
                                "full_rcsd_junction_candidate",
                            }
                            or support_source == "drivezone_constrained_completion"
                            or support_source == "accepted_surface_drivezone_union"
                            or line.length > config.relation_endpoint_max_distance_m
                        )
                    ),
                    "reason_codes": support_source,
                    "geometry": line,
                }
            )
            if not supported:
                group_rejected = True
                fallback_segments.update(built_segments)
            candidates.append(
                {
                    "group_id": group_id,
                    "portal_signature": portal_signature,
                    "source_object_id": source_by_group.get(group_id, group_id),
                    "source_patch_ids": _source_patch_ids(
                        cluster,
                        resolution.endpoint_rows,
                        segment_roads,
                    ),
                    "support_source": support_source,
                    "routing_state": routing_state,
                    "carrier_evidence_ids": carrier_evidence_ids,
                    "review_required": bool(
                        routing_state
                        in {
                            "support_constrained_path",
                            "full_rcsd_junction_candidate",
                        }
                        or support_source == "drivezone_constrained_completion"
                        or support_source == "accepted_surface_drivezone_union"
                        or line.length > config.relation_endpoint_max_distance_m
                    ),
                    "geometry": line,
                }
            )
        if group_rejected:
            rejected_groups += 1
            continue
        if not candidates:
            snap_only_groups += 1
            continue
        materialized_groups.add(group_id)
        for candidate in candidates:
            road = _junction_road(candidate, segment_roads, config.run_id)
            road_rows.append(road)
            source_rows.append(
                {
                    "run_id": config.run_id,
                    "road_id": road["id"],
                    "segment_id": "",
                    "source_span_id": f"{road['id']}:0",
                    "geometry_source": "hp_constrained_completion",
                    "source_object_ids": ",".join(
                        value
                        for value in (
                            str(candidate["source_object_id"]),
                            str(candidate.get("carrier_evidence_ids", "")),
                        )
                        if value
                    ),
                    "start_fraction": 0.0,
                    "end_fraction": 1.0,
                    "length_m": float(candidate["geometry"].length),
                    "geometry": candidate["geometry"],
                }
            )

    roads = _records_like(road_rows, segment_roads)
    sources = _records(
        source_rows,
        segment_roads.crs,
        (
            "run_id",
            "road_id",
            "segment_id",
            "source_span_id",
            "geometry_source",
            "source_object_ids",
            "start_fraction",
            "end_fraction",
            "length_m",
        ),
    )
    audit = _records(
        audit_rows,
        segment_roads.crs,
        (
            "run_id",
            "junction_group_id",
            "portal_signature",
            "portal_endpoint_count",
            "surface_coverage",
            "drivezone_coverage",
            "support_coverage",
            "routing_state",
            "detour_ratio",
            "carrier_evidence_ids",
            "length_m",
            "carrier_decision",
            "fallback_segment_ids",
            "review_required",
            "reason_codes",
        ),
    )
    summary = {
        "eligible_group_count": int(len(endpoints_by_group)),
        "materialized_group_count": int(len(materialized_groups)),
        "snap_only_group_count": int(snap_only_groups),
        "rejected_group_count": int(rejected_groups),
        "junction_carrier_road_count": int(len(roads)),
        "accepted_spoke_count": int(
            audit["carrier_decision"].eq("accepted").sum()
        )
        if not audit.empty
        else 0,
        "rejected_spoke_count": int(
            audit["carrier_decision"].eq("rejected").sum()
        )
        if not audit.empty
        else 0,
        "drivezone_supported_count": int(
            audit["reason_codes"].eq("drivezone_constrained_completion").sum()
        )
        if not audit.empty
        else 0,
        "routed_spoke_count": int(
            audit["routing_state"].eq("support_constrained_path").sum()
        )
        if not audit.empty
        else 0,
        "full_rcsd_candidate_count": int(
            audit["routing_state"].eq("full_rcsd_junction_candidate").sum()
        )
        if not audit.empty
        else 0,
        "fallback_segment_count": int(len(fallback_segments)),
    }
    return JunctionCarrierResult(
        roads,
        sources,
        audit,
        frozenset(materialized_groups),
        frozenset(fallback_segments),
        summary,
    )


def _eligible_portal_indexes(
    indexes: list[int],
    endpoints: list[dict[str, object]],
    forced_indexes: set[int] | None = None,
) -> list[int]:
    forced_indexes = forced_indexes or set()
    counts = pd.Series([str(endpoints[index]["road_id"]) for index in indexes]).value_counts()
    return [
        index
        for index in indexes
        if index in forced_indexes
        or int(counts.get(str(endpoints[index]["road_id"]), 0)) == 1
    ]


def _lane_topo_portal_requirements(
    explicit_pairs: pd.DataFrame | None,
    endpoints: list[dict[str, object]],
    memberships: dict[int, dict[str, object]],
    ordinary_group_ids: set[str],
) -> dict[int, set[str]]:
    if explicit_pairs is None or explicit_pairs.empty:
        return {}
    indexes_by_endpoint: dict[tuple[str, str], list[int]] = {}
    for index, endpoint in enumerate(endpoints):
        for patch_key in str(endpoint.get("patch_road_keys", "")).split(","):
            patch_key = patch_key.strip()
            if patch_key:
                indexes_by_endpoint.setdefault(
                    (patch_key, str(endpoint["endpoint"])), []
                ).append(index)
    result: dict[int, set[str]] = {}
    for pair in explicit_pairs.itertuples(index=False):
        if str(getattr(pair, "pair_source", "")) not in LANE_TOPO_PAIR_SOURCES:
            continue
        source_candidates = indexes_by_endpoint.get(
            (str(pair.source_patch_road_key), "end"), []
        )
        target_candidates = indexes_by_endpoint.get(
            (str(pair.target_patch_road_key), "start"), []
        )
        candidates: list[tuple[float, int, int]] = []
        for source in source_candidates:
            source_membership = memberships.get(source)
            if source_membership is None:
                continue
            group_id = str(source_membership["junction_group_id"])
            if group_id not in ordinary_group_ids:
                continue
            for target in target_candidates:
                target_membership = memberships.get(target)
                if (
                    target_membership is None
                    or str(target_membership["junction_group_id"]) != group_id
                    or endpoints[source]["road_id"] == endpoints[target]["road_id"]
                ):
                    continue
                candidates.append(
                    (
                        float(
                            endpoints[source]["geometry"].distance(
                                endpoints[target]["geometry"]
                            )
                        ),
                        source,
                        target,
                    )
                )
        if not candidates:
            continue
        _, source, target = min(candidates)
        evidence_id = str(getattr(pair, "source_relation_id", ""))
        if evidence_id:
            result.setdefault(source, set()).add(evidence_id)
            result.setdefault(target, set()).add(evidence_id)
    return result


def _portal_clusters(
    indexes: list[int],
    endpoints: list[dict[str, object]],
    snap_distance_m: float,
) -> list[list[int]]:
    parent = {index: index for index in indexes}

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for ordinal, left in enumerate(indexes):
        for right in indexes[ordinal + 1 :]:
            if (
                endpoints[left]["geometry"].distance(endpoints[right]["geometry"])
                <= snap_distance_m
            ):
                union(left, right)
    result: dict[int, list[int]] = {}
    for index in indexes:
        result.setdefault(find(index), []).append(index)
    return [sorted(cluster) for _, cluster in sorted(result.items())]


def _cluster_point(
    indexes: list[int],
    endpoints: list[dict[str, object]],
) -> Point:
    points = [endpoints[index]["geometry"] for index in indexes]
    return Point(
        float(median(point.x for point in points)),
        float(median(point.y for point in points)),
    )


def _junction_center(portals: list[Point], surface: object) -> Point:
    center = Point(
        float(median(point.x for point in portals)),
        float(median(point.y for point in portals)),
    )
    return center if surface.covers(center) else surface.representative_point()


def _coverage(line: LineString, surface: object | None) -> float:
    if line.length <= 1e-9:
        return 1.0
    if surface is None or surface.is_empty:
        return 0.0
    return float(line.intersection(surface).length / line.length)


def _route_inside_support(
    start: Point,
    end: Point,
    junction_surface: object,
    drivezone_surface: object | None,
    *,
    minimum_coverage: float,
    scope_buffer_m: float,
) -> tuple[LineString, str]:
    direct = LineString([start, end])
    support = (
        junction_surface.union(drivezone_surface)
        if drivezone_surface is not None
        else junction_surface
    )
    if _coverage(direct, support) >= minimum_coverage:
        return direct, "direct"
    scope = unary_union([junction_surface, start, end]).convex_hull.buffer(
        max(0.05, scope_buffer_m)
    )
    local_support = support.intersection(scope)
    components = (
        list(local_support.geoms)
        if local_support.geom_type in {"MultiPolygon", "GeometryCollection"}
        else [local_support]
    )
    candidates = [
        component
        for component in components
        if component.geom_type == "Polygon"
        and component.buffer(0.05).covers(start)
        and component.buffer(0.05).covers(end)
    ]
    for component in sorted(candidates, key=lambda geometry: float(geometry.area)):
        routed = _visibility_shortest_path(component, start, end)
        if routed is not None and _coverage(routed, support) >= minimum_coverage:
            return routed, "support_constrained_path"
    return direct, "direct"


def _full_rcsd_junction_candidate(
    start: Point,
    end: Point,
    full_rcsd_roads: gpd.GeoDataFrame,
    support_surface: object,
    *,
    maximum_endpoint_distance_m: float,
    minimum_coverage: float,
) -> tuple[LineString, str] | None:
    search_geometry = LineString([start, end]).buffer(maximum_endpoint_distance_m)
    indexes = list(full_rcsd_roads.sindex.query(search_geometry))
    candidates: list[tuple[float, float, str, LineString]] = []
    for road in full_rcsd_roads.iloc[indexes].itertuples():
        parts = (
            list(road.geometry.geoms)
            if road.geometry.geom_type == "MultiLineString"
            else [road.geometry]
        )
        for part in parts:
            if part.geom_type != "LineString" or part.length <= 1e-9:
                continue
            start_distance = float(start.distance(part))
            end_distance = float(end.distance(part))
            maximum_distance = max(start_distance, end_distance)
            if maximum_distance > maximum_endpoint_distance_m:
                continue
            clipped = substring(part, part.project(start), part.project(end))
            if clipped.geom_type != "LineString" or clipped.length <= 1e-9:
                continue
            coordinates = [start.coords[0], *list(clipped.coords), end.coords[0]]
            deduplicated = [coordinates[0]]
            for coordinate in coordinates[1:]:
                if Point(deduplicated[-1]).distance(Point(coordinate)) > 1e-6:
                    deduplicated.append(coordinate)
            if len(deduplicated) < 2:
                continue
            candidate = LineString(deduplicated)
            if (
                not candidate.is_simple
                or _coverage(candidate, support_surface) < minimum_coverage
            ):
                continue
            candidates.append(
                (
                    maximum_distance,
                    float(candidate.length),
                    str(getattr(road, "id", "")),
                    candidate,
                )
            )
    if not candidates:
        return None
    _, _, road_id, geometry = min(candidates, key=lambda item: item[:3])
    return geometry, road_id


def _visibility_shortest_path(
    polygon: object,
    start: Point,
    end: Point,
) -> LineString | None:
    simplified = polygon.simplify(0.05, preserve_topology=True)
    coordinates = [start.coords[0], end.coords[0]]
    coordinates.extend(list(simplified.exterior.coords)[:-1])
    for interior in simplified.interiors:
        coordinates.extend(list(interior.coords)[:-1])
    unique: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for coordinate in coordinates:
        key = (round(float(coordinate[0]), 6), round(float(coordinate[1]), 6))
        if key not in seen:
            seen.add(key)
            unique.append((float(coordinate[0]), float(coordinate[1])))
    visible_surface = polygon.buffer(0.05)
    adjacency: dict[int, list[tuple[float, int]]] = {
        index: [] for index in range(len(unique))
    }
    for left in range(len(unique)):
        for right in range(left + 1, len(unique)):
            edge = LineString([unique[left], unique[right]])
            if not visible_surface.covers(edge):
                continue
            distance = float(edge.length)
            adjacency[left].append((distance, right))
            adjacency[right].append((distance, left))
    distances = {0: 0.0}
    previous: dict[int, int] = {}
    queue: list[tuple[float, int]] = [(0.0, 0)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance > distances.get(current, float("inf")) + 1e-9:
            continue
        if current == 1:
            break
        for weight, target in adjacency[current]:
            candidate = distance + weight
            if candidate + 1e-9 < distances.get(target, float("inf")):
                distances[target] = candidate
                previous[target] = current
                heapq.heappush(queue, (candidate, target))
    if 1 not in distances:
        return None
    indexes = [1]
    while indexes[-1] != 0:
        indexes.append(previous[indexes[-1]])
    indexes.reverse()
    return LineString([unique[index] for index in indexes])


def _portal_signature(
    indexes: list[int],
    endpoints: list[dict[str, object]],
) -> str:
    return ",".join(
        sorted(
            f"{endpoints[index]['road_id']}:{endpoints[index]['endpoint']}"
            for index in indexes
        )
    )


def _source_patch_ids(
    indexes: list[int],
    endpoints: list[dict[str, object]],
    roads: gpd.GeoDataFrame,
) -> str:
    road_ids = {str(endpoints[index]["road_id"]) for index in indexes}
    selected = roads[roads["id"].astype(str).isin(road_ids)]
    values: set[str] = set()
    for value in selected.get("source_patch_ids", pd.Series(dtype=str)).fillna(""):
        values.update(item for item in str(value).split(",") if item)
    return ",".join(sorted(values))


def _built_segment_ids(
    indexes: list[int],
    endpoints: list[dict[str, object]],
) -> set[str]:
    return {
        str(endpoints[index]["segment_id"])
        for index in indexes
        if endpoints[index]["realization"] == "built"
        and str(endpoints[index]["segment_id"])
    }


def _junction_road(
    candidate: dict[str, object],
    template: gpd.GeoDataFrame,
    run_id: str,
) -> dict[str, object]:
    group_id = str(candidate["group_id"])
    portal_signature = str(candidate["portal_signature"])
    geometry = candidate["geometry"]
    record = {column: None for column in template.columns if column != "geometry"}
    record.update(
        {
            "mapid": 0,
            "id": _stable_int("junction-surface-road", group_id, portal_signature),
            "width": 0.0,
            "direction": 1,
            "const_st": 0,
            "snodeid": 0,
            "enodeid": 0,
            "source_snodeid": "",
            "source_enodeid": "",
            "funcclass": 0,
            "length": float(geometry.length),
            "lanenumsum": 0,
            "lanenums2e": 0,
            "lanenume2s": 0,
            "roadtype": 0,
            "roadclass": 0,
            "ownership": 0,
            "patchid": candidate["source_patch_ids"],
            "source": 1,
            "city_code": "",
            "formway": 0,
            "layer": 0,
            "source_road_id": candidate["source_object_id"],
            "segment_id": "",
            "owner_type": "JUNCTION_UNIT",
            "junction_group_id": group_id,
            "member_swsd_road_id": "",
            "carrier_role": "junction_surface_carrier",
            "realization": "built",
            "geometry_source": "hp_constrained_completion",
            "source_patch_ids": candidate["source_patch_ids"],
            "patch_road_key": "",
            "source_patch_road_keys": "",
            "start_patch_road_keys": "",
            "end_patch_road_keys": "",
            "source_lane_ids": "",
            "observed_coverage_ratio": 0.0,
            "internal_completion_fraction": 1.0,
            "assembly_state": candidate["support_source"],
            "base_geometry_length_m": float(geometry.length),
            "review_required": candidate["review_required"],
            "smoothing_state": (
                "junction_surface_routed_carrier"
                if candidate.get("routing_state") == "support_constrained_path"
                else "junction_full_rcsd_candidate_carrier"
                if candidate.get("routing_state")
                == "full_rcsd_junction_candidate"
                else "junction_surface_straight_carrier"
            ),
            "run_id": run_id,
            "geometry": geometry,
        }
    )
    return record


def _records_like(
    rows: list[dict[str, object]],
    template: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    columns = list(template.columns)
    for extra in ("owner_type", "junction_group_id"):
        if extra not in columns:
            columns.insert(len(columns) - 1, extra)
    if rows:
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=template.crs)[columns]
    data = {column: pd.Series(dtype="object") for column in columns if column != "geometry"}
    data["geometry"] = gpd.GeoSeries([], crs=template.crs)
    return gpd.GeoDataFrame(data, geometry="geometry", crs=template.crs)[columns]


def _records(
    rows: list[dict[str, object]],
    crs: object,
    columns: tuple[str, ...],
) -> gpd.GeoDataFrame:
    if rows:
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    data = {column: pd.Series(dtype="object") for column in columns}
    data["geometry"] = gpd.GeoSeries([], crs=crs)
    return gpd.GeoDataFrame(data, geometry="geometry", crs=crs)


def _empty_result(
    template: gpd.GeoDataFrame,
    crs: object,
) -> JunctionCarrierResult:
    empty_roads = _records_like([], template)
    empty = _records([], crs, ())
    return JunctionCarrierResult(
        empty_roads,
        empty.copy(),
        empty.copy(),
        frozenset(),
        frozenset(),
        {
            "eligible_group_count": 0,
            "materialized_group_count": 0,
            "snap_only_group_count": 0,
            "rejected_group_count": 0,
            "junction_carrier_road_count": 0,
            "accepted_spoke_count": 0,
            "rejected_spoke_count": 0,
            "drivezone_supported_count": 0,
            "fallback_segment_count": 0,
        },
    )


def _stable_int(prefix: str, *values: object) -> int:
    digest = hashlib.sha1(
        "|".join([prefix, *(str(value) for value in values)]).encode("utf-8")
    ).hexdigest()
    return 7_000_000_000_000_000 + int(digest[:13], 16) % 999_999_999_999_999


__all__ = ["JunctionCarrierResult", "materialize_ordinary_junction_carriers"]
