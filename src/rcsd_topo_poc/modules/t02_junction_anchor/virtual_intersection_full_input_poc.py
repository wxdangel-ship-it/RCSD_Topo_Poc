from __future__ import annotations

import argparse
import json
import struct
import time
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import resource
except ImportError:  # pragma: no cover - Windows Python does not provide resource.
    resource = None

import fiona
import numpy as np
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
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT,
    derive_stage3_review_metadata,
    stage3_official_review_decision_dict,
    stage3_review_metadata_dict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_audit_assembler import (
    STAGE3_EXECUTION_CONTRACT_VERSION,
    build_stage3_failure_audit_envelope,
    stage3_audit_record_dict,
    stage3_step7_acceptance_result_dict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_context_builder import (
    build_minimal_stage3_context,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ALLOWED_KIND_2_VALUES,
    REASON_INVALID_CRS_OR_UNPROJECTABLE,
    REASON_MISSING_REQUIRED_FIELD,
    VirtualIntersectionPocError,
    _coerce_int,
    _draw_failure_banner,
    _failure_overlay_palette,
    _load_layer_filtered,
    _parse_nodes,
    _resolve_geojson_crs_streaming,
    _write_png_rgba,
    run_t02_virtual_intersection_poc,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step7_acceptance import (
    build_stage3_failure_step7_result,
)


DEFAULT_WORKERS = 1
FULL_INPUT_MODE_NAME = "full-input"
CASE_PACKAGE_MODE_NAME = "case-package"
FULL_INPUT_RUN_PREFIX = "t02_virtual_intersection_full_input_poc"
CASE_EXECUTION_PROGRESS_FLUSH_EVERY = 8
CASE_EXECUTION_PROGRESS_FLUSH_INTERVAL_SEC = 2.0


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
    review_index_path: Path | None = None
    review_summary_path: Path | None = None
    package_manifest_path: Path | None = None
    package_consistency_audit_path: Path | None = None
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


def _read_png_rgba(path: Path) -> np.ndarray:
    png_bytes = path.read_bytes()
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Unsupported PNG header: {path}")
    offset = 8
    width = None
    height = None
    idat_parts: list[bytes] = []
    while offset < len(png_bytes):
        chunk_length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        payload = png_bytes[offset + 8 : offset + 8 + chunk_length]
        offset += 12 + chunk_length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif chunk_type == b"IDAT":
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None:
        raise ValueError(f"Missing IHDR chunk: {path}")
    raw_rows = zlib.decompress(b"".join(idat_parts))
    row_size = 1 + width * 4
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for row_index in range(height):
        row = raw_rows[row_index * row_size : (row_index + 1) * row_size]
        if not row or row[0] != 0:
            raise ValueError(f"Unsupported PNG filter row in {path}")
        image[row_index] = np.frombuffer(row[1:], dtype=np.uint8).reshape((width, 4))
    return image


def _ensure_failure_styled_render(
    path: str | Path | None,
    *,
    acceptance_class: str | None = None,
) -> None:
    if path is None:
        return
    render_path = Path(path)
    if not render_path.is_file():
        return
    image = _read_png_rgba(render_path)
    base = image[..., :3].astype(np.float32)
    palette = _failure_overlay_palette(
        acceptance_class or "rejected_status:full_input_overlay",
        failure_class=acceptance_class,
    )
    failure_color = np.array(palette["tint"], dtype=np.float32)
    image[..., :3] = np.clip(base * 0.84 + failure_color * 0.16, 0.0, 255.0).astype(np.uint8)
    image[..., 3] = 255
    border_px = max(8, min(image.shape[0], image.shape[1]) // 40)
    border_color = np.array(palette["border"], dtype=np.uint8)
    image[:border_px, :, :3] = border_color
    image[-border_px:, :, :3] = border_color
    image[:, :border_px, :3] = border_color
    image[:, -border_px:, :3] = border_color
    _draw_failure_banner(
        image,
        banner_height_px=max(12, min(24, image.shape[0] // 6)),
        banner_color=palette["banner"],
        label=palette["label"],
        label_text_color=palette["label_text"],
        label_shadow_color=palette["label_shadow"],
    )
    _write_png_rgba(render_path, image)


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
    if resource is not None:
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
    failed_rows = [row for row in rows if _row_is_failure_outcome(row)]
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


def _build_failure_row_from_audit_envelope(
    *,
    case_id: str,
    case_dir: Path,
    failure_audit_envelope: Any,
    detail: str,
    rendered_map_png: str | None = None,
) -> dict[str, Any]:
    step7_result = failure_audit_envelope.audit_record.step7
    review_metadata = failure_audit_envelope.review_metadata
    official_review_decision = failure_audit_envelope.official_review_decision
    context = failure_audit_envelope.audit_record.context
    resolved_kind = context.representative_kind
    kind_source = "nodes.kind"
    if resolved_kind in {None, ""} and context.representative_kind_2 not in {None, ""}:
        resolved_kind = context.representative_kind_2
        kind_source = "nodes.kind_2"
    if resolved_kind in {None, ""}:
        kind_source = None
    return {
        "case_id": case_id,
        "success": step7_result.success,
        "flow_success": False,
        "business_outcome_class": step7_result.business_outcome_class,
        "acceptance_class": step7_result.acceptance_class,
        "acceptance_reason": step7_result.acceptance_reason,
        "status": step7_result.status,
        "risks": [step7_result.acceptance_reason] if step7_result.acceptance_reason else [],
        "detail": detail,
        "representative_node_id": context.representative_node_id,
        "representative_kind": context.representative_kind,
        "representative_has_evd": None,
        "representative_is_anchor": None,
        "resolved_kind": resolved_kind,
        "kind_source": kind_source,
        "kind_2": context.representative_kind_2,
        "grade_2": context.representative_grade_2,
        **stage3_review_metadata_dict(review_metadata),
        **stage3_official_review_decision_dict(official_review_decision),
        "stage3_execution_contract_version": STAGE3_EXECUTION_CONTRACT_VERSION,
        "step7_result": stage3_step7_acceptance_result_dict(step7_result),
        "stage3_audit_record": stage3_audit_record_dict(
            failure_audit_envelope.audit_record
        ),
        "counts": {},
        "total_wall_time_sec": None,
        "python_tracemalloc_current_bytes": None,
        "python_tracemalloc_peak_bytes": None,
        "case_dir": str(case_dir),
        "status_path": str(case_dir / "t02_virtual_intersection_poc_status.json"),
        "audit_path": str(case_dir / "t02_virtual_intersection_poc_audit.json"),
        "polygon_path": str(case_dir / "virtual_intersection_polygon.gpkg"),
        "rendered_map_png": rendered_map_png,
        "virtual_polygon_path": str(case_dir / "virtual_intersection_polygon.gpkg"),
        "polygon_feature": None,
        "associated_rcsdroad_ids": [],
        "associated_rcsdnode_ids": [],
        "polygon_area_m2": None,
        "polygon_bounds": None,
    }


def _materialize_failure_case_artifacts(
    *,
    case_dir: Path,
    failure_audit_envelope: Any,
    detail: str,
    rendered_map_path: Path | None,
) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    status_path = case_dir / "t02_virtual_intersection_poc_status.json"
    audit_path = case_dir / "t02_virtual_intersection_poc_audit.json"
    polygon_path = case_dir / "virtual_intersection_polygon.gpkg"

    step7_result = failure_audit_envelope.audit_record.step7
    review_metadata = failure_audit_envelope.review_metadata
    official_review_decision = failure_audit_envelope.official_review_decision
    context = failure_audit_envelope.audit_record.context
    resolved_kind = context.representative_kind
    kind_source = "nodes.kind"
    if resolved_kind in {None, ""} and context.representative_kind_2 not in {None, ""}:
        resolved_kind = context.representative_kind_2
        kind_source = "nodes.kind_2"
    if resolved_kind in {None, ""}:
        kind_source = None

    if not polygon_path.is_file():
        write_vector(polygon_path, [], crs_text=TARGET_CRS.to_string())

    if not audit_path.is_file():
        write_json(audit_path, stage3_audit_record_dict(failure_audit_envelope.audit_record))

    if not status_path.is_file():
        write_json(
            status_path,
            {
                "run_id": context.normalized_mainnodeid,
                "success": False,
                "flow_success": False,
                "business_outcome_class": step7_result.business_outcome_class,
                "acceptance_class": step7_result.acceptance_class,
                "acceptance_reason": step7_result.acceptance_reason,
                "status": step7_result.status,
                "risks": [step7_result.acceptance_reason]
                if step7_result.acceptance_reason
                else [],
                "detail": detail,
                "mainnodeid": context.normalized_mainnodeid,
                "representative_node_id": context.representative_node_id,
                "representative_kind": context.representative_kind,
                "representative_has_evd": None,
                "representative_is_anchor": None,
                "resolved_kind": resolved_kind,
                "kind_source": kind_source,
                "kind_2": context.representative_kind_2,
                "grade_2": context.representative_grade_2,
                **stage3_review_metadata_dict(review_metadata),
                **stage3_official_review_decision_dict(official_review_decision),
                "stage3_execution_contract_version": STAGE3_EXECUTION_CONTRACT_VERSION,
                "step7_result": stage3_step7_acceptance_result_dict(step7_result),
                "stage3_audit_record": stage3_audit_record_dict(
                    failure_audit_envelope.audit_record
                ),
                "counts": {},
                "output_files": {
                    "virtual_intersection_polygon": str(polygon_path),
                    "audit_json": str(audit_path),
                    "virtual_intersection_polygon_gpkg": str(polygon_path),
                    "rendered_map_png": (
                        str(rendered_map_path)
                        if rendered_map_path is not None and rendered_map_path.is_file()
                        else None
                    ),
                },
            },
        )


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
    rendered_map_path = Path(str(job["debug_render_root"])) / f"{case_id}.png"
    try:
        artifacts = run_t02_virtual_intersection_poc(**job)
        status_doc = artifacts.status_doc
        if status_doc is None:
            status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
        canonical_step7_fields = _canonical_row_step7_fields(status_doc)
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
            "success": bool(canonical_step7_fields["success"]),
            "business_outcome_class": canonical_step7_fields["business_outcome_class"],
            "flow_success": bool(status_doc.get("flow_success", status_doc.get("success"))),
            "acceptance_class": canonical_step7_fields["acceptance_class"],
            "acceptance_reason": canonical_step7_fields["acceptance_reason"],
            "status": canonical_step7_fields["status"],
            "risks": list(status_doc.get("risks") or []),
            "detail": status_doc.get("detail"),
            "representative_node_id": status_doc.get("representative_node_id"),
            "representative_kind": status_doc.get("representative_kind"),
            "representative_has_evd": status_doc.get("representative_has_evd"),
            "representative_is_anchor": status_doc.get("representative_is_anchor"),
            "resolved_kind": status_doc.get("resolved_kind"),
            "kind_source": status_doc.get("kind_source"),
            "kind_2": status_doc.get("kind_2"),
            "grade_2": status_doc.get("grade_2"),
            "root_cause_layer": status_doc.get("root_cause_layer"),
            "root_cause_type": status_doc.get("root_cause_type"),
            "visual_review_class": status_doc.get("visual_review_class"),
            "official_review_eligible": status_doc.get("official_review_eligible"),
            "blocking_reason": status_doc.get("blocking_reason"),
            "failure_bucket": status_doc.get("failure_bucket"),
            "step7_result": status_doc.get("step7_result"),
            "counts": dict(status_doc.get("counts") or {}),
            "total_wall_time_sec": perf_doc.get("total_wall_time_sec"),
            "python_tracemalloc_current_bytes": perf_doc.get("python_tracemalloc_current_bytes"),
            "python_tracemalloc_peak_bytes": perf_doc.get("python_tracemalloc_peak_bytes"),
            "case_dir": str(case_dir),
            "status_path": str(artifacts.status_path),
            "audit_path": str(artifacts.audit_json_path),
            "polygon_path": str(artifacts.virtual_polygon_path),
            "rendered_map_png": str(artifacts.rendered_map_path) if artifacts.rendered_map_path and artifacts.rendered_map_path.is_file() else None,
            "virtual_polygon_path": str(artifacts.virtual_polygon_path),
            "polygon_feature": polygon_feature,
            "associated_rcsdroad_ids": list(associated_rcsdroad_ids),
            "associated_rcsdnode_ids": list(associated_rcsdnode_ids),
            "polygon_area_m2": polygon_area_m2,
            "polygon_bounds": polygon_bounds,
        }
    except Exception as exc:
        failure_step7_result = build_stage3_failure_step7_result(
            mainnodeid=case_id,
            template_class="",
            acceptance_reason="worker_exception",
            status="worker_exception",
        )
        failure_audit_envelope = build_stage3_failure_audit_envelope(
            mainnodeid=case_id,
            acceptance_reason="worker_exception",
            template_class="",
            context=build_minimal_stage3_context(
                representative_node_id=case_id,
                normalized_mainnodeid=case_id,
                template_class="",
            ),
            status="worker_exception",
            step7_result=failure_step7_result,
        )
        _materialize_failure_case_artifacts(
            case_dir=case_dir,
            failure_audit_envelope=failure_audit_envelope,
            detail=f"{type(exc).__name__}: {exc}",
            rendered_map_path=rendered_map_path,
        )
        return _build_failure_row_from_audit_envelope(
            case_id=case_id,
            case_dir=case_dir,
            failure_audit_envelope=failure_audit_envelope,
            detail=f"{type(exc).__name__}: {exc}",
            rendered_map_png=str(rendered_map_path) if rendered_map_path.is_file() else None,
        )


def _collect_polygon_features(rows: list[dict[str, Any]], polygon_feature_cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for row in rows:
        if _row_is_failure_outcome(row):
            continue
        polygon_feature = polygon_feature_cache.get(str(row["case_id"]))
        if polygon_feature is None or polygon_feature["geometry"] is None:
            continue
        properties = dict(polygon_feature["properties"])
        properties.update(
            {
                "mainnodeid": properties.get("mainnodeid") or row["case_id"],
                "kind": properties.get("kind", row.get("resolved_kind")),
                "kind_source": properties.get("kind_source") or row.get("kind_source"),
                "status": row["status"],
                "success": bool(row["success"]),
                "business_outcome_class": row.get("business_outcome_class"),
                "acceptance_class": row.get("acceptance_class"),
                "root_cause_layer": row.get("root_cause_layer"),
                "root_cause_type": row.get("root_cause_type"),
                "visual_review_class": row.get("visual_review_class"),
                "official_review_eligible": row.get("official_review_eligible"),
                "failure_bucket": row.get("failure_bucket"),
                "source_case_dir": row["case_dir"],
            }
        )
        features.append({"properties": properties, "geometry": polygon_feature["geometry"]})
    return features


def _require_row_official_review_fields(row: dict[str, Any]) -> dict[str, Any]:
    missing_fields = [
        field_name
        for field_name in (
            "official_review_eligible",
            "blocking_reason",
            "failure_bucket",
            "root_cause_layer",
            "root_cause_type",
            "visual_review_class",
        )
        if field_name not in row
    ]
    if missing_fields:
        raise ValueError(
            "review_index rows must carry explicit official review and review-triad fields; "
            f"missing {missing_fields} for case_id={row.get('case_id')!r}"
        )
    return {
        "official_review_eligible": bool(row.get("official_review_eligible")),
        "blocking_reason": row.get("blocking_reason"),
        "failure_bucket": row.get("failure_bucket"),
        "root_cause_layer": row.get("root_cause_layer"),
        "root_cause_type": row.get("root_cause_type"),
        "visual_review_class": row.get("visual_review_class"),
    }


def _canonical_row_step7_fields(row: dict[str, Any]) -> dict[str, Any]:
    step7_result = row.get("step7_result")
    if not isinstance(step7_result, dict):
        step7_result = {}
    return {
        "success": step7_result.get("success", row.get("success")),
        "business_outcome_class": step7_result.get(
            "business_outcome_class", row.get("business_outcome_class")
        ),
        "acceptance_class": step7_result.get("acceptance_class", row.get("acceptance_class")),
        "acceptance_reason": step7_result.get("acceptance_reason", row.get("acceptance_reason")),
        "status": step7_result.get("status", row.get("status")),
    }


def _row_business_outcome_class(row: dict[str, Any]) -> str | None:
    return _canonical_row_step7_fields(row).get("business_outcome_class")


def _row_acceptance_class(row: dict[str, Any]) -> str | None:
    return _canonical_row_step7_fields(row).get("acceptance_class")


def _row_is_failure_outcome(row: dict[str, Any]) -> bool:
    return _row_business_outcome_class(row) == "failure"


def _build_tri_state_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    acceptance_counter = Counter(str(_row_acceptance_class(row) or "unknown") for row in rows)
    outcome_counter = Counter(str(_row_business_outcome_class(row) or "unknown") for row in rows)
    return {
        "accepted_count": acceptance_counter.get("accepted", 0),
        "review_required_count": acceptance_counter.get("review_required", 0),
        "rejected_count": acceptance_counter.get("rejected", 0),
        "success_count": outcome_counter.get("success", 0),
        "risk_count": outcome_counter.get("risk", 0),
        "failure_count": outcome_counter.get("failure", 0),
    }


def _build_review_index(
    *,
    run_id: str,
    rows: list[dict[str, Any]],
    input_mode: str,
    input_paths: dict[str, str],
) -> list[dict[str, Any]]:
    review_rows: list[dict[str, Any]] = []
    for row in rows:
        official_review_fields = _require_row_official_review_fields(row)
        canonical_step7_fields = _canonical_row_step7_fields(row)
        review_rows.append(
            {
                "case_id": str(row["case_id"]),
                "test_case_name": None,
                "source_test_file": None,
                "mainnodeid": str(row.get("case_id")),
                "input_mode": input_mode,
                "input_paths": dict(input_paths),
                "reachable": True,
                "official_review_eligible": official_review_fields["official_review_eligible"],
                "output_dir": row["case_dir"],
                "success": bool(canonical_step7_fields["success"]),
                "business_outcome_class": canonical_step7_fields["business_outcome_class"],
                "flow_success": bool(row.get("flow_success", row.get("success"))),
                "acceptance_class": canonical_step7_fields["acceptance_class"],
                "acceptance_reason": canonical_step7_fields["acceptance_reason"],
                "status": canonical_step7_fields["status"],
                "root_cause_layer": official_review_fields["root_cause_layer"],
                "root_cause_type": official_review_fields["root_cause_type"],
                "visual_review_class": official_review_fields["visual_review_class"],
                "representative_node_id": row.get("representative_node_id"),
                "representative_kind": row.get("representative_kind"),
                "representative_has_evd": row.get("representative_has_evd"),
                "representative_is_anchor": row.get("representative_is_anchor"),
                "kind": row.get("resolved_kind"),
                "kind_source": row.get("kind_source"),
                "kind_2": row.get("kind_2"),
                "run_id": run_id,
                "status_path": row.get("status_path"),
                "audit_path": row.get("audit_path"),
                "polygon_path": row.get("polygon_path") or row.get("virtual_polygon_path"),
                "rendered_map_png": row.get("rendered_map_png"),
                "blocking_reason": official_review_fields["blocking_reason"],
                "failure_bucket": official_review_fields["failure_bucket"],
            }
        )
    return review_rows


def _render_review_summary_markdown(
    *,
    run_id: str,
    input_paths: dict[str, str],
    review_index: list[dict[str, Any]],
) -> str:
    visual_counter = Counter(str(item.get("visual_review_class") or "unknown") for item in review_index)
    failed_case_ids = [
        str(item["case_id"])
        for item in review_index
        if item.get("business_outcome_class") == "failure"
        or item.get("status") == "worker_exception"
    ]
    lines = [
        f"# Stage3 Review Summary ({run_id})",
        "",
        f"- run_id: `{run_id}`",
        "- 输入来源说明：本批正式材料全部来自同一批 full-input 运行结果。",
        f"- 正式 case 总数：`{len(review_index)}`",
        f"- V1 数量：`{visual_counter.get('V1 认可成功', 0)}`",
        f"- V2 数量：`{visual_counter.get('V2 业务正确但几何待修', 0)}`",
        f"- V3 数量：`{visual_counter.get('V3 漏包 required', 0)}`",
        f"- V4 数量：`{visual_counter.get('V4 误包 foreign', 0)}`",
        f"- V5 数量：`{visual_counter.get('V5 明确失败', 0)}`",
        f"- 失败 case 清单：{', '.join(failed_case_ids) if failed_case_ids else '无'}",
        (
            "- `520394575`：本批未出现。"
            if "520394575" not in {str(item['case_id']) for item in review_index}
            else "- `520394575`：已包含于本批 review index，请单独核查其最终状态。"
        ),
        "- 非 `520394575` 失败 case 的轮次变化说明：详见对应轮次 `failed_cases_diff.md` 与 `integration_round_summary.md`。",
        "- 是否存在环境缺失：否。",
        "- 是否存在 mixed-source 风险：否，本批文件均由同一批运行结果新生成。",
        "- 是否允许宣告完成：待主控结合测试轮次与多角色留痕统一判定。",
        "",
        "## 输入路径",
    ]
    for key, value in input_paths.items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def _render_review_summary_markdown_v2(
    *,
    run_id: str,
    input_paths: dict[str, str],
    review_index: list[dict[str, Any]],
) -> str:
    visual_counter = Counter(str(item.get("visual_review_class") or "unknown") for item in review_index)
    official_failure_case_ids = [
        str(item["case_id"])
        for item in review_index
        if item.get("official_review_eligible")
        and item.get("business_outcome_class") == "failure"
    ]
    out_of_scope_case_ids = [
        str(item["case_id"])
        for item in review_index
        if not item.get("official_review_eligible")
    ]
    lines = [
        f"# Stage3 Review Summary ({run_id})",
        "",
        f"- run_id: `{run_id}`",
        "- 输入来源说明：本批正式材料全部来自同一批真实运行结果。",
        f"- 正式 case 总数：`{len(review_index)}`",
        f"- official-review eligible 数量：`{sum(1 for item in review_index if item.get('official_review_eligible'))}`",
        f"- frozen-constraints conflict 数量：`{len(out_of_scope_case_ids)}`",
        f"- V1 数量：`{visual_counter.get('V1 认可成功', 0)}`",
        f"- V2 数量：`{visual_counter.get('V2 业务正确但几何待修', 0)}`",
        f"- V3 数量：`{visual_counter.get('V3 漏包 required', 0)}`",
        f"- V4 数量：`{visual_counter.get('V4 误包 foreign', 0)}`",
        f"- V5 数量：`{visual_counter.get('V5 明确失败', 0)}`",
        f"- official-review 失败 case：`{', '.join(official_failure_case_ids) if official_failure_case_ids else '无'}`",
        f"- out-of-scope / frozen-constraints conflict：`{', '.join(out_of_scope_case_ids) if out_of_scope_case_ids else '无'}`",
        (
            "- `520394575`：未出现在本批 review index 中。"
            if "520394575" not in {str(item['case_id']) for item in review_index}
            else "- `520394575`：已包含于本批 review index 中，请单独核查其最终状态。"
        ),
        "- 非 `520394575` 失败 case 的轮次变化说明：详见对应轮次 `failed_cases_diff.md` 与 `integration_round_summary.md`。",
        "- 是否存在环境缺失：否。",
        "- 是否存在 mixed-source 风险：否，本批文件均由同一批运行结果新生成。",
        "- 是否允许宣告完成：待主控结合测试轮次与多角色留痕统一判定。",
        "",
        "## 输入路径",
    ]
    for key, value in input_paths.items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def _render_review_summary_markdown_v3(
    *,
    run_id: str,
    input_paths: dict[str, str],
    review_index: list[dict[str, Any]],
) -> str:
    tri_state_counts = _build_tri_state_counts(review_index)
    visual_counter = Counter(str(item.get("visual_review_class") or "unknown") for item in review_index)
    official_failure_case_ids = [
        str(item["case_id"])
        for item in review_index
        if item.get("official_review_eligible")
        and item.get("business_outcome_class") == "failure"
    ]
    out_of_scope_case_ids = [
        str(item["case_id"])
        for item in review_index
        if not item.get("official_review_eligible")
    ]
    lines = [
        f"# Stage3 Review Summary ({run_id})",
        "",
        f"- run_id: `{run_id}`",
        "- 输入来源说明：本批正式材料全部来自同一批真实运行结果。",
        f"- 正式 case 总数：`{len(review_index)}`",
        f"- accepted 数量：`{tri_state_counts['accepted_count']}`",
        f"- review_required 数量：`{tri_state_counts['review_required_count']}`",
        f"- rejected 数量：`{tri_state_counts['rejected_count']}`",
        f"- business outcome / success 数量：`{tri_state_counts['success_count']}`",
        f"- business outcome / risk 数量：`{tri_state_counts['risk_count']}`",
        f"- business outcome / failure 数量：`{tri_state_counts['failure_count']}`",
        f"- official-review eligible 数量：`{sum(1 for item in review_index if item.get('official_review_eligible'))}`",
        f"- frozen-constraints conflict 数量：`{len(out_of_scope_case_ids)}`",
        f"- V1 数量：`{visual_counter.get('V1 认可成功', 0)}`",
        f"- V2 数量：`{visual_counter.get('V2 业务正确但几何待修', 0)}`",
        f"- V3 数量：`{visual_counter.get('V3 漏包 required', 0)}`",
        f"- V4 数量：`{visual_counter.get('V4 误包 foreign', 0)}`",
        f"- V5 数量：`{visual_counter.get('V5 明确失败', 0)}`",
        f"- official-review 失败 case：`{', '.join(official_failure_case_ids) if official_failure_case_ids else '无'}`",
        f"- out-of-scope / frozen-constraints conflict：`{', '.join(out_of_scope_case_ids) if out_of_scope_case_ids else '无'}`",
        (
            "- `520394575`：未出现在本批 review index 中。"
            if "520394575" not in {str(item['case_id']) for item in review_index}
            else "- `520394575`：已包含于本批 review index 中，请单独核查其最终状态。"
        ),
        "- 非 `520394575` 失败 case 的轮次变化说明：详见对应轮次 `failed_cases_diff.md` 与 `integration_round_summary.md`。",
        "- 是否存在环境缺失：否。",
        "- 是否存在 mixed-source 风险：否，本批文件均由同一批运行结果新生成。",
        "- 兼容字段说明：若 `summary.json` 保留 `success_count/failed_count`，仅作为兼容统计；主统计以 accepted/review_required/rejected 为准。",
        "- 是否允许宣告完成：待主控结合测试轮次与多角色留痕统一判定。",
        "",
        "## 输入路径",
    ]
    for key, value in input_paths.items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def _build_package_manifest(
    *,
    run_id: str,
    out_root: Path,
    input_mode: str,
    input_paths: dict[str, str],
    polygons_path: Path,
    summary_path: Path,
    review_index_path: Path,
    review_summary_path: Path,
    perf_summary_path: Path,
    exception_summary_path: Path,
    cases_root: Path,
    rendered_maps_root: Path,
    review_index: list[dict[str, Any]],
) -> dict[str, Any]:
    official_failure_case_ids = [
        str(item["case_id"])
        for item in review_index
        if item.get("official_review_eligible")
        and item.get("business_outcome_class") == "failure"
    ]
    excluded_out_of_scope_case_ids = [
        str(item["case_id"])
        for item in review_index
        if not item.get("official_review_eligible")
    ]
    return {
        "run_id": run_id,
        "generated_at": _now_text(),
        "input_mode": input_mode,
        "input_paths": dict(input_paths),
        "run_root": str(out_root),
        "mixed_source": False,
        "counts": {
            "case_count": len(review_index),
            "official_review_eligible_count": sum(
                1 for item in review_index if item.get("official_review_eligible")
            ),
            "frozen_constraints_conflict_count": len(excluded_out_of_scope_case_ids),
            "official_failure_count": len(official_failure_case_ids),
        },
        "official_failure_case_ids": official_failure_case_ids,
        "excluded_out_of_scope_case_ids": excluded_out_of_scope_case_ids,
        "structure": {
            "cases_dir": str(cases_root),
            "rendered_maps_dir": str(rendered_maps_root),
            "virtual_intersection_polygons": str(polygons_path),
            "summary": str(summary_path),
            "perf_summary": str(perf_summary_path),
            "review_index": str(review_index_path),
            "review_summary": str(review_summary_path),
            "exception_summary": str(exception_summary_path),
        },
        "whitelist": {
            "root_files": [
                str(polygons_path),
                str(summary_path),
                str(perf_summary_path),
                str(review_index_path),
                str(review_summary_path),
                str(exception_summary_path),
            ],
            "case_dirs": [str(item.get("output_dir")) for item in review_index],
        },
    }


def _build_package_manifest_v2(
    *,
    run_id: str,
    out_root: Path,
    input_mode: str,
    input_paths: dict[str, str],
    polygons_path: Path,
    summary_path: Path,
    review_index_path: Path,
    review_summary_path: Path,
    perf_summary_path: Path,
    exception_summary_path: Path,
    cases_root: Path,
    rendered_maps_root: Path,
    review_index: list[dict[str, Any]],
) -> dict[str, Any]:
    tri_state_counts = _build_tri_state_counts(review_index)
    official_failure_case_ids = [
        str(item["case_id"])
        for item in review_index
        if item.get("official_review_eligible")
        and item.get("business_outcome_class") == "failure"
    ]
    excluded_out_of_scope_case_ids = [
        str(item["case_id"])
        for item in review_index
        if not item.get("official_review_eligible")
    ]
    return {
        "run_id": run_id,
        "generated_at": _now_text(),
        "input_mode": input_mode,
        "input_paths": dict(input_paths),
        "run_root": str(out_root),
        "mixed_source": False,
        "counts": {
            "case_count": len(review_index),
            "accepted_count": tri_state_counts["accepted_count"],
            "review_required_count": tri_state_counts["review_required_count"],
            "rejected_count": tri_state_counts["rejected_count"],
            "success_count": tri_state_counts["success_count"],
            "risk_count": tri_state_counts["risk_count"],
            "failure_count": tri_state_counts["failure_count"],
            "official_review_eligible_count": sum(
                1 for item in review_index if item.get("official_review_eligible")
            ),
            "frozen_constraints_conflict_count": len(excluded_out_of_scope_case_ids),
            "official_failure_count": len(official_failure_case_ids),
        },
        "official_failure_case_ids": official_failure_case_ids,
        "excluded_out_of_scope_case_ids": excluded_out_of_scope_case_ids,
        "structure": {
            "cases_dir": str(cases_root),
            "rendered_maps_dir": str(rendered_maps_root),
            "virtual_intersection_polygons": str(polygons_path),
            "summary": str(summary_path),
            "perf_summary": str(perf_summary_path),
            "review_index": str(review_index_path),
            "review_summary": str(review_summary_path),
            "exception_summary": str(exception_summary_path),
        },
        "whitelist": {
            "root_files": [
                str(polygons_path),
                str(summary_path),
                str(perf_summary_path),
                str(review_index_path),
                str(review_summary_path),
                str(exception_summary_path),
            ],
            "case_dirs": [str(item.get("output_dir")) for item in review_index],
        },
    }


def _build_package_consistency_audit(
    *,
    run_id: str,
    out_root: Path,
    review_index: list[dict[str, Any]],
    package_manifest: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    out_root_resolved = out_root.resolve()

    def _check_path(case_id: str, label: str, path_text: str | None, *, expect_file: bool) -> None:
        if path_text is None:
            issues.append({"case_id": case_id, "kind": "missing_path", "field": label})
            return
        path = Path(path_text)
        exists = path.is_file() if expect_file else path.is_dir()
        if not exists:
            issues.append({"case_id": case_id, "kind": "missing_artifact", "field": label, "path": path_text})
            return
        try:
            path.resolve().relative_to(out_root_resolved)
        except Exception:
            issues.append({"case_id": case_id, "kind": "mixed_source_path", "field": label, "path": path_text})

    for item in review_index:
        case_id = str(item["case_id"])
        if item.get("run_id") != run_id:
            issues.append(
                {
                    "case_id": case_id,
                    "kind": "run_id_mismatch",
                    "expected": run_id,
                    "actual": item.get("run_id"),
                }
            )
        _check_path(case_id, "output_dir", item.get("output_dir"), expect_file=False)
        _check_path(case_id, "status_path", item.get("status_path"), expect_file=True)
        _check_path(case_id, "audit_path", item.get("audit_path"), expect_file=True)
        _check_path(case_id, "polygon_path", item.get("polygon_path"), expect_file=True)
        if item.get("rendered_map_png") is not None:
            _check_path(case_id, "rendered_map_png", item.get("rendered_map_png"), expect_file=True)
        if not item.get("official_review_eligible") and item.get("root_cause_layer") != ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT:
            issues.append(
                {
                    "case_id": case_id,
                    "kind": "ineligible_case_wrong_root_cause_layer",
                    "root_cause_layer": item.get("root_cause_layer"),
                }
            )
        if (
            item.get("official_review_eligible")
            and item.get("business_outcome_class") != "failure"
            and item.get("kind") in {None, ""}
        ):
            issues.append({"case_id": case_id, "kind": "eligible_success_missing_kind"})

    return {
        "run_id": run_id,
        "checked_case_count": len(review_index),
        "issue_count": len(issues),
        "mixed_source": any(issue.get("kind") == "mixed_source_path" for issue in issues),
        "official_failure_case_ids": package_manifest.get("official_failure_case_ids", []),
        "excluded_out_of_scope_case_ids": package_manifest.get("excluded_out_of_scope_case_ids", []),
        "issues": issues,
    }


def _build_full_input_summary_payload(
    *,
    run_id: str,
    mode: str,
    review_mode: bool,
    workers: int,
    max_cases: int | None,
    out_root_path: Path,
    cases_root: Path,
    rendered_maps_root: Path,
    polygons_path: Path,
    review_index_path: Path,
    review_summary_path: Path,
    package_manifest_path: Path,
    package_consistency_audit_path: Path,
    preflight: dict[str, Any],
    shared_memory_summary: dict[str, Any],
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    skipped_case_ids: list[str],
    rows: list[dict[str, Any]],
    package_manifest: dict[str, Any] | None = None,
    package_consistency_audit: dict[str, Any] | None = None,
    crashed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tri_state_counts = _build_tri_state_counts(rows)
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "review_mode": review_mode,
        "workers": workers,
        "max_cases": max_cases,
        "run_root": str(out_root_path),
        "structure": {
            "cases_dir": str(cases_root),
            "rendered_maps_dir": str(rendered_maps_root),
            "virtual_intersection_polygons": str(polygons_path),
            "review_index": str(review_index_path),
            "review_summary": str(review_summary_path),
            "review_package_manifest": str(package_manifest_path),
            "review_package_consistency_audit": str(package_consistency_audit_path),
        },
        "preflight": preflight,
        "shared_memory": shared_memory_summary,
        "selected_case_ids": selected_case_ids,
        "discovered_case_ids": discovered_case_ids,
        "skipped_case_ids": skipped_case_ids,
        "case_count": len(rows),
        "accepted_count": tri_state_counts["accepted_count"],
        "review_required_count": tri_state_counts["review_required_count"],
        "rejected_count": tri_state_counts["rejected_count"],
        "success_count": tri_state_counts["success_count"],
        "risk_count": tri_state_counts["risk_count"],
        "failed_count": tri_state_counts["failure_count"],
        "summary_semantics": {
            "primary_statistics": "accepted/review_required/rejected",
            "compatibility_statistics": {
                "success_count": "business_outcome=success",
                "risk_count": "business_outcome=risk",
                "failed_count": "business_outcome=failure",
            },
            "success_flag_semantics": "accepted_only_compat",
        },
        "rows": rows,
    }
    if package_manifest is not None:
        payload["official_failure_case_ids"] = package_manifest["official_failure_case_ids"]
        payload["excluded_out_of_scope_case_ids"] = package_manifest["excluded_out_of_scope_case_ids"]
        payload["package_manifest"] = package_manifest
    if package_consistency_audit is not None:
        payload["package_consistency_audit"] = package_consistency_audit
    if crashed is not None:
        payload["crashed"] = crashed
    return payload


SHARED_LAYER_PROPERTY_FIELDS: dict[str, tuple[str, ...]] = {
    "nodes": ("id", "mainnodeid", "has_evd", "is_anchor", "kind", "kind_2", "grade_2"),
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
    if debug:
        rendered_maps_root.mkdir(parents=True, exist_ok=True)

    preflight_path = out_root_path / "preflight.json"
    summary_path = out_root_path / "summary.json"
    perf_summary_path = out_root_path / "perf_summary.json"
    polygons_path = out_root_path / "virtual_intersection_polygons.gpkg"
    review_index_path = out_root_path / "review_index.json"
    review_summary_path = out_root_path / "review_summary.md"
    package_manifest_path = out_root_path / "review_package_manifest.json"
    package_consistency_audit_path = out_root_path / "review_package_consistency_audit.json"
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
    last_case_progress_completed_count = 0
    last_case_progress_written_at = 0.0
    shared_memory_summary: dict[str, Any] = {
        "enabled": False,
        "node_group_lookup": False,
        "shared_local_layer_query": False,
        "layers": {},
    }

    def _write_case_execution_progress(case_id: str, *, force: bool = False) -> None:
        nonlocal last_case_progress_completed_count
        nonlocal last_case_progress_written_at
        completed_case_count = int(counts["completed_case_count"])
        now = time.perf_counter()
        if not force:
            completed_delta = completed_case_count - last_case_progress_completed_count
            elapsed_since_last = now - last_case_progress_written_at
            if (
                completed_delta < CASE_EXECUTION_PROGRESS_FLUSH_EVERY
                and elapsed_since_last < CASE_EXECUTION_PROGRESS_FLUSH_INTERVAL_SEC
            ):
                return
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="case_execution",
            counts=counts,
            message=f"Completed case {case_id}.",
        )
        last_case_progress_completed_count = completed_case_count
        last_case_progress_written_at = now

    def _record_case_result(row: dict[str, Any]) -> None:
        case_id = str(row["case_id"])
        polygon_feature = row.pop("polygon_feature", None)
        if row.get("success") and polygon_feature is not None:
            polygon_feature_cache[case_id] = polygon_feature
        if row.get("acceptance_class") != "accepted" and row.get("rendered_map_png"):
            try:
                _ensure_failure_styled_render(
                    row.get("rendered_map_png"),
                    acceptance_class=row.get("acceptance_class"),
                )
            except Exception as exc:
                announce(logger, f"[T02-FULL-POC] failure style overlay skipped case_id={case_id} reason={type(exc).__name__}: {exc}")
        rows.append(row)
        counts["completed_case_count"] += 1
        if not _row_is_failure_outcome(row):
            counts["success_case_count"] += 1
        else:
            counts["failed_case_count"] += 1
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
        if _row_is_failure_outcome(row):
            _write_exception_summary(exception_summary_path, rows)
        _write_case_execution_progress(case_id, force=_row_is_failure_outcome(row))

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
            "write_run_progress": len(selected_case_ids) <= 1,
            "write_perf_markers": len(selected_case_ids) <= 1,
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
        review_input_paths = {
            "nodes": str(nodes_path),
            "roads": str(roads_path),
            "drivezone": str(drivezone_path),
            "rcsdroad": str(rcsdroad_path),
            "rcsdnode": str(rcsdnode_path),
        }
        review_index = _build_review_index(
            run_id=resolved_run_id,
            rows=rows,
            input_mode=FULL_INPUT_MODE_NAME,
            input_paths=review_input_paths,
        )
        write_json(review_index_path, review_index)
        review_summary_path.write_text(
            _render_review_summary_markdown_v3(
                run_id=resolved_run_id,
                input_paths=review_input_paths,
                review_index=review_index,
            ),
            encoding="utf-8",
        )

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

        package_manifest = _build_package_manifest_v2(
            run_id=resolved_run_id,
            out_root=out_root_path,
            input_mode=FULL_INPUT_MODE_NAME,
            input_paths=review_input_paths,
            polygons_path=polygons_path,
            summary_path=summary_path,
            review_index_path=review_index_path,
            review_summary_path=review_summary_path,
            perf_summary_path=perf_summary_path,
            exception_summary_path=exception_summary_path,
            cases_root=cases_root,
            rendered_maps_root=rendered_maps_root,
            review_index=review_index,
        )
        write_json(package_manifest_path, package_manifest)
        package_consistency_audit = _build_package_consistency_audit(
            run_id=resolved_run_id,
            out_root=out_root_path,
            review_index=review_index,
            package_manifest=package_manifest,
        )
        write_json(package_consistency_audit_path, package_consistency_audit)

        summary = _build_full_input_summary_payload(
            run_id=resolved_run_id,
            mode=mode,
            review_mode=review_mode,
            workers=workers,
            max_cases=max_cases,
            out_root_path=out_root_path,
            cases_root=cases_root,
            rendered_maps_root=rendered_maps_root,
            polygons_path=polygons_path,
            review_index_path=review_index_path,
            review_summary_path=review_summary_path,
            package_manifest_path=package_manifest_path,
            package_consistency_audit_path=package_consistency_audit_path,
            preflight=preflight,
            shared_memory_summary=shared_memory_summary,
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            skipped_case_ids=skipped_case_ids,
            rows=rows,
            package_manifest=package_manifest,
            package_consistency_audit=package_consistency_audit,
        )
        write_json(summary_path, summary)

        success = all(bool(item.get("success")) for item in rows)
        _write_progress(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="success" if success else "completed_with_failures",
            current_stage="completed",
            counts=counts,
            message=(
                "Finished "
                f"{len(rows)} cases; accepted={summary['accepted_count']} "
                f"review_required={summary['review_required_count']} rejected={summary['rejected_count']}."
            ),
        )
        announce(
            logger,
            (
                "[T02-FULL-POC] completed "
                f"accepted_count={summary['accepted_count']} "
                f"review_required_count={summary['review_required_count']} "
                f"rejected_count={summary['rejected_count']} "
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
            _build_full_input_summary_payload(
                run_id=resolved_run_id,
                mode=mode,
                review_mode=review_mode,
                workers=workers,
                max_cases=max_cases,
                out_root_path=out_root_path,
                cases_root=cases_root,
                rendered_maps_root=rendered_maps_root,
                polygons_path=polygons_path,
                review_index_path=review_index_path,
                review_summary_path=review_summary_path,
                package_manifest_path=package_manifest_path,
                package_consistency_audit_path=package_consistency_audit_path,
                preflight=preflight,
                shared_memory_summary=shared_memory_summary,
                selected_case_ids=selected_case_ids,
                discovered_case_ids=discovered_case_ids,
                skipped_case_ids=skipped_case_ids,
                rows=sorted(rows, key=lambda item: sort_patch_key(str(item["case_id"]))),
                crashed=crash_report,
            ),
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
        review_index_path=review_index_path,
        review_summary_path=review_summary_path,
        package_manifest_path=package_manifest_path,
        package_consistency_audit_path=package_consistency_audit_path,
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
