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

def _apply_required_rcsdnode_template_gate(
    *,
    context: AssociationContext,
    required_node_ids: set[str],
    grouped_candidate_nodes: dict[str, list[NodeRecord]],
    candidate_roads: list[RoadRecord],
    node_degree_map: dict[str, int],
) -> tuple[set[str], dict[str, dict[str, Any]], list[str]]:
    gate_audit: dict[str, dict[str, Any]] = {}
    if not required_node_ids:
        return required_node_ids, gate_audit, []

    anchor_point = _point_like(context.step1_context.representative_node.geometry)
    current_swsd_surface = _clean_geometry(context.current_swsd_surface_geometry)
    current_swsd_scope = (
        current_swsd_surface.buffer(RCSD_ALLOWED_BUFFER_M) if current_swsd_surface is not None else None
    )
    allowed_space = _clean_geometry(context.step3_allowed_space_geometry)
    allowed_scope = allowed_space.buffer(RCSD_ALLOWED_BUFFER_M) if allowed_space is not None else None
    required_groups: dict[str, set[str]] = {}
    for group_id, group_nodes in grouped_candidate_nodes.items():
        group_required_ids = {node.node_id for node in group_nodes if node.node_id in required_node_ids}
        if not group_required_ids:
            continue
        required_groups[group_id] = group_required_ids
        group_span_m = _max_node_group_span_m(group_nodes)
        gate_audit[group_id] = {
            "member_rcsdnode_ids": _sorted_ids(node.node_id for node in group_nodes),
            "required_member_rcsdnode_ids": _sorted_ids(group_required_ids),
            "effective_degree": max((int(node_degree_map.get(node.node_id, 0)) for node in group_nodes), default=0),
            "group_span_m": round(group_span_m, 6),
            "group_max_span_m": COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M,
            "compact_group_member_count": len(group_nodes),
            "compact_multi_node_semantic_group": len(group_nodes) > 1
            and group_span_m <= COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M,
            "intersects_current_swsd_surface": bool(
                current_swsd_scope is not None and any(node.geometry.intersects(current_swsd_scope) for node in group_nodes)
            ),
            "intersects_allowed_space": bool(
                allowed_scope is not None and any(node.geometry.intersects(allowed_scope) for node in group_nodes)
            ),
            "min_distance_to_representative_m": round(
                min(float(node.geometry.distance(anchor_point)) for node in group_nodes),
                6,
            ),
            "gate_decision": "retained",
            "gate_reason": "required_semantic_core",
        }

    if not required_groups:
        return set(), gate_audit, _sorted_ids(required_node_ids)

    template_class = context.template_result.template_class
    if template_class == "center_junction":
        has_anchor_core = any(
            row["min_distance_to_representative_m"] <= CENTER_REQUIRED_CORE_ANCHOR_DISTANCE_M
            for row in gate_audit.values()
        )
        near_anchor_group_count = sum(
            1
            for row in gate_audit.values()
            if row["min_distance_to_representative_m"] <= CENTER_REQUIRED_CORE_PAIR_DISTANCE_M
        )
        has_compact_offset_core = any(
            row["compact_multi_node_semantic_group"]
            and row["compact_group_member_count"] >= 3
            and row["effective_degree"] >= CENTER_COMPACT_OFFSET_CORE_MIN_DEGREE
            and row["min_distance_to_representative_m"] <= CENTER_COMPACT_OFFSET_CORE_DISTANCE_M
            for row in gate_audit.values()
        )
        if has_anchor_core or near_anchor_group_count >= 2 or has_compact_offset_core:
            for row in gate_audit.values():
                row["gate_reason"] = (
                    "center_required_core_has_anchor_local_or_compact_offset_semantic_group"
                )
            return required_node_ids, gate_audit, []
        for row in gate_audit.values():
            row["gate_decision"] = "dropped"
            row["gate_reason"] = "center_required_core_missing_anchor_local_semantic_group"
        return set(), gate_audit, _sorted_ids(required_node_ids)

    if template_class == "single_sided_t_mouth":
        pre_dropped_required_ids: set[str] = set()
        if len(required_groups) == 1:
            for group_id, group_required_ids in list(required_groups.items()):
                row = gate_audit[group_id]
                if not row["compact_multi_node_semantic_group"] and row["effective_degree"] < 3:
                    row["gate_decision"] = "dropped"
                    row["gate_reason"] = "single_sided_required_core_singleton_degree_below_semantic_threshold"
                    pre_dropped_required_ids.update(group_required_ids)
                    continue
                if not row["compact_multi_node_semantic_group"]:
                    direction_audit = build_single_sided_direction_gate_audit(
                        context=context,
                        group_nodes=grouped_candidate_nodes[group_id],
                        candidate_roads=candidate_roads,
                    )
                    row.update(direction_audit)
                    if not direction_audit["direction_gate_passed"]:
                        row["gate_decision"] = "dropped"
                        row["gate_reason"] = "single_sided_required_core_direction_signature_mismatch"
                        pre_dropped_required_ids.update(group_required_ids)
        if pre_dropped_required_ids:
            required_node_ids -= pre_dropped_required_ids
            required_groups = {
                group_id: group_ids - pre_dropped_required_ids
                for group_id, group_ids in required_groups.items()
                if group_ids - pre_dropped_required_ids
            }
            if not required_groups:
                return set(), gate_audit, _sorted_ids(pre_dropped_required_ids)
        has_required_pair = len(required_groups) >= 2
        has_anchor_singleton = any(
            not row["compact_multi_node_semantic_group"]
            and row["min_distance_to_representative_m"] <= SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M
            for row in gate_audit.values()
        )
        has_anchor_compact_group = any(
            row["compact_multi_node_semantic_group"]
            and row["min_distance_to_representative_m"] <= CENTER_REQUIRED_CORE_ANCHOR_DISTANCE_M
            for row in gate_audit.values()
        )
        has_allowed_only_compact_group = any(
            row["compact_multi_node_semantic_group"]
            and row["intersects_allowed_space"]
            and not row["intersects_current_swsd_surface"]
            for row in gate_audit.values()
        )
        if has_required_pair or has_anchor_singleton or has_anchor_compact_group or has_allowed_only_compact_group:
            for row in gate_audit.values():
                if row.get("gate_decision") != "dropped":
                    row["gate_reason"] = "single_sided_required_core_pair_anchor_or_allowed_only_compact_group"
            return required_node_ids, gate_audit, _sorted_ids(pre_dropped_required_ids)
        for row in gate_audit.values():
            if row.get("gate_decision") != "dropped":
                row["gate_decision"] = "dropped"
                row["gate_reason"] = "single_sided_required_core_missing_pair_anchor_or_allowed_only_compact_group"
        return set(), gate_audit, _sorted_ids(set(required_node_ids) | pre_dropped_required_ids)

    return required_node_ids, gate_audit, []

