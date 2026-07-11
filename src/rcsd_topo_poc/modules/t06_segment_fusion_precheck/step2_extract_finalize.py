from __future__ import annotations

from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from .attach_promotion import promote_isolated_attach_roads as _promote_isolated_attach_roads
from .adaptive_buffer_retry import high_grade_adaptive_buffer_retry_plan as _high_grade_adaptive_buffer_retry_plan
from .buffer_failure_diagnostics import (
    buffer_failed_metric_name as _buffer_failed_metric_name,
    buffer_failed_metric_value as _buffer_failed_metric_value,
    buffer_failed_threshold_value as _buffer_failed_threshold_value,
    buffer_failure_diagnostic as _buffer_failure_diagnostic,
    canonical_rcsd_ids as _canonical_rcsd_ids,
)
from .buffer_only_probe import BufferOnlyProbe, BufferOnlyProbeResult
from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor, BufferSegmentResult
from .failure_business_audit import (
    buffer_only_probe_row as _buffer_only_probe_row,
    business_audit_stats as _business_audit_stats,
    failure_business_audit_row as _failure_business_audit_row,
    failure_business_category as _failure_business_category,
    junc_failure_business_category as _junc_failure_business_category,
    repair_candidate_row as _repair_candidate_row,
    scenario_type as _scenario_type,
    should_emit_repair_candidate as _should_emit_repair_candidate,
)
from .graph_builders import NodeCanonicalizer
from .group_replacement_audit import (
    build_group_replacement_audit_rows as _build_group_replacement_audit_rows,
    path_corridor_group_covered_segment_ids as _path_corridor_group_covered_segment_ids,
)
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .pair_anchor_auto_retry import high_confidence_pair_anchor_relation as _high_confidence_pair_anchor_relation
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list, unique_preserve_order
from .pair_anchor_diagnostics import PairAnchorIssueDiagnostic, build_pair_anchor_issue_diagnostic
from .pair_anchor_relation_retry import (
    append_buffer_extraction_formal_retry_if_safe as _append_buffer_extraction_formal_retry_if_safe,
    append_relation_mapping_formal_retry_if_safe as _append_relation_mapping_formal_retry_if_safe,
)
from .rejected_context import annotate_rejected_swsd_context as _annotate_rejected_swsd_context
from .relation_mapping import RelationCheck, RelationRecord, build_relation_map, check_segment_relations
from .replacement_plan import (
    build_problem_registry_rows as _build_problem_registry_rows,
    build_replacement_plan_rows as _build_replacement_plan_rows,
)
from .single_direction_reality import (
    SingleDirectionRealityContext as _SingleRealityContext,
    resolve_single_rcsd_bidirectional_reality as _resolve_single_reality,
)
from .single_graph_connectivity_retry import SingleGraphConnectivityRetry as _SGR
from .single_direction_semantic_retry import semantic_endpoint_local_undirected_single_retry as _semantic_endpoint_local_single_retry
from .step2_progress import Step2Progress
from .step2_special_junctions import (
    annotate_special_junction_gate as _annotate_special_junction_gate,
    rcsd_graph_edges as _rcsd_graph_edges,
    rcsd_internal_road_ids as _rcsd_internal_road_ids,
    rcsd_road_coverage_stats as _rcsd_road_coverage_stats,
    rcsd_semantic_node_ids as _rcsd_semantic_node_ids,
    segment_special_junction_ids as _segment_special_junction_ids,
    special_gate_applies_to_segment as _special_gate_applies_to_segment,
    special_junction_gate as _special_junction_gate,
    special_swsd_junction_types as _special_swsd_junction_types,
)
from .step2_output_rows import (
    buffer_candidate_row as _buffer_candidate_row,
    buffer_replaceable_row as _buffer_replaceable_row,
    buffer_segment_row as _buffer_segment_row,
)
from .step2_runtime_indexes import RelationBaseIndex, lost_attach_road_ids as _lost_attach_road_ids
from .schemas import (
    STEP2_CANDIDATE_FIELDS,
    STEP2_CANDIDATES_STEM,
    STEP2_BUFFER_REJECTED_FIELDS,
    STEP2_BUFFER_REJECTED_STEM,
    STEP2_BUFFER_SEGMENT_FIELDS,
    STEP2_BUFFER_SEGMENTS_STEM,
    STEP2_BUFFER_ONLY_PROBE_FIELDS,
    STEP2_BUFFER_ONLY_PROBE_STEM,
    STEP2_DIR,
    STEP2_FAILURE_BUSINESS_AUDIT_FIELDS,
    STEP2_FAILURE_BUSINESS_AUDIT_STEM,
    STEP2_GROUP_REPLACEMENT_AUDIT_FIELDS,
    STEP2_GROUP_REPLACEMENT_AUDIT_STEM,
    STEP2_REPAIR_CANDIDATE_FIELDS,
    STEP2_REPAIR_CANDIDATES_STEM,
    STEP2_REJECTED_FIELDS,
    STEP2_REJECTED_STEM,
    STEP2_PROBLEM_REGISTRY_FIELDS,
    STEP2_PROBLEM_REGISTRY_STEM,
    STEP2_REPLACEABLE_FIELDS,
    STEP2_REPLACEABLE_STEM,
    STEP2_REPLACEMENT_PLAN_FIELDS,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP2_SPECIAL_JUNCTION_GROUP_FIELDS,
    STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
    STEP2_SUMMARY,
    T06Step2Artifacts,
    feature,
)


