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
from shapely.ops import linemerge, nearest_points, substring, unary_union

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
POLYGON_FOREIGN_BRANCH_BOUNDARY_TRIGGER_DISTANCE_M = 6.0
POLYGON_FOREIGN_ROAD_ENDPOINT_CLIP_M = 8.0
POLYGON_FOREIGN_ROAD_ENDPOINT_INTRUSION_MIN_M = 2.0
POLYGON_FOREIGN_INCIDENT_ROAD_ENDPOINT_INTRUSION_MIN_M = 4.0
POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M = 10.0
POLYGON_FOREIGN_ROAD_OVERLAP_MIN_M = 1.0
POLYGON_FOREIGN_TARGET_ARM_OVERREACH_TOLERANCE_M = 2.5
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
PATCH_ID_FIELD_NAMES = ("patchid", "patch_id")

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
BUSINESS_MATCH_COMPLETE_RCSD = "rcsd_complete_match"
BUSINESS_MATCH_PARTIAL_RCSD = "rcsd_partial_match"
BUSINESS_MATCH_SWSD_ONLY = "swsd_only_match"

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


def _normalize_single_patch_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if any(separator in text for separator in (",", ";", "|")):
        return None
    return _normalize_id(text)


def _patch_ids_from_properties(properties: dict[str, Any]) -> tuple[str, ...]:
    patch_ids: list[str] = []
    seen: set[str] = set()
    for field_name in PATCH_ID_FIELD_NAMES:
        value = properties.get(field_name)
        if value is None:
            continue
        text = str(value)
        if not text:
            continue
        for token in text.replace("|", ",").replace(";", ",").split(","):
            normalized = _normalize_id(token)
            if normalized is None:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            patch_ids.append(normalized)
    return tuple(patch_ids)


def _patch_id_from_properties(properties: dict[str, Any]) -> str | None:
    for field_name in PATCH_ID_FIELD_NAMES:
        if field_name in properties:
            return _normalize_single_patch_id(properties.get(field_name))
    return None


def _resolve_current_patch_id_from_roads(
    *,
    group_nodes: list[ParsedNode],
    roads: list[ParsedRoad],
) -> str | None:
    member_node_ids = {node.node_id for node in group_nodes}
    patch_ids = {
        patch_id
        for road in roads
        if road.snodeid in member_node_ids or road.enodeid in member_node_ids
        for patch_id in [_patch_id_from_properties(road.properties)]
        if patch_id is not None
    }
    if len(patch_ids) != 1:
        return None
    return next(iter(patch_ids))


def _filter_parsed_roads_to_patch(
    roads: list[ParsedRoad],
    *,
    patch_id: str | None,
) -> list[ParsedRoad]:
    if patch_id is None:
        return list(roads)
    return [road for road in roads if _patch_id_from_properties(road.properties) == patch_id]


def _filter_loaded_features_to_patch(
    features: Iterable[LoadedFeature],
    *,
    patch_id: str | None,
) -> list[LoadedFeature]:
    feature_list = list(features)
    if patch_id is None:
        return feature_list
    return [feature for feature in feature_list if _patch_id_from_properties(feature.properties) == patch_id]


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


def _failure_overlay_palette(failure_reason: str) -> dict[str, tuple[int, int, int]]:
    return {
        "tint": (220, 32, 32),
        "border": (164, 0, 0),
        "focus": (186, 0, 0),
        "hatch": (124, 0, 0),
    }


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
    local_divstrip_geometries: Iterable[BaseGeometry] = (),
    selected_divstrip_geometry: BaseGeometry | None = None,
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
    divstrip_mask = _rasterize_geometries(
        grid,
        [
            geometry
            for geometry in local_divstrip_geometries
            if geometry is not None and not geometry.is_empty
        ],
    )
    selected_divstrip_mask = _rasterize_geometries(
        grid,
        []
        if selected_divstrip_geometry is None or selected_divstrip_geometry.is_empty
        else [selected_divstrip_geometry],
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
    _blend_mask(image, divstrip_mask, color=(0, 157, 255), alpha=0.52)
    _blend_mask(image, selected_divstrip_mask, color=(0, 71, 171), alpha=0.98)
    _blend_mask(image, polygon_mask, color=(255, 140, 0), alpha=0.74)
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
        palette = _failure_overlay_palette(failure_reason)
        failure_mask = np.ones((grid.height, grid.width), dtype=bool)
        border_px = max(2, int(round(4.0 / grid.resolution_m)))
        focus_mask = polygon_mask | group_node_mask | representative_mask | selected_rc_road_mask | selected_rc_node_mask
        stripe_period_px = max(8, int(round(12.0 / grid.resolution_m)))
        stripe_width_px = max(2, stripe_period_px // 3)
        rr, cc = np.indices((grid.height, grid.width))
        border_mask = np.zeros((grid.height, grid.width), dtype=bool)
        border_mask[:border_px, :] = True
        border_mask[-border_px:, :] = True
        border_mask[:, :border_px] = True
        border_mask[:, -border_px:] = True
        hatch_mask = focus_mask & (((rr + cc) % stripe_period_px) < stripe_width_px)
        _blend_mask(image, failure_mask, color=palette["tint"], alpha=0.22)
        _blend_mask(image, focus_mask, color=palette["focus"], alpha=0.24)
        _blend_mask(image, hatch_mask, color=palette["hatch"], alpha=0.82)
        _blend_mask(image, border_mask, color=palette["border"], alpha=1.0)

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


def _collect_semantic_mainnodeids(
    local_nodes: list[ParsedNode],
    *,
    local_road_degree_by_node_id: Counter[str],
) -> set[str]:
    return {
        node.mainnodeid
        for node in local_nodes
        if node.mainnodeid not in {None, "0"}
    }


def _branch_direct_foreign_semantic_distance_m(
    branch: BranchEvidence,
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_node_by_id: dict[str, ParsedNode],
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> float:
    nearest_distance_m: float | None = None
    for road in local_roads:
        if road.road_id not in branch.road_ids:
            continue
        touches_snode = road.snodeid in target_group_node_ids
        touches_enode = road.enodeid in target_group_node_ids
        if touches_snode == touches_enode:
            continue
        foreign_node_id = road.enodeid if touches_snode else road.snodeid
        foreign_node = local_node_by_id.get(foreign_node_id)
        if foreign_node is None:
            continue
        if not _is_foreign_local_semantic_node(
            node=foreign_node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            semantic_mainnodeids=semantic_mainnodeids,
        ):
            continue
        distance_m = float(foreign_node.geometry.distance(center))
        if distance_m <= 0.5:
            continue
        if nearest_distance_m is None or distance_m < nearest_distance_m:
            nearest_distance_m = distance_m
    return nearest_distance_m or 0.0


def _select_main_pair_with_semantic_conflict_guard(
    branches: list[BranchEvidence],
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_nodes: list[ParsedNode],
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> tuple[tuple[str, str], set[str]]:
    local_node_by_id = {node.node_id: node for node in local_nodes}
    direct_foreign_semantic_conflict_distance_m = (
        POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M
        + POLYGON_FOREIGN_TARGET_ARM_OVERREACH_TOLERANCE_M
    )
    direct_foreign_semantic_branch_ids = {
        branch.branch_id
        for branch in branches
        if (
            0.0
            < _branch_direct_foreign_semantic_distance_m(
                branch,
                center=center,
                local_roads=local_roads,
                local_node_by_id=local_node_by_id,
                target_group_node_ids=target_group_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            <= direct_foreign_semantic_conflict_distance_m
        )
    }
    candidate_branches = [
        branch
        for branch in branches
        if branch.branch_id not in direct_foreign_semantic_branch_ids
    ]
    if len(candidate_branches) >= 2:
        try:
            return _select_main_pair(candidate_branches), direct_foreign_semantic_branch_ids
        except VirtualIntersectionPocError:
            pass
    return _select_main_pair(branches), direct_foreign_semantic_branch_ids


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
    normalized_mainnodeid: str,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
) -> tuple[Point, set[str], list[ParsedNode], list[BranchEvidence]] | None:
    member_node_ids = {node.node_id for node in group_nodes}
    local_node_by_id = {node.node_id: node for node in local_nodes}
    local_road_degree_by_node_id = _road_degree_by_node_id(local_roads)
    semantic_mainnodeids = _collect_semantic_mainnodeids(
        local_nodes,
        local_road_degree_by_node_id=local_road_degree_by_node_id,
    )
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
        if auxiliary_node.mainnodeid not in {None, normalized_mainnodeid}:
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
            _select_main_pair_with_semantic_conflict_guard(
                road_branches,
                center=representative_node.geometry,
                local_roads=local_roads,
                local_nodes=local_nodes,
                target_group_node_ids=expanded_member_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
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

    def _is_rc_only_bridge_candidate(branch: BranchEvidence) -> bool:
        return (
            branch.conflict_excluded
            and not branch.is_main_direction
            and branch.evidence_level != "edge_only"
            and bool(branch.rcsdroad_ids)
            and branch.rc_support_m >= 6.0
            and branch.drivezone_support_m >= 10.0
        )

    side_branches = [
        branch
        for branch in road_branches
        if not branch.is_main_direction
        and (branch.selected_for_polygon or _is_rc_only_bridge_candidate(branch))
    ]
    if kind_2 == 2048 and not has_rc_group_nodes:
        candidates: dict[str, tuple[float, str]] = {}
        for branch in road_branches:
            if not branch.selected_for_polygon and not _is_rc_only_bridge_candidate(branch):
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
                if (
                    (not branch.selected_for_polygon and not _is_rc_only_bridge_candidate(branch))
                    or branch.evidence_level == "edge_only"
                ):
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
        branch.road_support_m >= 40.0
        and branch.drivezone_support_m >= 5.0
        and branch.rc_support_m < 5.0
    ):
        local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 12.0))
        return max(8.0, min(local_support_m, 10.0))
    if (
        branch.road_support_m >= 12.0
        and branch.drivezone_support_m < 6.0
        and branch.rc_support_m < 4.0
    ):
        local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 10.0))
        return max(7.0, min(local_support_m, 10.0))
    local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 8.0))
    return max(6.0, min(local_support_m, 8.0))


def _local_road_mouth_reach_length_m(
    branch: BranchEvidence,
    *,
    branch_center_distance_m: float,
    far_junction_distance_m: float = 0.0,
) -> float:
    base_length = _local_road_mouth_polygon_length_m(branch)
    target_distance_m = max(branch_center_distance_m, far_junction_distance_m)
    if target_distance_m <= 0.5:
        return base_length
    hard_cap_m = 90.0 if far_junction_distance_m > branch_center_distance_m + 10.0 else 40.0
    return max(
        base_length,
        min(target_distance_m + base_length, target_distance_m + 12.0, hard_cap_m),
    )


def _branch_has_local_road_mouth(branch: BranchEvidence) -> bool:
    if (
        branch.is_main_direction
        or branch.evidence_level != "edge_only"
        or bool(branch.rcsdroad_ids)
    ):
        return False

    if branch.rc_support_m >= 12.0:
        return False

    if (
        branch.drivezone_support_m >= 6.0
        and branch.road_support_m >= 6.0
        and branch.rc_support_m < 5.0
    ):
        return True

    if (
        branch.road_support_m >= 60.0
        and branch.drivezone_support_m >= 5.0
        and branch.rc_support_m < 5.0
    ):
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


def _edge_branch_far_local_junction_distance_m(
    branch: BranchEvidence,
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_node_by_id: dict[str, ParsedNode],
    local_road_degree_by_node_id: Counter[str],
) -> float:
    if branch.is_main_direction or branch.evidence_level != "edge_only":
        return 0.0

    far_junction_distance_m = 0.0
    for road in local_roads:
        if road.road_id not in branch.road_ids:
            continue
        for node_id in (road.snodeid, road.enodeid):
            node = local_node_by_id.get(node_id)
            if node is None:
                continue
            if local_road_degree_by_node_id.get(node_id, 0) < 3:
                continue
            distance_m = float(node.geometry.distance(center))
            if distance_m <= 0.5:
                continue
            far_junction_distance_m = max(far_junction_distance_m, distance_m)
    return far_junction_distance_m


def _edge_branch_far_group_node_id(
    branch: BranchEvidence,
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_node_by_id: dict[str, ParsedNode],
    group_node_ids: set[str],
) -> str | None:
    if branch.is_main_direction or branch.evidence_level != "edge_only":
        return None

    farthest_node_id: str | None = None
    farthest_distance_m = 0.0
    for road in local_roads:
        if road.road_id not in branch.road_ids:
            continue
        for node_id in (road.snodeid, road.enodeid):
            if node_id not in group_node_ids:
                continue
            node = local_node_by_id.get(node_id)
            if node is None:
                continue
            distance_m = float(node.geometry.distance(center))
            if distance_m <= 0.5:
                continue
            if distance_m > farthest_distance_m:
                farthest_distance_m = distance_m
                farthest_node_id = node_id
    return farthest_node_id


def _edge_branch_far_local_junction_node_id(
    branch: BranchEvidence,
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_node_by_id: dict[str, ParsedNode],
    local_road_degree_by_node_id: Counter[str],
) -> str | None:
    if branch.is_main_direction or branch.evidence_level != "edge_only":
        return None

    farthest_node_id: str | None = None
    farthest_distance_m = 0.0
    for road in local_roads:
        if road.road_id not in branch.road_ids:
            continue
        for node_id in (road.snodeid, road.enodeid):
            node = local_node_by_id.get(node_id)
            if node is None:
                continue
            if local_road_degree_by_node_id.get(node_id, 0) < 3:
                continue
            distance_m = float(node.geometry.distance(center))
            if distance_m <= 0.5:
                continue
            if distance_m > farthest_distance_m:
                farthest_distance_m = distance_m
                farthest_node_id = node_id
    return farthest_node_id


def _edge_branch_far_local_junction_point(
    branch: BranchEvidence,
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_node_by_id: dict[str, ParsedNode],
    local_road_degree_by_node_id: Counter[str],
) -> Point | None:
    if branch.is_main_direction or branch.evidence_level != "edge_only":
        return None

    farthest_point: Point | None = None
    farthest_distance_m = 0.0
    for road in local_roads:
        if road.road_id not in branch.road_ids:
            continue
        for node_id in (road.snodeid, road.enodeid):
            node = local_node_by_id.get(node_id)
            if node is None:
                continue
            if local_road_degree_by_node_id.get(node_id, 0) < 3:
                continue
            distance_m = float(node.geometry.distance(center))
            if distance_m <= 0.5:
                continue
            if distance_m > farthest_distance_m:
                farthest_distance_m = distance_m
                farthest_point = node.geometry
    return farthest_point


