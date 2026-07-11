from __future__ import annotations

from collections import defaultdict

from collections.abc import Iterable

from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point

from shapely.geometry.base import BaseGeometry

from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.id_utils import normalize_id, stable_id_key

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step5_foreign_filter import build_association_foreign_result

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_direction_gate import (
    build_single_sided_direction_gate_audit,
)

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import (
    AssociationCaseResult,
    AssociationContext,
    AssociationOutputGeometries,
)

RCSD_ALLOWED_BUFFER_M = 1.0

SELECTED_CORRIDOR_BUFFER_M = 10.0

REQUIRED_NODE_CORRIDOR_BUFFER_M = 12.0

SUPPORT_CORRIDOR_BUFFER_M = 14.0

HOOK_SEGMENT_MAX_LENGTH_M = 24.0

HOOK_ZONE_BUFFER_M = 4.0

INCIDENT_NODE_DISTANCE_M = 6.0

CENTER_REQUIRED_CORE_ANCHOR_DISTANCE_M = 8.0

CENTER_REQUIRED_CORE_PAIR_DISTANCE_M = 12.0

CENTER_COMPACT_OFFSET_CORE_DISTANCE_M = 14.0

CENTER_COMPACT_OFFSET_CORE_MIN_DEGREE = 4

SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M = 18.0

PARALLEL_SUPPORT_DIRECTION_SIM = 0.94

PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M = 8.0

PARALLEL_SUPPORT_EXIT_CLUSTER_M = 45.0

UTURN_MAX_LENGTH_M = 60.0

UTURN_OPPOSITE_DIRECTION_DOT_MAX = -0.92

UTURN_FORMWAY_BIT = 1024

UTURN_TRUNK_PAIR_COLLINEAR_DOT_MAX = -0.92

UTURN_TRUNK_AXIS_PARALLEL_DOT_MIN = 0.94

UTURN_TRUNK_FLOW_OPPOSITE_DOT_MAX = -0.92

COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M = 9.0

from .step4_association_primitives import (
    _build_node_degree_map,
    _build_selected_corridor,
    _build_single_sided_vertical_exit_geometry,
    _clean_geometry,
    _compact_group_id_by_node,
    _direction_dot,
    _extract_line_geometry,
    _graph_incident_roads,
    _group_node_ids_by_group_id,
    _host_road_flow_vector,
    _incident_group_roads,
    _incident_roads,
    _iter_geometries,
    _largest_line_string,
    _line_direction_similarity,
    _line_tangent_at_node,
    _max_node_group_span_m,
    _nearest_exit_point,
    _negate_vector,
    _normalize_group_id,
    _normalize_vector,
    _point_like,
    _road_flow_flags_for_group,
    _road_group_endpoint_node_id,
    _road_touches_group_externally,
    _same_direction_vector_pair,
    _sorted_ids,
    _u_turn_detection_mode,
    _union_lines,
    _union_points,
)

