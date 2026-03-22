from __future__ import annotations

import argparse
import gc
import json
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import shapefile
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep

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
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    T02RunError,
    audit_row as shared_audit_row,
    normalize_id as shared_normalize_id,
    read_vector_layer_strict as shared_read_vector_layer_strict,
    resolve_junction_group as shared_resolve_junction_group,
)


KNOWN_S_GRADE_BUCKETS = ("0-0双", "0-1双", "0-2双")
ALL_D_SGRADE_BUCKET = "all__d_sgrade"
REASON_JUNCTION_NODES_NOT_FOUND = "junction_nodes_not_found"
REASON_REPRESENTATIVE_NODE_MISSING = "representative_node_missing"
REASON_NO_TARGET_JUNCTIONS = "no_target_junctions"
REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"

NODE_PROGRESS_INTERVAL = 10_000
SEGMENT_PROGRESS_INTERVAL = 5_000
JUNCTION_PROGRESS_INTERVAL = 5_000


class Stage1RunError(T02RunError):
    pass


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
    progress_path: Path
    perf_json_path: Path
    perf_markers_path: Path
    summary: dict[str, Any]


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = _find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise Stage1RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_stage1_drivezone_gate" / resolved_run_id, resolved_run_id


def _normalize_id(value: Any) -> str | None:
    return shared_normalize_id(value)


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
    return shared_read_vector_layer_strict(
        path,
        layer_name=layer_name,
        crs_override=crs_override,
        allow_null_geometry=allow_null_geometry,
        error_cls=Stage1RunError,
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
    return shared_audit_row(
        scope=scope,
        status=status,
        reason=reason,
        detail=detail,
        segment_id=segment_id,
        junction_id=junction_id,
    )


def _empty_bucket_summary() -> dict[str, dict[str, int]]:
    return {
        bucket: {
            "segment_count": 0,
            "segment_has_evd_count": 0,
            "junction_count": 0,
            "junction_has_evd_count": 0,
        }
        for bucket in (*KNOWN_S_GRADE_BUCKETS, ALL_D_SGRADE_BUCKET)
    }


def _write_perf_snapshot(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)


def _record_perf_marker(
    *,
    out_path: Path,
    run_id: str,
    stage: str,
    elapsed_sec: float,
    counts: dict[str, Any],
    note: str | None = None,
) -> None:
    marker = {
        "event": "stage_marker",
        "run_id": run_id,
        "at": _now_text(),
        "stage": stage,
        "elapsed_sec": round(elapsed_sec, 6),
        "counts": counts,
        **_tracemalloc_stats(),
    }
    if note is not None:
        marker["note"] = note
    _append_jsonl(out_path, marker)


def _write_failure_outputs(
    *,
    out_root: Path,
    run_id: str,
    audit_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    log_path: Path,
    progress_path: Path,
    perf_json_path: Path,
    perf_markers_path: Path,
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
        log_path=log_path,
        progress_path=progress_path,
        perf_json_path=perf_json_path,
        perf_markers_path=perf_markers_path,
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
    progress_path = resolved_out_root / "t02_stage1_progress.json"
    perf_json_path = resolved_out_root / "t02_stage1_perf.json"
    perf_markers_path = resolved_out_root / "t02_stage1_perf_markers.jsonl"
    logger = build_logger(log_path, f"t02_stage1_drivezone_gate.{resolved_run_id}")
    audit_rows: list[dict[str, Any]] = []
    stage_counts: dict[str, Any] = {
        "segment_feature_count": 0,
        "segment_has_evd_count": 0,
        "node_feature_count": 0,
        "valid_node_count": 0,
        "representative_node_written_count": 0,
        "junction_count": 0,
        "junction_has_evd_count": 0,
        "drivezone_feature_count": 0,
        "audit_count": 0,
    }
    stage_timings: list[dict[str, Any]] = []
    run_started_at = time.perf_counter()
    started_tracemalloc = False

    if not tracemalloc.is_tracing():
        tracemalloc.start()
        started_tracemalloc = True

    def _snapshot(status: str, current_stage: str | None, message: str) -> None:
        stage_counts["audit_count"] = len(audit_rows)
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status=status,
            current_stage=current_stage,
            message=message,
            counts=dict(stage_counts),
        )

    def _mark_stage(stage_name: str, started_at: float, note: str | None = None) -> None:
        elapsed_sec = time.perf_counter() - started_at
        stage_record = {
            "stage": stage_name,
            "elapsed_sec": round(elapsed_sec, 6),
            **_tracemalloc_stats(),
        }
        if note is not None:
            stage_record["note"] = note
        stage_timings.append(stage_record)
        _record_perf_marker(
            out_path=perf_markers_path,
            run_id=resolved_run_id,
            stage=stage_name,
            elapsed_sec=elapsed_sec,
            counts=dict(stage_counts),
            note=note,
        )

    try:
        _snapshot("running", "bootstrap", "Stage1 bootstrap started.")
        announce(logger, f"[T02] stage1 start run_id={resolved_run_id}")

        read_started_at = time.perf_counter()
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

        stage_counts["segment_feature_count"] = len(segment_layer_data.features)
        stage_counts["node_feature_count"] = len(nodes_layer_data.features)
        stage_counts["drivezone_feature_count"] = len(drivezone_layer_data.features)

        announce(
            logger,
            "[T02] loaded "
            f"segment_features={len(segment_layer_data.features)} "
            f"node_features={len(nodes_layer_data.features)} "
            f"drivezone_features={len(drivezone_layer_data.features)}",
        )
        _snapshot("running", "inputs_loaded", "Input layers loaded and projected to EPSG:3857.")
        _mark_stage("inputs_loaded", read_started_at)

        drivezone_started_at = time.perf_counter()
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
        drivezone_union = drivezone_geometries[0] if len(drivezone_geometries) == 1 else unary_union(drivezone_geometries)
        if drivezone_union.is_empty:
            raise Stage1RunError(
                REASON_MISSING_REQUIRED_FIELD,
                "DriveZone union is empty after projection to EPSG:3857.",
            )
        prepared_drivezone = prep(drivezone_union)
        del drivezone_geometries
        gc.collect()
        announce(logger, "[T02] drivezone prepared target_crs=EPSG:3857")
        _snapshot("running", "drivezone_prepared", "DriveZone geometry prepared.")
        _mark_stage("drivezone_prepared", drivezone_started_at)

        node_index_started_at = time.perf_counter()
        nodes_by_mainnodeid: dict[str, list[NodeRecord]] = {}
        singleton_nodes_by_id: dict[str, list[NodeRecord]] = {}

        for output_index, feature in enumerate(nodes_layer_data.features):
            feature.properties["has_evd"] = None

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

            stage_counts["valid_node_count"] += 1
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

            if (output_index + 1) % NODE_PROGRESS_INTERVAL == 0:
                message = (
                    f"Indexed node_features={output_index + 1}/{len(nodes_layer_data.features)} "
                    f"valid_nodes={stage_counts['valid_node_count']}"
                )
                announce(logger, f"[T02] {message}")
                _snapshot("running", "build_node_index", message)

        announce(
            logger,
            "[T02] node index built "
            f"valid_nodes={stage_counts['valid_node_count']} "
            f"mainnode_groups={len(nodes_by_mainnodeid)} "
            f"singleton_candidates={len(singleton_nodes_by_id)}",
        )
        _snapshot("running", "node_index_built", "Node index built.")
        _mark_stage("node_index_built", node_index_started_at)

        segment_scan_started_at = time.perf_counter()
        referenced_junctions: set[str] = set()
        segment_contexts: list[dict[str, Any]] = []

        for output_index, feature in enumerate(segment_layer_data.features):
            properties = feature.properties
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
            segment_contexts.append(
                {
                    "feature_index": feature.feature_index,
                    "output_index": output_index,
                    "segment_id": segment_id,
                    "s_grade": grade_value,
                    "junction_ids": junction_ids,
                    "missing_fields": missing_fields,
                }
            )

            if (output_index + 1) % SEGMENT_PROGRESS_INTERVAL == 0:
                message = (
                    f"Scanned segment_features={output_index + 1}/{len(segment_layer_data.features)} "
                    f"referenced_junctions={len(referenced_junctions)}"
                )
                announce(logger, f"[T02] {message}")
                _snapshot("running", "scan_segments", message)

        announce(
            logger,
            "[T02] segment scan built "
            f"segment_contexts={len(segment_contexts)} "
            f"referenced_junctions={len(referenced_junctions)}",
        )
        _snapshot("running", "segment_scan_done", "Segment contexts built.")
        _mark_stage("segment_scan_done", segment_scan_started_at)

        junction_gate_started_at = time.perf_counter()
        junction_results: dict[str, JunctionResult] = {}
        referenced_junction_ids = sorted(referenced_junctions)
        stage_counts["junction_count"] = len(referenced_junction_ids)
        for junction_index, junction_id in enumerate(referenced_junction_ids, start=1):
            resolved_group = shared_resolve_junction_group(
                junction_id,
                nodes_by_mainnodeid=nodes_by_mainnodeid,
                singleton_nodes_by_id=singleton_nodes_by_id,
                representative_missing_reason=REASON_REPRESENTATIVE_NODE_MISSING,
                junction_not_found_reason=REASON_JUNCTION_NODES_NOT_FOUND,
            )
            if resolved_group.reason is not None or resolved_group.representative is None:
                junction_results[junction_id] = JunctionResult(
                    junction_id=junction_id,
                    has_evd="no",
                    representative_output_index=None,
                    reason=resolved_group.reason,
                    detail=resolved_group.detail,
                )
            else:
                representative = resolved_group.representative
                group_nodes = resolved_group.group_nodes
                value = "yes" if any(prepared_drivezone.intersects(record.geometry) for record in group_nodes) else "no"
                nodes_layer_data.features[representative.output_index].properties["has_evd"] = value
                junction_results[junction_id] = JunctionResult(
                    junction_id=junction_id,
                    has_evd=value,
                    representative_output_index=representative.output_index,
                    reason=None,
                    detail=None,
                )
                if value == "yes":
                    stage_counts["junction_has_evd_count"] += 1

            if junction_index % JUNCTION_PROGRESS_INTERVAL == 0:
                message = (
                    f"Processed junctions={junction_index}/{len(referenced_junction_ids)} "
                    f"junction_has_evd_count={stage_counts['junction_has_evd_count']}"
                )
                announce(logger, f"[T02] {message}")
                _snapshot("running", "junction_gate", message)

        stage_counts["representative_node_written_count"] = sum(
            1 for feature in nodes_layer_data.features if feature.properties.get("has_evd") in {"yes", "no"}
        )
        announce(
            logger,
            "[T02] junction gate completed "
            f"junction_count={stage_counts['junction_count']} "
            f"junction_has_evd_count={stage_counts['junction_has_evd_count']} "
            f"representative_node_written_count={stage_counts['representative_node_written_count']}",
        )
        _snapshot("running", "junction_gate_done", "Junction gate completed.")
        _mark_stage("junction_gate_done", junction_gate_started_at)

        segment_finalize_started_at = time.perf_counter()
        bucket_summary = _empty_bucket_summary()
        bucket_keys = tuple(bucket_summary)
        bucket_junction_sets: dict[str, set[str]] = {bucket: set() for bucket in bucket_keys}
        bucket_yes_junction_sets: dict[str, set[str]] = {bucket: set() for bucket in bucket_keys}

        for context_index, context in enumerate(segment_contexts, start=1):
            segment_id = context["segment_id"]
            s_grade = context["s_grade"]
            missing_fields = context["missing_fields"]
            junction_ids = context["junction_ids"]
            output_index = context["output_index"]
            segment_properties = segment_layer_data.features[output_index].properties

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
                segment_properties["has_evd"] = "no"
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
                segment_properties["has_evd"] = "yes" if segment_has_evd else "no"
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
                if segment_properties.get("has_evd") == "yes":
                    bucket_summary[s_grade]["segment_has_evd_count"] += 1
                for junction_id in junction_ids:
                    bucket_junction_sets[s_grade].add(junction_id)
                    if junction_results[junction_id].has_evd == "yes":
                        bucket_yes_junction_sets[s_grade].add(junction_id)

            if s_grade is not None:
                bucket_summary[ALL_D_SGRADE_BUCKET]["segment_count"] += 1
                if segment_properties.get("has_evd") == "yes":
                    bucket_summary[ALL_D_SGRADE_BUCKET]["segment_has_evd_count"] += 1
                for junction_id in junction_ids:
                    bucket_junction_sets[ALL_D_SGRADE_BUCKET].add(junction_id)
                    if junction_results[junction_id].has_evd == "yes":
                        bucket_yes_junction_sets[ALL_D_SGRADE_BUCKET].add(junction_id)

            if context_index % SEGMENT_PROGRESS_INTERVAL == 0:
                message = (
                    f"Finalized segments={context_index}/{len(segment_contexts)} "
                    f"audit_count={len(audit_rows)}"
                )
                announce(logger, f"[T02] {message}")
                _snapshot("running", "finalize_segments", message)

        for bucket in bucket_keys:
            bucket_summary[bucket]["junction_count"] = len(bucket_junction_sets[bucket])
            bucket_summary[bucket]["junction_has_evd_count"] = len(bucket_yes_junction_sets[bucket])

        stage_counts["segment_has_evd_count"] = sum(
            1 for feature in segment_layer_data.features if feature.properties.get("has_evd") == "yes"
        )
        stage_counts["audit_count"] = len(audit_rows)
        announce(
            logger,
            "[T02] segment finalize completed "
            f"segment_has_evd_count={stage_counts['segment_has_evd_count']} "
            f"audit_count={stage_counts['audit_count']}",
        )
        _snapshot("running", "segment_finalize_done", "Segment outputs and summary counters computed.")
        _mark_stage("segment_finalize_done", segment_finalize_started_at)

        output_nodes_path = resolved_out_root / "nodes.geojson"
        output_segment_path = resolved_out_root / "segment.geojson"
        summary_path = resolved_out_root / "t02_stage1_summary.json"
        audit_csv_path = resolved_out_root / "t02_stage1_audit.csv"
        audit_json_path = resolved_out_root / "t02_stage1_audit.json"

        node_write_started_at = time.perf_counter()
        write_geojson(
            output_nodes_path,
            (
                {
                    "properties": feature.properties,
                    "geometry": feature.geometry,
                }
                for feature in nodes_layer_data.features
            ),
            crs_text=TARGET_CRS.to_string(),
        )
        announce(logger, f"[T02] nodes written path={output_nodes_path}")
        _snapshot("running", "nodes_written", "nodes.geojson written.")
        _mark_stage("nodes_written", node_write_started_at)

        segment_write_started_at = time.perf_counter()
        write_geojson(
            output_segment_path,
            (
                {
                    "properties": feature.properties,
                    "geometry": feature.geometry,
                }
                for feature in segment_layer_data.features
            ),
            crs_text=TARGET_CRS.to_string(),
        )
        announce(logger, f"[T02] segment written path={output_segment_path}")
        _snapshot("running", "segment_written", "segment.geojson written.")
        _mark_stage("segment_written", segment_write_started_at)

        audit_write_started_at = time.perf_counter()
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
        _mark_stage("audit_written", audit_write_started_at)

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
            "counts": dict(stage_counts),
            "stage_timings": stage_timings,
            "summary_by_s_grade": bucket_summary,
            "output_files": [
                output_nodes_path.name,
                output_segment_path.name,
                summary_path.name,
                audit_csv_path.name,
                audit_json_path.name,
                log_path.name,
                progress_path.name,
                perf_json_path.name,
                perf_markers_path.name,
            ],
        }
        _write_perf_snapshot(
            perf_json_path,
            {
                "run_id": resolved_run_id,
                "success": True,
                "total_wall_time_sec": round(time.perf_counter() - run_started_at, 6),
                "counts": dict(stage_counts),
                "stage_timings": stage_timings,
                "progress_path": str(progress_path),
                "perf_markers_path": str(perf_markers_path),
                **_tracemalloc_stats(),
            },
        )
        write_json(summary_path, summary)
        _snapshot("succeeded", None, "Stage1 completed successfully.")

        announce(
            logger,
            "[T02] wrote outputs "
            f"segment_has_evd_count={stage_counts['segment_has_evd_count']} "
            f"junction_count={stage_counts['junction_count']} "
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
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
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
        stage_counts["audit_count"] = len(audit_rows)
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
            "counts": dict(stage_counts),
            "stage_timings": stage_timings,
            "summary_by_s_grade": _empty_bucket_summary(),
            "fatal_error": {
                "reason": exc.reason,
                "detail": exc.detail,
            },
            "output_files": [
                "t02_stage1_summary.json",
                "t02_stage1_audit.csv",
                "t02_stage1_audit.json",
                "t02_stage1.log",
                "t02_stage1_progress.json",
                "t02_stage1_perf.json",
                "t02_stage1_perf_markers.jsonl",
            ],
        }
        _snapshot("failed", None, f"Stage1 failed: {exc.reason}")
        _record_perf_marker(
            out_path=perf_markers_path,
            run_id=resolved_run_id,
            stage="failed",
            elapsed_sec=time.perf_counter() - run_started_at,
            counts=dict(stage_counts),
            note=exc.reason,
        )
        _write_perf_snapshot(
            perf_json_path,
            {
                "run_id": resolved_run_id,
                "success": False,
                "total_wall_time_sec": round(time.perf_counter() - run_started_at, 6),
                "counts": dict(stage_counts),
                "stage_timings": stage_timings,
                "fatal_error": {
                    "reason": exc.reason,
                    "detail": exc.detail,
                },
                "progress_path": str(progress_path),
                "perf_markers_path": str(perf_markers_path),
                **_tracemalloc_stats(),
            },
        )
        announce(logger, f"[T02] stage1 failed reason={exc.reason} detail={exc.detail}")
        return _write_failure_outputs(
            out_root=resolved_out_root,
            run_id=resolved_run_id,
            audit_rows=audit_rows,
            summary=summary,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
        )
    finally:
        if started_tracemalloc:
            tracemalloc.stop()
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
