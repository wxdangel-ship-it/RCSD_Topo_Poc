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
STEP2_SPECIAL_JUNCTION_GROUPS_STEM = "t06_special_junction_group_audit"
STEP2_BUFFER_ONLY_PROBE_STEM = "t06_rcsd_buffer_only_probe"
STEP2_REPAIR_CANDIDATES_STEM = "t06_rcsd_repair_candidates"
STEP2_FAILURE_BUSINESS_AUDIT_STEM = "t06_rcsd_segment_failure_business_audit"
STEP2_GROUP_REPLACEMENT_AUDIT_STEM = "t06_segment_group_replacement_audit"
STEP2_REPLACEMENT_PLAN_STEM = "t06_segment_replacement_plan"
STEP2_PROBLEM_REGISTRY_STEM = "t06_segment_replacement_problem_registry"
STEP2_SUMMARY = "t06_step2_summary.json"

STEP3_FRCSD_ROAD_STEM = "t06_frcsd_road"
STEP3_FRCSD_NODE_STEM = "t06_frcsd_node"
STEP3_REPLACEMENT_UNITS_STEM = "t06_step3_replacement_units"
STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM = "t06_step3_swsd_frcsd_segment_relation"
STEP3_JUNCTION_REBUILD_AUDIT_STEM = "t06_step3_junction_rebuild_audit"
STEP3_REMOVED_SWSD_ROADS_STEM = "t06_step3_removed_swsd_roads"
STEP3_REMOVED_SWSD_NODES_STEM = "t06_step3_removed_swsd_nodes"
STEP3_ADDED_RCSD_ROADS_STEM = "t06_step3_added_rcsd_roads"
STEP3_ADDED_RCSD_NODES_STEM = "t06_step3_added_rcsd_nodes"
STEP3_UNREPLACED_RCSD_ROADS_STEM = "t06_step3_unreplaced_rcsd_roads"
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
    "detached_junc_nodes",
    "detached_junc_reasons",
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
    "adaptive_buffer_status",
    "adaptive_buffer_distance_m",
    "adaptive_buffer_source_reason",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_pair_nodes",
    "directed_swsd_pair_nodes",
    "original_rcsd_pair_nodes",
    "rcsd_pair_nodes",
    "directed_rcsd_pair_nodes",
    "special_junction_group_ids",
    "special_junction_group_types",
    "special_junction_gate_status",
    "special_junction_blocking_group_ids",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "rcsd_junc_nodes",
    "optional_junc_nodes",
    "optional_junc_rcsd_nodes",
    "dropped_junc_nodes",
    "dropped_junc_relation_nodes",
    "lost_attach_road_ids",
    "promoted_attach_road_ids",
    "blocked_attach_road_ids",
    "attach_promotion_status",
    "attach_promotion_reason",
    "isolated_attach_loss_count",
    "junc_attach_loss_reason",
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
    "directionality_conflict_status",
    "directionality_conflict_action",
    "directionality_conflict_reason",
    "forward_rcsd_road_ids",
    "bidirectional_rcsd_road_ids",
    "reverse_or_extra_rcsd_road_ids",
    "geometry_buffer_coverage_issue",
    "rcsd_outside_swsd_buffer_length_m",
    "rcsd_outside_swsd_buffer_ratio",
    "swsd_uncovered_by_rcsd_length_m",
    "swsd_uncovered_by_rcsd_ratio",
]

