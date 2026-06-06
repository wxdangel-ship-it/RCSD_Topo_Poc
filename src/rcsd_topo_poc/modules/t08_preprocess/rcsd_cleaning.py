from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep

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


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class T08RcsdCleaningArtifacts:
    nodes_output: Path
    roads_output: Path
    summary_output: Path


@dataclass(frozen=True)
class SemanticGroupDecision:
    semantic_group_id: str
    node_ids: tuple[str, ...]
    all_nodes_covered: bool


def run_t08_rcsd_cleaning(
    *,
    rcsdnode_gpkg: str | Path,
    rcsdroad_gpkg: str | Path,
    road_surface_gpkg: str | Path,
    nodes_output: str | Path,
    roads_output: str | Path,
    rcsdnode_layer: str | None = None,
    rcsdroad_layer: str | None = None,
    road_surface_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    rcsdnode_default_crs_text: str | None = None,
    rcsdroad_default_crs_text: str | None = None,
    road_surface_default_crs_text: str | None = None,
    node_predicate: str = "covers",
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08RcsdCleaningArtifacts:
    started = time.perf_counter()
    node_path = ensure_gpkg_path(rcsdnode_gpkg, label="--rcsdnode-gpkg")
    road_path = ensure_gpkg_path(rcsdroad_gpkg, label="--rcsdroad-gpkg")
    surface_path = ensure_gpkg_path(road_surface_gpkg, label="--road-surface-gpkg")
    output_nodes_path = ensure_tool_output_name(
        ensure_gpkg_path(nodes_output, label="--nodes-output"),
        tool_number=9,
        label="--nodes-output",
    )
    output_roads_path = ensure_tool_output_name(
        ensure_gpkg_path(roads_output, label="--roads-output"),
        tool_number=9,
        label="--roads-output",
    )
    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=9, label="--summary-output")
        if summary_output
        else output_nodes_path.with_name("rcsd_clean_summary_tool9.json")
    )
    if node_predicate not in {"covers", "contains"}:
        raise ValueError("--node-predicate must be one of: covers, contains")

    _emit_progress(progress_callback, f"[T08 Tool9] start rcsdnode={node_path} rcsdroad={road_path}")
    read_started = time.perf_counter()
    node_result = read_vector(
        node_path,
        layer_name=rcsdnode_layer,
        default_crs_text=rcsdnode_default_crs_text,
        target_epsg=target_epsg,
    )
    road_result = read_vector(
        road_path,
        layer_name=rcsdroad_layer,
        default_crs_text=rcsdroad_default_crs_text,
        target_epsg=target_epsg,
    )
    surface_result = read_vector(
        surface_path,
        layer_name=road_surface_layer,
        default_crs_text=road_surface_default_crs_text,
        target_epsg=target_epsg,
    )
    read_seconds = _elapsed_since(read_started)

    node_id_field = resolve_field_name(node_result.features, ["id"], "rcsdnode input")
    mainnodeid_field = _optional_field_name(node_result.features, ["mainnodeid", "mainNodeID"])
    road_id_field = resolve_field_name(road_result.features, ["id"], "rcsdroad input")
    snode_field = resolve_field_name(road_result.features, ["snodeid", "sNodeID"], "rcsdroad input")
    enode_field = resolve_field_name(road_result.features, ["enodeid", "eNodeID"], "rcsdroad input")

    surface_geometry = _build_road_surface_union(surface_result.features)
    prepared_surface = prep(surface_geometry)

    node_groups: dict[str, list[VectorFeature]] = defaultdict(list)
    duplicate_node_id_count = 0
    seen_node_ids: set[str] = set()
    for node in node_result.features:
        node_id = _required_normalized_id(node.properties.get(node_id_field), label="rcsdnode.id")
        if node_id in seen_node_ids:
            duplicate_node_id_count += 1
        seen_node_ids.add(node_id)
        group_id = _semantic_group_id(node.properties, node_id_field=node_id_field, mainnodeid_field=mainnodeid_field)
        node_groups[group_id].append(node)

    node_covered_by_id: dict[str, bool] = {}
    node_keep_ids: set[str] = set()
    group_decisions: list[SemanticGroupDecision] = []
    for group_id, group_nodes in node_groups.items():
        group_node_ids = tuple(
            _required_normalized_id(node.properties.get(node_id_field), label="rcsdnode.id") for node in group_nodes
        )
        covered_flags = [
            _node_is_covered(surface_geometry, prepared_surface, node.geometry, node_predicate=node_predicate)
            for node in group_nodes
        ]
        for node_id, covered in zip(group_node_ids, covered_flags):
            node_covered_by_id[node_id] = covered
        all_nodes_covered = all(covered_flags)
        group_decisions.append(
            SemanticGroupDecision(
                semantic_group_id=group_id,
                node_ids=group_node_ids,
                all_nodes_covered=all_nodes_covered,
            )
        )
        if all_nodes_covered:
            node_keep_ids.update(group_node_ids)

    kept_node_features = [
        node
        for node in node_result.features
        if _required_normalized_id(node.properties.get(node_id_field), label="rcsdnode.id") in node_keep_ids
    ]

    road_surface_intersect_count = 0
    road_endpoint_missing_count = 0
    road_endpoint_not_kept_count = 0
    road_surface_not_intersect_count = 0
    kept_road_features: list[VectorFeature] = []
    for index, road in enumerate(road_result.features, start=1):
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool9] processed {index} RCSDRoad feature(s)")
        if not prepared_surface.intersects(road.geometry):
            road_surface_not_intersect_count += 1
            continue
        road_surface_intersect_count += 1
        snode_id = _normalize_id(road.properties.get(snode_field))
        enode_id = _normalize_id(road.properties.get(enode_field))
        if snode_id is None or enode_id is None:
            road_endpoint_missing_count += 1
            continue
        if snode_id not in node_keep_ids or enode_id not in node_keep_ids:
            road_endpoint_not_kept_count += 1
            continue
        kept_road_features.append(road)

    write_started = time.perf_counter()
    node_write_stats = write_gpkg(
        output_nodes_path,
        _to_output_features(kept_node_features),
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=node_result.field_names,
        geometry_type="Point",
    )
    road_write_stats = write_gpkg(
        output_roads_path,
        _to_output_features(kept_road_features),
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=road_result.field_names,
        geometry_type="LineString",
    )
    write_seconds = _elapsed_since(write_started)
    elapsed_seconds = _elapsed_since(started)

    kept_group_count = sum(1 for decision in group_decisions if decision.all_nodes_covered)
    deleted_group_count = len(group_decisions) - kept_group_count
    summary = {
        "tool": "T08 Tool9",
        "stage": "rcsd_cleaning",
        "target_epsg": target_epsg,
        "input_paths": {
            "rcsdnode_gpkg": node_path,
            "rcsdroad_gpkg": road_path,
            "road_surface_gpkg": surface_path,
        },
        "output_paths": {
            "nodes_output": output_nodes_path,
            "roads_output": output_roads_path,
            "summary_output": summary_path,
        },
        "input_crs": {
            "rcsdnode": node_result.source_crs.to_string(),
            "rcsdnode_crs_source": node_result.crs_source,
            "rcsdroad": road_result.source_crs.to_string(),
            "rcsdroad_crs_source": road_result.crs_source,
            "road_surface": surface_result.source_crs.to_string(),
            "road_surface_crs_source": surface_result.crs_source,
        },
        "params": {
            "rcsdnode_layer": rcsdnode_layer,
            "rcsdroad_layer": rcsdroad_layer,
            "road_surface_layer": road_surface_layer,
            "rcsdnode_default_crs": rcsdnode_default_crs_text,
            "rcsdroad_default_crs": rcsdroad_default_crs_text,
            "road_surface_default_crs": road_surface_default_crs_text,
            "node_predicate": node_predicate,
            "progress_interval": progress_interval,
        },
        "field_audit": {
            "rcsdnode_layer": node_result.layer_name,
            "rcsdroad_layer": road_result.layer_name,
            "road_surface_layer": surface_result.layer_name,
            "node_id_field": node_id_field,
            "mainnodeid_field": mainnodeid_field,
            "road_id_field": road_id_field,
            "snode_field": snode_field,
            "enode_field": enode_field,
        },
        "counts": {
            "rcsdnode_input_count": len(node_result.features),
            "rcsdnode_individual_covered_count": sum(1 for covered in node_covered_by_id.values() if covered),
            "rcsdnode_output_count": len(kept_node_features),
            "rcsdnode_deleted_count": len(node_result.features) - len(kept_node_features),
            "semantic_group_count": len(group_decisions),
            "semantic_group_kept_count": kept_group_count,
            "semantic_group_deleted_count": deleted_group_count,
            "duplicate_node_id_count": duplicate_node_id_count,
            "road_surface_feature_count": len(surface_result.features),
            "rcsdroad_input_count": len(road_result.features),
            "rcsdroad_surface_intersect_count": road_surface_intersect_count,
            "rcsdroad_surface_not_intersect_count": road_surface_not_intersect_count,
            "rcsdroad_endpoint_missing_count": road_endpoint_missing_count,
            "rcsdroad_endpoint_not_kept_count": road_endpoint_not_kept_count,
            "rcsdroad_output_count": len(kept_road_features),
            "rcsdroad_deleted_count": len(road_result.features) - len(kept_road_features),
        },
        "output_bounds": {
            "nodes": aggregate_bounds(node.geometry for node in kept_node_features),
            "roads": aggregate_bounds(road.geometry for road in kept_road_features),
        },
        "write_stats": {
            "nodes": node_write_stats,
            "roads": road_write_stats,
        },
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "read_inputs_seconds": round(read_seconds, 6),
            "write_outputs_seconds": round(write_seconds, 6),
            "nodes_per_second": _items_per_second(len(node_result.features), elapsed_seconds),
            "roads_per_second": _items_per_second(len(road_result.features), elapsed_seconds),
        },
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        f"[T08 Tool9] finished nodes={len(kept_node_features)} roads={len(kept_road_features)} "
        f"elapsed={elapsed_seconds:.2f}s summary={summary_path}",
    )
    return T08RcsdCleaningArtifacts(
        nodes_output=output_nodes_path,
        roads_output=output_roads_path,
        summary_output=summary_path,
    )


