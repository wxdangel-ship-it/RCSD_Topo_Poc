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
MANUAL_FIX_FIELD = "是否修复"
MANUAL_FIX_DEFAULT = 1

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class T08NodesTypeQcArtifacts:
    csv_output: Path
    error_nodes_output: Path
    summary_output: Path


@dataclass(frozen=True)
class ParsedNode:
    feature_index: int
    node_id: str
    semantic_id: str
    kind_2: int | None
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
    kind: str | None
    length_m: float
    forward_vector: tuple[float, float]


@dataclass(frozen=True)
class DirectedEdge:
    src: str
    dst: str
    road_idx: int
    road_id: str
    length_m: float
    vector: tuple[float, float]


@dataclass(frozen=True)
class IncidentLeg:
    road_idx: int
    road_id: str
    outward_vector: tuple[float, float]
    has_in: bool
    has_out: bool
    remote_semantic_ids: tuple[str, ...]


@dataclass(frozen=True)
class Topology:
    in_degree: dict[str, int]
    out_degree: dict[str, int]
    in_edges: dict[str, tuple[DirectedEdge, ...]]
    out_edges: dict[str, tuple[DirectedEdge, ...]]
    incident_road_indices: dict[str, frozenset[int]]
    internal_road_count: int
    direction_errors: tuple[str, ...]


