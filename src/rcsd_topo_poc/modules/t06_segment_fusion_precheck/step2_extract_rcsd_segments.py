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

from .step2_extract_rcsd_segments_runner import run_t06_step2_extract_rcsd_segments

__all__ = ["run_t06_step2_extract_rcsd_segments"]
