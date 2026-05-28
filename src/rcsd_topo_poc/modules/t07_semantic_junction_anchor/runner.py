from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
import shapefile
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree
from shapely.validation import explain_validity

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    TARGET_CRS,
    build_run_id,
    prefer_vector_input_path,
    transform_geometry_to_target,
    write_json,
)
from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg as write_gpkg_sqlite


ALLOWED_KIND2 = {"4", "8", "16", "64", "128", "2048"}
INTERSECTION_ID_FIELDS = ("id", "intersection_id", "intersectionid", "fid", "objectid", "OBJECTID")


class T07RunError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class LoadedFeature:
    feature_index: int
    properties: dict[str, Any]
    geometry: BaseGeometry | None


@dataclass(frozen=True)
class LoadedLayer:
    features: list[LoadedFeature]
    source_crs: CRS
    crs_source: str


@dataclass(frozen=True)
class NodeRecord:
    feature_index: int
    output_index: int
    node_id: str
    mainnodeid: str | None
    geometry: BaseGeometry


@dataclass(frozen=True)
class ResolvedGroup:
    junction_id: str
    group_nodes: list[NodeRecord]
    representative: NodeRecord | None
    reason: str | None
    detail: str | None


@dataclass(frozen=True)
class IntersectionRecord:
    feature_index: int
    intersection_id: str
    geometry: BaseGeometry


@dataclass(frozen=True)
class T07StageArtifacts:
    run_root: Path
    stage_root: Path
    nodes_path: Path
    summary_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    perf_json_path: Path


@dataclass(frozen=True)
class T07Artifacts:
    run_root: Path
    step1: T07StageArtifacts
    step2: T07StageArtifacts


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    return text


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_geojson_crs(doc: dict[str, Any], crs_override: str | None) -> tuple[CRS, str]:
    if crs_override:
        return CRS.from_user_input(crs_override), "override"
    crs_payload = doc.get("crs")
    if isinstance(crs_payload, dict):
        name = (crs_payload.get("properties") or {}).get("name")
        if name:
            return CRS.from_user_input(name), "geojson.crs"
    raise T07RunError(
        "invalid_crs_or_unprojectable",
        "GeoJSON is missing CRS metadata and no CRS override was provided.",
    )


def _resolve_shapefile_crs(path: Path, crs_override: str | None) -> tuple[CRS, str]:
    if crs_override:
        return CRS.from_user_input(crs_override), "override"
    prj_path = path.with_suffix(".prj")
    if prj_path.is_file():
        return CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore")), "shapefile.prj"
    raise T07RunError(
        "invalid_crs_or_unprojectable",
        f"Shapefile '{path}' has no .prj and no CRS override was provided.",
    )


def _resolve_gpkg_layer(path: Path, layer_name: str | None) -> str:
    if layer_name:
        return layer_name
    layers = list(fiona.listlayers(str(path)))
    if len(layers) == 1:
        return layers[0]
    if path.stem in layers:
        return path.stem
    raise T07RunError(
        "missing_required_field",
        f"GeoPackage '{path}' has multiple layers {layers}; layer name is required.",
    )


def _resolve_gpkg_crs(path: Path, layer_name: str, crs_override: str | None) -> tuple[CRS, str]:
    if crs_override:
        return CRS.from_user_input(crs_override), "override"
    with fiona.open(str(path), layer=layer_name) as src:
        if src.crs_wkt:
            return CRS.from_wkt(src.crs_wkt), "gpkg.crs_wkt"
        if src.crs:
            return CRS.from_user_input(src.crs), "gpkg.crs"
    raise T07RunError(
        "invalid_crs_or_unprojectable",
        f"GeoPackage '{path}' layer '{layer_name}' has no CRS and no CRS override was provided.",
    )


def _transform_geometry(
    geometry_payload: Any,
    *,
    source_crs: CRS,
    layer_label: str,
    feature_index: int,
) -> BaseGeometry | None:
    if geometry_payload is None:
        return None
    try:
        geometry = transform_geometry_to_target(shape(geometry_payload), source_crs, TARGET_CRS)
    except Exception as exc:
        raise T07RunError(
            "invalid_crs_or_unprojectable",
            f"{layer_label} feature[{feature_index}] failed to transform to EPSG:3857: {exc}",
        ) from exc
    if not geometry.is_valid:
        raise T07RunError(
            "invalid_geometry_topology",
            f"{layer_label} feature[{feature_index}] has invalid geometry: {explain_validity(geometry)}",
        )
    return geometry


