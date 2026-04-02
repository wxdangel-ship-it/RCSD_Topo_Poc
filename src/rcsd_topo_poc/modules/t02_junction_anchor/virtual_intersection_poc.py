from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import struct
import time
import tracemalloc
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, TypeVar, Union

import ijson
import numpy as np
import fiona
import shapefile
from pyproj import CRS
from shapely import from_wkb, intersects_xy
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    prefer_vector_input_path,
    transform_geometry_to_target,
    write_vector,
    write_json,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv
from rcsd_topo_poc.modules.t02_junction_anchor.stage1_drivezone_gate import (
    LoadedFeature,
    LoadedLayer,
    _normalize_id,
    _read_vector_layer_strict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    _resolve_geopackage_crs_strict,
    _resolve_geopackage_layer_name,
    _resolve_shapefile_crs_strict,
    _transform_geometry,
)


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
MAIN_BRANCH_HALF_WIDTH_M = 7.0
SIDE_BRANCH_HALF_WIDTH_M = 5.0
MAIN_AXIS_ANGLE_TOLERANCE_DEG = 35.0
BRANCH_MATCH_TOLERANCE_DEG = 30.0
RC_BRANCH_PROXIMITY_M = 18.0
RC_OUTSIDE_DRIVEZONE_IGNORE_MARGIN_M = 25.0
RC_OUTSIDE_DRIVEZONE_RELEVANCE_MAX_DISTANCE_M = 50.0
RC_OUTSIDE_DRIVEZONE_SOFT_EXCLUDE_MIN_DISTANCE_M = 18.0
POLYGON_CORE_RADIUS_M = 7.0
POLYGON_TIP_BUFFER_M = 5.0
POLYGON_RC_NODE_BUFFER_M = 4.0
POLYGON_CONTESTED_RC_NODE_BUFFER_M = 2.0
POLYGON_SUPPORT_SMOOTH_M = 1.5
POLYGON_LOCAL_RC_NODE_DISTANCE_M = 20.0
POLYGON_LOCAL_RC_SEGMENT_EXTENSION_M = 14.0
POLYGON_LOCAL_RC_EXCLUSION_EXTENSION_M = 18.0
POLYGON_SUPPORT_SEED_MAX_DISTANCE_M = 8.0
POLYGON_SUPPORT_SEED_MARGIN_M = 2.5
POLYGON_SUPPORT_EXPANSION_HOPS = 2
POLYGON_SUPPORT_EXPANSION_MAX_DISTANCE_M = 32.0
POLYGON_SUPPORT_CLIP_RADIUS_M = 18.0
POLYGON_SUPPORT_CLIP_BUFFER_M = 4.0
POLYGON_ENDPOINT_SUPPORT_MAX_LENGTH_M = 70.0
POLYGON_ENDPOINT_SUPPORT_ANGLE_TOLERANCE_DEG = 40.0
POLYGON_ENDPOINT_SUPPORT_GROUP_DISTANCE_MARGIN_M = 3.0
POLYGON_ENDPOINT_SUPPORT_ORPHAN_GROUP_DISTANCE_M = 50.0
POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_LENGTH_M = 35.0
POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_GROUP_DISTANCE_M = 12.0
POLYGON_SUPPORT_NODE_LOCAL_GROUP_DISTANCE_M = 30.0
POLYGON_SUPPORT_VALIDATION_TOLERANCE_M = 0.75
POLYGON_SUPPORT_MIN_LINE_COVERAGE_RATIO = 0.9
POLYGON_SMALL_HOLE_AREA_M2 = 18.0
POLYGON_FINAL_COMPONENT_MIN_AREA_M2 = 1.0
POLYGON_FINAL_SMOOTH_M = 1.0
POLYGON_RC_EXCLUSION_BUFFER_FACTOR = 1.8
POLYGON_RC_EXCLUSION_KEEP_NODE_BUFFER_M = 4.5
POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M = 1.2
POLYGON_GROUP_NODE_BUFFER_M = 1.0
POLYGON_GROUP_NODE_REINCLUDE_M = 1.6
POLYGON_FOREIGN_NODE_TRIGGER_DISTANCE_M = 12.0
POLYGON_FOREIGN_NODE_BUFFER_M = 7.5
POLYGON_FOREIGN_NODE_ROAD_EXTENSION_M = 24.0
POLYGON_FOREIGN_NODE_ROAD_BUFFER_M = 4.0
POLYGON_COMPACT_RC_ENDPOINT_MIN_DISTANCE_M = 20.0
POLYGON_COMPACT_RC_ENDPOINT_MAX_DISTANCE_M = 45.0
POLYGON_COMPACT_RC_MAX_LENGTH_M = 80.0
COMPOUND_CENTER_MAX_LINK_M = 20.0
COMPOUND_CENTER_MAX_DISTANCE_M = 25.0
COMPOUND_CENTER_MIN_DRIVEZONE_COVERAGE_RATIO = 0.8
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
REASON_ANCHOR_SUPPORT_CONFLICT = "anchor_support_conflict"

STATUS_STABLE = "stable"
STATUS_SURFACE_ONLY = "surface_only"
STATUS_WEAK_BRANCH_SUPPORT = "weak_branch_support"
STATUS_AMBIGUOUS_RC_MATCH = "ambiguous_rc_match"
STATUS_NO_VALID_RC_CONNECTION = "no_valid_rc_connection"
STATUS_NODE_COMPONENT_CONFLICT = "node_component_conflict"
STATUS_REVIEW_ANCHOR_GATE_BYPASSED = "review_anchor_gate_bypassed"
STATUS_REVIEW_RC_OUTSIDE_DRIVEZONE_EXCLUDED = "review_rc_outside_drivezone_excluded"

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
    rendered_map_path: Path | None = None
    virtual_polygon_feature: dict[str, Any] | None = None
    status_doc: dict[str, Any] | None = None
    perf_doc: dict[str, Any] | None = None
    associated_rcsdroad_ids: tuple[str, ...] | None = None
    associated_rcsdnode_ids: tuple[str, ...] | None = None


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
    layer_path = prefer_vector_input_path(Path(path))
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

    if suffix in GEOPACKAGE_SUFFIXES:
        resolved_layer_name = _resolve_geopackage_layer_name(
            layer_path,
            layer_name,
            error_cls=VirtualIntersectionPocError,
        )
        source_crs, crs_source = _resolve_geopackage_crs_strict(
            layer_path,
            resolved_layer_name,
            crs_override,
            error_cls=VirtualIntersectionPocError,
        )
        source_query_bounds: tuple[float, float, float, float] | None = None
        if query_geometry is not None:
            source_query_geometry = transform_geometry_to_target(query_geometry, TARGET_CRS, source_crs)
            source_query_bounds = tuple(float(v) for v in source_query_geometry.bounds)
        features: list[LoadedFeature] = []
        matched_count = 0
        scanned_count = 0
        try:
            with fiona.open(str(layer_path), layer=resolved_layer_name) as src:
                iterator = src.items(bbox=source_query_bounds) if source_query_bounds is not None else enumerate(src)
                for item in iterator:
                    if source_query_bounds is not None:
                        feature_index, feature = item
                    else:
                        feature_index, feature = item
                    scanned_count += 1
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
                                f"{layer_path} layer '{resolved_layer_name}' feature[{feature_index}] is missing geometry.",
                            )
                        geometry = None
                    else:
                        geometry = _transform_geometry(
                            shape(geometry_payload),
                            source_crs=source_crs,
                            layer_label=f"{layer_path}:{resolved_layer_name}",
                            feature_index=int(feature_index),
                            error_cls=VirtualIntersectionPocError,
                        )
                    if query_geometry is not None and geometry is not None and not geometry.intersects(query_geometry):
                        continue
                    features.append(LoadedFeature(feature_index=int(feature_index), properties=properties, geometry=geometry))
                    matched_count += 1
        except VirtualIntersectionPocError:
            raise
        except Exception as exc:
            raise VirtualIntersectionPocError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Failed to read GeoPackage '{layer_path}' layer '{resolved_layer_name}': {exc}",
            ) from exc
        if progress_label and progress_callback:
            progress_callback(progress_label, scanned_count, matched_count)
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    return _load_layer(
        layer_path,
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


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _write_png_rgba(path: Path, rgba: np.ndarray) -> None:
    if rgba.dtype != np.uint8:
        raise ValueError("PNG image must be uint8.")
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("PNG image must have shape [height, width, 4].")
    height, width, _channels = rgba.shape
    raw_rows = b"".join(b"\x00" + rgba[row_index].tobytes() for row_index in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw_rows, level=9))
        + _png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)