def _build_road_surface_union(features: list[VectorFeature]) -> BaseGeometry:
    geometries = [feature.geometry for feature in features if feature.geometry is not None and not feature.geometry.is_empty]
    if not geometries:
        raise ValueError("Road surface input contains no non-empty geometry")
    surface_geometry = unary_union(geometries)
    if surface_geometry.is_empty:
        raise ValueError("Road surface union is empty")
    return surface_geometry


def _node_is_covered(
    surface_geometry: BaseGeometry,
    prepared_surface: Any,
    geometry: BaseGeometry,
    *,
    node_predicate: str,
) -> bool:
    if node_predicate == "contains":
        return bool(prepared_surface.contains(geometry))
    if hasattr(prepared_surface, "covers"):
        return bool(prepared_surface.covers(geometry))
    return bool(surface_geometry.covers(geometry))


def _semantic_group_id(
    properties: dict[str, Any],
    *,
    node_id_field: str,
    mainnodeid_field: str | None,
) -> str:
    node_id = _required_normalized_id(properties.get(node_id_field), label="rcsdnode.id")
    if mainnodeid_field is None:
        return node_id
    mainnode_id = _normalize_id(properties.get(mainnodeid_field))
    if mainnode_id is None or mainnode_id == "0":
        return node_id
    return mainnode_id


def _to_output_features(features: list[VectorFeature]) -> list[dict[str, Any]]:
    return [{"properties": dict(feature.properties), "geometry": feature.geometry} for feature in features]


def _optional_field_name(features: list[VectorFeature], candidates: list[str]) -> str | None:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    return None


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


def _required_normalized_id(value: Any, *, label: str) -> str:
    normalized = _normalize_id(value)
    if normalized is None:
        raise ValueError(f"Required id value is empty: {label}")
    return normalized


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _should_emit_progress(count: int, progress_interval: int) -> bool:
    return progress_interval > 0 and count > 0 and count % progress_interval == 0


def _elapsed_since(started: float) -> float:
    return max(0.0, time.perf_counter() - started)


def _items_per_second(count: int, seconds: float) -> float | None:
    if seconds <= 0:
        return None
    return round(float(count) / seconds, 6)


__all__ = [
    "T08RcsdCleaningArtifacts",
    "run_t08_rcsd_cleaning",
]
