from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorFeature,
    aggregate_bounds,
    ensure_gpkg_path,
    read_vector,
    resolve_case_insensitive_field_name,
    resolve_field_name,
    write_gpkg,
    write_json,
)


T_KIND_VALUE = 2048
CROSS_KIND_VALUE = 4
DIVERGE_KIND_VALUE = 16
MERGE_KIND_VALUE = 8

ERROR_T_JUNCTION = "错误T型路口"
ERROR_CROSS_JUNCTION = "错误交叉路口"
ERROR_DIVMERGE_JUNCTION = "错误分歧合流路口"

DEFAULT_TRACE_DISTANCE_M = 100.0
DEFAULT_ANGLE_TOLERANCE_DEGREES = 35.0

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class T08JunctionTypeRepairArtifacts:
    nodes_error_output: Path
    summary_output: Path


@dataclass(frozen=True)
class ParsedNode:
    feature_index: int
    node_id: str
    semantic_id: str
    kind_2: int | None
    properties: dict[str, Any]
    geometry: Point


@dataclass(frozen=True)
class SemanticNode:
    semantic_id: str
    representative: ParsedNode
    member_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedRoad:
    feature_index: int
    road_id: str
    snodeid: str
    enodeid: str
    direction: int | None
    geometry: BaseGeometry
    length_m: float


@dataclass(frozen=True)
class DirectedEdge:
    src: str
    dst: str
    road_idx: int
    road_id: str
    length_m: float
    vector: tuple[float, float]


@dataclass(frozen=True)
class Topology:
    in_degree: dict[str, int]
    out_degree: dict[str, int]
    in_edges: dict[str, tuple[DirectedEdge, ...]]
    out_edges: dict[str, tuple[DirectedEdge, ...]]
    reverse_edges: dict[str, tuple[DirectedEdge, ...]]
    incident_road_indices: dict[str, frozenset[int]]
    internal_road_count: int
    direction_errors: tuple[str, ...]


@dataclass(frozen=True)
class TraceResult:
    node_id: str
    distance_m: float
    path_road_indices: tuple[int, ...]
    first_vector: tuple[float, float]
    last_vector: tuple[float, float]