from .step2_extract_support import (
    _segment_index,
    _normalize_repair_candidate_rows_from_business_audit,
    _buffer_config_with_distance,
    _annotate_adaptive_buffer_metadata,
    _adaptive_buffer_failure_category,
    _adaptive_buffer_recommendation,
    _parse_unit_lists,
    _resolve_swsd_single_directed_pair,
    _canonical_swsd_pair_nodes,
    _swsd_road_canonical_endpoints,
    _map_directed_swsd_pair_to_rcsd,
    _first_present,
    _coerce_int,
    _directed_reachable,
    _order_swsd_junc_nodes_by_connectivity,
    _shortest_node_path,
    _relation_required_junc_nodes,
    _accepted_base_ids_for_nodes,
    _accepted_base_ids_for_nodes_ordered,
    _junc_attach_audit,
    _optional_allowed_rcsd_nodes,
    _pair_anchor_issue_diagnostic,
    _pair_anchor_issue_audit_kwargs,
    _buffer_rejected_row,
    _reject,
)

STEP2_FINALIZER_CONTEXT_NAMES = (
    "adaptive_high_grade_buffer_retry_count",
    "adaptive_high_grade_dual_buffer_retry_count",
    "adaptive_high_grade_single_buffer_retry_count",
    "advance_right_formway_bit",
    "buffer_config",
    "buffer_distance_m",
    "buffer_only_probe_rows",
    "buffer_rejected_rows",
    "buffer_segment_rows",
    "candidate_rows",
    "diag",
    "dual_input_count",
    "failure_business_audit_rows",
    "fusion_units",
    "intersection_match_path",
    "junc_kind2_relation_exempt_node_count",
    "junc_kind2_relation_exempt_segment_count",
    "max_coarse_length_ratio",
    "max_main_axis_angle_diff_deg",
    "min_buffer_road_overlap_length_m",
    "min_buffer_road_overlap_ratio",
    "min_coarse_length_ratio",
    "rcsd_junction_node_ids",
    "rcsd_junction_road_ids",
    "rcsd_node_canonicalizer",
    "rcsd_node_features",
    "rcsd_roads",
    "rcsdnode_path",
    "rcsdroad_path",
    "rejected_rows",
    "relation_map",
    "relation_success_count",
    "repair_candidate_rows",
    "replaceable_rows",
    "resolved_run_id",
    "run_root",
    "segment_special_junctions",
    "segments",
    "single_input_count",
    "special_junction_segments",
    "special_swsd_junction_types",
    "step_root",
    "swsd_fusion_units_path",
    "swsd_node_features",
    "swsd_nodes_path",
    "swsd_roads_path",
    "swsd_segment_path",
    "write_json_outputs",
)

