from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .case_models import NodeRecord, RoadRecord


RAW_ENDPOINT_TOLERANCE_M = 6.0
RAW_LOCAL_RADIUS_M = 50.0
RAW_ALIAS_TARGET_ANCHOR_TOLERANCE_M = 10.0
RAW_REQUIRED_CORE_COMPACT_SPAN_M = 12.0
VALID_DIRECTION_VALUES = frozenset({0, 1, 2, 3})


def evaluate_raw_topology_guard(
    *,
    template_class: str | None,
    association_class: str,
    target_nodes: Iterable[NodeRecord],
    swsd_roads: Iterable[RoadRecord],
    rcsd_roads: Iterable[RoadRecord],
    rcsd_nodes: Iterable[NodeRecord],
    support_road_ids: Iterable[str],
    required_road_ids: Iterable[str],
    required_node_gate_audit: dict[str, Any] | None,
    drivezone_input_audit: dict[str, Any] | None,
    drivezone_geometry: BaseGeometry | None = None,
) -> dict[str, Any]:
    targets = tuple(target_nodes)
    source_roads = tuple(swsd_roads)
    roads = tuple(
        road
        for road in rcsd_roads
        if road.geometry is not None and not road.geometry.is_empty
    )
    road_by_id = {road.road_id: road for road in roads}
    node_by_id = {
        node.node_id: node
        for node in rcsd_nodes
        if node.geometry is not None and not node.geometry.is_empty
    }
    target_ids = [node.node_id for node in targets]
    target_points = [node.geometry for node in targets]
    target_span_m = max(
        (
            float(left.distance(right))
            for left in target_points
            for right in target_points
        ),
        default=0.0,
    )
    published_support_ids = [
        road_id
        for road_id in dict.fromkeys(str(value) for value in support_road_ids)
        if road_id in road_by_id
    ]
    input_audit = dict(drivezone_input_audit or {})
    input_geometry_blocked = bool(
        input_audit.get("normalization_applied")
        or int(input_audit.get("invalid_feature_count") or 0) > 0
    )

    nearest_ids = _nearest_road_ids(target_points, road_by_id)
    collapse_ids = _terminal_collapse_support_ids(
        target_points=target_points,
        roads=road_by_id,
        nodes=node_by_id,
        seed_road_ids=nearest_ids,
    )
    collapse_rows = [road_by_id[road_id] for road_id in collapse_ids]
    collapse_components, collapse_degree = _support_topology(collapse_rows)
    collapse_projections = _target_projections(
        target_ids=target_ids,
        target_points=target_points,
        support_rows=collapse_rows,
        component_by_road=collapse_components,
        node_degree=collapse_degree,
        nodes=node_by_id,
    )
    terminal_ids = {
        str(row.get("endpoint_node_id") or "")
        for row in collapse_projections
        if row.get("projection_mode") == "terminal_endpoint"
    } - {""}
    all_terminal = bool(collapse_projections) and all(
        row.get("projection_mode") == "terminal_endpoint"
        for row in collapse_projections
    )
    shared_terminal_id = (
        next(iter(terminal_ids))
        if all_terminal and len(terminal_ids) == 1
        else ""
    )
    shared_terminal_degree = (
        int(collapse_projections[0].get("endpoint_support_degree") or 0)
        if shared_terminal_id
        else 0
    )
    collapse_direction_ok = _direction_values_valid(collapse_rows)
    terminal_collapse = bool(
        association_class in {"A", "B"}
        and len(targets) >= 2
        and shared_terminal_id
        and shared_terminal_degree == 1
        and collapse_direction_ok
        and not input_geometry_blocked
    )

    support_rows = [road_by_id[road_id] for road_id in published_support_ids]
    support_components, support_degree = _support_topology(support_rows)
    support_projections = _target_projections(
        target_ids=target_ids,
        target_points=target_points,
        support_rows=support_rows,
        component_by_road=support_components,
        node_degree=support_degree,
        nodes=node_by_id,
    )
    projection_components = sorted(
        {
            int(row["component_id"])
            for row in support_projections
            if row.get("component_id") is not None
        }
    )
    support_component_ids = sorted(set(support_components.values()))
    support_component_road_counts = {
        component_id: sum(
            1
            for value in support_components.values()
            if value == component_id
        )
        for component_id in support_component_ids
    }
    unmatched_components = sorted(
        set(support_component_ids) - set(projection_components)
    )
    full_local_components = _local_component_by_road(
        roads=road_by_id,
        anchor=targets[0].geometry if targets else None,
    )
    support_full_components = {
        full_local_components[road_id]
        for road_id in published_support_ids
        if road_id in full_local_components
    }
    alternate_full_local_raw_carrier = bool(
        len(support_component_ids) >= 2
        and len(support_full_components) == 1
        and all(
            road_id in full_local_components
            for road_id in published_support_ids
        )
    )
    canonical_alias_portal_audit = _canonical_alias_component_portals(
        support_rows=support_rows,
        component_by_road=support_components,
        projection_component_ids=projection_components,
        nodes=node_by_id,
        target_points=target_points,
        drivezone_geometry=drivezone_geometry,
    )
    alternate_canonical_alias_portal = bool(
        canonical_alias_portal_audit["all_support_components_reachable"]
    )
    alternate_raw_carrier = bool(
        alternate_full_local_raw_carrier
        or alternate_canonical_alias_portal
    )
    support_direction_ok = _direction_values_valid(support_rows)
    retained_required_group_ids = sorted(
        str(group_id)
        for group_id, row in dict(required_node_gate_audit or {}).items()
        if row.get("gate_decision") == "retained"
        and row.get("member_rcsdnode_ids")
    )
    unmatched_support = bool(
        association_class == "B"
        and not retained_required_group_ids
        and len(targets) >= 2
        and len(support_component_ids) >= 2
        and len(projection_components) == 1
        and unmatched_components
        and all(
            support_component_road_counts.get(component_id, 0) >= 2
            for component_id in unmatched_components
        )
        and support_direction_ok
        # A path in the nearby full raw graph is audit evidence only. It does
        # not establish that the bridge belongs to the current junction.
        # Only a canonical alias portal with explicit DriveZone ownership can
        # discharge the published-support ownership contradiction.
        and not alternate_canonical_alias_portal
        and not input_geometry_blocked
    )

    source_incoming_count, source_outgoing_count = _group_flow_counts(
        roads=source_roads,
        member_node_ids=set(target_ids),
    )
    directional_terminal_mismatch, directional_terminal_rows = (
        _directional_terminal_mismatch(support_rows)
    )
    compact_directional_terminal_mismatch = bool(
        template_class == "single_sided_t_mouth"
        and association_class == "B"
        and len(targets) >= 2
        and target_span_m <= RAW_ENDPOINT_TOLERANCE_M
        and len(support_component_ids) == 1
        and source_incoming_count > 0
        and source_outgoing_count > 0
        and directional_terminal_mismatch
        and support_direction_ok
        and not input_geometry_blocked
    )
    connected_semantic_core_ambiguity, connected_semantic_core_rows = (
        _connected_semantic_core_ambiguity(
            template_class=template_class,
            association_class=association_class,
            roads=roads,
            required_node_gate_audit=dict(required_node_gate_audit or {}),
        )
    )
    connected_semantic_core_ambiguity = bool(
        connected_semantic_core_ambiguity
        and not input_geometry_blocked
    )
    required_road_id_set = {
        str(road_id) for road_id in required_road_ids if str(road_id)
    }
    connected_semantic_core_explained_by_required_carrier = bool(
        association_class == "A"
        and len(retained_required_group_ids) >= 2
        and target_span_m <= RAW_REQUIRED_CORE_COMPACT_SPAN_M
        and connected_semantic_core_rows
        and all(
            set(row.get("connecting_rcsdroad_ids") or [])
            <= required_road_id_set
            for row in connected_semantic_core_rows
        )
    )
    if connected_semantic_core_explained_by_required_carrier:
        connected_semantic_core_ambiguity = False

    reason = None
    if unmatched_support:
        reason = "association_raw_multi_component_unmatched_support"
    elif compact_directional_terminal_mismatch:
        reason = "association_raw_compact_alias_directional_terminal_mismatch"
    elif connected_semantic_core_ambiguity:
        reason = "association_raw_connected_semantic_core_ambiguity"
    return {
        "mode": "raw_frcsd_topology_guard",
        "endpoint_tolerance_m": RAW_ENDPOINT_TOLERANCE_M,
        "local_radius_m": RAW_LOCAL_RADIUS_M,
        "distance_role": "retrieval_and_audit_only",
        "direction_role": "strict_input_validity_gate",
        "target_node_ids": target_ids,
        "target_group_span_m": round(target_span_m, 6),
        "nearest_raw_rcsdroad_ids": nearest_ids,
        "terminal_collapse_support_rcsdroad_ids": collapse_ids,
        "terminal_collapse_projections": collapse_projections,
        "shared_terminal_endpoint_id": shared_terminal_id,
        "shared_terminal_endpoint_degree": shared_terminal_degree,
        "published_support_rcsdroad_ids": published_support_ids,
        "support_component_count": len(support_component_ids),
        "support_component_road_counts": {
            str(component_id): count
            for component_id, count in sorted(
                support_component_road_counts.items()
            )
        },
        "target_projection_component_ids": projection_components,
        "unmatched_support_component_ids": unmatched_components,
        "support_projections": support_projections,
        "alternate_raw_carrier": alternate_raw_carrier,
        "alternate_full_local_raw_carrier": (
            alternate_full_local_raw_carrier
        ),
        "alternate_canonical_alias_portal": (
            alternate_canonical_alias_portal
        ),
        "canonical_alias_portal_audit": canonical_alias_portal_audit,
        "retained_required_group_ids": retained_required_group_ids,
        "input_geometry_blocked": input_geometry_blocked,
        "terminal_collapse_direction_ok": collapse_direction_ok,
        "unmatched_support_direction_ok": support_direction_ok,
        "terminal_collapse": terminal_collapse,
        "unmatched_support": unmatched_support,
        "source_incoming_count": source_incoming_count,
        "source_outgoing_count": source_outgoing_count,
        "directional_terminal_rows": directional_terminal_rows,
        "compact_directional_terminal_mismatch": (
            compact_directional_terminal_mismatch
        ),
        "connected_semantic_core_rows": connected_semantic_core_rows,
        "connected_semantic_core_ambiguity": (
            connected_semantic_core_ambiguity
        ),
        "connected_semantic_core_explained_by_required_carrier": (
            connected_semantic_core_explained_by_required_carrier
        ),
        "blocked": reason is not None,
        "reason": reason,
        "silent_fix": False,
        "source_geometry_modified": False,
    }


