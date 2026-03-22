from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import shapefile
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

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


KNOWN_S_GRADE_BUCKETS = ("0-0双", "0-1双", "0-2双")
REASON_JUNCTION_NODES_NOT_FOUND = "junction_nodes_not_found"
REASON_REPRESENTATIVE_NODE_MISSING = "representative_node_missing"
REASON_NO_TARGET_JUNCTIONS = "no_target_junctions"
REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"


class Stage1RunError(ValueError):
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
class JunctionResult:
    junction_id: str
    has_evd: str
    representative_output_index: int | None
    reason: str | None
    detail: str | None


@dataclass(frozen=True)
class Stage1Artifacts:
    success: bool
    out_root: Path
    nodes_path: Path | None
    segment_path: Path | None
    summary_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    log_path: Path
    summary: dict[str, Any]


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
    resolved_run_id = run_id or build_run_id("t02_stage1_drivezone_gate")
    if out_root is not None:
        return Path(out_root), resolved_run_id

    repo_root = _find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise Stage1RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_stage1_drivezone_gate" / resolved_run_id, resolved_run_id


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
    if not text:
        return None
    if text.lower() in {"null", "none", "nan"}:
        return None
    return text


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stage1RunError(REASON_INVALID_CRS_OR_UNPROJECTABLE, f"Failed to read GeoJSON '{path}': {exc}") from exc


def _resolve_geojson_crs_strict(doc: dict[str, Any], crs_override: Optional[str]) -> tuple[CRS, str]:
    if crs_override:
        try:
            return CRS.from_user_input(crs_override), "override"
        except Exception as exc:
            raise Stage1RunError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Invalid CRS override '{crs_override}': {exc}",
            ) from exc

    crs_payload = doc.get("crs")
    if isinstance(crs_payload, dict):
        props = crs_payload.get("properties") or {}
        name = props.get("name")
        if name:
            try:
                return CRS.from_user_input(name), "geojson.crs"
            except Exception as exc:
                raise Stage1RunError(
                    REASON_INVALID_CRS_OR_UNPROJECTABLE,
                    f"Invalid GeoJSON CRS '{name}': {exc}",
                ) from exc

    raise Stage1RunError(
        REASON_INVALID_CRS_OR_UNPROJECTABLE,
        "GeoJSON is missing CRS metadata and no CRS override was provided.",
    )


def _resolve_shapefile_crs_strict(path: Path, crs_override: Optional[str]) -> tuple[CRS, str]:
    if crs_override:
        try:
            return CRS.from_user_input(crs_override), "override"
        except Exception as exc:
            raise Stage1RunError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Invalid CRS override '{crs_override}': {exc}",
            ) from exc

    prj_path = path.with_suffix(".prj")
    if prj_path.is_file():
        try:
            return CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore")), "shapefile.prj"
        except Exception as exc:
            raise Stage1RunError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Failed to parse shapefile .prj for '{path}': {exc}",
            ) from exc

    raise Stage1RunError(
        REASON_INVALID_CRS_OR_UNPROJECTABLE,
        f"Shapefile '{path}' has no .prj and no CRS override was provided.",
    )


def _transform_geometry(
    geometry: BaseGeometry | None,
    *,
    source_crs: CRS,
    layer_label: str,
    feature_index: int,
) -> BaseGeometry | None:
    if geometry is None:
        return None
    try:
        return transform_geometry_to_target(geometry, source_crs, TARGET_CRS)
    except Exception as exc:
        raise Stage1RunError(
            REASON_INVALID_CRS_OR_UNPROJECTABLE,
            f"{layer_label} feature[{feature_index}] failed to transform to EPSG:3857: {exc}",
        ) from exc


