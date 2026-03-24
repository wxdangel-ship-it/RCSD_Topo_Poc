from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import time
import tracemalloc
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, TypeVar, Union

import ijson
import numpy as np
import shapefile
from pyproj import CRS
from shapely import from_wkb, intersects_xy
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    transform_geometry_to_target,
    write_geojson,
    write_json,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv
from rcsd_topo_poc.modules.t02_junction_anchor.stage1_drivezone_gate import (
    LoadedFeature,
    LoadedLayer,
    _normalize_id,
    _read_vector_layer_strict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import _resolve_shapefile_crs_strict, _transform_geometry


T = TypeVar("T")

ALLOWED_KIND_2_VALUES = {4, 2048}
KNOWN_S_GRADE_BUCKETS = ("0-0\u53cc", "0-1\u53cc", "0-2\u53cc")
DEFAULT_PATCH_BUFFER_M = 100.0
DEFAULT_PATCH_SIZE_M = 200.0
DEFAULT_RESOLUTION_M = 0.2
ROAD_BUFFER_M = 3.5
RC_ROAD_BUFFER_M = 3.5
NODE_SEED_RADIUS_M = 6.0
RC_NODE_SEED_RADIUS_M = 2.0
MAIN_BRANCH_HALF_WIDTH_M = 10.0
SIDE_BRANCH_HALF_WIDTH_M = 7.0
MAIN_AXIS_ANGLE_TOLERANCE_DEG = 35.0
BRANCH_MATCH_TOLERANCE_DEG = 30.0
RAY_GAP_STEPS = 3
RAY_SAMPLE_STEP_MULTIPLIER = 0.5
SPATIAL_CACHE_VERSION = "v1"
POC_SPATIAL_CACHE_DIR = Path(__file__).resolve().parents[4] / "outputs" / "_work" / "t02_poc_spatial_cache"

REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"
REASON_REPRESENTATIVE_NODE_MISSING = "representative_node_missing"
REASON_MAINNODEID_NOT_FOUND = "mainnodeid_not_found"
REASON_MAINNODEID_OUT_OF_SCOPE = "mainnodeid_out_of_scope"
REASON_MAIN_DIRECTION_UNSTABLE = "main_direction_unstable"
REASON_RC_OUTSIDE_DRIVEZONE = "rc_outside_drivezone"

STATUS_STABLE = "stable"
STATUS_SURFACE_ONLY = "surface_only"
STATUS_WEAK_BRANCH_SUPPORT = "weak_branch_support"
STATUS_AMBIGUOUS_RC_MATCH = "ambiguous_rc_match"
STATUS_NO_VALID_RC_CONNECTION = "no_valid_rc_connection"

AUDIT_FIELDNAMES = [
    "scope",
    "status",
    "reason",
    "detail",
    "mainnodeid",
    "feature_id",
]
ASSOCIATION_AUDIT_FIELDNAMES = [
    "entity_type",
    "entity_id",
    "selected",
    "reason",
    "group_id",
    "branch_id",
]


class VirtualIntersectionPocError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ParsedNode:
    feature_index: int
    properties: dict[str, Any]
    geometry: Point
    node_id: str
    mainnodeid: str | None
    has_evd: str | None
    is_anchor: str | None
    kind_2: int | None
    grade_2: int | None


@dataclass(frozen=True)
class ParsedRoad:
    feature_index: int
    properties: dict[str, Any]
    geometry: BaseGeometry
    road_id: str
    snodeid: str
    enodeid: str
    direction: int


@dataclass
class BranchEvidence:
    branch_id: str
    angle_deg: float
    branch_type: str
    road_ids: list[str] = field(default_factory=list)
    rcsdroad_ids: list[str] = field(default_factory=list)
    road_support_m: float = 0.0
    drivezone_support_m: float = 0.0
    rc_support_m: float = 0.0
    has_incoming_support: bool = False
    has_outgoing_support: bool = False
    is_main_direction: bool = False
    selected_for_polygon: bool = False
    selected_rc_group: bool = False
    conflict_excluded: bool = False
    evidence_level: str = "edge_only"
    polygon_length_m: float = 0.0


@dataclass(frozen=True)
class GridSpec:
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    resolution_m: float
    width: int
    height: int
    x_centers: np.ndarray
    y_centers: np.ndarray
    xx: np.ndarray
    yy: np.ndarray

    @property
    def patch_polygon(self) -> Polygon:
        return box(self.min_x, self.min_y, self.max_x, self.max_y)

    def xy_to_rc(self, x: float, y: float) -> tuple[int, int] | None:
        if x < self.min_x or x > self.max_x or y < self.min_y or y > self.max_y:
            return None
        col = int((x - self.min_x) / self.resolution_m)
        row = int((self.max_y - y) / self.resolution_m)
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None
        return row, col


@dataclass(frozen=True)
class VirtualIntersectionArtifacts:
    success: bool
    out_root: Path
    virtual_polygon_path: Path
    branch_evidence_json_path: Path
    branch_evidence_geojson_path: Path
    associated_rcsdroad_path: Path
    associated_rcsdroad_audit_csv_path: Path
    associated_rcsdroad_audit_json_path: Path
    associated_rcsdnode_path: Path
    associated_rcsdnode_audit_csv_path: Path
    associated_rcsdnode_audit_json_path: Path
    status_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    log_path: Path
    progress_path: Path
    perf_json_path: Path
    perf_markers_path: Path


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_int(value: Any) -> int | None:
    normalized = _normalize_id(value)
    if normalized is None:
        return None
    try:
        return int(float(normalized))
    except Exception:
        return None


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _tracemalloc_stats() -> dict[str, int]:
    if not tracemalloc.is_tracing():
        return {
            "python_tracemalloc_current_bytes": 0,
            "python_tracemalloc_peak_bytes": 0,
        }
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    return {
        "python_tracemalloc_current_bytes": current_bytes,
        "python_tracemalloc_peak_bytes": peak_bytes,
    }


def _write_progress_snapshot(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    current_stage: str | None,
    message: str,
    counts: dict[str, Any],
) -> None:
    write_json(
        out_path,
        {
            "run_id": run_id,
            "status": status,
            "updated_at": _now_text(),
            "current_stage": current_stage,
            "message": message,
            "counts": counts,
            **_tracemalloc_stats(),
        },
    )


def _record_perf_marker(
    *,
    out_path: Path,
    run_id: str,
    stage: str,
    elapsed_sec: float,
    counts: dict[str, Any],
    note: str | None = None,
) -> None:
    payload = {
        "event": "stage_marker",
        "run_id": run_id,
        "at": _now_text(),
        "stage": stage,
        "elapsed_sec": round(elapsed_sec, 6),
        "counts": counts,
        **_tracemalloc_stats(),
    }
    if note is not None:
        payload["note"] = note
    _append_jsonl(out_path, payload)


def _find_repo_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or build_run_id("t02_virtual_intersection_poc")
    if out_root is not None:
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = _find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise VirtualIntersectionPocError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_virtual_intersection_poc" / resolved_run_id, resolved_run_id


def _audit_row(
    *,
    scope: str,
    status: str,
    reason: str,
    detail: str,
    mainnodeid: str | None = None,
    feature_id: str | None = None,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "status": status,
        "reason": reason,
        "detail": detail,
        "mainnodeid": mainnodeid,
        "feature_id": feature_id,
    }


def _association_audit_row(
    *,
    entity_type: str,
    entity_id: str,
    selected: bool,
    reason: str,
    group_id: str | None,
    branch_id: str | None,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "selected": "yes" if selected else "no",
        "reason": reason,
        "group_id": group_id,
        "branch_id": branch_id,
    }


def _load_layer(
    path: Union[str, Path],
    *,
    layer_name: Optional[str],
    crs_override: Optional[str],
    allow_null_geometry: bool,
) -> LoadedLayer:
    try:
        return _read_vector_layer_strict(
            path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=allow_null_geometry,
        )
    except Exception as exc:
        if hasattr(exc, "reason") and hasattr(exc, "detail"):
            raise VirtualIntersectionPocError(getattr(exc, "reason"), getattr(exc, "detail")) from exc
        raise VirtualIntersectionPocError(REASON_INVALID_CRS_OR_UNPROJECTABLE, str(exc)) from exc


def _resolve_geojson_crs_streaming(path: Path, crs_override: Optional[str]) -> tuple[CRS, str]:
    if crs_override:
        try:
            return CRS.from_user_input(crs_override), "override"
        except Exception as exc:
            raise VirtualIntersectionPocError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Invalid CRS override '{crs_override}': {exc}",
            ) from exc

    try:
        with path.open("rb") as fp:
            for prefix, event, value in ijson.parse(fp):
                if prefix == "crs.properties.name" and event in {"string", "number"}:
                    try:
                        return CRS.from_user_input(str(value)), "geojson.crs"
                    except Exception as exc:
                        raise VirtualIntersectionPocError(
                            REASON_INVALID_CRS_OR_UNPROJECTABLE,
                            f"Invalid GeoJSON CRS '{value}' in '{path}': {exc}",
                        ) from exc
                if prefix == "features" and event == "start_array":
                    break
    except VirtualIntersectionPocError:
        raise
    except Exception as exc:
        raise VirtualIntersectionPocError(
            REASON_INVALID_CRS_OR_UNPROJECTABLE,
            f"Failed to read GeoJSON CRS from '{path}': {exc}",
        ) from exc

    raise VirtualIntersectionPocError(
        REASON_INVALID_CRS_OR_UNPROJECTABLE,
        f"GeoJSON '{path}' is missing CRS metadata and no CRS override was provided.",
    )


