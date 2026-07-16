from __future__ import annotations

import csv
import json
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import blake2b
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Any, Iterable

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import write_gpkg

from .schemas import PROCESS_CRS_TEXT


_SUPPRESS_FEATURE_JSON_DEPTH = 0
_JSON_WRITE_CHUNK_CHARS = 1 << 20
_READ_FEATURES_CACHE_MAX_PATHS = 24
_READ_FEATURES_SNAPSHOT_CACHE: OrderedDict[
    tuple[str, str | None],
    tuple[tuple[int, int, int], tuple[tuple[dict[str, Any], Any], ...]],
] = OrderedDict()
_READ_FEATURES_SNAPSHOT_CACHE_LOCK = RLock()
_PRESERVE_READ_FEATURES_CACHE_DEPTH = 0
_PRESERVED_READ_FEATURE_PATHS: list[set[str] | None] = []
_FEATURE_OUTPUT_STAGING_ROOTS: list[Path] = []


@contextmanager
def suppress_feature_json_outputs() -> Iterable[None]:
    global _SUPPRESS_FEATURE_JSON_DEPTH
    _SUPPRESS_FEATURE_JSON_DEPTH += 1
    try:
        yield
    finally:
        _SUPPRESS_FEATURE_JSON_DEPTH -= 1


@contextmanager
def stage_feature_outputs() -> Iterable[None]:
    """Build feature artifacts locally, then publish them to final paths."""

    with TemporaryDirectory(prefix="t06_feature_stage_") as temp_dir:
        _FEATURE_OUTPUT_STAGING_ROOTS.append(Path(temp_dir))
        try:
            yield
        finally:
            _FEATURE_OUTPUT_STAGING_ROOTS.pop()


def default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"t06_segment_fusion_precheck_{stamp}"


def prepare_run_roots(out_root: str | Path, run_id: str | None, step_dir: str) -> tuple[str, Path, Path]:
    resolved_run_id = run_id or default_run_id()
    run_root = Path(out_root) / resolved_run_id
    step_root = run_root / step_dir
    step_root.mkdir(parents=True, exist_ok=True)
    return resolved_run_id, run_root, step_root


