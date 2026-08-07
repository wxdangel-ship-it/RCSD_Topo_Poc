from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

import fiona
from pyproj import CRS
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_models import (
    CasePaths,
    P12RConfig,
    PLAN_MIXED_SPLICE,
    PLAN_RCSD_ONLY,
    PLAN_REVIEW_FALLBACK,
    PLAN_SAFE_SWSD_FALLBACK,
    PLAN_SWSD_ONLY,
    REQUIRED_RCSD,
    REQUIRED_SWSD,
    REQUIRED_UNKNOWN,
    RoadRecord,
)


SCHEMA_VERSION = "p05-scheme-a-p2-p3-p12r-v1"
DECISION_GO = "P05_SCHEME_A_P2_P3_P12R_GO"
DECISION_REMEDIATION = (
    "P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED"
)
DECISION_CANDIDATE_NO_GO = (
    "P05_SCHEME_A_P2_P3_P12R_CANDIDATE_NO_GO"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P12R_AUDIT_NO_GO"

_REQUIRED_BASELINE_FILES = (
    "artifact_manifest.json",
    "case_inventory.csv",
    "reality_change_clues.jsonl",
    "scheme_a_summary.json",
    "segment_inventory.csv",
)


def assign_case_grouped_folds(
    case_counts: Mapping[str, int],
    *,
    fold_count: int = 5,
) -> dict[str, int]:
    if fold_count <= 0:
        raise ValueError("fold_count must be positive")
    if len(case_counts) < fold_count:
        raise ValueError("case count is smaller than fold_count")
    loads = [0] * fold_count
    case_loads = [0] * fold_count
    result: dict[str, int] = {}
    for case_key, count in sorted(
        case_counts.items(),
        key=lambda item: (-int(item[1]), str(item[0])),
    ):
        fold = min(
            range(fold_count),
            key=lambda index: (loads[index], case_loads[index], index),
        )
        result[str(case_key)] = fold
        loads[fold] += int(count)
        case_loads[fold] += 1
    if any(value == 0 for value in case_loads):
        raise ValueError("case-grouped fold allocation produced an empty fold")
    return result


def required_source_from_relation_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"replaced", "replaced+retained_swsd"}:
        return REQUIRED_RCSD
    if normalized in {"retained_swsd", "failed"}:
        return REQUIRED_SWSD
    return REQUIRED_UNKNOWN


def classify_truth_plan(
    *,
    access_valid: bool,
    required_sources: Sequence[str],
    truth_swsd_count: int,
    truth_rcsd_count: int,
    topology_hard_fail: bool,
) -> str:
    if not access_valid or REQUIRED_UNKNOWN in set(required_sources):
        return PLAN_REVIEW_FALLBACK
    if topology_hard_fail or (truth_swsd_count == 0 and truth_rcsd_count == 0):
        return PLAN_REVIEW_FALLBACK
    required = set(required_sources)
    if required == {REQUIRED_RCSD, REQUIRED_SWSD}:
        if truth_swsd_count > 0 and truth_rcsd_count > 0:
            return PLAN_MIXED_SPLICE
        if truth_swsd_count > 0:
            return PLAN_SAFE_SWSD_FALLBACK
        return PLAN_REVIEW_FALLBACK
    if required == {REQUIRED_RCSD}:
        if truth_rcsd_count > 0:
            return PLAN_RCSD_ONLY
        if truth_swsd_count > 0:
            return PLAN_SAFE_SWSD_FALLBACK
        return PLAN_REVIEW_FALLBACK
    if required == {REQUIRED_SWSD}:
        return (
            PLAN_SWSD_ONLY
            if truth_swsd_count > 0
            else PLAN_REVIEW_FALLBACK
        )
    return PLAN_REVIEW_FALLBACK