def run_t08_junction_type_repair(
    *,
    nodes_gpkg: str | Path,
    roads_gpkg: str | Path,
    nodes_error_output: str | Path,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    nodes_default_crs_text: str | None = None,
    roads_default_crs_text: str | None = None,
    trace_distance_m: float = DEFAULT_TRACE_DISTANCE_M,
    angle_tolerance_degrees: float = DEFAULT_ANGLE_TOLERANCE_DEGREES,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08JunctionTypeRepairArtifacts:
    started = time.perf_counter()
    stage_timings: dict[str, float] = {}
    nodes_path = ensure_gpkg_path(nodes_gpkg, label="--nodes-gpkg")
    roads_path = ensure_gpkg_path(roads_gpkg, label="--roads-gpkg")
    output_path = ensure_gpkg_path(nodes_error_output, label="--nodes-error-output")
    summary_path = (
        Path(summary_output).expanduser().resolve()
        if summary_output
        else output_path.with_name("t08_junction_type_repair_summary.json")
    )

    _emit_progress(progress_callback, f"[T08 Tool4] start nodes={nodes_path} roads={roads_path}")
    stage_started = time.perf_counter()
    nodes_result = read_vector(
        nodes_path,
        layer_name=nodes_layer,
        default_crs_text=nodes_default_crs_text,
        target_epsg=target_epsg,
    )
    roads_result = read_vector(
        roads_path,
        layer_name=roads_layer,
        default_crs_text=roads_default_crs_text,
        target_epsg=target_epsg,
    )
    if not nodes_result.features:
        raise ValueError("Nodes input contains no features")
    stage_timings["read_inputs_seconds"] = _elapsed_since(stage_started)
    _emit_progress(
        progress_callback,
        f"[T08 Tool4] loaded nodes={len(nodes_result.features)} roads={len(roads_result.features)}",
    )

    stage_started = time.perf_counter()
    node_id_field = resolve_field_name(nodes_result.features, ["id"], "nodes input")
    node_kind_2_field = resolve_field_name(nodes_result.features, ["kind_2"], "nodes input")
    node_mainnodeid_field = _optional_field(nodes_result.features, ["mainnodeid"])
    road_id_field = resolve_field_name(roads_result.features, ["id"], "roads input")
    road_snode_field = resolve_field_name(roads_result.features, ["snodeid"], "roads input")
    road_enode_field = resolve_field_name(roads_result.features, ["enodeid"], "roads input")
    road_direction_field = resolve_field_name(roads_result.features, ["direction"], "roads input")
    parsed_nodes = _parse_nodes(
        nodes_result.features,
        node_id_field=node_id_field,
        node_kind_2_field=node_kind_2_field,
        node_mainnodeid_field=node_mainnodeid_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    semantic_nodes = _build_semantic_nodes(parsed_nodes)
    parsed_roads = _parse_roads(
        roads_result.features,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    node_to_semantic = {node.node_id: node.semantic_id for node in parsed_nodes}
    topology = _build_topology(parsed_roads, node_to_semantic=node_to_semantic)
    stage_timings["build_topology_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    errors = _detect_junction_type_errors(
        semantic_nodes=semantic_nodes,
        parsed_roads=parsed_roads,
        topology=topology,
        trace_distance_m=float(trace_distance_m),
        angle_tolerance_degrees=float(angle_tolerance_degrees),
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    stage_timings["detect_errors_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    output_features = _build_error_features(errors)
    output_fields = (
        "id",
        "semantic_node_id",
        "source_node_id",
        "kind_2",
        "error_type",
        "error_reason",
        "error_group_id",
        "in_degree",
        "out_degree",
        "related_node_ids",
        "related_road_ids",
        "audit_json",
    )
    _emit_progress(progress_callback, f"[T08 Tool4] writing nodes_error output={output_path}")
    write_gpkg(output_path, output_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields, geometry_type="Point")
    stage_timings["write_output_seconds"] = _elapsed_since(stage_started)
    elapsed_seconds = _elapsed_since(started)

    counts_by_type: dict[str, int] = defaultdict(int)
    for row in errors:
        counts_by_type[str(row["error_type"])] += 1

    summary = {
        "tool": "T08 Tool4",
        "stage": "junction_type_repair_error_detection",
        "target_epsg": target_epsg,
        "input_paths": {"nodes_gpkg": nodes_path, "roads_gpkg": roads_path},
        "output_paths": {"nodes_error_output": output_path, "summary_output": summary_path},
        "input_crs": {
            "nodes": nodes_result.source_crs.to_string(),
            "nodes_crs_source": nodes_result.crs_source,
            "roads": roads_result.source_crs.to_string(),
            "roads_crs_source": roads_result.crs_source,
        },
        "params": {
            "nodes_layer": nodes_layer,
            "roads_layer": roads_layer,
            "trace_distance_m": float(trace_distance_m),
            "angle_tolerance_degrees": float(angle_tolerance_degrees),
        },
        "field_audit": {
            "node_id_field": node_id_field,
            "node_kind_2_field": node_kind_2_field,
            "node_mainnodeid_field": node_mainnodeid_field,
            "road_id_field": road_id_field,
            "road_snode_field": road_snode_field,
            "road_enode_field": road_enode_field,
            "road_direction_field": road_direction_field,
        },
        "counts": {
            "node_feature_count": len(nodes_result.features),
            "semantic_node_count": len(semantic_nodes),
            "road_feature_count": len(roads_result.features),
            "error_feature_count": len(errors),
            "error_count_by_type": dict(sorted(counts_by_type.items())),
            "internal_road_count": topology.internal_road_count,
            "direction_error_count": len(topology.direction_errors),
        },
        "direction_errors": list(topology.direction_errors),
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in output_features),
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "semantic_nodes_per_second": _items_per_second(len(semantic_nodes), elapsed_seconds),
            "stage_timings": {key: round(value, 6) for key, value in stage_timings.items()},
        },
        "errors": [_summary_error_row(row) for row in errors],
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        (
            f"[T08 Tool4] finished semantic_nodes={len(semantic_nodes)} errors={len(errors)} "
            f"elapsed={elapsed_seconds:.2f}s summary={summary_path}"
        ),
    )
    return T08JunctionTypeRepairArtifacts(nodes_error_output=output_path, summary_output=summary_path)


def _parse_nodes(
    features: list[VectorFeature],
    *,
    node_id_field: str,
    node_kind_2_field: str,
    node_mainnodeid_field: str | None,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> list[ParsedNode]:
    parsed: list[ParsedNode] = []
    seen_ids: set[str] = set()
    for index, feature in enumerate(features):
        node_id = _required_id(feature.properties.get(node_id_field), "node id")
        if node_id in seen_ids:
            raise ValueError(f"Nodes input has duplicate id '{node_id}'.")
        seen_ids.add(node_id)
        semantic_id = (
            _valid_mainnodeid(feature.properties.get(node_mainnodeid_field))
            if node_mainnodeid_field is not None
            else None
        ) or node_id
        centroid = feature.geometry.centroid
        parsed.append(
            ParsedNode(
                feature_index=index,
                node_id=node_id,
                semantic_id=semantic_id,
                kind_2=_coerce_int(feature.properties.get(node_kind_2_field)),
                properties=dict(feature.properties),
                geometry=Point(float(centroid.x), float(centroid.y)),
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool4] parsed {index + 1} node feature(s)")
    return parsed


def _build_semantic_nodes(parsed_nodes: list[ParsedNode]) -> dict[str, SemanticNode]:
    grouped: dict[str, list[ParsedNode]] = defaultdict(list)
    for node in parsed_nodes:
        grouped[node.semantic_id].append(node)

    semantic_nodes: dict[str, SemanticNode] = {}
    for semantic_id, members in grouped.items():
        representative = _choose_representative(semantic_id, members)
        semantic_nodes[semantic_id] = SemanticNode(
            semantic_id=semantic_id,
            representative=representative,
            member_node_ids=tuple(sorted((node.node_id for node in members), key=_sort_key)),
        )
    return semantic_nodes


def _choose_representative(semantic_id: str, members: list[ParsedNode]) -> ParsedNode:
    exact = [node for node in members if node.node_id == semantic_id]
    if exact:
        return sorted(exact, key=lambda node: node.feature_index)[0]
    non_zero_kind = [node for node in members if int(node.kind_2 or 0) != 0]
    if non_zero_kind:
        return sorted(non_zero_kind, key=lambda node: (_sort_key(node.node_id), node.feature_index))[0]
    return sorted(members, key=lambda node: (_sort_key(node.node_id), node.feature_index))[0]


def _parse_roads(
    features: list[VectorFeature],
    *,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> list[ParsedRoad]:
    parsed: list[ParsedRoad] = []
    seen_ids: set[str] = set()
    for index, feature in enumerate(features):
        road_id = _required_id(feature.properties.get(road_id_field), "road id")
        if road_id in seen_ids:
            raise ValueError(f"Roads input has duplicate id '{road_id}'.")
        seen_ids.add(road_id)
        parsed.append(
            ParsedRoad(
                feature_index=index,
                road_id=road_id,
                snodeid=_required_id(feature.properties.get(road_snode_field), f"road '{road_id}' snodeid"),
                enodeid=_required_id(feature.properties.get(road_enode_field), f"road '{road_id}' enodeid"),
                direction=_coerce_int(feature.properties.get(road_direction_field)),
                geometry=feature.geometry,
                length_m=float(feature.geometry.length),
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool4] parsed {index + 1} road feature(s)")
    return parsed


def _build_topology(parsed_roads: list[ParsedRoad], *, node_to_semantic: dict[str, str]) -> Topology:
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    in_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    out_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    reverse_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    incident_road_indices: dict[str, set[int]] = defaultdict(set)
    direction_errors: list[str] = []
    internal_road_count = 0

    for road_index, road in enumerate(parsed_roads):
        source_semantic = node_to_semantic.get(road.snodeid)
        target_semantic = node_to_semantic.get(road.enodeid)
        if source_semantic is None or target_semantic is None:
            missing_node = road.snodeid if source_semantic is None else road.enodeid
            raise ValueError(f"Road '{road.road_id}' references missing node '{missing_node}'.")
        if source_semantic == target_semantic:
            internal_road_count += 1
            continue
        incident_road_indices[source_semantic].add(road_index)
        incident_road_indices[target_semantic].add(road_index)
        if road.direction in {0, 1}:
            forward_vector = _road_vector_for_direction(road, src_is_snode=True)
            _add_directed_edge(
                road=road,
                road_index=road_index,
                src=source_semantic,
                dst=target_semantic,
                vector=forward_vector,
                in_degree=in_degree,
                out_degree=out_degree,
                in_edges=in_edges,
                out_edges=out_edges,
                reverse_edges=reverse_edges,
            )
            _add_directed_edge(
                road=road,
                road_index=road_index,
                src=target_semantic,
                dst=source_semantic,
                vector=(-forward_vector[0], -forward_vector[1]),
                in_degree=in_degree,
                out_degree=out_degree,
                in_edges=in_edges,
                out_edges=out_edges,
                reverse_edges=reverse_edges,
            )
        elif road.direction == 2:
            _add_directed_edge(
                road=road,
                road_index=road_index,
                src=source_semantic,
                dst=target_semantic,
                vector=_road_vector_for_direction(road, src_is_snode=True),
                in_degree=in_degree,
                out_degree=out_degree,
                in_edges=in_edges,
                out_edges=out_edges,
                reverse_edges=reverse_edges,
            )
        elif road.direction == 3:
            _add_directed_edge(
                road=road,
                road_index=road_index,
                src=target_semantic,
                dst=source_semantic,
                vector=_road_vector_for_direction(road, src_is_snode=False),
                in_degree=in_degree,
                out_degree=out_degree,
                in_edges=in_edges,
                out_edges=out_edges,
                reverse_edges=reverse_edges,
            )
        else:
            direction_errors.append(f"direction_invalid:road_id={road.road_id}:value={road.direction}")

    return Topology(
        in_degree=dict(in_degree),
        out_degree=dict(out_degree),
        in_edges={key: tuple(value) for key, value in in_edges.items()},
        out_edges={key: tuple(value) for key, value in out_edges.items()},
        reverse_edges={key: tuple(value) for key, value in reverse_edges.items()},
        incident_road_indices={key: frozenset(value) for key, value in incident_road_indices.items()},
        internal_road_count=internal_road_count,
        direction_errors=tuple(direction_errors),
    )


def _add_directed_edge(
    *,
    road: ParsedRoad,
    road_index: int,
    src: str,
    dst: str,
    vector: tuple[float, float],
    in_degree: dict[str, int],
    out_degree: dict[str, int],
    in_edges: dict[str, list[DirectedEdge]],
    out_edges: dict[str, list[DirectedEdge]],
    reverse_edges: dict[str, list[DirectedEdge]],
) -> None:
    edge = DirectedEdge(
        src=src,
        dst=dst,
        road_idx=road_index,
        road_id=road.road_id,
        length_m=road.length_m,
        vector=vector,
    )
    reverse = DirectedEdge(
        src=edge.dst,
        dst=edge.src,
        road_idx=edge.road_idx,
        road_id=edge.road_id,
        length_m=edge.length_m,
        vector=(-edge.vector[0], -edge.vector[1]),
    )
    out_degree[edge.src] += 1
    in_degree[edge.dst] += 1
    out_edges[edge.src].append(edge)
    in_edges[edge.dst].append(edge)
    reverse_edges[edge.dst].append(reverse)


def _detect_junction_type_errors(
    *,
    semantic_nodes: dict[str, SemanticNode],
    parsed_roads: list[ParsedRoad],
    topology: Topology,
    trace_distance_m: float,
    angle_tolerance_degrees: float,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    seen_error_keys: set[tuple[str, str, str]] = set()

    for index, semantic in enumerate(semantic_nodes.values(), start=1):
        kind_2 = semantic.representative.kind_2
        in_count = int(topology.in_degree.get(semantic.semantic_id, 0))
        out_count = int(topology.out_degree.get(semantic.semantic_id, 0))
        if kind_2 == T_KIND_VALUE and (in_count != 2 or out_count != 2):
            _append_error(
                errors,
                seen_error_keys=seen_error_keys,
                semantic=semantic,
                topology=topology,
                parsed_roads=parsed_roads,
                error_type=ERROR_T_JUNCTION,
                error_reason="kind_2=2048 requires in_degree=2 and out_degree=2",
                group_id=f"t_error_{semantic.semantic_id}",
                related_node_ids=(semantic.semantic_id,),
                related_road_indices=topology.incident_road_indices.get(semantic.semantic_id, frozenset()),
                audit={"in_degree": in_count, "out_degree": out_count},
            )
        if kind_2 == CROSS_KIND_VALUE and in_count == 2 and out_count == 2:
            _append_error(
                errors,
                seen_error_keys=seen_error_keys,
                semantic=semantic,
                topology=topology,
                parsed_roads=parsed_roads,
                error_type=ERROR_CROSS_JUNCTION,
                error_reason="kind_2=4 has T-junction degree signature in_degree=2 and out_degree=2",
                group_id=f"cross_error_{semantic.semantic_id}",
                related_node_ids=(semantic.semantic_id,),
                related_road_indices=topology.incident_road_indices.get(semantic.semantic_id, frozenset()),
                audit={"in_degree": in_count, "out_degree": out_count},
            )
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool4] checked {index} semantic junction(s)")

    divmerge_rows = _detect_continuous_divmerge_as_t(
        semantic_nodes=semantic_nodes,
        parsed_roads=parsed_roads,
        topology=topology,
        trace_distance_m=trace_distance_m,
        angle_tolerance_degrees=angle_tolerance_degrees,
    )
    for row in divmerge_rows:
        for semantic_id in row["related_node_ids"]:
            semantic = semantic_nodes[semantic_id]
            _append_error(
                errors,
                seen_error_keys=seen_error_keys,
                semantic=semantic,
                topology=topology,
                parsed_roads=parsed_roads,
                error_type=ERROR_DIVMERGE_JUNCTION,
                error_reason="kind_2=16/8 continuous divmerge has T-junction topology signature",
                group_id=row["group_id"],
                related_node_ids=tuple(row["related_node_ids"]),
                related_road_indices=frozenset(row["related_road_indices"]),
                audit=row["audit"],
            )

    return sorted(errors, key=lambda row: (_sort_key(str(row["semantic_node_id"])), str(row["error_type"])))


def _detect_continuous_divmerge_as_t(
    *,
    semantic_nodes: dict[str, SemanticNode],
    parsed_roads: list[ParsedRoad],
    topology: Topology,
    trace_distance_m: float,
    angle_tolerance_degrees: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for semantic_id, semantic in sorted(semantic_nodes.items(), key=lambda item: _sort_key(item[0])):
        if semantic.representative.kind_2 != DIVERGE_KIND_VALUE:
            continue
        if int(topology.out_degree.get(semantic_id, 0)) != 2:
            continue
        incoming_edges = sorted(topology.in_edges.get(semantic_id, ()), key=_edge_sort_key)
        outgoing_edges = sorted(topology.out_edges.get(semantic_id, ()), key=_edge_sort_key)
        if len(outgoing_edges) != 2 or not incoming_edges:
            continue
        incoming_edge = max(incoming_edges, key=lambda edge: (edge.length_m, str(edge.road_id)))
        main_edge, side_edge = _split_main_and_side_edges(incoming_edge, outgoing_edges)
        main_trace = _trace_forward_to_kind(
            start_node_id=semantic_id,
            first_edge=main_edge,
            target_kind=MERGE_KIND_VALUE,
            semantic_nodes=semantic_nodes,
            topology=topology,
            max_distance_m=trace_distance_m,
        )
        if main_trace is None:
            continue
        merge_id = main_trace.node_id
        merge = semantic_nodes.get(merge_id)
        if merge is None or merge.representative.kind_2 != MERGE_KIND_VALUE:
            continue
        if int(topology.in_degree.get(merge_id, 0)) != 2:
            continue
        pair_key = (semantic_id, merge_id)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        merge_out_edges = sorted(topology.out_edges.get(merge_id, ()), key=_edge_sort_key)
        if not merge_out_edges:
            continue
        merge_out = min(merge_out_edges, key=lambda edge: (_angle_between(main_trace.last_vector, edge.vector), _edge_sort_key(edge)))
        horizontal_ok = (
            _angle_between(incoming_edge.vector, main_edge.vector) <= angle_tolerance_degrees
            and _angle_between(main_trace.last_vector, merge_out.vector) <= angle_tolerance_degrees
        )
        if not horizontal_ok:
            continue

        main_path_roads = set(main_trace.path_road_indices)
        merge_side_inputs = [
            edge for edge in sorted(topology.in_edges.get(merge_id, ()), key=_edge_sort_key) if edge.road_idx not in main_path_roads
        ]
        if not merge_side_inputs:
            continue
        merge_side_in = merge_side_inputs[0]
        merge_back_first = _reverse_edge(merge_side_in)
        immediate_same_node = side_edge.dst == merge_back_first.dst
        if immediate_same_node:
            side_trace = TraceResult(
                node_id=side_edge.dst,
                distance_m=side_edge.length_m,
                path_road_indices=(side_edge.road_idx,),
                first_vector=side_edge.vector,
                last_vector=side_edge.vector,
            )
            merge_back_trace = TraceResult(
                node_id=merge_back_first.dst,
                distance_m=merge_back_first.length_m,
                path_road_indices=(merge_back_first.road_idx,),
                first_vector=merge_back_first.vector,
                last_vector=merge_back_first.vector,
            )
        else:
            side_trace = _trace_through_degree2(
                first_edge=side_edge,
                topology=topology,
                max_distance_m=trace_distance_m,
                forward=True,
            )
            merge_back_trace = _trace_through_degree2(
                first_edge=merge_back_first,
                topology=topology,
                max_distance_m=trace_distance_m,
                forward=False,
            )
        if side_trace is None or merge_back_trace is None:
            continue
        start_distance = semantic.representative.geometry.distance(merge.representative.geometry)
        end_distance = semantic_nodes[side_trace.node_id].representative.geometry.distance(
            semantic_nodes[merge_back_trace.node_id].representative.geometry
        )
        vertical_same_node = immediate_same_node or side_trace.node_id == merge_back_trace.node_id
        vertical_parallel_shortening = (
            end_distance < start_distance
            and _angle_between(side_trace.first_vector, merge_back_trace.first_vector) <= angle_tolerance_degrees
        )
        if not (vertical_same_node or vertical_parallel_shortening):
            continue

        related_road_indices = set(main_trace.path_road_indices)
        related_road_indices.update(side_trace.path_road_indices)
        related_road_indices.update(merge_back_trace.path_road_indices)
        related_road_indices.add(incoming_edge.road_idx)
        related_road_indices.add(merge_out.road_idx)
        rows.append(
            {
                "group_id": f"divmerge_as_t_{semantic_id}_{merge_id}",
                "related_node_ids": (semantic_id, merge_id),
                "related_road_indices": tuple(sorted(related_road_indices)),
                "audit": {
                    "diverge_node_id": semantic_id,
                    "merge_node_id": merge_id,
                    "incoming_road_id": incoming_edge.road_id,
                    "main_branch_road_id": main_edge.road_id,
                    "side_branch_road_id": side_edge.road_id,
                    "merge_side_road_id": merge_side_in.road_id,
                    "merge_out_road_id": merge_out.road_id,
                    "main_trace_distance_m": round(main_trace.distance_m, 3),
                    "side_trace_node_id": side_trace.node_id,
                    "merge_back_trace_node_id": merge_back_trace.node_id,
                    "vertical_same_node": vertical_same_node,
                    "vertical_parallel_shortening": vertical_parallel_shortening,
                    "start_distance_m": round(float(start_distance), 3),
                    "end_distance_m": round(float(end_distance), 3),
                    "angle_tolerance_degrees": float(angle_tolerance_degrees),
                },
            }
        )
    return rows


def _split_main_and_side_edges(
    incoming_edge: DirectedEdge,
    outgoing_edges: list[DirectedEdge],
) -> tuple[DirectedEdge, DirectedEdge]:
    sorted_edges = sorted(
        outgoing_edges,
        key=lambda edge: (_angle_between(incoming_edge.vector, edge.vector), _edge_sort_key(edge)),
    )
    return sorted_edges[0], sorted_edges[1]


def _trace_forward_to_kind(
    *,
    start_node_id: str,
    first_edge: DirectedEdge,
    target_kind: int,
    semantic_nodes: dict[str, SemanticNode],
    topology: Topology,
    max_distance_m: float,
) -> TraceResult | None:
    return _trace_edges(
        start_node_id=start_node_id,
        first_edge=first_edge,
        edge_map=topology.out_edges,
        incident_road_indices=topology.incident_road_indices,
        max_distance_m=max_distance_m,
        stop_predicate=lambda node_id: semantic_nodes.get(node_id) is not None
        and semantic_nodes[node_id].representative.kind_2 == target_kind,
    )


def _trace_through_degree2(
    *,
    first_edge: DirectedEdge,
    topology: Topology,
    max_distance_m: float,
    forward: bool,
) -> TraceResult | None:
    edge_map = topology.out_edges if forward else topology.reverse_edges
    return _trace_edges(
        start_node_id=first_edge.src,
        first_edge=first_edge,
        edge_map=edge_map,
        incident_road_indices=topology.incident_road_indices,
        max_distance_m=max_distance_m,
        stop_predicate=lambda _node_id: False,
        return_on_non_degree2=True,
    )


def _trace_edges(
    *,
    start_node_id: str,
    first_edge: DirectedEdge,
    edge_map: dict[str, tuple[DirectedEdge, ...]],
    incident_road_indices: dict[str, frozenset[int]],
    max_distance_m: float,
    stop_predicate: Callable[[str], bool],
    return_on_non_degree2: bool = False,
) -> TraceResult | None:
    total = float(max(0.0, first_edge.length_m))
    if total > max_distance_m + 1e-9:
        return None
    prev_node = start_node_id
    curr_node = first_edge.dst
    path_roads = [first_edge.road_idx]
    last_vector = first_edge.vector

    for _ in range(256):
        if stop_predicate(curr_node):
            return TraceResult(
                node_id=curr_node,
                distance_m=total,
                path_road_indices=tuple(path_roads),
                first_vector=first_edge.vector,
                last_vector=last_vector,
            )
        incident_degree = len(incident_road_indices.get(curr_node, frozenset()))
        if incident_degree != 2:
            if return_on_non_degree2:
                return TraceResult(
                    node_id=curr_node,
                    distance_m=total,
                    path_road_indices=tuple(path_roads),
                    first_vector=first_edge.vector,
                    last_vector=last_vector,
                )
            return None
        candidates = [
            edge
            for edge in edge_map.get(curr_node, ())
            if edge.road_idx not in path_roads and edge.dst != prev_node
        ]
        if len(candidates) != 1:
            if return_on_non_degree2:
                return TraceResult(
                    node_id=curr_node,
                    distance_m=total,
                    path_road_indices=tuple(path_roads),
                    first_vector=first_edge.vector,
                    last_vector=last_vector,
                )
            return None
        next_edge = candidates[0]
        total += float(max(0.0, next_edge.length_m))
        if total > max_distance_m + 1e-9:
            return None
        path_roads.append(next_edge.road_idx)
        prev_node = curr_node
        curr_node = next_edge.dst
        last_vector = next_edge.vector
    return None


def _append_error(
    errors: list[dict[str, Any]],
    *,
    seen_error_keys: set[tuple[str, str, str]],
    semantic: SemanticNode,
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    error_type: str,
    error_reason: str,
    group_id: str,
    related_node_ids: tuple[str, ...],
    related_road_indices: frozenset[int] | tuple[int, ...],
    audit: dict[str, Any],
) -> None:
    key = (semantic.semantic_id, error_type, group_id)
    if key in seen_error_keys:
        return
    seen_error_keys.add(key)
    related_road_ids = tuple(
        sorted((parsed_roads[index].road_id for index in related_road_indices), key=_sort_key)
    )
    errors.append(
        {
            "id": f"{semantic.semantic_id}_{len(errors) + 1}",
            "semantic_node_id": semantic.semantic_id,
            "source_node_id": semantic.representative.node_id,
            "kind_2": semantic.representative.kind_2,
            "error_type": error_type,
            "error_reason": error_reason,
            "error_group_id": group_id,
            "in_degree": int(topology.in_degree.get(semantic.semantic_id, 0)),
            "out_degree": int(topology.out_degree.get(semantic.semantic_id, 0)),
            "related_node_ids": ",".join(sorted((str(node_id) for node_id in related_node_ids), key=_sort_key)),
            "related_road_ids": ",".join(related_road_ids),
            "audit_json": audit,
            "geometry": semantic.representative.geometry,
        }
    )


def _build_error_features(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for row in errors:
        properties = {key: value for key, value in row.items() if key != "geometry"}
        features.append({"properties": properties, "geometry": row["geometry"]})
    return features


def _summary_error_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "geometry"}


def _road_vector_for_direction(road: ParsedRoad, *, src_is_snode: bool) -> tuple[float, float]:
    coords = list(road.geometry.coords) if hasattr(road.geometry, "coords") else list(road.geometry.boundary.coords)
    if len(coords) < 2:
        return (0.0, 0.0)
    start = coords[0]
    end = coords[-1]
    if src_is_snode:
        return _unit_vector((float(end[0]) - float(start[0]), float(end[1]) - float(start[1])))
    return _unit_vector((float(start[0]) - float(end[0]), float(start[1]) - float(end[1])))


def _reverse_edge(edge: DirectedEdge) -> DirectedEdge:
    return DirectedEdge(
        src=edge.dst,
        dst=edge.src,
        road_idx=edge.road_idx,
        road_id=edge.road_id,
        length_m=edge.length_m,
        vector=(-edge.vector[0], -edge.vector[1]),
    )


def _angle_between(left: tuple[float, float], right: tuple[float, float]) -> float:
    left_len = math.hypot(left[0], left[1])
    right_len = math.hypot(right[0], right[1])
    if left_len <= 1e-12 or right_len <= 1e-12:
        return 180.0
    dot = (left[0] * right[0] + left[1] * right[1]) / (left_len * right_len)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _unit_vector(value: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(value[0], value[1])
    if length <= 1e-12:
        return (0.0, 0.0)
    return (float(value[0]) / length, float(value[1]) / length)


def _optional_field(features: list[VectorFeature], candidates: list[str]) -> str | None:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    return None


def _required_id(value: Any, label: str) -> str:
    normalized = _normalize_id(value)
    if normalized is None:
        raise ValueError(f"Missing required {label}")
    return normalized


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "nan"}:
            return None
        return text
    return value


def _normalize_id(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, int):
        return str(normalized)
    if isinstance(normalized, float) and normalized.is_integer():
        return str(int(normalized))
    return str(normalized)


def _valid_mainnodeid(value: Any) -> str | None:
    normalized = _normalize_id(value)
    if normalized in {None, "0", "0.0"}:
        return None
    return normalized


def _coerce_int(value: Any) -> int | None:
    normalized = _normalize_scalar(value)
    if normalized is None or isinstance(normalized, bool):
        return None
    if isinstance(normalized, int):
        return int(normalized)
    if isinstance(normalized, float):
        return int(normalized) if normalized.is_integer() else None
    try:
        return int(str(normalized), 10)
    except ValueError:
        try:
            parsed = float(str(normalized))
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


def _edge_sort_key(edge: DirectedEdge) -> tuple[tuple[int, int | str], tuple[int, int | str], tuple[int, int | str]]:
    return _sort_key(edge.src), _sort_key(edge.dst), _sort_key(edge.road_id)


def _sort_key(value: Any) -> tuple[int, int | str]:
    text = str(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _elapsed_since(started: float) -> float:
    return time.perf_counter() - started


def _items_per_second(count: int, elapsed_seconds: float) -> float | None:
    if elapsed_seconds <= 0:
        return None
    return round(float(count) / float(elapsed_seconds), 6)


def _should_emit_progress(index: int, progress_interval: int) -> bool:
    return progress_interval > 0 and index % progress_interval == 0


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