def _blend_mask(
    image: np.ndarray,
    mask: np.ndarray,
    *,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    if not mask.any():
        return
    alpha_value = max(0.0, min(1.0, alpha))
    if alpha_value <= 0.0:
        return
    base = image[mask, :3].astype(np.float32)
    color_array = np.array(color, dtype=np.float32)
    image[mask, :3] = np.clip(base * (1.0 - alpha_value) + color_array * alpha_value, 0.0, 255.0).astype(np.uint8)
    image[mask, 3] = 255


def _write_debug_rendered_map(
    *,
    out_path: Path,
    grid: GridSpec,
    drivezone_mask: np.ndarray,
    polygon_geometry: BaseGeometry,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    local_rc_roads: list[ParsedRoad],
    selected_rc_roads: list[ParsedRoad],
    selected_rc_node_ids: set[str],
    excluded_rc_road_ids: set[str],
    excluded_rc_node_ids: set[str] | None = None,
    failure_reason: str | None = None,
) -> None:
    excluded_rc_node_ids = excluded_rc_node_ids or set()
    image = np.full((grid.height, grid.width, 4), 255, dtype=np.uint8)
    image[..., 3] = 255

    polygon_mask = _rasterize_geometries(grid, [polygon_geometry]) & drivezone_mask
    road_display_buffer_m = 1.0
    node_display_buffer_m = 2.0
    road_mask = _rasterize_geometries(
        grid,
        [
            road.geometry.buffer(road_display_buffer_m, cap_style=2, join_style=2)
            for road in local_roads
        ],
    )
    rc_road_mask = _rasterize_geometries(
        grid,
        [
            road.geometry.buffer(road_display_buffer_m, cap_style=2, join_style=2)
            for road in local_rc_roads
        ],
    )
    selected_rc_road_mask = _rasterize_geometries(
        grid,
        [
            road.geometry.buffer(road_display_buffer_m, cap_style=2, join_style=2)
            for road in selected_rc_roads
        ],
    )
    excluded_rc_road_mask = _rasterize_geometries(
        grid,
        [
            road.geometry.buffer(road_display_buffer_m, cap_style=2, join_style=2)
            for road in local_rc_roads
            if road.road_id in excluded_rc_road_ids
        ],
    )
    group_node_ids = {node.node_id for node in group_nodes}
    group_node_mask = _rasterize_geometries(
        grid,
        [node.geometry.buffer(node_display_buffer_m) for node in group_nodes],
    )
    other_node_mask = _rasterize_geometries(
        grid,
        [
            node.geometry.buffer(node_display_buffer_m)
            for node in local_nodes
            if node.node_id not in group_node_ids
        ],
    )
    selected_rc_node_mask = _rasterize_geometries(
        grid,
        [
            node.geometry.buffer(node_display_buffer_m)
            for node in local_rc_nodes
            if node.node_id in selected_rc_node_ids
        ],
    )
    excluded_rc_node_mask = _rasterize_geometries(
        grid,
        [
            node.geometry.buffer(node_display_buffer_m)
            for node in local_rc_nodes
            if node.node_id in excluded_rc_node_ids
        ],
    )
    other_rc_node_mask = _rasterize_geometries(
        grid,
        [
            node.geometry.buffer(node_display_buffer_m)
            for node in local_rc_nodes
            if node.node_id not in selected_rc_node_ids and node.node_id not in excluded_rc_node_ids
        ],
    )
    representative_mask = _rasterize_geometries(
        grid,
        [representative_node.geometry.buffer(node_display_buffer_m)],
    )
    drivezone_edge_mask = drivezone_mask & ~_binary_erosion(drivezone_mask, iterations=max(1, int(round(1.2 / grid.resolution_m))))

    _blend_mask(image, drivezone_mask, color=(229, 220, 192), alpha=1.0)
    _blend_mask(image, drivezone_edge_mask, color=(190, 176, 132), alpha=1.0)
    _blend_mask(image, polygon_mask, color=(255, 179, 71), alpha=0.60)
    _blend_mask(image, road_mask, color=(24, 24, 24), alpha=1.0)
    _blend_mask(image, rc_road_mask, color=(193, 18, 31), alpha=1.0)
    _blend_mask(image, excluded_rc_road_mask, color=(138, 28, 42), alpha=1.0)
    _blend_mask(image, selected_rc_road_mask, color=(214, 69, 69), alpha=1.0)
    _blend_mask(image, other_rc_node_mask, color=(193, 18, 31), alpha=0.80)
    _blend_mask(image, selected_rc_node_mask, color=(193, 18, 31), alpha=0.95)
    _blend_mask(image, excluded_rc_node_mask, color=(138, 28, 42), alpha=0.95)
    _blend_mask(image, other_node_mask, color=(24, 24, 24), alpha=1.0)
    _blend_mask(image, group_node_mask, color=(24, 24, 24), alpha=1.0)
    _blend_mask(image, representative_mask, color=(0, 0, 0), alpha=1.0)
    if failure_reason is not None:
        failure_mask = np.ones((grid.height, grid.width), dtype=bool)
        border_px = max(2, int(round(4.0 / grid.resolution_m)))
        border_mask = np.zeros((grid.height, grid.width), dtype=bool)
        border_mask[:border_px, :] = True
        border_mask[-border_px:, :] = True
        border_mask[:, :border_px] = True
        border_mask[:, -border_px:] = True
        _blend_mask(image, failure_mask, color=(208, 43, 43), alpha=0.18)
        _blend_mask(image, border_mask, color=(144, 0, 0), alpha=1.0)

    _write_png_rgba(out_path, image)


def _build_debug_focus_geometry(
    *,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    resolution_m: float,
    extra_geometries: Iterable[BaseGeometry] = (),
) -> BaseGeometry:
    focus_radius_m = max(3.0, resolution_m * 10.0)
    focus_geometries: list[BaseGeometry] = [
        representative_node.geometry.buffer(focus_radius_m),
        *[node.geometry.buffer(focus_radius_m) for node in group_nodes],
        *[
            geometry.buffer(max(1.0, resolution_m * 4.0))
            for geometry in extra_geometries
            if geometry is not None and not geometry.is_empty
        ],
    ]
    if not focus_geometries:
        return representative_node.geometry.buffer(focus_radius_m)
    return unary_union(focus_geometries)


def _write_failure_debug_rendered_map(
    *,
    out_path: Path,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    local_rc_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
    patch_size_m: float,
    resolution_m: float,
    failure_reason: str,
    excluded_rc_road_ids: set[str] | None = None,
    excluded_rc_node_ids: set[str] | None = None,
    extra_highlight_geometries: Iterable[BaseGeometry] = (),
) -> None:
    grid = _build_grid(representative_node.geometry, patch_size_m=patch_size_m, resolution_m=resolution_m)
    drivezone_mask = _rasterize_geometries(grid, [drivezone_union]) if not drivezone_union.is_empty else np.zeros((grid.height, grid.width), dtype=bool)
    _write_debug_rendered_map(
        out_path=out_path,
        grid=grid,
        drivezone_mask=drivezone_mask,
        polygon_geometry=_build_debug_focus_geometry(
            representative_node=representative_node,
            group_nodes=group_nodes,
            resolution_m=resolution_m,
            extra_geometries=extra_highlight_geometries,
        ),
        representative_node=representative_node,
        group_nodes=group_nodes,
        local_nodes=local_nodes,
        local_roads=local_roads,
        local_rc_nodes=local_rc_nodes,
        local_rc_roads=local_rc_roads,
        selected_rc_roads=[],
        selected_rc_node_ids=set(),
        excluded_rc_road_ids=excluded_rc_road_ids or set(),
        excluded_rc_node_ids=excluded_rc_node_ids or set(),
        failure_reason=failure_reason,
    )


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


def _branch_candidate_from_center_proximity(
    road: ParsedRoad,
    *,
    center: Point,
    drivezone_union: BaseGeometry,
    max_distance_m: float,
) -> dict[str, Any] | None:
    line = _linearize(road.geometry)
    if line.distance(center) > max_distance_m:
        return None

    coords = list(line.coords)
    if len(coords) < 2:
        return None

    start = coords[0]
    end = coords[-1]
    start_distance = center.distance(Point(start))
    end_distance = center.distance(Point(end))
    if start_distance <= end_distance:
        anchor = start
        away = coords[1]
    else:
        anchor = end
        away = coords[-2]

    vector = (away[0] - anchor[0], away[1] - anchor[1])
    if math.hypot(vector[0], vector[1]) == 0.0:
        return None

    return {
        "road_id": road.road_id,
        "angle_deg": _vector_to_angle_deg(_normalize_vector(vector)),
        "vector": _normalize_vector(vector),
        "road_support_m": float(road.geometry.intersection(drivezone_union).length),
        "has_incoming_support": True,
        "has_outgoing_support": True,
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


def _build_road_branches_for_member_nodes(
    local_roads: list[ParsedRoad],
    *,
    member_node_ids: set[str],
    drivezone_union: BaseGeometry,
) -> tuple[list[ParsedRoad], set[str], list[BranchEvidence]]:
    incident_roads: list[ParsedRoad] = []
    internal_road_ids: set[str] = set()
    for road in local_roads:
        touches_snode = road.snodeid in member_node_ids
        touches_enode = road.enodeid in member_node_ids
        if not touches_snode and not touches_enode:
            continue
        if touches_snode and touches_enode:
            internal_road_ids.add(road.road_id)
            continue
        incident_roads.append(road)

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
    return incident_roads, internal_road_ids, road_branches


def _resolve_compound_center_branch_context(
    *,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
) -> tuple[Point, set[str], list[ParsedNode], list[BranchEvidence]] | None:
    member_node_ids = {node.node_id for node in group_nodes}
    local_node_by_id = {node.node_id: node for node in local_nodes}
    best_candidate: tuple[float, Point, set[str], list[ParsedNode], list[BranchEvidence]] | None = None

    for road in local_roads:
        line = _linearize(road.geometry)
        if line.length > COMPOUND_CENTER_MAX_LINK_M:
            continue

        touches_snode = road.snodeid in member_node_ids
        touches_enode = road.enodeid in member_node_ids
        if touches_snode == touches_enode:
            continue

        auxiliary_node_id = road.enodeid if touches_snode else road.snodeid
        auxiliary_node = local_node_by_id.get(auxiliary_node_id)
        if auxiliary_node is None or auxiliary_node.node_id in member_node_ids:
            continue
        if representative_node.geometry.distance(auxiliary_node.geometry) > COMPOUND_CENTER_MAX_DISTANCE_M:
            continue

        covered_length = float(line.intersection(drivezone_union).length)
        if line.length <= 0.0 or covered_length / line.length < COMPOUND_CENTER_MIN_DRIVEZONE_COVERAGE_RATIO:
            continue

        expanded_member_node_ids = set(member_node_ids)
        expanded_member_node_ids.add(auxiliary_node.node_id)
        _, _, road_branches = _build_road_branches_for_member_nodes(
            local_roads,
            member_node_ids=expanded_member_node_ids,
            drivezone_union=drivezone_union,
        )
        if len(road_branches) < 2:
            continue
        try:
            _select_main_pair(road_branches)
        except VirtualIntersectionPocError:
            continue

        connector_line = LineString(
            [
                (float(representative_node.geometry.x), float(representative_node.geometry.y)),
                (float(auxiliary_node.geometry.x), float(auxiliary_node.geometry.y)),
            ]
        )
        analysis_center = connector_line.interpolate(0.5, normalized=True)
        branch_score = sum(branch.road_support_m + branch.drivezone_support_m for branch in road_branches)
        score = branch_score + len(road_branches) * 100.0 - line.length
        candidate = (
            score,
            analysis_center,
            expanded_member_node_ids,
            [auxiliary_node],
            road_branches,
        )
        if best_candidate is None or candidate[0] > best_candidate[0]:
            best_candidate = candidate

    if best_candidate is None:
        return None
    _, analysis_center, expanded_member_node_ids, auxiliary_nodes, road_branches = best_candidate
    return analysis_center, expanded_member_node_ids, auxiliary_nodes, road_branches


def _covered_by_drivezone(geometry: BaseGeometry, drivezone_union: BaseGeometry) -> bool:
    tolerance = max(DEFAULT_RESOLUTION_M, 0.2)
    return drivezone_union.buffer(tolerance).covers(geometry)


def _is_rc_drivezone_validation_relevant(
    *,
    geometry: BaseGeometry,
    center: Point,
    buffer_m: float,
) -> bool:
    relevance_radius_m = max(RC_BRANCH_PROXIMITY_M, buffer_m - RC_OUTSIDE_DRIVEZONE_IGNORE_MARGIN_M)
    return geometry.distance(center) <= min(
        relevance_radius_m,
        RC_OUTSIDE_DRIVEZONE_RELEVANCE_MAX_DISTANCE_M,
    )


def _build_positive_negative_rc_groups(
    *,
    kind_2: int,
    road_branches: list[BranchEvidence],
    rc_branches: list[BranchEvidence],
    risks: list[str],
    has_rc_group_nodes: bool,
) -> tuple[set[str], set[str]]:
    rc_branch_by_id = {branch.branch_id: branch for branch in rc_branches}
    road_branch_by_id = {branch.branch_id: branch for branch in road_branches}
    positive: set[str] = set()
    negative: set[str] = set()

    side_branches = [branch for branch in road_branches if not branch.is_main_direction and branch.selected_for_polygon]
    if kind_2 == 2048 and not has_rc_group_nodes:
        candidates: dict[str, tuple[float, str]] = {}
        for branch in road_branches:
            if not branch.selected_for_polygon:
                continue
            for rc_group_id in branch.rcsdroad_ids:
                rc_branch = rc_branch_by_id[rc_group_id]
                score = rc_branch.road_support_m + branch.drivezone_support_m + branch.rc_support_m
                if not branch.is_main_direction:
                    score += 5.0
                current = candidates.get(rc_group_id)
                if current is None or score > current[0]:
                    candidates[rc_group_id] = (score, branch.branch_id)
        ranked_candidates = sorted(
            ((score, branch_id, rc_group_id) for rc_group_id, (score, branch_id) in candidates.items()),
            reverse=True,
        )
        if ranked_candidates:
            best_score = ranked_candidates[0][0]
            best_group = ranked_candidates[0][2]
            positive.add(best_group)
            if len(ranked_candidates) >= 2:
                second_score = ranked_candidates[1][0]
                if second_score >= max(best_score * 0.95, best_score - 3.0):
                    if STATUS_AMBIGUOUS_RC_MATCH not in risks:
                        risks.append(STATUS_AMBIGUOUS_RC_MATCH)
            for score, branch_id, rc_group_id in ranked_candidates[1:]:
                branch = road_branch_by_id.get(branch_id)
                if branch is None or branch.is_main_direction:
                    continue
                if not branch.selected_for_polygon or branch.evidence_level == "edge_only":
                    continue
                if (
                    branch.drivezone_support_m >= 40.0
                    and branch.road_support_m >= 20.0
                    and branch.rc_support_m >= 5.0
                ):
                    positive.add(rc_group_id)
            for _, _, rc_group_id in ranked_candidates:
                if rc_group_id not in positive:
                    negative.add(rc_group_id)
        return positive, negative

    for branch in road_branches:
        if branch.is_main_direction:
            for rc_group_id in branch.rcsdroad_ids:
                positive.add(rc_group_id)

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


def _has_structural_side_branch(road_branches: list[BranchEvidence]) -> bool:
    for branch in road_branches:
        if branch.is_main_direction or not branch.selected_for_polygon:
            continue
        if branch.evidence_level == "edge_only":
            continue
        if branch.drivezone_support_m >= 15.0 or branch.rc_support_m >= 8.0 or branch.road_support_m >= 25.0:
            return True
    return False


def _road_endpoint_infos(road: ParsedRoad, center: Point) -> tuple[tuple[str, Point, float], tuple[str, Point, float]]:
    line = _linearize(road.geometry)
    coords = list(line.coords)
    start_point = Point(coords[0])
    end_point = Point(coords[-1])
    return (
        (road.snodeid, start_point, float(start_point.distance(center))),
        (road.enodeid, end_point, float(end_point.distance(center))),
    )


def _road_angle_from_shared_node(road: ParsedRoad, node_id: str) -> float | None:
    line = _linearize(road.geometry)
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    if road.snodeid == node_id:
        anchor = coords[0]
        away = coords[1]
    elif road.enodeid == node_id:
        anchor = coords[-1]
        away = coords[-2]
    else:
        return None
    vector = (away[0] - anchor[0], away[1] - anchor[1])
    if math.hypot(vector[0], vector[1]) == 0.0:
        return None
    return _vector_to_angle_deg(_normalize_vector(vector))


def _select_positive_rc_road_ids(
    *,
    positive_rc_groups: set[str],
    negative_rc_groups: set[str],
    rc_branch_by_id: dict[str, BranchEvidence],
    local_rc_roads: list[ParsedRoad],
    center: Point,
    road_branches: list[BranchEvidence],
) -> tuple[set[str], set[str], set[str]]:
    positive_rc_road_ids: set[str] = set()
    polygon_included_adjacent_rc_road_ids: set[str] = set()
    polygon_excluded_rc_road_ids: set[str] = set()
    has_structural_side_branch = _has_structural_side_branch(road_branches)
    road_by_id = {road.road_id: road for road in local_rc_roads}

    for group_id in positive_rc_groups:
        group_road_ids = rc_branch_by_id[group_id].road_ids
        group_roads = [road_by_id[road_id] for road_id in group_road_ids if road_id in road_by_id]
        if not group_roads:
            continue

        chosen_roads: list[ParsedRoad]
        if not has_structural_side_branch:
            centered_two_way_roads = []
            for road in group_roads:
                endpoint_infos = _road_endpoint_infos(road, center)
                nearest_endpoint_distance = min(endpoint_infos[0][2], endpoint_infos[1][2])
                if nearest_endpoint_distance <= 18.0 and road.geometry.length >= 40.0:
                    centered_two_way_roads.append(road)
            if len(centered_two_way_roads) >= 2:
                chosen_roads = centered_two_way_roads
            else:
                closest_distance = min(road.geometry.distance(center) for road in group_roads)
                chosen_roads = [
                    road
                    for road in group_roads
                    if road.geometry.distance(center) <= closest_distance + 2.0
                ]
        else:
            closest_distance = min(road.geometry.distance(center) for road in group_roads)
            chosen_roads = [
                road
                for road in group_roads
                if road.geometry.distance(center) <= closest_distance + 2.0
            ]

        chosen_road_ids = {road.road_id for road in chosen_roads}
        positive_rc_road_ids.update(chosen_road_ids)
        polygon_excluded_rc_road_ids.update(set(group_road_ids) - chosen_road_ids)

        if has_structural_side_branch:
            for road in chosen_roads:
                start_info, end_info = _road_endpoint_infos(road, center)
                proximal_info, distal_info = (
                    (start_info, end_info) if start_info[2] <= end_info[2] else (end_info, start_info)
                )
                proximal_node_id = proximal_info[0]
                distal_node_id = distal_info[0]

                for candidate in local_rc_roads:
                    if candidate.road_id in chosen_road_ids:
                        continue
                    touches_proximal = candidate.snodeid == proximal_node_id or candidate.enodeid == proximal_node_id
                    touches_distal = candidate.snodeid == distal_node_id or candidate.enodeid == distal_node_id
                    if touches_proximal:
                        road_angle = _road_angle_from_shared_node(road, proximal_node_id)
                        candidate_angle = _road_angle_from_shared_node(candidate, proximal_node_id)
                        if (
                            road_angle is not None
                            and candidate_angle is not None
                            and _angle_diff_deg(road_angle, candidate_angle) >= 45.0
                            and candidate.geometry.length <= 40.0
                            and candidate.geometry.distance(center) <= proximal_info[2] + 12.0
                        ):
                            polygon_included_adjacent_rc_road_ids.add(candidate.road_id)
                    if touches_distal:
                        polygon_excluded_rc_road_ids.add(candidate.road_id)

    for group_id in negative_rc_groups:
        polygon_excluded_rc_road_ids.update(rc_branch_by_id[group_id].road_ids)

    polygon_excluded_rc_road_ids -= positive_rc_road_ids
    polygon_excluded_rc_road_ids -= polygon_included_adjacent_rc_road_ids
    return positive_rc_road_ids, polygon_included_adjacent_rc_road_ids, polygon_excluded_rc_road_ids


def _branch_uses_rc_tip_suppression(
    *,
    branch: BranchEvidence,
    positive_rc_groups: set[str],
    negative_rc_groups: set[str],
    rc_branch_by_id: dict[str, BranchEvidence],
    polygon_support_rc_road_ids: set[str],
) -> bool:
    if any(group_id in negative_rc_groups for group_id in branch.rcsdroad_ids):
        return True

    matched_positive_group_ids = [
        group_id for group_id in branch.rcsdroad_ids if group_id in positive_rc_groups
    ]
    if not matched_positive_group_ids:
        return False

    for group_id in matched_positive_group_ids:
        rc_branch = rc_branch_by_id.get(group_id)
        if rc_branch is None:
            continue
        if any(road_id in polygon_support_rc_road_ids for road_id in rc_branch.road_ids):
            return True
    return False


def _branch_has_positive_rc_gap(
    *,
    branch: BranchEvidence,
    positive_rc_groups: set[str],
    negative_rc_groups: set[str],
    rc_branch_by_id: dict[str, BranchEvidence],
    polygon_support_rc_road_ids: set[str],
) -> bool:
    if any(group_id in negative_rc_groups for group_id in branch.rcsdroad_ids):
        return False

    matched_positive_group_ids = [
        group_id for group_id in branch.rcsdroad_ids if group_id in positive_rc_groups
    ]
    if not matched_positive_group_ids:
        return False

    for group_id in matched_positive_group_ids:
        rc_branch = rc_branch_by_id.get(group_id)
        if rc_branch is None:
            continue
        if any(road_id in polygon_support_rc_road_ids for road_id in rc_branch.road_ids):
            return False
    return True


def _rc_gap_branch_polygon_length_m(branch: BranchEvidence) -> float:
    if branch.is_main_direction:
        return 0.0

    if branch.evidence_level == "arm_partial":
        return max(6.0, min(branch.drivezone_support_m, 12.0))

    if branch.evidence_level == "edge_only":
        local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 8.0))
        if local_support_m < 2.0:
            return 0.0
        return max(4.0, min(local_support_m, 6.0))

    return 0.0