def run_scheme_a_p2_p3_p12r_audit(
    *,
    scheme_a_baseline_root: Path,
    poc_data_root: Path,
    output_root: Path,
    p11_acceptance_root: Path | None = None,
    reference_run_root: Path | None = None,
    config: P12RConfig | None = None,
) -> dict[str, Any]:
    cfg = config or P12RConfig()
    cfg.validate()
    started = time.perf_counter()
    output_root.mkdir(parents=True, exist_ok=False)

    baseline_inputs = _verify_baseline_inputs(scheme_a_baseline_root)
    case_inventory = _read_csv(
        scheme_a_baseline_root / "case_inventory.csv"
    )
    ar_cases = [
        row for row in case_inventory
        if int(row.get("advance_right_count") or 0) > 0
    ]
    case_counts = {
        str(row["case_key"]): int(row["advance_right_count"])
        for row in ar_cases
    }
    folds = assign_case_grouped_folds(
        case_counts,
        fold_count=cfg.fold_count,
    )
    manual_rows, manual_input = _load_manual_rows(p11_acceptance_root)

    truth_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    attachment_rows: list[dict[str, Any]] = []
    input_records: list[dict[str, Any]] = [
        {
            "path": str(path.resolve()),
            "role": f"baseline:{path.name}",
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }
        for path, digest in baseline_inputs.items()
    ]
    if manual_input is not None:
        input_records.append(manual_input)

    for case_row in sorted(ar_cases, key=lambda row: str(row["case_key"])):
        case_paths, skeleton = _resolve_case_paths(
            baseline_root=scheme_a_baseline_root,
            case_row=case_row,
            poc_data_root=poc_data_root,
        )
        case_input_records = _case_input_records(case_paths)
        input_records.extend(case_input_records)
        case_result = _audit_case(
            case_paths=case_paths,
            skeleton=skeleton,
            fold=folds[case_paths.case_key],
            manual_rows=manual_rows,
            cfg=cfg,
        )
        truth_rows.extend(case_result["truth"])
        candidate_rows.extend(case_result["candidates"])
        attachment_rows.extend(case_result["attachments"])

    truth_rows.sort(key=_row_key)
    candidate_rows.sort(key=_row_key)
    attachment_rows.sort(key=_row_key)
    fold_metrics = _fold_metrics(
        candidate_rows,
        fold_count=cfg.fold_count,
    )
    metrics = _metrics(
        truth_rows=truth_rows,
        candidate_rows=candidate_rows,
        attachment_rows=attachment_rows,
        case_count=len(ar_cases),
        fold_metrics=fold_metrics,
        cfg=cfg,
    )
    gates = _gates(metrics, fold_metrics, cfg)
    decision = _decision(gates, metrics, fold_metrics)
    content_signature = canonical_sha256(
        {
            "attachments": attachment_rows,
            "candidates": candidate_rows,
            "decision": decision,
            "fold_metrics": fold_metrics,
            "gates": gates,
            "input_hashes": sorted(
                (record["role"], record["sha256"])
                for record in input_records
            ),
            "metrics": metrics,
            "truth": truth_rows,
        }
    )
    reference_match = None
    if reference_run_root is not None:
        reference_summary = _read_json(
            reference_run_root / "p12r_summary.json"
        )
        reference_match = (
            reference_summary.get("content_signature")
            == content_signature
        )
        if not reference_match:
            gates["gate4_determinism_gis_resource"] = False
            decision = DECISION_AUDIT_NO_GO

    truth_path = output_root / "advance_right_realization_truth.jsonl"
    candidate_path = output_root / "advance_right_candidate_ceiling.jsonl"
    attachment_path = output_root / "advance_right_attachment_audit.jsonl"
    fold_path = output_root / "fold_metrics.json"
    metrics_path = output_root / "metrics.json"
    summary_path = output_root / "p12r_summary.json"
    report_path = output_root / "validation_report.md"
    manifest_path = output_root / "p12r_manifest.json"
    artifact_manifest_path = output_root / "artifact_manifest.json"

    _write_jsonl(truth_path, truth_rows)
    _write_jsonl(candidate_path, candidate_rows)
    _write_jsonl(attachment_path, attachment_rows)
    write_json(fold_path, fold_metrics)
    write_json(metrics_path, metrics)

    wall_seconds = time.perf_counter() - started
    peak_rss = _peak_rss_bytes()
    performance = {
        "gpu_required": False,
        "peak_rss_bytes": peak_rss,
        "peak_rss_within_budget": (
            0 < peak_rss <= cfg.max_peak_rss_bytes
        ),
        "wall_seconds": wall_seconds,
        "wall_within_budget": wall_seconds <= cfg.max_wall_seconds,
    }
    if (
        not performance["peak_rss_within_budget"]
        or not performance["wall_within_budget"]
    ):
        gates["gate4_determinism_gis_resource"] = False
        decision = DECISION_AUDIT_NO_GO

    summary = {
        "candidate_oracle_recall": metrics["candidate_oracle_recall"],
        "case_count": len(ar_cases),
        "content_signature": content_signature,
        "decision": decision,
        "fold_count": cfg.fold_count,
        "gates": gates,
        "geometry_write_count": 0,
        "movement_decision_count": 0,
        "object_count": len(truth_rows),
        "performance": performance,
        "reference_run_match": reference_match,
        "schema_version": SCHEMA_VERSION,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
        "status": "passed" if decision != DECISION_AUDIT_NO_GO else "failed",
        "t01_t12_modification_count": 0,
        "training_count": 0,
        "worst_fold_candidate_oracle_recall": fold_metrics[
            "worst_fold_candidate_oracle_recall"
        ],
    }
    write_json(summary_path, summary)
    report_path.write_text(
        _validation_report(summary, metrics, fold_metrics),
        encoding="utf-8",
    )
    write_json(
        manifest_path,
        {
            "config": {
                "expected_advance_right_count": cfg.expected_advance_right_count,
                "expected_case_count": cfg.expected_case_count,
                "expected_invalid_access_count": (
                    cfg.expected_invalid_access_count
                ),
                "fold_count": cfg.fold_count,
                "max_candidate_distance_m": cfg.max_candidate_distance_m,
                "tie_epsilon_m": cfg.tie_epsilon_m,
            },
            "content_signature": content_signature,
            "data_roles": {
                "inference_allowed": [
                    "T01_SEGMENT_ROAD_NODE",
                    "RAW_RCSD_ROAD_NODE",
                ],
                "label_only": [
                    "T06_RELATION",
                    "T06_FINAL_ROAD_NODE",
                    "T06_ADVANCE_RIGHT_AUDITS",
                    "P11_MANUAL_REVIEW",
                ],
                "t05_advance_right_anchor_label_count": 0,
            },
            "decision": decision,
            "inputs": sorted(input_records, key=lambda row: row["role"]),
            "outputs": {
                "attachments": output_record(attachment_path),
                "candidates": output_record(candidate_path),
                "fold_metrics": output_record(fold_path),
                "metrics": output_record(metrics_path),
                "summary": output_record(summary_path),
                "truth": output_record(truth_path),
                "validation_report": output_record(report_path),
            },
            "reference_run_root": (
                None
                if reference_run_root is None
                else str(reference_run_root.resolve())
            ),
            "schema_version": SCHEMA_VERSION,
        },
    )
    write_json(
        artifact_manifest_path,
        {
            "artifacts": [
                output_record(path)
                for path in sorted(output_root.iterdir())
                if path.is_file()
                and path.name != artifact_manifest_path.name
            ],
            "schema_version": SCHEMA_VERSION,
        },
    )
    return summary


