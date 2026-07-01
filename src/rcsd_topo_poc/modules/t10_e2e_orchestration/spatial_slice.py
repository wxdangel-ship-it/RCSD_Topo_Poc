from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorFeature,
    VectorReadResult,
    aggregate_bounds,
    get_case_insensitive_property,
    read_vector,
    write_gpkg,
)

from .contracts import EXTERNAL_INPUT_REQUIREMENTS


CASE_ID_EMPTY_VALUES = {"", "0", "0.0", "none", "null", "nan", "-1"}
PROCESS_CRS_TEXT = "EPSG:3857"
SEGMENT_BUFFER_M = 200.0


@dataclass(frozen=True)
class T10SpatialSliceResult:
    included_inputs: list[dict[str, Any]]
    summary: dict[str, Any]


def build_case_spatial_input_slices(
    *,
    manifest: Mapping[str, Any],
    package_dir: Path,
    semantic_junction_id: str,
    radius_m: float,
    target_epsg: int = 3857,
) -> T10SpatialSliceResult:
    if radius_m <= 0:
        raise ValueError("radius_m must be > 0.")
    case_id = str(semantic_junction_id).strip()
    external_inputs = _mapping(manifest.get("external_inputs"))
    nodes_path_text = external_inputs.get("prepared_swsd_nodes")
    if not isinstance(nodes_path_text, str) or not nodes_path_text.strip():
        raise ValueError("manifest.external_inputs.prepared_swsd_nodes is required for spatial slicing.")

    read_cache: dict[str, VectorReadResult] = {}
    nodes_result = _read_slot(
        slot="prepared_swsd_nodes",
        path_text=nodes_path_text,
        target_epsg=target_epsg,
        read_cache=read_cache,
    )
    case_scope = _case_scope_from_swsd_nodes(
        nodes_result=nodes_result,
        semantic_junction_id=case_id,
        radius_m=radius_m,
        target_epsg=target_epsg,
    )
    window = box(
        float(case_scope["center_x"]) - radius_m,
        float(case_scope["center_y"]) - radius_m,
        float(case_scope["center_x"]) + radius_m,
        float(case_scope["center_y"]) + radius_m,
    )

    swsd_road_endpoint_node_ids = _road_endpoint_ids_for_selected_features(
        slot="prepared_swsd_roads",
        source_path_text=external_inputs.get("prepared_swsd_roads"),
        window=window,
        target_epsg=target_epsg,
        read_cache=read_cache,
    )
    initial_rcsd_node_ids = _node_identity_ids_for_selected_features(
        slot="rcsdnode",
        source_path_text=external_inputs.get("rcsdnode"),
        window=window,
        target_epsg=target_epsg,
        read_cache=read_cache,
    )
    rcsd_road_endpoint_node_ids = _road_endpoint_ids_for_selected_features(
        slot="rcsdroad",
        source_path_text=external_inputs.get("rcsdroad"),
        window=window,
        target_epsg=target_epsg,
        read_cache=read_cache,
        forced_road_endpoint_ids=initial_rcsd_node_ids,
    )

    included_inputs: list[dict[str, Any]] = []
    slot_summaries: dict[str, dict[str, Any]] = {}
    selected_features_by_slot: dict[str, list[VectorFeature]] = {}
    for requirement in EXTERNAL_INPUT_REQUIREMENTS:
        slot = requirement.slot
        forced_node_ids = set()
        forced_road_endpoint_ids = set()
        preserve_geometry = False
        if slot == "prepared_swsd_nodes":
            forced_node_ids = set(case_scope["member_node_ids"]) | set(swsd_road_endpoint_node_ids)
        elif slot == "prepared_swsd_roads":
            preserve_geometry = True
        elif slot == "rcsdnode":
            forced_node_ids = set(rcsd_road_endpoint_node_ids)
        elif slot == "rcsdroad":
            forced_road_endpoint_ids = set(initial_rcsd_node_ids)
            preserve_geometry = True

        entry, slot_summary, selected_features = _slice_slot(
            slot=slot,
            source_path_text=external_inputs.get(slot),
            package_dir=package_dir,
            window=window,
            target_epsg=target_epsg,
            read_cache=read_cache,
            forced_node_ids=forced_node_ids,
            forced_road_endpoint_ids=forced_road_endpoint_ids,
            preserve_geometry=preserve_geometry,
        )
        included_inputs.append(entry)
        slot_summaries[slot] = slot_summary
        selected_features_by_slot[slot] = selected_features

    dependency_audit = _build_dependency_audit(
        swsd_road_endpoint_node_ids=swsd_road_endpoint_node_ids,
        selected_swsd_nodes=selected_features_by_slot.get("prepared_swsd_nodes", []),
        rcsd_road_endpoint_node_ids=rcsd_road_endpoint_node_ids,
        selected_rcsd_nodes=selected_features_by_slot.get("rcsdnode", []),
    )

    summary = {
        "selection_mode": "swsd_semantic_junction_radius_window",
        "selection_status": "spatial_slice_completed",
        "case_id": case_id,
        "case_id_semantics": "swsd_semantic_junction_id",
        "target_epsg": int(target_epsg),
        "selection_crs": f"EPSG:{target_epsg}",
        "center": {"x": case_scope["center_x"], "y": case_scope["center_y"]},
        "radius_m": float(radius_m),
        "bounds": {
            "minx": float(window.bounds[0]),
            "miny": float(window.bounds[1]),
            "maxx": float(window.bounds[2]),
            "maxy": float(window.bounds[3]),
        },
        "member_node_ids": case_scope["member_node_ids"],
        "slot_summaries": slot_summaries,
        "materialized_file_count": sum(1 for item in included_inputs if item.get("package_path")),
        "selected_feature_count_total": sum(int(item.get("selected_feature_count") or 0) for item in slot_summaries.values()),
        "dependency_audit": dependency_audit,
        "qa": {
            "crs_and_transform": f"All readable vector slots are normalized to EPSG:{target_epsg} before selection.",
            "topology_silent_fix": False,
            "topology_dependency_complete": dependency_audit["topology_dependency_complete"],
            "geometry_semantics": "Case window is derived from SWSD semantic junction member node geometries and radius_m; selected road geometries are preserved whole to keep endpoint semantics auditable.",
            "audit_traceability": "Each slot records source path, source count, selected count, dependency audit, bounds, output path and output checksum.",
            "performance_verifiability": "Each slot records source and selected feature counts plus materialized file sizes.",
        },
    }
    return T10SpatialSliceResult(included_inputs=included_inputs, summary=summary)


