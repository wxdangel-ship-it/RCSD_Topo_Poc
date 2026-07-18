from __future__ import annotations

from typing import Any

from shapely.ops import substring

from rcsd_topo_poc.utils.field_names import (
    get_case_insensitive_property,
    resolve_case_insensitive_field_name,
)

from .phase2_models import RoadSplitResult, SplitPoint
from .phase2_node_grouping import generated_node_kind


def split_roads(
    *,
    target_id: str,
    split_points_by_road: dict[int, list[SplitPoint]],
    roads_by_id: dict[int, dict[str, Any]],
    next_road_id: int,
    next_node_id: int,
    swsd_properties: dict[str, Any],
    rcsdnode_template: dict[str, Any],
    min_split_gap_m: float,
    min_endpoint_gap_m: float,
) -> tuple[RoadSplitResult, int, int]:
    new_roads: list[dict[str, Any]] = []
    new_nodes: list[dict[str, Any]] = []
    original_road_ids: list[int] = []
    new_road_ids_by_original_road_id: dict[int, list[int]] = {}
    skipped: list[str] = []
    for road_id in sorted(split_points_by_road):
        road_feature = roads_by_id.get(road_id)
        if road_feature is None:
            skipped.append(f"missing_road:{road_id}")
            continue
        line = road_feature.get("geometry")
        if line is None or line.is_empty or line.length <= 0:
            skipped.append(f"invalid_road_geometry:{road_id}")
            continue
        distances = _normalized_distances(
            [point.distance_m for point in split_points_by_road[road_id]],
            line.length,
            min_split_gap_m=min_split_gap_m,
            min_endpoint_gap_m=min_endpoint_gap_m,
        )
        if not distances:
            skipped.append(f"no_valid_split_point:{road_id}")
            continue
        split_node_ids: list[int] = []
        for distance in distances:
            split_node_ids.append(next_node_id)
            new_nodes.append(
                _new_node_feature(
                    node_id=next_node_id,
                    target_id=target_id,
                    geometry=line.interpolate(distance),
                    swsd_properties=swsd_properties,
                    template=rcsdnode_template,
                )
            )
            next_node_id += 1
        segment_boundaries = [0.0, *distances, float(line.length)]
        node_boundaries = [
            _property_value(road_feature["properties"], "snodeid"),
            *split_node_ids,
            _property_value(road_feature["properties"], "enodeid"),
        ]
        new_road_ids_for_source: list[int] = []
        for index in range(len(segment_boundaries) - 1):
            start_m = segment_boundaries[index]
            end_m = segment_boundaries[index + 1]
            if end_m - start_m <= 1e-9:
                continue
            segment = substring(line, start_m, end_m)
            if segment is None or segment.is_empty or getattr(segment, "geom_type", "") != "LineString":
                skipped.append(f"invalid_split_segment:{road_id}:{index}")
                continue
            new_roads.append(
                _new_road_feature(
                    road_feature=road_feature,
                    road_id=next_road_id,
                    snodeid=node_boundaries[index],
                    enodeid=node_boundaries[index + 1],
                    geometry=segment,
                )
            )
            new_road_ids_for_source.append(next_road_id)
            next_road_id += 1
        original_road_ids.append(road_id)
        new_road_ids_by_original_road_id[road_id] = new_road_ids_for_source
    return (
        RoadSplitResult(
            new_road_features=new_roads,
            new_node_features=new_nodes,
            original_road_ids=original_road_ids,
            skipped_reasons=skipped,
            new_road_ids_by_original_road_id=new_road_ids_by_original_road_id,
        ),
        next_road_id,
        next_node_id,
    )


def _normalized_distances(
    distances: list[float],
    line_length: float,
    *,
    min_split_gap_m: float,
    min_endpoint_gap_m: float,
) -> list[float]:
    selected: list[float] = []
    for distance in sorted(distances):
        if distance <= min_endpoint_gap_m or line_length - distance <= min_endpoint_gap_m:
            continue
        if selected and abs(distance - selected[-1]) < min_split_gap_m:
            selected[-1] = (selected[-1] + distance) / 2.0
            continue
        selected.append(distance)
    return selected


def _new_node_feature(
    *,
    node_id: int,
    target_id: str,
    geometry,
    swsd_properties: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    props = {key: None for key in template.keys()}
    props[_field_name(props, "id")] = node_id
    props[_field_name(props, "mainnodeid")] = None
    props[_field_name(props, "target_id")] = target_id
    kind_value, kind_source = generated_node_kind(swsd_properties)
    if resolve_case_insensitive_field_name(template, "kind") is not None or kind_value is not None:
        props[_field_name(props, "kind")] = kind_value
    props[_field_name(props, "kind_source")] = kind_source
    return {"properties": props, "geometry": geometry}


def _new_road_feature(
    *,
    road_feature: dict[str, Any],
    road_id: int,
    snodeid: Any,
    enodeid: Any,
    geometry,
) -> dict[str, Any]:
    props = dict(road_feature.get("properties") or {})
    props[_field_name(props, "id")] = road_id
    props[_field_name(props, "snodeid")] = snodeid
    props[_field_name(props, "enodeid")] = enodeid
    return {"properties": props, "geometry": geometry}


def _property_value(properties: dict[str, Any], target: str) -> Any:
    return get_case_insensitive_property(properties, target)


def _field_name(properties: dict[str, Any], target: str) -> str:
    return resolve_case_insensitive_field_name(properties, target) or target
