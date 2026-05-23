from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    if enable_one_to_many and (node_error2_path is None) != (intersection_path is None):
        raise ValueError("--node-error2-gpkg and --intersection-gpkg must be provided together for one-to-many repair")

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
    one_to_many_enabled = bool(enable_one_to_many and node_error2_path is not None and intersection_path is not None)
    output_fields_nodes = unique_field_names(
        nodes_result.field_names,
        extra=("kind_2", "grade_2", "mainnodeid", "subnodeid"),
    )
    output_fields_roads = unique_field_names(roads_result.field_names)
    final_node_features: list[dict[str, Any]]
    final_road_features: list[dict[str, Any]]
    if one_to_many_enabled:
        stage_started = time.perf_counter()
        _emit_progress(progress_callback, "[T08 Tool5] one_to_many: start")
        with tempfile.TemporaryDirectory(prefix="t08_tool5_", dir=str(summary_path.parent)) as tmpdir:
            tmp_root = Path(tmpdir)
            tmp_nodes = tmp_root / "nodes_after_complex.gpkg"
            tmp_roads = tmp_root / "roads_after_complex.gpkg"
            tmp_nodes_fix = tmp_root / "nodes_after_one_to_many.gpkg"
            tmp_roads_fix = tmp_root / "roads_after_one_to_many.gpkg"
            tmp_report = tmp_root / "one_to_many_report.json"
            write_gpkg(tmp_nodes, node_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_nodes)
            write_gpkg(tmp_roads, road_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields_roads)
            run_t02_fix_node_error_2(
                node_error2_path=node_error2_path,
                nodes_path=tmp_nodes,
                roads_path=tmp_roads,
                intersection_path=intersection_path,
                nodes_fix_path=tmp_nodes_fix,
                roads_fix_path=tmp_roads_fix,
                report_path=tmp_report,
                node_error2_layer=node_error2_layer,
                nodes_layer=None,
                roads_layer=None,
                intersection_layer=intersection_layer,
                node_error2_crs=node_error2_crs_text,
                nodes_crs=f"EPSG:{target_epsg}",
                roads_crs=f"EPSG:{target_epsg}",
                intersection_crs=intersection_crs_text,
            )
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
            "one_to_many_executed": one_to_many_enabled,
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