def build_segment_spatial_input_slices(
    *,
    manifest: Mapping[str, Any],
    package_dir: Path,
    swsd_segment_path: str | Path,
    swsd_segment_id: str,
    target_epsg: int = 3857,
    segment_buffer_m: float = SEGMENT_BUFFER_M,
) -> T10SpatialSliceResult:
    segment_id = str(swsd_segment_id).strip()
    if not segment_id:
        raise ValueError("swsd_segment_id must be non-empty.")
    if segment_buffer_m <= 0:
        raise ValueError("segment_buffer_m must be > 0.")

    external_inputs = _mapping(manifest.get("external_inputs"))
    read_cache: dict[str, VectorReadResult] = {}
    segment_result = _read_slot(
        slot="t01_segment",
        path_text=str(swsd_segment_path),
        target_epsg=target_epsg,
        read_cache=read_cache,
    )
    segment_scope = _case_scope_from_swsd_segment(
        segment_result=segment_result,
        swsd_segment_id=segment_id,
        target_epsg=target_epsg,
    )
    segment_geometry = segment_scope["_segment_geometry"]
    selection_geometry = segment_geometry.buffer(float(segment_buffer_m))
    if selection_geometry is None or selection_geometry.is_empty:
        raise ValueError(f"SWSD Segment buffer is empty: {swsd_segment_id}")

    swsd_road_endpoint_node_ids = _road_endpoint_ids_for_selected_features(
        slot="prepared_swsd_roads",
        source_path_text=external_inputs.get("prepared_swsd_roads"),
        window=selection_geometry,
        target_epsg=target_epsg,
        read_cache=read_cache,
    )
    initial_rcsd_node_ids = _node_identity_ids_for_selected_features(
        slot="rcsdnode",
        source_path_text=external_inputs.get("rcsdnode"),
        window=selection_geometry,
        target_epsg=target_epsg,
        read_cache=read_cache,
    )
    rcsd_road_endpoint_node_ids = _road_endpoint_ids_for_selected_features(
        slot="rcsdroad",
        source_path_text=external_inputs.get("rcsdroad"),
        window=selection_geometry,
        target_epsg=target_epsg,
        read_cache=read_cache,
        forced_road_endpoint_ids=initial_rcsd_node_ids,
    )

    included_inputs: list[dict[str, Any]] = []
    slot_summaries: dict[str, dict[str, Any]] = {}
    selected_features_by_slot: dict[str, list[VectorFeature]] = {}
    for requirement in EXTERNAL_INPUT_REQUIREMENTS:
        slot = requirement.slot
        forced_node_ids = set()
        forced_road_endpoint_ids = set()
        preserve_geometry = False
        if slot == "prepared_swsd_nodes":
            forced_node_ids = (
                set(segment_scope["segment_endpoint_node_ids"])
                | _segment_id_endpoint_ids(segment_id)
                | set(swsd_road_endpoint_node_ids)
            )
        elif slot == "prepared_swsd_roads":
            preserve_geometry = True
        elif slot == "rcsdnode":
            forced_node_ids = set(rcsd_road_endpoint_node_ids)
        elif slot == "rcsdroad":
            forced_road_endpoint_ids = set(initial_rcsd_node_ids)
            preserve_geometry = True

        entry, slot_summary, selected_features = _slice_slot(
            slot=slot,
            source_path_text=external_inputs.get(slot),
            package_dir=package_dir,
            window=selection_geometry,
            target_epsg=target_epsg,
            read_cache=read_cache,
            forced_node_ids=forced_node_ids,
            forced_road_endpoint_ids=forced_road_endpoint_ids,
            preserve_geometry=preserve_geometry,
        )
        included_inputs.append(entry)
        slot_summaries[slot] = slot_summary
        selected_features_by_slot[slot] = selected_features

    dependency_audit = _build_dependency_audit(
        swsd_road_endpoint_node_ids=swsd_road_endpoint_node_ids,
        selected_swsd_nodes=selected_features_by_slot.get("prepared_swsd_nodes", []),
        rcsd_road_endpoint_node_ids=rcsd_road_endpoint_node_ids,
        selected_rcsd_nodes=selected_features_by_slot.get("rcsdnode", []),
    )

    summary = {
        "selection_mode": "swsd_segment_geometry_buffer",
        "selection_status": "spatial_slice_completed",
        "case_id": "segment_" + _safe_scope_id(segment_id),
        "case_id_semantics": "swsd_segment_package_case_id",
        "scope_type": "swsd_segment",
        "swsd_segment_id": segment_id,
        "target_epsg": int(target_epsg),
        "selection_crs": f"EPSG:{target_epsg}",
        "center": {"x": segment_scope["center_x"], "y": segment_scope["center_y"]},
        "buffer_m": float(segment_buffer_m),
        "segment_bounds": segment_scope["segment_bounds"],
        "bounds": {
            "minx": float(selection_geometry.bounds[0]),
            "miny": float(selection_geometry.bounds[1]),
            "maxx": float(selection_geometry.bounds[2]),
            "maxy": float(selection_geometry.bounds[3]),
        },
        "segment_endpoint_node_ids": segment_scope["segment_endpoint_node_ids"],
        "segment_properties": segment_scope["segment_properties"],
        "slot_summaries": slot_summaries,
        "materialized_file_count": sum(1 for item in included_inputs if item.get("package_path")),
        "selected_feature_count_total": sum(int(item.get("selected_feature_count") or 0) for item in slot_summaries.values()),
        "dependency_audit": dependency_audit,
        "qa": {
            "crs_and_transform": f"All readable vector slots are normalized to EPSG:{target_epsg} before selection.",
            "topology_silent_fix": False,
            "topology_dependency_complete": dependency_audit["topology_dependency_complete"],
            "geometry_semantics": "Segment selection is derived from T01 Segment geometry buffered by 200m; matched T10/T06 rows remain evidence references and do not expand the spatial scope.",
            "audit_traceability": "Each slot records source path, source count, selected count, dependency audit, bounds, output path and output checksum.",
            "performance_verifiability": "Each slot records source and selected feature counts plus materialized file sizes.",
        },
    }
    return T10SpatialSliceResult(included_inputs=included_inputs, summary=summary)