def _iter_geojson_feature_items(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    try:
        with path.open("rb") as fp:
            for feature_index, feature in enumerate(ijson.items(fp, "features.item")):
                yield feature_index, feature
    except Exception as exc:
        raise VirtualIntersectionPocError(
            REASON_INVALID_CRS_OR_UNPROJECTABLE,
            f"Failed to stream GeoJSON features from '{path}': {exc}",
        ) from exc


def _bounds_intersect(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    left_min_x, left_min_y, left_max_x, left_max_y = left
    right_min_x, right_min_y, right_max_x, right_max_y = right
    return not (
        left_max_x < right_min_x
        or left_min_x > right_max_x
        or left_max_y < right_min_y
        or left_min_y > right_max_y
    )


def _update_bounds_from_coordinates(
    coordinates: Any,
    current_bounds: list[float] | None = None,
) -> list[float] | None:
    if coordinates is None:
        return current_bounds
    if isinstance(coordinates, (list, tuple)):
        if len(coordinates) >= 2 and isinstance(coordinates[0], Real) and isinstance(coordinates[1], Real):
            x = float(coordinates[0])
            y = float(coordinates[1])
            if current_bounds is None:
                return [x, y, x, y]
            current_bounds[0] = min(current_bounds[0], x)
            current_bounds[1] = min(current_bounds[1], y)
            current_bounds[2] = max(current_bounds[2], x)
            current_bounds[3] = max(current_bounds[3], y)
            return current_bounds
        for item in coordinates:
            current_bounds = _update_bounds_from_coordinates(item, current_bounds)
    return current_bounds


def _geometry_payload_bounds(geometry_payload: dict[str, Any] | None) -> tuple[float, float, float, float] | None:
    if not isinstance(geometry_payload, dict):
        return None
    bounds = _update_bounds_from_coordinates(geometry_payload.get("coordinates"))
    if bounds is None and geometry_payload.get("type") == "GeometryCollection":
        for item in geometry_payload.get("geometries") or []:
            item_bounds = _geometry_payload_bounds(item)
            if item_bounds is None:
                continue
            if bounds is None:
                bounds = list(item_bounds)
            else:
                bounds[0] = min(bounds[0], item_bounds[0])
                bounds[1] = min(bounds[1], item_bounds[1])
                bounds[2] = max(bounds[2], item_bounds[2])
                bounds[3] = max(bounds[3], item_bounds[3])
    if bounds is None:
        return None
    return (bounds[0], bounds[1], bounds[2], bounds[3])


def _spatial_cache_path_for(layer_path: Path, *, crs_override: str | None) -> Path:
    cache_key = f"{layer_path.resolve()}|{crs_override or ''}|{SPATIAL_CACHE_VERSION}"
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:16]
    filename = f"{layer_path.stem}_{digest}.sqlite"
    return POC_SPATIAL_CACHE_DIR / filename


def _spatial_cache_signature(layer_path: Path, *, crs_override: str | None) -> dict[str, str]:
    stat = layer_path.stat()
    return {
        "version": SPATIAL_CACHE_VERSION,
        "source_path": str(layer_path.resolve()),
        "source_size": str(stat.st_size),
        "source_mtime_ns": str(stat.st_mtime_ns),
        "crs_override": crs_override or "",
    }


def _read_spatial_cache_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows}


