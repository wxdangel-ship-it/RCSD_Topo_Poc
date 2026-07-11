from __future__ import annotations

import csv

import json

import math

import time

from collections import defaultdict

from collections.abc import Callable

from dataclasses import dataclass

from pathlib import Path

from typing import Any

from shapely.geometry import Point

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name

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

DIVERGE_KIND_2 = 16

MERGE_KIND_2 = 8

CROSS_KIND_2 = 4

ERROR_DIVMERGE = "错误分歧合流路口"

ERROR_CROSS_T = "错误交叉路口_T型路口"

ERROR_CROSS_NON_CROSS = "错误交叉路口_非交叉路口"

ERROR_CROSS_DIVERGE = "错误交叉路口_分歧路口"

ERROR_CROSS_MERGE = "错误交叉路口_合流路口"

MANUAL_FIX_FIELD = "是否修复"

MANUAL_FIX_DEFAULT = 1

CROSS_ANGLE_TRACE_DISTANCE_M = 20.0

ProgressCallback = Callable[[str], None]

CSV_FIELDS = [
    "error_id",
    "error_group_id",
    "error_type",
    "semantic_node_id",
    "source_node_id",
    "role",
    "kind_2",
    "in_degree",
    "out_degree",
    "paired_semantic_node_id",
    "related_node_ids",
    "related_road_ids",
    "reason",
    "audit_json",
    MANUAL_FIX_FIELD,
]

__all__ = [
    "T08NodesTypeQcArtifacts",
    "run_t08_nodes_type_qc",
]


from . import nodes_type_qc as _facade


def ParsedRoad(*args: Any, **kwargs: Any) -> Any:
    return _facade.ParsedRoad(*args, **kwargs)


def SemanticNode(*args: Any, **kwargs: Any) -> Any:
    return _facade.SemanticNode(*args, **kwargs)


def T08NodesTypeQcArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T08NodesTypeQcArtifacts(*args, **kwargs)


def Topology(*args: Any, **kwargs: Any) -> Any:
    return _facade.Topology(*args, **kwargs)


def _all_incident_roads_oneway(*args: Any, **kwargs: Any) -> Any:
    return _facade._all_incident_roads_oneway(*args, **kwargs)


def _angle_degrees(*args: Any, **kwargs: Any) -> Any:
    return _facade._angle_degrees(*args, **kwargs)


def _angle_group_audit(*args: Any, **kwargs: Any) -> Any:
    return _facade._angle_group_audit(*args, **kwargs)


def _angle_group_has_in_and_out(*args: Any, **kwargs: Any) -> Any:
    return _facade._angle_group_has_in_and_out(*args, **kwargs)


def _angle_groups_are_parallel(*args: Any, **kwargs: Any) -> Any:
    return _facade._angle_groups_are_parallel(*args, **kwargs)


def _build_semantic_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_semantic_nodes(*args, **kwargs)