def _canonical_alias_component_portals(
    *,
    support_rows: Iterable[RoadRecord],
    component_by_road: dict[str, int],
    projection_component_ids: Iterable[int],
    nodes: dict[str, NodeRecord],
    target_points: Iterable[BaseGeometry],
    drivezone_geometry: BaseGeometry | None,
) -> dict[str, Any]:
    road_rows = tuple(support_rows)
    target_geometries = tuple(target_points)
    component_ids = sorted(set(component_by_road.values()))
    node_components: defaultdict[str, set[int]] = defaultdict(set)
    node_incident_rows: defaultdict[str, list[RoadRecord]] = defaultdict(list)
    for road in road_rows:
        component_id = component_by_road.get(road.road_id)
        if component_id is None:
            continue
        for node_id in (road.snodeid, road.enodeid):
            if not node_id:
                continue
            node_components[node_id].add(component_id)
            node_incident_rows[node_id].append(road)

    adjacency: defaultdict[int, set[int]] = defaultdict(set)
    portal_rows: list[dict[str, Any]] = []
    endpoint_ids = sorted(node_components)
    for left_index, left_id in enumerate(endpoint_ids):
        left = nodes.get(left_id)
        if left is None:
            continue
        left_group = _canonical_group_id(left)
        left_incoming, left_outgoing = _raw_node_flow_counts(
            left_id,
            node_incident_rows[left_id],
        )
        for right_id in endpoint_ids[left_index + 1 :]:
            right = nodes.get(right_id)
            if right is None or _canonical_group_id(right) != left_group:
                continue
            component_pairs = sorted(
                {
                    tuple(sorted((left_component, right_component)))
                    for left_component in node_components[left_id]
                    for right_component in node_components[right_id]
                    if left_component != right_component
                }
            )
            if not component_pairs:
                continue
            gap_m = float(left.geometry.distance(right.geometry))
            if gap_m > RAW_ENDPOINT_TOLERANCE_M:
                continue
            connector = LineString(
                [left.geometry.coords[0], right.geometry.coords[0]]
            )
            connector_length_m = float(connector.length)
            drivezone_coverage_ratio = 0.0
            if (
                drivezone_geometry is not None
                and not drivezone_geometry.is_empty
                and connector_length_m > 0.0
            ):
                drivezone_coverage_ratio = float(
                    connector.intersection(drivezone_geometry).length
                    / connector_length_m
                )
            right_incoming, right_outgoing = _raw_node_flow_counts(
                right_id,
                node_incident_rows[right_id],
            )
            left_to_right = left_incoming > 0 and right_outgoing > 0
            right_to_left = right_incoming > 0 and left_outgoing > 0
            directed_transition_compatible = left_to_right or right_to_left
            ownership_role_compatible = bool(
                left_incoming + left_outgoing > 0
                and right_incoming + right_outgoing > 0
            )
            target_anchor_distance_m = min(
                (
                    float(node_geometry.distance(target_geometry))
                    for node_geometry in (left.geometry, right.geometry)
                    for target_geometry in target_geometries
                ),
                default=float("inf"),
            )
            target_anchor_compatible = bool(
                target_anchor_distance_m
                <= RAW_ALIAS_TARGET_ANCHOR_TOLERANCE_M
            )
            accepted = bool(
                drivezone_coverage_ratio >= 0.999999
                and ownership_role_compatible
                and target_anchor_compatible
            )
            portal_rows.append(
                {
                    "left_node_id": left_id,
                    "right_node_id": right_id,
                    "canonical_group_id": left_group,
                    "component_pairs": [list(pair) for pair in component_pairs],
                    "gap_m": round(gap_m, 6),
                    "drivezone_coverage_ratio": round(
                        drivezone_coverage_ratio, 6
                    ),
                    "left_incoming_count": left_incoming,
                    "left_outgoing_count": left_outgoing,
                    "right_incoming_count": right_incoming,
                    "right_outgoing_count": right_outgoing,
                    "left_to_right": left_to_right,
                    "right_to_left": right_to_left,
                    "directed_transition_compatible": (
                        directed_transition_compatible
                    ),
                    "ownership_role_compatible": ownership_role_compatible,
                    "target_anchor_distance_m": round(
                        target_anchor_distance_m, 6
                    ),
                    "target_anchor_compatible": target_anchor_compatible,
                    "direction_compatible": ownership_role_compatible,
                    "accepted": accepted,
                }
            )
            if accepted:
                for left_component, right_component in component_pairs:
                    adjacency[left_component].add(right_component)
                    adjacency[right_component].add(left_component)

    reachable = set(int(value) for value in projection_component_ids)
    pending = list(reachable)
    while pending:
        current = pending.pop()
        for neighbor in adjacency[current] - reachable:
            reachable.add(neighbor)
            pending.append(neighbor)
    return {
        "mode": "canonical_raw_alias_directional_road_surface_portal",
        "endpoint_tolerance_m": RAW_ENDPOINT_TOLERANCE_M,
        "target_anchor_tolerance_m": (
            RAW_ALIAS_TARGET_ANCHOR_TOLERANCE_M
        ),
        "required_drivezone_coverage_ratio": 0.999999,
        "portal_rows": portal_rows,
        "accepted_portal_count": sum(
            1 for row in portal_rows if row["accepted"]
        ),
        "reachable_component_ids": sorted(reachable),
        "all_support_components_reachable": bool(
            component_ids
            and reachable
            and set(component_ids).issubset(reachable)
        ),
        "direction_role": (
            "strict_incident_road_flow_for_ownership;"
            "directed_transition_audited_separately"
        ),
        "target_anchor_role": (
            "hard_gate_before_canonical_alias_portal_establishes_ownership"
        ),
        "source_geometry_modified": False,
        "silent_fix": False,
    }


