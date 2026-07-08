from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import acos, degrees, hypot, isfinite
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    MainnodeGroup,
    RoadFeatureRecord,
    _allocate_unique_segmentid,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _coerce_int, _sort_key
from rcsd_topo_poc.modules.t01_data_preprocess.step2_geometry_utils import geometry_coords
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    get_road_segmentid,
    get_road_sgrade,
    is_allowed_road_kind,
    set_road_segmentid,
    set_road_sgrade,
)


SHAPE_CONTROL_BUILD_SOURCE = "segment_shape_control_split"
SIDE_ATTACHMENT_MERGE_BUILD_SOURCE = "side_attachment_merge"
SHAPE_CONTROL_TURN_THRESHOLD_DEG = 60.0
SHAPE_CONTROL_JUNCTION_KIND_2 = frozenset({4, 64, 128, 2048})
SHAPE_CONTROL_CLOSED_CON_VALUES = frozenset({2, 3})


@dataclass(frozen=True)
class _SegmentEdge:
    road_id: str
    a_node_id: str
    b_node_id: str


class _DisjointSet:
    def __init__(self, values: list[str]) -> None:
        self._parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self._parent[value]
        if parent != value:
            self._parent[value] = self.find(parent)
        return self._parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if _sort_key(right_root) < _sort_key(left_root):
            left_root, right_root = right_root, left_root
        self._parent[right_root] = left_root


def _parse_segment_pair_nodes(segmentid: str) -> Optional[tuple[str, str]]:
    parts = [part.strip() for part in segmentid.split("_")]
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    if len(parts) == 3 and parts[0] and parts[1] and parts[2].isdigit():
        return parts[0], parts[1]
    return None


def _is_dual_sgrade(sgrade: Optional[str]) -> bool:
    return bool(sgrade and sgrade.endswith("双"))


def _road_semantic_endpoints(
    road: RoadFeatureRecord,
    physical_to_semantic: dict[str, str],
) -> Optional[tuple[str, str]]:
    a_node_id = physical_to_semantic.get(road.snodeid)
    b_node_id = physical_to_semantic.get(road.enodeid)
    if a_node_id is None or b_node_id is None or a_node_id == b_node_id:
        return None
    return a_node_id, b_node_id


