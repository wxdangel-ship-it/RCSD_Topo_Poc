from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, sort_patch_key, write_json, write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.shared import T02RunError, normalize_id, read_vector_layer_strict


REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"
REASON_DUPLICATE_NODE_ID = "duplicate_node_id"
REASON_DUPLICATE_ROAD_ID = "duplicate_road_id"
REASON_UNRESOLVED_CHAIN_NODE = "unresolved_chain_node"

CONTINUOUS_DIST_MAX_M = 50.0
CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M = 75.0
COMPLEX_JUNCTION_KIND = 128
COMPLEX_JUNCTION_FORMWAY = 2048
STAGE4_KIND_2_VALUES = {8, 16}


class AggregateContinuousDivmergeError(T02RunError):
    pass


@dataclass(frozen=True)
class CandidateNode:
    feature_index: int
    properties: dict[str, Any]
    geometry: Point
    node_id: str
    mainnodeid: str | None
    has_evd: str | None
    is_anchor: str | None
    kind: int | None
    grade: int | None
    kind_2: int | None
    grade_2: int | None


@dataclass(frozen=True)
class CandidateRoad:
    feature_index: int
    properties: dict[str, Any]
    road_id: str
    snodeid: str
    enodeid: str
    direction: int
    length_m: float


@dataclass(frozen=True)
class DirectedEdge:
    src: str
    dst: str
    road_idx: int
    length_m: float


@dataclass(frozen=True)
class ChainEdge:
    src: str
    dst: str
    dist_m: float
    path_road_indices: tuple[int, ...]
    start_road_idx: int


@dataclass(frozen=True)
class ChainComponent:
    component_id: str
    node_ids: tuple[str, ...]
    edges: tuple[ChainEdge, ...]
    offsets_m: dict[str, float]
    predecessors: dict[str, tuple[str, ...]]
    diag: dict[str, Any]


@dataclass(frozen=True)
class AggregateContinuousDivmergeArtifacts:
    success: bool
    nodes_fix_path: Path
    roads_fix_path: Path
    report_path: Path
    complex_mainnodeids: tuple[str, ...]
    complex_junction_count: int


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


def _sort_key(value: str) -> tuple[int, int | str]:
    return sort_patch_key(str(value))


def _parse_nodes(path: Union[str, Path], *, layer_name: str | None, crs_override: str | None) -> list[CandidateNode]:
    layer = read_vector_layer_strict(
        path,
        layer_name=layer_name,
        crs_override=crs_override,
        allow_null_geometry=False,
        error_cls=AggregateContinuousDivmergeError,
    )
    parsed: list[CandidateNode] = []
    seen_ids: set[str] = set()
    for feature in layer.features:
        props = feature.properties
        node_id = normalize_id(props.get("id"))
        if node_id is None:
            raise AggregateContinuousDivmergeError(
                REASON_MISSING_REQUIRED_FIELD,
                f"nodes feature[{feature.feature_index}] missing id.",
            )
        if node_id in seen_ids:
            raise AggregateContinuousDivmergeError(
                REASON_DUPLICATE_NODE_ID,
                f"nodes has duplicate id='{node_id}'.",
            )
        seen_ids.add(node_id)
        if feature.geometry is None or feature.geometry.is_empty:
            raise AggregateContinuousDivmergeError(
                REASON_MISSING_REQUIRED_FIELD,
                f"nodes feature[{feature.feature_index}] has empty geometry.",
            )
        centroid = feature.geometry.centroid
        parsed.append(
            CandidateNode(
                feature_index=feature.feature_index,
                properties=props,
                geometry=Point(float(centroid.x), float(centroid.y)),
                node_id=node_id,
                mainnodeid=normalize_id(props.get("mainnodeid")),
                has_evd=normalize_id(props.get("has_evd")),
                is_anchor=normalize_id(props.get("is_anchor")),
                kind=_coerce_int(props.get("kind")),
                grade=_coerce_int(props.get("grade")),
                kind_2=_coerce_int(props.get("kind_2")),
                grade_2=_coerce_int(props.get("grade_2")),
            )
        )
    return parsed