def _canonical_group_id(node: NodeRecord) -> str:
    value = str(node.mainnodeid or "").strip()
    return value if value not in {"", "0"} else node.node_id


def _raw_node_flow_counts(
    node_id: str,
    roads: Iterable[RoadRecord],
) -> tuple[int, int]:
    incoming = 0
    outgoing = 0
    for road in roads:
        if road.direction in {0, 1, 2}:
            outgoing += int(road.snodeid == node_id)
            incoming += int(road.enodeid == node_id)
        if road.direction in {0, 1, 3}:
            outgoing += int(road.enodeid == node_id)
            incoming += int(road.snodeid == node_id)
    return incoming, outgoing


def _support_topology(
    roads: Iterable[RoadRecord],
) -> tuple[dict[str, int], dict[str, int]]:
    road_rows = tuple(roads)
    node_to_roads: defaultdict[str, set[str]] = defaultdict(set)
    adjacency: defaultdict[str, set[str]] = defaultdict(set)
    for road in road_rows:
        for node_id in (road.snodeid, road.enodeid):
            if node_id:
                node_to_roads[node_id].add(road.road_id)
    for road_ids in node_to_roads.values():
        for road_id in road_ids:
            adjacency[road_id].update(road_ids - {road_id})
    component_by_road: dict[str, int] = {}
    for road_id in sorted(road.road_id for road in road_rows):
        if road_id in component_by_road:
            continue
        component_id = len(set(component_by_road.values()))
        pending = [road_id]
        while pending:
            current = pending.pop()
            if current in component_by_road:
                continue
            component_by_road[current] = component_id
            pending.extend(adjacency[current] - set(component_by_road))
    return component_by_road, {
        node_id: len(road_ids)
        for node_id, road_ids in node_to_roads.items()
    }


