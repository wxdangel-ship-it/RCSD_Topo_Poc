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

STEP2_SUCCESS_CONTEXT_NAMES = (
    "auto_pair_anchor_diagnostic",
    "auto_pair_anchor_original_relation",
    "auto_pair_anchor_probe_result",
    "auto_pair_anchor_source_reason",
    "buffer_config",
    "buffer_result",
    "buffer_segment_rows",
    "candidate_rows",
    "directed_swsd_pair_nodes",
    "directionality",
    "directionality_conflict_props",
    "failure_business_audit_rows",
    "junc_audit",
    "junc_kind2_exempt_nodes",
    "junc_nodes",
    "pair_nodes",
    "props",
    "relation",
    "replaceable_rows",
    "segment_id",
    "semantic_endpoint_source_reason",
)

def _append_successful_buffer_rows(**context):
    (
        auto_pair_anchor_diagnostic,
        auto_pair_anchor_original_relation,
        auto_pair_anchor_probe_result,
        auto_pair_anchor_source_reason,
        buffer_config,
        buffer_result,
        buffer_segment_rows,
        candidate_rows,
        directed_swsd_pair_nodes,
        directionality,
        directionality_conflict_props,
        failure_business_audit_rows,
        junc_audit,
        junc_kind2_exempt_nodes,
        junc_nodes,
        pair_nodes,
        props,
        relation,
        replaceable_rows,
        segment_id,
        semantic_endpoint_source_reason,
    ) = (context[name] for name in STEP2_SUCCESS_CONTEXT_NAMES)
    buffer_feature = feature(_buffer_segment_row(segment_id, buffer_result), buffer_result.geometry)
    if directionality_conflict_props:
        buffer_feature["properties"].update(directionality_conflict_props)
    if semantic_endpoint_source_reason:
        _annotate_adaptive_buffer_metadata(
            buffer_feature,
            distance_m=buffer_config.buffer_distance_m,
            source_reason=semantic_endpoint_source_reason,
        )
    buffer_segment_rows.append(buffer_feature)
    candidate_feature = feature(
        _buffer_candidate_row(
            segment_id=segment_id,
            props=props,
            directionality=directionality,
            directed_swsd_pair_nodes=directed_swsd_pair_nodes,
            relation=relation,
            original_rcsd_pair_nodes=auto_pair_anchor_original_relation.rcsd_pair_nodes
            if auto_pair_anchor_original_relation is not None
            else None,
            junc_nodes=junc_nodes,
            junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
            junc_audit=junc_audit,
            result=buffer_result,
        ),
        buffer_result.geometry,
    )
    if directionality_conflict_props:
        candidate_feature["properties"].update(directionality_conflict_props)
    if semantic_endpoint_source_reason:
        _annotate_adaptive_buffer_metadata(
            candidate_feature,
            distance_m=buffer_config.buffer_distance_m,
            source_reason=semantic_endpoint_source_reason,
        )
    candidate_rows.append(candidate_feature)
    replaceable_rows.append(_buffer_replaceable_row(candidate_feature))
    if auto_pair_anchor_probe_result is not None and auto_pair_anchor_original_relation is not None:
        failure_business_audit_rows.append(
            feature(
                _failure_business_audit_row(
                    segment_id=segment_id,
                    segment_outcome="replaceable",
                    reject_reason=auto_pair_anchor_source_reason,
                    scenario_type="B",
                    failure_business_category="pair_anchor_mismatch",
                    pair_nodes=pair_nodes,
                    junc_nodes=junc_nodes,
                    relation=relation,
                    junc_audit=junc_audit,
                    probe_result=auto_pair_anchor_probe_result,
                    root_cause_category=None,
                    **_pair_anchor_issue_audit_kwargs(auto_pair_anchor_diagnostic),
                ),
                buffer_result.geometry,
            )
        )
    elif junc_audit.get("dropped_junc_nodes"):
        failure_business_audit_rows.append(
            feature(
                _failure_business_audit_row(
                    segment_id=segment_id,
                    segment_outcome="replaceable",
                    reject_reason="",
                    scenario_type="B",
                    failure_business_category=_junc_failure_business_category(junc_audit),
                    pair_nodes=pair_nodes,
                    junc_nodes=junc_nodes,
                    relation=relation,
                    junc_audit=junc_audit,
                    probe_result=None,
                    root_cause_category=None,
                ),
                buffer_result.geometry,
            )
        )

STEP2_AUTO_SUCCESS_CONTEXT_NAMES = (
    "auto_buffer_result",
    "auto_conflict_props",
    "auto_junc_audit",
    "auto_relation",
    "buffer_only_probe_rows",
    "buffer_result",
    "buffer_segment_rows",
    "candidate_rows",
    "diagnostic",
    "directed_swsd_pair_nodes",
    "directionality",
    "failure_business_audit_rows",
    "failure_category",
    "junc_kind2_exempt_nodes",
    "junc_nodes",
    "pair_anchor_diagnostic",
    "pair_nodes",
    "probe_result",
    "props",
    "relation",
    "repair_candidate_rows",
    "replaceable_rows",
    "segment_id",
)