def _parse_roads(path: Union[str, Path], *, layer_name: str | None, crs_override: str | None) -> list[CandidateRoad]:
    layer = read_vector_layer_strict(
        path,
        layer_name=layer_name,
        crs_override=crs_override,
        allow_null_geometry=False,
        error_cls=AggregateContinuousDivmergeError,
    )
    parsed: list[CandidateRoad] = []
    seen_ids: set[str] = set()
    for feature in layer.features:
        props = feature.properties
        road_id = normalize_id(props.get("id"))
        snodeid = normalize_id(props.get("snodeid"))
        enodeid = normalize_id(props.get("enodeid"))
        direction = _coerce_int(props.get("direction"))
        if road_id is None or snodeid is None or enodeid is None or direction is None:
            raise AggregateContinuousDivmergeError(
                REASON_MISSING_REQUIRED_FIELD,
                f"roads feature[{feature.feature_index}] missing required id/snodeid/enodeid/direction.",
            )
        if road_id in seen_ids:
            raise AggregateContinuousDivmergeError(
                REASON_DUPLICATE_ROAD_ID,
                f"roads has duplicate id='{road_id}'.",
            )
        seen_ids.add(road_id)
        if feature.geometry is None or feature.geometry.is_empty:
            raise AggregateContinuousDivmergeError(
                REASON_MISSING_REQUIRED_FIELD,
                f"roads feature[{feature.feature_index}] has empty geometry.",
            )
        parsed.append(
            CandidateRoad(
                feature_index=feature.feature_index,
                properties=props,
                road_id=road_id,
                snodeid=snodeid,
                enodeid=enodeid,
                direction=direction,
                length_m=float(feature.geometry.length),
            )
        )
    return parsed


def _is_stage4_representative(node: CandidateNode) -> bool:
    representative_id = node.mainnodeid or node.node_id
    return (
        node.has_evd == "yes"
        and node.is_anchor == "no"
        and node.kind_2 in STAGE4_KIND_2_VALUES
        and normalize_id(node.node_id) == normalize_id(representative_id)
    )


def _is_merge_kind(kind_2: int | None) -> bool:
    return int(kind_2 or 0) == 8


def _is_diverge_kind(kind_2: int | None) -> bool:
    return int(kind_2 or 0) == 16


def _edge_dist_limit_m(*, src_kind: int | None, dst_kind: int | None) -> float:
    if _is_diverge_kind(src_kind) and _is_merge_kind(dst_kind):
        return CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M
    return CONTINUOUS_DIST_MAX_M


def _build_effective_directed_edges(
    roads: list[CandidateRoad],
) -> tuple[dict[str, list[DirectedEdge]], dict[str, set[int]], list[str]]:
    adjacency_out: dict[str, list[DirectedEdge]] = defaultdict(list)
    incident_map: dict[str, set[int]] = defaultdict(set)
    direction_errors: list[str] = []

    for idx, road in enumerate(roads):
        if road.direction not in {2, 3}:
            if road.direction not in {0, 1}:
                direction_errors.append(f"direction_invalid:road_idx={idx}:value={road.direction}")
            continue

        incident_map[road.snodeid].add(idx)
        incident_map[road.enodeid].add(idx)
        if road.direction == 2:
            edge = DirectedEdge(src=road.snodeid, dst=road.enodeid, road_idx=idx, length_m=road.length_m)
        else:
            edge = DirectedEdge(src=road.enodeid, dst=road.snodeid, road_idx=idx, length_m=road.length_m)
        adjacency_out[edge.src].append(edge)
    return dict(adjacency_out), dict(incident_map), direction_errors


def _compute_degree(*, nodeid: str, incident_map: dict[str, set[int]]) -> int:
    return int(len(incident_map.get(nodeid, set())))