def _read_vector_layer(
    path: str | Path,
    *,
    layer_name: str | None = None,
    crs_override: str | None = None,
    allow_null_geometry: bool,
) -> LoadedLayer:
    layer_path = prefer_vector_input_path(Path(path))
    if not layer_path.is_file():
        raise T07RunError("missing_required_field", f"Input layer does not exist: {layer_path}")

    suffix = layer_path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        doc = json.loads(layer_path.read_text(encoding="utf-8"))
        source_crs, crs_source = _resolve_geojson_crs(doc, crs_override)
        features = []
        for feature_index, feature in enumerate(doc.get("features", [])):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None and not allow_null_geometry:
                raise T07RunError("missing_required_field", f"{layer_path} feature[{feature_index}] is missing geometry.")
            features.append(
                LoadedFeature(
                    feature_index=feature_index,
                    properties=dict(feature.get("properties") or {}),
                    geometry=_transform_geometry(
                        geometry_payload,
                        source_crs=source_crs,
                        layer_label=str(layer_path),
                        feature_index=feature_index,
                    ),
                )
            )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix == ".shp":
        source_crs, crs_source = _resolve_shapefile_crs(layer_path, crs_override)
        reader = shapefile.Reader(str(layer_path))
        field_names = [field[0] for field in reader.fields[1:]]
        features = []
        for feature_index, shape_record in enumerate(reader.iterShapeRecords()):
            features.append(
                LoadedFeature(
                    feature_index=feature_index,
                    properties=dict(zip(field_names, list(shape_record.record))),
                    geometry=_transform_geometry(
                        shape_record.shape.__geo_interface__,
                        source_crs=source_crs,
                        layer_label=str(layer_path),
                        feature_index=feature_index,
                    ),
                )
            )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix in GEOPACKAGE_SUFFIXES:
        resolved_layer = _resolve_gpkg_layer(layer_path, layer_name)
        source_crs, crs_source = _resolve_gpkg_crs(layer_path, resolved_layer, crs_override)
        features = []
        with fiona.open(str(layer_path), layer=resolved_layer) as src:
            for feature_index, feature in enumerate(src):
                geometry_payload = feature.get("geometry")
                if geometry_payload is None and not allow_null_geometry:
                    raise T07RunError(
                        "missing_required_field",
                        f"{layer_path}:{resolved_layer} feature[{feature_index}] is missing geometry.",
                    )
                features.append(
                    LoadedFeature(
                        feature_index=feature_index,
                        properties=dict(feature.get("properties") or {}),
                        geometry=_transform_geometry(
                            geometry_payload,
                            source_crs=source_crs,
                            layer_label=f"{layer_path}:{resolved_layer}",
                            feature_index=feature_index,
                        ),
                    )
                )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    raise T07RunError(
        "missing_required_field",
        f"Unsupported vector format for '{layer_path}'. Expected GeoJSON, Shapefile, or GeoPackage.",
    )


def _build_node_index(features: list[LoadedFeature], audit_rows: list[dict[str, Any]]) -> tuple[dict[str, list[NodeRecord]], dict[str, list[NodeRecord]]]:
    by_mainnodeid: dict[str, list[NodeRecord]] = {}
    singleton_by_id: dict[str, list[NodeRecord]] = {}
    for output_index, feature in enumerate(features):
        for field in ("has_evd", "is_anchor", "anchor_reason"):
            feature.properties.setdefault(field, None)

        missing = []
        for field in ("id", "mainnodeid", "kind_2"):
            if field not in feature.properties:
                missing.append(field)
        node_id = _normalize_id(feature.properties.get("id"))
        mainnodeid = _normalize_id(feature.properties.get("mainnodeid"))
        if node_id is None:
            missing.append("id_value")
        if feature.geometry is None or feature.geometry.is_empty:
            missing.append("geometry")
        if missing:
            audit_rows.append(
                _audit_row(
                    scope="node",
                    status="error",
                    reason="missing_required_field",
                    detail=f"node feature[{feature.feature_index}] missing/invalid: {','.join(missing)}",
                    node_id=node_id,
                )
            )
            continue

        record = NodeRecord(
            feature_index=feature.feature_index,
            output_index=output_index,
            node_id=node_id,
            mainnodeid=mainnodeid,
            geometry=feature.geometry,
        )
        if mainnodeid is None:
            singleton_by_id.setdefault(node_id, []).append(record)
        else:
            by_mainnodeid.setdefault(mainnodeid, []).append(record)
    return by_mainnodeid, singleton_by_id


