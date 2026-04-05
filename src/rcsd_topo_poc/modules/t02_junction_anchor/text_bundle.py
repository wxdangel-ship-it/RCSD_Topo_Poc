from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import struct
import tempfile
import zlib
import zipfile
from heapq import heappop, heappush
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import fiona
import numpy as np
from shapely.affinity import translate
from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon, Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedNode,
    VirtualIntersectionPocError,
    _build_grid,
    _filter_loaded_features_to_patch,
    _filter_parsed_roads_to_patch,
    _load_layer_filtered,
    _parse_nodes,
    _parse_roads,
    _rasterize_geometries,
    _resolve_group,
    _resolve_current_patch_id_from_roads,
)


TEXT_BUNDLE_VERSION = "1"
TEXT_BUNDLE_MODE_SINGLE = "single_case"
TEXT_BUNDLE_MODE_MULTI = "multi_case"
TEXT_BUNDLE_LIMIT_BYTES = 300 * 1024
TEXT_BUNDLE_BEGIN = "BEGIN_T02_BUNDLE"
TEXT_BUNDLE_PAYLOAD = "payload:"
TEXT_BUNDLE_META = "meta: "
TEXT_BUNDLE_CHECKSUM = "checksum: "
TEXT_BUNDLE_END = "END_T02_BUNDLE"
TEXT_BUNDLE_LINE_WIDTH = 120
LOCAL_COORD_DECIMALS = 1
BUNDLE_CONTEXT_MAX_DISTANCE_M = 200.0
BUNDLE_CONTEXT_SURFACE_MARGIN_M = 40.0

LEGACY_TEXT_BUNDLE_PAYLOAD = "PAYLOAD"
LEGACY_TEXT_BUNDLE_END_PAYLOAD = "END_PAYLOAD"
LEGACY_TEXT_BUNDLE_META = "META "
LEGACY_TEXT_BUNDLE_CHECKSUM = "CHECKSUM "

NODE_FIELDS = ("id", "mainnodeid", "has_evd", "is_anchor", "kind_2", "grade_2")
ROAD_REQUIRED_FIELDS = ("id", "direction", "snodeid", "enodeid")
ROAD_OPTIONAL_FIELDS = ("patchid", "patch_id")
RCSDNODE_FIELDS = ("id", "mainnodeid")
REQUIRED_BUNDLE_FILES = (
    "manifest.json",
    "drivezone_mask.png",
    "drivezone.gpkg",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
    "size_report.json",
)
OPTIONAL_BUNDLE_FILES = ("divstripzone.gpkg",)
VECTOR_BUNDLE_FILES = (
    "drivezone.gpkg",
    "divstripzone.gpkg",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
)


class TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    failure_reason: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path
    case_dirs: tuple[Path, ...] = ()


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except Exception:
            return text
    return text


def _out_txt_size_report_path(out_txt: Path) -> Path:
    return out_txt.with_suffix(out_txt.suffix + ".size_report.json")


def _vector_file_bytes(filename: str, features: Iterable[dict[str, Any]]) -> bytes:
    feature_list = list(features)
    with tempfile.TemporaryDirectory() as temp_dir:
        vector_path = Path(temp_dir) / filename
        write_vector(vector_path, feature_list, crs_text=None, layer_name=vector_path.stem)
        return vector_path.read_bytes()


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _mask_png_bytes(mask: np.ndarray) -> bytes:
    if mask.ndim != 2:
        raise TextBundleError("invalid_mask", "drivezone mask must be a 2D array.")
    image = np.where(mask, 255, 0).astype(np.uint8)
    rows = [b"\x00" + row.tobytes() for row in image]
    raw = b"".join(rows)
    width = int(image.shape[1])
    height = int(image.shape[0])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _round_number(value: float) -> float:
    return round(float(value), LOCAL_COORD_DECIMALS)


def _localize_coordinates(value: Any, *, origin_x: float, origin_y: float) -> Any:
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
            localized = [_round_number(float(value[0]) - origin_x), _round_number(float(value[1]) - origin_y)]
            if len(value) > 2:
                localized.extend(value[2:])
            return localized
        return [_localize_coordinates(item, origin_x=origin_x, origin_y=origin_y) for item in value]
    return value


def _local_geometry_payload(
    geometry: BaseGeometry | None,
    *,
    origin_x: float,
    origin_y: float,
) -> dict[str, Any] | None:
    if geometry is None:
        return None
    payload = json.loads(json.dumps(shape(geometry.__geo_interface__).__geo_interface__))
    payload["coordinates"] = _localize_coordinates(payload.get("coordinates"), origin_x=origin_x, origin_y=origin_y)
    if payload.get("type") == "GeometryCollection":
        payload["geometries"] = [
            _local_geometry_payload(shape(item), origin_x=origin_x, origin_y=origin_y)
            for item in payload.get("geometries") or []
        ]
    return payload


