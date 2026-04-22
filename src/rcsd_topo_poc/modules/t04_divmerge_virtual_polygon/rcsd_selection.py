from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedNode,
    ParsedRoad,
)


RCSD_SCOPE_RELATION_PAD_M = 8.0
RCSD_REFERENCE_BUFFER_M = 10.0
RCSD_REFERENCE_CORRIDOR_HALF_WIDTH_M = 9.0
RCSD_NODE_TOUCH_TOLERANCE_M = 2.5
RCSD_FIRST_HIT_SIGN_TOLERANCE_M = 0.75
RCSD_FIRST_HIT_MAX_DISTANCE_M = 24.0
RCSD_TRACE_MAX_DEPTH = 4


def _normalize_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    geom_type = str(getattr(geometry, "geom_type", "") or "")
    if geom_type in {"Polygon", "MultiPolygon"}:
        try:
            normalized = geometry.buffer(0)
        except Exception:
            normalized = geometry
    else:
        normalized = geometry
    if normalized is None or normalized.is_empty:
        return None
    return normalized


def _union_geometry(geometries: Iterable[BaseGeometry | None]) -> BaseGeometry | None:
    valid = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not valid:
        return None
    return _normalize_geometry(unary_union(valid))


def _as_point(geometry: BaseGeometry | None) -> Point | None:
    if geometry is None or geometry.is_empty:
        return None
    if getattr(geometry, "geom_type", None) == "Point":
        return geometry
    try:
        point = geometry.representative_point()
    except Exception:
        return None
    return None if point is None or point.is_empty else point


def _safe_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _operational_event_type(operational_kind_hint: int | None) -> str:
    if int(operational_kind_hint or 16) == 8:
        return "merge"
    return "diverge"


def _endpoint_points(road: ParsedRoad) -> tuple[tuple[str | None, Point], tuple[str | None, Point]]:
    coords = list(getattr(road.geometry, "coords", []))
    start = Point(coords[0])
    end = Point(coords[-1])
    return (
        (_safe_id(getattr(road, "snodeid", None)), start),
        (_safe_id(getattr(road, "enodeid", None)), end),
    )


def _signed_projection(origin: Point, target: Point, vector: tuple[float, float] | None) -> float | None:
    if vector is None:
        return None
    dx = float(target.x) - float(origin.x)
    dy = float(target.y) - float(origin.y)
    return dx * float(vector[0]) + dy * float(vector[1])


def _normal_vector(axis_vector: tuple[float, float] | None) -> tuple[float, float] | None:
    if axis_vector is None:
        return None
    return (-float(axis_vector[1]), float(axis_vector[0]))


def _road_nearest_point(road: ParsedRoad, point: Point) -> Point | None:
    geometry = getattr(road, "geometry", None)
    if geometry is None or geometry.is_empty:
        return None
    try:
        return nearest_points(point, geometry)[1]
    except Exception:
        return None


def _road_far_point(road: ParsedRoad, origin: Point) -> Point | None:
    start, end = _endpoint_points(road)
    return start[1] if start[1].distance(origin) >= end[1].distance(origin) else end[1]


def _road_side_label(road: ParsedRoad, *, origin: Point, normal_vector: tuple[float, float] | None) -> str:
    point = _road_far_point(road, origin) or _road_nearest_point(road, origin)
    if point is None:
        return "center"
    signed = _signed_projection(origin, point, normal_vector)
    if signed is None or abs(float(signed)) <= RCSD_FIRST_HIT_SIGN_TOLERANCE_M:
        return "center"
    return "right" if float(signed) > 0.0 else "left"


def _road_axis_side(
    road: ParsedRoad,
    *,
    origin: Point,
    axis_vector: tuple[float, float] | None,
) -> str:
    point = _road_far_point(road, origin) or _road_nearest_point(road, origin)
    if point is None:
        return "unknown"
    signed = _signed_projection(origin, point, axis_vector)
    if signed is None:
        return "unknown"
    return "event_side" if float(signed) >= 0.0 else "axis_side"