def _nearest_road_ids(
    target_points: list[Any],
    roads: dict[str, RoadRecord],
) -> list[str]:
    if not target_points or not roads:
        return []
    return list(
        dict.fromkeys(
            min(
                roads.items(),
                key=lambda item: (
                    float(item[1].geometry.distance(point)),
                    item[0],
                ),
            )[0]
            for point in target_points
        )
    )


def _terminal_collapse_support_ids(
    *,
    target_points: list[Any],
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
    seed_road_ids: list[str],
) -> list[str]:
    seed_endpoint_ids = {
        node_id
        for road_id in seed_road_ids
        if road_id in roads
        for node_id in (roads[road_id].snodeid, roads[road_id].enodeid)
        if node_id
    }
    candidates: list[tuple[float, float, str]] = []
    for road_id, road in roads.items():
        if road.direction not in VALID_DIRECTION_VALUES:
            continue
        endpoint_ids = (road.snodeid, road.enodeid)
        if not seed_endpoint_ids.intersection(
            node_id for node_id in endpoint_ids if node_id
        ):
            continue
        endpoints = {
            node_id: nodes[node_id].geometry
            for node_id in endpoint_ids
            if node_id in nodes
        }
        if len(endpoints) != 2:
            continue
        selected_endpoint_ids: list[str] = []
        target_distances: list[float] = []
        for point in target_points:
            projected = nearest_points(point, road.geometry)[1]
            endpoint_distance, endpoint_id = min(
                (
                    (float(projected.distance(geometry)), node_id)
                    for node_id, geometry in endpoints.items()
                ),
                key=lambda item: (item[0], item[1]),
            )
            if endpoint_distance > RAW_ENDPOINT_TOLERANCE_M:
                selected_endpoint_ids = []
                break
            selected_endpoint_ids.append(endpoint_id)
            target_distances.append(float(point.distance(road.geometry)))
        if (
            selected_endpoint_ids
            and len(set(selected_endpoint_ids)) == 1
            and selected_endpoint_ids[0] in seed_endpoint_ids
            and max(target_distances) <= RAW_LOCAL_RADIUS_M
        ):
            candidates.append(
                (max(target_distances), sum(target_distances), road_id)
            )
    return [min(candidates)[2]] if candidates else []


