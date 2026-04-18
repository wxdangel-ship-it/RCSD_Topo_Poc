from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import NodeRecord, RoadRecord
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_foreign_filter import build_step45_foreign_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_models import (
    Step45CaseResult,
    Step45Context,
    Step45OutputGeometries,
)


RCSD_ALLOWED_BUFFER_M = 1.0
SELECTED_CORRIDOR_BUFFER_M = 10.0
REQUIRED_NODE_CORRIDOR_BUFFER_M = 12.0
SUPPORT_CORRIDOR_BUFFER_M = 14.0
HOOK_SEGMENT_MAX_LENGTH_M = 24.0
HOOK_ZONE_BUFFER_M = 4.0
INCIDENT_NODE_DISTANCE_M = 6.0
PARALLEL_SUPPORT_DIRECTION_SIM = 0.94
PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M = 8.0
PARALLEL_SUPPORT_EXIT_CLUSTER_M = 45.0


def _sorted_ids(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


def _clean_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, GeometryCollection):
        cleaned = [_clean_geometry(part) for part in geometry.geoms]
        cleaned = [part for part in cleaned if part is not None and not part.is_empty]
        if not cleaned:
            return None
        merged = unary_union(cleaned)
        return None if merged.is_empty else merged
    if isinstance(geometry, (Point, MultiPoint, LineString, MultiLineString)):
        return geometry if not geometry.is_empty else None
    cleaned = geometry.buffer(0)
    return None if cleaned.is_empty else cleaned


def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for part in geometry.geoms:
            yield from _iter_geometries(part)
        return
    yield geometry


def _extract_line_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    parts = [
        part
        for part in _iter_geometries(geometry)
        if part.geom_type == "LineString" and getattr(part, "length", 0.0) > 0.0
    ]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))


def _largest_line_string(geometry: BaseGeometry | None) -> LineString | None:
    line = _extract_line_geometry(geometry)
    if line is None:
        return None
    if line.geom_type == "LineString":
        return line
    if line.geom_type == "MultiLineString":
        longest = max(line.geoms, key=lambda item: item.length, default=None)
        return longest if isinstance(longest, LineString) else None
    return None


def _union_points(geometries: Iterable[BaseGeometry]) -> BaseGeometry | None:
    parts = [
        part
        for geometry in geometries
        for part in _iter_geometries(geometry)
        if part.geom_type == "Point"
    ]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))


def _union_lines(geometries: Iterable[BaseGeometry]) -> BaseGeometry | None:
    parts = [
        part
        for geometry in geometries
        for part in _iter_geometries(geometry)
        if part.geom_type == "LineString" and getattr(part, "length", 0.0) > 0.0
    ]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))


def _point_like(geometry: BaseGeometry) -> Point:
    if isinstance(geometry, Point):
        return geometry
    point = geometry.representative_point()
    return point if isinstance(point, Point) else Point(point.coords[0])


def _line_direction_similarity(lhs: BaseGeometry | None, rhs: BaseGeometry | None) -> float:
    left = _largest_line_string(lhs)
    right = _largest_line_string(rhs)
    if left is None or right is None or left.length <= 0.0 or right.length <= 0.0:
        return 0.0
    l0, l1 = Point(left.coords[0]), Point(left.coords[-1])
    r0, r1 = Point(right.coords[0]), Point(right.coords[-1])
    ldx, ldy = l1.x - l0.x, l1.y - l0.y
    rdx, rdy = r1.x - r0.x, r1.y - r0.y
    lnorm = (ldx * ldx + ldy * ldy) ** 0.5
    rnorm = (rdx * rdx + rdy * rdy) ** 0.5
    if lnorm <= 0.0 or rnorm <= 0.0:
        return 0.0
    return abs((ldx * rdx + ldy * rdy) / (lnorm * rnorm))


