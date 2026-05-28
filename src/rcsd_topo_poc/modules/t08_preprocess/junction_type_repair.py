from __future__ import annotations

import math
import sqlite3
import time
import csv
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyproj import CRS
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name
from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorFeature,
    _build_geometry_transform,
    _geometry_from_gpkg_blob,
    _gpkg_table_columns,
    _quote_identifier,
    _resolve_gpkg_crs,
    _resolve_gpkg_layer_info,
    _transform_geometry_prepared,
    aggregate_bounds,
    ensure_gpkg_path,
    read_vector,
    resolve_case_insensitive_field_name,
    resolve_field_name,
    unique_field_names,
    write_gpkg,
    write_json,
)


T_KIND_VALUE = 2048
DIVERGE_KIND_VALUE = 16
MERGE_KIND_VALUE = 8
ADVANCE_RIGHT_TURN_FORMWAY_BIT = 128
AUXILIARY_ROAD_KIND_SUFFIX = "0a"

ERROR_T_JUNCTION = "错误T型路口"
ERROR_DIVMERGE_ONE_IN_ONE_OUT = "错误分歧合流路口_一入一出"
TOOL6_ERROR_DIVMERGE = "错误分歧合流路口"
TOOL6_ERROR_CROSS_T = "错误交叉路口_T型路口"
TOOL6_ERROR_CROSS_NON_CROSS = "错误交叉路口_非交叉路口"
TOOL6_MANUAL_FIX_FIELD = "是否修复"

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class T08JunctionTypeRepairArtifacts:
    nodes_output: Path
    roads_output: Path | None
    audit_nodes_output: Path
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
    formway: int | None
    is_advance_right_turn: bool
    is_auxiliary: bool
    length_m: float
    forward_vector: tuple[float, float]


@dataclass(frozen=True)
class RoadReadAudit:
    source_crs: CRS
    output_crs: CRS
    crs_source: str
    layer_name: str | None
    road_id_field: str
    road_snode_field: str
    road_enode_field: str
    road_direction_field: str
    road_kind_field: str | None
    road_formway_field: str | None
    reader: str
    selected_fields_only: bool
    geometry_stored: bool


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


