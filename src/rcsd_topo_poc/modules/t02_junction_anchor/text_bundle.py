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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import numpy as np
from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon, Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedNode,
    VirtualIntersectionPocError,
    _build_grid,
    _load_layer_filtered,
    _parse_nodes,
    _rasterize_geometries,
    _resolve_group,
)


TEXT_BUNDLE_VERSION = "1"
TEXT_BUNDLE_LIMIT_BYTES = 300 * 1024
TEXT_BUNDLE_BEGIN = "BEGIN_T02_BUNDLE"
TEXT_BUNDLE_PAYLOAD = "PAYLOAD"
TEXT_BUNDLE_END_PAYLOAD = "END_PAYLOAD"
TEXT_BUNDLE_META = "META "
TEXT_BUNDLE_CHECKSUM = "CHECKSUM "
TEXT_BUNDLE_END = "END_T02_BUNDLE"
TEXT_BUNDLE_LINE_WIDTH = 120
LOCAL_COORD_DECIMALS = 1

NODE_FIELDS = ("id", "mainnodeid", "has_evd", "is_anchor", "kind_2", "grade_2")
ROAD_FIELDS = ("id", "direction", "snodeid", "enodeid")
RCSDNODE_FIELDS = ("id", "mainnodeid")
REQUIRED_BUNDLE_FILES = (
    "manifest.json",
    "drivezone_mask.png",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
    "size_report.json",
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
        TEXT_BUNDLE_END_PAYLOAD,
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
        "nodes.gpkg": _vector_file_bytes("nodes.gpkg", nodes_features),
        "roads.gpkg": _vector_file_bytes("roads.gpkg", roads_features),
        "rcsdroad.gpkg": _vector_file_bytes("rcsdroad.gpkg", rcsdroad_features),
        "rcsdnode.gpkg": _vector_file_bytes("rcsdnode.gpkg", rcsdnode_features),
        "manifest.json": json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
    }
    if size_report is not None:
        files["size_report.json"] = json.dumps(size_report, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return files


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes, str]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != TEXT_BUNDLE_BEGIN:
        raise TextBundleError("invalid_bundle_format", "Bundle header not found.")

    try:
        meta_line = next(line for line in lines if line.startswith(TEXT_BUNDLE_META))
        payload_start = lines.index(TEXT_BUNDLE_PAYLOAD)
        payload_end = lines.index(TEXT_BUNDLE_END_PAYLOAD)
        checksum_line = next(line for line in lines if line.startswith(TEXT_BUNDLE_CHECKSUM))
        end_line = next(line for line in lines if line.strip() == TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc

    if payload_end <= payload_start:
        raise TextBundleError("invalid_bundle_format", "Bundle payload section is malformed.")
    if lines.index(TEXT_BUNDLE_END_PAYLOAD) >= lines.index(TEXT_BUNDLE_END):
        raise TextBundleError("invalid_bundle_format", "Bundle footer order is invalid.")

    meta = json.loads(meta_line[len(TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_start + 1 : payload_end]).strip()
    if not payload_text:
        raise TextBundleError("invalid_bundle_format", "Bundle payload is empty.")
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = checksum_line[len(TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if not end_line:
        raise TextBundleError("invalid_bundle_format", "Bundle footer not found.")
    return meta, payload_bytes, checksum


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


def run_t02_export_text_bundle(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int],
    out_txt: Union[str, Path],
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    rcsdroad_layer: Optional[str] = None,
    rcsdnode_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
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
        patch_query = representative_node.geometry.buffer(buffer_m)
        grid = _build_grid(representative_node.geometry, patch_size_m=patch_size_m, resolution_m=resolution_m)
        origin_x = grid.min_x
        origin_y = grid.min_y

        local_nodes_layer = _load_layer_filtered(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
        )
        local_roads_layer = _load_layer_filtered(
            roads_path,
            layer_name=roads_layer,
            crs_override=roads_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
        )
        local_drivezone_layer = _load_layer_filtered(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
        )
        local_rcsdroad_layer = _load_layer_filtered(
            rcsdroad_path,
            layer_name=rcsdroad_layer,
            crs_override=rcsdroad_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
        )
        local_rcsdnode_layer = _load_layer_filtered(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
        )

        local_drivezone_geometries = [feature.geometry for feature in local_drivezone_layer.features if feature.geometry is not None]
        if not local_drivezone_geometries:
            raise TextBundleError("missing_drivezone", f"mainnodeid='{normalized_mainnodeid}' local buffer has no DriveZone coverage.")
        drivezone_union = unary_union(local_drivezone_geometries)
        drivezone_mask = _rasterize_geometries(grid, [drivezone_union])
        drivezone_mask_png = _mask_png_bytes(drivezone_mask)

        nodes_features = []
        for feature in local_nodes_layer.features:
            nodes_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, NODE_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        roads_features = []
        for feature in local_roads_layer.features:
            roads_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, ROAD_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        rcsdroad_features = []
        for feature in local_rcsdroad_layer.features:
            rcsdroad_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, ROAD_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        rcsdnode_features = []
        for feature in local_rcsdnode_layer.features:
            rcsdnode_features.append(
                _local_feature(
                    properties=_filter_properties(feature.properties, RCSDNODE_FIELDS),
                    geometry=feature.geometry,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            )

        manifest = {
            "bundle_version": TEXT_BUNDLE_VERSION,
            "mainnodeid": normalized_mainnodeid,
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
            "file_list": list(REQUIRED_BUNDLE_FILES),
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
            },
            "created_at": _now_text(),
        }

        size_report: dict[str, Any] | None = None
        bundle_text = ""
        bundle_size_bytes = 0
        for _ in range(3):
            files = _prepare_bundle_files(
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


def run_t02_decode_text_bundle(
    *,
    bundle_txt: Union[str, Path],
    out_dir: Union[str, Path],
) -> TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    meta, payload_bytes, checksum = _parse_text_bundle(bundle_path.read_text(encoding="utf-8"))
    if str(meta.get("bundle_version")) != TEXT_BUNDLE_VERSION:
        raise TextBundleError(
            "bundle_version_mismatch",
            f"Unsupported bundle version '{meta.get('bundle_version')}'. Expected '{TEXT_BUNDLE_VERSION}'.",
        )

    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        names = set(zf.namelist())
        missing = [name for name in REQUIRED_BUNDLE_FILES if name not in names]
        if missing:
            raise TextBundleError("bundle_missing_files", f"Bundle is missing required files: {','.join(missing)}")
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
            checksums = manifest.get("checksum") or {}
            for name, expected_checksum in checksums.items():
                file_path = temp_dir / name
                if not file_path.is_file():
                    raise TextBundleError("bundle_missing_files", f"Bundle checksum file missing: {name}")
                actual_checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
                if actual_checksum != expected_checksum:
                    raise TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
            for child in temp_dir.iterdir():
                target_path = out_dir_path / child.name
                if target_path.exists():
                    if target_path.is_dir():
                        shutil.rmtree(target_path)
                    else:
                        target_path.unlink()
                shutil.move(str(child), str(target_path))

    _ = checksum
    return TextBundleDecodeArtifacts(
        success=True,
        out_dir=out_dir_path,
        manifest_path=out_dir_path / "manifest.json",
    )


def run_t02_export_text_bundle_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_export_text_bundle(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_txt=args.out_txt,
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
    return 0
