from __future__ import annotations

import json

import math

import tempfile

import time

from collections import Counter, defaultdict, deque

from collections.abc import Callable, Iterable

from dataclasses import dataclass

from pathlib import Path

from typing import Any

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t02_junction_anchor.fix_node_error_2 import run_t02_fix_node_error_2

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name

from rcsd_topo_poc.modules.t08_preprocess.nodes_type_aggregation import (
    _apply_complex_divmerge_aggregation,
    _elapsed_since,
    _empty_complex_summary,
    _first_non_empty_value,
    _items_per_second,
    _optional_field,
    _should_emit_progress,
)

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    aggregate_bounds,
    ensure_gpkg_path,
    read_vector,
    resolve_field_name,
    unique_field_names,
    write_gpkg,
    write_json,
)

ProgressCallback = Callable[[str], None]

T_JUNCTION_KIND_2 = "2048"

T_PAIR_HORIZONTAL_ANGLE_DEGREES = 35.0

T_PAIR_OPPOSITE_PARALLEL_ANGLE_DEGREES = 20.0

INTERSECTION_ID_FIELDS = (
    "id",
    "intersection_id",
    "intersectionid",
    "fid",
    "objectid",
    "OBJECTID",
)

NODE_ERROR_2_REASON = "intersection_shared_by_multiple_groups"

__all__ = [
    "T08ComplexJunctionPreprocessArtifacts",
    "run_t08_complex_junction_preprocess",
]


from . import complex_junction_preprocess as _facade


def T08ComplexJunctionPreprocessArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T08ComplexJunctionPreprocessArtifacts(*args, **kwargs)


def _apply_t_pair_one_to_many_fallback(*args: Any, **kwargs: Any) -> Any:
    return _facade._apply_t_pair_one_to_many_fallback(*args, **kwargs)