def _node_props(
    semantic_node_id: str,
    *,
    mainnode_groups: dict[str, MainnodeGroup],
    node_properties_map: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    group = mainnode_groups.get(semantic_node_id)
    if group is None:
        return node_properties_map.get(semantic_node_id)
    for node_id in (group.representative_node_id, *group.member_node_ids):
        props = node_properties_map.get(node_id)
        if props is not None:
            return props
    return None


def _is_shape_control_junction(
    semantic_node_id: str,
    *,
    all_incident_road_count: int,
    mainnode_groups: dict[str, MainnodeGroup],
    node_properties_map: dict[str, dict[str, Any]],
) -> bool:
    if all_incident_road_count < 3:
        return False
    props = _node_props(
        semantic_node_id,
        mainnode_groups=mainnode_groups,
        node_properties_map=node_properties_map,
    )
    if props is None:
        return False
    kind_2 = _coerce_int(props.get("kind_2"))
    grade_2 = _coerce_int(props.get("grade_2"))
    closed_con = _coerce_int(props.get("closed_con"))
    return (
        kind_2 in SHAPE_CONTROL_JUNCTION_KIND_2
        and grade_2 is not None
        and grade_2 >= 1
        and closed_con in SHAPE_CONTROL_CLOSED_CON_VALUES
    )


def _normalize_kind_token(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value:04d}"
    if isinstance(value, float):
        if not isfinite(value):
            return None
        if value.is_integer():
            return f"{int(value):04d}"
        return str(value).strip()

    token = str(value).strip()
    if not token:
        return None
    if token.endswith(".0") and token[:-2].isdigit():
        token = token[:-2]
    if token.isdigit() and len(token) < 4:
        token = token.zfill(4)
    return token


def _road_kind_levels(road: RoadFeatureRecord, properties: dict[str, Any]) -> tuple[str, ...]:
    raw_kind = properties.get("kind", road.properties.get("kind"))
    if raw_kind is None:
        return ()
    values = raw_kind if isinstance(raw_kind, (list, tuple, set)) else str(raw_kind).split("|")
    levels: list[str] = []
    for value in values:
        token = _normalize_kind_token(value)
        if token is None or len(token) < 2:
            continue
        levels.append(token[:2])
    return tuple(dict.fromkeys(levels))


def _best_kind_level(road: RoadFeatureRecord, properties: dict[str, Any]) -> Optional[str]:
    levels = _road_kind_levels(road, properties)
    if not levels:
        return None
    return sorted(levels)[0]


def _vector_away_from_node(
    road: RoadFeatureRecord,
    *,
    semantic_node_id: str,
    physical_to_semantic: dict[str, str],
) -> Optional[tuple[float, float]]:
    coords = geometry_coords(road.geometry)
    if len(coords) < 2:
        return None
    snode_semantic = physical_to_semantic.get(road.snodeid)
    enode_semantic = physical_to_semantic.get(road.enodeid)
    if snode_semantic == semantic_node_id and enode_semantic != semantic_node_id:
        return coords[1][0] - coords[0][0], coords[1][1] - coords[0][1]
    if enode_semantic == semantic_node_id and snode_semantic != semantic_node_id:
        return coords[-2][0] - coords[-1][0], coords[-2][1] - coords[-1][1]
    return None


def _angle_between_vectors_deg(
    left: tuple[float, float],
    right: tuple[float, float],
) -> Optional[float]:
    left_len = hypot(left[0], left[1])
    right_len = hypot(right[0], right[1])
    if left_len <= 0.0 or right_len <= 0.0:
        return None
    dot = max(-1.0, min(1.0, ((left[0] * right[0]) + (left[1] * right[1])) / (left_len * right_len)))
    return degrees(acos(dot))


def _turn_angle_at_node_deg(
    left_road: RoadFeatureRecord,
    right_road: RoadFeatureRecord,
    *,
    semantic_node_id: str,
    physical_to_semantic: dict[str, str],
) -> Optional[float]:
    left_vector = _vector_away_from_node(
        left_road,
        semantic_node_id=semantic_node_id,
        physical_to_semantic=physical_to_semantic,
    )
    right_vector = _vector_away_from_node(
        right_road,
        semantic_node_id=semantic_node_id,
        physical_to_semantic=physical_to_semantic,
    )
    if left_vector is None or right_vector is None:
        return None
    away_angle = _angle_between_vectors_deg(left_vector, right_vector)
    if away_angle is None:
        return None
    return 180.0 - away_angle


def _format_reason(reason_flags: list[str]) -> str:
    return "+".join(sorted(dict.fromkeys(reason_flags)))


def _cut_info_for_node(
    semantic_node_id: str,
    *,
    source_segment_road_count: int,
    incident_road_ids: list[str],
    all_incident_road_count: int,
    road_by_id: dict[str, RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
    physical_to_semantic: dict[str, str],
    mainnode_groups: dict[str, MainnodeGroup],
    node_properties_map: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not _is_shape_control_junction(
        semantic_node_id,
        all_incident_road_count=all_incident_road_count,
        mainnode_groups=mainnode_groups,
        node_properties_map=node_properties_map,
    ):
        return None

    sorted_incident = sorted(set(incident_road_ids), key=_sort_key)
    if any(
        road_properties_map[road_id].get("segment_build_source") == SIDE_ATTACHMENT_MERGE_BUILD_SOURCE
        for road_id in sorted_incident
    ):
        return None

    reason_flags: list[str] = []
    turn_angle_deg: Optional[float] = None
    best_kind_levels: list[str] = []
    if len(sorted_incident) == 2:
        left_road = road_by_id[sorted_incident[0]]
        right_road = road_by_id[sorted_incident[1]]
        turn_angle_deg = _turn_angle_at_node_deg(
            left_road,
            right_road,
            semantic_node_id=semantic_node_id,
            physical_to_semantic=physical_to_semantic,
        )
        if turn_angle_deg is not None and turn_angle_deg > SHAPE_CONTROL_TURN_THRESHOLD_DEG:
            reason_flags.append("internal_turn_angle_conflict")

        left_level = _best_kind_level(left_road, road_properties_map[sorted_incident[0]])
        right_level = _best_kind_level(right_road, road_properties_map[sorted_incident[1]])
        best_kind_levels = [level for level in (left_level, right_level) if level is not None]
        if (
            source_segment_road_count == 2
            and left_level is not None
            and right_level is not None
            and left_level != right_level
        ):
            reason_flags.append("internal_road_kind_level_conflict")
    if not reason_flags:
        return None

    props = _node_props(
        semantic_node_id,
        mainnode_groups=mainnode_groups,
        node_properties_map=node_properties_map,
    ) or {}
    return {
        "node_id": semantic_node_id,
        "reason": _format_reason(reason_flags),
        "source_segment_road_count": source_segment_road_count,
        "turn_angle_deg": None if turn_angle_deg is None else round(turn_angle_deg, 6),
        "threshold_deg": SHAPE_CONTROL_TURN_THRESHOLD_DEG,
        "segment_incident_road_ids": sorted_incident,
        "segment_incident_road_count": len(sorted_incident),
        "all_incident_road_count": all_incident_road_count,
        "best_kind_levels": best_kind_levels,
        "node_grade_2": _coerce_int(props.get("grade_2")),
        "node_kind_2": _coerce_int(props.get("kind_2")),
        "node_closed_con": _coerce_int(props.get("closed_con")),
    }


def _component_road_sets(
    road_ids: list[str],
    *,
    edges: dict[str, _SegmentEdge],
    cut_node_ids: set[str],
) -> list[list[str]]:
    disjoint = _DisjointSet(road_ids)
    roads_by_node: dict[str, list[str]] = defaultdict(list)
    for road_id in road_ids:
        edge = edges[road_id]
        roads_by_node[edge.a_node_id].append(road_id)
        roads_by_node[edge.b_node_id].append(road_id)

    for node_id, node_road_ids in roads_by_node.items():
        if node_id in cut_node_ids:
            continue
        if len(node_road_ids) < 2:
            continue
        first = node_road_ids[0]
        for road_id in node_road_ids[1:]:
            disjoint.union(first, road_id)

    grouped: dict[str, list[str]] = defaultdict(list)
    for road_id in road_ids:
        grouped[disjoint.find(road_id)].append(road_id)
    return [sorted(values, key=_sort_key) for _, values in sorted(grouped.items(), key=lambda item: _sort_key(item[0]))]


def _component_endpoint_pair(
    component_road_ids: list[str],
    *,
    edges: dict[str, _SegmentEdge],
    cut_node_ids: set[str],
    original_pair_nodes: tuple[str, str],
) -> Optional[tuple[str, str]]:
    degree: Counter[str] = Counter()
    for road_id in component_road_ids:
        edge = edges[road_id]
        degree[edge.a_node_id] += 1
        degree[edge.b_node_id] += 1

    endpoint_candidates: list[str] = []
    for node_id in original_pair_nodes:
        if degree.get(node_id, 0) > 0:
            endpoint_candidates.append(node_id)
    for node_id in sorted(cut_node_ids, key=_sort_key):
        if degree.get(node_id, 0) > 0:
            endpoint_candidates.append(node_id)
    for node_id, count in sorted(degree.items(), key=lambda item: _sort_key(item[0])):
        if count == 1:
            endpoint_candidates.append(node_id)

    deduped = list(dict.fromkeys(endpoint_candidates))
    if len(deduped) < 2:
        deduped = [node_id for node_id, _ in sorted(degree.items(), key=lambda item: _sort_key(item[0]))]
    if len(deduped) < 2:
        return None
    a_node_id, b_node_id = deduped[0], deduped[1]
    if a_node_id == b_node_id:
        return None
    return a_node_id, b_node_id


def _build_all_incident_counts(
    *,
    roads: list[RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
    physical_to_semantic: dict[str, str],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for road in roads:
        props = road_properties_map.get(road.road_id, road.properties)
        road_kind = _coerce_int(props.get("road_kind")) if "road_kind" in props else road.road_kind
        if not is_allowed_road_kind(road_kind):
            continue
        endpoints = _road_semantic_endpoints(road, physical_to_semantic)
        if endpoints is None:
            continue
        counts[endpoints[0]] += 1
        counts[endpoints[1]] += 1
    return counts


def apply_segment_shape_control(
    *,
    nodes: list[Any],
    roads: list[RoadFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    road_properties_map: dict[str, dict[str, Any]],
    mainnode_groups: dict[str, MainnodeGroup],
    physical_to_semantic: dict[str, str],
    used_segmentids: set[str],
) -> dict[str, Any]:
    road_by_id = {road.road_id: road for road in roads}
    segment_roads: dict[str, list[str]] = defaultdict(list)
    skipped_reason_counts: Counter[str] = Counter()
    for road in roads:
        props = road_properties_map.get(road.road_id)
        if props is None:
            continue
        segmentid = get_road_segmentid(props)
        if segmentid is None:
            continue
        if not _is_dual_sgrade(get_road_sgrade(props)):
            continue
        segment_roads[segmentid].append(road.road_id)

    all_incident_counts = _build_all_incident_counts(
        roads=roads,
        road_properties_map=road_properties_map,
        physical_to_semantic=physical_to_semantic,
    )
    split_events: list[dict[str, Any]] = []
    split_road_ids: set[str] = set()
    split_reason_counts: Counter[str] = Counter()

    for segmentid, road_ids in sorted(segment_roads.items(), key=lambda item: _sort_key(item[0])):
        sorted_road_ids = sorted(set(road_ids), key=_sort_key)
        if len(sorted_road_ids) < 2:
            continue
        pair_nodes = _parse_segment_pair_nodes(segmentid)
        if pair_nodes is None:
            skipped_reason_counts["segmentid_not_pair_form"] += 1
            continue

        edges: dict[str, _SegmentEdge] = {}
        incident_in_segment: dict[str, list[str]] = defaultdict(list)
        missing_endpoint = False
        for road_id in sorted_road_ids:
            road = road_by_id.get(road_id)
            if road is None:
                missing_endpoint = True
                break
            endpoints = _road_semantic_endpoints(road, physical_to_semantic)
            if endpoints is None:
                missing_endpoint = True
                break
            edge = _SegmentEdge(road_id=road_id, a_node_id=endpoints[0], b_node_id=endpoints[1])
            edges[road_id] = edge
            incident_in_segment[edge.a_node_id].append(road_id)
            incident_in_segment[edge.b_node_id].append(road_id)
        if missing_endpoint:
            skipped_reason_counts["missing_semantic_endpoint"] += 1
            continue

        cut_info_by_node: dict[str, dict[str, Any]] = {}
        for node_id, incident_road_ids in incident_in_segment.items():
            if node_id in pair_nodes:
                continue
            cut_info = _cut_info_for_node(
                node_id,
                source_segment_road_count=len(sorted_road_ids),
                incident_road_ids=incident_road_ids,
                all_incident_road_count=all_incident_counts.get(node_id, 0),
                road_by_id=road_by_id,
                road_properties_map=road_properties_map,
                physical_to_semantic=physical_to_semantic,
                mainnode_groups=mainnode_groups,
                node_properties_map=node_properties_map,
            )
            if cut_info is not None:
                cut_info_by_node[node_id] = cut_info
        if not cut_info_by_node:
            continue

        components = _component_road_sets(
            sorted_road_ids,
            edges=edges,
            cut_node_ids=set(cut_info_by_node),
        )
        if len(components) < 2:
            skipped_reason_counts["cut_did_not_split_component"] += 1
            continue

        assigned_components: list[dict[str, Any]] = []
        for component_road_ids in components:
            endpoint_pair = _component_endpoint_pair(
                component_road_ids,
                edges=edges,
                cut_node_ids=set(cut_info_by_node),
                original_pair_nodes=pair_nodes,
            )
            if endpoint_pair is None:
                assigned_components = []
                skipped_reason_counts["component_endpoint_unresolved"] += 1
                break
            new_segmentid = _allocate_unique_segmentid(
                a_node_id=endpoint_pair[0],
                b_node_id=endpoint_pair[1],
                used_segmentids=used_segmentids,
                force_suffix=False,
            )
            assigned_components.append(
                {
                    "segmentid": new_segmentid,
                    "endpoint_pair": endpoint_pair,
                    "road_ids": component_road_ids,
                }
            )
        if not assigned_components:
            continue

        cut_node_ids = sorted(cut_info_by_node, key=_sort_key)
        reasons = sorted({cut_info_by_node[node_id]["reason"] for node_id in cut_node_ids})
        reason_text = ",".join(reasons)
        cut_node_text = ",".join(cut_node_ids)
        for component in assigned_components:
            for road_id in component["road_ids"]:
                props = road_properties_map[road_id]
                props.setdefault("pre_shape_control_segmentid", get_road_segmentid(props))
                props.setdefault("pre_shape_control_sgrade", get_road_sgrade(props))
                props.setdefault("pre_shape_control_segment_build_source", props.get("segment_build_source"))
                props["segment_build_source"] = SHAPE_CONTROL_BUILD_SOURCE
                props["shape_control_source_segmentid"] = segmentid
                props["shape_control_split_node_ids"] = cut_node_text
                props["shape_control_split_reason"] = reason_text
                set_road_segmentid(props, component["segmentid"])
                set_road_sgrade(props, get_road_sgrade(props))
                split_road_ids.add(road_id)

        for reason in reasons:
            split_reason_counts[reason] += 1
        split_events.append(
            {
                "source_segmentid": segmentid,
                "source_road_count": len(sorted_road_ids),
                "split_node_ids": cut_node_ids,
                "split_reasons": reasons,
                "cut_infos": [cut_info_by_node[node_id] for node_id in cut_node_ids],
                "component_count": len(assigned_components),
                "components": assigned_components,
            }
        )

    return {
        "scanned_segment_count": len(segment_roads),
        "split_segment_count": len(split_events),
        "split_component_count": sum(len(event["components"]) for event in split_events),
        "split_road_count": len(split_road_ids),
        "split_reason_counts": dict(sorted(split_reason_counts.items())),
        "skipped_reason_counts": dict(sorted(skipped_reason_counts.items())),
        "events": split_events,
        "node_count": len(nodes),
    }
