from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    write_vector,
    write_json,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    NodeRecord,
    T02RunError,
    audit_row,
    collect_semantic_junction_ids,
    find_repo_root,
    normalize_id,
    read_vector_layer_strict,
    resolve_junction_group,
)


REASON_MULTIPLE_INTERSECTIONS_FOR_GROUP = "multiple_intersections_for_group"
REASON_INTERSECTION_SHARED_BY_MULTIPLE_GROUPS = "intersection_shared_by_multiple_groups"
REASON_REPRESENTATIVE_NODE_MISSING = "representative_node_missing"
REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"

NODE_PROGRESS_INTERVAL = 10_000
JUNCTION_PROGRESS_INTERVAL = 5_000
KNOWN_S_GRADE_BUCKETS = ("0-0双", "0-1双", "0-2双")
ALL_D_SGRADE_BUCKET = "all__d_sgrade"
KIND_GRADE_BUCKET_4_64_1 = "kind2_4_64_grade2_1"
KIND_GRADE_BUCKET_4_64_0_2_3 = "kind2_4_64_grade2_0_2_3"
KIND_GRADE_BUCKET_2048 = "kind2_2048"
KIND_GRADE_BUCKET_8_16 = "kind2_8_16"

INTERSECTION_ID_FIELDS = (
    "id",
    "intersection_id",
    "intersectionid",
    "fid",
    "objectid",
    "OBJECTID",
)


class Stage2RunError(T02RunError):
    pass


@dataclass(frozen=True)
class IntersectionRecord:
    feature_index: int
    intersection_id: str
    geometry: Any


@dataclass(frozen=True)
class AnchorGroupResult:
    junction_id: str
    representative_output_index: int | None
    representative_node_id: str | None
    group_nodes: list[NodeRecord]
    participates: bool
    provisional_state: str | None
    provisional_anchor_reason: str | None
    intersection_ids: list[str]


@dataclass(frozen=True)
class SegmentSummaryContext:
    segment_id: str
    s_grade: str | None
    pair_junction_ids: list[str]
    pair_and_junc_junction_ids: list[str]


@dataclass(frozen=True)
class Stage2Artifacts:
    success: bool
    out_root: Path
    nodes_path: Path | None
    summary_path: Path
    node_error_1_path: Path
    node_error_1_audit_csv_path: Path
    node_error_1_audit_json_path: Path
    node_error_2_path: Path
    node_error_2_audit_csv_path: Path
    node_error_2_audit_json_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    log_path: Path
    progress_path: Path
    perf_json_path: Path
    perf_markers_path: Path


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


