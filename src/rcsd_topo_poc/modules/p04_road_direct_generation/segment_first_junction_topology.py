from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely.geometry import GeometryCollection, LineString, Point

from .segment_first_geometry_metrics import surface_coverage_at_least

from .segment_first_skeleton import canonical_id, parse_id_list
from .segment_first_topology import (
    TopologyBuildResult,
    _endpoint_vector,
    _semantic_pair_allowed,
    _stable_int,
)


@dataclass(frozen=True)
class SwsdJunctionMovementContractResult:
    topology: TopologyBuildResult
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def materialize_swsd_junction_movement_contract(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    published_roads: gpd.GeoDataFrame,
    published_nodes: gpd.GeoDataFrame,
    topology: TopologyBuildResult,
    *,
    run_id: str,
    maximum_surface_distance_m: float,
    connection_evidence: gpd.GeoDataFrame | None = None,
) -> SwsdJunctionMovementContractResult:
    """Materialize and audit the complete SWSD-derived Junction movement set.

    Ordinary Junctions use the already classified JunctionUnit and the final
    distributed portal Nodes to require the full direction-compatible
    incoming × outgoing Road set. Complex T04 Junctions never use that
    cross-product: only exact shared-Node transitions from the original SWSD
    may supply a missing explicit physical movement.
    """
    group_modes = _group_modes(junction_units, segment_accesses)
    node_meta = _published_node_meta(published_nodes, set(group_modes))
    road_roles = _published_road_roles(published_roads, node_meta)
    segment_members = _segment_members(segment_units)
    swsd_road_to_segment = {
        road_id: segment_id
        for segment_id, road_ids in segment_members.items()
        for road_id in road_ids
    }
    expected_complex = _expected_complex_movements(
        swsd_roads,
        swsd_nodes,
        swsd_road_to_segment,
        {
            group_id
            for group_id, mode in group_modes.items()
            if mode == "explicit_physical"
        },
    )
    road_by_id = {
        canonical_id(row.id): row for row in published_roads.itertuples()
    }
    road_segment = {
        road_id: canonical_id(getattr(row, "segment_id", ""))
        for road_id, row in road_by_id.items()
    }
    surfaces = _group_surfaces(junction_units)
    relation_rows = [
        row._asdict() for row in topology.road_next_road.itertuples(index=False)
    ]
    actual_pairs = _relations_by_group(
        topology.road_next_road,
        node_meta,
    )
    explicit_advance_by_group: dict[
        str,
        set[tuple[str, str]],
    ] = {}
    if not topology.road_next_road.empty:
        advance_relations = topology.road_next_road[
            topology.road_next_road["compile_source"].eq(
                "explicit_lane_topo_advance_right_semantic"
            )
        ]
        for relation in advance_relations.itertuples():
            group_id = canonical_id(
                getattr(relation, "junction_group_id", "")
            )
            explicit_advance_by_group.setdefault(
                group_id,
                set(),
            ).add(
                (
                    canonical_id(relation.RoadId),
                    canonical_id(relation.NextRoadId),
                )
            )
    explicit_count = 0
    for group_id, expected in sorted(expected_complex.items()):
        actual_segments = _actual_segment_pairs(
            actual_pairs.get(group_id, set()),
            road_segment,
        )
        for segment_pair, lineage_pairs in sorted(expected.items()):
            if segment_pair in actual_segments:
                continue
            candidate = _select_complex_candidate(
                group_id,
                segment_pair,
                lineage_pairs,
                road_roles,
                node_meta,
                surfaces.get(group_id, GeometryCollection()),
                maximum_surface_distance_m=maximum_surface_distance_m,
            )
            if candidate is None:
                continue
            source, target = candidate
            relation_rows.append(
                _explicit_relation_row(
                    source,
                    target,
                    group_id,
                    node_meta,
                    run_id,
                )
            )
            actual_pairs.setdefault(group_id, set()).add(
                (source["road_id"], target["road_id"])
            )
            actual_segments.add(segment_pair)
            explicit_count += 1
    complex_lane_topo_rows = _complex_lane_topo_relation_rows(
        connection_evidence,
        topology,
        road_by_id,
        road_roles,
        node_meta,
        group_modes,
        surfaces,
        run_id=run_id,
        maximum_surface_distance_m=maximum_surface_distance_m,
    )
    relation_rows.extend(complex_lane_topo_rows)

    road_next_road = (
        gpd.GeoDataFrame(
            relation_rows,
            geometry="geometry",
            crs=published_roads.crs,
        )
        if relation_rows
        else topology.road_next_road.copy()
    )
    audit_rows: list[dict[str, object]] = []
    for group_id, mode in sorted(group_modes.items()):
        actual_road_pairs = actual_pairs.get(group_id, set())
        if mode == "ordinary_semantic":
            expected_pairs = {
                (source_id, target_id)
                for source_id, source in road_roles.get(group_id, {}).get(
                    "incoming",
                    {},
                ).items()
                for target_id, target in road_roles.get(group_id, {}).get(
                    "outgoing",
                    {},
                ).items()
                if (
                    _semantic_pair_allowed(source, target)
                    or (source_id, target_id) in actual_road_pairs
                )
            }
            expected_pairs.update(
                explicit_advance_by_group.get(group_id, set())
            )
            actual_for_contract = actual_road_pairs
        else:
            expected_pairs = set(
                expected_complex.get(group_id, {})
            )
            actual_for_contract = _actual_segment_pairs(
                actual_road_pairs,
                road_segment,
            )
        missing = expected_pairs - actual_for_contract
        unexpected = actual_for_contract - expected_pairs
        preserved = not missing and not unexpected
        reasons: list[str] = []
        if missing:
            reasons.append("swsd_junction_movement_missing")
        if unexpected:
            reasons.append("unexpected_junction_movement")
        audit_rows.append(
            {
                "run_id": run_id,
                "junction_group_id": group_id,
                "topology_mode": mode,
                "expected_movement_count": len(expected_pairs),
                "actual_movement_count": len(actual_for_contract),
                "missing_movement_keys": _format_pairs(missing),
                "unexpected_movement_keys": _format_pairs(unexpected),
                "movement_topology_preserved": preserved,
                "reason_codes": (
                    "swsd_junction_movement_topology_preserved"
                    if preserved
                    else ",".join(reasons)
                ),
                "geometry": _group_audit_point(
                    group_id,
                    surfaces,
                    segment_accesses,
                ),
            }
        )
    audit = gpd.GeoDataFrame(
        audit_rows,
        geometry="geometry",
        crs=published_roads.crs,
    )
    failures = audit[~audit["movement_topology_preserved"]]
    summary = {
        "junction_contract_count": int(len(audit)),
        "ordinary_junction_count": int(
            audit["topology_mode"].eq("ordinary_semantic").sum()
        ),
        "complex_junction_count": int(
            audit["topology_mode"].eq("explicit_physical").sum()
        ),
        "preserved_junction_count": int(
            audit["movement_topology_preserved"].sum()
        ),
        "failed_junction_count": int(len(failures)),
        "explicit_swsd_movement_count": explicit_count,
        "explicit_lane_topo_movement_count": len(
            complex_lane_topo_rows
        ),
        "expected_movement_count": int(
            audit["expected_movement_count"].sum()
        ),
        "actual_movement_count": int(
            audit["actual_movement_count"].sum()
        ),
        "gate_pass": bool(not audit.empty and failures.empty),
    }
    topology_summary = dict(topology.summary)
    topology_summary.update(
        {
            "road_next_road_count": int(len(road_next_road)),
            "complex_swsd_explicit_relation_count": explicit_count,
            "complex_lane_topo_explicit_relation_count": len(
                complex_lane_topo_rows
            ),
        }
    )
    return SwsdJunctionMovementContractResult(
        TopologyBuildResult(road_next_road, topology_summary),
        audit,
        summary,
    )