def _read_vector_layer_strict(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
    allow_null_geometry: bool,
) -> LoadedLayer:
    del layer_name
    layer_path = Path(path)
    if not layer_path.is_file():
        raise Stage1RunError(
            REASON_MISSING_REQUIRED_FIELD,
            f"Input layer does not exist: {layer_path}",
        )

    suffix = layer_path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        doc = _load_json(layer_path)
        source_crs, crs_source = _resolve_geojson_crs_strict(doc, crs_override)
        features: list[LoadedFeature] = []
        for feature_index, feature in enumerate(doc.get("features", [])):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None and not allow_null_geometry:
                raise Stage1RunError(
                    REASON_MISSING_REQUIRED_FIELD,
                    f"{layer_path} feature[{feature_index}] is missing geometry.",
                )
            geometry = None if geometry_payload is None else _transform_geometry(
                shape(geometry_payload),
                source_crs=source_crs,
                layer_label=str(layer_path),
                feature_index=feature_index,
            )
            features.append(
                LoadedFeature(
                    feature_index=feature_index,
                    properties=dict(feature.get("properties") or {}),
                    geometry=geometry,
                )
            )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix == ".shp":
        source_crs, crs_source = _resolve_shapefile_crs_strict(layer_path, crs_override)
        try:
            reader = shapefile.Reader(str(layer_path))
        except Exception as exc:
            raise Stage1RunError(
                REASON_INVALID_CRS_OR_UNPROJECTABLE,
                f"Failed to read shapefile '{layer_path}': {exc}",
            ) from exc

        field_names = [field[0] for field in reader.fields[1:]]
        features = []
        for feature_index, shape_record in enumerate(reader.iterShapeRecords()):
            geometry_payload = shape_record.shape.__geo_interface__
            geometry = _transform_geometry(
                shape(geometry_payload),
                source_crs=source_crs,
                layer_label=str(layer_path),
                feature_index=feature_index,
            )
            features.append(
                LoadedFeature(
                    feature_index=feature_index,
                    properties=dict(zip(field_names, list(shape_record.record))),
                    geometry=geometry,
                )
            )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    raise Stage1RunError(
        REASON_MISSING_REQUIRED_FIELD,
        f"Unsupported vector format for '{layer_path}'. Expected GeoJSON or Shapefile.",
    )


def _parse_junction_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return [item for item in (_normalize_id(item) for item in parsed) if item is not None]
        return [item for item in (_normalize_id(part) for part in stripped.split(",")) if item is not None]
    if isinstance(value, (list, tuple, set)):
        return [item for item in (_normalize_id(part) for part in value) if item is not None]
    normalized = _normalize_id(value)
    return [] if normalized is None else [normalized]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _segment_grade(properties: dict[str, Any]) -> tuple[str | None, str | None]:
    if "s_grade" in properties:
        return "s_grade", _normalize_id(properties.get("s_grade"))
    if "sgrade" in properties:
        return "sgrade", _normalize_id(properties.get("sgrade"))
    return None, None


def _audit_row(
    *,
    scope: str,
    status: str,
    reason: str,
    detail: str,
    segment_id: str | None = None,
    junction_id: str | None = None,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "segment_id": segment_id,
        "junction_id": junction_id,
        "status": status,
        "reason": reason,
        "detail": detail,
    }