def _clip_required_road(road: RoadRecord, allowed_space: BaseGeometry) -> BaseGeometry | None:
    return _extract_line_geometry(road.geometry.intersection(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)))

def _shrink_hook_fragment(fragment: BaseGeometry, *, anchor_point: Point) -> BaseGeometry | None:
    line = _extract_line_geometry(fragment)
    if line is None:
        return None
    if line.length <= HOOK_SEGMENT_MAX_LENGTH_M:
        return line
    if line.geom_type == "MultiLineString":
        first = max(line.geoms, key=lambda item: item.length)
        line = _clean_geometry(first)
        if line is None:
            return None
    assert line.geom_type == "LineString"
    distance = line.project(anchor_point)
    start = max(0.0, distance - HOOK_SEGMENT_MAX_LENGTH_M / 2.0)
    end = min(line.length, distance + HOOK_SEGMENT_MAX_LENGTH_M / 2.0)
    return _clean_geometry(substring(line, start, end))

def _build_support_fragment(
    road: RoadRecord,
    *,
    allowed_space: BaseGeometry,
    selected_corridor: BaseGeometry,
    anchor_point: Point,
) -> BaseGeometry | None:
    allowed_fragment = road.geometry.intersection(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))
    corridor_fragment = allowed_fragment.intersection(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M))
    fragment = _extract_line_geometry(corridor_fragment) or _extract_line_geometry(allowed_fragment)
    if fragment is None:
        return None
    if fragment.length >= road.geometry.length * 0.95:
        fragment = _shrink_hook_fragment(fragment, anchor_point=anchor_point)
    return _clean_geometry(fragment)

def _parallel_support_duplicate(
    lhs: BaseGeometry | None,
    rhs: BaseGeometry | None,
    *,
    vertical_exit_geometry: BaseGeometry | None,
) -> bool:
    left = _largest_line_string(lhs)
    right = _largest_line_string(rhs)
    if left is None or right is None:
        return False
    if _line_direction_similarity(left, right) < PARALLEL_SUPPORT_DIRECTION_SIM:
        return False
    if vertical_exit_geometry is None or vertical_exit_geometry.is_empty:
        return False
    left_exit_distance = float(left.distance(vertical_exit_geometry))
    right_exit_distance = float(right.distance(vertical_exit_geometry))
    if left_exit_distance > PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M or right_exit_distance > PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M:
        return False
    left_exit_point = _nearest_exit_point(left, vertical_exit_geometry)
    right_exit_point = _nearest_exit_point(right, vertical_exit_geometry)
    if left_exit_point is None or right_exit_point is None:
        return False
    return float(left_exit_point.distance(right_exit_point)) <= PARALLEL_SUPPORT_EXIT_CLUSTER_M