def _group_modes(
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
) -> dict[str, str]:
    access_groups = {
        canonical_id(value)
        for value in segment_accesses["junction_group_id"]
        if canonical_id(value)
    }
    modes: dict[str, str] = {}
    selected = junction_units[
        junction_units["junction_group_id"].map(canonical_id).isin(
            access_groups
        )
    ].sort_values(
        ["source_priority", "junction_group_id"],
        ascending=[False, True],
    )
    for row in selected.itertuples():
        if (
            str(getattr(row, "junction_source", ""))
            == "swsd_retained"
        ):
            continue
        group_id = canonical_id(row.junction_group_id)
        modes.setdefault(group_id, str(row.topology_mode))
    return modes


def _published_node_meta(
    nodes: gpd.GeoDataFrame,
    classified_groups: set[str],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in nodes.itertuples():
        node_id = canonical_id(row.id)
        groups = set(
            parse_id_list(getattr(row, "junction_group_ids", ""))
        )
        mainnode = canonical_id(getattr(row, "mainnodeid", ""))
        if mainnode in classified_groups:
            groups.add(mainnode)
        result[node_id] = {
            "groups": groups,
            "mainnodeid": mainnode,
            "junction_kind": str(
                getattr(row, "junction_kind", "")
            ),
            "geometry": row.geometry,
        }
    return result


def _published_road_roles(
    roads: gpd.GeoDataFrame,
    node_meta: dict[str, dict[str, object]],
) -> dict[str, dict[str, dict[str, dict[str, object]]]]:
    result: dict[str, dict[str, dict[str, dict[str, object]]]] = {}
    for row in roads.itertuples():
        road_id = canonical_id(row.id)
        record = {
            "road_id": road_id,
            "road_id_value": row.id,
            "segment_id": canonical_id(
                getattr(row, "segment_id", "")
            ),
            "member_swsd_road_ids": set(
                parse_id_list(
                    getattr(row, "member_swsd_road_id", "")
                )
            ),
            "carrier_role": str(
                getattr(row, "carrier_role", "")
            ),
            "realization": str(
                getattr(row, "realization", "")
            ),
            "geometry": row.geometry,
            "direction": _direction(getattr(row, "direction", 2)),
            "start_node_id": canonical_id(row.snodeid),
            "end_node_id": canonical_id(row.enodeid),
        }
        start_id = canonical_id(row.snodeid)
        end_id = canonical_id(row.enodeid)
        direction = _direction(getattr(row, "direction", 2))
        if direction in {0, 1}:
            _record_road_role(
                result,
                node_meta,
                start_id,
                record,
                incoming=True,
                outgoing=True,
            )
            _record_road_role(
                result,
                node_meta,
                end_id,
                record,
                incoming=True,
                outgoing=True,
            )
        elif direction == 2:
            _record_road_role(
                result,
                node_meta,
                start_id,
                record,
                outgoing=True,
            )
            _record_road_role(
                result,
                node_meta,
                end_id,
                record,
                incoming=True,
            )
        elif direction == 3:
            _record_road_role(
                result,
                node_meta,
                start_id,
                record,
                incoming=True,
            )
            _record_road_role(
                result,
                node_meta,
                end_id,
                record,
                outgoing=True,
            )
    return result


def _record_road_role(
    result: dict[str, dict[str, dict[str, dict[str, object]]]],
    node_meta: dict[str, dict[str, object]],
    node_id: str,
    base_record: dict[str, object],
    *,
    incoming: bool = False,
    outgoing: bool = False,
) -> None:
    meta = node_meta.get(node_id)
    if meta is None:
        return
    record = dict(base_record)
    record["node_id"] = node_id
    endpoint = (
        "start"
        if node_id == str(record["start_node_id"])
        else "end"
    )
    for group_id in meta["groups"]:
        roles = result.setdefault(
            group_id,
            {"incoming": {}, "outgoing": {}},
        )
        if incoming:
            incoming_record = dict(record)
            incoming_record["travel_vector"] = _endpoint_vector(
                record["geometry"],
                endpoint,
                "incoming",
            )
            roles["incoming"][str(record["road_id"])] = incoming_record
        if outgoing:
            outgoing_record = dict(record)
            outgoing_record["travel_vector"] = _endpoint_vector(
                record["geometry"],
                endpoint,
                "outgoing",
            )
            roles["outgoing"][str(record["road_id"])] = outgoing_record


def _segment_members(
    segment_units: gpd.GeoDataFrame,
) -> dict[str, set[str]]:
    return {
        canonical_id(row.segment_id): set(
            parse_id_list(row.swsd_road_ids)
        )
        for row in segment_units.itertuples()
    }


def _expected_complex_movements(
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    road_to_segment: dict[str, str],
    complex_groups: set[str],
) -> dict[
    str,
    dict[tuple[str, str], set[tuple[str, str]]],
]:
    group_nodes: dict[str, set[str]] = {
        group_id: set() for group_id in complex_groups
    }
    for row in swsd_nodes.itertuples():
        node_id = canonical_id(row.id)
        mainnode = canonical_id(getattr(row, "mainnodeid", ""))
        group_id = mainnode if mainnode and mainnode != "0" else node_id
        if group_id in group_nodes:
            group_nodes[group_id].add(node_id)
    exact_roles = _swsd_roles_by_node(swsd_roads)
    output: dict[
        str,
        dict[tuple[str, str], set[tuple[str, str]]],
    ] = {}
    for group_id, node_ids in group_nodes.items():
        movements: dict[
            tuple[str, str],
            set[tuple[str, str]],
        ] = {}
        for node_id in node_ids:
            roles = exact_roles.get(
                node_id,
                {"incoming": set(), "outgoing": set()},
            )
            for source_id in roles["incoming"]:
                for target_id in roles["outgoing"]:
                    if source_id == target_id:
                        continue
                    source_segment = road_to_segment.get(source_id, "")
                    target_segment = road_to_segment.get(target_id, "")
                    if not source_segment or not target_segment:
                        continue
                    movements.setdefault(
                        (source_segment, target_segment),
                        set(),
                    ).add((source_id, target_id))
        output[group_id] = movements
    return output


def _swsd_roles_by_node(
    roads: gpd.GeoDataFrame,
) -> dict[str, dict[str, set[str]]]:
    result: dict[str, dict[str, set[str]]] = {}
    for row in roads.itertuples():
        road_id = canonical_id(row.id)
        start_id = canonical_id(row.snodeid)
        end_id = canonical_id(row.enodeid)
        direction = _direction(getattr(row, "direction", 2))
        if direction in {0, 1}:
            _record_swsd_role(
                result,
                start_id,
                road_id,
                incoming=True,
                outgoing=True,
            )
            _record_swsd_role(
                result,
                end_id,
                road_id,
                incoming=True,
                outgoing=True,
            )
        elif direction == 2:
            _record_swsd_role(
                result,
                start_id,
                road_id,
                outgoing=True,
            )
            _record_swsd_role(
                result,
                end_id,
                road_id,
                incoming=True,
            )
        elif direction == 3:
            _record_swsd_role(
                result,
                start_id,
                road_id,
                incoming=True,
            )
            _record_swsd_role(
                result,
                end_id,
                road_id,
                outgoing=True,
            )
    return result


def _record_swsd_role(
    result: dict[str, dict[str, set[str]]],
    node_id: str,
    road_id: str,
    *,
    incoming: bool = False,
    outgoing: bool = False,
) -> None:
    roles = result.setdefault(
        node_id,
        {"incoming": set(), "outgoing": set()},
    )
    if incoming:
        roles["incoming"].add(road_id)
    if outgoing:
        roles["outgoing"].add(road_id)


def _relations_by_group(
    relations: gpd.GeoDataFrame,
    node_meta: dict[str, dict[str, object]],
) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {}
    for row in relations.itertuples():
        group_id = canonical_id(
            getattr(row, "junction_group_id", "")
        )
        if not group_id:
            shared_node = canonical_id(
                getattr(row, "shared_node_id", "")
            )
            groups = (
                node_meta.get(shared_node, {}).get("groups", set())
            )
            group_id = sorted(groups)[0] if groups else ""
        if not group_id:
            continue
        result.setdefault(group_id, set()).add(
            (
                canonical_id(row.RoadId),
                canonical_id(row.NextRoadId),
            )
        )
    return result


def _actual_segment_pairs(
    road_pairs: set[tuple[str, str]],
    road_segment: dict[str, str],
) -> set[tuple[str, str]]:
    return {
        (road_segment[source_id], road_segment[target_id])
        for source_id, target_id in road_pairs
        if road_segment.get(source_id)
        and road_segment.get(target_id)
    }


def _select_complex_candidate(
    group_id: str,
    segment_pair: tuple[str, str],
    lineage_pairs: set[tuple[str, str]],
    road_roles: dict[
        str,
        dict[str, dict[str, dict[str, object]]],
    ],
    node_meta: dict[str, dict[str, object]],
    surface: object,
    *,
    maximum_surface_distance_m: float,
) -> tuple[dict[str, object], dict[str, object]] | None:
    roles = road_roles.get(
        group_id,
        {"incoming": {}, "outgoing": {}},
    )
    candidates: list[
        tuple[
            tuple[object, ...],
            dict[str, object],
            dict[str, object],
        ]
    ] = []
    for source in roles["incoming"].values():
        if source["segment_id"] != segment_pair[0]:
            continue
        for target in roles["outgoing"].values():
            if (
                target["segment_id"] != segment_pair[1]
                or source["road_id"] == target["road_id"]
            ):
                continue
            if not any(
                source_lineage
                in source["member_swsd_road_ids"]
                and target_lineage
                in target["member_swsd_road_ids"]
                for source_lineage, target_lineage in lineage_pairs
            ):
                continue
            if not _portal_supported(
                group_id,
                source,
                node_meta,
                surface,
                maximum_surface_distance_m,
            ) or not _portal_supported(
                group_id,
                target,
                node_meta,
                surface,
                maximum_surface_distance_m,
            ):
                continue
            candidates.append(
                (
                    (
                        _carrier_rank(str(source["carrier_role"])),
                        _carrier_rank(str(target["carrier_role"])),
                        str(source["road_id"]),
                        str(target["road_id"]),
                    ),
                    source,
                    target,
                )
            )
    if not candidates:
        return None
    _, source, target = min(candidates, key=lambda item: item[0])
    return source, target


def _portal_supported(
    group_id: str,
    road: dict[str, object],
    node_meta: dict[str, dict[str, object]],
    surface: object,
    maximum_surface_distance_m: float,
) -> bool:
    meta = node_meta.get(str(road["node_id"]))
    if meta is None or group_id not in meta["groups"]:
        return False
    geometry = meta["geometry"]
    return bool(
        surface is not None
        and not surface.is_empty
        and float(geometry.distance(surface))
        <= maximum_surface_distance_m + 1e-9
    )


def _carrier_rank(role: str) -> int:
    return {
        "main_forward": 0,
        "main_reverse": 0,
        "main_oneway": 0,
        "semantic_carrier": 1,
        "auxiliary": 2,
        "local_connector": 3,
    }.get(role, 4)


def _explicit_relation_row(
    source: dict[str, object],
    target: dict[str, object],
    group_id: str,
    node_meta: dict[str, dict[str, object]],
    run_id: str,
    *,
    compile_source: str = "complex_junction_swsd_explicit",
) -> dict[str, object]:
    source_node_id = str(source["node_id"])
    target_node_id = str(target["node_id"])
    source_meta = node_meta[source_node_id]
    target_meta = node_meta[target_node_id]
    relation_id = _stable_int(
        "rnr",
        source["road_id_value"],
        target["road_id_value"],
        compile_source,
        group_id,
        source_node_id,
        target_node_id,
    )
    geometry = Point(
        (
            float(source_meta["geometry"].x)
            + float(target_meta["geometry"].x)
        )
        / 2.0,
        (
            float(source_meta["geometry"].y)
            + float(target_meta["geometry"].y)
        )
        / 2.0,
    )
    return {
        "run_id": run_id,
        "Id": relation_id,
        "RoadId": source["road_id_value"],
        "NextRoadId": target["road_id_value"],
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "shared_node_id": "",
        "junction_group_id": group_id,
        "mainnodeid": source_meta["mainnodeid"],
        "TurnType": 0,
        "Length": 0,
        "TrafficLightControl": 0,
        "MultiTurnType": 0,
        "compile_source": compile_source,
        "geometry": geometry,
    }


def _complex_lane_topo_relation_rows(
    connection_evidence: gpd.GeoDataFrame | None,
    topology: TopologyBuildResult,
    road_by_id: dict[str, object],
    road_roles: dict[
        str,
        dict[str, dict[str, dict[str, object]]],
    ],
    node_meta: dict[str, dict[str, object]],
    group_modes: dict[str, str],
    surfaces: dict[str, object],
    *,
    run_id: str,
    maximum_surface_distance_m: float,
) -> list[dict[str, object]]:
    if connection_evidence is None or connection_evidence.empty:
        return []
    required = {
        "source_relation_id",
        "pair_source",
        "source_road_id",
        "target_road_id",
        "connection_decision",
    }
    if not required.issubset(connection_evidence.columns):
        return []

    adjacency: dict[str, set[str]] = {}
    existing_pairs: set[tuple[str, str]] = set()
    for relation in topology.road_next_road.itertuples():
        source_id = canonical_id(relation.RoadId)
        target_id = canonical_id(relation.NextRoadId)
        if not source_id or not target_id:
            continue
        adjacency.setdefault(source_id, set()).add(target_id)
        existing_pairs.add((source_id, target_id))

    selected: dict[
        tuple[str, str, str],
        tuple[
            float,
            dict[str, object],
            dict[str, object],
            set[str],
        ],
    ] = {}
    accepted = connection_evidence[
        connection_evidence["connection_decision"].eq("accepted")
        & connection_evidence["pair_source"].astype(str).str.startswith(
            "lane"
        )
    ]
    for evidence in accepted.itertuples():
        source_id = canonical_id(evidence.source_road_id)
        target_id = canonical_id(evidence.target_road_id)
        if (
            not source_id
            or not target_id
            or source_id == target_id
            or (source_id, target_id) in existing_pairs
        ):
            continue
        candidates: list[
            tuple[
                float,
                str,
                str,
                dict[str, object],
                dict[str, object],
            ]
        ] = []
        for local_id in sorted(adjacency.get(source_id, set())):
            local = road_by_id.get(local_id)
            if local is None or str(
                getattr(local, "carrier_role", "")
            ) != "local_connector":
                continue
            for group_id, mode in sorted(group_modes.items()):
                if mode != "explicit_physical":
                    continue
                source = (
                    road_roles.get(group_id, {})
                    .get("incoming", {})
                    .get(local_id)
                )
                target = (
                    road_roles.get(group_id, {})
                    .get("outgoing", {})
                    .get(target_id)
                )
                if source is None or target is None:
                    continue
                source_point = node_meta[str(source["node_id"])][
                    "geometry"
                ]
                target_point = node_meta[str(target["node_id"])][
                    "geometry"
                ]
                connector = LineString([source_point, target_point])
                if connector.length > maximum_surface_distance_m:
                    continue
                surface = surfaces.get(group_id, GeometryCollection())
                if not surface_coverage_at_least(connector, surface, 0.8):
                    continue
                candidates.append(
                    (
                        float(connector.length),
                        local_id,
                        group_id,
                        source,
                        target,
                    )
                )
        if not candidates:
            continue
        distance, local_id, group_id, source, target = min(
            candidates,
            key=lambda value: (
                value[0],
                value[1],
                value[2],
            ),
        )
        key = (local_id, target_id, group_id)
        relation_id = canonical_id(evidence.source_relation_id)
        current = selected.get(key)
        if current is None:
            selected[key] = (
                distance,
                source,
                target,
                {relation_id} if relation_id else set(),
            )
        elif relation_id:
            current[3].add(relation_id)

    rows: list[dict[str, object]] = []
    for (_, _, group_id), (
        _,
        source,
        target,
        relation_ids,
    ) in sorted(selected.items()):
        row = _explicit_relation_row(
            source,
            target,
            group_id,
            node_meta,
            run_id,
            compile_source="complex_junction_lane_topo_explicit",
        )
        row["source_relation_ids"] = ",".join(sorted(relation_ids))
        row["relation_evidence"] = "lane_topo"
        rows.append(row)
    return rows


def _group_surfaces(
    junction_units: gpd.GeoDataFrame,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for group_id, group in junction_units.groupby(
        junction_units["junction_group_id"].map(canonical_id),
        sort=True,
    ):
        result[str(group_id)] = group.geometry.union_all()
    return result


def _group_audit_point(
    group_id: str,
    surfaces: dict[str, object],
    accesses: gpd.GeoDataFrame,
) -> Point:
    surface = surfaces.get(group_id)
    if surface is not None and not surface.is_empty:
        return surface.representative_point()
    candidates = accesses[
        accesses["junction_group_id"].map(canonical_id) == group_id
    ]
    if not candidates.empty:
        return candidates.iloc[0].geometry
    return Point()


def _format_pairs(pairs: set[tuple[str, str]]) -> str:
    return ",".join(
        f"{source}>{target}"
        for source, target in sorted(pairs)
    )


def _direction(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 2
