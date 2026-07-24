from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import GeometryCollection, LineString, Point
from shapely.ops import nearest_points, substring, unary_union

from .segment_first_config import SegmentFirstConfig
from .segment_first_junctions import endpoint_surface_geometry
from .segment_first_skeleton import canonical_id
from .segment_first_surface_routing import (
    interior_surface_target,
    route_endpoint_to_surface,
    route_tangent_endpoint_to_surface,
)


@dataclass(frozen=True)
class NodeBuildResult:
    roads: gpd.GeoDataFrame
    nodes: gpd.GeoDataFrame
    endpoint_audit: gpd.GeoDataFrame
    completion_sources: gpd.GeoDataFrame
    connection_evidence: gpd.GeoDataFrame
    summary: dict[str, object]


@dataclass(frozen=True)
class EndpointJunctionResolution:
    endpoint_rows: list[dict[str, object]]
    memberships: dict[int, dict[str, object]]
    lineage_override_count: int
    built_access_handoff_count: int


def resolve_road_endpoint_junctions(
    roads: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    t01_nodes: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
    semantic_endpoint_segment_ids: set[str] | None = None,
    completion_surface: object | None = None,
) -> EndpointJunctionResolution:
    """Resolve the JunctionUnit membership of each Road endpoint once.

    Junction carrier generation and Node compilation share this resolver so a
    carrier is never generated for a different junction interpretation than
    the one used to publish the endpoint Node.
    """

    endpoint_rows = _road_endpoints(roads)
    endpoint_frame = gpd.GeoDataFrame(
        endpoint_rows, geometry="geometry", crs=roads.crs
    )
    memberships = _endpoint_junction_memberships(
        endpoint_frame,
        junction_units,
        config.junction_endpoint_buffer_m,
    )
    split_lineage_override_count = (
        _apply_shared_split_access_lineage(
            endpoint_rows,
            memberships,
            junction_units,
        )
    )
    for index, endpoint in enumerate(endpoint_rows):
        group_id = canonical_id(endpoint["owner_junction_group_id"])
        if endpoint["owner_type"] != "JUNCTION_UNIT" or not group_id:
            continue
        context = _junction_context(group_id, junction_units)
        memberships[index] = {
            "junction_group_id": group_id,
            "junction_kind": context["junction_kind"],
            "junction_source": "junction_carrier_lineage",
        }
    t01_by_id = _node_by_id(t01_nodes)
    for endpoint in endpoint_rows:
        endpoint["source_node_mainnode_group_id"] = (
            _source_node_mainnode_group(
                canonical_id(endpoint["source_node_id"]),
                t01_by_id,
            )
        )
    access_group_by_source = _access_group_by_segment_source(segment_accesses)
    access_geometry_by_source = _access_geometry_by_segment_source(
        segment_accesses
    )
    lineage_override_count = split_lineage_override_count
    built_lineage_handoff_count = 0
    for index, endpoint in enumerate(endpoint_rows):
        source_node_id = canonical_id(endpoint["source_node_id"])
        if not source_node_id:
            continue
        exact_access_group = access_group_by_source.get(
            (str(endpoint["segment_id"]), source_node_id)
        )
        if endpoint["realization"] == "built":
            if not exact_access_group:
                continue
            context = _junction_context(
                exact_access_group,
                junction_units,
            )
            if context["junction_source"] != "swsd_retained":
                continue
            access_geometry = access_geometry_by_source.get(
                (str(endpoint["segment_id"]), source_node_id)
            )
            if (
                str(endpoint["segment_type"]) == "advance_right"
                and (
                    access_geometry is None
                    or float(endpoint["geometry"].distance(access_geometry))
                    > config.relation_endpoint_max_distance_m + 1e-9
                )
            ):
                continue
            if not _physical_portal_supported(
                endpoint["geometry"],
                completion_surface,
            ):
                continue
            lineage_group = exact_access_group
        else:
            lineage_group = exact_access_group or _source_node_mainnode_group(
                source_node_id,
                t01_by_id,
            )
        if not lineage_group:
            continue
        context = _junction_context(lineage_group, junction_units)
        previous = memberships.get(index)
        memberships[index] = {
            "junction_group_id": lineage_group,
            "junction_kind": context["junction_kind"],
            "junction_source": (
                "swsd_retained_exact_segment_access_lineage"
                if endpoint["realization"] == "built"
                else
                "t01_segment_access_lineage"
                if exact_access_group
                else "t01_node_lineage"
            ),
        }
        if endpoint["realization"] == "built":
            built_lineage_handoff_count += 1
        elif (
            previous is not None
            and str(previous["junction_group_id"]) != lineage_group
        ):
            lineage_override_count += 1
    built_access_handoff_count = _materialize_missing_built_access_memberships(
        endpoint_rows,
        memberships,
        segment_accesses,
        junction_units,
        max_distance_m=config.relation_endpoint_max_distance_m,
        semantic_endpoint_segment_ids=semantic_endpoint_segment_ids or set(),
        completion_surface=completion_surface,
        endpoint_buffer_m=config.junction_endpoint_buffer_m,
        minimum_surface_coverage=config.completion_surface_min_coverage,
        maximum_turn_deg=config.completion_hard_max_turn_deg,
        road_geometry_by_id={
            str(row.id): row.geometry
            for row in roads.itertuples(index=False)
        },
    )
    _distribute_colocated_built_portals(
        endpoint_rows,
        memberships,
        junction_units,
        roads,
        inset_m=config.junction_endpoint_buffer_m,
    )
    _enforce_built_endpoint_surface_interior(
        endpoint_rows,
        memberships,
        junction_units,
        roads,
        completion_surface=completion_surface,
        config=config,
    )
    return EndpointJunctionResolution(
        endpoint_rows,
        memberships,
        lineage_override_count,
        built_access_handoff_count + built_lineage_handoff_count,
    )