def _prune_parallel_support_duplicates(
    *,
    context: AssociationContext,
    support_fragments_by_id: dict[str, BaseGeometry],
    anchor_point: Point,
    vertical_exit_geometry: BaseGeometry | None,
) -> tuple[dict[str, BaseGeometry], list[str]]:
    if context.template_result.template_class != "single_sided_t_mouth" or vertical_exit_geometry is None:
        return support_fragments_by_id, []
    road_ids = list(support_fragments_by_id.keys())
    if len(road_ids) <= 1:
        return support_fragments_by_id, []
    adjacency: dict[str, set[str]] = {road_id: set() for road_id in road_ids}
    for index, road_id in enumerate(road_ids):
        for other_id in road_ids[index + 1 :]:
            if _parallel_support_duplicate(
                support_fragments_by_id[road_id],
                support_fragments_by_id[other_id],
                vertical_exit_geometry=vertical_exit_geometry,
            ):
                adjacency[road_id].add(other_id)
                adjacency[other_id].add(road_id)
    visited: set[str] = set()
    dropped_ids: list[str] = []
    kept = dict(support_fragments_by_id)
    for road_id in road_ids:
        if road_id in visited:
            continue
        stack = [road_id]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        if len(component) <= 1:
            continue

        def _score(item_id: str) -> tuple[float, float, str]:
            fragment = support_fragments_by_id[item_id]
            exit_distance = float(fragment.distance(vertical_exit_geometry))
            anchor_distance = float(fragment.distance(anchor_point))
            return (exit_distance, anchor_distance, item_id)

        winner = min(component, key=_score)
        for item_id in component:
            if item_id == winner:
                continue
            dropped_ids.append(item_id)
            kept.pop(item_id, None)
    return kept, _sorted_ids(dropped_ids)

def _group_support_fragments_by_degree2_chain(
    support_fragments_by_road_id: dict[str, BaseGeometry],
    *,
    chain_id_by_road_id: dict[str, str],
) -> dict[str, BaseGeometry]:
    grouped_fragments: dict[str, list[BaseGeometry]] = defaultdict(list)
    for road_id, fragment in support_fragments_by_road_id.items():
        chain_id = chain_id_by_road_id.get(road_id, road_id)
        grouped_fragments[chain_id].append(fragment)
    return {
        chain_id: _union_lines(fragments)
        for chain_id, fragments in grouped_fragments.items()
        if _union_lines(fragments) is not None
    }

def _visual_review_class(association_state: str, reason: str) -> str:
    if association_state == "established":
        return "V1 认可成功"
    if association_state == "review":
        if reason == "association_support_only":
            return "V2 业务正确但几何待修"
        return "V2 业务正确但几何待修"
    return "V5 明确失败"

def build_association_status_doc(case_result: AssociationCaseResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_id,
        "template_class": case_result.template_class,
        "association_class": case_result.association_class,
        "association_state": case_result.association_state,
        "association_established": case_result.association_established,
        "reason": case_result.reason,
        "visual_review_class": case_result.visual_review_class,
        "root_cause_layer": case_result.root_cause_layer,
        "root_cause_type": case_result.root_cause_type,
        "key_metrics": case_result.key_metrics,
        **case_result.extra_status_fields,
    }

def _empty_association_key_metrics() -> dict[str, Any]:
    return {
        "active_rcsdnode_count": 0,
        "active_rcsdroad_count": 0,
        "u_turn_rcsdroad_count": 0,
        "candidate_rcsdnode_count": 0,
        "candidate_rcsdroad_count": 0,
        "required_rcsdnode_count": 0,
        "required_rcsdroad_count": 0,
        "support_rcsdnode_count": 0,
        "support_rcsdroad_count": 0,
        "excluded_rcsdnode_count": 0,
        "excluded_rcsdroad_count": 0,
        "related_rcsdnode_count": 0,
        "related_rcsdroad_count": 0,
        "related_group_rcsdroad_count": 0,
        "related_outside_scope_rcsdroad_count": 0,
        "foreign_mask_source_rcsdroad_count": 0,
        "nonsemantic_connector_rcsdnode_count": 0,
        "true_foreign_rcsdnode_count": 0,
        "hook_zone_present": False,
        "hook_zone_area_m2": 0.0,
        "parallel_support_duplicate_drop_count": 0,
    }