def _target_projections(
    *,
    target_ids: list[str],
    target_points: list[Any],
    support_rows: list[RoadRecord],
    component_by_road: dict[str, int],
    node_degree: dict[str, int],
    nodes: dict[str, NodeRecord],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for target_id, target_point in zip(target_ids, target_points):
        if not support_rows:
            break
        road = min(
            support_rows,
            key=lambda item: (
                float(item.geometry.distance(target_point)),
                item.road_id,
            ),
        )
        projected = nearest_points(target_point, road.geometry)[1]
        endpoint_candidates = sorted(
            (
                float(projected.distance(nodes[node_id].geometry)),
                node_id,
            )
            for node_id in (road.snodeid, road.enodeid)
            if node_id in nodes
        )
        endpoint_id = ""
        endpoint_degree = None
        projection_mode = "interior"
        if (
            endpoint_candidates
            and endpoint_candidates[0][0] <= RAW_ENDPOINT_TOLERANCE_M
        ):
            endpoint_id = endpoint_candidates[0][1]
            endpoint_degree = int(node_degree.get(endpoint_id, 0))
            projection_mode = (
                "terminal_endpoint"
                if endpoint_degree == 1
                else "shared_endpoint"
            )
        output.append(
            {
                "target_node_id": target_id,
                "nearest_road_id": road.road_id,
                "distance_m": round(
                    float(target_point.distance(road.geometry)),
                    6,
                ),
                "component_id": component_by_road.get(road.road_id),
                "projection_mode": projection_mode,
                "endpoint_node_id": endpoint_id,
                "endpoint_support_degree": endpoint_degree,
            }
        )
    return output


def _local_component_by_road(
    *,
    roads: dict[str, RoadRecord],
    anchor: Any,
) -> dict[str, int]:
    if anchor is None:
        return {}
    window = anchor.buffer(RAW_LOCAL_RADIUS_M)
    component_by_road, _ = _support_topology(
        road
        for road in roads.values()
        if road.geometry.intersects(window)
    )
    return component_by_road


def _direction_values_valid(roads: Iterable[RoadRecord]) -> bool:
    values = {road.direction for road in roads}
    return bool(values) and values.issubset(VALID_DIRECTION_VALUES)


def _group_flow_counts(
    *,
    roads: Iterable[RoadRecord],
    member_node_ids: set[str],
) -> tuple[int, int]:
    incoming_count = 0
    outgoing_count = 0
    for road in roads:
        touches_start = road.snodeid in member_node_ids
        touches_end = road.enodeid in member_node_ids
        if touches_start == touches_end:
            continue
        if road.direction in {0, 1}:
            incoming_count += 1
            outgoing_count += 1
        elif road.direction == 2:
            incoming_count += int(touches_end)
            outgoing_count += int(touches_start)
        elif road.direction == 3:
            incoming_count += int(touches_start)
            outgoing_count += int(touches_end)
    return incoming_count, outgoing_count


def _directional_terminal_mismatch(
    roads: Iterable[RoadRecord],
) -> tuple[bool, list[dict[str, Any]]]:
    node_rows: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"degree": 0, "incoming": 0, "outgoing": 0, "road_ids": []}
    )
    for road in roads:
        for node_id in (road.snodeid, road.enodeid):
            if not node_id:
                continue
            node_rows[node_id]["degree"] += 1
            node_rows[node_id]["road_ids"].append(road.road_id)
        if road.snodeid and road.enodeid:
            if road.direction in {0, 1, 2}:
                node_rows[road.snodeid]["outgoing"] += 1
                node_rows[road.enodeid]["incoming"] += 1
            if road.direction in {0, 1, 3}:
                node_rows[road.enodeid]["outgoing"] += 1
                node_rows[road.snodeid]["incoming"] += 1
    rows = [
        {
            "node_id": node_id,
            "degree": int(values["degree"]),
            "incoming_count": int(values["incoming"]),
            "outgoing_count": int(values["outgoing"]),
            "road_ids": sorted(values["road_ids"]),
            "one_sided_terminal": bool(
                values["degree"] >= 2
                and (
                    (values["incoming"] >= 2 and values["outgoing"] == 0)
                    or (
                        values["outgoing"] >= 2
                        and values["incoming"] == 0
                    )
                )
            ),
        }
        for node_id, values in sorted(node_rows.items())
        if values["degree"] >= 2
    ]
    return any(row["one_sided_terminal"] for row in rows), rows