def _local_road_mouth_polygon_length_m(branch: BranchEvidence) -> float:
    if (
        branch.road_support_m >= 12.0
        and branch.drivezone_support_m < 6.0
        and branch.rc_support_m < 4.0
    ):
        local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 10.0))
        return max(7.0, min(local_support_m, 10.0))
    local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 8.0))
    return max(6.0, min(local_support_m, 8.0))


def _branch_has_local_road_mouth(branch: BranchEvidence) -> bool:
    if (
        branch.is_main_direction
        or branch.evidence_level != "edge_only"
        or bool(branch.rcsdroad_ids)
    ):
        return False

    if branch.rc_support_m >= 12.0:
        return False

    if branch.drivezone_support_m >= 6.0 and branch.road_support_m >= 6.0:
        return True

    if (
        branch.road_support_m >= 7.0
        and branch.drivezone_support_m >= 1.0
        and branch.rc_support_m < 1.5
    ):
        return True

    return (
        (
            branch.road_support_m >= 12.0
            and branch.rc_support_m < 4.0
            and (
                branch.drivezone_support_m >= 4.0
                or (branch.drivezone_support_m >= 1.0 and branch.rc_support_m < 2.0)
            )
        )
        or (
            not branch.selected_for_polygon
            and branch.road_support_m >= 8.0
            and branch.drivezone_support_m >= 6.0
            and 5.0 <= branch.rc_support_m < 12.0
        )
    )


def _branch_has_minimal_local_road_touch(branch: BranchEvidence) -> bool:
    return (
        not branch.is_main_direction
        and not branch.selected_for_polygon
        and branch.evidence_level == "edge_only"
        and not branch.rcsdroad_ids
        and branch.rc_support_m < 2.5
        and branch.drivezone_support_m >= 2.0
        and branch.road_support_m >= 2.0
    )


def _minimal_local_road_touch_polygon_length_m(branch: BranchEvidence) -> float:
    local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 4.5))
    return max(4.0, min(local_support_m, 4.5))


def _branch_prefers_compact_local_support(
    branch: BranchEvidence,
    *,
    branch_has_local_road_mouth: bool,
    branch_has_minimal_local_road_touch: bool,
) -> bool:
    if branch.rcsdroad_ids:
        return False
    if branch_has_local_road_mouth or branch_has_minimal_local_road_touch:
        return True
    if (
        branch.selected_for_polygon
        and branch.evidence_level == "arm_partial"
        and branch.road_support_m >= 40.0
        and branch.drivezone_support_m >= 40.0
    ):
        return False
    return branch.selected_for_polygon


def _can_soft_exclude_outside_rc(
    *,
    status: str,
    selected_rc_road_count: int,
    polygon_support_rc_road_count: int,
    max_selected_side_branch_covered_length_m: float,
    max_nonmain_branch_polygon_length_m: float,
    min_invalid_rc_distance_to_center_m: float | None,
    connected_rc_group_count: int,
    negative_rc_group_count: int,
) -> bool:
    if (
        status == STATUS_SURFACE_ONLY
        and selected_rc_road_count == 0
        and polygon_support_rc_road_count == 0
        and connected_rc_group_count == 0
    ):
        return True
    if (
        selected_rc_road_count >= 2
        and polygon_support_rc_road_count >= 1
        and max_selected_side_branch_covered_length_m >= 7.0
    ):
        return True
    if (
        (selected_rc_road_count + polygon_support_rc_road_count) >= 1
        and max_selected_side_branch_covered_length_m >= 7.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= RC_OUTSIDE_DRIVEZONE_SOFT_EXCLUDE_MIN_DISTANCE_M
    ):
        return True
    if status == STATUS_NO_VALID_RC_CONNECTION:
        return True
    if (
        status == STATUS_STABLE
        and negative_rc_group_count >= 1
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and max_nonmain_branch_polygon_length_m >= 10.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_SURFACE_ONLY, STATUS_NODE_COMPONENT_CONFLICT}
        and selected_rc_road_count >= 2
        and polygon_support_rc_road_count >= 2
        and max_selected_side_branch_covered_length_m >= 12.0
    ):
        return True
    return False


def _build_local_branch_mouth_fan_geometry(
    *,
    center: Point,
    branch_geometries: list[BaseGeometry],
    drivezone_union: BaseGeometry,
    half_width: float,
) -> BaseGeometry:
    valid_geometries = [
        geometry for geometry in branch_geometries if geometry is not None and not geometry.is_empty
    ]
    if not valid_geometries:
        return GeometryCollection()

    center_seed = center.buffer(half_width * 1.1, join_style=1)
    return (
        unary_union([center_seed, *valid_geometries])
        .convex_hull.buffer(max(0.6, half_width * 0.18), join_style=1)
        .intersection(drivezone_union)
    )


def _build_excluded_rc_geometry(
    *,
    road: ParsedRoad,
    local_clip: BaseGeometry,
    drivezone_union: BaseGeometry,
    keep_node_union: BaseGeometry | None,
) -> BaseGeometry:
    local_geometry = road.geometry.intersection(local_clip)
    if local_geometry.is_empty:
        return GeometryCollection()
    exclusion_geometry = local_geometry.buffer(
        RC_ROAD_BUFFER_M * POLYGON_RC_EXCLUSION_BUFFER_FACTOR,
        cap_style=2,
        join_style=2,
    ).intersection(drivezone_union)
    if keep_node_union is not None and not keep_node_union.is_empty:
        exclusion_geometry = exclusion_geometry.difference(keep_node_union)
    return exclusion_geometry if not exclusion_geometry.is_empty else GeometryCollection()


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


def _polygon_branch_length_m(branch: BranchEvidence) -> float:
    if (
        branch.selected_for_polygon
        and not branch.is_main_direction
        and not branch.rcsdroad_ids
        and branch.evidence_level == "arm_partial"
        and branch.rc_support_m < 6.0
    ):
        local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 14.0))
        hard_cap = (
            14.0
            if branch.drivezone_support_m >= 40.0 and branch.road_support_m >= 40.0
            else 10.0
        )
        return max(7.0, min(local_support_m, hard_cap))

    if (
        not branch.is_main_direction
        and not branch.rcsdroad_ids
        and branch.rc_support_m <= 1.0
        and branch.drivezone_support_m < 26.0
        and branch.road_support_m < 18.0
    ):
        return max(3.0, min(branch.drivezone_support_m, 4.0))

    if branch.is_main_direction:
        hard_cap = 20.0 if branch.evidence_level == "arm_full_rc" else 16.0
        return max(8.0, min(branch.drivezone_support_m, hard_cap))

    if (
        not branch.rcsdroad_ids
        and branch.rc_support_m < 5.0
        and branch.drivezone_support_m < 30.0
        and branch.road_support_m < 25.0
    ):
        return max(4.0, min(branch.drivezone_support_m, 5.0))

    if branch.evidence_level == "arm_full_rc":
        return max(6.0, min(branch.drivezone_support_m, 14.0))
    if branch.evidence_level == "arm_partial":
        return max(5.0, min(branch.drivezone_support_m, 8.0))
    return 0.0


def _point_along_branch(center: Point, *, angle_deg: float, distance_m: float) -> Point:
    radians = math.radians(angle_deg)
    return Point(
        center.x + math.cos(radians) * distance_m,
        center.y + math.sin(radians) * distance_m,
    )


def _seed_rc_road_ids_for_polygon_support(
    *,
    group_nodes: list[ParsedNode],
    local_rc_roads: list[ParsedRoad],
    analysis_center: Point,
    base_seed_road_ids: set[str],
) -> set[str]:
    seed_road_ids = set(base_seed_road_ids)
    anchor_points = [node.geometry for node in group_nodes] or [analysis_center]
    anchor_points = [*anchor_points, analysis_center]

    for anchor_point in anchor_points:
        distance_rows = sorted(
            (float(road.geometry.distance(anchor_point)), road.road_id)
            for road in local_rc_roads
        )
        if not distance_rows:
            continue
        threshold_m = min(
            POLYGON_SUPPORT_EXPANSION_MAX_DISTANCE_M,
            max(POLYGON_SUPPORT_SEED_MAX_DISTANCE_M, distance_rows[0][0] + POLYGON_SUPPORT_SEED_MARGIN_M),
        )
        for distance_m, road_id in distance_rows:
            if distance_m > threshold_m:
                break
            seed_road_ids.add(road_id)

    return seed_road_ids


def _build_polygon_support_rc_subgraph(
    *,
    local_rc_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    group_nodes: list[ParsedNode],
    analysis_center: Point,
    seed_road_ids: set[str],
    base_support_node_ids: set[str],
) -> tuple[set[str], set[str]]:
    road_by_id = {road.road_id: road for road in local_rc_roads}
    rc_node_by_id = {node.node_id: node for node in local_rc_nodes}
    road_ids_by_node: dict[str, set[str]] = {}
    for road in local_rc_roads:
        road_ids_by_node.setdefault(road.snodeid, set()).add(road.road_id)
        road_ids_by_node.setdefault(road.enodeid, set()).add(road.road_id)

    anchor_geometries: list[BaseGeometry] = [analysis_center]
    anchor_geometries.extend(node.geometry for node in group_nodes)
    anchor_geometries.extend(
        rc_node_by_id[node_id].geometry
        for node_id in base_support_node_ids
        if node_id in rc_node_by_id
    )
    anchor_union = unary_union(anchor_geometries) if anchor_geometries else analysis_center

    support_road_ids: set[str] = set()
    support_node_ids = set(base_support_node_ids)
    queue: deque[tuple[str, int]] = deque()
    queued_road_ids: set[str] = set()
    for road_id in seed_road_ids:
        if road_id not in road_by_id or road_id in queued_road_ids:
            continue
        queued_road_ids.add(road_id)
        queue.append((road_id, 0))

    while queue:
        road_id, hop = queue.popleft()
        road = road_by_id[road_id]
        if hop > 0 and road.geometry.distance(anchor_union) > POLYGON_SUPPORT_EXPANSION_MAX_DISTANCE_M:
            continue

        support_road_ids.add(road_id)
        for node_id in (road.snodeid, road.enodeid):
            if node_id in rc_node_by_id:
                support_node_ids.add(node_id)
            if hop >= POLYGON_SUPPORT_EXPANSION_HOPS:
                continue
            for neighbor_road_id in road_ids_by_node.get(node_id, set()):
                if neighbor_road_id in queued_road_ids:
                    continue
                neighbor_road = road_by_id[neighbor_road_id]
                if (
                    neighbor_road_id not in seed_road_ids
                    and neighbor_road.geometry.distance(anchor_union) > POLYGON_SUPPORT_EXPANSION_MAX_DISTANCE_M
                ):
                    continue
                queued_road_ids.add(neighbor_road_id)
                queue.append((neighbor_road_id, hop + 1))

    return support_road_ids, support_node_ids


def _min_distance_to_group_nodes(
    node: ParsedNode | None,
    *,
    group_nodes: list[ParsedNode],
) -> float:
    if node is None or not group_nodes:
        return math.inf
    return min(float(node.geometry.distance(group_node.geometry)) for group_node in group_nodes)


def _collect_local_polygon_support_node_ids(
    *,
    support_road_ids: set[str],
    base_support_node_ids: set[str],
    road_by_id: dict[str, ParsedRoad],
    rc_node_by_id: dict[str, ParsedNode],
    group_nodes: list[ParsedNode],
) -> set[str]:
    support_node_ids = {
        node_id
        for node_id in base_support_node_ids
        if node_id in rc_node_by_id
    }
    support_degree_by_node_id: Counter[str] = Counter()
    for road_id in support_road_ids:
        road = road_by_id.get(road_id)
        if road is None:
            continue
        for node_id in (road.snodeid, road.enodeid):
            if node_id in rc_node_by_id:
                support_degree_by_node_id[node_id] += 1

    for node_id, degree in support_degree_by_node_id.items():
        if node_id in support_node_ids or degree >= 2:
            support_node_ids.add(node_id)
            continue
        if (
            _min_distance_to_group_nodes(
                rc_node_by_id.get(node_id),
                group_nodes=group_nodes,
            )
            <= POLYGON_SUPPORT_NODE_LOCAL_GROUP_DISTANCE_M
        ):
            support_node_ids.add(node_id)
    return support_node_ids