def _finalize_step2_run(**context):
    (
        adaptive_high_grade_buffer_retry_count,
        adaptive_high_grade_dual_buffer_retry_count,
        adaptive_high_grade_single_buffer_retry_count,
        advance_right_formway_bit,
        buffer_config,
        buffer_distance_m,
        buffer_only_probe_rows,
        buffer_rejected_rows,
        buffer_segment_rows,
        candidate_rows,
        diag,
        dual_input_count,
        failure_business_audit_rows,
        fusion_units,
        intersection_match_path,
        junc_kind2_relation_exempt_node_count,
        junc_kind2_relation_exempt_segment_count,
        max_coarse_length_ratio,
        max_main_axis_angle_diff_deg,
        min_buffer_road_overlap_length_m,
        min_buffer_road_overlap_ratio,
        min_coarse_length_ratio,
        rcsd_junction_node_ids,
        rcsd_junction_road_ids,
        rcsd_node_canonicalizer,
        rcsd_node_features,
        rcsd_roads,
        rcsdnode_path,
        rcsdroad_path,
        rejected_rows,
        relation_map,
        relation_success_count,
        repair_candidate_rows,
        replaceable_rows,
        resolved_run_id,
        run_root,
        segment_special_junctions,
        segments,
        single_input_count,
        special_junction_segments,
        special_swsd_junction_types,
        step_root,
        swsd_fusion_units_path,
        swsd_node_features,
        swsd_nodes_path,
        swsd_roads_path,
        swsd_segment_path,
        write_json_outputs,
    ) = (context[name] for name in STEP2_FINALIZER_CONTEXT_NAMES)
    diag.stage("group_audit")
    pre_gate_group_replacement_audit_rows = _build_group_replacement_audit_rows(
        fusion_units=fusion_units,
        segments=list(segments.values()),
        relation_map=relation_map,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_node_features,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        replaceable_rows=replaceable_rows,
        rejected_rows=rejected_rows,
        failure_business_audit_rows=failure_business_audit_rows,
        buffer_config=buffer_config,
        progress=diag,
    )
    path_corridor_covered_segment_ids = _path_corridor_group_covered_segment_ids(pre_gate_group_replacement_audit_rows)
    diag.stage("special_junction_gate")
    special_group_rows, blocked_segment_ids, removed_replaceable_segment_ids, blocking_groups_by_segment = _special_junction_gate(
        special_junction_segments=special_junction_segments,
        special_swsd_junction_types=special_swsd_junction_types,
        replaceable_rows=replaceable_rows,
        additional_replaceable_segment_ids=path_corridor_covered_segment_ids,
        relation_map=relation_map,
        rcsd_junction_node_ids=rcsd_junction_node_ids,
        rcsd_junction_road_ids=rcsd_junction_road_ids,
    )
    _annotate_special_junction_gate(
        candidate_rows,
        segment_special_junctions=segment_special_junctions,
        special_swsd_junction_types=special_swsd_junction_types,
        blocked_segment_ids=blocked_segment_ids,
        blocking_groups_by_segment=blocking_groups_by_segment,
    )
    _annotate_special_junction_gate(
        replaceable_rows,
        segment_special_junctions=segment_special_junctions,
        special_swsd_junction_types=special_swsd_junction_types,
        blocked_segment_ids=blocked_segment_ids,
        blocking_groups_by_segment=blocking_groups_by_segment,
    )
    attach_promotion_stats = _promote_isolated_attach_roads(
        candidate_rows=candidate_rows,
        replaceable_rows=replaceable_rows,
        failure_business_audit_rows=failure_business_audit_rows,
    )
    _annotate_rejected_swsd_context(rejected_rows, fusion_units=fusion_units, segments=segments)
    _normalize_repair_candidate_rows_from_business_audit(repair_candidate_rows, failure_business_audit_rows)
    group_replacement_audit_rows = pre_gate_group_replacement_audit_rows
    diag.stage("replacement_plan")
    replacement_plan_rows = _build_replacement_plan_rows(
        replaceable_rows=replaceable_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        failure_business_audit_rows=failure_business_audit_rows,
        special_group_rows=special_group_rows,
        group_replacement_audit_rows=group_replacement_audit_rows,
        rcsd_roads=rcsd_roads,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        swsd_segments=list(segments.values()),
        swsd_nodes=swsd_node_features,
        rcsd_nodes=rcsd_node_features,
        relation_map=relation_map,
    )
    diag.stage("problem_registry")
    problem_registry_rows = _build_problem_registry_rows(
        rejected_rows=rejected_rows,
        failure_business_audit_rows=failure_business_audit_rows,
        replacement_plan_rows=replacement_plan_rows,
    )
    diag.stage("write_outputs")
    def _write_step2(stem: str, rows: list[dict[str, Any]], fields: list[str]) -> dict[str, Path]:
        return write_feature_triplet(
            step_root=step_root,
            stem=stem,
            features=rows,
            fieldnames=fields,
            write_json_output=write_json_outputs,
            progress=lambda fmt, status, path: diag.output(stem, fmt, status, path),
        )

    candidate_paths = _write_step2(STEP2_CANDIDATES_STEM, candidate_rows, STEP2_CANDIDATE_FIELDS)
    replaceable_paths = _write_step2(STEP2_REPLACEABLE_STEM, replaceable_rows, STEP2_REPLACEABLE_FIELDS)
    rejected_paths = _write_step2(STEP2_REJECTED_STEM, rejected_rows, STEP2_REJECTED_FIELDS)
    buffer_segment_paths = _write_step2(STEP2_BUFFER_SEGMENTS_STEM, buffer_segment_rows, STEP2_BUFFER_SEGMENT_FIELDS)
    buffer_rejected_paths = _write_step2(STEP2_BUFFER_REJECTED_STEM, buffer_rejected_rows, STEP2_BUFFER_REJECTED_FIELDS)
    buffer_only_probe_paths = _write_step2(STEP2_BUFFER_ONLY_PROBE_STEM, buffer_only_probe_rows, STEP2_BUFFER_ONLY_PROBE_FIELDS)
    repair_candidate_paths = _write_step2(STEP2_REPAIR_CANDIDATES_STEM, repair_candidate_rows, STEP2_REPAIR_CANDIDATE_FIELDS)
    failure_business_audit_paths = _write_step2(STEP2_FAILURE_BUSINESS_AUDIT_STEM, failure_business_audit_rows, STEP2_FAILURE_BUSINESS_AUDIT_FIELDS)
    special_group_paths = _write_step2(STEP2_SPECIAL_JUNCTION_GROUPS_STEM, special_group_rows, STEP2_SPECIAL_JUNCTION_GROUP_FIELDS)
    group_replacement_audit_paths = _write_step2(STEP2_GROUP_REPLACEMENT_AUDIT_STEM, group_replacement_audit_rows, STEP2_GROUP_REPLACEMENT_AUDIT_FIELDS)
    replacement_plan_paths = _write_step2(STEP2_REPLACEMENT_PLAN_STEM, replacement_plan_rows, STEP2_REPLACEMENT_PLAN_FIELDS)
    problem_registry_paths = _write_step2(STEP2_PROBLEM_REGISTRY_STEM, problem_registry_rows, STEP2_PROBLEM_REGISTRY_FIELDS)
    rcsd_road_stats = _rcsd_road_coverage_stats(rcsd_roads=rcsd_roads, replaceable_rows=replaceable_rows)
    business_stats = _business_audit_stats(failure_business_audit_rows, replaceable_rows, input_count=len(fusion_units))
    summary_path = step_root / STEP2_SUMMARY
    diag.stage("summary")
    write_json(
        summary_path,
        {
            "run_id": resolved_run_id,
            "input_paths": {
                "swsd_fusion_units_path": str(swsd_fusion_units_path),
                "swsd_segment_path": str(swsd_segment_path),
                "swsd_roads_path": str(swsd_roads_path),
                "swsd_nodes_path": str(swsd_nodes_path),
                "intersection_match_path": str(Path(intersection_match_path).resolve()),
                "rcsdroad_path": str(rcsdroad_path),
                "rcsdnode_path": str(rcsdnode_path),
            },
            "params": {
                "max_main_axis_angle_diff_deg": max_main_axis_angle_diff_deg,
                "min_coarse_length_ratio": min_coarse_length_ratio,
                "max_coarse_length_ratio": max_coarse_length_ratio,
                "buffer_distance_m": buffer_distance_m,
                "min_buffer_road_overlap_ratio": min_buffer_road_overlap_ratio,
                "min_buffer_road_overlap_length_m": min_buffer_road_overlap_length_m,
                "advance_right_formway_bit": advance_right_formway_bit,
                "max_geometry_buffer_mismatch_ratio": buffer_config.max_geometry_buffer_mismatch_ratio,
                "min_geometry_buffer_mismatch_length_m": buffer_config.min_geometry_buffer_mismatch_length_m,
                "visual_consistency_buffer_distance_m": buffer_config.visual_consistency_buffer_distance_m,
                "max_visual_consistency_mismatch_ratio": buffer_config.max_visual_consistency_mismatch_ratio,
                "min_visual_consistency_mismatch_length_m": buffer_config.min_visual_consistency_mismatch_length_m,
                "write_json_outputs": write_json_outputs,
            },
            "input_fusion_unit_count": len(fusion_units),
            "relation_success_count": relation_success_count,
            "relation_failure_count": len(fusion_units) - relation_success_count,
            "junc_kind2_relation_exempt_segment_count": junc_kind2_relation_exempt_segment_count,
            "junc_kind2_relation_exempt_node_count": junc_kind2_relation_exempt_node_count,
            "rcsd_candidate_count": len(candidate_rows),
            "replaceable_count": len(replaceable_rows),
            "rejected_count": len(rejected_rows),
            "reject_reason_counts": dict(Counter(item["properties"].get("reject_reason") for item in rejected_rows)),
            "candidate_strategy": "buffer_segment_extraction",
            "deprecated_pair_path_search_enabled": False,
            "ambiguous_candidate_count": 0,
            "single_segment_input_count": single_input_count,
            "dual_segment_input_count": dual_input_count,
            "single_segment_replaceable_count": sum(1 for item in replaceable_rows if item["properties"].get("swsd_directionality") == "single"),
            "dual_segment_replaceable_count": sum(1 for item in replaceable_rows if item["properties"].get("swsd_directionality") == "dual"),
            "buffer_segment_count": len(buffer_segment_rows),
            "buffer_rejected_count": len(buffer_rejected_rows),
            "buffer_reject_reason_counts": dict(Counter(item["properties"].get("reject_reason") for item in buffer_rejected_rows)),
            "buffer_retained_road_count_total": sum(len(item["properties"].get("retained_rcsd_road_ids") or []) for item in buffer_segment_rows),
            "buffer_excluded_advance_right_turn_road_count_total": sum(
                len(item["properties"].get("excluded_advance_right_turn_road_ids") or []) for item in buffer_segment_rows + buffer_rejected_rows
            ),
            "special_junction_group_count": len(special_group_rows),
            "special_junction_group_passed_count": sum(1 for item in special_group_rows if item["properties"].get("gate_status") == "passed"),
            "special_junction_group_partial_count": sum(1 for item in special_group_rows if item["properties"].get("gate_status") == "partial"),
            "special_junction_group_blocked_count": sum(1 for item in special_group_rows if item["properties"].get("gate_status") == "blocked"),
            "special_junction_blocked_segment_count": len(blocked_segment_ids),
            "special_junction_gate_removed_replaceable_count": len(removed_replaceable_segment_ids),
            "special_junction_group_type_counts": dict(Counter(item["properties"].get("special_junction_type") for item in special_group_rows)),
            "buffer_only_probe_count": len(buffer_only_probe_rows),
            "repair_candidate_count": len(repair_candidate_rows),
            "failure_business_audit_count": len(failure_business_audit_rows),
            "group_replacement_audit_count": len(group_replacement_audit_rows),
            "group_replacement_candidate_ready_count": sum(
                1 for item in group_replacement_audit_rows if item["properties"].get("audit_status") == "candidate_group_closure_ready"
            ),
            "group_replacement_closure_blocked_count": sum(
                1 for item in group_replacement_audit_rows if item["properties"].get("audit_status") == "blocked_group_closure_incomplete"
            ),
            "replacement_plan_count": len(replacement_plan_rows),
            "replacement_plan_ready_count": sum(1 for item in replacement_plan_rows if item["properties"].get("plan_status") == "ready"),
            "replacement_plan_scope_counts": dict(Counter(item["properties"].get("execution_scope") for item in replacement_plan_rows)),
            "problem_registry_count": len(problem_registry_rows),
            "problem_registry_status_counts": dict(Counter(item["properties"].get("problem_status") for item in problem_registry_rows)),
            "write_json_outputs": write_json_outputs,
            "adaptive_high_grade_buffer_retry_count": adaptive_high_grade_buffer_retry_count,
            "adaptive_high_grade_single_buffer_retry_count": adaptive_high_grade_single_buffer_retry_count,
            "adaptive_high_grade_dual_buffer_retry_count": adaptive_high_grade_dual_buffer_retry_count,
            **attach_promotion_stats,
            **business_stats,
            **rcsd_road_stats,
            "rcsd_semantic_node_alias_count": sum(1 for raw_id, canonical_id in rcsd_node_canonicalizer.aliases.items() if raw_id != canonical_id),
            "rcsd_semantic_node_group_count": len(rcsd_node_canonicalizer.semantic_node_ids),
            "outputs": {
                **{f"candidates_{k}": str(v) for k, v in candidate_paths.items()},
                **{f"replaceable_{k}": str(v) for k, v in replaceable_paths.items()},
                **{f"rejected_{k}": str(v) for k, v in rejected_paths.items()},
                **{f"buffer_segments_{k}": str(v) for k, v in buffer_segment_paths.items()},
                **{f"buffer_rejected_{k}": str(v) for k, v in buffer_rejected_paths.items()},
                **{f"buffer_only_probe_{k}": str(v) for k, v in buffer_only_probe_paths.items()},
                **{f"repair_candidates_{k}": str(v) for k, v in repair_candidate_paths.items()},
                **{f"failure_business_audit_{k}": str(v) for k, v in failure_business_audit_paths.items()},
                **{f"special_junction_group_audit_{k}": str(v) for k, v in special_group_paths.items()},
                **{f"group_replacement_audit_{k}": str(v) for k, v in group_replacement_audit_paths.items()},
                **{f"replacement_plan_{k}": str(v) for k, v in replacement_plan_paths.items()},
                **{f"problem_registry_{k}": str(v) for k, v in problem_registry_paths.items()},
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "buffer-based RCSD Segment graph uses canonicalized RCSD semantic nodes, explicit component coverage checks and special junction group gating",
                "geometry_semantics": "SWSD geometry defines the buffer window; RCSD geometry is used for intersects/overlap candidate selection and retained output geometry; Step2 replacement plan is the formal Step3 execution scope",
                "audit_traceability": "input paths, params, counts, reasons, adaptive buffer retry distance, replacement plan and problem registry outputs recorded",
                "performance_verifiable": "input counts, candidate counts, output paths, write_json_outputs and heartbeat output_write events are reproducible from summary/progress sidecars",
            },
        },
    )
    diag.finish(replaceable_count=len(replaceable_rows), replacement_plan_count=len(replacement_plan_rows))
    return T06Step2Artifacts(
        resolved_run_id,
        run_root,
        step_root,
        candidate_paths["gpkg"],
        replaceable_paths["gpkg"],
        rejected_paths["gpkg"],
        summary_path,
        replacement_plan_paths["gpkg"],
        problem_registry_paths["gpkg"],
    )
