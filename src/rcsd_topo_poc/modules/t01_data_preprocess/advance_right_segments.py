from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import RoadFeatureRecord
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _coerce_int, _sort_key
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    get_road_segmentid,
    set_road_segmentid,
)


ADVANCE_RIGHT_FORMWAY_MASK = 128
ADVANCE_RIGHT_SEGMENT_TYPE = "advance_right"
NORMAL_SEGMENT_TYPE = "normal"
ADVANCE_RIGHT_BUILD_SOURCE = "advance_right_component"


@dataclass(frozen=True)
class AdvanceRightAssignmentSummary:
    segment_count: int
    road_count: int
    skipped_preassigned_road_count: int
    segment_to_road_ids: dict[str, tuple[str, ...]]


def is_advance_right_properties(properties: dict[str, Any]) -> bool:
    formway = _coerce_int(properties.get("formway")) or 0
    return bool(formway & ADVANCE_RIGHT_FORMWAY_MASK)


def _connected_components(roads: list[RoadFeatureRecord]) -> list[tuple[str, ...]]:
    road_by_id = {road.road_id: road for road in roads}
    road_ids_by_node: dict[str, set[str]] = defaultdict(set)
    for road in roads:
        road_ids_by_node[road.snodeid].add(road.road_id)
        road_ids_by_node[road.enodeid].add(road.road_id)

    remaining = set(road_by_id)
    components: list[tuple[str, ...]] = []
    while remaining:
        seed = min(remaining, key=_sort_key)
        stack = [seed]
        component: set[str] = set()
        while stack:
            road_id = stack.pop()
            if road_id in component:
                continue
            component.add(road_id)
            road = road_by_id[road_id]
            for node_id in (road.snodeid, road.enodeid):
                stack.extend(road_ids_by_node[node_id] - component)
        remaining.difference_update(component)
        components.append(tuple(sorted(component, key=_sort_key)))
    return sorted(components, key=lambda values: tuple(_sort_key(value) for value in values))


def _component_segment_id(road_ids: tuple[str, ...]) -> str:
    digest = sha1("\x1f".join(road_ids).encode("utf-8")).hexdigest()[:16]
    return f"advance_right_{digest}"


def assign_advance_right_segments(
    *,
    roads: list[RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
) -> AdvanceRightAssignmentSummary:
    eligible_roads: list[RoadFeatureRecord] = []
    skipped_preassigned_road_count = 0
    for road in roads:
        properties = road_properties_map[road.road_id]
        if not is_advance_right_properties(properties):
            continue
        existing_segment_id = get_road_segmentid(properties)
        existing_segment_type = str(properties.get("segment_type") or "").strip()
        if existing_segment_id and existing_segment_type != ADVANCE_RIGHT_SEGMENT_TYPE:
            skipped_preassigned_road_count += 1
            continue
        eligible_roads.append(road)

    segment_to_road_ids: dict[str, tuple[str, ...]] = {}
    for road_ids in _connected_components(eligible_roads):
        segment_id = _component_segment_id(road_ids)
        segment_to_road_ids[segment_id] = road_ids
        for road_id in road_ids:
            properties = road_properties_map[road_id]
            set_road_segmentid(properties, segment_id)
            properties["segment_type"] = ADVANCE_RIGHT_SEGMENT_TYPE
            properties["segment_build_source"] = ADVANCE_RIGHT_BUILD_SOURCE

    return AdvanceRightAssignmentSummary(
        segment_count=len(segment_to_road_ids),
        road_count=sum(len(road_ids) for road_ids in segment_to_road_ids.values()),
        skipped_preassigned_road_count=skipped_preassigned_road_count,
        segment_to_road_ids=segment_to_road_ids,
    )