def _slice_slot(
    *,
    slot: str,
    source_path_text: Any,
    package_dir: Path,
    window: BaseGeometry,
    target_epsg: int,
    read_cache: dict[str, VectorReadResult],
    forced_node_ids: set[str],
    forced_road_endpoint_ids: set[str],
    forced_feature_ids: set[str] | None = None,
    preserve_geometry: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], list[VectorFeature]]:
    source_path = str(source_path_text) if isinstance(source_path_text, str) and source_path_text.strip() else ""
    entry: dict[str, Any] = {
        "slot": slot,
        "source_path": source_path,
        "source_exists": False,
        "source_sha256": "",
        "package_path": "",
        "materialization_mode": "spatial_slice",
    }
    summary: dict[str, Any] = {
        "slot": slot,
        "source_path": source_path,
        "source_exists": False,
        "source_feature_count": 0,
        "selected_feature_count": 0,
        "output_feature_count": 0,
        "invalid_geometry_count": 0,
        "empty_after_clip_count": 0,
        "output_bounds": None,
        "output_path": "",
        "output_sha256": "",
        "output_size_bytes": 0,
    }
    if not source_path:
        return entry, summary, []
    source = Path(source_path).expanduser()
    entry["source_exists"] = source.is_file()
    summary["source_exists"] = source.is_file()
    if not source.is_file():
        return entry, summary, []

    stat = source.stat()
    entry["source_size_bytes"] = stat.st_size
    entry["source_mtime_ns"] = stat.st_mtime_ns
    summary["source_size_bytes"] = stat.st_size
    summary["source_mtime_ns"] = stat.st_mtime_ns

    read_result = _read_slot(slot=slot, path_text=source_path, target_epsg=target_epsg, read_cache=read_cache)
    selected_features, selection_audit = _select_and_clip_features(
        read_result.features,
        window=window,
        forced_node_ids=forced_node_ids,
        forced_road_endpoint_ids=forced_road_endpoint_ids,
        forced_feature_ids=forced_feature_ids or set(),
        preserve_geometry=preserve_geometry,
    )
    output_rel = Path("external_inputs") / slot / f"{slot}_slice.gpkg"
    output_path = package_dir / output_rel
    write_stats = write_gpkg(
        output_path,
        _feature_dicts(selected_features),
        crs_text=f"EPSG:{target_epsg}",
        layer_name=slot,
        empty_fields=read_result.field_names,
        geometry_type="Unknown",
    )
    output_sha256 = _sha256_file(output_path)
    bounds = aggregate_bounds(feature.geometry for feature in selected_features)

    entry.update(
        {
            "package_path": output_rel.as_posix(),
            "slice_sha256": output_sha256,
            "selected_feature_count": len(selected_features),
            "source_feature_count": len(read_result.features),
            "selection_crs": f"EPSG:{target_epsg}",
        }
    )
    summary.update(
        {
            "source_feature_count": len(read_result.features),
            "selected_feature_count": len(selected_features),
            "output_feature_count": int(write_stats.get("feature_count") or 0),
            "invalid_geometry_count": selection_audit["invalid_geometry_count"],
            "empty_after_clip_count": selection_audit["empty_after_clip_count"],
            "forced_feature_count": selection_audit["forced_feature_count"],
            "source_crs": read_result.source_crs.to_string(),
            "crs_source": read_result.crs_source,
            "output_crs": read_result.output_crs.to_string(),
            "output_bounds": bounds,
            "output_path": output_rel.as_posix(),
            "output_sha256": output_sha256,
            "output_size_bytes": int(write_stats.get("size_bytes") or 0),
        }
    )
    return entry, summary, selected_features