def read_features(path: str | Path, *, crs_override: str | None = None) -> list[dict[str, Any]]:
    if _PRESERVE_READ_FEATURES_CACHE_DEPTH <= 0:
        result = read_vector_layer(path, crs_override=crs_override)
        return [
            {"properties": _normalize_property_keys(dict(item.properties)), "geometry": item.geometry}
            for item in result.features
        ]
    resolved = Path(path).absolute()
    try:
        stat = resolved.stat()
    except OSError:
        result = read_vector_layer(path, crs_override=crs_override)
        return [
            {"properties": _normalize_property_keys(dict(item.properties)), "geometry": item.geometry}
            for item in result.features
        ]
    snapshot = _read_features_snapshot(
        str(resolved),
        crs_override,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    return [
        {"properties": _copy_feature_properties(properties), "geometry": geometry}
        for properties, geometry in snapshot
    ]


def _copy_feature_properties(properties: dict[str, Any]) -> dict[str, Any]:
    if all(
        value is None or isinstance(value, (str, int, float, bool, bytes))
        for value in properties.values()
    ):
        return dict(properties)
    return deepcopy(properties)


def clear_read_features_cache(*, force: bool = False) -> None:
    if _PRESERVE_READ_FEATURES_CACHE_DEPTH > 0 and not force:
        preserved_paths = _active_preserved_read_feature_paths()
        if preserved_paths is not None:
            with _READ_FEATURES_SNAPSHOT_CACHE_LOCK:
                for key in list(_READ_FEATURES_SNAPSHOT_CACHE):
                    if key[0] not in preserved_paths:
                        _READ_FEATURES_SNAPSHOT_CACHE.pop(key, None)
        return
    with _READ_FEATURES_SNAPSHOT_CACHE_LOCK:
        _READ_FEATURES_SNAPSHOT_CACHE.clear()


def discard_read_features_cache(path: str | Path) -> None:
    resolved = str(Path(path).absolute())
    with _READ_FEATURES_SNAPSHOT_CACHE_LOCK:
        for key in list(_READ_FEATURES_SNAPSHOT_CACHE):
            if key[0] == resolved:
                _READ_FEATURES_SNAPSHOT_CACHE.pop(key, None)


def _active_preserved_read_feature_paths() -> set[str] | None:
    if any(paths is None for paths in _PRESERVED_READ_FEATURE_PATHS):
        return None
    preserved: set[str] = set()
    for paths in _PRESERVED_READ_FEATURE_PATHS:
        preserved.update(paths or set())
    return preserved


@contextmanager
def preserve_read_features_cache(paths: Iterable[str | Path] | None = None) -> Iterable[None]:
    global _PRESERVE_READ_FEATURES_CACHE_DEPTH
    preserved_paths = None if paths is None else {str(Path(path).absolute()) for path in paths}
    _PRESERVE_READ_FEATURES_CACHE_DEPTH += 1
    _PRESERVED_READ_FEATURE_PATHS.append(preserved_paths)
    try:
        yield
    finally:
        _PRESERVED_READ_FEATURE_PATHS.pop()
        _PRESERVE_READ_FEATURES_CACHE_DEPTH -= 1
        if _PRESERVE_READ_FEATURES_CACHE_DEPTH == 0:
            clear_read_features_cache(force=True)


def _read_features_cache_size() -> int:
    with _READ_FEATURES_SNAPSHOT_CACHE_LOCK:
        return len(_READ_FEATURES_SNAPSHOT_CACHE)


def _read_features_snapshot(
    path_text: str,
    crs_override: str | None,
    _size_bytes: int,
    _mtime_ns: int,
    _ctime_ns: int,
) -> tuple[tuple[dict[str, Any], Any], ...]:
    key = path_text, crs_override
    version = _size_bytes, _mtime_ns, _ctime_ns
    with _READ_FEATURES_SNAPSHOT_CACHE_LOCK:
        cached = _READ_FEATURES_SNAPSHOT_CACHE.get(key)
        if cached is not None and cached[0] == version:
            _READ_FEATURES_SNAPSHOT_CACHE.move_to_end(key)
            return cached[1]
    result = read_vector_layer(path_text, crs_override=crs_override)
    snapshot = tuple(
        (_normalize_property_keys(dict(item.properties)), item.geometry)
        for item in result.features
    )
    with _READ_FEATURES_SNAPSHOT_CACHE_LOCK:
        _READ_FEATURES_SNAPSHOT_CACHE[key] = version, snapshot
        _READ_FEATURES_SNAPSHOT_CACHE.move_to_end(key)
        while len(_READ_FEATURES_SNAPSHOT_CACHE) > _READ_FEATURES_CACHE_MAX_PATHS:
            _READ_FEATURES_SNAPSHOT_CACHE.popitem(last=False)
    return snapshot


def _normalize_property_keys(properties: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    source_keys: dict[str, str] = {}
    for raw_key, value in properties.items():
        key = str(raw_key).lower()
        if key not in normalized:
            normalized[key] = value
            source_keys[key] = str(raw_key)
            continue
        current = normalized[key]
        if current is None and value is not None:
            normalized[key] = value
            source_keys[key] = str(raw_key)
            continue
        if value is None or current == value:
            continue
        raise ValueError(
            "case-insensitive property conflict: "
            f"{source_keys[key]}={current!r} vs {raw_key}={value!r}"
        )
    return normalized


def write_feature_triplet(
    *,
    step_root: Path,
    stem: str,
    features: list[dict[str, Any]],
    fieldnames: list[str],
    write_json_output: bool = True,
    progress: Callable[[str, str, Path], None] | None = None,
) -> dict[str, Path]:
    gpkg_path = step_root / f"{stem}.gpkg"
    csv_path = step_root / f"{stem}.csv"
    json_path = step_root / f"{stem}.json"
    paths = {"gpkg": gpkg_path, "csv": csv_path}
    gpkg_features, gpkg_geometry_type = _gpkg_features_and_geometry_type(features)
    _notify_output_progress(progress, "gpkg", "start", gpkg_path)
    gpkg_write_path = _staged_output_path(gpkg_path)
    write_gpkg(gpkg_write_path, gpkg_features, empty_fields=fieldnames, geometry_type=gpkg_geometry_type)
    if gpkg_write_path != gpkg_path:
        gpkg_path.parent.mkdir(parents=True, exist_ok=True)
        copy2(gpkg_write_path, gpkg_path)
    _notify_output_progress(progress, "gpkg", "end", gpkg_path)
    from .step3_validation_publish import is_decision_only_validation_step3_run

    if is_decision_only_validation_step3_run():
        _notify_output_progress(progress, "csv", "skipped", csv_path)
    else:
        _notify_output_progress(progress, "csv", "start", csv_path)
        write_csv(csv_path, (feature.get("properties") or {} for feature in features), fieldnames)
        _notify_output_progress(progress, "csv", "end", csv_path)
    effective_write_json_output = write_json_output and _SUPPRESS_FEATURE_JSON_DEPTH <= 0
    if effective_write_json_output:
        _notify_output_progress(progress, "json", "start", json_path)
        _write_normalized_json(
            json_path,
            {
                "row_count": len(features),
                "features": [_feature_json(feature) for feature in features],
            },
        )
        _notify_output_progress(progress, "json", "end", json_path)
        paths["json"] = json_path
    else:
        _notify_output_progress(progress, "json", "skipped", json_path)
    return paths


def _staged_output_path(target_path: Path) -> Path:
    if not _FEATURE_OUTPUT_STAGING_ROOTS:
        return target_path
    digest = blake2b(str(target_path.resolve()).encode("utf-8"), digest_size=8).hexdigest()
    staged_path = _FEATURE_OUTPUT_STAGING_ROOTS[-1] / f"{digest}_{target_path.name}"
    staged_path.parent.mkdir(parents=True, exist_ok=True)
    return staged_path


def _infer_gpkg_geometry_type(features: list[dict[str, Any]]) -> str:
    geometry_types = {
        geometry_type
        for feature in features
        for geometry_type in [_feature_geometry_type(feature.get("geometry"))]
        if geometry_type
    }
    if len(geometry_types) == 1:
        return next(iter(geometry_types))
    return "Unknown"


def _gpkg_features_and_geometry_type(features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    geometry_type = _infer_gpkg_geometry_type(features)
    if geometry_type != "Unknown":
        return features, geometry_type
    geometry_types = {
        geometry_type
        for feature in features
        for geometry_type in [_feature_geometry_type(feature.get("geometry"))]
        if geometry_type
    }
    if geometry_types <= {"LineString", "MultiLineString"}:
        return [_with_gpkg_geometry(feature, _as_multiline(feature.get("geometry"))) for feature in features], "MultiLineString"
    if geometry_types <= {"Polygon", "MultiPolygon"}:
        return [_with_gpkg_geometry(feature, _as_multipolygon(feature.get("geometry"))) for feature in features], "MultiPolygon"
    return features, geometry_type


def _with_gpkg_geometry(feature: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {**feature, "geometry": geometry}


def _as_multiline(geometry: Any) -> Any:
    if isinstance(geometry, LineString):
        return MultiLineString([geometry])
    if isinstance(geometry, dict) and geometry.get("type") == "LineString":
        return mapping(MultiLineString([shape(geometry)]))
    return geometry


def _as_multipolygon(geometry: Any) -> Any:
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    if isinstance(geometry, dict) and geometry.get("type") == "Polygon":
        return mapping(MultiPolygon([shape(geometry)]))
    return geometry


def _feature_geometry_type(geometry: Any) -> str:
    if isinstance(geometry, BaseGeometry):
        return "" if geometry.is_empty else geometry.geom_type
    if isinstance(geometry, dict):
        return str(geometry.get("type") or "")
    return ""


def _notify_output_progress(progress: Callable[[str, str, Path], None] | None, fmt: str, status: str, path: Path) -> None:
    if progress is not None:
        progress(fmt, status, path)


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    out_path = Path(path)
    write_path = _staged_output_path(out_path)
    write_path.parent.mkdir(parents=True, exist_ok=True)
    with write_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _plain_value(row.get(field)) for field in fieldnames})
    if write_path != out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        copy2(write_path, out_path)


def write_json(path: str | Path, payload: Any) -> None:
    _write_normalized_json(path, _plain_value(payload))


def _write_normalized_json(path: str | Path, payload: Any) -> None:
    """Write a payload that has already been converted to JSON-native values."""
    out_path = Path(path)
    write_path = _staged_output_path(out_path)
    write_path.parent.mkdir(parents=True, exist_ok=True)
    with write_path.open("w", encoding="utf-8") as fp:
        _dump_json_buffered(fp, payload)
    if write_path != out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        copy2(write_path, out_path)


def _dump_json_buffered(fp: Any, payload: Any, *, chunk_chars: int = _JSON_WRITE_CHUNK_CHARS) -> None:
    encoder = json.JSONEncoder(ensure_ascii=False, indent=2, allow_nan=False)
    pending: list[str] = []
    pending_chars = 0
    for chunk in encoder.iterencode(payload):
        pending.append(chunk)
        pending_chars += len(chunk)
        if pending_chars >= chunk_chars:
            fp.write("".join(pending))
            pending.clear()
            pending_chars = 0
    if pending:
        fp.write("".join(pending))


def _feature_json(feature: dict[str, Any]) -> dict[str, Any]:
    geometry = feature.get("geometry")
    return {
        "properties": _plain_value(feature.get("properties") or {}),
        "geometry": mapping(geometry) if isinstance(geometry, BaseGeometry) else geometry,
        "crs": PROCESS_CRS_TEXT,
    }


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseGeometry):
        return mapping(value)
    return value