def _nearest_exit_point(geometry: BaseGeometry | None, vertical_exit_geometry: BaseGeometry | None) -> Point | None:
    if geometry is None or geometry.is_empty or vertical_exit_geometry is None or vertical_exit_geometry.is_empty:
        return None
    _source, exit_point = nearest_points(geometry, vertical_exit_geometry)
    return exit_point if isinstance(exit_point, Point) else Point(exit_point.coords[0])


def _normalize_group_id(node: NodeRecord) -> str:
    mainnodeid = None if node.mainnodeid in {None, "", "0"} else node.mainnodeid
    return str(mainnodeid or node.node_id)


def _build_selected_corridor(context: Step45Context) -> BaseGeometry:
    roads = [road.geometry.buffer(SELECTED_CORRIDOR_BUFFER_M, cap_style=2, join_style=2) for road in context.step1_context.roads if road.road_id in set(context.selected_road_ids)]
    if not roads:
        return context.step1_context.representative_node.geometry.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)
    return unary_union(roads)


def _build_single_sided_vertical_exit_geometry(context: Step45Context) -> BaseGeometry | None:
    if context.template_result.template_class != "single_sided_t_mouth":
        return None
    horizontal_pair_ids = {
        str(item)
        for item in (context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
        if item is not None and str(item) != ""
    }
    exit_roads = [
        road.geometry
        for road in context.step1_context.roads
        if road.road_id in set(context.selected_road_ids) and road.road_id not in horizontal_pair_ids
    ]
    if not exit_roads:
        return None
    return _extract_line_geometry(unary_union(exit_roads))


def _incident_roads(candidate_roads: list[RoadRecord], node: NodeRecord) -> list[RoadRecord]:
    matches = []
    for road in candidate_roads:
        if road.snodeid == node.node_id or road.enodeid == node.node_id:
            matches.append(road)
            continue
        if road.geometry.distance(node.geometry) <= INCIDENT_NODE_DISTANCE_M:
            matches.append(road)
    return matches


def _graph_incident_roads(all_roads: Iterable[RoadRecord], node: NodeRecord) -> list[RoadRecord]:
    explicit = [
        road
        for road in all_roads
        if road.snodeid == node.node_id or road.enodeid == node.node_id
    ]
    if explicit:
        return list({road.road_id: road for road in explicit}.values())
    return _incident_roads(list(all_roads), node)


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
    context: Step45Context,
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


def _visual_review_class(step45_state: str, reason: str) -> str:
    if step45_state == "established":
        return "V1 认可成功"
    if step45_state == "review":
        if reason == "step45_support_only":
            return "V2 业务正确但几何待修"
        return "V2 业务正确但几何待修"
    return "V5 明确失败"


def build_step45_status_doc(case_result: Step45CaseResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_id,
        "template_class": case_result.template_class,
        "association_class": case_result.association_class,
        "step45_state": case_result.step45_state,
        "step45_established": case_result.step45_established,
        "reason": case_result.reason,
        "visual_review_class": case_result.visual_review_class,
        "root_cause_layer": case_result.root_cause_layer,
        "root_cause_type": case_result.root_cause_type,
        "key_metrics": case_result.key_metrics,
        **case_result.extra_status_fields,
    }


def _empty_step45_key_metrics() -> dict[str, Any]:
    return {
        "active_rcsdnode_count": 0,
        "active_rcsdroad_count": 0,
        "candidate_rcsdnode_count": 0,
        "candidate_rcsdroad_count": 0,
        "required_rcsdnode_count": 0,
        "required_rcsdroad_count": 0,
        "support_rcsdnode_count": 0,
        "support_rcsdroad_count": 0,
        "excluded_rcsdnode_count": 0,
        "excluded_rcsdroad_count": 0,
        "nonsemantic_connector_rcsdnode_count": 0,
        "true_foreign_rcsdnode_count": 0,
        "hook_zone_present": False,
        "hook_zone_area_m2": 0.0,
        "parallel_support_duplicate_drop_count": 0,
    }


def _build_gate_failure_case_result(
    *,
    context: Step45Context,
    base_extra_fields: dict[str, Any],
    blocker: str,
    supported_template: bool,
    allowed_space_loaded: bool,
    current_swsd_surface_loaded: bool,
) -> Step45CaseResult:
    empty_geometries = Step45OutputGeometries(None, None, None, None, None, None, None, None, None)
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
            "degree2_connector_candidate_rcsdnode_ids": [],
            "parallel_support_duplicate_dropped_rcsdroad_ids": [],
            "hook_zone_shrunk_road_ids": [],
        },
        "step5": {
            "association_class": "C",
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "excluded_rcsdnode_ids": [],
            "excluded_rcsdroad_ids": [],
            "foreign_swsd_group_ids": [],
            "foreign_swsd_road_ids": [],
            "nonsemantic_connector_rcsdnode_ids": [],
            "true_foreign_rcsdnode_ids": [],
        },
        "joint_phase": {
            "step45_state": "not_established",
            "reason": blocker,
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "rcsd_semantic_core_missing": False,
            "prerequisite_issues": list(context.prerequisite_issues),
        },
    }
    return Step45CaseResult(
        case_id=context.step1_context.case_spec.case_id,
        template_class=context.template_result.template_class,
        association_class="C",
        step45_state="not_established",
        step45_established=False,
        reason=blocker,
        visual_review_class="V5 明确失败",
        root_cause_layer="step45",
        root_cause_type=blocker,
        output_geometries=empty_geometries,
        key_metrics=_empty_step45_key_metrics(),
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
            "ignored_outside_current_swsd_surface_rcsdnode_ids": [],
            "ignored_outside_current_swsd_surface_rcsdroad_ids": [],
            "parallel_support_duplicate_dropped_rcsdroad_ids": [],
            "hook_zone_shrunk_road_ids": [],
        },
    )