def _clip_to_pair_local_scope(
    geometry: BaseGeometry | None,
    *,
    pair_local_region_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if pair_local_region_geometry is None or pair_local_region_geometry.is_empty:
        return geometry
    try:
        clipped = geometry.intersection(pair_local_region_geometry.buffer(RCSD_SCOPE_RELATION_PAD_M, join_style=2))
    except Exception:
        clipped = geometry
    return _normalize_geometry(clipped)


def _build_candidate_scope_geometry(
    *,
    representative_point: Point,
    fact_reference_point: Point | None,
    selected_evidence_region_geometry: BaseGeometry | None,
    pair_local_middle_geometry: BaseGeometry | None,
    pair_local_region_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    parts: list[BaseGeometry] = []
    if selected_evidence_region_geometry is not None and not selected_evidence_region_geometry.is_empty:
        parts.append(selected_evidence_region_geometry.buffer(RCSD_SCOPE_RELATION_PAD_M, join_style=2))
    if fact_reference_point is not None and not fact_reference_point.is_empty:
        parts.append(fact_reference_point.buffer(RCSD_REFERENCE_BUFFER_M, join_style=2))
    if pair_local_middle_geometry is not None and not pair_local_middle_geometry.is_empty:
        parts.append(pair_local_middle_geometry.buffer(2.0, join_style=2))
    if fact_reference_point is not None and representative_point.distance(fact_reference_point) > 1e-6:
        parts.append(
            LineString(
                [
                    (float(representative_point.x), float(representative_point.y)),
                    (float(fact_reference_point.x), float(fact_reference_point.y)),
                ]
            ).buffer(
                RCSD_REFERENCE_CORRIDOR_HALF_WIDTH_M,
                cap_style=2,
                join_style=2,
            )
        )
    scope = _union_geometry(parts)
    return _clip_to_pair_local_scope(scope, pair_local_region_geometry=pair_local_region_geometry)


def _road_enters_candidate_scope(
    road: ParsedRoad,
    *,
    candidate_scope_geometry: BaseGeometry | None,
    selected_evidence_region_geometry: BaseGeometry | None,
    fact_reference_point: Point | None,
) -> bool:
    geometry = getattr(road, "geometry", None)
    if geometry is None or geometry.is_empty:
        return False
    if candidate_scope_geometry is not None and candidate_scope_geometry.buffer(1e-6).intersects(geometry):
        return True
    if (
        selected_evidence_region_geometry is not None
        and not selected_evidence_region_geometry.is_empty
        and geometry.distance(selected_evidence_region_geometry) <= RCSD_SCOPE_RELATION_PAD_M
    ):
        return True
    if fact_reference_point is not None and geometry.distance(fact_reference_point) <= RCSD_REFERENCE_BUFFER_M:
        return True
    return False


def _first_hit_roads(
    *,
    roads: Sequence[ParsedRoad],
    fact_reference_point: Point | None,
    axis_vector: tuple[float, float] | None,
) -> tuple[tuple[str, ...], dict[str, Point], BaseGeometry | None]:
    if fact_reference_point is None or axis_vector is None or not roads:
        return (), {}, None
    normal_vector = _normal_vector(axis_vector)
    if normal_vector is None:
        return (), {}, None
    best_positive: tuple[float, str, Point] | None = None
    best_negative: tuple[float, str, Point] | None = None
    hit_points: dict[str, Point] = {}
    for road in roads:
        road_id = _safe_id(getattr(road, "road_id", None))
        if road_id is None:
            continue
        nearest_point = _road_nearest_point(road, fact_reference_point)
        if nearest_point is None:
            continue
        signed = _signed_projection(fact_reference_point, nearest_point, normal_vector)
        if signed is None:
            continue
        signed_value = float(signed)
        abs_signed = abs(signed_value)
        if abs_signed > RCSD_FIRST_HIT_MAX_DISTANCE_M or abs_signed <= RCSD_FIRST_HIT_SIGN_TOLERANCE_M:
            continue
        hit_points[road_id] = nearest_point
        if signed_value > 0.0:
            candidate = (abs_signed, road_id, nearest_point)
            if best_positive is None or candidate < best_positive:
                best_positive = candidate
        else:
            candidate = (abs_signed, road_id, nearest_point)
            if best_negative is None or candidate < best_negative:
                best_negative = candidate
    ordered_ids = tuple(
        road_id
        for road_id in (
            None if best_negative is None else best_negative[1],
            None if best_positive is None else best_positive[1],
        )
        if road_id is not None
    )
    road_lookup = _road_lookup(roads)
    geometry = _union_geometry(
        road_lookup[road_id].geometry
        for road_id in ordered_ids
        if road_id in road_lookup
    )
    return ordered_ids, hit_points, geometry


def _road_lookup(roads: Iterable[ParsedRoad]) -> dict[str, ParsedRoad]:
    return {
        road_id: road
        for road in roads
        if (road_id := _safe_id(getattr(road, "road_id", None))) is not None
    }


def _node_lookup(
    nodes: Iterable[ParsedNode],
    *,
    roads: Iterable[ParsedRoad],
) -> dict[str, Point]:
    result: dict[str, Point] = {}
    for node in nodes:
        node_id = _safe_id(getattr(node, "node_id", None))
        geometry = _as_point(getattr(node, "geometry", None))
        if node_id is None or geometry is None:
            continue
        result[node_id] = geometry
    for road in roads:
        start, end = _endpoint_points(road)
        if start[0] is not None and start[0] not in result:
            result[start[0]] = start[1]
        if end[0] is not None and end[0] not in result:
            result[end[0]] = end[1]
    return result


def _roads_by_node(roads: Iterable[ParsedRoad]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for road in roads:
        road_id = _safe_id(getattr(road, "road_id", None))
        if road_id is None:
            continue
        for node_id, _point in _endpoint_points(road):
            if node_id is None:
                continue
            mapping[node_id].add(road_id)
    return mapping


def _node_ids_for_roads(road_ids: Iterable[str], roads_by_id: dict[str, ParsedRoad]) -> set[str]:
    result: set[str] = set()
    for road_id in road_ids:
        road = roads_by_id.get(str(road_id))
        if road is None:
            continue
        for node_id, _point in _endpoint_points(road):
            if node_id is not None:
                result.add(node_id)
    return result


def _trace_path_to_node(
    *,
    start_road_id: str,
    target_node_id: str,
    roads_by_id: dict[str, ParsedRoad],
    roads_by_node_id: dict[str, set[str]],
) -> tuple[str, ...]:
    if start_road_id not in roads_by_id:
        return ()
    if target_node_id in _node_ids_for_roads([start_road_id], roads_by_id):
        return (start_road_id,)
    queue: deque[tuple[str, tuple[str, ...], int]] = deque([(start_road_id, (start_road_id,), 0)])
    seen_roads = {start_road_id}
    while queue:
        road_id, path, depth = queue.popleft()
        if depth >= RCSD_TRACE_MAX_DEPTH:
            continue
        for node_id in _node_ids_for_roads([road_id], roads_by_id):
            if node_id == target_node_id:
                return path
            for next_road_id in sorted(roads_by_node_id.get(node_id, ())):
                if next_road_id in seen_roads:
                    continue
                seen_roads.add(next_road_id)
                queue.append((next_road_id, (*path, next_road_id), depth + 1))
    return ()


def _branch_side_labels(
    *,
    boundary_branch_ids: Sequence[str],
    preferred_axis_branch_id: str | None,
    branch_road_memberships: dict[str, Sequence[str]],
    scoped_roads: Sequence[ParsedRoad],
    representative_point: Point,
    normal_vector: tuple[float, float] | None,
) -> dict[str, str]:
    road_lookup = _road_lookup(scoped_roads)
    labels: dict[str, str] = {}
    for branch_id in boundary_branch_ids:
        if str(branch_id) == str(preferred_axis_branch_id):
            labels[str(branch_id)] = "axis"
            continue
        branch_roads = [
            road_lookup[road_id]
            for road_id in branch_road_memberships.get(str(branch_id), ())
            if road_id in road_lookup
        ]
        if not branch_roads:
            labels[str(branch_id)] = "unknown"
            continue
        signed_candidates: list[tuple[float, str]] = []
        for road in branch_roads:
            side_label = _road_side_label(road, origin=representative_point, normal_vector=normal_vector)
            point = _road_far_point(road, representative_point) or _road_nearest_point(road, representative_point)
            if point is None:
                continue
            signed = _signed_projection(representative_point, point, normal_vector)
            signed_candidates.append((0.0 if signed is None else abs(float(signed)), side_label))
        if not signed_candidates:
            labels[str(branch_id)] = "unknown"
            continue
        signed_candidates.sort(reverse=True)
        labels[str(branch_id)] = signed_candidates[0][1]
    return labels


def _expected_swsd_role_map(
    *,
    event_type: str,
    boundary_branch_ids: Sequence[str],
    scoped_input_branch_ids: Sequence[str],
    scoped_output_branch_ids: Sequence[str],
    preferred_axis_branch_id: str | None,
    branch_road_memberships: dict[str, Sequence[str]],
    scoped_roads: Sequence[ParsedRoad],
    representative_point: Point,
    normal_vector: tuple[float, float] | None,
) -> dict[str, Any]:
    boundary_set = {str(branch_id) for branch_id in boundary_branch_ids}
    entering = [str(branch_id) for branch_id in scoped_input_branch_ids if str(branch_id) in boundary_set]
    exiting = [str(branch_id) for branch_id in scoped_output_branch_ids if str(branch_id) in boundary_set]
    if not entering or not exiting:
        if str(event_type) == "merge":
            entering = [str(branch_id) for branch_id in boundary_branch_ids if str(branch_id) != str(preferred_axis_branch_id)]
            exiting = [str(preferred_axis_branch_id)] if preferred_axis_branch_id else []
        else:
            entering = [str(preferred_axis_branch_id)] if preferred_axis_branch_id else []
            exiting = [str(branch_id) for branch_id in boundary_branch_ids if str(branch_id) != str(preferred_axis_branch_id)]
    side_labels = _branch_side_labels(
        boundary_branch_ids=boundary_branch_ids,
        preferred_axis_branch_id=preferred_axis_branch_id,
        branch_road_memberships=branch_road_memberships,
        scoped_roads=scoped_roads,
        representative_point=representative_point,
        normal_vector=normal_vector,
    )
    event_side_role = "entering" if str(event_type) == "merge" else "exiting"
    event_side_branch_ids = entering if event_side_role == "entering" else exiting
    event_side_labels = tuple(
        label
        for label in (side_labels.get(branch_id, "unknown") for branch_id in event_side_branch_ids)
        if label not in {"axis", "center", "unknown"}
    )
    return {
        "event_type": str(event_type),
        "entering_branch_ids": tuple(entering),
        "exiting_branch_ids": tuple(exiting),
        "event_side_role": event_side_role,
        "event_side_branch_ids": tuple(event_side_branch_ids),
        "event_side_labels": tuple(sorted(event_side_labels)),
        "preferred_axis_branch_id": preferred_axis_branch_id,
        "boundary_branch_side_labels": side_labels,
    }


@dataclass(frozen=True)
class _LocalRcsdUnit:
    unit_id: str
    unit_kind: str
    node_id: str | None
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    entering_road_ids: tuple[str, ...]
    exiting_road_ids: tuple[str, ...]
    event_side_road_ids: tuple[str, ...]
    axis_side_road_ids: tuple[str, ...]
    event_side_labels: tuple[str, ...]
    first_hit_cover_count: int
    trunk_present: bool
    positive_rcsd_present: bool
    positive_rcsd_present_reason: str
    role_match_result: str
    consistency_level: str
    support_level: str
    decision_reason: str
    score: tuple[int, ...]
    road_geometry: BaseGeometry | None
    node_geometry: BaseGeometry | None
    geometry: BaseGeometry | None
    role_assignments: tuple[dict[str, Any], ...] = ()

    def to_doc(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_kind": self.unit_kind,
            "node_id": self.node_id,
            "road_ids": list(self.road_ids),
            "node_ids": list(self.node_ids),
            "entering_road_ids": list(self.entering_road_ids),
            "exiting_road_ids": list(self.exiting_road_ids),
            "event_side_road_ids": list(self.event_side_road_ids),
            "axis_side_road_ids": list(self.axis_side_road_ids),
            "event_side_labels": list(self.event_side_labels),
            "first_hit_cover_count": self.first_hit_cover_count,
            "trunk_present": self.trunk_present,
            "positive_rcsd_present": self.positive_rcsd_present,
            "positive_rcsd_present_reason": self.positive_rcsd_present_reason,
            "role_match_result": self.role_match_result,
            "consistency_level": self.consistency_level,
            "support_level": self.support_level,
            "decision_reason": self.decision_reason,
            "score": list(self.score),
            "role_assignments": list(self.role_assignments),
        }


@dataclass(frozen=True)
class _AggregatedRcsdUnit:
    unit_id: str
    member_unit_ids: tuple[str, ...]
    member_unit_kinds: tuple[str, ...]
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    entering_road_ids: tuple[str, ...]
    exiting_road_ids: tuple[str, ...]
    event_side_road_ids: tuple[str, ...]
    axis_side_road_ids: tuple[str, ...]
    event_side_labels: tuple[str, ...]
    normalized_event_side_labels: tuple[str, ...]
    axis_polarity_inverted: bool
    positive_rcsd_present: bool
    positive_rcsd_present_reason: str
    primary_local_unit_id: str | None
    primary_node_id: str | None
    required_node_id: str | None
    required_node_source: str | None
    consistency_level: str
    support_level: str
    decision_reason: str
    score: tuple[int, ...]
    road_geometry: BaseGeometry | None
    node_geometry: BaseGeometry | None
    geometry: BaseGeometry | None
    role_assignments: tuple[dict[str, Any], ...] = ()

    def to_doc(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "member_unit_ids": list(self.member_unit_ids),
            "member_unit_kinds": list(self.member_unit_kinds),
            "road_ids": list(self.road_ids),
            "node_ids": list(self.node_ids),
            "entering_road_ids": list(self.entering_road_ids),
            "exiting_road_ids": list(self.exiting_road_ids),
            "event_side_road_ids": list(self.event_side_road_ids),
            "axis_side_road_ids": list(self.axis_side_road_ids),
            "event_side_labels": list(self.event_side_labels),
            "normalized_event_side_labels": list(self.normalized_event_side_labels),
            "axis_polarity_inverted": self.axis_polarity_inverted,
            "positive_rcsd_present": self.positive_rcsd_present,
            "positive_rcsd_present_reason": self.positive_rcsd_present_reason,
            "primary_local_unit_id": self.primary_local_unit_id,
            "primary_node_id": self.primary_node_id,
            "required_node_id": self.required_node_id,
            "required_node_source": self.required_node_source,
            "consistency_level": self.consistency_level,
            "support_level": self.support_level,
            "decision_reason": self.decision_reason,
            "score": list(self.score),
            "role_assignments": list(self.role_assignments),
        }


@dataclass(frozen=True)
class PositiveRcsdSelectionDecision:
    selected_rcsdroad_ids: tuple[str, ...]
    selected_rcsdnode_ids: tuple[str, ...]
    primary_main_rc_node_id: str | None
    positive_rcsd_present: bool
    positive_rcsd_present_reason: str
    positive_rcsd_support_level: str
    positive_rcsd_consistency_level: str
    rcsd_consistency_result: str
    required_rcsd_node: str | None
    required_rcsd_node_source: str | None
    pair_local_rcsd_empty: bool
    pair_local_rcsd_road_ids: tuple[str, ...]
    pair_local_rcsd_node_ids: tuple[str, ...]
    first_hit_rcsdroad_ids: tuple[str, ...]
    local_rcsd_unit_id: str | None
    local_rcsd_unit_kind: str | None
    aggregated_rcsd_unit_id: str | None
    aggregated_rcsd_unit_ids: tuple[str, ...]
    axis_polarity_inverted: bool
    rcsd_selection_mode: str
    rcsd_decision_reason: str
    positive_rcsd_geometry: BaseGeometry | None
    positive_rcsd_road_geometry: BaseGeometry | None
    positive_rcsd_node_geometry: BaseGeometry | None
    primary_main_rc_node_geometry: BaseGeometry | None
    required_rcsd_node_geometry: BaseGeometry | None
    pair_local_rcsd_scope_geometry: BaseGeometry | None
    first_hit_rcsd_road_geometry: BaseGeometry | None
    local_rcsd_unit_geometry: BaseGeometry | None
    positive_rcsd_audit: dict[str, Any] = field(default_factory=dict)


def _mirror_side_label(label: str) -> str:
    if label == "left":
        return "right"
    if label == "right":
        return "left"
    return label


def _mirror_side_labels(labels: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_mirror_side_label(str(label)) for label in labels if str(label)}))


def _select_primary_node_id(
    *,
    node_ids: Iterable[str],
    node_points_by_id: dict[str, Point],
    representative_point: Point,
) -> str | None:
    best: tuple[float, str] | None = None
    for node_id in sorted({str(node_id) for node_id in node_ids if str(node_id)}):
        point = node_points_by_id.get(node_id)
        if point is None:
            continue
        candidate = (float(point.distance(representative_point)), node_id)
        if best is None or candidate < best:
            best = candidate
    return None if best is None else best[1]


def _select_required_node_id(
    *,
    node_ids: Iterable[str],
    local_units: Sequence["_LocalRcsdUnit"],
    road_ids: Iterable[str],
    roads_by_id: dict[str, ParsedRoad],
    roads_by_node_id: dict[str, set[str]],
    first_hit_road_ids: Iterable[str],
    node_points_by_id: dict[str, Point],
    representative_point: Point,
) -> str | None:
    candidate_node_ids = tuple(sorted({str(node_id) for node_id in node_ids if str(node_id)}))
    if not candidate_node_ids:
        return None
    component_road_ids = {str(road_id) for road_id in road_ids if str(road_id)}
    first_hit_set = {str(road_id) for road_id in first_hit_road_ids if str(road_id)}
    local_node_ids = {str(unit.node_id) for unit in local_units if unit.node_id}
    best: tuple[tuple[int, int, int, int, int, str], str] | None = None
    for node_id in candidate_node_ids:
        point = node_points_by_id.get(node_id)
        if point is None:
            continue
        incident_road_ids = set(roads_by_node_id.get(node_id, set())) & component_road_ids
        direct_first_hit_count = len(incident_road_ids & first_hit_set)
        traced_first_hit_count = 0
        for first_hit_road_id in sorted(first_hit_set):
            if _trace_path_to_node(
                start_road_id=first_hit_road_id,
                target_node_id=node_id,
                roads_by_id=roads_by_id,
                roads_by_node_id=roads_by_node_id,
            ):
                traced_first_hit_count += 1
        candidate = (
            traced_first_hit_count,
            len(incident_road_ids),
            direct_first_hit_count,
            1 if node_id in local_node_ids else 0,
            -int(round(float(point.distance(representative_point)) * 10.0)),
            node_id,
        )
        if best is None or candidate > best[0]:
            best = (candidate, node_id)
    return None if best is None else best[1]


def _unit_from_roads_and_node(
    *,
    unit_id: str,
    unit_kind: str,
    node_id: str | None,
    road_ids: Iterable[str],
    roads_by_id: dict[str, ParsedRoad],
    node_points_by_id: dict[str, Point],
    actual_node_ids: set[str],
    expected_role_map: dict[str, Any],
    representative_point: Point,
    axis_vector: tuple[float, float] | None,
    normal_vector: tuple[float, float] | None,
    first_hit_road_ids: set[str],
) -> _LocalRcsdUnit:
    ordered_road_ids = tuple(sorted({str(road_id) for road_id in road_ids if str(road_id) in roads_by_id}))
    event_side_role = str(expected_role_map.get("event_side_role") or "exiting")
    role_assignments: list[dict[str, Any]] = []
    event_side_road_ids: list[str] = []
    axis_side_road_ids: list[str] = []
    event_side_labels: list[str] = []
    for road_id in ordered_road_ids:
        road = roads_by_id[road_id]
        axis_side = _road_axis_side(
            road,
            origin=node_points_by_id.get(node_id) or representative_point,
            axis_vector=axis_vector,
        )
        side_label = _road_side_label(
            road,
            origin=node_points_by_id.get(node_id) or representative_point,
            normal_vector=normal_vector,
        )
        if axis_side == "event_side":
            role = event_side_role
            event_side_road_ids.append(road_id)
            if side_label not in {"center", "unknown"}:
                event_side_labels.append(side_label)
        elif axis_side == "axis_side":
            role = "exiting" if event_side_role == "entering" else "entering"
            axis_side_road_ids.append(road_id)
        else:
            role = "unknown"
        role_assignments.append(
            {
                "road_id": road_id,
                "role": role,
                "axis_side": axis_side,
                "side_label": side_label,
                "first_hit": road_id in first_hit_road_ids,
            }
        )
    expected_event_labels = set(expected_role_map.get("event_side_labels") or ())
    observed_event_labels = {label for label in event_side_labels if label}
    unexpected_labels = observed_event_labels - expected_event_labels
    matched_label_count = len(observed_event_labels & expected_event_labels)
    expected_event_arm_count = max(1, len(expected_role_map.get("event_side_branch_ids") or ()))
    trunk_present = bool(axis_side_road_ids)
    exact_match = (
        unit_kind == "node_centric"
        and trunk_present
        and not unexpected_labels
        and len(event_side_road_ids) == expected_event_arm_count
        and (
            not expected_event_labels
            or observed_event_labels == expected_event_labels
        )
    )
    partial_match = (
        bool(event_side_road_ids)
        and not unexpected_labels
        and len(event_side_road_ids) <= expected_event_arm_count
        and (
            not expected_event_labels
            or matched_label_count >= max(1, min(len(expected_event_labels), len(observed_event_labels)))
        )
    )
    if unit_kind == "road_only" and exact_match:
        exact_match = False
        partial_match = True
    positive_rcsd_present = bool(event_side_road_ids) and (
        trunk_present or unit_kind == "node_centric" or len(ordered_road_ids) >= 2
    )
    structural_conflict = bool(
        positive_rcsd_present
        and unit_kind == "node_centric"
        and not trunk_present
        and len(event_side_road_ids) >= expected_event_arm_count
    )
    if exact_match:
        consistency_level = "A"
        support_level = "primary_support"
        decision_reason = "local_role_mapping_exact"
        role_match_result = "exact"
        positive_rcsd_present_reason = "matched_event_side_with_trunk"
    elif structural_conflict:
        consistency_level = "C"
        support_level = "no_support"
        decision_reason = "local_role_mapping_structural_conflict"
        role_match_result = "structural_conflict"
        positive_rcsd_present_reason = "matched_event_side_without_trunk_conflict"
    elif partial_match:
        consistency_level = "B"
        support_level = "secondary_support"
        decision_reason = "local_role_mapping_partial"
        role_match_result = "partial"
        positive_rcsd_present_reason = "matched_event_side_partial"
    elif positive_rcsd_present:
        consistency_level = "B"
        support_level = "secondary_support"
        decision_reason = "local_role_mapping_label_relaxed"
        role_match_result = "label_mismatch_relaxed"
        positive_rcsd_present_reason = "matched_event_side_label_relaxed"
    else:
        consistency_level = "C"
        support_level = "no_support"
        if not ordered_road_ids:
            decision_reason = "empty_local_rcsd_unit"
            role_match_result = "empty"
            positive_rcsd_present_reason = "missing_local_structure"
        elif unexpected_labels:
            decision_reason = "local_role_mapping_label_mismatch_without_presence"
            role_match_result = "label_mismatch_without_presence"
            positive_rcsd_present_reason = "label_mismatch_without_presence"
        else:
            decision_reason = "local_role_mapping_failed"
            role_match_result = "failed"
            positive_rcsd_present_reason = "missing_event_side_role"
    road_geometry = _union_geometry(roads_by_id[road_id].geometry for road_id in ordered_road_ids)
    node_ids = tuple(
        sorted(
            ({node_id} if node_id is not None else set()) | (_node_ids_for_roads(ordered_road_ids, roads_by_id) & set(actual_node_ids))
        )
    )
    node_geometry = _union_geometry(
        node_points_by_id[node_id_value]
        for node_id_value in node_ids
        if node_id_value in node_points_by_id
    )
    geometry = _union_geometry([road_geometry, node_geometry])
    first_hit_cover_count = len(set(ordered_road_ids) & set(first_hit_road_ids))
    score = (
        3 if consistency_level == "A" else 2 if consistency_level == "B" else 1,
        1 if unit_kind == "node_centric" else 0,
        first_hit_cover_count,
        1 if trunk_present else 0,
        matched_label_count,
        -len(unexpected_labels),
        -int(round(float((node_points_by_id.get(node_id) or representative_point).distance(representative_point)) * 10.0)),
    )
    return _LocalRcsdUnit(
        unit_id=unit_id,
        unit_kind=unit_kind,
        node_id=node_id,
        road_ids=ordered_road_ids,
        node_ids=node_ids,
        entering_road_ids=tuple(
            assignment["road_id"] for assignment in role_assignments if assignment["role"] == "entering"
        ),
        exiting_road_ids=tuple(
            assignment["road_id"] for assignment in role_assignments if assignment["role"] == "exiting"
        ),
        event_side_road_ids=tuple(event_side_road_ids),
        axis_side_road_ids=tuple(axis_side_road_ids),
        event_side_labels=tuple(sorted(observed_event_labels)),
        first_hit_cover_count=first_hit_cover_count,
        trunk_present=trunk_present,
        positive_rcsd_present=positive_rcsd_present,
        positive_rcsd_present_reason=positive_rcsd_present_reason,
        role_match_result=role_match_result,
        consistency_level=consistency_level,
        support_level=support_level,
        decision_reason=decision_reason,
        score=score,
        road_geometry=road_geometry,
        node_geometry=node_geometry,
        geometry=geometry,
        role_assignments=tuple(role_assignments),
    )


def _build_aggregated_rcsd_units(
    *,
    event_unit_id: str,
    local_units: Sequence[_LocalRcsdUnit],
    expected_role_map: dict[str, Any],
    first_hit_road_ids: tuple[str, ...],
    roads_by_id: dict[str, ParsedRoad],
    roads_by_node_id: dict[str, set[str]],
    node_points_by_id: dict[str, Point],
    representative_point: Point,
) -> tuple[_AggregatedRcsdUnit, ...]:
    matched_units = [unit for unit in local_units if unit.positive_rcsd_present]
    if not matched_units:
        return ()

    adjacency: dict[int, set[int]] = defaultdict(set)
    for left_index, left_unit in enumerate(matched_units):
        for right_index in range(left_index + 1, len(matched_units)):
            right_unit = matched_units[right_index]
            if (
                set(left_unit.road_ids) & set(right_unit.road_ids)
                or set(left_unit.node_ids) & set(right_unit.node_ids)
                or (
                    set(left_unit.road_ids) & set(first_hit_road_ids)
                    and set(right_unit.road_ids) & set(first_hit_road_ids)
                )
            ):
                adjacency[left_index].add(right_index)
                adjacency[right_index].add(left_index)

    components: list[list[_LocalRcsdUnit]] = []
    seen_indices: set[int] = set()
    for start_index, start_unit in enumerate(matched_units):
        if start_index in seen_indices:
            continue
        queue = deque([start_index])
        seen_indices.add(start_index)
        component_indices: list[int] = []
        while queue:
            index = queue.popleft()
            component_indices.append(index)
            for next_index in adjacency.get(index, set()):
                if next_index in seen_indices:
                    continue
                seen_indices.add(next_index)
                queue.append(next_index)
        components.append([matched_units[index] for index in sorted(component_indices)])

    expected_event_labels = set(expected_role_map.get("event_side_labels") or ())
    expected_event_arm_count = max(1, len(expected_role_map.get("event_side_branch_ids") or ()))
    aggregated_units: list[_AggregatedRcsdUnit] = []
    first_hit_set = set(first_hit_road_ids)
    for component_index, component_units in enumerate(components, start=1):
        component_units_sorted = sorted(component_units, key=lambda unit: unit.score, reverse=True)
        primary_local_unit = component_units_sorted[0]
        road_ids = tuple(sorted({road_id for unit in component_units_sorted for road_id in unit.road_ids}))
        node_ids = tuple(sorted({node_id for unit in component_units_sorted for node_id in unit.node_ids if node_id}))
        event_side_road_ids = tuple(
            sorted({road_id for unit in component_units_sorted for road_id in unit.event_side_road_ids})
        )
        axis_side_road_ids = tuple(
            sorted({road_id for unit in component_units_sorted for road_id in unit.axis_side_road_ids})
        )
        entering_road_ids = tuple(
            sorted({road_id for unit in component_units_sorted for road_id in unit.entering_road_ids})
        )
        exiting_road_ids = tuple(
            sorted({road_id for unit in component_units_sorted for road_id in unit.exiting_road_ids})
        )
        observed_labels = tuple(
            sorted({label for unit in component_units_sorted for label in unit.event_side_labels if label})
        )
        mirrored_labels = _mirror_side_labels(observed_labels)
        normalized_labels = observed_labels
        axis_polarity_inverted = False
        if expected_event_labels and observed_labels:
            if set(observed_labels).issubset(expected_event_labels):
                normalized_labels = observed_labels
            elif set(mirrored_labels).issubset(expected_event_labels):
                normalized_labels = mirrored_labels
                axis_polarity_inverted = True
        positive_rcsd_present = any(unit.positive_rcsd_present for unit in component_units_sorted)
        matched_arm_count = (
            len(set(normalized_labels) & expected_event_labels)
            if expected_event_labels
            else (1 if event_side_road_ids else 0)
        )
        observed_event_arm_count = (
            len(set(normalized_labels))
            if normalized_labels
            else (1 if event_side_road_ids else 0)
        )
        has_node_centric = any(unit.unit_kind == "node_centric" for unit in component_units_sorted)
        has_exact_local_node_unit = any(
            unit.unit_kind == "node_centric" and unit.consistency_level == "A"
            for unit in component_units_sorted
        )
        trunk_present = bool(axis_side_road_ids)
        primary_node_id = _select_primary_node_id(
            node_ids=node_ids,
            node_points_by_id=node_points_by_id,
            representative_point=representative_point,
        )
        required_node_id = (
            _select_required_node_id(
                node_ids=node_ids,
                local_units=component_units_sorted,
                road_ids=road_ids,
                roads_by_id=roads_by_id,
                roads_by_node_id=roads_by_node_id,
                first_hit_road_ids=first_hit_road_ids,
                node_points_by_id=node_points_by_id,
                representative_point=representative_point,
            )
            if has_node_centric and positive_rcsd_present
            else None
        )
        required_node_source = None
        if required_node_id is not None:
            required_node_source = (
                "aggregated_node_centric"
                if required_node_id == primary_node_id
                else "aggregated_structural_required"
            )
        required_incident_road_ids = (
            set(roads_by_node_id.get(required_node_id, set())) & set(road_ids)
            if required_node_id is not None
            else set()
        )
        required_first_hit_trace_count = 0
        if required_node_id is not None:
            for first_hit_road_id in first_hit_road_ids:
                if _trace_path_to_node(
                    start_road_id=first_hit_road_id,
                    target_node_id=required_node_id,
                    roads_by_id=roads_by_id,
                    roads_by_node_id=roads_by_node_id,
                ):
                    required_first_hit_trace_count += 1
        structural_arm_target = expected_event_arm_count + 1
        structural_support_complete = bool(
            required_node_id is not None
            and len(required_incident_road_ids) >= structural_arm_target
            and (
                not first_hit_road_ids
                or required_first_hit_trace_count >= max(1, len(tuple(sorted(set(first_hit_road_ids)))))
            )
        )
        structural_conflict = bool(
            positive_rcsd_present
            and has_node_centric
            and not trunk_present
            and len(event_side_road_ids) >= expected_event_arm_count
        )
        if not positive_rcsd_present:
            consistency_level = "C"
            support_level = "no_support"
            decision_reason = "aggregated_role_mapping_failed"
            positive_rcsd_present_reason = "no_positive_rcsd_present"
        elif structural_conflict:
            consistency_level = "C"
            support_level = "no_support"
            decision_reason = "role_mapping_structural_conflict"
            positive_rcsd_present_reason = "aggregated_structural_conflict"
        else:
            positive_rcsd_present_reason = (
                "aggregated_axis_polarity_inverted"
                if axis_polarity_inverted
                else "aggregated_forward_rcsd_present"
            )
            exact_match = (
                has_node_centric
                and (has_exact_local_node_unit or structural_support_complete)
            )
            if exact_match:
                consistency_level = "A"
                support_level = "primary_support"
                decision_reason = (
                    "role_mapping_exact_axis_polarity_inverted"
                    if axis_polarity_inverted
                    else "role_mapping_exact_aggregated"
                )
            else:
                consistency_level = "B"
                support_level = "secondary_support"
                if axis_polarity_inverted:
                    decision_reason = "role_mapping_partial_axis_polarity_inverted"
                elif observed_event_arm_count < expected_event_arm_count:
                    decision_reason = "role_mapping_partial_missing_arms"
                else:
                    decision_reason = "role_mapping_partial_aggregated"
        road_geometry = _union_geometry(unit.road_geometry for unit in component_units_sorted)
        node_geometry = _union_geometry(unit.node_geometry for unit in component_units_sorted)
        geometry = _union_geometry([road_geometry, node_geometry])
        role_assignments = tuple(
            assignment
            for unit in component_units_sorted
            for assignment in unit.role_assignments
        )
        score = (
            3 if consistency_level == "A" else 2 if consistency_level == "B" else 1,
            1 if positive_rcsd_present else 0,
            1 if has_node_centric else 0,
            len(set(road_ids) & first_hit_set),
            max(matched_arm_count, len(required_incident_road_ids)),
            -int(axis_polarity_inverted),
            -int(
                round(
                    float(
                        (node_points_by_id.get(primary_node_id) or representative_point).distance(
                            representative_point
                        )
                    )
                    * 10.0
                )
            ),
        )
        aggregated_units.append(
            _AggregatedRcsdUnit(
                unit_id=f"{event_unit_id}:aggregated:{component_index:02d}",
                member_unit_ids=tuple(unit.unit_id for unit in component_units_sorted),
                member_unit_kinds=tuple(sorted({unit.unit_kind for unit in component_units_sorted})),
                road_ids=road_ids,
                node_ids=node_ids,
                entering_road_ids=entering_road_ids,
                exiting_road_ids=exiting_road_ids,
                event_side_road_ids=event_side_road_ids,
                axis_side_road_ids=axis_side_road_ids,
                event_side_labels=observed_labels,
                normalized_event_side_labels=tuple(sorted(set(normalized_labels))),
                axis_polarity_inverted=axis_polarity_inverted,
                positive_rcsd_present=positive_rcsd_present,
                positive_rcsd_present_reason=positive_rcsd_present_reason,
                primary_local_unit_id=primary_local_unit.unit_id,
                primary_node_id=primary_node_id,
                required_node_id=required_node_id,
                required_node_source=required_node_source,
                consistency_level=consistency_level,
                support_level=support_level,
                decision_reason=decision_reason,
                score=score,
                road_geometry=road_geometry,
                node_geometry=node_geometry,
                geometry=geometry,
                role_assignments=role_assignments,
            )
        )
    aggregated_units.sort(key=lambda unit: unit.score, reverse=True)
    return tuple(aggregated_units)


def resolve_positive_rcsd_selection(
    *,
    event_unit_id: str,
    operational_kind_hint: int | None,
    representative_node: ParsedNode,
    selected_evidence_region_geometry: BaseGeometry | None,
    fact_reference_point: BaseGeometry | None,
    pair_local_region_geometry: BaseGeometry | None,
    pair_local_middle_geometry: BaseGeometry | None,
    scoped_rcsd_roads: Sequence[ParsedRoad],
    scoped_rcsd_nodes: Sequence[ParsedNode],
    pair_local_scope_rcsd_roads: Sequence[ParsedRoad],
    pair_local_scope_rcsd_nodes: Sequence[ParsedNode],
    scoped_roads: Sequence[ParsedRoad],
    boundary_branch_ids: Sequence[str],
    preferred_axis_branch_id: str | None,
    scoped_input_branch_ids: Sequence[str],
    scoped_output_branch_ids: Sequence[str],
    branch_road_memberships: dict[str, Sequence[str]],
    axis_vector: tuple[float, float] | None,
) -> PositiveRcsdSelectionDecision:
    representative_point = _as_point(getattr(representative_node, "geometry", None))
    reference_point = _as_point(fact_reference_point)
    if representative_point is None:
        raise ValueError("representative_node.geometry is required for RCSD selection")

    event_type = _operational_event_type(operational_kind_hint)
    pair_local_seed_node_ids = {
        node_id
        for node in pair_local_scope_rcsd_nodes
        if (node_id := _safe_id(getattr(node, "node_id", None))) is not None
    }
    raw_roads_by_id = _road_lookup(pair_local_scope_rcsd_roads)
    if pair_local_seed_node_ids:
        for road in scoped_rcsd_roads:
            road_id = _safe_id(getattr(road, "road_id", None))
            if road_id is None or road_id in raw_roads_by_id:
                continue
            if { _safe_id(getattr(road, "snodeid", None)), _safe_id(getattr(road, "enodeid", None)) } & pair_local_seed_node_ids:
                raw_roads_by_id[road_id] = road
    raw_road_endpoint_node_ids = _node_ids_for_roads(raw_roads_by_id.keys(), raw_roads_by_id)
    raw_node_features: list[ParsedNode] = []
    seen_raw_node_ids: set[str] = set()
    for node in (*pair_local_scope_rcsd_nodes, *scoped_rcsd_nodes):
        node_id = _safe_id(getattr(node, "node_id", None))
        if node_id is None or node_id in seen_raw_node_ids:
            continue
        if node in pair_local_scope_rcsd_nodes or node_id in raw_road_endpoint_node_ids:
            raw_node_features.append(node)
            seen_raw_node_ids.add(node_id)
    actual_rcsd_node_ids = {
        node_id
        for node in raw_node_features
        if (node_id := _safe_id(getattr(node, "node_id", None))) is not None
    }
    raw_nodes_by_id = _node_lookup(raw_node_features, roads=raw_roads_by_id.values())
    raw_rcsd_road_ids = tuple(sorted(raw_roads_by_id))
    raw_rcsd_node_ids = tuple(sorted(actual_rcsd_node_ids))
    pair_local_rcsd_empty = not raw_rcsd_road_ids and not raw_rcsd_node_ids
    candidate_scope_geometry = _build_candidate_scope_geometry(
        representative_point=representative_point,
        fact_reference_point=reference_point,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        pair_local_region_geometry=pair_local_region_geometry,
    )
    if pair_local_rcsd_empty:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="pair_local_rcsd_empty",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=True,
            pair_local_rcsd_road_ids=raw_rcsd_road_ids,
            pair_local_rcsd_node_ids=raw_rcsd_node_ids,
            first_hit_rcsdroad_ids=(),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="pair_local_empty",
            rcsd_decision_reason="pair_local_rcsd_empty",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=None,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": True,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": list(raw_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(raw_rcsd_node_ids),
                "candidate_scope_rcsdroad_ids": [],
                "candidate_scope_rcsdnode_ids": [],
                "first_hit_rcsdroad_ids": [],
                "local_rcsd_units": [],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "pair_local_rcsd_empty",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": {},
                "rcsd_decision_reason": "pair_local_rcsd_empty",
            },
        )

    axis_vector_tuple = None if axis_vector is None else (float(axis_vector[0]), float(axis_vector[1]))
    normal_vector = _normal_vector(axis_vector_tuple)
    expected_role_map = _expected_swsd_role_map(
        event_type=event_type,
        boundary_branch_ids=boundary_branch_ids,
        scoped_input_branch_ids=scoped_input_branch_ids,
        scoped_output_branch_ids=scoped_output_branch_ids,
        preferred_axis_branch_id=preferred_axis_branch_id,
        branch_road_memberships=branch_road_memberships,
        scoped_roads=scoped_roads,
        representative_point=representative_point,
        normal_vector=normal_vector,
    )

    raw_roads = list(raw_roads_by_id.values())
    roads_by_id = raw_roads_by_id
    node_points_by_id = dict(raw_nodes_by_id)
    first_hit_road_ids, _hit_points, first_hit_geometry = _first_hit_roads(
        roads=raw_roads,
        fact_reference_point=reference_point,
        axis_vector=axis_vector_tuple,
    )

    candidate_scope_road_ids = {
        road_id
        for road_id, road in roads_by_id.items()
        if _road_enters_candidate_scope(
            road,
            candidate_scope_geometry=candidate_scope_geometry,
            selected_evidence_region_geometry=selected_evidence_region_geometry,
            fact_reference_point=reference_point,
        )
    }
    candidate_scope_road_ids.update(first_hit_road_ids)
    roads_by_node_id = _roads_by_node(raw_roads)
    candidate_node_ids = _node_ids_for_roads(candidate_scope_road_ids or first_hit_road_ids, roads_by_id) & set(actual_rcsd_node_ids)
    if candidate_scope_geometry is not None:
        for node_id, geometry in node_points_by_id.items():
            if node_id not in actual_rcsd_node_ids:
                continue
            if candidate_scope_geometry.buffer(1e-6).covers(geometry):
                candidate_node_ids.add(node_id)
    pair_local_rcsd_road_ids = tuple(sorted(candidate_scope_road_ids))
    pair_local_rcsd_node_ids = tuple(sorted(candidate_node_ids))
    pair_local_rcsd_empty = not pair_local_rcsd_road_ids and not pair_local_rcsd_node_ids
    if pair_local_rcsd_empty:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="candidate_scope_empty",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=True,
            pair_local_rcsd_road_ids=(),
            pair_local_rcsd_node_ids=(),
            first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="pair_local_empty",
            rcsd_decision_reason="pair_local_rcsd_empty",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=first_hit_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": True,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": [],
                "pair_local_rcsd_node_ids": [],
                "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
                "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(first_hit_road_ids),
                "local_rcsd_units": [],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "candidate_scope_empty",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": expected_role_map,
                "rcsd_decision_reason": "pair_local_rcsd_empty",
            },
        )
    discussion_road_ids = set(candidate_scope_road_ids)
    for node_id in tuple(candidate_node_ids):
        discussion_road_ids.update(roads_by_node_id.get(node_id, set()))

    local_units: list[_LocalRcsdUnit] = []
    for node_id in sorted(candidate_node_ids):
        attached_road_ids = [
            road_id
            for road_id in sorted(roads_by_node_id.get(node_id, set()))
            if road_id in roads_by_id and (
                road_id in discussion_road_ids or road_id in set(first_hit_road_ids)
            )
        ]
        if len(attached_road_ids) < 2:
            continue
        unit = _unit_from_roads_and_node(
            unit_id=f"{event_unit_id}:node:{node_id}",
            unit_kind="node_centric",
            node_id=node_id,
            road_ids=attached_road_ids,
            roads_by_id=roads_by_id,
            node_points_by_id=node_points_by_id,
            actual_node_ids=set(actual_rcsd_node_ids),
            expected_role_map=expected_role_map,
            representative_point=representative_point,
            axis_vector=axis_vector_tuple,
            normal_vector=normal_vector,
            first_hit_road_ids=set(first_hit_road_ids),
        )
        local_units.append(unit)

    road_only_road_ids = tuple(sorted(discussion_road_ids or set(first_hit_road_ids)))
    if road_only_road_ids:
        local_units.append(
            _unit_from_roads_and_node(
                unit_id=f"{event_unit_id}:road_only:01",
                unit_kind="road_only",
                node_id=None,
                road_ids=road_only_road_ids,
                roads_by_id=roads_by_id,
                node_points_by_id=node_points_by_id,
                actual_node_ids=set(actual_rcsd_node_ids),
                expected_role_map=expected_role_map,
                representative_point=representative_point,
                axis_vector=axis_vector_tuple,
                normal_vector=normal_vector,
                first_hit_road_ids=set(first_hit_road_ids),
            )
        )

    if not local_units:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="local_rcsd_unit_not_constructed",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=False,
            pair_local_rcsd_road_ids=pair_local_rcsd_road_ids,
            pair_local_rcsd_node_ids=pair_local_rcsd_node_ids,
            first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="no_local_unit",
            rcsd_decision_reason="pair_local_rcsd_unit_not_constructed",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=first_hit_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": False,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": list(pair_local_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(pair_local_rcsd_node_ids),
                "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
                "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(first_hit_road_ids),
                "local_rcsd_units": [],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "local_rcsd_unit_not_constructed",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": expected_role_map,
                "rcsd_decision_reason": "pair_local_rcsd_unit_not_constructed",
            },
        )

    local_units.sort(key=lambda unit: unit.score, reverse=True)
    aggregated_units = _build_aggregated_rcsd_units(
        event_unit_id=event_unit_id,
        local_units=local_units,
        expected_role_map=expected_role_map,
        first_hit_road_ids=tuple(first_hit_road_ids),
        roads_by_id=roads_by_id,
        roads_by_node_id=roads_by_node_id,
        node_points_by_id=node_points_by_id,
        representative_point=representative_point,
    )
    if not aggregated_units:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="positive_rcsd_absent_after_local_units",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=False,
            pair_local_rcsd_road_ids=pair_local_rcsd_road_ids,
            pair_local_rcsd_node_ids=pair_local_rcsd_node_ids,
            first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="no_positive_present",
            rcsd_decision_reason="positive_rcsd_absent_after_local_units",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=first_hit_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": False,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": list(pair_local_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(pair_local_rcsd_node_ids),
                "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
                "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(first_hit_road_ids),
                "local_rcsd_units": [unit.to_doc() for unit in local_units],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "positive_rcsd_absent_after_local_units",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": expected_role_map,
                "rcsd_decision_reason": "positive_rcsd_absent_after_local_units",
            },
        )

    selected_aggregated = aggregated_units[0]
    selected_local_unit = next(
        (
            unit
            for unit in local_units
            if unit.unit_id == selected_aggregated.primary_local_unit_id
        ),
        local_units[0],
    )
    selected_road_ids = set(selected_aggregated.road_ids)
    if selected_aggregated.required_node_id is not None and first_hit_road_ids:
        for road_id in first_hit_road_ids:
            traced = _trace_path_to_node(
                start_road_id=road_id,
                target_node_id=selected_aggregated.required_node_id,
                roads_by_id=roads_by_id,
                roads_by_node_id=roads_by_node_id,
            )
            selected_road_ids.update(traced)
    selected_rcsd_roads = tuple(sorted(selected_road_ids))
    selected_rcsd_nodes = tuple(sorted({*selected_aggregated.node_ids} - {None}))
    selected_road_geometry = _union_geometry(
        roads_by_id[road_id].geometry
        for road_id in selected_rcsd_roads
        if road_id in roads_by_id
    )
    selected_node_geometry = _union_geometry(
        node_points_by_id[node_id]
        for node_id in selected_rcsd_nodes
        if node_id in node_points_by_id
    )
    selected_geometry = _union_geometry([selected_road_geometry, selected_node_geometry])
    primary_main_rc_node_id = selected_aggregated.primary_node_id
    primary_main_rc_node_geometry = None
    if primary_main_rc_node_id is not None and primary_main_rc_node_id in node_points_by_id:
        primary_main_rc_node_geometry = node_points_by_id[primary_main_rc_node_id]
    required_rcsd_node = selected_aggregated.required_node_id
    required_rcsd_node_geometry = None
    if required_rcsd_node is not None and required_rcsd_node in node_points_by_id:
        required_rcsd_node_geometry = node_points_by_id[required_rcsd_node]
    if selected_aggregated.consistency_level == "A":
        consistency_result = "positive_rcsd_strong_consistent"
    elif selected_aggregated.consistency_level == "B":
        consistency_result = "positive_rcsd_partial_consistent"
    else:
        consistency_result = "missing_positive_rcsd"
    selection_mode = "aggregated"
    if selected_local_unit.unit_kind:
        selection_mode = f"aggregated_{selected_local_unit.unit_kind}"
    if first_hit_road_ids:
        selection_mode = f"{selection_mode}_from_first_hit"
    return PositiveRcsdSelectionDecision(
        selected_rcsdroad_ids=selected_rcsd_roads,
        selected_rcsdnode_ids=selected_rcsd_nodes,
        primary_main_rc_node_id=primary_main_rc_node_id,
        positive_rcsd_present=selected_aggregated.positive_rcsd_present,
        positive_rcsd_present_reason=selected_aggregated.positive_rcsd_present_reason,
        positive_rcsd_support_level=selected_aggregated.support_level,
        positive_rcsd_consistency_level=selected_aggregated.consistency_level,
        rcsd_consistency_result=consistency_result,
        required_rcsd_node=required_rcsd_node,
        required_rcsd_node_source=selected_aggregated.required_node_source,
        pair_local_rcsd_empty=False,
        pair_local_rcsd_road_ids=pair_local_rcsd_road_ids,
        pair_local_rcsd_node_ids=pair_local_rcsd_node_ids,
        first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
        local_rcsd_unit_id=selected_local_unit.unit_id,
        local_rcsd_unit_kind=selected_local_unit.unit_kind,
        aggregated_rcsd_unit_id=selected_aggregated.unit_id,
        aggregated_rcsd_unit_ids=selected_aggregated.member_unit_ids,
        axis_polarity_inverted=selected_aggregated.axis_polarity_inverted,
        rcsd_selection_mode=selection_mode,
        rcsd_decision_reason=selected_aggregated.decision_reason,
        positive_rcsd_geometry=selected_geometry,
        positive_rcsd_road_geometry=selected_road_geometry,
        positive_rcsd_node_geometry=selected_node_geometry,
        primary_main_rc_node_geometry=primary_main_rc_node_geometry,
        required_rcsd_node_geometry=required_rcsd_node_geometry,
        pair_local_rcsd_scope_geometry=candidate_scope_geometry,
        first_hit_rcsd_road_geometry=first_hit_geometry,
        local_rcsd_unit_geometry=selected_local_unit.geometry,
        positive_rcsd_audit={
            "pair_local_rcsd_empty": False,
            "operational_event_type": event_type,
            "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
            "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
            "pair_local_rcsd_road_ids": list(pair_local_rcsd_road_ids),
            "pair_local_rcsd_node_ids": list(pair_local_rcsd_node_ids),
            "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
            "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
            "first_hit_rcsdroad_ids": list(first_hit_road_ids),
            "local_rcsd_unit_id": selected_local_unit.unit_id,
            "local_rcsd_unit_kind": selected_local_unit.unit_kind,
            "aggregated_rcsd_unit_id": selected_aggregated.unit_id,
            "aggregated_rcsd_unit_ids": list(selected_aggregated.member_unit_ids),
            "rcsd_selection_mode": selection_mode,
            "positive_rcsd_present": selected_aggregated.positive_rcsd_present,
            "positive_rcsd_present_reason": selected_aggregated.positive_rcsd_present_reason,
            "axis_polarity_inverted": selected_aggregated.axis_polarity_inverted,
            "required_rcsd_node_source": selected_aggregated.required_node_source,
            "rcsd_decision_reason": selected_aggregated.decision_reason,
            "rcsd_role_map": expected_role_map,
            "selected_unit_role_assignments": list(selected_local_unit.role_assignments),
            "local_rcsd_units": [unit.to_doc() for unit in local_units],
            "aggregated_rcsd_units": [unit.to_doc() for unit in aggregated_units],
        },
    )