def _build_audit_node_features(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_audit_node_features(*args, **kwargs)


def _build_node_error2_from_intersections(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_node_error2_from_intersections(*args, **kwargs)


def _emit_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._emit_progress(*args, **kwargs)


def _empty_node_error2_detection_summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._empty_node_error2_detection_summary(*args, **kwargs)


def _ensure_type_2_fields(*args: Any, **kwargs: Any) -> Any:
    return _facade._ensure_type_2_fields(*args, **kwargs)


def _retag_complex_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._retag_complex_progress(*args, **kwargs)


def run_t08_complex_junction_preprocess(
    *,
    nodes_gpkg: str | Path,
    roads_gpkg: str | Path,
    nodes_output: str | Path,
    roads_output: str | Path,
    audit_nodes_output: str | Path,
    node_error2_gpkg: str | Path | None = None,
    intersection_gpkg: str | Path | None = None,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    node_error2_layer: str | None = None,
    intersection_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    nodes_default_crs_text: str | None = None,
    roads_default_crs_text: str | None = None,
    node_error2_crs_text: str | None = None,
    intersection_crs_text: str | None = None,
    enable_complex_divmerge: bool = True,
    enable_one_to_many: bool = True,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08ComplexJunctionPreprocessArtifacts:
    started = time.perf_counter()
    stage_timings: dict[str, float] = {}
    nodes_path = ensure_gpkg_path(nodes_gpkg, label="--nodes-gpkg")
    roads_path = ensure_gpkg_path(roads_gpkg, label="--roads-gpkg")
    output_nodes_path = ensure_tool_output_name(
        ensure_gpkg_path(nodes_output, label="--nodes-output"),
        tool_number=5,
        label="--nodes-output",
    )
    output_roads_path = ensure_tool_output_name(
        ensure_gpkg_path(roads_output, label="--roads-output"),
        tool_number=5,
        label="--roads-output",
    )
    output_audit_nodes_path = ensure_tool_output_name(
        ensure_gpkg_path(audit_nodes_output, label="--audit-nodes-output"),
        tool_number=5,
        label="--audit-nodes-output",
    )
    node_error2_path = (
        ensure_gpkg_path(node_error2_gpkg, label="--node-error2-gpkg") if node_error2_gpkg is not None else None
    )
    intersection_path = (
        ensure_gpkg_path(intersection_gpkg, label="--intersection-gpkg") if intersection_gpkg is not None else None
    )
    if enable_one_to_many and node_error2_path is not None and intersection_path is None:
        raise ValueError("--intersection-gpkg must be provided when --node-error2-gpkg is used")

    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=5, label="--summary-output")
        if summary_output
        else output_nodes_path.with_name("t08_complex_junction_preprocess_summary_tool5.json")
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    _emit_progress(progress_callback, f"[T08 Tool5] start nodes={nodes_path} roads={roads_path}")
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
        f"[T08 Tool5] loaded nodes={len(nodes_result.features)} roads={len(roads_result.features)}",
    )
    stage_started = time.perf_counter()
    node_id_field = resolve_field_name(nodes_result.features, ["id"], "nodes input")
    node_kind_field = resolve_field_name(nodes_result.features, ["kind"], "nodes input")
    node_grade_field = resolve_field_name(nodes_result.features, ["grade"], "nodes input")
    road_id_field = resolve_field_name(roads_result.features, ["id"], "roads input")
    road_snode_field = resolve_field_name(roads_result.features, ["snodeid"], "roads input")
    road_enode_field = resolve_field_name(roads_result.features, ["enodeid"], "roads input")
    road_kind_field = _optional_field(roads_result.features, ["kind"])
    road_direction_field = (
        resolve_field_name(roads_result.features, ["direction"], "roads input")
        if enable_complex_divmerge
        else _optional_field(roads_result.features, ["direction"])
    )
    node_features = [
        {"properties": dict(feature.properties), "geometry": feature.geometry}
        for feature in nodes_result.features
    ]
    road_features = [
        {"properties": dict(feature.properties), "geometry": feature.geometry}
        for feature in roads_result.features
    ]
    initialized_type_field_count = _ensure_type_2_fields(
        node_features=node_features,
        kind_field=node_kind_field,
        grade_field=node_grade_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    stage_timings["prepare_fields_seconds"] = _elapsed_since(stage_started)

    kind_sample = _first_non_empty_value(nodes_result.features, node_kind_field)
    grade_sample = _first_non_empty_value(nodes_result.features, node_grade_field)
    complex_summary: dict[str, Any] = _empty_complex_summary()
    if enable_complex_divmerge:
        stage_started = time.perf_counter()
        _emit_progress(progress_callback, "[T08 Tool5] complex_divmerge: start")
        complex_summary = _apply_complex_divmerge_aggregation(
            node_features=node_features,
            road_features=road_features,
            node_id_field=node_id_field,
            node_kind_field=node_kind_field,
            node_grade_field=node_grade_field,
            road_id_field=road_id_field,
            road_snode_field=road_snode_field,
            road_enode_field=road_enode_field,
            road_direction_field=road_direction_field,
            kind_sample=kind_sample,
            grade_sample=grade_sample,
            progress_callback=_retag_complex_progress(progress_callback),
            progress_interval=progress_interval,
        )
        stage_timings["complex_divmerge_seconds"] = _elapsed_since(stage_started)
        _emit_progress(
            progress_callback,
            (
                f"[T08 Tool5] complex_divmerge: junctions={complex_summary['complex_junction_count']} "
                f"updated_nodes={complex_summary['updated_node_count']} "
                f"elapsed={stage_timings['complex_divmerge_seconds']:.2f}s"
            ),
        )

    one_to_many_summary: dict[str, Any]
    node_error2_detection_summary: dict[str, Any] = _empty_node_error2_detection_summary(
        status="skipped",
        skip_reason="disabled_by_param" if not enable_one_to_many else "intersection_input_not_provided",
    )
    one_to_many_requested = bool(enable_one_to_many and intersection_path is not None)
    one_to_many_executed = False
    output_fields_nodes = unique_field_names(
        nodes_result.field_names,
        extra=("kind_2", "grade_2", "mainnodeid", "subnodeid"),
    )
    output_fields_roads = unique_field_names(roads_result.field_names)
    final_node_features: list[dict[str, Any]]
    final_road_features: list[dict[str, Any]]
    if one_to_many_requested:
        stage_started = time.perf_counter()
        _emit_progress(progress_callback, "[T08 Tool5] one_to_many: start")
        with tempfile.TemporaryDirectory(prefix="t08_tool5_") as tmpdir:
            tmp_root = Path(tmpdir)
            _emit_progress(progress_callback, f"[T08 Tool5] one_to_many: temp workspace={tmp_root}")
            tmp_nodes = tmp_root / "nodes_after_complex.gpkg"
            tmp_roads = tmp_root / "roads_after_complex.gpkg"
            tmp_generated_node_error2 = tmp_root / "generated_node_error_2.gpkg"
            tmp_nodes_fix = tmp_root / "nodes_after_one_to_many.gpkg"
            tmp_roads_fix = tmp_root / "roads_after_one_to_many.gpkg"
            tmp_report = tmp_root / "one_to_many_report.json"
            effective_node_error2_path = node_error2_path
            effective_node_error2_crs = node_error2_crs_text
            if effective_node_error2_path is None:
                sub_stage_started = time.perf_counter()
                _emit_progress(progress_callback, "[T08 Tool5] node_error_2: generating from intersections")
                generated = _build_node_error2_from_intersections(
                    node_features=node_features,
                    intersection_path=intersection_path,
                    node_id_field=node_id_field,
                    intersection_layer=intersection_layer,
                    intersection_crs_text=intersection_crs_text,
                    target_epsg=target_epsg,
                    progress_callback=progress_callback,
                    progress_interval=progress_interval,
                )
                stage_timings["one_to_many_generate_node_error2_seconds"] = _elapsed_since(sub_stage_started)
                node_error2_detection_summary = generated.summary
                if generated.features:
                    _emit_progress(
                        progress_callback,
                        f"[T08 Tool5] node_error_2: writing generated features={len(generated.features)}",
                    )
                    generated_fields = unique_field_names(
                        output_fields_nodes,
                        extra=("junction_id", "error_type", "error_reason", "intersection_ids", "intersection_count"),
                    )
                    write_gpkg(
                        tmp_generated_node_error2,
                        generated.features,
                        crs_text=f"EPSG:{target_epsg}",
                        empty_fields=generated_fields,
                        geometry_type="Point",
                    )
                    effective_node_error2_path = tmp_generated_node_error2
                    effective_node_error2_crs = f"EPSG:{target_epsg}"
                else:
                    _emit_progress(progress_callback, "[T08 Tool5] node_error_2: no generated candidates")
            else:
                node_error2_detection_summary = _empty_node_error2_detection_summary(
                    status="provided",
                    skip_reason=None,
                    node_error2_source="provided_node_error_2",
                )

            if effective_node_error2_path is not None:
                sub_stage_started = time.perf_counter()
                _emit_progress(progress_callback, "[T08 Tool5] one_to_many: writing temporary inputs")
                write_gpkg(tmp_nodes, node_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_nodes)
                write_gpkg(tmp_roads, road_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_roads)
                stage_timings["one_to_many_write_temp_inputs_seconds"] = _elapsed_since(sub_stage_started)
                sub_stage_started = time.perf_counter()
                _emit_progress(progress_callback, "[T08 Tool5] one_to_many: running T02 node_error_2 repair")
                run_t02_fix_node_error_2(
                    node_error2_path=effective_node_error2_path,
                    nodes_path=tmp_nodes,
                    roads_path=tmp_roads,
                    intersection_path=intersection_path,
                    nodes_fix_path=tmp_nodes_fix,
                    roads_fix_path=tmp_roads_fix,
                    report_path=tmp_report,
                    node_error2_layer=node_error2_layer if node_error2_path is not None else None,
                    nodes_layer=None,
                    roads_layer=None,
                    intersection_layer=intersection_layer,
                    node_error2_crs=effective_node_error2_crs,
                    nodes_crs=f"EPSG:{target_epsg}",
                    roads_crs=f"EPSG:{target_epsg}",
                    intersection_crs=intersection_crs_text,
                )
                stage_timings["one_to_many_t02_fix_seconds"] = _elapsed_since(sub_stage_started)
                one_to_many_executed = True
                one_to_many_summary = json.loads(tmp_report.read_text(encoding="utf-8"))
                one_to_many_summary["output_files"] = {
                    "nodes_fix_path": str(output_nodes_path),
                    "roads_fix_path": str(output_roads_path),
                }
                sub_stage_started = time.perf_counter()
                _emit_progress(progress_callback, "[T08 Tool5] one_to_many: reading temporary outputs")
                nodes_fix_result = read_vector(tmp_nodes_fix, default_crs_text=f"EPSG:{target_epsg}", target_epsg=target_epsg)
                roads_fix_result = read_vector(tmp_roads_fix, default_crs_text=f"EPSG:{target_epsg}", target_epsg=target_epsg)
                final_node_features = [
                    {"properties": dict(feature.properties), "geometry": feature.geometry} for feature in nodes_fix_result.features
                ]
                final_road_features = [
                    {"properties": dict(feature.properties), "geometry": feature.geometry} for feature in roads_fix_result.features
                ]
                stage_timings["one_to_many_read_temp_outputs_seconds"] = _elapsed_since(sub_stage_started)
                fallback_started = time.perf_counter()
                fallback_summary = _apply_t_pair_one_to_many_fallback(
                    final_node_features=final_node_features,
                    final_road_features=final_road_features,
                    one_to_many_summary=one_to_many_summary,
                    intersection_path=intersection_path,
                    intersection_layer=intersection_layer,
                    intersection_crs_text=intersection_crs_text,
                    target_epsg=target_epsg,
                    node_id_field=node_id_field,
                    road_id_field=road_id_field,
                    road_snode_field=road_snode_field,
                    road_enode_field=road_enode_field,
                    road_direction_field=road_direction_field,
                    road_kind_field=road_kind_field,
                    progress_callback=progress_callback,
                )
                one_to_many_summary["tool5_t_pair_virtual_connectivity"] = fallback_summary
                stage_timings["one_to_many_t_pair_fallback_seconds"] = _elapsed_since(fallback_started)
            else:
                final_node_features = node_features
                final_road_features = road_features
                one_to_many_summary = {
                    "success": True,
                    "status": "skipped",
                    "skip_reason": "generated_node_error_2_empty",
                    "counts": {
                        "node_error_2_feature_count": 0,
                        "intersection_feature_count": node_error2_detection_summary["counts"]["intersection_feature_count"],
                        "merged_intersection_count": 0,
                        "skipped_intersection_count": node_error2_detection_summary["counts"]["intersection_feature_count"],
                        "deleted_road_count": 0,
                    },
                    "rows": node_error2_detection_summary["rows"],
                }

            sub_stage_started = time.perf_counter()
            _emit_progress(progress_callback, "[T08 Tool5] one_to_many: writing final outputs")
            write_gpkg(
                output_nodes_path,
                final_node_features,
                crs_text=f"EPSG:{target_epsg}",
                empty_fields=output_fields_nodes,
            )
            write_gpkg(
                output_roads_path,
                final_road_features,
                crs_text=f"EPSG:{target_epsg}",
                empty_fields=output_fields_roads,
            )
            stage_timings["one_to_many_write_final_outputs_seconds"] = _elapsed_since(sub_stage_started)
        stage_timings["one_to_many_seconds"] = _elapsed_since(stage_started)
        _emit_progress(
            progress_callback,
            (
                "[T08 Tool5] one_to_many: merged_intersections="
                f"{one_to_many_summary.get('counts', {}).get('merged_intersection_count', 0)} "
                f"elapsed={stage_timings['one_to_many_seconds']:.2f}s"
            ),
        )
    else:
        stage_started = time.perf_counter()
        _emit_progress(progress_callback, f"[T08 Tool5] writing outputs nodes={output_nodes_path} roads={output_roads_path}")
        final_node_features = node_features
        final_road_features = road_features
        write_gpkg(output_nodes_path, node_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_nodes)
        write_gpkg(output_roads_path, road_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_roads)
        stage_timings["write_output_seconds"] = _elapsed_since(stage_started)
        one_to_many_summary = {
            "success": True,
            "status": "skipped",
            "skip_reason": "inputs_not_provided" if enable_one_to_many else "disabled_by_param",
            "counts": {
                "merged_intersection_count": 0,
                "skipped_intersection_count": 0,
                "deleted_road_count": 0,
            },
            "rows": [],
        }

    stage_started = time.perf_counter()
    audit_node_features = _build_audit_node_features(
        final_node_features=final_node_features,
        node_id_field=node_id_field,
        complex_summary=complex_summary,
        one_to_many_summary=one_to_many_summary,
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
    _emit_progress(progress_callback, f"[T08 Tool5] writing audit nodes={output_audit_nodes_path}")
    write_gpkg(
        output_audit_nodes_path,
        audit_node_features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=audit_output_fields,
        geometry_type="Point",
    )
    stage_timings["write_audit_nodes_seconds"] = _elapsed_since(stage_started)

    elapsed_seconds = _elapsed_since(started)
    summary = {
        "tool": "T08 Tool5",
        "stage": "complex_junction_preprocess",
        "target_epsg": target_epsg,
        "input_paths": {
            "nodes_gpkg": nodes_path,
            "roads_gpkg": roads_path,
            "node_error2_gpkg": node_error2_path,
            "intersection_gpkg": intersection_path,
        },
        "output_paths": {
            "nodes_output": output_nodes_path,
            "roads_output": output_roads_path,
            "audit_nodes_output": output_audit_nodes_path,
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
            "node_error2_layer": node_error2_layer,
            "intersection_layer": intersection_layer,
            "enable_complex_divmerge": enable_complex_divmerge,
            "enable_one_to_many": enable_one_to_many,
            "one_to_many_executed": one_to_many_executed,
        },
        "field_audit": {
            "node_id_field": node_id_field,
            "node_kind_field": node_kind_field,
            "node_grade_field": node_grade_field,
            "road_id_field": road_id_field,
            "road_snode_field": road_snode_field,
            "road_enode_field": road_enode_field,
            "road_direction_field": road_direction_field,
            "road_kind_field": road_kind_field,
            "initialized_type_field_count": initialized_type_field_count,
        },
        "counts": {
            "node_feature_count": len(node_features),
            "road_feature_count": len(road_features),
            "complex_junction_count": complex_summary["complex_junction_count"],
            "complex_updated_node_count": complex_summary["updated_node_count"],
            "one_to_many_merged_intersection_count": one_to_many_summary.get("counts", {}).get(
                "merged_intersection_count", 0
            ),
            "one_to_many_deleted_road_count": one_to_many_summary.get("counts", {}).get("deleted_road_count", 0),
            "node_error_2_generated_feature_count": node_error2_detection_summary.get("counts", {}).get(
                "generated_feature_count", 0
            ),
            "node_error_2_detected_group_count": node_error2_detection_summary.get("counts", {}).get(
                "generated_group_count", 0
            ),
            "audit_node_feature_count": len(audit_node_features),
        },
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in final_node_features),
        "audit_nodes_bounds": aggregate_bounds(feature["geometry"] for feature in audit_node_features),
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "nodes_per_second": _items_per_second(len(node_features), elapsed_seconds),
            "stage_timings": {key: round(value, 6) for key, value in stage_timings.items()},
        },
        "complex_divmerge": complex_summary,
        "node_error_2_detection": node_error2_detection_summary,
        "one_to_many": one_to_many_summary,
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        (
            f"[T08 Tool5] finished nodes={len(node_features)} roads={len(road_features)} "
            f"elapsed={elapsed_seconds:.2f}s summary={summary_path}"
        ),
    )
    return T08ComplexJunctionPreprocessArtifacts(
        nodes_output=output_nodes_path,
        roads_output=output_roads_path,
        audit_nodes_output=output_audit_nodes_path,
        summary_output=summary_path,
    )