def _branch_nearest_foreign_local_junction_distance_m(
    branch: BranchEvidence,
    *,
    center: Point,
    local_roads: list[ParsedRoad],
    local_node_by_id: dict[str, ParsedNode],
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> float:
    nearest_distance_m: float | None = None
    for road in local_roads:
        if road.road_id not in branch.road_ids:
            continue
        for node_id in (road.snodeid, road.enodeid):
            node = local_node_by_id.get(node_id)
            if node is None:
                continue
            local_degree = local_road_degree_by_node_id.get(node.node_id, 0)
            is_foreign_branch_boundary = _is_foreign_local_junction_node(
                node=node,
                target_group_node_ids=target_group_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            ) or (
                node.node_id not in target_group_node_ids
                and node.mainnodeid is None
                and local_degree >= 3
                and float(node.geometry.distance(center))
                >= POLYGON_FOREIGN_BRANCH_BOUNDARY_TRIGGER_DISTANCE_M
            )
            if not is_foreign_branch_boundary:
                continue
            distance_m = float(node.geometry.distance(center))
            if distance_m <= 0.5:
                continue
            if nearest_distance_m is None or distance_m < nearest_distance_m:
                nearest_distance_m = distance_m
    return nearest_distance_m or 0.0


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
        and branch.road_support_m >= 20.0
        and branch.drivezone_support_m >= 10.0
        and branch.rc_support_m >= 6.0
    ):
        return False
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
    effective_local_rc_node_count: int | None = None,
    effective_associated_rc_node_count: int = 0,
    associated_nonzero_mainnode_count: int = 0,
    covered_extra_local_node_count: int = 0,
    covered_extra_local_road_count: int = 0,
    local_road_count: int | None = None,
    local_node_count: int | None = None,
) -> bool:
    if effective_local_rc_node_count is None:
        effective_local_rc_node_count = 0
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 16
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 1
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m == 0.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 0.5
    ):
        return True
    if (
        associated_nonzero_mainnode_count >= 1
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m < 1.0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m == 0.0
    ):
        if not (
            effective_local_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and negative_rc_group_count == 0
            and connected_rc_group_count <= 1
            and local_node_count is not None
            and local_road_count is not None
            and local_node_count <= 8
            and local_road_count <= 16
            and selected_rc_road_count >= 1
            and polygon_support_rc_road_count >= 1
        ) and not (
            status == STATUS_NODE_COMPONENT_CONFLICT
            and effective_local_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and negative_rc_group_count == 0
            and connected_rc_group_count == 1
            and local_node_count is not None
            and local_road_count is not None
            and local_node_count <= 7
            and local_road_count <= 15
            and selected_rc_road_count >= 1
            and polygon_support_rc_road_count <= 1
        ):
            return False
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
        and max_nonmain_branch_polygon_length_m >= 8.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and negative_rc_group_count >= 1
        and connected_rc_group_count >= 2
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and max_nonmain_branch_polygon_length_m <= 2.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_SURFACE_ONLY, STATUS_NODE_COMPONENT_CONFLICT}
        and selected_rc_road_count >= 2
        and polygon_support_rc_road_count >= 2
        and max_selected_side_branch_covered_length_m >= 12.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_SURFACE_ONLY, STATUS_NODE_COMPONENT_CONFLICT}
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status == STATUS_NODE_COMPONENT_CONFLICT
        and selected_rc_road_count >= 2
        and polygon_support_rc_road_count >= 2
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 5
        and local_road_count <= 10
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 10.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 4.5
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_NODE_COMPONENT_CONFLICT}
        and
        effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 2
        and local_road_count <= 5
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 1
        and max_selected_side_branch_covered_length_m >= 12.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 1.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_NODE_COMPONENT_CONFLICT}
        and
        effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 3
        and local_road_count <= 6
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 2
        and negative_rc_group_count == 0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_NODE_COMPONENT_CONFLICT, REASON_RC_OUTSIDE_DRIVEZONE}
        and effective_local_rc_node_count >= 1
        and effective_associated_rc_node_count >= 1
        and associated_nonzero_mainnode_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 16
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 1
        and max_selected_side_branch_covered_length_m >= 10.0
        and max_nonmain_branch_polygon_length_m >= 7.5
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 2.0
    ):
        return True
    if (
        status == STATUS_WEAK_BRANCH_SUPPORT
        and covered_extra_local_node_count == 0
        and covered_extra_local_road_count == 0
        and selected_rc_road_count >= 2
        and polygon_support_rc_road_count >= 2
        and effective_local_rc_node_count >= 2
        and effective_associated_rc_node_count >= 2
        and associated_nonzero_mainnode_count >= 2
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 12
        and local_road_count <= 16
        and max_selected_side_branch_covered_length_m <= 4.0
        and max_nonmain_branch_polygon_length_m >= 8.0
        and max_nonmain_branch_polygon_length_m <= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 1.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and covered_extra_local_node_count == 0
        and covered_extra_local_road_count == 0
        and effective_local_rc_node_count >= 1
        and effective_associated_rc_node_count >= 1
        and associated_nonzero_mainnode_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 2
        and negative_rc_group_count == 1
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m <= 4.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 1.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 5
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and max_selected_side_branch_covered_length_m >= 10.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 6.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_NODE_COMPONENT_CONFLICT}
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 7.0
        and max_nonmain_branch_polygon_length_m >= 8.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 3.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count == 0
        and negative_rc_group_count >= 1
        and max_selected_side_branch_covered_length_m >= 8.0
        and max_nonmain_branch_polygon_length_m >= 8.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 16
        and local_road_count <= 32
    ):
        return True
    if (
        status == STATUS_STABLE
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 3
        and local_road_count <= 6
        and connected_rc_group_count >= 2
        and selected_rc_road_count >= 4
        and polygon_support_rc_road_count >= 4
        and max_nonmain_branch_polygon_length_m >= 0.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 9.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 1
        and local_road_count <= 3
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and max_selected_side_branch_covered_length_m >= 12.0
        and max_nonmain_branch_polygon_length_m >= 10.0
    ):
        return True
    if (
        status in {STATUS_STABLE, STATUS_WEAK_BRANCH_SUPPORT}
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 5
        and local_road_count <= 10
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 2
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m <= 8.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 4.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 4
        and local_road_count <= 8
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_nonmain_branch_polygon_length_m == 0.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count >= 1
        and effective_associated_rc_node_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 4
        and local_road_count <= 8
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_nonmain_branch_polygon_length_m <= 2.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and (effective_associated_rc_node_count >= 1 or associated_nonzero_mainnode_count >= 1)
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 7
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 2
        and max_selected_side_branch_covered_length_m >= 5.0
        and max_nonmain_branch_polygon_length_m >= 5.0
    ):
        return True
    if (
        status == STATUS_NODE_COMPONENT_CONFLICT
        and effective_local_rc_node_count >= 1
        and effective_associated_rc_node_count >= 1
        and associated_nonzero_mainnode_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m <= 4.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 2.0
    ):
        return True
    if (
        status == STATUS_NODE_COMPONENT_CONFLICT
        and covered_extra_local_node_count == 0
        and covered_extra_local_road_count <= 2
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 7
        and local_road_count <= 15
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count <= 1
        and connected_rc_group_count == 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m == 0.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 1.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and associated_nonzero_mainnode_count >= 2
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 3
        and local_road_count <= 6
        and selected_rc_road_count >= 4
        and polygon_support_rc_road_count >= 4
        and connected_rc_group_count >= 2
        and negative_rc_group_count == 0
        and max_nonmain_branch_polygon_length_m == 0.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 5
        and local_road_count <= 10
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 2
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m <= 3.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 4.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 5
        and local_road_count <= 10
        and selected_rc_road_count >= 2
        and polygon_support_rc_road_count == 0
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m <= 3.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 4.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 2
        and local_road_count <= 5
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 18.0
        and max_nonmain_branch_polygon_length_m >= 12.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 1.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 11
        and local_road_count <= 11
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and negative_rc_group_count >= 2
        and max_selected_side_branch_covered_length_m >= 10.0
        and max_nonmain_branch_polygon_length_m >= 8.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 4
        and local_road_count <= 9
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 20.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 6.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count >= 3
        and effective_associated_rc_node_count >= 1
        and associated_nonzero_mainnode_count >= 2
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 15
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count == 0
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 14.0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 1.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and associated_nonzero_mainnode_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 2
        and negative_rc_group_count == 0
        and max_nonmain_branch_polygon_length_m >= 7.5
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_associated_rc_node_count >= 1
        and associated_nonzero_mainnode_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 8
        and local_road_count <= 16
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 1
        and connected_rc_group_count <= 2
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 10.0
        and max_nonmain_branch_polygon_length_m >= 7.5
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m <= 2.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count >= 1
        and effective_associated_rc_node_count >= 1
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 7
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 2
        and negative_rc_group_count == 0
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 10.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_associated_rc_node_count >= 1
        and associated_nonzero_mainnode_count >= 2
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 16
        and local_road_count <= 32
        and (selected_rc_road_count + polygon_support_rc_road_count) >= 2
        and connected_rc_group_count <= 4
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m >= 8.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 15.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count == 0
        and effective_associated_rc_node_count == 0
        and associated_nonzero_mainnode_count == 0
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 5
        and local_road_count <= 16
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count >= 1
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m >= 7.5
        and max_nonmain_branch_polygon_length_m >= 10.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 4.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and effective_local_rc_node_count >= 4
        and effective_associated_rc_node_count >= 2
        and associated_nonzero_mainnode_count >= 4
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 16
        and local_road_count <= 28
        and selected_rc_road_count >= 2
        and polygon_support_rc_road_count == 0
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m >= 8.0
        and min_invalid_rc_distance_to_center_m is not None
        and min_invalid_rc_distance_to_center_m >= 15.0
    ):
        return True
    if (
        status == STATUS_STABLE
        and associated_nonzero_mainnode_count >= 2
        and local_node_count is not None
        and local_road_count is not None
        and local_node_count <= 7
        and local_road_count <= 15
        and selected_rc_road_count >= 1
        and polygon_support_rc_road_count == 0
        and connected_rc_group_count <= 1
        and negative_rc_group_count == 0
        and max_selected_side_branch_covered_length_m == 0.0
        and max_nonmain_branch_polygon_length_m >= 7.5
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


def _branch_cap_clip_geometry(
    center: Point,
    *,
    angle_deg: float,
    length_m: float,
    half_width_m: float,
    drivezone_union: BaseGeometry,
    extension_m: float = 0.0,
    lateral_scale: float = 1.0,
    minimum_half_width_m: float = 0.0,
    center_radius_m: float = 0.0,
) -> BaseGeometry:
    clip_parts: list[BaseGeometry] = []
    clip_half_width_m = max(half_width_m * lateral_scale, minimum_half_width_m)
    if clip_half_width_m > 0.0:
        clip_parts.append(
            _branch_ray_geometry(
                center,
                angle_deg=angle_deg,
                length_m=max(1.0, float(length_m) + float(extension_m)),
            ).buffer(
                clip_half_width_m,
                cap_style=2,
                join_style=2,
            )
        )
    if center_radius_m > 0.0:
        clip_parts.append(center.buffer(center_radius_m, join_style=1))
    if not clip_parts:
        return GeometryCollection()
    return unary_union(clip_parts).intersection(drivezone_union)


def _build_compact_surface_only_hull_geometry(
    *,
    analysis_center: Point,
    road_branches: list[BranchEvidence],
    drivezone_union: BaseGeometry,
) -> BaseGeometry:
    selected_branches = [
        branch
        for branch in road_branches
        if branch.polygon_length_m > 0.0 and (branch.selected_for_polygon or branch.is_main_direction)
    ]
    if len(selected_branches) < 2 or len(selected_branches) > 3:
        return GeometryCollection()

    hull_parts: list[BaseGeometry] = [
        analysis_center.buffer(max(POLYGON_GROUP_NODE_BUFFER_M + 1.0, 4.0), join_style=1).intersection(
            drivezone_union
        )
    ]
    for branch in selected_branches:
        half_width = MAIN_BRANCH_HALF_WIDTH_M if branch.is_main_direction else SIDE_BRANCH_HALF_WIDTH_M
        branch_clip = _branch_cap_clip_geometry(
            analysis_center,
            angle_deg=branch.angle_deg,
            length_m=max(float(branch.polygon_length_m), 4.0),
            half_width_m=half_width,
            drivezone_union=drivezone_union,
            extension_m=max(0.5, half_width * 0.15),
            lateral_scale=1.05 if branch.is_main_direction else 1.0,
            minimum_half_width_m=max(4.0, half_width * 0.85),
            center_radius_m=max(6.0, half_width + 1.5),
        )
        if not branch_clip.is_empty:
            hull_parts.append(branch_clip)

    if len(hull_parts) < 3:
        return GeometryCollection()

    return unary_union(hull_parts).convex_hull.intersection(drivezone_union)


def _build_semantic_branch_hard_cap_exclusion_geometry(
    *,
    analysis_center: Point,
    road_branches: list[BranchEvidence],
    drivezone_union: BaseGeometry,
    patch_size_m: float,
    resolution_m: float,
    hard_keep_geometries: Iterable[BaseGeometry],
) -> BaseGeometry:
    hard_keep_parts = [
        geometry
        for geometry in hard_keep_geometries
        if geometry is not None and not geometry.is_empty
    ]
    hard_keep_union = unary_union(hard_keep_parts) if hard_keep_parts else GeometryCollection()
    exclusion_geometries: list[BaseGeometry] = []
    for branch in road_branches:
        if branch.polygon_length_m <= 0.0:
            continue
        if not (
            branch.is_main_direction
            or branch.selected_for_polygon
            or (branch.conflict_excluded and not branch.is_main_direction)
        ):
            continue
        half_width = MAIN_BRANCH_HALF_WIDTH_M if branch.is_main_direction else SIDE_BRANCH_HALF_WIDTH_M
        branch_sector = _branch_cap_clip_geometry(
            analysis_center,
            angle_deg=branch.angle_deg,
            length_m=patch_size_m / 2.0,
            half_width_m=half_width,
            drivezone_union=drivezone_union,
            lateral_scale=1.65 if branch.is_main_direction else 1.85,
            minimum_half_width_m=max(6.0, half_width * (1.1 if branch.is_main_direction else 1.0)),
            center_radius_m=max(7.0, half_width + 2.0),
        )
        if branch_sector.is_empty:
            continue
        branch_keep_length_m = max(float(branch.polygon_length_m), 3.0)
        if branch.conflict_excluded and not branch.is_main_direction:
            branch_keep_length_m = min(branch_keep_length_m, 4.0)
        branch_keep_geometry = _branch_cap_clip_geometry(
            analysis_center,
            angle_deg=branch.angle_deg,
            length_m=branch_keep_length_m,
            half_width_m=half_width,
            drivezone_union=drivezone_union,
            extension_m=max(1.0, half_width * 0.25),
            lateral_scale=1.12 if branch.is_main_direction else 1.18,
            minimum_half_width_m=max(4.0, half_width * 0.9),
            center_radius_m=max(6.0, half_width + 1.5),
        )
        keep_parts = [branch_keep_geometry]
        if (
            not hard_keep_union.is_empty
            and (
                not branch.conflict_excluded
                or not branch.is_main_direction
            )
        ):
            keep_parts.append(hard_keep_union.intersection(branch_sector))
        keep_parts = [
            geometry
            for geometry in keep_parts
            if geometry is not None and not geometry.is_empty
        ]
        if not keep_parts:
            continue
        keep_geometry = unary_union(keep_parts).buffer(max(resolution_m, 0.4), join_style=1)
        keep_geometry = keep_geometry.intersection(drivezone_union)
        branch_exclusion_geometry = branch_sector.difference(keep_geometry)
        if not branch_exclusion_geometry.is_empty:
            exclusion_geometries.append(branch_exclusion_geometry)
    if not exclusion_geometries:
        return GeometryCollection()
    return unary_union(exclusion_geometries)


def _build_selected_partial_local_branch_repair_geometries(
    *,
    polygon_geometry: BaseGeometry,
    analysis_center: Point,
    road_branches: list[BranchEvidence],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
) -> list[BaseGeometry]:
    if polygon_geometry.is_empty:
        return []

    local_road_by_id = {road.road_id: road for road in local_roads}
    repair_geometries: list[BaseGeometry] = []
    for branch in road_branches:
        if not (
            branch.selected_for_polygon
            and not branch.is_main_direction
            and not branch.rcsdroad_ids
            and branch.evidence_level == "arm_partial"
            and branch.rc_support_m >= 6.0
            and branch.road_support_m >= 20.0
            and branch.drivezone_support_m >= 10.0
        ):
            continue
        branch_roads = [
            local_road_by_id[road_id].geometry
            for road_id in branch.road_ids
            if road_id in local_road_by_id
        ]
        if not branch_roads:
            continue
        target_length_m = min(max(float(branch.polygon_length_m), 8.0), 10.0)
        current_covered_length_m = sum(
            float(polygon_geometry.intersection(road_geometry).length)
            for road_geometry in branch_roads
        )
        if current_covered_length_m + 0.5 >= target_length_m:
            continue
        branch_clip = _branch_ray_geometry(
            analysis_center,
            angle_deg=branch.angle_deg,
            length_m=target_length_m + 2.0,
        ).buffer(
            max(SIDE_BRANCH_HALF_WIDTH_M * 1.15, 4.2),
            cap_style=2,
            join_style=2,
        ).intersection(drivezone_union)
        if branch_clip.is_empty:
            continue
        branch_repair_parts = [
            road_geometry.intersection(branch_clip).buffer(
                max(SIDE_BRANCH_HALF_WIDTH_M * 1.05, 4.0),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            for road_geometry in branch_roads
        ]
        branch_repair_parts = [
            geometry
            for geometry in branch_repair_parts
            if geometry is not None and not geometry.is_empty
        ]
        if branch_repair_parts:
            repair_geometries.append(unary_union(branch_repair_parts).intersection(drivezone_union))
    return repair_geometries


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
        and branch.rc_support_m >= 6.0
        and branch.road_support_m >= 20.0
        and branch.drivezone_support_m >= 10.0
    ):
        local_support_m = max(branch.drivezone_support_m, min(branch.road_support_m, 10.0))
        return max(8.0, min(local_support_m, 10.0))

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


def _business_branch_length_cap_m(
    branch: BranchEvidence,
    *,
    max_length_m: float,
    branch_has_positive_rc_gap: bool,
    branch_has_local_road_mouth: bool,
    branch_has_minimal_local_road_touch: bool,
) -> float:
    if max_length_m <= 0.0:
        return 0.0
    if (
        branch.selected_for_polygon
        and not branch.is_main_direction
        and not branch.rcsdroad_ids
        and branch.evidence_level == "arm_partial"
        and branch.rc_support_m >= 6.0
        and branch.road_support_m >= 20.0
        and branch.drivezone_support_m >= 10.0
    ):
        return min(max_length_m, 10.0)
    if branch.is_main_direction and branch.evidence_level == "arm_partial" and len(branch.rcsdroad_ids) >= 2:
        return min(max_length_m, 8.0)
    return min(max_length_m, 10.0)


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


def _road_degree_by_node_id(roads: Iterable[ParsedRoad]) -> Counter[str]:
    degree_by_node_id: Counter[str] = Counter()
    for road in roads:
        degree_by_node_id[road.snodeid] += 1
        degree_by_node_id[road.enodeid] += 1
    return degree_by_node_id


def _collect_local_polygon_support_node_ids(
    *,
    support_road_ids: set[str],
    base_support_node_ids: set[str],
    road_by_id: dict[str, ParsedRoad],
    rc_node_by_id: dict[str, ParsedNode],
    group_nodes: list[ParsedNode],
    analysis_center: Point,
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
        node = rc_node_by_id.get(node_id)
        if node is None:
            continue
        if node_id in support_node_ids or degree >= 2:
            support_node_ids.add(node_id)
            continue
        group_distance_m = _min_distance_to_group_nodes(
            node,
            group_nodes=group_nodes,
        )
        center_distance_m = float(node.geometry.distance(analysis_center))
        if (
            group_distance_m <= POLYGON_SUPPORT_NODE_LOCAL_GROUP_DISTANCE_M
            and center_distance_m <= 16.0
        ):
            support_node_ids.add(node_id)
            continue
        if (
            node.mainnodeid not in {None, "0"}
            and group_distance_m <= POLYGON_ENDPOINT_SUPPORT_ORPHAN_GROUP_DISTANCE_M
            and center_distance_m <= 16.0
        ):
            support_node_ids.add(node_id)
    return support_node_ids


def _build_polygon_support_from_association(
    *,
    positive_rc_road_ids: set[str],
    base_support_node_ids: set[str],
    excluded_rc_road_ids: set[str],
    analysis_center: Point,
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
        analysis_center=analysis_center,
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
        analysis_center=analysis_center,
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
    simple_center_support = len(group_nodes) <= 1 and len(support_node_ids) <= 1
    center_segment_extension_m = (
        8.0 if simple_center_support else POLYGON_LOCAL_RC_SEGMENT_EXTENSION_M
    )
    center_group_clip_radius_m = (
        10.0 if simple_center_support else POLYGON_SUPPORT_CLIP_RADIUS_M
    )
    near_center_support_node_clip_radius_m = (
        10.0 if simple_center_support else POLYGON_SUPPORT_CLIP_RADIUS_M
    )
    center_geometry = analysis_center.buffer(center_segment_extension_m)
    group_clip_geometries = [
        node.geometry.buffer(
            center_group_clip_radius_m
            if float(node.geometry.distance(analysis_center)) <= 0.5
            else POLYGON_SUPPORT_CLIP_RADIUS_M
        )
        for node in group_nodes
    ]
    support_node_clip_geometries = [
        node.geometry.buffer(
            near_center_support_node_clip_radius_m
            if float(node.geometry.distance(analysis_center)) <= 8.0
            else POLYGON_SUPPORT_CLIP_RADIUS_M
        )
        for node in local_rc_nodes
        if node.node_id in support_node_ids
    ]
    support_focus_parts: list[BaseGeometry] = [
        center_geometry,
        *group_clip_geometries,
        *support_node_clip_geometries,
    ]
    support_focus_parts.extend(
        LineString(
            [
                (float(analysis_center.x), float(analysis_center.y)),
                (float(node.geometry.x), float(node.geometry.y)),
            ]
        ).buffer(
            max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 1.6, 2.0),
            cap_style=2,
            join_style=2,
        )
        for node in local_rc_nodes
        if node.node_id in support_node_ids
        and float(node.geometry.distance(analysis_center)) > 0.5
    )
    support_focus_parts = [
        geometry
        for geometry in support_focus_parts
        if geometry is not None and not geometry.is_empty
    ]
    support_focus_geometry = (
        unary_union(support_focus_parts).buffer(
            max(POLYGON_SUPPORT_CLIP_BUFFER_M + 1.0, 3.0),
            join_style=1,
        )
        if support_focus_parts
        else center_geometry
    )

    clip_geometries: list[BaseGeometry] = [center_geometry]
    clip_geometries.extend(group_clip_geometries)
    clip_geometries.extend(
        road.geometry.intersection(support_focus_geometry)
        for road in local_rc_roads
        if (
            road.road_id in support_road_ids
            and road.snodeid in support_node_ids
            and road.enodeid in support_node_ids
            and not road.geometry.intersection(support_focus_geometry).is_empty
        )
    )
    clip_geometries.extend(support_node_clip_geometries)
    clip_geometries = [geometry for geometry in clip_geometries if not geometry.is_empty]
    if not clip_geometries:
        return analysis_center.buffer(center_segment_extension_m)
    return unary_union(clip_geometries).buffer(POLYGON_SUPPORT_CLIP_BUFFER_M)


def _build_associated_output_clip(
    *,
    analysis_center: Point,
    group_nodes: list[ParsedNode],
    local_rc_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    support_road_ids: set[str] | list[str],
    support_node_ids: set[str] | list[str],
) -> BaseGeometry:
    """Backward-compatible wrapper for legacy tests expecting this helper name."""
    return _build_polygon_support_clip(
        analysis_center=analysis_center,
        group_nodes=group_nodes,
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        support_road_ids=set(support_road_ids),
        support_node_ids=set(support_node_ids),
    )


def _collect_selected_rc_support_road_ids(
    *,
    road_branches: list[BranchEvidence],
    positive_rc_groups: set[str],
    negative_rc_groups: set[str],
    rc_branch_by_id: dict[str, BranchEvidence],
    positive_rc_road_ids: set[str],
    local_rc_roads: list[ParsedRoad],
    analysis_center: Point,
    drivezone_union: BaseGeometry,
) -> tuple[set[str], dict[str, BaseGeometry]]:
    local_rc_road_by_id = {road.road_id: road for road in local_rc_roads}
    selected_rc_support_road_ids: set[str] = set()
    selected_rc_support_clips: dict[str, list[BaseGeometry]] = {}

    for branch in road_branches:
        if branch.polygon_length_m <= 0.0:
            continue
        matched_positive_group_ids = [
            group_id
            for group_id in branch.rcsdroad_ids
            if group_id in positive_rc_groups and group_id not in negative_rc_groups
        ]
        if not matched_positive_group_ids:
            continue
        branch_support_clip = _branch_ray_geometry(
            analysis_center,
            angle_deg=branch.angle_deg,
            length_m=max(float(branch.polygon_length_m or 0.0) + 6.0, 10.0),
        ).buffer(
            max(RC_ROAD_BUFFER_M * 1.5, SIDE_BRANCH_HALF_WIDTH_M * 1.2),
            cap_style=2,
            join_style=2,
        ).intersection(drivezone_union)
        if branch_support_clip.is_empty:
            continue
        for group_id in matched_positive_group_ids:
            fallback_positive_roads = {
                road_id
                for road_id in rc_branch_by_id[group_id].road_ids
                if road_id in positive_rc_road_ids
            }
            if not fallback_positive_roads:
                continue
            if not branch.is_main_direction and not branch.conflict_excluded:
                for road_id in fallback_positive_roads:
                    selected_rc_support_road_ids.add(road_id)
                    selected_rc_support_clips.setdefault(road_id, []).append(branch_support_clip)
            candidate_roads = [
                local_rc_road_by_id[road_id]
                for road_id in rc_branch_by_id[group_id].road_ids
                if road_id in local_rc_road_by_id
                and local_rc_road_by_id[road_id].geometry.intersects(branch_support_clip)
            ]
            if not candidate_roads:
                continue
            representative_road = min(
                candidate_roads,
                key=lambda road: (
                    float(road.geometry.distance(analysis_center)),
                    -float(road.geometry.intersection(branch_support_clip).length),
                    float(road.geometry.length),
                ),
            )
            selected_rc_support_road_ids.add(representative_road.road_id)
            if not branch.is_main_direction:
                selected_rc_support_clips.setdefault(representative_road.road_id, []).append(branch_support_clip)
            else:
                existing_clips = selected_rc_support_clips.get(representative_road.road_id, [])
                if not existing_clips:
                    selected_rc_support_clips[representative_road.road_id] = [branch_support_clip]
                else:
                    existing_clip = existing_clips[0]
                    existing_cover_length_m = float(
                        representative_road.geometry.intersection(existing_clip).length
                    )
                    candidate_cover_length_m = float(
                        representative_road.geometry.intersection(branch_support_clip).length
                    )
                    if candidate_cover_length_m < existing_cover_length_m:
                        selected_rc_support_clips[representative_road.road_id] = [branch_support_clip]

    support_clip_by_road_id: dict[str, BaseGeometry] = {}
    for road_id, clip_geometries in selected_rc_support_clips.items():
        valid_geometries = [
            geometry
            for geometry in clip_geometries
            if geometry is not None and not geometry.is_empty
        ]
        if not valid_geometries:
            continue
        support_clip_by_road_id[road_id] = (
            unary_union(valid_geometries).intersection(drivezone_union)
            if len(valid_geometries) > 1
            else valid_geometries[0]
        )
    return selected_rc_support_road_ids, support_clip_by_road_id


def _restrict_keep_geometries_to_focus(
    geometries: Iterable[BaseGeometry],
    *,
    focus_geometry: BaseGeometry | None,
) -> list[BaseGeometry]:
    restricted_geometries: list[BaseGeometry] = []
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        clipped_geometry = geometry
        if focus_geometry is not None and not focus_geometry.is_empty:
            clipped_geometry = geometry.intersection(focus_geometry)
        if clipped_geometry is None or clipped_geometry.is_empty:
            continue
        restricted_geometries.append(clipped_geometry)
    return restricted_geometries


def _build_selected_rc_support_geometries(
    *,
    selected_rc_support_road_ids: set[str],
    polygon_support_rc_road_ids: set[str],
    selected_rc_support_clip_by_road_id: dict[str, BaseGeometry],
    positive_nonmain_bridge_road_ids: set[str],
    local_rc_roads: list[ParsedRoad],
    local_rc_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    local_nodes: list[ParsedNode],
    local_road_degree_by_node_id: Counter[str],
    group_nodes: list[ParsedNode],
    normalized_mainnodeid: str,
    analysis_center: Point,
    drivezone_union: BaseGeometry,
    semantic_mainnodeids: set[str] | None = None,
) -> tuple[list[BaseGeometry], set[str]]:
    road_by_id = {road.road_id: road for road in local_rc_roads}
    rc_node_by_id = {node.node_id: node for node in local_rc_nodes}
    local_node_by_id = {node.node_id: node for node in local_nodes}
    target_group_node_ids = {node.node_id for node in group_nodes}
    support_geometries: list[BaseGeometry] = []
    support_node_ids: set[str] = set()
    endpoint_cover = POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.2

    for road_id in selected_rc_support_road_ids:
        road = road_by_id.get(road_id)
        support_clip = selected_rc_support_clip_by_road_id.get(road_id)
        if road is None or support_clip is None or support_clip.is_empty:
            continue
        local_geometry = road.geometry.intersection(
            support_clip.buffer(RC_ROAD_BUFFER_M + 1.0, join_style=1)
        )
        foreign_local_junction_cap_geometries = [
            node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M * 1.8, 5.5)).intersection(drivezone_union)
            for node in local_nodes
            if _is_foreign_local_junction_node(
                node=node,
                target_group_node_ids=target_group_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            and float(node.geometry.distance(analysis_center)) > 8.0
            and float(road.geometry.distance(node.geometry)) <= 6.5
        ]
        foreign_local_junction_cap_geometries = [
            geometry
            for geometry in foreign_local_junction_cap_geometries
            if geometry is not None and not geometry.is_empty
        ]
        has_foreign_local_junction_near_support = bool(foreign_local_junction_cap_geometries)
        if foreign_local_junction_cap_geometries:
            local_geometry = local_geometry.difference(unary_union(foreign_local_junction_cap_geometries))
        if local_geometry.is_empty or local_geometry.length <= 0.5:
            continue
        support_cover = support_clip.buffer(endpoint_cover)
        long_endpoint_support_span = local_geometry.length >= 60.0
        nearby_local_node_distance_cap_m = 14.0 if long_endpoint_support_span else 11.0
        nearby_local_node_limit = 3 if long_endpoint_support_span else 2
        local_node_road_clip_radius_m = 12.0 if long_endpoint_support_span else 11.0
        endpoint_local_support_cap_buffer_m = (
            max(1.0, SIDE_BRANCH_HALF_WIDTH_M * 0.45)
            if long_endpoint_support_span
            else max(1.0, SIDE_BRANCH_HALF_WIDTH_M * 0.4)
        )
        endpoint_node_geometries: list[BaseGeometry] = []
        endpoint_road_geometries: list[BaseGeometry] = []
        for node_id in (road.snodeid, road.enodeid):
            node = rc_node_by_id.get(node_id)
            if node is None or not support_cover.covers(node.geometry):
                continue
            support_node_ids.add(node_id)
            node_geometry = node.geometry.buffer(POLYGON_RC_NODE_BUFFER_M).intersection(drivezone_union)
            if not node_geometry.is_empty:
                support_geometries.append(node_geometry)
                endpoint_node_geometries.append(node_geometry)
            endpoint_support_clip = node.geometry.buffer(
                max(POLYGON_RC_NODE_BUFFER_M * 2.5, 12.0)
            ).intersection(drivezone_union)
            endpoint_road_geometry = local_geometry.intersection(
                endpoint_support_clip.buffer(RC_ROAD_BUFFER_M + 1.0, join_style=1)
            )
            if not endpoint_road_geometry.is_empty:
                endpoint_road_geometries.append(endpoint_road_geometry)
            endpoint_cap_parts = [
                geometry
                for geometry in [
                    node_geometry,
                    endpoint_road_geometry.buffer(
                        RC_ROAD_BUFFER_M * 0.95,
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                    if not endpoint_road_geometry.is_empty
                    else GeometryCollection(),
                ]
                if geometry is not None and not geometry.is_empty
            ]
            if endpoint_cap_parts:
                endpoint_support_cap = unary_union(endpoint_cap_parts).convex_hull.buffer(
                    max(0.6, RC_ROAD_BUFFER_M * 0.45),
                    join_style=1,
                ).intersection(drivezone_union)
                if not endpoint_support_cap.is_empty:
                    support_geometries.append(endpoint_support_cap)
            nearby_local_support_parts: list[BaseGeometry] = []
            nearby_local_nodes = sorted(
                (
                    (float(local_node.geometry.distance(node.geometry)), local_node)
                    for local_node in local_nodes
                    if (
                        _is_supportable_local_node_for_rc_bridge(
                            node=local_node,
                            target_group_node_ids=target_group_node_ids,
                            normalized_mainnodeid=normalized_mainnodeid,
                            local_road_degree_by_node_id=local_road_degree_by_node_id,
                        )
                        or any(
                            local_road.road_id in positive_nonmain_bridge_road_ids
                            and (
                                local_road.snodeid == local_node.node_id
                                or local_road.enodeid == local_node.node_id
                            )
                            for local_road in local_roads
                        )
                    )
                    if local_road_degree_by_node_id.get(local_node.node_id, 0) >= 2
                    and float(local_node.geometry.distance(node.geometry)) <= nearby_local_node_distance_cap_m
                ),
                key=lambda item: (
                    item[0],
                    float(item[1].geometry.distance(analysis_center)),
                ),
            )[:nearby_local_node_limit]
            for local_node_distance_m, local_node in nearby_local_nodes:
                local_node_degree = local_road_degree_by_node_id.get(local_node.node_id, 0)
                local_node_distance_to_center_m = float(local_node.geometry.distance(analysis_center))
                local_node_geometry = local_node.geometry.buffer(
                    max(
                        POLYGON_GROUP_NODE_BUFFER_M * (0.8 if local_node_degree >= 3 else 0.7),
                        2.2 if local_node_degree >= 3 else 1.8,
                    )
                ).intersection(drivezone_union)
                if not local_node_geometry.is_empty:
                    nearby_local_support_parts.append(local_node_geometry)
                if local_node_distance_m > 0.75:
                    local_connector_geometry = LineString(
                        [
                            (float(node.geometry.x), float(node.geometry.y)),
                            (float(local_node.geometry.x), float(local_node.geometry.y)),
                        ]
                    ).buffer(
                        max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.55, 1.2),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                    if not local_connector_geometry.is_empty:
                        nearby_local_support_parts.append(local_connector_geometry)
                local_road_clip = local_node.geometry.buffer(
                    (
                        max(local_node_road_clip_radius_m, 18.0)
                        if local_node_degree < 3
                        else local_node_road_clip_radius_m + 1.0
                    )
                ).intersection(drivezone_union)
                if local_road_clip.is_empty:
                    continue
                for local_road in local_roads:
                    if local_road.snodeid != local_node.node_id and local_road.enodeid != local_node.node_id:
                        continue
                    local_road_geometry = local_road.geometry.intersection(local_road_clip)
                    if local_road_geometry.is_empty or local_road_geometry.length <= 0.5:
                        continue
                    if local_node_degree < 3:
                        other_node_id = (
                            local_road.enodeid
                            if local_road.snodeid == local_node.node_id
                            else local_road.snodeid
                        )
                        other_node = local_node_by_id.get(other_node_id)
                        if (
                            other_node is not None
                            and float(other_node.geometry.distance(analysis_center))
                            > local_node_distance_to_center_m + 14.0
                        ):
                            continue
                        if (
                            other_node is not None
                            and float(other_node.geometry.distance(analysis_center))
                            > local_node_distance_to_center_m + 8.0
                            and float(local_road_geometry.length) < 3.0
                        ):
                            continue
                    local_road_support_geometry = local_road_geometry.buffer(
                        max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                    if not local_road_support_geometry.is_empty:
                        nearby_local_support_parts.append(local_road_support_geometry)
            if nearby_local_support_parts:
                endpoint_local_support_cap = unary_union(
                    [*endpoint_cap_parts, *nearby_local_support_parts]
                ).convex_hull.buffer(
                    endpoint_local_support_cap_buffer_m,
                    join_style=1,
                ).intersection(drivezone_union)
                if not endpoint_local_support_cap.is_empty:
                    support_geometries.append(endpoint_local_support_cap)
        support_road_geometry = local_geometry
        if (long_endpoint_support_span or has_foreign_local_junction_near_support) and endpoint_road_geometries:
            capped_support_road_geometry = unary_union(endpoint_road_geometries).intersection(local_geometry)
            if (
                not capped_support_road_geometry.is_empty
                and capped_support_road_geometry.length
                >= (4.0 if has_foreign_local_junction_near_support else 6.0)
            ):
                support_road_geometry = capped_support_road_geometry
        road_geometry = support_road_geometry.buffer(
            RC_ROAD_BUFFER_M * 0.9,
            cap_style=2,
            join_style=2,
        ).intersection(drivezone_union)
        if not road_geometry.is_empty:
            support_geometries.append(road_geometry)
        nearest_support_point = nearest_points(analysis_center, support_road_geometry)[1]
        connector_geometry = LineString(
            [
                (float(analysis_center.x), float(analysis_center.y)),
                (float(nearest_support_point.x), float(nearest_support_point.y)),
            ]
        ).buffer(
            POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M,
            cap_style=2,
            join_style=2,
        ).intersection(drivezone_union)
        if not connector_geometry.is_empty:
            support_geometries.append(connector_geometry)
        if local_geometry.length <= 20.0:
            cap_parts = [
                geometry
                for geometry in [road_geometry, connector_geometry, *endpoint_node_geometries]
                if geometry is not None and not geometry.is_empty
            ]
            if cap_parts:
                short_support_cap = unary_union(cap_parts).convex_hull.buffer(
                    max(0.8, RC_ROAD_BUFFER_M * 0.7),
                    join_style=1,
                ).intersection(drivezone_union)
                if not short_support_cap.is_empty:
                    support_geometries.append(short_support_cap)

    return support_geometries, support_node_ids


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


def _relax_targeted_foreign_trim_support_gaps(
    *,
    uncovered_support_node_ids: list[str],
    uncovered_support_road_ids: list[str],
    rc_node_by_id: dict[str, ParsedNode],
    rc_road_by_id: dict[str, ParsedRoad],
    hard_support_node_ids: set[str],
    hard_support_road_ids: set[str],
    analysis_center: Point | None = None,
    relax_node_ids: set[str] | None = None,
    relax_road_ids: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    relax_node_ids = relax_node_ids or set()
    relax_road_ids = relax_road_ids or set()
    far_relax_distance_m = (
        POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M
        + POLYGON_FOREIGN_TARGET_ARM_OVERREACH_TOLERANCE_M
    )
    remaining_support_node_ids: list[str] = []
    for node_id in uncovered_support_node_ids:
        if node_id in relax_node_ids:
            continue
        node = rc_node_by_id.get(node_id)
        if node is None:
            remaining_support_node_ids.append(node_id)
            continue
        if (
            analysis_center is not None
            and float(node.geometry.distance(analysis_center)) > far_relax_distance_m
        ):
            continue
        if node_id in hard_support_node_ids or node.mainnodeid not in {None, "0"}:
            remaining_support_node_ids.append(node_id)

    remaining_support_road_ids: list[str] = []
    for road_id in uncovered_support_road_ids:
        if road_id in relax_road_ids:
            continue
        road = rc_road_by_id.get(road_id)
        if road is None:
            remaining_support_road_ids.append(road_id)
            continue
        endpoint_nodes = [
            rc_node_by_id.get(road.snodeid),
            rc_node_by_id.get(road.enodeid),
        ]
        present_endpoint_nodes = [node for node in endpoint_nodes if node is not None]
        has_missing_endpoint = len(present_endpoint_nodes) < 2
        has_nonzero_endpoint = any(
            node is not None and node.mainnodeid not in {None, "0"}
            for node in endpoint_nodes
        )
        nonzero_endpoint_count = sum(
            1
            for node in endpoint_nodes
            if node is not None and node.mainnodeid not in {None, "0"}
        )
        standalone_semantic_endpoint_count = sum(
            1
            for node in endpoint_nodes
            if (
                node is not None
                and node.mainnodeid not in {None, "0"}
                and _normalize_id(node.mainnodeid) == node.node_id
            )
        )
        endpoint_distances_to_center_m = [
            float(node.geometry.distance(analysis_center))
            for node in endpoint_nodes
            if node is not None and analysis_center is not None
        ]
        if endpoint_distances_to_center_m and min(endpoint_distances_to_center_m) > far_relax_distance_m:
            continue
        if road_id in hard_support_road_ids:
            if (
                nonzero_endpoint_count >= 2
                and not (
                    standalone_semantic_endpoint_count <= 1
                    and float(road.geometry.length) <= POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_LENGTH_M
                )
            ):
                remaining_support_road_ids.append(road_id)
            continue
        if not has_nonzero_endpoint:
            continue
        if nonzero_endpoint_count <= 1:
            continue
        if has_missing_endpoint and not any(
            node.mainnodeid not in {None, "0"}
            for node in present_endpoint_nodes
        ):
            continue
        if has_nonzero_endpoint:
            remaining_support_road_ids.append(road_id)
            continue
        if float(road.geometry.length) > 12.0:
            remaining_support_road_ids.append(road_id)

    return remaining_support_node_ids, remaining_support_road_ids


def _relax_targeted_foreign_trim_selected_gaps(
    *,
    uncovered_selected_node_ids: list[str],
    uncovered_selected_road_ids: list[str],
    rc_node_by_id: dict[str, ParsedNode],
    rc_road_by_id: dict[str, ParsedRoad],
    analysis_center: Point | None = None,
    hard_selected_node_ids: set[str] | None = None,
    relax_node_ids: set[str] | None = None,
    relax_road_ids: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    hard_selected_node_ids = hard_selected_node_ids or set()
    relax_node_ids = relax_node_ids or set()
    relax_road_ids = relax_road_ids or set()
    far_relax_distance_m = (
        POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M
        + POLYGON_FOREIGN_TARGET_ARM_OVERREACH_TOLERANCE_M
    )
    remaining_selected_node_ids: list[str] = []
    for node_id in uncovered_selected_node_ids:
        node = rc_node_by_id.get(node_id)
        if node_id in hard_selected_node_ids:
            if (
                node is not None
                and analysis_center is not None
                and float(node.geometry.distance(analysis_center)) > far_relax_distance_m
            ):
                continue
            if (
                node is not None
                and node.mainnodeid in {None, "0"}
                and analysis_center is not None
                and float(node.geometry.distance(analysis_center))
                > max(POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M + 2.0, 14.0)
            ):
                continue
            remaining_selected_node_ids.append(node_id)
            continue
        if node_id in relax_node_ids:
            continue
        if node is None:
            remaining_selected_node_ids.append(node_id)
            continue
        if (
            analysis_center is not None
            and float(node.geometry.distance(analysis_center)) > far_relax_distance_m
        ):
            continue
        if node.mainnodeid not in {None, "0"}:
            remaining_selected_node_ids.append(node_id)

    remaining_selected_road_ids: list[str] = []
    for road_id in uncovered_selected_road_ids:
        if road_id in relax_road_ids:
            continue
        road = rc_road_by_id.get(road_id)
        if road is None:
            remaining_selected_road_ids.append(road_id)
            continue
        endpoint_nodes = [
            rc_node_by_id.get(road.snodeid),
            rc_node_by_id.get(road.enodeid),
        ]
        present_endpoint_nodes = [node for node in endpoint_nodes if node is not None]
        has_missing_endpoint = len(present_endpoint_nodes) < 2
        has_nonzero_endpoint = any(
            node is not None and node.mainnodeid not in {None, "0"}
            for node in endpoint_nodes
        )
        nonzero_endpoint_count = sum(
            1
            for node in endpoint_nodes
            if node is not None and node.mainnodeid not in {None, "0"}
        )
        standalone_semantic_endpoint_count = sum(
            1
            for node in endpoint_nodes
            if (
                node is not None
                and node.mainnodeid not in {None, "0"}
                and _normalize_id(node.mainnodeid) == node.node_id
            )
        )
        endpoint_distances_to_center_m = [
            float(node.geometry.distance(analysis_center))
            for node in endpoint_nodes
            if node is not None and analysis_center is not None
        ]
        if endpoint_distances_to_center_m and min(endpoint_distances_to_center_m) > far_relax_distance_m:
            continue
        if nonzero_endpoint_count >= 2:
            if (
                standalone_semantic_endpoint_count <= 1
                and float(road.geometry.length) <= POLYGON_SINGLE_SIDED_ENDPOINT_SUPPORT_MAX_LENGTH_M
            ):
                continue
            remaining_selected_road_ids.append(road_id)
            continue
        if not has_nonzero_endpoint:
            continue
        if nonzero_endpoint_count <= 1:
            continue
        if has_missing_endpoint and not any(
            node.mainnodeid not in {None, "0"}
            for node in present_endpoint_nodes
        ):
            continue
        if has_nonzero_endpoint:
            remaining_selected_road_ids.append(road_id)
            continue
        if float(road.geometry.length) > 12.0:
            remaining_selected_road_ids.append(road_id)

    return remaining_selected_node_ids, remaining_selected_road_ids


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
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> bool:
    if node.node_id in target_group_node_ids:
        return False
    local_degree = local_road_degree_by_node_id.get(node.node_id, 0)
    if local_degree == 2:
        return False
    if node.mainnodeid is not None:
        if node.mainnodeid == normalized_mainnodeid:
            return False
        if semantic_mainnodeids is not None and node.mainnodeid not in semantic_mainnodeids:
            return False
        return True
    return local_degree >= 3


def _is_polygon_cover_foreign_local_junction_node(
    *,
    node: ParsedNode,
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    analysis_center: Point,
    semantic_mainnodeids: set[str] | None = None,
) -> bool:
    if node.node_id in target_group_node_ids:
        return False
    return _is_foreign_local_junction_node(
        node=node,
        target_group_node_ids=target_group_node_ids,
        normalized_mainnodeid=normalized_mainnodeid,
        local_road_degree_by_node_id=local_road_degree_by_node_id,
        semantic_mainnodeids=semantic_mainnodeids,
    )


def _is_foreign_local_group_member_node(
    *,
    node: ParsedNode,
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    semantic_mainnodeids: set[str] | None = None,
) -> bool:
    if node.node_id in target_group_node_ids:
        return False
    if node.mainnodeid is None or node.mainnodeid == normalized_mainnodeid:
        return False
    if semantic_mainnodeids is not None and node.mainnodeid not in semantic_mainnodeids:
        return False
    return True


def _is_foreign_local_semantic_node(
    *,
    node: ParsedNode,
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> bool:
    if _is_foreign_local_group_member_node(
        node=node,
        target_group_node_ids=target_group_node_ids,
        normalized_mainnodeid=normalized_mainnodeid,
        semantic_mainnodeids=semantic_mainnodeids,
    ):
        return True
    local_degree = local_road_degree_by_node_id.get(node.node_id, 0)
    if node.node_id not in target_group_node_ids and local_degree == 2:
        return False
    return _is_foreign_local_junction_node(
        node=node,
        target_group_node_ids=target_group_node_ids,
        normalized_mainnodeid=normalized_mainnodeid,
        local_road_degree_by_node_id=local_road_degree_by_node_id,
        semantic_mainnodeids=semantic_mainnodeids,
    )


def _polygon_substantively_covers_node(
    polygon_geometry: BaseGeometry,
    node_geometry: BaseGeometry,
    *,
    cover_radius_m: float,
) -> bool:
    if polygon_geometry.is_empty:
        return False
    return polygon_geometry.covers(node_geometry.buffer(max(cover_radius_m, 0.5)))


def _is_effective_rc_junction_node(
    *,
    node: ParsedNode,
    local_rc_road_degree_by_node_id: Counter[str],
) -> bool:
    local_degree = local_rc_road_degree_by_node_id.get(node.node_id, 0)
    if local_degree == 2:
        return False
    if local_degree >= 3:
        return True
    return node.mainnodeid not in {None, "0"}


def _is_supportable_local_node_for_rc_bridge(
    *,
    node: ParsedNode,
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
) -> bool:
    if node.node_id in target_group_node_ids:
        return True
    if node.mainnodeid not in {None, normalized_mainnodeid}:
        return False
    if local_road_degree_by_node_id.get(node.node_id, 0) <= 2:
        return True
    return not _is_foreign_local_junction_node(
        node=node,
        target_group_node_ids=target_group_node_ids,
        normalized_mainnodeid=normalized_mainnodeid,
        local_road_degree_by_node_id=local_road_degree_by_node_id,
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
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> BaseGeometry:
    if polygon_geometry.is_empty:
        return GeometryCollection()

    target_group_node_ids = {node.node_id for node in group_nodes}
    exclusion_geometries: list[BaseGeometry] = []
    for node in local_nodes:
        is_foreign_junction_node = _is_foreign_local_junction_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        is_foreign_group_member_node = _is_foreign_local_group_member_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        if not is_foreign_junction_node and not is_foreign_group_member_node:
            continue
        if polygon_geometry.distance(node.geometry) > POLYGON_FOREIGN_NODE_TRIGGER_DISTANCE_M:
            continue
        node_buffer = node.geometry.buffer(
            POLYGON_FOREIGN_NODE_BUFFER_M
            if is_foreign_junction_node
            else POLYGON_FOREIGN_NODE_BUFFER_M * 0.8
        ).intersection(drivezone_union)
        if not node_buffer.is_empty:
            exclusion_geometries.append(node_buffer)
        incident_clip = node.geometry.buffer(
            POLYGON_FOREIGN_NODE_ROAD_EXTENSION_M
            if is_foreign_junction_node
            else POLYGON_FOREIGN_NODE_ROAD_EXTENSION_M * 0.85
        )
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
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
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
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            semantic_mainnodeids=semantic_mainnodeids,
        )
    ]
    if not foreign_distances:
        return False
    return min(foreign_distances) + 3.0 < representative_distance_m


def _build_explicit_foreign_group_arm_exclusion_geometry(
    *,
    polygon_geometry: BaseGeometry,
    analysis_center: Point,
    normalized_mainnodeid: str,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    protected_road_ids: set[str],
    drivezone_union: BaseGeometry,
    local_road_degree_by_node_id: Counter[str],
    semantic_mainnodeids: set[str] | None = None,
) -> BaseGeometry:
    if polygon_geometry.is_empty:
        return GeometryCollection()

    target_group_node_ids = {node.node_id for node in group_nodes}
    local_node_by_id = {node.node_id: node for node in local_nodes}
    polygon_cover = polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
    exclusion_geometries: list[BaseGeometry] = []
    for node in local_nodes:
        is_foreign_junction_node = _is_polygon_cover_foreign_local_junction_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            analysis_center=analysis_center,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        is_foreign_group_member_node = _is_foreign_local_group_member_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        if not is_foreign_junction_node and not is_foreign_group_member_node:
            continue
        if not polygon_cover.covers(node.geometry):
            continue
        if float(node.geometry.distance(analysis_center)) <= 8.0:
            continue
        incident_roads = [
            road
            for road in local_roads
            if road.snodeid == node.node_id or road.enodeid == node.node_id
        ]
        if not incident_roads:
            continue

        def _other_endpoint_distance_to_center(road: ParsedRoad) -> float:
            other_node_id = road.enodeid if road.snodeid == node.node_id else road.snodeid
            other_node = local_node_by_id.get(other_node_id)
            if other_node is not None:
                return float(other_node.geometry.distance(analysis_center))
            return float(road.geometry.distance(analysis_center))

        node_distance_to_center = float(node.geometry.distance(analysis_center))
        keep_road_candidates = [
            road
            for road in incident_roads
            if _other_endpoint_distance_to_center(road) + 0.5 < node_distance_to_center
        ]
        if keep_road_candidates:
            keep_road_ids = {
                road.road_id
                for road in sorted(
                    keep_road_candidates,
                    key=lambda road: (
                        _other_endpoint_distance_to_center(road),
                        -float(polygon_geometry.intersection(road.geometry).length),
                        float(road.geometry.length),
                    ),
                )[:1]
            }
        else:
            keep_road_ids = {
                min(
                    incident_roads,
                    key=lambda road: (
                        _other_endpoint_distance_to_center(road),
                        -float(polygon_geometry.intersection(road.geometry).length),
                        float(road.geometry.length),
                    ),
                ).road_id
            }
        if not keep_road_ids:
            continue
        near_clip = node.geometry.buffer(10.0).intersection(drivezone_union)
        far_clip = node.geometry.buffer(35.0).intersection(drivezone_union)
        if near_clip.is_empty or far_clip.is_empty:
            continue
        node_core_exclusion_geometry = node.geometry.buffer(
            max(
                POLYGON_GROUP_NODE_BUFFER_M * (1.05 if is_foreign_junction_node else 0.9),
                3.2 if is_foreign_junction_node else 2.4,
            )
        ).intersection(drivezone_union)
        if is_foreign_junction_node and not node_core_exclusion_geometry.is_empty:
            exclusion_geometries.append(node_core_exclusion_geometry)
        node_keep_geometry = (
            GeometryCollection()
            if is_foreign_junction_node
            else node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M * 0.75, 2.0)).intersection(drivezone_union)
        )
        for road in incident_roads:
            local_far_geometry = road.geometry.intersection(far_clip)
            if local_far_geometry.is_empty or polygon_geometry.intersection(local_far_geometry).length <= 6.0:
                continue
            keep_clip = node.geometry.buffer(
                12.0 if road.road_id in keep_road_ids else 7.5
            ).intersection(drivezone_union)
            local_keep_geometry = road.geometry.intersection(keep_clip)
            if not local_keep_geometry.is_empty and not node_core_exclusion_geometry.is_empty:
                local_keep_geometry = local_keep_geometry.difference(
                    node_core_exclusion_geometry.buffer(max(0.2, POLYGON_SUPPORT_VALIDATION_TOLERANCE_M))
                )
            keep_parts = [node_keep_geometry]
            if not local_keep_geometry.is_empty:
                keep_parts.append(
                    local_keep_geometry.buffer(
                        max(
                            ROAD_BUFFER_M * (0.85 if is_foreign_junction_node else 0.95),
                            SIDE_BRANCH_HALF_WIDTH_M * (0.7 if is_foreign_junction_node else 0.85),
                        ),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                )
            keep_geometry = unary_union(
                [geometry for geometry in keep_parts if geometry is not None and not geometry.is_empty]
            ).buffer(0.4, join_style=1).intersection(drivezone_union)
            road_exclusion_geometry = local_far_geometry.buffer(
                max(
                    ROAD_BUFFER_M * (1.0 if is_foreign_junction_node else 0.95),
                    SIDE_BRANCH_HALF_WIDTH_M * (0.95 if is_foreign_junction_node else 0.9),
                ),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if road_exclusion_geometry.is_empty:
                continue
            road_exclusion_geometry = road_exclusion_geometry.difference(keep_geometry)
            if not road_exclusion_geometry.is_empty:
                exclusion_geometries.append(road_exclusion_geometry)

    if not exclusion_geometries:
        return GeometryCollection()
    return unary_union(exclusion_geometries)


def _build_strict_foreign_local_junction_core_exclusion_geometry(
    *,
    polygon_geometry: BaseGeometry,
    analysis_center: Point,
    normalized_mainnodeid: str,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
    local_road_degree_by_node_id: Counter[str],
    keep_geometry: BaseGeometry | None = None,
    semantic_mainnodeids: set[str] | None = None,
) -> BaseGeometry:
    if polygon_geometry.is_empty:
        return GeometryCollection()

    target_group_node_ids = {node.node_id for node in group_nodes}
    polygon_cover = polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
    node_exclusion_geometries: list[BaseGeometry] = []
    road_exclusion_geometries: list[BaseGeometry] = []
    for node in local_nodes:
        if not _is_polygon_cover_foreign_local_junction_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            analysis_center=analysis_center,
            semantic_mainnodeids=semantic_mainnodeids,
        ):
            continue
        if float(node.geometry.distance(analysis_center)) <= 8.0:
            continue
        if not polygon_cover.covers(node.geometry):
            continue
        node_exclusion_radius_m = max(POLYGON_GROUP_NODE_BUFFER_M * 2.0, 6.5)
        if (
            keep_geometry is not None
            and not keep_geometry.is_empty
            and keep_geometry.intersects(node.geometry.buffer(4.0))
        ):
            node_exclusion_radius_m = max(POLYGON_GROUP_NODE_BUFFER_M * 1.5, 2.2)
        node_exclusion_geometry = node.geometry.buffer(
            node_exclusion_radius_m
        ).intersection(drivezone_union)
        if not node_exclusion_geometry.is_empty:
            node_exclusion_geometries.append(node_exclusion_geometry)
        incident_clip = node.geometry.buffer(16.0).intersection(drivezone_union)
        if incident_clip.is_empty:
            continue
        for road in local_roads:
            if road.snodeid != node.node_id and road.enodeid != node.node_id:
                continue
            local_geometry = road.geometry.intersection(incident_clip)
            if local_geometry.is_empty or local_geometry.length <= 0.5:
                continue
            road_exclusion_geometry = local_geometry.buffer(
                max(ROAD_BUFFER_M * 1.05, SIDE_BRANCH_HALF_WIDTH_M * 1.05),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if not road_exclusion_geometry.is_empty:
                road_exclusion_geometries.append(road_exclusion_geometry)

    if not node_exclusion_geometries and not road_exclusion_geometries:
        return GeometryCollection()
    node_exclusion_geometry = (
        unary_union(node_exclusion_geometries)
        if node_exclusion_geometries
        else GeometryCollection()
    )
    road_exclusion_geometry = (
        unary_union(road_exclusion_geometries)
        if road_exclusion_geometries
        else GeometryCollection()
    )
    if keep_geometry is not None and not keep_geometry.is_empty and not road_exclusion_geometry.is_empty:
        road_exclusion_geometry = road_exclusion_geometry.difference(keep_geometry)
    if node_exclusion_geometry.is_empty:
        return road_exclusion_geometry
    if road_exclusion_geometry.is_empty:
        return node_exclusion_geometry
    return unary_union([node_exclusion_geometry, road_exclusion_geometry])


def _build_foreign_local_junction_node_core_exclusion_geometry(
    *,
    polygon_geometry: BaseGeometry,
    analysis_center: Point,
    normalized_mainnodeid: str,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
    local_road_degree_by_node_id: Counter[str],
    keep_geometry: BaseGeometry | None = None,
    semantic_mainnodeids: set[str] | None = None,
) -> BaseGeometry:
    if polygon_geometry.is_empty:
        return GeometryCollection()

    target_group_node_ids = {node.node_id for node in group_nodes}
    polygon_cover = polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
    node_exclusion_geometries: list[BaseGeometry] = []
    road_exclusion_geometries: list[BaseGeometry] = []
    for node in local_nodes:
        if not _is_polygon_cover_foreign_local_junction_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            analysis_center=analysis_center,
            semantic_mainnodeids=semantic_mainnodeids,
        ):
            continue
        if float(node.geometry.distance(analysis_center)) <= 8.0:
            continue
        if not polygon_cover.covers(node.geometry):
            continue
        node_exclusion_radius_m = max(POLYGON_GROUP_NODE_BUFFER_M * 2.0, 6.5)
        if (
            keep_geometry is not None
            and not keep_geometry.is_empty
            and keep_geometry.intersects(node.geometry.buffer(4.0))
        ):
            node_exclusion_radius_m = max(POLYGON_GROUP_NODE_BUFFER_M * 1.5, 2.2)
        node_core_exclusion_geometry = node.geometry.buffer(
            node_exclusion_radius_m
        ).intersection(drivezone_union)
        if not node_core_exclusion_geometry.is_empty:
            node_exclusion_geometries.append(node_core_exclusion_geometry)
        incident_clip = node.geometry.buffer(14.0).intersection(drivezone_union)
        if incident_clip.is_empty:
            continue
        for road in local_roads:
            if road.snodeid != node.node_id and road.enodeid != node.node_id:
                continue
            local_geometry = road.geometry.intersection(incident_clip)
            if local_geometry.is_empty or local_geometry.length <= 0.5:
                continue
            road_exclusion_geometry = local_geometry.buffer(
                max(ROAD_BUFFER_M * 1.0, SIDE_BRANCH_HALF_WIDTH_M * 1.0),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if not road_exclusion_geometry.is_empty:
                road_exclusion_geometries.append(road_exclusion_geometry)

    if not node_exclusion_geometries and not road_exclusion_geometries:
        return GeometryCollection()
    node_exclusion_geometry = (
        unary_union(node_exclusion_geometries)
        if node_exclusion_geometries
        else GeometryCollection()
    )
    road_exclusion_geometry = (
        unary_union(road_exclusion_geometries)
        if road_exclusion_geometries
        else GeometryCollection()
    )
    if keep_geometry is not None and not keep_geometry.is_empty and not road_exclusion_geometry.is_empty:
        road_exclusion_geometry = road_exclusion_geometry.difference(keep_geometry)
    if node_exclusion_geometry.is_empty:
        return road_exclusion_geometry
    if road_exclusion_geometry.is_empty:
        return node_exclusion_geometry
    return unary_union([node_exclusion_geometry, road_exclusion_geometry])


def _build_targeted_foreign_local_junction_trim_geometry(
    *,
    node_ids: set[str],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
) -> BaseGeometry:
    if not node_ids:
        return GeometryCollection()

    local_node_by_id = {node.node_id: node for node in local_nodes}
    exclusion_geometries: list[BaseGeometry] = []
    for node_id in node_ids:
        node = local_node_by_id.get(node_id)
        if node is None:
            continue
        node_exclusion_geometry = node.geometry.buffer(
            max(POLYGON_GROUP_NODE_BUFFER_M * 2.0, 6.5)
        ).intersection(drivezone_union)
        if not node_exclusion_geometry.is_empty:
            exclusion_geometries.append(node_exclusion_geometry)
        incident_clip = node.geometry.buffer(16.0).intersection(drivezone_union)
        if incident_clip.is_empty:
            continue
        for road in local_roads:
            if road.snodeid != node_id and road.enodeid != node_id:
                continue
            local_geometry = road.geometry.intersection(incident_clip)
            if local_geometry.is_empty or local_geometry.length <= 0.5:
                continue
            road_exclusion_geometry = local_geometry.buffer(
                max(ROAD_BUFFER_M * 1.05, SIDE_BRANCH_HALF_WIDTH_M * 1.05),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if not road_exclusion_geometry.is_empty:
                exclusion_geometries.append(road_exclusion_geometry)
    if not exclusion_geometries:
        return GeometryCollection()
    return unary_union(exclusion_geometries)


def _build_targeted_foreign_semantic_node_core_trim_geometry(
    *,
    node_ids: set[str],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
    keep_geometry: BaseGeometry | None = None,
) -> BaseGeometry:
    if not node_ids:
        return GeometryCollection()

    local_node_by_id = {node.node_id: node for node in local_nodes}
    exclusion_geometries: list[BaseGeometry] = []
    for node_id in node_ids:
        node = local_node_by_id.get(node_id)
        if node is None:
            continue
        node_core_geometry = node.geometry.buffer(
            max(POLYGON_GROUP_NODE_BUFFER_M * 1.5, 2.2)
        ).intersection(drivezone_union)
        if keep_geometry is not None and not keep_geometry.is_empty and not node_core_geometry.is_empty:
            node_core_geometry = node_core_geometry.difference(keep_geometry)
        if not node_core_geometry.is_empty:
            exclusion_geometries.append(node_core_geometry)
        incident_clip = node.geometry.buffer(6.0).intersection(drivezone_union)
        if incident_clip.is_empty:
            continue
        for road in local_roads:
            if road.snodeid != node_id and road.enodeid != node_id:
                continue
            local_geometry = road.geometry.intersection(incident_clip)
            if local_geometry.is_empty or local_geometry.length <= 0.5:
                continue
            local_trim_geometry = local_geometry.buffer(
                max(ROAD_BUFFER_M * 0.8, SIDE_BRANCH_HALF_WIDTH_M * 0.65),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if keep_geometry is not None and not keep_geometry.is_empty and not local_trim_geometry.is_empty:
                local_trim_geometry = local_trim_geometry.difference(keep_geometry)
            if not local_trim_geometry.is_empty:
                exclusion_geometries.append(local_trim_geometry)
    if not exclusion_geometries:
        return GeometryCollection()
    return unary_union(exclusion_geometries)


def _road_touches_foreign_local_semantic_junction(
    *,
    road: ParsedRoad,
    local_node_by_id: dict[str, ParsedNode],
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    analysis_center: Point,
    semantic_mainnodeids: set[str] | None = None,
) -> bool:
    for node_id in (road.snodeid, road.enodeid):
        node = local_node_by_id.get(node_id)
        if node is None:
            continue
        if _is_foreign_local_semantic_node(
            node=node,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            semantic_mainnodeids=semantic_mainnodeids,
        ):
            return True
    return False


def _covered_foreign_local_road_ids(
    *,
    polygon_geometry: BaseGeometry,
    local_roads: list[ParsedRoad],
    local_nodes: list[ParsedNode],
    allowed_road_ids: set[str],
    target_group_node_ids: set[str],
    normalized_mainnodeid: str,
    local_road_degree_by_node_id: Counter[str],
    analysis_center: Point,
    semantic_mainnodeids: set[str] | None = None,
) -> list[str]:
    if polygon_geometry.is_empty:
        return []
    local_node_by_id = {node.node_id: node for node in local_nodes}
    foreign_node_cover_radius_m = max(DEFAULT_RESOLUTION_M, 0.5)
    covered_road_ids: list[str] = []
    for road in local_roads:
        if road.road_id in allowed_road_ids:
            continue
        endpoint_nodes = [
            local_node_by_id.get(road.snodeid),
            local_node_by_id.get(road.enodeid),
        ]
        touches_target_group = (
            road.snodeid in target_group_node_ids
            or road.enodeid in target_group_node_ids
        )
        touches_non_target_group = any(
            node is not None
            and node.mainnodeid not in {None, normalized_mainnodeid}
            and local_road_degree_by_node_id.get(node.node_id, 0) != 2
            for node in endpoint_nodes
        )
        foreign_endpoint_nodes = [
            node
            for node in endpoint_nodes
            if node is not None
            and _is_foreign_local_semantic_node(
                node=node,
                target_group_node_ids=target_group_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
        ]
        target_group_endpoint_nodes = [
            node
            for node in endpoint_nodes
            if node is not None and node.node_id in target_group_node_ids
        ]
        covered_geometry = road.geometry.intersection(
            polygon_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.5), join_style=1)
        )
        if covered_geometry.is_empty or covered_geometry.length <= 0.5:
            covered_geometry = road.geometry.intersection(polygon_geometry)
        covered_length_m = float(covered_geometry.length)
        touches_foreign_semantic_junction = _road_touches_foreign_local_semantic_junction(
            road=road,
            local_node_by_id=local_node_by_id,
            target_group_node_ids=target_group_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            analysis_center=analysis_center,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        if not touches_foreign_semantic_junction:
            if not touches_target_group and touches_non_target_group and covered_length_m > POLYGON_FOREIGN_ROAD_OVERLAP_MIN_M:
                covered_road_ids.append(road.road_id)
            continue
        if touches_target_group and foreign_endpoint_nodes and target_group_endpoint_nodes:
            target_group_keep_parts = [
                road.geometry.intersection(
                    node.geometry.buffer(
                        POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M + max(DEFAULT_RESOLUTION_M, 0.5)
                    )
                )
                for node in target_group_endpoint_nodes
            ]
            target_group_keep_parts = [
                geometry
                for geometry in target_group_keep_parts
                if geometry is not None and not geometry.is_empty
            ]
            if target_group_keep_parts:
                target_group_keep_geometry = unary_union(target_group_keep_parts)
                covered_overreach_geometry = covered_geometry.difference(
                    target_group_keep_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.2), join_style=1)
                )
                if covered_overreach_geometry.length > POLYGON_FOREIGN_TARGET_ARM_OVERREACH_TOLERANCE_M:
                    covered_road_ids.append(road.road_id)
                    continue
        elif covered_length_m > POLYGON_FOREIGN_ROAD_OVERLAP_MIN_M:
            covered_road_ids.append(road.road_id)
            continue
        covered_foreign_endpoint = any(
            _polygon_substantively_covers_node(
                polygon_geometry,
                node.geometry,
                cover_radius_m=foreign_node_cover_radius_m,
            )
            for node in foreign_endpoint_nodes
        )
        covered_foreign_endpoint_approach_length_m = max(
            (
                float(
                    polygon_geometry.intersection(
                        road.geometry.intersection(
                            node.geometry.buffer(POLYGON_FOREIGN_ROAD_ENDPOINT_CLIP_M)
                        )
                    ).length
                )
                for node in foreign_endpoint_nodes
            ),
            default=0.0,
        )
        minimum_endpoint_intrusion_m = (
            POLYGON_FOREIGN_INCIDENT_ROAD_ENDPOINT_INTRUSION_MIN_M
            if touches_target_group
            else POLYGON_FOREIGN_ROAD_ENDPOINT_INTRUSION_MIN_M
        )
        covered_foreign_endpoint_approach = (
            covered_foreign_endpoint_approach_length_m
            >= minimum_endpoint_intrusion_m
        )
        if covered_length_m <= max(DEFAULT_RESOLUTION_M, 0.5) and not covered_foreign_endpoint:
            continue
        if not covered_foreign_endpoint and not covered_foreign_endpoint_approach:
            continue
        covered_road_ids.append(road.road_id)
    return sorted(set(covered_road_ids))


def _build_targeted_foreign_local_road_trim_geometry(
    *,
    polygon_geometry: BaseGeometry,
    road_ids: set[str],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
    keep_geometry: BaseGeometry | None = None,
    local_nodes: list[ParsedNode] | None = None,
    target_group_node_ids: set[str] | None = None,
    normalized_mainnodeid: str | None = None,
    local_road_degree_by_node_id: Counter[str] | None = None,
    semantic_mainnodeids: set[str] | None = None,
    respect_keep_geometry_for_target_group_foreign_roads: bool = False,
    target_group_keep_length_m_override: float | None = None,
) -> BaseGeometry:
    if not road_ids or polygon_geometry.is_empty:
        return GeometryCollection()

    local_node_by_id = (
        {node.node_id: node for node in local_nodes}
        if local_nodes is not None
        else {}
    )
    exclusion_geometries: list[BaseGeometry] = []
    for road in local_roads:
        if road.road_id not in road_ids:
            continue
        covered_geometry = GeometryCollection()
        allow_keep_geometry = True
        road_keep_parts: list[BaseGeometry] = []
        if (
            target_group_node_ids is not None
            and normalized_mainnodeid is not None
            and local_road_degree_by_node_id is not None
            and local_node_by_id
        ):
            touches_target_group = (
                road.snodeid in target_group_node_ids
                or road.enodeid in target_group_node_ids
            )
            target_group_endpoint_nodes = [
                node
                for node_id in (road.snodeid, road.enodeid)
                for node in [local_node_by_id.get(node_id)]
                if node is not None and node.node_id in target_group_node_ids
            ]
            foreign_endpoint_nodes = [
                node
                for node_id in (road.snodeid, road.enodeid)
                for node in [local_node_by_id.get(node_id)]
                if node is not None
                and _is_foreign_local_semantic_node(
                    node=node,
                    target_group_node_ids=target_group_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            ]
            if touches_target_group and foreign_endpoint_nodes and target_group_endpoint_nodes:
                allow_keep_geometry = respect_keep_geometry_for_target_group_foreign_roads
                target_group_keep_length_m = (
                    target_group_keep_length_m_override
                    if target_group_keep_length_m_override is not None
                    else POLYGON_FOREIGN_TARGET_ARM_KEEP_LENGTH_M
                )
                target_group_keep_parts = [
                    road.geometry.intersection(
                        node.geometry.buffer(
                            target_group_keep_length_m + max(DEFAULT_RESOLUTION_M, 0.5)
                        )
                    )
                    for node in target_group_endpoint_nodes
                ]
                target_group_keep_parts = [
                    geometry
                    for geometry in target_group_keep_parts
                    if geometry is not None and not geometry.is_empty
                ]
                if target_group_keep_parts:
                    target_group_keep_geometry = unary_union(target_group_keep_parts)
                    road_keep_parts.append(target_group_keep_geometry)
                    if allow_keep_geometry and keep_geometry is not None and not keep_geometry.is_empty:
                        keep_on_road = road.geometry.intersection(
                            keep_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.3), join_style=1)
                        )
                        if keep_on_road is not None and not keep_on_road.is_empty:
                            road_keep_parts.append(keep_on_road)
                    road_keep_geometry = unary_union(
                        [
                            geometry
                            for geometry in road_keep_parts
                            if geometry is not None and not geometry.is_empty
                        ]
                    )
                    covered_geometry = road.geometry.difference(
                        road_keep_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.2), join_style=1)
                    ).intersection(
                        polygon_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.5), join_style=1)
                    )
                    if covered_geometry.is_empty or covered_geometry.length <= 0.5:
                        covered_geometry = road.geometry.difference(
                            road_keep_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.2), join_style=1)
                        ).intersection(polygon_geometry)
            elif not touches_target_group and foreign_endpoint_nodes:
                covered_geometry = road.geometry.intersection(
                    polygon_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.5), join_style=1)
                )
                if covered_geometry.is_empty or covered_geometry.length <= 0.5:
                    covered_geometry = road.geometry.intersection(polygon_geometry)
            endpoint_trim_parts: list[BaseGeometry] = []
            endpoint_clip_radius_m = (
                POLYGON_FOREIGN_ROAD_ENDPOINT_CLIP_M
                if touches_target_group
                else POLYGON_FOREIGN_ROAD_ENDPOINT_CLIP_M + 4.0
            )
            for node in foreign_endpoint_nodes:
                endpoint_clip = node.geometry.buffer(
                    endpoint_clip_radius_m
                ).intersection(drivezone_union)
                if endpoint_clip.is_empty:
                    continue
                endpoint_geometry = road.geometry.intersection(endpoint_clip)
                if endpoint_geometry.is_empty or endpoint_geometry.length <= 0.5:
                    continue
                endpoint_covered_geometry = endpoint_geometry.intersection(
                    polygon_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.5), join_style=1)
                )
                if endpoint_covered_geometry.is_empty or endpoint_covered_geometry.length <= 0.5:
                    endpoint_covered_geometry = endpoint_geometry.intersection(polygon_geometry)
                if not endpoint_covered_geometry.is_empty and endpoint_covered_geometry.length > 0.5:
                    endpoint_trim_parts.append(endpoint_covered_geometry)
            if covered_geometry.is_empty and endpoint_trim_parts:
                covered_geometry = unary_union(endpoint_trim_parts)
        if covered_geometry.is_empty or covered_geometry.length <= 0.5:
            covered_geometry = road.geometry.intersection(
                polygon_geometry.buffer(max(DEFAULT_RESOLUTION_M, 0.5), join_style=1)
            )
        if covered_geometry.is_empty or covered_geometry.length <= 0.5:
            covered_geometry = road.geometry.intersection(polygon_geometry)
        if covered_geometry.is_empty or covered_geometry.length <= 0.5:
            continue
        road_exclusion_buffer_m = max(ROAD_BUFFER_M * 1.1, SIDE_BRANCH_HALF_WIDTH_M * 1.05)
        if (
            target_group_node_ids is not None
            and (road.snodeid in target_group_node_ids or road.enodeid in target_group_node_ids)
        ):
            foreign_endpoint_node_count = sum(
                1
                for node_id in (road.snodeid, road.enodeid)
                for node in [local_node_by_id.get(node_id)]
                if node is not None
                and _is_foreign_local_semantic_node(
                    node=node,
                    target_group_node_ids=target_group_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid or "",
                    local_road_degree_by_node_id=local_road_degree_by_node_id or Counter(),
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            if foreign_endpoint_node_count >= 1:
                road_exclusion_buffer_m = max(
                    road_exclusion_buffer_m,
                    max(ROAD_BUFFER_M * 1.45, SIDE_BRANCH_HALF_WIDTH_M * 1.3),
                )
        if (
            target_group_node_ids is not None
            and normalized_mainnodeid is not None
            and local_road_degree_by_node_id is not None
            and local_node_by_id
            and road.snodeid not in (target_group_node_ids or set())
            and road.enodeid not in (target_group_node_ids or set())
        ):
            foreign_endpoint_node_count = sum(
                1
                for node_id in (road.snodeid, road.enodeid)
                for node in [local_node_by_id.get(node_id)]
                if node is not None
                and _is_foreign_local_semantic_node(
                    node=node,
                    target_group_node_ids=target_group_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            if foreign_endpoint_node_count >= 1:
                road_exclusion_buffer_m = max(
                    road_exclusion_buffer_m,
                    max(ROAD_BUFFER_M * 1.45, SIDE_BRANCH_HALF_WIDTH_M * 1.3),
                )
                if road.snodeid not in (target_group_node_ids or set()) and road.enodeid not in (target_group_node_ids or set()):
                    road_exclusion_buffer_m = max(
                        road_exclusion_buffer_m,
                        max(ROAD_BUFFER_M * 2.2, SIDE_BRANCH_HALF_WIDTH_M * 1.8),
                    )
        road_exclusion_geometry = covered_geometry.buffer(
            road_exclusion_buffer_m,
            cap_style=2,
            join_style=2,
        ).intersection(drivezone_union)
        if (
            allow_keep_geometry
            and keep_geometry is not None
            and not keep_geometry.is_empty
            and not road_exclusion_geometry.is_empty
        ):
            road_exclusion_geometry = road_exclusion_geometry.difference(keep_geometry)
        if not road_exclusion_geometry.is_empty:
            exclusion_geometries.append(road_exclusion_geometry)
    if not exclusion_geometries:
        return GeometryCollection()
    return unary_union(exclusion_geometries)


def _nearest_true_grid_cell(
    *,
    mask: np.ndarray,
    grid: GridSpec,
    point: Point,
) -> tuple[int, int] | None:
    true_cells = np.argwhere(mask)
    if true_cells.size == 0:
        return None
    rows = true_cells[:, 0]
    cols = true_cells[:, 1]
    distances = (grid.x_centers[cols] - float(point.x)) ** 2 + (
        grid.y_centers[rows] - float(point.y)
    ) ** 2
    best_index = int(np.argmin(distances))
    return int(rows[best_index]), int(cols[best_index])


def _find_grid_path_to_goal(
    *,
    traversable_mask: np.ndarray,
    start_rc: tuple[int, int],
    goal_mask: np.ndarray,
) -> list[tuple[int, int]]:
    if not traversable_mask[start_rc] or not np.any(goal_mask & traversable_mask):
        return []

    queue: deque[tuple[int, int]] = deque([start_rc])
    visited = np.zeros_like(traversable_mask, dtype=bool)
    visited[start_rc] = True
    parent_by_rc: dict[tuple[int, int], tuple[int, int] | None] = {start_rc: None}

    while queue:
        row, col = queue.popleft()
        if goal_mask[row, col]:
            path: list[tuple[int, int]] = []
            current: tuple[int, int] | None = (row, col)
            while current is not None:
                path.append(current)
                current = parent_by_rc[current]
            path.reverse()
            return path
        for row_delta, col_delta in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            next_row = row + row_delta
            next_col = col + col_delta
            if (
                next_row < 0
                or next_row >= traversable_mask.shape[0]
                or next_col < 0
                or next_col >= traversable_mask.shape[1]
            ):
                continue
            if visited[next_row, next_col] or not traversable_mask[next_row, next_col]:
                continue
            visited[next_row, next_col] = True
            parent_by_rc[(next_row, next_col)] = (row, col)
            queue.append((next_row, next_col))
    return []


def _build_obstacle_avoiding_connector_geometry(
    *,
    start_point: Point,
    target_geometry: BaseGeometry,
    drivezone_union: BaseGeometry,
    obstacle_geometries: list[BaseGeometry],
    connector_half_width_m: float,
) -> BaseGeometry:
    if target_geometry.is_empty or drivezone_union.is_empty:
        return GeometryCollection()

    obstacle_geometries = [
        geometry for geometry in obstacle_geometries if geometry is not None and not geometry.is_empty
    ]
    if not obstacle_geometries:
        return GeometryCollection()

    nearest_target_point = nearest_points(start_point, target_geometry)[1]
    bbox_padding_m = max(
        8.0,
        float(start_point.distance(nearest_target_point)) * 0.5 + 6.0,
    )
    min_x = min(float(start_point.x), float(nearest_target_point.x)) - bbox_padding_m
    max_x = max(float(start_point.x), float(nearest_target_point.x)) + bbox_padding_m
    min_y = min(float(start_point.y), float(nearest_target_point.y)) - bbox_padding_m
    max_y = max(float(start_point.y), float(nearest_target_point.y)) + bbox_padding_m
    patch_size_m = max(max_x - min_x, max_y - min_y, 10.0) + max(DEFAULT_RESOLUTION_M, 0.5)
    grid = _build_grid(
        Point((min_x + max_x) * 0.5, (min_y + max_y) * 0.5),
        patch_size_m=patch_size_m,
        resolution_m=max(DEFAULT_RESOLUTION_M * 2.0, 0.4),
    )

    free_space = drivezone_union.intersection(grid.patch_polygon)
    if free_space.is_empty:
        return GeometryCollection()

    obstacle_union = unary_union(obstacle_geometries).intersection(grid.patch_polygon)
    if not obstacle_union.is_empty:
        obstacle_buffer = obstacle_union.buffer(
            max(connector_half_width_m + 0.2, 0.75),
            join_style=1,
        )
        free_space = free_space.difference(obstacle_buffer)
    if free_space.is_empty:
        return GeometryCollection()

    traversable_mask = _rasterize_geometries(grid, [free_space])
    if not np.any(traversable_mask):
        return GeometryCollection()

    start_rc = _nearest_true_grid_cell(mask=traversable_mask, grid=grid, point=start_point)
    if start_rc is None:
        return GeometryCollection()

    goal_geometry = target_geometry.buffer(
        max(connector_half_width_m + 0.15, 0.7),
        join_style=1,
    ).intersection(free_space)
    if goal_geometry.is_empty:
        goal_geometry = target_geometry.intersection(free_space)
    if goal_geometry.is_empty:
        goal_geometry = nearest_target_point.buffer(
            max(connector_half_width_m + 0.3, 0.8)
        ).intersection(free_space)
    if goal_geometry.is_empty:
        return GeometryCollection()

    goal_mask = _rasterize_geometries(grid, [goal_geometry]) & traversable_mask
    if not np.any(goal_mask):
        return GeometryCollection()

    path = _find_grid_path_to_goal(
        traversable_mask=traversable_mask,
        start_rc=start_rc,
        goal_mask=goal_mask,
    )
    if len(path) < 2:
        return GeometryCollection()

    path_coordinates = [
        (float(grid.x_centers[col]), float(grid.y_centers[row]))
        for row, col in path
    ]
    connector_line = LineString(path_coordinates)
    if connector_line.is_empty or connector_line.length <= 0.1:
        return GeometryCollection()
    connector_geometry = connector_line.buffer(
        max(connector_half_width_m, 0.3),
        cap_style=2,
        join_style=2,
    ).intersection(free_space)
    return connector_geometry if not connector_geometry.is_empty else GeometryCollection()


def _build_uncovered_group_node_repair_geometries(
    *,
    uncovered_group_node_ids: list[str],
    current_polygon_geometry: BaseGeometry,
    analysis_center: Point,
    normalized_mainnodeid: str,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union: BaseGeometry,
    local_road_degree_by_node_id: Counter[str],
) -> list[BaseGeometry]:
    if current_polygon_geometry.is_empty or not uncovered_group_node_ids:
        return []

    target_group_node_ids = {node.node_id for node in group_nodes}
    group_node_by_id = {node.node_id: node for node in group_nodes}
    current_polygon_cover = current_polygon_geometry.buffer(
        POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.2
    )
    repair_geometries: list[BaseGeometry] = []

    for group_node_id in uncovered_group_node_ids:
        group_node = group_node_by_id.get(group_node_id)
        if group_node is None:
            continue

        group_support_parts: list[BaseGeometry] = [
            group_node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M * 0.85, 2.4)).intersection(
                drivezone_union
            )
        ]
        group_incident_clip = group_node.geometry.buffer(16.0).intersection(drivezone_union)
        if not group_incident_clip.is_empty:
            for local_road in local_roads:
                if local_road.snodeid != group_node_id and local_road.enodeid != group_node_id:
                    continue
                local_geometry = local_road.geometry.intersection(group_incident_clip)
                if local_geometry.is_empty or local_geometry.length <= 0.5:
                    continue
                group_support_parts.append(
                    local_geometry.buffer(
                        max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                )

        nearby_candidate_by_semantic_id: dict[str, tuple[tuple[bool, float, float], ParsedNode]] = {}
        for local_node in local_nodes:
            if local_node.node_id in target_group_node_ids:
                continue
            if local_road_degree_by_node_id.get(local_node.node_id, 0) < 2:
                continue
            if float(local_node.geometry.distance(group_node.geometry)) > 40.0:
                continue
            if not _is_supportable_local_node_for_rc_bridge(
                node=local_node,
                target_group_node_ids=target_group_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
            ):
                continue
            semantic_id = _normalize_id(local_node.mainnodeid) or local_node.node_id
            ranking = (
                local_node.node_id != semantic_id,
                float(local_node.geometry.distance(group_node.geometry)),
                float(local_node.geometry.distance(analysis_center)),
            )
            existing = nearby_candidate_by_semantic_id.get(semantic_id)
            if existing is None or ranking < existing[0]:
                nearby_candidate_by_semantic_id[semantic_id] = (ranking, local_node)

        nearby_local_nodes = [
            node
            for _, node in sorted(
                nearby_candidate_by_semantic_id.values(),
                key=lambda item: item[0],
            )[:2]
        ]

        for local_node in nearby_local_nodes:
            incident_local_roads = [
                local_road
                for local_road in local_roads
                if local_road.snodeid == local_node.node_id or local_road.enodeid == local_node.node_id
            ]
            if len(incident_local_roads) < 2:
                continue

            node_degree = local_road_degree_by_node_id.get(local_node.node_id, 0)
            local_road_clip = local_node.geometry.buffer(
                13.0 if node_degree >= 3 else 11.0
            ).intersection(drivezone_union)
            if local_road_clip.is_empty:
                continue

            local_support_parts: list[BaseGeometry] = [
                local_node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M * 0.85, 2.4)).intersection(
                    drivezone_union
                )
            ]
            connector_geometry = LineString(
                [
                    (float(group_node.geometry.x), float(group_node.geometry.y)),
                    (float(local_node.geometry.x), float(local_node.geometry.y)),
                ]
            ).buffer(
                max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.55, 1.2),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if not connector_geometry.is_empty:
                local_support_parts.append(connector_geometry)

            substantive_local_road_count = 0
            undercovered_local_road_count = 0
            desired_local_road_cover_m = 14.0 if node_degree >= 3 else 10.0
            for local_road in incident_local_roads:
                local_road_geometry = local_road.geometry.intersection(local_road_clip)
                if local_road_geometry.is_empty or local_road_geometry.length <= 0.5:
                    continue
                substantive_local_road_count += 1
                covered_length_m = float(local_road_geometry.intersection(current_polygon_cover).length)
                road_cover_target_m = min(
                    float(local_road_geometry.length),
                    desired_local_road_cover_m,
                )
                if covered_length_m + 0.5 >= road_cover_target_m:
                    continue
                undercovered_local_road_count += 1
                local_support_parts.append(
                    local_road_geometry.buffer(
                        max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                )

            if substantive_local_road_count < 2:
                continue
            if undercovered_local_road_count == 0 and current_polygon_cover.covers(local_node.geometry):
                continue

            group_support_parts.extend(
                geometry
                for geometry in local_support_parts
                if geometry is not None and not geometry.is_empty
            )

        group_support_parts = [
            geometry
            for geometry in group_support_parts
            if geometry is not None and not geometry.is_empty
        ]
        if not group_support_parts:
            continue
        group_repair_geometry = unary_union(group_support_parts).intersection(drivezone_union)
        if (
            not group_repair_geometry.is_empty
            and not current_polygon_geometry.is_empty
            and not group_repair_geometry.intersects(current_polygon_geometry)
        ):
            current_point, repair_point = nearest_points(
                current_polygon_geometry,
                group_repair_geometry,
            )
            repair_connector_geometry = LineString(
                [
                    (float(current_point.x), float(current_point.y)),
                    (float(repair_point.x), float(repair_point.y)),
                ]
            ).buffer(
                max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.55, 1.2),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            if not repair_connector_geometry.is_empty:
                group_repair_geometry = unary_union(
                    [group_repair_geometry, repair_connector_geometry]
                ).intersection(drivezone_union)
        if not group_repair_geometry.is_empty:
            repair_geometries.append(group_repair_geometry)

    return repair_geometries


def _build_uncovered_selected_rc_node_repair_geometries(
    *,
    uncovered_selected_node_ids: list[str],
    current_polygon_geometry: BaseGeometry,
    local_rc_nodes: list[ParsedNode],
    drivezone_union: BaseGeometry,
    selected_rc_roads: list[ParsedRoad] | None = None,
    obstacle_geometries: list[BaseGeometry] | None = None,
    node_buffer_m: float | None = None,
    connector_half_width_m: float | None = None,
) -> list[BaseGeometry]:
    if current_polygon_geometry.is_empty or not uncovered_selected_node_ids:
        return []

    rc_node_by_id = {node.node_id: node for node in local_rc_nodes}
    selected_rc_roads = selected_rc_roads or []
    node_buffer_m = node_buffer_m or max(POLYGON_RC_NODE_BUFFER_M + 0.6, 2.6)
    connector_half_width_m = connector_half_width_m or max(
        POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.7,
        1.6,
    )
    repair_geometries: list[BaseGeometry] = []
    for node_id in uncovered_selected_node_ids:
        node = rc_node_by_id.get(node_id)
        if node is None:
            continue
        repair_geometries.append(
            node.geometry.buffer(node_buffer_m).intersection(drivezone_union)
        )
        if obstacle_geometries:
            preferred_selected_road_geometries: list[BaseGeometry] = []
            preferred_selected_road_cover_m = max(8.0, node_buffer_m * 6.0)
            for road in selected_rc_roads:
                if road.snodeid != node_id and road.enodeid != node_id:
                    continue
                road_geometry = road.geometry
                if road_geometry is None or road_geometry.is_empty:
                    continue
                road_length_m = float(road_geometry.length)
                if road_length_m <= 0.2:
                    continue
                node_projection = float(road_geometry.project(node.geometry))
                if road.snodeid == node_id:
                    segment_start = node_projection
                    segment_end = min(road_length_m, node_projection + preferred_selected_road_cover_m)
                elif road.enodeid == node_id:
                    segment_start = max(0.0, node_projection - preferred_selected_road_cover_m)
                    segment_end = node_projection
                else:
                    half_cover_m = preferred_selected_road_cover_m * 0.5
                    segment_start = max(0.0, node_projection - half_cover_m)
                    segment_end = min(road_length_m, node_projection + half_cover_m)
                if segment_end - segment_start <= 0.2:
                    continue
                preferred_segment_geometry = substring(
                    road_geometry,
                    segment_start,
                    segment_end,
                )
                if preferred_segment_geometry is None or preferred_segment_geometry.is_empty:
                    continue
                preferred_selected_road_geometries.append(
                    preferred_segment_geometry.buffer(
                        max(connector_half_width_m * 1.2, 0.55),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                )
            repair_geometries.extend(
                geometry
                for geometry in preferred_selected_road_geometries
                if geometry is not None and not geometry.is_empty
            )
            obstacle_avoiding_connector_geometry = _build_obstacle_avoiding_connector_geometry(
                start_point=node.geometry,
                target_geometry=current_polygon_geometry,
                drivezone_union=drivezone_union,
                obstacle_geometries=obstacle_geometries,
                connector_half_width_m=max(connector_half_width_m, 0.3),
            )
            if obstacle_avoiding_connector_geometry is not None and not obstacle_avoiding_connector_geometry.is_empty:
                repair_geometries.append(obstacle_avoiding_connector_geometry)
                continue
        road_connector_geometries: list[BaseGeometry] = []
        for road in selected_rc_roads:
            if road.snodeid != node_id and road.enodeid != node_id:
                continue
            road_geometry = road.geometry
            if road_geometry is None or road_geometry.is_empty:
                continue
            nearest_road_point, _ = nearest_points(road_geometry, current_polygon_geometry)
            node_projection = float(road_geometry.project(node.geometry))
            polygon_projection = float(road_geometry.project(nearest_road_point))
            if abs(node_projection - polygon_projection) <= max(DEFAULT_RESOLUTION_M, 0.2):
                connector_geometry = road_geometry.intersection(
                    node.geometry.buffer(max(POLYGON_RC_NODE_BUFFER_M * 2.5, 6.0))
                )
            else:
                connector_geometry = substring(
                    road_geometry,
                    min(node_projection, polygon_projection),
                    max(node_projection, polygon_projection),
                )
            if connector_geometry is None or connector_geometry.is_empty:
                continue
            road_connector_geometries.append(
                connector_geometry.buffer(
                    max(connector_half_width_m, 0.3),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
            )
        if road_connector_geometries:
            repair_geometries.extend(
                geometry
                for geometry in road_connector_geometries
                if geometry is not None and not geometry.is_empty
            )
            continue
        nearest_polygon_point = nearest_points(node.geometry, current_polygon_geometry)[1]
        repair_geometries.append(
            LineString(
                [
                    (float(node.geometry.x), float(node.geometry.y)),
                    (float(nearest_polygon_point.x), float(nearest_polygon_point.y)),
                ]
            ).buffer(
                connector_half_width_m,
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
        )
    return [
        geometry
        for geometry in repair_geometries
        if geometry is not None and not geometry.is_empty
    ]


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


def _max_nonmain_edge_branch_support_metrics(
    *,
    road_branches: list[BranchEvidence],
) -> tuple[float, float]:
    max_road_support_m = 0.0
    max_rc_support_m = 0.0
    for branch in road_branches:
        if branch.is_main_direction or branch.selected_for_polygon:
            continue
        if branch.evidence_level != "edge_only":
            continue
        max_road_support_m = max(max_road_support_m, float(branch.road_support_m or 0.0))
        max_rc_support_m = max(max_rc_support_m, float(branch.rc_support_m or 0.0))
    return max_road_support_m, max_rc_support_m


def _effect_success_acceptance(
    *,
    status: str,
    review_mode: bool,
    max_selected_side_branch_covered_length_m: float,
    max_nonmain_branch_polygon_length_m: float,
    associated_rc_road_count: int,
    polygon_support_rc_node_count: int = 0,
    polygon_support_rc_road_count: int = 0,
    min_invalid_rc_distance_to_center_m: float | None,
    local_rc_road_count: int,
    local_rc_node_count: int,
    effective_local_rc_node_count: int | None = None,
    local_road_count: int,
    local_node_count: int,
    connected_rc_group_count: int,
    nonmain_branch_connected_rc_group_count: int,
    negative_rc_group_count: int,
    positive_rc_group_count: int = 0,
    road_branch_count: int | None = None,
    has_structural_side_branch: bool = True,
    max_nonmain_edge_branch_road_support_m: float = 0.0,
    max_nonmain_edge_branch_rc_support_m: float = 0.0,
    excluded_local_rc_road_count: int = 0,
    excluded_local_rc_node_count: int = 0,
    covered_extra_local_node_count: int = 0,
    covered_extra_local_road_count: int = 0,
    has_main_edge_only_branch: bool = False,
    representative_kind_2: int | None = None,
    effective_associated_rc_node_count: int = 0,
    associated_nonzero_mainnode_count: int = 0,
    final_selected_node_cover_repair_discarded_due_to_extra_roads: bool = False,
) -> tuple[bool, str, str]:
    if effective_local_rc_node_count is None:
        effective_local_rc_node_count = local_rc_node_count
    has_excluded_local_rc = (
        excluded_local_rc_road_count > 0
        or excluded_local_rc_node_count > 0
    )
    if review_mode:
        return False, "review_required", "review_mode"
    if covered_extra_local_node_count > 0 or covered_extra_local_road_count > 0:
        if status == STATUS_STABLE:
            return False, "review_required", "stable_with_foreign_swsd_intrusion"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_STABLE:
        if (
            representative_kind_2 == 2048
            and positive_rc_group_count >= 2
            and negative_rc_group_count >= 1
            and associated_nonzero_mainnode_count == 0
            and associated_rc_road_count >= 3
            and effective_associated_rc_node_count >= 3
        ):
            return False, "review_required", "stable_with_rc_group_semantic_gap"
        if (
            representative_kind_2 == 2048
            and associated_rc_road_count <= 1
            and polygon_support_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and (
                max_nonmain_branch_polygon_length_m >= 20.0
                or final_selected_node_cover_repair_discarded_due_to_extra_roads
            )
        ):
            return False, "review_required", "stable_with_incomplete_t_mouth_rc_context"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and local_rc_road_count >= 20
            and effective_local_rc_node_count >= 2
        ):
            return False, "review_required", "stable_with_sparse_rc_association_against_dense_local_rcsd_context"
        if has_main_edge_only_branch:
            return False, "review_required", "stable_with_weak_main_direction"
        return True, "accepted", "stable"
    if status == STATUS_SURFACE_ONLY:
        if (
            not has_excluded_local_rc
            and local_rc_road_count == 0
            and effective_local_rc_node_count == 0
        ):
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
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and connected_rc_group_count == 1
            and nonmain_branch_connected_rc_group_count == 0
            and local_rc_road_count <= 4
            and local_rc_node_count <= 2
            and local_road_count <= 4
            and local_node_count <= 1
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return True, "accepted", "rc_gap_with_compact_local_mouth_geometry"
        if (
            connected_rc_group_count == 0
            and associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and effective_local_rc_node_count == 0
        ):
            return True, "accepted", "rc_gap_without_connected_local_rcsd_evidence"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and nonmain_branch_connected_rc_group_count == 0
            and effective_local_rc_node_count == 0
        ):
            return True, "accepted", "rc_gap_without_connected_local_rcsd_evidence"
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 0
            and not has_structural_side_branch
            and effective_local_rc_node_count <= 1
            and local_road_count <= 10
            and local_node_count <= 4
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return True, "accepted", "rc_gap_with_compact_mainline_geometry"
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 0
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and local_road_count <= 20
            and local_node_count <= 12
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m <= 8.0
            and max_nonmain_edge_branch_road_support_m <= 6.5
            and max_nonmain_edge_branch_rc_support_m <= 5.0
        ):
            return True, "accepted", "rc_gap_with_only_weak_unselected_edge_rc_groups"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 2
            and not has_structural_side_branch
            and local_road_count <= 13
            and local_node_count <= 6
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return True, "accepted", "rc_gap_without_structural_side_branch"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and effective_local_rc_node_count <= 1
            and local_road_count <= 10
            and local_node_count <= 4
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
            and max_nonmain_edge_branch_road_support_m <= 40.0
            and max_nonmain_edge_branch_rc_support_m <= 85.0
        ):
            return True, "accepted", "rc_gap_with_compact_edge_rc_tail"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and effective_local_rc_node_count <= 1
            and local_road_count <= 12
            and local_node_count <= 5
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
            and max_nonmain_edge_branch_road_support_m <= 20.0
            and max_nonmain_edge_branch_rc_support_m <= 60.0
        ):
            return True, "accepted", "rc_gap_with_single_weak_edge_side_branch"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
            and max_nonmain_edge_branch_road_support_m >= 50.0
            and max_nonmain_edge_branch_road_support_m <= 90.0
            and max_nonmain_edge_branch_rc_support_m <= 5.0
        ):
            return True, "accepted", "rc_gap_with_long_weak_unselected_edge_branch"
        if max_nonmain_branch_polygon_length_m >= 4.0:
            return True, "accepted", "rc_gap_with_nonmain_branch_polygon_coverage"
        return False, "review_required", "rc_gap_without_substantive_nonmain_branch_coverage"
    if status == STATUS_NODE_COMPONENT_CONFLICT:
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_WEAK_BRANCH_SUPPORT:
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 1
            and polygon_support_rc_road_count >= 1
            and effective_local_rc_node_count <= 0
            and local_road_count <= 3
            and local_node_count <= 1
            and max_selected_side_branch_covered_length_m >= 12.0
            and max_nonmain_branch_polygon_length_m >= 10.0
        ):
            return True, "accepted", "weak_branch_supported_compact_t_shape"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and effective_associated_rc_node_count >= 2
            and road_branch_count is not None
            and road_branch_count <= 3
            and max_selected_side_branch_covered_length_m >= 15.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return True, "accepted", "weak_branch_supported_rc_handoff_core"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and effective_local_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and associated_nonzero_mainnode_count == 0
            and local_road_count <= 5
            and local_node_count <= 2
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return True, "accepted", "weak_branch_supported_compact_outside_rc_core"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and effective_local_rc_node_count >= 2
            and effective_associated_rc_node_count >= 2
            and associated_nonzero_mainnode_count >= 2
            and local_road_count <= 16
            and local_node_count <= 12
            and max_selected_side_branch_covered_length_m <= 4.0
            and max_nonmain_branch_polygon_length_m >= 8.0
            and max_nonmain_branch_polygon_length_m <= 10.0
        ):
            return True, "accepted", "weak_branch_supported_compact_near_center_outside_rc"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_AMBIGUOUS_RC_MATCH:
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and nonmain_branch_connected_rc_group_count == 0
            and max_selected_side_branch_covered_length_m >= 7.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_nonmain_branch_polygon_coverage"
        if (
            associated_rc_road_count <= 2
            and polygon_support_rc_road_count <= 1
            and connected_rc_group_count >= 2
            and nonmain_branch_connected_rc_group_count <= 1
            and negative_rc_group_count >= 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and max_selected_side_branch_covered_length_m >= 7.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_compact_polygon"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count <= 2
            and polygon_support_rc_road_count <= 2
            and positive_rc_group_count >= 1
            and negative_rc_group_count >= 1
            and effective_associated_rc_node_count == 0
            and representative_kind_2 in {4, 2048}
            and road_branch_count is not None
            and road_branch_count <= 3
            and local_road_count <= 24
            and local_node_count <= 12
            and max_selected_side_branch_covered_length_m >= 7.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_compact_polygon"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count <= 1
            and connected_rc_group_count >= 2
            and nonmain_branch_connected_rc_group_count <= 1
            and negative_rc_group_count >= 1
            and max_nonmain_branch_polygon_length_m >= 8.0
            and max_selected_side_branch_covered_length_m <= 2.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_compact_polygon"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count <= 1
            and positive_rc_group_count == 1
            and negative_rc_group_count >= 1
            and not has_structural_side_branch
            and local_road_count <= 7
            and local_node_count <= 3
            and max_nonmain_branch_polygon_length_m >= 4.0
            and max_selected_side_branch_covered_length_m <= 1.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_compact_supported_polygon"
        if (
            associated_rc_road_count == 2
            and polygon_support_rc_road_count >= associated_rc_road_count
            and positive_rc_group_count <= 2
            and negative_rc_group_count >= 1
            and local_road_count <= 6
            and local_node_count <= 4
            and max_selected_side_branch_covered_length_m >= 18.0
            and max_nonmain_branch_polygon_length_m >= 10.0
        ):
            return True, "accepted", "ambiguous_main_rc_gap_with_supported_branch_polygon_coverage"
        return False, "review_required", f"review_required_status:{status}"
    return False, "rejected", f"rejected_status:{status}"


def _business_match_class(
    *,
    status: str,
    acceptance_class: str,
    associated_rc_road_count: int,
    polygon_support_rc_road_count: int,
    local_rc_road_count: int,
    excluded_rc_road_count: int = 0,
) -> str:
    has_any_rc_context = (
        associated_rc_road_count > 0
        or polygon_support_rc_road_count > 0
        or local_rc_road_count > 0
    )
    if status == STATUS_SURFACE_ONLY and not has_any_rc_context:
        return BUSINESS_MATCH_SWSD_ONLY
    if status in {
        STATUS_AMBIGUOUS_RC_MATCH,
        STATUS_NO_VALID_RC_CONNECTION,
        STATUS_NODE_COMPONENT_CONFLICT,
        STATUS_WEAK_BRANCH_SUPPORT,
    }:
        return BUSINESS_MATCH_PARTIAL_RCSD if has_any_rc_context else BUSINESS_MATCH_SWSD_ONLY
    if excluded_rc_road_count > 0:
        return BUSINESS_MATCH_PARTIAL_RCSD if has_any_rc_context else BUSINESS_MATCH_SWSD_ONLY
    if acceptance_class == "accepted" and status == STATUS_STABLE and has_any_rc_context:
        return BUSINESS_MATCH_COMPLETE_RCSD
    if has_any_rc_context:
        return BUSINESS_MATCH_PARTIAL_RCSD
    return BUSINESS_MATCH_SWSD_ONLY


def _business_match_reason(
    *,
    status: str,
    business_match_class: str,
    acceptance_reason: str,
    excluded_rc_road_count: int = 0,
) -> str:
    if business_match_class == BUSINESS_MATCH_COMPLETE_RCSD:
        return "matched_complete_rcsd_junction"
    if business_match_class == BUSINESS_MATCH_SWSD_ONLY:
        return "no_usable_rcsd_context"
    if excluded_rc_road_count > 0:
        return "partial_rcsd_context_after_excluding_incompatible_rcsd"
    if status == STATUS_AMBIGUOUS_RC_MATCH:
        return "multiple_rcsd_candidates_require_internal_disambiguation"
    if status == STATUS_NO_VALID_RC_CONNECTION:
        return "rcsd_missing_required_branch_or_handoff"
    if status == STATUS_NODE_COMPONENT_CONFLICT:
        return "rcsd_component_conflicts_with_swsd_base"
    if status == STATUS_WEAK_BRANCH_SUPPORT:
        return "branch_support_insufficient_for_full_rcsd_match"
    return acceptance_reason


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
    write_run_progress: bool = True,
    write_perf_markers: bool = True,
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
        "excluded_rcsdroad_count": 0,
        "excluded_rcsdnode_count": 0,
        "review_excluded_rcsdroad_count": 0,
        "review_excluded_rcsdnode_count": 0,
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

    def emit_progress_snapshot(
        *,
        status: str,
        current_stage: str | None,
        message: str,
    ) -> None:
        if not write_run_progress:
            return
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status=status,
            current_stage=current_stage,
            message=message,
            counts=counts,
        )

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
        if write_perf_markers:
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
        emit_progress_snapshot(
            status="running",
            current_stage=current_stage,
            message=message,
        )

    emit_progress_snapshot(
        status="running",
        current_stage="start",
        message="T02 virtual intersection POC started.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="target_group_resolved",
            message="Resolved target representative node and local buffer.",
        )

        emit_progress_snapshot(
            status="running",
            current_stage="loading_local_inputs",
            message="Loading local POC inputs around the target junction.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="local_nodes_loaded",
            message="Loaded local nodes around the target junction.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="local_roads_loaded",
            message="Loaded local roads around the target junction.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="local_drivezone_loaded",
            message="Loaded local DriveZone coverage around the target junction.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="local_rcsdroad_loaded",
            message="Loaded local RCSDRoad coverage around the target junction.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="local_rcsdnode_loaded",
            message="Loaded local RCSDNode coverage around the target junction.",
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
        emit_progress_snapshot(
            status="running",
            current_stage="inputs_loaded",
            message="Loaded local POC inputs around the target junction.",
        )
        current_patch_id = _resolve_current_patch_id_from_roads(group_nodes=group_nodes, roads=parsed_roads)
        local_roads = _filter_parsed_roads_to_patch(parsed_roads, patch_id=current_patch_id)
        local_drivezone_features = [
            feature
            for feature in _filter_loaded_features_to_patch(drivezone_layer_data.features, patch_id=current_patch_id)
            if feature.geometry is not None
        ]
        local_rc_roads = parsed_rc_roads
        local_rc_nodes = parsed_rc_nodes
        local_road_degree_by_node_id = _road_degree_by_node_id(local_roads)
        semantic_mainnodeids = _collect_semantic_mainnodeids(
            local_nodes,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
        )
        local_rc_road_degree_by_node_id = _road_degree_by_node_id(local_rc_roads)
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
        counts["current_patch_id"] = current_patch_id
        counts["same_patch_filter_applied"] = current_patch_id is not None

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
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
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
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
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
            local_rc_road_degree_by_node_id = _road_degree_by_node_id(local_rc_roads)

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
        incident_roads, internal_road_ids, road_branches = _build_road_branches_for_member_nodes(
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
            main_pair, direct_foreign_semantic_branch_ids = (
                _select_main_pair_with_semantic_conflict_guard(
                    road_branches,
                    center=analysis_center,
                    local_roads=local_roads,
                    local_nodes=local_nodes,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            main_branch_ids = set(main_pair)
        except VirtualIntersectionPocError:
            compound_center_context = _resolve_compound_center_branch_context(
                normalized_mainnodeid=normalized_mainnodeid,
                representative_node=representative_node,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                drivezone_union=drivezone_union,
            )
            if compound_center_context is None:
                raise
            analysis_center, analysis_member_node_ids, analysis_auxiliary_nodes, road_branches = compound_center_context
            incident_roads, internal_road_ids, road_branches = _build_road_branches_for_member_nodes(
                local_roads,
                member_node_ids=analysis_member_node_ids,
                drivezone_union=drivezone_union,
            )
            main_pair, direct_foreign_semantic_branch_ids = (
                _select_main_pair_with_semantic_conflict_guard(
                    road_branches,
                    center=analysis_center,
                    local_roads=local_roads,
                    local_nodes=local_nodes,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            main_branch_ids = set(main_pair)
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
        emit_progress_snapshot(
            status="running",
            current_stage="local_patch_built",
            message="Built local feature patch around target junction.",
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
            branch.conflict_excluded = branch.branch_id in direct_foreign_semantic_branch_ids
            branch.is_main_direction = branch.branch_id in main_branch_ids
            branch.evidence_level = _classify_branch_evidence(branch)
            branch.selected_for_polygon = (not branch.conflict_excluded) and (
                branch.is_main_direction or branch.evidence_level != "edge_only"
            )
        if len(road_branches) <= 3:
            strong_main_branch_exists = any(
                branch.is_main_direction and branch.evidence_level in {"arm_full_rc", "arm_partial"}
                for branch in road_branches
            )
            if strong_main_branch_exists:
                for branch in road_branches:
                    if (
                        branch.conflict_excluded
                        or not branch.is_main_direction
                        or branch.evidence_level != "edge_only"
                    ):
                        continue
                    if not branch.rcsdroad_ids:
                        continue
                    if branch.road_support_m < 18.0:
                        continue
                    if branch.drivezone_support_m < 8.0 and branch.rc_support_m < 12.0:
                        continue
                    # 紧凑 T / 简单交叉口里，主臂即使局部 DriveZone 很短，
                    # 只要已有稳定对向主臂和明确 RC 贴靠，也不应继续按 edge-only 视作弱主方向。
                    branch.evidence_level = "arm_partial"
                    branch.selected_for_polygon = True
        if (
            (representative_node.kind_2 or 0) == 4
            and sum(
                1
                for branch in road_branches
                if branch.is_main_direction and branch.evidence_level == "arm_full_rc"
            ) >= 2
        ):
            for branch in road_branches:
                if (
                    branch.conflict_excluded
                    or branch.is_main_direction
                    or branch.evidence_level != "edge_only"
                ):
                    continue
                if branch.drivezone_support_m < 7.0 or branch.road_support_m < 7.0:
                    continue
                # kind=4 全通口允许把接近阈值的弱侧臂提升为 compact arm，
                # 否则容易把完整十字口误退化成双向主轴 + 漏臂。
                branch.evidence_level = "arm_partial"
                branch.selected_for_polygon = True

        record_stage("main_direction_identified")

        if any(
            branch.is_main_direction and branch.evidence_level == "edge_only"
            for branch in road_branches
        ):
            if STATUS_WEAK_BRANCH_SUPPORT not in risks:
                risks.append(STATUS_WEAK_BRANCH_SUPPORT)
        if any(
            branch.selected_for_polygon and branch.evidence_level == "edge_only"
            for branch in road_branches
            if not branch.is_main_direction
        ):
            risks.append(STATUS_WEAK_BRANCH_SUPPORT)
        if (
            (representative_node.kind_2 or 0) == 2048
            and len(local_nodes) > 3
            and any(
                not branch.is_main_direction
                and branch.selected_for_polygon
                and not branch.rcsdroad_ids
                and branch.evidence_level == "arm_partial"
                and branch.drivezone_support_m >= 40.0
                and branch.road_support_m >= 30.0
                and not _branch_has_local_road_mouth(branch)
                and not _branch_has_minimal_local_road_touch(branch)
                for branch in road_branches
            )
        ):
            if STATUS_WEAK_BRANCH_SUPPORT not in risks:
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
        rc_road_by_id = {road.road_id: road for road in local_rc_roads}
        rc_node_by_id = {node.node_id: node for node in local_rc_nodes}
        candidate_selected_positive_group_rc_road_ids = {
            road_id
            for group_id in positive_rc_groups
            for road_id in (rc_branch_by_id[group_id].road_ids if group_id in rc_branch_by_id else [])
        }
        conflict_excluded_rc_group_ids = {
            rc_group_id
            for branch in road_branches
            if branch.conflict_excluded
            for rc_group_id in branch.rcsdroad_ids
        }
        conflict_excluded_rc_road_ids = {
            road_id
            for rc_group_id in conflict_excluded_rc_group_ids
            for rc_branch in [rc_branch_by_id.get(rc_group_id)]
            if rc_branch is not None
            for road_id in rc_branch.road_ids
        }
        conflict_excluded_rc_node_ids = {
            node_id
            for road_id in conflict_excluded_rc_road_ids
            for road in [rc_road_by_id.get(road_id)]
            if road is not None
            for node_id in (road.snodeid, road.enodeid)
        }
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
        compact_endpoint_max_distance_m = POLYGON_COMPACT_RC_ENDPOINT_MAX_DISTANCE_M
        if not rc_group_nodes and len(group_nodes) <= 1:
            compact_endpoint_max_distance_m = min(compact_endpoint_max_distance_m, 24.0)
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
                        <= compact_endpoint_max_distance_m
                    ):
                        road_compact_endpoint_ids.append(node_id)
                if (
                    not rc_group_nodes
                    and line.length <= POLYGON_COMPACT_RC_MAX_LENGTH_M
                    and min(endpoint_distances) >= POLYGON_COMPACT_RC_ENDPOINT_MIN_DISTANCE_M
                    and max(endpoint_distances) <= compact_endpoint_max_distance_m
                    and len(road_compact_endpoint_ids) >= 2
                ):
                    compact_endpoint_node_ids.update(road_compact_endpoint_ids)
        candidate_selected_rc_node_ids.update(compact_endpoint_node_ids)
        polygon_support_rc_road_ids, polygon_support_rc_node_ids, orphan_positive_support = _build_polygon_support_from_association(
            positive_rc_road_ids=positive_rc_road_ids,
            base_support_node_ids=candidate_selected_rc_node_ids,
            excluded_rc_road_ids=polygon_excluded_rc_road_ids,
            analysis_center=analysis_center,
            local_rc_roads=local_rc_roads,
            local_rc_nodes=local_rc_nodes,
            group_nodes=group_nodes,
        )
        has_multi_rc_group_main_branch = any(
            branch.is_main_direction and len(branch.rcsdroad_ids) >= 2
            for branch in road_branches
        )
        selected_positive_support_rc_endpoint_node_ids = {
            node_id
            for road in local_rc_roads
            if road.road_id in (positive_rc_road_ids | polygon_support_rc_road_ids)
            for node_id in (road.snodeid, road.enodeid)
            if node_id in rc_node_by_id
        }
        positive_nonmain_bridge_road_ids = {
            road_id
            for branch in road_branches
            if (
                not branch.is_main_direction
                and branch.selected_for_polygon
                and any(group_id in positive_rc_groups for group_id in branch.rcsdroad_ids)
            )
            for road_id in branch.road_ids
        }
        enable_t_mouth_rc_bridge_support = (
            bool(selected_positive_support_rc_endpoint_node_ids)
            and any(
                float(local_node.geometry.distance(rc_node_by_id[node_id].geometry)) <= 10.0
                and local_road_degree_by_node_id.get(local_node.node_id, 0) >= 2
                and _is_supportable_local_node_for_rc_bridge(
                    node=local_node,
                    target_group_node_ids={node.node_id for node in group_nodes},
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                )
                for node_id in selected_positive_support_rc_endpoint_node_ids
                for local_node in local_nodes
            )
        )
        should_expand_polygon_support_rc_subgraph = (
            bool(polygon_support_rc_road_ids)
            and bool(polygon_support_rc_node_ids)
            and enable_t_mouth_rc_bridge_support
            and has_multi_rc_group_main_branch
            and not any(
                local_rc_road_degree_by_node_id.get(node_id, 0) >= 3
                for node_id in polygon_support_rc_node_ids
            )
        )
        if should_expand_polygon_support_rc_subgraph:
            expanded_polygon_support_rc_road_ids, expanded_polygon_support_rc_node_ids = (
                _build_polygon_support_rc_subgraph(
                    local_rc_roads=local_rc_roads,
                    local_rc_nodes=local_rc_nodes,
                    group_nodes=group_nodes,
                    analysis_center=analysis_center,
                    seed_road_ids=polygon_support_rc_road_ids,
                    base_support_node_ids=polygon_support_rc_node_ids,
                )
            )
            expanded_polygon_support_rc_road_ids -= polygon_excluded_rc_road_ids
            if expanded_polygon_support_rc_road_ids:
                positive_rc_road_ids |= expanded_polygon_support_rc_road_ids
                polygon_support_rc_road_ids |= expanded_polygon_support_rc_road_ids
                polygon_support_rc_node_ids |= expanded_polygon_support_rc_node_ids
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
        group_node_local_support_geometries = []
        for node in group_nodes:
            if node.geometry.distance(analysis_center) <= max(resolution_m, 0.2):
                continue
            local_road_clip = node.geometry.buffer(10.0).intersection(drivezone_union)
            if local_road_clip.is_empty:
                continue
            local_support_parts: list[BaseGeometry] = [
                node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M * 0.9, 2.6)).intersection(drivezone_union)
            ]
            for road in local_roads:
                if road.snodeid != node.node_id and road.enodeid != node.node_id:
                    continue
                local_road_geometry = road.geometry.intersection(local_road_clip)
                if local_road_geometry.is_empty or local_road_geometry.length <= 0.5:
                    continue
                local_support_parts.append(
                    local_road_geometry.buffer(
                        max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                )
            local_support_parts = [
                geometry
                for geometry in local_support_parts
                if geometry is not None and not geometry.is_empty
            ]
            if not local_support_parts:
                continue
            group_node_local_support_geometries.append(
                unary_union(local_support_parts).convex_hull.buffer(
                    max(0.6, SIDE_BRANCH_HALF_WIDTH_M * 0.25),
                    join_style=1,
                ).intersection(drivezone_union)
            )
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
        support_geometries.extend(
            geometry
            for geometry in group_node_local_support_geometries
            if geometry is not None and not geometry.is_empty
        )
        support_geometries.extend(geometry for geometry in group_node_connectors if not geometry.is_empty)
        local_node_by_id = {node.node_id: node for node in local_nodes}
        positive_nonmain_bridge_local_node_ids: set[str] = set()
        if enable_t_mouth_rc_bridge_support and positive_nonmain_bridge_road_ids:
            positive_nonmain_bridge_local_node_ids = {
                local_node.node_id
                for local_node in local_nodes
                if local_road_degree_by_node_id.get(local_node.node_id, 0) >= 2
                and any(
                    local_road.road_id in positive_nonmain_bridge_road_ids
                    and (
                        local_road.snodeid == local_node.node_id
                        or local_road.enodeid == local_node.node_id
                    )
                    for local_road in local_roads
                )
                and any(
                    float(local_node.geometry.distance(rc_node_by_id[node_id].geometry)) <= 10.0
                    for node_id in selected_positive_support_rc_endpoint_node_ids
                )
            }
        local_mouth_protected_road_ids: set[str] = set()
        remote_mouth_protected_road_ids = {
            road_id
            for branch in road_branches
            if branch.is_main_direction or bool(branch.rcsdroad_ids)
            for road_id in branch.road_ids
        }
        analyzed_branch_road_ids = {
            road_id
            for branch in road_branches
            for road_id in branch.road_ids
        }
        has_any_local_road_mouth_branch = any(
            _branch_has_local_road_mouth(branch)
            for branch in road_branches
        )
        branch_overreach_exclusion_geometries: list[BaseGeometry] = []
        branch_mandatory_support_geometries: list[BaseGeometry] = []
        branch_local_refinement_specs: list[tuple[BaseGeometry, BaseGeometry, bool]] = []
        branch_features: list[dict[str, Any]] = []
        group_node_ids = {node.node_id for node in group_nodes}
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
            branch_center_distance_m = min(
                (
                    float(road.geometry.distance(analysis_center))
                    for road in local_roads
                    if road.road_id in branch.road_ids
                ),
                default=0.0,
            )
            far_group_node_id = _edge_branch_far_group_node_id(
                branch,
                center=analysis_center,
                local_roads=local_roads,
                local_node_by_id=local_node_by_id,
                group_node_ids=group_node_ids,
            )
            far_junction_node_id = _edge_branch_far_local_junction_node_id(
                branch,
                center=analysis_center,
                local_roads=local_roads,
                local_node_by_id=local_node_by_id,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
            )
            far_junction_point = _edge_branch_far_local_junction_point(
                branch,
                center=analysis_center,
                local_roads=local_roads,
                local_node_by_id=local_node_by_id,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
            )
            far_junction_distance_m = _edge_branch_far_local_junction_distance_m(
                branch,
                center=analysis_center,
                local_roads=local_roads,
                local_node_by_id=local_node_by_id,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
            )
            far_group_node = (
                local_node_by_id.get(far_group_node_id)
                if far_group_node_id is not None
                else None
            )
            far_group_node_distance_m = (
                float(far_group_node.geometry.distance(analysis_center))
                if far_group_node is not None
                else 0.0
            )
            far_junction_is_group_node = far_junction_node_id in group_node_ids
            if (
                has_any_local_road_mouth_branch
                and not branch.is_main_direction
                and not branch.rcsdroad_ids
                and not branch_has_local_road_mouth
                and branch.evidence_level == "arm_full_rc"
            ):
                max_length = min(max_length, 3.0 if branch.rc_support_m >= 20.0 else 4.5)
            if branch_has_positive_rc_gap:
                max_length = max(max_length, _rc_gap_branch_polygon_length_m(branch))
            if branch_has_local_road_mouth:
                max_length = max(
                    max_length,
                    _local_road_mouth_reach_length_m(
                        branch,
                        branch_center_distance_m=branch_center_distance_m,
                        far_junction_distance_m=(
                            max(far_group_node_distance_m, far_junction_distance_m)
                            if (far_group_node is not None or far_junction_is_group_node)
                            else 0.0
                        ),
                    ),
                )
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
                not branch.conflict_excluded
                and (
                    branch.is_main_direction
                    or branch.selected_for_polygon
                    or branch_has_positive_rc_gap
                    or branch_has_local_road_mouth
                    or branch_has_minimal_local_road_touch
                )
            )
            nearest_foreign_junction_distance_m = _branch_nearest_foreign_local_junction_distance_m(
                branch,
                center=analysis_center,
                local_roads=local_roads,
                local_node_by_id=local_node_by_id,
                target_group_node_ids=group_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            if branch_selected_for_polygon and nearest_foreign_junction_distance_m > 0.0:
                foreign_branch_cap_length_m = max(
                    6.0 if branch.is_main_direction else 3.5,
                    nearest_foreign_junction_distance_m - (6.0 if branch.is_main_direction else 4.0),
                )
                max_length = min(max_length, foreign_branch_cap_length_m)
                foreign_guard_margin_m = 4.5 if branch.is_main_direction else 3.0
                foreign_guard_keep_length_m = max(
                    3.0 if not branch.is_main_direction else 5.0,
                    nearest_foreign_junction_distance_m - foreign_guard_margin_m,
                )
                foreign_branch_clip = _branch_ray_geometry(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    length_m=patch_size_m / 2.0,
                ).buffer(
                    max(
                        half_width * (2.1 if branch.is_main_direction else 1.9),
                        8.5 if branch.is_main_direction else 7.0,
                    ),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                foreign_branch_keep = _branch_ray_geometry(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    length_m=foreign_guard_keep_length_m,
                ).buffer(
                    max(
                        half_width * (1.05 if branch.is_main_direction else 0.95),
                        4.5 if branch.is_main_direction else 3.5,
                    ),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                if not foreign_branch_clip.is_empty:
                    foreign_branch_overreach_exclusion = foreign_branch_clip.difference(
                        foreign_branch_keep.buffer(max(resolution_m, 0.4), join_style=1)
                    )
                    if not foreign_branch_overreach_exclusion.is_empty:
                        branch_overreach_exclusion_geometries.append(
                            foreign_branch_overreach_exclusion
                        )
            pre_business_max_length = max_length
            business_cap_length_m = _business_branch_length_cap_m(
                branch,
                max_length_m=max_length,
                branch_has_positive_rc_gap=branch_has_positive_rc_gap,
                branch_has_local_road_mouth=branch_has_local_road_mouth,
                branch_has_minimal_local_road_touch=branch_has_minimal_local_road_touch,
            )
            max_length = min(max_length, business_cap_length_m)
            business_cap_applied = max_length + 0.5 < pre_business_max_length
            if (
                branch_selected_for_polygon
                and max_length > 0.0
                and business_cap_applied
            ):
                branch_business_keep_clip = _branch_cap_clip_geometry(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    length_m=max_length,
                    half_width_m=half_width,
                    drivezone_union=drivezone_union,
                    extension_m=max(1.0, half_width * 0.2),
                    lateral_scale=1.15 if not branch.is_main_direction else 1.08,
                    minimum_half_width_m=(
                        4.5 if branch.rcsdroad_ids else 4.0
                    ) if not branch.is_main_direction else max(5.0, half_width * 0.85),
                    center_radius_m=max(half_width + 2.0, 6.0 if not branch.is_main_direction else 7.0),
                )
                branch_business_sector = _branch_cap_clip_geometry(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    length_m=patch_size_m / 2.0,
                    half_width_m=half_width,
                    drivezone_union=drivezone_union,
                    lateral_scale=(
                        1.9 if branch.rcsdroad_ids else 1.8
                    ) if not branch.is_main_direction else 1.5,
                    minimum_half_width_m=(
                        8.0 if branch.rcsdroad_ids else 7.0
                    ) if not branch.is_main_direction else max(7.0, half_width * 1.15),
                    center_radius_m=max(half_width + 2.0, 6.0 if not branch.is_main_direction else 7.0),
                )
                if not branch_business_sector.is_empty and not branch_business_keep_clip.is_empty:
                    branch_business_overreach_exclusion = branch_business_sector.difference(
                        branch_business_keep_clip.buffer(max(resolution_m, 0.4), join_style=1)
                    )
                    if not branch_business_overreach_exclusion.is_empty:
                        branch_overreach_exclusion_geometries.append(
                            branch_business_overreach_exclusion
                        )
            if (
                branch_selected_for_polygon
                and not branch.is_main_direction
                and not branch.rcsdroad_ids
                and not branch_has_local_road_mouth
                and not branch_has_minimal_local_road_touch
            ):
                compact_selected_keep_length = max(float(max_length) + 1.0, 4.5)
                compact_selected_keep_width = max(half_width * 1.2, 4.5)
                if (
                    has_any_local_road_mouth_branch
                    and branch.evidence_level == "arm_full_rc"
                    and branch.rc_support_m >= 20.0
                ):
                    compact_selected_keep_length = max(float(max_length) + 0.2, 3.2)
                    compact_selected_keep_width = max(half_width * 1.0, 3.5)
                branch_keep_clip = _branch_ray_geometry(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    length_m=compact_selected_keep_length,
                ).buffer(
                    compact_selected_keep_width,
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                branch_sector_band = _branch_ray_geometry(
                    analysis_center,
                    angle_deg=branch.angle_deg,
                    length_m=patch_size_m / 2.0,
                ).buffer(
                    max(half_width * 1.8, 8.0),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                if not branch_sector_band.is_empty:
                    branch_overreach_exclusion = branch_sector_band.difference(
                        branch_keep_clip.buffer(max(resolution_m, 0.4), join_style=1)
                    )
                    if not branch_overreach_exclusion.is_empty:
                        branch_overreach_exclusion_geometries.append(branch_overreach_exclusion)
            if (
                branch_has_local_road_mouth
                and branch_selected_for_polygon
                and (
                    branch_center_distance_m > 12.0
                    or far_junction_distance_m > branch_center_distance_m + 10.0
                )
            ):
                local_mouth_protected_road_ids.update(branch.road_ids)
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
                    branch_road_geometries = [
                        geometry
                        for geometry in branch_road_geometries
                        if geometry is not None and not geometry.is_empty
                    ]
                    compact_local_branch_support = bool(branch_road_geometries) and _branch_prefers_compact_local_support(
                        branch,
                        branch_has_local_road_mouth=branch_has_local_road_mouth,
                        branch_has_minimal_local_road_touch=branch_has_minimal_local_road_touch,
                    )
                    if not compact_local_branch_support:
                        support_geometries.extend(branch_road_geometries)
                        branch_selected_geometries.extend(branch_road_geometries)
                    if compact_local_branch_support:
                        compact_branch_clip = _branch_ray_geometry(
                            analysis_center,
                            angle_deg=branch.angle_deg,
                            length_m=max(max_length + 4.0, 8.0),
                        ).buffer(
                            max(half_width * 1.2, 4.0),
                            cap_style=2,
                            join_style=2,
                        ).intersection(drivezone_union)
                        compact_branch_geometries = [
                            geometry.intersection(compact_branch_clip)
                            for geometry in branch_road_geometries
                        ]
                        compact_branch_geometries = [
                            geometry
                            for geometry in compact_branch_geometries
                            if geometry is not None and not geometry.is_empty
                        ]
                        mouth_fan_source_geometries = (
                            compact_branch_geometries
                            if compact_branch_geometries
                            else branch_road_geometries
                        )
                        mouth_fan_center = analysis_center
                        remote_refine_clip = GeometryCollection()
                        uses_remote_mouth_anchor = False
                        if (
                            branch_has_local_road_mouth
                            and branch_road_geometries
                        ):
                            branch_geometry_union = unary_union(branch_road_geometries)
                            mouth_anchor_point: Point | None = None
                            if far_group_node is not None:
                                mouth_anchor_point = far_group_node.geometry
                            elif far_junction_point is not None and far_junction_is_group_node:
                                mouth_anchor_point = far_junction_point
                            elif branch_center_distance_m > 12.0:
                                mouth_anchor_point = nearest_points(
                                    analysis_center,
                                    branch_geometry_union,
                                )[1]
                            if mouth_anchor_point is not None:
                                uses_remote_mouth_anchor = True
                                remote_connector_geometry = LineString(
                                    [
                                        (float(analysis_center.x), float(analysis_center.y)),
                                        (float(mouth_anchor_point.x), float(mouth_anchor_point.y)),
                                    ]
                                ).buffer(
                                    max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.75, half_width * 0.35),
                                    cap_style=2,
                                    join_style=2,
                                ).intersection(drivezone_union)
                                if not remote_connector_geometry.is_empty:
                                    support_geometries.append(remote_connector_geometry)
                                    branch_selected_geometries.append(remote_connector_geometry)
                                distal_support_clip = mouth_anchor_point.buffer(
                                    max(half_width * 2.0, 10.0),
                                    join_style=1,
                                ).intersection(drivezone_union)
                                distal_branch_geometries = [
                                    geometry.intersection(distal_support_clip)
                                    for geometry in mouth_fan_source_geometries
                                ]
                                distal_branch_geometries = [
                                    geometry
                                    for geometry in distal_branch_geometries
                                    if geometry is not None and not geometry.is_empty
                                ]
                                if distal_branch_geometries:
                                    mouth_fan_source_geometries = distal_branch_geometries
                                mouth_fan_center = mouth_anchor_point
                                remote_refine_clip = unary_union(
                                    [
                                        analysis_center.buffer(half_width + 4.0),
                                        distal_support_clip,
                                        remote_connector_geometry,
                                    ]
                                ).buffer(max(resolution_m, 0.4), join_style=1).intersection(drivezone_union)
                                if far_group_node is not None or far_junction_is_group_node:
                                    remote_mouth_exclusion_clip = mouth_anchor_point.buffer(
                                        max(half_width * 4.0, 26.0),
                                        join_style=1,
                                    ).intersection(drivezone_union)
                                    remote_mouth_keep_geometry = unary_union(
                                        [
                                            remote_connector_geometry,
                                            distal_support_clip,
                                        ]
                                    ).buffer(max(resolution_m, 0.4), join_style=1).intersection(drivezone_union)
                                    for road in local_roads:
                                        if road.road_id in remote_mouth_protected_road_ids or road.road_id in branch.road_ids:
                                            continue
                                        if not road.geometry.intersects(remote_mouth_exclusion_clip):
                                            continue
                                        remote_mouth_exclusion = road.geometry.intersection(
                                            remote_mouth_exclusion_clip
                                        ).buffer(
                                            max(half_width * 1.15, 3.2),
                                            cap_style=2,
                                            join_style=2,
                                        ).intersection(drivezone_union)
                                        if remote_mouth_exclusion.is_empty:
                                            continue
                                        remote_mouth_exclusion = remote_mouth_exclusion.difference(
                                            remote_mouth_keep_geometry
                                        )
                                        if not remote_mouth_exclusion.is_empty:
                                            branch_overreach_exclusion_geometries.append(remote_mouth_exclusion)
                        mouth_fan_geometry = _build_local_branch_mouth_fan_geometry(
                            center=mouth_fan_center,
                            branch_geometries=mouth_fan_source_geometries,
                            drivezone_union=drivezone_union,
                            half_width=half_width,
                        )
                        if not mouth_fan_geometry.is_empty:
                            support_geometries.append(mouth_fan_geometry)
                            branch_selected_geometries.append(mouth_fan_geometry)
                            compact_connector_length = min(
                                max_length,
                                6.0 if branch_has_local_road_mouth else 4.5,
                            )
                            compact_connector_geometry = _branch_ray_geometry(
                                analysis_center,
                                angle_deg=branch.angle_deg,
                                length_m=max(compact_connector_length, 2.0),
                            ).buffer(
                                max(half_width * 0.55, 1.4),
                                cap_style=2,
                                join_style=2,
                            ).intersection(drivezone_union)
                            if not compact_connector_geometry.is_empty:
                                support_geometries.append(compact_connector_geometry)
                                branch_selected_geometries.append(compact_connector_geometry)
                            refine_clip = (
                                remote_refine_clip
                                if not remote_refine_clip.is_empty
                                else analysis_center.buffer(
                                    max_length + half_width + 6.0
                                ).intersection(drivezone_union)
                            )
                            if not refine_clip.is_empty:
                                refine_geometry = unary_union(
                                    [
                                        geometry.intersection(refine_clip)
                                        for geometry in branch_selected_geometries
                                        if geometry is not None and not geometry.is_empty
                                    ]
                                )
                                if refine_geometry.is_empty:
                                    refine_geometry = mouth_fan_geometry.intersection(refine_clip)
                                branch_local_refinement_specs.append(
                                    (
                                        refine_clip,
                                        refine_geometry,
                                        branch_has_local_road_mouth and uses_remote_mouth_anchor,
                                    )
                                )
                        else:
                            compact_local_branch_support = False
                            support_geometries.extend(branch_road_geometries)
                            branch_selected_geometries.extend(branch_road_geometries)
                if not connector_geometry.is_empty and not compact_local_branch_support:
                    support_geometries.append(connector_geometry)
                    branch_selected_geometries.append(connector_geometry)
                if not tip_geometry.is_empty and not compact_local_branch_support:
                    support_geometries.append(tip_geometry)
                    branch_selected_geometries.append(tip_geometry)
                if (
                    branch.rcsdroad_ids
                    and not compact_local_branch_support
                    and not branch.is_main_direction
                    and any(group_id in positive_rc_groups for group_id in branch.rcsdroad_ids)
                ):
                    positive_branch_mouth_fan = _build_local_branch_mouth_fan_geometry(
                        center=analysis_center,
                        branch_geometries=branch_selected_geometries,
                        drivezone_union=drivezone_union,
                        half_width=half_width,
                    )
                    if not positive_branch_mouth_fan.is_empty:
                        support_geometries.append(positive_branch_mouth_fan)
                        branch_selected_geometries.append(positive_branch_mouth_fan)
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

        if enable_t_mouth_rc_bridge_support:
            selected_rc_support_road_ids, selected_rc_support_clip_by_road_id = _collect_selected_rc_support_road_ids(
                road_branches=road_branches,
                positive_rc_groups=positive_rc_groups,
                negative_rc_groups=negative_rc_groups,
                rc_branch_by_id=rc_branch_by_id,
                positive_rc_road_ids=positive_rc_road_ids,
                local_rc_roads=local_rc_roads,
                analysis_center=analysis_center,
                drivezone_union=drivezone_union,
            )
        else:
            selected_rc_support_road_ids = set()
            selected_rc_support_clip_by_road_id = {}

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
        positive_rc_connector_geometries: list[BaseGeometry] = []
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
                nearest_support_point = nearest_points(analysis_center, local_geometry)[1]
                connector_geometry = LineString(
                    [
                        (float(analysis_center.x), float(analysis_center.y)),
                        (float(nearest_support_point.x), float(nearest_support_point.y)),
                    ]
                ).buffer(
                    POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M,
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                if not connector_geometry.is_empty:
                    positive_rc_connector_geometries.append(connector_geometry)
            if positive_rc_geometries or positive_rc_connector_geometries:
                support_geometries.extend(
                    geometry
                    for geometry in [*positive_rc_geometries, *positive_rc_connector_geometries]
                    if not geometry.is_empty
                )
        if enable_t_mouth_rc_bridge_support:
            selected_rc_support_geometries, selected_rc_support_node_ids = _build_selected_rc_support_geometries(
                selected_rc_support_road_ids=selected_rc_support_road_ids,
                polygon_support_rc_road_ids=polygon_support_rc_road_ids,
                selected_rc_support_clip_by_road_id=selected_rc_support_clip_by_road_id,
                positive_nonmain_bridge_road_ids=positive_nonmain_bridge_road_ids,
                local_rc_roads=local_rc_roads,
                local_rc_nodes=local_rc_nodes,
                local_roads=local_roads,
                local_nodes=local_nodes,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                group_nodes=group_nodes,
                normalized_mainnodeid=normalized_mainnodeid,
                analysis_center=analysis_center,
                drivezone_union=drivezone_union,
                semantic_mainnodeids=semantic_mainnodeids,
            )
        else:
            selected_rc_support_geometries = []
            selected_rc_support_node_ids = set()
        validation_support_rc_node_ids = polygon_support_rc_node_ids | selected_rc_support_node_ids
        validation_support_rc_road_ids = polygon_support_rc_road_ids | selected_rc_support_road_ids
        validation_support_clip_parts = [polygon_support_clip]
        validation_support_clip_parts.extend(
            geometry
            for geometry in selected_rc_support_clip_by_road_id.values()
            if geometry is not None and not geometry.is_empty
        )
        validation_support_clip = unary_union(validation_support_clip_parts)
        validation_support_cover = validation_support_clip.buffer(
            max(resolution_m, 0.5),
            join_style=1,
        )
        candidate_selected_positive_group_rc_road_ids = {
            road_id
            for road_id in candidate_selected_positive_group_rc_road_ids
            if road_id in (
                positive_rc_road_ids
                | polygon_support_rc_road_ids
                | selected_rc_support_road_ids
            )
        }
        if selected_rc_support_geometries:
            support_geometries.extend(
                geometry
                for geometry in selected_rc_support_geometries
                if geometry is not None and not geometry.is_empty
            )
        mandatory_support_geometries = [
            *group_node_buffers,
            *group_node_connectors,
            *selected_rc_node_buffers,
            *selected_rc_node_connectors,
            *positive_rc_geometries,
            *positive_rc_connector_geometries,
            *selected_rc_support_geometries,
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
        selected_positive_rc_keep_clip = _build_polygon_support_clip(
            analysis_center=analysis_center,
            group_nodes=group_nodes,
            local_rc_roads=local_rc_roads,
            local_rc_nodes=local_rc_nodes,
            support_road_ids=candidate_selected_positive_group_rc_road_ids,
            support_node_ids=candidate_selected_rc_node_ids,
        )
        selected_positive_rc_keep_geometries = [
            road.geometry.intersection(selected_positive_rc_keep_clip).buffer(
                max(RC_ROAD_BUFFER_M * 0.9, 2.0),
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union)
            for road in local_rc_roads
            if road.road_id in positive_rc_road_ids
            and not road.geometry.intersection(selected_positive_rc_keep_clip).is_empty
        ]
        enable_semantic_branch_hard_cap = not (
            representative_node.kind_2 == 4
            and bool(positive_rc_road_ids)
            and not local_rc_nodes
        )
        semantic_branch_hard_cap_exclusion_geometry = (
            _build_semantic_branch_hard_cap_exclusion_geometry(
                analysis_center=analysis_center,
                road_branches=road_branches,
                drivezone_union=drivezone_union,
                patch_size_m=patch_size_m,
                resolution_m=resolution_m,
                hard_keep_geometries=[
                    core_geometry,
                    *group_node_buffers,
                    *group_node_connectors,
                    *group_node_reinclude_geometries,
                    *selected_rc_node_buffers,
                    *selected_rc_node_connectors,
                    *selected_positive_rc_keep_geometries,
                    *positive_rc_connector_geometries,
                    *selected_rc_support_geometries,
                ],
            )
            if enable_semantic_branch_hard_cap
            else GeometryCollection()
        )
        if not semantic_branch_hard_cap_exclusion_geometry.is_empty:
            branch_overreach_exclusion_geometries.append(
                semantic_branch_hard_cap_exclusion_geometry
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
        if (
            not positive_rc_groups
            and not polygon_support_rc_road_ids
            and not selected_rc_support_road_ids
            and not selected_rc_node_buffers
        ):
            surface_only_center_clip = analysis_center.buffer(12.0).intersection(drivezone_union)
            if not surface_only_center_clip.is_empty:
                surface_only_center_geometries = [
                    geometry.intersection(surface_only_center_clip)
                    for geometry in support_geometries
                    if geometry is not None and not geometry.is_empty
                ]
                surface_only_center_geometries = [
                    geometry
                    for geometry in surface_only_center_geometries
                    if geometry is not None and not geometry.is_empty
                ]
                if surface_only_center_geometries:
                    surface_only_center_fill = _build_local_branch_mouth_fan_geometry(
                        center=analysis_center,
                        branch_geometries=surface_only_center_geometries,
                        drivezone_union=surface_only_center_clip,
                        half_width=max(MAIN_BRANCH_HALF_WIDTH_M, SIDE_BRANCH_HALF_WIDTH_M),
                    )
                    if not surface_only_center_fill.is_empty:
                        candidate_polygon_geometry = unary_union(
                            [candidate_polygon_geometry, surface_only_center_fill]
                        )
                surface_only_center_geometry = candidate_polygon_geometry.intersection(
                    surface_only_center_clip
                )
                if not surface_only_center_geometry.is_empty:
                    surface_only_center_geometry = surface_only_center_geometry.convex_hull.buffer(
                        max(resolution_m, 0.4),
                        join_style=1,
                    ).intersection(surface_only_center_clip)
                    if not surface_only_center_geometry.is_empty:
                        candidate_polygon_geometry = unary_union(
                            [
                                candidate_polygon_geometry.difference(surface_only_center_clip),
                                surface_only_center_geometry,
                            ]
                        )
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
        if (
            not virtual_polygon_geometry.is_empty
            and not semantic_branch_hard_cap_exclusion_geometry.is_empty
        ):
            virtual_polygon_geometry = virtual_polygon_geometry.difference(
                semantic_branch_hard_cap_exclusion_geometry
            ).intersection(drivezone_union)
            if group_node_reinclude_geometries:
                virtual_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, *group_node_reinclude_geometries]
                ).intersection(drivezone_union)
            if not virtual_polygon_geometry.is_empty:
                virtual_polygon_geometry = _fill_small_polygon_holes(
                    virtual_polygon_geometry.buffer(0),
                    max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                )
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(
                        drivezone_union
                    )
        if not virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                geometry=virtual_polygon_geometry,
                drivezone_union=drivezone_union,
                seed_geometry=core_geometry,
            )
        if not virtual_polygon_geometry.is_empty and branch_overreach_exclusion_geometries:
            virtual_polygon_geometry = virtual_polygon_geometry.difference(
                unary_union(branch_overreach_exclusion_geometries)
            ).intersection(drivezone_union)
            if not virtual_polygon_geometry.is_empty:
                virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                    geometry=virtual_polygon_geometry,
                    drivezone_union=drivezone_union,
                    seed_geometry=core_geometry,
                )
        if not virtual_polygon_geometry.is_empty and branch_local_refinement_specs:
            for refine_clip, refine_geometry, preserve_branch_shape in branch_local_refinement_specs:
                if refine_clip.is_empty or refine_geometry.is_empty:
                    continue
                replacement_geometries = [
                    core_geometry.intersection(refine_clip),
                    refine_geometry,
                    *[
                        geometry.intersection(refine_clip)
                        for geometry in group_node_reinclude_geometries
                    ],
                    *[
                        geometry.intersection(refine_clip)
                        for geometry in group_node_buffers
                    ],
                ]
                replacement_geometries = [
                    geometry
                    for geometry in replacement_geometries
                    if geometry is not None and not geometry.is_empty
                ]
                if not replacement_geometries:
                    continue
                replacement_base = unary_union(replacement_geometries).intersection(refine_clip)
                if preserve_branch_shape:
                    replacement = replacement_base.buffer(
                        max(resolution_m, 0.4),
                        join_style=1,
                    ).intersection(refine_clip)
                else:
                    replacement = replacement_base.convex_hull.intersection(refine_clip)
                if replacement.is_empty:
                    replacement = replacement_base
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
        if (
            not virtual_polygon_geometry.is_empty
            and not positive_rc_groups
            and not polygon_support_rc_road_ids
            and not selected_rc_support_road_ids
            and not selected_rc_node_buffers
            and not selected_rc_support_geometries
        ):
            compact_surface_only_hull_geometry = _build_compact_surface_only_hull_geometry(
                analysis_center=analysis_center,
                road_branches=road_branches,
                drivezone_union=drivezone_union,
            )
            if not compact_surface_only_hull_geometry.is_empty:
                virtual_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, compact_surface_only_hull_geometry]
                ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
        if not virtual_polygon_geometry.is_empty:
            protected_group_node_ids = {node.node_id for node in group_nodes}
            protected_branch_road_ids = {
                road_id
                for branch in road_branches
                if branch.is_main_direction or bool(branch.rcsdroad_ids)
                for road_id in branch.road_ids
            }
            if positive_nonmain_bridge_local_node_ids:
                protected_branch_road_ids.update(
                    road.road_id
                    for road in local_roads
                    if (
                        road.snodeid in positive_nonmain_bridge_local_node_ids
                        or road.enodeid in positive_nonmain_bridge_local_node_ids
                    )
                )
            protected_branch_road_ids.update(local_mouth_protected_road_ids)
            protected_branch_road_ids.update(
                road.road_id
                for road in local_roads
                if road.snodeid in protected_group_node_ids or road.enodeid in protected_group_node_ids
            )
            foreign_node_exclusion_geometry = _build_foreign_node_exclusion_geometry(
                polygon_geometry=virtual_polygon_geometry,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                allowed_road_ids=protected_branch_road_ids,
                drivezone_union=drivezone_union,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            if not foreign_node_exclusion_geometry.is_empty:
                keep_seed_parts = [core_geometry, *group_node_reinclude_geometries]
                if not mandatory_support_union.is_empty:
                    keep_seed_parts.append(mandatory_support_union)
                keep_seed_geometry = unary_union(keep_seed_parts).buffer(
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
        if not virtual_polygon_geometry.is_empty and branch_overreach_exclusion_geometries:
            virtual_polygon_geometry = virtual_polygon_geometry.difference(
                unary_union(branch_overreach_exclusion_geometries)
            ).intersection(drivezone_union)
            if not virtual_polygon_geometry.is_empty:
                virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                    geometry=virtual_polygon_geometry,
                    drivezone_union=drivezone_union,
                    seed_geometry=core_geometry,
                )
        legacy_validation_polygon_geometry = (
            virtual_polygon_geometry
            if not virtual_polygon_geometry.is_empty
            else GeometryCollection()
        )
        rc_foreign_keep_parts = [
            *selected_rc_node_buffers,
            *selected_rc_node_connectors,
            *positive_rc_geometries,
            *positive_rc_connector_geometries,
        ]
        if positive_nonmain_bridge_local_node_ids:
            rc_foreign_keep_parts.extend(
                local_node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M + 1.2, 4.0)).intersection(drivezone_union)
                for local_node in local_nodes
                if local_node.node_id in positive_nonmain_bridge_local_node_ids
            )
            rc_foreign_keep_parts.extend(
                road.geometry.buffer(
                    max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                for road in local_roads
                if (
                    road.snodeid in positive_nonmain_bridge_local_node_ids
                    or road.enodeid in positive_nonmain_bridge_local_node_ids
                )
            )
        rc_foreign_keep_parts = [
            geometry
            for geometry in rc_foreign_keep_parts
            if geometry is not None and not geometry.is_empty
        ]
        rc_foreign_keep_geometry = (
            unary_union(rc_foreign_keep_parts)
            if rc_foreign_keep_parts
            else GeometryCollection()
        )
        rc_foreign_tail_keep_parts = [
            *selected_rc_node_buffers,
            *positive_rc_geometries,
        ]
        if positive_nonmain_bridge_local_node_ids:
            rc_foreign_tail_keep_parts.extend(
                local_node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M + 1.2, 4.0)).intersection(drivezone_union)
                for local_node in local_nodes
                if local_node.node_id in positive_nonmain_bridge_local_node_ids
            )
            rc_foreign_tail_keep_parts.extend(
                road.geometry.buffer(
                    max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                for road in local_roads
                if (
                    road.snodeid in positive_nonmain_bridge_local_node_ids
                    or road.enodeid in positive_nonmain_bridge_local_node_ids
                )
            )
        rc_foreign_tail_keep_parts = [
            geometry
            for geometry in rc_foreign_tail_keep_parts
            if geometry is not None and not geometry.is_empty
        ]
        rc_foreign_tail_keep_geometry = (
            unary_union(rc_foreign_tail_keep_parts)
            if rc_foreign_tail_keep_parts
            else GeometryCollection()
        )
        if not virtual_polygon_geometry.is_empty:
            explicit_foreign_group_arm_exclusion_geometry = _build_explicit_foreign_group_arm_exclusion_geometry(
                polygon_geometry=virtual_polygon_geometry,
                analysis_center=analysis_center,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                protected_road_ids=protected_branch_road_ids,
                drivezone_union=drivezone_union,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            if not explicit_foreign_group_arm_exclusion_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    explicit_foreign_group_arm_exclusion_geometry
                ).intersection(drivezone_union)
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
        if not virtual_polygon_geometry.is_empty:
            strict_foreign_local_junction_core_exclusion_geometry = (
                _build_strict_foreign_local_junction_core_exclusion_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    analysis_center=analysis_center,
                    normalized_mainnodeid=normalized_mainnodeid,
                    group_nodes=group_nodes,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    keep_geometry=rc_foreign_tail_keep_geometry,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            if not strict_foreign_local_junction_core_exclusion_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    strict_foreign_local_junction_core_exclusion_geometry
                ).intersection(drivezone_union)
                if group_node_reinclude_geometries:
                    virtual_polygon_geometry = unary_union(
                        [virtual_polygon_geometry, *group_node_reinclude_geometries]
                    ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _fill_small_polygon_holes(
                        virtual_polygon_geometry.buffer(0),
                        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                    )
                    if not virtual_polygon_geometry.is_empty:
                        virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(
                            drivezone_union
                        )
        if not virtual_polygon_geometry.is_empty and not validation_support_rc_road_ids:
            stray_local_road_exclusion_geometries: list[BaseGeometry] = []
            stray_keep_geometry = core_geometry.buffer(
                max(SIDE_BRANCH_HALF_WIDTH_M, 5.0),
                join_style=1,
            ).intersection(drivezone_union)
            for road in local_roads:
                if road.road_id in analyzed_branch_road_ids or road.road_id in local_mouth_protected_road_ids:
                    continue
                covered_geometry = road.geometry.intersection(virtual_polygon_geometry)
                foreign_endpoint_present = any(
                    (
                        local_node_by_id.get(node_id) is not None
                        and local_node_by_id[node_id].mainnodeid not in {None, "0", normalized_mainnodeid}
                    )
                    for node_id in (road.snodeid, road.enodeid)
                )
                minimum_stray_exclusion_length_m = 4.0 if foreign_endpoint_present else 18.0
                if covered_geometry.is_empty or covered_geometry.length < minimum_stray_exclusion_length_m:
                    continue
                exclusion_geometry = road.geometry.buffer(
                    max(SIDE_BRANCH_HALF_WIDTH_M * 1.1, 3.2),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                if exclusion_geometry.is_empty:
                    continue
                exclusion_geometry = exclusion_geometry.difference(stray_keep_geometry)
                if not exclusion_geometry.is_empty:
                    stray_local_road_exclusion_geometries.append(exclusion_geometry)
            if stray_local_road_exclusion_geometries:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    unary_union(stray_local_road_exclusion_geometries)
                ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
        if (
            not virtual_polygon_geometry.is_empty
            and validation_support_rc_road_ids
            and (
                selected_rc_node_buffers
                or selected_rc_node_connectors
                or selected_rc_support_geometries
            )
        ):
            (
                _pre_uncovered_group_node_ids,
                pre_uncovered_support_rc_node_ids,
                pre_uncovered_support_rc_road_ids,
            ) = _validate_polygon_support(
                polygon_geometry=virtual_polygon_geometry,
                group_nodes=group_nodes,
                local_rc_nodes=local_rc_nodes,
                local_rc_roads=local_rc_roads,
                support_node_ids=validation_support_rc_node_ids,
                support_road_ids=validation_support_rc_road_ids,
                support_clip=validation_support_clip,
            )
            if pre_uncovered_support_rc_node_ids or pre_uncovered_support_rc_road_ids:
                virtual_polygon_geometry = unary_union(
                    [
                        virtual_polygon_geometry,
                        *positive_rc_geometries,
                        *positive_rc_connector_geometries,
                        *selected_rc_node_buffers,
                        *selected_rc_node_connectors,
                        *selected_rc_support_geometries,
                    ]
                ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _fill_small_polygon_holes(
                        virtual_polygon_geometry.buffer(0),
                        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                    )
                    if not virtual_polygon_geometry.is_empty:
                        virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(drivezone_union)
                    repair_foreign_node_exclusion_geometry = _build_foreign_node_exclusion_geometry(
                        polygon_geometry=virtual_polygon_geometry,
                        normalized_mainnodeid=normalized_mainnodeid,
                        group_nodes=group_nodes,
                        local_nodes=local_nodes,
                        local_roads=local_roads,
                        allowed_road_ids=protected_branch_road_ids,
                        drivezone_union=drivezone_union,
                        local_road_degree_by_node_id=local_road_degree_by_node_id,
                        semantic_mainnodeids=semantic_mainnodeids,
                    )
                    if not repair_foreign_node_exclusion_geometry.is_empty:
                        repair_keep_seed_parts = [core_geometry, *group_node_reinclude_geometries]
                        if not mandatory_support_union.is_empty:
                            repair_keep_seed_parts.append(mandatory_support_union)
                        repair_keep_seed_geometry = unary_union(repair_keep_seed_parts).buffer(
                            max(resolution_m, 0.4),
                            join_style=1,
                        ).intersection(drivezone_union)
                        repair_exclusion_geometry = repair_foreign_node_exclusion_geometry.difference(
                            repair_keep_seed_geometry
                        )
                        if not repair_exclusion_geometry.is_empty:
                            virtual_polygon_geometry = virtual_polygon_geometry.difference(
                                repair_exclusion_geometry
                            ).intersection(drivezone_union)
                            if group_node_reinclude_geometries:
                                virtual_polygon_geometry = unary_union(
                                    [virtual_polygon_geometry, *group_node_reinclude_geometries]
                                ).intersection(drivezone_union)
                            if not virtual_polygon_geometry.is_empty:
                                virtual_polygon_geometry = _fill_small_polygon_holes(
                                    virtual_polygon_geometry.buffer(0),
                                    max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                                )
                                if not virtual_polygon_geometry.is_empty:
                                    virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(drivezone_union)
        if not virtual_polygon_geometry.is_empty:
            final_stray_local_road_exclusion_geometries: list[BaseGeometry] = []
            for road in local_roads:
                if road.road_id in analyzed_branch_road_ids or road.road_id in local_mouth_protected_road_ids:
                    continue
                covered_geometry = road.geometry.intersection(virtual_polygon_geometry)
                if covered_geometry.is_empty or covered_geometry.length < 9999.0:
                    continue
                road_keep_parts: list[BaseGeometry] = [
                    core_geometry.buffer(
                        max(SIDE_BRANCH_HALF_WIDTH_M, 5.0),
                        join_style=1,
                    ).intersection(drivezone_union)
                ]
                road_keep_parts.extend(
                    node.geometry.buffer(max(POLYGON_RC_NODE_BUFFER_M + 1.5, 20.0)).intersection(drivezone_union)
                    for node in local_rc_nodes
                    if node.node_id in validation_support_rc_node_ids
                    and road.geometry.distance(node.geometry) <= 20.0
                )
                road_keep_parts.extend(
                    node.geometry.buffer(POLYGON_GROUP_NODE_BUFFER_M + 1.0).intersection(drivezone_union)
                    for node in group_nodes
                    if road.geometry.distance(node.geometry) <= 12.0
                )
                road_keep_geometry = unary_union(
                    [
                        geometry
                        for geometry in road_keep_parts
                        if geometry is not None and not geometry.is_empty
                    ]
                ).buffer(max(resolution_m, 0.4), join_style=1).intersection(drivezone_union)
                exclusion_geometry = road.geometry.buffer(
                    max(SIDE_BRANCH_HALF_WIDTH_M * 1.1, 3.2),
                    cap_style=2,
                    join_style=2,
                ).intersection(drivezone_union)
                if exclusion_geometry.is_empty:
                    continue
                exclusion_geometry = exclusion_geometry.difference(road_keep_geometry)
                if not exclusion_geometry.is_empty:
                    final_stray_local_road_exclusion_geometries.append(exclusion_geometry)
            if final_stray_local_road_exclusion_geometries:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    unary_union(final_stray_local_road_exclusion_geometries)
                ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
        processed_local_junction_node_ids: set[str] = set()
        if (
            not virtual_polygon_geometry.is_empty
            and enable_t_mouth_rc_bridge_support
            and validation_support_rc_node_ids
        ):
            current_polygon_cover = virtual_polygon_geometry.buffer(
                POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.2
            )
            final_support_node_seal_geometries = [
                node.geometry.buffer(
                    max(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.8, 1.2)
                ).intersection(drivezone_union)
                for node in local_rc_nodes
                if node.node_id in validation_support_rc_node_ids
            ]
            final_support_local_junction_geometries: list[BaseGeometry] = []
            for support_rc_node in local_rc_nodes:
                if support_rc_node.node_id not in validation_support_rc_node_ids:
                    continue
                nearby_local_nodes = sorted(
                    (
                        (float(local_node.geometry.distance(support_rc_node.geometry)), local_node)
                        for local_node in local_nodes
                        if local_road_degree_by_node_id.get(local_node.node_id, 0) >= 2
                        and (
                            _is_supportable_local_node_for_rc_bridge(
                                node=local_node,
                                target_group_node_ids=analysis_member_node_ids,
                                normalized_mainnodeid=normalized_mainnodeid,
                                local_road_degree_by_node_id=local_road_degree_by_node_id,
                            )
                            or local_node.node_id in positive_nonmain_bridge_local_node_ids
                        )
                        and local_node.node_id not in processed_local_junction_node_ids
                        and float(local_node.geometry.distance(support_rc_node.geometry)) <= 8.0
                    ),
                    key=lambda item: (item[0], float(item[1].geometry.distance(analysis_center))),
                )[:3]
                for _, local_node in nearby_local_nodes:
                    incident_local_roads = [
                        local_road
                        for local_road in local_roads
                        if local_road.snodeid == local_node.node_id or local_road.enodeid == local_node.node_id
                    ]
                    if len(incident_local_roads) < 2:
                        continue
                    node_degree = local_road_degree_by_node_id.get(local_node.node_id, 0)
                    node_clip_radius_m = 13.0 if node_degree >= 3 else 11.0
                    local_road_clip = local_node.geometry.buffer(node_clip_radius_m).intersection(drivezone_union)
                    if local_road_clip.is_empty:
                        continue
                    local_support_parts: list[BaseGeometry] = [
                        local_node.geometry.buffer(
                            max(POLYGON_GROUP_NODE_BUFFER_M * 0.85, 2.4)
                        ).intersection(drivezone_union)
                    ]
                    local_connector_geometry = LineString(
                        [
                            (float(support_rc_node.geometry.x), float(support_rc_node.geometry.y)),
                            (float(local_node.geometry.x), float(local_node.geometry.y)),
                        ]
                    ).buffer(
                        max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.55, 1.2),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                    if not local_connector_geometry.is_empty:
                        local_support_parts.append(local_connector_geometry)
                    substantive_local_road_count = 0
                    undercovered_local_road_count = 0
                    desired_local_road_cover_m = (
                        14.0 if node_degree >= 3 else 10.0
                    )
                    for local_road in incident_local_roads:
                        local_road_geometry = local_road.geometry.intersection(local_road_clip)
                        if local_road_geometry.is_empty or local_road_geometry.length <= 0.5:
                            continue
                        substantive_local_road_count += 1
                        covered_length_m = float(local_road_geometry.intersection(current_polygon_cover).length)
                        road_cover_target_m = min(
                            float(local_road_geometry.length),
                            desired_local_road_cover_m,
                        )
                        road_is_undercovered = covered_length_m + 0.5 < road_cover_target_m
                        if road_is_undercovered:
                            undercovered_local_road_count += 1
                        if node_degree >= 3 or road_is_undercovered:
                            local_road_support_geometry = local_road_geometry.buffer(
                                max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                                cap_style=2,
                                join_style=2,
                            ).intersection(drivezone_union)
                            if not local_road_support_geometry.is_empty:
                                local_support_parts.append(local_road_support_geometry)
                    if substantive_local_road_count < 2:
                        continue
                    if (
                        undercovered_local_road_count == 0
                        and current_polygon_cover.covers(local_node.geometry)
                    ):
                        continue
                    local_support_parts = [
                        geometry
                        for geometry in local_support_parts
                        if geometry is not None and not geometry.is_empty
                    ]
                    if not local_support_parts:
                        continue
                    final_support_local_junction_geometry = unary_union(
                        local_support_parts
                    ).convex_hull.buffer(
                        max(1.0, SIDE_BRANCH_HALF_WIDTH_M * (0.36 if node_degree >= 3 else 0.32)),
                        join_style=1,
                    ).intersection(drivezone_union)
                    if final_support_local_junction_geometry.is_empty:
                        continue
                    final_support_local_junction_geometries.append(final_support_local_junction_geometry)
                    processed_local_junction_node_ids.add(local_node.node_id)
            final_support_node_seal_geometries = [
                geometry
                for geometry in final_support_node_seal_geometries
                if geometry is not None and not geometry.is_empty
            ]
            final_support_local_junction_geometries = [
                geometry
                for geometry in final_support_local_junction_geometries
                if geometry is not None and not geometry.is_empty
            ]
            if final_support_node_seal_geometries or final_support_local_junction_geometries:
                virtual_polygon_geometry = unary_union(
                    [
                        virtual_polygon_geometry,
                        *final_support_node_seal_geometries,
                        *final_support_local_junction_geometries,
                    ]
                ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
        if not virtual_polygon_geometry.is_empty:
            current_group_polygon_cover = virtual_polygon_geometry.buffer(
                POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.2
            )
            uncovered_group_node_ids_for_repair = [
                node.node_id
                for node in group_nodes
                if not current_group_polygon_cover.covers(node.geometry)
            ]
            final_group_node_repair_geometries = _build_uncovered_group_node_repair_geometries(
                uncovered_group_node_ids=uncovered_group_node_ids_for_repair,
                current_polygon_geometry=virtual_polygon_geometry,
                analysis_center=analysis_center,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                drivezone_union=drivezone_union,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
            )
            final_group_node_repair_geometries = [
                geometry
                for geometry in final_group_node_repair_geometries
                if geometry is not None and not geometry.is_empty
            ]
            if final_group_node_repair_geometries:
                virtual_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, *final_group_node_repair_geometries]
                ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
        if not virtual_polygon_geometry.is_empty:
            final_strict_foreign_local_junction_core_exclusion_geometry = (
                _build_strict_foreign_local_junction_core_exclusion_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    analysis_center=analysis_center,
                    normalized_mainnodeid=normalized_mainnodeid,
                    group_nodes=group_nodes,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    keep_geometry=rc_foreign_keep_geometry,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            if not final_strict_foreign_local_junction_core_exclusion_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    final_strict_foreign_local_junction_core_exclusion_geometry
                ).intersection(drivezone_union)
                if group_node_reinclude_geometries:
                    virtual_polygon_geometry = unary_union(
                        [virtual_polygon_geometry, *group_node_reinclude_geometries]
                    ).intersection(drivezone_union)
                if not virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = _fill_small_polygon_holes(
                        virtual_polygon_geometry.buffer(0),
                        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                    )
                    if not virtual_polygon_geometry.is_empty:
                        virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(
                            drivezone_union
                        )
        if not virtual_polygon_geometry.is_empty and validation_support_rc_road_ids:
            (
                _final_pre_uncovered_group_node_ids,
                final_pre_uncovered_support_rc_node_ids,
                final_pre_uncovered_support_rc_road_ids,
            ) = _validate_polygon_support(
                polygon_geometry=virtual_polygon_geometry,
                group_nodes=group_nodes,
                local_rc_nodes=local_rc_nodes,
                local_rc_roads=local_rc_roads,
                support_node_ids=validation_support_rc_node_ids,
                support_road_ids=validation_support_rc_road_ids,
                support_clip=validation_support_clip,
            )
            if final_pre_uncovered_support_rc_node_ids or final_pre_uncovered_support_rc_road_ids:
                final_support_repair_geometries: list[BaseGeometry] = [
                    node.geometry.buffer(POLYGON_RC_NODE_BUFFER_M + 0.4).intersection(drivezone_union)
                    for node in local_rc_nodes
                    if node.node_id in final_pre_uncovered_support_rc_node_ids
                ]
                for road in local_rc_roads:
                    if road.road_id not in final_pre_uncovered_support_rc_road_ids:
                        continue
                    local_repair_geometry = road.geometry.intersection(validation_support_clip)
                    if local_repair_geometry.is_empty or local_repair_geometry.length <= 0.5:
                        continue
                    final_support_repair_geometries.append(
                        local_repair_geometry.buffer(
                            RC_ROAD_BUFFER_M * 0.9,
                            cap_style=2,
                            join_style=2,
                        ).intersection(drivezone_union)
                    )
                final_support_repair_geometries = [
                    geometry
                    for geometry in final_support_repair_geometries
                    if geometry is not None and not geometry.is_empty
                ]
                if final_support_repair_geometries:
                    virtual_polygon_geometry = unary_union(
                        [virtual_polygon_geometry, *final_support_repair_geometries]
                    ).intersection(drivezone_union)
                    if not virtual_polygon_geometry.is_empty:
                        virtual_polygon_geometry = _fill_small_polygon_holes(
                            virtual_polygon_geometry.buffer(0),
                            max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                        )
                        if not virtual_polygon_geometry.is_empty:
                            virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(
                                drivezone_union
                            )
                    final_strict_foreign_local_junction_core_exclusion_geometry = (
                        _build_strict_foreign_local_junction_core_exclusion_geometry(
                            polygon_geometry=virtual_polygon_geometry,
                            analysis_center=analysis_center,
                            normalized_mainnodeid=normalized_mainnodeid,
                            group_nodes=group_nodes,
                            local_nodes=local_nodes,
                            local_roads=local_roads,
                            drivezone_union=drivezone_union,
                            local_road_degree_by_node_id=local_road_degree_by_node_id,
                            keep_geometry=rc_foreign_keep_geometry,
                            semantic_mainnodeids=semantic_mainnodeids,
                        )
                    )
                    if not final_strict_foreign_local_junction_core_exclusion_geometry.is_empty:
                        virtual_polygon_geometry = virtual_polygon_geometry.difference(
                            final_strict_foreign_local_junction_core_exclusion_geometry
                        ).intersection(drivezone_union)
                        if group_node_reinclude_geometries:
                            virtual_polygon_geometry = unary_union(
                                [virtual_polygon_geometry, *group_node_reinclude_geometries]
                            ).intersection(drivezone_union)
                        if not virtual_polygon_geometry.is_empty:
                            virtual_polygon_geometry = _fill_small_polygon_holes(
                                virtual_polygon_geometry.buffer(0),
                                max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                            )
                            if not virtual_polygon_geometry.is_empty:
                                virtual_polygon_geometry = virtual_polygon_geometry.buffer(0).intersection(
                                    drivezone_union
                                )
        if not virtual_polygon_geometry.is_empty:
            virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                geometry=virtual_polygon_geometry,
                drivezone_union=drivezone_union,
                seed_geometry=core_geometry,
            )
        legacy_validation_polygon_geometry = (
            virtual_polygon_geometry
            if not virtual_polygon_geometry.is_empty
            else GeometryCollection()
        )
        uncovered_group_node_ids, uncovered_support_rc_node_ids, uncovered_support_rc_road_ids = _validate_polygon_support(
            polygon_geometry=virtual_polygon_geometry,
            group_nodes=group_nodes,
            local_rc_nodes=local_rc_nodes,
            local_rc_roads=local_rc_roads,
            support_node_ids=validation_support_rc_node_ids,
            support_road_ids=validation_support_rc_road_ids,
            support_clip=validation_support_clip,
        )
        uncovered_support_rc_node_ids, uncovered_support_rc_road_ids = _relax_targeted_foreign_trim_support_gaps(
            uncovered_support_node_ids=uncovered_support_rc_node_ids,
            uncovered_support_road_ids=uncovered_support_rc_road_ids,
            rc_node_by_id=rc_node_by_id,
            rc_road_by_id=rc_road_by_id,
            analysis_center=analysis_center,
            hard_support_node_ids=candidate_selected_rc_node_ids,
            hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
            relax_node_ids=conflict_excluded_rc_node_ids,
            relax_road_ids=conflict_excluded_rc_road_ids,
        )
        if (
            (uncovered_group_node_ids or uncovered_support_rc_node_ids or uncovered_support_rc_road_ids)
            and not legacy_validation_polygon_geometry.is_empty
            and not legacy_validation_polygon_geometry.equals(virtual_polygon_geometry)
        ):
            (
                legacy_uncovered_group_node_ids,
                legacy_uncovered_support_rc_node_ids,
                legacy_uncovered_support_rc_road_ids,
            ) = _validate_polygon_support(
                polygon_geometry=legacy_validation_polygon_geometry,
                group_nodes=group_nodes,
                local_rc_nodes=local_rc_nodes,
                local_rc_roads=local_rc_roads,
                support_node_ids=validation_support_rc_node_ids,
                support_road_ids=validation_support_rc_road_ids,
                support_clip=validation_support_clip,
            )
            legacy_uncovered_support_rc_node_ids, legacy_uncovered_support_rc_road_ids = _relax_targeted_foreign_trim_support_gaps(
                uncovered_support_node_ids=legacy_uncovered_support_rc_node_ids,
                uncovered_support_road_ids=legacy_uncovered_support_rc_road_ids,
                rc_node_by_id=rc_node_by_id,
                rc_road_by_id=rc_road_by_id,
                analysis_center=analysis_center,
                hard_support_node_ids=candidate_selected_rc_node_ids,
                hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                relax_node_ids=conflict_excluded_rc_node_ids,
                relax_road_ids=conflict_excluded_rc_road_ids,
            )
            if (
                not legacy_uncovered_group_node_ids
                and not legacy_uncovered_support_rc_node_ids
                and not legacy_uncovered_support_rc_road_ids
            ):
                announce(
                    logger,
                    (
                        f"[T02-POC] restored legacy validation polygon mainnodeid={normalized_mainnodeid} "
                        f"discarding post-processing regression"
                    ),
                )
                virtual_polygon_geometry = legacy_validation_polygon_geometry
                uncovered_group_node_ids = []
                uncovered_support_rc_node_ids = []
                uncovered_support_rc_road_ids = []
        if uncovered_group_node_ids:
            fallback_group_node_repair_geometries = _build_uncovered_group_node_repair_geometries(
                uncovered_group_node_ids=uncovered_group_node_ids,
                current_polygon_geometry=virtual_polygon_geometry,
                analysis_center=analysis_center,
                normalized_mainnodeid=normalized_mainnodeid,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                drivezone_union=drivezone_union,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
            )
            fallback_group_node_repair_geometries = [
                geometry
                for geometry in fallback_group_node_repair_geometries
                if geometry is not None and not geometry.is_empty
            ]
            if not fallback_group_node_repair_geometries:
                group_node_by_id = {node.node_id: node for node in group_nodes}
                for node_id in uncovered_group_node_ids:
                    node = group_node_by_id.get(node_id)
                    if node is None:
                        continue
                    fallback_group_node_repair_geometries.append(
                        node.geometry.buffer(max(POLYGON_GROUP_NODE_BUFFER_M * 0.95, 2.5)).intersection(
                            drivezone_union
                        )
                    )
                    if not virtual_polygon_geometry.is_empty:
                        nearest_polygon_point = nearest_points(node.geometry, virtual_polygon_geometry)[1]
                        fallback_group_node_repair_geometries.append(
                            LineString(
                                [
                                    (float(node.geometry.x), float(node.geometry.y)),
                                    (float(nearest_polygon_point.x), float(nearest_polygon_point.y)),
                                ]
                            ).buffer(
                                max(POLYGON_GROUP_NODE_CONNECTOR_HALF_WIDTH_M * 0.85, 1.6),
                                cap_style=2,
                                join_style=2,
                            ).intersection(drivezone_union)
                        )
                    local_clip = node.geometry.buffer(14.0).intersection(drivezone_union)
                    if not local_clip.is_empty:
                        for road in local_roads:
                            if road.snodeid != node_id and road.enodeid != node_id:
                                continue
                            local_geometry = road.geometry.intersection(local_clip)
                            if local_geometry.is_empty or local_geometry.length <= 0.5:
                                continue
                            fallback_group_node_repair_geometries.append(
                                local_geometry.buffer(
                                    max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                                    cap_style=2,
                                    join_style=2,
                                ).intersection(drivezone_union)
                            )
                fallback_group_node_repair_geometries = [
                    geometry
                    for geometry in fallback_group_node_repair_geometries
                    if geometry is not None and not geometry.is_empty
                ]
            if fallback_group_node_repair_geometries:
                repaired_validation_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, *fallback_group_node_repair_geometries]
                ).intersection(drivezone_union)
                if not repaired_validation_polygon_geometry.is_empty:
                    repaired_validation_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=repaired_validation_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
                (
                    repaired_uncovered_group_node_ids,
                    repaired_uncovered_support_rc_node_ids,
                    repaired_uncovered_support_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=repaired_validation_polygon_geometry,
                    group_nodes=group_nodes,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=validation_support_rc_node_ids,
                    support_road_ids=validation_support_rc_road_ids,
                    support_clip=validation_support_clip,
                )
                repaired_uncovered_support_rc_node_ids, repaired_uncovered_support_rc_road_ids = _relax_targeted_foreign_trim_support_gaps(
                    uncovered_support_node_ids=repaired_uncovered_support_rc_node_ids,
                    uncovered_support_road_ids=repaired_uncovered_support_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_support_node_ids=candidate_selected_rc_node_ids,
                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                if (
                    not repaired_uncovered_group_node_ids
                    and not repaired_uncovered_support_rc_node_ids
                    and not repaired_uncovered_support_rc_road_ids
                ):
                    announce(
                        logger,
                        (
                            f"[T02-POC] fallback group-node repair applied mainnodeid={normalized_mainnodeid} "
                            f"group_nodes={','.join(sorted(uncovered_group_node_ids))}"
                        ),
                    )
                    virtual_polygon_geometry = repaired_validation_polygon_geometry
                    uncovered_group_node_ids = []
                    uncovered_support_rc_node_ids = []
                    uncovered_support_rc_road_ids = []
                else:
                    announce(
                        logger,
                        (
                            f"[T02-POC] fallback group-node repair discarded mainnodeid={normalized_mainnodeid} "
                            f"group_uncovered={','.join(sorted(repaired_uncovered_group_node_ids)) or '-'} "
                            f"support_nodes={','.join(sorted(repaired_uncovered_support_rc_node_ids)) or '-'} "
                            f"support_roads={','.join(sorted(repaired_uncovered_support_rc_road_ids)) or '-'}"
                        ),
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
        if not virtual_polygon_geometry.is_empty and not positive_nonmain_bridge_local_node_ids:
            final_foreign_local_junction_node_core_exclusion_geometry = (
                _build_foreign_local_junction_node_core_exclusion_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    analysis_center=analysis_center,
                    normalized_mainnodeid=normalized_mainnodeid,
                    group_nodes=group_nodes,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    keep_geometry=rc_foreign_keep_geometry,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            if not final_foreign_local_junction_node_core_exclusion_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    final_foreign_local_junction_node_core_exclusion_geometry
                ).intersection(drivezone_union)
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
        analysis_auxiliary_node_ids = {node.node_id for node in analysis_auxiliary_nodes}
        covered_extra_local_road_ids: list[str] = []
        polygon_cover = virtual_polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
        foreign_node_cover = virtual_polygon_geometry.buffer(max(resolution_m, 0.25))
        covered_extra_local_node_ids = sorted(
            node.node_id
            for node in local_nodes
            if (
                _is_foreign_local_semantic_node(
                    node=node,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
                and _polygon_substantively_covers_node(
                    virtual_polygon_geometry,
                    node.geometry,
                    cover_radius_m=max(resolution_m, 0.5),
                )
            )
        )
        if covered_extra_local_node_ids:
            targeted_foreign_local_trim_geometry = _build_targeted_foreign_local_junction_trim_geometry(
                node_ids=set(covered_extra_local_node_ids),
                local_nodes=local_nodes,
                local_roads=local_roads,
                drivezone_union=drivezone_union,
            )
            if not targeted_foreign_local_trim_geometry.is_empty:
                announce(
                    logger,
                    (
                        f"[T02-POC] targeted foreign trim candidate mainnodeid={normalized_mainnodeid} "
                        f"extra_nodes={','.join(covered_extra_local_node_ids)}"
                    ),
                )
                trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    targeted_foreign_local_trim_geometry
                ).intersection(drivezone_union)
                if group_node_reinclude_geometries:
                    trimmed_virtual_polygon_geometry = unary_union(
                        [trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                    ).intersection(drivezone_union)
                if not trimmed_virtual_polygon_geometry.is_empty:
                    trimmed_virtual_polygon_geometry = _fill_small_polygon_holes(
                        trimmed_virtual_polygon_geometry.buffer(0),
                        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                    )
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = trimmed_virtual_polygon_geometry.buffer(0).intersection(
                            drivezone_union
                        )
                (
                    trimmed_uncovered_group_node_ids,
                    trimmed_uncovered_support_rc_node_ids,
                    trimmed_uncovered_support_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=trimmed_virtual_polygon_geometry,
                    group_nodes=group_nodes,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=validation_support_rc_node_ids,
                    support_road_ids=validation_support_rc_road_ids,
                    support_clip=validation_support_clip,
                )
                (
                    trimmed_uncovered_support_rc_node_ids,
                    trimmed_uncovered_support_rc_road_ids,
                ) = _relax_targeted_foreign_trim_support_gaps(
                    uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                    uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_support_node_ids=candidate_selected_rc_node_ids,
                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                if (
                    not trimmed_uncovered_group_node_ids
                    and not trimmed_uncovered_support_rc_node_ids
                    and not trimmed_uncovered_support_rc_road_ids
                ):
                    announce(
                        logger,
                        (
                            f"[T02-POC] targeted foreign trim applied mainnodeid={normalized_mainnodeid} "
                            f"extra_nodes={','.join(covered_extra_local_node_ids)}"
                        ),
                    )
                    virtual_polygon_geometry = trimmed_virtual_polygon_geometry
                    polygon_cover = virtual_polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
                    foreign_node_cover = virtual_polygon_geometry.buffer(max(resolution_m, 0.25))
                    covered_extra_local_node_ids = sorted(
                        node.node_id
                        for node in local_nodes
                        if (
                            _is_foreign_local_semantic_node(
                                node=node,
                                target_group_node_ids=analysis_member_node_ids,
                                normalized_mainnodeid=normalized_mainnodeid,
                                local_road_degree_by_node_id=local_road_degree_by_node_id,
                                semantic_mainnodeids=semantic_mainnodeids,
                            )
                            and _polygon_substantively_covers_node(
                                virtual_polygon_geometry,
                                node.geometry,
                                cover_radius_m=max(resolution_m, 0.5),
                            )
                        )
                    )
                    announce(
                        logger,
                        (
                            f"[T02-POC] targeted foreign trim result mainnodeid={normalized_mainnodeid} "
                            f"remaining_extra_nodes={','.join(covered_extra_local_node_ids)}"
                        ),
                    )
                else:
                    announce(
                        logger,
                        (
                            f"[T02-POC] targeted foreign trim discarded mainnodeid={normalized_mainnodeid} "
                            f"group_uncovered={','.join(sorted(trimmed_uncovered_group_node_ids)) or '-'} "
                            f"support_nodes={','.join(sorted(trimmed_uncovered_support_rc_node_ids)) or '-'} "
                            f"support_roads={','.join(sorted(trimmed_uncovered_support_rc_road_ids)) or '-'}"
                        ),
                    )
                    targeted_foreign_semantic_core_trim_geometry = (
                        _build_targeted_foreign_semantic_node_core_trim_geometry(
                            node_ids=set(covered_extra_local_node_ids),
                            local_nodes=local_nodes,
                            local_roads=local_roads,
                            drivezone_union=drivezone_union,
                        )
                    )
                    if not targeted_foreign_semantic_core_trim_geometry.is_empty:
                        fallback_trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                            targeted_foreign_semantic_core_trim_geometry
                        ).intersection(drivezone_union)
                        if group_node_reinclude_geometries:
                            fallback_trimmed_virtual_polygon_geometry = unary_union(
                                [fallback_trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                            ).intersection(drivezone_union)
                        if not fallback_trimmed_virtual_polygon_geometry.is_empty:
                            fallback_trimmed_virtual_polygon_geometry = _fill_small_polygon_holes(
                                fallback_trimmed_virtual_polygon_geometry.buffer(0),
                                max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                            )
                            if not fallback_trimmed_virtual_polygon_geometry.is_empty:
                                fallback_trimmed_virtual_polygon_geometry = (
                                    fallback_trimmed_virtual_polygon_geometry.buffer(0).intersection(drivezone_union)
                                )
                        (
                            fallback_uncovered_group_node_ids,
                            fallback_uncovered_support_rc_node_ids,
                            fallback_uncovered_support_rc_road_ids,
                        ) = _validate_polygon_support(
                            polygon_geometry=fallback_trimmed_virtual_polygon_geometry,
                            group_nodes=group_nodes,
                            local_rc_nodes=local_rc_nodes,
                            local_rc_roads=local_rc_roads,
                            support_node_ids=validation_support_rc_node_ids,
                            support_road_ids=validation_support_rc_road_ids,
                            support_clip=validation_support_clip,
                        )
                        (
                            fallback_uncovered_support_rc_node_ids,
                            fallback_uncovered_support_rc_road_ids,
                        ) = _relax_targeted_foreign_trim_support_gaps(
                            uncovered_support_node_ids=fallback_uncovered_support_rc_node_ids,
                            uncovered_support_road_ids=fallback_uncovered_support_rc_road_ids,
                            rc_node_by_id=rc_node_by_id,
                            rc_road_by_id=rc_road_by_id,
                            analysis_center=analysis_center,
                            hard_support_node_ids=candidate_selected_rc_node_ids,
                            hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                            relax_node_ids=conflict_excluded_rc_node_ids,
                            relax_road_ids=conflict_excluded_rc_road_ids,
                        )
                        if (
                            not fallback_uncovered_group_node_ids
                            and not fallback_uncovered_support_rc_node_ids
                            and not fallback_uncovered_support_rc_road_ids
                        ):
                            announce(
                                logger,
                                (
                                    f"[T02-POC] targeted foreign semantic-core trim applied "
                                    f"mainnodeid={normalized_mainnodeid} "
                                    f"extra_nodes={','.join(covered_extra_local_node_ids)}"
                                ),
                            )
                            virtual_polygon_geometry = fallback_trimmed_virtual_polygon_geometry
                            polygon_cover = virtual_polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
                            foreign_node_cover = virtual_polygon_geometry.buffer(max(resolution_m, 0.25))
                            covered_extra_local_node_ids = sorted(
                                node.node_id
                                for node in local_nodes
                                if (
                                    _is_foreign_local_semantic_node(
                                        node=node,
                                        target_group_node_ids=analysis_member_node_ids,
                                        normalized_mainnodeid=normalized_mainnodeid,
                                        local_road_degree_by_node_id=local_road_degree_by_node_id,
                                        semantic_mainnodeids=semantic_mainnodeids,
                                    )
                                    and _polygon_substantively_covers_node(
                                        virtual_polygon_geometry,
                                        node.geometry,
                                        cover_radius_m=max(resolution_m, 0.5),
                                    )
                                )
                            )
        # 只豁免当前语义路口的内部 roads。分支 roads 即使起点属于当前
        # 路口，也不能在 final foreign-road 审计中整条自动放行；否则
        # 会把延伸到其他语义路口的 road 一并视为“合法当前路口范围”。
        allowed_local_road_ids = set(internal_road_ids)
        if positive_nonmain_bridge_local_node_ids:
            allowed_positive_bridge_node_ids = {
                node_id
                for node_id in positive_nonmain_bridge_local_node_ids
                if (
                    node_id not in analysis_member_node_ids
                    and
                    local_node_by_id.get(node_id) is not None
                    and not _is_foreign_local_semantic_node(
                        node=local_node_by_id[node_id],
                        target_group_node_ids=analysis_member_node_ids,
                        normalized_mainnodeid=normalized_mainnodeid,
                        local_road_degree_by_node_id=local_road_degree_by_node_id,
                        semantic_mainnodeids=semantic_mainnodeids,
                    )
                )
            }
            allowed_local_road_ids.update(
                road.road_id
                for road in local_roads
                if (
                    road.snodeid in allowed_positive_bridge_node_ids
                    or road.enodeid in allowed_positive_bridge_node_ids
                )
            )
        covered_extra_local_road_ids = _covered_foreign_local_road_ids(
            polygon_geometry=virtual_polygon_geometry,
            local_roads=local_roads,
            local_nodes=local_nodes,
            allowed_road_ids=allowed_local_road_ids,
            target_group_node_ids=analysis_member_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            analysis_center=analysis_center,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        if covered_extra_local_road_ids:
            targeted_foreign_local_road_keep_focus_parts = [
                geometry
                for geometry in (
                    core_geometry,
                    *group_node_buffers,
                    *group_node_connectors,
                    *group_node_reinclude_geometries,
                    *selected_rc_node_buffers,
                    *selected_rc_node_connectors,
                )
                if geometry is not None and not geometry.is_empty
            ]
            targeted_foreign_local_road_keep_focus = (
                unary_union(targeted_foreign_local_road_keep_focus_parts)
                .buffer(max(resolution_m * 6.0, 2.0), join_style=1)
                .intersection(drivezone_union)
                if targeted_foreign_local_road_keep_focus_parts
                else GeometryCollection()
            )
            targeted_foreign_local_road_trim_keep_parts: list[BaseGeometry] = _restrict_keep_geometries_to_focus(
                [
                    *group_node_buffers,
                    *group_node_connectors,
                    *group_node_reinclude_geometries,
                    *branch_mandatory_support_geometries,
                    *selected_positive_rc_keep_geometries,
                    *positive_rc_connector_geometries,
                    *selected_rc_support_geometries,
                ],
                focus_geometry=targeted_foreign_local_road_keep_focus,
            )
            targeted_foreign_local_road_trim_keep_parts.extend(
                rc_node_by_id[node_id].geometry.buffer(
                    max(POLYGON_RC_NODE_BUFFER_M + 1.0, 3.0),
                    join_style=1,
                ).intersection(drivezone_union)
                for node_id in (validation_support_rc_node_ids | candidate_selected_rc_node_ids)
                if node_id in rc_node_by_id
            )
            targeted_foreign_local_road_trim_keep_geometry = (
                unary_union(targeted_foreign_local_road_trim_keep_parts)
                if targeted_foreign_local_road_trim_keep_parts
                else GeometryCollection()
            )
            targeted_foreign_local_road_trim_geometry = _build_targeted_foreign_local_road_trim_geometry(
                polygon_geometry=virtual_polygon_geometry,
                road_ids=set(covered_extra_local_road_ids),
                local_roads=local_roads,
                drivezone_union=drivezone_union,
                keep_geometry=targeted_foreign_local_road_trim_keep_geometry,
                local_nodes=local_nodes,
                target_group_node_ids=analysis_member_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                semantic_mainnodeids=semantic_mainnodeids,
                respect_keep_geometry_for_target_group_foreign_roads=True,
            )
            if not targeted_foreign_local_road_trim_geometry.is_empty:
                announce(
                    logger,
                    (
                        f"[T02-POC] targeted foreign road trim candidate mainnodeid={normalized_mainnodeid} "
                        f"extra_roads={','.join(covered_extra_local_road_ids)}"
                    ),
                )
                trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    targeted_foreign_local_road_trim_geometry
                ).intersection(drivezone_union)
                if group_node_reinclude_geometries:
                    trimmed_virtual_polygon_geometry = unary_union(
                        [trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                    ).intersection(drivezone_union)
                if not trimmed_virtual_polygon_geometry.is_empty:
                    trimmed_virtual_polygon_geometry = _fill_small_polygon_holes(
                        trimmed_virtual_polygon_geometry.buffer(0),
                        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                    )
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = trimmed_virtual_polygon_geometry.buffer(0).intersection(
                            drivezone_union
                        )
                (
                    trimmed_uncovered_group_node_ids,
                    trimmed_uncovered_support_rc_node_ids,
                    trimmed_uncovered_support_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=trimmed_virtual_polygon_geometry,
                    group_nodes=group_nodes,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=validation_support_rc_node_ids,
                    support_road_ids=validation_support_rc_road_ids,
                    support_clip=validation_support_clip,
                )
                (
                    trimmed_uncovered_support_rc_node_ids,
                    trimmed_uncovered_support_rc_road_ids,
                ) = _relax_targeted_foreign_trim_support_gaps(
                    uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                    uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_support_node_ids=candidate_selected_rc_node_ids,
                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                (
                    _trimmed_candidate_selected_group_node_ids,
                    trimmed_uncovered_candidate_selected_rc_node_ids,
                    trimmed_uncovered_candidate_selected_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=trimmed_virtual_polygon_geometry,
                    group_nodes=[],
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=candidate_selected_rc_node_ids,
                    support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    support_clip=validation_support_clip,
                )
                if (
                    not trimmed_uncovered_group_node_ids
                    and not trimmed_uncovered_support_rc_node_ids
                    and not trimmed_uncovered_support_rc_road_ids
                    and not trimmed_uncovered_candidate_selected_rc_node_ids
                    and not trimmed_uncovered_candidate_selected_rc_road_ids
                ):
                    announce(
                        logger,
                        (
                            f"[T02-POC] targeted foreign road trim applied mainnodeid={normalized_mainnodeid} "
                            f"extra_roads={','.join(covered_extra_local_road_ids)}"
                        ),
                    )
                    virtual_polygon_geometry = trimmed_virtual_polygon_geometry
                    covered_extra_local_road_ids = _covered_foreign_local_road_ids(
                        polygon_geometry=virtual_polygon_geometry,
                        local_roads=local_roads,
                        local_nodes=local_nodes,
                        allowed_road_ids=allowed_local_road_ids,
                        target_group_node_ids=analysis_member_node_ids,
                        normalized_mainnodeid=normalized_mainnodeid,
                        local_road_degree_by_node_id=local_road_degree_by_node_id,
                        analysis_center=analysis_center,
                        semantic_mainnodeids=semantic_mainnodeids,
                    )
                    polygon_cover = virtual_polygon_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
                    foreign_node_cover = virtual_polygon_geometry.buffer(max(resolution_m, 0.25))
                    covered_extra_local_node_ids = sorted(
                        node.node_id
                        for node in local_nodes
                        if (
                            _is_foreign_local_semantic_node(
                                node=node,
                                target_group_node_ids=analysis_member_node_ids,
                                normalized_mainnodeid=normalized_mainnodeid,
                                local_road_degree_by_node_id=local_road_degree_by_node_id,
                                semantic_mainnodeids=semantic_mainnodeids,
                            )
                            and _polygon_substantively_covers_node(
                                virtual_polygon_geometry,
                                node.geometry,
                                cover_radius_m=max(resolution_m, 0.5),
                            )
                        )
                    )
                    announce(
                        logger,
                        (
                            f"[T02-POC] targeted foreign road trim result mainnodeid={normalized_mainnodeid} "
                            f"remaining_extra_roads={','.join(covered_extra_local_road_ids)} "
                            f"remaining_extra_nodes={','.join(covered_extra_local_node_ids)}"
                        ),
                    )
                else:
                    announce(
                        logger,
                        (
                            f"[T02-POC] targeted foreign road trim discarded mainnodeid={normalized_mainnodeid} "
                            f"group_uncovered={','.join(sorted(trimmed_uncovered_group_node_ids)) or '-'} "
                            f"support_nodes={','.join(sorted(trimmed_uncovered_support_rc_node_ids)) or '-'} "
                            f"support_roads={','.join(sorted(trimmed_uncovered_support_rc_road_ids)) or '-'} "
                            f"candidate_selected_nodes={','.join(sorted(trimmed_uncovered_candidate_selected_rc_node_ids)) or '-'} "
                            f"candidate_selected_roads={','.join(sorted(trimmed_uncovered_candidate_selected_rc_road_ids)) or '-'}"
                        ),
                    )
        counts["covered_extra_local_node_count"] = len(covered_extra_local_node_ids)
        counts["covered_extra_local_road_count"] = len(covered_extra_local_road_ids)
        if covered_extra_local_node_ids or covered_extra_local_road_ids:
            if STATUS_NODE_COMPONENT_CONFLICT not in risks:
                risks.append(STATUS_NODE_COMPONENT_CONFLICT)
            audit_rows.append(
                _audit_row(
                    scope="virtual_intersection_poc",
                    status="warning",
                    reason=STATUS_NODE_COMPONENT_CONFLICT,
                    detail=(
                        f"mainnodeid='{normalized_mainnodeid}' polygon covers extra local node ids="
                        f"{','.join(covered_extra_local_node_ids) or '-'} and extra local road ids="
                        f"{','.join(covered_extra_local_road_ids) or '-'} beyond own-group / compact internal roads."
                    ),
                    mainnodeid=normalized_mainnodeid,
                    feature_id=(covered_extra_local_node_ids or covered_extra_local_road_ids)[0],
                )
            )
        record_stage("virtual_polygon_built")
        selected_positive_group_rc_road_ids = {
            road_id
            for group_id in positive_rc_groups
            for road_id in (rc_branch_by_id[group_id].road_ids if group_id in rc_branch_by_id else [])
        }
        selected_positive_rc_road_ids = (
            selected_positive_group_rc_road_ids | selected_rc_support_road_ids
        )
        if (
            not selected_positive_rc_road_ids
            and (representative_node.kind_2 or 0) == 4
            and not local_rc_nodes
            and positive_rc_groups
        ):
            selected_positive_rc_road_ids = {
                road_id
                for group_id in positive_rc_groups
                for road_id in (rc_branch_by_id[group_id].road_ids if group_id in rc_branch_by_id else [])
            }
        selected_rc_roads = [
            road
            for road in local_rc_roads
            if (
                road.road_id in selected_positive_rc_road_ids
                and (
                    road.geometry.intersects(virtual_polygon_geometry)
                    or road.road_id in selected_rc_support_road_ids
                    or (
                        (representative_node.kind_2 or 0) == 4
                        and not local_rc_nodes
                        and float(road.geometry.distance(virtual_polygon_geometry)) <= max(RC_ROAD_BUFFER_M * 1.2, 4.5)
                    )
                )
            )
        ]
        selected_output_clip = _build_associated_output_clip(
            analysis_center=analysis_center,
            group_nodes=group_nodes,
            local_rc_roads=local_rc_roads,
            local_rc_nodes=local_rc_nodes,
            support_road_ids=selected_positive_rc_road_ids,
            support_node_ids=polygon_support_rc_node_ids | selected_rc_support_node_ids,
        )
        selected_output_node_cover_geometry = selected_output_clip
        selected_output_cover = selected_output_node_cover_geometry.buffer(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M)
        selected_rc_endpoint_node_ids: set[str] = {
            node_id
            for road in selected_rc_roads
            for node_id in (road.snodeid, road.enodeid)
            if node_id in rc_node_by_id
        }
        selected_rc_node_ids: set[str] = {
            node.node_id
            for node in rc_group_nodes
            if selected_output_cover.covers(node.geometry)
        }
        selected_rc_node_ids.update(
            node_id
            for node_id in (polygon_support_rc_node_ids | selected_rc_support_node_ids)
            if node_id in rc_node_by_id and selected_output_cover.covers(rc_node_by_id[node_id].geometry)
        )
        for road in selected_rc_roads:
            for node_id in (road.snodeid, road.enodeid):
                node = rc_node_by_id.get(node_id)
                if node is not None and selected_output_cover.covers(node.geometry):
                    selected_rc_node_ids.add(node_id)
        enable_selected_rc_node_bridge_support = (
            (len(group_nodes) >= 2 or bool(positive_nonmain_bridge_local_node_ids))
            and not selected_rc_node_ids
        )
        enable_selected_rc_endpoint_bridge_support = not selected_rc_node_ids
        if enable_selected_rc_node_bridge_support or enable_selected_rc_endpoint_bridge_support:
            selected_output_extension_parts: list[BaseGeometry] = []
            selected_output_near_polygon = virtual_polygon_geometry.buffer(8.0)
            for road in selected_rc_roads:
                selected_road_on_polygon_length_m = float(
                    road.geometry.intersection(virtual_polygon_geometry).length
                )
                nearby_selected_road_geometry = road.geometry.intersection(selected_output_near_polygon)
                if not nearby_selected_road_geometry.is_empty and nearby_selected_road_geometry.length > 0.5:
                    selected_output_extension_parts.append(
                        nearby_selected_road_geometry.buffer(
                            max(RC_ROAD_BUFFER_M * 0.9, 2.0),
                            cap_style=2,
                            join_style=2,
                        ).intersection(drivezone_union)
                    )
                for node_id in (road.snodeid, road.enodeid):
                    node = rc_node_by_id.get(node_id)
                    if node is None:
                        continue
                    node_distance_to_polygon_m = float(node.geometry.distance(virtual_polygon_geometry))
                    if enable_selected_rc_node_bridge_support:
                        if node_distance_to_polygon_m > 12.0:
                            continue
                    elif not (
                        selected_road_on_polygon_length_m >= 16.0
                        and node.mainnodeid not in {None, "0"}
                        and node_distance_to_polygon_m <= 10.5
                    ):
                        continue
                    selected_output_extension_parts.append(
                        node.geometry.buffer(max(POLYGON_RC_NODE_BUFFER_M, 2.0)).intersection(drivezone_union)
                    )
                    nearest_polygon_point = nearest_points(node.geometry, virtual_polygon_geometry)[1]
                    selected_output_extension_parts.append(
                        LineString(
                            [
                                (float(node.geometry.x), float(node.geometry.y)),
                                (float(nearest_polygon_point.x), float(nearest_polygon_point.y)),
                            ]
                        ).buffer(
                            max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.55, 1.2),
                            cap_style=2,
                            join_style=2,
                        ).intersection(drivezone_union)
                    )
            selected_output_extension_parts = [
                geometry
                for geometry in selected_output_extension_parts
                if geometry is not None and not geometry.is_empty
            ]
            if selected_output_extension_parts:
                selected_output_node_cover_geometry = unary_union(
                    [selected_output_clip, *selected_output_extension_parts]
                ).intersection(drivezone_union)
                selected_output_cover = selected_output_node_cover_geometry.buffer(
                    POLYGON_SUPPORT_VALIDATION_TOLERANCE_M
                )
                selected_rc_node_ids = {
                    node.node_id
                    for node in rc_group_nodes
                    if selected_output_cover.covers(node.geometry)
                }
                selected_rc_node_ids.update(
                    node_id
                    for node_id in (polygon_support_rc_node_ids | selected_rc_support_node_ids)
                    if node_id in rc_node_by_id and selected_output_cover.covers(rc_node_by_id[node_id].geometry)
                )
                for road in selected_rc_roads:
                    for node_id in (road.snodeid, road.enodeid):
                        node = rc_node_by_id.get(node_id)
                        if node is not None and selected_output_cover.covers(node.geometry):
                            selected_rc_node_ids.add(node_id)
        selected_association_repair_geometries: list[BaseGeometry] = []
        if not selected_rc_roads and positive_rc_road_ids and STATUS_NO_VALID_RC_CONNECTION not in risks:
            risks.append(STATUS_NO_VALID_RC_CONNECTION)
        _, uncovered_selected_rc_node_ids, uncovered_selected_rc_road_ids = _validate_polygon_support(
            polygon_geometry=virtual_polygon_geometry,
            group_nodes=[],
            local_rc_nodes=local_rc_nodes,
            local_rc_roads=local_rc_roads,
            support_node_ids=selected_rc_node_ids,
            support_road_ids={road.road_id for road in selected_rc_roads},
            support_clip=selected_output_clip,
        )
        if uncovered_selected_rc_node_ids or uncovered_selected_rc_road_ids:
            if enable_selected_rc_node_bridge_support or enable_selected_rc_endpoint_bridge_support:
                for node in local_rc_nodes:
                    if node.node_id not in uncovered_selected_rc_node_ids:
                        continue
                    selected_association_repair_geometries.append(
                        node.geometry.buffer(max(POLYGON_RC_NODE_BUFFER_M + 0.6, 2.6)).intersection(drivezone_union)
                    )
                    nearest_polygon_point = nearest_points(node.geometry, virtual_polygon_geometry)[1]
                    selected_association_repair_geometries.append(
                        LineString(
                            [
                                (float(node.geometry.x), float(node.geometry.y)),
                                (float(nearest_polygon_point.x), float(nearest_polygon_point.y)),
                            ]
                        ).buffer(
                            max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.7, 1.6),
                            cap_style=2,
                            join_style=2,
                        ).intersection(drivezone_union)
                    )
                    nearby_local_nodes = sorted(
                        (
                            (float(local_node.geometry.distance(node.geometry)), local_node)
                            for local_node in local_nodes
                            if local_road_degree_by_node_id.get(local_node.node_id, 0) >= 2
                            and (
                                _is_supportable_local_node_for_rc_bridge(
                                    node=local_node,
                                    target_group_node_ids=analysis_member_node_ids,
                                    normalized_mainnodeid=normalized_mainnodeid,
                                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                                )
                                or local_node.node_id in positive_nonmain_bridge_local_node_ids
                            )
                            and float(local_node.geometry.distance(node.geometry)) <= 8.0
                        ),
                        key=lambda item: (item[0], float(item[1].geometry.distance(analysis_center))),
                    )[:3]
                    for _, local_node in nearby_local_nodes:
                        incident_local_roads = [
                            local_road
                            for local_road in local_roads
                            if local_road.snodeid == local_node.node_id or local_road.enodeid == local_node.node_id
                        ]
                        if len(incident_local_roads) < 2:
                            continue
                        node_degree = local_road_degree_by_node_id.get(local_node.node_id, 0)
                        local_road_clip = local_node.geometry.buffer(
                            13.0 if node_degree >= 3 else 11.0
                        ).intersection(drivezone_union)
                        if local_road_clip.is_empty:
                            continue
                        local_support_parts: list[BaseGeometry] = [
                            local_node.geometry.buffer(
                                max(POLYGON_GROUP_NODE_BUFFER_M * 0.85, 2.4)
                            ).intersection(drivezone_union),
                            LineString(
                                [
                                    (float(node.geometry.x), float(node.geometry.y)),
                                    (float(local_node.geometry.x), float(local_node.geometry.y)),
                                ]
                            ).buffer(
                                max(POLYGON_RC_NODE_CONNECTOR_HALF_WIDTH_M * 0.55, 1.2),
                                cap_style=2,
                                join_style=2,
                            ).intersection(drivezone_union),
                        ]
                        substantive_local_road_count = 0
                        for local_road in incident_local_roads:
                            local_road_geometry = local_road.geometry.intersection(local_road_clip)
                            if local_road_geometry.is_empty or local_road_geometry.length <= 0.5:
                                continue
                            substantive_local_road_count += 1
                            local_support_parts.append(
                                local_road_geometry.buffer(
                                    max(ROAD_BUFFER_M * 0.95, SIDE_BRANCH_HALF_WIDTH_M * 0.85),
                                    cap_style=2,
                                    join_style=2,
                                ).intersection(drivezone_union)
                            )
                        if substantive_local_road_count < 2:
                            continue
                        local_support_parts = [
                            geometry
                            for geometry in local_support_parts
                            if geometry is not None and not geometry.is_empty
                        ]
                        if not local_support_parts:
                            continue
                        selected_association_repair_geometries.append(
                            unary_union(local_support_parts).convex_hull.buffer(
                                max(1.0, SIDE_BRANCH_HALF_WIDTH_M * (0.36 if node_degree >= 3 else 0.32)),
                                join_style=1,
                            ).intersection(drivezone_union)
                        )
            for road in local_rc_roads:
                if road.road_id not in uncovered_selected_rc_road_ids:
                    continue
                selected_road_repair_geometry = road.geometry.intersection(
                    selected_output_node_cover_geometry.buffer(max(resolution_m, 0.4), join_style=1)
                )
                if selected_road_repair_geometry.is_empty or selected_road_repair_geometry.length <= 0.5:
                    continue
                selected_association_repair_geometries.append(
                    selected_road_repair_geometry.buffer(
                        max(RC_ROAD_BUFFER_M * 0.9, 2.0),
                        cap_style=2,
                        join_style=2,
                    ).intersection(drivezone_union)
                )
            selected_association_repair_geometries = [
                geometry
                for geometry in selected_association_repair_geometries
                if geometry is not None and not geometry.is_empty
            ]
            if selected_association_repair_geometries:
                repaired_virtual_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, *selected_association_repair_geometries]
                ).intersection(drivezone_union)
                if not repaired_virtual_polygon_geometry.is_empty:
                    repaired_virtual_polygon_geometry = _fill_small_polygon_holes(
                        repaired_virtual_polygon_geometry.buffer(0),
                        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
                    )
                candidate_virtual_polygon_geometry = repaired_virtual_polygon_geometry
                if not candidate_virtual_polygon_geometry.is_empty:
                    (
                        _candidate_uncovered_selected_group_node_ids,
                        candidate_uncovered_selected_rc_node_ids,
                        candidate_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=candidate_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                else:
                    candidate_uncovered_selected_rc_node_ids = uncovered_selected_rc_node_ids
                    candidate_uncovered_selected_rc_road_ids = uncovered_selected_rc_road_ids
                if (
                    candidate_virtual_polygon_geometry.is_empty
                    or candidate_uncovered_selected_rc_node_ids
                    or candidate_uncovered_selected_rc_road_ids
                ):
                    candidate_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=repaired_virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
                    (
                        _candidate_uncovered_selected_group_node_ids,
                        candidate_uncovered_selected_rc_node_ids,
                        candidate_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=candidate_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                selected_output_hard_cap_focus_parts = [
                    geometry
                    for geometry in (
                        core_geometry,
                        *group_node_buffers,
                        *group_node_connectors,
                        *group_node_reinclude_geometries,
                        *selected_rc_node_buffers,
                        *selected_rc_node_connectors,
                        selected_output_node_cover_geometry,
                    )
                    if geometry is not None and not geometry.is_empty
                ]
                selected_output_hard_cap_focus = (
                    unary_union(selected_output_hard_cap_focus_parts)
                    .buffer(max(resolution_m * 6.0, 2.0), join_style=1)
                    .intersection(drivezone_union)
                    if selected_output_hard_cap_focus_parts
                    else GeometryCollection()
                )
                selected_output_hard_cap_exclusion_geometry = (
                    _build_semantic_branch_hard_cap_exclusion_geometry(
                        analysis_center=analysis_center,
                        road_branches=road_branches,
                        drivezone_union=drivezone_union,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        hard_keep_geometries=[
                            core_geometry,
                            *group_node_buffers,
                            *group_node_connectors,
                            *group_node_reinclude_geometries,
                            *selected_rc_node_buffers,
                            *selected_rc_node_connectors,
                            *_restrict_keep_geometries_to_focus(
                                selected_positive_rc_keep_geometries,
                                focus_geometry=selected_output_hard_cap_focus,
                            ),
                            *_restrict_keep_geometries_to_focus(
                                positive_rc_connector_geometries,
                                focus_geometry=selected_output_hard_cap_focus,
                            ),
                            *_restrict_keep_geometries_to_focus(
                                selected_rc_support_geometries,
                                focus_geometry=selected_output_hard_cap_focus,
                            ),
                            selected_output_node_cover_geometry,
                            *_restrict_keep_geometries_to_focus(
                                selected_association_repair_geometries,
                                focus_geometry=selected_output_hard_cap_focus,
                            ),
                        ],
                    )
                )
                if (
                    not candidate_virtual_polygon_geometry.is_empty
                    and not selected_output_hard_cap_exclusion_geometry.is_empty
                ):
                    candidate_virtual_polygon_geometry = candidate_virtual_polygon_geometry.difference(
                        selected_output_hard_cap_exclusion_geometry
                    ).intersection(drivezone_union)
                    if group_node_reinclude_geometries:
                        candidate_virtual_polygon_geometry = unary_union(
                            [candidate_virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not candidate_virtual_polygon_geometry.is_empty:
                        candidate_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=candidate_virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        _candidate_uncovered_selected_group_node_ids,
                        candidate_uncovered_selected_rc_node_ids,
                        candidate_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=candidate_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                if not candidate_virtual_polygon_geometry.is_empty:
                    virtual_polygon_geometry = candidate_virtual_polygon_geometry
                uncovered_selected_rc_node_ids = candidate_uncovered_selected_rc_node_ids
                uncovered_selected_rc_road_ids = candidate_uncovered_selected_rc_road_ids
        if not virtual_polygon_geometry.is_empty:
            post_selected_foreign_core_keep_geometry = rc_foreign_keep_geometry
            if not selected_output_node_cover_geometry.is_empty:
                if post_selected_foreign_core_keep_geometry.is_empty:
                    post_selected_foreign_core_keep_geometry = selected_output_node_cover_geometry
                else:
                    post_selected_foreign_core_keep_geometry = unary_union(
                        [post_selected_foreign_core_keep_geometry, selected_output_node_cover_geometry]
                    )
            post_selected_foreign_local_junction_node_core_exclusion_geometry = (
                _build_foreign_local_junction_node_core_exclusion_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    analysis_center=analysis_center,
                    normalized_mainnodeid=normalized_mainnodeid,
                    group_nodes=group_nodes,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    keep_geometry=post_selected_foreign_core_keep_geometry,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
            )
            if not post_selected_foreign_local_junction_node_core_exclusion_geometry.is_empty:
                virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    post_selected_foreign_local_junction_node_core_exclusion_geometry
                ).intersection(drivezone_union)
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
            (
                _post_selected_group_node_ids,
                uncovered_selected_rc_node_ids,
                uncovered_selected_rc_road_ids,
            ) = _validate_polygon_support(
                polygon_geometry=virtual_polygon_geometry,
                group_nodes=[],
                local_rc_nodes=local_rc_nodes,
                local_rc_roads=local_rc_roads,
                support_node_ids=selected_rc_node_ids,
                support_road_ids={road.road_id for road in selected_rc_roads},
                support_clip=selected_output_clip,
            )
        post_selected_trim_keep_parts: list[BaseGeometry] = [
            geometry
            for geometry in (
                core_geometry,
                *group_node_buffers,
                *group_node_connectors,
                *group_node_reinclude_geometries,
            )
            if geometry is not None and not geometry.is_empty
        ]
        if not selected_output_node_cover_geometry.is_empty:
            post_selected_trim_keep_parts.append(selected_output_node_cover_geometry)
        post_selected_trim_keep_geometry = (
            unary_union(post_selected_trim_keep_parts)
            if post_selected_trim_keep_parts
            else GeometryCollection()
        )
        if not virtual_polygon_geometry.is_empty:
            post_selected_covered_extra_local_node_ids = sorted(
                node.node_id
                for node in local_nodes
                if (
                    _is_foreign_local_semantic_node(
                        node=node,
                        target_group_node_ids=analysis_member_node_ids,
                        normalized_mainnodeid=normalized_mainnodeid,
                        local_road_degree_by_node_id=local_road_degree_by_node_id,
                        semantic_mainnodeids=semantic_mainnodeids,
                    )
                    and _polygon_substantively_covers_node(
                        virtual_polygon_geometry,
                        node.geometry,
                        cover_radius_m=max(resolution_m, 0.5),
                    )
                )
            )
            if post_selected_covered_extra_local_node_ids:
                announce(
                    logger,
                    (
                        f"[T02-POC] post-selected foreign semantic trim candidate mainnodeid={normalized_mainnodeid} "
                        f"extra_nodes={','.join(post_selected_covered_extra_local_node_ids)}"
                    ),
                )
                targeted_foreign_semantic_core_trim_geometry = (
                    _build_targeted_foreign_semantic_node_core_trim_geometry(
                        node_ids=set(post_selected_covered_extra_local_node_ids),
                        local_nodes=local_nodes,
                        local_roads=local_roads,
                        drivezone_union=drivezone_union,
                        keep_geometry=None,
                    )
                )
                if not targeted_foreign_semantic_core_trim_geometry.is_empty:
                    trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                        targeted_foreign_semantic_core_trim_geometry
                    ).intersection(drivezone_union)
                    if group_node_reinclude_geometries:
                        trimmed_virtual_polygon_geometry = unary_union(
                            [trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=trimmed_virtual_polygon_geometry.buffer(0),
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        trimmed_uncovered_group_node_ids,
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=group_nodes,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=validation_support_rc_node_ids,
                        support_road_ids=validation_support_rc_road_ids,
                        support_clip=validation_support_clip,
                    )
                    (
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_support_gaps(
                        uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                        uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_support_node_ids=candidate_selected_rc_node_ids,
                        hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    (
                        _trimmed_selected_group_node_ids,
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                    (
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_selected_gaps(
                        uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                        uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=None,
                        hard_selected_node_ids=selected_rc_endpoint_node_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        selected_node_repair_geometries = _build_uncovered_selected_rc_node_repair_geometries(
                            uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                            current_polygon_geometry=trimmed_virtual_polygon_geometry,
                            local_rc_nodes=local_rc_nodes,
                            drivezone_union=drivezone_union,
                        )
                        if selected_node_repair_geometries:
                            trimmed_virtual_polygon_geometry = unary_union(
                                [trimmed_virtual_polygon_geometry, *selected_node_repair_geometries]
                            ).intersection(drivezone_union)
                            if not trimmed_virtual_polygon_geometry.is_empty:
                                trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                                    geometry=trimmed_virtual_polygon_geometry,
                                    drivezone_union=drivezone_union,
                                    seed_geometry=core_geometry,
                                )
                            (
                                _trimmed_selected_group_node_ids,
                                trimmed_uncovered_selected_rc_node_ids,
                                trimmed_uncovered_selected_rc_road_ids,
                            ) = _validate_polygon_support(
                                polygon_geometry=trimmed_virtual_polygon_geometry,
                                group_nodes=[],
                                local_rc_nodes=local_rc_nodes,
                                local_rc_roads=local_rc_roads,
                                support_node_ids=selected_rc_node_ids,
                                support_road_ids={road.road_id for road in selected_rc_roads},
                                support_clip=selected_output_clip,
                            )
                            (
                                trimmed_uncovered_selected_rc_node_ids,
                                trimmed_uncovered_selected_rc_road_ids,
                            ) = _relax_targeted_foreign_trim_selected_gaps(
                                uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                                uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                                rc_node_by_id=rc_node_by_id,
                                rc_road_by_id=rc_road_by_id,
                                analysis_center=None,
                                hard_selected_node_ids=selected_rc_endpoint_node_ids,
                                relax_node_ids=conflict_excluded_rc_node_ids,
                                relax_road_ids=conflict_excluded_rc_road_ids,
                            )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and not trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        announce(
                            logger,
                            (
                                f"[T02-POC] post-selected foreign semantic trim applied mainnodeid={normalized_mainnodeid} "
                                f"extra_nodes={','.join(post_selected_covered_extra_local_node_ids)}"
                            ),
                        )
                        virtual_polygon_geometry = trimmed_virtual_polygon_geometry
                        uncovered_selected_rc_node_ids = []
                        uncovered_selected_rc_road_ids = []
                    else:
                        announce(
                            logger,
                            (
                                f"[T02-POC] post-selected foreign semantic trim discarded mainnodeid={normalized_mainnodeid} "
                                f"group_uncovered={','.join(sorted(trimmed_uncovered_group_node_ids)) or '-'} "
                                f"support_nodes={','.join(sorted(trimmed_uncovered_support_rc_node_ids)) or '-'} "
                                f"support_roads={','.join(sorted(trimmed_uncovered_support_rc_road_ids)) or '-'} "
                                f"selected_nodes={','.join(sorted(trimmed_uncovered_selected_rc_node_ids)) or '-'} "
                                f"selected_roads={','.join(sorted(trimmed_uncovered_selected_rc_road_ids)) or '-'}"
                            ),
                        )
        if not virtual_polygon_geometry.is_empty:
            post_selected_covered_extra_local_road_ids = _covered_foreign_local_road_ids(
                polygon_geometry=virtual_polygon_geometry,
                local_roads=local_roads,
                local_nodes=local_nodes,
                allowed_road_ids=allowed_local_road_ids,
                target_group_node_ids=analysis_member_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                analysis_center=analysis_center,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            if post_selected_covered_extra_local_road_ids:
                announce(
                    logger,
                    (
                        f"[T02-POC] post-selected foreign road trim candidate mainnodeid={normalized_mainnodeid} "
                        f"extra_roads={','.join(post_selected_covered_extra_local_road_ids)}"
                    ),
                )
                post_selected_foreign_road_keep_focus = (
                    post_selected_trim_keep_geometry.buffer(
                        max(resolution_m * 6.0, 2.0),
                        join_style=1,
                    ).intersection(drivezone_union)
                    if not post_selected_trim_keep_geometry.is_empty
                    else GeometryCollection()
                )
                post_selected_foreign_road_keep_parts = [
                    geometry
                    for geometry in (
                        post_selected_foreign_core_keep_geometry,
                        *[
                            geometry.intersection(post_selected_foreign_road_keep_focus)
                            if not post_selected_foreign_road_keep_focus.is_empty
                            else geometry
                            for geometry in branch_mandatory_support_geometries
                        ],
                        *[
                            geometry.intersection(post_selected_foreign_road_keep_focus)
                            if not post_selected_foreign_road_keep_focus.is_empty
                            else geometry
                            for geometry in selected_rc_support_geometries
                        ],
                        *[
                            geometry.intersection(post_selected_foreign_road_keep_focus)
                            if not post_selected_foreign_road_keep_focus.is_empty
                            else geometry
                            for geometry in selected_association_repair_geometries
                        ],
                    )
                    if geometry is not None and not geometry.is_empty
                ]
                post_selected_foreign_road_keep_geometry = (
                    unary_union(post_selected_foreign_road_keep_parts)
                    if post_selected_foreign_road_keep_parts
                    else None
                )
                post_selected_foreign_local_road_trim_geometry = _build_targeted_foreign_local_road_trim_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    road_ids=set(post_selected_covered_extra_local_road_ids),
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    keep_geometry=post_selected_foreign_road_keep_geometry,
                    local_nodes=local_nodes,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                    respect_keep_geometry_for_target_group_foreign_roads=True,
                )
                if not post_selected_foreign_local_road_trim_geometry.is_empty:
                    trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                        post_selected_foreign_local_road_trim_geometry
                    ).intersection(drivezone_union)
                    if group_node_reinclude_geometries:
                        trimmed_virtual_polygon_geometry = unary_union(
                            [trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=trimmed_virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        trimmed_uncovered_group_node_ids,
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=group_nodes,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=validation_support_rc_node_ids,
                        support_road_ids=validation_support_rc_road_ids,
                        support_clip=validation_support_clip,
                    )
                    (
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_support_gaps(
                        uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                        uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_support_node_ids=candidate_selected_rc_node_ids,
                        hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    )
                    (
                        _trimmed_selected_group_node_ids,
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                    (
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_selected_gaps(
                        uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                        uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_selected_node_ids=selected_rc_endpoint_node_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        selected_node_repair_geometries = _build_uncovered_selected_rc_node_repair_geometries(
                            uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                            current_polygon_geometry=trimmed_virtual_polygon_geometry,
                            local_rc_nodes=local_rc_nodes,
                            drivezone_union=drivezone_union,
                        )
                        if selected_node_repair_geometries:
                            trimmed_virtual_polygon_geometry = unary_union(
                                [trimmed_virtual_polygon_geometry, *selected_node_repair_geometries]
                            ).intersection(drivezone_union)
                            if not trimmed_virtual_polygon_geometry.is_empty:
                                trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                                    geometry=trimmed_virtual_polygon_geometry,
                                    drivezone_union=drivezone_union,
                                    seed_geometry=core_geometry,
                                )
                            (
                                _trimmed_selected_group_node_ids,
                                trimmed_uncovered_selected_rc_node_ids,
                                trimmed_uncovered_selected_rc_road_ids,
                            ) = _validate_polygon_support(
                                polygon_geometry=trimmed_virtual_polygon_geometry,
                                group_nodes=[],
                                local_rc_nodes=local_rc_nodes,
                                local_rc_roads=local_rc_roads,
                                support_node_ids=selected_rc_node_ids,
                                support_road_ids={road.road_id for road in selected_rc_roads},
                                support_clip=selected_output_clip,
                            )
                            (
                                trimmed_uncovered_selected_rc_node_ids,
                                trimmed_uncovered_selected_rc_road_ids,
                            ) = _relax_targeted_foreign_trim_selected_gaps(
                                uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                                uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                                rc_node_by_id=rc_node_by_id,
                                rc_road_by_id=rc_road_by_id,
                                analysis_center=analysis_center,
                                hard_selected_node_ids=selected_rc_endpoint_node_ids,
                                relax_node_ids=conflict_excluded_rc_node_ids,
                                relax_road_ids=conflict_excluded_rc_road_ids,
                            )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and not trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        announce(
                            logger,
                            (
                                f"[T02-POC] post-selected foreign road trim applied mainnodeid={normalized_mainnodeid} "
                                f"extra_roads={','.join(post_selected_covered_extra_local_road_ids)}"
                            ),
                        )
                        virtual_polygon_geometry = trimmed_virtual_polygon_geometry
                        uncovered_selected_rc_node_ids = []
                        uncovered_selected_rc_road_ids = []
                    else:
                        announce(
                            logger,
                            (
                                f"[T02-POC] post-selected foreign road trim discarded mainnodeid={normalized_mainnodeid} "
                                f"group_uncovered={','.join(sorted(trimmed_uncovered_group_node_ids)) or '-'} "
                                f"support_nodes={','.join(sorted(trimmed_uncovered_support_rc_node_ids)) or '-'} "
                                f"support_roads={','.join(sorted(trimmed_uncovered_support_rc_road_ids)) or '-'} "
                                f"selected_nodes={','.join(sorted(trimmed_uncovered_selected_rc_node_ids)) or '-'} "
                                f"selected_roads={','.join(sorted(trimmed_uncovered_selected_rc_road_ids)) or '-'}"
                            ),
                        )
        if not virtual_polygon_geometry.is_empty:
            final_semantic_branch_hard_cap_keep_focus = (
                post_selected_trim_keep_geometry.buffer(
                    max(resolution_m * 4.0, 1.5),
                    join_style=1,
                ).intersection(drivezone_union)
                if not post_selected_trim_keep_geometry.is_empty
                else GeometryCollection()
            )
            final_semantic_branch_hard_cap_keep_parts = [
                geometry
                for geometry in (
                    core_geometry,
                    *group_node_buffers,
                    *group_node_connectors,
                    *group_node_reinclude_geometries,
                    *_restrict_keep_geometries_to_focus(
                        selected_rc_node_buffers,
                        focus_geometry=final_semantic_branch_hard_cap_keep_focus,
                    ),
                    *_restrict_keep_geometries_to_focus(
                        selected_rc_node_connectors,
                        focus_geometry=final_semantic_branch_hard_cap_keep_focus,
                    ),
                )
                if geometry is not None and not geometry.is_empty
            ]
            final_semantic_branch_hard_cap_exclusion_geometry = (
                _build_semantic_branch_hard_cap_exclusion_geometry(
                    analysis_center=analysis_center,
                    road_branches=road_branches,
                    drivezone_union=drivezone_union,
                    patch_size_m=patch_size_m,
                    resolution_m=resolution_m,
                    hard_keep_geometries=final_semantic_branch_hard_cap_keep_parts,
                )
            )
            if not final_semantic_branch_hard_cap_exclusion_geometry.is_empty:
                capped_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                    final_semantic_branch_hard_cap_exclusion_geometry
                ).intersection(drivezone_union)
                if group_node_reinclude_geometries:
                    capped_virtual_polygon_geometry = unary_union(
                        [capped_virtual_polygon_geometry, *group_node_reinclude_geometries]
                    ).intersection(drivezone_union)
                if not capped_virtual_polygon_geometry.is_empty:
                    capped_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=capped_virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
                (
                    capped_uncovered_group_node_ids,
                    capped_uncovered_support_rc_node_ids,
                    capped_uncovered_support_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=capped_virtual_polygon_geometry,
                    group_nodes=group_nodes,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=validation_support_rc_node_ids,
                    support_road_ids=validation_support_rc_road_ids,
                    support_clip=validation_support_clip,
                )
                (
                    capped_uncovered_support_rc_node_ids,
                    capped_uncovered_support_rc_road_ids,
                ) = _relax_targeted_foreign_trim_support_gaps(
                    uncovered_support_node_ids=capped_uncovered_support_rc_node_ids,
                    uncovered_support_road_ids=capped_uncovered_support_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_support_node_ids=candidate_selected_rc_node_ids,
                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                (
                    _capped_selected_group_node_ids,
                    capped_uncovered_selected_rc_node_ids,
                    capped_uncovered_selected_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=capped_virtual_polygon_geometry,
                    group_nodes=[],
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=selected_rc_node_ids,
                    support_road_ids={road.road_id for road in selected_rc_roads},
                    support_clip=selected_output_clip,
                )
                (
                    capped_uncovered_selected_rc_node_ids,
                    capped_uncovered_selected_rc_road_ids,
                ) = _relax_targeted_foreign_trim_selected_gaps(
                    uncovered_selected_node_ids=capped_uncovered_selected_rc_node_ids,
                    uncovered_selected_road_ids=capped_uncovered_selected_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_selected_node_ids=selected_rc_endpoint_node_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                if (
                    not capped_uncovered_group_node_ids
                    and not capped_uncovered_support_rc_node_ids
                    and not capped_uncovered_support_rc_road_ids
                    and not capped_uncovered_selected_rc_node_ids
                    and not capped_uncovered_selected_rc_road_ids
                ):
                    virtual_polygon_geometry = capped_virtual_polygon_geometry
                    uncovered_selected_rc_node_ids = []
                    uncovered_selected_rc_road_ids = []
        if uncovered_selected_rc_node_ids or uncovered_selected_rc_road_ids:
            (
                uncovered_selected_rc_node_ids,
                uncovered_selected_rc_road_ids,
            ) = _relax_targeted_foreign_trim_selected_gaps(
                uncovered_selected_node_ids=uncovered_selected_rc_node_ids,
                uncovered_selected_road_ids=uncovered_selected_rc_road_ids,
                rc_node_by_id=rc_node_by_id,
                rc_road_by_id=rc_road_by_id,
                analysis_center=analysis_center,
                hard_selected_node_ids=selected_rc_endpoint_node_ids,
                relax_node_ids=conflict_excluded_rc_node_ids,
                relax_road_ids=conflict_excluded_rc_road_ids,
            )
        if (
            uncovered_selected_rc_node_ids
            and not uncovered_selected_rc_road_ids
            and not virtual_polygon_geometry.is_empty
        ):
            final_selected_node_repair_geometries = _build_uncovered_selected_rc_node_repair_geometries(
                uncovered_selected_node_ids=uncovered_selected_rc_node_ids,
                current_polygon_geometry=virtual_polygon_geometry,
                local_rc_nodes=local_rc_nodes,
                drivezone_union=drivezone_union,
            )
            if final_selected_node_repair_geometries:
                repaired_virtual_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, *final_selected_node_repair_geometries]
                ).intersection(drivezone_union)
                if group_node_reinclude_geometries:
                    repaired_virtual_polygon_geometry = unary_union(
                        [repaired_virtual_polygon_geometry, *group_node_reinclude_geometries]
                    ).intersection(drivezone_union)
                if not repaired_virtual_polygon_geometry.is_empty:
                    repaired_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=repaired_virtual_polygon_geometry,
                        drivezone_union=drivezone_union,
                        seed_geometry=core_geometry,
                    )
                (
                    repaired_uncovered_group_node_ids,
                    repaired_uncovered_support_rc_node_ids,
                    repaired_uncovered_support_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=repaired_virtual_polygon_geometry,
                    group_nodes=group_nodes,
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=validation_support_rc_node_ids,
                    support_road_ids=validation_support_rc_road_ids,
                    support_clip=validation_support_clip,
                )
                (
                    repaired_uncovered_support_rc_node_ids,
                    repaired_uncovered_support_rc_road_ids,
                ) = _relax_targeted_foreign_trim_support_gaps(
                    uncovered_support_node_ids=repaired_uncovered_support_rc_node_ids,
                    uncovered_support_road_ids=repaired_uncovered_support_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_support_node_ids=candidate_selected_rc_node_ids,
                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                (
                    _repaired_selected_group_node_ids,
                    repaired_uncovered_selected_rc_node_ids,
                    repaired_uncovered_selected_rc_road_ids,
                ) = _validate_polygon_support(
                    polygon_geometry=repaired_virtual_polygon_geometry,
                    group_nodes=[],
                    local_rc_nodes=local_rc_nodes,
                    local_rc_roads=local_rc_roads,
                    support_node_ids=selected_rc_node_ids,
                    support_road_ids={road.road_id for road in selected_rc_roads},
                    support_clip=selected_output_clip,
                )
                (
                    repaired_uncovered_selected_rc_node_ids,
                    repaired_uncovered_selected_rc_road_ids,
                ) = _relax_targeted_foreign_trim_selected_gaps(
                    uncovered_selected_node_ids=repaired_uncovered_selected_rc_node_ids,
                    uncovered_selected_road_ids=repaired_uncovered_selected_rc_road_ids,
                    rc_node_by_id=rc_node_by_id,
                    rc_road_by_id=rc_road_by_id,
                    analysis_center=analysis_center,
                    hard_selected_node_ids=selected_rc_endpoint_node_ids,
                    relax_node_ids=conflict_excluded_rc_node_ids,
                    relax_road_ids=conflict_excluded_rc_road_ids,
                )
                if (
                    not repaired_uncovered_group_node_ids
                    and not repaired_uncovered_support_rc_node_ids
                    and not repaired_uncovered_support_rc_road_ids
                    and not repaired_uncovered_selected_rc_node_ids
                    and not repaired_uncovered_selected_rc_road_ids
                ):
                    virtual_polygon_geometry = repaired_virtual_polygon_geometry
                    uncovered_selected_rc_node_ids = []
                    uncovered_selected_rc_road_ids = []
        if uncovered_selected_rc_node_ids or uncovered_selected_rc_road_ids:
            detail_parts: list[str] = []
            if uncovered_selected_rc_node_ids:
                detail_parts.append(f"selected_rcsdnode={','.join(sorted(uncovered_selected_rc_node_ids))}")
            if uncovered_selected_rc_road_ids:
                detail_parts.append(f"selected_rcsdroad={','.join(sorted(uncovered_selected_rc_road_ids))}")
            raise VirtualIntersectionPocError(
                REASON_ANCHOR_SUPPORT_CONFLICT,
                (
                    f"mainnodeid='{normalized_mainnodeid}' selected association coverage failed: "
                    + "; ".join(detail_parts)
                ),
            )
        if not virtual_polygon_geometry.is_empty:
            point_covered_foreign_local_node_ids = sorted(
                node.node_id
                for node in local_nodes
                if (
                    _is_foreign_local_semantic_node(
                        node=node,
                        target_group_node_ids=analysis_member_node_ids,
                        normalized_mainnodeid=normalized_mainnodeid,
                        local_road_degree_by_node_id=local_road_degree_by_node_id,
                        semantic_mainnodeids=semantic_mainnodeids,
                    )
                    and virtual_polygon_geometry.buffer(max(resolution_m, 0.2)).covers(node.geometry)
                )
            )
            if point_covered_foreign_local_node_ids:
                point_trim_geometry = unary_union(
                    [
                        local_node_by_id[node_id].geometry.buffer(max(resolution_m, 0.8)).intersection(drivezone_union)
                        for node_id in point_covered_foreign_local_node_ids
                        if node_id in local_node_by_id
                    ]
                )
                if not point_trim_geometry.is_empty:
                    trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                        point_trim_geometry
                    ).intersection(drivezone_union)
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=trimmed_virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        trimmed_uncovered_group_node_ids,
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=group_nodes,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=validation_support_rc_node_ids,
                        support_road_ids=validation_support_rc_road_ids,
                        support_clip=validation_support_clip,
                    )
                    (
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_support_gaps(
                        uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                        uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_support_node_ids=candidate_selected_rc_node_ids,
                        hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    (
                        _trimmed_selected_group_node_ids,
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                    (
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_selected_gaps(
                        uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                        uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_selected_node_ids=selected_rc_endpoint_node_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and not trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        virtual_polygon_geometry = trimmed_virtual_polygon_geometry
        if not virtual_polygon_geometry.is_empty:
            selected_partial_local_branch_repair_geometries = (
                _build_selected_partial_local_branch_repair_geometries(
                    polygon_geometry=virtual_polygon_geometry,
                    analysis_center=analysis_center,
                    road_branches=road_branches,
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                )
            )
            if selected_partial_local_branch_repair_geometries:
                virtual_polygon_geometry = unary_union(
                    [virtual_polygon_geometry, *selected_partial_local_branch_repair_geometries]
                ).intersection(drivezone_union)
                virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                    geometry=virtual_polygon_geometry,
                    drivezone_union=drivezone_union,
                    seed_geometry=core_geometry,
                )
        if not virtual_polygon_geometry.is_empty:
            final_covered_extra_local_road_ids = _covered_foreign_local_road_ids(
                polygon_geometry=virtual_polygon_geometry,
                local_roads=local_roads,
                local_nodes=local_nodes,
                allowed_road_ids=allowed_local_road_ids,
                target_group_node_ids=analysis_member_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                analysis_center=analysis_center,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            if final_covered_extra_local_road_ids:
                announce(
                    logger,
                    (
                        f"[T02-POC] final foreign road trim candidate mainnodeid={normalized_mainnodeid} "
                        f"extra_roads={','.join(final_covered_extra_local_road_ids)}"
                    ),
                )
                final_foreign_road_keep_focus = (
                    post_selected_trim_keep_geometry.buffer(
                        max(resolution_m * 3.0, 1.0),
                        join_style=1,
                    ).intersection(drivezone_union)
                    if not post_selected_trim_keep_geometry.is_empty
                    else GeometryCollection()
                )
                final_foreign_road_keep_parts = [
                    geometry
                    for geometry in (
                        *group_node_buffers,
                        *group_node_connectors,
                        *group_node_reinclude_geometries,
                        *_restrict_keep_geometries_to_focus(
                            selected_rc_node_buffers,
                            focus_geometry=final_foreign_road_keep_focus,
                        ),
                        *_restrict_keep_geometries_to_focus(
                            selected_rc_node_connectors,
                            focus_geometry=final_foreign_road_keep_focus,
                        ),
                    )
                    if geometry is not None and not geometry.is_empty
                ]
                final_foreign_road_keep_geometry = (
                    unary_union(final_foreign_road_keep_parts)
                    if final_foreign_road_keep_parts
                    else None
                )
                final_foreign_local_road_trim_geometry = _build_targeted_foreign_local_road_trim_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    road_ids=set(final_covered_extra_local_road_ids),
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    keep_geometry=final_foreign_road_keep_geometry,
                    local_nodes=local_nodes,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                    respect_keep_geometry_for_target_group_foreign_roads=True,
                )
                if final_foreign_local_road_trim_geometry.is_empty:
                    announce(
                        logger,
                        (
                            f"[T02-POC] final foreign road trim empty mainnodeid={normalized_mainnodeid} "
                            f"extra_roads={','.join(final_covered_extra_local_road_ids)}"
                        ),
                    )
                else:
                    trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                        final_foreign_local_road_trim_geometry
                    ).intersection(drivezone_union)
                    if group_node_reinclude_geometries:
                        trimmed_virtual_polygon_geometry = unary_union(
                            [trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=trimmed_virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        trimmed_uncovered_group_node_ids,
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=group_nodes,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=validation_support_rc_node_ids,
                        support_road_ids=validation_support_rc_road_ids,
                        support_clip=validation_support_clip,
                    )
                    (
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_support_gaps(
                        uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                        uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_support_node_ids=candidate_selected_rc_node_ids,
                        hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    (
                        _trimmed_selected_group_node_ids,
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                    (
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_selected_gaps(
                        uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                        uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_selected_node_ids=selected_rc_endpoint_node_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and not trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        announce(
                            logger,
                            (
                                f"[T02-POC] final foreign road trim applied mainnodeid={normalized_mainnodeid} "
                                f"extra_roads={','.join(final_covered_extra_local_road_ids)}"
                            ),
                        )
                        virtual_polygon_geometry = trimmed_virtual_polygon_geometry
                    else:
                        announce(
                            logger,
                            (
                                f"[T02-POC] final foreign road trim discarded mainnodeid={normalized_mainnodeid} "
                                f"group_uncovered={','.join(sorted(trimmed_uncovered_group_node_ids)) or '-'} "
                                f"support_nodes={','.join(sorted(trimmed_uncovered_support_rc_node_ids)) or '-'} "
                                f"support_roads={','.join(sorted(trimmed_uncovered_support_rc_road_ids)) or '-'} "
                                f"selected_nodes={','.join(sorted(trimmed_uncovered_selected_rc_node_ids)) or '-'} "
                                f"selected_roads={','.join(sorted(trimmed_uncovered_selected_rc_road_ids)) or '-'}"
                            ),
                        )
        if not virtual_polygon_geometry.is_empty:
            residual_target_group_foreign_road_ids = _covered_foreign_local_road_ids(
                polygon_geometry=virtual_polygon_geometry,
                local_roads=local_roads,
                local_nodes=local_nodes,
                allowed_road_ids=allowed_local_road_ids,
                target_group_node_ids=analysis_member_node_ids,
                normalized_mainnodeid=normalized_mainnodeid,
                local_road_degree_by_node_id=local_road_degree_by_node_id,
                analysis_center=analysis_center,
                semantic_mainnodeids=semantic_mainnodeids,
            )
            if residual_target_group_foreign_road_ids:
                announce(
                    logger,
                    (
                        f"[T02-POC] residual foreign road hard-trim candidate mainnodeid={normalized_mainnodeid} "
                        f"extra_roads={','.join(residual_target_group_foreign_road_ids)}"
                    ),
                )
                residual_hard_keep_parts = [
                    geometry
                    for geometry in (
                        *group_node_buffers,
                        *group_node_connectors,
                        *group_node_reinclude_geometries,
                    )
                    if geometry is not None and not geometry.is_empty
                ]
                residual_hard_keep_geometry = (
                    unary_union(residual_hard_keep_parts)
                    if residual_hard_keep_parts
                    else None
                )
                residual_foreign_local_road_trim_geometry = _build_targeted_foreign_local_road_trim_geometry(
                    polygon_geometry=virtual_polygon_geometry,
                    road_ids=set(residual_target_group_foreign_road_ids),
                    local_roads=local_roads,
                    drivezone_union=drivezone_union,
                    keep_geometry=residual_hard_keep_geometry,
                    local_nodes=local_nodes,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                    respect_keep_geometry_for_target_group_foreign_roads=False,
                )
                if residual_foreign_local_road_trim_geometry.is_empty:
                    announce(
                        logger,
                        (
                            f"[T02-POC] residual foreign road hard-trim empty mainnodeid={normalized_mainnodeid} "
                            f"extra_roads={','.join(residual_target_group_foreign_road_ids)}"
                        ),
                    )
                else:
                    trimmed_virtual_polygon_geometry = virtual_polygon_geometry.difference(
                        residual_foreign_local_road_trim_geometry
                    ).intersection(drivezone_union)
                    if group_node_reinclude_geometries:
                        trimmed_virtual_polygon_geometry = unary_union(
                            [trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not trimmed_virtual_polygon_geometry.is_empty:
                        trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=trimmed_virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        trimmed_uncovered_group_node_ids,
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=group_nodes,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=validation_support_rc_node_ids,
                        support_road_ids=validation_support_rc_road_ids,
                        support_clip=validation_support_clip,
                    )
                    (
                        trimmed_uncovered_support_rc_node_ids,
                        trimmed_uncovered_support_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_support_gaps(
                        uncovered_support_node_ids=trimmed_uncovered_support_rc_node_ids,
                        uncovered_support_road_ids=trimmed_uncovered_support_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_support_node_ids=candidate_selected_rc_node_ids,
                        hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    (
                        _trimmed_selected_group_node_ids,
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=trimmed_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                    (
                        trimmed_uncovered_selected_rc_node_ids,
                        trimmed_uncovered_selected_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_selected_gaps(
                        uncovered_selected_node_ids=trimmed_uncovered_selected_rc_node_ids,
                        uncovered_selected_road_ids=trimmed_uncovered_selected_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_selected_node_ids=selected_rc_endpoint_node_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    if (
                        not trimmed_uncovered_group_node_ids
                        and not trimmed_uncovered_support_rc_node_ids
                        and not trimmed_uncovered_support_rc_road_ids
                        and not trimmed_uncovered_selected_rc_node_ids
                        and not trimmed_uncovered_selected_rc_road_ids
                    ):
                        announce(
                            logger,
                            (
                                f"[T02-POC] residual foreign road hard-trim applied mainnodeid={normalized_mainnodeid} "
                                f"extra_roads={','.join(residual_target_group_foreign_road_ids)}"
                            ),
                        )
                        virtual_polygon_geometry = trimmed_virtual_polygon_geometry
                    else:
                        announce(
                            logger,
                            (
                                f"[T02-POC] residual foreign road hard-trim discarded mainnodeid={normalized_mainnodeid} "
                                f"group_uncovered={','.join(sorted(trimmed_uncovered_group_node_ids)) or '-'} "
                                f"support_nodes={','.join(sorted(trimmed_uncovered_support_rc_node_ids)) or '-'} "
                                f"support_roads={','.join(sorted(trimmed_uncovered_support_rc_road_ids)) or '-'} "
                                f"selected_nodes={','.join(sorted(trimmed_uncovered_selected_rc_node_ids)) or '-'} "
                                f"selected_roads={','.join(sorted(trimmed_uncovered_selected_rc_road_ids)) or '-'}"
                            ),
                        )
        final_selected_node_cover_repair_discarded_due_to_extra_roads = False
        if not virtual_polygon_geometry.is_empty and selected_rc_node_ids:
            selected_node_cover_geometry = virtual_polygon_geometry.buffer(
                max(resolution_m, 0.5),
                join_style=1,
            )
            directly_uncovered_selected_rc_node_ids = sorted(
                node_id
                for node_id in selected_rc_node_ids
                if node_id in rc_node_by_id
                and node_id in selected_rc_endpoint_node_ids
                and not selected_node_cover_geometry.covers(rc_node_by_id[node_id].geometry)
            )
            if directly_uncovered_selected_rc_node_ids:
                announce(
                    logger,
                    (
                        f"[T02-POC] final selected node cover repair candidate mainnodeid={normalized_mainnodeid} "
                        f"node_ids={','.join(directly_uncovered_selected_rc_node_ids)}"
                    ),
                )
                final_selected_node_cover_repair_geometries = (
                    _build_uncovered_selected_rc_node_repair_geometries(
                        uncovered_selected_node_ids=directly_uncovered_selected_rc_node_ids,
                        current_polygon_geometry=virtual_polygon_geometry,
                        local_rc_nodes=local_rc_nodes,
                        drivezone_union=drivezone_union,
                        selected_rc_roads=selected_rc_roads,
                        node_buffer_m=max(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.05, 0.35),
                        connector_half_width_m=max(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.05, 0.35),
                    )
                )
                if final_selected_node_cover_repair_geometries:
                    repaired_virtual_polygon_geometry = unary_union(
                        [virtual_polygon_geometry, *final_selected_node_cover_repair_geometries]
                    ).intersection(drivezone_union)
                    if group_node_reinclude_geometries:
                        repaired_virtual_polygon_geometry = unary_union(
                            [repaired_virtual_polygon_geometry, *group_node_reinclude_geometries]
                        ).intersection(drivezone_union)
                    if not repaired_virtual_polygon_geometry.is_empty:
                        repaired_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                            geometry=repaired_virtual_polygon_geometry,
                            drivezone_union=drivezone_union,
                            seed_geometry=core_geometry,
                        )
                    (
                        repaired_uncovered_group_node_ids,
                        repaired_uncovered_support_rc_node_ids,
                        repaired_uncovered_support_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=repaired_virtual_polygon_geometry,
                        group_nodes=group_nodes,
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=validation_support_rc_node_ids,
                        support_road_ids=validation_support_rc_road_ids,
                        support_clip=validation_support_clip,
                    )
                    (
                        repaired_uncovered_support_rc_node_ids,
                        repaired_uncovered_support_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_support_gaps(
                        uncovered_support_node_ids=repaired_uncovered_support_rc_node_ids,
                        uncovered_support_road_ids=repaired_uncovered_support_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=analysis_center,
                        hard_support_node_ids=candidate_selected_rc_node_ids,
                        hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    (
                        _repaired_selected_group_node_ids,
                        repaired_uncovered_selected_rc_node_ids,
                        repaired_uncovered_selected_rc_road_ids,
                    ) = _validate_polygon_support(
                        polygon_geometry=repaired_virtual_polygon_geometry,
                        group_nodes=[],
                        local_rc_nodes=local_rc_nodes,
                        local_rc_roads=local_rc_roads,
                        support_node_ids=selected_rc_node_ids,
                        support_road_ids={road.road_id for road in selected_rc_roads},
                        support_clip=selected_output_clip,
                    )
                    (
                        repaired_uncovered_selected_rc_node_ids,
                        repaired_uncovered_selected_rc_road_ids,
                    ) = _relax_targeted_foreign_trim_selected_gaps(
                        uncovered_selected_node_ids=repaired_uncovered_selected_rc_node_ids,
                        uncovered_selected_road_ids=repaired_uncovered_selected_rc_road_ids,
                        rc_node_by_id=rc_node_by_id,
                        rc_road_by_id=rc_road_by_id,
                        analysis_center=None,
                        hard_selected_node_ids=selected_rc_endpoint_node_ids,
                        relax_node_ids=conflict_excluded_rc_node_ids,
                        relax_road_ids=conflict_excluded_rc_road_ids,
                    )
                    if (
                        not repaired_uncovered_group_node_ids
                        and not repaired_uncovered_support_rc_node_ids
                        and not repaired_uncovered_support_rc_road_ids
                        and not repaired_uncovered_selected_rc_node_ids
                        and not repaired_uncovered_selected_rc_road_ids
                    ):
                        repaired_extra_local_road_ids = _covered_foreign_local_road_ids(
                            polygon_geometry=repaired_virtual_polygon_geometry,
                            local_roads=local_roads,
                            local_nodes=local_nodes,
                            allowed_road_ids=allowed_local_road_ids,
                            target_group_node_ids=analysis_member_node_ids,
                            normalized_mainnodeid=normalized_mainnodeid,
                            local_road_degree_by_node_id=local_road_degree_by_node_id,
                            analysis_center=analysis_center,
                            semantic_mainnodeids=semantic_mainnodeids,
                        )
                        if repaired_extra_local_road_ids:
                            repair_keep_parts = [
                                geometry
                                for geometry in (
                                    *group_node_buffers,
                                    *group_node_connectors,
                                    *group_node_reinclude_geometries,
                                    *final_selected_node_cover_repair_geometries,
                                )
                                if geometry is not None and not geometry.is_empty
                            ]
                            repair_keep_geometry = (
                                unary_union(repair_keep_parts)
                                if repair_keep_parts
                                else None
                            )
                            repair_trim_geometry = _build_targeted_foreign_local_road_trim_geometry(
                                polygon_geometry=repaired_virtual_polygon_geometry,
                                road_ids=set(repaired_extra_local_road_ids),
                                local_roads=local_roads,
                                drivezone_union=drivezone_union,
                                keep_geometry=repair_keep_geometry,
                                local_nodes=local_nodes,
                                target_group_node_ids=analysis_member_node_ids,
                                normalized_mainnodeid=normalized_mainnodeid,
                                local_road_degree_by_node_id=local_road_degree_by_node_id,
                                semantic_mainnodeids=semantic_mainnodeids,
                                respect_keep_geometry_for_target_group_foreign_roads=False,
                            )
                            if not repair_trim_geometry.is_empty:
                                repaired_trimmed_virtual_polygon_geometry = repaired_virtual_polygon_geometry.difference(
                                    repair_trim_geometry
                                ).intersection(drivezone_union)
                                if group_node_reinclude_geometries:
                                    repaired_trimmed_virtual_polygon_geometry = unary_union(
                                        [repaired_trimmed_virtual_polygon_geometry, *group_node_reinclude_geometries]
                                    ).intersection(drivezone_union)
                                if not repaired_trimmed_virtual_polygon_geometry.is_empty:
                                    repaired_trimmed_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                                        geometry=repaired_trimmed_virtual_polygon_geometry,
                                        drivezone_union=drivezone_union,
                                        seed_geometry=core_geometry,
                                    )
                                (
                                    retrim_uncovered_group_node_ids,
                                    retrim_uncovered_support_rc_node_ids,
                                    retrim_uncovered_support_rc_road_ids,
                                ) = _validate_polygon_support(
                                    polygon_geometry=repaired_trimmed_virtual_polygon_geometry,
                                    group_nodes=group_nodes,
                                    local_rc_nodes=local_rc_nodes,
                                    local_rc_roads=local_rc_roads,
                                    support_node_ids=validation_support_rc_node_ids,
                                    support_road_ids=validation_support_rc_road_ids,
                                    support_clip=validation_support_clip,
                                )
                                (
                                    retrim_uncovered_support_rc_node_ids,
                                    retrim_uncovered_support_rc_road_ids,
                                ) = _relax_targeted_foreign_trim_support_gaps(
                                    uncovered_support_node_ids=retrim_uncovered_support_rc_node_ids,
                                    uncovered_support_road_ids=retrim_uncovered_support_rc_road_ids,
                                    rc_node_by_id=rc_node_by_id,
                                    rc_road_by_id=rc_road_by_id,
                                    analysis_center=analysis_center,
                                    hard_support_node_ids=candidate_selected_rc_node_ids,
                                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                                    relax_node_ids=conflict_excluded_rc_node_ids,
                                    relax_road_ids=conflict_excluded_rc_road_ids,
                                )
                                (
                                    _retrim_selected_group_node_ids,
                                    retrim_uncovered_selected_rc_node_ids,
                                    retrim_uncovered_selected_rc_road_ids,
                                ) = _validate_polygon_support(
                                    polygon_geometry=repaired_trimmed_virtual_polygon_geometry,
                                    group_nodes=[],
                                    local_rc_nodes=local_rc_nodes,
                                    local_rc_roads=local_rc_roads,
                                    support_node_ids=selected_rc_node_ids,
                                    support_road_ids={road.road_id for road in selected_rc_roads},
                                    support_clip=selected_output_clip,
                                )
                                (
                                    retrim_uncovered_selected_rc_node_ids,
                                    retrim_uncovered_selected_rc_road_ids,
                                ) = _relax_targeted_foreign_trim_selected_gaps(
                                    uncovered_selected_node_ids=retrim_uncovered_selected_rc_node_ids,
                                    uncovered_selected_road_ids=retrim_uncovered_selected_rc_road_ids,
                                    rc_node_by_id=rc_node_by_id,
                                    rc_road_by_id=rc_road_by_id,
                                    analysis_center=None,
                                    hard_selected_node_ids=selected_rc_endpoint_node_ids,
                                    relax_node_ids=conflict_excluded_rc_node_ids,
                                    relax_road_ids=conflict_excluded_rc_road_ids,
                                )
                                retrim_extra_local_road_ids = _covered_foreign_local_road_ids(
                                    polygon_geometry=repaired_trimmed_virtual_polygon_geometry,
                                    local_roads=local_roads,
                                    local_nodes=local_nodes,
                                    allowed_road_ids=allowed_local_road_ids,
                                    target_group_node_ids=analysis_member_node_ids,
                                    normalized_mainnodeid=normalized_mainnodeid,
                                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                                    analysis_center=analysis_center,
                                    semantic_mainnodeids=semantic_mainnodeids,
                                )
                                if (
                                    not retrim_uncovered_group_node_ids
                                    and not retrim_uncovered_support_rc_node_ids
                                    and not retrim_uncovered_support_rc_road_ids
                                    and not retrim_uncovered_selected_rc_node_ids
                                    and not retrim_uncovered_selected_rc_road_ids
                                    and not retrim_extra_local_road_ids
                                ):
                                    repaired_virtual_polygon_geometry = repaired_trimmed_virtual_polygon_geometry
                                    repaired_extra_local_road_ids = []
                        if not repaired_extra_local_road_ids:
                            announce(
                                logger,
                                (
                                    f"[T02-POC] final selected node cover repair applied mainnodeid={normalized_mainnodeid} "
                                    f"node_ids={','.join(directly_uncovered_selected_rc_node_ids)}"
                                ),
                            )
                            virtual_polygon_geometry = repaired_virtual_polygon_geometry
                        else:
                            obstacle_aware_repair_geometries = _build_uncovered_selected_rc_node_repair_geometries(
                                uncovered_selected_node_ids=directly_uncovered_selected_rc_node_ids,
                                current_polygon_geometry=virtual_polygon_geometry,
                                local_rc_nodes=local_rc_nodes,
                                drivezone_union=drivezone_union,
                                selected_rc_roads=selected_rc_roads,
                                obstacle_geometries=[
                                    road.geometry
                                    for road in local_roads
                                    if road.road_id in set(repaired_extra_local_road_ids)
                                ],
                                node_buffer_m=max(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M + 0.05, 0.35),
                                connector_half_width_m=max(POLYGON_SUPPORT_VALIDATION_TOLERANCE_M * 0.45, 0.3),
                            )
                            if obstacle_aware_repair_geometries:
                                obstacle_aware_virtual_polygon_geometry = unary_union(
                                    [virtual_polygon_geometry, *obstacle_aware_repair_geometries]
                                ).intersection(drivezone_union)
                                if group_node_reinclude_geometries:
                                    obstacle_aware_virtual_polygon_geometry = unary_union(
                                        [obstacle_aware_virtual_polygon_geometry, *group_node_reinclude_geometries]
                                    ).intersection(drivezone_union)
                                if not obstacle_aware_virtual_polygon_geometry.is_empty:
                                    obstacle_aware_virtual_polygon_geometry = _regularize_virtual_polygon_geometry(
                                        geometry=obstacle_aware_virtual_polygon_geometry,
                                        drivezone_union=drivezone_union,
                                        seed_geometry=core_geometry,
                                    )
                                (
                                    obstacle_uncovered_group_node_ids,
                                    obstacle_uncovered_support_rc_node_ids,
                                    obstacle_uncovered_support_rc_road_ids,
                                ) = _validate_polygon_support(
                                    polygon_geometry=obstacle_aware_virtual_polygon_geometry,
                                    group_nodes=group_nodes,
                                    local_rc_nodes=local_rc_nodes,
                                    local_rc_roads=local_rc_roads,
                                    support_node_ids=validation_support_rc_node_ids,
                                    support_road_ids=validation_support_rc_road_ids,
                                    support_clip=validation_support_clip,
                                )
                                (
                                    obstacle_uncovered_support_rc_node_ids,
                                    obstacle_uncovered_support_rc_road_ids,
                                ) = _relax_targeted_foreign_trim_support_gaps(
                                    uncovered_support_node_ids=obstacle_uncovered_support_rc_node_ids,
                                    uncovered_support_road_ids=obstacle_uncovered_support_rc_road_ids,
                                    rc_node_by_id=rc_node_by_id,
                                    rc_road_by_id=rc_road_by_id,
                                    analysis_center=analysis_center,
                                    hard_support_node_ids=candidate_selected_rc_node_ids,
                                    hard_support_road_ids=candidate_selected_positive_group_rc_road_ids,
                                    relax_node_ids=conflict_excluded_rc_node_ids,
                                    relax_road_ids=conflict_excluded_rc_road_ids,
                                )
                                (
                                    _obstacle_selected_group_node_ids,
                                    obstacle_uncovered_selected_rc_node_ids,
                                    obstacle_uncovered_selected_rc_road_ids,
                                ) = _validate_polygon_support(
                                    polygon_geometry=obstacle_aware_virtual_polygon_geometry,
                                    group_nodes=[],
                                    local_rc_nodes=local_rc_nodes,
                                    local_rc_roads=local_rc_roads,
                                    support_node_ids=selected_rc_node_ids,
                                    support_road_ids={road.road_id for road in selected_rc_roads},
                                    support_clip=selected_output_clip,
                                )
                                (
                                    obstacle_uncovered_selected_rc_node_ids,
                                    obstacle_uncovered_selected_rc_road_ids,
                                ) = _relax_targeted_foreign_trim_selected_gaps(
                                    uncovered_selected_node_ids=obstacle_uncovered_selected_rc_node_ids,
                                    uncovered_selected_road_ids=obstacle_uncovered_selected_rc_road_ids,
                                    rc_node_by_id=rc_node_by_id,
                                    rc_road_by_id=rc_road_by_id,
                                    analysis_center=None,
                                    hard_selected_node_ids=selected_rc_endpoint_node_ids,
                                    relax_node_ids=conflict_excluded_rc_node_ids,
                                    relax_road_ids=conflict_excluded_rc_road_ids,
                                )
                                obstacle_extra_local_road_ids = _covered_foreign_local_road_ids(
                                    polygon_geometry=obstacle_aware_virtual_polygon_geometry,
                                    local_roads=local_roads,
                                    local_nodes=local_nodes,
                                    allowed_road_ids=allowed_local_road_ids,
                                    target_group_node_ids=analysis_member_node_ids,
                                    normalized_mainnodeid=normalized_mainnodeid,
                                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                                    analysis_center=analysis_center,
                                    semantic_mainnodeids=semantic_mainnodeids,
                                )
                                if (
                                    not obstacle_uncovered_group_node_ids
                                    and not obstacle_uncovered_support_rc_node_ids
                                    and not obstacle_uncovered_support_rc_road_ids
                                    and not obstacle_uncovered_selected_rc_node_ids
                                    and not obstacle_uncovered_selected_rc_road_ids
                                    and not obstacle_extra_local_road_ids
                                ):
                                    announce(
                                        logger,
                                        (
                                            f"[T02-POC] final selected node cover repair applied via obstacle-aware connector mainnodeid={normalized_mainnodeid} "
                                            f"node_ids={','.join(directly_uncovered_selected_rc_node_ids)}"
                                        ),
                                    )
                                    virtual_polygon_geometry = obstacle_aware_virtual_polygon_geometry
                                    repaired_extra_local_road_ids = []
                                if repaired_extra_local_road_ids:
                                    final_selected_node_cover_repair_discarded_due_to_extra_roads = True
                                    announce(
                                        logger,
                                        (
                                            f"[T02-POC] final selected node cover repair discarded due to extra_roads mainnodeid={normalized_mainnodeid} "
                                            f"extra_roads={','.join(sorted(repaired_extra_local_road_ids))}"
                                        ),
                                    )
                    else:
                        announce(
                            logger,
                            (
                                f"[T02-POC] final selected node cover repair discarded mainnodeid={normalized_mainnodeid} "
                                f"group_uncovered={','.join(sorted(repaired_uncovered_group_node_ids)) or '-'} "
                                f"support_nodes={','.join(sorted(repaired_uncovered_support_rc_node_ids)) or '-'} "
                                f"support_roads={','.join(sorted(repaired_uncovered_support_rc_road_ids)) or '-'} "
                                f"selected_nodes={','.join(sorted(repaired_uncovered_selected_rc_node_ids)) or '-'} "
                                f"selected_roads={','.join(sorted(repaired_uncovered_selected_rc_road_ids)) or '-'}"
                            ),
                        )
        covered_extra_local_node_ids = sorted(
            node.node_id
            for node in local_nodes
            if (
                _is_foreign_local_semantic_node(
                    node=node,
                    target_group_node_ids=analysis_member_node_ids,
                    normalized_mainnodeid=normalized_mainnodeid,
                    local_road_degree_by_node_id=local_road_degree_by_node_id,
                    semantic_mainnodeids=semantic_mainnodeids,
                )
                and _polygon_substantively_covers_node(
                    virtual_polygon_geometry,
                    node.geometry,
                    cover_radius_m=max(resolution_m, 0.5),
                )
            )
        )
        covered_extra_local_road_ids = _covered_foreign_local_road_ids(
            polygon_geometry=virtual_polygon_geometry,
            local_roads=local_roads,
            local_nodes=local_nodes,
            allowed_road_ids=allowed_local_road_ids,
            target_group_node_ids=analysis_member_node_ids,
            normalized_mainnodeid=normalized_mainnodeid,
            local_road_degree_by_node_id=local_road_degree_by_node_id,
            analysis_center=analysis_center,
            semantic_mainnodeids=semantic_mainnodeids,
        )
        counts["covered_extra_local_node_count"] = len(covered_extra_local_node_ids)
        counts["covered_extra_local_road_count"] = len(covered_extra_local_road_ids)
        if covered_extra_local_node_ids or covered_extra_local_road_ids:
            if STATUS_NODE_COMPONENT_CONFLICT not in risks:
                risks.append(STATUS_NODE_COMPONENT_CONFLICT)
                audit_rows.append(
                    _audit_row(
                        scope="virtual_intersection_poc",
                        status="warning",
                        reason=STATUS_NODE_COMPONENT_CONFLICT,
                        detail=(
                            "Final polygon still covers extra local semantic nodes / roads after selected-association "
                            "repair: extra_nodes="
                            f"{','.join(covered_extra_local_node_ids) or '-'} extra_roads="
                            f"{','.join(covered_extra_local_road_ids) or '-'}."
                        ),
                        mainnodeid=normalized_mainnodeid,
                        feature_id=(covered_extra_local_node_ids or covered_extra_local_road_ids)[0],
                    )
                )
        else:
            risks = [risk for risk in risks if risk != STATUS_NODE_COMPONENT_CONFLICT]
            audit_rows = [
                row
                for row in audit_rows
                if row.get("reason") != STATUS_NODE_COMPONENT_CONFLICT
            ]
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
        effective_local_rc_node_count = sum(
            1
            for node in local_rc_nodes
            if (
                float(node.geometry.distance(analysis_center)) <= 10.0
                and _is_effective_rc_junction_node(
                    node=node,
                    local_rc_road_degree_by_node_id=local_rc_road_degree_by_node_id,
                )
            )
        )
        counts["effective_local_rcsdnode_count"] = effective_local_rc_node_count
        effective_associated_rc_node_count = sum(
            1
            for node in local_rc_nodes
            if (
                node.node_id in selected_rc_node_ids
                or node.node_id in polygon_support_rc_node_ids
            )
            and _is_effective_rc_junction_node(
                node=node,
                local_rc_road_degree_by_node_id=local_rc_road_degree_by_node_id,
            )
        )
        counts["effective_associated_rcsdnode_count"] = effective_associated_rc_node_count
        associated_nonzero_mainnode_count = sum(
            1
            for node in local_rc_nodes
            if (
                node.node_id in selected_rc_node_ids
                or node.node_id in polygon_support_rc_node_ids
            )
            and node.mainnodeid not in {None, "0"}
        )
        counts["associated_nonzero_mainnode_count"] = associated_nonzero_mainnode_count
        connected_rc_group_ids = {
            rc_group_id
            for branch in road_branches
            for rc_group_id in branch.rcsdroad_ids
        }
        has_structural_side_branch = _has_structural_side_branch(road_branches)
        has_main_edge_only_branch = any(
            branch.is_main_direction and branch.evidence_level == "edge_only"
            for branch in road_branches
        )
        max_nonmain_edge_branch_road_support_m, max_nonmain_edge_branch_rc_support_m = _max_nonmain_edge_branch_support_metrics(
            road_branches=road_branches
        )
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

        if (
            STATUS_NODE_COMPONENT_CONFLICT in risks
            and not covered_extra_local_node_ids
            and len(covered_extra_local_road_ids) <= 1
            and representative_node.kind_2 == 2048
            and len(selected_rc_roads) >= 2
            and max_selected_side_branch_covered_length_m <= 0.5
            and max_nonmain_branch_polygon_length_m <= 8.5
        ):
            risks = [risk for risk in risks if risk != STATUS_NODE_COMPONENT_CONFLICT]

        status = _status_from_risks(risks, has_associated_roads=bool(associated_rcsdroad_features))
        if status == STATUS_STABLE and not associated_rcsdroad_features:
            status = STATUS_SURFACE_ONLY
        effect_success, acceptance_class, acceptance_reason = _effect_success_acceptance(
            status=status,
            review_mode=review_mode,
            max_selected_side_branch_covered_length_m=max_selected_side_branch_covered_length_m,
            max_nonmain_branch_polygon_length_m=max_nonmain_branch_polygon_length_m,
            associated_rc_road_count=len(associated_rcsdroad_features),
            polygon_support_rc_node_count=len(polygon_support_rc_node_ids),
            polygon_support_rc_road_count=len(polygon_support_rc_road_ids),
            min_invalid_rc_distance_to_center_m=min_invalid_rc_distance_to_center_m,
            local_rc_road_count=len(local_rc_roads),
            local_rc_node_count=len(local_rc_nodes),
            effective_local_rc_node_count=effective_local_rc_node_count,
            local_road_count=len(local_roads),
            local_node_count=len(local_nodes),
            connected_rc_group_count=len(connected_rc_group_ids),
            nonmain_branch_connected_rc_group_count=len(nonmain_branch_connected_rc_group_ids),
            negative_rc_group_count=len(negative_rc_groups),
            positive_rc_group_count=len(positive_rc_groups),
            road_branch_count=len(road_branches),
            has_structural_side_branch=has_structural_side_branch,
            max_nonmain_edge_branch_road_support_m=max_nonmain_edge_branch_road_support_m,
            max_nonmain_edge_branch_rc_support_m=max_nonmain_edge_branch_rc_support_m,
            excluded_local_rc_road_count=len(invalid_rc_road_ids),
            excluded_local_rc_node_count=len(invalid_rc_node_ids),
            covered_extra_local_node_count=len(covered_extra_local_node_ids),
            covered_extra_local_road_count=len(covered_extra_local_road_ids),
            has_main_edge_only_branch=has_main_edge_only_branch,
            representative_kind_2=representative_node.kind_2,
            effective_associated_rc_node_count=effective_associated_rc_node_count,
            associated_nonzero_mainnode_count=associated_nonzero_mainnode_count,
            final_selected_node_cover_repair_discarded_due_to_extra_roads=final_selected_node_cover_repair_discarded_due_to_extra_roads,
        )
        business_match_class = _business_match_class(
            status=status,
            acceptance_class=acceptance_class,
            associated_rc_road_count=counts["associated_rcsdroad_count"],
            polygon_support_rc_road_count=len(polygon_support_rc_road_ids),
            local_rc_road_count=len(local_rc_roads),
            excluded_rc_road_count=counts.get("excluded_rcsdroad_count", 0),
        )
        business_match_reason = _business_match_reason(
            status=status,
            business_match_class=business_match_class,
            acceptance_reason=acceptance_reason,
            excluded_rc_road_count=counts.get("excluded_rcsdroad_count", 0),
        )
        can_soft_exclude_outside_rc = False
        if rc_outside_drivezone_error is not None and not review_mode:
            can_soft_exclude_outside_rc = _can_soft_exclude_outside_rc(
                status=status,
                selected_rc_road_count=len(selected_rc_roads),
                polygon_support_rc_road_count=len(polygon_support_rc_road_ids),
                max_selected_side_branch_covered_length_m=max_selected_side_branch_covered_length_m,
                max_nonmain_branch_polygon_length_m=max_nonmain_branch_polygon_length_m,
                min_invalid_rc_distance_to_center_m=min_invalid_rc_distance_to_center_m,
                connected_rc_group_count=len(connected_rc_group_ids),
                negative_rc_group_count=len(negative_rc_groups),
                effective_local_rc_node_count=effective_local_rc_node_count,
                effective_associated_rc_node_count=effective_associated_rc_node_count,
                associated_nonzero_mainnode_count=associated_nonzero_mainnode_count,
                covered_extra_local_node_count=len(covered_extra_local_node_ids),
                covered_extra_local_road_count=len(covered_extra_local_road_ids),
                local_road_count=len(local_roads),
                local_node_count=len(local_nodes),
            )
            announce(
                logger,
                (
                    f"[T02-POC] outside-rc soft-exclude check mainnodeid={normalized_mainnodeid} "
                    f"status={status} selected_rc_road_count={len(selected_rc_roads)} "
                    f"polygon_support_rc_road_count={len(polygon_support_rc_road_ids)} "
                    f"max_selected_side_branch_covered_length_m={max_selected_side_branch_covered_length_m:.3f} "
                    f"max_nonmain_branch_polygon_length_m={max_nonmain_branch_polygon_length_m:.3f} "
                    f"min_invalid_rc_distance_to_center_m={min_invalid_rc_distance_to_center_m} "
                    f"connected_rc_group_count={len(connected_rc_group_ids)} "
                    f"negative_rc_group_count={len(negative_rc_groups)} "
                    f"effective_local_rc_node_count={effective_local_rc_node_count} "
                    f"effective_associated_rc_node_count={effective_associated_rc_node_count} "
                    f"associated_nonzero_mainnode_count={associated_nonzero_mainnode_count} "
                    f"local_node_count={len(local_nodes)} local_road_count={len(local_roads)} "
                    f"result={can_soft_exclude_outside_rc}"
                ),
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
            "business_match_class": business_match_class,
            "business_match_reason": business_match_reason,
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
        emit_progress_snapshot(
            status="success" if effect_success else "completed_with_review_required_result",
            current_stage="complete",
            message=(
                "T02 virtual intersection POC completed and accepted."
                if effect_success
                else "T02 virtual intersection POC completed but requires review before acceptance."
            ),
        )
        record_stage("outputs_written")
        total_wall_time_sec = time.perf_counter() - started_at
        perf_doc = {
            "run_id": resolved_run_id,
            "success": effect_success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "business_match_class": business_match_class,
            "business_match_reason": business_match_reason,
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
        emit_progress_snapshot(
            status="failed",
            current_stage="failed",
            message=exc.detail,
        )
        if debug:
            try:
                representative_node_for_failure = locals().get("representative_node")
                group_nodes_for_failure = locals().get("group_nodes")
                local_nodes_for_failure = locals().get("local_nodes")
                local_roads_for_failure = locals().get("local_roads")
                local_rc_nodes_for_failure = locals().get("local_rc_nodes")
                local_rc_roads_for_failure = locals().get("local_rc_roads")
                drivezone_union_for_failure = locals().get("drivezone_union")
                if (
                    representative_node_for_failure is not None
                    and group_nodes_for_failure is not None
                    and local_nodes_for_failure is not None
                    and local_roads_for_failure is not None
                    and local_rc_nodes_for_failure is not None
                    and local_rc_roads_for_failure is not None
                    and drivezone_union_for_failure is not None
                ):
                    _write_failure_debug_rendered_map(
                        out_path=rendered_map_path,
                        representative_node=representative_node_for_failure,
                        group_nodes=group_nodes_for_failure,
                        local_nodes=local_nodes_for_failure,
                        local_roads=local_roads_for_failure,
                        local_rc_nodes=local_rc_nodes_for_failure,
                        local_rc_roads=local_rc_roads_for_failure,
                        drivezone_union=drivezone_union_for_failure,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        failure_reason=exc.reason,
                    )
                    debug_rendered_map_written = True
                    announce(
                        logger,
                        (
                            "[T02-POC] wrote failure debug rendered map "
                            f"path={rendered_map_path} reason={exc.reason}"
                        ),
                    )
            except Exception as render_exc:
                announce(
                    logger,
                    (
                        "[T02-POC] failure debug rendered map skipped "
                        f"reason={type(render_exc).__name__}: {render_exc}"
                    ),
                )
        write_csv(audit_csv_path, audit_rows, fieldnames=AUDIT_FIELDNAMES)
        write_json(audit_json_path, audit_rows)
        status_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "business_match_class": (
                BUSINESS_MATCH_PARTIAL_RCSD
                if counts.get("local_rcsdroad_count", 0) > 0 or counts.get("local_rcsdnode_count", 0) > 0
                else BUSINESS_MATCH_SWSD_ONLY
            ),
            "business_match_reason": (
                "failed_with_partial_rcsd_context"
                if counts.get("local_rcsdroad_count", 0) > 0 or counts.get("local_rcsdnode_count", 0) > 0
                else "failed_without_usable_rcsd_context"
            ),
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
            "business_match_class": status_doc["business_match_class"],
            "business_match_reason": status_doc["business_match_reason"],
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