STEP2_REPLACEABLE_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "replacement_ready",
    "replacement_strategy",
    "adaptive_buffer_status",
    "adaptive_buffer_distance_m",
    "adaptive_buffer_source_reason",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_pair_nodes",
    "directed_swsd_pair_nodes",
    "original_rcsd_pair_nodes",
    "rcsd_pair_nodes",
    "directed_rcsd_pair_nodes",
    "special_junction_group_ids",
    "special_junction_group_types",
    "special_junction_gate_status",
    "special_junction_blocking_group_ids",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "rcsd_junc_nodes",
    "optional_junc_nodes",
    "optional_junc_rcsd_nodes",
    "dropped_junc_nodes",
    "dropped_junc_relation_nodes",
    "lost_attach_road_ids",
    "promoted_attach_road_ids",
    "blocked_attach_road_ids",
    "attach_promotion_status",
    "attach_promotion_reason",
    "isolated_attach_loss_count",
    "junc_attach_loss_reason",
    "rcsd_road_ids",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "retained_node_ids",
    "inner_node_ids",
    "out_node_ids",
    "unexpected_endpoint_node_ids",
    "unexpected_mapped_semantic_node_ids",
    "excluded_advance_right_turn_road_ids",
    "directionality_conflict_status",
    "directionality_conflict_action",
    "directionality_conflict_reason",
    "forward_rcsd_road_ids",
    "bidirectional_rcsd_road_ids",
    "reverse_or_extra_rcsd_road_ids",
    "geometry_buffer_coverage_issue",
    "rcsd_outside_swsd_buffer_length_m",
    "rcsd_outside_swsd_buffer_ratio",
    "swsd_uncovered_by_rcsd_length_m",
    "swsd_uncovered_by_rcsd_ratio",
    "hard_filter_passed",
]

STEP2_REJECTED_FIELDS = [
    "swsd_segment_id",
    "rcsd_candidate_id",
    "swsd_sgrade",
    "swsd_directionality",
    "reject_stage",
    "reject_reason",
    "root_cause_category",
    "full_graph_status",
    "candidate_graph_status",
    "directional_status",
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
    "adaptive_buffer_status",
    "adaptive_buffer_distance_m",
    "adaptive_buffer_source_reason",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "directed_rcsd_pair_nodes",
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
    "directionality_conflict_status",
    "directionality_conflict_action",
    "directionality_conflict_reason",
    "forward_rcsd_road_ids",
    "bidirectional_rcsd_road_ids",
    "reverse_or_extra_rcsd_road_ids",
    "geometry_buffer_coverage_issue",
    "rcsd_outside_swsd_buffer_length_m",
    "rcsd_outside_swsd_buffer_ratio",
    "swsd_uncovered_by_rcsd_length_m",
    "swsd_uncovered_by_rcsd_ratio",
]

STEP2_BUFFER_REJECTED_FIELDS = [
    "swsd_segment_id",
    "reject_stage",
    "reject_reason",
    "root_cause_category",
    "full_graph_status",
    "candidate_graph_status",
    "directional_status",
    "required_rcsd_nodes",
    "optional_allowed_rcsd_nodes",
    "directed_rcsd_pair_nodes",
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
    "notes",
]

STEP2_SPECIAL_JUNCTION_GROUP_FIELDS = [
    "special_junction_id",
    "special_junction_type",
    "gate_status",
    "relation_status",
    "rcsd_junction_id",
    "associated_segment_ids",
    "associated_segment_count",
    "replaceable_segment_ids",
    "replaceable_segment_count",
    "missing_replaceable_segment_ids",
    "removed_replaceable_segment_ids",
    "rcsd_junction_node_ids",
    "rcsd_junction_road_ids",
    "notes",
]

STEP2_GROUP_REPLACEMENT_AUDIT_FIELDS = [
    "swsd_segment_id",
    "audit_status",
    "corridor_audit_status",
    "source_reject_reason",
    "failure_business_category",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "rcsd_pair_nodes",
    "path_direction_count",
    "path_rcsd_road_ids",
    "path_rcsd_node_ids",
    "unexpected_mapped_rcsd_node_ids",
    "unexpected_mapped_swsd_target_ids",
    "unexpected_mapped_swsd_target_count",
    "group_segment_ids",
    "group_segment_count",
    "replaceable_group_segment_ids",
    "rejected_group_segment_ids",
    "outside_step1_group_segment_ids",
    "blocked_group_segment_ids",
    "blocker_reasons",
    "path_corridor_group_segment_ids",
    "path_corridor_group_segment_count",
    "path_corridor_blocked_segment_ids",
    "path_corridor_blocker_reasons",
    "side_incident_group_segment_ids",
    "group_probe_status",
    "group_probe_reason",
    "group_probe_buffer_distance_m",
    "group_probe_rcsd_road_ids",
    "group_probe_rcsd_road_count",
    "group_probe_swsd_uncovered_ratio",
    "group_probe_rcsd_outside_ratio",
    "group_probe_repair_owner",
    "repair_recommendation",
    "notes",
]