def _spatial_cache_is_valid(cache_path: Path, *, layer_path: Path, crs_override: str | None) -> bool:
    if not cache_path.is_file():
        return False
    try:
        conn = sqlite3.connect(str(cache_path))
        try:
            meta = _read_spatial_cache_meta(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return meta == _spatial_cache_signature(layer_path, crs_override=crs_override)


def _create_spatial_cache_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE features (
            fid INTEGER PRIMARY KEY,
            feature_index INTEGER NOT NULL,
            properties_json TEXT NOT NULL,
            geometry_wkb BLOB NOT NULL
        )
        """
    )
    conn.execute("CREATE VIRTUAL TABLE spatial_index USING rtree(fid, minx, maxx, miny, maxy)")


def _write_spatial_cache_meta(conn: sqlite3.Connection, *, layer_path: Path, crs_override: str | None) -> None:
    meta = _spatial_cache_signature(layer_path, crs_override=crs_override)
    conn.executemany(
        "INSERT INTO meta(key, value) VALUES(?, ?)",
        [(key, value) for key, value in meta.items()],
    )


def _build_spatial_cache(
    layer_path: Path,
    *,
    layer_name: str | None,
    crs_override: str | None,
    allow_null_geometry: bool,
    progress_label: str | None,
    progress_every: int,
    progress_callback: Callable[[str, int, int], None] | None,
) -> Path:
    cache_path = _spatial_cache_path_for(layer_path, crs_override=crs_override)
    temp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if temp_path.exists():
        temp_path.unlink()

    def _report(scanned_count: int, indexed_count: int) -> None:
        if progress_label and progress_callback:
            progress_callback(f"{progress_label}_cache_build", scanned_count, indexed_count)

    try:
        conn = sqlite3.connect(str(temp_path))
        try:
            _create_spatial_cache_schema(conn)
            indexed_count = 0
            scanned_count = 0

            suffix = layer_path.suffix.lower()
            if suffix in {".geojson", ".json"}:
                source_crs, _crs_source = _resolve_geojson_crs_streaming(layer_path, crs_override)
                for feature_index, feature in _iter_geojson_feature_items(layer_path):
                    scanned_count = feature_index + 1
                    if scanned_count % progress_every == 0:
                        _report(scanned_count, indexed_count)
                    geometry_payload = feature.get("geometry")
                    if geometry_payload is None:
                        if not allow_null_geometry:
                            raise VirtualIntersectionPocError(
                                REASON_MISSING_REQUIRED_FIELD,
                                f"{layer_path} feature[{feature_index}] is missing geometry.",
                            )
                        continue
                    geometry = _transform_geometry(
                        shape(geometry_payload),
                        source_crs=source_crs,
                        layer_label=str(layer_path),
                        feature_index=feature_index,
                        error_cls=VirtualIntersectionPocError,
                    )
                    if geometry.is_empty:
                        continue
                    properties = dict(feature.get("properties") or {})
                    min_x, min_y, max_x, max_y = geometry.bounds
                    fid = feature_index
                    conn.execute(
                        "INSERT INTO features(fid, feature_index, properties_json, geometry_wkb) VALUES(?, ?, ?, ?)",
                        (
                            fid,
                            feature_index,
                            json.dumps(properties, ensure_ascii=False, separators=(",", ":")),
                            sqlite3.Binary(geometry.wkb),
                        ),
                    )
                    conn.execute(
                        "INSERT INTO spatial_index(fid, minx, maxx, miny, maxy) VALUES(?, ?, ?, ?, ?)",
                        (fid, min_x, max_x, min_y, max_y),
                    )
                    indexed_count += 1
            elif suffix == ".shp":
                source_crs, _crs_source = _resolve_shapefile_crs_strict(
                    layer_path,
                    crs_override,
                    error_cls=VirtualIntersectionPocError,
                )
                reader = shapefile.Reader(str(layer_path))
                field_names = [field[0] for field in reader.fields[1:]]
                for feature_index, shape_record in enumerate(reader.iterShapeRecords()):
                    scanned_count = feature_index + 1
                    if scanned_count % progress_every == 0:
                        _report(scanned_count, indexed_count)
                    geometry_payload = shape_record.shape.__geo_interface__
                    geometry = _transform_geometry(
                        shape(geometry_payload),
                        source_crs=source_crs,
                        layer_label=str(layer_path),
                        feature_index=feature_index,
                        error_cls=VirtualIntersectionPocError,
                    )
                    if geometry.is_empty:
                        continue
                    properties = dict(zip(field_names, list(shape_record.record)))
                    min_x, min_y, max_x, max_y = geometry.bounds
                    fid = feature_index
                    conn.execute(
                        "INSERT INTO features(fid, feature_index, properties_json, geometry_wkb) VALUES(?, ?, ?, ?)",
                        (
                            fid,
                            feature_index,
                            json.dumps(properties, ensure_ascii=False, separators=(",", ":")),
                            sqlite3.Binary(geometry.wkb),
                        ),
                    )
                    conn.execute(
                        "INSERT INTO spatial_index(fid, minx, maxx, miny, maxy) VALUES(?, ?, ?, ?, ?)",
                        (fid, min_x, max_x, min_y, max_y),
                    )
                    indexed_count += 1
            else:
                raise VirtualIntersectionPocError(
                    REASON_INVALID_CRS_OR_UNPROJECTABLE,
                    f"Spatial cache is not supported for '{layer_path.suffix}' inputs.",
                )

            _report(scanned_count, indexed_count)
            _write_spatial_cache_meta(conn, layer_path=layer_path, crs_override=crs_override)
            conn.commit()
        finally:
            conn.close()
        temp_path.replace(cache_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return cache_path


def _load_layer_filtered_from_spatial_cache(
    layer_path: Path,
    *,
    layer_name: str | None,
    crs_override: str | None,
    allow_null_geometry: bool,
    query_geometry: BaseGeometry,
    property_predicate: Callable[[dict[str, Any]], bool] | None,
    progress_label: str | None,
    progress_every: int,
    progress_callback: Callable[[str, int, int], None] | None,
) -> LoadedLayer:
    cache_path = _spatial_cache_path_for(layer_path, crs_override=crs_override)
    if not _spatial_cache_is_valid(cache_path, layer_path=layer_path, crs_override=crs_override):
        cache_path = _build_spatial_cache(
            layer_path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=allow_null_geometry,
            progress_label=progress_label,
            progress_every=progress_every,
            progress_callback=progress_callback,
        )

    query_min_x, query_min_y, query_max_x, query_max_y = (float(v) for v in query_geometry.bounds)
    try:
        conn = sqlite3.connect(str(cache_path))
        rows = conn.execute(
            """
            SELECT f.feature_index, f.properties_json, f.geometry_wkb
            FROM spatial_index idx
            JOIN features f ON f.fid = idx.fid
            WHERE idx.maxx >= ? AND idx.minx <= ? AND idx.maxy >= ? AND idx.miny <= ?
            ORDER BY f.feature_index
            """,
            (query_min_x, query_max_x, query_min_y, query_max_y),
        )
        features: list[LoadedFeature] = []
        scanned_count = 0
        matched_count = 0
        for feature_index, properties_json, geometry_wkb in rows:
            scanned_count += 1
            if progress_label and progress_callback and scanned_count % progress_every == 0:
                progress_callback(f"{progress_label}_cache_query", scanned_count, matched_count)
            properties = dict(json.loads(properties_json))
            if property_predicate is not None and not property_predicate(properties):
                continue
            geometry = from_wkb(bytes(geometry_wkb))
            if not geometry.intersects(query_geometry):
                continue
            features.append(LoadedFeature(feature_index=int(feature_index), properties=properties, geometry=geometry))
            matched_count += 1
        if progress_label and progress_callback:
            progress_callback(f"{progress_label}_cache_query", scanned_count, matched_count)
    except sqlite3.Error as exc:
        raise VirtualIntersectionPocError(
            REASON_INVALID_CRS_OR_UNPROJECTABLE,
            f"Failed to query spatial cache for '{layer_path}': {exc}",
        ) from exc
    finally:
        if 'conn' in locals():
            conn.close()

    return LoadedLayer(features=features, source_crs=TARGET_CRS, crs_source="spatial_cache_target_crs")


def _load_layer_filtered(
    path: Union[str, Path],
    *,
    layer_name: Optional[str],
    crs_override: Optional[str],
    allow_null_geometry: bool,
    query_geometry: BaseGeometry | None = None,
    property_predicate: Callable[[dict[str, Any]], bool] | None = None,
    progress_label: str | None = None,
    progress_every: int = 5000,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> LoadedLayer:
    layer_path = Path(path)
    if not layer_path.is_file():
        raise VirtualIntersectionPocError(REASON_MISSING_REQUIRED_FIELD, f"Input layer does not exist: {layer_path}")

    suffix = layer_path.suffix.lower()
    if query_geometry is not None and suffix in {".geojson", ".json", ".shp"}:
        return _load_layer_filtered_from_spatial_cache(
            layer_path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=allow_null_geometry,
            query_geometry=query_geometry,
            property_predicate=property_predicate,
            progress_label=progress_label,
            progress_every=progress_every,
            progress_callback=progress_callback,
        )

    if suffix in {".geojson", ".json"}:
        source_crs, crs_source = _resolve_geojson_crs_streaming(layer_path, crs_override)
        source_query_bounds: tuple[float, float, float, float] | None = None
        if query_geometry is not None:
            source_query_geometry = transform_geometry_to_target(query_geometry, TARGET_CRS, source_crs)
            source_query_bounds = tuple(float(v) for v in source_query_geometry.bounds)
        features: list[LoadedFeature] = []
        matched_count = 0
        scanned_count = 0
        for feature_index, feature in _iter_geojson_feature_items(layer_path):
            scanned_count = feature_index + 1
            properties = dict(feature.get("properties") or {})
            if progress_label and progress_callback and scanned_count % progress_every == 0:
                progress_callback(progress_label, scanned_count, matched_count)
            if property_predicate is not None and not property_predicate(properties):
                continue
            geometry_payload = feature.get("geometry")
            if geometry_payload is None:
                if not allow_null_geometry:
                    raise VirtualIntersectionPocError(
                        REASON_MISSING_REQUIRED_FIELD,
                        f"{layer_path} feature[{feature_index}] is missing geometry.",
                    )
                geometry = None
            else:
                if source_query_bounds is not None:
                    raw_bounds = _geometry_payload_bounds(geometry_payload)
                    if raw_bounds is not None and not _bounds_intersect(raw_bounds, source_query_bounds):
                        continue
                geometry = _transform_geometry(
                    shape(geometry_payload),
                    source_crs=source_crs,
                    layer_label=str(layer_path),
                    feature_index=feature_index,
                    error_cls=VirtualIntersectionPocError,
                )
            if query_geometry is not None and geometry is not None and not geometry.intersects(query_geometry):
                continue
            features.append(LoadedFeature(feature_index=feature_index, properties=properties, geometry=geometry))
            matched_count += 1
        if progress_label and progress_callback:
            progress_callback(progress_label, scanned_count, matched_count)
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix == ".shp":
        source_crs, crs_source = _resolve_shapefile_crs_strict(
            layer_path,
            crs_override,
            error_cls=VirtualIntersectionPocError,
        )
        source_query_bounds: tuple[float, float, float, float] | None = None
        if query_geometry is not None:
            source_query_geometry = transform_geometry_to_target(query_geometry, TARGET_CRS, source_crs)
            source_query_bounds = tuple(float(v) for v in source_query_geometry.bounds)
        try:
            reader = shapefile.Reader(str(layer_path))
        except Exception as exc:
            raise VirtualIntersectionPocError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Failed to read shapefile '{layer_path}': {exc}",
            ) from exc

        field_names = [field[0] for field in reader.fields[1:]]
        features: list[LoadedFeature] = []
        matched_count = 0
        scanned_count = 0
        for feature_index, shape_record in enumerate(reader.iterShapeRecords()):
            scanned_count = feature_index + 1
            properties = dict(zip(field_names, list(shape_record.record)))
            if progress_label and progress_callback and scanned_count % progress_every == 0:
                progress_callback(progress_label, scanned_count, matched_count)
            if property_predicate is not None and not property_predicate(properties):
                continue
            if source_query_bounds is not None:
                raw_bounds = tuple(float(value) for value in shape_record.shape.bbox)
                if len(raw_bounds) == 4 and not _bounds_intersect(raw_bounds, source_query_bounds):
                    continue
            geometry_payload = shape_record.shape.__geo_interface__
            geometry = _transform_geometry(
                shape(geometry_payload),
                source_crs=source_crs,
                layer_label=str(layer_path),
                feature_index=feature_index,
                error_cls=VirtualIntersectionPocError,
            )
            if query_geometry is not None and not geometry.intersects(query_geometry):
                continue
            features.append(LoadedFeature(feature_index=feature_index, properties=properties, geometry=geometry))
            matched_count += 1
        if progress_label and progress_callback:
            progress_callback(progress_label, scanned_count, matched_count)
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    return _load_layer(
        path,
        layer_name=layer_name,
        crs_override=crs_override,
        allow_null_geometry=allow_null_geometry,
    )


def _linearize(geometry: BaseGeometry) -> LineString:
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        if isinstance(merged, MultiLineString):
            return max(merged.geoms, key=lambda item: item.length)
    raise VirtualIntersectionPocError(
        REASON_MISSING_REQUIRED_FIELD,
        f"Unsupported road geometry type for POC: {geometry.geom_type}",
    )


def _parse_nodes(layer: LoadedLayer, *, require_anchor_fields: bool) -> list[ParsedNode]:
    parsed: list[ParsedNode] = []
    for feature in layer.features:
        props = feature.properties
        missing_fields = []
        for field_name in ("id", "mainnodeid", "kind_2", "grade_2"):
            if field_name not in props:
                missing_fields.append(field_name)
        if require_anchor_fields:
            for field_name in ("has_evd", "is_anchor"):
                if field_name not in props:
                    missing_fields.append(field_name)
        if missing_fields:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"node feature[{feature.feature_index}] missing required fields: {','.join(missing_fields)}",
            )
        if feature.geometry is None or feature.geometry.is_empty:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"node feature[{feature.feature_index}] has empty geometry.",
            )
        centroid = feature.geometry.centroid
        parsed.append(
            ParsedNode(
                feature_index=feature.feature_index,
                properties=props,
                geometry=Point(float(centroid.x), float(centroid.y)),
                node_id=_normalize_id(props.get("id")) or "",
                mainnodeid=_normalize_id(props.get("mainnodeid")),
                has_evd=_normalize_id(props.get("has_evd")),
                is_anchor=_normalize_id(props.get("is_anchor")),
                kind_2=_coerce_int(props.get("kind_2")),
                grade_2=_coerce_int(props.get("grade_2")),
            )
        )
    return parsed


def _parse_rc_nodes(layer: LoadedLayer) -> list[ParsedNode]:
    parsed: list[ParsedNode] = []
    for feature in layer.features:
        props = feature.properties
        missing_fields = []
        for field_name in ("id", "mainnodeid"):
            if field_name not in props:
                missing_fields.append(field_name)
        if missing_fields:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"RCSDNode feature[{feature.feature_index}] missing required fields: {','.join(missing_fields)}",
            )
        if feature.geometry is None or feature.geometry.is_empty:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"RCSDNode feature[{feature.feature_index}] has empty geometry.",
            )
        centroid = feature.geometry.centroid
        parsed.append(
            ParsedNode(
                feature_index=feature.feature_index,
                properties=props,
                geometry=Point(float(centroid.x), float(centroid.y)),
                node_id=_normalize_id(props.get("id")) or "",
                mainnodeid=_normalize_id(props.get("mainnodeid")),
                has_evd=None,
                is_anchor=None,
                kind_2=None,
                grade_2=None,
            )
        )
    return parsed


def _parse_roads(layer: LoadedLayer, *, label: str) -> list[ParsedRoad]:
    parsed: list[ParsedRoad] = []
    for feature in layer.features:
        props = feature.properties
        missing_fields = []
        for field_name in ("id", "snodeid", "enodeid", "direction"):
            if field_name not in props:
                missing_fields.append(field_name)
        road_id = _normalize_id(props.get("id"))
        snodeid = _normalize_id(props.get("snodeid"))
        enodeid = _normalize_id(props.get("enodeid"))
        direction = _coerce_int(props.get("direction"))
        if road_id is None:
            missing_fields.append("id_value")
        if snodeid is None:
            missing_fields.append("snodeid_value")
        if enodeid is None:
            missing_fields.append("enodeid_value")
        if direction is None:
            missing_fields.append("direction_value")
        if feature.geometry is None or feature.geometry.is_empty:
            missing_fields.append("geometry")
        if missing_fields:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"{label} feature[{feature.feature_index}] missing required fields: {','.join(missing_fields)}",
            )
        parsed.append(
            ParsedRoad(
                feature_index=feature.feature_index,
                properties=props,
                geometry=feature.geometry,
                road_id=road_id or "",
                snodeid=snodeid or "",
                enodeid=enodeid or "",
                direction=direction or 0,
            )
        )
    return parsed


def _road_flow_flags_for_group(road: ParsedRoad, member_node_ids: set[str]) -> tuple[bool, bool]:
    touches_snode = road.snodeid in member_node_ids
    touches_enode = road.enodeid in member_node_ids
    if not touches_snode and not touches_enode:
        return False, False

    if road.direction in {0, 1}:
        return True, True
    if touches_snode and touches_enode:
        return True, True
    if road.direction == 2:
        return touches_enode, touches_snode
    if road.direction == 3:
        return touches_snode, touches_enode
    return False, False


def _resolve_group(
    *,
    mainnodeid: str,
    nodes: list[ParsedNode],
) -> tuple[ParsedNode, list[ParsedNode]]:
    group_nodes = [node for node in nodes if node.mainnodeid == mainnodeid]
    if group_nodes:
        representatives = [node for node in group_nodes if node.node_id == mainnodeid]
        if not representatives:
            raise VirtualIntersectionPocError(
                REASON_REPRESENTATIVE_NODE_MISSING,
                f"mainnodeid='{mainnodeid}' matched a group but no representative node with id == mainnodeid exists.",
            )
        return representatives[0], group_nodes

    singleton = [node for node in nodes if node.mainnodeid is None and node.node_id == mainnodeid]
    if singleton:
        return singleton[0], [singleton[0]]

    raise VirtualIntersectionPocError(
        REASON_MAINNODEID_NOT_FOUND,
        f"mainnodeid='{mainnodeid}' matched neither a mainnodeid group nor singleton fallback node.",
    )


def _query_local_features(items: list[T], query_geometry: BaseGeometry, geometry_getter: Callable[[T], BaseGeometry]) -> list[T]:
    return [item for item in items if geometry_getter(item).intersects(query_geometry)]


def _build_grid(center: Point, *, patch_size_m: float, resolution_m: float) -> GridSpec:
    half_size = patch_size_m / 2.0
    min_x = float(center.x) - half_size
    max_x = float(center.x) + half_size
    min_y = float(center.y) - half_size
    max_y = float(center.y) + half_size
    width = int(round(patch_size_m / resolution_m))
    height = int(round(patch_size_m / resolution_m))
    x_centers = min_x + resolution_m * (0.5 + np.arange(width))
    y_centers = max_y - resolution_m * (0.5 + np.arange(height))
    xx, yy = np.meshgrid(x_centers, y_centers)
    return GridSpec(
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        resolution_m=resolution_m,
        width=width,
        height=height,
        x_centers=x_centers,
        y_centers=y_centers,
        xx=xx,
        yy=yy,
    )


def _rasterize_geometries(grid: GridSpec, geometries: Iterable[BaseGeometry]) -> np.ndarray:
    mask = np.zeros((grid.height, grid.width), dtype=bool)
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        clipped = geometry.intersection(grid.patch_polygon)
        if clipped.is_empty:
            continue
        mask |= intersects_xy(clipped, grid.xx, grid.yy)
    return mask


def _binary_dilation(mask: np.ndarray, *, iterations: int) -> np.ndarray:
    result = mask.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1, mode="constant", constant_values=False)
        neighborhoods = []
        for row_offset in (-1, 0, 1):
            for col_offset in (-1, 0, 1):
                neighborhoods.append(
                    padded[
                        1 + row_offset : 1 + row_offset + result.shape[0],
                        1 + col_offset : 1 + col_offset + result.shape[1],
                    ]
                )
        result = np.logical_or.reduce(neighborhoods)
    return result


def _binary_erosion(mask: np.ndarray, *, iterations: int) -> np.ndarray:
    result = mask.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1, mode="constant", constant_values=False)
        neighborhoods = []
        for row_offset in (-1, 0, 1):
            for col_offset in (-1, 0, 1):
                neighborhoods.append(
                    padded[
                        1 + row_offset : 1 + row_offset + result.shape[0],
                        1 + col_offset : 1 + col_offset + result.shape[1],
                    ]
                )
        result = np.logical_and.reduce(neighborhoods)
    return result


def _binary_open(mask: np.ndarray, *, iterations: int) -> np.ndarray:
    return _binary_dilation(_binary_erosion(mask, iterations=iterations), iterations=iterations)


def _binary_close(mask: np.ndarray, *, iterations: int) -> np.ndarray:
    return _binary_erosion(_binary_dilation(mask, iterations=iterations), iterations=iterations)


def _extract_seed_component(mask: np.ndarray, seed_mask: np.ndarray) -> np.ndarray:
    starts = np.argwhere(mask & seed_mask)
    if starts.size == 0:
        return np.zeros_like(mask, dtype=bool)

    visited = np.zeros_like(mask, dtype=bool)
    queue: deque[tuple[int, int]] = deque((int(row), int(col)) for row, col in starts)
    for row, col in queue:
        visited[row, col] = True

    while queue:
        row, col = queue.popleft()
        for row_delta, col_delta in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            next_row = row + row_delta
            next_col = col + col_delta
            if next_row < 0 or next_row >= mask.shape[0] or next_col < 0 or next_col >= mask.shape[1]:
                continue
            if visited[next_row, next_col] or not mask[next_row, next_col]:
                continue
            visited[next_row, next_col] = True
            queue.append((next_row, next_col))
    return visited


def _mask_to_geometry(mask: np.ndarray, grid: GridSpec) -> BaseGeometry:
    polygons: list[Polygon] = []
    resolution_m = grid.resolution_m
    for row_index in range(mask.shape[0]):
        true_cols = np.flatnonzero(mask[row_index])
        if true_cols.size == 0:
            continue
        run_start = int(true_cols[0])
        run_end = int(true_cols[0])
        for current_col in true_cols[1:]:
            current_col = int(current_col)
            if current_col == run_end + 1:
                run_end = current_col
                continue
            x0 = grid.min_x + run_start * resolution_m
            x1 = grid.min_x + (run_end + 1) * resolution_m
            y1 = grid.max_y - row_index * resolution_m
            y0 = y1 - resolution_m
            polygons.append(box(x0, y0, x1, y1))
            run_start = current_col
            run_end = current_col
        x0 = grid.min_x + run_start * resolution_m
        x1 = grid.min_x + (run_end + 1) * resolution_m
        y1 = grid.max_y - row_index * resolution_m
        y0 = y1 - resolution_m
        polygons.append(box(x0, y0, x1, y1))

    if not polygons:
        return GeometryCollection()
    merged = unary_union(polygons)
    if isinstance(merged, (Polygon, MultiPolygon)):
        return merged
    return merged.buffer(0)


def _vector_to_angle_deg(vector: tuple[float, float]) -> float:
    return (math.degrees(math.atan2(vector[1], vector[0])) + 360.0) % 360.0


def _normalize_vector(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length == 0.0:
        raise VirtualIntersectionPocError(REASON_MAIN_DIRECTION_UNSTABLE, "Encountered zero-length branch direction.")
    return (vector[0] / length, vector[1] / length)


def _angle_diff_deg(first: float, second: float) -> float:
    raw = abs(first - second) % 360.0
    return min(raw, 360.0 - raw)


def _branch_candidate_from_road(
    road: ParsedRoad,
    *,
    member_node_ids: set[str],
    drivezone_union: BaseGeometry,
) -> dict[str, Any] | None:
    touches_snode = road.snodeid in member_node_ids
    touches_enode = road.enodeid in member_node_ids
    if not touches_snode and not touches_enode:
        return None

    line = _linearize(road.geometry)
    coords = list(line.coords)
    if len(coords) < 2:
        return None

    if touches_snode and not touches_enode:
        anchor = coords[0]
        away = coords[1]
    elif touches_enode and not touches_snode:
        anchor = coords[-1]
        away = coords[-2]
    else:
        start = coords[0]
        end = coords[-1]
        if Point(start).distance(Point(end)) == 0.0:
            return None
        if Point(start).distance(Point(coords[len(coords) // 2])) >= Point(end).distance(Point(coords[len(coords) // 2])):
            anchor = start
            away = coords[1]
        else:
            anchor = end
            away = coords[-2]

    vector = (away[0] - anchor[0], away[1] - anchor[1])
    if math.hypot(vector[0], vector[1]) == 0.0:
        return None

    incoming, outgoing = _road_flow_flags_for_group(road, member_node_ids)
    return {
        "road_id": road.road_id,
        "angle_deg": _vector_to_angle_deg(_normalize_vector(vector)),
        "vector": _normalize_vector(vector),
        "road_support_m": float(road.geometry.intersection(drivezone_union).length),
        "has_incoming_support": incoming,
        "has_outgoing_support": outgoing,
        "geometry": road.geometry,
    }


def _cluster_branch_candidates(
    candidates: list[dict[str, Any]],
    *,
    branch_type: str,
    angle_tolerance_deg: float,
) -> list[BranchEvidence]:
    clusters: list[dict[str, Any]] = []
    for candidate in candidates:
        assigned = False
        for cluster in clusters:
            if _angle_diff_deg(cluster["angle_deg"], candidate["angle_deg"]) <= angle_tolerance_deg:
                cluster["vectors"].append(candidate["vector"])
                cluster["road_ids"].append(candidate["road_id"])
                cluster["road_support_m"] += candidate["road_support_m"]
                cluster["has_incoming_support"] = cluster["has_incoming_support"] or candidate["has_incoming_support"]
                cluster["has_outgoing_support"] = cluster["has_outgoing_support"] or candidate["has_outgoing_support"]
                weighted_x = sum(vector[0] for vector in cluster["vectors"])
                weighted_y = sum(vector[1] for vector in cluster["vectors"])
                cluster["angle_deg"] = _vector_to_angle_deg(_normalize_vector((weighted_x, weighted_y)))
                assigned = True
                break
        if assigned:
            continue
        clusters.append(
            {
                "angle_deg": candidate["angle_deg"],
                "vectors": [candidate["vector"]],
                "road_ids": [candidate["road_id"]],
                "road_support_m": candidate["road_support_m"],
                "has_incoming_support": candidate["has_incoming_support"],
                "has_outgoing_support": candidate["has_outgoing_support"],
            }
        )

    evidences: list[BranchEvidence] = []
    for index, cluster in enumerate(clusters, start=1):
        evidences.append(
            BranchEvidence(
                branch_id=f"{branch_type}_{index}",
                angle_deg=cluster["angle_deg"],
                branch_type=branch_type,
                road_ids=sorted(set(cluster["road_ids"])),
                road_support_m=round(cluster["road_support_m"], 3),
                has_incoming_support=cluster["has_incoming_support"],
                has_outgoing_support=cluster["has_outgoing_support"],
            )
        )
    return evidences


def _ray_support_m(
    *,
    mask: np.ndarray,
    grid: GridSpec,
    center: Point,
    angle_deg: float,
    max_length_m: float,
) -> float:
    radians = math.radians(angle_deg)
    direction = (math.cos(radians), math.sin(radians))
    step_m = max(grid.resolution_m * RAY_SAMPLE_STEP_MULTIPLIER, 0.1)
    last_positive = 0.0
    seen_positive = False
    gap_steps = 0

    distance_m = step_m
    while distance_m <= max_length_m:
        x = float(center.x) + direction[0] * distance_m
        y = float(center.y) + direction[1] * distance_m
        rc = grid.xy_to_rc(x, y)
        if rc is None:
            break
        row, col = rc
        if mask[row, col]:
            last_positive = distance_m
            seen_positive = True
            gap_steps = 0
        elif seen_positive:
            gap_steps += 1
            if gap_steps > RAY_GAP_STEPS:
                break
        distance_m += step_m

    return round(last_positive, 3)


def _classify_branch_evidence(branch: BranchEvidence) -> str:
    if branch.rc_support_m >= 18.0 and branch.drivezone_support_m >= 18.0:
        return "arm_full_rc"
    if branch.drivezone_support_m >= 10.0 and branch.road_support_m >= 8.0:
        return "arm_partial"
    return "edge_only"


def _select_main_pair(branches: list[BranchEvidence]) -> tuple[str, str]:
    if len(branches) < 2:
        raise VirtualIntersectionPocError(
            REASON_MAIN_DIRECTION_UNSTABLE,
            "Need at least two incident road branches to identify a main axis.",
        )

    best_pair: tuple[str, str] | None = None
    best_score = -1.0
    for first_index in range(len(branches)):
        for second_index in range(first_index + 1, len(branches)):
            first_branch = branches[first_index]
            second_branch = branches[second_index]
            if _angle_diff_deg(first_branch.angle_deg, second_branch.angle_deg) < 180.0 - MAIN_AXIS_ANGLE_TOLERANCE_DEG:
                continue
            if not (first_branch.has_incoming_support or second_branch.has_incoming_support):
                continue
            if not (first_branch.has_outgoing_support or second_branch.has_outgoing_support):
                continue
            score = (
                first_branch.drivezone_support_m
                + second_branch.drivezone_support_m
                + first_branch.road_support_m
                + second_branch.road_support_m
            )
            if score > best_score:
                best_score = score
                best_pair = (first_branch.branch_id, second_branch.branch_id)

    if best_pair is None:
        raise VirtualIntersectionPocError(
            REASON_MAIN_DIRECTION_UNSTABLE,
            "Failed to identify a stable opposite main-direction pair with at least one incoming and one outgoing support.",
        )
    return best_pair


def _covered_by_drivezone(geometry: BaseGeometry, drivezone_union: BaseGeometry) -> bool:
    tolerance = max(DEFAULT_RESOLUTION_M, 0.2)
    return drivezone_union.buffer(tolerance).covers(geometry)


def _build_positive_negative_rc_groups(
    *,
    kind_2: int,
    road_branches: list[BranchEvidence],
    rc_branches: list[BranchEvidence],
    risks: list[str],
) -> tuple[set[str], set[str]]:
    rc_branch_by_id = {branch.branch_id: branch for branch in rc_branches}
    positive: set[str] = set()
    negative: set[str] = set()

    for branch in road_branches:
        if branch.is_main_direction:
            for rc_group_id in branch.rcsdroad_ids:
                positive.add(rc_group_id)

    side_branches = [branch for branch in road_branches if not branch.is_main_direction and branch.selected_for_polygon]
    if kind_2 == 2048:
        candidates: list[tuple[float, str, str]] = []
        for branch in side_branches:
            for rc_group_id in branch.rcsdroad_ids:
                rc_branch = rc_branch_by_id[rc_group_id]
                score = rc_branch.road_support_m + branch.road_support_m + branch.drivezone_support_m
                candidates.append((score, branch.branch_id, rc_group_id))
        candidates.sort(reverse=True)
        if candidates:
            if len(candidates) >= 2:
                best_score = candidates[0][0]
                second_score = candidates[1][0]
                if second_score >= max(best_score * 0.9, best_score - 5.0):
                    if STATUS_AMBIGUOUS_RC_MATCH not in risks:
                        risks.append(STATUS_AMBIGUOUS_RC_MATCH)
                else:
                    positive.add(candidates[0][2])
            else:
                positive.add(candidates[0][2])
            chosen = set(positive)
            for _, _, rc_group_id in candidates:
                if rc_group_id not in chosen:
                    negative.add(rc_group_id)
        return positive, negative

    for branch in side_branches:
        positive.update(branch.rcsdroad_ids)
    return positive, negative


def _branch_ray_geometry(center: Point, *, angle_deg: float, length_m: float) -> LineString:
    radians = math.radians(angle_deg)
    end_x = float(center.x) + math.cos(radians) * length_m
    end_y = float(center.y) + math.sin(radians) * length_m
    return LineString([(float(center.x), float(center.y)), (end_x, end_y)])


def _branch_to_json(branch: BranchEvidence) -> dict[str, Any]:
    return {
        "branch_id": branch.branch_id,
        "angle_deg": round(branch.angle_deg, 3),
        "branch_type": branch.branch_type,
        "road_ids": branch.road_ids,
        "rcsdroad_ids": branch.rcsdroad_ids,
        "road_support_m": round(branch.road_support_m, 3),
        "drivezone_support_m": round(branch.drivezone_support_m, 3),
        "rc_support_m": round(branch.rc_support_m, 3),
        "has_incoming_support": branch.has_incoming_support,
        "has_outgoing_support": branch.has_outgoing_support,
        "is_main_direction": branch.is_main_direction,
        "selected_for_polygon": branch.selected_for_polygon,
        "selected_rc_group": branch.selected_rc_group,
        "conflict_excluded": branch.conflict_excluded,
        "evidence_level": branch.evidence_level,
        "polygon_length_m": round(branch.polygon_length_m, 3),
    }


def _branch_feature(
    *,
    branch: BranchEvidence,
    center: Point,
    length_m: float,
) -> dict[str, Any]:
    return {
        "properties": _branch_to_json(branch),
        "geometry": _branch_ray_geometry(center, angle_deg=branch.angle_deg, length_m=max(length_m, 1.0)),
    }


def _write_association_outputs(
    *,
    geojson_path: Path,
    audit_csv_path: Path,
    audit_json_path: Path,
    features: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> None:
    write_geojson(geojson_path, features)
    write_csv(audit_csv_path, audits, fieldnames=ASSOCIATION_AUDIT_FIELDNAMES)
    write_json(audit_json_path, audits)


def _status_from_risks(risks: list[str], *, has_associated_roads: bool) -> str:
    if STATUS_AMBIGUOUS_RC_MATCH in risks:
        return STATUS_AMBIGUOUS_RC_MATCH
    if STATUS_NO_VALID_RC_CONNECTION in risks:
        return STATUS_NO_VALID_RC_CONNECTION
    if STATUS_WEAK_BRANCH_SUPPORT in risks:
        return STATUS_WEAK_BRANCH_SUPPORT
    if has_associated_roads:
        return STATUS_STABLE
    return STATUS_SURFACE_ONLY


def run_t02_virtual_intersection_poc(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
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
    buffer_m: float = DEFAULT_PATCH_BUFFER_M,
    patch_size_m: float = DEFAULT_PATCH_SIZE_M,
    resolution_m: float = DEFAULT_RESOLUTION_M,
) -> VirtualIntersectionArtifacts:
    tracemalloc.start()
    started_at = time.perf_counter()

    out_root_path, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    out_root_path.mkdir(parents=True, exist_ok=True)

    virtual_polygon_path = out_root_path / "virtual_intersection_polygon.geojson"
    branch_evidence_json_path = out_root_path / "branch_evidence.json"
    branch_evidence_geojson_path = out_root_path / "branch_evidence.geojson"
    associated_rcsdroad_path = out_root_path / "associated_rcsdroad.geojson"
    associated_rcsdroad_audit_csv_path = out_root_path / "associated_rcsdroad_audit.csv"
    associated_rcsdroad_audit_json_path = out_root_path / "associated_rcsdroad_audit.json"
    associated_rcsdnode_path = out_root_path / "associated_rcsdnode.geojson"
    associated_rcsdnode_audit_csv_path = out_root_path / "associated_rcsdnode_audit.csv"
    associated_rcsdnode_audit_json_path = out_root_path / "associated_rcsdnode_audit.json"
    status_path = out_root_path / "t02_virtual_intersection_poc_status.json"
    audit_csv_path = out_root_path / "t02_virtual_intersection_poc_audit.csv"
    audit_json_path = out_root_path / "t02_virtual_intersection_poc_audit.json"
    log_path = out_root_path / "t02_virtual_intersection_poc.log"
    progress_path = out_root_path / "t02_virtual_intersection_poc_progress.json"
    perf_json_path = out_root_path / "t02_virtual_intersection_poc_perf.json"
    perf_markers_path = out_root_path / "t02_virtual_intersection_poc_perf_markers.jsonl"

    logger = build_logger(log_path, f"t02_virtual_intersection_poc_{resolved_run_id}")
    counts: dict[str, Any] = {
        "mainnodeid": _normalize_id(mainnodeid),
        "local_node_count": 0,
        "local_road_count": 0,
        "local_drivezone_feature_count": 0,
        "local_rcsdroad_count": 0,
        "local_rcsdnode_count": 0,
        "associated_rcsdroad_count": 0,
        "associated_rcsdnode_count": 0,
        "risk_count": 0,
        "audit_count": 0,
    }
    stage_timings: list[dict[str, Any]] = []
    stage_started_at = time.perf_counter()
    audit_rows: list[dict[str, Any]] = []
    road_association_audits: list[dict[str, Any]] = []
    node_association_audits: list[dict[str, Any]] = []

    def record_stage(stage_name: str, *, note: str | None = None) -> None:
        nonlocal stage_started_at
        elapsed = time.perf_counter() - stage_started_at
        stage_timings.append(
            {
                "stage": stage_name,
                "elapsed_sec": round(elapsed, 6),
                **_tracemalloc_stats(),
            }
        )
        _record_perf_marker(
            out_path=perf_markers_path,
            run_id=resolved_run_id,
            stage=stage_name,
            elapsed_sec=elapsed,
            counts=counts,
            note=note,
        )
        stage_started_at = time.perf_counter()

    def report_local_scan(layer_label: str, scanned_count: int, matched_count: int) -> None:
        counts[f"{layer_label}_scanned_count"] = scanned_count
        counts[f"{layer_label}_matched_count"] = matched_count
        if layer_label.endswith("_cache_build"):
            base_label = layer_label[: -len("_cache_build")]
            current_stage = f"building_{base_label}_spatial_cache"
            message = f"Building spatial cache for {base_label}: scanned={scanned_count}, indexed={matched_count}."
            log_line = f"[T02-POC] building spatial cache {base_label} scanned={scanned_count} indexed={matched_count}"
        elif layer_label.endswith("_cache_query"):
            base_label = layer_label[: -len("_cache_query")]
            current_stage = f"querying_{base_label}_spatial_cache"
            message = f"Querying spatial cache for {base_label}: candidates={scanned_count}, matched={matched_count}."
            log_line = f"[T02-POC] querying spatial cache {base_label} candidates={scanned_count} matched={matched_count}"
        else:
            base_label = layer_label
            current_stage = f"scanning_{base_label}"
            message = f"Scanning {base_label}: scanned={scanned_count}, matched={matched_count}."
            log_line = f"[T02-POC] scanning {base_label} scanned={scanned_count} matched={matched_count}"
        announce(
            logger,
            log_line,
        )
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage=current_stage,
            message=message,
            counts=counts,
        )

    _write_progress_snapshot(
        out_path=progress_path,
        run_id=resolved_run_id,
        status="running",
        current_stage="start",
        message="T02 virtual intersection POC started.",
        counts=counts,
    )
    announce(logger, f"[T02-POC] start run_id={resolved_run_id}")

    try:
        normalized_mainnodeid = _normalize_id(mainnodeid)
        if normalized_mainnodeid is None:
            raise VirtualIntersectionPocError(REASON_MAINNODEID_NOT_FOUND, "mainnodeid is empty.")

        def _target_group_match(properties: dict[str, Any]) -> bool:
            node_id = _normalize_id(properties.get("id"))
            group_id = _normalize_id(properties.get("mainnodeid"))
            return group_id == normalized_mainnodeid or (group_id is None and node_id == normalized_mainnodeid)

        target_nodes_layer_data = _load_layer_filtered(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
            property_predicate=_target_group_match,
        )
        target_group_nodes = _parse_nodes(target_nodes_layer_data, require_anchor_fields=True)
        counts["target_group_candidate_count"] = len(target_group_nodes)
        representative_node, group_nodes = _resolve_group(mainnodeid=normalized_mainnodeid, nodes=target_group_nodes)
        if representative_node.has_evd != "yes" or representative_node.is_anchor != "no" or representative_node.kind_2 not in ALLOWED_KIND_2_VALUES:
            raise VirtualIntersectionPocError(
                REASON_MAINNODEID_OUT_OF_SCOPE,
                (
                    f"mainnodeid='{normalized_mainnodeid}' is out of scope: "
                    f"has_evd={representative_node.has_evd}, is_anchor={representative_node.is_anchor}, "
                    f"kind_2={representative_node.kind_2}."
                ),
            )

        patch_query = representative_node.geometry.buffer(buffer_m)
        announce(
            logger,
            (
                "[T02-POC] target resolved "
                f"mainnodeid={normalized_mainnodeid} target_group_candidates={counts['target_group_candidate_count']} "
                f"buffer_m={buffer_m}"
            ),
        )
        record_stage("target_group_resolved")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="target_group_resolved",
            message="Resolved target representative node and local buffer.",
            counts=counts,
        )

        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="loading_local_inputs",
            message="Loading local POC inputs around the target junction.",
            counts=counts,
        )

        local_nodes_layer_data = _load_layer_filtered(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
            progress_label="local_nodes",
            progress_callback=report_local_scan,
        )
        counts["node_feature_count"] = len(local_nodes_layer_data.features)
        announce(
            logger,
            f"[T02-POC] local nodes loaded matched={counts['node_feature_count']}",
        )
        record_stage("local_nodes_loaded")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_nodes_loaded",
            message="Loaded local nodes around the target junction.",
            counts=counts,
        )

        roads_layer_data = _load_layer_filtered(
            roads_path,
            layer_name=roads_layer,
            crs_override=roads_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
            progress_label="roads",
            progress_callback=report_local_scan,
        )
        parsed_roads = _parse_roads(roads_layer_data, label="roads")
        counts["road_feature_count"] = len(parsed_roads)
        announce(
            logger,
            f"[T02-POC] local roads loaded matched={counts['road_feature_count']}",
        )
        record_stage("local_roads_loaded")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_roads_loaded",
            message="Loaded local roads around the target junction.",
            counts=counts,
        )

        drivezone_layer_data = _load_layer_filtered(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
            progress_label="drivezone",
            progress_callback=report_local_scan,
        )
        counts["drivezone_feature_count"] = len(drivezone_layer_data.features)
        announce(
            logger,
            f"[T02-POC] local drivezone loaded matched={counts['drivezone_feature_count']}",
        )
        record_stage("local_drivezone_loaded")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_drivezone_loaded",
            message="Loaded local DriveZone coverage around the target junction.",
            counts=counts,
        )

        rcsdroad_layer_data = _load_layer_filtered(
            rcsdroad_path,
            layer_name=rcsdroad_layer,
            crs_override=rcsdroad_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
            progress_label="rcsdroad",
            progress_callback=report_local_scan,
        )
        parsed_rc_roads = _parse_roads(rcsdroad_layer_data, label="RCSDRoad")
        counts["rcsdroad_feature_count"] = len(parsed_rc_roads)
        announce(
            logger,
            f"[T02-POC] local rcsdroad loaded matched={counts['rcsdroad_feature_count']}",
        )
        record_stage("local_rcsdroad_loaded")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_rcsdroad_loaded",
            message="Loaded local RCSDRoad coverage around the target junction.",
            counts=counts,
        )

        rcsdnode_layer_data = _load_layer_filtered(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
            progress_label="rcsdnode",
            progress_callback=report_local_scan,
        )
        parsed_rc_nodes = _parse_rc_nodes(rcsdnode_layer_data)
        counts["rcsdnode_feature_count"] = len(parsed_rc_nodes)
        announce(
            logger,
            f"[T02-POC] local rcsdnode loaded matched={counts['rcsdnode_feature_count']}",
        )
        record_stage("local_rcsdnode_loaded")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_rcsdnode_loaded",
            message="Loaded local RCSDNode coverage around the target junction.",
            counts=counts,
        )
        announce(
            logger,
            (
                "[T02-POC] local inputs loaded "
                f"nodes={counts['node_feature_count']} roads={counts['road_feature_count']} "
                f"drivezone={counts['drivezone_feature_count']} rcsdroad={counts['rcsdroad_feature_count']} "
                f"rcsdnode={counts['rcsdnode_feature_count']}"
            ),
        )
        record_stage("inputs_loaded")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="inputs_loaded",
            message="Loaded local POC inputs around the target junction.",
            counts=counts,
        )
        local_roads = parsed_roads
        local_drivezone_features = [feature for feature in drivezone_layer_data.features if feature.geometry is not None]
        local_rc_roads = parsed_rc_roads
        local_rc_nodes = parsed_rc_nodes
        if not local_drivezone_features:
            raise VirtualIntersectionPocError(
                REASON_MISSING_REQUIRED_FIELD,
                f"mainnodeid='{normalized_mainnodeid}' local buffer has no DriveZone coverage.",
            )
        counts["local_node_count"] = len(local_nodes_layer_data.features)
        counts["local_road_count"] = len(local_roads)
        counts["local_drivezone_feature_count"] = len(local_drivezone_features)
        counts["local_rcsdroad_count"] = len(local_rc_roads)
        counts["local_rcsdnode_count"] = len(local_rc_nodes)

        drivezone_union = unary_union([feature.geometry for feature in local_drivezone_features if feature.geometry is not None])
        for rc_road in local_rc_roads:
            if not _covered_by_drivezone(rc_road.geometry, drivezone_union):
                raise VirtualIntersectionPocError(
                    REASON_RC_OUTSIDE_DRIVEZONE,
                    f"RCSDRoad id='{rc_road.road_id}' is not fully covered by DriveZone within the local patch.",
                )
        for rc_node in local_rc_nodes:
            if not _covered_by_drivezone(rc_node.geometry.buffer(max(resolution_m, 0.2)), drivezone_union):
                raise VirtualIntersectionPocError(
                    REASON_RC_OUTSIDE_DRIVEZONE,
                    f"RCSDNode id='{rc_node.node_id}' is not covered by DriveZone within the local patch.",
                )

        try:
            _rc_representative_node, rc_group_nodes = _resolve_group(mainnodeid=normalized_mainnodeid, nodes=local_rc_nodes)
        except VirtualIntersectionPocError as exc:
            if exc.reason == REASON_MAINNODEID_NOT_FOUND:
                rc_group_nodes = []
            else:
                raise

        record_stage("local_patch_built")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_patch_built",
            message="Built local feature patch around target junction.",
            counts=counts,
        )

        grid = _build_grid(representative_node.geometry, patch_size_m=patch_size_m, resolution_m=resolution_m)
        drivezone_mask = _rasterize_geometries(grid, [drivezone_union])
        road_mask = _rasterize_geometries(
            grid,
            [road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2) for road in local_roads],
        )
        rc_road_mask = _rasterize_geometries(
            grid,
            [road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2) for road in local_rc_roads],
        )
        node_seed_mask = _rasterize_geometries(
            grid,
            [node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
        )
        if rc_group_nodes:
            rc_node_seed_mask = _rasterize_geometries(
                grid,
                [node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in rc_group_nodes],
            )
        else:
            rc_node_seed_mask = np.zeros_like(node_seed_mask, dtype=bool)
        record_stage("masks_built")

        member_node_ids = {node.node_id for node in group_nodes}
        incident_roads = [road for road in local_roads if road.snodeid in member_node_ids or road.enodeid in member_node_ids]
        if not incident_roads:
            raise VirtualIntersectionPocError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                f"mainnodeid='{normalized_mainnodeid}' has no incident roads inside the local patch.",
            )

        road_candidates = [
            candidate
            for candidate in (
                _branch_candidate_from_road(road, member_node_ids=member_node_ids, drivezone_union=drivezone_union)
                for road in incident_roads
            )
            if candidate is not None
        ]
        road_branches = _cluster_branch_candidates(
            road_candidates,
            branch_type="road",
            angle_tolerance_deg=BRANCH_MATCH_TOLERANCE_DEG,
        )

        rc_member_node_ids = {node.node_id for node in rc_group_nodes}
        incident_rc_roads = [road for road in local_rc_roads if road.snodeid in rc_member_node_ids or road.enodeid in rc_member_node_ids]
        rc_candidates = [
            candidate
            for candidate in (
                _branch_candidate_from_road(road, member_node_ids=rc_member_node_ids, drivezone_union=drivezone_union)
                for road in incident_rc_roads
            )
            if candidate is not None
        ]
        rc_branches = _cluster_branch_candidates(
            rc_candidates,
            branch_type="rc_group",
            angle_tolerance_deg=BRANCH_MATCH_TOLERANCE_DEG,
        )

        for branch in road_branches:
            branch.drivezone_support_m = _ray_support_m(
                mask=drivezone_mask,
                grid=grid,
                center=representative_node.geometry,
                angle_deg=branch.angle_deg,
                max_length_m=patch_size_m / 2.0,
            )
            branch.rc_support_m = _ray_support_m(
                mask=rc_road_mask,
                grid=grid,
                center=representative_node.geometry,
                angle_deg=branch.angle_deg,
                max_length_m=patch_size_m / 2.0,
            )

        for branch in rc_branches:
            branch.drivezone_support_m = _ray_support_m(
                mask=drivezone_mask,
                grid=grid,
                center=representative_node.geometry,
                angle_deg=branch.angle_deg,
                max_length_m=patch_size_m / 2.0,
            )

        for branch in road_branches:
            matched_rc_groups = [
                rc_branch.branch_id
                for rc_branch in rc_branches
                if (
                    _angle_diff_deg(branch.angle_deg, rc_branch.angle_deg) <= BRANCH_MATCH_TOLERANCE_DEG
                    or _angle_diff_deg((branch.angle_deg + 180.0) % 360.0, rc_branch.angle_deg)
                    <= BRANCH_MATCH_TOLERANCE_DEG
                )
            ]
            branch.rcsdroad_ids = sorted(set(matched_rc_groups))

        main_branch_ids = set(_select_main_pair(road_branches))
        for branch in road_branches:
            branch.is_main_direction = branch.branch_id in main_branch_ids
            branch.evidence_level = _classify_branch_evidence(branch)
            branch.selected_for_polygon = branch.is_main_direction or branch.evidence_level != "edge_only"

        record_stage("main_direction_identified")

        risks: list[str] = []
        if any(
            branch.selected_for_polygon and branch.evidence_level == "edge_only"
            for branch in road_branches
            if not branch.is_main_direction
        ):
            risks.append(STATUS_WEAK_BRANCH_SUPPORT)
        positive_rc_groups, negative_rc_groups = _build_positive_negative_rc_groups(
            kind_2=representative_node.kind_2 or 0,
            road_branches=road_branches,
            rc_branches=rc_branches,
            risks=risks,
        )
        if rc_branches and not positive_rc_groups:
            risks.append(STATUS_NO_VALID_RC_CONNECTION)
        for branch in rc_branches:
            branch.selected_rc_group = branch.branch_id in positive_rc_groups
            branch.conflict_excluded = branch.branch_id in negative_rc_groups

        rc_branch_by_id = {branch.branch_id: branch for branch in rc_branches}
        positive_rc_road_ids: set[str] = set()
        negative_rc_road_ids: set[str] = set()
        for group_id in positive_rc_groups:
            positive_rc_road_ids.update(rc_branch_by_id[group_id].road_ids)
        for group_id in negative_rc_groups:
            negative_rc_road_ids.update(rc_branch_by_id[group_id].road_ids)

        core_mask = _rasterize_geometries(
            grid,
            [representative_node.geometry.buffer(NODE_SEED_RADIUS_M * 1.5)],
        ) & drivezone_mask
        polygon_mask = core_mask.copy()
        branch_features: list[dict[str, Any]] = []
        for branch in road_branches:
            max_length = max(branch.drivezone_support_m, branch.road_support_m, 8.0)
            half_width = MAIN_BRANCH_HALF_WIDTH_M if branch.is_main_direction else SIDE_BRANCH_HALF_WIDTH_M
            corridor_geometry = _branch_ray_geometry(
                representative_node.geometry,
                angle_deg=branch.angle_deg,
                length_m=max_length,
            ).buffer(half_width, cap_style=2, join_style=2)
            corridor_mask = _rasterize_geometries(grid, [corridor_geometry]) & drivezone_mask
            if branch.selected_for_polygon:
                polygon_mask |= corridor_mask
            branch.polygon_length_m = max_length
            branch_features.append(
                _branch_feature(
                    branch=branch,
                    center=representative_node.geometry,
                    length_m=max_length,
                )
            )

        if positive_rc_road_ids:
            positive_rc_geometries = [
                road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2)
                for road in local_rc_roads
                if road.road_id in positive_rc_road_ids
            ]
            if positive_rc_geometries:
                polygon_mask |= _rasterize_geometries(grid, positive_rc_geometries) & drivezone_mask
        if negative_rc_road_ids:
            negative_rc_geometries = [
                road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2)
                for road in local_rc_roads
                if road.road_id in negative_rc_road_ids
            ]
            if negative_rc_geometries:
                polygon_mask &= ~_rasterize_geometries(grid, negative_rc_geometries)

        polygon_mask &= drivezone_mask
        polygon_mask = _binary_close(polygon_mask, iterations=1)
        polygon_mask = _extract_seed_component(polygon_mask, core_mask | node_seed_mask | rc_node_seed_mask)
        if not polygon_mask.any():
            polygon_mask = core_mask
        virtual_polygon_geometry = _mask_to_geometry(polygon_mask, grid)
        if virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = representative_node.geometry.buffer(12.0).intersection(drivezone_union)
        record_stage("virtual_polygon_built")
        selected_rc_roads = [
            road
            for road in local_rc_roads
            if road.road_id in positive_rc_road_ids and road.geometry.intersects(virtual_polygon_geometry)
        ]
        if not selected_rc_roads and positive_rc_road_ids and STATUS_NO_VALID_RC_CONNECTION not in risks:
            risks.append(STATUS_NO_VALID_RC_CONNECTION)

        associated_rcsdroad_features: list[dict[str, Any]] = []
        for road in local_rc_roads:
            selected = road in selected_rc_roads
            reason = "selected_by_positive_rc_group" if selected else "not_selected"
            branch_id = next(
                (branch_id for branch_id, branch in rc_branch_by_id.items() if road.road_id in branch.road_ids),
                None,
            )
            road_association_audits.append(
                _association_audit_row(
                    entity_type="rcsdroad",
                    entity_id=road.road_id,
                    selected=selected,
                    reason=reason,
                    group_id=branch_id,
                    branch_id=branch_id,
                )
            )
            if selected:
                associated_rcsdroad_features.append({"properties": dict(road.properties), "geometry": road.geometry})

        selected_rc_node_ids: set[str] = {node.node_id for node in rc_group_nodes}
        for road in selected_rc_roads:
            selected_rc_node_ids.add(road.snodeid)
            selected_rc_node_ids.add(road.enodeid)
        associated_rcsdnode_features: list[dict[str, Any]] = []
        for node in local_rc_nodes:
            selected = node.node_id in selected_rc_node_ids
            node_association_audits.append(
                _association_audit_row(
                    entity_type="rcsdnode",
                    entity_id=node.node_id,
                    selected=selected,
                    reason="selected_by_rcsdroad_or_group" if selected else "not_selected",
                    group_id=normalized_mainnodeid,
                    branch_id=None,
                )
            )
            if selected:
                associated_rcsdnode_features.append({"properties": dict(node.properties), "geometry": node.geometry})

        counts["associated_rcsdroad_count"] = len(associated_rcsdroad_features)
        counts["associated_rcsdnode_count"] = len(associated_rcsdnode_features)
        counts["risk_count"] = len(risks)

        status = _status_from_risks(risks, has_associated_roads=bool(associated_rcsdroad_features))
        if status == STATUS_STABLE and not associated_rcsdroad_features:
            status = STATUS_SURFACE_ONLY

        write_geojson(
            virtual_polygon_path,
            [
                {
                    "properties": {
                        "mainnodeid": normalized_mainnodeid,
                        "status": status,
                        "representative_node_id": representative_node.node_id,
                        "kind_2": representative_node.kind_2,
                        "grade_2": representative_node.grade_2,
                    },
                    "geometry": virtual_polygon_geometry,
                }
            ],
        )
        write_json(
            branch_evidence_json_path,
            {
                "mainnodeid": normalized_mainnodeid,
                "representative_node_id": representative_node.node_id,
                "branches": [_branch_to_json(branch) for branch in road_branches],
                "rc_groups": [_branch_to_json(branch) for branch in rc_branches],
                "selected_positive_rc_groups": sorted(positive_rc_groups),
                "excluded_negative_rc_groups": sorted(negative_rc_groups),
            },
        )
        write_geojson(branch_evidence_geojson_path, branch_features)
        _write_association_outputs(
            geojson_path=associated_rcsdroad_path,
            audit_csv_path=associated_rcsdroad_audit_csv_path,
            audit_json_path=associated_rcsdroad_audit_json_path,
            features=associated_rcsdroad_features,
            audits=road_association_audits,
        )
        _write_association_outputs(
            geojson_path=associated_rcsdnode_path,
            audit_csv_path=associated_rcsdnode_audit_csv_path,
            audit_json_path=associated_rcsdnode_audit_json_path,
            features=associated_rcsdnode_features,
            audits=node_association_audits,
        )
        write_csv(audit_csv_path, audit_rows, fieldnames=AUDIT_FIELDNAMES)
        write_json(audit_json_path, audit_rows)
        counts["audit_count"] = len(audit_rows)
        write_json(
            status_path,
            {
                "run_id": resolved_run_id,
                "success": True,
                "mainnodeid": normalized_mainnodeid,
                "representative_node_id": representative_node.node_id,
                "kind_2": representative_node.kind_2,
                "grade_2": representative_node.grade_2,
                "status": status,
                "risks": risks,
                "counts": counts,
                "patch": {
                    "buffer_m": buffer_m,
                    "patch_size_m": patch_size_m,
                    "resolution_m": resolution_m,
                },
                "selected_positive_rc_groups": sorted(positive_rc_groups),
                "excluded_negative_rc_groups": sorted(negative_rc_groups),
                "output_files": {
                    "virtual_intersection_polygon": str(virtual_polygon_path),
                    "branch_evidence_json": str(branch_evidence_json_path),
                    "branch_evidence_geojson": str(branch_evidence_geojson_path),
                    "associated_rcsdroad": str(associated_rcsdroad_path),
                    "associated_rcsdnode": str(associated_rcsdnode_path),
                    "audit_csv": str(audit_csv_path),
                    "audit_json": str(audit_json_path),
                },
            },
        )
        announce(
            logger,
            (
                "[T02-POC] wrote outputs "
                f"status={status} associated_rcsdroad_count={counts['associated_rcsdroad_count']} "
                f"associated_rcsdnode_count={counts['associated_rcsdnode_count']} out_root={out_root_path}"
            ),
        )
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="success",
            current_stage="complete",
            message="T02 virtual intersection POC completed.",
            counts=counts,
        )
        record_stage("outputs_written")
        total_wall_time_sec = time.perf_counter() - started_at
        write_json(
            perf_json_path,
            {
                "run_id": resolved_run_id,
                "success": True,
                "total_wall_time_sec": round(total_wall_time_sec, 6),
                "counts": counts,
                "stage_timings": stage_timings,
                **_tracemalloc_stats(),
            },
        )
        return VirtualIntersectionArtifacts(
            success=True,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            branch_evidence_json_path=branch_evidence_json_path,
            branch_evidence_geojson_path=branch_evidence_geojson_path,
            associated_rcsdroad_path=associated_rcsdroad_path,
            associated_rcsdroad_audit_csv_path=associated_rcsdroad_audit_csv_path,
            associated_rcsdroad_audit_json_path=associated_rcsdroad_audit_json_path,
            associated_rcsdnode_path=associated_rcsdnode_path,
            associated_rcsdnode_audit_csv_path=associated_rcsdnode_audit_csv_path,
            associated_rcsdnode_audit_json_path=associated_rcsdnode_audit_json_path,
            status_path=status_path,
            audit_csv_path=audit_csv_path,
            audit_json_path=audit_json_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
        )
    except VirtualIntersectionPocError as exc:
        audit_rows.append(
            _audit_row(
                scope="virtual_intersection_poc",
                status="failed",
                reason=exc.reason,
                detail=exc.detail,
                mainnodeid=_normalize_id(mainnodeid),
            )
        )
        counts["audit_count"] = len(audit_rows)
        counts["risk_count"] = 1
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="failed",
            current_stage="failed",
            message=exc.detail,
            counts=counts,
        )
        write_csv(audit_csv_path, audit_rows, fieldnames=AUDIT_FIELDNAMES)
        write_json(audit_json_path, audit_rows)
        write_json(
            status_path,
            {
                "run_id": resolved_run_id,
                "success": False,
                "mainnodeid": _normalize_id(mainnodeid),
                "status": exc.reason,
                "risks": [exc.reason],
                "detail": exc.detail,
                "counts": counts,
            },
        )
        total_wall_time_sec = time.perf_counter() - started_at
        write_json(
            perf_json_path,
            {
                "run_id": resolved_run_id,
                "success": False,
                "total_wall_time_sec": round(total_wall_time_sec, 6),
                "counts": counts,
                "stage_timings": stage_timings,
                **_tracemalloc_stats(),
            },
        )
        announce(logger, f"[T02-POC] failed reason={exc.reason} detail={exc.detail}")
        return VirtualIntersectionArtifacts(
            success=False,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            branch_evidence_json_path=branch_evidence_json_path,
            branch_evidence_geojson_path=branch_evidence_geojson_path,
            associated_rcsdroad_path=associated_rcsdroad_path,
            associated_rcsdroad_audit_csv_path=associated_rcsdroad_audit_csv_path,
            associated_rcsdroad_audit_json_path=associated_rcsdroad_audit_json_path,
            associated_rcsdnode_path=associated_rcsdnode_path,
            associated_rcsdnode_audit_csv_path=associated_rcsdnode_audit_csv_path,
            associated_rcsdnode_audit_json_path=associated_rcsdnode_audit_json_path,
            status_path=status_path,
            audit_csv_path=audit_csv_path,
            audit_json_path=audit_json_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
        )
    finally:
        close_logger(logger)
        tracemalloc.stop()


def run_t02_virtual_intersection_poc_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_virtual_intersection_poc(
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
        buffer_m=args.buffer_m,
        patch_size_m=args.patch_size_m,
        resolution_m=args.resolution_m,
    )
    if artifacts.success:
        print(f"T02 virtual intersection POC outputs written to: {artifacts.out_root}")
        return 0
    print(f"T02 virtual intersection POC failed; audit written to: {artifacts.out_root}")
    return 1