def _build_polygon_support_from_association(
    *,
    positive_rc_road_ids: set[str],
    base_support_node_ids: set[str],
    excluded_rc_road_ids: set[str],
    local_rc_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    group_nodes: list[ParsedNode],
) -> tuple[set[str], set[str], bool]:
    road_by_id = {road.road_id: road for road in local_rc_roads}
    rc_node_by_id = {node.node_id: node for node in local_rc_nodes}
    support_road_ids = {road_id for road_id in positive_rc_road_ids if road_id in road_by_id}

    def _endpoint_extension_candidates(
        shared_node_id: str,
        *,
        max_length_m: float,
        max_other_group_distance_m: float | None,
    ) -> list[tuple[float, str]]:
        shared_node = rc_node_by_id.get(shared_node_id)
        shared_group_distance_m = _min_distance_to_group_nodes(shared_node, group_nodes=group_nodes)
        base_road = next((road_by_id[road_id] for road_id in support_road_ids if shared_node_id in {road_by_id[road_id].snodeid, road_by_id[road_id].enodeid}), None)
        base_angle = _road_angle_from_shared_node(base_road, shared_node_id) if base_road is not None else None
        candidates: list[tuple[float, str]] = []
        for candidate in local_rc_roads:
            if candidate.road_id in support_road_ids or candidate.road_id in excluded_rc_road_ids:
                continue
            if shared_node_id not in {candidate.snodeid, candidate.enodeid}:
                continue
            if candidate.geometry.length > max_length_m:
                continue

            other_node_id = candidate.enodeid if candidate.snodeid == shared_node_id else candidate.snodeid
            other_node = rc_node_by_id.get(other_node_id)
            if other_node is None:
                continue
            other_group_distance_m = _min_distance_to_group_nodes(other_node, group_nodes=group_nodes)
            if (
                max_other_group_distance_m is not None
                and other_group_distance_m > max_other_group_distance_m
            ):
                continue
            candidate_angle = _road_angle_from_shared_node(candidate, shared_node_id)
            angle_diff_deg = (
                _angle_diff_deg(base_angle, candidate_angle)
                if base_angle is not None and candidate_angle is not None
                else 180.0
            )
            matches_endpoint_direction = angle_diff_deg <= POLYGON_ENDPOINT_SUPPORT_ANGLE_TOLERANCE_DEG
            preserves_group_proximity = (
                other_group_distance_m <= shared_group_distance_m + POLYGON_ENDPOINT_SUPPORT_GROUP_DISTANCE_MARGIN_M
            )
            if not matches_endpoint_direction and not preserves_group_proximity:
                continue

            score = float(candidate.geometry.length)
            if matches_endpoint_direction:
                score -= 8.0
            if preserves_group_proximity:
                score -= 4.0
            if other_node_id in base_support_node_ids:
                score -= 6.0
            score += other_group_distance_m * 0.05
            candidates.append((score, candidate.road_id))
        candidates.sort()
        return candidates

    endpoint_extension_selected = False
    if len(support_road_ids) == 1:
        selected_road = road_by_id[next(iter(support_road_ids))]
        local_endpoint_ids = [
            node_id
            for node_id in (selected_road.snodeid, selected_road.enodeid)
            if node_id in rc_node_by_id
        ]
        if len(local_endpoint_ids) == 2:
            for shared_node_id in local_endpoint_ids:
                candidates = _endpoint_extension_candidates(
                    shared_node_id,
                    max_length_m=POLYGON_ENDPOINT_SUPPORT_MAX_LENGTH_M,
                    max_other_group_distance_m=None,
                )
                if not candidates:
                    continue
                best_road_id = candidates[0][1]
                support_road_ids.add(best_road_id)
                endpoint_extension_selected = True
        elif len(local_endpoint_ids) == 1:
            shared_node_id = local_endpoint_ids[0]
            shared_group_distance_m = _min_distance_to_group_nodes(
                rc_node_by_id.get(shared_node_id),
                group_nodes=group_nodes,
            )
            if shared_group_distance_m <= POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_GROUP_DISTANCE_M:
                candidates = _endpoint_extension_candidates(
                    shared_node_id,
                    max_length_m=POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_LENGTH_M,
                    max_other_group_distance_m=POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_GROUP_DISTANCE_M,
                )
                if candidates:
                    best_road_id = candidates[0][1]
                    support_road_ids.add(best_road_id)
                    endpoint_extension_selected = True

    orphan_positive_support = False
    if len(support_road_ids) == 1 and not endpoint_extension_selected:
        only_road = road_by_id[next(iter(support_road_ids))]
        endpoint_line = _linearize(only_road.geometry)
        endpoint_points = [Point(endpoint_line.coords[0]), Point(endpoint_line.coords[-1])]
        endpoint_distances = [
            min(float(endpoint_point.distance(group_node.geometry)) for group_node in group_nodes)
            if group_nodes
            else math.inf
            for endpoint_point in endpoint_points
        ]
        if endpoint_distances and min(endpoint_distances) > POLYGON_ENDPOINT_SUPPORT_ORPHAN_GROUP_DISTANCE_M:
            orphan_positive_support = True
            support_road_ids.clear()

    support_node_ids = _collect_local_polygon_support_node_ids(
        support_road_ids=support_road_ids,
        base_support_node_ids=base_support_node_ids,
        road_by_id=road_by_id,
        rc_node_by_id=rc_node_by_id,
        group_nodes=group_nodes,
    )

    bridge_candidates: list[ParsedRoad] = []
    for road in local_rc_roads:
        if road.road_id in support_road_ids or road.road_id in excluded_rc_road_ids:
            continue
        if road.geometry.length > POLYGON_ENDPOINT_SUPPORT_MAX_LENGTH_M:
            continue
        if road.snodeid in support_node_ids and road.enodeid in support_node_ids:
            bridge_candidates.append(road)
    for road in bridge_candidates:
        support_road_ids.add(road.road_id)
    support_node_ids = _collect_local_polygon_support_node_ids(
        support_road_ids=support_road_ids,
        base_support_node_ids=base_support_node_ids,
        road_by_id=road_by_id,
        rc_node_by_id=rc_node_by_id,
        group_nodes=group_nodes,
    )

    return support_road_ids, support_node_ids, orphan_positive_support


def _build_polygon_support_clip(
    *,
    analysis_center: Point,
    group_nodes: list[ParsedNode],
    local_rc_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    support_road_ids: set[str],
    support_node_ids: set[str],
) -> BaseGeometry:
    clip_geometries: list[BaseGeometry] = [analysis_center.buffer(POLYGON_LOCAL_RC_SEGMENT_EXTENSION_M)]
    clip_geometries.extend(
        node.geometry.buffer(POLYGON_SUPPORT_CLIP_RADIUS_M)
        for node in group_nodes
    )
    clip_geometries.extend(
        road.geometry
        for road in local_rc_roads
        if (
            road.road_id in support_road_ids
            and road.snodeid in support_node_ids
            and road.enodeid in support_node_ids
        )
    )
    clip_geometries.extend(
        node.geometry.buffer(POLYGON_SUPPORT_CLIP_RADIUS_M)
        for node in local_rc_nodes
        if node.node_id in support_node_ids
    )
    clip_geometries = [geometry for geometry in clip_geometries if not geometry.is_empty]
    if not clip_geometries:
        return analysis_center.buffer(POLYGON_LOCAL_RC_SEGMENT_EXTENSION_M)
    return unary_union(clip_geometries).buffer(POLYGON_SUPPORT_CLIP_BUFFER_M)


def _validate_polygon_support(
    *,
    polygon_geometry: BaseGeometry,
    group_nodes: list[ParsedNode],
    local_rc_nodes: list[ParsedNode],
    local_rc_roads: list[ParsedRoad],
    support_node_ids: set[str],
    support_road_ids: set[str],
    support_clip: BaseGeometry,
) -> tuple[list[str], list[str], list[str]]:
    polygon_cover = polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)

    uncovered_group_node_ids = [
        node.node_id
        for node in group_nodes
        if not polygon_cover.covers(node.geometry)
    ]
    uncovered_support_node_ids = [
        node.node_id
        for node in local_rc_nodes
        if node.node_id in support_node_ids and not polygon_cover.covers(node.geometry)
    ]

    uncovered_support_road_ids: list[str] = []
    for road in local_rc_roads:
        if road.road_id not in support_road_ids:
            continue
        local_geometry = road.geometry.intersection(support_clip)
        if local_geometry.is_empty or local_geometry.length <= 1.0:
            continue
        covered_ratio = float(local_geometry.intersection(polygon_cover).length) / float(local_geometry.length)
        if covered_ratio < POLYGON_SUPPORT_MIN_LINE_COVERAGE_RATIO:
            uncovered_support_road_ids.append(road.road_id)

    return uncovered_group_node_ids, uncovered_support_node_ids, uncovered_support_road_ids


def _fill_small_polygon_holes(
    geometry: BaseGeometry,
    *,
    max_hole_area_m2: float,
) -> BaseGeometry:
    if geometry.is_empty:
        return geometry

    if isinstance(geometry, Polygon):
        kept_interiors = [
            ring.coords
            for ring in geometry.interiors
            if Polygon(ring).area > max_hole_area_m2
        ]
        return Polygon(geometry.exterior.coords, kept_interiors)

    if isinstance(geometry, MultiPolygon):
        return MultiPolygon(
            [
                polygon
                for polygon in (
                    _fill_small_polygon_holes(part, max_hole_area_m2=max_hole_area_m2)
                    for part in geometry.geoms
                )
                if isinstance(polygon, Polygon) and not polygon.is_empty
            ]
        )

    return geometry


def _remove_all_polygon_holes(geometry: BaseGeometry) -> BaseGeometry:
    if geometry.is_empty:
        return geometry

    if isinstance(geometry, Polygon):
        return Polygon(geometry.exterior.coords)

    if isinstance(geometry, MultiPolygon):
        polygons = [
            Polygon(polygon.exterior.coords)
            for polygon in geometry.geoms
            if not polygon.is_empty
        ]
        if not polygons:
            return GeometryCollection()
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)

    return geometry


def _polygon_components(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [polygon for polygon in geometry.geoms if not polygon.is_empty]
    return []


def _is_foreign_local_junction_node(
    *,
    node: ParsedNode,
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
) -> bool:
    if node.node_id in target_group_node_ids:
        return False
    if node.mainnodeid is not None:
        return node.mainnodeid != normalized_mainnodeid
    return (
        node.has_evd == "yes"
        or node.is_anchor == "yes"
        or node.kind_2 in ALLOWED_KIND_2_VALUES
    )


def _build_foreign_node_exclusion_geometry(
    *,
    polygon_geometry: BaseGeometry,
    normalized_mainnodeid: str,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    allowed_road_ids: set[str],
    drivezone_union: BaseGeometry,
) -> BaseGeometry:
    if polygon_geometry.is_empty:
        return GeometryCollection()

    target_group_node_ids = {node.node_id for node in group_nodes}
    exclusion_geometries: list[BaseGeometry] = []
    for node in local_nodes:
        if not _is_foreign_local_junction_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
        ):
            continue
        if polygon_geometry.distance(node.geometry) > POLYGON_FOREIGN_NODE_TRIGGER_DISTANCE_M:
            continue
        node_buffer = node.geometry.buffer(POLYGON_FOREIGN_NODE_BUFFER_M).intersection(drivezone_union)
        if not node_buffer.is_empty:
            exclusion_geometries.append(node_buffer)
        incident_clip = node.geometry.buffer(POLYGON_FOREIGN_NODE_ROAD_EXTENSION_M)
        for road in local_roads:
            if road.snodeid != node.node_id and road.enodeid != node.node_id:
                continue
            local_geometry = (
                road.geometry
                if road.road_id not in allowed_road_ids
                else road.geometry.intersection(incident_clip)
            )
            if local_geometry.is_empty or local_geometry.length <= 0.5:
                continue
            if (
                road.road_id not in allowed_road_ids
                and polygon_geometry.intersection(local_geometry).length <= 1.0
            ):
                continue
            road_buffer = local_geometry.buffer(
                POLYGON_FOREIGN_NODE_ROAD_BUFFER_M,
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if not road_buffer.is_empty:
                exclusion_geometries.append(road_buffer)

    if not exclusion_geometries:
        return GeometryCollection()
    return unary_union(exclusion_geometries)


def _is_foreign_rc_drivezone_violation(
    *,
    geometry: BaseGeometry,
    representative_node: ParsedNode,
    normalized_mainnodeid: str,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
) -> bool:
    representative_distance_m = float(geometry.distance(representative_node.geometry))
    if representative_distance_m < 20.0:
        return False

    target_group_node_ids = {node.node_id for node in group_nodes}
    foreign_distances = [
        float(geometry.distance(node.geometry))
        for node in local_nodes
        if _is_foreign_local_junction_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
        )
    ]
    if not foreign_distances:
        return False
    return min(foreign_distances) + 3.0 < representative_distance_m


def _select_seed_connected_polygon(
    *,
    geometry: BaseGeometry,
    seed_geometry: BaseGeometry,
) -> BaseGeometry:
    components = [
        component
        for component in _polygon_components(geometry)
        if component.area > POLYGON_FINAL_COMPONENT_MIN_AREA_M2
    ]
    if not components:
        return GeometryCollection()

    seeded_components = [component for component in components if component.intersects(seed_geometry)]
    if seeded_components:
        selected = max(seeded_components, key=lambda component: component.area)
    else:
        selected = min(
            components,
            key=lambda component: (component.distance(seed_geometry), -component.area),
        )
    return selected.buffer(0)


def _regularize_virtual_polygon_geometry(
    *,
    geometry: BaseGeometry,
    drivezone_union: BaseGeometry,
    seed_geometry: BaseGeometry,
) -> BaseGeometry:
    if geometry.is_empty:
        return geometry

    regularized = geometry.intersection(drivezone_union)
    if regularized.is_empty:
        return regularized

    regularized = regularized.buffer(0)
    regularized = _fill_small_polygon_holes(
        regularized,
        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
    )
    regularized = regularized.buffer(POLYGON_FINAL_SMOOTH_M, join_style=1).buffer(
        -POLYGON_FINAL_SMOOTH_M,
        join_style=1,
    )
    regularized = regularized.intersection(drivezone_union)
    if regularized.is_empty:
        return regularized
    regularized = regularized.buffer(0)
    regularized = _fill_small_polygon_holes(
        regularized,
        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
    )
    regularized = _remove_all_polygon_holes(regularized)
    regularized = _select_seed_connected_polygon(
        geometry=regularized,
        seed_geometry=seed_geometry,
    )
    return regularized.intersection(drivezone_union).buffer(0) if not regularized.is_empty else regularized