STEP2_BUFFER_ONLY_PROBE_FIELDS = [
    "swsd_segment_id",
    "probe_status",
    "buffer_only_candidate_status",
    "failure_business_category",
    "original_pair_nodes",
    "original_rcsd_pair_nodes",
    "candidate_rcsd_pair_node_sets",
    "candidate_score",
    "geometry_overlap_ratio",
    "directionality_score",
    "connectivity_score",
    "shape_similarity_score",
    "candidate_rcsd_road_ids",
    "candidate_rcsd_node_ids",
    "candidate_component_count",
    "manual_review_required",
    "repair_recommendation",
    "source_reject_reason",
    "notes",
]

STEP2_REPAIR_CANDIDATE_FIELDS = [
    "swsd_segment_id",
    "original_pair_nodes",
    "original_rcsd_pair_nodes",
    "candidate_rcsd_pair_node_sets",
    "candidate_score",
    "geometry_overlap_ratio",
    "directionality_score",
    "connectivity_score",
    "shape_similarity_score",
    "manual_review_required",
    "repair_recommendation",
    "buffer_only_candidate_status",
    "failure_business_category",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_endpoint_cluster_nodes",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "pair_anchor_diagnostic_source",
    "pair_anchor_diagnostic_reason",
    "candidate_rcsd_road_ids",
    "candidate_rcsd_node_ids",
    "source_reject_reason",
]

STEP2_FAILURE_BUSINESS_AUDIT_FIELDS = [
    "swsd_segment_id",
    "segment_outcome",
    "reject_reason",
    "scenario_type",
    "buffer_only_candidate_status",
    "failure_business_category",
    "auto_fix_candidate",
    "manual_review_required",
    "repair_recommendation",
    "adaptive_buffer_status",
    "adaptive_buffer_distance_m",
    "adaptive_buffer_source_reason",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_endpoint_cluster_nodes",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "pair_anchor_diagnostic_source",
    "pair_anchor_diagnostic_reason",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "original_rcsd_pair_nodes",
    "rcsd_pair_nodes",
    "rcsd_junc_nodes",
    "required_rcsd_nodes",
    "optional_junc_nodes",
    "optional_junc_rcsd_nodes",
    "dropped_junc_nodes",
    "dropped_junc_relation_nodes",
    "lost_attach_road_ids",
    "promoted_attach_road_ids",
    "blocked_attach_road_ids",
    "attach_promotion_status",
    "attach_promotion_reason",
    "isolated_attach_loss_count",
    "junc_attach_loss_reason",
    "candidate_rcsd_pair_node_sets",
    "candidate_score",
    "geometry_overlap_ratio",
    "directionality_score",
    "connectivity_score",
    "shape_similarity_score",
    "root_cause_category",
    "upstream_issue_owner",
]

STEP2_REPLACEMENT_PLAN_FIELDS = [
    "replacement_plan_id",
    "swsd_segment_id",
    "plan_status",
    "execution_action",
    "execution_scope",
    "plan_owner",
    "upstream_owner",
    "source_artifact",
    "source_reason",
    "replacement_strategy",
    "special_junction_id",
    "special_junction_type",
    "swsd_sgrade",
    "swsd_directionality",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "detached_junc_nodes",
    "optional_junc_nodes",
    "optional_junc_rcsd_nodes",
    "dropped_junc_nodes",
    "dropped_junc_relation_nodes",
    "original_rcsd_pair_nodes",
    "rcsd_pair_nodes",
    "rcsd_junc_nodes",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_repair_recommendation",
    "pair_anchor_repair_manual_review_required",
    "postplan_anchor_gate_original_reason",
    "postplan_anchor_gate_evidence",
    "postplan_anchor_gate_peer_segment_ids",
    "rcsd_road_ids",
    "retained_node_ids",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "group_segment_ids",
    "source_segment_ids",
    "buffer_distances_m",
    "directionality_conflict_status",
    "directionality_conflict_action",
    "directionality_conflict_reason",
    "forward_rcsd_road_ids",
    "bidirectional_rcsd_road_ids",
    "reverse_or_extra_rcsd_road_ids",
    "risk_flags",
    "notes",
]