def _case_scope_from_swsd_nodes(
    *,
    nodes_result: VectorReadResult,
    semantic_junction_id: str,
    radius_m: float,
    target_epsg: int,
) -> dict[str, Any]:
    target = _normalize_id(semantic_junction_id)
    group = [
        feature
        for feature in nodes_result.features
        if _canonical_case_id(feature.properties) == target
    ]
    if not group:
        raise ValueError(f"SWSD semantic junction id not found in prepared_swsd_nodes: {semantic_junction_id}")
    centroids = [feature.geometry.centroid for feature in group if feature.geometry is not None and not feature.geometry.is_empty]
    if not centroids:
        raise ValueError(f"SWSD semantic junction id has no usable geometry: {semantic_junction_id}")
    return {
        "case_id": str(semantic_junction_id),
        "center_x": sum(point.x for point in centroids) / len(centroids),
        "center_y": sum(point.y for point in centroids) / len(centroids),
        "radius_m": float(radius_m),
        "target_epsg": int(target_epsg),
        "member_node_ids": sorted(
            {
                node_id
                for feature in group
                for node_id in _node_identity_ids(feature.properties)
            },
            key=_sort_key,
        ),
    }


def _case_scope_from_swsd_segment(
    *,
    segment_result: VectorReadResult,
    swsd_segment_id: str,
    target_epsg: int,
) -> dict[str, Any]:
    target = _normalize_id(swsd_segment_id)
    matches = [
        feature
        for feature in segment_result.features
        if target in _segment_identity_ids(feature.properties)
    ]
    if not matches:
        raise ValueError(f"SWSD Segment id not found in t01_segment: {swsd_segment_id}")
    feature = matches[0]
    geometry = feature.geometry
    if geometry is None or geometry.is_empty:
        raise ValueError(f"SWSD Segment has no usable geometry: {swsd_segment_id}")
    minx, miny, maxx, maxy = geometry.bounds
    centroid = geometry.centroid
    return {
        "case_id": "segment_" + _safe_scope_id(str(swsd_segment_id)),
        "swsd_segment_id": str(swsd_segment_id),
        "center_x": float(centroid.x),
        "center_y": float(centroid.y),
        "target_epsg": int(target_epsg),
        "segment_bounds": {
            "minx": float(minx),
            "miny": float(miny),
            "maxx": float(maxx),
            "maxy": float(maxy),
        },
        "segment_endpoint_node_ids": sorted(_road_endpoint_ids(feature.properties), key=_sort_key),
        "segment_properties": {str(key): _json_safe_value(value) for key, value in feature.properties.items()},
        "_segment_geometry": geometry,
    }