def build_step45_case_result(context: Step45Context) -> Step45CaseResult:
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
        "required_rcsdnode_ids": [],
        "required_rcsdroad_ids": [],
        "support_rcsdnode_ids": [],
        "support_rcsdroad_ids": [],
        "excluded_rcsdnode_ids": [],
        "excluded_rcsdroad_ids": [],
        "step45_prerequisite_issues": list(context.prerequisite_issues),
        "association_executed": False,
        "association_reason": None,
        "association_blocker": None,
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
            blocker="step45_step3_not_established",
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
    active_rcsd_nodes = [
        node for node in step1.rcsd_nodes if node.geometry.intersects(current_swsd_surface.buffer(RCSD_ALLOWED_BUFFER_M))
    ]
    active_rcsd_roads = [
        road for road in step1.rcsd_roads if road.geometry.intersects(current_swsd_surface.buffer(RCSD_ALLOWED_BUFFER_M))
    ]
    ignored_outside_current_swsd_surface_rcsdnode_ids = _sorted_ids(
        node.node_id for node in step1.rcsd_nodes if node.node_id not in {item.node_id for item in active_rcsd_nodes}
    )
    ignored_outside_current_swsd_surface_rcsdroad_ids = _sorted_ids(
        road.road_id for road in step1.rcsd_roads if road.road_id not in {item.road_id for item in active_rcsd_roads}
    )

    node_graph_incident_map = {
        node.node_id: _graph_incident_roads(active_rcsd_roads, node)
        for node in active_rcsd_nodes
    }
    node_degree_map = {
        node_id: len({road.road_id for road in roads})
        for node_id, roads in node_graph_incident_map.items()
    }

    candidate_nodes = [node for node in active_rcsd_nodes if node.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))]
    candidate_roads = [road for road in active_rcsd_roads if road.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))]
    degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes
        if node_degree_map.get(node.node_id, 0) == 2
    }

    grouped_candidate_nodes: dict[str, list[NodeRecord]] = defaultdict(list)
    for node in candidate_nodes:
        grouped_candidate_nodes[_normalize_group_id(node)].append(node)

    for group_nodes in grouped_candidate_nodes.values():
        eligible_group_nodes = [
            node
            for node in group_nodes
            if node.node_id not in degree2_connector_candidate_node_ids
        ]
        if not eligible_group_nodes:
            continue
        group_incident_roads: list[RoadRecord] = []
        for node in eligible_group_nodes:
            group_incident_roads.extend(_incident_roads(candidate_roads, node))
        group_incident_roads = list({road.road_id: road for road in group_incident_roads}.values())
        overlap_count = sum(1 for road in group_incident_roads if road.geometry.intersects(selected_corridor.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)))
        if overlap_count <= 0 and not any(node.geometry.buffer(6.0).intersects(selected_corridor) for node in eligible_group_nodes):
            continue
        for node in eligible_group_nodes:
            required_node_ids.add(node.node_id)
            required_nodes.append(node)
        for road in group_incident_roads:
            if not road.geometry.intersects(selected_corridor.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)):
                continue
            required_road_ids.add(road.road_id)
            required_roads.append(road)

    required_roads = list({road.road_id: road for road in required_roads}.values())

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
        support_road_ids.add(road.road_id)
        support_roads.append(road)
        support_fragments.append(fragment)
    support_fragments_by_id = {
        road.road_id: fragment
        for road, fragment in zip(support_roads, support_fragments, strict=False)
    }
    support_fragments_by_id, dropped_parallel_support_road_ids = _prune_parallel_support_duplicates(
        context=context,
        support_fragments_by_id=support_fragments_by_id,
        anchor_point=anchor_point,
        vertical_exit_geometry=vertical_exit_geometry,
    )
    if dropped_parallel_support_road_ids:
        support_roads = [road for road in support_roads if road.road_id in support_fragments_by_id]
        support_fragments = [support_fragments_by_id[road.road_id] for road in support_roads]
        support_road_ids = {road.road_id for road in support_roads}
        hook_shrunk_road_ids = [road_id for road_id in hook_shrunk_road_ids if road_id in support_road_ids]
    support_roads = list({road.road_id: road for road in support_roads}.values())

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
        if node.node_id in degree2_connector_candidate_node_ids:
            continue
        if node.geometry.buffer(6.0).intersects(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M)):
            support_node_ids.add(node.node_id)

    rcsd_semantic_core_missing = association_class == "B" and not required_node_ids
    foreign_result = build_step45_foreign_result(
        context=context,
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        required_rcsdnode_ids=required_node_ids,
        support_rcsdnode_ids=support_node_ids,
        required_rcsdroad_ids=required_road_ids,
        support_rcsdroad_ids=support_road_ids,
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
        step45_state = "not_established"
        reason = "step45_missing_hook_zone"
    elif association_class == "B":
        step45_state = "review"
        reason = "step45_support_only"
    elif association_class == "C":
        step45_state = "review" if step3_state == "review" else "established"
        reason = "step45_upstream_step3_review" if step3_state == "review" else "step45_no_related_rcsd"
    else:
        step45_state = "review" if step3_state == "review" else "established"
        reason = "step45_upstream_step3_review" if step3_state == "review" else "step45_established"

    output_geometries = Step45OutputGeometries(
        required_rcsdnode_geometry=_union_points(node.geometry for node in candidate_nodes if node.node_id in required_node_ids),
        required_rcsdroad_geometry=required_road_geometry,
        support_rcsdnode_geometry=_union_points(node.geometry for node in candidate_nodes if node.node_id in support_node_ids),
        support_rcsdroad_geometry=support_road_geometry,
        excluded_rcsdnode_geometry=foreign_result.excluded_rcsdnode_geometry,
        excluded_rcsdroad_geometry=foreign_result.excluded_rcsdroad_geometry,
        required_hook_zone_geometry=hook_zone_geometry,
        foreign_swsd_context_geometry=foreign_result.foreign_swsd_context_geometry,
        foreign_rcsd_context_geometry=foreign_result.foreign_rcsd_context_geometry,
    )

    key_metrics = {
        "active_rcsdnode_count": len(active_rcsd_nodes),
        "active_rcsdroad_count": len(active_rcsd_roads),
        "candidate_rcsdnode_count": len(candidate_nodes),
        "candidate_rcsdroad_count": len(candidate_roads),
        "required_rcsdnode_count": len(required_node_ids),
        "required_rcsdroad_count": len(required_road_ids),
        "support_rcsdnode_count": len(support_node_ids),
        "support_rcsdroad_count": len(support_road_ids),
        "excluded_rcsdnode_count": len(foreign_result.excluded_rcsdnode_ids),
        "excluded_rcsdroad_count": len(foreign_result.excluded_rcsdroad_ids),
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
            "active_rcsdroad_ids": [road.road_id for road in active_rcsd_roads],
            "ignored_outside_current_swsd_surface_rcsdnode_ids": ignored_outside_current_swsd_surface_rcsdnode_ids,
            "ignored_outside_current_swsd_surface_rcsdroad_ids": ignored_outside_current_swsd_surface_rcsdroad_ids,
            "candidate_rcsdnode_ids": [node.node_id for node in candidate_nodes],
            "candidate_rcsdroad_ids": [road.road_id for road in candidate_roads],
            "required_rcsdnode_ids": _sorted_ids(required_node_ids),
            "required_rcsdroad_ids": _sorted_ids(required_road_ids),
            "support_rcsdnode_ids": _sorted_ids(support_node_ids),
            "support_rcsdroad_ids": _sorted_ids(support_road_ids),
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
            "degree2_connector_candidate_rcsdnode_ids": _sorted_ids(degree2_connector_candidate_node_ids),
            "rcsdnode_degree_map": {node_id: int(node_degree_map.get(node_id, 0)) for node_id in _sorted_ids(node_degree_map.keys())},
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
            "step45_state": step45_state,
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
        "required_rcsdnode_ids": audit_doc["step4"]["required_rcsdnode_ids"],
        "required_rcsdroad_ids": audit_doc["step4"]["required_rcsdroad_ids"],
        "support_rcsdnode_ids": audit_doc["step4"]["support_rcsdnode_ids"],
        "support_rcsdroad_ids": audit_doc["step4"]["support_rcsdroad_ids"],
        "excluded_rcsdnode_ids": list(foreign_result.excluded_rcsdnode_ids),
        "excluded_rcsdroad_ids": list(foreign_result.excluded_rcsdroad_ids),
        "association_executed": True,
        "association_reason": association_reason,
        "association_blocker": None,
        "rcsd_semantic_core_missing": rcsd_semantic_core_missing,
        "nonsemantic_connector_rcsdnode_ids": list(foreign_result.nonsemantic_connector_rcsdnode_ids),
        "true_foreign_rcsdnode_ids": list(foreign_result.true_foreign_rcsdnode_ids),
        "degree2_connector_candidate_rcsdnode_ids": audit_doc["step4"]["degree2_connector_candidate_rcsdnode_ids"],
        "ignored_outside_current_swsd_surface_rcsdnode_ids": ignored_outside_current_swsd_surface_rcsdnode_ids,
        "ignored_outside_current_swsd_surface_rcsdroad_ids": ignored_outside_current_swsd_surface_rcsdroad_ids,
        "parallel_support_duplicate_dropped_rcsdroad_ids": dropped_parallel_support_road_ids,
        "hook_zone_shrunk_road_ids": audit_doc["step4"]["hook_zone_shrunk_road_ids"],
    }
    return Step45CaseResult(
        case_id=step1.case_spec.case_id,
        template_class=template_result.template_class,
        association_class=association_class,
        step45_state=step45_state,
        step45_established=step45_state == "established",
        reason=reason,
        visual_review_class=_visual_review_class(step45_state, reason),
        root_cause_layer=None if step45_state == "established" else "step45",
        root_cause_type=None if step45_state == "established" else reason,
        output_geometries=output_geometries,
        key_metrics=key_metrics,
        audit_doc=audit_doc,
        extra_status_fields=extra_status_fields,
    )
