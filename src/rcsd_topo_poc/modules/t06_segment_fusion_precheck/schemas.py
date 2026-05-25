from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROCESS_CRS_TEXT = "EPSG:3857"

STEP1_DIR = "step1_identify_fusion_units"
STEP2_DIR = "step2_extract_rcsd_segments"

STEP1_EVD_STEM = "t06_swsd_segment_evd_candidates"
STEP1_FUSION_STEM = "t06_swsd_segment_fusion_units"
STEP1_REJECTED_STEM = "t06_swsd_segment_rejected"
STEP1_SUMMARY = "t06_step1_summary.json"

STEP2_CANDIDATES_STEM = "t06_rcsd_segment_candidates"
STEP2_REPLACEABLE_STEM = "t06_rcsd_segment_replaceable"
STEP2_REJECTED_STEM = "t06_rcsd_segment_rejected"
STEP2_BUFFER_SEGMENTS_STEM = "t06_rcsd_buffer_segments"
STEP2_BUFFER_REJECTED_STEM = "t06_rcsd_buffer_segment_rejected"
STEP2_SUMMARY = "t06_step2_summary.json"

FUSION_UNIT_FIELDS = [
    "swsd_segment_id",
    "sgrade",
    "pair_nodes",
    "junc_nodes",
    "semantic_node_set",
    "roads",
    "pair_node_count",
    "junc_node_count",
    "junc_kind2_exempt_nodes",
    "has_fail4_fallback",
]

STEP1_REJECTED_FIELDS = [
    "swsd_segment_id",
    "reject_stage",
    "reject_reason",
    "failed_node_ids",
    "failed_node_attrs",
    "junc_kind2_exempt_nodes",
    "pair_nodes",
    "junc_nodes",
    "sgrade",
]

STEP2_CANDIDATE_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_oneway_source_node",
    "swsd_oneway_target_node",
    "swsd_direction_inference",
    "rcsd_directionality",
    "swsd_pair_nodes",
    "rcsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "rcsd_junc_nodes",
    "rcsd_road_ids",
    "rcsd_node_path",
    "rcsd_forward_reachable",
    "rcsd_reverse_reachable",
    "directionality_trend_pass",
    "oneway_direction_trend_pass",
    "semantic_junc_order_trend_pass",
    "main_axis_angle_diff_deg",
    "main_axis_trend_pass",
    "length_ratio",
    "coarse_length_trend_pass",
    "candidate_status",
    "candidate_reason",
]

STEP2_REPLACEABLE_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "replacement_ready",
    "swsd_sgrade",
    "swsd_directionality",
    "rcsd_directionality",
    "swsd_pair_nodes",
    "rcsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "rcsd_junc_nodes",
    "rcsd_road_ids",
    "trend_filter_passed",
    "hard_filter_passed",
]

STEP2_REJECTED_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "reject_stage",
    "reject_reason",
    "failed_pair_nodes",
    "failed_junc_nodes",
    "junc_kind2_exempt_nodes",
    "failed_metric_name",
    "failed_metric_value",
    "threshold_value",
    "notes",
]

STEP2_BUFFER_SEGMENT_FIELDS = [
    "swsd_segment_id",
    "buffer_candidate_id",
    "buffer_status",
    "buffer_reason",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "retained_rcsd_road_ids",
    "candidate_rcsd_road_ids",
    "candidate_rcsd_node_ids",
    "excluded_advance_right_turn_road_ids",
    "retained_node_ids",
    "inner_node_ids",
    "out_node_ids",
    "selected_component_id",
    "candidate_road_count",
    "retained_road_count",
    "candidate_node_count",
    "retained_node_count",
]

STEP2_BUFFER_REJECTED_FIELDS = [
    "swsd_segment_id",
    "reject_stage",
    "reject_reason",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "missing_required_node_ids",
    "candidate_rcsd_road_ids",
    "candidate_rcsd_node_ids",
    "excluded_advance_right_turn_road_ids",
    "selected_component_id",
    "candidate_road_count",
    "retained_road_count",
    "candidate_node_count",
    "retained_node_count",
]


@dataclass(frozen=True)
class T06Step1Artifacts:
    run_id: str
    run_root: Path
    step_root: Path
    evd_candidates_gpkg_path: Path
    fusion_units_gpkg_path: Path
    rejected_gpkg_path: Path
    summary_path: Path


@dataclass(frozen=True)
class T06Step2Artifacts:
    run_id: str
    run_root: Path
    step_root: Path
    candidates_gpkg_path: Path
    replaceable_gpkg_path: Path
    rejected_gpkg_path: Path
    summary_path: Path


@dataclass(frozen=True)
class T06PrecheckArtifacts:
    run_id: str
    run_root: Path
    step1: T06Step1Artifacts
    step2: T06Step2Artifacts


def feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"properties": properties, "geometry": geometry}