def _filter_properties(properties: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
    missing = [field_name for field_name in field_names if field_name not in properties]
    if missing:
        raise TextBundleError("missing_required_field", f"Missing required fields: {','.join(missing)}")
    return {field_name: properties.get(field_name) for field_name in field_names}


def _filter_road_properties(properties: dict[str, Any]) -> dict[str, Any]:
    filtered = _filter_properties(properties, ROAD_REQUIRED_FIELDS)
    for field_name in ROAD_OPTIONAL_FIELDS:
        if field_name in properties:
            filtered[field_name] = properties.get(field_name)
    return filtered


def _local_feature(
    *,
    properties: dict[str, Any],
    geometry: BaseGeometry | None,
    origin_x: float,
    origin_y: float,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": _local_geometry_payload(geometry, origin_x=origin_x, origin_y=origin_y),
    }


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _wrap_payload_text(text: str, *, width: int = TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        TEXT_BUNDLE_BEGIN,
        TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        TEXT_BUNDLE_CHECKSUM + checksum,
        TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _build_size_report(
    *,
    total_text_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    limit_bytes: int,
) -> dict[str, Any]:
    dominant_size_source = None
    if per_file_compressed_size_bytes:
        dominant_size_source = max(per_file_compressed_size_bytes.items(), key=lambda item: item[1])[0]
    return {
        "total_text_size_bytes": total_text_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
        "dominant_size_source": dominant_size_source,
        "within_limit": total_text_size_bytes <= limit_bytes,
        "limit_bytes": limit_bytes,
    }


def _prepare_bundle_files(
    *,
    drivezone_features: list[dict[str, Any]],
    divstripzone_features: list[dict[str, Any]] | None,
    nodes_features: list[dict[str, Any]],
    roads_features: list[dict[str, Any]],
    rcsdroad_features: list[dict[str, Any]],
    rcsdnode_features: list[dict[str, Any]],
    drivezone_mask_png: bytes,
    manifest: dict[str, Any],
    size_report: dict[str, Any] | None,
) -> dict[str, bytes]:
    files = {
        "drivezone_mask.png": drivezone_mask_png,
        "drivezone.gpkg": _vector_file_bytes("drivezone.gpkg", drivezone_features),
        "nodes.gpkg": _vector_file_bytes("nodes.gpkg", nodes_features),
        "roads.gpkg": _vector_file_bytes("roads.gpkg", roads_features),
        "rcsdroad.gpkg": _vector_file_bytes("rcsdroad.gpkg", rcsdroad_features),
        "rcsdnode.gpkg": _vector_file_bytes("rcsdnode.gpkg", rcsdnode_features),
        "manifest.json": json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
    }
    if divstripzone_features is not None:
        files["divstripzone.gpkg"] = _vector_file_bytes("divstripzone.gpkg", divstripzone_features)
    if size_report is not None:
        files["size_report.json"] = json.dumps(size_report, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return files


def _bundle_file_list_from_manifest(
    manifest: dict[str, Any],
    *,
    available_names: Iterable[str] | None = None,
) -> tuple[str, ...]:
    resolved = list(REQUIRED_BUNDLE_FILES)
    optional_sources: set[str] = set(available_names or ())
    manifest_file_list = manifest.get("file_list")
    if isinstance(manifest_file_list, list):
        optional_sources.update(str(name) for name in manifest_file_list)
    for optional_name in OPTIONAL_BUNDLE_FILES:
        if optional_name in optional_sources and optional_name not in resolved:
            resolved.append(optional_name)
    return tuple(resolved)


def _parse_current_text_bundle(lines: list[str]) -> tuple[dict[str, Any], bytes, str]:
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc

    if not (meta_index < payload_index < checksum_index < end_index):
        raise TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    if not payload_text:
        raise TextBundleError("invalid_bundle_format", "Bundle payload is empty.")
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    return meta, payload_bytes, checksum


def _parse_legacy_text_bundle(lines: list[str]) -> tuple[dict[str, Any], bytes, str]:
    try:
        meta_line = next(line for line in lines if line.startswith(LEGACY_TEXT_BUNDLE_META))
        payload_start = lines.index(LEGACY_TEXT_BUNDLE_PAYLOAD)
        payload_end = lines.index(LEGACY_TEXT_BUNDLE_END_PAYLOAD)
        checksum_line = next(line for line in lines if line.startswith(LEGACY_TEXT_BUNDLE_CHECKSUM))
        end_line = next(line for line in lines if line.strip() == TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc

    if payload_end <= payload_start:
        raise TextBundleError("invalid_bundle_format", "Bundle payload section is malformed.")
    if lines.index(LEGACY_TEXT_BUNDLE_END_PAYLOAD) >= lines.index(TEXT_BUNDLE_END):
        raise TextBundleError("invalid_bundle_format", "Bundle footer order is invalid.")

    meta = json.loads(meta_line[len(LEGACY_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_start + 1 : payload_end]).strip()
    if not payload_text:
        raise TextBundleError("invalid_bundle_format", "Bundle payload is empty.")
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = checksum_line[len(LEGACY_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if not end_line:
        raise TextBundleError("invalid_bundle_format", "Bundle footer not found.")
    return meta, payload_bytes, checksum


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes, str]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != TEXT_BUNDLE_BEGIN:
        raise TextBundleError("invalid_bundle_format", "Bundle header not found.")

    if any(line.startswith(TEXT_BUNDLE_META) for line in lines) and any(line.strip() == TEXT_BUNDLE_PAYLOAD for line in lines):
        return _parse_current_text_bundle(lines)
    return _parse_legacy_text_bundle(lines)


def _resolve_target_nodes(
    *,
    nodes_path: Union[str, Path],
    nodes_layer: str | None,
    nodes_crs: str | None,
    normalized_mainnodeid: str,
) -> tuple[ParsedNode, list[ParsedNode]]:
    def target_group_match(properties: dict[str, Any]) -> bool:
        node_id = _normalize_id(properties.get("id"))
        group_id = _normalize_id(properties.get("mainnodeid"))
        return group_id == normalized_mainnodeid or (group_id is None and node_id == normalized_mainnodeid)

    target_nodes_layer_data = _load_layer_filtered(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=False,
        property_predicate=target_group_match,
    )
    target_group_nodes = _parse_nodes(target_nodes_layer_data, require_anchor_fields=True)
    if not target_group_nodes:
        raise TextBundleError("mainnodeid_not_found", f"mainnodeid='{normalized_mainnodeid}' was not found in nodes.")
    return _resolve_group(mainnodeid=normalized_mainnodeid, nodes=target_group_nodes)


def _non_empty_feature_geometries(features: Iterable[Any]) -> list[BaseGeometry]:
    geometries: list[BaseGeometry] = []
    for feature in features:
        geometry = getattr(feature, "geometry", None)
        if geometry is None or geometry.is_empty:
            continue
        geometries.append(geometry)
    return geometries


def _load_bundle_local_layers(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    divstripzone_path: Union[str, Path, None],
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    query_geometry: BaseGeometry,
    nodes_layer: Optional[str],
    roads_layer: Optional[str],
    drivezone_layer: Optional[str],
    divstripzone_layer: Optional[str],
    rcsdroad_layer: Optional[str],
    rcsdnode_layer: Optional[str],
    nodes_crs: Optional[str],
    roads_crs: Optional[str],
    drivezone_crs: Optional[str],
    divstripzone_crs: Optional[str],
    rcsdroad_crs: Optional[str],
    rcsdnode_crs: Optional[str],
) -> dict[str, Any]:
    local_divstripzone_layer = None
    if divstripzone_path is not None:
        local_divstripzone_layer = _load_layer_filtered(
            divstripzone_path,
            layer_name=divstripzone_layer,
            crs_override=divstripzone_crs,
            allow_null_geometry=False,
            query_geometry=query_geometry,
        )
    return {
        "nodes": _load_layer_filtered(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
            query_geometry=query_geometry,
        ),
        "roads": _load_layer_filtered(
            roads_path,
            layer_name=roads_layer,
            crs_override=roads_crs,
            allow_null_geometry=False,
            query_geometry=query_geometry,
        ),
        "drivezone": _load_layer_filtered(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
            query_geometry=query_geometry,
        ),
        "divstripzone": local_divstripzone_layer,
        "rcsdroad": _load_layer_filtered(
            rcsdroad_path,
            layer_name=rcsdroad_layer,
            crs_override=rcsdroad_crs,
            allow_null_geometry=False,
            query_geometry=query_geometry,
        ),
        "rcsdnode": _load_layer_filtered(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=False,
            query_geometry=query_geometry,
        ),
    }


def _build_bundle_context_query(
    *,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    local_nodes_layer: Any,
    parsed_roads: list[Any],
    local_drivezone_layer: Any,
    local_divstripzone_layer: Any | None,
    local_rcsdroad_layer: Any,
    local_rcsdnode_layer: Any,
    context_margin_m: float,
    is_complex_group: bool,
) -> BaseGeometry | None:
    seed_geometries: list[BaseGeometry] = [representative_node.geometry]
    seed_geometries.extend(
        node.geometry
        for node in group_nodes
        if node.geometry is not None and not node.geometry.is_empty
    )
    seed_geometries.extend(_non_empty_feature_geometries(local_nodes_layer.features))

    roadlike_geometries = [
        road.geometry
        for road in parsed_roads
        if road.geometry is not None and not road.geometry.is_empty
    ]
    roadlike_geometries.extend(_non_empty_feature_geometries(local_rcsdroad_layer.features))
    if local_divstripzone_layer is not None:
        roadlike_geometries.extend(_non_empty_feature_geometries(local_divstripzone_layer.features))
    seed_geometries.extend(roadlike_geometries)
    seed_geometries.extend(_non_empty_feature_geometries(local_rcsdnode_layer.features))

    drivezone_clip_geometry: BaseGeometry | None = None
    if roadlike_geometries:
        roadlike_multiplier = 3.0 if is_complex_group else 1.25
        node_multiplier = 2.0 if is_complex_group else 1.0
        drivezone_clip_geometry = unary_union(roadlike_geometries).buffer(
            context_margin_m * roadlike_multiplier,
            cap_style=2,
            join_style=2,
        )
        node_geometries = _non_empty_feature_geometries(local_nodes_layer.features)
        if node_geometries:
            drivezone_clip_geometry = unary_union(
                [
                    drivezone_clip_geometry,
                    unary_union(node_geometries).buffer(
                        context_margin_m * node_multiplier,
                        cap_style=2,
                        join_style=2,
                    ),
                ]
            )

    drivezone_geometries = _non_empty_feature_geometries(local_drivezone_layer.features)
    if drivezone_clip_geometry is None:
        seed_geometries.extend(drivezone_geometries)
    else:
        for geometry in drivezone_geometries:
            clipped = geometry.intersection(drivezone_clip_geometry)
            if clipped.is_empty:
                continue
            seed_geometries.append(clipped)

    if not seed_geometries:
        return None
    return unary_union(seed_geometries).buffer(
        context_margin_m,
        cap_style=2,
        join_style=2,
    )


def _build_bundle_extent_query(
    *,
    group_nodes: list[ParsedNode],
    representative_node: ParsedNode,
    max_distance_m: float,
) -> BaseGeometry:
    seed_geometries = [
        node.geometry
        for node in group_nodes
        if node.geometry is not None and not node.geometry.is_empty
    ]
    if not seed_geometries:
        seed_geometries = [representative_node.geometry]
    union_geometry = unary_union(seed_geometries)
    return union_geometry.buffer(max_distance_m)


def _is_bundle_semantic_boundary_node(node: ParsedNode) -> bool:
    if node.kind_2 in {None, 0}:
        return False
    return node.mainnodeid is None or node.mainnodeid == node.node_id


def _other_road_node_id(road: ParsedRoad, node_id: str) -> str | None:
    if road.snodeid == node_id and road.enodeid != node_id:
        return road.enodeid
    if road.enodeid == node_id and road.snodeid != node_id:
        return road.snodeid
    if road.snodeid == node_id and road.enodeid == node_id:
        return node_id
    return None


def _select_bundle_component_roads(
    *,
    parsed_roads: list[ParsedRoad],
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    max_distance_m: float,
) -> list[ParsedRoad]:
    adjacency: dict[str, list[ParsedRoad]] = {}
    for road in parsed_roads:
        adjacency.setdefault(road.snodeid, []).append(road)
        adjacency.setdefault(road.enodeid, []).append(road)

    member_node_ids = {node.node_id for node in group_nodes}
    boundary_node_ids = {
        node.node_id
        for node in local_nodes
        if node.node_id not in member_node_ids and _is_bundle_semantic_boundary_node(node)
    }

    heap: list[tuple[float, str]] = []
    best_distance: dict[str, float] = {}
    for node_id in member_node_ids:
        best_distance[node_id] = 0.0
        heappush(heap, (0.0, node_id))

    included_roads: dict[str, ParsedRoad] = {}
    while heap:
        distance_m, node_id = heappop(heap)
        if distance_m > best_distance.get(node_id, float("inf")):
            continue
        is_boundary = node_id in boundary_node_ids
        for road in adjacency.get(node_id, []):
            included_roads.setdefault(road.road_id, road)
            if is_boundary:
                continue
            other_node_id = _other_road_node_id(road, node_id)
            if other_node_id is None:
                continue
            next_distance_m = distance_m + float(road.geometry.length)
            if next_distance_m > max_distance_m:
                continue
            if next_distance_m >= best_distance.get(other_node_id, float("inf")):
                continue
            best_distance[other_node_id] = next_distance_m
            heappush(heap, (next_distance_m, other_node_id))
    return list(included_roads.values())


def _normalize_mainnodeids(value: Union[str, int, Iterable[Union[str, int]], None]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        raw_values: list[Union[str, int, float]] = [value]
    else:
        raw_values = list(value)

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        normalized_value = _normalize_id(raw_value)
        if normalized_value is None or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized_values.append(normalized_value)
    return normalized_values


def _extract_bundle_files(bundle_path: Path) -> dict[str, bytes]:
    _meta, payload_bytes, _checksum = _parse_text_bundle(bundle_path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        names = set(zf.namelist())
        missing = [name for name in REQUIRED_BUNDLE_FILES if name not in names]
        if missing:
            raise TextBundleError("bundle_missing_files", f"Bundle is missing required files: {','.join(missing)}")
        manifest = json.loads(zf.read("manifest.json"))
        bundle_files = _bundle_file_list_from_manifest(manifest, available_names=names)
        missing_bundle_files = [name for name in bundle_files if name not in names]
        if missing_bundle_files:
            raise TextBundleError("bundle_missing_files", f"Bundle is missing required files: {','.join(missing_bundle_files)}")
        return {name: zf.read(name) for name in bundle_files}


def _resolve_manifest_local_origin(manifest: dict[str, Any]) -> tuple[float, float]:
    local_origin = manifest.get("local_origin")
    if not isinstance(local_origin, dict):
        raise TextBundleError("bundle_missing_files", "Bundle manifest is missing local_origin.")
    try:
        origin_x = float(local_origin["x_epsg3857"])
        origin_y = float(local_origin["y_epsg3857"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TextBundleError("bundle_missing_files", "Bundle manifest local_origin is incomplete.") from exc
    return origin_x, origin_y


def _restore_local_vector_file_to_target_crs(
    *,
    source_path: Path,
    target_path: Path,
    origin_x: float,
    origin_y: float,
) -> None:
    restored_features: list[dict[str, Any]] = []
    with fiona.open(source_path) as src:
        for feature in src:
            geometry_payload = feature.get("geometry")
            geometry = None if geometry_payload is None else translate(shape(geometry_payload), xoff=origin_x, yoff=origin_y)
            restored_features.append(
                {
                    "properties": dict(feature.get("properties") or {}),
                    "geometry": geometry,
                }
            )
    write_vector(
        target_path,
        restored_features,
        crs_text=TARGET_CRS.to_string(),
        layer_name=target_path.stem,
    )


def _restore_decoded_case_dir(
    *,
    source_dir: Path,
    target_dir: Path,
) -> None:
    manifest_path = source_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    origin_x, origin_y = _resolve_manifest_local_origin(manifest)
    bundle_files = _bundle_file_list_from_manifest(
        manifest,
        available_names=[path.name for path in source_dir.iterdir() if path.is_file()],
    )

    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for name in bundle_files:
        source_path = source_dir / name
        target_path = target_dir / name
        if name in VECTOR_BUNDLE_FILES:
            _restore_local_vector_file_to_target_crs(
                source_path=source_path,
                target_path=target_path,
                origin_x=origin_x,
                origin_y=origin_y,
            )
            continue
        shutil.copy2(source_path, target_path)

    manifest["decoded_output"] = {
        "vector_coordinates": "absolute_epsg3857",
        "vector_crs": TARGET_CRS.to_string(),
        "bundle_internal_vectors_localized": True,
        "decoded_at": _now_text(),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_t02_export_single_text_bundle(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    divstripzone_path: Union[str, Path, None],
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int],
    out_txt: Union[str, Path],
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    divstripzone_layer: Optional[str] = None,
    rcsdroad_layer: Optional[str] = None,
    rcsdnode_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
    divstripzone_crs: Optional[str] = None,
    rcsdroad_crs: Optional[str] = None,
    rcsdnode_crs: Optional[str] = None,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    max_text_size_bytes: int = TEXT_BUNDLE_LIMIT_BYTES,
) -> TextBundleExportArtifacts:
    out_txt_path = Path(out_txt)
    out_txt_path.parent.mkdir(parents=True, exist_ok=True)
    if out_txt_path.exists():
        out_txt_path.unlink()
    size_report_path = _out_txt_size_report_path(out_txt_path)
    if size_report_path.exists():
        size_report_path.unlink()

    normalized_mainnodeid = _normalize_id(mainnodeid)
    if normalized_mainnodeid is None:
        return TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=None,
            bundle_size_bytes=0,
            failure_reason="mainnodeid_not_found",
            failure_detail="mainnodeid is empty.",
        )

    try:
        representative_node, group_nodes = _resolve_target_nodes(
            nodes_path=nodes_path,
            nodes_layer=nodes_layer,
            nodes_crs=nodes_crs,
            normalized_mainnodeid=normalized_mainnodeid,
        )
        patch_query = _build_bundle_extent_query(
            group_nodes=group_nodes,
            representative_node=representative_node,
            max_distance_m=max(float(buffer_m), BUNDLE_CONTEXT_MAX_DISTANCE_M),
        )
        grid = _build_grid(representative_node.geometry, patch_size_m=patch_size_m, resolution_m=resolution_m)
        origin_x = grid.min_x
        origin_y = grid.min_y

        local_layers = _load_bundle_local_layers(
            nodes_path=nodes_path,
            roads_path=roads_path,
            drivezone_path=drivezone_path,
            divstripzone_path=divstripzone_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            query_geometry=patch_query,
            nodes_layer=nodes_layer,
            roads_layer=roads_layer,
            drivezone_layer=drivezone_layer,
            divstripzone_layer=divstripzone_layer,
            rcsdroad_layer=rcsdroad_layer,
            rcsdnode_layer=rcsdnode_layer,
            nodes_crs=nodes_crs,
            roads_crs=roads_crs,
            drivezone_crs=drivezone_crs,
            divstripzone_crs=divstripzone_crs,
            rcsdroad_crs=rcsdroad_crs,
            rcsdnode_crs=rcsdnode_crs,
        )
        local_nodes_layer = local_layers["nodes"]
        local_roads_layer = local_layers["roads"]
        local_drivezone_layer = local_layers["drivezone"]
        local_divstripzone_layer = local_layers["divstripzone"]
        local_rcsdroad_layer = local_layers["rcsdroad"]
        local_rcsdnode_layer = local_layers["rcsdnode"]

        local_nodes = _parse_nodes(local_nodes_layer, require_anchor_fields=True)
        parsed_roads = _parse_roads(local_roads_layer, label="roads")
        current_patch_id = _resolve_current_patch_id_from_roads(group_nodes=group_nodes, roads=parsed_roads)
        filtered_roads = _select_bundle_component_roads(
            parsed_roads=parsed_roads,
            group_nodes=group_nodes,
            local_nodes=local_nodes,
            max_distance_m=BUNDLE_CONTEXT_MAX_DISTANCE_M,
        )
        patch_filter_mode = "bounded_scene_extent_200m"

        road_surface_geometries = [
            road.geometry
            for road in filtered_roads
            if road.geometry is not None and not road.geometry.is_empty
        ]
        road_surface_geometries.extend(
            node.geometry
            for node in group_nodes
            if node.geometry is not None and not node.geometry.is_empty
        )
        if not road_surface_geometries:
            raise TextBundleError(
                "missing_roads",
                f"mainnodeid='{normalized_mainnodeid}' resolved no connected roads inside bounded scene extent.",
            )
        scene_query = unary_union(road_surface_geometries).buffer(
            BUNDLE_CONTEXT_SURFACE_MARGIN_M,
            cap_style=2,
            join_style=2,
        )

        included_node_ids = {
            node.node_id
            for node in group_nodes
        }
        for road in filtered_roads:
            included_node_ids.add(road.snodeid)
            included_node_ids.add(road.enodeid)

        local_drivezone_features = [
            feature
            for feature in local_drivezone_layer.features
            if feature.geometry is not None and feature.geometry.intersects(scene_query)
        ]
        local_divstripzone_features = (
            None
            if local_divstripzone_layer is None
            else [
                feature
                for feature in local_divstripzone_layer.features
                if feature.geometry is not None and feature.geometry.intersects(scene_query)
            ]
        )
        local_nodes_features = [
            feature
            for feature in local_nodes_layer.features
            if feature.geometry is not None
            and (
                _normalize_id(feature.properties.get("id")) in included_node_ids
                or feature.geometry.intersects(scene_query)
            )
        ]
        local_rcsdroad_features = [
            feature
            for feature in local_rcsdroad_layer.features
            if feature.geometry is not None and feature.geometry.intersects(scene_query)
        ]
        local_rcsdnode_features = [
            feature
            for feature in local_rcsdnode_layer.features
            if feature.geometry is not None and feature.geometry.intersects(scene_query)
        ]

        local_drivezone_geometries = [feature.geometry for feature in local_drivezone_features if feature.geometry is not None]
        if not local_drivezone_geometries:
            raise TextBundleError("missing_drivezone", f"mainnodeid='{normalized_mainnodeid}' local buffer has no DriveZone coverage.")
        drivezone_union = unary_union(local_drivezone_geometries)
        drivezone_mask = _rasterize_geometries(grid, [drivezone_union])
        drivezone_mask_png = _mask_png_bytes(drivezone_mask)

        drivezone_features = []
        for feature in local_drivezone_features:
            drivezone_features.append(
                _local_feature(
                    properties=dict(feature.properties),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        divstripzone_features: list[dict[str, Any]] | None = None
        if local_divstripzone_features is not None:
            divstripzone_features = []
            for feature in local_divstripzone_features:
                divstripzone_features.append(
                    _local_feature(
                        properties=dict(feature.properties),
                        geometry=feature.geometry,
                        origin_x=origin_x,
                        origin_y=origin_y,
                    )
                )

        nodes_features = []
        for feature in local_nodes_features:
            nodes_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, NODE_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        roads_features = []
        for road in filtered_roads:
            roads_features.append(
                _local_feature(
                    properties=_filter_road_properties(road.properties),
                    geometry=road.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        rcsdroad_features = []
        for feature in local_rcsdroad_features:
            rcsdroad_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, ROAD_REQUIRED_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        rcsdnode_features = []
        for feature in local_rcsdnode_features:
            rcsdnode_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, RCSDNODE_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        bundle_file_list = list(REQUIRED_BUNDLE_FILES)
        if divstripzone_features is not None:
            bundle_file_list.append("divstripzone.gpkg")

        manifest = {
            "bundle_version": TEXT_BUNDLE_VERSION,
            "bundle_mode": TEXT_BUNDLE_MODE_SINGLE,
            "mainnodeid": normalized_mainnodeid,
            "current_patch_id": current_patch_id,
            "patch_filter_mode": patch_filter_mode,
            "epsg": TARGET_CRS.to_epsg(),
            "buffer_m": buffer_m,
            "patch_size_m": patch_size_m,
            "resolution_m": resolution_m,
            "local_origin": {
                "x_epsg3857": origin_x,
                "y_epsg3857": origin_y,
            },
            "transform": {
                "type": "north_up_affine",
                "local_to_epsg3857": {
                    "x_offset": origin_x,
                    "y_offset": origin_y,
                    "x_scale": 1.0,
                    "y_scale": 1.0,
                },
                "raster": {
                    "width": grid.width,
                    "height": grid.height,
                    "resolution_m": grid.resolution_m,
                    "top_left_x_epsg3857": grid.min_x,
                    "top_left_y_epsg3857": grid.max_y,
                },
            },
            "file_list": bundle_file_list,
            "checksum": {},
            "encoder_info": {
                "archive_format": "zip",
                "compression": "deflate",
                "text_encoding": "base85",
                "line_width": TEXT_BUNDLE_LINE_WIDTH,
                "max_text_size_bytes": max_text_size_bytes,
                "local_coord_decimals": LOCAL_COORD_DECIMALS,
                "vector_format": "GeoPackage",
            },
            "feature_counts": {
                "target_group_node_count": len(group_nodes),
                "nodes": len(nodes_features),
                "roads": len(roads_features),
                "rcsdroad": len(rcsdroad_features),
                "rcsdnode": len(rcsdnode_features),
                "drivezone": len(local_drivezone_geometries),
                "divstripzone": None if divstripzone_features is None else len(divstripzone_features),
            },
            "created_at": _now_text(),
        }

        size_report: dict[str, Any] | None = None
        bundle_text = ""
        bundle_size_bytes = 0
        for _ in range(3):
            files = _prepare_bundle_files(
                drivezone_features=drivezone_features,
                divstripzone_features=divstripzone_features,
                nodes_features=nodes_features,
                roads_features=roads_features,
                rcsdroad_features=rcsdroad_features,
                rcsdnode_features=rcsdnode_features,
                drivezone_mask_png=drivezone_mask_png,
                manifest=manifest,
                size_report=size_report,
            )
            manifest["checksum"] = {
                name: hashlib.sha256(content).hexdigest()
                for name, content in files.items()
                if name != "manifest.json"
            }
            files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            payload_bytes, per_file_compressed = _zip_bytes(files)
            meta = {
                "bundle_version": TEXT_BUNDLE_VERSION,
                "bundle_mode": TEXT_BUNDLE_MODE_SINGLE,
                "mainnodeid": normalized_mainnodeid,
                "archive_format": "zip",
                "encoding": "base85",
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "created_at": _now_text(),
            }
            bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
            next_size_report = _build_size_report(
                total_text_size_bytes=bundle_size_bytes,
                payload_size_bytes=len(payload_bytes),
                per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
                per_file_compressed_size_bytes=per_file_compressed,
                limit_bytes=max_text_size_bytes,
            )
            if next_size_report == size_report:
                break
            size_report = next_size_report

        assert size_report is not None
        if bundle_size_bytes > max_text_size_bytes:
            size_report_path.write_text(
                json.dumps(size_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return TextBundleExportArtifacts(
                success=False,
                bundle_txt_path=out_txt_path,
                size_report_path=size_report_path,
                bundle_size_bytes=bundle_size_bytes,
                failure_reason="bundle_too_large",
                failure_detail=(
                    f"Bundle text size {bundle_size_bytes} exceeds limit {max_text_size_bytes}. "
                    f"See {size_report_path} for size analysis."
                ),
            )

        out_txt_path.write_text(bundle_text, encoding="utf-8")
        return TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=None,
            bundle_size_bytes=bundle_size_bytes,
        )
    except (TextBundleError, VirtualIntersectionPocError) as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def run_t02_export_text_bundle(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    divstripzone_path: Union[str, Path, None] = None,
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int, Iterable[Union[str, int]], None],
    out_txt: Union[str, Path],
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    divstripzone_layer: Optional[str] = None,
    rcsdroad_layer: Optional[str] = None,
    rcsdnode_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
    divstripzone_crs: Optional[str] = None,
    rcsdroad_crs: Optional[str] = None,
    rcsdnode_crs: Optional[str] = None,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    max_text_size_bytes: int = TEXT_BUNDLE_LIMIT_BYTES,
) -> TextBundleExportArtifacts:
    normalized_mainnodeids = _normalize_mainnodeids(mainnodeid)
    out_txt_path = Path(out_txt)
    if not normalized_mainnodeids:
        return TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=None,
            bundle_size_bytes=0,
            failure_reason="mainnodeid_not_found",
            failure_detail="mainnodeid is empty.",
        )

    if len(normalized_mainnodeids) == 1:
        return _run_t02_export_single_text_bundle(
            nodes_path=nodes_path,
            roads_path=roads_path,
            drivezone_path=drivezone_path,
            divstripzone_path=divstripzone_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            mainnodeid=normalized_mainnodeids[0],
            out_txt=out_txt,
            nodes_layer=nodes_layer,
            roads_layer=roads_layer,
            drivezone_layer=drivezone_layer,
            divstripzone_layer=divstripzone_layer,
            rcsdroad_layer=rcsdroad_layer,
            rcsdnode_layer=rcsdnode_layer,
            nodes_crs=nodes_crs,
            roads_crs=roads_crs,
            drivezone_crs=drivezone_crs,
            divstripzone_crs=divstripzone_crs,
            rcsdroad_crs=rcsdroad_crs,
            rcsdnode_crs=rcsdnode_crs,
            buffer_m=buffer_m,
            patch_size_m=patch_size_m,
            resolution_m=resolution_m,
            max_text_size_bytes=max_text_size_bytes,
        )

    out_txt_path.parent.mkdir(parents=True, exist_ok=True)
    if out_txt_path.exists():
        out_txt_path.unlink()
    size_report_path = _out_txt_size_report_path(out_txt_path)
    if size_report_path.exists():
        size_report_path.unlink()

    try:
        case_archive_files: dict[str, bytes] = {}
        for normalized_mainnodeid in normalized_mainnodeids:
            with tempfile.TemporaryDirectory() as temp_dir_text:
                temp_bundle_path = Path(temp_dir_text) / f"{normalized_mainnodeid}.txt"
                artifacts = _run_t02_export_single_text_bundle(
                    nodes_path=nodes_path,
                    roads_path=roads_path,
                    drivezone_path=drivezone_path,
                    divstripzone_path=divstripzone_path,
                    rcsdroad_path=rcsdroad_path,
                    rcsdnode_path=rcsdnode_path,
                    mainnodeid=normalized_mainnodeid,
                    out_txt=temp_bundle_path,
                    nodes_layer=nodes_layer,
                    roads_layer=roads_layer,
                    drivezone_layer=drivezone_layer,
                    divstripzone_layer=divstripzone_layer,
                    rcsdroad_layer=rcsdroad_layer,
                    rcsdnode_layer=rcsdnode_layer,
                    nodes_crs=nodes_crs,
                    roads_crs=roads_crs,
                    drivezone_crs=drivezone_crs,
                    divstripzone_crs=divstripzone_crs,
                    rcsdroad_crs=rcsdroad_crs,
                    rcsdnode_crs=rcsdnode_crs,
                    buffer_m=buffer_m,
                    patch_size_m=patch_size_m,
                    resolution_m=resolution_m,
                    max_text_size_bytes=max_text_size_bytes,
                )
                if not artifacts.success:
                    detail = artifacts.failure_detail or artifacts.failure_reason or "bundle export failed"
                    return TextBundleExportArtifacts(
                        success=False,
                        bundle_txt_path=out_txt_path,
                        size_report_path=None,
                        bundle_size_bytes=0,
                        failure_reason=artifacts.failure_reason,
                        failure_detail=f"mainnodeid='{normalized_mainnodeid}': {detail}",
                    )
                for name, content in _extract_bundle_files(temp_bundle_path).items():
                    case_archive_files[f"{normalized_mainnodeid}/{name}"] = content

        manifest = {
            "bundle_version": TEXT_BUNDLE_VERSION,
            "bundle_mode": TEXT_BUNDLE_MODE_MULTI,
            "mainnodeids": normalized_mainnodeids,
            "case_count": len(normalized_mainnodeids),
            "file_list": [],
            "checksum": {},
            "encoder_info": {
                "archive_format": "zip",
                "compression": "deflate",
                "text_encoding": "base85",
                "line_width": TEXT_BUNDLE_LINE_WIDTH,
                "max_text_size_bytes": max_text_size_bytes,
                "vector_format": "GeoPackage",
            },
            "created_at": _now_text(),
        }

        size_report: dict[str, Any] | None = None
        bundle_text = ""
        bundle_size_bytes = 0
        for _ in range(3):
            files = dict(case_archive_files)
            manifest["checksum"] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
            manifest["file_list"] = ["manifest.json", *sorted(files)]
            files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            payload_bytes, per_file_compressed = _zip_bytes(files)
            meta = {
                "bundle_version": TEXT_BUNDLE_VERSION,
                "bundle_mode": TEXT_BUNDLE_MODE_MULTI,
                "mainnodeids": normalized_mainnodeids,
                "archive_format": "zip",
                "encoding": "base85",
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "created_at": _now_text(),
            }
            bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
            next_size_report = _build_size_report(
                total_text_size_bytes=bundle_size_bytes,
                payload_size_bytes=len(payload_bytes),
                per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
                per_file_compressed_size_bytes=per_file_compressed,
                limit_bytes=max_text_size_bytes,
            )
            if next_size_report == size_report:
                break
            size_report = next_size_report

        assert size_report is not None
        if bundle_size_bytes > max_text_size_bytes:
            size_report_path.write_text(json.dumps(size_report, ensure_ascii=False, indent=2), encoding="utf-8")
            return TextBundleExportArtifacts(
                success=False,
                bundle_txt_path=out_txt_path,
                size_report_path=size_report_path,
                bundle_size_bytes=bundle_size_bytes,
                failure_reason="bundle_too_large",
                failure_detail=(
                    f"Bundle text size {bundle_size_bytes} exceeds limit {max_text_size_bytes}. "
                    f"See {size_report_path} for size analysis."
                ),
            )

        out_txt_path.write_text(bundle_text, encoding="utf-8")
        return TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=None,
            bundle_size_bytes=bundle_size_bytes,
        )
    except (TextBundleError, VirtualIntersectionPocError) as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def run_t02_decode_text_bundle(
    *,
    bundle_txt: Union[str, Path],
    out_dir: Union[str, Path, None] = None,
) -> TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    meta, payload_bytes, checksum = _parse_text_bundle(bundle_path.read_text(encoding="utf-8"))
    if str(meta.get("bundle_version")) != TEXT_BUNDLE_VERSION:
        raise TextBundleError(
            "bundle_version_mismatch",
            f"Unsupported bundle version '{meta.get('bundle_version')}'. Expected '{TEXT_BUNDLE_VERSION}'.",
        )
    bundle_mode = str(meta.get("bundle_mode") or TEXT_BUNDLE_MODE_SINGLE)
    out_dir_path = Path(out_dir) if out_dir is not None else (Path.cwd() if bundle_mode == TEXT_BUNDLE_MODE_MULTI else bundle_path.with_suffix(""))
    out_dir_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        with tempfile.TemporaryDirectory() as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            zf.extractall(temp_dir)
            manifest_path = temp_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("bundle_version") != TEXT_BUNDLE_VERSION:
                raise TextBundleError(
                    "bundle_version_mismatch",
                    f"Manifest bundle version '{manifest.get('bundle_version')}' is not supported.",
                )
            manifest_bundle_mode = str(manifest.get("bundle_mode") or TEXT_BUNDLE_MODE_SINGLE)
            checksums = manifest.get("checksum") or {}
            for name, expected_checksum in checksums.items():
                file_path = temp_dir / name
                if not file_path.is_file():
                    raise TextBundleError("bundle_missing_files", f"Bundle checksum file missing: {name}")
                actual_checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
                if actual_checksum != expected_checksum:
                    raise TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
            if manifest_bundle_mode == TEXT_BUNDLE_MODE_MULTI:
                case_ids = _normalize_mainnodeids(manifest.get("mainnodeids"))
                if not case_ids:
                    raise TextBundleError("bundle_missing_files", "Multi-case bundle manifest is missing mainnodeids.")
                for case_id in case_ids:
                    case_dir = temp_dir / case_id
                    if not case_dir.is_dir():
                        raise TextBundleError("bundle_missing_files", f"Bundle is missing case directory: {case_id}")
                    case_manifest_path = case_dir / "manifest.json"
                    if not case_manifest_path.is_file():
                        raise TextBundleError("bundle_missing_files", f"Case '{case_id}' is missing manifest.json.")
                    case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
                    case_bundle_files = _bundle_file_list_from_manifest(
                        case_manifest,
                        available_names=[path.name for path in case_dir.iterdir() if path.is_file()],
                    )
                    missing = [name for name in case_bundle_files if not (case_dir / name).is_file()]
                    if missing:
                        raise TextBundleError("bundle_missing_files", f"Case '{case_id}' is missing required files: {','.join(missing)}")

                manifest_out_path = out_dir_path / f"{bundle_path.stem}.bundle_manifest.json"
                if manifest_out_path.exists():
                    manifest_out_path.unlink()
                manifest_out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

                case_dirs: list[Path] = []
                for case_id in case_ids:
                    source_dir = temp_dir / case_id
                    target_dir = out_dir_path / case_id
                    _restore_decoded_case_dir(source_dir=source_dir, target_dir=target_dir)
                    case_dirs.append(target_dir)

                _ = checksum
                return TextBundleDecodeArtifacts(
                    success=True,
                    out_dir=out_dir_path,
                    manifest_path=manifest_out_path,
                    case_dirs=tuple(case_dirs),
                )

            names = set(zf.namelist())
            missing = [name for name in REQUIRED_BUNDLE_FILES if name not in names]
            if missing:
                raise TextBundleError("bundle_missing_files", f"Bundle is missing required files: {','.join(missing)}")
            _restore_decoded_case_dir(source_dir=temp_dir, target_dir=out_dir_path)

    _ = checksum
    return TextBundleDecodeArtifacts(
        success=True,
        out_dir=out_dir_path,
        manifest_path=out_dir_path / "manifest.json",
        case_dirs=(out_dir_path,),
    )


def run_t02_export_text_bundle_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_export_text_bundle(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        divstripzone_path=args.divstripzone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_txt=args.out_txt,
        nodes_layer=args.nodes_layer,
        roads_layer=args.roads_layer,
        drivezone_layer=args.drivezone_layer,
        divstripzone_layer=args.divstripzone_layer,
        rcsdroad_layer=args.rcsdroad_layer,
        rcsdnode_layer=args.rcsdnode_layer,
        nodes_crs=args.nodes_crs,
        roads_crs=args.roads_crs,
        drivezone_crs=args.drivezone_crs,
        divstripzone_crs=args.divstripzone_crs,
        rcsdroad_crs=args.rcsdroad_crs,
        rcsdnode_crs=args.rcsdnode_crs,
        buffer_m=args.buffer_m,
        patch_size_m=args.patch_size_m,
        resolution_m=args.resolution_m,
    )
    if not artifacts.success:
        detail = artifacts.failure_detail or artifacts.failure_reason or "bundle export failed"
        if artifacts.size_report_path is not None:
            detail = f"{detail} (size report: {artifacts.size_report_path})"
        raise ValueError(detail)
    print(f"T02 text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    return 0


def run_t02_decode_text_bundle_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_decode_text_bundle(bundle_txt=args.bundle_txt, out_dir=args.out_dir)
    print(f"T02 text bundle decoded to: {artifacts.out_dir}")
    if artifacts.case_dirs:
        print(f"case_count={len(artifacts.case_dirs)}")
    return 0
