from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROCESS_CRS_TEXT = "EPSG:3857"

STEP1_DIR = "step1_identify_fusion_units"
STEP2_DIR = "step2_extract_rcsd_segments"
STEP3_DIR = "step3_segment_replacement"

STEP1_EVD_STEM = "t06_swsd_segment_evd_candidates"
STEP1_CANDIDATES_STEM = "t06_swsd_segment_candidates"
STEP1_FUSION_STEM = "t06_swsd_segment_fusion_units"
STEP1_FINAL_FUSION_STEM = "t06_swsd_segment_final_fusion_units"
STEP1_REJECTED_STEM = "t06_swsd_segment_rejected"
STEP1_SUMMARY = "t06_step1_summary.json"
STEP1_STATS_CSV = "t06_step1_segment_stats.csv"

STEP2_CANDIDATES_STEM = "t06_rcsd_segment_candidates"
STEP2_REPLACEABLE_STEM = "t06_rcsd_segment_replaceable"
STEP2_REJECTED_STEM = "t06_rcsd_segment_rejected"
STEP2_BUFFER_SEGMENTS_STEM = "t06_rcsd_buffer_segments"
STEP2_BUFFER_REJECTED_STEM = "t06_rcsd_buffer_segment_rejected"
STEP2_SUMMARY = "t06_step2_summary.json"

STEP3_FRCSD_ROAD_STEM = "t06_frcsd_road"
STEP3_FRCSD_NODE_STEM = "t06_frcsd_node"
STEP3_REPLACEMENT_UNITS_STEM = "t06_step3_replacement_units"
STEP3_JUNCTION_REBUILD_AUDIT_STEM = "t06_step3_junction_rebuild_audit"
STEP3_REMOVED_SWSD_ROADS_STEM = "t06_step3_removed_swsd_roads"
STEP3_REMOVED_SWSD_NODES_STEM = "t06_step3_removed_swsd_nodes"
STEP3_ADDED_RCSD_ROADS_STEM = "t06_step3_added_rcsd_roads"
STEP3_ADDED_RCSD_NODES_STEM = "t06_step3_added_rcsd_nodes"
STEP3_ID_COLLISION_AUDIT_STEM = "t06_step3_id_collision_audit"
STEP3_SUMMARY = "t06_step3_summary.json"

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

STEP1_STATS_FIELDS = [
    "sgrade",
    "total_segment_count",
    "evd_candidate_count",
    "final_fusion_unit_count",
]

STEP2_CANDIDATE_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "candidate_strategy",
    "candidate_status",
    "candidate_reason",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_pair_nodes",
    "rcsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "rcsd_junc_nodes",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "candidate_rcsd_road_ids",
    "candidate_rcsd_node_ids",
    "retained_rcsd_road_ids",
    "retained_node_ids",
    "inner_node_ids",
    "out_node_ids",
    "unexpected_endpoint_node_ids",
    "unexpected_mapped_semantic_node_ids",
    "excluded_advance_right_turn_road_ids",
    "selected_component_id",
    "candidate_road_count",
    "retained_road_count",
    "candidate_node_count",
    "retained_node_count",
]

STEP2_REPLACEABLE_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "replacement_ready",
    "replacement_strategy",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_pair_nodes",
    "rcsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "rcsd_junc_nodes",
    "rcsd_road_ids",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "retained_node_ids",
    "inner_node_ids",
    "out_node_ids",
    "unexpected_endpoint_node_ids",
    "unexpected_mapped_semantic_node_ids",
    "excluded_advance_right_turn_road_ids",
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
    "unexpected_endpoint_node_ids",
    "unexpected_mapped_semantic_node_ids",
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
    "retained_rcsd_road_ids",
    "candidate_rcsd_road_ids",
    "candidate_rcsd_node_ids",
    "excluded_advance_right_turn_road_ids",
    "retained_node_ids",
    "inner_node_ids",
    "out_node_ids",
    "unexpected_endpoint_node_ids",
    "unexpected_mapped_semantic_node_ids",
    "selected_component_id",
    "candidate_road_count",
    "retained_road_count",
    "candidate_node_count",
    "retained_node_count",
]

STEP3_REPLACEMENT_UNIT_FIELDS = [
    "swsd_segment_id",
    "unit_status",
    "unit_reason",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "swsd_road_ids",
    "removed_swsd_road_ids",
    "removed_swsd_node_ids",
    "rcsd_road_ids",
    "rcsd_node_ids",
    "rcsd_pair_nodes",
    "rcsd_junc_nodes",
    "junction_c_ids",
]

STEP3_JUNCTION_REBUILD_AUDIT_FIELDS = [
    "junction_c_id",
    "replacement_segment_ids",
    "original_mainnode_id",
    "original_mainnode_removed",
    "new_mainnode_id",
    "mainnode_selection_reason",
    "original_member_node_ids",
    "removed_swsd_node_ids",
    "remaining_swsd_node_ids",
    "added_rcsd_node_ids",
    "rebuilt_node_ids",
    "inherited_kind",
    "inherited_grade",
    "inherited_kind_2",
    "inherited_grade_2",
    "inherited_closed_con",
]

STEP3_CHANGE_AUDIT_FIELDS = [
    "entity_id",
    "entity_type",
    "source",
    "reason",
    "swsd_segment_ids",
]

STEP3_ID_COLLISION_AUDIT_FIELDS = [
    "entity_type",
    "entity_id",
    "swsd_present",
    "rcsd_present",
    "policy",
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
    swsd_candidates_gpkg_path: Path | None = None
    final_fusion_units_gpkg_path: Path | None = None
    stats_csv_path: Path | None = None


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
class T06Step3Artifacts:
    run_id: str
    run_root: Path
    step_root: Path
    frcsd_road_gpkg_path: Path
    frcsd_node_gpkg_path: Path
    replacement_units_gpkg_path: Path
    junction_rebuild_audit_gpkg_path: Path
    summary_path: Path


@dataclass(frozen=True)
class T06PrecheckArtifacts:
    run_id: str
    run_root: Path
    step1: T06Step1Artifacts
    step2: T06Step2Artifacts


def feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"properties": properties, "geometry": geometry}
