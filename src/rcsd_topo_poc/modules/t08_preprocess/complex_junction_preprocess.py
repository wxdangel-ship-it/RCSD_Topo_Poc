from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t02_junction_anchor.fix_node_error_2 import run_t02_fix_node_error_2
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

INTERSECTION_ID_FIELDS = (
    "id",
    "intersection_id",
    "intersectionid",
    "fid",
    "objectid",
    "OBJECTID",
)
NODE_ERROR_2_REASON = "intersection_shared_by_multiple_groups"


@dataclass(frozen=True)
class _GeneratedNodeError2:
    features: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass(frozen=True)
class T08ComplexJunctionPreprocessArtifacts:
    nodes_output: Path
    roads_output: Path
    audit_nodes_output: Path
    summary_output: Path


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
    output_nodes_path = ensure_gpkg_path(nodes_output, label="--nodes-output")
    output_roads_path = ensure_gpkg_path(roads_output, label="--roads-output")
    output_audit_nodes_path = ensure_gpkg_path(audit_nodes_output, label="--audit-nodes-output")
    node_error2_path = (
        ensure_gpkg_path(node_error2_gpkg, label="--node-error2-gpkg") if node_error2_gpkg is not None else None
    )
    intersection_path = (
        ensure_gpkg_path(intersection_gpkg, label="--intersection-gpkg") if intersection_gpkg is not None else None
    )
    if enable_one_to_many and node_error2_path is not None and intersection_path is None:
        raise ValueError("--intersection-gpkg must be provided when --node-error2-gpkg is used")

    summary_path = (
        Path(summary_output).expanduser().resolve()
        if summary_output
        else output_nodes_path.with_name("t08_complex_junction_preprocess_summary.json")
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
        with tempfile.TemporaryDirectory(prefix="t08_tool5_", dir=str(summary_path.parent)) as tmpdir:
            tmp_root = Path(tmpdir)
            tmp_nodes = tmp_root / "nodes_after_complex.gpkg"
            tmp_roads = tmp_root / "roads_after_complex.gpkg"
            tmp_generated_node_error2 = tmp_root / "generated_node_error_2.gpkg"
            tmp_nodes_fix = tmp_root / "nodes_after_one_to_many.gpkg"
            tmp_roads_fix = tmp_root / "roads_after_one_to_many.gpkg"
            tmp_report = tmp_root / "one_to_many_report.json"
            write_gpkg(tmp_nodes, node_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_nodes)
            write_gpkg(tmp_roads, road_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_roads)
            effective_node_error2_path = node_error2_path
            effective_node_error2_crs = node_error2_crs_text
            if effective_node_error2_path is None:
                generated = _build_node_error2_from_intersections(
                    node_features=node_features,
                    intersection_path=intersection_path,
                    node_id_field=node_id_field,
                    intersection_layer=intersection_layer,
                    intersection_crs_text=intersection_crs_text,
                    target_epsg=target_epsg,
                )
                node_error2_detection_summary = generated.summary
                if generated.features:
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
                node_error2_detection_summary = _empty_node_error2_detection_summary(
                    status="provided",
                    skip_reason=None,
                    node_error2_source="provided_node_error_2",
                )

            if effective_node_error2_path is not None:
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
                one_to_many_executed = True
                one_to_many_summary = json.loads(tmp_report.read_text(encoding="utf-8"))
                one_to_many_summary["output_files"] = {
                    "nodes_fix_path": str(output_nodes_path),
                    "roads_fix_path": str(output_roads_path),
                }
                nodes_fix_result = read_vector(tmp_nodes_fix, default_crs_text=f"EPSG:{target_epsg}", target_epsg=target_epsg)
                roads_fix_result = read_vector(tmp_roads_fix, default_crs_text=f"EPSG:{target_epsg}", target_epsg=target_epsg)
                final_node_features = [
                    {"properties": dict(feature.properties), "geometry": feature.geometry} for feature in nodes_fix_result.features
                ]
                final_road_features = [
                    {"properties": dict(feature.properties), "geometry": feature.geometry} for feature in roads_fix_result.features
                ]
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


def _ensure_type_2_fields(
    *,
    node_features: list[dict[str, Any]],
    kind_field: str,
    grade_field: str,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> int:
    initialized = 0
    for index, feature in enumerate(node_features, start=1):
        props = feature["properties"]
        if "kind_2" not in props:
            props["kind_2"] = props.get(kind_field)
            initialized += 1
        if "grade_2" not in props:
            props["grade_2"] = props.get(grade_field)
            initialized += 1
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool5] prepared {index} node feature(s)")
    return initialized


def _build_node_error2_from_intersections(
    *,
    node_features: list[dict[str, Any]],
    intersection_path: Path,
    node_id_field: str,
    intersection_layer: str | None,
    intersection_crs_text: str | None,
    target_epsg: int,
) -> _GeneratedNodeError2:
    intersection_result = read_vector(
        intersection_path,
        layer_name=intersection_layer,
        default_crs_text=intersection_crs_text,
        target_epsg=target_epsg,
    )
    if not intersection_result.features:
        return _GeneratedNodeError2(
            features=[],
            summary=_empty_node_error2_detection_summary(
                status="skipped",
                skip_reason="intersection_input_empty",
                intersection_source_crs=None,
                intersection_crs_source=None,
            ),
        )

    groups_by_id = _semantic_groups_for_node_error2(node_features, node_id_field=node_id_field)
    node_tree_records = [
        (feature["geometry"], _semantic_group_id(feature["properties"], node_id_field))
        for feature in node_features
        if feature.get("geometry") is not None
        and not feature["geometry"].is_empty
        and _semantic_group_id(feature["properties"], node_id_field) in groups_by_id
    ]
    if not node_tree_records:
        return _GeneratedNodeError2(
            features=[],
            summary=_empty_node_error2_detection_summary(
                status="skipped",
                skip_reason="no_semantic_nodes",
                intersection_feature_count=len(intersection_result.features),
                intersection_source_crs=intersection_result.source_crs.to_string(),
                intersection_crs_source=intersection_result.crs_source,
            ),
        )

    node_geometries = [record[0] for record in node_tree_records]
    node_group_ids = [str(record[1]) for record in node_tree_records]
    node_tree = STRtree(node_geometries)
    group_to_intersection_ids: dict[str, set[str]] = {}
    rows: list[dict[str, Any]] = []

    for intersection_index, intersection in enumerate(intersection_result.features):
        intersection_id = _intersection_identity(intersection.properties, intersection_index)
        if intersection.geometry is None or intersection.geometry.is_empty:
            rows.append(
                {
                    "intersection_id": intersection_id,
                    "candidate_group_ids": [],
                    "candidate_group_count": 0,
                    "ignored_kind1_group_ids": [],
                    "remaining_group_ids": [],
                    "remaining_group_count": 0,
                    "status": "skipped",
                    "skip_reason": "empty_intersection_geometry",
                }
            )
            continue

        candidate_indexes = node_tree.query(intersection.geometry, predicate="intersects")
        candidate_group_ids = sorted({node_group_ids[int(index)] for index in candidate_indexes}, key=_sort_key)
        groups_with_representative = [
            group_id for group_id in candidate_group_ids if groups_by_id[group_id]["representative_node_id"] is not None
        ]
        unresolved_group_ids = [
            group_id for group_id in candidate_group_ids if groups_by_id[group_id]["representative_node_id"] is None
        ]
        ignored_kind1_group_ids = [
            group_id
            for group_id in groups_with_representative
            if _normalize_id(groups_by_id[group_id]["representative_kind_2"]) == "1"
        ]
        remaining_group_ids = [
            group_id
            for group_id in groups_with_representative
            if _normalize_id(groups_by_id[group_id]["representative_kind_2"]) != "1"
        ]
        row: dict[str, Any] = {
            "intersection_id": intersection_id,
            "candidate_group_ids": candidate_group_ids,
            "candidate_group_count": len(candidate_group_ids),
            "unresolved_group_ids": unresolved_group_ids,
            "ignored_kind1_group_ids": ignored_kind1_group_ids,
            "ignored_kind1_group_count": len(ignored_kind1_group_ids),
            "remaining_group_ids": remaining_group_ids,
            "remaining_group_count": len(remaining_group_ids),
            "status": "skipped",
            "skip_reason": None,
        }
        if len(candidate_group_ids) <= 1:
            row["skip_reason"] = "single_group_in_intersection"
        elif len(remaining_group_ids) <= 1:
            row["skip_reason"] = "single_group_after_kind1_filter"
        else:
            row["status"] = "generated"
            row["skip_reason"] = None
            for group_id in remaining_group_ids:
                group_to_intersection_ids.setdefault(group_id, set()).add(intersection_id)
        rows.append(row)

    generated_features: list[dict[str, Any]] = []
    for group_id in sorted(group_to_intersection_ids, key=_sort_key):
        intersection_ids = sorted(group_to_intersection_ids[group_id], key=_sort_key)
        group = groups_by_id[group_id]
        for feature in group["features"]:
            props = dict(feature["properties"])
            node_id = _normalize_id(props.get(node_id_field))
            if node_id is None:
                continue
            props.update(
                {
                    "id": node_id,
                    "junction_id": group_id,
                    "error_type": "node_error_2",
                    "error_reason": NODE_ERROR_2_REASON,
                    "intersection_ids": ",".join(intersection_ids),
                    "intersection_count": len(intersection_ids),
                }
            )
            generated_features.append({"properties": props, "geometry": feature["geometry"]})

    summary = {
        "status": "generated" if generated_features else "skipped",
        "skip_reason": None if generated_features else "generated_node_error_2_empty",
        "node_error2_source": "generated_from_intersection",
        "target_epsg": target_epsg,
        "input_crs": {
            "intersection": intersection_result.source_crs.to_string(),
            "intersection_crs_source": intersection_result.crs_source,
        },
        "counts": {
            "intersection_feature_count": len(intersection_result.features),
            "candidate_intersection_count": sum(1 for row in rows if row["candidate_group_count"] > 1),
            "generated_intersection_count": sum(1 for row in rows if row["status"] == "generated"),
            "generated_group_count": len(group_to_intersection_ids),
            "generated_feature_count": len(generated_features),
        },
        "rows": rows,
    }
    return _GeneratedNodeError2(features=generated_features, summary=summary)


def _semantic_groups_for_node_error2(
    node_features: list[dict[str, Any]],
    *,
    node_id_field: str,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for output_index, feature in enumerate(node_features):
        props = feature["properties"]
        node_id = _normalize_id(props.get(node_id_field))
        group_id = _semantic_group_id(props, node_id_field)
        if node_id is None or group_id is None:
            continue
        group = groups.setdefault(
            group_id,
            {
                "features": [],
                "node_ids": [],
                "representative_node_id": None,
                "representative_kind_2": None,
                "representative_output_index": None,
            },
        )
        group["features"].append(feature)
        group["node_ids"].append(node_id)
        if node_id == group_id:
            group["representative_node_id"] = node_id
            group["representative_kind_2"] = _normalize_id(props.get("kind_2"))
            group["representative_output_index"] = output_index
    return groups


def _empty_node_error2_detection_summary(
    *,
    status: str,
    skip_reason: str | None,
    node_error2_source: str = "generated_from_intersection",
    intersection_feature_count: int = 0,
    intersection_source_crs: str | None = None,
    intersection_crs_source: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "skip_reason": skip_reason,
        "node_error2_source": node_error2_source,
        "input_crs": {
            "intersection": intersection_source_crs,
            "intersection_crs_source": intersection_crs_source,
        },
        "counts": {
            "intersection_feature_count": intersection_feature_count,
            "candidate_intersection_count": 0,
            "generated_intersection_count": 0,
            "generated_group_count": 0,
            "generated_feature_count": 0,
        },
        "rows": [],
    }


def _intersection_identity(properties: dict[str, Any], feature_index: int) -> str:
    for field in INTERSECTION_ID_FIELDS:
        value = _normalize_id(properties.get(field))
        if value is not None:
            return f"{field}:{value}"
    return f"feature_index:{feature_index}"


def _semantic_group_id(properties: dict[str, Any], node_id_field: str) -> str | None:
    return _normalize_id(properties.get("mainnodeid")) or _normalize_id(properties.get(node_id_field))


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "nan"}:
            return None
        return text
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sort_key(value: Any) -> tuple[int, Any]:
    normalized = _normalize_id(value)
    if normalized is None:
        return (2, "")
    if normalized.isdigit():
        return (0, int(normalized))
    try:
        return (0, int(float(normalized)))
    except Exception:
        return (1, normalized)


def _build_audit_node_features(
    *,
    final_node_features: list[dict[str, Any]],
    node_id_field: str,
    complex_summary: dict[str, Any],
    one_to_many_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    node_by_id = {
        str(feature["properties"].get(node_id_field)): feature
        for feature in final_node_features
        if feature["properties"].get(node_id_field) is not None
    }
    audit_rows: list[dict[str, str | None]] = []
    for row in complex_summary.get("rows", []):
        if row.get("status") != "aggregated":
            continue
        group_id = str(row.get("component_id") or "")
        mainnodeid = str(row.get("mainnodeid") or "")
        for node_id in row.get("node_ids") or []:
            source_node_id = str(node_id)
            audit_rows.append(
                {
                    "process": "complex_divmerge",
                    "group_id": group_id,
                    "source_node_id": source_node_id,
                    "mainnodeid": mainnodeid,
                    "role": "main" if source_node_id == mainnodeid else "member",
                }
            )
    for row in one_to_many_summary.get("rows", []):
        if row.get("status") != "merged":
            continue
        group_id = str(row.get("intersection_id") or "")
        mainnodeid = str(row.get("chosen_mainnodeid") or "")
        for node_id in row.get("merged_node_ids") or []:
            source_node_id = str(node_id)
            audit_rows.append(
                {
                    "process": "one_to_many",
                    "group_id": group_id,
                    "source_node_id": source_node_id,
                    "mainnodeid": mainnodeid,
                    "role": "main" if source_node_id == mainnodeid else "member",
                }
            )

    audit_features: list[dict[str, Any]] = []
    seen_audit_ids: set[str] = set()
    for row in audit_rows:
        source_node_id = str(row["source_node_id"])
        source_feature = node_by_id.get(source_node_id)
        if source_feature is None:
            continue
        audit_id = f"{row['process']}:{row['group_id']}:{source_node_id}"
        if audit_id in seen_audit_ids:
            continue
        seen_audit_ids.add(audit_id)
        properties = dict(source_feature["properties"])
        properties.update(
            {
                "audit_id": audit_id,
                "audit_process": row["process"],
                "audit_group_id": row["group_id"],
                "audit_role": row["role"],
                "audit_mainnodeid": row["mainnodeid"],
                "audit_source_node_id": source_node_id,
            }
        )
        audit_features.append({"properties": properties, "geometry": source_feature["geometry"]})
    return audit_features


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _retag_complex_progress(callback: ProgressCallback | None) -> ProgressCallback | None:
    if callback is None:
        return None

    def _wrapped(message: str) -> None:
        if message.startswith("[T08 Tool3] complex_divmerge"):
            message = message.replace("[T08 Tool3]", "[T08 Tool5]", 1)
        callback(message)

    return _wrapped


__all__ = [
    "T08ComplexJunctionPreprocessArtifacts",
    "run_t08_complex_junction_preprocess",
]