STEP2_PROBLEM_REGISTRY_FIELDS = [
    "problem_id",
    "swsd_segment_id",
    "problem_status",
    "root_cause_category",
    "failure_business_category",
    "reject_reason",
    "upstream_issue_owner",
    "recommended_module",
    "feedback_action",
    "replan_trigger",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "rcsd_pair_nodes",
    "candidate_rcsd_pair_node_sets",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_endpoint_cluster_nodes",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "pair_anchor_diagnostic_source",
    "pair_anchor_diagnostic_reason",
    "evidence_artifacts",
    "manual_review_required",
    "notes",
]

STEP3_REPLACEMENT_UNIT_FIELDS = [
    "swsd_segment_id",
    "unit_status",
    "unit_reason",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "detached_junc_nodes",
    "retained_detached_swsd_road_ids",
    "external_retained_swsd_carrier_ids",
    "swsd_road_ids",
    "removed_swsd_road_ids",
    "removed_swsd_node_ids",
    "rcsd_road_ids",
    "rcsd_node_ids",
    "rcsd_pair_nodes",
    "rcsd_junc_nodes",
    "junction_c_ids",
    "group_replacement_plan_ids",
    "group_replacement_source_segment_ids",
    "group_replacement_segment_ids",
    "group_replacement_buffer_distances_m",
]

STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS = [
    "swsd_segment_id",
    "relation_status",
    "relation_reason",
    "swsd_pair_nodes",
    "swsd_junc_nodes",
    "junc_kind2_exempt_nodes",
    "detached_junc_nodes",
    "swsd_road_ids",
    "removed_swsd_road_ids",
    "retained_detached_swsd_road_ids",
    "external_retained_swsd_carrier_ids",
    "frcsd_road_ids",
    "owned_frcsd_road_ids",
    "connectivity_group_ids",
    "related_connectivity_road_ids",
    "frcsd_road_source_values",
    "rcsd_pair_nodes",
    "rcsd_junc_nodes",
    "junction_c_ids",
    "group_replacement_plan_ids",
    "group_replacement_source_segment_ids",
    "group_replacement_segment_ids",
    "swsd_to_frcsd_node_map",
    "source_mix",
    "risk_flags",
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
    "advance_attachment_rcsd_node_ids",
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

STEP3_UNREPLACED_RCSD_ROAD_FIELDS = [
    "id",
    "replacement_status",
    "audit_reason",
    "source",
    "snodeid",
    "enodeid",
    "direction",
    "formway",
    "length_m",
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
    replacement_plan_gpkg_path: Path | None = None
    problem_registry_gpkg_path: Path | None = None


@dataclass(frozen=True)
class T06Step3Artifacts:
    run_id: str
    run_root: Path
    step_root: Path
    frcsd_road_gpkg_path: Path
    frcsd_node_gpkg_path: Path
    replacement_units_gpkg_path: Path
    swsd_frcsd_segment_relation_gpkg_path: Path
    junction_rebuild_audit_gpkg_path: Path
    summary_path: Path
    rcsd_road_ownership_gpkg_path: Path | None = None
    multi_segment_connectivity_group_gpkg_path: Path | None = None
    segment_construction_audit_gpkg_path: Path | None = None


@dataclass(frozen=True)
class T06PrecheckArtifacts:
    run_id: str
    run_root: Path
    step1: T06Step1Artifacts
    step2: T06Step2Artifacts


def feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"properties": properties, "geometry": geometry}