def _select_and_clip_features(
    features: list[VectorFeature],
    *,
    window: BaseGeometry,
    forced_node_ids: set[str],
    forced_road_endpoint_ids: set[str],
    forced_feature_ids: set[str],
    preserve_geometry: bool = False,
) -> tuple[list[VectorFeature], dict[str, int]]:
    selected: list[VectorFeature] = []
    invalid_count = 0
    empty_after_clip_count = 0
    forced_count = 0
    for feature in features:
        geometry = feature.geometry
        if geometry is None or geometry.is_empty:
            continue
        if not geometry.is_valid:
            invalid_count += 1
        forced = bool(forced_node_ids and _node_identity_ids(feature.properties) & forced_node_ids)
        forced = forced or bool(forced_road_endpoint_ids and _road_endpoint_ids(feature.properties) & forced_road_endpoint_ids)
        forced = forced or bool(forced_feature_ids and _feature_identity_ids(feature.properties) & forced_feature_ids)
        if not forced and not geometry.intersects(window):
            continue
        clipped = geometry if forced or preserve_geometry else geometry.intersection(window)
        if clipped is None or clipped.is_empty:
            empty_after_clip_count += 1
            continue
        if forced:
            forced_count += 1
        selected.append(VectorFeature(properties=dict(feature.properties), geometry=clipped))
    return selected, {
        "invalid_geometry_count": invalid_count,
        "empty_after_clip_count": empty_after_clip_count,
        "forced_feature_count": forced_count,
    }