def _evaluate_u_turn_trunk_at_group(
    *,
    group_id: str,
    member_node_ids: set[str],
    active_roads: list[RoadRecord],
    u_turn_road: RoadRecord,
) -> dict[str, Any]:
    incident_roads = _incident_group_roads(active_roads, member_node_ids)
    host_roads = [road for road in incident_roads if road.road_id != u_turn_road.road_id]
    audit: dict[str, Any] = {
        "group_id": group_id,
        "member_node_ids": _sorted_ids(member_node_ids),
        "effective_degree": len({road.road_id for road in incident_roads}),
        "host_rcsdroad_ids": _sorted_ids(road.road_id for road in host_roads),
    }
    if audit["effective_degree"] != 3:
        audit["structure_ok"] = False
        audit["reason"] = "endpoint_group_effective_degree_not_3"
        return audit
    if len(host_roads) != 2:
        audit["structure_ok"] = False
        audit["reason"] = "endpoint_group_host_pair_not_2"
        return audit

    host_tangents: list[tuple[str, tuple[float, float]]] = []
    for host_road in host_roads:
        node_id = _road_group_endpoint_node_id(host_road, member_node_ids)
        tangent = _line_tangent_at_node(host_road, node_id or "")
        if tangent is None:
            audit["structure_ok"] = False
            audit["reason"] = "endpoint_group_host_tangent_missing"
            return audit
        host_tangents.append((host_road.road_id, tangent))

    tangent_dot = _direction_dot(host_tangents[0][1], host_tangents[1][1])
    audit["host_pair_tangent_dot"] = round(tangent_dot, 6) if tangent_dot is not None else None
    if tangent_dot is None or tangent_dot > UTURN_TRUNK_PAIR_COLLINEAR_DOT_MAX:
        audit["structure_ok"] = False
        audit["reason"] = "endpoint_group_host_pair_not_collinear"
        return audit

    audit["structure_ok"] = True
    axis = _same_direction_vector_pair(host_tangents[0][1], host_tangents[1][1])
    audit["_axis_vector"] = axis

    flow_vectors = []
    flow_statuses: dict[str, str] = {}
    for host_road in host_roads:
        flow_vector, status = _host_road_flow_vector(host_road, member_node_ids)
        flow_statuses[host_road.road_id] = status
        flow_vectors.append(flow_vector)
    audit["host_direction_status_by_rcsdroad_id"] = flow_statuses
    if any(vector is None for vector in flow_vectors):
        audit["direction_status"] = "unavailable_or_untrusted"
        audit["_flow_vector"] = None
        return audit

    flow_dot = _direction_dot(flow_vectors[0], flow_vectors[1])
    audit["host_pair_flow_dot"] = round(flow_dot, 6) if flow_dot is not None else None
    if flow_dot is None or flow_dot < UTURN_TRUNK_AXIS_PARALLEL_DOT_MIN:
        audit["direction_status"] = "not_opposite"
        audit["_flow_vector"] = None
        return audit

    audit["direction_status"] = "trusted"
    audit["_flow_vector"] = _same_direction_vector_pair(flow_vectors[0], flow_vectors[1])
    return audit

def _evaluate_geometry_u_turn_candidate(
    *,
    road: RoadRecord,
    active_nodes: list[NodeRecord],
    active_roads: list[RoadRecord],
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "detection_mode": "geometry_fallback_no_formway",
        "formway": road.formway,
        "road_length_m": round(road.geometry.length, 6),
    }
    if road.geometry.length > UTURN_MAX_LENGTH_M:
        audit["candidate"] = False
        audit["reason"] = "road_too_long"
        return audit

    group_id_by_node_id, group_node_ids = _group_node_ids_by_group_id(active_nodes)
    endpoint_group_ids = [
        group_id_by_node_id.get(str(node_id))
        for node_id in (road.snodeid, road.enodeid)
        if node_id not in {None, ""}
    ]
    endpoint_group_ids = [group_id for group_id in endpoint_group_ids if group_id is not None]
    audit["endpoint_group_ids"] = endpoint_group_ids
    if len(endpoint_group_ids) != 2 or endpoint_group_ids[0] == endpoint_group_ids[1]:
        audit["candidate"] = False
        audit["reason"] = "road_does_not_connect_two_semantic_groups"
        return audit

    endpoint_audit = [
        _evaluate_u_turn_trunk_at_group(
            group_id=group_id,
            member_node_ids=group_node_ids[group_id],
            active_roads=active_roads,
            u_turn_road=road,
        )
        for group_id in endpoint_group_ids
    ]
    audit["endpoint_trunk_audit"] = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in endpoint_audit
    ]
    if not all(row.get("structure_ok") for row in endpoint_audit):
        audit["candidate"] = False
        audit["reason"] = "endpoint_trunk_structure_not_satisfied"
        return audit

    axis_dot = _direction_dot(endpoint_audit[0].get("_axis_vector"), endpoint_audit[1].get("_axis_vector"))
    axis_parallel_similarity = abs(axis_dot) if axis_dot is not None else None
    audit["trunk_axis_parallel_similarity"] = (
        round(axis_parallel_similarity, 6) if axis_parallel_similarity is not None else None
    )
    if axis_parallel_similarity is None or axis_parallel_similarity < UTURN_TRUNK_AXIS_PARALLEL_DOT_MIN:
        audit["candidate"] = False
        audit["reason"] = "endpoint_trunk_axes_not_parallel"
        return audit

    audit["candidate"] = True
    if any(row.get("direction_status") == "unavailable_or_untrusted" for row in endpoint_audit):
        audit["decision"] = "suspect_audit_only"
        audit["reason"] = "direction_unavailable_or_untrusted"
        return audit
    if any(row.get("direction_status") != "trusted" for row in endpoint_audit):
        audit["decision"] = "not_u_turn"
        audit["reason"] = "host_pair_direction_not_trusted"
        return audit

    flow_dot = _direction_dot(endpoint_audit[0].get("_flow_vector"), endpoint_audit[1].get("_flow_vector"))
    audit["trunk_flow_dot"] = round(flow_dot, 6) if flow_dot is not None else None
    if flow_dot is not None and flow_dot <= UTURN_TRUNK_FLOW_OPPOSITE_DOT_MAX:
        audit["decision"] = "qualified_u_turn"
        audit["reason"] = "effective_degree3_parallel_trunks_opposite_flow"
        return audit
    audit["decision"] = "not_u_turn"
    audit["reason"] = "trunk_flow_not_opposite"
    return audit