def _build_topology(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_topology(*args, **kwargs)


def _choose_merge_out_edge(*args: Any, **kwargs: Any) -> Any:
    return _facade._choose_merge_out_edge(*args, **kwargs)


def _choose_merge_side_in_edge(*args: Any, **kwargs: Any) -> Any:
    return _facade._choose_merge_side_in_edge(*args, **kwargs)


def _cross(*args: Any, **kwargs: Any) -> Any:
    return _facade._cross(*args, **kwargs)


def _cross_non_cross_classification(*args: Any, **kwargs: Any) -> Any:
    return _facade._cross_non_cross_classification(*args, **kwargs)


def _elapsed_since(*args: Any, **kwargs: Any) -> Any:
    return _facade._elapsed_since(*args, **kwargs)


def _emit_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._emit_progress(*args, **kwargs)


def _error_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._error_row(*args, **kwargs)


def _find_cross_t_pattern(*args: Any, **kwargs: Any) -> Any:
    return _facade._find_cross_t_pattern(*args, **kwargs)


def _find_cross_t_pattern_by_same_remote_pair(*args: Any, **kwargs: Any) -> Any:
    return _facade._find_cross_t_pattern_by_same_remote_pair(*args, **kwargs)


def _group_incident_legs_by_outward_angle(*args: Any, **kwargs: Any) -> Any:
    return _facade._group_incident_legs_by_outward_angle(*args, **kwargs)


def _has_kind_suffix(*args: Any, **kwargs: Any) -> Any:
    return _facade._has_kind_suffix(*args, **kwargs)


def _has_only_two_bidirectional_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._has_only_two_bidirectional_roads(*args, **kwargs)


def _incident_legs_for_semantic(*args: Any, **kwargs: Any) -> Any:
    return _facade._incident_legs_for_semantic(*args, **kwargs)


def _items_per_second(*args: Any, **kwargs: Any) -> Any:
    return _facade._items_per_second(*args, **kwargs)


def _left_right_edges(*args: Any, **kwargs: Any) -> Any:
    return _facade._left_right_edges(*args, **kwargs)


def _oneway_vertical_connects_diverge_and_merge(*args: Any, **kwargs: Any) -> Any:
    return _facade._oneway_vertical_connects_diverge_and_merge(*args, **kwargs)


def _optional_field(*args: Any, **kwargs: Any) -> Any:
    return _facade._optional_field(*args, **kwargs)


def _parse_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._parse_nodes(*args, **kwargs)


def _parse_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._parse_roads(*args, **kwargs)


def _related_divmerge_road_indices(*args: Any, **kwargs: Any) -> Any:
    return _facade._related_divmerge_road_indices(*args, **kwargs)


def _reverse_edge(*args: Any, **kwargs: Any) -> Any:
    return _facade._reverse_edge(*args, **kwargs)


def _road_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_ids(*args, **kwargs)


def _should_emit_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._should_emit_progress(*args, **kwargs)


def _sort_key(*args: Any, **kwargs: Any) -> Any:
    return _facade._sort_key(*args, **kwargs)


def _suppressed_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._suppressed_row(*args, **kwargs)


def _trace_branch(*args: Any, **kwargs: Any) -> Any:
    return _facade._trace_branch(*args, **kwargs)


def _trace_to_merge(*args: Any, **kwargs: Any) -> Any:
    return _facade._trace_to_merge(*args, **kwargs)


def _trace_vector(*args: Any, **kwargs: Any) -> Any:
    return _facade._trace_vector(*args, **kwargs)


def _write_csv(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_csv(*args, **kwargs)


def run_t08_nodes_type_qc(
    *,
    nodes_gpkg: str | Path,
    roads_gpkg: str | Path,
    csv_output: str | Path,
    error_nodes_output: str | Path,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    nodes_default_crs_text: str | None = None,
    roads_default_crs_text: str | None = None,
    divmerge_search_distance_m: float = 100.0,
    vertical_parallel_angle_degrees: float = 20.0,
    vertical_endpoint_distance_m: float = 20.0,
    horizontal_angle_degrees: float = 35.0,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08NodesTypeQcArtifacts:
    started = time.perf_counter()
    nodes_path = ensure_gpkg_path(nodes_gpkg, label="--nodes-gpkg")
    roads_path = ensure_gpkg_path(roads_gpkg, label="--roads-gpkg")
    csv_path = ensure_tool_output_name(csv_output, tool_number=6, label="--csv-output")
    error_nodes_path = ensure_tool_output_name(
        ensure_gpkg_path(error_nodes_output, label="--error-nodes-output"),
        tool_number=6,
        label="--error-nodes-output",
    )
    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=6, label="--summary-output")
        if summary_output
        else csv_path.with_name("node_error_summary_tool6.json")
    )

    _emit_progress(progress_callback, f"[T08 Tool6] start nodes={nodes_path} roads={roads_path}")
    read_started = time.perf_counter()
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
    read_seconds = _elapsed_since(read_started)

    node_id_field = resolve_field_name(nodes_result.features, ["id"], "nodes input")
    node_kind_2_field = resolve_field_name(nodes_result.features, ["kind_2"], "nodes input")
    node_mainnodeid_field = _optional_field(nodes_result.features, ["mainnodeid"])
    road_id_field = resolve_field_name(roads_result.features, ["id"], "roads input")
    road_snode_field = resolve_field_name(roads_result.features, ["snodeid"], "roads input")
    road_enode_field = resolve_field_name(roads_result.features, ["enodeid"], "roads input")
    road_direction_field = resolve_field_name(roads_result.features, ["direction"], "roads input")
    road_kind_field = _optional_field(roads_result.features, ["kind"])

    parsed_nodes = _parse_nodes(
        nodes_result.features,
        node_id_field=node_id_field,
        node_kind_2_field=node_kind_2_field,
        node_mainnodeid_field=node_mainnodeid_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    node_geometries = {node.node_id: node.geometry for node in parsed_nodes}
    parsed_roads = _parse_roads(
        roads_result.features,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        road_kind_field=road_kind_field,
        node_geometries=node_geometries,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    semantic_nodes = _build_semantic_nodes(parsed_nodes)
    node_to_semantic = {node.node_id: node.semantic_id for node in parsed_nodes}
    topology = _build_topology(parsed_roads, node_to_semantic=node_to_semantic)

    detect_started = time.perf_counter()
    divmerge_rows, divmerge_suppressed = _detect_divmerge_errors(
        semantic_nodes=semantic_nodes,
        topology=topology,
        parsed_roads=parsed_roads,
        search_distance_m=divmerge_search_distance_m,
        vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
        vertical_endpoint_distance_m=vertical_endpoint_distance_m,
        horizontal_angle_degrees=horizontal_angle_degrees,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    cross_rows = _detect_cross_errors(
        semantic_nodes=semantic_nodes,
        topology=topology,
        parsed_roads=parsed_roads,
        vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
        horizontal_angle_degrees=horizontal_angle_degrees,
    )
    error_rows = sorted(
        [*divmerge_rows, *cross_rows],
        key=lambda row: (_sort_key(str(row["semantic_node_id"])), str(row["error_type"]), str(row["role"])),
    )
    detect_seconds = _elapsed_since(detect_started)

    _write_csv(csv_path, error_rows)
    gpkg_features = [
        {
            "properties": {field: row.get(field) for field in CSV_FIELDS},
            "geometry": row["geometry"],
        }
        for row in error_rows
    ]
    write_gpkg(
        error_nodes_path,
        gpkg_features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=CSV_FIELDS,
        geometry_type="Point",
    )
    elapsed_seconds = _elapsed_since(started)
    counts_by_type: dict[str, int] = defaultdict(int)
    for row in error_rows:
        counts_by_type[str(row["error_type"])] += 1
    summary = {
        "tool": "T08 Tool6",
        "stage": "nodes_type_qc",
        "target_epsg": target_epsg,
        "input_paths": {"nodes_gpkg": nodes_path, "roads_gpkg": roads_path},
        "output_paths": {
            "csv_output": csv_path,
            "error_nodes_output": error_nodes_path,
            "summary_output": summary_path,
        },
        "input_crs": {
            "nodes": nodes_result.source_crs.to_string(),
            "nodes_crs_source": nodes_result.crs_source,
            "roads": roads_result.source_crs.to_string(),
            "roads_crs_source": roads_result.crs_source,
        },
        "params": {
            "nodes_layer": nodes_layer,
            "roads_layer": roads_layer,
            "divmerge_search_distance_m": divmerge_search_distance_m,
            "vertical_parallel_angle_degrees": vertical_parallel_angle_degrees,
            "vertical_endpoint_distance_m": vertical_endpoint_distance_m,
            "horizontal_angle_degrees": horizontal_angle_degrees,
            "manual_fix_default": MANUAL_FIX_DEFAULT,
        },
        "field_audit": {
            "node_id_field": node_id_field,
            "node_kind_2_field": node_kind_2_field,
            "node_mainnodeid_field": node_mainnodeid_field,
            "road_id_field": road_id_field,
            "road_snode_field": road_snode_field,
            "road_enode_field": road_enode_field,
            "road_direction_field": road_direction_field,
            "road_kind_field": road_kind_field,
        },
        "counts": {
            "node_feature_count": len(parsed_nodes),
            "semantic_node_count": len(semantic_nodes),
            "road_feature_count": len(parsed_roads),
            "topology_road_count": len(parsed_roads) - len(topology.skipped_missing_node_roads),
            "error_feature_count": len(error_rows),
            "error_count_by_type": dict(sorted(counts_by_type.items())),
            "divmerge_error_group_count": len({row["error_group_id"] for row in divmerge_rows}),
            "cross_error_count": len(cross_rows),
            "divmerge_suppressed_count": len(divmerge_suppressed),
            "internal_road_count": topology.internal_road_count,
            "direction_error_count": len(topology.direction_errors),
            "skipped_missing_node_road_count": len(topology.skipped_missing_node_roads),
        },
        "direction_errors": list(topology.direction_errors),
        "skipped_missing_node_roads": list(topology.skipped_missing_node_roads),
        "divmerge_suppressed": divmerge_suppressed,
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in gpkg_features),
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "read_inputs_seconds": round(read_seconds, 6),
            "detect_errors_seconds": round(detect_seconds, 6),
            "semantic_nodes_per_second": _items_per_second(len(semantic_nodes), elapsed_seconds),
        },
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        f"[T08 Tool6] finished errors={len(error_rows)} elapsed={elapsed_seconds:.2f}s summary={summary_path}",
    )
    return T08NodesTypeQcArtifacts(
        csv_output=csv_path,
        error_nodes_output=error_nodes_path,
        summary_output=summary_path,
    )


def _detect_divmerge_errors(
    *,
    semantic_nodes: dict[str, SemanticNode],
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    search_distance_m: float,
    vertical_parallel_angle_degrees: float,
    vertical_endpoint_distance_m: float,
    horizontal_angle_degrees: float,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    candidates = [
        semantic
        for semantic in semantic_nodes.values()
        if semantic.representative.kind_2 == DIVERGE_KIND_2
        and int(topology.in_degree.get(semantic.semantic_id, 0)) == 1
        and int(topology.out_degree.get(semantic.semantic_id, 0)) == 2
    ]
    for index, diverge in enumerate(sorted(candidates, key=lambda item: _sort_key(item.semantic_id)), start=1):
        result = _evaluate_divmerge_candidate(
            diverge=diverge,
            semantic_nodes=semantic_nodes,
            topology=topology,
            parsed_roads=parsed_roads,
            search_distance_m=search_distance_m,
            vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
            vertical_endpoint_distance_m=vertical_endpoint_distance_m,
            horizontal_angle_degrees=horizontal_angle_degrees,
        )
        if result is None:
            continue
        if result["status"] == "suppressed":
            suppressed.append(result)
            continue
        group_id = str(result["error_group_id"])
        if group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        rows.extend(result["rows"])
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool6] divmerge: checked {index} candidate(s)")
    return rows, suppressed


def _evaluate_divmerge_candidate(
    *,
    diverge: SemanticNode,
    semantic_nodes: dict[str, SemanticNode],
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    search_distance_m: float,
    vertical_parallel_angle_degrees: float,
    vertical_endpoint_distance_m: float,
    horizontal_angle_degrees: float,
) -> dict[str, Any] | None:
    in_edges = topology.in_edges.get(diverge.semantic_id, ())
    out_edges = topology.out_edges.get(diverge.semantic_id, ())
    if not in_edges or len(out_edges) < 2:
        return None

    for incoming in sorted(in_edges, key=lambda edge: (_sort_key(edge.road_id), _sort_key(edge.src))):
        outgoing = [edge for edge in out_edges if edge.road_idx != incoming.road_idx]
        if len(outgoing) != 2:
            continue
        left_edge, right_edge = _left_right_edges(incoming.vector, outgoing)
        merge_trace = _trace_to_merge(
            first_edge=left_edge,
            semantic_nodes=semantic_nodes,
            topology=topology,
            search_distance_m=search_distance_m,
        )
        if merge_trace is None:
            continue
        merge = semantic_nodes.get(merge_trace.end_semantic_id)
        if merge is None or merge.representative.kind_2 != MERGE_KIND_2:
            continue
        if int(topology.in_degree.get(merge.semantic_id, 0)) != 2 or int(topology.out_degree.get(merge.semantic_id, 0)) != 1:
            continue
        start_distance = diverge.representative.geometry.distance(merge.representative.geometry)
        if start_distance > search_distance_m:
            continue

        merge_out = _choose_merge_out_edge(
            merge_id=merge.semantic_id,
            left_edge=left_edge,
            left_trace=merge_trace,
            topology=topology,
        )
        merge_side_in = _choose_merge_side_in_edge(
            merge_id=merge.semantic_id,
            left_trace=merge_trace,
            horizontal_vector=left_edge.vector,
            topology=topology,
        )
        if merge_out is None or merge_side_in is None:
            continue
        horizontal_angle = max(
            _angle_degrees(incoming.vector, left_edge.vector),
            _angle_degrees(left_edge.vector, merge_out.vector),
        )
        if horizontal_angle > horizontal_angle_degrees:
            continue
        merge_side_reverse = _reverse_edge(merge_side_in)
        if _cross(left_edge.vector, right_edge.vector) >= 0 or _cross(left_edge.vector, merge_side_reverse.vector) >= 0:
            return _suppressed_row(
                diverge=diverge,
                merge=merge,
                reason="vertical_not_on_right_side_of_horizontal",
                related_road_indices=_related_divmerge_road_indices(
                    incoming,
                    left_edge,
                    right_edge,
                    merge_trace,
                    merge_out,
                    merge_side_reverse,
                    (),
                    (),
                ),
                parsed_roads=parsed_roads,
            )

        right_trace = _trace_branch(
            first_edge=right_edge,
            semantic_nodes=semantic_nodes,
            topology=topology,
            max_distance_m=search_distance_m,
        )
        merge_side_trace = _trace_branch(
            first_edge=merge_side_reverse,
            semantic_nodes=semantic_nodes,
            topology=topology,
            max_distance_m=search_distance_m,
        )
        if _oneway_vertical_connects_diverge_and_merge(
            right_trace=right_trace,
            merge_side_trace=merge_side_trace,
            diverge_id=diverge.semantic_id,
            merge_id=merge.semantic_id,
            parsed_roads=parsed_roads,
        ):
            return _suppressed_row(
                diverge=diverge,
                merge=merge,
                reason="oneway_vertical_connects_diverge_and_merge",
                related_road_indices=_related_divmerge_road_indices(
                    incoming,
                    left_edge,
                    right_edge,
                    merge_trace,
                    merge_out,
                    merge_side_reverse,
                    right_trace.path_road_indices,
                    merge_side_trace.path_road_indices,
                ),
                parsed_roads=parsed_roads,
            )
        same_endpoint = right_trace.end_semantic_id == merge_side_trace.end_semantic_id
        end_distance = right_trace.end_point.distance(merge_side_trace.end_point)
        vertical_parallel_angle = _angle_degrees(_trace_vector(diverge, right_trace), _trace_vector(merge, merge_side_trace))
        vertical_ok = same_endpoint or (
            end_distance < start_distance
            and end_distance < vertical_endpoint_distance_m
            and vertical_parallel_angle <= vertical_parallel_angle_degrees
        )
        related_indices = _related_divmerge_road_indices(
            incoming,
            left_edge,
            right_edge,
            merge_trace,
            merge_out,
            merge_side_reverse,
            right_trace.path_road_indices,
            merge_side_trace.path_road_indices,
        )
        if _has_kind_suffix(parsed_roads, related_indices, "17"):
            return _suppressed_row(
                diverge=diverge,
                merge=merge,
                reason="associated_road_kind_suffix_17",
                related_road_indices=related_indices,
                parsed_roads=parsed_roads,
            )
        if not vertical_ok:
            continue
        group_id = f"divmerge_t_{diverge.semantic_id}_{merge.semantic_id}"
        related_node_ids = tuple(sorted(set(diverge.member_node_ids + merge.member_node_ids), key=_sort_key))
        related_road_ids = _road_ids(parsed_roads, related_indices)
        audit = {
            "diverge_id": diverge.semantic_id,
            "merge_id": merge.semantic_id,
            "incoming_road_id": incoming.road_id,
            "left_road_id": left_edge.road_id,
            "right_road_id": right_edge.road_id,
            "merge_out_road_id": merge_out.road_id,
            "merge_side_road_id": merge_side_in.road_id,
            "left_trace_distance_m": round(float(merge_trace.distance_m), 3),
            "right_trace_end": right_trace.end_semantic_id,
            "merge_side_trace_end": merge_side_trace.end_semantic_id,
            "same_vertical_endpoint": same_endpoint,
            "vertical_start_distance_m": round(float(start_distance), 3),
            "vertical_end_distance_m": round(float(end_distance), 3),
            "vertical_parallel_angle_degrees": round(float(vertical_parallel_angle), 3),
            "horizontal_angle_degrees": round(float(horizontal_angle), 3),
        }
        return {
            "status": "error",
            "error_group_id": group_id,
            "rows": [
                _error_row(
                    error_id=f"{group_id}:diverge:{diverge.semantic_id}",
                    error_group_id=group_id,
                    error_type=ERROR_DIVMERGE,
                    semantic=diverge,
                    role="diverge",
                    paired_semantic_node_id=merge.semantic_id,
                    topology=topology,
                    related_node_ids=related_node_ids,
                    related_road_ids=related_road_ids,
                    reason="continuous_divmerge_matches_t_junction_pattern",
                    audit=audit,
                ),
                _error_row(
                    error_id=f"{group_id}:merge:{merge.semantic_id}",
                    error_group_id=group_id,
                    error_type=ERROR_DIVMERGE,
                    semantic=merge,
                    role="merge",
                    paired_semantic_node_id=diverge.semantic_id,
                    topology=topology,
                    related_node_ids=related_node_ids,
                    related_road_ids=related_road_ids,
                    reason="continuous_divmerge_matches_t_junction_pattern",
                    audit=audit,
                ),
            ],
        }
    return None

def _detect_cross_errors(
    *,
    semantic_nodes: dict[str, SemanticNode],
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    vertical_parallel_angle_degrees: float,
    horizontal_angle_degrees: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for semantic in semantic_nodes.values():
        if semantic.representative.kind_2 == CROSS_KIND_2:
            low_incident_classification = _classify_low_incident_cross_error(
                semantic_id=semantic.semantic_id,
                topology=topology,
                parsed_roads=parsed_roads,
                horizontal_angle_degrees=horizontal_angle_degrees,
            )
            if low_incident_classification is not None:
                group_id = f"{low_incident_classification['group_prefix']}_{semantic.semantic_id}"
                rows.append(
                    _error_row(
                        error_id=f"{group_id}:{semantic.semantic_id}",
                        error_group_id=group_id,
                        error_type=str(low_incident_classification["error_type"]),
                        semantic=semantic,
                        role=str(low_incident_classification["role"]),
                        paired_semantic_node_id="",
                        topology=topology,
                        related_node_ids=semantic.member_node_ids,
                        related_road_ids=_road_ids(parsed_roads, low_incident_classification["related_road_indices"]),
                        reason=str(low_incident_classification["reason"]),
                        audit=low_incident_classification["audit"],
                    )
                )
                continue
            divmerge_like_classification = _classify_cross_divmerge_like_error(
                semantic_id=semantic.semantic_id,
                topology=topology,
                parsed_roads=parsed_roads,
                horizontal_angle_degrees=horizontal_angle_degrees,
            )
            if divmerge_like_classification is not None:
                group_id = f"{divmerge_like_classification['group_prefix']}_{semantic.semantic_id}"
                rows.append(
                    _error_row(
                        error_id=f"{group_id}:{semantic.semantic_id}",
                        error_group_id=group_id,
                        error_type=str(divmerge_like_classification["error_type"]),
                        semantic=semantic,
                        role=str(divmerge_like_classification["role"]),
                        paired_semantic_node_id="",
                        topology=topology,
                        related_node_ids=semantic.member_node_ids,
                        related_road_ids=_road_ids(parsed_roads, divmerge_like_classification["related_road_indices"]),
                        reason=str(divmerge_like_classification["reason"]),
                        audit=divmerge_like_classification["audit"],
                    )
                )
                continue
        in_degree = int(topology.in_degree.get(semantic.semantic_id, 0))
        out_degree = int(topology.out_degree.get(semantic.semantic_id, 0))
        if semantic.representative.kind_2 == CROSS_KIND_2 and in_degree == 2 and out_degree == 2:
            classification = _classify_cross_error(
                semantic_id=semantic.semantic_id,
                topology=topology,
                parsed_roads=parsed_roads,
                semantic_nodes=semantic_nodes,
                vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
                horizontal_angle_degrees=horizontal_angle_degrees,
            )
            if classification is None:
                continue
            group_id = f"{classification['group_prefix']}_{semantic.semantic_id}"
            rows.append(
                _error_row(
                    error_id=f"{group_id}:{semantic.semantic_id}",
                    error_group_id=group_id,
                    error_type=str(classification["error_type"]),
                    semantic=semantic,
                    role=str(classification["role"]),
                    paired_semantic_node_id="",
                    topology=topology,
                    related_node_ids=semantic.member_node_ids,
                    related_road_ids=_road_ids(parsed_roads, classification["related_road_indices"]),
                    reason=str(classification["reason"]),
                    audit=classification["audit"],
                )
            )
    return rows


def _classify_low_incident_cross_error(
    *,
    semantic_id: str,
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    horizontal_angle_degrees: float,
) -> dict[str, Any] | None:
    related_road_indices = tuple(sorted(topology.incident_road_indices.get(semantic_id, frozenset())))
    incident_road_count = len(related_road_indices)
    if incident_road_count not in {1, 2}:
        return None

    in_edges = tuple(topology.in_edges.get(semantic_id, ()))
    out_edges = tuple(topology.out_edges.get(semantic_id, ()))
    incident_legs = _incident_legs_for_semantic(semantic_id=semantic_id, in_edges=in_edges, out_edges=out_edges)
    angle_groups = _group_incident_legs_by_outward_angle(
        incident_legs,
        angle_threshold_degrees=horizontal_angle_degrees,
    )
    angle_audit = _angle_group_audit(angle_groups, angle_threshold_degrees=horizontal_angle_degrees)
    if incident_road_count == 1:
        reason = "only_one_incident_road"
    elif _has_only_two_bidirectional_roads(incident_legs):
        reason = "only_two_bidirectional_roads"
    else:
        reason = "only_two_incident_roads"
    return _cross_non_cross_classification(
        semantic_id=semantic_id,
        topology=topology,
        related_road_indices=related_road_indices,
        reason=reason,
        audit_extra={
            "incident_road_count": incident_road_count,
            "incident_road_ids": _road_ids(parsed_roads, related_road_indices),
            "outward_angle_group_count": len(angle_groups),
            **angle_audit,
        },
    )


def _classify_cross_divmerge_like_error(
    *,
    semantic_id: str,
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    horizontal_angle_degrees: float,
) -> dict[str, Any] | None:
    related_road_indices = tuple(sorted(topology.incident_road_indices.get(semantic_id, frozenset())))
    if not related_road_indices or not _all_incident_roads_oneway(parsed_roads, related_road_indices):
        return None
    in_degree = int(topology.in_degree.get(semantic_id, 0))
    out_degree = int(topology.out_degree.get(semantic_id, 0))
    if in_degree == 1 and out_degree >= 2:
        error_type = ERROR_CROSS_DIVERGE
        group_prefix = "cross_diverge"
        role = "cross_diverge"
        suggested_fix_kind_2 = DIVERGE_KIND_2
        reason = "kind_2_4_oneway_roads_in_degree_1_out_degree_ge_2"
    elif out_degree == 1 and in_degree >= 2:
        error_type = ERROR_CROSS_MERGE
        group_prefix = "cross_merge"
        role = "cross_merge"
        suggested_fix_kind_2 = MERGE_KIND_2
        reason = "kind_2_4_oneway_roads_out_degree_1_in_degree_ge_2"
    else:
        return None

    incident_legs = _incident_legs_for_semantic(
        semantic_id=semantic_id,
        in_edges=tuple(topology.in_edges.get(semantic_id, ())),
        out_edges=tuple(topology.out_edges.get(semantic_id, ())),
    )
    angle_groups = _group_incident_legs_by_outward_angle(
        incident_legs,
        angle_threshold_degrees=horizontal_angle_degrees,
    )
    return {
        "error_type": error_type,
        "group_prefix": group_prefix,
        "role": role,
        "reason": reason,
        "related_road_indices": related_road_indices,
        "audit": {
            "in_degree": in_degree,
            "out_degree": out_degree,
            "suggested_fix_kind_2": suggested_fix_kind_2,
            "four_distinct_direction_pattern": False,
            "t_junction_pattern": False,
            "incident_road_count": len(related_road_indices),
            "incident_road_ids": _road_ids(parsed_roads, related_road_indices),
            "all_incident_roads_oneway": True,
            **_angle_group_audit(angle_groups, angle_threshold_degrees=horizontal_angle_degrees),
        },
    }


def _classify_cross_error(
    *,
    semantic_id: str,
    topology: Topology,
    parsed_roads: list[ParsedRoad],
    semantic_nodes: dict[str, SemanticNode],
    vertical_parallel_angle_degrees: float,
    horizontal_angle_degrees: float,
) -> dict[str, Any] | None:
    in_edges = tuple(topology.in_edges.get(semantic_id, ()))
    out_edges = tuple(topology.out_edges.get(semantic_id, ()))
    related_road_indices = tuple(sorted({edge.road_idx for edge in (*in_edges, *out_edges)}))
    incident_legs = _incident_legs_for_semantic(semantic_id=semantic_id, in_edges=in_edges, out_edges=out_edges)
    angle_groups = _group_incident_legs_by_outward_angle(
        incident_legs,
        angle_threshold_degrees=horizontal_angle_degrees,
    )
    angle_audit = _angle_group_audit(angle_groups, angle_threshold_degrees=horizontal_angle_degrees)
    if len(angle_groups) >= 4:
        return None
    if _has_only_two_bidirectional_roads(incident_legs):
        return _cross_non_cross_classification(
            semantic_id=semantic_id,
            topology=topology,
            related_road_indices=related_road_indices,
            reason="only_two_bidirectional_roads",
            audit_extra={
                "outward_angle_group_count": len(angle_groups),
                "incident_road_ids": [leg.road_id for leg in incident_legs],
                **angle_audit,
            },
        )
    if (
        len(angle_groups) == 2
        and all(_angle_group_has_in_and_out(group) for group in angle_groups)
        and _angle_groups_are_parallel(
            angle_groups,
            parallel_angle_degrees=vertical_parallel_angle_degrees,
        )
    ):
        return _cross_non_cross_classification(
            semantic_id=semantic_id,
            topology=topology,
            related_road_indices=related_road_indices,
            reason="two_parallel_outward_angle_groups_each_has_in_and_out",
            audit_extra={
                "outward_angle_group_count": len(angle_groups),
                "outward_angle_group_parallel": True,
                **angle_audit,
            },
        )

    t_pattern = _find_cross_t_pattern(
        in_edges=in_edges,
        out_edges=out_edges,
        angle_groups=angle_groups,
        vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
        horizontal_angle_degrees=horizontal_angle_degrees,
    )
    if t_pattern is None:
        t_pattern = _find_cross_t_pattern_by_same_remote_pair(
            in_edges=in_edges,
            out_edges=out_edges,
            angle_groups=angle_groups,
            semantic_nodes=semantic_nodes,
            vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
            horizontal_angle_degrees=horizontal_angle_degrees,
        )
    if t_pattern is not None:
        return {
            "error_type": ERROR_CROSS_T,
            "group_prefix": "cross_t",
            "role": "cross_t",
            "reason": "kind_2_4_matches_t_junction_pattern",
            "related_road_indices": t_pattern["related_road_indices"],
            "audit": {
                "in_degree": int(topology.in_degree.get(semantic_id, 0)),
                "out_degree": int(topology.out_degree.get(semantic_id, 0)),
                "suggested_fix_kind_2": 2048,
                **angle_audit,
                **t_pattern["audit"],
            },
        }

    return None