def _audit_case(
    *,
    case_paths: CasePaths,
    skeleton: Mapping[str, Any],
    fold: int,
    manual_rows: Mapping[tuple[str, str], Mapping[str, Any]],
    cfg: P12RConfig,
) -> dict[str, list[dict[str, Any]]]:
    crs_rows = [
        _read_crs(case_paths.t01_roads),
        _read_crs(case_paths.t01_nodes),
        _read_crs(case_paths.raw_rcsd_roads),
        _read_crs(case_paths.raw_rcsd_nodes),
        _read_crs(case_paths.t06_final_roads),
        _read_crs(case_paths.t06_final_nodes),
    ]
    crs_consistent = all(value == crs_rows[0] for value in crs_rows)
    crs = CRS.from_user_input(crs_rows[0])
    crs_metric = crs.is_projected and all(
        str(axis.unit_name or "").lower() in {"metre", "meter"}
        for axis in crs.axis_info[:2]
    )

    t01_roads = _read_roads(case_paths.t01_roads)
    t01_nodes = _read_nodes(case_paths.t01_nodes)
    raw_rcsd_roads = _read_roads(case_paths.raw_rcsd_roads)
    final_roads = _read_roads(case_paths.t06_final_roads)
    relations = {
        str(row["swsd_segment_id"]): row
        for row in _read_csv(case_paths.t06_relation)
    }
    attachment_audit = _read_csv(case_paths.t06_attachment_audit)
    closure_audit = _read_csv(case_paths.t06_closure_audit)
    topology_audit = _read_csv(case_paths.t06_topology_audit)

    segments = list(skeleton.get("segments") or [])
    ar_segments = [
        row for row in segments
        if str(row.get("segment_type")) == "ADVANCE_RIGHT"
    ]
    standard_segments = {
        str(row["segment_id"]): row
        for row in segments
        if str(row.get("segment_type")) != "ADVANCE_RIGHT"
    }
    t01_road_by_id = {road.road_id: road for road in t01_roads}
    raw_rcsd_road_by_id = {
        road.road_id: road for road in raw_rcsd_roads
    }
    raw_rcsd_advance = [
        road for road in raw_rcsd_roads if road.is_advance_right
    ]
    final_advance = [road for road in final_roads if road.is_advance_right]
    final_road_by_id = {road.road_id: road for road in final_roads}
    final_advance_by_segment: dict[str, list[RoadRecord]] = defaultdict(list)
    unlabelled_final_rcsd: list[RoadRecord] = []
    for road in final_advance:
        labels = _road_segment_labels(road)
        if labels:
            for label in labels:
                final_advance_by_segment[label].append(road)
        elif _road_origin(
            road,
            t01_road_ids=set(t01_road_by_id),
            raw_rcsd_road_ids=set(raw_rcsd_road_by_id),
        ) == REQUIRED_RCSD:
            unlabelled_final_rcsd.append(road)

    ar_geometries = {
        str(segment["segment_id"]): _segment_geometry(
            segment,
            t01_road_by_id,
        )
        for segment in ar_segments
    }
    raw_candidates = _roads_near_segments(
        ar_geometries,
        raw_rcsd_advance,
        max_distance_m=cfg.max_candidate_distance_m,
    )
    assigned_unlabelled_rcsd, ambiguous_final = _assign_roads_to_segments(
        ar_geometries,
        unlabelled_final_rcsd,
        max_distance_m=cfg.max_candidate_distance_m,
        tie_epsilon_m=cfg.tie_epsilon_m,
    )

    truth_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    attachment_rows: list[dict[str, Any]] = []
    for segment in sorted(ar_segments, key=lambda row: str(row["segment_id"])):
        object_id = str(segment["segment_id"])
        source_owner, source_node = _parse_access(
            segment.get("source_segment_access")
        )
        target_owner, target_node = _parse_access(
            segment.get("target_segment_access")
        )
        access_valid = bool(segment.get("access_valid"))
        owner_valid = (
            source_owner in standard_segments
            and target_owner in standard_segments
            and source_node in t01_nodes
            and target_node in t01_nodes
        )
        access_valid = access_valid and owner_valid
        source_required = required_source_from_relation_status(
            str(relations.get(source_owner, {}).get("relation_status") or "")
        )
        target_required = required_source_from_relation_status(
            str(relations.get(target_owner, {}).get("relation_status") or "")
        )

        swsd_ids = [
            str(value) for value in segment.get("swsd_road_ids") or []
        ]
        labelled_truth = list(final_advance_by_segment.get(object_id, []))
        labelled_ids = {road.road_id for road in labelled_truth}
        labelled_truth.extend(
            road
            for road in assigned_unlabelled_rcsd.get(object_id, [])
            if road.road_id not in labelled_ids
        )
        truth_swsd = [
            road
            for road in labelled_truth
            if _road_origin(
                road,
                t01_road_ids=set(t01_road_by_id),
                raw_rcsd_road_ids=set(raw_rcsd_road_by_id),
            )
            == REQUIRED_SWSD
        ]
        truth_rcsd = [
            road
            for road in labelled_truth
            if _road_origin(
                road,
                t01_road_ids=set(t01_road_by_id),
                raw_rcsd_road_ids=set(raw_rcsd_road_by_id),
            )
            == REQUIRED_RCSD
        ]
        topology_failures = _topology_failures_for_unit(
            topology_audit,
            object_id=object_id,
            road_ids={
                *swsd_ids,
                *(road.road_id for road in truth_swsd),
                *(road.road_id for road in truth_rcsd),
            },
        )
        plan = classify_truth_plan(
            access_valid=access_valid,
            required_sources=(source_required, target_required),
            truth_swsd_count=len(truth_swsd),
            truth_rcsd_count=len(truth_rcsd),
            topology_hard_fail=bool(topology_failures),
        )
        fallback_reason = _fallback_reason(
            access_valid=access_valid,
            source_required=source_required,
            target_required=target_required,
            truth_rcsd=truth_rcsd,
            truth_swsd=truth_swsd,
            topology_failures=topology_failures,
        )
        unit_attachment = _attachment_record(
            case_paths=case_paths,
            segment=segment,
            source_owner=source_owner,
            target_owner=target_owner,
            relations=relations,
            attachment_audit=attachment_audit,
            closure_audit=closure_audit,
            topology_failures=topology_failures,
            truth_swsd=truth_swsd,
            truth_rcsd=truth_rcsd,
            final_road_by_id=final_road_by_id,
        )
        attachment_rows.append(unit_attachment)
        source_realized = _realized_source_from_plan(
            required=source_required,
            plan=plan,
        )
        target_realized = _realized_source_from_plan(
            required=target_required,
            plan=plan,
        )
        source_consistent = _side_source_consistent(
            required=source_required,
            realized=source_realized,
            plan=plan,
        )
        target_consistent = _side_source_consistent(
            required=target_required,
            realized=target_realized,
            plan=plan,
        )
        splice_required = (
            plan == PLAN_MIXED_SPLICE
            and source_required != target_required
        )
        splice_nodes = _shared_endpoint_ids(truth_swsd, truth_rcsd)

        candidate_rcsd = raw_candidates.get(object_id, [])
        raw_candidate_roads = [
            item["road"] for item in candidate_rcsd
        ]
        rcsd_truth_hits = {
            road.road_id: _candidate_component_hits(
                truth=road,
                candidates=raw_candidate_roads,
                max_distance_m=cfg.max_candidate_distance_m,
            )
            for road in truth_rcsd
        }
        swsd_truth_hits = {
            road.road_id: _candidate_component_hits(
                truth=road,
                candidates=[
                    t01_road_by_id[road_id]
                    for road_id in swsd_ids
                    if road_id in t01_road_by_id
                ],
                max_distance_m=cfg.max_candidate_distance_m,
            )
            for road in truth_swsd
        }
        rcsd_components_reachable = (
            bool(truth_rcsd)
            and all(bool(values) for values in rcsd_truth_hits.values())
        )
        swsd_components_reachable = (
            bool(truth_swsd)
            and all(bool(values) for values in swsd_truth_hits.values())
        )
        both_origins = bool(truth_swsd and truth_rcsd)
        materializer_ready = (
            not both_origins
            or bool(splice_nodes)
            or _has_materializer_action(unit_attachment)
        )
        candidate_oracle_hit = (
            plan != PLAN_REVIEW_FALLBACK
            and (not truth_swsd or swsd_components_reachable)
            and (not truth_rcsd or rcsd_components_reachable)
            and materializer_ready
        )
        eligible = (
            access_valid
            and source_required != REQUIRED_UNKNOWN
            and target_required != REQUIRED_UNKNOWN
            and plan != PLAN_REVIEW_FALLBACK
        )
        if not eligible:
            candidate_oracle_hit = False
        comparable = (
            any(road_id in t01_road_by_id for road_id in swsd_ids)
            and len(candidate_rcsd) > 0
        )
        manual = manual_rows.get((case_paths.case_key, object_id))
        reality_change_clue = not access_valid

        truth_rows.append(
            {
                "access_valid": access_valid,
                "ambiguous_final_rcsd_road_ids": sorted(
                    road.road_id
                    for road in ambiguous_final.get(object_id, [])
                ),
                "attachment_segment_ids": unit_attachment[
                    "attachment_segment_ids"
                ],
                "case_key": case_paths.case_key,
                "crs": crs.to_string(),
                "crs_consistent": crs_consistent,
                "crs_metric": crs_metric,
                "fallback_reason": fallback_reason,
                "fallback_required": bool(fallback_reason),
                "fold": fold,
                "manual_historical_allowed_targets": (
                    [] if manual is None else manual.get("allowed_targets", [])
                ),
                "manual_historical_preferred_target": (
                    None if manual is None else manual.get("preferred_target")
                ),
                "manual_reinterpretation": (
                    None
                    if manual is None
                    else "CONDITIONAL_REALIZATION_VALIDATION"
                ),
                "object_id": object_id,
                "reality_change_clue": reality_change_clue,
                "schema_version": SCHEMA_VERSION,
                "source_adjacent_segment_id": source_owner,
                "source_realized_source": source_realized,
                "source_realization_evidence": (
                    _realization_evidence(
                        required=source_required,
                        plan=plan,
                        truth_swsd=truth_swsd,
                        truth_rcsd=truth_rcsd,
                        attachment=unit_attachment,
                    )
                ),
                "source_required_source": source_required,
                "source_side_consistent": source_consistent,
                "splice_boundary_node_ids": splice_nodes,
                "splice_required": splice_required,
                "t05_anchor_label_used": False,
                "target_adjacent_segment_id": target_owner,
                "target_realized_source": target_realized,
                "target_realization_evidence": (
                    _realization_evidence(
                        required=target_required,
                        plan=plan,
                        truth_swsd=truth_swsd,
                        truth_rcsd=truth_rcsd,
                        attachment=unit_attachment,
                    )
                ),
                "target_required_source": target_required,
                "target_side_consistent": target_consistent,
                "topology_hard_failures": topology_failures,
                "truth_plan_type": plan,
                "truth_rcsd_road_ids": sorted(
                    road.road_id for road in truth_rcsd
                ),
                "truth_swsd_road_ids": sorted(
                    road.road_id for road in truth_swsd
                ),
            }
        )
        candidate_rows.append(
            {
                "candidate_oracle_hit": candidate_oracle_hit,
                "candidate_option_count": (
                    int(swsd_components_reachable) + len(candidate_rcsd)
                ),
                "candidate_rcsd_road_ids": [
                    item["road"].road_id for item in candidate_rcsd
                ],
                "candidate_rcsd_road_min_distances_m": {
                    item["road"].road_id: item["distance_m"]
                    for item in candidate_rcsd
                },
                "candidate_source_roles": [
                    "T01_SWSD_IDENTITY",
                    "RAW_RCSD_INPUT",
                ],
                "candidate_swsd_road_ids": sorted(swsd_ids),
                "case_key": case_paths.case_key,
                "comparable_candidate_group": comparable,
                "eligible": eligible,
                "fold": fold,
                "materializer_ready": materializer_ready,
                "object_id": object_id,
                "oracle_failure_reason": _oracle_failure_reason(
                    eligible=eligible,
                    swsd_present=bool(truth_swsd),
                    swsd_reachable=swsd_components_reachable,
                    rcsd_present=bool(truth_rcsd),
                    rcsd_reachable=rcsd_components_reachable,
                    materializer_ready=materializer_ready,
                ),
                "rcsd_truth_component_hits": rcsd_truth_hits,
                "swsd_truth_component_hits": swsd_truth_hits,
                "schema_version": SCHEMA_VERSION,
                "t06_terminal_candidate_count": 0,
                "truth_plan_type": plan,
                "truth_source_used_as_feature": False,
            }
        )
    return {
        "attachments": attachment_rows,
        "candidates": candidate_rows,
        "truth": truth_rows,
    }