def _detect_u_turn_rcsdroads(
    active_rcsd_roads: list[RoadRecord],
    *,
    active_rcsd_nodes: list[NodeRecord],
    graph_rcsd_nodes: Iterable[NodeRecord] | None = None,
    graph_rcsd_roads: Iterable[RoadRecord] | None = None,
    same_path_protected_rcsdroad_ids: set[str] | None = None,
    same_path_terminal_rcsdnode_ids: set[str] | None = None,
) -> tuple[set[str], dict[str, dict[str, Any]], set[str], set[str], set[str]]:
    same_path_protected_rcsdroad_ids = same_path_protected_rcsdroad_ids or set()
    same_path_terminal_rcsdnode_ids = same_path_terminal_rcsdnode_ids or set()
    u_turn_ids: set[str] = set()
    candidate_ids: set[str] = set()
    rejected_by_same_path_ids: set[str] = set()
    suspect_ids: set[str] = set()
    audit_rows: dict[str, dict[str, Any]] = {}
    detection_mode = _u_turn_detection_mode(active_rcsd_roads)
    if detection_mode == "formway_bit":
        for road in active_rcsd_roads:
            formway_has_u_turn_bit = road.formway is not None and bool(road.formway & UTURN_FORMWAY_BIT)
            if not formway_has_u_turn_bit:
                continue
            candidate_ids.add(road.road_id)
            audit_rows[road.road_id] = {
                "detection_mode": detection_mode,
                "formway": road.formway,
                "u_turn_formway_bit": UTURN_FORMWAY_BIT,
                "road_length_m": round(road.geometry.length, 6),
                "endpoint_matches": [],
                "rejected_by_same_path_chain": False,
                "rejected_by_same_path_terminal": False,
            }
            u_turn_ids.add(road.road_id)
        return u_turn_ids, audit_rows, candidate_ids, rejected_by_same_path_ids, suspect_ids

    graph_nodes = list(graph_rcsd_nodes or active_rcsd_nodes)
    graph_roads = list(graph_rcsd_roads or active_rcsd_roads)
    active_node_ids = {node.node_id for node in active_rcsd_nodes}
    for road in active_rcsd_roads:
        audit_row = _evaluate_geometry_u_turn_candidate(
            road=road,
            active_nodes=active_rcsd_nodes,
            active_roads=active_rcsd_roads,
        )
        endpoint_node_ids = set(_endpoint_node_ids(road))
        missing_endpoint_node_ids = endpoint_node_ids - active_node_ids
        if not audit_row.get("candidate") and missing_endpoint_node_ids:
            graph_audit_row = _evaluate_geometry_u_turn_candidate(
                road=road,
                active_nodes=graph_nodes,
                active_roads=graph_roads,
            )
            if graph_audit_row.get("candidate"):
                graph_audit_row["graph_fallback_applied"] = True
                graph_audit_row["active_scope_reason"] = audit_row.get("reason")
                graph_audit_row["active_scope_missing_endpoint_node_ids"] = _sorted_ids(missing_endpoint_node_ids)
                audit_row = graph_audit_row
        if not audit_row.get("candidate"):
            continue
        candidate_ids.add(road.road_id)
        qualified_u_turn = audit_row.get("decision") == "qualified_u_turn"
        same_path_protected = road.road_id in same_path_protected_rcsdroad_ids
        same_path_override = qualified_u_turn
        audit_row["rejected_by_same_path_chain"] = same_path_protected and not same_path_override
        audit_row["rejected_by_same_path_terminal"] = any(
            node_id in same_path_terminal_rcsdnode_ids for node_id in _endpoint_node_ids(road)
        )
        audit_rows[road.road_id] = audit_row
        if same_path_protected and not same_path_override:
            rejected_by_same_path_ids.add(road.road_id)
            continue
        if audit_rows[road.road_id]["rejected_by_same_path_terminal"]:
            continue
        if audit_row.get("decision") == "qualified_u_turn":
            u_turn_ids.add(road.road_id)
        elif audit_row.get("decision") == "suspect_audit_only":
            suspect_ids.add(road.road_id)
    return u_turn_ids, audit_rows, candidate_ids, rejected_by_same_path_ids, suspect_ids

