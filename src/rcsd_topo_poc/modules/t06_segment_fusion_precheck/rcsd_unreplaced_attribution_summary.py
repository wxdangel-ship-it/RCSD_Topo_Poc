"""RCSD road attribution for unreplaced Step3 output."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from .io import write_feature_triplet, write_json
from .parsing import normalize_id, parse_id_list, unique_preserve_order
from .schemas import STEP3_SUMMARY

PROCESS_CRS = "EPSG:3857"
STEP1_DIR_NAME = "step1_identify_fusion_units"
STEP2_DIR_NAME = "step2_extract_rcsd_segments"
STEP3_DIR_NAME = "step3_segment_replacement"

STEP1_CANDIDATES_STEM = "t06_swsd_segment_candidates"
STEP1_FINAL_FUSION_UNITS_STEM = "t06_swsd_segment_final_fusion_units"
STEP1_REJECTED_STEM = "t06_swsd_segment_rejected"
STEP2_REPLACEABLE_STEM = "t06_rcsd_segment_replaceable"
STEP2_CANDIDATES_STEM = "t06_rcsd_segment_candidates"
STEP2_REJECTED_STEM = "t06_rcsd_segment_rejected"
STEP2_PLAN_STEM = "t06_segment_replacement_plan"
STEP2_PROBLEM_REGISTRY_STEM = "t06_segment_replacement_problem_registry"
STEP3_FRCSD_ROAD_STEM = "t06_frcsd_road"
STEP3_REPLACEMENT_UNITS_STEM = "t06_step3_replacement_units"
STEP3_RELATION_STEM = "t06_step3_swsd_frcsd_segment_relation"
STEP3_UNREPLACED_RCSD_STEM = "t06_step3_unreplaced_rcsd_roads"
ATTRIBUTION_STEM = "t06_step3_unreplaced_rcsd_attribution"
ATTRIBUTION_SUMMARY_NAME = "t06_step3_unreplaced_rcsd_attribution_summary.json"

RELATION_FAILURE_REASONS = {
    "invalid_pair_base_id",
    "invalid_pair_relation_status",
    "missing_pair_relation",
    "missing_relation",
    "pair_relation_missing",
    "relation_failed",
}

RELATION_INCOMPLETE_IF_NOT_REPLACEABLE_REASONS = {
    "required_semantic_nodes_missing_from_buffer_graph",
    "required_semantic_nodes_not_connected_in_buffer",
    "rcsd_pair_nodes_not_distinct",
}

STEP3_FAILURE_STATUSES = {"failed", "topology_failed", "connectivity_failed"}
STEP3_PARTIAL_STATUSES = {"replaced+retained_swsd", "partial_replaced"}
STEP3_SUCCESS_STATUSES = {"replaced", "replaced+retained_swsd", "retained_swsd"}
STEP3_REPLACED_STATUSES = {"replaced", "replaced+retained_swsd", "failed"}
CANDIDATE_ONLY_POST_REPLACEMENT_REVIEW_FLAG = "candidate_only_post_replacement_review"
CANDIDATE_ONLY_MANUAL_AUDIT_CLASS = "6_unattributed_manual_audit_without_dominant_class"
CANDIDATE_ONLY_MANUAL_AUDIT_SUBCLASS = "6_candidate_only_post_replacement_review"

PRIMARY_BUFFER_M = 20.0
PRIMARY_MIN_COVER_RATIO = 0.5
AUDIT_MIN_STRONG_COVER_RATIO = 0.85
AUDIT_MAX_STRONG_DISTANCE_M = 5.0
MIXED_COMPETING_MAX_DISTANCE_M = 1.0
MIXED_COMPETING_MIN_PRIMARY_COVER_RATIO = 0.05

PPT_CLASS_SEGMENT_RCSD_QUALITY = "1_segment_rcsd_quality_unreplaceable"
PPT_CLASS_SEGMENT_PREREQUISITE_UNSATISFIED = "2_segment_replacement_prerequisite_unsatisfied"
PPT_CLASS_OUTSIDE_SEGMENT_SCOPE = "3_rcsd_outside_segment_scope"
PPT_CLASS_MANUAL_AUDIT = "6_manual_audit"


def _build_summary(
    *,
    features: list[dict[str, Any]],
    rcsd_roads: gpd.GeoDataFrame,
    unreplaced_roads: gpd.GeoDataFrame,
    audit_buffer_m: float,
    target_crs: Any,
    swsd_segment_count: int,
    evidence_segment_count: int,
    relation_segment_count: int,
    replaceable_segment_count: int,
    step2_reported_relation_success_count: Any,
    step2_reported_relation_failure_count: Any,
    attribution_gpkg_path: Path,
    attribution_csv_path: Path,
) -> dict[str, Any]:
    total_count = int(len(rcsd_roads))
    total_length = _frame_length_m(rcsd_roads)
    raw_unreplaced_count = int(len(unreplaced_roads))
    raw_unreplaced_length = _frame_length_m(unreplaced_roads)
    unreplaced_count = int(len(features))
    unreplaced_length = _features_length_m(features)
    replaced_count = max(total_count - unreplaced_count, 0)
    replaced_length = max(total_length - unreplaced_length, 0.0)
    rows = [dict(feature.get("properties") or {}) for feature in features]
    by_class = _aggregate(rows, "attribution_class", total_length, unreplaced_length)
    by_subclass = _aggregate(rows, "attribution_subclass", total_length, unreplaced_length)
    by_owner = _aggregate(rows, "attribution_owner", total_length, unreplaced_length)
    by_final_class = _aggregate(rows, "final_attribution_class", total_length, unreplaced_length)
    by_final_subclass = _aggregate(rows, "final_attribution_subclass", total_length, unreplaced_length)
    by_final_owner = _aggregate(rows, "final_attribution_owner", total_length, unreplaced_length)
    by_final_confidence = _aggregate(rows, "final_attribution_confidence", total_length, unreplaced_length)
    by_ppt_class = _aggregate(rows, "ppt_attribution_class", total_length, unreplaced_length)
    by_ppt_review_flag = _aggregate(rows, "ppt_review_flag", total_length, unreplaced_length)
    return {
        "audit_name": "t06_step3_unreplaced_rcsd_attribution",
        "audit_buffer_m": float(audit_buffer_m),
        "geometry_primary_buffer_m": PRIMARY_BUFFER_M,
        "geometry_primary_min_cover_ratio": PRIMARY_MIN_COVER_RATIO,
        "geometry_audit_min_strong_cover_ratio": AUDIT_MIN_STRONG_COVER_RATIO,
        "geometry_audit_max_strong_distance_m": AUDIT_MAX_STRONG_DISTANCE_M,
        "crs": str(target_crs),
        "classification_priority": ["5", "4", "3", "2", "1", "6"],
        "final_classification_rule": (
            "road-level exact plan/unit evidence first; otherwise choose the geometric primary SWSD Segment "
            "before applying the six-class attribution; weak primary matches become class 1; mixed partial "
            "coverage keeps the primary Segment class with low confidence and a PPT review flag; candidate-only "
            "roads already present in final FRCSD are treated as replaced and excluded from unreplaced attribution; "
            "candidate-only roads on successful replaced/retained segments without exact plan/unit evidence are "
            "class 6 manual-audit risks rather than confirmed class 5 unreplaced roads."
        ),
        "ppt_class_mapping": {
            "1_segment_rcsd_quality_unreplaceable": [
                "4_relation_scope_not_replaceable",
                "5_replaceable_scope_unreplaced",
            ],
            "2_segment_replacement_prerequisite_unsatisfied": [
                "2_swsd_scope_no_t06_evidence",
                "3_evidence_scope_relation_incomplete",
            ],
            "3_rcsd_outside_segment_scope": ["1_outside_swsd_segment_scope"],
            "6_manual_audit": [
                "6_unattributed_manual_audit_without_dominant_class",
            ],
        },
        "total_rcsd_road_count": total_count,
        "total_rcsd_road_length_m": round(total_length, 3),
        "raw_step3_unreplaced_rcsd_road_count": raw_unreplaced_count,
        "raw_step3_unreplaced_rcsd_road_length_m": round(raw_unreplaced_length, 3),
        "unreplaced_rcsd_road_count": unreplaced_count,
        "unreplaced_rcsd_road_length_m": round(unreplaced_length, 3),
        "replaced_rcsd_road_count": replaced_count,
        "replaced_rcsd_road_length_m": round(replaced_length, 3),
        "replaced_rcsd_road_rate_by_count": _rate(replaced_count, total_count),
        "replaced_rcsd_road_rate_by_length": _rate(replaced_length, total_length),
        "swsd_segment_count": swsd_segment_count,
        "evidence_segment_count": evidence_segment_count,
        "relation_scope_segment_count": relation_segment_count,
        "step2_reported_relation_success_count": step2_reported_relation_success_count,
        "step2_reported_relation_failure_count": step2_reported_relation_failure_count,
        "replaceable_scope_segment_count": replaceable_segment_count,
        "by_attribution_class": by_class,
        "by_attribution_subclass": by_subclass,
        "by_attribution_owner": by_owner,
        "by_final_attribution_class": by_final_class,
        "by_final_attribution_subclass": by_final_subclass,
        "by_final_attribution_owner": by_final_owner,
        "by_final_attribution_confidence": by_final_confidence,
        "by_ppt_attribution_class": by_ppt_class,
        "by_ppt_review_flag": by_ppt_review_flag,
        "outputs": {
            "gpkg": str(attribution_gpkg_path),
            "csv": str(attribution_csv_path),
        },
        "qa_notes": {
            "crs_check": "All spatial joins are normalized to one working CRS before buffering.",
            "topology_check": "This audit is read-only and does not perform silent geometry fixes.",
            "geometry_semantics": "Final attribution selects the geometric primary Segment before applying funnel status.",
            "traceability": "Each attributed road keeps matched segment ids and upstream Step1/Step2/Step3 reasons.",
            "performance": "One spatial join collects candidate Segment matches and records per-match geometry metrics.",
        },
    }


def _frame_length_m(frame: gpd.GeoDataFrame) -> float:
    if frame.empty:
        return 0.0
    if "length_m" in frame.columns:
        return float(frame["length_m"].fillna(0).sum())
    return float(frame.geometry.length.sum())


def _features_length_m(features: list[dict[str, Any]]) -> float:
    return float(sum(float((feature.get("properties") or {}).get("length_m") or 0.0) for feature in features))


def _aggregate(rows: list[dict[str, Any]], key: str, total_length: float, unreplaced_length: float) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value not in grouped:
            grouped[value] = {"value": value, "count": 0, "length_m": 0.0}
        grouped[value]["count"] += 1
        grouped[value]["length_m"] += float(row.get("length_m") or 0.0)
    out = []
    for item in grouped.values():
        length = float(item["length_m"])
        out.append(
            {
                "value": item["value"],
                "count": int(item["count"]),
                "length_m": round(length, 3),
                "unreplaced_length_rate": _rate(length, unreplaced_length),
                "total_length_rate": _rate(length, total_length),
            }
        )
    return sorted(out, key=lambda item: (-item["length_m"], item["value"]))


def _rate(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _patch_step3_summary(
    step3_summary_path: Path,
    attribution_summary: dict[str, Any],
    attribution_gpkg_path: Path,
    attribution_summary_path: Path,
) -> None:
    if not step3_summary_path.exists():
        return
    summary = json.loads(step3_summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        return
    summary["rcsd_unreplaced_attribution_count"] = attribution_summary["unreplaced_rcsd_road_count"]
    summary["rcsd_unreplaced_attribution_length_m"] = attribution_summary["unreplaced_rcsd_road_length_m"]
    summary["rcsd_unreplaced_attribution_by_class"] = attribution_summary["by_attribution_class"]
    summary["rcsd_unreplaced_final_attribution_by_class"] = attribution_summary["by_final_attribution_class"]
    summary["rcsd_unreplaced_final_attribution_by_confidence"] = attribution_summary[
        "by_final_attribution_confidence"
    ]
    summary["rcsd_unreplaced_ppt_attribution_by_class"] = attribution_summary["by_ppt_attribution_class"]
    outputs = summary.setdefault("outputs", {})
    if isinstance(outputs, dict):
        outputs["unreplaced_rcsd_attribution_gpkg"] = str(attribution_gpkg_path)
        outputs["unreplaced_rcsd_attribution_summary"] = str(attribution_summary_path)
    write_json(step3_summary_path, summary)


def _attribution_fields() -> list[str]:
    return [
        "id",
        "rcsd_road_id",
        "snodeid",
        "enodeid",
        "direction",
        "formway",
        "patchid",
        "source",
        "length_m",
        "attribution_priority",
        "attribution_class",
        "attribution_subclass",
        "attribution_owner",
        "attribution_reason",
        "coarse_attribution_class",
        "coarse_attribution_subclass",
        "final_attribution_class",
        "final_attribution_subclass",
        "final_attribution_owner",
        "final_attribution_reason",
        "final_attribution_confidence",
        "final_attribution_basis",
        "final_primary_segment_id",
        "final_primary_scope",
        "final_primary_distance_m",
        "final_primary_cover20_ratio",
        "final_primary_cover50_ratio",
        "final_primary_effective_match",
        "final_competing_segment_id",
        "final_competing_distance_m",
        "final_competing_cover20_ratio",
        "final_competing_cover50_ratio",
        "final_plan_statuses",
        "final_step3_relation_statuses",
        "final_step1_reject_reasons",
        "final_step2_reject_reasons",
        "final_problem_registry_reasons",
        "competing_final_attribution_classes",
        "ppt_attribution_class",
        "ppt_attribution_label",
        "ppt_source_attribution_class",
        "ppt_review_flag",
        "audit_buffer_m",
        "matched_segment_count",
        "matched_segment_ids",
        "matched_evidence_segment_ids",
        "matched_relation_segment_ids",
        "matched_replaceable_segment_ids",
        "step1_reject_reasons",
        "step2_reject_reasons",
        "problem_registry_reasons",
        "plan_statuses",
        "step3_relation_statuses",
    ]