def _follow_to_next_deg3(
    *,
    start_nodeid: str,
    first_edge: DirectedEdge,
    adjacency_out: dict[str, list[DirectedEdge]],
    incident_map: dict[str, set[int]],
    max_dist_m: float,
) -> tuple[str, float, list[int], dict[str, Any]] | None:
    total = float(max(0.0, first_edge.length_m))
    if total > max_dist_m + 1e-9:
        return None

    prev_node = start_nodeid
    curr_node = first_edge.dst
    path_edges = [first_edge.road_idx]
    diag: dict[str, Any] = {
        "stopped_reason": "none",
        "deg2_steps": 0,
        "branch_stop": False,
    }

    hops = 0
    while hops < 256:
        hops += 1
        degree = _compute_degree(nodeid=curr_node, incident_map=incident_map)
        if degree >= 3:
            return curr_node, float(total), path_edges, diag
        if degree != 2:
            diag["stopped_reason"] = "dead_end_or_isolated"
            return None

        out_edges = adjacency_out.get(curr_node, [])
        candidates = [edge for edge in out_edges if edge.dst != prev_node]
        if len(candidates) != 1:
            diag["stopped_reason"] = "deg2_out_not_unique"
            diag["branch_stop"] = True
            return None

        nxt = candidates[0]
        total += float(max(0.0, nxt.length_m))
        if total > max_dist_m + 1e-9:
            diag["stopped_reason"] = "distance_exceed"
            return None
        path_edges.append(nxt.road_idx)
        prev_node = curr_node
        curr_node = nxt.dst
        diag["deg2_steps"] = int(diag.get("deg2_steps", 0)) + 1

    diag["stopped_reason"] = "max_hops_reached"
    return None


def _connected_components(nodes: set[str], edges: list[ChainEdge]) -> list[set[str]]:
    undirected: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for edge in edges:
        undirected.setdefault(edge.src, set()).add(edge.dst)
        undirected.setdefault(edge.dst, set()).add(edge.src)

    components: list[set[str]] = []
    seen: set[str] = set()
    for node_id in sorted(nodes, key=_sort_key):
        if node_id in seen:
            continue
        component: set[str] = set()
        queue: deque[str] = deque([node_id])
        seen.add(node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbour in sorted(undirected.get(current, set()), key=_sort_key):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                queue.append(neighbour)
        components.append(component)
    return components


def _topo_offsets(
    *,
    component_nodes: set[str],
    component_edges: list[ChainEdge],
) -> tuple[dict[str, float], dict[str, tuple[str, ...]], dict[str, Any]]:
    predecessors: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in component_nodes}
    successors: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in component_nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in component_nodes}

    for edge in component_edges:
        if edge.src not in component_nodes or edge.dst not in component_nodes:
            continue
        predecessors[edge.dst].append((edge.src, float(edge.dist_m)))
        successors[edge.src].append((edge.dst, float(edge.dist_m)))
        indegree[edge.dst] += 1

    sources = [node_id for node_id, value in indegree.items() if value == 0]
    offsets: dict[str, float] = {node_id: 0.0 for node_id in sources}
    queue: deque[str] = deque(sorted(sources, key=_sort_key))
    processed = 0
    while queue:
        current = queue.popleft()
        processed += 1
        current_offset = float(offsets.get(current, 0.0))
        for nxt, dist_m in successors.get(current, []):
            candidate_offset = current_offset + float(dist_m)
            if nxt not in offsets or candidate_offset < float(offsets[nxt]):
                offsets[nxt] = float(candidate_offset)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    is_dag = bool(processed == len(component_nodes))
    cycle_nodes: list[str] = []
    if not is_dag:
        cycle_nodes = sorted([node_id for node_id, value in indegree.items() if value > 0], key=_sort_key)
        for node_id in cycle_nodes:
            offsets.setdefault(node_id, 0.0)

    predecessor_ids = {
        node_id: tuple(sorted((pred for pred, _ in items), key=_sort_key))
        for node_id, items in predecessors.items()
    }
    return offsets, predecessor_ids, {
        "is_dag": is_dag,
        "sources": sorted(sources, key=_sort_key),
        "cycle_nodes": cycle_nodes,
    }