@dataclass(frozen=True)
class TraceResult:
    end_semantic_id: str
    end_point: Point
    distance_m: float
    path_road_indices: tuple[int, ...]
    last_edge: DirectedEdge
    status: str


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
    parsed_roads = _parse_roads(
        roads_result.features,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        road_kind_field=road_kind_field,
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
            "error_feature_count": len(error_rows),
            "error_count_by_type": dict(sorted(counts_by_type.items())),
            "divmerge_error_group_count": len({row["error_group_id"] for row in divmerge_rows}),
            "cross_error_count": len(cross_rows),
            "divmerge_suppressed_count": len(divmerge_suppressed),
            "internal_road_count": topology.internal_road_count,
            "direction_error_count": len(topology.direction_errors),
        },
        "direction_errors": list(topology.direction_errors),
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
        in_degree = int(topology.in_degree.get(semantic.semantic_id, 0))
        out_degree = int(topology.out_degree.get(semantic.semantic_id, 0))
        if semantic.representative.kind_2 == CROSS_KIND_2 and in_degree == 2 and out_degree == 2:
            classification = _classify_cross_error(
                semantic_id=semantic.semantic_id,
                topology=topology,
                parsed_roads=parsed_roads,
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


def _classify_cross_error(
    *,
    semantic_id: str,
    topology: Topology,
    parsed_roads: list[ParsedRoad],
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


def _cross_non_cross_classification(
    *,
    semantic_id: str,
    topology: Topology,
    related_road_indices: tuple[int, ...],
    reason: str,
    audit_extra: dict[str, Any],
) -> dict[str, Any]:
    return {
        "error_type": ERROR_CROSS_NON_CROSS,
        "group_prefix": "cross_non_cross",
        "role": "cross_non_cross",
        "reason": reason,
        "related_road_indices": related_road_indices,
        "audit": {
            "in_degree": int(topology.in_degree.get(semantic_id, 0)),
            "out_degree": int(topology.out_degree.get(semantic_id, 0)),
            "suggested_fix_kind_2": None,
            "four_distinct_direction_pattern": False,
            "t_junction_pattern": False,
            **audit_extra,
        },
    }


def _incident_legs_for_semantic(
    *,
    semantic_id: str,
    in_edges: tuple[DirectedEdge, ...],
    out_edges: tuple[DirectedEdge, ...],
) -> tuple[IncidentLeg, ...]:
    entries: dict[int, dict[str, Any]] = {}
    for edge in in_edges:
        entry = entries.setdefault(
            edge.road_idx,
            {
                "road_id": edge.road_id,
                "outward_vector": (-edge.vector[0], -edge.vector[1]),
                "has_in": False,
                "has_out": False,
                "remote_semantic_ids": set(),
            },
        )
        entry["has_in"] = True
        entry["remote_semantic_ids"].add(edge.src)
    for edge in out_edges:
        entry = entries.setdefault(
            edge.road_idx,
            {
                "road_id": edge.road_id,
                "outward_vector": edge.vector,
                "has_in": False,
                "has_out": False,
                "remote_semantic_ids": set(),
            },
        )
        entry["has_out"] = True
        entry["outward_vector"] = edge.vector
        entry["remote_semantic_ids"].add(edge.dst)
    return tuple(
        sorted(
            (
                IncidentLeg(
                    road_idx=road_idx,
                    road_id=str(entry["road_id"]),
                    outward_vector=_unit_vector(entry["outward_vector"]),
                    has_in=bool(entry["has_in"]),
                    has_out=bool(entry["has_out"]),
                    remote_semantic_ids=tuple(
                        sorted((str(value) for value in entry["remote_semantic_ids"] if value != semantic_id), key=_sort_key)
                    ),
                )
                for road_idx, entry in entries.items()
            ),
            key=lambda leg: _sort_key(leg.road_id),
        )
    )


def _group_incident_legs_by_outward_angle(
    legs: tuple[IncidentLeg, ...],
    *,
    angle_threshold_degrees: float,
) -> list[list[IncidentLeg]]:
    groups: list[list[IncidentLeg]] = []
    for leg in legs:
        for group in groups:
            if any(_same_outward_angle(leg, existing, angle_threshold_degrees=angle_threshold_degrees) for existing in group):
                group.append(leg)
                break
        else:
            groups.append([leg])
    return groups


def _same_outward_angle(left: IncidentLeg, right: IncidentLeg, *, angle_threshold_degrees: float) -> bool:
    if set(left.remote_semantic_ids) & set(right.remote_semantic_ids):
        return True
    return _angle_degrees(left.outward_vector, right.outward_vector) <= angle_threshold_degrees


def _angle_group_audit(
    groups: list[list[IncidentLeg]],
    *,
    angle_threshold_degrees: float,
) -> dict[str, Any]:
    return {
        "outward_angle_group_count": len(groups),
        "outward_angle_threshold_degrees": float(angle_threshold_degrees),
        "angle_groups": [
            {
                "group_index": group_index,
                "road_ids": [leg.road_id for leg in group],
                "has_in": _angle_group_has_in(group),
                "has_out": _angle_group_has_out(group),
                "members": [_incident_leg_audit(leg) for leg in group],
                "merge_reasons": _angle_group_merge_reasons(group, angle_threshold_degrees=angle_threshold_degrees),
            }
            for group_index, group in enumerate(groups)
        ],
    }


def _incident_leg_audit(leg: IncidentLeg) -> dict[str, Any]:
    return {
        "road_id": leg.road_id,
        "has_in": leg.has_in,
        "has_out": leg.has_out,
        "outward_vector": [round(float(leg.outward_vector[0]), 6), round(float(leg.outward_vector[1]), 6)],
        "remote_semantic_ids": list(leg.remote_semantic_ids),
    }


def _angle_group_merge_reasons(
    group: list[IncidentLeg],
    *,
    angle_threshold_degrees: float,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for left_index, left in enumerate(group):
        for right in group[left_index + 1 :]:
            shared_remote_ids = sorted(set(left.remote_semantic_ids) & set(right.remote_semantic_ids), key=_sort_key)
            angle_degrees = _angle_degrees(left.outward_vector, right.outward_vector)
            if shared_remote_ids:
                reason = "same_remote_semantic"
            elif angle_degrees <= angle_threshold_degrees:
                reason = "angle_within_threshold"
            else:
                reason = "transitive_group_member"
            reasons.append(
                {
                    "left_road_id": left.road_id,
                    "right_road_id": right.road_id,
                    "reason": reason,
                    "angle_degrees": round(float(angle_degrees), 3),
                    "shared_remote_semantic_ids": shared_remote_ids,
                }
            )
    return reasons


def _has_only_two_bidirectional_roads(legs: tuple[IncidentLeg, ...]) -> bool:
    return len(legs) == 2 and all(leg.has_in and leg.has_out for leg in legs)


def _angle_group_has_in(group: list[IncidentLeg]) -> bool:
    return any(leg.has_in for leg in group)


def _angle_group_has_out(group: list[IncidentLeg]) -> bool:
    return any(leg.has_out for leg in group)


def _angle_group_has_in_and_out(group: list[IncidentLeg]) -> bool:
    return _angle_group_has_in(group) and _angle_group_has_out(group)


def _angle_groups_are_parallel(
    groups: list[list[IncidentLeg]],
    *,
    parallel_angle_degrees: float,
) -> bool:
    if len(groups) != 2 or any(not group for group in groups):
        return False
    return _parallel_angle_degrees(groups[0][0].outward_vector, groups[1][0].outward_vector) <= parallel_angle_degrees


def _find_cross_t_pattern(
    *,
    in_edges: tuple[DirectedEdge, ...],
    out_edges: tuple[DirectedEdge, ...],
    vertical_parallel_angle_degrees: float,
    horizontal_angle_degrees: float,
) -> dict[str, Any] | None:
    for horizontal_in in sorted(in_edges, key=lambda edge: (_sort_key(edge.road_id), _sort_key(edge.src))):
        for horizontal_out in sorted(out_edges, key=lambda edge: (_sort_key(edge.road_id), _sort_key(edge.dst))):
            if horizontal_in.road_idx == horizontal_out.road_idx:
                continue
            horizontal_angle = _angle_degrees(horizontal_in.vector, horizontal_out.vector)
            if horizontal_angle > horizontal_angle_degrees:
                continue
            vertical_in = [edge for edge in in_edges if edge is not horizontal_in]
            vertical_out = [edge for edge in out_edges if edge is not horizontal_out]
            if len(vertical_in) != 1 or len(vertical_out) != 1:
                continue
            t_pattern = _evaluate_cross_t_vertical(
                horizontal_in=horizontal_in,
                horizontal_out=horizontal_out,
                vertical_in=vertical_in[0],
                vertical_out=vertical_out[0],
                vertical_parallel_angle_degrees=vertical_parallel_angle_degrees,
                horizontal_angle_degrees=horizontal_angle,
            )
            if t_pattern is not None:
                return t_pattern
    return None


def _evaluate_cross_t_vertical(
    *,
    horizontal_in: DirectedEdge,
    horizontal_out: DirectedEdge,
    vertical_in: DirectedEdge,
    vertical_out: DirectedEdge,
    vertical_parallel_angle_degrees: float,
    horizontal_angle_degrees: float,
) -> dict[str, Any] | None:
    vertical_mode: str | None = None
    vertical_parallel_angle = _parallel_angle_degrees(vertical_in.vector, vertical_out.vector)
    if vertical_in.road_idx == vertical_out.road_idx:
        vertical_mode = "bidirectional_road"
    elif vertical_parallel_angle <= vertical_parallel_angle_degrees:
        vertical_mode = "parallel_oneway_roads"
    if vertical_mode is None:
        return None

    horizontal_vector = _unit_vector(
        (
            horizontal_in.vector[0] + horizontal_out.vector[0],
            horizontal_in.vector[1] + horizontal_out.vector[1],
        )
    )
    vertical_on_right = _cross(horizontal_vector, vertical_out.vector) < 0
    if not vertical_on_right:
        return None

    related_road_indices = tuple(
        sorted({horizontal_in.road_idx, horizontal_out.road_idx, vertical_in.road_idx, vertical_out.road_idx})
    )
    return {
        "related_road_indices": related_road_indices,
        "audit": {
            "four_distinct_direction_pattern": False,
            "t_junction_pattern": True,
            "horizontal_in_road_id": horizontal_in.road_id,
            "horizontal_out_road_id": horizontal_out.road_id,
            "vertical_in_road_id": vertical_in.road_id,
            "vertical_out_road_id": vertical_out.road_id,
            "vertical_mode": vertical_mode,
            "vertical_on_right": True,
            "horizontal_angle_degrees": round(float(horizontal_angle_degrees), 3),
            "vertical_parallel_angle_degrees": round(float(vertical_parallel_angle), 3),
        },
    }


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
                geometry=Point(float(centroid.x), float(centroid.y)),
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool6] parsed {index + 1} node feature(s)")
    return parsed


def _parse_roads(
    features: list[VectorFeature],
    *,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str,
    road_kind_field: str | None,
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
        forward_vector = _line_forward_vector(feature.geometry)
        parsed.append(
            ParsedRoad(
                feature_index=index,
                road_id=road_id,
                snodeid=_required_id(feature.properties.get(road_snode_field), f"road '{road_id}' snodeid"),
                enodeid=_required_id(feature.properties.get(road_enode_field), f"road '{road_id}' enodeid"),
                direction=_coerce_int(feature.properties.get(road_direction_field)),
                kind=_normalize_text(feature.properties.get(road_kind_field)) if road_kind_field else None,
                length_m=float(feature.geometry.length),
                forward_vector=forward_vector,
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool6] parsed {index + 1} road feature(s)")
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


def _build_topology(parsed_roads: list[ParsedRoad], *, node_to_semantic: dict[str, str]) -> Topology:
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    in_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    out_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    incident_road_indices: dict[str, set[int]] = defaultdict(set)
    direction_errors: list[str] = []
    internal_road_count = 0
    for road_index, road in enumerate(parsed_roads):
        source_semantic = node_to_semantic.get(road.snodeid)
        target_semantic = node_to_semantic.get(road.enodeid)
        if source_semantic is None or target_semantic is None:
            missing_node = road.snodeid if source_semantic is None else road.enodeid
            raise ValueError(f"Road '{road.road_id}' references missing node '{missing_node}'.")
        incident_road_indices[source_semantic].add(road_index)
        if source_semantic == target_semantic:
            internal_road_count += 1
            if road.direction in {0, 1, 2, 3}:
                in_degree[source_semantic] += 1
                out_degree[source_semantic] += 1
            else:
                direction_errors.append(f"direction_invalid:road_id={road.road_id}:value={road.direction}")
            continue
        incident_road_indices[target_semantic].add(road_index)
        if road.direction in {0, 1}:
            _add_edge(
                road,
                road_index,
                source_semantic,
                target_semantic,
                road.forward_vector,
                in_degree,
                out_degree,
                in_edges,
                out_edges,
            )
            _add_edge(
                road,
                road_index,
                target_semantic,
                source_semantic,
                (-road.forward_vector[0], -road.forward_vector[1]),
                in_degree,
                out_degree,
                in_edges,
                out_edges,
            )
        elif road.direction == 2:
            _add_edge(
                road,
                road_index,
                source_semantic,
                target_semantic,
                road.forward_vector,
                in_degree,
                out_degree,
                in_edges,
                out_edges,
            )
        elif road.direction == 3:
            _add_edge(
                road,
                road_index,
                target_semantic,
                source_semantic,
                (-road.forward_vector[0], -road.forward_vector[1]),
                in_degree,
                out_degree,
                in_edges,
                out_edges,
            )
        else:
            direction_errors.append(f"direction_invalid:road_id={road.road_id}:value={road.direction}")
    return Topology(
        in_degree=dict(in_degree),
        out_degree=dict(out_degree),
        in_edges={key: tuple(value) for key, value in in_edges.items()},
        out_edges={key: tuple(value) for key, value in out_edges.items()},
        incident_road_indices={key: frozenset(value) for key, value in incident_road_indices.items()},
        internal_road_count=internal_road_count,
        direction_errors=tuple(direction_errors),
    )


def _add_edge(
    road: ParsedRoad,
    road_index: int,
    src: str,
    dst: str,
    vector: tuple[float, float],
    in_degree: dict[str, int],
    out_degree: dict[str, int],
    in_edges: dict[str, list[DirectedEdge]],
    out_edges: dict[str, list[DirectedEdge]],
) -> None:
    edge = DirectedEdge(src=src, dst=dst, road_idx=road_index, road_id=road.road_id, length_m=road.length_m, vector=vector)
    out_degree[src] += 1
    in_degree[dst] += 1
    out_edges[src].append(edge)
    in_edges[dst].append(edge)


def _trace_to_merge(
    *,
    first_edge: DirectedEdge,
    semantic_nodes: dict[str, SemanticNode],
    topology: Topology,
    search_distance_m: float,
) -> TraceResult | None:
    trace = _trace_branch(
        first_edge=first_edge,
        semantic_nodes=semantic_nodes,
        topology=topology,
        max_distance_m=search_distance_m,
        stop_kind_2=MERGE_KIND_2,
    )
    semantic = semantic_nodes.get(trace.end_semantic_id)
    if semantic is None or semantic.representative.kind_2 != MERGE_KIND_2:
        return None
    return trace


def _trace_branch(
    *,
    first_edge: DirectedEdge,
    semantic_nodes: dict[str, SemanticNode],
    topology: Topology,
    max_distance_m: float,
    stop_kind_2: int | None = None,
) -> TraceResult:
    total = float(max(0.0, first_edge.length_m))
    prev_semantic = first_edge.src
    current = first_edge.dst
    previous_road_idx = first_edge.road_idx
    path = [first_edge.road_idx]
    last_edge = first_edge
    status = "max_distance_reached" if total > max_distance_m else "traced"
    while total <= max_distance_m + 1e-9:
        semantic = semantic_nodes.get(current)
        if semantic is None:
            status = "missing_semantic"
            break
        if stop_kind_2 is not None and semantic.representative.kind_2 == stop_kind_2:
            status = "target_kind_found"
            break
        incident_count = len(topology.incident_road_indices.get(current, frozenset()))
        if incident_count != 2:
            status = "non_degree2_stop"
            break
        next_edges = [
            edge
            for edge in topology.out_edges.get(current, ())
            if edge.road_idx != previous_road_idx and edge.dst != prev_semantic
        ]
        if len(next_edges) != 1:
            status = "degree2_out_not_unique"
            break
        nxt = next_edges[0]
        if total + float(max(0.0, nxt.length_m)) > max_distance_m + 1e-9:
            status = "max_distance_reached"
            break
        total += float(max(0.0, nxt.length_m))
        path.append(nxt.road_idx)
        prev_semantic = current
        current = nxt.dst
        previous_road_idx = nxt.road_idx
        last_edge = nxt
    end_point = semantic_nodes[current].representative.geometry if current in semantic_nodes else Point()
    return TraceResult(
        end_semantic_id=current,
        end_point=end_point,
        distance_m=float(total),
        path_road_indices=tuple(path),
        last_edge=last_edge,
        status=status,
    )


def _choose_representative(semantic_id: str, members: list[ParsedNode]) -> ParsedNode:
    exact = [node for node in members if node.node_id == semantic_id]
    if exact:
        return sorted(exact, key=lambda node: node.feature_index)[0]
    non_zero = [node for node in members if int(node.kind_2 or 0) != 0]
    if non_zero:
        return sorted(non_zero, key=lambda node: (_sort_key(node.node_id), node.feature_index))[0]
    return sorted(members, key=lambda node: (_sort_key(node.node_id), node.feature_index))[0]


def _left_right_edges(
    incoming_vector: tuple[float, float],
    outgoing: list[DirectedEdge],
) -> tuple[DirectedEdge, DirectedEdge]:
    ordered = sorted(
        outgoing,
        key=lambda edge: (_signed_angle_degrees(incoming_vector, edge.vector), _sort_key(edge.road_id)),
        reverse=True,
    )
    return ordered[0], ordered[-1]


def _choose_merge_out_edge(
    *,
    merge_id: str,
    left_edge: DirectedEdge,
    left_trace: TraceResult,
    topology: Topology,
) -> DirectedEdge | None:
    candidates = [edge for edge in topology.out_edges.get(merge_id, ()) if edge.road_idx != left_trace.last_edge.road_idx]
    if not candidates:
        return None
    return sorted(candidates, key=lambda edge: (_angle_degrees(left_edge.vector, edge.vector), _sort_key(edge.road_id)))[0]


def _choose_merge_side_in_edge(
    *,
    merge_id: str,
    left_trace: TraceResult,
    horizontal_vector: tuple[float, float],
    topology: Topology,
) -> DirectedEdge | None:
    candidates = [edge for edge in topology.in_edges.get(merge_id, ()) if edge.road_idx != left_trace.last_edge.road_idx]
    if not candidates:
        return None
    return sorted(candidates, key=lambda edge: (_cross(horizontal_vector, _reverse_edge(edge).vector), _sort_key(edge.road_id)))[0]


def _reverse_edge(edge: DirectedEdge) -> DirectedEdge:
    return DirectedEdge(
        src=edge.dst,
        dst=edge.src,
        road_idx=edge.road_idx,
        road_id=edge.road_id,
        length_m=edge.length_m,
        vector=(-edge.vector[0], -edge.vector[1]),
    )


def _related_divmerge_road_indices(
    incoming: DirectedEdge,
    left_edge: DirectedEdge,
    right_edge: DirectedEdge,
    merge_trace: TraceResult,
    merge_out: DirectedEdge,
    merge_side_reverse: DirectedEdge,
    right_trace_indices: tuple[int, ...],
    merge_side_trace_indices: tuple[int, ...],
) -> tuple[int, ...]:
    indices = {
        incoming.road_idx,
        left_edge.road_idx,
        right_edge.road_idx,
        merge_out.road_idx,
        merge_side_reverse.road_idx,
        *merge_trace.path_road_indices,
        *right_trace_indices,
        *merge_side_trace_indices,
    }
    return tuple(sorted(indices))


def _oneway_vertical_connects_diverge_and_merge(
    *,
    right_trace: TraceResult,
    merge_side_trace: TraceResult,
    diverge_id: str,
    merge_id: str,
    parsed_roads: list[ParsedRoad],
) -> bool:
    if right_trace.end_semantic_id == merge_id and _all_oneway_roads(parsed_roads, right_trace.path_road_indices):
        return True
    if merge_side_trace.end_semantic_id == diverge_id and _all_oneway_roads(parsed_roads, merge_side_trace.path_road_indices):
        return True
    return False


def _all_oneway_roads(parsed_roads: list[ParsedRoad], road_indices: tuple[int, ...]) -> bool:
    return bool(road_indices) and all(parsed_roads[index].direction in {2, 3} for index in road_indices)


def _suppressed_row(
    *,
    diverge: SemanticNode,
    merge: SemanticNode,
    reason: str,
    related_road_indices: tuple[int, ...],
    parsed_roads: list[ParsedRoad],
) -> dict[str, Any]:
    return {
        "status": "suppressed",
        "reason": reason,
        "diverge_semantic_node_id": diverge.semantic_id,
        "merge_semantic_node_id": merge.semantic_id,
        "related_road_ids": list(_road_ids(parsed_roads, related_road_indices)),
    }


def _error_row(
    *,
    error_id: str,
    error_group_id: str,
    error_type: str,
    semantic: SemanticNode,
    role: str,
    paired_semantic_node_id: str,
    topology: Topology,
    related_node_ids: tuple[str, ...],
    related_road_ids: tuple[str, ...],
    reason: str,
    audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "error_id": error_id,
        "error_group_id": error_group_id,
        "error_type": error_type,
        "semantic_node_id": semantic.semantic_id,
        "source_node_id": semantic.representative.node_id,
        "role": role,
        "kind_2": semantic.representative.kind_2,
        "in_degree": int(topology.in_degree.get(semantic.semantic_id, 0)),
        "out_degree": int(topology.out_degree.get(semantic.semantic_id, 0)),
        "paired_semantic_node_id": paired_semantic_node_id,
        "related_node_ids": ",".join(sorted((str(node_id) for node_id in related_node_ids), key=_sort_key)),
        "related_road_ids": ",".join(related_road_ids),
        "reason": reason,
        "audit_json": json.dumps(audit, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        MANUAL_FIX_FIELD: MANUAL_FIX_DEFAULT,
        "geometry": semantic.representative.geometry,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})


def _road_ids(parsed_roads: list[ParsedRoad], road_indices: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(sorted((parsed_roads[index].road_id for index in road_indices), key=_sort_key))


def _has_kind_suffix(parsed_roads: list[ParsedRoad], road_indices: tuple[int, ...], suffix: str) -> bool:
    wanted = suffix.lower()
    for index in road_indices:
        road = parsed_roads[index]
        for token in str(road.kind or "").split("|"):
            text = token.strip().lower()
            if len(text) >= 2 and text[-2:] == wanted:
                return True
    return False


def _trace_vector(start: SemanticNode, trace: TraceResult) -> tuple[float, float]:
    dx = trace.end_point.x - start.representative.geometry.x
    dy = trace.end_point.y - start.representative.geometry.y
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return trace.last_edge.vector
    return _unit_vector((dx, dy))


def _line_forward_vector(geometry: Any) -> tuple[float, float]:
    try:
        coords = list(geometry.coords)
    except Exception:
        try:
            line = geometry.boundary
            coords = list(line.coords)
        except Exception:
            coords = []
    if len(coords) >= 2:
        start = coords[0]
        end = coords[-1]
        return _unit_vector((float(end[0]) - float(start[0]), float(end[1]) - float(start[1])))
    return (1.0, 0.0)


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _angle_degrees(a: tuple[float, float], b: tuple[float, float]) -> float:
    au = _unit_vector(a)
    bu = _unit_vector(b)
    dot = max(-1.0, min(1.0, au[0] * bu[0] + au[1] * bu[1]))
    return abs(math.degrees(math.acos(dot)))


def _parallel_angle_degrees(a: tuple[float, float], b: tuple[float, float]) -> float:
    angle = _angle_degrees(a, b)
    return min(angle, abs(180.0 - angle))


def _signed_angle_degrees(a: tuple[float, float], b: tuple[float, float]) -> float:
    au = _unit_vector(a)
    bu = _unit_vector(b)
    return math.degrees(math.atan2(_cross(au, bu), au[0] * bu[0] + au[1] * bu[1]))


def _unit_vector(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        return (1.0, 0.0)
    return (float(vector[0]) / length, float(vector[1]) / length)


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


def _normalize_text(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    return None if normalized is None else str(normalized)


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


def _sort_key(value: str) -> tuple[int, int | str]:
    text = str(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _elapsed_since(started: float) -> float:
    return time.perf_counter() - started


def _should_emit_progress(index: int, progress_interval: int) -> bool:
    return progress_interval > 0 and index % progress_interval == 0


def _items_per_second(item_count: int, elapsed_seconds: float) -> float | None:
    if elapsed_seconds <= 0:
        return None
    return round(float(item_count) / elapsed_seconds, 3)


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


__all__ = [
    "T08NodesTypeQcArtifacts",
    "run_t08_nodes_type_qc",
]
