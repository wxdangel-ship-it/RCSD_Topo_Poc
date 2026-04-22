from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, TypeVar, Union

import fiona
import ijson
import numpy as np
import shapefile
from pyproj import CRS
from shapely import from_wkb, intersects_xy
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    TARGET_CRS,
    prefer_vector_input_path,
    transform_geometry_to_target,
)

from ._runtime_shared import (
    LoadedFeature,
    LoadedLayer,
    NodeRecord,
    ResolvedJunctionGroup,
    _resolve_geopackage_crs_strict,
    _resolve_geopackage_layer_name,
    _resolve_shapefile_crs_strict,
    _transform_geometry,
    normalize_id,
    read_vector_layer_strict,
)

T = TypeVar("T")

_normalize_id = normalize_id
_read_vector_layer_strict = read_vector_layer_strict


def _coerce_int(value: Any) -> int | None:
    normalized = _normalize_id(value)
    if normalized is None:
        return None
    try:
        return int(float(normalized))
    except Exception:
        return None


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
COMPOUND_CENTER_MAX_LINK_M = 20.0
COMPOUND_CENTER_MAX_DISTANCE_M = 25.0
COMPOUND_CENTER_MIN_DRIVEZONE_COVERAGE_RATIO = 0.8
RAY_GAP_STEPS = 3
RAY_SAMPLE_STEP_MULTIPLIER = 0.5
SPATIAL_CACHE_VERSION = "v1"
POC_SPATIAL_CACHE_DIR = Path(__file__).resolve().parents[4] / "outputs" / "_work" / "t04_poc_spatial_cache"
PATCH_ID_FIELD_NAMES = ("patchid", "patch_id")

REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"
REASON_REPRESENTATIVE_NODE_MISSING = "representative_node_missing"
REASON_MAINNODEID_NOT_FOUND = "mainnodeid_not_found"
REASON_MAINNODEID_OUT_OF_SCOPE = "mainnodeid_out_of_scope"
REASON_MAIN_DIRECTION_UNSTABLE = "main_direction_unstable"
REASON_RC_OUTSIDE_DRIVEZONE = "rc_outside_drivezone"
REASON_ANCHOR_SUPPORT_CONFLICT = "anchor_support_conflict"

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
    kind: Any | None = None


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
class SingleSidedTMouthCorridorPattern:
    main_branch_ids: tuple[str, ...]
    side_branch_ids: tuple[str, ...]
    shared_positive_rc_groups: tuple[str, ...]


def _classify_stage3_template(
    *,
    representative_kind_2: int | None,
    single_sided_t_mouth_corridor_pattern: SingleSidedTMouthCorridorPattern | None,
) -> str:
    if representative_kind_2 == 2048:
        return TEMPLATE_SINGLE_SIDED_T_MOUTH
    return TEMPLATE_CENTER_JUNCTION


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
                kind=props.get("kind"),
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
                kind=props.get("kind"),
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