def build_nodes_and_connect_roads(
    roads: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    explicit_pairs: pd.DataFrame,
    drivezones: gpd.GeoDataFrame,
    t01_nodes: gpd.GeoDataFrame,
    full_rcsd_nodes: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
    materialized_ordinary_group_ids: set[str] | None = None,
    semantic_endpoint_segment_ids: set[str] | None = None,
) -> NodeBuildResult:
    materialized_ordinary_group_ids = materialized_ordinary_group_ids or set()
    drivezone_surface = (
        drivezones.geometry.union_all().buffer(config.completion_surface_buffer_m)
        if not drivezones.empty
        else GeometryCollection()
    )
    accepted_units = (
        junction_units[
            junction_units["junction_source"].isin(
                {"t07_accepted", "t03_accepted", "t04_accepted"}
            )
        ]
        if not junction_units.empty
        and "junction_source" in junction_units
        else junction_units.iloc[0:0]
    )
    accepted_junction_surface = (
        unary_union(
            list(_junction_surfaces(accepted_units).values())
        ).buffer(
            config.completion_surface_buffer_m
        )
        if not accepted_units.empty
        else GeometryCollection()
    )
    handoff_completion_surface = drivezone_surface.union(
        accepted_junction_surface
    )
    resolution = resolve_road_endpoint_junctions(
        roads,
        junction_units,
        segment_accesses,
        t01_nodes,
        config=config,
        semantic_endpoint_segment_ids=semantic_endpoint_segment_ids,
        completion_surface=handoff_completion_surface,
    )
    endpoint_rows = resolution.endpoint_rows
    endpoint_frame = gpd.GeoDataFrame(endpoint_rows, geometry="geometry", crs=roads.crs)
    endpoint_memberships = resolution.memberships
    t01_by_id = _node_by_id(t01_nodes)
    lineage_override_count = resolution.lineage_override_count
    built_access_handoff_count = resolution.built_access_handoff_count
    shared_access_group_pairs = _shared_access_group_pairs(segment_accesses)
    junction_kind_by_group = {
        str(membership["junction_group_id"]): str(membership["junction_kind"])
        for membership in endpoint_memberships.values()
    }
    access_group_ids = (
        {
            canonical_id(value)
            for value in segment_accesses["junction_group_id"]
            if canonical_id(value)
        }
        if "junction_group_id" in segment_accesses
        else set()
    )
    for group_id in access_group_ids:
        junction_kind_by_group.setdefault(
            group_id,
            _junction_context(group_id, junction_units)["junction_kind"],
        )
    parent = list(range(len(endpoint_rows)))
    component_roads = [{row["road_id"]} for row in endpoint_rows]
    component_junction_groups = [
        {str(endpoint_memberships[index]["junction_group_id"])}
        if index in endpoint_memberships
        else set()
        for index in range(len(endpoint_rows))
    ]

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(
        left: int,
        right: int,
        *,
        allow_shared_access_portal: bool = False,
    ) -> bool:
        a, b = find(left), find(right)
        if a == b:
            return True
        if component_roads[a].intersection(component_roads[b]):
            return False
        if (
            component_junction_groups[a]
            and component_junction_groups[b]
            and not component_junction_groups[a].intersection(
                component_junction_groups[b]
            )
            and not (
                allow_shared_access_portal
                and _shared_access_portal_allowed(
                    component_junction_groups[a],
                    component_junction_groups[b],
                    shared_access_group_pairs,
                    junction_kind_by_group,
                )
            )
        ):
            return False
        retained, merged = min(a, b), max(a, b)
        parent[merged] = retained
        component_roads[retained].update(component_roads[merged])
        component_roads[merged].clear()
        component_junction_groups[retained].update(
            component_junction_groups[merged]
        )
        component_junction_groups[merged].clear()
        return True

    indexes_by_road_endpoint: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(endpoint_rows):
        for patch_key in _split_keys(row["patch_road_keys"]):
            indexes_by_road_endpoint.setdefault(
                (patch_key, str(row["endpoint"])), []
            ).append(index)
    road_ids_by_patch_key: dict[str, set[object]] = {}
    for row in endpoint_rows:
        for patch_key in _split_keys(row["all_patch_road_keys"]):
            road_ids_by_patch_key.setdefault(patch_key, set()).add(row["road_id"])
    connection_rows: list[dict[str, object]] = []
    for pair in explicit_pairs.itertuples():
        source_candidates = indexes_by_road_endpoint.get(
            (str(pair.source_patch_road_key), "end"), []
        )
        target_candidates = indexes_by_road_endpoint.get(
            (str(pair.target_patch_road_key), "start"), []
        )
        endpoint_pair = _select_endpoint_pair(
            source_candidates,
            target_candidates,
            endpoint_rows,
        )
        if endpoint_pair is None:
            source_roads = road_ids_by_patch_key.get(
                str(pair.source_patch_road_key), set()
            )
            target_roads = road_ids_by_patch_key.get(
                str(pair.target_patch_road_key), set()
            )
            if source_roads.intersection(target_roads):
                continue
            if source_roads and target_roads:
                connection_rows.append(
                    {
                        "run_id": config.run_id,
                        "source_patch_road_key": str(pair.source_patch_road_key),
                        "target_patch_road_key": str(pair.target_patch_road_key),
                        "source_relation_id": str(pair.source_relation_id),
                        "pair_source": str(pair.pair_source),
                        "source_road_id": "",
                        "target_road_id": "",
                        "source_segment_id": "",
                        "target_segment_id": "",
                        "endpoint_distance_m": math.nan,
                        "same_accepted_surface": False,
                        "drivezone_coverage": 0.0,
                        "connection_decision": "rejected",
                        "reason_codes": "relation_endpoint_orientation_conflict",
                        "geometry": Point(),
                    }
                )
            continue
        source, target = endpoint_pair
        source_road_id = endpoint_rows[source]["road_id"]
        target_road_id = endpoint_rows[target]["road_id"]
        source_segment_id = str(endpoint_rows[source]["segment_id"])
        target_segment_id = str(endpoint_rows[target]["segment_id"])
        same_road = (
            endpoint_rows[source]["road_id"] == endpoint_rows[target]["road_id"]
        )
        same_carrier_lineage = (
            endpoint_rows[source]["carrier_lineage_id"]
            == endpoint_rows[target]["carrier_lineage_id"]
        )
        if same_road or same_carrier_lineage:
            connection_rows.append(
                {
                    "run_id": config.run_id,
                    "source_patch_road_key": str(pair.source_patch_road_key),
                    "target_patch_road_key": str(pair.target_patch_road_key),
                    "source_relation_id": str(pair.source_relation_id),
                    "pair_source": str(pair.pair_source),
                    "source_road_id": source_road_id,
                    "target_road_id": target_road_id,
                    "source_segment_id": source_segment_id,
                    "target_segment_id": target_segment_id,
                    "endpoint_distance_m": 0.0,
                    "same_accepted_surface": False,
                    "drivezone_coverage": 1.0,
                    "connection_decision": "accepted",
                    "reason_codes": (
                        "within_assembled_road"
                        if same_road
                        else "within_assembled_carrier_path"
                    ),
                    "geometry": endpoint_rows[source]["geometry"],
                }
            )
            continue
        source_point = endpoint_rows[source]["geometry"]
        target_point = endpoint_rows[target]["geometry"]
        connector = LineString([source_point, target_point])
        endpoint_distance = float(connector.length)
        distance_ok = endpoint_distance <= config.endpoint_snap_distance_m
        source_membership = endpoint_memberships.get(source)
        target_membership = endpoint_memberships.get(target)
        same_accepted_surface = (
            source_membership is not None
            and target_membership is not None
            and source_membership["junction_group_id"]
            == target_membership["junction_group_id"]
        )
        surface_coverage = _surface_coverage(connector, drivezone_surface)
        surface_supported = surface_coverage >= config.completion_surface_min_coverage
        routed_by_junction_carrier = _same_materialized_ordinary_junction(
            source,
            target,
            endpoint_memberships,
            materialized_ordinary_group_ids,
        )
        same_segment = source_segment_id == target_segment_id
        already_connected = find(source) == find(target)
        accepted = (
            already_connected
            or distance_ok
            or routed_by_junction_carrier
            or (
                same_segment
                and (same_accepted_surface or surface_supported)
            )
        )
        union_accepted = (
            True
            if routed_by_junction_carrier or already_connected
            else union(source, target)
            if accepted
            else False
        )
        reason = (
            "already_connected_physical_component"
            if already_connected
            else "materialized_junction_carrier_path"
            if routed_by_junction_carrier
            else "endpoint_snap"
            if distance_ok
            else "accepted_junction_surface"
            if same_segment and same_accepted_surface
            else "drivezone_supported_completion"
            if same_segment and surface_supported
            else "cross_segment_physical_portal_separation"
            if not same_segment
            else "completion_surface_insufficient"
        )
        if accepted and not union_accepted:
            reason = "junction_group_or_same_road_cycle_rejected"
        connection_rows.append(
            {
                "run_id": config.run_id,
                "source_patch_road_key": str(pair.source_patch_road_key),
                "target_patch_road_key": str(pair.target_patch_road_key),
                "source_relation_id": str(pair.source_relation_id),
                "pair_source": str(pair.pair_source),
                "source_road_id": source_road_id,
                "target_road_id": target_road_id,
                "source_segment_id": source_segment_id,
                "target_segment_id": target_segment_id,
                "endpoint_distance_m": endpoint_distance,
                "same_accepted_surface": same_accepted_surface,
                "drivezone_coverage": surface_coverage,
                "connection_decision": "accepted" if union_accepted else "rejected",
                "reason_codes": reason,
                "geometry": connector,
            }
        )

    endpoints_by_source_node: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(endpoint_rows):
        source_node_id = str(row["source_node_id"])
        if source_node_id:
            endpoints_by_source_node.setdefault(
                (str(row["segment_id"]), source_node_id), []
            ).append(index)
    for (_, source_node_id), indexes in endpoints_by_source_node.items():
        if len(indexes) < 2:
            continue
        anchor = indexes[0]
        for index in indexes[1:]:
            if endpoint_rows[anchor]["road_id"] == endpoint_rows[index]["road_id"]:
                continue
            if _preserve_separate_ordinary_built_portals(
                anchor,
                index,
                endpoint_rows,
                endpoint_memberships,
            ):
                continue
            all_retained = all(
                endpoint_rows[value]["realization"] == "retained"
                for value in (anchor, index)
            )
            connector = LineString(
                [endpoint_rows[anchor]["geometry"], endpoint_rows[index]["geometry"]]
            )
            distance_ok = connector.length <= config.endpoint_snap_distance_m
            surface_coverage = _surface_coverage(connector, drivezone_surface)
            surface_supported = surface_coverage >= config.completion_surface_min_coverage
            within_lineage_limit = (
                connector.length <= config.relation_endpoint_max_distance_m
            )
            routed_by_junction_carrier = _same_materialized_ordinary_junction(
                anchor,
                index,
                endpoint_memberships,
                materialized_ordinary_group_ids,
            )
            accepted = routed_by_junction_carrier or all_retained or (
                within_lineage_limit and distance_ok
            )
            union_accepted = (
                True
                if routed_by_junction_carrier
                else union(anchor, index)
                if accepted
                else False
            )
            connection_rows.append(
                {
                    "run_id": config.run_id,
                    "source_patch_road_key": _first_key(
                        endpoint_rows[anchor]["patch_road_keys"]
                    ),
                    "target_patch_road_key": _first_key(
                        endpoint_rows[index]["patch_road_keys"]
                    ),
                    "source_relation_id": f"swsd-node:{source_node_id}",
                    "pair_source": "swsd_member_node_lineage",
                    "source_road_id": endpoint_rows[anchor]["road_id"],
                    "target_road_id": endpoint_rows[index]["road_id"],
                    "source_segment_id": str(endpoint_rows[anchor]["segment_id"]),
                    "target_segment_id": str(endpoint_rows[index]["segment_id"]),
                    "endpoint_distance_m": float(connector.length),
                    "same_accepted_surface": False,
                    "drivezone_coverage": surface_coverage,
                    "connection_decision": "accepted" if union_accepted else "rejected",
                    "reason_codes": (
                        "source_node_junction_carrier_path"
                        if routed_by_junction_carrier
                        else "retained_source_node_lineage"
                        if all_retained
                        else "source_node_endpoint_snap"
                        if distance_ok
                        else "source_node_lineage_distance_exceeded"
                        if not within_lineage_limit
                        else "source_node_physical_portal_separation"
                    ),
                    "geometry": connector,
                }
            )

    if not endpoint_frame.empty:
        sindex = endpoint_frame.sindex
        for left, row in endpoint_frame.iterrows():
            for right in sindex.query(row.geometry.buffer(1e-6)):
                right = int(right)
                if right <= left:
                    continue
                if row.road_id == endpoint_frame.iloc[right].road_id:
                    continue
                if _preserve_separate_ordinary_built_portals(
                    int(left),
                    right,
                    endpoint_rows,
                    endpoint_memberships,
                ):
                    continue
                distance = row.geometry.distance(endpoint_frame.iloc[right].geometry)
                if distance <= 1e-6:
                    union(
                        int(left),
                        right,
                        allow_shared_access_portal=True,
                    )
        for left, row in endpoint_frame.iterrows():
            for right in sindex.query(row.geometry.buffer(config.endpoint_snap_distance_m)):
                right = int(right)
                if right <= left:
                    continue
                if row.road_id == endpoint_frame.iloc[right].road_id:
                    continue
                if (
                    str(row.endpoint)
                    == str(endpoint_frame.iloc[right].endpoint)
                ):
                    continue
                if _preserve_separate_ordinary_built_portals(
                    int(left),
                    right,
                    endpoint_rows,
                    endpoint_memberships,
                ):
                    continue
                distance = row.geometry.distance(endpoint_frame.iloc[right].geometry)
                if 1e-6 < distance <= config.endpoint_snap_distance_m:
                    union(
                        int(left),
                        right,
                        allow_shared_access_portal=False,
                    )

    endpoint_junction = {
        index: str(membership["junction_group_id"])
        for index, membership in endpoint_memberships.items()
    }
    endpoint_junction_kind = {
        index: str(membership["junction_kind"])
        for index, membership in endpoint_memberships.items()
    }
    endpoint_junction_source = {
        index: str(membership["junction_source"])
        for index, membership in endpoint_memberships.items()
    }
    junction_surfaces = _junction_surfaces(junction_units)
    junction_unit_source_by_group = {
        canonical_id(row.junction_group_id): str(row.junction_source)
        for row in junction_units.itertuples()
    }
    junction_surface_source_by_group = {
        canonical_id(row.junction_group_id): str(
            getattr(row, "surface_source", row.junction_source)
        )
        for row in junction_units.itertuples()
    }
    access_geometries = _segment_access_geometries(segment_accesses)
    access_group_geometries = (
        {
            canonical_id(group_id): group.geometry.union_all()
            for group_id, group in segment_accesses.groupby(
                segment_accesses["junction_group_id"].map(
                    canonical_id
                ),
                sort=True,
            )
        }
        if "junction_group_id" in segment_accesses
        else {}
    )
    clusters: dict[int, list[int]] = {}
    for index in range(len(endpoint_rows)):
        clusters.setdefault(find(index), []).append(index)
    full_nodes_index = full_rcsd_nodes.sindex
    node_rows: list[dict[str, object]] = []
    endpoint_to_node: dict[int, tuple[int, Point, int]] = {}
    used_ids: set[int] = set()
    for cluster_indexes in clusters.values():
        points = [endpoint_rows[index]["geometry"] for index in cluster_indexes]
        point = _cluster_node_point(
            cluster_indexes,
            endpoint_rows,
            endpoint_junction,
            junction_surfaces,
            junction_unit_source_by_group,
            endpoint_buffer_m=config.junction_endpoint_buffer_m,
        )
        source_node_ids = sorted(
            {str(endpoint_rows[index]["source_node_id"]) for index in cluster_indexes if endpoint_rows[index]["source_node_id"]}
        )
        junction_groups = _ordered_junction_groups(
            {
                endpoint_junction[index]
                for index in cluster_indexes
                if index in endpoint_junction
            },
            junction_kind_by_group,
        )
        junction_kinds = sorted(
            {endpoint_junction_kind[index] for index in cluster_indexes if index in endpoint_junction_kind}
        )
        junction_kind = (
            "complex_divmerge"
            if "complex_divmerge" in junction_kinds
            else "ordinary"
            if "ordinary" in junction_kinds
            else "retained"
            if "retained" in junction_kinds
            else ""
        )
        inherited = _near_full_rcsd_node(point, full_rcsd_nodes, full_nodes_index, 1.5)
        if len(source_node_ids) == 1:
            node_id = _safe_int(source_node_ids[0], "node", source_node_ids[0])
        elif inherited is not None:
            node_id = int(inherited.id)
        else:
            signature = ",".join(sorted(str(endpoint_rows[index]["road_id"]) + ":" + str(endpoint_rows[index]["endpoint"]) for index in cluster_indexes))
            node_id = _stable_int("node-cluster", signature)
        if node_id in used_ids:
            node_id = _stable_int("node-collision", f"{node_id}|{point.wkt}")
        used_ids.add(node_id)
        mainnode = _mainnode_id(junction_groups, source_node_ids, t01_by_id, inherited, node_id)
        source = 1 if any(endpoint_rows[index]["realization"] == "built" for index in cluster_indexes) else 2
        node_rows.append(
            {
                "id": node_id,
                "mapid": 0,
                "kind": 0,
                "cross_flag": 0,
                "light_flag": 0,
                "cross_lid": "",
                "mainnodeid": mainnode,
                "subnodeid": "",
                "adjoin_mid": "",
                "adjoind_nid": "",
                "node_lid": "",
                "source": source,
                "city_code": "",
                "layer": 0,
                "city_patch_ids": "",
                "park_patch_ids": "",
                "junction_group_ids": ",".join(junction_groups),
                "junction_kind": junction_kind,
                "run_id": config.run_id,
                "geometry": point,
            }
        )
        for index in cluster_indexes:
            endpoint_to_node[index] = (node_id, point, mainnode)

    updated = roads.copy()
    audit_rows: list[dict[str, object]] = []
    completion_rows: list[dict[str, object]] = []
    road_index_by_id = {str(row.id): index for index, row in updated.iterrows()}
    for endpoint_index, endpoint in enumerate(endpoint_rows):
        node_id, node_point, mainnode = endpoint_to_node[endpoint_index]
        road_index = road_index_by_id[str(endpoint["road_id"])]
        old_geometry = updated.at[road_index, "geometry"]
        new_geometry, completion = _connect_endpoint(old_geometry, endpoint["endpoint"], node_point)
        updated.at[road_index, "geometry"] = new_geometry
        field = "snodeid" if endpoint["endpoint"] == "start" else "enodeid"
        updated.at[road_index, field] = node_id
        updated.at[road_index, "length"] = float(new_geometry.length)
        shift = float(endpoint["geometry"].distance(node_point))
        junction_group = endpoint_junction.get(endpoint_index, "")
        membership_source = endpoint_junction_source.get(endpoint_index, "")
        junction_surface = junction_surfaces.get(junction_group)
        access_geometry = access_geometries.get(
            (str(endpoint["segment_id"]), junction_group)
        )
        surface_distance = (
            float(node_point.distance(junction_surface))
            if junction_surface is not None
            else None
        )
        junction_unit_source = junction_unit_source_by_group.get(
            junction_group,
            "",
        )
        junction_surface_source = junction_surface_source_by_group.get(
            junction_group,
            "",
        )
        junction_surface_required = (
            endpoint["realization"] == "built"
            and junction_unit_source
            in {"t07_accepted", "t03_accepted", "t04_accepted"}
        )
        junction_surface_strict_inside = (
            bool(junction_surface.contains(node_point))
            if junction_surface_required
            and junction_surface is not None
            and not junction_surface.is_empty
            else None
        )
        junction_surface_inset_m = (
            float(node_point.distance(junction_surface.boundary))
            if junction_surface_strict_inside
            else 0.0
            if junction_surface_required
            else None
        )
        access_distance = (
            float(node_point.distance(access_geometry))
            if access_geometry is not None
            else None
        )
        review_required = (
            membership_source
            in {
                "segment_access_surface_handoff",
                "segment_endpoint_access_lineage_override",
                "segment_endpoint_surface_constrained_completion",
                "segment_access_surface_constrained_completion",
            }
            or bool(endpoint["junction_interior_completion_source"])
            or shift > 20.0
        )
        audit_rows.append(
            {
                "run_id": config.run_id,
                "road_id": endpoint["road_id"],
                "endpoint": endpoint["endpoint"],
                "node_id": node_id,
                "mainnodeid": mainnode,
                "junction_group_id": junction_group,
                "junction_membership_source": membership_source,
                "junction_unit_source": junction_unit_source,
                "junction_surface_source": junction_surface_source,
                "junction_surface_distance_m": surface_distance,
                "junction_surface_required": junction_surface_required,
                "junction_surface_strict_inside": (
                    junction_surface_strict_inside
                ),
                "junction_surface_inset_m": junction_surface_inset_m,
                "junction_interior_completion_source": endpoint[
                    "junction_interior_completion_source"
                ],
                "junction_access_distance_m": access_distance,
                "realization": endpoint["realization"],
                "owner_type": endpoint["owner_type"],
                "endpoint_shift_m": shift,
                "connection_state": "unchanged" if shift <= 1e-6 else "hp_constrained_completion",
                "review_required": review_required,
                "reason_codes": membership_source or "no_junction_membership",
                "geometry": node_point,
            }
        )
        if completion is not None and completion.length > 1e-6:
            completion_rows.append(
                {
                    "run_id": config.run_id,
                    "road_id": endpoint["road_id"],
                    "segment_id": endpoint["segment_id"],
                    "source_span_id": f"{endpoint['road_id']}:{endpoint['endpoint']}:completion",
                    "endpoint": endpoint["endpoint"],
                    "geometry_source": "hp_constrained_completion"
                    if endpoint["realization"] == "built"
                    else "retained_endpoint_coordination",
                    "source_object_ids": str(node_id),
                    "start_fraction": None,
                    "end_fraction": None,
                    "length_m": float(completion.length),
                    "geometry": completion,
                }
            )
    recovered_junction_lineage_count = 0
    recovered_node_groups: dict[str, str] = {}
    for node_row in node_rows:
        mainnode_group = canonical_id(node_row["mainnodeid"])
        if mainnode_group not in access_group_ids:
            continue
        surface = junction_surfaces.get(mainnode_group)
        unit_source = junction_unit_source_by_group.get(mainnode_group, "")
        if (
            unit_source in {"t07_accepted", "t03_accepted", "t04_accepted"}
            and (
                surface is None
                or surface.is_empty
                or not surface.contains(node_row["geometry"])
            )
        ):
            continue
        access_geometry = access_group_geometries.get(mainnode_group)
        if not (
            (
                surface is not None
                and float(node_row["geometry"].distance(surface))
                <= config.relation_endpoint_max_distance_m + 1e-9
            )
            or (
                access_geometry is not None
                and float(
                    node_row["geometry"].distance(access_geometry)
                )
                <= config.relation_endpoint_max_distance_m + 1e-9
            )
        ):
            continue
        groups = set(_split_keys(node_row["junction_group_ids"]))
        if mainnode_group in groups:
            continue
        groups.add(mainnode_group)
        node_row["junction_group_ids"] = ",".join(
            _ordered_junction_groups(groups, junction_kind_by_group)
        )
        if not str(node_row["junction_kind"]):
            node_row["junction_kind"] = junction_kind_by_group.get(
                mainnode_group,
                "retained",
            )
        recovered_node_groups[str(node_row["id"])] = mainnode_group
        recovered_junction_lineage_count += 1
    for audit_row in audit_rows:
        group_id = recovered_node_groups.get(str(audit_row["node_id"]))
        if not group_id or str(audit_row["junction_group_id"]):
            continue
        audit_row["junction_group_id"] = group_id
        audit_row["junction_membership_source"] = (
            "swsd_mainnode_lineage_recovered"
        )
        surface = junction_surfaces.get(group_id)
        unit_source = junction_unit_source_by_group.get(group_id, "")
        audit_row["junction_surface_distance_m"] = (
            float(audit_row["geometry"].distance(surface))
            if surface is not None
            else None
        )
        audit_row["junction_unit_source"] = unit_source
        audit_row["junction_surface_source"] = (
            junction_surface_source_by_group.get(group_id, "")
        )
        required = (
            str(audit_row["realization"]) == "built"
            and unit_source
            in {"t07_accepted", "t03_accepted", "t04_accepted"}
        )
        strict_inside = bool(
            required
            and surface is not None
            and not surface.is_empty
            and surface.contains(audit_row["geometry"])
        )
        audit_row["junction_surface_required"] = required
        audit_row["junction_surface_strict_inside"] = (
            strict_inside if required else None
        )
        audit_row["junction_surface_inset_m"] = (
            float(audit_row["geometry"].distance(surface.boundary))
            if strict_inside
            else 0.0
            if required
            else None
        )
        audit_row["reason_codes"] = "swsd_mainnode_lineage_recovered"
    nodes = gpd.GeoDataFrame(node_rows, geometry="geometry", crs=roads.crs)
    audit = gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=roads.crs)
    completions = _records_geodataframe(
        completion_rows,
        roads.crs,
        columns=(
            "run_id",
            "road_id",
            "segment_id",
            "source_span_id",
            "endpoint",
            "geometry_source",
            "source_object_ids",
            "start_fraction",
            "end_fraction",
            "length_m",
        ),
    )
    connection_evidence = _records_geodataframe(
        connection_rows,
        roads.crs,
        columns=(
            "run_id",
            "source_patch_road_key",
            "target_patch_road_key",
            "source_relation_id",
            "pair_source",
            "source_road_id",
            "target_road_id",
            "source_segment_id",
            "target_segment_id",
            "endpoint_distance_m",
            "same_accepted_surface",
            "drivezone_coverage",
            "connection_decision",
            "reason_codes",
        ),
    )
    summary = {
        "node_count": int(len(nodes)),
        "road_endpoint_count": int(len(endpoint_rows)),
        "constrained_completion_count": int(len(completions)),
        "max_endpoint_shift_m": float(audit["endpoint_shift_m"].max()) if not audit.empty else 0.0,
        "missing_node_reference_count": int(
            (~updated["snodeid"].isin(nodes["id"])).sum() + (~updated["enodeid"].isin(nodes["id"])).sum()
        ),
        "explicit_pair_accepted_count": int(
            connection_evidence["connection_decision"].eq("accepted").sum()
        ),
        "explicit_pair_rejected_count": int(
            connection_evidence["connection_decision"].eq("rejected").sum()
        ),
        "retained_lineage_override_count": lineage_override_count,
        "recovered_junction_lineage_count": (
            recovered_junction_lineage_count
        ),
        "built_access_handoff_count": built_access_handoff_count,
        "built_accepted_surface_endpoint_count": int(
            audit["junction_surface_required"].fillna(False).astype(bool).sum()
        ),
        "built_accepted_surface_endpoint_outside_count": int(
            (
                audit["junction_surface_required"].fillna(False).astype(bool)
                & ~audit["junction_surface_strict_inside"]
                .fillna(False)
                .astype(bool)
            ).sum()
        ),
        "minimum_built_accepted_surface_inset_m": float(
            audit.loc[
                audit["junction_surface_required"]
                .fillna(False)
                .astype(bool)
                & audit["junction_surface_strict_inside"]
                .fillna(False)
                .astype(bool),
                "junction_surface_inset_m",
            ].min()
        )
        if bool(
            (
                audit["junction_surface_required"]
                .fillna(False)
                .astype(bool)
                & audit["junction_surface_strict_inside"]
                .fillna(False)
                .astype(bool)
            ).any()
        )
        else 0.0,
        "built_access_handoff_max_surface_distance_m": float(
            audit.loc[
                audit["junction_membership_source"].isin(
                    {
                        "segment_access_surface_handoff",
                        "segment_endpoint_access_lineage_override",
                        "segment_endpoint_surface_constrained_completion",
                        "segment_access_surface_constrained_completion",
                    }
                ),
                "junction_surface_distance_m",
            ].max()
        )
        if built_access_handoff_count
        else 0.0,
    }
    return NodeBuildResult(
        updated,
        nodes,
        audit,
        completions,
        connection_evidence,
        summary,
    )