def _connected_semantic_core_ambiguity(
    *,
    template_class: str | None,
    association_class: str,
    roads: Iterable[RoadRecord],
    required_node_gate_audit: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    if (
        template_class != "single_sided_t_mouth"
        or association_class != "A"
    ):
        return False, []
    retained_groups = [
        {
            "group_id": str(group_id),
            "member_ids": set(row.get("member_rcsdnode_ids") or []),
        }
        for group_id, row in required_node_gate_audit.items()
        if row.get("gate_decision") == "retained"
        and len(row.get("member_rcsdnode_ids") or []) >= 2
    ]
    dropped_groups = [
        {
            "group_id": str(group_id),
            "member_ids": set(row.get("member_rcsdnode_ids") or []),
        }
        for group_id, row in required_node_gate_audit.items()
        if (
            row.get("gate_reason")
            == "single_sided_t_mouth_overflow_after_strong_pair_selection"
            and row.get("intersects_current_swsd_surface")
            and row.get("intersects_allowed_space")
            and int(row.get("effective_degree") or 0) >= 3
        )
    ]
    rows: list[dict[str, Any]] = []
    for retained in retained_groups:
        for dropped in dropped_groups:
            connecting_ids = sorted(
                road.road_id
                for road in roads
                if (
                    {road.snodeid, road.enodeid}
                    & retained["member_ids"]
                    and {road.snodeid, road.enodeid}
                    & dropped["member_ids"]
                )
            )
            if connecting_ids:
                rows.append(
                    {
                        "retained_group_id": retained["group_id"],
                        "retained_member_node_ids": sorted(
                            retained["member_ids"]
                        ),
                        "dropped_group_id": dropped["group_id"],
                        "dropped_member_node_ids": sorted(
                            dropped["member_ids"]
                        ),
                        "connecting_rcsdroad_ids": connecting_ids,
                    }
                )
    return bool(rows), rows