def _build_degree2_rcsdroad_chains(
    candidate_roads: list[RoadRecord],
    degree2_connector_candidate_node_ids: set[str],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    roads_by_id = {road.road_id: road for road in candidate_roads}
    if not roads_by_id:
        return {}, {}

    parent = {road_id: road_id for road_id in roads_by_id}

    def _find(road_id: str) -> str:
        while parent[road_id] != road_id:
            parent[road_id] = parent[parent[road_id]]
            road_id = parent[road_id]
        return road_id

    def _union(lhs: str, rhs: str) -> None:
        left_root = _find(lhs)
        right_root = _find(rhs)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    incident_roads_by_node: dict[str, set[str]] = defaultdict(set)
    for road in candidate_roads:
        if road.snodeid in degree2_connector_candidate_node_ids:
            incident_roads_by_node[str(road.snodeid)].add(road.road_id)
        if road.enodeid in degree2_connector_candidate_node_ids:
            incident_roads_by_node[str(road.enodeid)].add(road.road_id)

    for road_ids in incident_roads_by_node.values():
        ordered_ids = _sorted_ids(road_ids)
        if len(ordered_ids) < 2:
            continue
        pivot = ordered_ids[0]
        for other_id in ordered_ids[1:]:
            _union(pivot, other_id)

    groups_by_root: dict[str, list[str]] = defaultdict(list)
    for road_id in roads_by_id:
        groups_by_root[_find(road_id)].append(road_id)

    chain_id_by_road_id: dict[str, str] = {}
    chain_members_by_chain_id: dict[str, tuple[str, ...]] = {}
    for member_ids in groups_by_root.values():
        ordered_ids = tuple(_sorted_ids(member_ids))
        chain_id = ordered_ids[0]
        chain_members_by_chain_id[chain_id] = ordered_ids
        for road_id in ordered_ids:
            chain_id_by_road_id[road_id] = chain_id
    return chain_id_by_road_id, chain_members_by_chain_id

def _build_same_path_chain_protection(
    *,
    candidate_roads: list[RoadRecord],
    candidate_node_ids: set[str],
    degree2_connector_candidate_node_ids: set[str],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], set[str], set[str]]:
    chain_id_by_road_id, chain_members_by_chain_id = _build_degree2_rcsdroad_chains(
        candidate_roads,
        degree2_connector_candidate_node_ids,
    )
    incident_road_ids_by_node: dict[str, set[str]] = defaultdict(set)
    for road in candidate_roads:
        if road.snodeid not in {None, ""}:
            incident_road_ids_by_node[str(road.snodeid)].add(road.road_id)
        if road.enodeid not in {None, ""}:
            incident_road_ids_by_node[str(road.enodeid)].add(road.road_id)

    terminals_by_chain_id: dict[str, set[str]] = defaultdict(set)
    for node_id in candidate_node_ids - degree2_connector_candidate_node_ids:
        for road_id in incident_road_ids_by_node.get(node_id, set()):
            chain_id = chain_id_by_road_id.get(road_id)
            if chain_id is not None:
                terminals_by_chain_id[chain_id].add(node_id)

    protected_chain_members: dict[str, tuple[str, ...]] = {}
    protected_chain_terminals: dict[str, tuple[str, ...]] = {}
    protected_road_ids: set[str] = set()
    protected_terminal_node_ids: set[str] = set()
    for chain_id, member_ids in chain_members_by_chain_id.items():
        terminal_ids = terminals_by_chain_id.get(chain_id, set())
        if len(member_ids) <= 1 or len(terminal_ids) < 2:
            continue
        protected_chain_members[chain_id] = member_ids
        protected_chain_terminals[chain_id] = tuple(_sorted_ids(terminal_ids))
        protected_road_ids.update(member_ids)
        protected_terminal_node_ids.update(terminal_ids)
    return protected_chain_members, protected_chain_terminals, protected_road_ids, protected_terminal_node_ids