_BITMAP_TEXT_GLYPHS_5X7: dict[str, tuple[str, ...]] = {
    "/": ("00001", "00010", "00100", "00100", "01000", "10000", "00000"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "V": ("10001", "10001", "10001", "10001", "01010", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "\u5f85": ("0010000", "1111111", "0010000", "1111110", "0010010", "1111111", "0010000"),
    "\u590d": ("1111111", "0010000", "0111110", "0001000", "0011100", "0100010", "1111111"),
    "\u6838": ("1001001", "1111111", "0101010", "0011100", "0101010", "1001001", "1111111"),
    "\u5931": ("0010000", "1111111", "0010000", "0111110", "0010000", "0101000", "1000111"),
    "\u8d25": ("1000001", "1110111", "0010100", "1110111", "0010100", "0100010", "1000001"),
}


def _paint_rect(
    image: np.ndarray,
    *,
    top: int,
    left: int,
    bottom: int,
    right: int,
    color: tuple[int, int, int],
) -> None:
    clamped_top = max(0, min(image.shape[0], top))
    clamped_bottom = max(clamped_top, min(image.shape[0], bottom))
    clamped_left = max(0, min(image.shape[1], left))
    clamped_right = max(clamped_left, min(image.shape[1], right))
    if clamped_top >= clamped_bottom or clamped_left >= clamped_right:
        return
    image[clamped_top:clamped_bottom, clamped_left:clamped_right, :3] = np.array(color, dtype=np.uint8)
    image[clamped_top:clamped_bottom, clamped_left:clamped_right, 3] = 255


def _bitmap_text_width(text: str, *, scale: int) -> int:
    width = 0
    for index, char in enumerate(text):
        glyph = _BITMAP_TEXT_GLYPHS_5X7.get(char)
        if glyph is None:
            continue
        width += len(glyph[0]) * scale
        if index < len(text) - 1:
            width += scale
    return width


def _draw_bitmap_text(
    image: np.ndarray,
    *,
    text: str,
    top: int,
    left: int,
    color: tuple[int, int, int],
    scale: int,
) -> None:
    cursor_left = left
    for char in text:
        glyph = _BITMAP_TEXT_GLYPHS_5X7.get(char)
        if glyph is None:
            cursor_left += scale
            continue
        for row_index, row in enumerate(glyph):
            for col_index, value in enumerate(row):
                if value != "1":
                    continue
                _paint_rect(
                    image,
                    top=top + row_index * scale,
                    left=cursor_left + col_index * scale,
                    bottom=top + (row_index + 1) * scale,
                    right=cursor_left + (col_index + 1) * scale,
                    color=color,
                )
        cursor_left += (len(glyph[0]) + 1) * scale


def _draw_failure_banner(
    image: np.ndarray,
    *,
    banner_height_px: int,
    banner_color: tuple[int, int, int],
    label: str,
    label_text_color: tuple[int, int, int],
    label_shadow_color: tuple[int, int, int],
) -> None:
    if banner_height_px <= 0:
        return
    _paint_rect(
        image,
        top=0,
        left=0,
        bottom=banner_height_px,
        right=image.shape[1],
        color=banner_color,
    )
    label_scale = 2 if image.shape[1] >= 96 and banner_height_px >= 18 else 1
    label_text = label
    if _bitmap_text_width(label_text, scale=label_scale) > image.shape[1] - 4:
        label_scale = 1
    if _bitmap_text_width(label_text, scale=label_scale) > image.shape[1] - 4:
        label_text = label[:3]
    label_width = _bitmap_text_width(label_text, scale=label_scale)
    label_height = 7 * label_scale
    label_left = max(2, (image.shape[1] - label_width) // 2)
    label_top = max(2, (banner_height_px - label_height) // 2)
    _draw_bitmap_text(
        image,
        text=label_text,
        top=label_top + 1,
        left=label_left + 1,
        color=label_shadow_color,
        scale=label_scale,
    )
    _draw_bitmap_text(
        image,
        text=label_text,
        top=label_top,
        left=label_left,
        color=label_text_color,
        scale=label_scale,
    )


def _failure_overlay_palette(
    failure_reason: str,
    *,
    failure_class: str | None = None,
) -> dict[str, Any]:
    normalized_reason = failure_reason.lower()
    normalized_class = (failure_class or "").lower()
    if not normalized_class:
        normalized_class = "review_required" if normalized_reason.startswith("review_required") else "rejected"
    if normalized_class == "review_required":
        return {
            "tint": (241, 172, 51),
            "border": (176, 96, 0),
            "focus": (214, 132, 34),
            "hatch": (145, 78, 0),
            "banner": (176, 96, 0),
            "label": "REVIEW / \u5f85\u590d\u6838",
            "label_text": (255, 255, 255),
            "label_shadow": (92, 49, 0),
        }
    return {
        "tint": (220, 32, 32),
        "border": (164, 0, 0),
        "focus": (186, 0, 0),
        "hatch": (124, 0, 0),
        "banner": (164, 0, 0),
        "label": "REJECTED / \u5931\u8d25",
        "label_text": (255, 255, 255),
        "label_shadow": (72, 0, 0),
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
    failure_class: str | None = None,
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
        palette = _failure_overlay_palette(failure_reason, failure_class=failure_class)
        failure_mask = np.ones((grid.height, grid.width), dtype=bool)
        border_px = max(2, int(round(4.0 / grid.resolution_m)))
        banner_height_px = max(12, min(24, grid.height // 6))
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
        _draw_failure_banner(
            image,
            banner_height_px=banner_height_px,
            banner_color=palette["banner"],
            label=palette["label"],
            label_text_color=palette["label_text"],
            label_shadow_color=palette["label_shadow"],
        )

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
        failure_class="rejected",
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




__all__ = [name for name in globals() if not name.startswith('__')]