def _write_perf_snapshot(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or build_run_id("t02_stage2_anchor_recognition")
    if out_root is not None:
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise Stage2RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_stage2_anchor_recognition" / resolved_run_id, resolved_run_id


def _intersection_identity(properties: dict[str, Any], feature_index: int) -> str:
    for field in INTERSECTION_ID_FIELDS:
        value = normalize_id(properties.get(field))
        if value is not None:
            return f"{field}:{value}"
    return f"feature_index:{feature_index}"


def _error_audit_row(
    *,
    error_type: str,
    reason: str,
    junction_id: str,
    representative_node_id: str | None,
    involved_node_ids: list[str],
    intersection_ids: list[str],
    detail: str,
) -> dict[str, Any]:
    return {
        "error_type": error_type,
        "junction_id": junction_id,
        "representative_node_id": representative_node_id,
        "involved_node_ids": involved_node_ids,
        "group_size": len(involved_node_ids),
        "intersection_ids": intersection_ids,
        "intersection_count": len(intersection_ids),
        "status": "error",
        "reason": reason,
        "detail": detail,
    }


def _write_error_outputs(
    *,
    vector_path: Path,
    audit_csv_path: Path,
    audit_json_path: Path,
    nodes_features: list[Any],
    feature_indexes: set[int],
    feature_metadata: dict[int, dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    run_id: str,
) -> None:
    write_vector(
        vector_path,
        (
            {
                "properties": {
                    **nodes_features[feature_index].properties,
                    **feature_metadata[feature_index],
                },
                "geometry": nodes_features[feature_index].geometry,
            }
            for feature_index in sorted(feature_indexes)
        ),
        crs_text=TARGET_CRS.to_string(),
    )
    fieldnames = [
        "error_type",
        "junction_id",
        "representative_node_id",
        "involved_node_ids",
        "group_size",
        "intersection_ids",
        "intersection_count",
        "status",
        "reason",
        "detail",
    ]
    write_csv(audit_csv_path, audit_rows, fieldnames)
    write_json(
        audit_json_path,
        {
            "run_id": run_id,
            "error_count": len(audit_rows),
            "rows": audit_rows,
        },
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
                return [item for item in (normalize_id(item) for item in parsed) if item is not None]
        return [item for item in (normalize_id(part) for part in stripped.split(",")) if item is not None]
    if isinstance(value, (list, tuple, set)):
        return [item for item in (normalize_id(part) for part in value) if item is not None]
    normalized = normalize_id(value)
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
        return "s_grade", normalize_id(properties.get("s_grade"))
    if "sgrade" in properties:
        return "sgrade", normalize_id(properties.get("sgrade"))
    return None, None


def _empty_anchor_s_grade_summary() -> dict[str, dict[str, int]]:
    return {
        bucket: {
            "total_segment_count": 0,
            "pair_nodes_all_anchor_segment_count": 0,
            "pair_and_junc_nodes_all_anchor_segment_count": 0,
        }
        for bucket in (*KNOWN_S_GRADE_BUCKETS, ALL_D_SGRADE_BUCKET)
    }


def _empty_anchor_kind_grade_summary() -> dict[str, dict[str, int]]:
    return {
        KIND_GRADE_BUCKET_4_64_1: {
            "evidence_junction_count": 0,
            "anchored_junction_count": 0,
        },
        KIND_GRADE_BUCKET_4_64_0_2_3: {
            "evidence_junction_count": 0,
            "anchored_junction_count": 0,
        },
        KIND_GRADE_BUCKET_2048: {
            "evidence_junction_count": 0,
            "anchored_junction_count": 0,
        },
        KIND_GRADE_BUCKET_8_16: {
            "evidence_junction_count": 0,
            "anchored_junction_count": 0,
        },
    }


def _kind_grade_bucket(kind_2_value: str | None, grade_2_value: str | None) -> str | None:
    if kind_2_value in {"4", "64"} and grade_2_value == "1":
        return KIND_GRADE_BUCKET_4_64_1
    if kind_2_value in {"4", "64"} and grade_2_value in {"0", "2", "3"}:
        return KIND_GRADE_BUCKET_4_64_0_2_3
    if kind_2_value == "2048":
        return KIND_GRADE_BUCKET_2048
    if kind_2_value in {"8", "16"}:
        return KIND_GRADE_BUCKET_8_16
    return None


def _read_segment_features(
    path: Union[str, Path],
    *,
    crs_override: Optional[str] = None,
) -> list[dict[str, Any]]:
    layer = read_vector_layer_strict(
        path,
        crs_override=crs_override,
        allow_null_geometry=True,
        error_cls=Stage2RunError,
    )
    return [feature.properties for feature in layer.features]


def run_t02_stage2_anchor_recognition(
    *,
    segment_path: Union[str, Path],
    nodes_path: Union[str, Path],
    intersection_path: Union[str, Path],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    segment_crs: Optional[str] = None,
    nodes_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    intersection_layer: Optional[str] = None,
    intersection_crs: Optional[str] = None,
) -> Stage2Artifacts:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    log_path = resolved_out_root / "t02_stage2.log"
    progress_path = resolved_out_root / "t02_stage2_progress.json"
    perf_json_path = resolved_out_root / "t02_stage2_perf.json"
    perf_markers_path = resolved_out_root / "t02_stage2_perf_markers.jsonl"
    summary_path = resolved_out_root / "t02_stage2_summary.json"
    nodes_output_path = resolved_out_root / "nodes.gpkg"
    node_error_1_path = resolved_out_root / "node_error_1.gpkg"
    node_error_1_audit_csv_path = resolved_out_root / "node_error_1_audit.csv"
    node_error_1_audit_json_path = resolved_out_root / "node_error_1_audit.json"
    node_error_2_path = resolved_out_root / "node_error_2.gpkg"
    node_error_2_audit_csv_path = resolved_out_root / "node_error_2_audit.csv"
    node_error_2_audit_json_path = resolved_out_root / "node_error_2_audit.json"
    audit_csv_path = resolved_out_root / "t02_stage2_audit.csv"
    audit_json_path = resolved_out_root / "t02_stage2_audit.json"

    logger = build_logger(log_path, f"t02_stage2_anchor_recognition.{resolved_run_id}")
    audit_rows: list[dict[str, Any]] = []
    stage_counts: dict[str, Any] = {
        "node_feature_count": 0,
        "segment_feature_count": 0,
        "segment_referenced_junction_count": 0,
        "valid_node_count": 0,
        "semantic_candidate_junction_count": 0,
        "semantic_only_candidate_junction_count": 0,
        "candidate_junction_count": 0,
        "stage2_candidate_group_count": 0,
        "stage2_anchor_domain_group_count": 0,
        "stage2_candidate_node_count": 0,
        "intersection_feature_count": 0,
        "anchor_yes_count": 0,
        "anchor_no_count": 0,
        "anchor_fail1_count": 0,
        "anchor_fail2_count": 0,
        "kind_grade_evidence_junction_count": 0,
        "kind_grade_anchored_junction_count": 0,
        "kind_grade_unclassified_junction_count": 0,
        "unknown_s_grade_segment_count": 0,
        "node_error_1_group_count": 0,
        "node_error_2_group_count": 0,
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
        _snapshot("running", "bootstrap", "Stage2 bootstrap started.")
        announce(logger, f"[T02] stage2 start run_id={resolved_run_id}")

        read_started_at = time.perf_counter()
        nodes_layer_data = read_vector_layer_strict(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=True,
            error_cls=Stage2RunError,
        )
        intersection_layer_data = read_vector_layer_strict(
            intersection_path,
            layer_name=intersection_layer,
            crs_override=intersection_crs,
            allow_null_geometry=False,
            error_cls=Stage2RunError,
        )
        stage_counts["node_feature_count"] = len(nodes_layer_data.features)
        stage_counts["intersection_feature_count"] = len(intersection_layer_data.features)
        announce(
            logger,
            "[T02] loaded "
            f"node_features={len(nodes_layer_data.features)} "
            f"intersection_features={len(intersection_layer_data.features)}",
        )
        _snapshot("running", "inputs_loaded", "Input layers loaded and projected to EPSG:3857.")
        _mark_stage("inputs_loaded", read_started_at)

        intersection_prepare_started_at = time.perf_counter()
        intersection_records: list[IntersectionRecord] = []
        for feature in intersection_layer_data.features:
            if feature.geometry is None or feature.geometry.is_empty:
                continue
            intersection_records.append(
                IntersectionRecord(
                    feature_index=feature.feature_index,
                    intersection_id=_intersection_identity(feature.properties, feature.feature_index),
                    geometry=feature.geometry,
                )
            )
        if not intersection_records:
            raise Stage2RunError(
                REASON_MISSING_REQUIRED_FIELD,
                "RCSDIntersection layer has no non-empty geometry features after projection to EPSG:3857.",
            )
        intersection_tree = STRtree([record.geometry for record in intersection_records])
        announce(
            logger,
            "[T02] intersections prepared "
            f"target_crs=EPSG:3857 index_size={len(intersection_records)}",
        )
        _snapshot("running", "intersections_prepared", "RCSDIntersection geometries prepared.")
        _mark_stage("intersections_prepared", intersection_prepare_started_at)

        node_index_started_at = time.perf_counter()
        nodes_by_mainnodeid: dict[str, list[NodeRecord]] = {}
        singleton_nodes_by_id: dict[str, list[NodeRecord]] = {}

        for output_index, feature in enumerate(nodes_layer_data.features):
            feature.properties["is_anchor"] = None
            feature.properties["anchor_reason"] = None

            missing_fields: list[str] = []
            if "id" not in feature.properties:
                missing_fields.append("id")
            if "mainnodeid" not in feature.properties:
                missing_fields.append("mainnodeid")
            if "has_evd" not in feature.properties:
                missing_fields.append("has_evd")
            node_id = normalize_id(feature.properties.get("id"))
            mainnodeid = normalize_id(feature.properties.get("mainnodeid"))
            if node_id is None:
                missing_fields.append("id_value")
            if feature.geometry is None or feature.geometry.is_empty:
                missing_fields.append("geometry")
            if missing_fields:
                audit_rows.append(
                    audit_row(
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

        semantic_candidate_junction_ids = collect_semantic_junction_ids(
            nodes_by_mainnodeid=nodes_by_mainnodeid,
            singleton_nodes_by_id=singleton_nodes_by_id,
            nodes_features=nodes_layer_data.features,
        )
        stage_counts["semantic_candidate_junction_count"] = len(semantic_candidate_junction_ids)
        segment_read_started_at = time.perf_counter()
        segment_feature_properties = _read_segment_features(segment_path, crs_override=segment_crs)
        stage_counts["segment_feature_count"] = len(segment_feature_properties)
        referenced_junction_ids: set[str] = set()
        segment_contexts: list[SegmentSummaryContext] = []
        for feature_index, properties in enumerate(segment_feature_properties):
            missing_fields: list[str] = []
            segment_id = normalize_id(properties.get("id"))
            if segment_id is None:
                missing_fields.append("id")
            if "pair_nodes" not in properties:
                missing_fields.append("pair_nodes")
            if "junc_nodes" not in properties:
                missing_fields.append("junc_nodes")
            _, s_grade = _segment_grade(properties)
            if "s_grade" not in properties and "sgrade" not in properties:
                missing_fields.append("s_grade|sgrade")
            if missing_fields:
                audit_rows.append(
                    audit_row(
                        scope="segment",
                        status="error",
                        reason=REASON_MISSING_REQUIRED_FIELD,
                        detail=(
                            f"segment feature[{feature_index}] missing required fields: {','.join(missing_fields)}"
                        ),
                        segment_id=segment_id,
                    )
                )
                continue

            pair_junction_ids = _dedupe_preserve_order(_parse_junction_values(properties.get("pair_nodes")))
            pair_and_junc_junction_ids = _dedupe_preserve_order(
                pair_junction_ids + _parse_junction_values(properties.get("junc_nodes"))
            )
            referenced_junction_ids.update(pair_and_junc_junction_ids)
            segment_contexts.append(
                SegmentSummaryContext(
                    segment_id=segment_id,
                    s_grade=s_grade,
                    pair_junction_ids=pair_junction_ids,
                    pair_and_junc_junction_ids=pair_and_junc_junction_ids,
                )
            )

        stage_counts["segment_referenced_junction_count"] = len(referenced_junction_ids)
        stage_counts["semantic_only_candidate_junction_count"] = len(
            set(semantic_candidate_junction_ids) - referenced_junction_ids
        )
        candidate_junction_ids = sorted(set(semantic_candidate_junction_ids) | referenced_junction_ids)
        stage_counts["candidate_junction_count"] = len(candidate_junction_ids)
        announce(
            logger,
            "[T02] node index built "
            f"valid_nodes={stage_counts['valid_node_count']} "
            f"semantic_candidate_junctions={stage_counts['semantic_candidate_junction_count']} "
            f"candidate_junctions={stage_counts['candidate_junction_count']}",
        )
        announce(
            logger,
            "[T02] loaded segment summary inputs "
            f"segment_features={stage_counts['segment_feature_count']} "
            f"segment_referenced_junctions={stage_counts['segment_referenced_junction_count']}",
        )
        _snapshot("running", "node_index_built", "Node index and segment summary inputs built.")
        _mark_stage("node_index_built", node_index_started_at)
        _mark_stage("segment_inputs_loaded", segment_read_started_at)

        anchor_scan_started_at = time.perf_counter()
        group_results: dict[str, AnchorGroupResult] = {}
        intersection_to_junctions: dict[str, set[str]] = {}
        error1_rows: list[dict[str, Any]] = []
        error2_rows: list[dict[str, Any]] = []
        error1_feature_indexes: set[int] = set()
        error2_feature_indexes: set[int] = set()
        error1_feature_metadata: dict[int, dict[str, Any]] = {}
        error2_feature_metadata: dict[int, dict[str, Any]] = {}
        node_hit_cache: dict[int, tuple[str, ...]] = {}
        for junction_index, junction_id in enumerate(candidate_junction_ids, start=1):
            resolved_group = resolve_junction_group(
                junction_id,
                nodes_by_mainnodeid=nodes_by_mainnodeid,
                singleton_nodes_by_id=singleton_nodes_by_id,
                representative_missing_reason=REASON_REPRESENTATIVE_NODE_MISSING,
                junction_not_found_reason=REASON_MISSING_REQUIRED_FIELD,
            )
            if resolved_group.reason is not None or resolved_group.representative is None:
                audit_rows.append(
                    audit_row(
                        scope="junction",
                        status="error",
                        reason=resolved_group.reason or REASON_REPRESENTATIVE_NODE_MISSING,
                        detail=resolved_group.detail or resolved_group.reason or REASON_REPRESENTATIVE_NODE_MISSING,
                        junction_id=junction_id,
                    )
                )
                group_results[junction_id] = AnchorGroupResult(
                    junction_id=junction_id,
                    representative_output_index=None,
                    representative_node_id=None,
                    group_nodes=list(resolved_group.group_nodes),
                    participates=False,
                    provisional_state=None,
                    provisional_anchor_reason=None,
                    intersection_ids=[],
                )
                continue

            representative = resolved_group.representative
            representative_properties = nodes_layer_data.features[representative.output_index].properties
            representative_has_evd = normalize_id(representative_properties.get("has_evd"))
            if representative_has_evd != "yes":
                group_results[junction_id] = AnchorGroupResult(
                    junction_id=junction_id,
                    representative_output_index=representative.output_index,
                    representative_node_id=representative.node_id,
                    group_nodes=list(resolved_group.group_nodes),
                    participates=False,
                    provisional_state=None,
                    provisional_anchor_reason=None,
                    intersection_ids=[],
                )
                continue

            stage_counts["stage2_candidate_group_count"] += 1
            representative_kind_2 = normalize_id(representative_properties.get("kind_2"))
            stage_counts["stage2_anchor_domain_group_count"] += 1
            hit_intersection_ids: set[str] = set()
            every_group_node_hit = True
            for record in resolved_group.group_nodes:
                cached_hit_ids = node_hit_cache.get(record.output_index)
                if cached_hit_ids is None:
                    stage_counts["stage2_candidate_node_count"] += 1
                    candidate_indexes = intersection_tree.query(record.geometry, predicate="intersects")
                    cached_hit_ids = tuple(
                        sorted({intersection_records[int(index)].intersection_id for index in candidate_indexes})
                    )
                    node_hit_cache[record.output_index] = cached_hit_ids
                if not cached_hit_ids:
                    every_group_node_hit = False
                for intersection_id in cached_hit_ids:
                    hit_intersection_ids.add(intersection_id)
                    intersection_to_junctions.setdefault(intersection_id, set()).add(junction_id)

            sorted_hit_intersection_ids = sorted(hit_intersection_ids)
            provisional_anchor_reason = None
            if representative_kind_2 == "64" and every_group_node_hit:
                provisional_anchor_reason = "roundabout"
            elif representative_kind_2 == "2048" and every_group_node_hit:
                provisional_anchor_reason = "t"

            provisional_state = "no"
            if len(sorted_hit_intersection_ids) == 1:
                provisional_state = "yes"
            elif len(sorted_hit_intersection_ids) > 1:
                if len(resolved_group.group_nodes) == 1 or provisional_anchor_reason is not None:
                    provisional_state = "yes"
                else:
                    provisional_state = "fail1"
                    involved_node_ids = [record.node_id for record in resolved_group.group_nodes]
                    error1_rows.append(
                        _error_audit_row(
                            error_type="node_error_1",
                            reason=REASON_MULTIPLE_INTERSECTIONS_FOR_GROUP,
                            junction_id=junction_id,
                            representative_node_id=representative.node_id,
                            involved_node_ids=involved_node_ids,
                            intersection_ids=sorted_hit_intersection_ids,
                            detail="One junction group intersects more than one RCSDIntersection feature.",
                        )
                    )
                    for record in resolved_group.group_nodes:
                        error1_feature_indexes.add(record.output_index)
                        error1_feature_metadata[record.output_index] = {
                            "error_type": "node_error_1",
                            "junction_id": junction_id,
                            "representative_node_id": representative.node_id,
                            "intersection_ids": sorted_hit_intersection_ids,
                            "intersection_count": len(sorted_hit_intersection_ids),
                            "group_size": len(involved_node_ids),
                        }

            group_results[junction_id] = AnchorGroupResult(
                junction_id=junction_id,
                representative_output_index=representative.output_index,
                representative_node_id=representative.node_id,
                group_nodes=list(resolved_group.group_nodes),
                participates=True,
                provisional_state=provisional_state,
                provisional_anchor_reason=provisional_anchor_reason if provisional_state == "yes" else None,
                intersection_ids=sorted_hit_intersection_ids,
            )

            if junction_index % JUNCTION_PROGRESS_INTERVAL == 0:
                message = (
                    f"Processed candidate_groups={junction_index}/{len(candidate_junction_ids)} "
                    f"stage2_candidate_groups={stage_counts['stage2_candidate_group_count']} "
                    f"stage2_candidate_nodes={stage_counts['stage2_candidate_node_count']}"
                )
                announce(logger, f"[T02] {message}")
                _snapshot("running", "anchor_scan", message)

        announce(
            logger,
            "[T02] anchor scan completed "
            f"candidate_junctions={stage_counts['candidate_junction_count']} "
            f"stage2_candidate_groups={stage_counts['stage2_candidate_group_count']} "
            f"stage2_candidate_nodes={stage_counts['stage2_candidate_node_count']}",
        )
        _snapshot("running", "anchor_scan_done", "Anchor scan completed.")
        _mark_stage("anchor_scan_done", anchor_scan_started_at)

        fail2_started_at = time.perf_counter()
        junction_to_fail2_intersection_ids: dict[str, set[str]] = {}
        for intersection_id, junction_ids in intersection_to_junctions.items():
            if len(junction_ids) <= 1:
                continue
            filtered_junction_ids: list[str] = []
            for junction_id in sorted(junction_ids):
                group_result = group_results.get(junction_id)
                if group_result is None or not group_result.participates or group_result.representative_output_index is None:
                    continue
                representative_properties = nodes_layer_data.features[group_result.representative_output_index].properties
                representative_kind_2 = normalize_id(representative_properties.get("kind_2"))
                if representative_kind_2 == "1":
                    continue
                filtered_junction_ids.append(junction_id)
            if len(filtered_junction_ids) <= 1:
                continue
            for junction_id in filtered_junction_ids:
                junction_to_fail2_intersection_ids.setdefault(junction_id, set()).add(intersection_id)

        for junction_id, fail2_intersection_ids in sorted(junction_to_fail2_intersection_ids.items()):
            group_result = group_results[junction_id]
            involved_node_ids = [record.node_id for record in group_result.group_nodes]
            sorted_fail2_intersection_ids = sorted(fail2_intersection_ids)
            error2_rows.append(
                _error_audit_row(
                    error_type="node_error_2",
                    reason=REASON_INTERSECTION_SHARED_BY_MULTIPLE_GROUPS,
                    junction_id=junction_id,
                    representative_node_id=group_result.representative_node_id,
                    involved_node_ids=involved_node_ids,
                    intersection_ids=sorted_fail2_intersection_ids,
                    detail="One RCSDIntersection feature intersects more than one junction group.",
                )
            )
            for record in group_result.group_nodes:
                error2_feature_indexes.add(record.output_index)
                error2_feature_metadata[record.output_index] = {
                    "error_type": "node_error_2",
                    "junction_id": junction_id,
                    "representative_node_id": group_result.representative_node_id,
                    "intersection_ids": sorted_fail2_intersection_ids,
                    "intersection_count": len(sorted_fail2_intersection_ids),
                    "group_size": len(involved_node_ids),
                }

        stage_counts["node_error_1_group_count"] = len(error1_rows)
        stage_counts["node_error_2_group_count"] = len(error2_rows)
        announce(
            logger,
            "[T02] fail2 resolution completed "
            f"node_error_1_group_count={stage_counts['node_error_1_group_count']} "
            f"node_error_2_group_count={stage_counts['node_error_2_group_count']}",
        )
        _snapshot("running", "fail2_resolution_done", "Fail2 resolution completed.")
        _mark_stage("fail2_resolution_done", fail2_started_at)

        finalize_started_at = time.perf_counter()
        for junction_id, group_result in group_results.items():
            if not group_result.participates or group_result.representative_output_index is None:
                continue
            if junction_id in junction_to_fail2_intersection_ids:
                final_state = "fail2"
                final_anchor_reason = None
            elif group_result.provisional_state == "fail1":
                final_state = "fail1"
                final_anchor_reason = None
            elif group_result.provisional_state == "yes":
                final_state = "yes"
                final_anchor_reason = group_result.provisional_anchor_reason
            elif group_result.provisional_state == "no":
                final_state = "no"
                final_anchor_reason = None
            else:
                final_state = None
                final_anchor_reason = None
            nodes_layer_data.features[group_result.representative_output_index].properties["is_anchor"] = final_state
            nodes_layer_data.features[group_result.representative_output_index].properties["anchor_reason"] = final_anchor_reason
            if final_state == "yes":
                stage_counts["anchor_yes_count"] += 1
            elif final_state == "no":
                stage_counts["anchor_no_count"] += 1
            elif final_state == "fail1":
                stage_counts["anchor_fail1_count"] += 1
            elif final_state == "fail2":
                stage_counts["anchor_fail2_count"] += 1

        stage_counts["audit_count"] = len(audit_rows)
        announce(
            logger,
            "[T02] anchor finalize completed "
            f"anchor_yes_count={stage_counts['anchor_yes_count']} "
            f"anchor_no_count={stage_counts['anchor_no_count']} "
            f"anchor_fail1_count={stage_counts['anchor_fail1_count']} "
            f"anchor_fail2_count={stage_counts['anchor_fail2_count']} "
            f"audit_count={stage_counts['audit_count']}",
        )
        _snapshot("running", "anchor_finalize_done", "Anchor states finalized.")
        _mark_stage("anchor_finalize_done", finalize_started_at)

        summary_started_at = time.perf_counter()
        final_anchor_state_by_junction: dict[str, str | None] = {}
        anchor_summary_by_kind_grade = _empty_anchor_kind_grade_summary()
        evidence_junction_ids: set[str] = set()
        anchored_junction_ids: set[str] = set()
        kind_grade_unclassified_junction_count = 0

        for junction_id, group_result in group_results.items():
            if not group_result.participates or group_result.representative_output_index is None:
                final_anchor_state_by_junction[junction_id] = None
                continue
            representative_properties = nodes_layer_data.features[group_result.representative_output_index].properties
            final_anchor_state_by_junction[junction_id] = representative_properties.get("is_anchor")

        for junction_id in candidate_junction_ids:
            group_result = group_results.get(junction_id)
            if group_result is None or group_result.representative_output_index is None:
                kind_grade_unclassified_junction_count += 1
                continue
            representative_properties = nodes_layer_data.features[group_result.representative_output_index].properties
            representative_has_evd = normalize_id(representative_properties.get("has_evd"))
            if representative_has_evd != "yes":
                continue
            kind_2_value = normalize_id(representative_properties.get("kind_2"))
            grade_2_value = normalize_id(representative_properties.get("grade_2"))
            bucket = _kind_grade_bucket(kind_2_value, grade_2_value)
            if bucket is None:
                kind_grade_unclassified_junction_count += 1
                continue
            anchor_summary_by_kind_grade[bucket]["evidence_junction_count"] += 1
            evidence_junction_ids.add(junction_id)
            if final_anchor_state_by_junction.get(junction_id) == "yes":
                anchor_summary_by_kind_grade[bucket]["anchored_junction_count"] += 1
                anchored_junction_ids.add(junction_id)

        anchor_summary_by_s_grade = _empty_anchor_s_grade_summary()

        def _all_anchor(junction_ids: list[str]) -> bool:
            return bool(junction_ids) and all(final_anchor_state_by_junction.get(junction_id) == "yes" for junction_id in junction_ids)

        for context in segment_contexts:
            s_grade = context.s_grade
            pair_all_anchor = _all_anchor(context.pair_junction_ids)
            pair_and_junc_all_anchor = _all_anchor(context.pair_and_junc_junction_ids)

            if s_grade in KNOWN_S_GRADE_BUCKETS:
                anchor_summary_by_s_grade[s_grade]["total_segment_count"] += 1
                if pair_all_anchor:
                    anchor_summary_by_s_grade[s_grade]["pair_nodes_all_anchor_segment_count"] += 1
                if pair_and_junc_all_anchor:
                    anchor_summary_by_s_grade[s_grade]["pair_and_junc_nodes_all_anchor_segment_count"] += 1
            elif s_grade is not None:
                stage_counts["unknown_s_grade_segment_count"] += 1

            if s_grade is not None:
                anchor_summary_by_s_grade[ALL_D_SGRADE_BUCKET]["total_segment_count"] += 1
                if pair_all_anchor:
                    anchor_summary_by_s_grade[ALL_D_SGRADE_BUCKET]["pair_nodes_all_anchor_segment_count"] += 1
                if pair_and_junc_all_anchor:
                    anchor_summary_by_s_grade[ALL_D_SGRADE_BUCKET]["pair_and_junc_nodes_all_anchor_segment_count"] += 1

        stage_counts["kind_grade_evidence_junction_count"] = len(evidence_junction_ids)
        stage_counts["kind_grade_anchored_junction_count"] = len(anchored_junction_ids)
        stage_counts["kind_grade_unclassified_junction_count"] = kind_grade_unclassified_junction_count
        announce(
            logger,
            "[T02] summary prepared "
            f"evidence_junction_count={stage_counts['kind_grade_evidence_junction_count']} "
            f"anchored_junction_count={stage_counts['kind_grade_anchored_junction_count']} "
            f"unclassified_kind_grade_junction_count={stage_counts['kind_grade_unclassified_junction_count']} "
            f"unknown_s_grade_segment_count={stage_counts['unknown_s_grade_segment_count']}",
        )
        _snapshot("running", "summary_prepared", "Stage2 summary prepared.")
        _mark_stage("summary_prepared", summary_started_at)

        node_write_started_at = time.perf_counter()
        write_vector(
            nodes_output_path,
            (
                {
                    "properties": feature.properties,
                    "geometry": feature.geometry,
                }
                for feature in nodes_layer_data.features
            ),
            crs_text=TARGET_CRS.to_string(),
        )
        announce(logger, f"[T02] nodes written path={nodes_output_path}")
        _snapshot("running", "nodes_written", "nodes.gpkg written.")
        _mark_stage("nodes_written", node_write_started_at)

        error_write_started_at = time.perf_counter()
        _write_error_outputs(
            vector_path=node_error_1_path,
            audit_csv_path=node_error_1_audit_csv_path,
            audit_json_path=node_error_1_audit_json_path,
            nodes_features=nodes_layer_data.features,
            feature_indexes=error1_feature_indexes,
            feature_metadata=error1_feature_metadata,
            audit_rows=error1_rows,
            run_id=resolved_run_id,
        )
        _write_error_outputs(
            vector_path=node_error_2_path,
            audit_csv_path=node_error_2_audit_csv_path,
            audit_json_path=node_error_2_audit_json_path,
            nodes_features=nodes_layer_data.features,
            feature_indexes=error2_feature_indexes,
            feature_metadata=error2_feature_metadata,
            audit_rows=error2_rows,
            run_id=resolved_run_id,
        )
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
        announce(logger, "[T02] error outputs written")
        _snapshot("running", "error_outputs_written", "Error outputs written.")
        _mark_stage("error_outputs_written", error_write_started_at)

        summary_write_started_at = time.perf_counter()
        write_json(
            summary_path,
            {
                "run_id": resolved_run_id,
                "success": True,
                "target_crs": TARGET_CRS.to_string(),
                "inputs": {
                    "segment_path": str(Path(segment_path)),
                    "nodes_path": str(Path(nodes_path)),
                    "intersection_path": str(Path(intersection_path)),
                    "segment_crs_override": segment_crs,
                    "nodes_crs_override": nodes_crs,
                    "intersection_crs_override": intersection_crs,
                },
                "counts": {
                    "segment_feature_count": stage_counts["segment_feature_count"],
                    "segment_referenced_junction_count": stage_counts["segment_referenced_junction_count"],
                    "semantic_candidate_junction_count": stage_counts["semantic_candidate_junction_count"],
                    "semantic_only_candidate_junction_count": stage_counts["semantic_only_candidate_junction_count"],
                    "candidate_junction_count": stage_counts["candidate_junction_count"],
                    "stage2_candidate_group_count": stage_counts["stage2_candidate_group_count"],
                    "stage2_anchor_domain_group_count": stage_counts["stage2_anchor_domain_group_count"],
                    "anchor_yes_count": stage_counts["anchor_yes_count"],
                    "anchor_no_count": stage_counts["anchor_no_count"],
                    "anchor_fail1_count": stage_counts["anchor_fail1_count"],
                    "anchor_fail2_count": stage_counts["anchor_fail2_count"],
                    "evidence_junction_count": stage_counts["kind_grade_evidence_junction_count"],
                    "anchored_junction_count": stage_counts["kind_grade_anchored_junction_count"],
                    "unclassified_kind_grade_junction_count": stage_counts["kind_grade_unclassified_junction_count"],
                    "unknown_s_grade_segment_count": stage_counts["unknown_s_grade_segment_count"],
                },
                "summary_scope": {
                    "anchor_summary_by_s_grade": "segment_referenced_junction_set",
                    "anchor_summary_by_kind_grade": "stage2_candidate_junction_set",
                },
                "anchor_summary_by_s_grade": anchor_summary_by_s_grade,
                "anchor_summary_by_kind_grade": anchor_summary_by_kind_grade,
                "output_files": [
                    summary_path.name,
                    nodes_output_path.name,
                    node_error_1_path.name,
                    node_error_1_audit_csv_path.name,
                    node_error_1_audit_json_path.name,
                    node_error_2_path.name,
                    node_error_2_audit_csv_path.name,
                    node_error_2_audit_json_path.name,
                    audit_csv_path.name,
                    audit_json_path.name,
                    log_path.name,
                    progress_path.name,
                    perf_json_path.name,
                    perf_markers_path.name,
                ],
            },
        )
        announce(logger, f"[T02] summary written path={summary_path}")
        _snapshot("running", "summary_written", "Stage2 summary written.")
        _mark_stage("summary_written", summary_write_started_at)

        _write_perf_snapshot(
            perf_json_path,
            {
                "run_id": resolved_run_id,
                "success": True,
                "target_crs": TARGET_CRS.to_string(),
                "inputs": {
                    "segment_path": str(Path(segment_path)),
                    "nodes_path": str(Path(nodes_path)),
                    "intersection_path": str(Path(intersection_path)),
                    "segment_crs_override": segment_crs,
                    "nodes_crs_override": nodes_crs,
                    "intersection_crs_override": intersection_crs,
                },
                "counts": dict(stage_counts),
                "stage_timings": stage_timings,
                "output_files": [
                    summary_path.name,
                    nodes_output_path.name,
                    node_error_1_path.name,
                    node_error_1_audit_csv_path.name,
                    node_error_1_audit_json_path.name,
                    node_error_2_path.name,
                    node_error_2_audit_csv_path.name,
                    node_error_2_audit_json_path.name,
                    audit_csv_path.name,
                    audit_json_path.name,
                    log_path.name,
                    progress_path.name,
                    perf_json_path.name,
                    perf_markers_path.name,
                ],
                "total_wall_time_sec": round(time.perf_counter() - run_started_at, 6),
                "progress_path": str(progress_path),
                "perf_markers_path": str(perf_markers_path),
                **_tracemalloc_stats(),
            },
        )
        _snapshot("succeeded", None, "Stage2 completed successfully.")
        announce(
            logger,
            "[T02] wrote outputs "
            f"anchor_yes_count={stage_counts['anchor_yes_count']} "
            f"anchor_no_count={stage_counts['anchor_no_count']} "
            f"anchor_fail1_count={stage_counts['anchor_fail1_count']} "
            f"anchor_fail2_count={stage_counts['anchor_fail2_count']} "
            f"out_root={resolved_out_root}",
        )
        return Stage2Artifacts(
            success=True,
            out_root=resolved_out_root,
            nodes_path=nodes_output_path,
            summary_path=summary_path,
            node_error_1_path=node_error_1_path,
            node_error_1_audit_csv_path=node_error_1_audit_csv_path,
            node_error_1_audit_json_path=node_error_1_audit_json_path,
            node_error_2_path=node_error_2_path,
            node_error_2_audit_csv_path=node_error_2_audit_csv_path,
            node_error_2_audit_json_path=node_error_2_audit_json_path,
            audit_csv_path=audit_csv_path,
            audit_json_path=audit_json_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
        )
    except Stage2RunError as exc:
        audit_rows.append(
            audit_row(
                scope="run",
                status="error",
                reason=exc.reason,
                detail=exc.detail,
            )
        )
        stage_counts["audit_count"] = len(audit_rows)
        _write_error_outputs(
            vector_path=node_error_1_path,
            audit_csv_path=node_error_1_audit_csv_path,
            audit_json_path=node_error_1_audit_json_path,
            nodes_features=[],
            feature_indexes=set(),
            feature_metadata={},
            audit_rows=[],
            run_id=resolved_run_id,
        )
        _write_error_outputs(
            vector_path=node_error_2_path,
            audit_csv_path=node_error_2_audit_csv_path,
            audit_json_path=node_error_2_audit_json_path,
            nodes_features=[],
            feature_indexes=set(),
            feature_metadata={},
            audit_rows=[],
            run_id=resolved_run_id,
        )
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
        _snapshot("failed", None, f"Stage2 failed: {exc.reason}")
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
                "counts": dict(stage_counts),
                "stage_timings": stage_timings,
                "fatal_error": {
                    "reason": exc.reason,
                    "detail": exc.detail,
                },
                "total_wall_time_sec": round(time.perf_counter() - run_started_at, 6),
                "progress_path": str(progress_path),
                "perf_markers_path": str(perf_markers_path),
                **_tracemalloc_stats(),
            },
        )
        announce(logger, f"[T02] stage2 failed reason={exc.reason} detail={exc.detail}")
        return Stage2Artifacts(
            success=False,
            out_root=resolved_out_root,
            nodes_path=None,
            summary_path=summary_path,
            node_error_1_path=node_error_1_path,
            node_error_1_audit_csv_path=node_error_1_audit_csv_path,
            node_error_1_audit_json_path=node_error_1_audit_json_path,
            node_error_2_path=node_error_2_path,
            node_error_2_audit_csv_path=node_error_2_audit_csv_path,
            node_error_2_audit_json_path=node_error_2_audit_json_path,
            audit_csv_path=audit_csv_path,
            audit_json_path=audit_json_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
        )
    finally:
        if started_tracemalloc:
            tracemalloc.stop()
        close_logger(logger)


def run_t02_stage2_anchor_recognition_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_stage2_anchor_recognition(
        segment_path=args.segment_path,
        nodes_path=args.nodes_path,
        intersection_path=args.intersection_path,
        out_root=args.out_root,
        run_id=args.run_id,
        segment_crs=args.segment_crs,
        nodes_layer=args.nodes_layer,
        nodes_crs=args.nodes_crs,
        intersection_layer=args.intersection_layer,
        intersection_crs=args.intersection_crs,
    )
    if artifacts.success:
        print(f"T02 stage2 outputs written to: {artifacts.out_root}")
        return 0
    print(f"T02 stage2 failed; audit written to: {artifacts.out_root}")
    return 1