def _write_failure_outputs(
    *,
    out_root: Path,
    run_id: str,
    audit_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Stage1Artifacts:
    audit_csv_path = out_root / "t02_stage1_audit.csv"
    audit_json_path = out_root / "t02_stage1_audit.json"
    summary_path = out_root / "t02_stage1_summary.json"
    write_csv(
        audit_csv_path,
        audit_rows,
        ["scope", "segment_id", "junction_id", "status", "reason", "detail"],
    )
    write_json(
        audit_json_path,
        {
            "run_id": run_id,
            "audit_count": len(audit_rows),
            "rows": audit_rows,
        },
    )
    write_json(summary_path, summary)
    return Stage1Artifacts(
        success=False,
        out_root=out_root,
        nodes_path=None,
        segment_path=None,
        summary_path=summary_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        log_path=out_root / "t02_stage1.log",
        summary=summary,
    )


def run_t02_stage1_drivezone_gate(
    *,
    segment_path: Union[str, Path],
    nodes_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    segment_layer: Optional[str] = None,
    nodes_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    segment_crs: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
) -> Stage1Artifacts:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    log_path = resolved_out_root / "t02_stage1.log"
    logger = build_logger(log_path, f"t02_stage1_drivezone_gate.{resolved_run_id}")
    audit_rows: list[dict[str, Any]] = []

    try:
        announce(logger, f"[T02] stage1 start run_id={resolved_run_id}")
        segment_layer_data = _read_vector_layer_strict(
            segment_path,
            layer_name=segment_layer,
            crs_override=segment_crs,
            allow_null_geometry=True,
        )
        nodes_layer_data = _read_vector_layer_strict(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=True,
        )
        drivezone_layer_data = _read_vector_layer_strict(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
        )

        announce(
            logger,
            "[T02] loaded "
            f"segment_features={len(segment_layer_data.features)} "
            f"node_features={len(nodes_layer_data.features)} "
            f"drivezone_features={len(drivezone_layer_data.features)}",
        )

        drivezone_geometries = [
            feature.geometry
            for feature in drivezone_layer_data.features
            if feature.geometry is not None and not feature.geometry.is_empty
        ]
        if not drivezone_geometries:
            raise Stage1RunError(
                REASON_MISSING_REQUIRED_FIELD,
                "DriveZone layer has no non-empty geometry features after projection to EPSG:3857.",
            )
        drivezone_union = unary_union(drivezone_geometries)
        if drivezone_union.is_empty:
            raise Stage1RunError(
                REASON_MISSING_REQUIRED_FIELD,
                "DriveZone union is empty after projection to EPSG:3857.",
            )

        node_output_features: list[dict[str, Any]] = []
        nodes_by_mainnodeid: dict[str, list[NodeRecord]] = {}
        singleton_nodes_by_id: dict[str, list[NodeRecord]] = {}

        for output_index, feature in enumerate(nodes_layer_data.features):
            properties = dict(feature.properties)
            properties["has_evd"] = None
            node_output_features.append({"properties": properties, "geometry": feature.geometry})

            missing_fields: list[str] = []
            if "id" not in feature.properties:
                missing_fields.append("id")
            if "mainnodeid" not in feature.properties:
                missing_fields.append("mainnodeid")
            node_id = _normalize_id(feature.properties.get("id"))
            mainnodeid = _normalize_id(feature.properties.get("mainnodeid"))
            if node_id is None:
                missing_fields.append("id_value")
            if feature.geometry is None or feature.geometry.is_empty:
                missing_fields.append("geometry")
            if missing_fields:
                audit_rows.append(
                    _audit_row(
                        scope="node",
                        status="error",
                        reason=REASON_MISSING_REQUIRED_FIELD,
                        detail=f"node feature[{feature.feature_index}] missing/invalid: {','.join(missing_fields)}",
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
            if mainnodeid is not None:
                nodes_by_mainnodeid.setdefault(mainnodeid, []).append(record)
            else:
                singleton_nodes_by_id.setdefault(node_id, []).append(record)

        segment_output_features: list[dict[str, Any]] = []
        referenced_junctions: set[str] = set()
        segment_contexts: list[dict[str, Any]] = []

        for feature in segment_layer_data.features:
            properties = dict(feature.properties)
            segment_id = _normalize_id(properties.get("id"))
            grade_field, grade_value = _segment_grade(properties)
            missing_fields: list[str] = []
            if "id" not in properties:
                missing_fields.append("id")
            if "pair_nodes" not in properties:
                missing_fields.append("pair_nodes")
            if "junc_nodes" not in properties:
                missing_fields.append("junc_nodes")
            if grade_field is None:
                missing_fields.append("s_grade|sgrade")
            if segment_id is None:
                missing_fields.append("id_value")

            junction_ids: list[str] = []
            if not missing_fields:
                junction_ids = _dedupe_preserve_order(
                    _parse_junction_values(properties.get("pair_nodes"))
                    + _parse_junction_values(properties.get("junc_nodes"))
                )
                referenced_junctions.update(junction_ids)

            properties["has_evd"] = "no" if missing_fields else None
            segment_output_features.append({"properties": properties, "geometry": feature.geometry})
            segment_contexts.append(
                {
                    "feature_index": feature.feature_index,
                    "segment_id": segment_id,
                    "s_grade": grade_value,
                    "junction_ids": junction_ids,
                    "missing_fields": missing_fields,
                }
            )

        junction_results: dict[str, JunctionResult] = {}
        for junction_id in sorted(referenced_junctions):
            group_nodes = nodes_by_mainnodeid.get(junction_id)
            if group_nodes:
                representatives = [record for record in group_nodes if record.node_id == junction_id]
                if not representatives:
                    junction_results[junction_id] = JunctionResult(
                        junction_id=junction_id,
                        has_evd="no",
                        representative_output_index=None,
                        reason=REASON_REPRESENTATIVE_NODE_MISSING,
                        detail=(
                            f"junction_id='{junction_id}' matched mainnodeid group but no node with id == junction_id exists."
                        ),
                    )
                    continue
                representative = representatives[0]
                value = "yes" if any(record.geometry.intersects(drivezone_union) for record in group_nodes) else "no"
                node_output_features[representative.output_index]["properties"]["has_evd"] = value
                junction_results[junction_id] = JunctionResult(
                    junction_id=junction_id,
                    has_evd=value,
                    representative_output_index=representative.output_index,
                    reason=None,
                    detail=None,
                )
                continue

            singleton_candidates = singleton_nodes_by_id.get(junction_id) or []
            if singleton_candidates:
                representative = singleton_candidates[0]
                value = "yes" if representative.geometry.intersects(drivezone_union) else "no"
                node_output_features[representative.output_index]["properties"]["has_evd"] = value
                junction_results[junction_id] = JunctionResult(
                    junction_id=junction_id,
                    has_evd=value,
                    representative_output_index=representative.output_index,
                    reason=None,
                    detail=None,
                )
                continue

            junction_results[junction_id] = JunctionResult(
                junction_id=junction_id,
                has_evd="no",
                representative_output_index=None,
                reason=REASON_JUNCTION_NODES_NOT_FOUND,
                detail=f"junction_id='{junction_id}' has neither mainnodeid group nor singleton fallback node.",
            )

        bucket_summary: dict[str, dict[str, Any]] = {
            bucket: {
                "segment_count": 0,
                "segment_has_evd_count": 0,
                "junction_count": 0,
                "junction_has_evd_count": 0,
            }
            for bucket in KNOWN_S_GRADE_BUCKETS
        }
        bucket_junction_sets: dict[str, set[str]] = {bucket: set() for bucket in KNOWN_S_GRADE_BUCKETS}
        bucket_yes_junction_sets: dict[str, set[str]] = {bucket: set() for bucket in KNOWN_S_GRADE_BUCKETS}

        for output_index, context in enumerate(segment_contexts):
            segment_id = context["segment_id"]
            s_grade = context["s_grade"]
            missing_fields = context["missing_fields"]
            junction_ids = context["junction_ids"]

            if missing_fields:
                audit_rows.append(
                    _audit_row(
                        scope="segment",
                        status="error",
                        reason=REASON_MISSING_REQUIRED_FIELD,
                        detail=(
                            f"segment feature[{context['feature_index']}] missing required fields: "
                            + ",".join(missing_fields)
                        ),
                        segment_id=segment_id,
                    )
                )
            elif not junction_ids:
                segment_output_features[output_index]["properties"]["has_evd"] = "no"
                audit_rows.append(
                    _audit_row(
                        scope="segment",
                        status="error",
                        reason=REASON_NO_TARGET_JUNCTIONS,
                        detail="pair_nodes + junc_nodes resolved to an empty target junction set after dedupe.",
                        segment_id=segment_id,
                    )
                )
            else:
                segment_has_evd = all(junction_results[junction_id].has_evd == "yes" for junction_id in junction_ids)
                segment_output_features[output_index]["properties"]["has_evd"] = "yes" if segment_has_evd else "no"
                for junction_id in junction_ids:
                    junction_result = junction_results[junction_id]
                    if junction_result.reason is None:
                        continue
                    audit_rows.append(
                        _audit_row(
                            scope="junction",
                            status="error",
                            reason=junction_result.reason,
                            detail=junction_result.detail or junction_result.reason,
                            segment_id=segment_id,
                            junction_id=junction_id,
                        )
                    )

            if s_grade in KNOWN_S_GRADE_BUCKETS:
                bucket_summary[s_grade]["segment_count"] += 1
                if segment_output_features[output_index]["properties"].get("has_evd") == "yes":
                    bucket_summary[s_grade]["segment_has_evd_count"] += 1
                for junction_id in junction_ids:
                    bucket_junction_sets[s_grade].add(junction_id)
                    if junction_results[junction_id].has_evd == "yes":
                        bucket_yes_junction_sets[s_grade].add(junction_id)

        for bucket in KNOWN_S_GRADE_BUCKETS:
            bucket_summary[bucket]["junction_count"] = len(bucket_junction_sets[bucket])
            bucket_summary[bucket]["junction_has_evd_count"] = len(bucket_yes_junction_sets[bucket])

        output_nodes_path = resolved_out_root / "nodes.geojson"
        output_segment_path = resolved_out_root / "segment.geojson"
        summary_path = resolved_out_root / "t02_stage1_summary.json"
        audit_csv_path = resolved_out_root / "t02_stage1_audit.csv"
        audit_json_path = resolved_out_root / "t02_stage1_audit.json"

        write_geojson(output_nodes_path, node_output_features, crs_text=TARGET_CRS.to_string())
        write_geojson(output_segment_path, segment_output_features, crs_text=TARGET_CRS.to_string())
        write_csv(
            audit_csv_path,
            audit_rows,
            ["scope", "segment_id", "junction_id", "status", "reason", "detail"],
        )
        write_json(
            audit_json_path,
            {
                "run_id": resolved_run_id,
                "audit_count": len(audit_rows),
                "rows": audit_rows,
            },
        )

        segment_has_evd_count = sum(
            1 for feature in segment_output_features if feature["properties"].get("has_evd") == "yes"
        )
        summary = {
            "run_id": resolved_run_id,
            "success": True,
            "target_crs": TARGET_CRS.to_string(),
            "inputs": {
                "segment_path": str(Path(segment_path)),
                "nodes_path": str(Path(nodes_path)),
                "drivezone_path": str(Path(drivezone_path)),
                "segment_crs_override": segment_crs,
                "nodes_crs_override": nodes_crs,
                "drivezone_crs_override": drivezone_crs,
            },
            "counts": {
                "segment_feature_count": len(segment_output_features),
                "segment_has_evd_count": segment_has_evd_count,
                "node_feature_count": len(node_output_features),
                "representative_node_written_count": sum(
                    1 for feature in node_output_features if feature["properties"].get("has_evd") in {"yes", "no"}
                ),
                "junction_count": len(junction_results),
                "junction_has_evd_count": sum(1 for item in junction_results.values() if item.has_evd == "yes"),
                "audit_count": len(audit_rows),
            },
            "summary_by_s_grade": bucket_summary,
            "output_files": [
                output_nodes_path.name,
                output_segment_path.name,
                summary_path.name,
                audit_csv_path.name,
                audit_json_path.name,
                log_path.name,
            ],
        }
        write_json(summary_path, summary)

        announce(
            logger,
            "[T02] wrote outputs "
            f"segment_has_evd_count={segment_has_evd_count} "
            f"junction_count={len(junction_results)} "
            f"audit_count={len(audit_rows)} "
            f"out_root={resolved_out_root}",
        )

        return Stage1Artifacts(
            success=True,
            out_root=resolved_out_root,
            nodes_path=output_nodes_path,
            segment_path=output_segment_path,
            summary_path=summary_path,
            audit_csv_path=audit_csv_path,
            audit_json_path=audit_json_path,
            log_path=log_path,
            summary=summary,
        )
    except Stage1RunError as exc:
        audit_rows.append(
            _audit_row(
                scope="run",
                status="error",
                reason=exc.reason,
                detail=exc.detail,
            )
        )
        summary = {
            "run_id": resolved_run_id,
            "success": False,
            "target_crs": TARGET_CRS.to_string(),
            "inputs": {
                "segment_path": str(Path(segment_path)),
                "nodes_path": str(Path(nodes_path)),
                "drivezone_path": str(Path(drivezone_path)),
                "segment_crs_override": segment_crs,
                "nodes_crs_override": nodes_crs,
                "drivezone_crs_override": drivezone_crs,
            },
            "counts": {
                "segment_feature_count": 0,
                "segment_has_evd_count": 0,
                "node_feature_count": 0,
                "representative_node_written_count": 0,
                "junction_count": 0,
                "junction_has_evd_count": 0,
                "audit_count": len(audit_rows),
            },
            "summary_by_s_grade": {
                bucket: {
                    "segment_count": 0,
                    "segment_has_evd_count": 0,
                    "junction_count": 0,
                    "junction_has_evd_count": 0,
                }
                for bucket in KNOWN_S_GRADE_BUCKETS
            },
            "fatal_error": {
                "reason": exc.reason,
                "detail": exc.detail,
            },
            "output_files": [
                "t02_stage1_summary.json",
                "t02_stage1_audit.csv",
                "t02_stage1_audit.json",
                "t02_stage1.log",
            ],
        }
        announce(logger, f"[T02] stage1 failed reason={exc.reason} detail={exc.detail}")
        return _write_failure_outputs(
            out_root=resolved_out_root,
            run_id=resolved_run_id,
            audit_rows=audit_rows,
            summary=summary,
        )
    finally:
        close_logger(logger)


def run_t02_stage1_drivezone_gate_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=args.segment_path,
        nodes_path=args.nodes_path,
        drivezone_path=args.drivezone_path,
        out_root=args.out_root,
        run_id=args.run_id,
        segment_layer=args.segment_layer,
        nodes_layer=args.nodes_layer,
        drivezone_layer=args.drivezone_layer,
        segment_crs=args.segment_crs,
        nodes_crs=args.nodes_crs,
        drivezone_crs=args.drivezone_crs,
    )
    if artifacts.success:
        print(f"T02 stage1 outputs written to: {artifacts.out_root}")
        return 0
    print(f"T02 stage1 failed; audit written to: {artifacts.out_root}")
    return 1
