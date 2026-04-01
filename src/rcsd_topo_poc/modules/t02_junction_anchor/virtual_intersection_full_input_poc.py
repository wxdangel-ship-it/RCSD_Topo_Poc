from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import fiona
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    prefer_vector_input_path,
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage1_drivezone_gate import LoadedFeature, LoadedLayer
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    find_repo_root,
    normalize_id,
    _resolve_geopackage_crs_strict,
    _resolve_geopackage_layer_name,
    _resolve_shapefile_crs_strict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ALLOWED_KIND_2_VALUES,
    REASON_INVALID_CRS_OR_UNPROJECTABLE,
    REASON_MISSING_REQUIRED_FIELD,
    VirtualIntersectionPocError,
    _coerce_int,
    _load_layer_filtered,
    _parse_nodes,
    _resolve_geojson_crs_streaming,
    run_t02_virtual_intersection_poc,
)


DEFAULT_WORKERS = 1
FULL_INPUT_MODE_NAME = "full-input"
CASE_PACKAGE_MODE_NAME = "case-package"
FULL_INPUT_RUN_PREFIX = "t02_virtual_intersection_full_input_poc"


@dataclass(frozen=True)
class VirtualIntersectionFullInputArtifacts:
    success: bool
    out_root: Path
    preflight_path: Path
    summary_path: Path
    perf_summary_path: Path
    polygons_path: Path
    log_path: Path
    progress_path: Path
    rendered_maps_root: Path
    case_events_path: Path | None = None
    exception_summary_path: Path | None = None
    crash_report_path: Path | None = None