def _build_gate_failure_case_result(
    *,
    context: AssociationContext,
    base_extra_fields: dict[str, Any],
    blocker: str,
    supported_template: bool,
    allowed_space_loaded: bool,
    current_swsd_surface_loaded: bool,
) -> AssociationCaseResult:
    empty_geometries = AssociationOutputGeometries(None, None, None, None, None, None, None, None, None)
    audit_doc = {
        "step3_prerequisite": {
            "step3_state": base_extra_fields.get("step3_state"),
            "step3_reason": base_extra_fields.get("step3_reason"),
            "step3_case_dir": base_extra_fields.get("step3_case_dir"),
            "selected_road_ids": list(base_extra_fields.get("selected_road_ids") or []),
            "step3_excluded_road_ids": list(base_extra_fields.get("step3_excluded_road_ids") or []),
            "supported_template": supported_template,
            "allowed_space_loaded": allowed_space_loaded,
            "current_swsd_surface_loaded": current_swsd_surface_loaded,
            "prerequisite_issues": list(context.prerequisite_issues),
        },
        "step4": {
            "association_class": "C",
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "candidate_rcsdnode_ids": [],
            "candidate_rcsdroad_ids": [],
            "required_rcsdnode_ids": [],
            "required_rcsdroad_ids": [],
            "support_rcsdnode_ids": [],
            "support_rcsdroad_ids": [],
            "related_rcsdnode_ids": [],
            "related_rcsdroad_ids": [],
            "related_local_rcsdroad_ids": [],
            "related_group_rcsdroad_ids": [],
            "related_outside_scope_rcsdroad_ids": [],
            "related_outside_scope_rcsdroad_audit": {},
            "related_rcsdnode_group_audit": {},
            "degree2_merged_rcsdroad_groups": {},
            "degree2_connector_candidate_rcsdnode_ids": [],
            "parallel_support_duplicate_dropped_rcsdroad_ids": [],
            "hook_zone_shrunk_road_ids": [],
            "u_turn_rcsdroad_ids": [],
            "u_turn_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_ids": [],
            "u_turn_suspect_rcsdroad_audit": {},
            "u_turn_suspect_rcsdroad_ids": [],
            "u_turn_rejected_by_same_path_chain_ids": [],
            "same_path_chain_protected_rcsdroad_ids": [],
            "same_path_chain_terminal_rcsdnode_ids": [],
            "same_path_rcsdroad_chain_groups": {},
            "same_path_rcsdroad_chain_terminal_groups": {},
            "t_mouth_strong_related_rcsdnode_ids": [],
            "t_mouth_strong_related_overflow_rcsdnode_ids": [],
            "required_rcsdnode_gate_dropped_ids": [],
            "required_rcsdnode_gate_audit": {},
        },
        "step5": {
            "association_class": "C",
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "excluded_rcsdnode_ids": [],
            "excluded_rcsdroad_ids": [],
            "foreign_mask_source_rcsdroad_ids": [],
            "related_rcsdroad_ids": [],
            "foreign_swsd_group_ids": [],
            "foreign_swsd_road_ids": [],
            "nonsemantic_connector_rcsdnode_ids": [],
            "true_foreign_rcsdnode_ids": [],
        },
        "joint_phase": {
            "association_state": "not_established",
            "reason": blocker,
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "rcsd_semantic_core_missing": False,
            "prerequisite_issues": list(context.prerequisite_issues),
        },
    }
    return AssociationCaseResult(
        case_id=context.step1_context.case_spec.case_id,
        template_class=context.template_result.template_class,
        association_class="C",
        association_state="not_established",
        association_established=False,
        reason=blocker,
        visual_review_class="V5 明确失败",
        root_cause_layer="association",
        root_cause_type=blocker,
        output_geometries=empty_geometries,
        key_metrics=_empty_association_key_metrics(),
        audit_doc=audit_doc,
        extra_status_fields={
            **base_extra_fields,
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "rcsd_semantic_core_missing": False,
            "nonsemantic_connector_rcsdnode_ids": [],
            "true_foreign_rcsdnode_ids": [],
            "degree2_connector_candidate_rcsdnode_ids": [],
            "degree2_merged_rcsdroad_groups": {},
            "ignored_outside_current_swsd_surface_rcsdnode_ids": [],
            "ignored_outside_current_swsd_surface_rcsdroad_ids": [],
            "parallel_support_duplicate_dropped_rcsdroad_ids": [],
            "hook_zone_shrunk_road_ids": [],
            "u_turn_rcsdroad_ids": [],
            "u_turn_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_ids": [],
            "u_turn_suspect_rcsdroad_audit": {},
            "u_turn_suspect_rcsdroad_ids": [],
            "u_turn_rejected_by_same_path_chain_ids": [],
            "same_path_chain_protected_rcsdroad_ids": [],
            "same_path_chain_terminal_rcsdnode_ids": [],
            "same_path_rcsdroad_chain_groups": {},
            "same_path_rcsdroad_chain_terminal_groups": {},
            "t_mouth_strong_related_rcsdnode_ids": [],
            "t_mouth_strong_related_overflow_rcsdnode_ids": [],
            "required_rcsdnode_gate_dropped_ids": [],
            "required_rcsdnode_gate_audit": {},
        },
    )