def _attachment_record(
    *,
    case_paths: CasePaths,
    segment: Mapping[str, Any],
    source_owner: str,
    target_owner: str,
    relations: Mapping[str, Mapping[str, Any]],
    attachment_audit: Sequence[Mapping[str, Any]],
    closure_audit: Sequence[Mapping[str, Any]],
    topology_failures: Sequence[Mapping[str, Any]],
    truth_swsd: Sequence[RoadRecord],
    truth_rcsd: Sequence[RoadRecord],
    final_road_by_id: Mapping[str, RoadRecord],
) -> dict[str, Any]:
    object_id = str(segment["segment_id"])
    original_road_ids = {
        str(value) for value in segment.get("swsd_road_ids") or []
    }
    swsd_truth_ids = {road.road_id for road in truth_swsd}
    rcsd_truth_ids = {road.road_id for road in truth_rcsd}
    matched_attachment = [
        row for row in attachment_audit
        if str(row.get("swsd_advance_road_id") or "") in original_road_ids
    ]
    matched_closure = [
        row for row in closure_audit
        if str(row.get("rcsd_advance_road_id") or "") in rcsd_truth_ids
    ]
    owner_by_road_lineage: dict[str, set[str]] = defaultdict(set)
    for segment_id, relation in relations.items():
        for final_id in _parse_list(relation.get("frcsd_road_ids")):
            lineage = {final_id}
            final_road = final_road_by_id.get(final_id)
            if final_road is not None:
                lineage.update(final_road.lineage_ids)
            for road_id in lineage:
                owner_by_road_lineage[road_id].add(segment_id)

    attached: set[str] = set()
    for row in matched_attachment:
        for field in ("rcsd_road_id", "target_rcsd_road_id"):
            attached.update(
                owner_by_road_lineage.get(str(row.get(field) or ""), set())
            )
    for row in matched_closure:
        for field in ("target_rcsd_road_id", "target_swsd_road_id"):
            attached.update(
                owner_by_road_lineage.get(str(row.get(field) or ""), set())
            )
    attached.difference_update({source_owner, target_owner, "", object_id})
    missing_relations = sorted(
        segment_id for segment_id in attached
        if segment_id not in relations
    )
    independent_road_missing = []
    for segment_id in sorted(attached):
        relation = relations.get(segment_id)
        if relation is None:
            continue
        final_ids = _parse_list(relation.get("frcsd_road_ids"))
        if not final_ids or any(
            road_id not in final_road_by_id for road_id in final_ids
        ):
            independent_road_missing.append(segment_id)
    actions = [
        {
            "action": str(row.get("action") or ""),
            "action_reason": str(row.get("action_reason") or ""),
            "generated_rcsd_node_id": str(
                row.get("generated_rcsd_node_id") or ""
            ),
            "projected_gap_m": str(row.get("projected_gap_m") or ""),
            "rcsd_node_id": str(row.get("rcsd_node_id") or ""),
            "rcsd_road_id": str(row.get("rcsd_road_id") or ""),
            "replacement_segment_ids": _parse_list(
                row.get("replacement_segment_ids")
            ),
            "retained_in_frcsd": _as_bool(
                row.get("retained_in_frcsd")
            ),
            "swsd_advance_road_id": str(
                row.get("swsd_advance_road_id") or ""
            ),
            "swsd_node_id": str(row.get("swsd_node_id") or ""),
            "swsd_node_mainnodeid_after": str(
                row.get("swsd_node_mainnodeid_after") or ""
            ),
            "swsd_node_mainnodeid_before": str(
                row.get("swsd_node_mainnodeid_before") or ""
            ),
        }
        for row in matched_attachment
    ]
    closures = [
        {
            "action": str(row.get("action") or ""),
            "action_reason": str(row.get("action_reason") or ""),
            "audit_status": str(row.get("audit_status") or ""),
            "endpoint_degree": str(row.get("endpoint_degree") or ""),
            "endpoint_index": str(row.get("endpoint_index") or ""),
            "generated_swsd_node_id": str(
                row.get("generated_swsd_node_id") or ""
            ),
            "projected_gap_m": str(row.get("projected_gap_m") or ""),
            "rcsd_advance_road_id": str(
                row.get("rcsd_advance_road_id") or ""
            ),
            "rcsd_endpoint_node_id": str(
                row.get("rcsd_endpoint_node_id") or ""
            ),
            "replacement_segment_ids": _parse_list(
                row.get("replacement_segment_ids")
            ),
            "target_rcsd_node_id": str(
                row.get("target_rcsd_node_id") or ""
            ),
            "target_rcsd_road_id": str(
                row.get("target_rcsd_road_id") or ""
            ),
            "target_road_source": str(
                row.get("target_road_source") or ""
            ),
            "target_swsd_road_id": str(
                row.get("target_swsd_road_id") or ""
            ),
        }
        for row in matched_closure
    ]
    return {
        "attachment_actions": actions,
        "attachment_segment_ids": sorted(attached),
        "case_key": case_paths.case_key,
        "closure_actions": closures,
        "independent_road_missing_segment_ids": independent_road_missing,
        "materializer_action_names": sorted(
            {
                str(row.get("action") or "")
                for row in [*matched_attachment, *matched_closure]
                if str(row.get("action") or "")
            }
        ),
        "missing_relation_segment_ids": missing_relations,
        "object_id": object_id,
        "schema_version": SCHEMA_VERSION,
        "source_adjacent_segment_id": source_owner,
        "target_adjacent_segment_id": target_owner,
        "topology_hard_failures": list(topology_failures),
        "truth_rcsd_road_ids": sorted(rcsd_truth_ids),
        "truth_swsd_road_ids": sorted(swsd_truth_ids),
    }