def _select_endpoint_pair(
    source_candidates: list[int],
    target_candidates: list[int],
    endpoint_rows: list[dict[str, object]],
) -> tuple[int, int] | None:
    if not source_candidates or not target_candidates:
        return None
    return min(
        (
            (source, target)
            for source in source_candidates
            for target in target_candidates
        ),
        key=lambda pair: (
            endpoint_rows[pair[0]]["road_id"]
            != endpoint_rows[pair[1]]["road_id"],
            float(
                endpoint_rows[pair[0]]["geometry"].distance(
                    endpoint_rows[pair[1]]["geometry"]
                )
            ),
            pair,
        ),
    )


def _same_materialized_ordinary_junction(
    left: int,
    right: int,
    memberships: dict[int, dict[str, object]],
    materialized_group_ids: set[str],
) -> bool:
    left_membership = memberships.get(left)
    right_membership = memberships.get(right)
    if left_membership is None or right_membership is None:
        return False
    group_id = str(left_membership["junction_group_id"])
    kinds = {
        str(left_membership["junction_kind"]),
        str(right_membership["junction_kind"]),
    }
    return (
        group_id == str(right_membership["junction_group_id"])
        and kinds.issubset({"ordinary", "retained"})
        and (
            group_id in materialized_group_ids
            or kinds == {"retained"}
        )
    )


