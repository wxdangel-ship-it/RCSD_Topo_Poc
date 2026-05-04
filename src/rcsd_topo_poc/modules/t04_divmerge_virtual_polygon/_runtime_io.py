from __future__ import annotations

from ._runtime_types import *

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



__all__ = [name for name in globals() if not name.startswith("__")]
