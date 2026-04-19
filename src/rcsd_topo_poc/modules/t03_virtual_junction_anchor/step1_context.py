from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from shapely.ops import unary_union

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature, read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import (
    CaseSpec,
    NodeRecord,
    RoadRecord,
    SemanticGroup,
    Step1Context,
)


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_nodes(features: Iterable[LayerFeature]) -> tuple[NodeRecord, ...]:
    rows: list[NodeRecord] = []
    for feature_index, feature in enumerate(features):
        props = dict(feature.properties)
        node_id = _normalize_text(props.get("id"))
        if node_id is None or feature.geometry is None:
            continue
        rows.append(
            NodeRecord(
                feature_index=feature_index,
                node_id=node_id,
                mainnodeid=_normalize_text(props.get("mainnodeid")),
                has_evd=_normalize_text(props.get("has_evd")),
                is_anchor=_normalize_text(props.get("is_anchor")),
                kind_2=_coerce_int(props.get("kind_2")),
                grade_2=_coerce_int(props.get("grade_2")),
                geometry=feature.geometry,
            )
        )
    return tuple(rows)


def _parse_roads(features: Iterable[LayerFeature]) -> tuple[RoadRecord, ...]:
    rows: list[RoadRecord] = []
    for feature_index, feature in enumerate(features):
        props = dict(feature.properties)
        road_id = _normalize_text(props.get("id"))
        if road_id is None or feature.geometry is None:
            continue
        rows.append(
            RoadRecord(
                feature_index=feature_index,
                road_id=road_id,
                snodeid=_normalize_text(props.get("snodeid")),
                enodeid=_normalize_text(props.get("enodeid")),
                direction=_coerce_int(props.get("direction")),
                geometry=feature.geometry,
            )
        )
    return tuple(rows)


def _resolve_representative_node(nodes: tuple[NodeRecord, ...], case_id: str) -> NodeRecord:
    for node in nodes:
        if node.node_id == case_id:
            return node
    for node in nodes:
        if node.mainnodeid == case_id:
            return node
    raise ValueError(f"representative node not found for case_id={case_id}")


def _build_target_group(nodes: tuple[NodeRecord, ...], representative_node: NodeRecord, case_id: str) -> SemanticGroup:
    group_nodes = tuple(
        sorted(
            (
                node
                for node in nodes
                if node.mainnodeid is not None and node.mainnodeid == (representative_node.mainnodeid or case_id)
            ),
            key=lambda item: item.node_id,
        )
    )
    if group_nodes:
        group_id = representative_node.mainnodeid or case_id
        return SemanticGroup(group_id=group_id, nodes=group_nodes)
    return SemanticGroup(group_id=case_id, nodes=(representative_node,))


def _build_foreign_groups(nodes: tuple[NodeRecord, ...], target_group: SemanticGroup) -> tuple[SemanticGroup, ...]:
    target_ids = {node.node_id for node in target_group.nodes}
    grouped: dict[str, list[NodeRecord]] = defaultdict(list)
    for node in nodes:
        if node.node_id in target_ids:
            continue
        group_id = node.mainnodeid or node.node_id
        grouped[group_id].append(node)
    return tuple(
        SemanticGroup(group_id=group_id, nodes=tuple(sorted(group_nodes, key=lambda item: item.node_id)))
        for group_id, group_nodes in sorted(grouped.items(), key=lambda item: item[0])
    )


def _resolve_target_road_ids(roads: tuple[RoadRecord, ...], target_group: SemanticGroup) -> frozenset[str]:
    target_node_ids = {node.node_id for node in target_group.nodes}
    road_ids = {
        road.road_id
        for road in roads
        if road.snodeid in target_node_ids or road.enodeid in target_node_ids
    }
    if road_ids:
        return frozenset(road_ids)
    target_geometry = unary_union([node.geometry.buffer(6.0) for node in target_group.nodes])
    return frozenset(
        road.road_id
        for road in roads
        if not road.geometry.is_empty and road.geometry.distance(target_geometry) <= 12.0
    )


def build_step1_context_from_features(
    *,
    case_spec: CaseSpec,
    node_features: Iterable[LayerFeature],
    road_features: Iterable[LayerFeature],
    drivezone_features: Iterable[LayerFeature],
    rcsdroad_features: Iterable[LayerFeature],
    rcsdnode_features: Iterable[LayerFeature],
) -> Step1Context:
    nodes = _parse_nodes(node_features)
    roads = _parse_roads(road_features)
    rcsd_roads = _parse_roads(rcsdroad_features)
    rcsd_nodes = _parse_nodes(rcsdnode_features)
    drivezone_features = tuple(drivezone_features)
    drivezone_geometries = [feature.geometry for feature in drivezone_features if feature.geometry is not None]
    if not drivezone_geometries:
        raise ValueError(f"drivezone is empty for case_id={case_spec.case_id}")
    representative_node = _resolve_representative_node(nodes, case_spec.case_id)
    target_group = _build_target_group(nodes, representative_node, case_spec.case_id)
    foreign_groups = _build_foreign_groups(nodes, target_group)
    return Step1Context(
        case_spec=case_spec,
        representative_node=representative_node,
        target_group=target_group,
        all_nodes=nodes,
        foreign_groups=foreign_groups,
        roads=roads,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        drivezone_geometry=unary_union(drivezone_geometries).buffer(0),
        target_road_ids=_resolve_target_road_ids(roads, target_group),
    )


def build_step1_context(case_spec: CaseSpec) -> Step1Context:
    return build_step1_context_from_features(
        case_spec=case_spec,
        node_features=read_vector_layer(case_spec.input_paths["nodes_path"]).features,
        road_features=read_vector_layer(case_spec.input_paths["roads_path"]).features,
        drivezone_features=read_vector_layer(case_spec.input_paths["drivezone_path"]).features,
        rcsdroad_features=read_vector_layer(case_spec.input_paths["rcsdroad_path"]).features,
        rcsdnode_features=read_vector_layer(case_spec.input_paths["rcsdnode_path"]).features,
    )