def _preserve_separate_ordinary_built_portals(
    left: int,
    right: int,
    endpoint_rows: list[dict[str, object]],
    memberships: dict[int, dict[str, object]],
) -> bool:
    left_membership = memberships.get(left)
    right_membership = memberships.get(right)
    if left_membership is None or right_membership is None:
        return False
    left_endpoint = endpoint_rows[left]
    right_endpoint = endpoint_rows[right]
    realizations = {
        str(left_endpoint["realization"]),
        str(right_endpoint["realization"]),
    }
    roles = {
        str(left_endpoint["carrier_role"]),
        str(right_endpoint["carrier_role"]),
    }
    separate_built_lineages = (
        realizations == {"built"}
        and {
            str(left_endpoint["owner_type"]),
            str(right_endpoint["owner_type"]),
        }
        == {"SEGMENT"}
        and left_endpoint["carrier_lineage_id"]
        != right_endpoint["carrier_lineage_id"]
    )
    separate_built_from_retained_semantic = (
        realizations == {"built", "retained"}
        and "semantic_carrier" in roles
        and any(role.startswith("main_") for role in roles)
    )
    return bool(
        str(left_membership["junction_group_id"])
        == str(right_membership["junction_group_id"])
        and {
            str(left_membership["junction_kind"]),
            str(right_membership["junction_kind"]),
        }.issubset({"ordinary", "retained"})
        and (
            separate_built_lineages
            or separate_built_from_retained_semantic
        )
    )