def _build_continuous_graph(
    *,
    starts_set: set[str],
    nodes_kind: dict[str, int],
    roads: list[CandidateRoad],
) -> tuple[list[ChainEdge], list[ChainComponent], dict[str, Any]]:
    adjacency_out, incident_map, direction_errors = _build_effective_directed_edges(roads)
    search_limit_m = max(CONTINUOUS_DIST_MAX_M, CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M)

    edges_map: dict[tuple[str, str], ChainEdge] = {}
    visit_queue: deque[str] = deque(sorted(starts_set, key=_sort_key))
    seen_expand: set[str] = set()
    trace_diag: dict[str, list[dict[str, Any]]] = defaultdict(list)

    while visit_queue:
        src = visit_queue.popleft()
        if src in seen_expand:
            continue
        seen_expand.add(src)
        src_kind = nodes_kind.get(src)
        out_edges = adjacency_out.get(src, [])
        for first_edge in out_edges:
            result = _follow_to_next_deg3(
                start_nodeid=src,
                first_edge=first_edge,
                adjacency_out=adjacency_out,
                incident_map=incident_map,
                max_dist_m=float(search_limit_m),
            )
            if result is None:
                continue
            dst, dist_m, path_road_indices, diag = result
            dst_kind = nodes_kind.get(dst)
            distance_limit_m = _edge_dist_limit_m(src_kind=src_kind, dst_kind=dst_kind)
            trace_diag[src].append(
                {
                    "dst": dst,
                    "dist_m": float(dist_m),
                    "dist_limit_m": float(distance_limit_m),
                    "path_road_indices": [int(index) for index in path_road_indices],
                    "diag": dict(diag),
                }
            )
            if dst not in starts_set:
                continue
            if float(dist_m) >= float(distance_limit_m):
                continue
            key = (src, dst)
            current = ChainEdge(
                src=src,
                dst=dst,
                dist_m=float(dist_m),
                path_road_indices=tuple(int(index) for index in path_road_indices),
                start_road_idx=int(first_edge.road_idx),
            )
            previous = edges_map.get(key)
            if previous is None or current.dist_m < previous.dist_m:
                edges_map[key] = current
            if dst not in seen_expand:
                visit_queue.append(dst)

    chain_edges = sorted(edges_map.values(), key=lambda item: (_sort_key(item.src), _sort_key(item.dst), item.dist_m))
    component_nodes: set[str] = set()
    for edge in chain_edges:
        component_nodes.add(edge.src)
        component_nodes.add(edge.dst)

    components: list[ChainComponent] = []
    for index, nodes in enumerate(_connected_components(component_nodes, chain_edges)):
        component_edges = [edge for edge in chain_edges if edge.src in nodes and edge.dst in nodes]
        offsets_m, predecessors, topology_diag = _topo_offsets(component_nodes=nodes, component_edges=component_edges)
        components.append(
            ChainComponent(
                component_id=f"chain_{index:03d}",
                node_ids=tuple(sorted(nodes, key=_sort_key)),
                edges=tuple(sorted(component_edges, key=lambda item: (_sort_key(item.src), _sort_key(item.dst), item.dist_m))),
                offsets_m={node_id: float(value) for node_id, value in offsets_m.items()},
                predecessors=predecessors,
                diag={"topology": topology_diag},
            )
        )

    return chain_edges, components, {
        "direction_errors": direction_errors,
        "trace": {key: value for key, value in trace_diag.items()},
    }


def _resolved_grade(node: CandidateNode) -> int | None:
    for value in (node.grade, node.grade_2):
        if value is not None and value >= 0:
            return int(value)
    return None


def _grade_sort_tuple(node: CandidateNode) -> tuple[int, int, tuple[int, int | str]]:
    grade = _resolved_grade(node)
    if grade is None or grade <= 0:
        rank = 9999
    else:
        rank = int(grade)
    grade_2_rank = int(node.grade_2) if node.grade_2 is not None and node.grade_2 > 0 else 9999
    return rank, grade_2_rank, _sort_key(node.node_id)


def _serialize_feature(feature) -> dict[str, Any]:
    return {
        "properties": dict(feature.properties),
        "geometry": feature.geometry,
    }


