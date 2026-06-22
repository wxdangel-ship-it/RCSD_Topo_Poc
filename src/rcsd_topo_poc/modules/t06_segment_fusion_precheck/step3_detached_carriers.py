from __future__ import annotations

from typing import Any

from .parsing import ParseError, normalize_id, unique_preserve_order


def retain_detached_junc_swsd_roads(units: list[Any], swsd_road_by_id: dict[str, dict[str, Any]]) -> None:
    for unit in units:
        if not unit.detached_junc_nodes:
            continue
        detached = set(unit.detached_junc_nodes)
        retained: list[str] = []
        for road_id in unit.swsd_road_ids:
            road = swsd_road_by_id.get(road_id)
            if road is not None and detached.intersection(_road_endpoint_node_ids(road)):
                retained.append(road_id)
        unit.retained_detached_swsd_road_ids = unique_preserve_order(retained)
        unit.swsd_road_ids = [road_id for road_id in unit.swsd_road_ids if road_id not in retained]


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return unique_preserve_order(result)