def _distribute_colocated_built_portals(
    endpoint_rows: list[dict[str, object]],
    memberships: dict[int, dict[str, object]],
    junction_units: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    *,
    inset_m: float,
) -> int:
    surfaces = _junction_surfaces(junction_units)
    unit_sources = {
        canonical_id(row.junction_group_id): str(row.junction_source)
        for row in junction_units.itertuples(index=False)
    }
    road_geometry = {
        row.id: row.geometry for row in roads.itertuples(index=False)
    }
    groups: dict[tuple[str, float, float], list[int]] = {}
    for index, endpoint in enumerate(endpoint_rows):
        membership = memberships.get(index)
        if (
            membership is None
            or endpoint["realization"] != "built"
            or str(membership["junction_kind"]) != "ordinary"
        ):
            continue
        group_id = canonical_id(membership["junction_group_id"])
        if unit_sources.get(group_id) == "swsd_retained":
            continue
        point = endpoint["geometry"]
        groups.setdefault(
            (group_id, round(float(point.x), 6), round(float(point.y), 6)),
            [],
        ).append(index)
    moved = 0
    for (group_id, _, _), indexes in groups.items():
        if len(indexes) < 2 or len(
            {
                endpoint_rows[index]["carrier_lineage_id"]
                for index in indexes
            }
        ) < 2:
            continue
        surface = surfaces.get(group_id)
        if surface is None or surface.is_empty:
            continue
        target_surface = interior_surface_target(
            surface,
            inset_m=inset_m,
        )
        portals: dict[int, Point] = {}
        for index in indexes:
            endpoint = endpoint_rows[index]
            portal = _directional_surface_portal(
                road_geometry.get(endpoint["road_id"]),
                str(endpoint["endpoint"]),
                target_surface,
            )
            if portal is None:
                portals = {}
                break
            portals[index] = portal
        if len(portals) != len(indexes) or len(
            {
                (round(float(point.x), 6), round(float(point.y), 6))
                for point in portals.values()
            }
        ) < 2:
            continue
        for index, portal in portals.items():
            endpoint_rows[index]["geometry"] = portal
            memberships[index]["junction_source"] = (
                "accepted_surface_directional_portal"
            )
            moved += 1
    return moved


def _enforce_built_endpoint_surface_interior(
    endpoint_rows: list[dict[str, object]],
    memberships: dict[int, dict[str, object]],
    junction_units: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    *,
    completion_surface: object | None,
    config: SegmentFirstConfig,
) -> int:
    surfaces = _junction_surfaces(junction_units)
    accepted_sources = {
        canonical_id(row.junction_group_id): str(row.junction_source)
        for row in junction_units.itertuples(index=False)
    }
    road_geometry = {
        str(row.id): row.geometry for row in roads.itertuples(index=False)
    }
    moved = 0
    for index, endpoint in enumerate(endpoint_rows):
        membership = memberships.get(index)
        if membership is None or endpoint["realization"] != "built":
            continue
        group_id = canonical_id(membership["junction_group_id"])
        if accepted_sources.get(group_id) not in {
            "t07_accepted",
            "t03_accepted",
            "t04_accepted",
        }:
            continue
        surface = surfaces.get(group_id)
        point = endpoint["geometry"]
        if (
            surface is None
            or surface.is_empty
            or surface.contains(point)
        ):
            continue
        target_surface = interior_surface_target(
            surface,
            inset_m=config.junction_endpoint_buffer_m,
        )
        geometry = road_geometry.get(str(endpoint["road_id"]))
        target_point = nearest_points(point, target_surface)[1]
        if _target_on_existing_endpoint_segment(endpoint, target_point):
            endpoint["geometry"] = target_point
            endpoint["junction_interior_completion_source"] = (
                "accepted_surface_interior_existing_road_trim"
            )
            moved += 1
            continue
        existing_portal = (
            _directional_surface_portal(
                geometry,
                str(endpoint["endpoint"]),
                target_surface,
            )
            if geometry is not None
            else None
        )
        if (
            existing_portal is not None
            and surface.contains(existing_portal)
        ):
            endpoint["geometry"] = existing_portal
            endpoint["junction_interior_completion_source"] = (
                "accepted_surface_interior_existing_road_trim"
            )
            moved += 1
            continue
        completion = (
            route_tangent_endpoint_to_surface(
                geometry,
                str(endpoint["endpoint"]),
                target_surface,
                completion_surface,
                maximum_distance_m=(
                    config.relation_endpoint_max_distance_m
                ),
                minimum_coverage=config.completion_surface_min_coverage,
            )
            if geometry is not None
            else None
        )
        completion_source = "accepted_surface_interior_tangent_completion"
        if completion is None:
            target = nearest_points(point, target_surface)[1]
            if not _completion_extends_outward(endpoint, target):
                continue
            completion = route_endpoint_to_surface(
                point,
                target_surface,
                completion_surface,
                maximum_distance_m=config.relation_endpoint_max_distance_m,
                minimum_coverage=config.completion_surface_min_coverage,
            )
            completion_source = "accepted_surface_interior_routed_completion"
        if completion is None or completion.is_empty:
            continue
        portal = Point(completion.coords[-1])
        if not surface.contains(portal):
            continue
        endpoint["geometry"] = portal
        endpoint["junction_interior_completion_source"] = completion_source
        moved += 1
    return moved


def _directional_surface_portal(
    geometry: LineString | None,
    endpoint: str,
    surface: object,
) -> Point | None:
    if geometry is None or geometry.is_empty or geometry.length <= 1e-9:
        return None
    points = _intersection_points(geometry.intersection(surface.boundary))
    measures = sorted(
        {
            round(float(geometry.project(point)), 9)
            for point in points
            if float(point.distance(geometry)) <= 1e-6
        }
    )
    if endpoint == "start":
        candidates = [value for value in measures if value > 1e-6]
        measure = min(candidates) if candidates else None
    else:
        candidates = [
            value for value in measures
            if value < float(geometry.length) - 1e-6
        ]
        measure = max(candidates) if candidates else None
    if measure is None:
        return None
    return geometry.interpolate(measure)


def _intersection_points(geometry: object) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
        return [Point(coords[0]), Point(coords[-1])]
    points: list[Point] = []
    for part in getattr(geometry, "geoms", ()):
        points.extend(_intersection_points(part))
    return points


def _surface_coverage(connector: LineString, surface: object | None) -> float:
    if connector.length <= 1e-9:
        return 1.0
    if surface is None or surface.is_empty:
        return 0.0
    return float(connector.intersection(surface).length / connector.length)


def _records_geodataframe(
    records: list[dict[str, object]],
    crs: object,
    *,
    columns: tuple[str, ...],
) -> gpd.GeoDataFrame:
    if records:
        return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)
    data = {column: pd.Series(dtype="object") for column in columns}
    data["geometry"] = gpd.GeoSeries([], crs=crs)
    return gpd.GeoDataFrame(data, geometry="geometry", crs=crs)


