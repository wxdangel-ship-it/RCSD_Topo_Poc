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

from .step4_association_uturn import (
    _build_degree2_rcsdroad_chains,
    _build_related_outside_scope_rcsdroad_ids,
    _build_related_rcsd_group_ids,
    _build_same_path_chain_protection,
    _collect_required_road_ids_for_nodes,
    _detect_u_turn_rcsdroads,
    _endpoint_node_ids,
    _evaluate_geometry_u_turn_candidate,
    _evaluate_u_turn_trunk_at_group,
    _expand_rcsdroad_ids_via_degree2_chains,
    _merge_same_path_chain_protection,
    _select_single_sided_t_mouth_strong_nodes,
)

from .step4_association_gates import (
    _apply_required_rcsdnode_template_gate,
    _build_gate_failure_case_result,
    _build_support_fragment,
    _clip_required_road,
    _empty_association_key_metrics,
    _group_support_fragments_by_degree2_chain,
    _parallel_support_duplicate,
    _prune_parallel_support_duplicates,
    _shrink_hook_fragment,
    _visual_review_class,
    build_association_status_doc,
)

def build_association_case_result(context: AssociationContext) -> AssociationCaseResult:
    step1 = context.step1_context
    template_result = context.template_result
    step3_state = str(context.step3_status_doc.get("step3_state") or "")
    allowed_space = _clean_geometry(context.step3_allowed_space_geometry)
    current_swsd_surface = _clean_geometry(context.current_swsd_surface_geometry)
    base_extra_fields = {
        "step3_state": step3_state,
        "step3_reason": context.step3_status_doc.get("reason"),
        "step3_case_dir": str(context.step3_case_dir),
        "step3_run_root": str(context.step3_run_root),
        "selected_road_ids": list(context.selected_road_ids),
        "step3_excluded_road_ids": list(context.step3_excluded_road_ids),
        "u_turn_rcsdroad_ids": [],
        "required_rcsdnode_ids": [],
        "required_rcsdroad_ids": [],
        "support_rcsdnode_ids": [],
        "support_rcsdroad_ids": [],
        "excluded_rcsdnode_ids": [],
        "excluded_rcsdroad_ids": [],
        "related_rcsdnode_ids": [],
        "related_rcsdroad_ids": [],
        "related_local_rcsdroad_ids": [],
        "related_group_rcsdroad_ids": [],
        "related_outside_scope_rcsdroad_ids": [],
        "related_outside_scope_rcsdroad_audit": {},
        "related_rcsdnode_group_audit": {},
        "foreign_mask_source_rcsdroad_ids": [],
        "association_prerequisite_issues": list(context.prerequisite_issues),
        "association_executed": False,
        "association_reason": None,
        "association_blocker": None,
        "same_path_chain_protected_rcsdroad_ids": [],
        "same_path_chain_terminal_rcsdnode_ids": [],
        "same_path_rcsdroad_chain_groups": {},
        "same_path_rcsdroad_chain_terminal_groups": {},
        "u_turn_candidate_rcsdroad_ids": [],
        "u_turn_candidate_rcsdroad_audit": {},
        "u_turn_suspect_rcsdroad_ids": [],
        "u_turn_suspect_rcsdroad_audit": {},
        "u_turn_rejected_by_same_path_chain_ids": [],
        "t_mouth_strong_related_rcsdnode_ids": [],
        "t_mouth_strong_related_overflow_rcsdnode_ids": [],
        "required_rcsdnode_gate_dropped_ids": [],
        "required_rcsdnode_gate_audit": {},
    }
    if not template_result.supported:
        return _build_gate_failure_case_result(
            context=context,
            base_extra_fields=base_extra_fields,
            blocker="unsupported_template",
            supported_template=False,
            allowed_space_loaded=allowed_space is not None,
            current_swsd_surface_loaded=current_swsd_surface is not None,
        )
    if context.prerequisite_issues:
        return _build_gate_failure_case_result(
            context=context,
            base_extra_fields=base_extra_fields,
            blocker=context.prerequisite_issues[0],
            supported_template=True,
            allowed_space_loaded=allowed_space is not None,
            current_swsd_surface_loaded=current_swsd_surface is not None,
        )
    if step3_state not in {"established", "review"}:
        return _build_gate_failure_case_result(
            context=context,
            base_extra_fields=base_extra_fields,
            blocker="association_step3_not_established",
            supported_template=True,
            allowed_space_loaded=allowed_space is not None,
            current_swsd_surface_loaded=current_swsd_surface is not None,
        )

    selected_corridor = _build_selected_corridor(context)
    vertical_exit_geometry = _build_single_sided_vertical_exit_geometry(context)
    required_node_ids: set[str] = set()
    required_road_ids: set[str] = set()
    support_node_ids: set[str] = set()
    support_road_ids: set[str] = set()
    required_nodes: list[NodeRecord] = []
    required_roads: list[RoadRecord] = []
    support_roads: list[RoadRecord] = []
    support_fragments: list[BaseGeometry] = []
    hook_shrunk_road_ids: list[str] = []
    dropped_parallel_support_road_ids: list[str] = []
    anchor_point = _point_like(step1.representative_node.geometry)
    current_swsd_scope = current_swsd_surface.buffer(RCSD_ALLOWED_BUFFER_M)
    allowed_space_scope = allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)
    active_rcsd_nodes = [
        node
        for node in step1.rcsd_nodes
        if node.geometry.intersects(current_swsd_scope) or node.geometry.intersects(allowed_space_scope)
    ]
    active_rcsd_roads_raw = [
        road
        for road in step1.rcsd_roads
        if road.geometry.intersects(current_swsd_scope)
    ]
    candidate_nodes_raw = [
        node for node in active_rcsd_nodes if node.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))
    ]
    candidate_roads_raw = [
        road for road in active_rcsd_roads_raw if road.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))
    ]
    raw_node_degree_map = _build_node_degree_map(
        active_rcsd_nodes,
        active_rcsd_roads_raw,
        graph_nodes=step1.rcsd_nodes,
        graph_roads=step1.rcsd_roads,
    )
    raw_degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes_raw
        if raw_node_degree_map.get(node.node_id, 0) == 2
    }
    (
        same_path_chain_groups,
        same_path_chain_terminal_groups,
        same_path_protected_rcsdroad_ids,
        same_path_chain_terminal_rcsdnode_ids,
    ) = _build_same_path_chain_protection(
        candidate_roads=candidate_roads_raw,
        candidate_node_ids={node.node_id for node in candidate_nodes_raw},
        degree2_connector_candidate_node_ids=raw_degree2_connector_candidate_node_ids,
    )
    same_path_terminal_rejection_rcsdnode_ids = set(same_path_chain_terminal_rcsdnode_ids)
    (
        tentative_u_turn_rcsdroad_ids,
        _tentative_u_turn_rcsdroad_audit,
        _tentative_u_turn_candidate_rcsdroad_ids,
        _tentative_u_turn_rejected_by_same_path_chain_ids,
        _tentative_u_turn_suspect_rcsdroad_ids,
    ) = _detect_u_turn_rcsdroads(
        active_rcsd_roads_raw,
        active_rcsd_nodes=active_rcsd_nodes,
        graph_rcsd_nodes=step1.rcsd_nodes,
        graph_rcsd_roads=step1.rcsd_roads,
        same_path_protected_rcsdroad_ids=same_path_protected_rcsdroad_ids,
        same_path_terminal_rcsdnode_ids=same_path_terminal_rejection_rcsdnode_ids,
    )
    tentative_active_rcsd_roads = [
        road for road in active_rcsd_roads_raw if road.road_id not in tentative_u_turn_rcsdroad_ids
    ]
    tentative_node_degree_map = _build_node_degree_map(
        active_rcsd_nodes,
        tentative_active_rcsd_roads,
        graph_nodes=step1.rcsd_nodes,
        graph_roads=[
            road for road in step1.rcsd_roads if road.road_id not in tentative_u_turn_rcsdroad_ids
        ],
    )
    post_filter_degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes_raw
        if tentative_node_degree_map.get(node.node_id, 0) == 2
    }
    (
        post_filter_same_path_chain_groups,
        post_filter_same_path_chain_terminal_groups,
        post_filter_same_path_protected_rcsdroad_ids,
        post_filter_same_path_chain_terminal_rcsdnode_ids,
    ) = _build_same_path_chain_protection(
        candidate_roads=active_rcsd_roads_raw,
        candidate_node_ids={node.node_id for node in active_rcsd_nodes},
        degree2_connector_candidate_node_ids=post_filter_degree2_connector_candidate_node_ids,
    )
    raw_post_filter_new_u_turn_candidate_protected_ids = (
        post_filter_same_path_protected_rcsdroad_ids
        & _tentative_u_turn_candidate_rcsdroad_ids
    ) - same_path_protected_rcsdroad_ids
    post_filter_new_u_turn_candidate_protected_ids = {
        road_id
        for road_id in raw_post_filter_new_u_turn_candidate_protected_ids
        if any(
            road_id in member_ids
            and len(set(member_ids) & _tentative_u_turn_candidate_rcsdroad_ids) >= 2
            for member_ids in post_filter_same_path_chain_groups.values()
        )
    }
    if post_filter_new_u_turn_candidate_protected_ids:
        post_filter_relevant_chain_ids = {
            chain_id
            for chain_id, member_ids in post_filter_same_path_chain_groups.items()
            if set(member_ids) & post_filter_new_u_turn_candidate_protected_ids
        }
        _merge_same_path_chain_protection(
            same_path_chain_groups,
            same_path_chain_terminal_groups,
            same_path_protected_rcsdroad_ids,
            same_path_chain_terminal_rcsdnode_ids,
            source_members={
                chain_id: post_filter_same_path_chain_groups[chain_id]
                for chain_id in post_filter_relevant_chain_ids
            },
            source_terminals={
                chain_id: post_filter_same_path_chain_terminal_groups[chain_id]
                for chain_id in post_filter_relevant_chain_ids
            },
            source_road_ids=post_filter_new_u_turn_candidate_protected_ids,
            source_terminal_ids={
                node_id
                for chain_id in post_filter_relevant_chain_ids
                for node_id in post_filter_same_path_chain_terminal_groups.get(chain_id, ())
            },
        )
    (
        u_turn_rcsdroad_ids,
        u_turn_rcsdroad_audit,
        u_turn_candidate_rcsdroad_ids,
        u_turn_rejected_by_same_path_chain_ids,
        u_turn_suspect_rcsdroad_ids,
    ) = _detect_u_turn_rcsdroads(
        active_rcsd_roads_raw,
        active_rcsd_nodes=active_rcsd_nodes,
        graph_rcsd_nodes=step1.rcsd_nodes,
        graph_rcsd_roads=step1.rcsd_roads,
        same_path_protected_rcsdroad_ids=same_path_protected_rcsdroad_ids,
        same_path_terminal_rcsdnode_ids=same_path_terminal_rejection_rcsdnode_ids,
    )
    active_rcsd_roads = [
        road for road in active_rcsd_roads_raw if road.road_id not in u_turn_rcsdroad_ids
    ]
    ignored_outside_current_swsd_surface_rcsdnode_ids = _sorted_ids(
        node.node_id for node in step1.rcsd_nodes if node.node_id not in {item.node_id for item in active_rcsd_nodes}
    )
    ignored_outside_current_swsd_surface_rcsdroad_ids = _sorted_ids(
        road.road_id for road in step1.rcsd_roads if road.road_id not in {item.road_id for item in active_rcsd_roads_raw}
    )
    node_degree_map = _build_node_degree_map(
        active_rcsd_nodes,
        active_rcsd_roads,
        graph_nodes=step1.rcsd_nodes,
        graph_roads=[road for road in step1.rcsd_roads if road.road_id not in u_turn_rcsdroad_ids],
    )

    candidate_nodes = [node for node in active_rcsd_nodes if node.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))]
    candidate_roads = [road for road in active_rcsd_roads if road.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))]
    active_degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes
        if node_degree_map.get(node.node_id, 0) == 2
    }
    degree2_connector_candidate_node_ids = (
        raw_degree2_connector_candidate_node_ids | active_degree2_connector_candidate_node_ids
    ) - same_path_chain_terminal_rcsdnode_ids
    road_chain_id_by_road_id, road_chain_members_by_chain_id = _build_degree2_rcsdroad_chains(
        candidate_roads,
        degree2_connector_candidate_node_ids,
    )

    grouped_candidate_nodes: dict[str, list[NodeRecord]] = defaultdict(list)
    compact_group_id_by_node = _compact_group_id_by_node(active_rcsd_nodes)
    for node in candidate_nodes:
        grouped_candidate_nodes[compact_group_id_by_node.get(node.node_id, node.node_id)].append(node)

    for group_nodes in grouped_candidate_nodes.values():
        eligible_group_nodes = [
            node
            for node in group_nodes
            if node.node_id not in degree2_connector_candidate_node_ids
            and node_degree_map.get(node.node_id, 0) > 0
        ]
        required_min_degree = 1 if template_result.template_class == "single_sided_t_mouth" else 3
        eligible_group_nodes = [
            node
            for node in eligible_group_nodes
            if node_degree_map.get(node.node_id, 0) >= required_min_degree
        ]
        if not eligible_group_nodes:
            continue
        group_incident_roads: list[RoadRecord] = []
        for node in eligible_group_nodes:
            group_incident_roads.extend(_incident_roads(candidate_roads, node))
        group_incident_roads = list({road.road_id: road for road in group_incident_roads}.values())
        if not group_incident_roads:
            continue
        overlap_count = sum(1 for road in group_incident_roads if road.geometry.intersects(selected_corridor.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)))
        if overlap_count <= 0 and not any(node.geometry.buffer(6.0).intersects(selected_corridor) for node in eligible_group_nodes):
            continue
        for node in eligible_group_nodes:
            required_node_ids.add(node.node_id)
            required_nodes.append(node)

    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    (
        required_node_ids,
        required_rcsdnode_gate_audit,
        required_rcsdnode_gate_dropped_ids,
    ) = _apply_required_rcsdnode_template_gate(
        context=context,
        required_node_ids=required_node_ids,
        grouped_candidate_nodes=grouped_candidate_nodes,
        candidate_roads=candidate_roads,
        node_degree_map=node_degree_map,
    )
    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    (
        required_node_ids,
        t_mouth_strong_related_rcsdnode_ids,
        t_mouth_strong_related_overflow_rcsdnode_ids,
    ) = _select_single_sided_t_mouth_strong_nodes(
        context=context,
        required_nodes=required_nodes,
        selected_corridor=selected_corridor,
    )
    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    single_sided_terminal_required_rcsdnode_ids: set[str] = set()
    single_sided_terminal_pruned_rcsdroad_ids: set[str] = set()
    overflow_node_ids = set(t_mouth_strong_related_overflow_rcsdnode_ids)
    has_isolated_overflow_group = any(
        bool({node.node_id for node in group_nodes} & overflow_node_ids)
        and not bool({node.node_id for node in group_nodes} & required_node_ids)
        for group_nodes in grouped_candidate_nodes.values()
    )
    if template_result.template_class == "single_sided_t_mouth" and has_isolated_overflow_group:
        anchor_local_node_ids = {
            node.node_id
            for node in required_nodes
            if node.geometry.distance(anchor_point) <= SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M
        }
        if anchor_local_node_ids:
            single_sided_terminal_required_rcsdnode_ids = {
                node.node_id
                for node in required_nodes
                if node.node_id not in anchor_local_node_ids
                and node.geometry.distance(anchor_point) > SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M * 2.0
            }
            required_node_ids -= single_sided_terminal_required_rcsdnode_ids
            single_sided_terminal_pruned_rcsdroad_ids = {
                road.road_id
                for road in candidate_roads
                if set(_endpoint_node_ids(road)) & single_sided_terminal_required_rcsdnode_ids
                and not set(_endpoint_node_ids(road)) & required_node_ids
            }
            t_mouth_strong_related_rcsdnode_ids = _sorted_ids(
                set(t_mouth_strong_related_rcsdnode_ids) - single_sided_terminal_required_rcsdnode_ids
            )
    for gate_row in required_rcsdnode_gate_audit.values():
        if gate_row.get("gate_decision") == "dropped":
            continue
        retained_member_ids = set(gate_row["required_member_rcsdnode_ids"]) & required_node_ids
        if retained_member_ids:
            gate_row["required_member_rcsdnode_ids"] = _sorted_ids(retained_member_ids)
            continue
        if set(gate_row["required_member_rcsdnode_ids"]) & single_sided_terminal_required_rcsdnode_ids:
            gate_row["gate_decision"] = "dropped"
            gate_row["gate_reason"] = "single_sided_remote_terminal_node_pruned_at_next_semantic_boundary"
            continue
        gate_row["gate_decision"] = "dropped"
        gate_row["gate_reason"] = "single_sided_t_mouth_overflow_after_strong_pair_selection"
    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    required_road_ids = _collect_required_road_ids_for_nodes(
        required_nodes=required_nodes,
        candidate_roads=candidate_roads,
        selected_corridor=selected_corridor,
    )
    if single_sided_terminal_required_rcsdnode_ids:
        road_by_id = {road.road_id: road for road in candidate_roads}
        for road_id in list(required_road_ids):
            endpoint_node_ids = set(_endpoint_node_ids(road_by_id[road_id]))
            if endpoint_node_ids & single_sided_terminal_required_rcsdnode_ids and not endpoint_node_ids & required_node_ids:
                required_road_ids.remove(road_id)
                single_sided_terminal_pruned_rcsdroad_ids.add(road_id)

    required_road_ids = _expand_rcsdroad_ids_via_degree2_chains(
        required_road_ids,
        chain_id_by_road_id=road_chain_id_by_road_id,
        chain_members_by_chain_id=road_chain_members_by_chain_id,
    )
    required_roads = [road for road in candidate_roads if road.road_id in required_road_ids]
    required_roads = list({road.road_id: road for road in required_roads}.values())

    support_fragments_by_road_id: dict[str, BaseGeometry] = {}
    for road in candidate_roads:
        if road.road_id in required_road_ids:
            continue
        if not road.geometry.intersects(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M)):
            continue
        fragment = _build_support_fragment(
            road,
            allowed_space=allowed_space,
            selected_corridor=selected_corridor,
            anchor_point=anchor_point,
        )
        if fragment is None:
            continue
        if fragment.length < road.geometry.length * 0.95:
            hook_shrunk_road_ids.append(road.road_id)
        support_fragments_by_road_id[road.road_id] = fragment
    support_fragments_by_chain_id = _group_support_fragments_by_degree2_chain(
        support_fragments_by_road_id,
        chain_id_by_road_id=road_chain_id_by_road_id,
    )
    support_fragments_by_chain_id, dropped_parallel_support_chain_ids = _prune_parallel_support_duplicates(
        context=context,
        support_fragments_by_id=support_fragments_by_chain_id,
        anchor_point=anchor_point,
        vertical_exit_geometry=vertical_exit_geometry,
    )
    retained_support_chain_ids = set(support_fragments_by_chain_id.keys())
    support_road_ids = _expand_rcsdroad_ids_via_degree2_chains(
        (
            road_id
            for road_id, chain_id in road_chain_id_by_road_id.items()
            if chain_id in retained_support_chain_ids
        ),
        chain_id_by_road_id=road_chain_id_by_road_id,
        chain_members_by_chain_id=road_chain_members_by_chain_id,
    )
    support_road_ids -= required_road_ids
    dropped_parallel_support_road_ids = _sorted_ids(
        road_id
        for chain_id in dropped_parallel_support_chain_ids
        for road_id in road_chain_members_by_chain_id.get(chain_id, (chain_id,))
    )
    support_roads = [road for road in candidate_roads if road.road_id in support_road_ids]
    support_roads = list({road.road_id: road for road in support_roads}.values())
    support_fragments = [
        support_fragments_by_chain_id[chain_id]
        for chain_id in _sorted_ids(retained_support_chain_ids)
        if chain_id in support_fragments_by_chain_id
    ]
    if support_road_ids:
        hook_shrunk_road_ids = [road_id for road_id in hook_shrunk_road_ids if road_id in support_road_ids]
    if required_node_ids:
        association_class = "A"
    elif support_road_ids:
        association_class = "B"
    else:
        association_class = "C"
    association_reason = {
        "A": "required_rcsd_semantic_core_present",
        "B": "support_only_hook_zone",
        "C": "no_related_rcsd",
    }[association_class]

    for node in candidate_nodes:
        if node.node_id in required_node_ids:
            continue
        if node.node_id in t_mouth_strong_related_overflow_rcsdnode_ids:
            continue
        if node.node_id in degree2_connector_candidate_node_ids:
            continue
        if node.node_id in set(required_rcsdnode_gate_dropped_ids):
            continue
        if node_degree_map.get(node.node_id, 0) <= 0:
            continue
        if node.geometry.buffer(6.0).intersects(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M)):
            support_node_ids.add(node.node_id)

    related_local_road_ids = set(required_road_ids)
    related_outside_scope_road_ids, related_outside_scope_road_audit = _build_related_outside_scope_rcsdroad_ids(
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        required_rcsdroad_ids=set(required_road_ids),
        candidate_rcsdnode_ids={node.node_id for node in candidate_nodes},
        allowed_space=allowed_space,
        node_degree_map=node_degree_map,
    )
    related_road_ids = related_local_road_ids | related_outside_scope_road_ids
    related_node_ids, related_group_road_ids, related_rcsdnode_group_audit = _build_related_rcsd_group_ids(
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        seed_rcsdnode_ids=set(required_node_ids),
        related_rcsdroad_ids=related_road_ids,
        node_degree_map=node_degree_map,
    )
    related_road_ids |= related_group_road_ids

    rcsd_semantic_core_missing = association_class == "B" and not required_node_ids
    foreign_result = build_association_foreign_result(
        context=context,
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        required_rcsdnode_ids=required_node_ids,
        support_rcsdnode_ids=support_node_ids,
        required_rcsdroad_ids=required_road_ids,
        support_rcsdroad_ids=support_road_ids,
        related_rcsdnode_ids=related_node_ids,
        related_rcsdroad_ids=related_road_ids,
        node_degree_map=node_degree_map,
    )

    required_road_geometry = _union_lines(
        _clip_required_road(road, allowed_space) for road in required_roads
    )
    support_road_geometry = _union_lines(support_fragments)
    hook_zone_geometry = _clean_geometry(
        unary_union(
            [
                fragment.buffer(HOOK_ZONE_BUFFER_M, cap_style=2, join_style=2)
                for fragment in support_fragments
            ]
        )
    ) if support_fragments else None
    if hook_zone_geometry is not None:
        hook_zone_geometry = _clean_geometry(hook_zone_geometry.intersection(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)))

    if association_class == "B" and hook_zone_geometry is None:
        association_state = "not_established"
        reason = "association_missing_hook_zone"
    elif association_class == "B":
        association_state = "review"
        reason = "association_support_only"
    elif association_class == "C":
        association_state = "review" if step3_state == "review" else "established"
        reason = "association_upstream_step3_review" if step3_state == "review" else "association_no_related_rcsd"
    else:
        association_state = "review" if step3_state == "review" else "established"
        reason = "association_upstream_step3_review" if step3_state == "review" else "association_established"

    output_geometries = AssociationOutputGeometries(
        required_rcsdnode_geometry=_union_points(node.geometry for node in candidate_nodes if node.node_id in required_node_ids),
        required_rcsdroad_geometry=required_road_geometry,
        support_rcsdnode_geometry=_union_points(node.geometry for node in candidate_nodes if node.node_id in support_node_ids),
        support_rcsdroad_geometry=support_road_geometry,
        excluded_rcsdnode_geometry=foreign_result.excluded_rcsdnode_geometry,
        excluded_rcsdroad_geometry=foreign_result.excluded_rcsdroad_geometry,
        required_hook_zone_geometry=hook_zone_geometry,
        foreign_swsd_context_geometry=foreign_result.foreign_swsd_context_geometry,
        foreign_rcsd_context_geometry=foreign_result.foreign_rcsd_context_geometry,
        related_rcsdroad_geometry=_union_lines(
            road.geometry for road in active_rcsd_roads if road.road_id in related_road_ids
        ),
        u_turn_rcsdroad_geometry=_union_lines(
            road.geometry for road in active_rcsd_roads_raw if road.road_id in u_turn_rcsdroad_ids
        ),
    )

    key_metrics = {
        "active_rcsdnode_count": len(active_rcsd_nodes),
        "active_rcsdroad_count": len(active_rcsd_roads),
        "u_turn_rcsdroad_count": len(u_turn_rcsdroad_ids),
        "candidate_rcsdnode_count": len(candidate_nodes),
        "candidate_rcsdroad_count": len(candidate_roads),
        "required_rcsdnode_count": len(required_node_ids),
        "required_rcsdroad_count": len(required_road_ids),
        "support_rcsdnode_count": len(support_node_ids),
        "support_rcsdroad_count": len(support_road_ids),
        "excluded_rcsdnode_count": len(foreign_result.excluded_rcsdnode_ids),
        "excluded_rcsdroad_count": len(foreign_result.excluded_rcsdroad_ids),
        "related_rcsdnode_count": len(related_node_ids),
        "related_rcsdroad_count": len(related_road_ids),
        "related_group_rcsdroad_count": len(related_group_road_ids),
        "related_outside_scope_rcsdroad_count": len(related_outside_scope_road_ids),
        "foreign_mask_source_rcsdroad_count": len(foreign_result.excluded_rcsdroad_ids),
        "nonsemantic_connector_rcsdnode_count": len(foreign_result.nonsemantic_connector_rcsdnode_ids),
        "true_foreign_rcsdnode_count": len(foreign_result.true_foreign_rcsdnode_ids),
        "hook_zone_present": hook_zone_geometry is not None,
        "hook_zone_area_m2": round(hook_zone_geometry.area, 6) if hook_zone_geometry is not None else 0.0,
        "step3_allowed_area_m2": round(allowed_space.area, 6),
        "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
        "parallel_support_duplicate_drop_count": len(dropped_parallel_support_road_ids),
    }
    audit_doc = {
        "step3_prerequisite": {
            "step3_state": step3_state,
            "step3_reason": context.step3_status_doc.get("reason"),
            "step3_case_dir": str(context.step3_case_dir),
            "selected_road_ids": list(context.selected_road_ids),
            "step3_excluded_road_ids": list(context.step3_excluded_road_ids),
        },
        "step4": {
            "association_class": association_class,
            "association_executed": True,
            "association_reason": association_reason,
            "association_blocker": None,
            "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
            "active_rcsdnode_ids": [node.node_id for node in active_rcsd_nodes],
            "active_rcsdroad_ids_before_u_turn_filter": [road.road_id for road in active_rcsd_roads_raw],
            "active_rcsdroad_ids": [road.road_id for road in active_rcsd_roads],
            "u_turn_detection_mode": _u_turn_detection_mode(active_rcsd_roads_raw),
            "u_turn_formway_bit": UTURN_FORMWAY_BIT,
            "u_turn_rcsdroad_ids": _sorted_ids(u_turn_rcsdroad_ids),
            "u_turn_rcsdroad_audit": {
                road_id: u_turn_rcsdroad_audit[road_id]
                for road_id in _sorted_ids(u_turn_rcsdroad_ids)
            },
            "u_turn_candidate_rcsdroad_audit": {
                road_id: u_turn_rcsdroad_audit[road_id]
                for road_id in _sorted_ids(u_turn_candidate_rcsdroad_ids)
            },
            "u_turn_candidate_rcsdroad_ids": _sorted_ids(u_turn_candidate_rcsdroad_ids),
            "u_turn_suspect_rcsdroad_audit": {
                road_id: u_turn_rcsdroad_audit[road_id]
                for road_id in _sorted_ids(u_turn_suspect_rcsdroad_ids)
            },
            "u_turn_suspect_rcsdroad_ids": _sorted_ids(u_turn_suspect_rcsdroad_ids),
            "u_turn_rejected_by_same_path_chain_ids": _sorted_ids(u_turn_rejected_by_same_path_chain_ids),
            "same_path_chain_protected_rcsdroad_ids": _sorted_ids(same_path_protected_rcsdroad_ids),
            "same_path_chain_terminal_rcsdnode_ids": _sorted_ids(same_path_chain_terminal_rcsdnode_ids),
            "same_path_rcsdroad_chain_groups": {
                chain_id: list(member_ids)
                for chain_id, member_ids in sorted(same_path_chain_groups.items())
            },
            "same_path_rcsdroad_chain_terminal_groups": {
                chain_id: list(member_ids)
                for chain_id, member_ids in sorted(same_path_chain_terminal_groups.items())
            },
            "ignored_outside_current_swsd_surface_rcsdnode_ids": ignored_outside_current_swsd_surface_rcsdnode_ids,
            "ignored_outside_current_swsd_surface_rcsdroad_ids": ignored_outside_current_swsd_surface_rcsdroad_ids,
            "candidate_rcsdnode_ids": [node.node_id for node in candidate_nodes],
            "candidate_rcsdroad_ids": [road.road_id for road in candidate_roads],
            "required_rcsdnode_ids": _sorted_ids(required_node_ids),
            "required_rcsdroad_ids": _sorted_ids(required_road_ids),
            "support_rcsdnode_ids": _sorted_ids(support_node_ids),
            "support_rcsdroad_ids": _sorted_ids(support_road_ids),
            "related_rcsdnode_ids": _sorted_ids(related_node_ids),
            "related_rcsdroad_ids": _sorted_ids(related_road_ids),
            "related_local_rcsdroad_ids": _sorted_ids(related_local_road_ids),
            "related_group_rcsdroad_ids": _sorted_ids(related_group_road_ids),
            "related_outside_scope_rcsdroad_ids": _sorted_ids(related_outside_scope_road_ids),
            "related_outside_scope_rcsdroad_audit": {
                road_id: related_outside_scope_road_audit[road_id]
                for road_id in _sorted_ids(related_outside_scope_road_ids)
            },
            "related_rcsdnode_group_audit": {
                group_id: related_rcsdnode_group_audit[group_id]
                for group_id in _sorted_ids(related_rcsdnode_group_audit.keys())
            },
            "t_mouth_strong_related_rcsdnode_ids": t_mouth_strong_related_rcsdnode_ids,
            "t_mouth_strong_related_overflow_rcsdnode_ids": t_mouth_strong_related_overflow_rcsdnode_ids,
            "single_sided_terminal_required_rcsdnode_ids": _sorted_ids(single_sided_terminal_required_rcsdnode_ids),
            "single_sided_terminal_pruned_rcsdroad_ids": _sorted_ids(single_sided_terminal_pruned_rcsdroad_ids),
            "required_rcsdnode_gate_dropped_ids": required_rcsdnode_gate_dropped_ids,
            "required_rcsdnode_gate_audit": {
                group_id: required_rcsdnode_gate_audit[group_id]
                for group_id in _sorted_ids(required_rcsdnode_gate_audit.keys())
            },
            "single_sided_vertical_exit_selected_road_ids": [
                road_id
                for road_id in context.selected_road_ids
                if road_id not in {
                    str(item)
                    for item in (context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
                    if item is not None and str(item) != ""
                }
            ],
            "parallel_support_duplicate_dropped_rcsdroad_ids": dropped_parallel_support_road_ids,
            "degree2_merged_rcsdroad_groups": {
                chain_id: list(member_ids)
                for chain_id, member_ids in sorted(road_chain_members_by_chain_id.items())
                if len(member_ids) > 1
            },
            "degree2_connector_candidate_rcsdnode_ids": _sorted_ids(degree2_connector_candidate_node_ids),
            "raw_degree2_connector_candidate_rcsdnode_ids": _sorted_ids(raw_degree2_connector_candidate_node_ids),
            "active_degree2_connector_candidate_rcsdnode_ids": _sorted_ids(active_degree2_connector_candidate_node_ids),
            "rcsdnode_degree_map": {node_id: int(node_degree_map.get(node_id, 0)) for node_id in _sorted_ids(node_degree_map.keys())},
            "raw_rcsdnode_degree_map": {node_id: int(raw_node_degree_map.get(node_id, 0)) for node_id in _sorted_ids(raw_node_degree_map.keys())},
            "hook_zone_shrunk_road_ids": _sorted_ids(hook_shrunk_road_ids),
            "grouped_candidate_node_ids": {
                group_id: [node.node_id for node in nodes]
                for group_id, nodes in sorted(grouped_candidate_nodes.items())
            },
        },
        "step5": {
            **foreign_result.audit_doc,
            "association_class": association_class,
            "association_executed": True,
            "association_reason": association_reason,
            "association_blocker": None,
        },
        "joint_phase": {
            "association_state": association_state,
            "reason": reason,
            "association_executed": True,
            "association_reason": association_reason,
            "association_blocker": None,
            "rcsd_semantic_core_missing": rcsd_semantic_core_missing,
            "allowed_space_area_m2": round(allowed_space.area, 6),
            "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
        },
    }
    extra_status_fields = {
        **base_extra_fields,
        "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
        "u_turn_rcsdroad_ids": audit_doc["step4"]["u_turn_rcsdroad_ids"],
        "required_rcsdnode_ids": audit_doc["step4"]["required_rcsdnode_ids"],
        "required_rcsdroad_ids": audit_doc["step4"]["required_rcsdroad_ids"],
        "support_rcsdnode_ids": audit_doc["step4"]["support_rcsdnode_ids"],
        "support_rcsdroad_ids": audit_doc["step4"]["support_rcsdroad_ids"],
        "excluded_rcsdnode_ids": list(foreign_result.excluded_rcsdnode_ids),
        "excluded_rcsdroad_ids": list(foreign_result.excluded_rcsdroad_ids),
        "related_rcsdnode_ids": audit_doc["step4"]["related_rcsdnode_ids"],
        "related_rcsdroad_ids": audit_doc["step4"]["related_rcsdroad_ids"],
        "related_local_rcsdroad_ids": audit_doc["step4"]["related_local_rcsdroad_ids"],
        "related_group_rcsdroad_ids": audit_doc["step4"]["related_group_rcsdroad_ids"],
        "related_outside_scope_rcsdroad_ids": audit_doc["step4"]["related_outside_scope_rcsdroad_ids"],
        "foreign_mask_source_rcsdroad_ids": list(foreign_result.excluded_rcsdroad_ids),
        "u_turn_detection_mode": audit_doc["step4"]["u_turn_detection_mode"],
        "u_turn_formway_bit": audit_doc["step4"]["u_turn_formway_bit"],
        "u_turn_candidate_rcsdroad_ids": audit_doc["step4"]["u_turn_candidate_rcsdroad_ids"],
        "u_turn_suspect_rcsdroad_ids": audit_doc["step4"]["u_turn_suspect_rcsdroad_ids"],
        "u_turn_rejected_by_same_path_chain_ids": audit_doc["step4"]["u_turn_rejected_by_same_path_chain_ids"],
        "same_path_chain_protected_rcsdroad_ids": audit_doc["step4"]["same_path_chain_protected_rcsdroad_ids"],
        "same_path_chain_terminal_rcsdnode_ids": audit_doc["step4"]["same_path_chain_terminal_rcsdnode_ids"],
        "same_path_rcsdroad_chain_groups": audit_doc["step4"]["same_path_rcsdroad_chain_groups"],
        "same_path_rcsdroad_chain_terminal_groups": audit_doc["step4"]["same_path_rcsdroad_chain_terminal_groups"],
        "t_mouth_strong_related_rcsdnode_ids": audit_doc["step4"]["t_mouth_strong_related_rcsdnode_ids"],
        "t_mouth_strong_related_overflow_rcsdnode_ids": audit_doc["step4"]["t_mouth_strong_related_overflow_rcsdnode_ids"],
        "single_sided_terminal_required_rcsdnode_ids": audit_doc["step4"][
            "single_sided_terminal_required_rcsdnode_ids"
        ],
        "single_sided_terminal_pruned_rcsdroad_ids": audit_doc["step4"][
            "single_sided_terminal_pruned_rcsdroad_ids"
        ],
        "required_rcsdnode_gate_dropped_ids": audit_doc["step4"]["required_rcsdnode_gate_dropped_ids"],
        "required_rcsdnode_gate_audit": audit_doc["step4"]["required_rcsdnode_gate_audit"],
        "association_executed": True,
        "association_reason": association_reason,
        "association_blocker": None,
        "rcsd_semantic_core_missing": rcsd_semantic_core_missing,
        "nonsemantic_connector_rcsdnode_ids": list(foreign_result.nonsemantic_connector_rcsdnode_ids),
        "true_foreign_rcsdnode_ids": list(foreign_result.true_foreign_rcsdnode_ids),
        "degree2_connector_candidate_rcsdnode_ids": audit_doc["step4"]["degree2_connector_candidate_rcsdnode_ids"],
        "degree2_merged_rcsdroad_groups": audit_doc["step4"]["degree2_merged_rcsdroad_groups"],
        "ignored_outside_current_swsd_surface_rcsdnode_ids": ignored_outside_current_swsd_surface_rcsdnode_ids,
        "ignored_outside_current_swsd_surface_rcsdroad_ids": ignored_outside_current_swsd_surface_rcsdroad_ids,
        "parallel_support_duplicate_dropped_rcsdroad_ids": dropped_parallel_support_road_ids,
        "hook_zone_shrunk_road_ids": audit_doc["step4"]["hook_zone_shrunk_road_ids"],
        "u_turn_rcsdroad_audit": audit_doc["step4"]["u_turn_rcsdroad_audit"],
        "u_turn_candidate_rcsdroad_audit": audit_doc["step4"]["u_turn_candidate_rcsdroad_audit"],
        "u_turn_suspect_rcsdroad_audit": audit_doc["step4"]["u_turn_suspect_rcsdroad_audit"],
        "related_outside_scope_rcsdroad_audit": audit_doc["step4"]["related_outside_scope_rcsdroad_audit"],
        "related_rcsdnode_group_audit": audit_doc["step4"]["related_rcsdnode_group_audit"],
    }
    return AssociationCaseResult(
        case_id=step1.case_spec.case_id,
        template_class=template_result.template_class,
        association_class=association_class,
        association_state=association_state,
        association_established=association_state == "established",
        reason=reason,
        visual_review_class=_visual_review_class(association_state, reason),
        root_cause_layer=None if association_state == "established" else "association",
        root_cause_type=None if association_state == "established" else reason,
        output_geometries=output_geometries,
        key_metrics=key_metrics,
        audit_doc=audit_doc,
        extra_status_fields=extra_status_fields,
    )
