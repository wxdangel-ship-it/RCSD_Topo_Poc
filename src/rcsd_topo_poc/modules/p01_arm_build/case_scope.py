from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
from shapely.geometry import shape

from rcsd_topo_poc.modules.p01_arm_build.io import (
    _first_present,
    _layer_info,
    _normalise_properties,
    normalise_id,
)
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput, LoadedDataset, NodeRecord, RoadRecord
from rcsd_topo_poc.modules.p01_arm_build.topology import valid_mainnodeid
from rcsd_topo_poc.utils.field_names import normalize_field_name


@dataclass(frozen=True)
class CaseScopedDataset:
    loaded: LoadedDataset
    selected_node_ids: frozenset[str]
    selected_road_ids: frozenset[str]
    audit: dict[str, Any]


def _semantic_group_id(node_meta: dict[str, tuple[str | None, str | None]], node_id: str) -> str:
    meta = node_meta.get(node_id)
    if meta is None:
        return normalise_id(node_id)
    mainnodeid, _kind = meta
    return valid_mainnodeid(mainnodeid) or node_id


def _resolve_junction_group(
    *,
    dataset: str,
    junction_id: str,
    groups: dict[str, list[str]],
    node_to_group: dict[str, str],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    target = normalise_id(junction_id)
    issues: list[str] = []
    candidates = [target]
    if dataset == "RCSD" and target.startswith("R") and len(target) > 1:
        candidates.append(target[1:])
    if dataset == "FRCSD" and target.startswith("F") and len(target) > 1:
        candidates.append(target[1:])
    for candidate in dict.fromkeys(candidates):
        if candidate in groups:
            return candidate, tuple(sorted(groups[candidate])), tuple(issues)
        if candidate in node_to_group:
            group_id = node_to_group[candidate]
            return group_id, tuple(sorted(groups.get(group_id, [candidate]))), tuple(issues)
    issues.append("junction_member_nodes_not_found")
    return target, tuple(), tuple(issues)


def _scan_node_groups(path: Path) -> tuple[dict[str, tuple[str | None, str | None]], dict[str, list[str]], dict[str, str], Any]:
    node_meta: dict[str, tuple[str | None, str | None]] = {}
    groups: dict[str, list[str]] = {}
    node_to_group: dict[str, str] = {}
    with fiona.open(path) as src:
        schema_properties = tuple(normalize_field_name(key) for key in src.schema.get("properties", {}).keys())
        feature_count = 0
        for feature in src:
            feature_count += 1
            properties = _normalise_properties(feature.get("properties"))
            node_id = normalise_id(_first_present(properties, ("id", "nodeid", "node_id")))
            if not node_id:
                raise ValueError(f"Node feature without id in {path}")
            mainnodeid = normalise_id(_first_present(properties, ("mainnodeid", "main_node_id"))) or None
            kind = normalise_id(_first_present(properties, ("kind", "kind_2"))) or None
            group_id = valid_mainnodeid(mainnodeid) or node_id
            node_meta[node_id] = (mainnodeid, kind)
            groups.setdefault(group_id, []).append(node_id)
            node_to_group[node_id] = group_id
        layer = _layer_info(path, feature_count, schema_properties, src)
    return node_meta, groups, node_to_group, layer


def _scan_road_graph(
    path: Path,
    *,
    node_meta: dict[str, tuple[str | None, str | None]],
) -> tuple[dict[str, tuple[str, str, str, str]], dict[str, list[tuple[str, str]]], Any]:
    road_groups: dict[str, tuple[str, str, str, str]] = {}
    adjacency: dict[str, list[tuple[str, str]]] = {}
    with fiona.open(path) as src:
        schema_properties = tuple(normalize_field_name(key) for key in src.schema.get("properties", {}).keys())
        feature_count = 0
        for feature in src:
            feature_count += 1
            properties = _normalise_properties(feature.get("properties"))
            road_id = normalise_id(_first_present(properties, ("id", "roadid", "road_id")))
            snodeid = normalise_id(_first_present(properties, ("snodeid", "snode_id", "startnodeid")))
            enodeid = normalise_id(_first_present(properties, ("enodeid", "enode_id", "endnodeid")))
            if not road_id or not snodeid or not enodeid:
                raise ValueError(f"Road feature without id/snodeid/enodeid in {path}")
            start_group = _semantic_group_id(node_meta, snodeid)
            end_group = _semantic_group_id(node_meta, enodeid)
            road_groups[road_id] = (start_group, end_group, snodeid, enodeid)
            if start_group == end_group:
                continue
            adjacency.setdefault(start_group, []).append((end_group, road_id))
            adjacency.setdefault(end_group, []).append((start_group, road_id))
        layer = _layer_info(path, feature_count, schema_properties, src)
    return road_groups, adjacency, layer


def _selected_context(
    *,
    resolved_group_id: str,
    member_node_ids: tuple[str, ...],
    groups: dict[str, list[str]],
    road_groups: dict[str, tuple[str, str, str, str]],
    adjacency: dict[str, list[tuple[str, str]]],
    bfs_depth: int,
) -> tuple[set[str], set[str], dict[str, int]]:
    group_depths: dict[str, int] = {resolved_group_id: 0}
    queue: deque[str] = deque([resolved_group_id])
    while queue:
        group_id = queue.popleft()
        current_depth = group_depths[group_id]
        if current_depth >= bfs_depth:
            continue
        for next_group_id, _road_id in adjacency.get(group_id, []):
            if next_group_id in group_depths:
                continue
            group_depths[next_group_id] = current_depth + 1
            queue.append(next_group_id)

    selected_node_ids: set[str] = set(member_node_ids)
    selected_road_ids: set[str] = set()
    for group_id in group_depths:
        selected_node_ids.update(groups.get(group_id, (group_id,)))
    for road_id, (start_group, end_group, snodeid, enodeid) in road_groups.items():
        if start_group not in group_depths and end_group not in group_depths:
            continue
        selected_road_ids.add(road_id)
        selected_node_ids.add(snodeid)
        selected_node_ids.add(enodeid)
        selected_node_ids.update(groups.get(start_group, (start_group,)))
        selected_node_ids.update(groups.get(end_group, (end_group,)))
    return selected_node_ids, selected_road_ids, group_depths


def _read_selected_nodes(
    path: Path,
    *,
    selected_node_ids: set[str],
) -> dict[str, NodeRecord]:
    nodes: dict[str, NodeRecord] = {}
    with fiona.open(path) as src:
        for feature in src:
            properties = _normalise_properties(feature.get("properties"))
            node_id = normalise_id(_first_present(properties, ("id", "nodeid", "node_id")))
            if node_id not in selected_node_ids:
                continue
            mainnodeid = normalise_id(_first_present(properties, ("mainnodeid", "main_node_id"))) or None
            kind = normalise_id(_first_present(properties, ("kind", "kind_2"))) or None
            nodes[node_id] = NodeRecord(
                node_id=node_id,
                mainnodeid=mainnodeid,
                kind=kind,
                geometry=shape(feature["geometry"]),
                properties=properties,
            )
    return nodes


def _read_selected_roads(
    path: Path,
    *,
    selected_road_ids: set[str],
) -> dict[str, RoadRecord]:
    roads: dict[str, RoadRecord] = {}
    with fiona.open(path) as src:
        for feature in src:
            properties = _normalise_properties(feature.get("properties"))
            road_id = normalise_id(_first_present(properties, ("id", "roadid", "road_id")))
            if road_id not in selected_road_ids:
                continue
            snodeid = normalise_id(_first_present(properties, ("snodeid", "snode_id", "startnodeid")))
            enodeid = normalise_id(_first_present(properties, ("enodeid", "enode_id", "endnodeid")))
            direction_value = _first_present(properties, ("direction",))
            try:
                direction = int(direction_value) if direction_value is not None and str(direction_value).strip() != "" else None
            except (TypeError, ValueError):
                direction = None
            formway = normalise_id(_first_present(properties, ("formway",))) or None
            roads[road_id] = RoadRecord(
                road_id=road_id,
                snodeid=snodeid,
                enodeid=enodeid,
                direction=direction,
                formway=formway,
                geometry=shape(feature["geometry"]),
                properties=properties,
            )
    return roads


def load_case_scoped_dataset(
    dataset_input: DatasetInput,
    *,
    junction_id: str,
    bfs_depth: int,
) -> CaseScopedDataset:
    if bfs_depth < 0:
        raise ValueError("bfs_depth must be >= 0")
    node_meta, groups, node_to_group, node_layer = _scan_node_groups(dataset_input.nodes_path)
    resolved_group_id, member_node_ids, input_flags = _resolve_junction_group(
        dataset=dataset_input.dataset,
        junction_id=junction_id,
        groups=groups,
        node_to_group=node_to_group,
    )
    road_groups, adjacency, road_layer = _scan_road_graph(dataset_input.roads_path, node_meta=node_meta)
    selected_node_ids, selected_road_ids, group_depths = _selected_context(
        resolved_group_id=resolved_group_id,
        member_node_ids=member_node_ids,
        groups=groups,
        road_groups=road_groups,
        adjacency=adjacency,
        bfs_depth=bfs_depth,
    )
    selected_node_ids = {node_id for node_id in selected_node_ids if node_id in node_meta}
    nodes = _read_selected_nodes(dataset_input.nodes_path, selected_node_ids=selected_node_ids)
    roads = _read_selected_roads(dataset_input.roads_path, selected_road_ids=selected_road_ids)
    loaded = LoadedDataset(
        dataset=dataset_input.dataset,
        nodes=nodes,
        roads=roads,
        node_layer=node_layer,
        road_layer=road_layer,
    )
    audit = {
        "dataset": dataset_input.dataset,
        "junction_id": junction_id,
        "scope_mode": "semantic_road_topology_bfs",
        "bfs_depth": bfs_depth,
        "resolved_group_id": resolved_group_id,
        "input_issue_flags": tuple(sorted(set(input_flags))),
        "source_node_feature_count": node_layer.feature_count,
        "source_road_feature_count": road_layer.feature_count,
        "visited_group_count": len(group_depths),
        "selected_node_count": len(nodes),
        "selected_road_count": len(roads),
        "group_depths": dict(sorted(group_depths.items(), key=lambda item: (item[1], item[0]))),
    }
    return CaseScopedDataset(
        loaded=loaded,
        selected_node_ids=frozenset(nodes),
        selected_road_ids=frozenset(roads),
        audit=audit,
    )