def _endpoint_junction_memberships(
    endpoints: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    buffer_m: float,
) -> dict[int, dict[str, object]]:
    if endpoints.empty or junction_units.empty:
        return {}
    accepted = junction_units[
        junction_units["junction_source"].isin(
            {"t03_accepted", "t04_accepted", "t07_accepted"}
        )
    ].copy()
    if accepted.empty:
        return {}
    accepted.geometry = gpd.GeoSeries(
        [
            endpoint_surface_geometry(row)
            for row in accepted.itertuples(index=False)
        ],
        index=accepted.index,
        crs=accepted.crs,
    )
    sindex = accepted.sindex
    result: dict[int, dict[str, object]] = {}
    for endpoint_index, endpoint in endpoints.iterrows():
        candidates: list[pd.Series] = []
        for candidate_index in sindex.query(endpoint.geometry):
            candidate = accepted.iloc[int(candidate_index)]
            geometry = candidate.geometry
            if geometry is None or geometry.is_empty:
                continue
            if geometry.contains(endpoint.geometry):
                candidates.append(candidate)
        if not candidates:
            continue
        selected = min(
            candidates,
            key=lambda row: (
                -int(row.get("source_priority", 0)),
                float(row.geometry.area),
                str(row.get("junction_group_id", "")),
            ),
        )
        result[int(endpoint_index)] = {
            "junction_group_id": str(selected["junction_group_id"]),
            "junction_kind": str(selected["junction_kind"]),
            "junction_source": str(selected["junction_source"]),
        }
    return result