def _candidate_junction_ids(by_mainnodeid: dict[str, list[NodeRecord]], singleton_by_id: dict[str, list[NodeRecord]]) -> list[str]:
    return sorted(set(by_mainnodeid) | set(singleton_by_id))


def _resolve_group(
    junction_id: str,
    *,
    by_mainnodeid: dict[str, list[NodeRecord]],
    singleton_by_id: dict[str, list[NodeRecord]],
) -> ResolvedGroup:
    group_nodes = by_mainnodeid.get(junction_id)
    if group_nodes:
        representatives = [record for record in group_nodes if record.node_id == junction_id]
        if not representatives:
            return ResolvedGroup(
                junction_id=junction_id,
                group_nodes=list(group_nodes),
                representative=None,
                reason="representative_node_missing",
                detail=f"junction_id='{junction_id}' matched mainnodeid group but no node with id == junction_id exists.",
            )
        return ResolvedGroup(junction_id, list(group_nodes), representatives[0], None, None)

    singleton = singleton_by_id.get(junction_id) or []
    if singleton:
        return ResolvedGroup(junction_id, [singleton[0]], singleton[0], None, None)

    return ResolvedGroup(
        junction_id=junction_id,
        group_nodes=[],
        representative=None,
        reason="junction_nodes_not_found",
        detail=f"junction_id='{junction_id}' has no semantic junction group.",
    )


def _audit_row(
    *,
    scope: str,
    status: str,
    reason: str,
    detail: str,
    junction_id: str | None = None,
    node_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "scope": scope,
        "junction_id": junction_id,
        "node_id": node_id,
        "status": status,
        "reason": reason,
        "detail": detail,
    }
    payload.update(extra)
    return payload


def _stage_root(out_root: str | Path, run_id: str | None, stage_name: str) -> tuple[Path, Path, str]:
    resolved_run_id = run_id or build_run_id("t07_semantic_junction_anchor")
    run_root = Path(out_root) / resolved_run_id
    return run_root, run_root / stage_name, resolved_run_id


def _elapsed_since(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 6)


def _write_nodes(path: Path, features: list[LoadedFeature]) -> None:
    write_gpkg_sqlite(
        path,
        ({"properties": feature.properties, "geometry": feature.geometry} for feature in features),
        crs_text=TARGET_CRS.to_string(),
    )