def _merge_same_path_chain_protection(
    target_members: dict[str, tuple[str, ...]],
    target_terminals: dict[str, tuple[str, ...]],
    target_road_ids: set[str],
    target_terminal_ids: set[str],
    *,
    source_members: dict[str, tuple[str, ...]],
    source_terminals: dict[str, tuple[str, ...]],
    source_road_ids: set[str],
    source_terminal_ids: set[str],
) -> None:
    for chain_id, member_ids in source_members.items():
        target_members[chain_id] = tuple(_sorted_ids(set(target_members.get(chain_id, ())) | set(member_ids)))
    for chain_id, terminal_ids in source_terminals.items():
        target_terminals[chain_id] = tuple(_sorted_ids(set(target_terminals.get(chain_id, ())) | set(terminal_ids)))
    target_road_ids.update(source_road_ids)
    target_terminal_ids.update(source_terminal_ids)

def _expand_rcsdroad_ids_via_degree2_chains(
    road_ids: Iterable[str],
    *,
    chain_id_by_road_id: dict[str, str],
    chain_members_by_chain_id: dict[str, tuple[str, ...]],
) -> set[str]:
    expanded_ids: set[str] = set()
    for road_id in road_ids:
        chain_id = chain_id_by_road_id.get(road_id, road_id)
        expanded_ids.update(chain_members_by_chain_id.get(chain_id, (road_id,)))
    return expanded_ids

def _collect_required_road_ids_for_nodes(
    *,
    required_nodes: list[NodeRecord],
    candidate_roads: list[RoadRecord],
    selected_corridor: BaseGeometry,
) -> set[str]:
    required_road_ids: set[str] = set()
    for node in required_nodes:
        for road in _incident_roads(candidate_roads, node):
            if not road.geometry.intersects(selected_corridor.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)):
                continue
            required_road_ids.add(road.road_id)
    return required_road_ids

def _endpoint_node_ids(road: RoadRecord) -> tuple[str, ...]:
    return tuple(
        str(node_id)
        for node_id in (road.snodeid, road.enodeid)
        if node_id not in {None, ""}
    )

def _build_related_outside_scope_rcsdroad_ids(
    *,
    active_rcsd_nodes: list[NodeRecord],
    active_rcsd_roads: list[RoadRecord],
    required_rcsdroad_ids: set[str],
    candidate_rcsdnode_ids: set[str],
    allowed_space: BaseGeometry,
    node_degree_map: dict[str, int],
) -> tuple[set[str], dict[str, Any]]:
    if not required_rcsdroad_ids:
        return set(), {}
    allowed_scope = allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)
    active_node_ids = {node.node_id for node in active_rcsd_nodes}
    nodes_by_id = {node.node_id: node for node in active_rcsd_nodes}
    incident_road_ids_by_node: dict[str, set[str]] = defaultdict(set)
    for road in active_rcsd_roads:
        for node_id in _endpoint_node_ids(road):
            incident_road_ids_by_node[node_id].add(road.road_id)

    outside_scope_ids: set[str] = set()
    audit_rows: dict[str, Any] = {}
    for road in active_rcsd_roads:
        if road.road_id in required_rcsdroad_ids:
            continue
        if road.geometry.intersects(allowed_scope):
            continue
        connector_matches = []
        endpoint_node_ids = set(_endpoint_node_ids(road))
        if not endpoint_node_ids or not endpoint_node_ids <= active_node_ids:
            continue
        for node_id in _sorted_ids(endpoint_node_ids):
            if node_degree_map.get(node_id, 0) != 2:
                continue
            node = nodes_by_id.get(node_id)
            if node is None:
                continue
            if node_id not in candidate_rcsdnode_ids and not node.geometry.intersects(allowed_scope):
                continue
            retained_incident_ids = _sorted_ids(
                incident_road_ids_by_node.get(node_id, set()) & required_rcsdroad_ids
            )
            if not retained_incident_ids:
                continue
            connector_matches.append(
                {
                    "connector_rcsdnode_id": node_id,
                    "retained_incident_rcsdroad_ids": retained_incident_ids,
                }
            )
        if not connector_matches:
            continue
        outside_scope_ids.add(road.road_id)
        audit_rows[road.road_id] = {
            "reason": "required_core_degree2_connector_one_hop_outside_step3_scope",
            "connector_matches": connector_matches,
        }
    return outside_scope_ids, audit_rows