def run_t08_junction_type_repair(
    *,
    nodes_gpkg: str | Path,
    roads_gpkg: str | Path,
    nodes_output: str | Path,
    audit_nodes_output: str | Path,
    roads_output: str | Path | None = None,
    tool6_node_error_gpkg: str | Path | None = None,
    tool6_node_error_csv: str | Path | None = None,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    nodes_default_crs_text: str | None = None,
    roads_default_crs_text: str | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08JunctionTypeRepairArtifacts:
    started = time.perf_counter()
    stage_timings: dict[str, float] = {}
    nodes_path = ensure_gpkg_path(nodes_gpkg, label="--nodes-gpkg")
    roads_path = ensure_gpkg_path(roads_gpkg, label="--roads-gpkg")
    output_nodes_path = ensure_tool_output_name(
        ensure_gpkg_path(nodes_output, label="--nodes-output"),
        tool_number=4,
        label="--nodes-output",
    )
    output_audit_nodes_path = ensure_tool_output_name(
        ensure_gpkg_path(audit_nodes_output, label="--audit-nodes-output"),
        tool_number=4,
        label="--audit-nodes-output",
    )
    output_roads_path = (
        ensure_tool_output_name(
            ensure_gpkg_path(roads_output, label="--roads-output"),
            tool_number=4,
            label="--roads-output",
        )
        if roads_output is not None
        else None
    )
    tool6_node_error_gpkg_path = (
        ensure_gpkg_path(tool6_node_error_gpkg, label="--tool6-node-error-gpkg")
        if tool6_node_error_gpkg is not None
        else None
    )
    tool6_node_error_csv_path = Path(tool6_node_error_csv) if tool6_node_error_csv is not None else None
    if tool6_node_error_gpkg_path is not None and tool6_node_error_csv_path is not None:
        raise ValueError("Provide only one of --tool6-node-error-gpkg or --tool6-node-error-csv.")
    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=4, label="--summary-output")
        if summary_output
        else output_nodes_path.with_name("t08_junction_type_repair_summary_tool4.json")
    )

    _emit_progress(progress_callback, f"[T08 Tool4] start nodes={nodes_path} roads={roads_path}")
    read_started = time.perf_counter()
    nodes_result = read_vector(
        nodes_path,
        layer_name=nodes_layer,
        default_crs_text=nodes_default_crs_text,
        target_epsg=target_epsg,
    )
    if not nodes_result.features:
        raise ValueError("Nodes input contains no features")
    node_feature_count = len(nodes_result.features)
    node_source_crs_text = nodes_result.source_crs.to_string()
    node_crs_source = nodes_result.crs_source
    node_features = [
        {"properties": dict(feature.properties), "geometry": feature.geometry}
        for feature in nodes_result.features
    ]
    stage_timings["read_nodes_seconds"] = _elapsed_since(read_started)

    read_started = time.perf_counter()
    parsed_roads, roads_audit = _read_roads_for_tool4(
        roads_path,
        layer_name=roads_layer,
        default_crs_text=roads_default_crs_text,
        target_epsg=target_epsg,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    stage_timings["read_roads_seconds"] = _elapsed_since(read_started)
    stage_timings["read_inputs_seconds"] = stage_timings["read_nodes_seconds"] + stage_timings["read_roads_seconds"]
    _emit_progress(
        progress_callback,
        f"[T08 Tool4] loaded nodes={node_feature_count} roads={len(parsed_roads)} "
        f"road_reader={roads_audit.reader}",
    )

    stage_started = time.perf_counter()
    node_id_field = resolve_field_name(nodes_result.features, ["id"], "nodes input")
    node_kind_2_field = resolve_field_name(nodes_result.features, ["kind_2"], "nodes input")
    node_mainnodeid_field = _optional_field(nodes_result.features, ["mainnodeid"])
    node_grade_2_field = _optional_field(nodes_result.features, ["grade_2"])
    output_node_mainnodeid_field = node_mainnodeid_field or "mainnodeid"
    output_node_grade_2_field = node_grade_2_field or "grade_2"
    output_fields_nodes = unique_field_names(
        nodes_result.field_names,
        extra=(output_node_mainnodeid_field, output_node_grade_2_field),
    )
    parsed_nodes = _parse_nodes(
        nodes_result.features,
        node_id_field=node_id_field,
        node_kind_2_field=node_kind_2_field,
        node_mainnodeid_field=node_mainnodeid_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    del nodes_result
    semantic_nodes = _build_semantic_nodes(parsed_nodes)
    node_to_semantic = {node.node_id: node.semantic_id for node in parsed_nodes}
    topology = _build_topology(parsed_roads, node_to_semantic=node_to_semantic)
    special_road_indices = {
        index for index, road in enumerate(parsed_roads) if road.is_advance_right_turn or road.is_auxiliary
    }
    degree_exception_topology = _build_topology(
        parsed_roads,
        node_to_semantic=node_to_semantic,
        ignored_road_indices=special_road_indices,
    )
    stage_timings["build_topology_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    tool6_rows = _read_tool6_node_error_rows(
        tool6_node_error_gpkg_path=tool6_node_error_gpkg_path,
        tool6_node_error_csv_path=tool6_node_error_csv_path,
        target_epsg=target_epsg,
    )
    stage_timings["read_tool6_qc_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    errors, degree_exception_rows = _detect_junction_type_errors(
        semantic_nodes=semantic_nodes,
        parsed_roads=parsed_roads,
        topology=topology,
        degree_exception_topology=degree_exception_topology,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    stage_timings["detect_errors_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    repair_rows = _apply_t_junction_repairs(
        node_features=node_features,
        errors=errors,
        node_id_field=node_id_field,
        node_kind_2_field=node_kind_2_field,
    )
    tool6_repair_rows, deleted_road_indices, tool6_skipped_rows = _apply_tool6_qc_repairs(
        node_features=node_features,
        tool6_rows=tool6_rows,
        node_id_field=node_id_field,
        node_kind_2_field=node_kind_2_field,
        node_mainnodeid_field=output_node_mainnodeid_field,
        node_grade_2_field=output_node_grade_2_field,
        parsed_roads=parsed_roads,
        node_to_semantic=node_to_semantic,
    )
    repair_rows.extend(tool6_repair_rows)
    if deleted_road_indices and output_roads_path is None:
        raise ValueError("--roads-output is required when Tool6 divmerge repairs delete Road features.")
    audit_features = _build_audit_node_features(
        final_node_features=node_features,
        node_id_field=node_id_field,
        repair_rows=repair_rows,
    )
    audit_output_fields = unique_field_names(
        output_fields_nodes,
        extra=(
            "audit_id",
            "audit_process",
            "audit_group_id",
            "audit_role",
            "audit_mainnodeid",
            "audit_source_node_id",
        ),
    )
    _emit_progress(progress_callback, f"[T08 Tool4] writing nodes output={output_nodes_path}")
    write_gpkg(output_nodes_path, node_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_nodes)
    roads_output_feature_count: int | None = None
    if output_roads_path is not None:
        _emit_progress(progress_callback, f"[T08 Tool4] writing roads output={output_roads_path}")
        roads_result = read_vector(
            roads_path,
            layer_name=roads_layer,
            default_crs_text=roads_default_crs_text,
            target_epsg=target_epsg,
        )
        roads_output_features = [
            {"properties": dict(feature.properties), "geometry": feature.geometry}
            for index, feature in enumerate(roads_result.features)
            if index not in deleted_road_indices
        ]
        roads_output_feature_count = len(roads_output_features)
        write_gpkg(
            output_roads_path,
            roads_output_features,
            crs_text=f"EPSG:{target_epsg}",
            empty_fields=roads_result.field_names,
        )
    _emit_progress(progress_callback, f"[T08 Tool4] writing audit nodes={output_audit_nodes_path}")
    write_gpkg(
        output_audit_nodes_path,
        audit_features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=audit_output_fields,
        geometry_type="Point",
    )
    stage_timings["write_output_seconds"] = _elapsed_since(stage_started)
    elapsed_seconds = _elapsed_since(started)

    counts_by_type: dict[str, int] = defaultdict(int)
    for row in [*errors, *tool6_repair_rows]:
        counts_by_type[str(row["error_type"])] += 1

    summary = {
        "tool": "T08 Tool4",
        "stage": "junction_type_repair",
        "target_epsg": target_epsg,
        "input_paths": {
            "nodes_gpkg": nodes_path,
            "roads_gpkg": roads_path,
            "tool6_node_error_gpkg": tool6_node_error_gpkg_path,
            "tool6_node_error_csv": tool6_node_error_csv_path,
        },
        "output_paths": {
            "nodes_output": output_nodes_path,
            "roads_output": output_roads_path,
            "audit_nodes_output": output_audit_nodes_path,
            "summary_output": summary_path,
        },
        "input_crs": {
            "nodes": node_source_crs_text,
            "nodes_crs_source": node_crs_source,
            "roads": roads_audit.source_crs.to_string(),
            "roads_crs_source": roads_audit.crs_source,
        },
        "params": {
            "nodes_layer": nodes_layer,
            "roads_layer": roads_layer,
        },
        "field_audit": {
            "node_id_field": node_id_field,
            "node_kind_2_field": node_kind_2_field,
            "node_mainnodeid_field": node_mainnodeid_field,
            "node_grade_2_field": node_grade_2_field,
            "road_id_field": roads_audit.road_id_field,
            "road_snode_field": roads_audit.road_snode_field,
            "road_enode_field": roads_audit.road_enode_field,
            "road_direction_field": roads_audit.road_direction_field,
            "road_kind_field": roads_audit.road_kind_field,
            "road_formway_field": roads_audit.road_formway_field,
        },
        "counts": {
            "node_feature_count": node_feature_count,
            "semantic_node_count": len(semantic_nodes),
            "road_feature_count": len(parsed_roads),
            "roads_output_feature_count": roads_output_feature_count,
            "error_feature_count": len(errors),
            "repaired_semantic_node_count": len(repair_rows),
            "audit_node_feature_count": len(audit_features),
            "tool6_qc_feature_count": len(tool6_rows),
            "tool6_repair_count": len(tool6_repair_rows),
            "tool6_skipped_count": len(tool6_skipped_rows),
            "deleted_road_count": len(deleted_road_indices),
            "error_count_by_type": dict(sorted(counts_by_type.items())),
            "internal_road_count": topology.internal_road_count,
            "direction_error_count": len(topology.direction_errors),
            "advance_right_turn_road_count": sum(1 for road in parsed_roads if road.is_advance_right_turn),
            "auxiliary_road_count": sum(1 for road in parsed_roads if road.is_auxiliary),
            "degree_exception_suppressed_count": sum(1 for row in degree_exception_rows if row["status"] == "suppressed"),
        },
        "direction_errors": list(topology.direction_errors),
        "degree_exceptions": degree_exception_rows,
        "tool6_skipped": tool6_skipped_rows,
        "deleted_road_ids": [parsed_roads[index].road_id for index in sorted(deleted_road_indices)],
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in node_features),
        "audit_nodes_bounds": aggregate_bounds(feature["geometry"] for feature in audit_features),
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "semantic_nodes_per_second": _items_per_second(len(semantic_nodes), elapsed_seconds),
            "stage_timings": {key: round(value, 6) for key, value in stage_timings.items()},
            "road_read_mode": {
                "reader": roads_audit.reader,
                "selected_fields_only": roads_audit.selected_fields_only,
                "geometry_stored": roads_audit.geometry_stored,
                "output_crs": roads_audit.output_crs.to_string(),
                "layer_name": roads_audit.layer_name,
            },
        },
        "repairs": repair_rows,
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
    return T08JunctionTypeRepairArtifacts(
        nodes_output=output_nodes_path,
        roads_output=output_roads_path,
        audit_nodes_output=output_audit_nodes_path,
        summary_output=summary_path,
    )


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
    non_zero_kind_2 = [node for node in members if int(node.kind_2 or 0) != 0]
    if non_zero_kind_2:
        return sorted(non_zero_kind_2, key=lambda node: (_sort_key(node.node_id), node.feature_index))[0]
    return sorted(members, key=lambda node: (_sort_key(node.node_id), node.feature_index))[0]


def _read_roads_for_tool4(
    path: Path,
    *,
    layer_name: str | None,
    default_crs_text: str | None,
    target_epsg: int,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> tuple[list[ParsedRoad], RoadReadAudit]:
    sqlite_result = _try_read_roads_light_gpkg(
        path,
        layer_name=layer_name,
        default_crs_text=default_crs_text,
        target_epsg=target_epsg,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    if sqlite_result is not None:
        return sqlite_result

    roads_result = read_vector(
        path,
        layer_name=layer_name,
        default_crs_text=default_crs_text,
        target_epsg=target_epsg,
    )
    road_id_field = resolve_field_name(roads_result.features, ["id"], "roads input")
    road_snode_field = resolve_field_name(roads_result.features, ["snodeid"], "roads input")
    road_enode_field = resolve_field_name(roads_result.features, ["enodeid"], "roads input")
    road_direction_field = resolve_field_name(roads_result.features, ["direction"], "roads input")
    road_kind_field = _optional_field(roads_result.features, ["kind"])
    road_formway_field = _optional_field(roads_result.features, ["formway"])
    parsed_roads = _parse_roads(
        roads_result.features,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        road_kind_field=road_kind_field,
        road_formway_field=road_formway_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    return parsed_roads, RoadReadAudit(
        source_crs=roads_result.source_crs,
        output_crs=roads_result.output_crs,
        crs_source=roads_result.crs_source,
        layer_name=roads_result.layer_name,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        road_kind_field=road_kind_field,
        road_formway_field=road_formway_field,
        reader="vector_fallback",
        selected_fields_only=False,
        geometry_stored=False,
    )


def _try_read_roads_light_gpkg(
    path: Path,
    *,
    layer_name: str | None,
    default_crs_text: str | None,
    target_epsg: int,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> tuple[list[ParsedRoad], RoadReadAudit] | None:
    try:
        with sqlite3.connect(path) as conn:
            table_info = _resolve_gpkg_layer_info(conn, layer_name=layer_name)
            if table_info is None:
                return None
            table_name, geometry_column, srs_id = table_info
            columns = _gpkg_table_columns(conn, table_name=table_name, geometry_column=geometry_column)
            if columns is None:
                return None
            road_id_field = _resolve_required_column(columns, ["id"], "roads input")
            road_snode_field = _resolve_required_column(columns, ["snodeid"], "roads input")
            road_enode_field = _resolve_required_column(columns, ["enodeid"], "roads input")
            road_direction_field = _resolve_required_column(columns, ["direction"], "roads input")
            road_kind_field = _resolve_optional_column(columns, ["kind"])
            road_formway_field = _resolve_optional_column(columns, ["formway"])
            source_crs, crs_source = _resolve_gpkg_crs(
                conn,
                srs_id=srs_id,
                default_crs_text=default_crs_text,
            )
            output_crs = CRS.from_epsg(target_epsg)
            transform_func = _build_geometry_transform(source_crs, output_crs)
            property_columns = [road_id_field, road_snode_field, road_enode_field, road_direction_field]
            for optional_column in (road_kind_field, road_formway_field):
                if optional_column is not None and optional_column not in property_columns:
                    property_columns.append(optional_column)
            select_columns = [*property_columns, geometry_column]
            rows = conn.execute(
                f"SELECT {', '.join(_quote_identifier(column) for column in select_columns)} "
                f"FROM {_quote_identifier(table_name)}"
            )
            parsed_roads: list[ParsedRoad] = []
            seen_ids: set[str] = set()
            for index, row in enumerate(rows):
                values = list(row)
                geometry_blob = values[-1]
                if geometry_blob is None:
                    raise ValueError(f"Feature {index + 1} in {path} has no geometry")
                geometry = _geometry_from_gpkg_blob(geometry_blob)
                if geometry.is_empty:
                    raise ValueError(f"Feature {index + 1} in {path} has empty geometry")
                geometry = _transform_geometry_prepared(geometry, transform_func)
                properties = {column: values[column_index] for column_index, column in enumerate(property_columns)}
                road_id = _required_id(properties.get(road_id_field), "road id")
                if road_id in seen_ids:
                    raise ValueError(f"Roads input has duplicate id '{road_id}'.")
                seen_ids.add(road_id)
                length_m, forward_vector = _line_metrics_from_geometry(geometry)
                road_kind = _normalize_road_kind(properties.get(road_kind_field)) if road_kind_field else None
                formway = _coerce_int(properties.get(road_formway_field)) if road_formway_field else None
                parsed_roads.append(
                    ParsedRoad(
                        feature_index=index,
                        road_id=road_id,
                        snodeid=_required_id(properties.get(road_snode_field), f"road '{road_id}' snodeid"),
                        enodeid=_required_id(properties.get(road_enode_field), f"road '{road_id}' enodeid"),
                        direction=_coerce_int(properties.get(road_direction_field)),
                        kind=road_kind,
                        formway=formway,
                        is_advance_right_turn=_has_formway_bit(formway, ADVANCE_RIGHT_TURN_FORMWAY_BIT),
                        is_auxiliary=_is_auxiliary_road_kind(road_kind),
                        length_m=length_m,
                        forward_vector=forward_vector,
                    )
                )
                if _should_emit_progress(index + 1, progress_interval):
                    _emit_progress(progress_callback, f"[T08 Tool4] parsed {index + 1} road feature(s)")
    except sqlite3.Error:
        return None

    return parsed_roads, RoadReadAudit(
        source_crs=source_crs,
        output_crs=output_crs,
        crs_source=crs_source,
        layer_name=table_name,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        road_kind_field=road_kind_field,
        road_formway_field=road_formway_field,
        reader="gpkg_sqlite_light",
        selected_fields_only=True,
        geometry_stored=False,
    )


def _resolve_required_column(columns: list[str], candidates: list[str], label: str) -> str:
    lower_map = {column.lower(): column for column in columns}
    for candidate in candidates:
        resolved = lower_map.get(candidate.lower())
        if resolved is not None:
            return resolved
    raise ValueError(f"Required field {candidates} not found in {label}")


def _resolve_optional_column(columns: list[str], candidates: list[str]) -> str | None:
    lower_map = {column.lower(): column for column in columns}
    for candidate in candidates:
        resolved = lower_map.get(candidate.lower())
        if resolved is not None:
            return resolved
    return None


def _parse_roads(
    features: list[VectorFeature],
    *,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str,
    road_kind_field: str | None,
    road_formway_field: str | None,
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
        length_m, forward_vector = _line_metrics_from_geometry(feature.geometry)
        road_kind = _normalize_road_kind(feature.properties.get(road_kind_field)) if road_kind_field else None
        formway = _coerce_int(feature.properties.get(road_formway_field)) if road_formway_field else None
        parsed.append(
            ParsedRoad(
                feature_index=index,
                road_id=road_id,
                snodeid=_required_id(feature.properties.get(road_snode_field), f"road '{road_id}' snodeid"),
                enodeid=_required_id(feature.properties.get(road_enode_field), f"road '{road_id}' enodeid"),
                direction=_coerce_int(feature.properties.get(road_direction_field)),
                kind=road_kind,
                formway=formway,
                is_advance_right_turn=_has_formway_bit(formway, ADVANCE_RIGHT_TURN_FORMWAY_BIT),
                is_auxiliary=_is_auxiliary_road_kind(road_kind),
                length_m=length_m,
                forward_vector=forward_vector,
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool4] parsed {index + 1} road feature(s)")
    return parsed


def _build_topology(
    parsed_roads: list[ParsedRoad],
    *,
    node_to_semantic: dict[str, str],
    ignored_road_indices: set[int] | frozenset[int] = frozenset(),
) -> Topology:
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    in_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    out_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    reverse_edges: dict[str, list[DirectedEdge]] = defaultdict(list)
    incident_road_indices: dict[str, set[int]] = defaultdict(set)
    direction_errors: list[str] = []
    internal_road_count = 0

    for road_index, road in enumerate(parsed_roads):
        if road_index in ignored_road_indices:
            continue
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
            forward_vector = road.forward_vector
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
                vector=road.forward_vector,
                in_degree=in_degree,
                out_degree=out_degree,
                in_edges=in_edges,
                out_edges=out_edges,
                reverse_edges=reverse_edges,
            )
        elif road.direction == 3:
            reverse_vector = (-road.forward_vector[0], -road.forward_vector[1])
            _add_directed_edge(
                road=road,
                road_index=road_index,
                src=target_semantic,
                dst=source_semantic,
                vector=reverse_vector,
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
    degree_exception_topology: Topology,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    degree_exception_rows: list[dict[str, Any]] = []
    seen_error_keys: set[tuple[str, str, str]] = set()

    for index, semantic in enumerate(semantic_nodes.values(), start=1):
        kind_2 = semantic.representative.kind_2
        in_count = int(topology.in_degree.get(semantic.semantic_id, 0))
        out_count = int(topology.out_degree.get(semantic.semantic_id, 0))
        degree_exception = _degree_exception_for_semantic(
            semantic_id=semantic.semantic_id,
            topology=topology,
            degree_exception_topology=degree_exception_topology,
            parsed_roads=parsed_roads,
        )
        if kind_2 == T_KIND_VALUE and (in_count != 2 or out_count != 2):
            if _is_suppressed_by_degree_exception(degree_exception):
                degree_exception_rows.append(
                    {
                        **degree_exception,
                        "status": "suppressed",
                        "error_type": ERROR_T_JUNCTION,
                        "reason": "special_road_excluded_degree_is_2_2",
                    }
                )
                continue
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
                audit={"in_degree": in_count, "out_degree": out_count, "degree_exception": degree_exception},
            )
        if kind_2 in {DIVERGE_KIND_VALUE, MERGE_KIND_VALUE} and in_count == 1 and out_count == 1:
            _append_error(
                errors,
                seen_error_keys=seen_error_keys,
                semantic=semantic,
                topology=topology,
                parsed_roads=parsed_roads,
                error_type=ERROR_DIVMERGE_ONE_IN_ONE_OUT,
                error_reason="kind_2=8 or 16 with in_degree=1 and out_degree=1 should be ordinary junction",
                group_id=f"divmerge_one_in_one_out_{semantic.semantic_id}",
                related_node_ids=(semantic.semantic_id,),
                related_road_indices=topology.incident_road_indices.get(semantic.semantic_id, frozenset()),
                audit={"in_degree": in_count, "out_degree": out_count},
            )
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool4] checked {index} semantic junction(s)")

    return (
        sorted(errors, key=lambda row: (_sort_key(str(row["semantic_node_id"])), str(row["error_type"]))),
        sorted(degree_exception_rows, key=lambda row: (_sort_key(str(row["semantic_node_id"])), str(row["error_type"]))),
    )


def _degree_exception_for_semantic(
    *,
    semantic_id: str,
    topology: Topology,
    degree_exception_topology: Topology,
    parsed_roads: list[ParsedRoad],
) -> dict[str, Any] | None:
    incident_indices = topology.incident_road_indices.get(semantic_id, frozenset())
    advance_right_turn_indices = [
        index for index in incident_indices if parsed_roads[index].is_advance_right_turn
    ]
    auxiliary_indices = [
        index for index in incident_indices if parsed_roads[index].is_auxiliary
    ]
    excluded_indices = sorted(set(advance_right_turn_indices) | set(auxiliary_indices))
    if not excluded_indices:
        return None
    return {
        "semantic_node_id": semantic_id,
        "raw_in_degree": int(topology.in_degree.get(semantic_id, 0)),
        "raw_out_degree": int(topology.out_degree.get(semantic_id, 0)),
        "effective_in_degree": int(degree_exception_topology.in_degree.get(semantic_id, 0)),
        "effective_out_degree": int(degree_exception_topology.out_degree.get(semantic_id, 0)),
        "excluded_road_ids": [parsed_roads[index].road_id for index in excluded_indices],
        "excluded_advance_right_turn_road_ids": [
            parsed_roads[index].road_id for index in sorted(set(advance_right_turn_indices))
        ],
        "excluded_auxiliary_road_ids": [
            parsed_roads[index].road_id for index in sorted(set(auxiliary_indices))
        ],
    }


def _is_suppressed_by_degree_exception(degree_exception: dict[str, Any] | None) -> bool:
    return bool(
        degree_exception is not None
        and int(degree_exception.get("effective_in_degree", -1)) == 2
        and int(degree_exception.get("effective_out_degree", -1)) == 2
    )


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
            "source_feature_index": semantic.representative.feature_index,
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


def _read_tool6_node_error_rows(
    *,
    tool6_node_error_gpkg_path: Path | None,
    tool6_node_error_csv_path: Path | None,
    target_epsg: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if tool6_node_error_csv_path is not None:
        with tool6_node_error_csv_path.open("r", encoding="utf-8-sig", newline="") as fp:
            rows.extend({key: value for key, value in row.items()} for row in csv.DictReader(fp))
    if tool6_node_error_gpkg_path is not None:
        result = read_vector(tool6_node_error_gpkg_path, target_epsg=target_epsg)
        rows.extend(dict(feature.properties) for feature in result.features)
    return rows


def _apply_tool6_qc_repairs(
    *,
    node_features: list[dict[str, Any]],
    tool6_rows: list[dict[str, Any]],
    node_id_field: str,
    node_kind_2_field: str,
    node_mainnodeid_field: str,
    node_grade_2_field: str,
    parsed_roads: list[ParsedRoad],
    node_to_semantic: dict[str, str],
) -> tuple[list[dict[str, Any]], set[int], list[dict[str, Any]]]:
    if not tool6_rows:
        return [], set(), []

    node_index_by_id = _node_feature_index_by_id(node_features, node_id_field=node_id_field)
    repair_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    deleted_road_indices: set[int] = set()

    rows_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tool6_rows:
        rows_by_group[_tool6_group_id(row)].append(row)

    for group_id, group_rows in sorted(rows_by_group.items(), key=lambda item: _sort_key(item[0])):
        error_types = {str(row.get("error_type") or "") for row in group_rows}
        if TOOL6_ERROR_DIVMERGE in error_types:
            group_repairs, group_deletes, group_skips = _apply_tool6_divmerge_group(
                group_id=group_id,
                rows=group_rows,
                node_features=node_features,
                node_index_by_id=node_index_by_id,
                node_id_field=node_id_field,
                node_kind_2_field=node_kind_2_field,
                node_mainnodeid_field=node_mainnodeid_field,
                node_grade_2_field=node_grade_2_field,
                parsed_roads=parsed_roads,
                node_to_semantic=node_to_semantic,
            )
            repair_rows.extend(group_repairs)
            deleted_road_indices.update(group_deletes)
            skipped_rows.extend(group_skips)
        for row in group_rows:
            error_type = str(row.get("error_type") or "")
            if error_type in {TOOL6_ERROR_CROSS_T, TOOL6_ERROR_CROSS_NON_CROSS}:
                repair = _apply_tool6_cross_row(
                    row=row,
                    node_features=node_features,
                    node_index_by_id=node_index_by_id,
                    node_id_field=node_id_field,
                    node_kind_2_field=node_kind_2_field,
                )
                if repair is None:
                    skipped_rows.append(_tool6_skip_row(row, reason="manual_fix_disabled_or_missing_node"))
                else:
                    repair_rows.append(repair)
    return repair_rows, deleted_road_indices, skipped_rows


def _apply_tool6_divmerge_group(
    *,
    group_id: str,
    rows: list[dict[str, Any]],
    node_features: list[dict[str, Any]],
    node_index_by_id: dict[str, int],
    node_id_field: str,
    node_kind_2_field: str,
    node_mainnodeid_field: str,
    node_grade_2_field: str,
    parsed_roads: list[ParsedRoad],
    node_to_semantic: dict[str, str],
) -> tuple[list[dict[str, Any]], set[int], list[dict[str, Any]]]:
    divmerge_rows = [row for row in rows if str(row.get("error_type") or "") == TOOL6_ERROR_DIVMERGE]
    if not divmerge_rows:
        return [], set(), []
    if any(not _manual_fix_enabled(row.get(TOOL6_MANUAL_FIX_FIELD)) for row in divmerge_rows):
        return [], set(), [_tool6_skip_row(divmerge_rows[0], reason="manual_fix_disabled_in_group")]
    diverge_row = _first_tool6_role(divmerge_rows, "diverge")
    merge_row = _first_tool6_role(divmerge_rows, "merge")
    if diverge_row is None or merge_row is None:
        return [], set(), [_tool6_skip_row(divmerge_rows[0], reason="missing_diverge_or_merge_row")]

    diverge_node_id = _tool6_source_node_id(diverge_row)
    merge_node_id = _tool6_source_node_id(merge_row)
    if diverge_node_id is None or merge_node_id is None:
        return [], set(), [_tool6_skip_row(divmerge_rows[0], reason="missing_source_node_id")]
    diverge_index = node_index_by_id.get(diverge_node_id)
    merge_index = node_index_by_id.get(merge_node_id)
    if diverge_index is None or merge_index is None:
        return [], set(), [_tool6_skip_row(divmerge_rows[0], reason="source_node_not_found")]

    related_node_ids = sorted(
        set(
            _split_csv_ids(diverge_row.get("related_node_ids"))
            + _split_csv_ids(merge_row.get("related_node_ids"))
            + [diverge_node_id, merge_node_id]
        ),
        key=_sort_key,
    )
    for node_id in related_node_ids:
        node_index = node_index_by_id.get(node_id)
        if node_index is not None:
            node_features[node_index]["properties"][node_mainnodeid_field] = diverge_node_id

    repairs: list[dict[str, Any]] = []
    repairs.append(
        _update_node_kind_from_tool6(
            node_features=node_features,
            feature_index=diverge_index,
            node_id_field=node_id_field,
            node_kind_2_field=node_kind_2_field,
            after_kind_2=T_KIND_VALUE,
            error_row=diverge_row,
            repair_rule="tool6_divmerge_to_t_junction_main",
            audit_role="main",
            audit_mainnodeid=diverge_node_id,
        )
    )
    merge_feature = node_features[merge_index]
    merge_props = merge_feature["properties"]
    before_grade_2 = _coerce_int(merge_props.get(node_grade_2_field))
    repairs.append(
        _update_node_kind_from_tool6(
            node_features=node_features,
            feature_index=merge_index,
            node_id_field=node_id_field,
            node_kind_2_field=node_kind_2_field,
            after_kind_2=0,
            error_row=merge_row,
            repair_rule="tool6_divmerge_to_t_junction_member",
            audit_role="member",
            audit_mainnodeid=diverge_node_id,
            extra={"before_grade_2": before_grade_2, "after_grade_2": 0},
        )
    )
    merge_props[node_grade_2_field] = 0

    diverge_semantic_id = str(diverge_row.get("semantic_node_id") or diverge_node_id)
    merge_semantic_id = str(merge_row.get("semantic_node_id") or merge_node_id)
    deleted_indices = _direct_road_indices_between_semantic_nodes(
        parsed_roads=parsed_roads,
        node_to_semantic=node_to_semantic,
        first_semantic_id=diverge_semantic_id,
        second_semantic_id=merge_semantic_id,
    )
    for repair in repairs:
        repair["related_node_ids"] = ",".join(related_node_ids)
        repair["related_road_ids"] = ",".join(parsed_roads[index].road_id for index in sorted(deleted_indices))
        repair["deleted_road_ids"] = repair["related_road_ids"]
    return repairs, deleted_indices, []


def _apply_tool6_cross_row(
    *,
    row: dict[str, Any],
    node_features: list[dict[str, Any]],
    node_index_by_id: dict[str, int],
    node_id_field: str,
    node_kind_2_field: str,
) -> dict[str, Any] | None:
    if not _manual_fix_enabled(row.get(TOOL6_MANUAL_FIX_FIELD)):
        return None
    node_id = _tool6_source_node_id(row)
    if node_id is None:
        return None
    feature_index = node_index_by_id.get(node_id)
    if feature_index is None:
        return None
    after_kind_2 = T_KIND_VALUE if str(row.get("error_type") or "") == TOOL6_ERROR_CROSS_T else 1
    return _update_node_kind_from_tool6(
        node_features=node_features,
        feature_index=feature_index,
        node_id_field=node_id_field,
        node_kind_2_field=node_kind_2_field,
        after_kind_2=after_kind_2,
        error_row=row,
        repair_rule="tool6_cross_t_to_kind_2048" if after_kind_2 == T_KIND_VALUE else "tool6_cross_non_cross_to_kind_1",
        audit_role="main",
        audit_mainnodeid=str(row.get("semantic_node_id") or node_id),
    )


def _update_node_kind_from_tool6(
    *,
    node_features: list[dict[str, Any]],
    feature_index: int,
    node_id_field: str,
    node_kind_2_field: str,
    after_kind_2: int,
    error_row: dict[str, Any],
    repair_rule: str,
    audit_role: str,
    audit_mainnodeid: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    feature = node_features[feature_index]
    props = feature["properties"]
    before_kind_2 = _coerce_int(props.get(node_kind_2_field))
    props[node_kind_2_field] = after_kind_2
    node_id = _normalize_id(props.get(node_id_field)) or str(error_row.get("source_node_id") or "")
    row = {
        "semantic_node_id": str(error_row.get("semantic_node_id") or node_id),
        "source_node_id": node_id,
        "source_feature_index": feature_index,
        "node_id": node_id,
        "error_type": str(error_row.get("error_type") or ""),
        "error_reason": str(error_row.get("reason") or ""),
        "error_group_id": _tool6_group_id(error_row),
        "in_degree": _coerce_int(error_row.get("in_degree")),
        "out_degree": _coerce_int(error_row.get("out_degree")),
        "before_kind_2": before_kind_2,
        "after_kind_2": after_kind_2,
        "repair_rule": repair_rule,
        "related_node_ids": error_row.get("related_node_ids"),
        "related_road_ids": error_row.get("related_road_ids"),
        "audit_process": "tool6_qc_repair",
        "audit_role": audit_role,
        "audit_mainnodeid": audit_mainnodeid,
    }
    if extra:
        row.update(extra)
    return row


def _node_feature_index_by_id(node_features: list[dict[str, Any]], *, node_id_field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, feature in enumerate(node_features):
        node_id = _normalize_id(feature["properties"].get(node_id_field))
        if node_id is not None:
            result[node_id] = index
    return result


def _tool6_group_id(row: dict[str, Any]) -> str:
    value = _normalize_id(row.get("error_group_id"))
    return value or str(row.get("error_id") or row.get("semantic_node_id") or "")


def _tool6_source_node_id(row: dict[str, Any]) -> str | None:
    return _normalize_id(row.get("source_node_id")) or _normalize_id(row.get("semantic_node_id"))


def _manual_fix_enabled(value: Any) -> bool:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return False
    if isinstance(normalized, bool):
        return bool(normalized)
    if isinstance(normalized, (int, float)):
        return int(normalized) == 1
    return str(normalized).strip().lower() in {"1", "true", "yes", "y"}


def _first_tool6_role(rows: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("role") or "").strip().lower() == role:
            return row
    return None


def _split_csv_ids(value: Any) -> list[str]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return []
    return [text for item in str(normalized).split(",") if (text := item.strip())]


def _tool6_skip_row(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "error_group_id": _tool6_group_id(row),
        "error_type": str(row.get("error_type") or ""),
        "semantic_node_id": str(row.get("semantic_node_id") or ""),
        "source_node_id": str(row.get("source_node_id") or ""),
        "reason": reason,
    }


def _direct_road_indices_between_semantic_nodes(
    *,
    parsed_roads: list[ParsedRoad],
    node_to_semantic: dict[str, str],
    first_semantic_id: str,
    second_semantic_id: str,
) -> set[int]:
    result: set[int] = set()
    for index, road in enumerate(parsed_roads):
        source_semantic = node_to_semantic.get(road.snodeid)
        target_semantic = node_to_semantic.get(road.enodeid)
        if source_semantic is None or target_semantic is None:
            continue
        if {source_semantic, target_semantic} == {first_semantic_id, second_semantic_id}:
            result.add(index)
    return result


def _apply_t_junction_repairs(
    *,
    node_features: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    node_id_field: str,
    node_kind_2_field: str,
) -> list[dict[str, Any]]:
    repair_rows: list[dict[str, Any]] = []
    for row in errors:
        error_type = str(row.get("error_type"))
        if error_type not in {ERROR_T_JUNCTION, ERROR_DIVMERGE_ONE_IN_ONE_OUT}:
            continue
        feature_index = int(row["source_feature_index"])
        if feature_index < 0 or feature_index >= len(node_features):
            continue
        feature = node_features[feature_index]
        props = feature["properties"]
        before_kind_2 = _coerce_int(props.get(node_kind_2_field))
        in_degree = int(row.get("in_degree", 0))
        out_degree = int(row.get("out_degree", 0))
        if error_type == ERROR_DIVMERGE_ONE_IN_ONE_OUT:
            after_kind_2 = 1
            repair_rule = "divmerge_one_in_one_out_to_kind_1"
        else:
            after_kind_2 = 1 if in_degree == 0 or out_degree == 0 else 4
            repair_rule = (
                "zero_in_or_out_degree_to_kind_1"
                if after_kind_2 == 1
                else "nonzero_degree_error_to_kind_4"
            )
        props[node_kind_2_field] = after_kind_2
        repair_rows.append(
            {
                "semantic_node_id": str(row["semantic_node_id"]),
                "source_node_id": str(row["source_node_id"]),
                "source_feature_index": feature_index,
                "node_id": _normalize_id(props.get(node_id_field)),
                "error_type": error_type,
                "error_reason": row["error_reason"],
                "error_group_id": row["error_group_id"],
                "in_degree": in_degree,
                "out_degree": out_degree,
                "before_kind_2": before_kind_2,
                "after_kind_2": after_kind_2,
                "repair_rule": repair_rule,
                "related_node_ids": row.get("related_node_ids"),
                "related_road_ids": row.get("related_road_ids"),
            }
        )
    return repair_rows


def _build_audit_node_features(
    *,
    final_node_features: list[dict[str, Any]],
    node_id_field: str,
    repair_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    node_by_id = {
        normalized_id: feature
        for feature in final_node_features
        if (normalized_id := _normalize_id(feature["properties"].get(node_id_field))) is not None
    }
    audit_features: list[dict[str, Any]] = []
    seen_audit_ids: set[str] = set()
    for row in repair_rows:
        source_node_id = str(row["source_node_id"])
        source_feature = None
        feature_index = int(row.get("source_feature_index", -1))
        if 0 <= feature_index < len(final_node_features):
            source_feature = final_node_features[feature_index]
        if source_feature is None:
            source_feature = node_by_id.get(source_node_id)
        if source_feature is None:
            continue
        audit_process = str(row.get("audit_process") or "t_junction_repair")
        audit_id = f"{audit_process}:{row['error_group_id']}:{source_node_id}"
        if audit_id in seen_audit_ids:
            continue
        seen_audit_ids.add(audit_id)
        properties = dict(source_feature["properties"])
        properties.update(
            {
                "audit_id": audit_id,
                "audit_process": audit_process,
                "audit_group_id": str(row["error_group_id"]),
                "audit_role": str(row.get("audit_role") or "main"),
                "audit_mainnodeid": str(row.get("audit_mainnodeid") or row["semantic_node_id"]),
                "audit_source_node_id": source_node_id,
            }
        )
        audit_features.append({"properties": properties, "geometry": source_feature["geometry"]})
    return audit_features


def _build_error_features(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for row in errors:
        properties = {key: value for key, value in row.items() if key != "geometry"}
        features.append({"properties": properties, "geometry": row["geometry"]})
    return features


def _summary_error_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "geometry"}


def _line_metrics_from_geometry(geometry: BaseGeometry) -> tuple[float, tuple[float, float]]:
    endpoints = _line_endpoints(geometry)
    if endpoints is None:
        return float(geometry.length), (0.0, 0.0)
    start, end = endpoints
    forward_vector = _unit_vector((float(end[0]) - float(start[0]), float(end[1]) - float(start[1])))
    return float(geometry.length), forward_vector


def _line_endpoints(geometry: BaseGeometry) -> tuple[tuple[float, float], tuple[float, float]] | None:
    try:
        coords = list(geometry.coords) if hasattr(geometry, "coords") else []
    except NotImplementedError:
        coords = []
    if len(coords) >= 2:
        return (float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))
    for part in getattr(geometry, "geoms", ()):
        endpoints = _line_endpoints(part)
        if endpoints is not None:
            return endpoints
    return None


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


def _normalize_road_kind(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    return str(normalized).strip()


def _is_auxiliary_road_kind(kind: str | None) -> bool:
    return _has_road_kind_suffix(kind, AUXILIARY_ROAD_KIND_SUFFIX)


def _has_road_kind_suffix(kind: str | None, suffix: str) -> bool:
    if kind is None:
        return False
    normalized_suffix = suffix.lower()
    for token in str(kind).split("|"):
        text = token.strip().lower()
        if len(text) >= len(normalized_suffix) and text[-len(normalized_suffix) :] == normalized_suffix:
            return True
    return False


def _has_formway_bit(formway: int | None, bit_value: int) -> bool:
    return formway is not None and bool(int(formway) & int(bit_value))


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