def _access_group_by_segment_source(
    accesses: gpd.GeoDataFrame,
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    if accesses.empty:
        return result
    for access in accesses.itertuples():
        key = (str(access.segment_id), canonical_id(access.source_node_id))
        group = canonical_id(access.junction_group_id)
        if key[1] and group:
            result[key] = group
    return result


def _access_geometry_by_segment_source(
    accesses: gpd.GeoDataFrame,
) -> dict[tuple[str, str], object]:
    if accesses.empty:
        return {}
    keys = [
        accesses["segment_id"].astype(str),
        accesses["source_node_id"].map(canonical_id),
    ]
    return {
        (str(segment_id), str(source_node_id)): frame.geometry.union_all()
        for (segment_id, source_node_id), frame in accesses.groupby(
            keys,
            sort=True,
        )
    }


def _junction_context(
    junction_group_id: str,
    junction_units: gpd.GeoDataFrame,
) -> dict[str, str]:
    candidates = junction_units[
        junction_units["junction_group_id"].map(canonical_id) == junction_group_id
    ]
    if candidates.empty:
        return {"junction_kind": "retained", "junction_source": "swsd_retained"}
    selected = min(
        candidates.itertuples(),
        key=lambda row: (
            -int(getattr(row, "source_priority", 0)),
            float(row.geometry.area),
            str(getattr(row, "source_object_id", "")),
        ),
    )
    return {
        "junction_kind": str(selected.junction_kind),
        "junction_source": str(selected.junction_source),
    }


def _materialize_missing_built_access_memberships(
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
) -> int:
    """Bind every uncovered built Road handoff for a Segment access.

    This is relation-scoped handoff against the accepted JunctionUnit surface,
    not a global distance search for a junction. Existing memberships are never
    reassigned, so an ambiguous candidate remains a hard-gate failure.
    """

    if accesses.empty:
        return 0
    endpoints_by_segment: dict[str, list[int]] = {}
    for index, endpoint in enumerate(endpoint_rows):
        endpoints_by_segment.setdefault(str(endpoint["segment_id"]), []).append(index)
    surface_by_group = _junction_surfaces(junction_units)
    count = 0
    ordered_accesses = accesses.sort_values(
        ["segment_id", "access_type", "access_ordinal", "access_id"]
    )
    for access in ordered_accesses.itertuples():
        segment_id = str(access.segment_id)
        access_id = str(access.access_id)
        group = canonical_id(access.junction_group_id)
        indexes = endpoints_by_segment.get(segment_id, [])
        target = surface_by_group.get(group, access.geometry)
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
                        float(access.geometry.distance(point)),
                        str(endpoint["endpoint"]),
                        index,
                    )
                )
            context = _junction_context(group, junction_units)
            for candidates in candidates_by_role.values():
                surface_distance, _, _, index = min(candidates)
                if surface_distance > max_distance_m:
                    continue
                if (
                    context["junction_source"] == "swsd_retained"
                    and not _physical_portal_supported(
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
                    existing_trim = _target_on_existing_endpoint_segment(
                        endpoint_rows[index],
                        target_point,
                    )
                    outward_completion = _completion_extends_outward(
                        endpoint_rows[index],
                        target_point,
                    )
                    smooth_lateral = (
                        not existing_trim
                        and not outward_completion
                        and _smooth_surface_completion_supported(
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
                    coverage = _surface_coverage(
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
                    float(access.geometry.distance(point)),
                    str(endpoint["endpoint"]),
                    index,
                )
            )
        context = _junction_context(group, junction_units)
        for candidates in candidates_by_road.values():
            distance, _, _, index = min(candidates)
            if distance > max_distance_m:
                continue
            if (
                context["junction_source"] == "swsd_retained"
                and not _physical_portal_supported(
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
                existing_trim = _target_on_existing_endpoint_segment(
                    endpoint_rows[index],
                    target_point,
                )
                outward_completion = _completion_extends_outward(
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
                    and _smooth_surface_completion_supported(
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
                coverage = _surface_coverage(
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
    return count


def _junction_surfaces(
    junction_units: gpd.GeoDataFrame,
) -> dict[str, object]:
    if junction_units.empty:
        return {}
    return {
        str(group): unary_union(
            [
                endpoint_surface_geometry(row)
                for row in frame.itertuples(index=False)
            ]
        )
        for group, frame in junction_units.groupby(
            junction_units["junction_group_id"].map(canonical_id)
        )
    }


def _physical_portal_supported(
    point: Point,
    completion_surface: object | None,
) -> bool:
    """Require final SWSD-only portal geometry to stay on a Road surface.

    ``None`` is reserved for preliminary resolution where a surface was not
    supplied.  The final Node build supplies either buffered DriveZone or an
    explicit empty geometry, preventing semantic lineage from hiding a
    physically unsupported endpoint.
    """

    if completion_surface is None:
        return True
    return bool(
        not completion_surface.is_empty
        and float(point.distance(completion_surface)) <= 1e-9
    )


def _completion_extends_outward(
    endpoint: dict[str, object],
    target: Point,
    *,
    maximum_turn_deg: float = 75.0,
) -> bool:
    point = endpoint["geometry"]
    interior_x = float(endpoint["interior_x"])
    interior_y = float(endpoint["interior_y"])
    outward_x = float(point.x) - interior_x
    outward_y = float(point.y) - interior_y
    completion_x = float(target.x) - float(point.x)
    completion_y = float(target.y) - float(point.y)
    outward_norm = math.hypot(outward_x, outward_y)
    completion_norm = math.hypot(completion_x, completion_y)
    if outward_norm <= 1e-9 or completion_norm <= 1e-9:
        return True
    cosine = max(
        -1.0,
        min(
            1.0,
            (
                outward_x * completion_x + outward_y * completion_y
            )
            / (outward_norm * completion_norm),
        ),
    )
    return math.degrees(math.acos(cosine)) <= maximum_turn_deg


def _target_on_existing_endpoint_segment(
    endpoint: dict[str, object],
    target: Point,
) -> bool:
    point = endpoint["geometry"]
    segment = LineString(
        [
            point,
            Point(
                float(endpoint["interior_x"]),
                float(endpoint["interior_y"]),
            ),
        ]
    )
    return bool(
        segment.length > 1e-9
        and float(target.distance(segment)) <= 1e-6
        and float(point.distance(target)) <= float(segment.length) + 1e-6
    )


def _smooth_surface_completion_supported(
    geometry: LineString | None,
    endpoint_name: str,
    target: Point,
    completion_surface: object | None,
    *,
    maximum_distance_m: float,
    minimum_surface_coverage: float,
    maximum_turn_deg: float,
) -> bool:
    if (
        geometry is None
        or geometry.is_empty
        or completion_surface is None
        or completion_surface.is_empty
    ):
        return False
    endpoint = Point(
        geometry.coords[0]
        if endpoint_name == "start"
        else geometry.coords[-1]
    )
    if float(endpoint.distance(target)) > maximum_distance_m + 1e-9:
        return False
    candidate, completion = _connect_endpoint(
        geometry,
        endpoint_name,
        target,
    )
    return bool(
        completion is not None
        and not completion.is_empty
        and candidate.is_valid
        and candidate.is_simple
        and _surface_coverage(completion, completion_surface)
        + 1e-9
        >= minimum_surface_coverage
        and _max_sample_turn(completion, 1.0)
        <= maximum_turn_deg + 1e-9
        and _max_sample_turn(candidate, 2.0)
        <= maximum_turn_deg + 1e-9
    )


def _cluster_node_point(
    cluster_indexes: list[int],
    endpoint_rows: list[dict[str, object]],
    endpoint_junction: dict[int, str],
    junction_surfaces: dict[str, object],
    junction_source_by_group: dict[str, str],
    *,
    endpoint_buffer_m: float,
) -> Point:
    points = [endpoint_rows[index]["geometry"] for index in cluster_indexes]
    trusted_portals: list[Point] = []
    for index in cluster_indexes:
        group_id = endpoint_junction.get(index, "")
        surface = junction_surfaces.get(group_id)
        point = endpoint_rows[index]["geometry"]
        if (
            group_id
            and junction_source_by_group.get(group_id) != "swsd_retained"
            and surface is not None
            and not surface.is_empty
            and surface.contains(point)
        ):
            trusted_portals.append(point)
    if trusted_portals:
        return min(
            trusted_portals,
            key=lambda candidate: (
                sum(float(candidate.distance(other)) for other in trusted_portals),
                float(candidate.x),
                float(candidate.y),
            ),
        )
    return Point(
        float(np.median([item.x for item in points])),
        float(np.median([item.y for item in points])),
    )


def _segment_access_geometries(
    accesses: gpd.GeoDataFrame,
) -> dict[tuple[str, str], object]:
    if accesses.empty:
        return {}
    keys = [
        accesses["segment_id"].astype(str),
        accesses["junction_group_id"].map(canonical_id),
    ]
    return {
        (str(segment_id), str(group)): frame.geometry.union_all()
        for (segment_id, group), frame in accesses.groupby(keys)
    }


def _road_endpoints(roads: gpd.GeoDataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for road in roads.itertuples():
        coords = list(road.geometry.coords)
        retained = str(road.realization) == "retained"
        raw_carrier_id = getattr(road, "carrier_id", "")
        carrier_id = (
            str(raw_carrier_id)
            if pd.notna(raw_carrier_id) and str(raw_carrier_id)
            else f"road:{road.id}"
        )
        carrier_lineage_id = carrier_id.split(":part:", 1)[0]
        internal_start = getattr(road, "lineage_internal_start", False)
        internal_end = getattr(road, "lineage_internal_end", False)
        start_keys = (
            ""
            if pd.notna(internal_start) and bool(internal_start)
            else str(
                getattr(road, "start_patch_road_keys", "")
                or getattr(road, "patch_road_key", "")
            )
        )
        end_keys = (
            ""
            if pd.notna(internal_end) and bool(internal_end)
            else str(
                getattr(road, "end_patch_road_keys", "")
                or getattr(road, "patch_road_key", "")
            )
        )
        all_keys = str(
            getattr(road, "source_patch_road_keys", "")
            or getattr(road, "patch_road_key", "")
        )
        completion_access_ids = getattr(
            road, "constrained_completion_access_ids", ""
        )
        support_access_ids = getattr(road, "access_support_access_ids", "")
        rows.extend(
            [
                {
                    "road_id": road.id,
                    "segment_id": road.segment_id,
                    "segment_type": str(getattr(road, "segment_type", "normal")),
                    "target_class": str(getattr(road, "target_class", "not_target")),
                    "patch_road_key": start_keys,
                    "patch_road_keys": start_keys,
                    "all_patch_road_keys": all_keys,
                    "realization": road.realization,
                    "owner_type": str(getattr(road, "owner_type", "SEGMENT")),
                    "owner_junction_group_id": canonical_id(
                        getattr(road, "junction_group_id", "")
                    ),
                    "declared_junction_group_id": _single_key(
                        getattr(road, "start_junction_group_ids", "")
                    ),
                    "carrier_role": str(getattr(road, "carrier_role", "")),
                    "access_support_access_ids": support_access_ids,
                    "constrained_completion_access_ids": completion_access_ids,
                    "carrier_lineage_id": carrier_lineage_id,
                    "junction_interior_completion_source": "",
                    "endpoint": "start",
                    "source_node_id": canonical_id(getattr(road, "source_snodeid", "")),
                    "interior_x": float(coords[1][0]),
                    "interior_y": float(coords[1][1]),
                    "geometry": Point(coords[0]),
                },
                {
                    "road_id": road.id,
                    "segment_id": road.segment_id,
                    "segment_type": str(getattr(road, "segment_type", "normal")),
                    "target_class": str(getattr(road, "target_class", "not_target")),
                    "patch_road_key": end_keys,
                    "patch_road_keys": end_keys,
                    "all_patch_road_keys": all_keys,
                    "realization": road.realization,
                    "owner_type": str(getattr(road, "owner_type", "SEGMENT")),
                    "owner_junction_group_id": canonical_id(
                        getattr(road, "junction_group_id", "")
                    ),
                    "declared_junction_group_id": _single_key(
                        getattr(road, "end_junction_group_ids", "")
                    ),
                    "carrier_role": str(getattr(road, "carrier_role", "")),
                    "access_support_access_ids": support_access_ids,
                    "constrained_completion_access_ids": completion_access_ids,
                    "carrier_lineage_id": carrier_lineage_id,
                    "junction_interior_completion_source": "",
                    "endpoint": "end",
                    "source_node_id": canonical_id(getattr(road, "source_enodeid", "")),
                    "interior_x": float(coords[-2][0]),
                    "interior_y": float(coords[-2][1]),
                    "geometry": Point(coords[-1]),
                },
            ]
        )
    return rows


def _apply_shared_split_access_lineage(
    endpoint_rows: list[dict[str, object]],
    memberships: dict[int, dict[str, object]],
    junction_units: gpd.GeoDataFrame,
) -> int:
    """Use declared access lineage only at an actual shared split boundary."""

    surfaces = _junction_surfaces(junction_units)
    candidates: dict[tuple[str, float, float], list[int]] = {}
    for index, endpoint in enumerate(endpoint_rows):
        group_id = canonical_id(
            endpoint["declared_junction_group_id"]
        )
        carrier_lineage_id = str(
            endpoint["carrier_lineage_id"]
        )
        if not group_id or not carrier_lineage_id:
            continue
        point = endpoint["geometry"]
        candidates.setdefault(
            (
                carrier_lineage_id,
                round(float(point.x), 6),
                round(float(point.y), 6),
            ),
            [],
        ).append(index)

    override_count = 0
    for indexes in candidates.values():
        if len(indexes) < 2:
            continue
        if {endpoint_rows[index]["endpoint"] for index in indexes} != {
            "start",
            "end",
        }:
            continue
        if len({endpoint_rows[index]["road_id"] for index in indexes}) < 2:
            continue
        group_ids = {
            canonical_id(
                endpoint_rows[index]["declared_junction_group_id"]
            )
            for index in indexes
        }
        if len(group_ids) != 1:
            continue
        group_id = next(iter(group_ids))
        context = _junction_context(group_id, junction_units)
        surface = surfaces.get(group_id)
        split_point = endpoint_rows[indexes[0]]["geometry"]
        if (
            context["junction_source"] != "swsd_retained"
            and (
                surface is None
                or surface.is_empty
                or not surface.contains(split_point)
            )
        ):
            continue
        for index in indexes:
            previous = memberships.get(index)
            if (
                previous is not None
                and str(previous["junction_group_id"]) != group_id
            ):
                override_count += 1
            memberships[index] = {
                "junction_group_id": group_id,
                "junction_kind": context["junction_kind"],
                "junction_source": "carrier_split_access_lineage",
            }
    return override_count


def _split_keys(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _single_key(value: object) -> str:
    keys = _split_keys(value)
    return canonical_id(keys[0]) if len(keys) == 1 else ""


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


def _shared_access_group_pairs(accesses: gpd.GeoDataFrame) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    if accesses.empty:
        return pairs
    for _, frame in accesses.groupby(accesses["segment_id"].astype(str)):
        groups = sorted(
            {
                canonical_id(value)
                for value in frame["junction_group_id"]
                if canonical_id(value)
            }
        )
        for index, left in enumerate(groups):
            for right in groups[index + 1 :]:
                pairs.add(frozenset((left, right)))
    return pairs


def _shared_access_portal_allowed(
    left_groups: set[str],
    right_groups: set[str],
    shared_pairs: set[frozenset[str]],
    kind_by_group: dict[str, str],
) -> bool:
    for left in left_groups:
        for right in right_groups:
            kinds = {kind_by_group.get(left, ""), kind_by_group.get(right, "")}
            if (
                frozenset((left, right)) not in shared_pairs
                or "retained" not in kinds
                or len(kinds) != 2
            ):
                return False
    return True


def _ordered_junction_groups(
    groups: set[str],
    kind_by_group: dict[str, str],
) -> list[str]:
    priority = {"ordinary": 0, "complex_divmerge": 1, "retained": 2}
    return sorted(
        groups,
        key=lambda group: (priority.get(kind_by_group.get(group, ""), 3), group),
    )


def _first_key(value: object) -> str:
    keys = _split_keys(value)
    return keys[0] if keys else ""


def _split_same_road_endpoint_clusters(
    clusters: dict[int, list[int]],
    endpoint_rows: list[dict[str, object]],
) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    next_key = max(clusters, default=0) + 1
    for key, indexes in clusters.items():
        seen_roads: set[object] = set()
        retained: list[int] = []
        for index in indexes:
            road_id = endpoint_rows[index]["road_id"]
            if road_id in seen_roads:
                result[next_key] = [index]
                next_key += 1
            else:
                seen_roads.add(road_id)
                retained.append(index)
        if retained:
            result[key] = retained
    return result


def _connect_endpoint(line: LineString, endpoint: str, node: Point) -> tuple[LineString, LineString | None]:
    reverse = endpoint == "start"
    coords = [(coord[0], coord[1]) for coord in line.coords]
    oriented = list(reversed(coords)) if reverse else coords
    observed_endpoint = Point(oriented[-1])
    distance = observed_endpoint.distance(node)
    if distance <= 1e-6:
        return line, None
    projection = float(line.project(node))
    projected = line.interpolate(projection)
    if (
        float(projected.distance(node)) <= 1e-6
        and 1e-6 < projection < float(line.length) - 1e-6
    ):
        trimmed = (
            substring(line, projection, float(line.length))
            if endpoint == "start"
            else substring(line, 0.0, projection)
        )
        if isinstance(trimmed, LineString) and trimmed.length > 1e-6:
            return trimmed, None
    if distance <= 1.0:
        oriented[-1] = (node.x, node.y)
        result = LineString(list(reversed(oriented)) if reverse else oriented)
        return result, LineString([observed_endpoint, node])
    oriented_line = LineString(oriented)
    anchor_distance = _connection_anchor_distance(oriented_line, node, distance)
    base = substring(oriented_line, 0.0, anchor_distance)
    base_coords = (
        [(coord[0], coord[1]) for coord in base.coords]
        if isinstance(base, LineString)
        else [(float(base.x), float(base.y))]
    )
    start = Point(base_coords[-1])
    previous_distance = max(0.0, anchor_distance - min(2.0, anchor_distance))
    previous = oriented_line.interpolate(previous_distance)
    vx, vy = start.x - previous.x, start.y - previous.y
    norm = math.hypot(vx, vy) or 1.0
    connection_distance = start.distance(node)
    tangent = min(connection_distance / 3.0, 10.0)
    p0 = np.array([start.x, start.y])
    p1 = p0 + np.array([vx / norm, vy / norm]) * tangent
    p3 = np.array([node.x, node.y])
    toward = p3 - p0
    toward_norm = np.linalg.norm(toward) or 1.0
    p2 = p3 - toward / toward_norm * tangent
    curve = []
    for t in np.linspace(0.0, 1.0, max(4, int(connection_distance / 2.0) + 2)):
        point = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3
        curve.append((float(point[0]), float(point[1])))
    candidate_coords = base_coords[:-1] + curve
    final_coords = list(reversed(candidate_coords)) if reverse else candidate_coords
    candidate = LineString(final_coords)
    completion = LineString(curve)
    if (
        candidate.is_valid
        and candidate.is_simple
        and _max_sample_turn(completion, 1.0) <= 75.0
        and _max_sample_turn(candidate, 2.0) <= 75.0
    ):
        return candidate, completion
    direct_coords = base_coords + [(node.x, node.y)]
    direct_coords = _deduplicate_coords(direct_coords)
    direct = LineString(list(reversed(direct_coords)) if reverse else direct_coords)
    if direct.is_valid and direct.is_simple:
        return direct, LineString([start, node])
    repaired = _trimmed_connection(line, endpoint, node)
    if repaired.is_valid and repaired.is_simple:
        return repaired, LineString([observed_endpoint, node])
    fallback = [(coord[0], coord[1]) for coord in line.coords]
    fallback[0 if reverse else -1] = (node.x, node.y)
    replaced = LineString(fallback)
    return replaced, LineString([observed_endpoint, node])


def _connection_anchor_distance(
    line: LineString,
    node: Point,
    endpoint_distance: float,
) -> float:
    max_trim = min(line.length * 0.75, max(10.0, endpoint_distance * 2.0))
    minimum = max(0.0, line.length - max_trim)
    positions = np.linspace(line.length, minimum, max(3, int(max_trim / 2.0) + 2))
    for position in positions:
        anchor = line.interpolate(float(position))
        previous = line.interpolate(max(0.0, float(position) - min(2.0, float(position))))
        tangent = np.array([anchor.x - previous.x, anchor.y - previous.y])
        toward = np.array([node.x - anchor.x, node.y - anchor.y])
        denominator = float(np.linalg.norm(tangent) * np.linalg.norm(toward))
        if denominator <= 1e-9:
            return float(position)
        cosine = float(np.dot(tangent, toward) / denominator)
        if cosine >= 0.5:
            return float(position)
    return max(minimum, min(line.length, 1.0))


def _max_sample_turn(line: LineString, spacing: float) -> float:
    if line.length <= spacing * 2:
        return 0.0
    count = max(3, int(math.ceil(line.length / spacing)) + 1)
    points = [line.interpolate(value) for value in np.linspace(0.0, line.length, count)]
    maximum = 0.0
    for index in range(1, len(points) - 1):
        first = np.array(
            [
                points[index].x - points[index - 1].x,
                points[index].y - points[index - 1].y,
            ]
        )
        second = np.array(
            [
                points[index + 1].x - points[index].x,
                points[index + 1].y - points[index].y,
            ]
        )
        denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
        if denominator <= 1e-9:
            continue
        cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
        maximum = max(maximum, math.degrees(math.acos(cosine)))
    return maximum


def _deduplicate_coords(
    coords: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    result = [coords[0]]
    for coord in coords[1:]:
        if coord != result[-1]:
            result.append(coord)
    return result


def _trimmed_connection(line: LineString, endpoint: str, node: Point) -> LineString:
    projected = float(line.project(node))
    if endpoint == "end":
        base = substring(line, 0.0, projected)
        coords = [(coord[0], coord[1]) for coord in base.coords]
        if not coords or coords[-1] != (node.x, node.y):
            coords.append((node.x, node.y))
    else:
        base = substring(line, projected, float(line.length))
        coords = [(node.x, node.y), *[(coord[0], coord[1]) for coord in base.coords]]
    deduplicated = [coords[0]]
    for coord in coords[1:]:
        if coord != deduplicated[-1]:
            deduplicated.append(coord)
    if len(deduplicated) < 2:
        original = [(coord[0], coord[1]) for coord in line.coords]
        far = original[-1] if endpoint == "start" else original[0]
        if far != (node.x, node.y):
            deduplicated = [(node.x, node.y), far] if endpoint == "start" else [far, (node.x, node.y)]
        else:
            return LineString(original)
    return LineString(deduplicated)


def _node_by_id(nodes: gpd.GeoDataFrame) -> dict[str, object]:
    return {canonical_id(row.id): row for row in nodes.itertuples()}


def _source_node_mainnode_group(
    source_node_id: str,
    t01_by_id: dict[str, object],
) -> str:
    row = t01_by_id.get(source_node_id)
    if row is None:
        return source_node_id
    value = canonical_id(getattr(row, "mainnodeid", ""))
    return value if value and value != "0" else source_node_id


def _near_full_rcsd_node(point: Point, nodes: gpd.GeoDataFrame, sindex: object, distance: float):
    indexes = list(sindex.query(point.buffer(distance)))
    candidates = [nodes.iloc[int(index)] for index in indexes if nodes.iloc[int(index)].geometry.distance(point) <= distance]
    return min(candidates, key=lambda row: row.geometry.distance(point)) if candidates else None


def _mainnode_id(
    junction_groups: list[str],
    source_node_ids: list[str],
    t01_by_id: dict[str, object],
    inherited: pd.Series | None,
    node_id: int,
) -> int:
    if junction_groups:
        group = junction_groups[0]
        lineage_group = _source_node_mainnode_group(group, t01_by_id)
        return _safe_int(lineage_group, "mainnode", lineage_group)
    values = []
    for node in source_node_ids:
        row = t01_by_id.get(node)
        if row is not None:
            value = canonical_id(getattr(row, "mainnodeid", ""))
            if value and value != "0":
                values.append(value)
    if values:
        return _safe_int(sorted(values)[0], "mainnode", sorted(values)[0])
    if inherited is not None:
        value = canonical_id(inherited.get("mainnodeid"))
        if value and value != "0":
            return _safe_int(value, "mainnode", value)
    return node_id


def _safe_int(value: str, prefix: str, fallback: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return _stable_int(prefix, fallback)


def _stable_int(prefix: str, value: object) -> int:
    digest = hashlib.sha1(f"{prefix}|{value}".encode("utf-8")).hexdigest()
    return 8_000_000_000_000_000 + int(digest[:13], 16) % 999_999_999_999_999


__all__ = [
    "EndpointJunctionResolution",
    "NodeBuildResult",
    "build_nodes_and_connect_roads",
    "resolve_road_endpoint_junctions",
]