def run_t07_step1_has_evd(
    *,
    nodes_path: str | Path,
    drivezone_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    drivezone_layer: str | None = None,
    nodes_crs: str | None = None,
    drivezone_crs: str | None = None,
) -> T07StageArtifacts:
    started_at = time.perf_counter()
    stage_timings: dict[str, float] = {}
    run_root, stage_root, resolved_run_id = _stage_root(out_root, run_id, "step1_has_evd")
    stage_root.mkdir(parents=True, exist_ok=True)
    audit_rows: list[dict[str, Any]] = []

    stage_started = time.perf_counter()
    nodes_layer_data = _read_vector_layer(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=True,
    )
    drivezone_layer_data = _read_vector_layer(
        drivezone_path,
        layer_name=drivezone_layer,
        crs_override=drivezone_crs,
        allow_null_geometry=False,
    )
    stage_timings["read_inputs_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    drivezone_geoms = [feature.geometry for feature in drivezone_layer_data.features if feature.geometry is not None and not feature.geometry.is_empty]
    if not drivezone_geoms:
        raise T07RunError("missing_required_field", "DriveZone layer has no non-empty geometry.")
    prepared_drivezone = prep(drivezone_geoms[0] if len(drivezone_geoms) == 1 else unary_union(drivezone_geoms))

    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    stage_timings["prepare_semantic_junctions_seconds"] = _elapsed_since(stage_started)
    counts = {
        "semantic_junction_count": len(junction_ids),
        "processed_kind2_count": 0,
        "skipped_kind2_count": 0,
        "has_evd_yes_count": 0,
        "has_evd_no_count": 0,
        "has_evd_null_count": 0,
        "representative_missing_count": 0,
    }

    stage_started = time.perf_counter()
    for junction_id in junction_ids:
        group = _resolve_group(junction_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            counts["representative_missing_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing",
                    junction_id=junction_id,
                )
            )
            continue

        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        kind_2 = _normalize_id(representative_props.get("kind_2"))
        if kind_2 not in ALLOWED_KIND2:
            representative_props["has_evd"] = None
            representative_props["is_anchor"] = None
            representative_props["anchor_reason"] = None
            counts["skipped_kind2_count"] += 1
            counts["has_evd_null_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="kind2_out_of_scope",
                    detail=f"representative kind_2={kind_2} is outside T07 Step1 scope.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                )
            )
            continue

        counts["processed_kind2_count"] += 1
        has_evd = "yes" if any(prepared_drivezone.intersects(record.geometry) for record in group.group_nodes) else "no"
        representative_props["has_evd"] = has_evd
        if has_evd == "yes":
            counts["has_evd_yes_count"] += 1
        else:
            counts["has_evd_no_count"] += 1
    stage_timings["process_has_evd_seconds"] = _elapsed_since(stage_started)

    nodes_output_path = stage_root / "nodes.gpkg"
    summary_path = stage_root / "t07_step1_summary.json"
    audit_csv_path = stage_root / "t07_step1_audit.csv"
    audit_json_path = stage_root / "t07_step1_audit.json"
    perf_path = stage_root / "t07_step1_perf.json"

    stage_started = time.perf_counter()
    _write_nodes(nodes_output_path, nodes_layer_data.features)
    stage_timings["write_nodes_seconds"] = _elapsed_since(stage_started)
    summary = {
        "run_id": resolved_run_id,
        **counts,
        "input_paths": {"nodes": str(nodes_path), "drivezone": str(drivezone_path)},
        "output_paths": {"nodes": str(nodes_output_path)},
        "target_crs": TARGET_CRS.to_string(),
        "audit_count": len(audit_rows),
        "performance": {
            "elapsed_seconds": _elapsed_since(started_at),
            "stage_timings": stage_timings,
        },
    }
    stage_started = time.perf_counter()
    write_json(summary_path, summary)
    _write_csv(audit_csv_path, audit_rows, ["scope", "junction_id", "node_id", "status", "reason", "detail", "kind_2"])
    write_json(audit_json_path, {"run_id": resolved_run_id, "rows": audit_rows})
    stage_timings["write_audit_summary_seconds"] = _elapsed_since(stage_started)
    write_json(
        perf_path,
        {
            "run_id": resolved_run_id,
            "elapsed_sec": _elapsed_since(started_at),
            "stage_timings": stage_timings,
            **counts,
        },
    )
    return T07StageArtifacts(run_root, stage_root, nodes_output_path, summary_path, audit_csv_path, audit_json_path, perf_path)


def _intersection_identity(properties: dict[str, Any], feature_index: int) -> str:
    for field in INTERSECTION_ID_FIELDS:
        value = _normalize_id(properties.get(field))
        if value is not None:
            return value
    return f"feature_{feature_index}"


def _read_intersections(layer: LoadedLayer) -> list[IntersectionRecord]:
    records = []
    for feature in layer.features:
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        records.append(
            IntersectionRecord(
                feature_index=feature.feature_index,
                intersection_id=_intersection_identity(feature.properties, feature.feature_index),
                geometry=feature.geometry,
            )
        )
    if not records:
        raise T07RunError("missing_required_field", "RCSDIntersection layer has no non-empty geometry.")
    return records


def _same_single_intersection_for_all(node_hits: list[tuple[str, ...]]) -> str | None:
    if not node_hits:
        return None
    first_hits = node_hits[0]
    if len(first_hits) != 1:
        return None
    target = first_hits[0]
    if all(hits == (target,) for hits in node_hits):
        return target
    return None


def _write_error_outputs(
    *,
    vector_path: Path,
    audit_csv_path: Path,
    audit_json_path: Path,
    node_features: list[LoadedFeature],
    feature_indexes: set[int],
    metadata: dict[int, dict[str, Any]],
    rows: list[dict[str, Any]],
    run_id: str,
) -> None:
    write_gpkg_sqlite(
        vector_path,
        (
            {
                "properties": {**node_features[index].properties, **metadata.get(index, {})},
                "geometry": node_features[index].geometry,
            }
            for index in sorted(feature_indexes)
        ),
        crs_text=TARGET_CRS.to_string(),
    )
    _write_csv(
        audit_csv_path,
        rows,
        ["scope", "junction_id", "node_id", "status", "reason", "detail", "intersection_ids", "involved_node_ids"],
    )
    write_json(audit_json_path, {"run_id": run_id, "rows": rows})


def run_t07_step2_anchor_recognition(
    *,
    nodes_path: str | Path,
    intersection_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    intersection_layer: str | None = None,
    nodes_crs: str | None = None,
    intersection_crs: str | None = None,
) -> T07StageArtifacts:
    started_at = time.perf_counter()
    stage_timings: dict[str, float] = {}
    run_root, stage_root, resolved_run_id = _stage_root(out_root, run_id, "step2_anchor_recognition")
    stage_root.mkdir(parents=True, exist_ok=True)
    audit_rows: list[dict[str, Any]] = []

    stage_started = time.perf_counter()
    nodes_layer_data = _read_vector_layer(nodes_path, layer_name=nodes_layer, crs_override=nodes_crs, allow_null_geometry=True)
    intersection_layer_data = _read_vector_layer(
        intersection_path,
        layer_name=intersection_layer,
        crs_override=intersection_crs,
        allow_null_geometry=False,
    )
    stage_timings["read_inputs_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    intersections = _read_intersections(intersection_layer_data)
    intersection_tree = STRtree([record.geometry for record in intersections])
    stage_timings["build_intersection_index_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    stage_timings["prepare_semantic_junctions_seconds"] = _elapsed_since(stage_started)
    counts = {
        "semantic_junction_count": len(junction_ids),
        "stage2_candidate_count": 0,
        "anchor_yes_count": 0,
        "anchor_no_count": 0,
        "anchor_fail1_count": 0,
        "anchor_fail2_count": 0,
        "anchor_null_count": 0,
        "roundabout_reason_count": 0,
        "t_reason_count": 0,
    }
    group_results: dict[str, dict[str, Any]] = {}
    intersection_to_junctions: dict[str, set[str]] = {}
    error1_rows: list[dict[str, Any]] = []
    error1_indexes: set[int] = set()
    error1_metadata: dict[int, dict[str, Any]] = {}
    node_hit_cache: dict[int, tuple[str, ...]] = {}

    stage_started = time.perf_counter()
    for junction_id in junction_ids:
        group = _resolve_group(junction_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing",
                    junction_id=junction_id,
                )
            )
            group_results[junction_id] = {"participates": False, "group": group}
            continue

        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        representative_has_evd = _normalize_id(representative_props.get("has_evd"))
        kind_2 = _normalize_id(representative_props.get("kind_2"))
        if representative_has_evd != "yes" or kind_2 not in ALLOWED_KIND2:
            representative_props["is_anchor"] = None
            representative_props["anchor_reason"] = None
            counts["anchor_null_count"] += 1
            group_results[junction_id] = {"participates": False, "group": group}
            continue

        if kind_2 in {"64", "128"}:
            representative_props["is_anchor"] = None
            representative_props["anchor_reason"] = None
            counts["anchor_null_count"] += 1
            group_results[junction_id] = {"participates": False, "group": group}
            continue

        counts["stage2_candidate_count"] += 1
        hit_intersection_ids: set[str] = set()
        group_node_hits: list[tuple[str, ...]] = []
        for record in group.group_nodes:
            cached = node_hit_cache.get(record.output_index)
            if cached is None:
                indexes = intersection_tree.query(record.geometry, predicate="intersects")
                cached = tuple(sorted({intersections[int(index)].intersection_id for index in indexes}))
                node_hit_cache[record.output_index] = cached
            group_node_hits.append(cached)
            for intersection_id in cached:
                hit_intersection_ids.add(intersection_id)

        sorted_hits = sorted(hit_intersection_ids)
        if kind_2 == "2048":
            shared_intersection_id = _same_single_intersection_for_all(group_node_hits)
            if shared_intersection_id is None:
                representative_props["is_anchor"] = None
                representative_props["anchor_reason"] = None
                counts["anchor_null_count"] += 1
            else:
                representative_props["is_anchor"] = "yes"
                representative_props["anchor_reason"] = "t"
                counts["anchor_yes_count"] += 1
                counts["t_reason_count"] += 1
            group_results[junction_id] = {"participates": False, "group": group}
            continue

        for intersection_id in sorted_hits:
            intersection_to_junctions.setdefault(intersection_id, set()).add(junction_id)

        provisional_reason = None

        if not sorted_hits:
            provisional_state = "no"
        elif len(sorted_hits) == 1:
            provisional_state = "yes"
        elif len(group.group_nodes) == 1 or provisional_reason is not None:
            provisional_state = "yes"
        else:
            provisional_state = "fail1"
            involved_node_ids = [record.node_id for record in group.group_nodes]
            error1_rows.append(
                _audit_row(
                    scope="node_error_1",
                    status="error",
                    reason="multiple_intersections_for_group",
                    detail="One semantic junction group intersects more than one RCSDIntersection feature.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    intersection_ids=sorted_hits,
                    involved_node_ids=involved_node_ids,
                )
            )
            for record in group.group_nodes:
                error1_indexes.add(record.output_index)
                error1_metadata[record.output_index] = {
                    "error_type": "node_error_1",
                    "junction_id": junction_id,
                    "representative_node_id": group.representative.node_id,
                    "intersection_ids": ",".join(sorted_hits),
                }

        group_results[junction_id] = {
            "participates": True,
            "group": group,
            "kind_2": kind_2,
            "provisional_state": provisional_state,
            "provisional_reason": provisional_reason if provisional_state == "yes" else None,
            "intersection_ids": sorted_hits,
        }
    stage_timings["process_anchor_candidates_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    fail2_by_junction: dict[str, set[str]] = {}
    for intersection_id, linked_junction_ids in intersection_to_junctions.items():
        filtered = []
        for junction_id in sorted(linked_junction_ids):
            result = group_results.get(junction_id)
            if not result or not result.get("participates"):
                continue
            if result.get("kind_2") == "1":
                continue
            filtered.append(junction_id)
        if len(filtered) <= 1:
            continue
        for junction_id in filtered:
            fail2_by_junction.setdefault(junction_id, set()).add(intersection_id)

    error2_rows: list[dict[str, Any]] = []
    error2_indexes: set[int] = set()
    error2_metadata: dict[int, dict[str, Any]] = {}
    for junction_id, intersection_ids in sorted(fail2_by_junction.items()):
        group = group_results[junction_id]["group"]
        involved_node_ids = [record.node_id for record in group.group_nodes]
        sorted_ids = sorted(intersection_ids)
        error2_rows.append(
            _audit_row(
                scope="node_error_2",
                status="error",
                reason="intersection_shared_by_multiple_groups",
                detail="One RCSDIntersection feature intersects more than one semantic junction group.",
                junction_id=junction_id,
                node_id=group.representative.node_id if group.representative else None,
                intersection_ids=sorted_ids,
                involved_node_ids=involved_node_ids,
            )
        )
        for record in group.group_nodes:
            error2_indexes.add(record.output_index)
            error2_metadata[record.output_index] = {
                "error_type": "node_error_2",
                "junction_id": junction_id,
                "representative_node_id": group.representative.node_id if group.representative else None,
                "intersection_ids": ",".join(sorted_ids),
            }

    for junction_id, result in group_results.items():
        if not result.get("participates"):
            continue
        group = result["group"]
        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        if junction_id in fail2_by_junction:
            final_state = "fail2"
            final_reason = None
        elif result["provisional_state"] == "fail1":
            final_state = "fail1"
            final_reason = None
        elif result["provisional_state"] == "yes":
            final_state = "yes"
            final_reason = result["provisional_reason"]
        else:
            final_state = "no"
            final_reason = None

        representative_props["is_anchor"] = final_state
        representative_props["anchor_reason"] = final_reason
        if final_state == "yes":
            counts["anchor_yes_count"] += 1
        elif final_state == "no":
            counts["anchor_no_count"] += 1
        elif final_state == "fail1":
            counts["anchor_fail1_count"] += 1
        elif final_state == "fail2":
            counts["anchor_fail2_count"] += 1
        if final_reason == "roundabout":
            counts["roundabout_reason_count"] += 1
        elif final_reason == "t":
            counts["t_reason_count"] += 1
    stage_timings["resolve_conflicts_seconds"] = _elapsed_since(stage_started)

    nodes_output_path = stage_root / "nodes.gpkg"
    summary_path = stage_root / "t07_step2_summary.json"
    audit_csv_path = stage_root / "t07_step2_audit.csv"
    audit_json_path = stage_root / "t07_step2_audit.json"
    perf_path = stage_root / "t07_step2_perf.json"
    node_error_1_path = stage_root / "node_error_1.gpkg"
    node_error_2_path = stage_root / "node_error_2.gpkg"

    stage_started = time.perf_counter()
    _write_nodes(nodes_output_path, nodes_layer_data.features)
    stage_timings["write_nodes_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_error_outputs(
        vector_path=node_error_1_path,
        audit_csv_path=stage_root / "node_error_1_audit.csv",
        audit_json_path=stage_root / "node_error_1_audit.json",
        node_features=nodes_layer_data.features,
        feature_indexes=error1_indexes,
        metadata=error1_metadata,
        rows=error1_rows,
        run_id=resolved_run_id,
    )
    _write_error_outputs(
        vector_path=node_error_2_path,
        audit_csv_path=stage_root / "node_error_2_audit.csv",
        audit_json_path=stage_root / "node_error_2_audit.json",
        node_features=nodes_layer_data.features,
        feature_indexes=error2_indexes,
        metadata=error2_metadata,
        rows=error2_rows,
        run_id=resolved_run_id,
    )
    stage_timings["write_error_outputs_seconds"] = _elapsed_since(stage_started)
    summary = {
        "run_id": resolved_run_id,
        **counts,
        "input_paths": {"nodes": str(nodes_path), "intersection": str(intersection_path)},
        "output_paths": {
            "nodes": str(nodes_output_path),
            "node_error_1": str(node_error_1_path),
            "node_error_2": str(node_error_2_path),
        },
        "target_crs": TARGET_CRS.to_string(),
        "audit_count": len(audit_rows),
        "performance": {
            "elapsed_seconds": _elapsed_since(started_at),
            "stage_timings": stage_timings,
        },
    }
    stage_started = time.perf_counter()
    write_json(summary_path, summary)
    _write_csv(audit_csv_path, audit_rows, ["scope", "junction_id", "node_id", "status", "reason", "detail"])
    write_json(audit_json_path, {"run_id": resolved_run_id, "rows": audit_rows})
    stage_timings["write_audit_summary_seconds"] = _elapsed_since(stage_started)
    write_json(
        perf_path,
        {
            "run_id": resolved_run_id,
            "elapsed_sec": _elapsed_since(started_at),
            "stage_timings": stage_timings,
            **counts,
        },
    )
    return T07StageArtifacts(run_root, stage_root, nodes_output_path, summary_path, audit_csv_path, audit_json_path, perf_path)


def run_t07_semantic_junction_anchor(
    *,
    nodes_path: str | Path,
    drivezone_path: str | Path,
    intersection_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    drivezone_layer: str | None = None,
    intersection_layer: str | None = None,
    nodes_crs: str | None = None,
    drivezone_crs: str | None = None,
    intersection_crs: str | None = None,
) -> T07Artifacts:
    resolved_run_id = run_id or build_run_id("t07_semantic_junction_anchor")
    step1 = run_t07_step1_has_evd(
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=out_root,
        run_id=resolved_run_id,
        nodes_layer=nodes_layer,
        drivezone_layer=drivezone_layer,
        nodes_crs=nodes_crs,
        drivezone_crs=drivezone_crs,
    )
    step2 = run_t07_step2_anchor_recognition(
        nodes_path=step1.nodes_path,
        intersection_path=intersection_path,
        out_root=out_root,
        run_id=resolved_run_id,
        intersection_layer=intersection_layer,
        intersection_crs=intersection_crs,
    )
    return T07Artifacts(run_root=step1.run_root, step1=step1, step2=step2)