def _write_association_outputs(
    *,
    vector_path: Path,
    audit_csv_path: Path,
    audit_json_path: Path,
    features: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> None:
    write_vector(vector_path, features)
    write_csv(audit_csv_path, audits, fieldnames=ASSOCIATION_AUDIT_FIELDNAMES)
    write_json(audit_json_path, audits)


def _status_from_risks(risks: list[str], *, has_associated_roads: bool) -> str:
    if STATUS_AMBIGUOUS_RC_MATCH in risks:
        return STATUS_AMBIGUOUS_RC_MATCH
    if STATUS_NO_VALID_RC_CONNECTION in risks:
        return STATUS_NO_VALID_RC_CONNECTION
    if STATUS_NODE_COMPONENT_CONFLICT in risks:
        return STATUS_NODE_COMPONENT_CONFLICT
    if STATUS_WEAK_BRANCH_SUPPORT in risks:
        return STATUS_WEAK_BRANCH_SUPPORT
    if has_associated_roads:
        return STATUS_STABLE
    return STATUS_SURFACE_ONLY


def _max_selected_side_branch_covered_length_m(
    *,
    polygon_geometry: BaseGeometry,
    road_branches: list[BranchEvidence],
    local_roads: list[ParsedRoad],
) -> float:
    road_by_id = {road.road_id: road for road in local_roads}
    max_covered_length_m = 0.0
    for branch in road_branches:
        if branch.is_main_direction or not branch.selected_for_polygon:
            continue
        if branch.evidence_level == "edge_only":
            continue
        for road_id in branch.road_ids:
            road = road_by_id.get(road_id)
            if road is None:
                continue
            covered_length_m = polygon_geometry.intersection(road.geometry).length
            if covered_length_m > max_covered_length_m:
                max_covered_length_m = float(covered_length_m)
    return max_covered_length_m


def _max_nonmain_branch_polygon_length_m(*, road_branches: list[BranchEvidence]) -> float:
    max_polygon_length_m = 0.0
    for branch in road_branches:
        if branch.is_main_direction:
            continue
        polygon_length_m = float(branch.polygon_length_m or 0.0)
        if polygon_length_m > max_polygon_length_m:
            max_polygon_length_m = polygon_length_m
    return max_polygon_length_m


def _effect_success_acceptance(
    *,
    status: str,
    review_mode: bool,
    max_selected_side_branch_covered_length_m: float,
    max_nonmain_branch_polygon_length_m: float,
    associated_rc_road_count: int,
    polygon_support_rc_road_count: int,
    min_invalid_rc_distance_to_center_m: float | None,
    local_rc_road_count: int,
    local_rc_node_count: int,
    connected_rc_group_count: int,
    nonmain_branch_connected_rc_group_count: int,
) -> tuple[bool, str, str]:
    if review_mode:
        return False, "review_required", "review_mode"
    if status == STATUS_STABLE:
        return True, "accepted", "stable"
    if status == STATUS_SURFACE_ONLY:
        if local_rc_road_count == 0 and local_rc_node_count == 0:
            return True, "accepted", "surface_only_without_any_local_rcsd_data"
        if (
            connected_rc_group_count == 0
            and associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
        ):
            return True, "accepted", "surface_only_without_connected_local_rcsd_evidence"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_NO_VALID_RC_CONNECTION:
        if (
            connected_rc_group_count == 0
            and associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and local_rc_node_count == 0
        ):
            return True, "accepted", "rc_gap_without_connected_local_rcsd_evidence"
        if max_nonmain_branch_polygon_length_m >= 4.0:
            return True, "accepted", "rc_gap_with_nonmain_branch_polygon_coverage"
        return False, "review_required", "rc_gap_without_substantive_nonmain_branch_coverage"
    if status == STATUS_NODE_COMPONENT_CONFLICT:
        if (
            polygon_support_rc_road_count >= 2
            and associated_rc_road_count >= 2
            and max_selected_side_branch_covered_length_m >= 12.0
            and max_nonmain_branch_polygon_length_m >= 10.0
        ):
            return True, "accepted", "node_component_conflict_with_strong_rc_supported_side_coverage"
        if (
            polygon_support_rc_road_count >= 1
            and associated_rc_road_count >= 1
            and max_selected_side_branch_covered_length_m >= 18.0
            and max_nonmain_branch_polygon_length_m >= 10.0
            and min_invalid_rc_distance_to_center_m is not None
            and min_invalid_rc_distance_to_center_m >= 25.0
        ):
            return True, "accepted", "node_component_conflict_with_remote_outside_rc_gap"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_WEAK_BRANCH_SUPPORT:
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_AMBIGUOUS_RC_MATCH:
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and nonmain_branch_connected_rc_group_count == 0
            and max_selected_side_branch_covered_length_m >= 10.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_nonmain_branch_polygon_coverage"
        return False, "review_required", f"review_required_status:{status}"
    return False, "rejected", f"rejected_status:{status}"


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
    debug: bool = False,
    debug_render_root: Optional[Union[str, Path]] = None,
    review_mode: bool = False,
    trace_memory: bool = True,
    layer_loader: Callable[..., LoadedLayer] | None = None,
    target_group_loader: Callable[[str], LoadedLayer] | None = None,
) -> VirtualIntersectionArtifacts:
    if trace_memory:
        tracemalloc.start()
    started_at = time.perf_counter()

    out_root_path, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    out_root_path.mkdir(parents=True, exist_ok=True)

    virtual_polygon_path = out_root_path / "virtual_intersection_polygon.gpkg"
    branch_evidence_json_path = out_root_path / "branch_evidence.json"
    branch_evidence_geojson_path = out_root_path / "branch_evidence.gpkg"
    associated_rcsdroad_path = out_root_path / "associated_rcsdroad.gpkg"
    associated_rcsdroad_audit_csv_path = out_root_path / "associated_rcsdroad_audit.csv"
    associated_rcsdroad_audit_json_path = out_root_path / "associated_rcsdroad_audit.json"
    associated_rcsdnode_path = out_root_path / "associated_rcsdnode.gpkg"
    associated_rcsdnode_audit_csv_path = out_root_path / "associated_rcsdnode_audit.csv"
    associated_rcsdnode_audit_json_path = out_root_path / "associated_rcsdnode_audit.json"
    status_path = out_root_path / "t02_virtual_intersection_poc_status.json"
    audit_csv_path = out_root_path / "t02_virtual_intersection_poc_audit.csv"
    audit_json_path = out_root_path / "t02_virtual_intersection_poc_audit.json"
    log_path = out_root_path / "t02_virtual_intersection_poc.log"
    progress_path = out_root_path / "t02_virtual_intersection_poc_progress.json"
    perf_json_path = out_root_path / "t02_virtual_intersection_poc_perf.json"
    perf_markers_path = out_root_path / "t02_virtual_intersection_poc_perf_markers.jsonl"
    debug_render_root_path = (
        Path(debug_render_root)
        if debug_render_root is not None
        else out_root_path.parent / "_rendered_maps"
    )
    rendered_map_path = debug_render_root_path / f"{_normalize_id(mainnodeid) or 'unknown'}.png"

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
    risks: list[str] = []
    normalized_mainnodeid = _normalize_id(mainnodeid)
    debug_rendered_map_written = False
    load_layer_filtered = layer_loader or _load_layer_filtered

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
        if normalized_mainnodeid is None:
            raise VirtualIntersectionPocError(REASON_MAINNODEID_NOT_FOUND, "mainnodeid is empty.")

        def _target_group_match(properties: dict[str, Any]) -> bool:
            node_id = _normalize_id(properties.get("id"))
            group_id = _normalize_id(properties.get("mainnodeid"))
            return group_id == normalized_mainnodeid or (group_id is None and node_id == normalized_mainnodeid)

        if target_group_loader is not None:
            target_nodes_layer_data = target_group_loader(normalized_mainnodeid)
        else:
            target_nodes_layer_data = load_layer_filtered(
                nodes_path,
                layer_name=nodes_layer,
                crs_override=nodes_crs,
                allow_null_geometry=False,
                property_predicate=_target_group_match,
            )
        target_group_nodes = _parse_nodes(target_nodes_layer_data, require_anchor_fields=True)
        counts["target_group_candidate_count"] = len(target_group_nodes)
        representative_node, group_nodes = _resolve_group(mainnodeid=normalized_mainnodeid, nodes=target_group_nodes)
        out_of_scope_error: VirtualIntersectionPocError | None = None
        if representative_node.has_evd != "yes" or representative_node.kind_2 not in ALLOWED_KIND_2_VALUES:
            out_of_scope_error = VirtualIntersectionPocError(
                REASON_MAINNODEID_OUT_OF_SCOPE,
                (
                    f"mainnodeid='{normalized_mainnodeid}' is out of scope: "
                    f"has_evd={representative_node.has_evd}, is_anchor={representative_node.is_anchor}, "
                    f"kind_2={representative_node.kind_2}."
                ),
            )
        if out_of_scope_error is not None and not debug:
            raise out_of_scope_error

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

        local_nodes_layer_data = load_layer_filtered(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
            query_geometry=patch_query,
            progress_label="local_nodes",
            progress_callback=report_local_scan,
        )
        local_nodes = _parse_nodes(local_nodes_layer_data, require_anchor_fields=False)
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

        roads_layer_data = load_layer_filtered(
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

        drivezone_layer_data = load_layer_filtered(
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

        rcsdroad_layer_data = load_layer_filtered(
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

        rcsdnode_layer_data = load_layer_filtered(
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
        if out_of_scope_error is not None:
            if debug:
                try:
                    _write_failure_debug_rendered_map(
                        out_path=rendered_map_path,
                        representative_node=representative_node,
                        group_nodes=group_nodes,
                        local_nodes=local_nodes,
                        local_roads=local_roads,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        drivezone_union=drivezone_union,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        failure_reason=out_of_scope_error.reason,
                    )
                    debug_rendered_map_written = True
                    announce(
                        logger,
                        (
                            "[T02-POC] wrote failure debug rendered map "
                            f"path={rendered_map_path} reason={out_of_scope_error.reason}"
                        ),
                    )
                except Exception as exc:
                    announce(logger, f"[T02-POC] failure debug rendered map skipped reason={type(exc).__name__}: {exc}")
            raise out_of_scope_error
        invalid_rc_road_ids: set[str] = set()
        invalid_rc_node_ids: set[str] = set()
        rc_outside_drivezone_error: VirtualIntersectionPocError | None = None
        min_invalid_rc_distance_to_center_m: float | None = None
        for rc_road in local_rc_roads:
            if _covered_by_drivezone(rc_road.geometry, drivezone_union):
                continue
            if not _is_rc_drivezone_validation_relevant(
                geometry=rc_road.geometry,
                center=representative_node.geometry,
                buffer_m=buffer_m,
            ):
                continue
            if _is_foreign_rc_drivezone_violation(
                geometry=rc_road.geometry,
                representative_node=representative_node,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
            ):
                continue
            if not review_mode:
                invalid_rc_road_ids.add(rc_road.road_id)
                invalid_distance_m = float(rc_road.geometry.distance(representative_node.geometry))
                min_invalid_rc_distance_to_center_m = (
                    invalid_distance_m
                    if min_invalid_rc_distance_to_center_m is None
                    else min(min_invalid_rc_distance_to_center_m, invalid_distance_m)
                )
                if rc_outside_drivezone_error is None:
                    rc_outside_drivezone_error = VirtualIntersectionPocError(
                        REASON_RC_OUTSIDE_DRIVEZONE,
                        f"RCSDRoad id='{rc_road.road_id}' is not fully covered by DriveZone within the local patch.",
                    )
                continue
            invalid_rc_road_ids.add(rc_road.road_id)
            invalid_distance_m = float(rc_road.geometry.distance(representative_node.geometry))
            min_invalid_rc_distance_to_center_m = (
                invalid_distance_m
                if min_invalid_rc_distance_to_center_m is None
                else min(min_invalid_rc_distance_to_center_m, invalid_distance_m)
            )
            audit_rows.append(
                _audit_row(
                    scope="virtual_intersection_poc",
                    status="warning",
                    reason=STATUS_REVIEW_RC_OUTSIDE_DRIVEZONE_EXCLUDED,
                    detail=(
                        f"review_mode excluded RCSDRoad id='{rc_road.road_id}' because it is not fully "
                        "covered by DriveZone within the local patch."
                    ),
                    mainnodeid=normalized_mainnodeid,
                    feature_id=rc_road.road_id,
                )
            )
        for rc_node in local_rc_nodes:
            if _covered_by_drivezone(rc_node.geometry.buffer(max(resolution_m, 0.2)), drivezone_union):
                continue
            if not _is_rc_drivezone_validation_relevant(
                geometry=rc_node.geometry,
                center=representative_node.geometry,
                buffer_m=buffer_m,
            ):
                continue
            if _is_foreign_rc_drivezone_violation(
                geometry=rc_node.geometry,
                representative_node=representative_node,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
            ):
                continue
            if not review_mode:
                invalid_rc_node_ids.add(rc_node.node_id)
                invalid_distance_m = float(rc_node.geometry.distance(representative_node.geometry))
                min_invalid_rc_distance_to_center_m = (
                    invalid_distance_m
                    if min_invalid_rc_distance_to_center_m is None
                    else min(min_invalid_rc_distance_to_center_m, invalid_distance_m)
                )
                if rc_outside_drivezone_error is None:
                    rc_outside_drivezone_error = VirtualIntersectionPocError(
                        REASON_RC_OUTSIDE_DRIVEZONE,
                        f"RCSDNode id='{rc_node.node_id}' is not covered by DriveZone within the local patch.",
                    )
                continue
            invalid_rc_node_ids.add(rc_node.node_id)
            invalid_distance_m = float(rc_node.geometry.distance(representative_node.geometry))
            min_invalid_rc_distance_to_center_m = (
                invalid_distance_m
                if min_invalid_rc_distance_to_center_m is None
                else min(min_invalid_rc_distance_to_center_m, invalid_distance_m)
            )
            audit_rows.append(
                _audit_row(
                    scope="virtual_intersection_poc",
                    status="warning",
                    reason=STATUS_REVIEW_RC_OUTSIDE_DRIVEZONE_EXCLUDED,
                    detail=(
                        f"review_mode excluded RCSDNode id='{rc_node.node_id}' because it is not covered "
                        "by DriveZone within the local patch."
                    ),
                    mainnodeid=normalized_mainnodeid,
                    feature_id=rc_node.node_id,
                )
            )
        if invalid_rc_road_ids or invalid_rc_node_ids:
            if STATUS_REVIEW_RC_OUTSIDE_DRIVEZONE_EXCLUDED not in risks:
                if review_mode:
                    risks.append(STATUS_REVIEW_RC_OUTSIDE_DRIVEZONE_EXCLUDED)
            local_rc_roads = [road for road in local_rc_roads if road.road_id not in invalid_rc_road_ids]
            local_rc_nodes = [node for node in local_rc_nodes if node.node_id not in invalid_rc_node_ids]
            counts["review_excluded_rcsdroad_count" if review_mode else "excluded_rcsdroad_count"] = len(invalid_rc_road_ids)
            counts["review_excluded_rcsdnode_count" if review_mode else "excluded_rcsdnode_count"] = len(invalid_rc_node_ids)
            counts["local_rcsdroad_count"] = len(local_rc_roads)
            counts["local_rcsdnode_count"] = len(local_rc_nodes)

        try:
            _rc_representative_node, rc_group_nodes = _resolve_group(mainnodeid=normalized_mainnodeid, nodes=local_rc_nodes)
        except VirtualIntersectionPocError as exc:
            if exc.reason == REASON_MAINNODEID_NOT_FOUND:
                rc_group_nodes = []
            else:
                raise

        analysis_center = representative_node.geometry
        analysis_member_node_ids = {node.node_id for node in group_nodes}
        analysis_auxiliary_nodes: list[ParsedNode] = []
        incident_roads, _, road_branches = _build_road_branches_for_member_nodes(
            local_roads,
            member_node_ids=analysis_member_node_ids,
            drivezone_union=drivezone_union,
        )
        if not incident_roads:
            raise VirtualIntersectionPocError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                f"mainnodeid='{normalized_mainnodeid}' has no incident roads inside the local patch.",
            )
        try:
            main_branch_ids = set(_select_main_pair(road_branches))
        except VirtualIntersectionPocError:
            compound_center_context = _resolve_compound_center_branch_context(
                representative_node=representative_node,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                drivezone_union=drivezone_union,
            )
            if compound_center_context is None:
                raise
            analysis_center, analysis_member_node_ids, analysis_auxiliary_nodes, road_branches = compound_center_context
            incident_roads, _, road_branches = _build_road_branches_for_member_nodes(
                local_roads,
                member_node_ids=analysis_member_node_ids,
                drivezone_union=drivezone_union,
            )
            main_branch_ids = set(_select_main_pair(road_branches))
            audit_rows.append(
                _audit_row(
                    scope="main_direction",
                    status="warning",
                    reason="compound_center_applied",
                    detail=(
                        f"mainnodeid='{normalized_mainnodeid}' used a short-link compound center with "
                        f"auxiliary node id='{analysis_auxiliary_nodes[0].node_id}'."
                    ),
                    mainnodeid=normalized_mainnodeid,
                    feature_id=analysis_auxiliary_nodes[0].node_id,
                )
            )

        record_stage("local_patch_built")
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status="running",
            current_stage="local_patch_built",
            message="Built local feature patch around target junction.",
            counts=counts,
        )

        grid = _build_grid(analysis_center, patch_size_m=patch_size_m, resolution_m=resolution_m)
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
            [node.geometry.buffer(NODE_SEED_RADIUS_M) for node in [*group_nodes, *analysis_auxiliary_nodes]],
        )
        if rc_group_nodes:
            rc_node_seed_mask = _rasterize_geometries(
                grid,
                [node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in rc_group_nodes],
            )
        else:
            rc_node_seed_mask = np.zeros_like(node_seed_mask, dtype=bool)
        record_stage("masks_built")

        rc_member_node_ids = {node.node_id for node in rc_group_nodes}
        incident_rc_roads = [road for road in local_rc_roads if road.snodeid in rc_member_node_ids or road.enodeid in rc_member_node_ids]
        if incident_rc_roads:
            rc_candidates = [
                candidate
                for candidate in (
                    _branch_candidate_from_road(road, member_node_ids=rc_member_node_ids, drivezone_union=drivezone_union)
                    for road in incident_rc_roads
                )
                if candidate is not None
            ]
        else:
            rc_candidates = [
                candidate
                for candidate in (
                    _branch_candidate_from_center_proximity(
                        road,
                        center=analysis_center,
                        drivezone_union=drivezone_union,
                        max_distance_m=RC_BRANCH_PROXIMITY_M,
                    )
                    for road in local_rc_roads
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
                center=analysis_center,
                angle_deg=branch.angle_deg,
                max_length_m=patch_size_m / 2.0,
            )
            branch.rc_support_m = _ray_support_m(
                mask=rc_road_mask,
                grid=grid,
                center=analysis_center,
                angle_deg=branch.angle_deg,
                max_length_m=patch_size_m / 2.0,
            )

        for branch in rc_branches:
            branch.drivezone_support_m = _ray_support_m(
                mask=drivezone_mask,
                grid=grid,
                center=analysis_center,
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

        for branch in road_branches:
            branch.is_main_direction = branch.branch_id in main_branch_ids
            branch.evidence_level = _classify_branch_evidence(branch)
            branch.selected_for_polygon = branch.is_main_direction or branch.evidence_level != "edge_only"

        record_stage("main_direction_identified")

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
            has_rc_group_nodes=bool(rc_group_nodes),
        )
        if rc_branches and not positive_rc_groups:
            risks.append(STATUS_NO_VALID_RC_CONNECTION)
        for branch in rc_branches:
            branch.selected_rc_group = branch.branch_id in positive_rc_groups
            branch.conflict_excluded = branch.branch_id in negative_rc_groups

        rc_branch_by_id = {branch.branch_id: branch for branch in rc_branches}
        rc_node_by_id = {node.node_id: node for node in local_rc_nodes}
        positive_rc_road_ids, polygon_included_adjacent_rc_road_ids, polygon_excluded_rc_road_ids = _select_positive_rc_road_ids(
            positive_rc_groups=positive_rc_groups,
            negative_rc_groups=negative_rc_groups,
            rc_branch_by_id=rc_branch_by_id,
            local_rc_roads=local_rc_roads,
            center=analysis_center,
            road_branches=road_branches,
        )

        candidate_selected_rc_node_ids: set[str] = {node.node_id for node in rc_group_nodes}
        compact_endpoint_node_ids: set[str] = set()
        for road in local_rc_roads:
            if road.road_id in positive_rc_road_ids:
                line = _linearize(road.geometry)
                coords = list(line.coords)
                endpoint_infos = [
                    (road.snodeid, Point(coords[0])),
                    (road.enodeid, Point(coords[-1])),
                ]
                endpoint_distances = [point.distance(analysis_center) for _, point in endpoint_infos]
                road_compact_endpoint_ids: list[str] = []
                for node_id, endpoint_point in endpoint_infos:
                    rc_node = rc_node_by_id.get(node_id)
                    if rc_node is None:
                        continue
                    if bool(rc_group_nodes):
                        candidate_selected_rc_node_ids.add(node_id)
                    elif (
                        line.length <= POLYGON_COMPACT_RC_MAX_LENGTH_M
                        and POLYGON_COMPACT_RC_ENDPOINT_MIN_DISTANCE_M
                        <= endpoint_point.distance(analysis_center)
                        <= POLYGON_COMPACT_RC_ENDPOINT_MAX_DISTANCE_M
                    ):
                        road_compact_endpoint_ids.append(node_id)
                if (
                    not rc_group_nodes
                    and line.length <= POLYGON_COMPACT_RC_MAX_LENGTH_M
                    and min(endpoint_distances) >= POLYGON_COMPACT_RC_ENDPOINT_MIN_DISTANCE_M
                    and max(endpoint_distances) <= POLYGON_COMPACT_RC_ENDPOINT_MAX_DISTANCE_M
                    and len(road_compact_endpoint_ids) >= 2
                ):
                    compact_endpoint_node_ids.update(road_compact_endpoint_ids)
        candidate_selected_rc_node_ids.update(compact_endpoint_node_ids)
        polygon_support_rc_road_ids, polygon_support_rc_node_ids, orphan_positive_support = _build_polygon_support_from_association(
            positive_rc_road_ids=positive_rc_road_ids,
            base_support_node_ids=candidate_selected_rc_node_ids,
            excluded_rc_road_ids=polygon_excluded_rc_road_ids,
            local_rc_roads=local_rc_roads,
            local_rc_nodes=local_rc_nodes,
            group_nodes=group_nodes,
        )
        if orphan_positive_support:
            positive_rc_road_ids.clear()
            if STATUS_NO_VALID_RC_CONNECTION not in risks:
                risks.append(STATUS_NO_VALID_RC_CONNECTION)
        polygon_excluded_rc_road_ids -= polygon_support_rc_road_ids
        counts["polygon_support_rcsdroad_count"] = len(polygon_support_rc_road_ids)
        counts["polygon_support_rcsdnode_count"] = len(polygon_support_rc_node_ids)
        support_rc_node_seed_mask = (
            _rasterize_geometries(
                grid,
                [
                    node.geometry.buffer(RC_NODE_SEED_RADIUS_M)
                    for node in local_rc_nodes
                    if node.node_id in polygon_support_rc_node_ids
                ],
            )
            if polygon_support_rc_node_ids
            else np.zeros_like(node_seed_mask, dtype=bool)
        )

        core_geometry = analysis_center.buffer(POLYGON_CORE_RADIUS_M).intersection(drivezone_union)
        core_mask = _rasterize_geometries(grid, [core_geometry]) & drivezone_mask
        support_geometries: list[BaseGeometry] = [core_geometry]
        group_node_buffers = [
            node.geometry.buffer(POLYGON_GROUP_NODE_BUFFER_M).intersection(drivezone_union)
            for node in group_nodes
        ]
        group_node_reinclude_geometries = [
            unary_union(
                [
                    node.geometry.buffer(POLYGON_GROUP_NODE_REINCLUDE_M),
                    LineString(
                        [
                            (float(analysis_center.x), float(analysis_center.y)),
                            (float(node.geometry.x), float(node.geometry.y)),
                        ]
                    ).buffer(POLYGON_GROUP_NODE_REINCLUDE_M * 0.5, cap_style=1, join_style=1),
                ]
            ).intersection(drivezone_union)
            for node in group_nodes
            if node.geometry.distance(analysis_center) > max(resolution_m, 0.2)
        ]
        group_node_connectors = [
            LineString(
                [
                    (float(analysis_center.x), float(analysis_center.y)),
                    (float(node.geometry.x), float(node.geometry.y)),
                ]
            ).buffer(POLYGON_GROUP_NODE_BUFFER_M * 0.75, cap_style=1, join_style=1).intersection(drivezone_union)
            for node in group_nodes
            if node.geometry.distance(analysis_center) > max(resolution_m, 0.2)
        ]
        group_node_mask = _rasterize_geometries(grid, group_node_buffers) & drivezone_mask if group_node_buffers else np.zeros_like(core_mask, dtype=bool)
        support_geometries.extend(geometry for geometry in group_node_buffers if not geometry.is_empty)
        support_geometries.extend(geometry for geometry in group_node_connectors if not geometry.is_empty)
        branch_mandatory_support_geometries: list[BaseGeometry] = []
        branch_local_refinement_specs: list[tuple[BaseGeometry, BaseGeometry]] = []
        branch_features: list[dict[str, Any]] = []
        for branch in road_branches:
            max_length = _polygon_branch_length_m(branch)
            branch_has_positive_rc_gap = _branch_has_positive_rc_gap(
                branch=branch,
                positive_rc_groups=positive_rc_groups,
                negative_rc_groups=negative_rc_groups,
                rc_branch_by_id=rc_branch_by_id,
                polygon_support_rc_road_ids=polygon_support_rc_road_ids,
            )
            branch_has_local_road_mouth = _branch_has_local_road_mouth(branch)
            branch_has_minimal_local_road_touch = _branch_has_minimal_local_road_touch(branch)
            if branch_has_positive_rc_gap:
                max_length = max(max_length, _rc_gap_branch_polygon_length_m(branch))
            if branch_has_local_road_mouth:
                max_length = max(max_length, _local_road_mouth_polygon_length_m(branch))
            if branch_has_minimal_local_road_touch:
                max_length = max(max_length, _minimal_local_road_touch_polygon_length_m(branch))
            if max_length <= 0.0:
                branch.polygon_length_m = 0.0
                branch_features.append(
                    _branch_feature(
                        branch=branch,
                        center=analysis_center,
                        length_m=8.0,
                    )
                )
                continue
            half_width = MAIN_BRANCH_HALF_WIDTH_M if branch.is_main_direction else SIDE_BRANCH_HALF_WIDTH_M
            branch_uses_rc_tip_suppression = _branch_uses_rc_tip_suppression(
                branch=branch,
                positive_rc_groups=positive_rc_groups,
                negative_rc_groups=negative_rc_groups,
                rc_branch_by_id=rc_branch_by_id,
                polygon_support_rc_road_ids=polygon_support_rc_road_ids,
            )
            branch_selected_for_polygon = (
                branch.selected_for_polygon
                or branch_has_positive_rc_gap
                or branch_has_local_road_mouth
                or branch_has_minimal_local_road_touch
            )
            connector_length = min(
                max_length,
                14.0 if branch.is_main_direction else 8.0,
            )
            connector_geometry = _branch_ray_geometry(
                analysis_center,
                angle_deg=branch.angle_deg,
                length_m=connector_length,
            ).buffer(half_width * 0.95, cap_style=2, join_style=2).intersection(drivezone_union)
            tip_geometry = GeometryCollection()
            if not branch_uses_rc_tip_suppression:
                tip_point = _point_along_branch(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    distance_m=max_length,
                )
                tip_geometry = tip_point.buffer(max(POLYGON_TIP_BUFFER_M, half_width * 0.8)).intersection(drivezone_union)
            if branch_selected_for_polygon:
                branch_selected_geometries: list[BaseGeometry] = []
                compact_local_branch_support = False
                if not branch.is_main_direction and not branch_uses_rc_tip_suppression:
                    local_branch_clip = analysis_center.buffer(
                        max_length + half_width + (4.0 if not branch.rcsdroad_ids else 2.0)
                    )
                    branch_road_geometries = [
                        road.geometry.intersection(local_branch_clip)
                        .buffer(
                            half_width
                            * (
                                1.1
                                if (
                                    not branch.rcsdroad_ids
                                    and (
                                        branch.selected_for_polygon
                                        or branch_has_local_road_mouth
                                        or branch_has_minimal_local_road_touch
                                    )
                                )
                                else 0.9
                            ),
                            cap_style=2,
                            join_style=2,
                        )
                        .intersection(drivezone_union)
                        for road in local_roads
                        if road.road_id in branch.road_ids
                    ]
                    support_geometries.extend(
                        geometry
                        for geometry in branch_road_geometries
                        if geometry is not None and not geometry.is_empty
                    )
                    branch_selected_geometries.extend(
                        geometry
                        for geometry in branch_road_geometries
                        if geometry is not None and not geometry.is_empty
                    )
                    compact_local_branch_support = bool(branch_selected_geometries) and _branch_prefers_compact_local_support(
                        branch,
                        branch_has_local_road_mouth=branch_has_local_road_mouth,
                        branch_has_minimal_local_road_touch=branch_has_minimal_local_road_touch,
                    )
                    if compact_local_branch_support:
                        mouth_fan_geometry = _build_local_branch_mouth_fan_geometry(
                            center=analysis_center,
                            branch_geometries=branch_selected_geometries,
                            drivezone_union=drivezone_union,
                            half_width=half_width,
                        )
                        if not mouth_fan_geometry.is_empty:
                            support_geometries.append(mouth_fan_geometry)
                            branch_selected_geometries.append(mouth_fan_geometry)
                            refine_clip = analysis_center.buffer(
                                max_length + half_width + 6.0
                            ).intersection(drivezone_union)
                            if not refine_clip.is_empty and not polygon_support_rc_road_ids:
                                branch_local_refinement_specs.append(
                                    (refine_clip, mouth_fan_geometry.intersection(refine_clip))
                                )
                if not connector_geometry.is_empty and not compact_local_branch_support:
                    support_geometries.append(connector_geometry)
                    branch_selected_geometries.append(connector_geometry)
                if not tip_geometry.is_empty and not compact_local_branch_support:
                    support_geometries.append(tip_geometry)
                    branch_selected_geometries.append(tip_geometry)
                if not branch.rcsdroad_ids and not compact_local_branch_support:
                    mouth_fan_geometry = _build_local_branch_mouth_fan_geometry(
                        center=analysis_center,
                        branch_geometries=branch_selected_geometries,
                        drivezone_union=drivezone_union,
                        half_width=half_width,
                    )
                    if not mouth_fan_geometry.is_empty:
                        support_geometries.append(mouth_fan_geometry)
                        branch_selected_geometries.append(mouth_fan_geometry)
                if not branch.is_main_direction and not branch_uses_rc_tip_suppression:
                    branch_mandatory_support_geometries.extend(branch_selected_geometries)
            branch.polygon_length_m = max_length
            branch_features.append(
                _branch_feature(
                    branch=branch,
                    center=analysis_center,
                    length_m=max_length,
                )
            )

        contested_selected_rc_node_ids = {
            node_id
            for road in local_rc_roads
            if road.road_id in polygon_excluded_rc_road_ids
            for node_id in (road.snodeid, road.enodeid)
            if node_id in polygon_support_rc_node_ids
        }
        selected_rc_node_buffers = [
            node.geometry.buffer(
                POLYGON_CONTESTED_RC_NODE_BUFFER_M
                if node.node_id in contested_selected_rc_node_ids
                else POLYGON_RC_NODE_BUFFER_M
            ).intersection(drivezone_union)
            for node in local_rc_nodes
            if node.node_id in polygon_support_rc_node_ids
        ]
        selected_rc_node_connectors = [
            LineString(
                [
                    (float(analysis_center.x), float(analysis_center.y)),
                    (float(node.geometry.x), float(node.geometry.y)),
                ]
            )
            .buffer(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M, cap_style=2, join_style=2)
            .intersection(drivezone_union)
            for node in local_rc_nodes
            if node.node_id in polygon_support_rc_node_ids and not rc_group_nodes
        ]
        support_geometries.extend(geometry for geometry in selected_rc_node_buffers if not geometry.is_empty)
        support_geometries.extend(geometry for geometry in selected_rc_node_connectors if not geometry.is_empty)
        positive_anchor_geometries: list[BaseGeometry] = [core_geometry]
        positive_anchor_geometries.extend(group_node_buffers)
        positive_anchor_geometries.extend(group_node_connectors)
        positive_anchor_geometries.extend(selected_rc_node_buffers)
        positive_anchor_geometries.extend(selected_rc_node_connectors)
        positive_anchor_zone = unary_union([geometry for geometry in positive_anchor_geometries if not geometry.is_empty])
        rc_exclusion_keep_node_union = (
            unary_union(
                [
                    node.geometry.buffer(
                        (
                            POLYGON_CONTESTED_RC_NODE_BUFFER_M
                            if node.node_id in contested_selected_rc_node_ids
                            else POLYGON_RC_NODE_BUFFER_M
                        )
                        + 0.8
                    ).intersection(drivezone_union)
                    for node in local_rc_nodes
                    if node.node_id in polygon_support_rc_node_ids
                ]
            )
            if polygon_support_rc_node_ids
            else GeometryCollection()
        )

        positive_rc_geometries: list[BaseGeometry] = []
        polygon_support_clip = _build_polygon_support_clip(
            analysis_center=analysis_center,
            group_nodes=group_nodes,
            local_rc_roads=local_rc_roads,
            local_rc_nodes=local_rc_nodes,
            support_road_ids=polygon_support_rc_road_ids,
            support_node_ids=polygon_support_rc_node_ids,
        )
        if polygon_support_rc_road_ids:
            if polygon_support_rc_node_ids:
                positive_anchor_zone = positive_anchor_zone.buffer(
                    POLYGON_SUPPORT_SMOOTH_M
                )
            for road in local_rc_roads:
                if road.road_id not in polygon_support_rc_road_ids:
                    continue
                local_geometry = road.geometry.intersection(polygon_support_clip)
                if local_geometry.is_empty:
                    continue
                if road.road_id in polygon_included_adjacent_rc_road_ids:
                    positive_geometry = local_geometry.buffer(
                        RC_ROAD_BUFFER_M * 0.85,
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                elif rc_group_nodes and road.road_id in positive_rc_road_ids:
                    positive_geometry = road.geometry.buffer(
                        RC_ROAD_BUFFER_M,
                        cap_style=2,
                        join_style=2,
                    ).intersection(positive_anchor_zone)
                else:
                    positive_geometry = local_geometry.buffer(
                        RC_ROAD_BUFFER_M * 0.9,
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                if not positive_geometry.is_empty:
                    positive_rc_geometries.append(positive_geometry)
            if positive_rc_geometries:
                support_geometries.extend(geometry for geometry in positive_rc_geometries if not geometry.is_empty)
        mandatory_support_geometries = [
            *group_node_buffers,
            *group_node_connectors,
            *selected_rc_node_buffers,
            *selected_rc_node_connectors,
            *positive_rc_geometries,
            *branch_mandatory_support_geometries,
        ]
        mandatory_support_geometries = [
            geometry
            for geometry in mandatory_support_geometries
            if geometry is not None and not geometry.is_empty
        ]
        mandatory_support_union = (
            unary_union(mandatory_support_geometries)
            if mandatory_support_geometries
            else GeometryCollection()
        )
        rc_exclusion_keep_union = rc_exclusion_keep_node_union
        if not mandatory_support_union.is_empty:
            support_keep_geometry = mandatory_support_union.buffer(
                max(resolution_m, 0.4),
                join_style=1,
            ).intersection(drivezone_union)
            if rc_exclusion_keep_union.is_empty:
                rc_exclusion_keep_union = support_keep_geometry
            else:
                rc_exclusion_keep_union = unary_union(
                    [rc_exclusion_keep_union, support_keep_geometry]
                )
        support_geometries = [geometry for geometry in support_geometries if geometry is not None and not geometry.is_empty]
        support_union = unary_union(support_geometries) if support_geometries else core_geometry
        candidate_polygon_geometry = support_union.buffer(POLYGON_SUPPORT_SMOOTH_M, join_style=1)
        has_excluded_rc_touching_selected_endpoint = any(
            road.road_id in polygon_excluded_rc_road_ids
            and (road.snodeid in candidate_selected_rc_node_ids or road.enodeid in candidate_selected_rc_node_ids)
            for road in local_rc_roads
        )
        if (
            selected_rc_node_buffers
            and (rc_group_nodes or compact_endpoint_node_ids)
            and not has_excluded_rc_touching_selected_endpoint
        ):
            endpoint_hull = unary_union([core_geometry, *selected_rc_node_buffers]).convex_hull.buffer(
                POLYGON_SUPPORT_SMOOTH_M * 0.75,
                join_style=1,
            )
            candidate_polygon_geometry = unary_union([candidate_polygon_geometry, endpoint_hull])
        candidate_polygon_geometry = candidate_polygon_geometry.intersection(drivezone_union)
        if candidate_polygon_geometry.is_empty:
            candidate_polygon_geometry = core_geometry

        polygon_mask = _rasterize_geometries(grid, [candidate_polygon_geometry]) & drivezone_mask
        group_node_reinclude_mask = (
            _rasterize_geometries(grid, group_node_reinclude_geometries) & drivezone_mask
            if group_node_reinclude_geometries
            else np.zeros_like(polygon_mask, dtype=bool)
        )
        if polygon_excluded_rc_road_ids:
            local_exclusion_clip = analysis_center.buffer(POLYGON_LOCAL_RC_EXCLUSION_EXTENSION_M)
            exclusion_geometries = []
            for road in local_rc_roads:
                if road.road_id not in polygon_excluded_rc_road_ids:
                    continue
                exclusion_geometry = _build_excluded_rc_geometry(
                    road=road,
                    local_clip=local_exclusion_clip,
                    drivezone_union=drivezone_union,
                    keep_node_union=rc_exclusion_keep_union,
                )
                if not exclusion_geometry.is_empty:
                    exclusion_geometries.append(exclusion_geometry)
            if exclusion_geometries:
                exclusion_mask = _rasterize_geometries(grid, exclusion_geometries)
                polygon_mask &= ~exclusion_mask
        polygon_mask = _binary_close(polygon_mask, iterations=1)
        polygon_mask |= group_node_reinclude_mask
        polygon_mask = _extract_seed_component(polygon_mask, core_mask | node_seed_mask | support_rc_node_seed_mask)
        if not polygon_mask.any():
            polygon_mask = core_mask
        virtual_polygon_geometry = _mask_to_geometry(polygon_mask, grid)
        if not virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = (
                virtual_polygon_geometry.buffer(POLYGON_SUPPORT_SMOOTH_M, join_style=1)
                .buffer(-POLYGON_SUPPORT_SMOOTH_M * 0.5, join_style=1)
                .intersection(drivezone_union)
            )
        if virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = analysis_center.buffer(12.0).intersection(drivezone_union)
        if not mandatory_support_union.is_empty:
            virtual_polygon_geometry = unary_union([virtual_polygon_geometry, mandatory_support_union]).intersection(
                drivezone_union
            )
            if not virtual_polygon_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.buffer(0)
        if polygon_excluded_rc_road_ids:
            final_local_exclusion_clip = analysis_center.buffer(POLYGON_LOCAL_RC_EXCLUSION_EXTENSION_M)
            final_exclusion_geometries = []
            for road in local_rc_roads:
                if road.road_id not in polygon_excluded_rc_road_ids:
                    continue
                exclusion_geometry = _build_excluded_rc_geometry(
                    road=road,
                    local_clip=final_local_exclusion_clip,
                    drivezone_union=drivezone_union,
                    keep_node_union=rc_exclusion_keep_union,
                )
                if not exclusion_geometry.is_empty:
                    final_exclusion_geometries.append(exclusion_geometry)
            if final_exclusion_geometries:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(unary_union(final_exclusion_geometries))
                if group_node_reinclude_geometries:
                    virtual_polygon_geometry = unary_union([virtual_polygon_geometry, *group_node_reinclude_geometries]).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = virtual_polygon_geometry.buffer(0)
        if not virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = _fill_small_polygon_holes(
                virtual_polygon_geometry,
                max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
            )
            if not virtual_polygon_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.buffer(0)
        if not virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                geometry=virtual_polygon_geometry,
                drivezone_union=drivezone_union,
                seed_geometry=core_geometry,
            )
        if not virtual_polygon_geometry.is_empty and branch_local_refinement_specs:
            for refine_clip, refine_geometry in branch_local_refinement_specs:
                if refine_clip.is_empty or refine_geometry.is_empty:
                    continue
                replacement = unary_union(
                    [
                        core_geometry.intersection(refine_clip),
                        refine_geometry,
                    ]
                ).convex_hull.intersection(refine_clip)
                virtual_polygon_geometry = unary_union(
                    [
                        virtual_polygon_geometry.difference(refine_clip),
                        replacement,
                    ]
                ).intersection(drivezone_union)
            if not virtual_polygon_geometry.is_empty:
                virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                    geometry=virtual_polygon_geometry,
                    drivezone_union=drivezone_union,
                    seed_geometry=core_geometry,
                )
        if not virtual_polygon_geometry.is_empty:
            branch_road_ids = {
                road_id
                for branch in road_branches
                for road_id in branch.road_ids
            }
            foreign_node_exclusion_geometry = _build_foreign_node_exclusion_geometry(
                polygon_geometry=virtual_polygon_geometry,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                allowed_road_ids=branch_road_ids,
                drivezone_union=drivezone_union,
            )
            if not foreign_node_exclusion_geometry.is_empty:
                keep_seed_geometry = unary_union(
                    [core_geometry, *group_node_reinclude_geometries]
                ).buffer(
                    max(resolution_m, 0.4),
                    join_style=1,
                ).intersection(drivezone_union)
                exclusion_geometry = foreign_node_exclusion_geometry.difference(keep_seed_geometry)
                if not exclusion_geometry.is_empty:
                    virtual_polygon_geometry = virtual_polygon_geometry.difference(
                        exclusion_geometry
                    ).intersection(drivezone_union)
                    excluded_polygon_support_node_ids = {
                        node.node_id
                        for node in local_rc_nodes
                        if node.node_id in polygon_support_rc_node_ids
                        and exclusion_geometry.buffer(0.2).intersects(node.geometry)
                    }
                    excluded_polygon_support_road_ids = {
                        road.road_id
                        for road in local_rc_roads
                        if road.road_id in polygon_support_rc_road_ids
                        and road.geometry.intersection(exclusion_geometry).length >= 1.0
                    }
                    polygon_support_rc_node_ids.difference_update(excluded_polygon_support_node_ids)
                    polygon_support_rc_road_ids.difference_update(excluded_polygon_support_road_ids)
                    if group_node_reinclude_geometries:
                        virtual_polygon_geometry = unary_union(
                            [virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not virtual_polygon_geometry.is_empty:
                        virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
        uncovered_group_node_ids, uncovered_support_rc_node_ids, uncovered_support_rc_road_ids = _validate_polygon_support(
            polygon_geometry=virtual_polygon_geometry,
            group_nodes=group_nodes,
            local_rc_nodes=local_rc_nodes,
            local_rc_roads=local_rc_roads,
            support_node_ids=polygon_support_rc_node_ids,
            support_road_ids=polygon_support_rc_road_ids,
            support_clip=polygon_support_clip,
        )
        if uncovered_group_node_ids or uncovered_support_rc_node_ids or uncovered_support_rc_road_ids:
            detail_parts: list[str] = []
            if uncovered_group_node_ids:
                detail_parts.append(f"group_nodes={','.join(sorted(uncovered_group_node_ids))}")
            if uncovered_support_rc_node_ids:
                detail_parts.append(f"polygon_support_rcsdnode={','.join(sorted(uncovered_support_rc_node_ids))}")
            if uncovered_support_rc_road_ids:
                detail_parts.append(f"polygon_support_rcsdroad={','.join(sorted(uncovered_support_rc_road_ids))}")
            raise VirtualIntersectionPocError(
                REASON_ANCHOR_SUPPORT_CONFLICT,
                (
                    f"mainnodeid='{normalized_mainnodeid}' polygon support validation failed: "
                    + "; ".join(detail_parts)
                ),
            )
        analysis_auxiliary_node_ids = {node.node_id for node in analysis_auxiliary_nodes}
        polygon_cover = virtual_polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
        covered_extra_local_node_ids = sorted(
            node.node_id
            for node in local_nodes
            if (
                node.node_id not in analysis_member_node_ids
                and node.node_id not in analysis_auxiliary_node_ids
                and polygon_cover.covers(node.geometry)
            )
        )
        counts["covered_extra_local_node_count"] = len(covered_extra_local_node_ids)
        if len(covered_extra_local_node_ids) >= 2:
            if STATUS_NODE_COMPONENT_CONFLICT not in risks:
                risks.append(STATUS_NODE_COMPONENT_CONFLICT)
            audit_rows.append(
                _audit_row(
                    scope="virtual_intersection_poc",
                    status="warning",
                    reason=STATUS_NODE_COMPONENT_CONFLICT,
                    detail=(
                        f"mainnodeid='{normalized_mainnodeid}' polygon covers extra local node ids="
                        f"{','.join(covered_extra_local_node_ids)} beyond own-group and compound auxiliary nodes."
                    ),
                    mainnodeid=normalized_mainnodeid,
                    feature_id=covered_extra_local_node_ids[0],
                )
            )
        record_stage("virtual_polygon_built")
        selected_rc_roads = [
            road
            for road in local_rc_roads
            if road.road_id in positive_rc_road_ids and road.geometry.intersects(virtual_polygon_geometry)
        ]
        selected_rc_node_ids: set[str] = {node.node_id for node in rc_group_nodes}
        for road in selected_rc_roads:
            selected_rc_node_ids.add(road.snodeid)
            selected_rc_node_ids.add(road.enodeid)
        if not selected_rc_roads and positive_rc_road_ids and STATUS_NO_VALID_RC_CONNECTION not in risks:
            risks.append(STATUS_NO_VALID_RC_CONNECTION)
        max_selected_side_branch_covered_length_m = _max_selected_side_branch_covered_length_m(
            polygon_geometry=virtual_polygon_geometry,
            road_branches=road_branches,
            local_roads=local_roads,
        )
        max_nonmain_branch_polygon_length_m = _max_nonmain_branch_polygon_length_m(
            road_branches=road_branches,
        )
        counts["max_selected_side_branch_covered_length_m"] = round(
            max_selected_side_branch_covered_length_m,
            3,
        )
        counts["max_nonmain_branch_polygon_length_m"] = round(
            max_nonmain_branch_polygon_length_m,
            3,
        )

        if debug:
            try:
                _write_debug_rendered_map(
                    out_path=rendered_map_path,
                    grid=grid,
                    drivezone_mask=drivezone_mask,
                    polygon_geometry=virtual_polygon_geometry,
                    representative_node=representative_node,
                    group_nodes=group_nodes,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    selected_rc_roads=selected_rc_roads,
                    selected_rc_node_ids=selected_rc_node_ids,
                    excluded_rc_road_ids=polygon_excluded_rc_road_ids,
                )
                debug_rendered_map_written = True
                announce(logger, f"[T02-POC] wrote debug rendered map path={rendered_map_path}")
            except Exception as exc:
                announce(logger, f"[T02-POC] debug rendered map skipped reason={type(exc).__name__}: {exc}")

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

        associated_rcsdnode_features: list[dict[str, Any]] = []
        for node in local_rc_nodes:
            selected = (
                node.node_id in selected_rc_node_ids
                or node.node_id in polygon_support_rc_node_ids
            )
            node_association_audits.append(
                _association_audit_row(
                    entity_type="rcsdnode",
                    entity_id=node.node_id,
                    selected=selected,
                    reason=(
                        "selected_by_rcsdroad_or_group"
                        if node.node_id in selected_rc_node_ids
                        else "selected_by_polygon_support"
                    ) if selected else "not_selected",
                    group_id=normalized_mainnodeid,
                    branch_id=None,
                )
            )
            if selected:
                associated_rcsdnode_features.append({"properties": dict(node.properties), "geometry": node.geometry})

        counts["associated_rcsdroad_count"] = len(associated_rcsdroad_features)
        counts["associated_rcsdnode_count"] = len(associated_rcsdnode_features)
        counts["risk_count"] = len(risks)
        connected_rc_group_ids = {
            rc_group_id
            for branch in road_branches
            for rc_group_id in branch.rcsdroad_ids
        }
        nonmain_branch_connected_rc_group_ids = {
            rc_group_id
            for branch in road_branches
            if not branch.is_main_direction
            for rc_group_id in branch.rcsdroad_ids
        }
        if min_invalid_rc_distance_to_center_m is not None:
            counts["min_invalid_rc_distance_to_center_m"] = round(
                min_invalid_rc_distance_to_center_m,
                3,
            )

        status = _status_from_risks(risks, has_associated_roads=bool(associated_rcsdroad_features))
        if status == STATUS_STABLE and not associated_rcsdroad_features:
            status = STATUS_SURFACE_ONLY
        effect_success, acceptance_class, acceptance_reason = _effect_success_acceptance(
            status=status,
            review_mode=review_mode,
            max_selected_side_branch_covered_length_m=max_selected_side_branch_covered_length_m,
            max_nonmain_branch_polygon_length_m=max_nonmain_branch_polygon_length_m,
            associated_rc_road_count=len(associated_rcsdroad_features),
            polygon_support_rc_road_count=len(polygon_support_rc_road_ids),
            min_invalid_rc_distance_to_center_m=min_invalid_rc_distance_to_center_m,
            local_rc_road_count=len(local_rc_roads),
            local_rc_node_count=len(local_rc_nodes),
            connected_rc_group_count=len(connected_rc_group_ids),
            nonmain_branch_connected_rc_group_count=len(nonmain_branch_connected_rc_group_ids),
        )
        can_soft_exclude_outside_rc = (
            rc_outside_drivezone_error is not None
            and not review_mode
            and _can_soft_exclude_outside_rc(
                status=status,
                selected_rc_road_count=len(selected_rc_roads),
                polygon_support_rc_road_count=len(polygon_support_rc_road_ids),
                max_selected_side_branch_covered_length_m=max_selected_side_branch_covered_length_m,
                max_nonmain_branch_polygon_length_m=max_nonmain_branch_polygon_length_m,
                min_invalid_rc_distance_to_center_m=min_invalid_rc_distance_to_center_m,
                connected_rc_group_count=len(connected_rc_group_ids),
                negative_rc_group_count=len(negative_rc_groups),
            )
        )
        if (
            rc_outside_drivezone_error is not None
            and not review_mode
            and not can_soft_exclude_outside_rc
        ):
            if debug and not debug_rendered_map_written:
                try:
                    _write_failure_debug_rendered_map(
                        out_path=rendered_map_path,
                        representative_node=representative_node,
                        group_nodes=group_nodes,
                        local_nodes=local_nodes,
                        local_roads=local_roads,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        drivezone_union=drivezone_union,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        failure_reason=rc_outside_drivezone_error.reason,
                        excluded_rc_road_ids=invalid_rc_road_ids,
                        excluded_rc_node_ids=invalid_rc_node_ids,
                    )
                    debug_rendered_map_written = True
                except Exception as exc:
                    announce(logger, f"[T02-POC] failure debug rendered map skipped reason={type(exc).__name__}: {exc}")
            raise rc_outside_drivezone_error
        if can_soft_exclude_outside_rc:
            for road_id in sorted(invalid_rc_road_ids):
                audit_rows.append(
                    _audit_row(
                        scope="virtual_intersection_poc",
                        status="warning",
                        reason=REASON_RC_OUTSIDE_DRIVEZONE,
                        detail=(
                            f"Excluded RCSDRoad id='{road_id}' after DriveZone validation because the remaining "
                            "junction evidence was treated as an RC gap rather than a contradictory RC connection."
                        ),
                        mainnodeid=normalized_mainnodeid,
                        feature_id=road_id,
                    )
                )
            for node_id in sorted(invalid_rc_node_ids):
                audit_rows.append(
                    _audit_row(
                        scope="virtual_intersection_poc",
                        status="warning",
                        reason=REASON_RC_OUTSIDE_DRIVEZONE,
                        detail=(
                            f"Excluded RCSDNode id='{node_id}' after DriveZone validation because the remaining "
                            "junction evidence was treated as an RC gap rather than a contradictory RC connection."
                        ),
                        mainnodeid=normalized_mainnodeid,
                        feature_id=node_id,
                    )
                )

        virtual_polygon_feature = {
            "properties": {
                "mainnodeid": normalized_mainnodeid,
                "status": status,
                "representative_node_id": representative_node.node_id,
                "kind_2": representative_node.kind_2,
                "grade_2": representative_node.grade_2,
            },
            "geometry": virtual_polygon_geometry,
        }
        write_vector(virtual_polygon_path, [virtual_polygon_feature])
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
        write_vector(branch_evidence_geojson_path, branch_features)
        _write_association_outputs(
            vector_path=associated_rcsdroad_path,
            audit_csv_path=associated_rcsdroad_audit_csv_path,
            audit_json_path=associated_rcsdroad_audit_json_path,
            features=associated_rcsdroad_features,
            audits=road_association_audits,
        )
        _write_association_outputs(
            vector_path=associated_rcsdnode_path,
            audit_csv_path=associated_rcsdnode_audit_csv_path,
            audit_json_path=associated_rcsdnode_audit_json_path,
            features=associated_rcsdnode_features,
            audits=node_association_audits,
        )
        write_csv(audit_csv_path, audit_rows, fieldnames=AUDIT_FIELDNAMES)
        write_json(audit_json_path, audit_rows)
        counts["audit_count"] = len(audit_rows)
        if debug and not effect_success:
            try:
                _write_debug_rendered_map(
                    out_path=rendered_map_path,
                    grid=grid,
                    drivezone_mask=drivezone_mask,
                    polygon_geometry=virtual_polygon_geometry,
                    representative_node=representative_node,
                    group_nodes=group_nodes,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    selected_rc_roads=selected_rc_roads,
                    selected_rc_node_ids=selected_rc_node_ids,
                    excluded_rc_road_ids=polygon_excluded_rc_road_ids,
                    excluded_rc_node_ids=invalid_rc_node_ids,
                    failure_reason=acceptance_reason or status,
                )
                debug_rendered_map_written = True
                announce(
                    logger,
                    (
                        "[T02-POC] rewrote debug rendered map with failure overlay "
                        f"path={rendered_map_path} reason={acceptance_reason or status}"
                    ),
                )
            except Exception as exc:
                announce(logger, f"[T02-POC] failure overlay debug rendered map skipped reason={type(exc).__name__}: {exc}")
        status_doc = {
            "run_id": resolved_run_id,
            "success": effect_success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "mainnodeid": normalized_mainnodeid,
            "representative_node_id": representative_node.node_id,
            "kind_2": representative_node.kind_2,
            "grade_2": representative_node.grade_2,
            "status": status,
            "risks": risks,
            "counts": counts,
            "review_mode": review_mode,
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
                "rendered_map_png": str(rendered_map_path) if debug_rendered_map_written else None,
            },
        }
        write_json(status_path, status_doc)
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
            status="success" if effect_success else "completed_with_review_required_result",
            current_stage="complete",
            message=(
                "T02 virtual intersection POC completed and accepted."
                if effect_success
                else "T02 virtual intersection POC completed but requires review before acceptance."
            ),
            counts=counts,
        )
        record_stage("outputs_written")
        total_wall_time_sec = time.perf_counter() - started_at
        perf_doc = {
            "run_id": resolved_run_id,
            "success": effect_success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "total_wall_time_sec": round(total_wall_time_sec, 6),
            "counts": counts,
            "stage_timings": stage_timings,
            **_tracemalloc_stats(),
        }
        write_json(perf_json_path, perf_doc)
        return VirtualIntersectionArtifacts(
            success=effect_success,
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
            rendered_map_path=rendered_map_path if debug_rendered_map_written else None,
            virtual_polygon_feature=virtual_polygon_feature,
            status_doc=status_doc,
            perf_doc=perf_doc,
            associated_rcsdroad_ids=tuple(
                str(feature["properties"].get("id"))
                for feature in associated_rcsdroad_features
                if feature["properties"].get("id") is not None
            ),
            associated_rcsdnode_ids=tuple(
                str(feature["properties"].get("id"))
                for feature in associated_rcsdnode_features
                if feature["properties"].get("id") is not None
            ),
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
        status_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "mainnodeid": normalized_mainnodeid,
            "status": exc.reason,
            "risks": [exc.reason],
            "detail": exc.detail,
            "counts": counts,
            "review_mode": review_mode,
            "output_files": {
                "rendered_map_png": str(rendered_map_path) if debug_rendered_map_written else None,
            },
        }
        write_json(status_path, status_doc)
        total_wall_time_sec = time.perf_counter() - started_at
        perf_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "total_wall_time_sec": round(total_wall_time_sec, 6),
            "counts": counts,
            "stage_timings": stage_timings,
            **_tracemalloc_stats(),
        }
        write_json(perf_json_path, perf_doc)
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
            rendered_map_path=rendered_map_path if debug_rendered_map_written else None,
            status_doc=status_doc,
            perf_doc=perf_doc,
            associated_rcsdroad_ids=(),
            associated_rcsdnode_ids=(),
        )
    finally:
        close_logger(logger)
        if trace_memory:
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
        debug=args.debug,
        debug_render_root=args.debug_render_root,
        review_mode=args.review_mode,
    )
    if artifacts.success:
        print(f"T02 virtual intersection POC outputs written to: {artifacts.out_root}")
        return 0
    print(f"T02 virtual intersection POC failed; audit written to: {artifacts.out_root}")
    return 1