def _read_slot(
    *,
    slot: str,
    path_text: str,
    target_epsg: int,
    read_cache: dict[str, VectorReadResult],
) -> VectorReadResult:
    cache_key = f"{slot}\0{Path(path_text).expanduser()}\0{target_epsg}"
    cached = read_cache.get(cache_key)
    if cached is not None:
        return cached
    result = read_vector(path_text, target_epsg=target_epsg)
    read_cache[cache_key] = result
    return result


def _feature_dicts(features: list[VectorFeature]) -> list[dict[str, Any]]:
    return [{"properties": dict(feature.properties), "geometry": feature.geometry} for feature in features]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _canonical_case_id(properties: Mapping[str, Any]) -> str | None:
    mainnodeid = _normalize_id(_field_value(properties, "mainnodeid"))
    if _is_valid_case_id(mainnodeid):
        return mainnodeid
    return _normalize_id(_field_value(properties, "id"))


def _node_identity_ids(properties: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for field in ("id", "mainnodeid"):
        normalized = _normalize_id(_field_value(properties, field))
        if _is_valid_case_id(normalized):
            values.add(normalized)
    values.update(_parse_id_list(_field_value(properties, "subnodeid")))
    return values


def _feature_identity_ids(properties: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for field in (
        "id",
        "road_id",
        "roadid",
        "RoadID",
        "link_id",
        "linkid",
        "LinkID",
        "road_no",
        "source_id",
    ):
        normalized = _normalize_id(_field_value(properties, field))
        if _is_valid_case_id(normalized):
            values.add(normalized)
    return values


def _road_endpoint_ids(properties: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for field in ("snodeid", "enodeid"):
        normalized = _normalize_id(_field_value(properties, field))
        if _is_valid_case_id(normalized):
            values.add(normalized)
    return values


def _segment_identity_ids(properties: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for field in ("id", "segment_id", "swsd_segment_id", "SegmentID", "segmentid"):
        normalized = _normalize_id(_field_value(properties, field))
        if _is_valid_case_id(normalized):
            values.add(normalized)
    endpoint_ids = _road_endpoint_ids(properties)
    if len(endpoint_ids) == 2:
        ordered = sorted(endpoint_ids, key=_sort_key)
        values.add(f"{ordered[0]}_{ordered[1]}")
        values.add(f"{ordered[1]}_{ordered[0]}")
    return values


def _road_endpoint_ids_for_selected_features(
    *,
    slot: str,
    source_path_text: Any,
    window: BaseGeometry,
    target_epsg: int,
    read_cache: dict[str, VectorReadResult],
    forced_road_endpoint_ids: set[str] | None = None,
) -> list[str]:
    selected = _selected_features_for_dependency(
        slot=slot,
        source_path_text=source_path_text,
        window=window,
        target_epsg=target_epsg,
        read_cache=read_cache,
        forced_road_endpoint_ids=forced_road_endpoint_ids or set(),
    )
    return _unique_sorted(node_id for feature in selected for node_id in _road_endpoint_ids(feature.properties))


def _node_identity_ids_for_selected_features(
    *,
    slot: str,
    source_path_text: Any,
    window: BaseGeometry,
    target_epsg: int,
    read_cache: dict[str, VectorReadResult],
) -> set[str]:
    selected = _selected_features_for_dependency(
        slot=slot,
        source_path_text=source_path_text,
        window=window,
        target_epsg=target_epsg,
        read_cache=read_cache,
        forced_road_endpoint_ids=set(),
    )
    return {node_id for feature in selected for node_id in _node_identity_ids(feature.properties)}


def _segment_id_endpoint_ids(segment_id: str) -> set[str]:
    parts = [_normalize_id(part) for part in str(segment_id).replace("-", "_").split("_")]
    return {part for part in parts if _is_valid_case_id(part)}


def _selected_features_for_dependency(
    *,
    slot: str,
    source_path_text: Any,
    window: BaseGeometry,
    target_epsg: int,
    read_cache: dict[str, VectorReadResult],
    forced_road_endpoint_ids: set[str],
) -> list[VectorFeature]:
    source_path = str(source_path_text) if isinstance(source_path_text, str) and source_path_text.strip() else ""
    if not source_path or not Path(source_path).expanduser().is_file():
        return []
    read_result = _read_slot(slot=slot, path_text=source_path, target_epsg=target_epsg, read_cache=read_cache)
    selected: list[VectorFeature] = []
    for feature in read_result.features:
        geometry = feature.geometry
        if geometry is None or geometry.is_empty:
            continue
        forced = bool(forced_road_endpoint_ids and _road_endpoint_ids(feature.properties) & forced_road_endpoint_ids)
        if forced or geometry.intersects(window):
            selected.append(feature)
    return selected


def _build_dependency_audit(
    *,
    swsd_road_endpoint_node_ids: list[str],
    selected_swsd_nodes: list[VectorFeature],
    rcsd_road_endpoint_node_ids: list[str],
    selected_rcsd_nodes: list[VectorFeature],
) -> dict[str, Any]:
    selected_swsd_node_ids = {node_id for feature in selected_swsd_nodes for node_id in _node_identity_ids(feature.properties)}
    selected_rcsd_node_ids = {node_id for feature in selected_rcsd_nodes for node_id in _node_identity_ids(feature.properties)}
    missing_swsd = [node_id for node_id in swsd_road_endpoint_node_ids if node_id not in selected_swsd_node_ids]
    missing_rcsd = [node_id for node_id in rcsd_road_endpoint_node_ids if node_id not in selected_rcsd_node_ids]
    return {
        "topology_dependency_complete": not missing_swsd and not missing_rcsd,
        "swsd_road_endpoint_node_count": len(swsd_road_endpoint_node_ids),
        "swsd_missing_road_endpoint_node_count": len(missing_swsd),
        "swsd_missing_road_endpoint_node_ids": missing_swsd,
        "rcsd_road_endpoint_node_count": len(rcsd_road_endpoint_node_ids),
        "rcsd_missing_road_endpoint_node_count": len(missing_rcsd),
        "rcsd_missing_road_endpoint_node_ids": missing_rcsd,
    }


def _unique_sorted(values: Any) -> list[str]:
    return sorted({value for value in values if _is_valid_case_id(value)}, key=_sort_key)


def _field_value(properties: Mapping[str, Any], field_name: str) -> Any:
    if isinstance(properties, dict):
        return get_case_insensitive_property(properties, (field_name,))
    for key, value in properties.items():
        if str(key).lower() == field_name.lower():
            return value
    return None


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _parse_id_list(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {item for item in (_normalize_id(part) for part in value) if _is_valid_case_id(item)}
    text = str(value).strip()
    if not text or text in {"[]", "{}"}:
        return set()
    cleaned = text.strip("[](){}")
    values: set[str] = set()
    for part in cleaned.replace(";", ",").split(","):
        normalized = _normalize_id(part.strip().strip("'\""))
        if _is_valid_case_id(normalized):
            values.add(normalized)
    return values


def _is_valid_case_id(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in CASE_ID_EMPTY_VALUES


def _sort_key(value: str) -> tuple[int, Any]:
    text = str(value)
    return (0, int(text)) if text.isdigit() else (1, text)


def _safe_scope_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value))


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