@dataclass(frozen=True)
class _SharedLayerHandle:
    label: str
    features: tuple[LoadedFeature, ...]
    geometry_feature_positions: tuple[int, ...]
    tree: STRtree | None
    group_members_by_mainnodeid: dict[str, tuple[int, ...]] | None = None
    orphan_members_by_nodeid: dict[str, tuple[int, ...]] | None = None


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _process_memory_stats() -> dict[str, int | None]:
    current_rss_bytes = None
    status_path = Path("/proc/self/status")
    if status_path.is_file():
        try:
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if not line.startswith("VmRSS:"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    current_rss_bytes = int(parts[1]) * 1024
                break
        except Exception:
            current_rss_bytes = None

    peak_rss_bytes = None
    try:
        peak_rss_kb = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if peak_rss_kb > 0:
            peak_rss_bytes = peak_rss_kb * 1024
    except Exception:
        peak_rss_bytes = None

    return {
        "process_current_rss_bytes": current_rss_bytes,
        "process_peak_rss_bytes": peak_rss_bytes,
    }


def _filter_properties(properties: dict[str, Any], allowed_fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field_name: properties.get(field_name)
        for field_name in allowed_fields
        if field_name in properties
    }


def _build_shared_layer_handle(
    *,
    label: str,
    path: str | Path,
    layer_name: str | None,
    crs_override: str | None,
    allow_null_geometry: bool,
    allowed_fields: tuple[str, ...],
) -> _SharedLayerHandle:
    layer = _load_layer_filtered(
        path,
        layer_name=layer_name,
        crs_override=crs_override,
        allow_null_geometry=allow_null_geometry,
    )
    features: list[LoadedFeature] = []
    geometry_feature_positions: list[int] = []
    geometries: list[BaseGeometry] = []
    group_members_by_mainnodeid: defaultdict[str, list[int]] | None = None
    orphan_members_by_nodeid: defaultdict[str, list[int]] | None = None
    if label == "nodes":
        group_members_by_mainnodeid = defaultdict(list)
        orphan_members_by_nodeid = defaultdict(list)

    for feature in layer.features:
        filtered_feature = LoadedFeature(
            feature_index=feature.feature_index,
            properties=_filter_properties(feature.properties, allowed_fields),
            geometry=feature.geometry,
        )
        feature_position = len(features)
        features.append(filtered_feature)
        if filtered_feature.geometry is not None and not filtered_feature.geometry.is_empty:
            geometry_feature_positions.append(feature_position)
            geometries.append(filtered_feature.geometry)
        if label == "nodes":
            node_id = normalize_id(filtered_feature.properties.get("id"))
            mainnodeid = normalize_id(filtered_feature.properties.get("mainnodeid"))
            if mainnodeid is not None:
                group_members_by_mainnodeid[mainnodeid].append(feature_position)
            elif node_id is not None:
                orphan_members_by_nodeid[node_id].append(feature_position)

    return _SharedLayerHandle(
        label=label,
        features=tuple(features),
        geometry_feature_positions=tuple(geometry_feature_positions),
        tree=STRtree(geometries) if geometries else None,
        group_members_by_mainnodeid=(
            {key: tuple(value) for key, value in group_members_by_mainnodeid.items()}
            if group_members_by_mainnodeid is not None
            else None
        ),
        orphan_members_by_nodeid=(
            {key: tuple(value) for key, value in orphan_members_by_nodeid.items()}
            if orphan_members_by_nodeid is not None
            else None
        ),
    )


def _loaded_layer_from_features(features: list[LoadedFeature]) -> LoadedLayer:
    return LoadedLayer(features=features, source_crs=TARGET_CRS, crs_source="shared_memory_target_crs")


def _shared_query_layer(
    handle: _SharedLayerHandle,
    *,
    query_geometry: BaseGeometry | None,
    property_predicate: Callable[[dict[str, Any]], bool] | None,
    allow_null_geometry: bool,
) -> LoadedLayer:
    if query_geometry is None:
        matched_features = [
            feature
            for feature in handle.features
            if property_predicate is None or property_predicate(feature.properties)
        ]
        return _loaded_layer_from_features(sorted(matched_features, key=lambda item: item.feature_index))

    feature_positions: list[int]
    if handle.tree is None:
        feature_positions = list(range(len(handle.features)))
    else:
        feature_positions = [
            handle.geometry_feature_positions[int(tree_index)]
            for tree_index in handle.tree.query(query_geometry)
        ]

    matched_features: list[LoadedFeature] = []
    seen_positions: set[int] = set()
    for feature_position in feature_positions:
        if feature_position in seen_positions:
            continue
        seen_positions.add(feature_position)
        feature = handle.features[feature_position]
        if property_predicate is not None and not property_predicate(feature.properties):
            continue
        if feature.geometry is None:
            if not allow_null_geometry:
                raise VirtualIntersectionPocError(
                    REASON_MISSING_REQUIRED_FIELD,
                    f"shared layer '{handle.label}' contains feature[{feature.feature_index}] without geometry.",
                )
            matched_features.append(feature)
            continue
        if not feature.geometry.intersects(query_geometry):
            continue
        matched_features.append(feature)
    matched_features.sort(key=lambda item: item.feature_index)
    return _loaded_layer_from_features(matched_features)


def _load_target_group_from_shared_nodes(handle: _SharedLayerHandle, mainnodeid: str) -> LoadedLayer:
    group_positions = list((handle.group_members_by_mainnodeid or {}).get(mainnodeid, ()))
    group_positions.extend((handle.orphan_members_by_nodeid or {}).get(mainnodeid, ()))
    features = [handle.features[position] for position in sorted(set(group_positions))]
    return _loaded_layer_from_features(features)


def _discover_candidate_mainnodeids_from_shared_nodes(handle: _SharedLayerHandle) -> list[str]:
    candidate_mainnodeids: list[str] = []
    for feature in handle.features:
        properties = feature.properties
        if not _is_auto_candidate(properties):
            continue
        normalized_mainnodeid = normalize_id(properties.get("mainnodeid")) or normalize_id(properties.get("id"))
        if normalized_mainnodeid is None:
            continue
        candidate_mainnodeids.append(normalized_mainnodeid)
    return sorted(set(candidate_mainnodeids), key=sort_patch_key)


def _build_shared_layer_loader(
    handles: dict[str, _SharedLayerHandle],
) -> Callable[..., LoadedLayer]:
    def _loader(
        path: str | Path,
        *,
        layer_name: str | None,
        crs_override: str | None,
        allow_null_geometry: bool,
        query_geometry: BaseGeometry | None = None,
        property_predicate: Callable[[dict[str, Any]], bool] | None = None,
        progress_label: str | None = None,
        progress_every: int = 5000,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> LoadedLayer:
        del layer_name, crs_override, progress_label, progress_every, progress_callback
        resolved_path = str(prefer_vector_input_path(Path(path)).resolve())
        handle = handles.get(resolved_path)
        if handle is None:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"Missing shared layer handle for '{path}'.",
            )
        return _shared_query_layer(
            handle,
            query_geometry=query_geometry,
            property_predicate=property_predicate,
            allow_null_geometry=allow_null_geometry,
        )

    return _loader


def _write_exception_summary(path: Path, rows: list[dict[str, Any]], *, crashed: dict[str, Any] | None = None) -> None:
    failed_rows = [row for row in rows if not row.get("success")]
    status_counter = Counter(str(row.get("status") or "unknown") for row in failed_rows)
    summary = {
        "updated_at": _now_text(),
        "failed_case_count": len(failed_rows),
        "status_counts": dict(sorted(status_counter.items())),
        "worker_exception_count": sum(1 for row in failed_rows if row.get("status") == "worker_exception"),
        "failed_cases": [
            {
                "case_id": row.get("case_id"),
                "status": row.get("status"),
                "detail": row.get("detail"),
                "total_wall_time_sec": row.get("total_wall_time_sec"),
            }
            for row in failed_rows
        ],
        "crashed": crashed,
        **_process_memory_stats(),
    }
    write_json(path, summary)


def _resolve_out_root(*, out_root: str | Path | None, run_id: str | None, cwd: Path | None = None) -> tuple[Path, str]:
    resolved_run_id = run_id or build_run_id(FULL_INPUT_RUN_PREFIX)
    if out_root is not None:
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise VirtualIntersectionPocError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / FULL_INPUT_RUN_PREFIX / resolved_run_id, resolved_run_id


def _vector_profile(
    *,
    path: str | Path,
    layer_name: str | None,
    crs_override: str | None,
) -> tuple[Path, str | None, CRS, str, int, list[float]]:
    resolved_path = prefer_vector_input_path(Path(path))
    if not resolved_path.is_file():
        raise VirtualIntersectionPocError(REASON_MISSING_REQUIRED_FIELD, f"Input layer does not exist: {resolved_path}")

    suffix = resolved_path.suffix.lower()
    if suffix in GEOPACKAGE_SUFFIXES:
        resolved_layer_name = _resolve_geopackage_layer_name(
            resolved_path,
            layer_name,
            error_cls=VirtualIntersectionPocError,
        )
        source_crs, crs_source = _resolve_geopackage_crs_strict(
            resolved_path,
            resolved_layer_name,
            crs_override,
            error_cls=VirtualIntersectionPocError,
        )
        with fiona.open(str(resolved_path), layer=resolved_layer_name) as src:
            feature_count = len(src)
            bounds = [round(float(value), 3) for value in src.bounds]
        return resolved_path, resolved_layer_name, source_crs, crs_source, feature_count, bounds

    if suffix == ".shp":
        source_crs, crs_source = _resolve_shapefile_crs_strict(
            resolved_path,
            crs_override,
            error_cls=VirtualIntersectionPocError,
        )
        with fiona.open(str(resolved_path)) as src:
            feature_count = len(src)
            bounds = [round(float(value), 3) for value in src.bounds]
        return resolved_path, None, source_crs, crs_source, feature_count, bounds

    if suffix in {".geojson", ".json"}:
        source_crs, crs_source = _resolve_geojson_crs_streaming(resolved_path, crs_override)
        with fiona.open(str(resolved_path)) as src:
            feature_count = len(src)
            bounds = [round(float(value), 3) for value in src.bounds]
        return resolved_path, None, source_crs, crs_source, feature_count, bounds

    raise VirtualIntersectionPocError(
        REASON_INVALID_CRS_OR_UNPROJECTABLE,
        f"Unsupported vector input format for '{resolved_path}'.",
    )


def _build_preflight(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    nodes_layer: str | None,
    roads_layer: str | None,
    drivezone_layer: str | None,
    rcsdroad_layer: str | None,
    rcsdnode_layer: str | None,
    nodes_crs: str | None,
    roads_crs: str | None,
    drivezone_crs: str | None,
    rcsdroad_crs: str | None,
    rcsdnode_crs: str | None,
) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {}
    resolved_layers: dict[str, str | None] = {}

    for label, path, layer_name, crs_override in (
        ("nodes", nodes_path, nodes_layer, nodes_crs),
        ("roads", roads_path, roads_layer, roads_crs),
        ("drivezone", drivezone_path, drivezone_layer, drivezone_crs),
        ("rcsdroad", rcsdroad_path, rcsdroad_layer, rcsdroad_crs),
        ("rcsdnode", rcsdnode_path, rcsdnode_layer, rcsdnode_crs),
    ):
        resolved_path, resolved_layer, source_crs, crs_source, feature_count, bounds = _vector_profile(
            path=path,
            layer_name=layer_name,
            crs_override=crs_override,
        )
        resolved_layers[label] = resolved_layer
        profiles[label] = {
            "path": str(resolved_path),
            "layer": resolved_layer,
            "feature_count": feature_count,
            "source_crs": source_crs.to_string(),
            "crs_source": crs_source,
            "target_crs": TARGET_CRS.to_string(),
            "bounds": bounds,
        }

    return {
        "updated_at": _now_text(),
        "resolved_layers": resolved_layers,
        "profiles": profiles,
    }


def _is_auto_candidate(properties: dict[str, Any]) -> bool:
    node_id = normalize_id(properties.get("id"))
    mainnodeid = normalize_id(properties.get("mainnodeid"))
    kind_2 = _coerce_int(properties.get("kind_2"))
    has_evd = normalize_id(properties.get("has_evd"))
    is_anchor = normalize_id(properties.get("is_anchor"))
    is_representative = (mainnodeid is not None and node_id == mainnodeid) or (mainnodeid is None and node_id is not None)
    return (
        is_representative
        and has_evd == "yes"
        and is_anchor == "no"
        and kind_2 in ALLOWED_KIND_2_VALUES
    )


def _discover_candidate_mainnodeids(
    *,
    nodes_path: str | Path,
    nodes_layer: str | None,
    nodes_crs: str | None,
) -> list[str]:
    nodes_layer_data = _load_layer_filtered(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=False,
        property_predicate=_is_auto_candidate,
        progress_label="full_input_candidate_scan",
    )
    nodes = _parse_nodes(nodes_layer_data, require_anchor_fields=True)
    candidate_mainnodeids = []
    for node in nodes:
        normalized_mainnodeid = node.mainnodeid or node.node_id
        if normalized_mainnodeid is None:
            continue
        candidate_mainnodeids.append(normalized_mainnodeid)
    return sorted(set(candidate_mainnodeids), key=sort_patch_key)


def _write_progress(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    current_stage: str,
    counts: dict[str, Any],
    message: str,
) -> None:
    write_json(
        out_path,
        {
            "run_id": run_id,
            "updated_at": _now_text(),
            "status": status,
            "current_stage": current_stage,
            "message": message,
            "counts": counts,
        },
    )


def _read_polygon_feature(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with fiona.open(str(path)) as src:
        for feature in src:
            return {
                "properties": dict(feature.get("properties") or {}),
                "geometry": shape(feature["geometry"]) if feature.get("geometry") is not None else None,
            }
    return None


def _read_ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    with fiona.open(str(path)) as src:
        return [
            str(feature["properties"].get("id"))
            for feature in src
            if feature["properties"].get("id") is not None
        ]


def _case_job_payload(
    *,
    mainnodeid: str,
    cases_root: Path,
    rendered_maps_root: Path,
    shared_args: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(shared_args)
    payload.update(
        {
            "mainnodeid": mainnodeid,
            "out_root": str(cases_root),
            "run_id": mainnodeid,
            "debug_render_root": str(rendered_maps_root),
        }
    )
    return payload


def _run_case_job(job: dict[str, Any]) -> dict[str, Any]:
    case_id = str(job["mainnodeid"])
    case_dir = Path(job["out_root"]) / case_id
    try:
        artifacts = run_t02_virtual_intersection_poc(**job)
        status_doc = artifacts.status_doc
        if status_doc is None:
            status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
        perf_doc = artifacts.perf_doc
        if perf_doc is None:
            perf_doc = json.loads(artifacts.perf_json_path.read_text(encoding="utf-8"))
        polygon_feature = artifacts.virtual_polygon_feature
        if polygon_feature is None:
            polygon_feature = _read_polygon_feature(artifacts.virtual_polygon_path)
        polygon_area_m2 = None
        polygon_bounds = None
        if polygon_feature is not None and polygon_feature["geometry"] is not None:
            polygon_area_m2 = round(float(polygon_feature["geometry"].area), 3)
            polygon_bounds = [round(float(value), 3) for value in polygon_feature["geometry"].bounds]
        associated_rcsdroad_ids = artifacts.associated_rcsdroad_ids
        if associated_rcsdroad_ids is None:
            associated_rcsdroad_ids = tuple(_read_ids(artifacts.associated_rcsdroad_path))
        associated_rcsdnode_ids = artifacts.associated_rcsdnode_ids
        if associated_rcsdnode_ids is None:
            associated_rcsdnode_ids = tuple(_read_ids(artifacts.associated_rcsdnode_path))
        return {
            "case_id": case_id,
            "success": bool(status_doc.get("success")),
            "status": status_doc.get("status"),
            "risks": list(status_doc.get("risks") or []),
            "detail": status_doc.get("detail"),
            "representative_node_id": status_doc.get("representative_node_id"),
            "kind_2": status_doc.get("kind_2"),
            "grade_2": status_doc.get("grade_2"),
            "counts": dict(status_doc.get("counts") or {}),
            "total_wall_time_sec": perf_doc.get("total_wall_time_sec"),
            "python_tracemalloc_current_bytes": perf_doc.get("python_tracemalloc_current_bytes"),
            "python_tracemalloc_peak_bytes": perf_doc.get("python_tracemalloc_peak_bytes"),
            "case_dir": str(case_dir),
            "rendered_map_png": str(artifacts.rendered_map_path) if artifacts.rendered_map_path and artifacts.rendered_map_path.is_file() else None,
            "virtual_polygon_path": str(artifacts.virtual_polygon_path),
            "polygon_feature": polygon_feature,
            "associated_rcsdroad_ids": list(associated_rcsdroad_ids),
            "associated_rcsdnode_ids": list(associated_rcsdnode_ids),
            "polygon_area_m2": polygon_area_m2,
            "polygon_bounds": polygon_bounds,
        }
    except Exception as exc:
        return {
            "case_id": case_id,
            "success": False,
            "status": "worker_exception",
            "risks": ["worker_exception"],
            "detail": f"{type(exc).__name__}: {exc}",
            "representative_node_id": None,
            "kind_2": None,
            "grade_2": None,
            "counts": {},
            "total_wall_time_sec": None,
            "python_tracemalloc_current_bytes": None,
            "python_tracemalloc_peak_bytes": None,
            "case_dir": str(case_dir),
            "rendered_map_png": None,
            "virtual_polygon_path": str(case_dir / "virtual_intersection_polygon.gpkg"),
            "polygon_feature": None,
            "associated_rcsdroad_ids": [],
            "associated_rcsdnode_ids": [],
            "polygon_area_m2": None,
            "polygon_bounds": None,
        }


def _collect_polygon_features(rows: list[dict[str, Any]], polygon_feature_cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("success"):
            continue
        polygon_feature = polygon_feature_cache.get(str(row["case_id"]))
        if polygon_feature is None or polygon_feature["geometry"] is None:
            continue
        properties = dict(polygon_feature["properties"])
        properties.update(
            {
                "mainnodeid": row["case_id"],
                "status": row["status"],
                "success": bool(row["success"]),
                "source_case_dir": row["case_dir"],
            }
        )
        features.append({"properties": properties, "geometry": polygon_feature["geometry"]})
    return features


SHARED_LAYER_PROPERTY_FIELDS: dict[str, tuple[str, ...]] = {
    "nodes": ("id", "mainnodeid", "has_evd", "is_anchor", "kind_2", "grade_2"),
    "roads": ("id", "snodeid", "enodeid", "direction"),
    "drivezone": ("name", "id"),
    "rcsdroad": ("id", "snodeid", "enodeid", "direction"),
    "rcsdnode": ("id", "mainnodeid"),
}


def run_t02_virtual_intersection_full_input_poc(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    mainnodeid: str | int | None = None,
    out_root: str | Path | None = None,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    drivezone_layer: str | None = None,
    rcsdroad_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    roads_crs: str | None = None,
    drivezone_crs: str | None = None,
    rcsdroad_crs: str | None = None,
    rcsdnode_crs: str | None = None,
    max_cases: int | None = None,
    workers: int = DEFAULT_WORKERS,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    debug: bool = False,
    debug_render_root: str | Path | None = None,
    review_mode: bool = False,
) -> VirtualIntersectionFullInputArtifacts:
    if max_cases is not None and max_cases <= 0:
        raise VirtualIntersectionPocError(REASON_MISSING_REQUIRED_FIELD, "max_cases must be greater than 0.")
    if workers <= 0:
        raise VirtualIntersectionPocError(REASON_MISSING_REQUIRED_FIELD, "workers must be greater than 0.")

    started_at = time.perf_counter()
    out_root_path, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    out_root_path.mkdir(parents=True, exist_ok=True)
    cases_root = out_root_path / "cases"
    rendered_maps_root = Path(debug_render_root) if debug_render_root is not None else out_root_path / "_rendered_maps"
    cases_root.mkdir(parents=True, exist_ok=True)
    rendered_maps_root.mkdir(parents=True, exist_ok=True)

    preflight_path = out_root_path / "preflight.json"
    summary_path = out_root_path / "summary.json"
    perf_summary_path = out_root_path / "perf_summary.json"
    polygons_path = out_root_path / "virtual_intersection_polygons.gpkg"
    log_path = out_root_path / "t02_virtual_intersection_full_input_poc.log"
    progress_path = out_root_path / "t02_virtual_intersection_full_input_poc_progress.json"
    case_events_path = out_root_path / "case_events.jsonl"
    exception_summary_path = out_root_path / "exception_summary.json"
    crash_report_path = out_root_path / "crash_report.json"

    counts: dict[str, Any] = {
        "selected_case_count": 0,
        "completed_case_count": 0,
        "success_case_count": 0,
        "failed_case_count": 0,
    }
    logger = build_logger(log_path, f"t02_virtual_intersection_full_input_poc_{resolved_run_id}")
    success = False
    preflight: dict[str, Any] = {}
    normalized_mainnodeid = normalize_id(mainnodeid)
    mode = "specified_mainnodeid" if normalized_mainnodeid is not None else "auto_discovery"
    discovered_case_ids: list[str] = []
    selected_case_ids: list[str] = []
    skipped_case_ids: list[str] = []
    rows: list[dict[str, Any]] = []
    polygon_feature_cache: dict[str, dict[str, Any]] = {}
    shared_memory_summary: dict[str, Any] = {
        "enabled": False,
        "node_group_lookup": False,
        "shared_local_layer_query": False,
        "layers": {},
    }

    def _record_case_result(row: dict[str, Any]) -> None:
        case_id = str(row["case_id"])
        polygon_feature = row.pop("polygon_feature", None)
        if row.get("success") and polygon_feature is not None:
            polygon_feature_cache[case_id] = polygon_feature
        rows.append(row)
        counts["completed_case_count"] = len(rows)
        counts["success_case_count"] = sum(1 for item in rows if item.get("success"))
        counts["failed_case_count"] = counts["completed_case_count"] - counts["success_case_count"]
        _append_jsonl(
            case_events_path,
            {
                "event": "case_completed",
                "at": _now_text(),
                "case_id": case_id,
                "success": bool(row.get("success")),
                "status": row.get("status"),
                "detail": row.get("detail"),
                "total_wall_time_sec": row.get("total_wall_time_sec"),
                "python_tracemalloc_peak_bytes": row.get("python_tracemalloc_peak_bytes"),
                "counts": counts,
                **_process_memory_stats(),
            },
        )
        _write_exception_summary(exception_summary_path, rows)
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="case_execution",
            counts=counts,
            message=f"Completed case {case_id}.",
        )

    try:
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="preflight",
            counts=counts,
            message="Building full-input preflight.",
        )
        preflight = _build_preflight(
            nodes_path=nodes_path,
            roads_path=roads_path,
            drivezone_path=drivezone_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            nodes_layer=nodes_layer,
            roads_layer=roads_layer,
            drivezone_layer=drivezone_layer,
            rcsdroad_layer=rcsdroad_layer,
            rcsdnode_layer=rcsdnode_layer,
            nodes_crs=nodes_crs,
            roads_crs=roads_crs,
            drivezone_crs=drivezone_crs,
            rcsdroad_crs=rcsdroad_crs,
            rcsdnode_crs=rcsdnode_crs,
        )
        write_json(preflight_path, preflight)
        announce(logger, f"[T02-FULL-POC] preflight written path={preflight_path}")

        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="shared_memory_preload",
            counts=counts,
            message="Preloading shared nodes index for full-input execution.",
        )
        preload_started_at = time.perf_counter()
        shared_nodes_handle = _build_shared_layer_handle(
            label="nodes",
            path=nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
            allowed_fields=SHARED_LAYER_PROPERTY_FIELDS["nodes"],
        )
        shared_memory_summary["enabled"] = True
        shared_memory_summary["node_group_lookup"] = True
        shared_memory_summary["layers"]["nodes"] = {
            "feature_count": len(shared_nodes_handle.features),
        }

        if normalized_mainnodeid is not None:
            selected_case_ids = [normalized_mainnodeid]
        else:
            _write_progress(
                out_path=progress_path,
                run_id=resolved_run_id,
                status="running",
                current_stage="candidate_discovery",
                counts=counts,
                message="Discovering candidate mainnodeids from shared nodes input.",
            )
            discovered_case_ids = _discover_candidate_mainnodeids_from_shared_nodes(shared_nodes_handle)
            selected_case_ids = discovered_case_ids[:max_cases] if max_cases is not None else discovered_case_ids

        skipped_case_ids = discovered_case_ids[len(selected_case_ids) :] if discovered_case_ids else []
        counts["discovered_case_count"] = len(discovered_case_ids)
        counts["selected_case_count"] = len(selected_case_ids)
        counts["skipped_case_count"] = len(skipped_case_ids)

        target_group_loader = lambda case_id: _load_target_group_from_shared_nodes(shared_nodes_handle, case_id)
        shared_layer_loader = None
        if len(selected_case_ids) > 1:
            shared_layer_handles: dict[str, _SharedLayerHandle] = {
                str(prefer_vector_input_path(Path(nodes_path)).resolve()): shared_nodes_handle,
            }
            for label, path, layer_name, crs_override in (
                ("roads", roads_path, roads_layer, roads_crs),
                ("drivezone", drivezone_path, drivezone_layer, drivezone_crs),
                ("rcsdroad", rcsdroad_path, rcsdroad_layer, rcsdroad_crs),
                ("rcsdnode", rcsdnode_path, rcsdnode_layer, rcsdnode_crs),
            ):
                shared_handle = _build_shared_layer_handle(
                    label=label,
                    path=path,
                    layer_name=layer_name,
                    crs_override=crs_override,
                    allow_null_geometry=False,
                    allowed_fields=SHARED_LAYER_PROPERTY_FIELDS[label],
                )
                shared_layer_handles[str(prefer_vector_input_path(Path(path)).resolve())] = shared_handle
                shared_memory_summary["layers"][label] = {
                    "feature_count": len(shared_handle.features),
                }
            shared_layer_loader = _build_shared_layer_loader(shared_layer_handles)
            shared_memory_summary["shared_local_layer_query"] = True

        shared_memory_summary["preload_wall_time_sec"] = round(time.perf_counter() - preload_started_at, 6)
        shared_memory_summary.update(_process_memory_stats())

        announce(
            logger,
            (
                "[T02-FULL-POC] candidate selection "
                f"mode={mode} selected_case_count={counts['selected_case_count']} "
                f"discovered_case_count={counts['discovered_case_count']}"
            ),
        )
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="case_execution",
            counts=counts,
            message=f"Executing {counts['selected_case_count']} virtual intersection cases.",
        )

        shared_job_args = {
            "nodes_path": str(nodes_path),
            "roads_path": str(roads_path),
            "drivezone_path": str(drivezone_path),
            "rcsdroad_path": str(rcsdroad_path),
            "rcsdnode_path": str(rcsdnode_path),
            "nodes_layer": nodes_layer,
            "roads_layer": roads_layer,
            "drivezone_layer": drivezone_layer,
            "rcsdroad_layer": rcsdroad_layer,
            "rcsdnode_layer": rcsdnode_layer,
            "nodes_crs": nodes_crs,
            "roads_crs": roads_crs,
            "drivezone_crs": drivezone_crs,
            "rcsdroad_crs": rcsdroad_crs,
            "rcsdnode_crs": rcsdnode_crs,
            "buffer_m": buffer_m,
            "patch_size_m": patch_size_m,
            "resolution_m": resolution_m,
            "debug": debug,
            "review_mode": review_mode,
            "trace_memory": False,
            "layer_loader": shared_layer_loader,
            "target_group_loader": target_group_loader,
        }

        if workers == 1 or len(selected_case_ids) <= 1:
            for case_id in selected_case_ids:
                _record_case_result(
                    _run_case_job(
                    _case_job_payload(
                        mainnodeid=case_id,
                        cases_root=cases_root,
                        rendered_maps_root=rendered_maps_root,
                        shared_args=shared_job_args,
                    )
                    )
                )
        else:
            jobs = [
                _case_job_payload(
                    mainnodeid=case_id,
                    cases_root=cases_root,
                    rendered_maps_root=rendered_maps_root,
                    shared_args=shared_job_args,
                )
                for case_id in selected_case_ids
            ]
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="t02_virtual_intersection") as executor:
                future_to_case_id = {executor.submit(_run_case_job, job): str(job["mainnodeid"]) for job in jobs}
                for future in as_completed(future_to_case_id):
                    _record_case_result(future.result())

        rows = sorted(rows, key=lambda item: sort_patch_key(str(item["case_id"])))
        polygon_features = _collect_polygon_features(rows, polygon_feature_cache)
        write_vector(polygons_path, polygon_features, crs_text=TARGET_CRS.to_string())

        summary = {
            "run_id": resolved_run_id,
            "mode": mode,
            "review_mode": review_mode,
            "workers": workers,
            "max_cases": max_cases,
            "run_root": str(out_root_path),
            "structure": {
                "cases_dir": str(cases_root),
                "rendered_maps_dir": str(rendered_maps_root),
                "virtual_intersection_polygons": str(polygons_path),
            },
            "preflight": preflight,
            "shared_memory": shared_memory_summary,
            "selected_case_ids": selected_case_ids,
            "discovered_case_ids": discovered_case_ids,
            "skipped_case_ids": skipped_case_ids,
            "case_count": len(rows),
            "success_count": sum(1 for item in rows if item.get("success")),
            "failed_count": sum(1 for item in rows if not item.get("success")),
            "rows": rows,
        }
        write_json(summary_path, summary)

        perf_values = [item["total_wall_time_sec"] for item in rows if isinstance(item.get("total_wall_time_sec"), (int, float))]
        tracemalloc_peaks = [
            item["python_tracemalloc_peak_bytes"]
            for item in rows
            if isinstance(item.get("python_tracemalloc_peak_bytes"), int)
        ]
        perf_summary = {
            "run_id": resolved_run_id,
            "run_root": str(out_root_path),
            "case_count": len(rows),
            "workers": workers,
            "average_total_wall_time_sec": round(sum(perf_values) / len(perf_values), 6) if perf_values else None,
            "min_total_wall_time_sec": round(min(perf_values), 6) if perf_values else None,
            "max_total_wall_time_sec": round(max(perf_values), 6) if perf_values else None,
            "max_case_python_tracemalloc_peak_bytes": max(tracemalloc_peaks) if tracemalloc_peaks else None,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            "shared_memory": shared_memory_summary,
            **_process_memory_stats(),
            "rows": [
                {
                    "case_id": item["case_id"],
                    "total_wall_time_sec": item.get("total_wall_time_sec"),
                    "python_tracemalloc_peak_bytes": item.get("python_tracemalloc_peak_bytes"),
                }
                for item in rows
            ],
        }
        write_json(perf_summary_path, perf_summary)
        _write_exception_summary(exception_summary_path, rows)

        success = all(bool(item.get("success")) for item in rows)
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="success" if success else "completed_with_failures",
            current_stage="completed",
            counts=counts,
            message=(
                f"Finished {len(rows)} cases; success={summary['success_count']} failed={summary['failed_count']}."
            ),
        )
        announce(
            logger,
            (
                "[T02-FULL-POC] completed "
                f"success_count={summary['success_count']} failed_count={summary['failed_count']} "
                f"out_root={out_root_path}"
            ),
        )
    except Exception as exc:
        success = False
        crash_report = {
            "run_id": resolved_run_id,
            "updated_at": _now_text(),
            "error_type": type(exc).__name__,
            "detail": str(exc),
            "counts": counts,
            "selected_case_ids": selected_case_ids,
            "completed_case_ids": [str(item.get("case_id")) for item in rows],
            **_process_memory_stats(),
        }
        write_json(crash_report_path, crash_report)
        _write_exception_summary(exception_summary_path, rows, crashed=crash_report)
        write_json(
            summary_path,
            {
                "run_id": resolved_run_id,
                "mode": mode,
                "review_mode": review_mode,
                "workers": workers,
                "max_cases": max_cases,
                "run_root": str(out_root_path),
                "structure": {
                    "cases_dir": str(cases_root),
                    "rendered_maps_dir": str(rendered_maps_root),
                    "virtual_intersection_polygons": str(polygons_path),
                },
                "preflight": preflight,
                "shared_memory": shared_memory_summary,
                "selected_case_ids": selected_case_ids,
                "discovered_case_ids": discovered_case_ids,
                "skipped_case_ids": skipped_case_ids,
                "case_count": len(rows),
                "success_count": sum(1 for item in rows if item.get("success")),
                "failed_count": sum(1 for item in rows if not item.get("success")),
                "rows": sorted(rows, key=lambda item: sort_patch_key(str(item["case_id"]))),
                "crashed": crash_report,
            },
        )
        write_json(
            perf_summary_path,
            {
                "run_id": resolved_run_id,
                "run_root": str(out_root_path),
                "case_count": len(rows),
                "workers": workers,
                "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
                "shared_memory": shared_memory_summary,
                "crashed": crash_report,
                **_process_memory_stats(),
                "rows": [
                    {
                        "case_id": item["case_id"],
                        "total_wall_time_sec": item.get("total_wall_time_sec"),
                        "python_tracemalloc_peak_bytes": item.get("python_tracemalloc_peak_bytes"),
                    }
                    for item in sorted(rows, key=lambda item: sort_patch_key(str(item["case_id"])))
                ],
            },
        )
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="failed",
            current_stage="crashed",
            counts=counts,
            message=f"{type(exc).__name__}: {exc}",
        )
        announce(logger, f"[T02-FULL-POC] crashed type={type(exc).__name__} detail={exc}")
    finally:
        close_logger(logger)

    return VirtualIntersectionFullInputArtifacts(
        success=success,
        out_root=out_root_path,
        preflight_path=preflight_path,
        summary_path=summary_path,
        perf_summary_path=perf_summary_path,
        polygons_path=polygons_path,
        log_path=log_path,
        progress_path=progress_path,
        rendered_maps_root=rendered_maps_root,
        case_events_path=case_events_path,
        exception_summary_path=exception_summary_path,
        crash_report_path=crash_report_path,
    )


def run_t02_virtual_intersection_full_input_poc_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_virtual_intersection_full_input_poc(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_root=args.out_root,
        run_id=args.run_id,
        nodes_layer=args.nodes_layer,
        roads_layer=args.roads_layer,
        drivezone_layer=args.drivezone_layer,
        rcsdroad_layer=args.rcsdroad_layer,
        rcsdnode_layer=args.rcsdnode_layer,
        nodes_crs=args.nodes_crs,
        roads_crs=args.roads_crs,
        drivezone_crs=args.drivezone_crs,
        rcsdroad_crs=args.rcsdroad_crs,
        rcsdnode_crs=args.rcsdnode_crs,
        max_cases=args.max_cases,
        workers=args.workers,
        buffer_m=args.buffer_m,
        patch_size_m=args.patch_size_m,
        resolution_m=args.resolution_m,
        debug=args.debug,
        debug_render_root=args.debug_render_root,
        review_mode=args.review_mode,
    )
    if artifacts.success:
        print(f"T02 virtual intersection full-input POC outputs written to: {artifacts.out_root}")
        return 0
    print(f"T02 virtual intersection full-input POC completed with failures; outputs written to: {artifacts.out_root}")
    return 1
