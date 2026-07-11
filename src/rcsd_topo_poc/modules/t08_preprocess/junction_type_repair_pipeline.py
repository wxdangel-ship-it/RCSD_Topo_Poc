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

TOOL6_ERROR_CROSS_DIVERGE = "错误交叉路口_分歧路口"

TOOL6_ERROR_CROSS_MERGE = "错误交叉路口_合流路口"

TOOL6_MANUAL_FIX_FIELD = "是否修复"

ProgressCallback = Callable[[str], None]


from . import junction_type_repair as _facade


def T08JunctionTypeRepairArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T08JunctionTypeRepairArtifacts(*args, **kwargs)


def _apply_t_junction_repairs(*args: Any, **kwargs: Any) -> Any:
    return _facade._apply_t_junction_repairs(*args, **kwargs)


def _apply_tool6_qc_repairs(*args: Any, **kwargs: Any) -> Any:
    return _facade._apply_tool6_qc_repairs(*args, **kwargs)


def _build_audit_node_features(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_audit_node_features(*args, **kwargs)


def _build_semantic_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_semantic_nodes(*args, **kwargs)


def _build_topology(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_topology(*args, **kwargs)


def _detect_junction_type_errors(*args: Any, **kwargs: Any) -> Any:
    return _facade._detect_junction_type_errors(*args, **kwargs)


def _elapsed_since(*args: Any, **kwargs: Any) -> Any:
    return _facade._elapsed_since(*args, **kwargs)


def _emit_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._emit_progress(*args, **kwargs)


def _items_per_second(*args: Any, **kwargs: Any) -> Any:
    return _facade._items_per_second(*args, **kwargs)


def _optional_field(*args: Any, **kwargs: Any) -> Any:
    return _facade._optional_field(*args, **kwargs)


def _parse_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._parse_nodes(*args, **kwargs)


def _read_roads_for_tool4(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_roads_for_tool4(*args, **kwargs)


def _read_tool6_node_error_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_tool6_node_error_rows(*args, **kwargs)


def _summary_error_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._summary_error_row(*args, **kwargs)


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
            "topology_road_count": len(parsed_roads) - len(topology.skipped_missing_node_roads),
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
            "skipped_missing_node_road_count": len(topology.skipped_missing_node_roads),
            "advance_right_turn_road_count": sum(1 for road in parsed_roads if road.is_advance_right_turn),
            "auxiliary_road_count": sum(1 for road in parsed_roads if road.is_auxiliary),
            "degree_exception_suppressed_count": sum(1 for row in degree_exception_rows if row["status"] == "suppressed"),
        },
        "direction_errors": list(topology.direction_errors),
        "skipped_missing_node_roads": list(topology.skipped_missing_node_roads),
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