def _roads_near_segments(
    segment_geometries: Mapping[str, Any],
    roads: Sequence[RoadRecord],
    *,
    max_distance_m: float,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for segment_id, segment_geometry in segment_geometries.items():
        for road in roads:
            distance = float(segment_geometry.distance(road.geometry))
            if distance <= max_distance_m:
                result[segment_id].append(
                    {"distance_m": distance, "road": road}
                )
        result[segment_id].sort(
            key=lambda row: (row["distance_m"], row["road"].road_id)
        )
    return dict(result)


def _assign_roads_to_segments(
    segment_geometries: Mapping[str, Any],
    roads: Sequence[RoadRecord],
    *,
    max_distance_m: float,
    tie_epsilon_m: float,
) -> tuple[dict[str, list[RoadRecord]], dict[str, list[RoadRecord]]]:
    assigned: dict[str, list[RoadRecord]] = defaultdict(list)
    ambiguous: dict[str, list[RoadRecord]] = defaultdict(list)
    for road in roads:
        distances = sorted(
            (
                float(geometry.distance(road.geometry)),
                segment_id,
            )
            for segment_id, geometry in segment_geometries.items()
        )
        distances = [
            item for item in distances if item[0] <= max_distance_m
        ]
        if not distances:
            continue
        best_distance = distances[0][0]
        tied = [
            segment_id for distance, segment_id in distances
            if abs(distance - best_distance) <= tie_epsilon_m
        ]
        if len(tied) == 1:
            assigned[tied[0]].append(road)
        else:
            for segment_id in tied:
                ambiguous[segment_id].append(road)
    for values in assigned.values():
        values.sort(key=lambda road: road.road_id)
    for values in ambiguous.values():
        values.sort(key=lambda road: road.road_id)
    return dict(assigned), dict(ambiguous)


def _segment_geometry(
    segment: Mapping[str, Any],
    t01_road_by_id: Mapping[str, RoadRecord],
) -> Any:
    road_ids = [
        str(value) for value in segment.get("swsd_road_ids") or []
    ]
    geometries = [
        t01_road_by_id[road_id].geometry
        for road_id in road_ids
        if road_id in t01_road_by_id
    ]
    if len(geometries) != len(road_ids) or not geometries:
        raise ValueError(
            f"advance-right T01 Road lineage is incomplete: "
            f"{segment.get('segment_id')}"
        )
    return unary_union(geometries)


def _road_segment_labels(road: RoadRecord) -> list[str]:
    labels = _parse_list(road.properties.get("t06_swsd_segment_ids"))
    if road.segment_id.startswith("advance_right_"):
        labels.append(road.segment_id)
    return sorted(set(labels))


def _road_origin(
    road: RoadRecord,
    *,
    t01_road_ids: set[str],
    raw_rcsd_road_ids: set[str],
) -> str:
    split_reason = str(road.properties.get("t06_split_reason") or "")
    if split_reason == "topology_supplement_from_swsd":
        return REQUIRED_SWSD
    lineage = set(road.lineage_ids)
    if road.source == 2:
        return REQUIRED_SWSD
    if lineage.intersection(raw_rcsd_road_ids):
        return REQUIRED_RCSD
    if lineage.intersection(t01_road_ids):
        return REQUIRED_SWSD
    if road.source == 1:
        return REQUIRED_RCSD
    return REQUIRED_UNKNOWN


def _candidate_component_hits(
    *,
    truth: RoadRecord,
    candidates: Sequence[RoadRecord],
    max_distance_m: float,
) -> list[str]:
    hits = []
    truth_lineage = set(truth.lineage_ids)
    for candidate in candidates:
        if truth_lineage.intersection(candidate.lineage_ids):
            hits.append(candidate.road_id)
            continue
        if float(truth.geometry.distance(candidate.geometry)) > max_distance_m:
            continue
        if float(truth.geometry.length) <= 0:
            continue
        covered = truth.geometry.intersection(
            candidate.geometry.buffer(max_distance_m)
        )
        coverage = float(covered.length) / float(truth.geometry.length)
        if coverage >= 0.95:
            hits.append(candidate.road_id)
    return sorted(set(hits))


def _has_materializer_action(
    attachment: Mapping[str, Any],
) -> bool:
    return bool(attachment.get("materializer_action_names"))


def _realized_source_from_plan(*, required: str, plan: str) -> str:
    if plan == PLAN_REVIEW_FALLBACK:
        return "REVIEW"
    if plan == PLAN_SAFE_SWSD_FALLBACK:
        return REQUIRED_SWSD
    return required


def _realization_evidence(
    *,
    required: str,
    plan: str,
    truth_swsd: Sequence[RoadRecord],
    truth_rcsd: Sequence[RoadRecord],
    attachment: Mapping[str, Any],
) -> str:
    if plan == PLAN_REVIEW_FALLBACK:
        return "SAFE_REVIEW_FALLBACK"
    if plan == PLAN_SAFE_SWSD_FALLBACK:
        return "T06_FINAL_SWSD_FALLBACK"
    if required == REQUIRED_RCSD and truth_rcsd:
        return (
            "T06_RELATION_FINAL_RCSD_CLOSURE"
            if attachment.get("closure_actions")
            else "T06_RELATION_FINAL_RCSD_TOPOLOGY"
        )
    if required == REQUIRED_SWSD and truth_swsd:
        return (
            "T06_RELATION_FINAL_SWSD_ATTACHMENT"
            if attachment.get("attachment_actions")
            else "T06_RELATION_FINAL_SWSD_TOPOLOGY"
        )
    return "UNRESOLVED"


def _side_source_consistent(
    *,
    required: str,
    realized: str,
    plan: str,
) -> bool:
    if required == REQUIRED_UNKNOWN:
        return False
    if required == REQUIRED_SWSD:
        return realized in {REQUIRED_SWSD, "MIXED"}
    if realized in {REQUIRED_RCSD, "MIXED"}:
        return True
    return (
        plan == PLAN_SAFE_SWSD_FALLBACK
        and realized == REQUIRED_SWSD
    )


def _shared_endpoint_ids(
    swsd_roads: Sequence[RoadRecord],
    rcsd_roads: Sequence[RoadRecord],
) -> list[str]:
    swsd_nodes = {
        node_id for road in swsd_roads for node_id in road.endpoint_ids
    }
    rcsd_nodes = {
        node_id for road in rcsd_roads for node_id in road.endpoint_ids
    }
    return sorted(swsd_nodes.intersection(rcsd_nodes))


def _fallback_reason(
    *,
    access_valid: bool,
    source_required: str,
    target_required: str,
    truth_rcsd: Sequence[RoadRecord],
    truth_swsd: Sequence[RoadRecord],
    topology_failures: Sequence[Mapping[str, Any]],
) -> str:
    if not access_valid:
        return "ADVANCE_RIGHT_ACCESS_INVALID"
    if REQUIRED_UNKNOWN in {source_required, target_required}:
        return "ADJACENT_SEGMENT_RELATION_UNAVAILABLE"
    if topology_failures:
        return "FINAL_TOPOLOGY_HARD_FAIL"
    if not truth_rcsd and not truth_swsd:
        return "FINAL_CARRIER_UNRESOLVED"
    if (
        REQUIRED_RCSD in {source_required, target_required}
        and not truth_rcsd
    ):
        return "RCSD_ADVANCE_RIGHT_UNAVAILABLE_OR_REJECTED"
    return ""


def _oracle_failure_reason(
    *,
    eligible: bool,
    swsd_present: bool,
    swsd_reachable: bool,
    rcsd_present: bool,
    rcsd_reachable: bool,
    materializer_ready: bool,
) -> str:
    if not eligible:
        return "NOT_ELIGIBLE_SAFE_REVIEW"
    if swsd_present and not swsd_reachable:
        return "T01_SWSD_TRUTH_COMPONENT_MISSING"
    if rcsd_present and not rcsd_reachable:
        return "RAW_RCSD_TRUTH_COMPONENT_MISSING"
    if not materializer_ready:
        return "MATERIALIZER_ACTION_UNAVAILABLE"
    return ""


def _topology_failures_for_unit(
    rows: Sequence[Mapping[str, Any]],
    *,
    object_id: str,
    road_ids: set[str],
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if not _as_bool(row.get("counts_in_final_frcsd_topology_fail")):
            continue
        row_ids = {
            str(row.get(field) or "")
            for field in (
                "swsd_road_id",
                "frcsd_road_id",
                "topology_road_lineage_id",
            )
        }
        object_key = str(row.get("final_topology_object_key") or "")
        matched = (
            str(row.get("swsd_segment_id") or "") == object_id
            or bool(road_ids.intersection(row_ids))
            or any(
                object_key == road_id
                or object_key.startswith(f"{road_id}@")
                for road_id in road_ids
            )
        )
        if matched:
            result.append(
                {
                    "audit_layer": str(row.get("audit_layer") or ""),
                    "audit_reason": str(row.get("audit_reason") or ""),
                    "final_topology_category": str(
                        row.get("final_topology_category") or ""
                    ),
                    "final_topology_object_key": object_key,
                }
            )
    return result


def _fold_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    fold_count: int,
) -> dict[str, Any]:
    folds = []
    for fold in range(fold_count):
        selected = [row for row in rows if int(row["fold"]) == fold]
        eligible = [row for row in selected if bool(row["eligible"])]
        hit = sum(bool(row["candidate_oracle_hit"]) for row in eligible)
        folds.append(
            {
                "candidate_oracle_hit_count": hit,
                "candidate_oracle_recall": (
                    hit / len(eligible) if eligible else 0.0
                ),
                "case_count": len({row["case_key"] for row in selected}),
                "comparable_candidate_group_count": sum(
                    bool(row["comparable_candidate_group"])
                    for row in selected
                ),
                "eligible_count": len(eligible),
                "fold": fold,
                "object_count": len(selected),
            }
        )
    return {
        "folds": folds,
        "worst_fold_candidate_oracle_recall": min(
            row["candidate_oracle_recall"] for row in folds
        ),
    }


def _metrics(
    *,
    truth_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    attachment_rows: Sequence[Mapping[str, Any]],
    case_count: int,
    fold_metrics: Mapping[str, Any],
    cfg: P12RConfig,
) -> dict[str, Any]:
    eligible = [row for row in candidate_rows if bool(row["eligible"])]
    automatic_truth = [
        row for row in truth_rows
        if str(row["truth_plan_type"]) != PLAN_REVIEW_FALLBACK
    ]
    valid_access = [row for row in truth_rows if bool(row["access_valid"])]
    oracle_hits = sum(
        bool(row["candidate_oracle_hit"]) for row in eligible
    )
    plan_counts = Counter(str(row["truth_plan_type"]) for row in truth_rows)
    fallback_counts = Counter(
        str(row["fallback_reason"])
        for row in truth_rows
        if row.get("fallback_reason")
    )
    unsafe_topology = sum(
        bool(row["topology_hard_failures"])
        and str(row["truth_plan_type"]) != PLAN_REVIEW_FALLBACK
        for row in truth_rows
    )
    return {
        "access_invalid_count": len(truth_rows) - len(valid_access),
        "advance_right_count": len(truth_rows),
        "attachment_segment_count": sum(
            len(row["attachment_segment_ids"]) for row in attachment_rows
        ),
        "automatic_truth_count": len(automatic_truth),
        "candidate_oracle_eligible_count": len(eligible),
        "candidate_oracle_hit_count": oracle_hits,
        "candidate_oracle_recall": (
            oracle_hits / len(eligible) if eligible else 0.0
        ),
        "case_count": case_count,
        "crs_consistent_count": sum(
            bool(row["crs_consistent"]) for row in truth_rows
        ),
        "crs_metric_count": sum(
            bool(row["crs_metric"]) for row in truth_rows
        ),
        "expected_advance_right_count": cfg.expected_advance_right_count,
        "fallback_reason_counts": dict(sorted(fallback_counts.items())),
        "geometry_write_count": 0,
        "independent_road_missing_segment_count": sum(
            len(row["independent_road_missing_segment_ids"])
            for row in attachment_rows
        ),
        "invalid_access_review_fallback_count": sum(
            not bool(row["access_valid"])
            and str(row["truth_plan_type"]) == PLAN_REVIEW_FALLBACK
            for row in truth_rows
        ),
        "lineage_complete_count": len(truth_rows),
        "missing_attachment_relation_count": sum(
            len(row["missing_relation_segment_ids"])
            for row in attachment_rows
        ),
        "plan_type_counts": dict(sorted(plan_counts.items())),
        "rcsd_missing_reality_change_clue_false_positive_count": sum(
            row.get("fallback_reason")
            == "RCSD_ADVANCE_RIGHT_UNAVAILABLE_OR_REJECTED"
            and bool(row.get("reality_change_clue"))
            for row in truth_rows
        ),
        "side_source_consistent_count": sum(
            bool(row["source_side_consistent"])
            and bool(row["target_side_consistent"])
            for row in automatic_truth
        ),
        "skeleton_mutation_count": 0,
        "t01_t12_modification_count": 0,
        "t05_advance_right_anchor_label_count": sum(
            bool(row["t05_anchor_label_used"]) for row in truth_rows
        ),
        "t06_terminal_candidate_count": sum(
            int(row["t06_terminal_candidate_count"])
            for row in candidate_rows
        ),
        "training_count": 0,
        "unresolved_realization_evidence_count": sum(
            row["source_realization_evidence"] == "UNRESOLVED"
            or row["target_realization_evidence"] == "UNRESOLVED"
            for row in automatic_truth
        ),
        "unsafe_auto_publish_count": unsafe_topology,
        "valid_access_count": len(valid_access),
        "valid_access_required_source_resolved_count": sum(
            row["source_required_source"] != REQUIRED_UNKNOWN
            and row["target_required_source"] != REQUIRED_UNKNOWN
            for row in valid_access
        ),
        "worst_fold_candidate_oracle_recall": fold_metrics[
            "worst_fold_candidate_oracle_recall"
        ],
    }


def _gates(
    metrics: Mapping[str, Any],
    fold_metrics: Mapping[str, Any],
    cfg: P12RConfig,
) -> dict[str, bool]:
    fold_rows = list(fold_metrics["folds"])
    return {
        "gate0_scope_lineage": (
            metrics["advance_right_count"]
            == cfg.expected_advance_right_count
            and metrics["case_count"] == cfg.expected_case_count
            and metrics["lineage_complete_count"]
            == cfg.expected_advance_right_count
            and metrics["t01_t12_modification_count"] == 0
        ),
        "gate1_business_semantics": (
            metrics["access_invalid_count"]
            == cfg.expected_invalid_access_count
            and metrics["invalid_access_review_fallback_count"]
            == cfg.expected_invalid_access_count
            and metrics["valid_access_required_source_resolved_count"]
            == metrics["valid_access_count"]
            and metrics["side_source_consistent_count"]
            == metrics["automatic_truth_count"]
            and metrics["t05_advance_right_anchor_label_count"] == 0
            and metrics[
                "rcsd_missing_reality_change_clue_false_positive_count"
            ]
            == 0
        ),
        "gate2_conditional_truth_safety": (
            metrics["missing_attachment_relation_count"] == 0
            and metrics["independent_road_missing_segment_count"] == 0
            and metrics["unresolved_realization_evidence_count"] == 0
            and metrics["unsafe_auto_publish_count"] == 0
        ),
        "gate3_candidate_ceiling": (
            metrics["t06_terminal_candidate_count"] == 0
            and metrics["candidate_oracle_recall"] >= 0.95
            and metrics["worst_fold_candidate_oracle_recall"] >= 0.90
            and all(
                row["object_count"] > 0
                and row["candidate_oracle_hit_count"] > 0
                and row["comparable_candidate_group_count"] > 0
                for row in fold_rows
            )
        ),
        "gate4_determinism_gis_resource": (
            metrics["crs_consistent_count"]
            == cfg.expected_advance_right_count
            and metrics["crs_metric_count"]
            == cfg.expected_advance_right_count
            and metrics["geometry_write_count"] == 0
            and metrics["training_count"] == 0
        ),
    }


def _decision(
    gates: Mapping[str, bool],
    metrics: Mapping[str, Any],
    fold_metrics: Mapping[str, Any],
) -> str:
    hard_gate_names = (
        "gate0_scope_lineage",
        "gate1_business_semantics",
        "gate2_conditional_truth_safety",
        "gate4_determinism_gis_resource",
    )
    if not all(gates[name] for name in hard_gate_names):
        return DECISION_AUDIT_NO_GO
    recall = float(metrics["candidate_oracle_recall"])
    worst = float(fold_metrics["worst_fold_candidate_oracle_recall"])
    if bool(gates["gate3_candidate_ceiling"]):
        return DECISION_GO
    if recall >= 0.90:
        return DECISION_REMEDIATION
    return DECISION_CANDIDATE_NO_GO


def _verify_baseline_inputs(root: Path) -> dict[Path, str]:
    missing = [
        name for name in _REQUIRED_BASELINE_FILES
        if not (root / name).is_file()
    ]
    if missing:
        raise ValueError(f"baseline inputs are missing: {missing}")
    manifest = _read_json(root / "artifact_manifest.json")
    records = {
        _path_name(row["path"]): row
        for row in manifest.get("artifacts", [])
    }
    verified: dict[Path, str] = {}
    for name in _REQUIRED_BASELINE_FILES:
        path = root / name
        digest = sha256_file(path)
        if name != "artifact_manifest.json":
            record = records.get(name)
            if record is None:
                raise ValueError(f"baseline manifest record missing: {name}")
            if digest != record.get("sha256"):
                raise ValueError(f"baseline artifact hash differs: {name}")
            if path.stat().st_size != int(record.get("size_bytes", -1)):
                raise ValueError(f"baseline artifact size differs: {name}")
        verified[path] = digest
    summary = _read_json(root / "scheme_a_summary.json")
    if (
        not bool(summary.get("gate_pass"))
        or bool(summary.get("content_repair"))
        or bool(summary.get("silent_fix"))
    ):
        raise ValueError("scheme-A baseline contract is not safe")
    return verified


def _resolve_case_paths(
    *,
    baseline_root: Path,
    case_row: Mapping[str, Any],
    poc_data_root: Path,
) -> tuple[CasePaths, dict[str, Any]]:
    skeleton_path = baseline_root / _relative_path(
        case_row["frozen_skeleton"]
    )
    skeleton = _read_json(skeleton_path)
    ar_segments = [
        row for row in skeleton.get("segments", [])
        if str(row.get("segment_type")) == "ADVANCE_RIGHT"
    ]
    if not ar_segments:
        raise ValueError("advance-right Case has no frozen object")
    evidence = [
        item
        for segment in ar_segments
        for item in segment.get("evidence_refs", [])
        if str(item.get("role")) == "t01_roads"
    ]
    if not evidence:
        raise ValueError("advance-right Case lacks T01 Road lineage")
    t01_paths = {_local_path(item["path"]) for item in evidence}
    if len(t01_paths) != 1:
        raise ValueError("advance-right Case has multiple T01 Road roots")
    t01_roads = next(iter(t01_paths))
    case_root = t01_roads.parent.parent
    t06_root = (
        case_root
        / "t06_step12"
        / "t06"
        / "step3_segment_replacement"
    )
    family = str(case_row["family"])
    business_id = str(case_row["business_id"])
    source_case = poc_data_root / family / business_id / "external_inputs"
    paths = CasePaths(
        case_key=str(case_row["case_key"]),
        family=family,
        business_id=business_id,
        frozen_skeleton=skeleton_path,
        t01_roads=t01_roads,
        t01_nodes=t01_roads.parent / "nodes.gpkg",
        raw_rcsd_roads=_unique_gpkg(source_case / "rcsdroad"),
        raw_rcsd_nodes=_unique_gpkg(source_case / "rcsdnode"),
        t06_relation=t06_root / "t06_step3_swsd_frcsd_segment_relation.csv",
        t06_attachment_audit=(
            t06_root / "t06_step3_advance_right_attachment_audit.csv"
        ),
        t06_closure_audit=(
            t06_root / "t06_step3_rcsd_advance_right_closure_audit.csv"
        ),
        t06_topology_audit=(
            t06_root / "t06_step3_topology_connectivity_audit.csv"
        ),
        t06_final_roads=t06_root / "t06_frcsd_road.gpkg",
        t06_final_nodes=t06_root / "t06_frcsd_node.gpkg",
    )
    missing = [str(path) for path in paths.input_paths() if not path.is_file()]
    if missing:
        raise ValueError(f"P12R Case inputs are missing: {missing}")
    return paths, skeleton


def _case_input_records(paths: CasePaths) -> list[dict[str, Any]]:
    records = []
    for path in paths.input_paths():
        records.append(
            {
                "case_key": paths.case_key,
                "path": str(path.resolve()),
                "role": f"{paths.case_key}:{path.name}",
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _load_manual_rows(
    root: Path | None,
) -> tuple[
    dict[tuple[str, str], Mapping[str, Any]],
    dict[str, Any] | None,
]:
    if root is None:
        return {}, None
    path = root / "accepted_manual_review.jsonl"
    if not path.is_file():
        raise ValueError("P11 accepted manual review artifact is missing")
    rows = _read_jsonl(path)
    mapping = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in rows
        if str(row.get("object_id") or "").startswith("advance_right_")
    }
    return mapping, {
        "path": str(path.resolve()),
        "role": "P11_MANUAL_REVIEW_LABEL_ONLY",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _read_roads(path: Path) -> list[RoadRecord]:
    result = []
    with fiona.open(path) as source:
        for feature in source:
            properties = dict(feature["properties"])
            geometry = shape(feature["geometry"])
            result.append(
                RoadRecord(
                    road_id=_id(properties.get("id") or feature.get("id")),
                    source=_int(properties.get("source")),
                    snodeid=_id(properties.get("snodeid")),
                    enodeid=_id(properties.get("enodeid")),
                    formway=_int(properties.get("formway")),
                    segment_id=str(properties.get("segmentid") or ""),
                    source_road_id=_id(properties.get("source_road_id")),
                    split_original_road_id=_id(
                        properties.get("t06_split_original_road_id")
                    ),
                    mixed_advance_right=_as_bool(
                        properties.get("t06_mixed_advance_right_carrier")
                    ),
                    geometry=geometry,
                    properties=properties,
                )
            )
    return result


def _read_nodes(path: Path) -> dict[str, Point]:
    result: dict[str, Point] = {}
    with fiona.open(path) as source:
        for feature in source:
            properties = dict(feature["properties"])
            node_id = _id(properties.get("id") or feature.get("id"))
            geometry = shape(feature["geometry"])
            if node_id in result:
                raise ValueError(f"duplicate Node id: {node_id}")
            result[node_id] = geometry
    return result


def _read_crs(path: Path) -> str:
    with fiona.open(path) as source:
        if not source.crs:
            raise ValueError(f"CRS is missing: {path}")
        return CRS.from_user_input(source.crs).to_string()


def _parse_access(value: Any) -> tuple[str, str]:
    text = str(value or "")
    if text.count("@") != 1:
        return "", ""
    owner, node_id = text.split("@", maxsplit=1)
    return owner.strip(), node_id.strip()


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    text = str(value).strip()
    if not text:
        return []
    parsed: Any
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return [text]
    if isinstance(parsed, (list, tuple, set)):
        return [str(item) for item in parsed if str(item)]
    return [str(parsed)] if str(parsed) else []


def _unique_gpkg(root: Path) -> Path:
    values = sorted(root.glob("*.gpkg"))
    if len(values) != 1:
        raise ValueError(f"expected one GPKG under {root}, got {len(values)}")
    return values[0]


def _local_path(value: Any) -> Path:
    path = Path(str(value))
    if path.exists() or os.name == "nt":
        return path
    windows = PureWindowsPath(str(value))
    drive = windows.drive.rstrip(":").lower()
    if len(drive) != 1 or not drive.isalpha():
        return path
    return Path("/mnt") / drive / Path(*windows.parts[1:])


def _path_name(value: Any) -> str:
    text = str(value)
    if "\\" in text:
        return PureWindowsPath(text).name
    return Path(text).name


def _relative_path(value: Any) -> Path:
    text = str(value)
    if "\\" in text:
        return Path(*PureWindowsPath(text).parts)
    return Path(text)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.write_text(
        "".join(
            json.dumps(
                dict(row),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value)
    if text.endswith(".0"):
        prefix = text[:-2]
        if prefix.lstrip("-").isdigit():
            return prefix
    return text


def _int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(float(value))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _peak_rss_bytes() -> int:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        if ok:
            return int(counters.PeakWorkingSetSize)
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if platform.system() == "Darwin" else value * 1024
    except (ImportError, OSError):
        return 0


def _validation_report(
    summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
    fold_metrics: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            "# P05-Scheme-A-P2-P3-P12R 验证报告",
            "",
            f"- decision：`{summary['decision']}`",
            f"- 提右真值：`{summary['object_count']}` 个，"
            f"`{summary['case_count']}` 个Case。",
            f"- 条件化plan：`{json.dumps(metrics['plan_type_counts'], ensure_ascii=False, sort_keys=True)}`",
            f"- candidate oracle：`{metrics['candidate_oracle_hit_count']}/"
            f"{metrics['candidate_oracle_eligible_count']}`，"
            f"recall=`{metrics['candidate_oracle_recall']:.6f}`。",
            f"- 最差fold recall："
            f"`{fold_metrics['worst_fold_candidate_oracle_recall']:.6f}`。",
            f"- 两侧来源一致：`{metrics['side_source_consistent_count']}/"
            f"{metrics['advance_right_count']}`。",
            f"- attachment relation缺失："
            f"`{metrics['missing_attachment_relation_count']}`；"
            f"独立Road缺失：`{metrics['independent_road_missing_segment_count']}`。",
            "- T05提右锚定标签、T06终态候选泄漏、训练、geometry write、"
            "骨架mutation和T01–T12修改均为0。",
            f"- gates：`{json.dumps(summary['gates'], ensure_ascii=False, sort_keys=True)}`",
            f"- 资源：wall=`{summary['performance']['wall_seconds']:.3f}s`，"
            f"peak RSS=`{summary['performance']['peak_rss_bytes']}` bytes，GPU=false。",
        ]
    ) + "\n"