def _build_related_rcsd_group_ids(
    *,
    active_rcsd_nodes: list[NodeRecord],
    active_rcsd_roads: list[RoadRecord],
    seed_rcsdnode_ids: set[str],
    related_rcsdroad_ids: set[str],
    node_degree_map: dict[str, int],
) -> tuple[set[str], set[str], dict[str, Any]]:
    related_node_ids = set(seed_rcsdnode_ids)
    if not related_rcsdroad_ids:
        return related_node_ids, set(), {}
    nodes_by_id = {node.node_id: node for node in active_rcsd_nodes}
    node_group_by_id = _compact_group_id_by_node(active_rcsd_nodes)
    group_node_ids: dict[str, set[str]] = defaultdict(set)
    for node in active_rcsd_nodes:
        group_node_ids[node_group_by_id[node.node_id]].add(node.node_id)

    incident_road_ids_by_group: dict[str, set[str]] = defaultdict(set)
    related_incident_road_ids_by_group: dict[str, set[str]] = defaultdict(set)
    for road in active_rcsd_roads:
        endpoint_group_ids = {
            node_group_by_id[node_id]
            for node_id in _endpoint_node_ids(road)
            if node_id in nodes_by_id
        }
        for group_id in endpoint_group_ids:
            incident_road_ids_by_group[group_id].add(road.road_id)
        if road.road_id not in related_rcsdroad_ids:
            continue
        for group_id in endpoint_group_ids:
            related_incident_road_ids_by_group[group_id].add(road.road_id)

    related_group_road_ids: set[str] = set()
    audit_rows: dict[str, Any] = {}
    for group_id, member_node_ids in group_node_ids.items():
        related_incident_road_ids = related_incident_road_ids_by_group.get(group_id, set())
        if len(member_node_ids) <= 1 or len(related_incident_road_ids) < 2:
            continue
        member_nodes = [nodes_by_id[node_id] for node_id in member_node_ids if node_id in nodes_by_id]
        group_span_m = _max_node_group_span_m(member_nodes)
        if group_span_m > COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M:
            continue
        group_degrees = {
            int(node_degree_map.get(node_id, 0))
            for node_id in member_node_ids
            if node_id in node_degree_map
        }
        if group_degrees and max(group_degrees) == 2:
            continue
        group_incident_road_ids = incident_road_ids_by_group.get(group_id, set())
        related_node_ids.update(member_node_ids)
        related_group_road_ids.update(related_incident_road_ids)
        audit_rows[group_id] = {
            "reason": "multi_node_rcsd_semantic_group_incident_to_related_roads",
            "group_span_m": round(group_span_m, 6),
            "group_max_span_m": COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M,
            "member_rcsdnode_ids": _sorted_ids(member_node_ids),
            "related_incident_rcsdroad_ids": _sorted_ids(related_incident_road_ids),
            "related_group_incident_rcsdroad_ids": _sorted_ids(related_incident_road_ids),
            "group_incident_rcsdroad_ids": _sorted_ids(group_incident_road_ids),
        }
    return related_node_ids, related_group_road_ids, audit_rows

def _select_single_sided_t_mouth_strong_nodes(
    *,
    context: AssociationContext,
    required_nodes: list[NodeRecord],
    selected_corridor: BaseGeometry,
) -> tuple[set[str], list[str], list[str]]:
    if context.template_result.template_class != "single_sided_t_mouth":
        return {node.node_id for node in required_nodes}, [], []
    if len(required_nodes) <= 2:
        strong_ids = _sorted_ids(node.node_id for node in required_nodes)
        return set(strong_ids), strong_ids, []

    horizontal_pair_ids = {
        str(item)
        for item in (context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
        if item is not None and str(item) != ""
    }
    horizontal_geometry = _union_lines(
        road.geometry
        for road in context.step1_context.roads
        if road.road_id in horizontal_pair_ids
    )
    anchor_point = _point_like(context.step1_context.representative_node.geometry)

    def _score(node: NodeRecord) -> tuple[float, float, str]:
        reference_geometry = horizontal_geometry or selected_corridor
        return (
            float(node.geometry.distance(reference_geometry)),
            float(node.geometry.distance(anchor_point)),
            node.node_id,
        )

    ordered_nodes = sorted(required_nodes, key=_score)
    strong_ids = set(node.node_id for node in ordered_nodes[:2])
    overflow_ids = _sorted_ids(node.node_id for node in ordered_nodes[2:])
    return strong_ids, _sorted_ids(strong_ids), overflow_ids