def run_t02_aggregate_continuous_divmerge(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    nodes_fix_path: Union[str, Path],
    roads_fix_path: Union[str, Path],
    report_path: Optional[Union[str, Path]] = None,
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
) -> AggregateContinuousDivmergeArtifacts:
    nodes_fix_path = Path(nodes_fix_path)
    roads_fix_path = Path(roads_fix_path)
    report_path = Path(report_path) if report_path is not None else nodes_fix_path.with_name("continuous_divmerge_report.json")

    nodes_layer_data = read_vector_layer_strict(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=False,
        error_cls=AggregateContinuousDivmergeError,
    )
    roads_layer_data = read_vector_layer_strict(
        roads_path,
        layer_name=roads_layer,
        crs_override=roads_crs,
        allow_null_geometry=False,
        error_cls=AggregateContinuousDivmergeError,
    )
    nodes = _parse_nodes(nodes_path, layer_name=nodes_layer, crs_override=nodes_crs)
    roads = _parse_roads(roads_path, layer_name=roads_layer, crs_override=roads_crs)

    node_by_id = {node.node_id: node for node in nodes}
    candidate_nodes = [node for node in nodes if _is_stage4_representative(node)]
    candidate_node_ids = {node.node_id for node in candidate_nodes}
    candidate_kind_map = {node.node_id: int(node.kind_2 or 0) for node in candidate_nodes}

    chain_edges, chain_components, chain_diag = _build_continuous_graph(
        starts_set=candidate_node_ids,
        nodes_kind=candidate_kind_map,
        roads=roads,
    )

    aggregated_rows: list[dict[str, Any]] = []
    updated_node_ids: set[str] = set()
    updated_road_ids: set[str] = set()

    for component in chain_components:
        component_nodes = [node_by_id[node_id] for node_id in component.node_ids if node_id in node_by_id]
        if len(component_nodes) != len(component.node_ids):
            missing = sorted(set(component.node_ids) - set(node_by_id), key=_sort_key)
            raise AggregateContinuousDivmergeError(
                REASON_UNRESOLVED_CHAIN_NODE,
                f"Chain component '{component.component_id}' references missing nodes: {missing}",
            )
        if len(component_nodes) < 2:
            continue

        topology_diag = component.diag.get("topology") or {}
        if not bool(topology_diag.get("is_dag", False)):
            aggregated_rows.append(
                {
                    "component_id": component.component_id,
                    "status": "skipped",
                    "reason": "topology_not_dag",
                    "node_ids": list(component.node_ids),
                    "edge_count": len(component.edges),
                    "topology": topology_diag,
                }
            )
            continue

        chosen_main = sorted(component_nodes, key=_grade_sort_tuple)[0]
        chosen_mainnodeid = chosen_main.node_id
        group_node_ids = sorted(component.node_ids, key=_sort_key)
        grouped_subnodeid = ",".join(group_node_ids)
        changed_road_indices = sorted(
            {road_index for edge in component.edges for road_index in edge.path_road_indices}
        )
        changed_road_ids = sorted({roads[road_index].road_id for road_index in changed_road_indices}, key=_sort_key)

        chosen_props = nodes_layer_data.features[chosen_main.feature_index].properties
        chosen_props["mainnodeid"] = chosen_mainnodeid
        chosen_props["kind"] = COMPLEX_JUNCTION_KIND
        chosen_props["kind_2"] = COMPLEX_JUNCTION_KIND
        if chosen_props.get("grade") is None and _resolved_grade(chosen_main) is not None:
            chosen_props["grade"] = _resolved_grade(chosen_main)
        if chosen_props.get("grade_2") is None and _resolved_grade(chosen_main) is not None:
            chosen_props["grade_2"] = _resolved_grade(chosen_main)
        chosen_props["subnodeid"] = grouped_subnodeid
        updated_node_ids.add(chosen_mainnodeid)

        for node in component_nodes:
            if node.node_id == chosen_mainnodeid:
                continue
            props = nodes_layer_data.features[node.feature_index].properties
            props["mainnodeid"] = chosen_mainnodeid
            props["grade"] = 0
            props["kind"] = 0
            props["grade_2"] = 0
            props["kind_2"] = 0
            props["subnodeid"] = None
            updated_node_ids.add(node.node_id)

        for road_index in changed_road_indices:
            props = roads_layer_data.features[road_index].properties
            props["formway"] = COMPLEX_JUNCTION_FORMWAY
            updated_road_ids.add(roads[road_index].road_id)

        aggregated_rows.append(
            {
                "component_id": component.component_id,
                "status": "aggregated",
                "reason": None,
                "node_ids": list(group_node_ids),
                "mainnodeid": chosen_mainnodeid,
                "main_grade": _resolved_grade(chosen_main),
                "edge_count": len(component.edges),
                "road_ids": changed_road_ids,
                "offsets_m": {node_id: round(float(value), 3) for node_id, value in component.offsets_m.items()},
                "predecessors": {node_id: list(items) for node_id, items in component.predecessors.items()},
                "topology": topology_diag,
            }
        )

    complex_mainnodeids = tuple(
        sorted(
            [str(row["mainnodeid"]) for row in aggregated_rows if row["status"] == "aggregated" and row.get("mainnodeid") is not None],
            key=_sort_key,
        )
    )
    complex_junction_count = len(complex_mainnodeids)

    nodes_fix_features = [_serialize_feature(feature) for feature in nodes_layer_data.features]
    roads_fix_features = [_serialize_feature(feature) for feature in roads_layer_data.features]
    write_vector(nodes_fix_path, nodes_fix_features, crs_text=TARGET_CRS.to_string())
    write_vector(roads_fix_path, roads_fix_features, crs_text=TARGET_CRS.to_string())
    write_json(
        report_path,
        {
            "success": True,
            "target_crs": TARGET_CRS.to_string(),
            "inputs": {
                "nodes_path": str(Path(nodes_path)),
                "roads_path": str(Path(roads_path)),
            },
            "output_files": {
                "nodes_fix_path": str(nodes_fix_path),
                "roads_fix_path": str(roads_fix_path),
                "report_path": str(report_path),
            },
            "params": {
                "continuous_dist_max_m": CONTINUOUS_DIST_MAX_M,
                "continuous_diverge_then_merge_dist_max_m": CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M,
                "stage4_candidate_filter": {
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": [8, 16],
                    "representative_only": True,
                },
            },
            "counts": {
                "node_feature_count": len(nodes),
                "road_feature_count": len(roads),
                "candidate_node_count": len(candidate_nodes),
                "chain_edge_count": len(chain_edges),
                "chain_component_count": len(chain_components),
                "complex_junction_count": complex_junction_count,
                "aggregated_component_count": sum(1 for row in aggregated_rows if row["status"] == "aggregated"),
                "skipped_component_count": sum(1 for row in aggregated_rows if row["status"] != "aggregated"),
                "updated_node_count": len(updated_node_ids),
                "updated_road_count": len(updated_road_ids),
            },
            "complex_mainnodeids": list(complex_mainnodeids),
            "diag": chain_diag,
            "rows": aggregated_rows,
        },
    )
    return AggregateContinuousDivmergeArtifacts(
        success=True,
        nodes_fix_path=nodes_fix_path,
        roads_fix_path=roads_fix_path,
        report_path=report_path,
        complex_mainnodeids=complex_mainnodeids,
        complex_junction_count=complex_junction_count,
    )


def run_t02_aggregate_continuous_divmerge_cli(args: argparse.Namespace) -> int:
    try:
        artifacts = run_t02_aggregate_continuous_divmerge(
            nodes_path=args.nodes_path,
            roads_path=args.roads_path,
            nodes_fix_path=args.nodes_fix_path,
            roads_fix_path=args.roads_fix_path,
            report_path=args.report_path,
            nodes_layer=args.nodes_layer,
            roads_layer=args.roads_layer,
            nodes_crs=args.nodes_crs,
            roads_crs=args.roads_crs,
        )
    except AggregateContinuousDivmergeError as exc:
        print(f"ERROR[{exc.reason}]: {exc.detail}")
        return 1

    print(f"T02 continuous div/merge aggregation completed: {artifacts.nodes_fix_path}")
    print(f"Complex junction count: {artifacts.complex_junction_count}")
    print(
        "Complex junction mainnodeids: "
        + (",".join(artifacts.complex_mainnodeids) if artifacts.complex_mainnodeids else "<none>")
    )
    return 0