def _append_auto_pair_anchor_success_rows(**context):
    (
        auto_buffer_result,
        auto_conflict_props,
        auto_junc_audit,
        auto_relation,
        buffer_only_probe_rows,
        buffer_result,
        buffer_segment_rows,
        candidate_rows,
        diagnostic,
        directed_swsd_pair_nodes,
        directionality,
        failure_business_audit_rows,
        failure_category,
        junc_kind2_exempt_nodes,
        junc_nodes,
        pair_anchor_diagnostic,
        pair_nodes,
        probe_result,
        props,
        relation,
        repair_candidate_rows,
        replaceable_rows,
        segment_id,
    ) = (context[name] for name in STEP2_AUTO_SUCCESS_CONTEXT_NAMES)
    buffer_only_probe_rows.append(
        feature(
            _buffer_only_probe_row(
                segment_id=segment_id,
                pair_nodes=pair_nodes,
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                probe_result=probe_result,
                failure_business_category=failure_category,
                source_reject_reason=buffer_result.reason,
            ),
            probe_result.geometry,
        )
    )
    repair_candidate_rows.append(
        feature(
            _repair_candidate_row(
                segment_id=segment_id,
                pair_nodes=pair_nodes,
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                probe_result=probe_result,
                failure_business_category=failure_category,
                source_reject_reason=buffer_result.reason,
                pair_anchor_diagnostic=pair_anchor_diagnostic,
            ),
            probe_result.geometry,
        )
    )
    buffer_feature = feature(_buffer_segment_row(segment_id, auto_buffer_result), auto_buffer_result.geometry)
    if auto_conflict_props:
        buffer_feature["properties"].update(auto_conflict_props)
    buffer_segment_rows.append(buffer_feature)
    candidate_feature = feature(
        _buffer_candidate_row(
            segment_id=segment_id,
            props=props,
            directionality=directionality,
            directed_swsd_pair_nodes=directed_swsd_pair_nodes,
            relation=auto_relation,
            original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
            junc_nodes=junc_nodes,
            junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
            junc_audit=auto_junc_audit,
            result=auto_buffer_result,
        ),
        auto_buffer_result.geometry,
    )
    if auto_conflict_props:
        candidate_feature["properties"].update(auto_conflict_props)
    candidate_rows.append(candidate_feature)
    replaceable_rows.append(_buffer_replaceable_row(candidate_feature))
    failure_business_audit_rows.append(
        feature(
            _failure_business_audit_row(
                segment_id=segment_id,
                segment_outcome="replaceable",
                reject_reason=buffer_result.reason,
                scenario_type="B",
                failure_business_category="pair_anchor_mismatch",
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                relation=auto_relation,
                junc_audit=auto_junc_audit,
                probe_result=probe_result,
                root_cause_category=diagnostic.get("root_cause_category"),
                **_pair_anchor_issue_audit_kwargs(pair_anchor_diagnostic),
            ),
            auto_buffer_result.geometry,
        )
    )
STEP2_REJECTION_CONTEXT_NAMES = (
    "buffer_config",
    "buffer_only_probe_rows",
    "buffer_rejected_rows",
    "buffer_result",
    "diagnostic",
    "failure_business_audit_rows",
    "failure_category",
    "junc_audit",
    "junc_kind2_exempt_nodes",
    "junc_nodes",
    "pair_anchor_diagnostic",
    "pair_nodes",
    "probe_result",
    "rejected_rows",
    "relation",
    "repair_candidate_rows",
    "segment",
    "segment_id",
)

def _append_final_rejection_rows(**context):
    (
        buffer_config,
        buffer_only_probe_rows,
        buffer_rejected_rows,
        buffer_result,
        diagnostic,
        failure_business_audit_rows,
        failure_category,
        junc_audit,
        junc_kind2_exempt_nodes,
        junc_nodes,
        pair_anchor_diagnostic,
        pair_nodes,
        probe_result,
        rejected_rows,
        relation,
        repair_candidate_rows,
        segment,
        segment_id,
    ) = (context[name] for name in STEP2_REJECTION_CONTEXT_NAMES)
    buffer_rejected = _buffer_rejected_row(segment_id, buffer_result, diagnostic)
    buffer_rejected_rows.append(buffer_rejected)
    rejected_rows.append(
        _reject(
            segment_id,
            None,
            "buffer_segment_extraction",
            buffer_result.reason,
            junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
            failed_metric_name=_buffer_failed_metric_name(buffer_result),
            failed_metric_value=_buffer_failed_metric_value(buffer_result),
            threshold_value=_buffer_failed_threshold_value(buffer_result, buffer_config),
            root_cause_category=diagnostic.get("root_cause_category"),
            full_graph_status=diagnostic.get("full_graph_status"),
            candidate_graph_status=diagnostic.get("candidate_graph_status"),
            directional_status=diagnostic.get("directional_status"),
            notes=diagnostic.get("diagnostic_notes") or "buffer-based RCSD Segment construction failed",
        )
    )
    buffer_only_probe_rows.append(
        feature(
            _buffer_only_probe_row(
                segment_id=segment_id,
                pair_nodes=pair_nodes,
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                probe_result=probe_result,
                failure_business_category=failure_category,
                source_reject_reason=buffer_result.reason,
            ),
            probe_result.geometry,
        )
    )
    if _should_emit_repair_candidate(probe_result):
        repair_candidate_rows.append(
            feature(
                _repair_candidate_row(
                    segment_id=segment_id,
                    pair_nodes=pair_nodes,
                    original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                    probe_result=probe_result,
                    failure_business_category=failure_category,
                    source_reject_reason=buffer_result.reason,
                    pair_anchor_diagnostic=pair_anchor_diagnostic,
                ),
                probe_result.geometry,
            )
        )
    failure_business_audit_rows.append(
        feature(
            _failure_business_audit_row(
                segment_id=segment_id,
                segment_outcome="rejected",
                reject_reason=buffer_result.reason,
                scenario_type=_scenario_type(failure_category),
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                relation=relation,
                junc_audit=junc_audit,
                probe_result=probe_result,
                root_cause_category=diagnostic.get("root_cause_category"),
                **_pair_anchor_issue_audit_kwargs(pair_anchor_diagnostic),
            ),
            segment.get("geometry"),
        )
    )
