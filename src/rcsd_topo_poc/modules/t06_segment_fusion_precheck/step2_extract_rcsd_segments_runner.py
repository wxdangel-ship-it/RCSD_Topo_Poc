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

from .step2_extract_outcomes import (
    STEP2_SUCCESS_CONTEXT_NAMES,
    _append_successful_buffer_rows,
    STEP2_AUTO_SUCCESS_CONTEXT_NAMES,
    _append_auto_pair_anchor_success_rows,
    STEP2_REJECTION_CONTEXT_NAMES,
    _append_final_rejection_rows,
)

from .step2_extract_finalize import (
    STEP2_FINALIZER_CONTEXT_NAMES,
    _finalize_step2_run,
)

def run_t06_step2_extract_rcsd_segments(
    *,
    swsd_fusion_units_path: str | Path,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    intersection_match_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    max_main_axis_angle_diff_deg: float = 60.0,
    min_coarse_length_ratio: float = 0.4,
    max_coarse_length_ratio: float = 2.5,
    buffer_distance_m: float = 50.0,
    min_buffer_road_overlap_ratio: float = 0.2,
    min_buffer_road_overlap_length_m: float = 1.0,
    advance_right_formway_bit: int = 128,
    progress: bool = False,
    write_json_outputs: bool = True,
) -> T06Step2Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP2_DIR)
    fusion_units = read_features(swsd_fusion_units_path)
    diag = Step2Progress(step_root, progress, len(fusion_units))
    segments = _segment_index(read_features(swsd_segment_path))
    swsd_roads = _segment_index(read_features(swsd_roads_path))
    swsd_node_features = read_features(swsd_nodes_path)
    swsd_node_canonicalizer = NodeCanonicalizer.from_node_features(swsd_node_features)
    special_swsd_junction_types = _special_swsd_junction_types(swsd_node_features, swsd_node_canonicalizer)
    relation_map = build_relation_map(read_features(intersection_match_path, crs_override="EPSG:4326"))
    rcsd_roads = read_features(rcsdroad_path)
    rcsd_node_features = read_features(rcsdnode_path)
    rcsd_node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
    rcsd_junction_node_ids = _rcsd_semantic_node_ids(rcsd_node_features, rcsd_node_canonicalizer)
    rcsd_junction_road_ids = _rcsd_internal_road_ids(rcsd_roads, rcsd_node_canonicalizer)
    rcsd_graph_edges = _rcsd_graph_edges(rcsd_roads, rcsd_node_canonicalizer)
    buffer_extractor = BufferSegmentExtractor(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_node_features)
    graph_retry = _SGR(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_node_features)
    buffer_probe = BufferOnlyProbe(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_node_features)
    buffer_config = BufferExtractionConfig(
        buffer_distance_m=buffer_distance_m,
        min_road_overlap_ratio=min_buffer_road_overlap_ratio,
        min_road_overlap_length_m=min_buffer_road_overlap_length_m,
        advance_right_formway_bit=advance_right_formway_bit,
    )
    relation_base_index = RelationBaseIndex.from_relation_map(relation_map)
    all_base_ids = set(relation_base_index.all_base_ids)

    candidate_rows: list[dict[str, Any]] = []
    replaceable_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    buffer_segment_rows: list[dict[str, Any]] = []
    buffer_rejected_rows: list[dict[str, Any]] = []
    buffer_only_probe_rows: list[dict[str, Any]] = []
    repair_candidate_rows: list[dict[str, Any]] = []
    failure_business_audit_rows: list[dict[str, Any]] = []
    formal_retry_rows = (
        buffer_segment_rows,
        candidate_rows,
        replaceable_rows,
        buffer_only_probe_rows,
        repair_candidate_rows,
        failure_business_audit_rows,
    )
    relation_success_count = 0
    single_input_count = 0
    dual_input_count = 0
    junc_kind2_relation_exempt_segment_count = 0
    junc_kind2_relation_exempt_node_count = 0
    adaptive_high_grade_buffer_retry_count = 0
    adaptive_high_grade_single_buffer_retry_count = 0
    adaptive_high_grade_dual_buffer_retry_count = 0
    segment_special_junctions: dict[str, list[str]] = {}
    special_junction_segments: dict[str, list[str]] = defaultdict(list)

    for index, unit in enumerate(fusion_units, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step2] processed {index}/{len(fusion_units)}", flush=True)
        props = dict(unit.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or props.get("id") or f"segment_{index}")
        diag.unit(index, segment_id)
        segment = segments.get(segment_id, unit)
        segment_props = dict(segment.get("properties") or {})
        pair_nodes, junc_nodes, junc_kind2_exempt_nodes, _roads, parse_reason = _parse_unit_lists(props, segment_props)
        if parse_reason is not None:
            rejected_rows.append(_reject(segment_id, None, "parse", parse_reason))
            continue
        junc_nodes = _order_swsd_junc_nodes_by_connectivity(
            pair_nodes=pair_nodes,
            junc_nodes=junc_nodes,
            road_ids=_roads,
            swsd_roads=swsd_roads,
            swsd_node_canonicalizer=swsd_node_canonicalizer,
        )
        special_junction_ids = _segment_special_junction_ids(
            [*pair_nodes, *junc_nodes],
            special_swsd_junction_types,
            swsd_node_canonicalizer,
        )
        segment_special_junctions[segment_id] = special_junction_ids if _special_gate_applies_to_segment(pair_nodes) else []
        if _special_gate_applies_to_segment(pair_nodes):
            for special_junction_id in special_junction_ids:
                if segment_id not in special_junction_segments[special_junction_id]:
                    special_junction_segments[special_junction_id].append(segment_id)
        relation_junc_nodes = _relation_required_junc_nodes(junc_nodes, junc_kind2_exempt_nodes)
        all_base_ids_for_segment = all_base_ids - _accepted_base_ids_for_nodes(junc_kind2_exempt_nodes, relation_map)
        unexpected_base_ids_for_segment = relation_base_index.unexpected_for([*pair_nodes, *junc_nodes])
        single_reality_ctx = _SingleRealityContext(
            buffer_extractor,
            segment.get("geometry"),
            all_base_ids_for_segment,
            unexpected_base_ids_for_segment,
            buffer_config,
        )
        if junc_kind2_exempt_nodes:
            junc_kind2_relation_exempt_segment_count += 1
            junc_kind2_relation_exempt_node_count += len(junc_kind2_exempt_nodes)
        segment_sgrade = segment_props.get("sgrade") or props.get("sgrade")
        directionality = directionality_from_sgrade(segment_sgrade) or "unknown"
        allow_single_missing_candidate_anchor_mismatch = directionality == "single" and str(segment_sgrade or "").startswith(("0-0", "0-1"))

        relation = check_segment_relations(pair_nodes=pair_nodes, junc_nodes=relation_junc_nodes, relation_map=relation_map)
        auto_pair_anchor_probe_result: BufferOnlyProbeResult | None = None
        auto_pair_anchor_original_relation: RelationCheck | None = None
        auto_pair_anchor_diagnostic: PairAnchorIssueDiagnostic | None = None
        auto_pair_anchor_source_reason = ""
        if not relation.ok:
            probe_result = buffer_probe.probe(
                segment_geometry=segment.get("geometry"),
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                directionality=directionality,
                config=buffer_config,
            )
            failure_category = _failure_business_category(
                relation.reject_reason or "relation_mapping_failed",
                probe_result=probe_result,
                relation=relation,
                junc_audit=None,
                diagnostic=None,
            )
            optional_allowed_rcsd_nodes = _optional_allowed_rcsd_nodes(
                relation=relation,
                relation_junc_nodes=relation_junc_nodes,
                junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                relation_map=relation_map,
            )
            pair_anchor_diagnostic = _pair_anchor_issue_diagnostic(
                probe_result=probe_result,
                relation=relation,
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                rcsd_roads=rcsd_roads,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
            auto_relation = _high_confidence_pair_anchor_relation(
                probe_result=probe_result,
                relation=relation,
                pair_anchor_diagnostic=pair_anchor_diagnostic,
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                relation_junc_nodes=relation_junc_nodes,
                relation_map=relation_map,
                allow_single_missing_candidate_anchor_mismatch=allow_single_missing_candidate_anchor_mismatch,
            )
            if auto_relation is not None:
                auto_pair_anchor_probe_result = probe_result
                auto_pair_anchor_original_relation = relation
                auto_pair_anchor_diagnostic = pair_anchor_diagnostic
                auto_pair_anchor_source_reason = relation.reject_reason or "relation_mapping_failed"
                relation = auto_relation
                buffer_only_probe_rows.append(
                    feature(
                        _buffer_only_probe_row(
                            segment_id=segment_id,
                            pair_nodes=pair_nodes,
                            original_rcsd_pair_nodes=auto_pair_anchor_original_relation.rcsd_pair_nodes,
                            probe_result=probe_result,
                            failure_business_category=failure_category,
                            source_reject_reason=auto_pair_anchor_source_reason,
                        ),
                        probe_result.geometry,
                    )
                )
                repair_candidate_rows.append(
                    feature(
                        _repair_candidate_row(
                            segment_id=segment_id,
                            pair_nodes=pair_nodes,
                            original_rcsd_pair_nodes=auto_pair_anchor_original_relation.rcsd_pair_nodes,
                            probe_result=probe_result,
                            failure_business_category=failure_category,
                            source_reject_reason=auto_pair_anchor_source_reason,
                            pair_anchor_diagnostic=pair_anchor_diagnostic,
                        ),
                        probe_result.geometry,
                    )
                )
            else:
                formal_retry_stats = _append_relation_mapping_formal_retry_if_safe(
                    segment_id=segment_id,
                    props=props,
                    directionality=directionality,
                    pair_nodes=pair_nodes,
                    road_ids=_roads,
                    junc_nodes=junc_nodes,
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    relation=relation,
                    failure_business_category=failure_category,
                    probe_result=probe_result,
                    pair_anchor_diagnostic=pair_anchor_diagnostic,
                    relation_junc_nodes=relation_junc_nodes,
                    relation_map=relation_map,
                    segment_geometry=segment.get("geometry"),
                    sgrade=segment_props.get("sgrade") or props.get("sgrade"),
                    swsd_roads=swsd_roads,
                    swsd_node_canonicalizer=swsd_node_canonicalizer,
                    buffer_extractor=buffer_extractor,
                    graph_retry=graph_retry,
                    buffer_config=buffer_config,
                    all_base_ids_for_segment=all_base_ids_for_segment,
                    unexpected_base_ids_for_segment=unexpected_base_ids_for_segment,
                    rcsd_graph_edges=rcsd_graph_edges,
                    rcsd_node_canonicalizer=rcsd_node_canonicalizer,
                    max_path_to_swsd_length_ratio=max_coarse_length_ratio,
                    rcsd_roads=rcsd_roads,
                    resolve_swsd_single_directed_pair=_resolve_swsd_single_directed_pair,
                    junc_attach_audit=_junc_attach_audit,
                    output_rows=formal_retry_rows,
                )
                if formal_retry_stats.applied:
                    adaptive_high_grade_buffer_retry_count += formal_retry_stats.adaptive_high_grade_buffer_retry_count
                    adaptive_high_grade_single_buffer_retry_count += (
                        formal_retry_stats.adaptive_high_grade_single_buffer_retry_count
                    )
                    continue
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "relation_mapping",
                        relation.reject_reason or "relation_mapping_failed",
                        failed_pair_nodes=relation.failed_pair_nodes or [],
                        failed_junc_nodes=relation.failed_junc_nodes or [],
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
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
                            source_reject_reason=relation.reject_reason or "relation_mapping_failed",
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
                                source_reject_reason=relation.reject_reason or "relation_mapping_failed",
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
                            reject_reason=relation.reject_reason or "relation_mapping_failed",
                            scenario_type=_scenario_type(failure_category),
                            failure_business_category=failure_category,
                            pair_nodes=pair_nodes,
                            junc_nodes=junc_nodes,
                            relation=relation,
                            junc_audit=None,
                            probe_result=probe_result,
                            root_cause_category=None,
                            **_pair_anchor_issue_audit_kwargs(pair_anchor_diagnostic),
                        ),
                        segment.get("geometry"),
                    )
                )
                continue
        relation_success_count += 1
        if directionality == "single":
            single_input_count += 1
        elif directionality == "dual":
            dual_input_count += 1
        if len(set(pair_nodes)) < 2:
            probe_result = buffer_probe.probe(
                segment_geometry=segment.get("geometry"),
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                directionality=directionality,
                config=buffer_config,
            )
            failure_category = _failure_business_category(
                "swsd_pair_nodes_not_distinct",
                probe_result=probe_result,
                relation=relation,
                junc_audit=None,
                diagnostic=None,
            )
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "semantic_pair_validation",
                    "swsd_pair_nodes_not_distinct",
                    failed_pair_nodes=pair_nodes,
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    failed_metric_name="swsd_pair_nodes",
                    failed_metric_value=pair_nodes,
                    notes="SWSD Segment pair_nodes must represent two distinct semantic junctions for RCSD Segment replacement",
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
                        source_reject_reason="swsd_pair_nodes_not_distinct",
                    ),
                    probe_result.geometry,
                )
            )
            failure_business_audit_rows.append(
                feature(
                    _failure_business_audit_row(
                        segment_id=segment_id,
                        segment_outcome="rejected",
                        reject_reason="swsd_pair_nodes_not_distinct",
                        scenario_type=_scenario_type(failure_category),
                        failure_business_category=failure_category,
                        pair_nodes=pair_nodes,
                        junc_nodes=junc_nodes,
                        relation=relation,
                        junc_audit=None,
                        probe_result=probe_result,
                        root_cause_category=None,
                    ),
                    segment.get("geometry"),
                )
            )
            continue
        canonical_rcsd_pair_nodes = _canonical_rcsd_ids(relation.rcsd_pair_nodes, rcsd_node_canonicalizer)
        if len(set(canonical_rcsd_pair_nodes)) < 2:
            probe_result = buffer_probe.probe(
                segment_geometry=segment.get("geometry"),
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                directionality=directionality,
                config=buffer_config,
            )
            failure_category = _failure_business_category(
                "rcsd_pair_nodes_not_distinct",
                probe_result=probe_result,
                relation=relation,
                junc_audit=None,
                diagnostic=None,
            )
            optional_allowed_rcsd_nodes = _optional_allowed_rcsd_nodes(
                relation=relation,
                relation_junc_nodes=relation_junc_nodes,
                junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                relation_map=relation_map,
            )
            pair_anchor_diagnostic = _pair_anchor_issue_diagnostic(
                probe_result=probe_result,
                relation=relation,
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                rcsd_roads=rcsd_roads,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
            auto_relation = _high_confidence_pair_anchor_relation(
                probe_result=probe_result,
                relation=relation,
                pair_anchor_diagnostic=pair_anchor_diagnostic,
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                relation_junc_nodes=relation_junc_nodes,
                relation_map=relation_map,
                allow_single_missing_candidate_anchor_mismatch=allow_single_missing_candidate_anchor_mismatch,
            )
            if auto_relation is not None:
                auto_pair_anchor_probe_result = probe_result
                auto_pair_anchor_original_relation = relation
                auto_pair_anchor_diagnostic = pair_anchor_diagnostic
                auto_pair_anchor_source_reason = "rcsd_pair_nodes_not_distinct"
                relation = auto_relation
                buffer_only_probe_rows.append(
                    feature(
                        _buffer_only_probe_row(
                            segment_id=segment_id,
                            pair_nodes=pair_nodes,
                            original_rcsd_pair_nodes=auto_pair_anchor_original_relation.rcsd_pair_nodes,
                            probe_result=probe_result,
                            failure_business_category=failure_category,
                            source_reject_reason=auto_pair_anchor_source_reason,
                        ),
                        probe_result.geometry,
                    )
                )
                repair_candidate_rows.append(
                    feature(
                        _repair_candidate_row(
                            segment_id=segment_id,
                            pair_nodes=pair_nodes,
                            original_rcsd_pair_nodes=auto_pair_anchor_original_relation.rcsd_pair_nodes,
                            probe_result=probe_result,
                            failure_business_category=failure_category,
                            source_reject_reason=auto_pair_anchor_source_reason,
                            pair_anchor_diagnostic=pair_anchor_diagnostic,
                        ),
                        probe_result.geometry,
                    )
                )
            else:
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "semantic_pair_validation",
                        "rcsd_pair_nodes_not_distinct",
                        failed_pair_nodes=relation.rcsd_pair_nodes,
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                        failed_metric_name="rcsd_pair_nodes",
                        failed_metric_value={
                            "rcsd_pair_nodes": relation.rcsd_pair_nodes,
                            "canonical_rcsd_pair_nodes": canonical_rcsd_pair_nodes,
                        },
                        notes="T05 relation maps the SWSD pair to the same RCSD semantic junction, so no replaceable RCSD Segment can be constructed",
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
                            source_reject_reason="rcsd_pair_nodes_not_distinct",
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
                                source_reject_reason="rcsd_pair_nodes_not_distinct",
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
                            reject_reason="rcsd_pair_nodes_not_distinct",
                            scenario_type=_scenario_type(failure_category),
                            failure_business_category=failure_category,
                            pair_nodes=pair_nodes,
                            junc_nodes=junc_nodes,
                            relation=relation,
                            junc_audit=None,
                            probe_result=probe_result,
                            root_cause_category=None,
                            **_pair_anchor_issue_audit_kwargs(pair_anchor_diagnostic),
                        ),
                        segment.get("geometry"),
                    )
                )
                continue

        directed_swsd_pair_nodes: list[str] = []
        directed_rcsd_pair_nodes: list[str] = []
        if directionality == "single":
            directed_swsd_pair_nodes, direction_reason = _resolve_swsd_single_directed_pair(
                pair_nodes=pair_nodes,
                road_ids=_roads,
                swsd_roads=swsd_roads,
                swsd_node_canonicalizer=swsd_node_canonicalizer,
            )
            if direction_reason is not None:
                probe_result = buffer_probe.probe(
                    segment_geometry=segment.get("geometry"),
                    original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                    directionality=directionality,
                    config=buffer_config,
                )
                failure_category = _failure_business_category(
                    direction_reason,
                    probe_result=probe_result,
                    relation=relation,
                    junc_audit=None,
                    diagnostic=None,
                )
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "swsd_direction_resolution",
                        direction_reason,
                        failed_pair_nodes=pair_nodes,
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                        failed_metric_name="swsd_road_direction",
                        failed_metric_value=_roads,
                        notes="single SWSD Segment direction must be resolved from SWSDRoad snodeid/enodeid/direction",
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
                            source_reject_reason=direction_reason,
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
                                source_reject_reason=direction_reason,
                            ),
                            probe_result.geometry,
                        )
                    )
                failure_business_audit_rows.append(
                    feature(
                        _failure_business_audit_row(
                            segment_id=segment_id,
                            segment_outcome="rejected",
                            reject_reason=direction_reason,
                            scenario_type=_scenario_type(failure_category),
                            failure_business_category=failure_category,
                            pair_nodes=pair_nodes,
                            junc_nodes=junc_nodes,
                            relation=relation,
                            junc_audit=None,
                            probe_result=probe_result,
                            root_cause_category=None,
                        ),
                        segment.get("geometry"),
                    )
                )
                continue
            directed_rcsd_pair_nodes = _map_directed_swsd_pair_to_rcsd(
                pair_nodes=pair_nodes,
                rcsd_pair_nodes=relation.rcsd_pair_nodes,
                directed_swsd_pair_nodes=directed_swsd_pair_nodes,
            )
            if len(directed_rcsd_pair_nodes) != 2:
                probe_result = buffer_probe.probe(
                    segment_geometry=segment.get("geometry"),
                    original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                    directionality=directionality,
                    config=buffer_config,
                )
                failure_category = _failure_business_category(
                    "swsd_single_direction_relation_mismatch",
                    probe_result=probe_result,
                    relation=relation,
                    junc_audit=None,
                    diagnostic=None,
                )
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "swsd_direction_resolution",
                        "swsd_single_direction_relation_mismatch",
                        failed_pair_nodes=pair_nodes,
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                        failed_metric_name="directed_swsd_pair_nodes",
                        failed_metric_value=directed_swsd_pair_nodes,
                        notes="resolved SWSD directed pair cannot be mapped to relation RCSD pair nodes",
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
                            source_reject_reason="swsd_single_direction_relation_mismatch",
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
                                source_reject_reason="swsd_single_direction_relation_mismatch",
                            ),
                            probe_result.geometry,
                        )
                    )
                failure_business_audit_rows.append(
                    feature(
                        _failure_business_audit_row(
                            segment_id=segment_id,
                            segment_outcome="rejected",
                            reject_reason="swsd_single_direction_relation_mismatch",
                            scenario_type=_scenario_type(failure_category),
                            failure_business_category=failure_category,
                            pair_nodes=pair_nodes,
                            junc_nodes=junc_nodes,
                            relation=relation,
                            junc_audit=None,
                            probe_result=probe_result,
                            root_cause_category=None,
                        ),
                        segment.get("geometry"),
                    )
                )
                continue
        optional_allowed_rcsd_nodes = _optional_allowed_rcsd_nodes(
            relation=relation,
            relation_junc_nodes=relation_junc_nodes,
            junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
            relation_map=relation_map,
        )
        buffer_result = buffer_extractor.extract(
            segment_geometry=segment.get("geometry"),
            relation=relation,
            optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
            all_relation_base_ids=all_base_ids_for_segment,
            unexpected_relation_base_ids=unexpected_base_ids_for_segment,
            directed_pair_nodes=directed_rcsd_pair_nodes,
            require_directed_pair=directionality == "single",
            require_bidirectional=directionality == "dual",
            config=buffer_config,
        )
        semantic_endpoint_source_reason = ""
        semantic_endpoint_guarded = False
        if directionality == "single" and not buffer_result.ok and buffer_result.reason == "rcsd_directed_path_missing":
            semantic_endpoint_guarded, semantic_retry_result, semantic_endpoint_source_reason = _semantic_endpoint_local_single_retry(
                buffer_extractor=buffer_extractor,
                segment_geometry=segment.get("geometry"),
                relation=relation,
                optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
                all_relation_base_ids=all_base_ids_for_segment,
                unexpected_relation_base_ids=unexpected_base_ids_for_segment,
                directed_swsd_pair_nodes=directed_swsd_pair_nodes,
                directed_rcsd_pair_nodes=directed_rcsd_pair_nodes,
                pair_nodes=pair_nodes,
                road_ids=_roads,
                swsd_roads=swsd_roads,
                swsd_node_canonicalizer=swsd_node_canonicalizer,
                special_swsd_junction_types=special_swsd_junction_types,
                config=buffer_config,
            )
            if semantic_retry_result is not None:
                buffer_result = semantic_retry_result
        directionality_conflict_props: dict[str, Any] = {}
        if buffer_result.ok:
            buffer_result, directionality_conflict_props = _resolve_single_reality(
                single_reality_ctx,
                directionality,
                relation,
                optional_allowed_rcsd_nodes,
                directed_rcsd_pair_nodes,
                buffer_result,
            )
        junc_audit = _junc_attach_audit(
            junc_nodes=relation_junc_nodes,
            relation=relation,
            relation_map=relation_map,
            buffer_result=buffer_result,
            rcsd_roads=rcsd_roads,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
        if buffer_result.ok:
            successful_buffer_context = locals()
            _append_successful_buffer_rows(
                **{name: successful_buffer_context[name] for name in STEP2_SUCCESS_CONTEXT_NAMES}
            )
        else:
            diagnostic = _buffer_failure_diagnostic(
                result=buffer_result,
                directionality=directionality,
                rcsd_pair_nodes=relation.rcsd_pair_nodes,
                rcsd_graph_edges=rcsd_graph_edges,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
            probe_result = buffer_probe.probe(
                segment_geometry=segment.get("geometry"),
                original_rcsd_pair_nodes=relation.rcsd_pair_nodes,
                directionality=directionality,
                config=buffer_config,
            )
            failure_category = _failure_business_category(
                buffer_result.reason,
                probe_result=probe_result,
                relation=relation,
                junc_audit=junc_audit,
                diagnostic=diagnostic,
            )
            pair_anchor_diagnostic = _pair_anchor_issue_diagnostic(
                probe_result=probe_result,
                relation=relation,
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                rcsd_roads=rcsd_roads,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            )
            auto_relation = None if semantic_endpoint_guarded else _high_confidence_pair_anchor_relation(
                probe_result=probe_result,
                relation=relation,
                pair_anchor_diagnostic=pair_anchor_diagnostic,
                failure_business_category=failure_category,
                pair_nodes=pair_nodes,
                relation_junc_nodes=relation_junc_nodes,
                relation_map=relation_map,
            )
            auto_directed_rcsd_pair_nodes: list[str] = []
            if auto_relation is not None and directionality == "single":
                auto_directed_rcsd_pair_nodes = _map_directed_swsd_pair_to_rcsd(
                    pair_nodes=pair_nodes,
                    rcsd_pair_nodes=auto_relation.rcsd_pair_nodes,
                    directed_swsd_pair_nodes=directed_swsd_pair_nodes,
                )
                if len(auto_directed_rcsd_pair_nodes) != 2:
                    auto_relation = None
            if auto_relation is not None:
                auto_optional_allowed_rcsd_nodes = _optional_allowed_rcsd_nodes(
                    relation=auto_relation,
                    relation_junc_nodes=relation_junc_nodes,
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    relation_map=relation_map,
                )
                auto_buffer_result = buffer_extractor.extract(
                    segment_geometry=segment.get("geometry"),
                    relation=auto_relation,
                    optional_allowed_rcsd_nodes=auto_optional_allowed_rcsd_nodes,
                    all_relation_base_ids=all_base_ids_for_segment,
                    unexpected_relation_base_ids=unexpected_base_ids_for_segment,
                    directed_pair_nodes=auto_directed_rcsd_pair_nodes,
                    require_directed_pair=directionality == "single",
                    require_bidirectional=directionality == "dual",
                    config=buffer_config,
                )
                auto_conflict_props = {}
                if auto_buffer_result.ok:
                    auto_buffer_result, auto_conflict_props = _resolve_single_reality(
                        single_reality_ctx,
                        directionality,
                        auto_relation,
                        auto_optional_allowed_rcsd_nodes,
                        auto_directed_rcsd_pair_nodes,
                        auto_buffer_result,
                    )
                auto_junc_audit = _junc_attach_audit(
                    junc_nodes=relation_junc_nodes,
                    relation=auto_relation,
                    relation_map=relation_map,
                    buffer_result=auto_buffer_result,
                    rcsd_roads=rcsd_roads,
                    rcsd_node_canonicalizer=rcsd_node_canonicalizer,
                )
                if auto_buffer_result.ok:
                    auto_success_context = locals()
                    _append_auto_pair_anchor_success_rows(
                        **{name: auto_success_context[name] for name in STEP2_AUTO_SUCCESS_CONTEXT_NAMES}
                    )
                    continue
            adaptive_plan = _high_grade_adaptive_buffer_retry_plan(
                sgrade=segment_props.get("sgrade") or props.get("sgrade"),
                directionality=directionality,
                buffer_result=buffer_result,
                diagnostic=diagnostic,
                base_buffer_distance_m=buffer_config.buffer_distance_m,
            )
            if adaptive_plan is not None and auto_pair_anchor_original_relation is None:
                adaptive_success = False
                adaptive_failure_category = _adaptive_buffer_failure_category(buffer_result.reason, diagnostic)
                adaptive_attempts: tuple[float | None, ...] = adaptive_plan.distances_m
                if directionality == "dual":
                    adaptive_attempts = (*adaptive_attempts, None)
                for adaptive_distance_m in adaptive_attempts:
                    src_reason = buffer_result.reason
                    retry_config = buffer_config
                    if adaptive_distance_m is None:
                        graph = graph_retry.retry_dual_bidirectional(
                            segment.get("geometry"),
                            relation,
                            optional_allowed_rcsd_nodes,
                            unexpected_base_ids_for_segment,
                            segment_props.get("sgrade") or props.get("sgrade"),
                            buffer_result,
                            diagnostic,
                            buffer_config,
                            max_coarse_length_ratio,
                        )
                        if graph is None:
                            continue
                        r = graph.buffer_result
                        adaptive_distance_m = graph.reference_distance_m
                        src_reason = graph.source_reason
                    elif directionality == "single":
                        graph = graph_retry.retry(
                            segment.get("geometry"),
                            relation,
                            optional_allowed_rcsd_nodes,
                            unexpected_base_ids_for_segment,
                            directed_rcsd_pair_nodes,
                            segment_props.get("sgrade") or props.get("sgrade"),
                            directionality,
                            buffer_result,
                            diagnostic,
                            buffer_config,
                            max_coarse_length_ratio,
                        )
                        if graph is None:
                            continue
                        r = graph.buffer_result
                        adaptive_distance_m = graph.reference_distance_m
                        src_reason = graph.source_reason
                    else:
                        retry_config = _buffer_config_with_distance(buffer_config, adaptive_distance_m)
                        r = buffer_extractor.extract(
                            segment_geometry=segment.get("geometry"),
                            relation=relation,
                            optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
                            all_relation_base_ids=all_base_ids_for_segment,
                            unexpected_relation_base_ids=unexpected_base_ids_for_segment,
                            directed_pair_nodes=directed_rcsd_pair_nodes,
                            require_directed_pair=False,
                            require_bidirectional=True,
                            config=retry_config,
                        )
                    conflict_props = {}
                    if r.ok:
                        r, conflict_props = _resolve_single_reality(
                            _SingleRealityContext(
                                buffer_extractor,
                                segment.get("geometry"),
                                all_base_ids_for_segment,
                                unexpected_base_ids_for_segment,
                                retry_config,
                            ),
                            directionality,
                            relation,
                            optional_allowed_rcsd_nodes,
                            directed_rcsd_pair_nodes,
                            r,
                        )
                    adaptive_junc_audit = _junc_attach_audit(
                        junc_nodes=relation_junc_nodes,
                        relation=relation,
                        relation_map=relation_map,
                        buffer_result=r,
                        rcsd_roads=rcsd_roads,
                        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
                    )
                    if not r.ok:
                        continue
                    buffer_feature = feature(_buffer_segment_row(segment_id, r), r.geometry)
                    if conflict_props:
                        buffer_feature["properties"].update(conflict_props)
                    _annotate_adaptive_buffer_metadata(
                        buffer_feature,
                        distance_m=adaptive_distance_m,
                        source_reason=src_reason,
                    )
                    buffer_segment_rows.append(buffer_feature)
                    candidate_feature = feature(
                        _buffer_candidate_row(
                            segment_id=segment_id,
                            props=props,
                            directionality=directionality,
                            directed_swsd_pair_nodes=directed_swsd_pair_nodes,
                            relation=relation,
                            original_rcsd_pair_nodes=None,
                            junc_nodes=junc_nodes,
                            junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                            junc_audit=adaptive_junc_audit,
                            result=r,
                        ),
                        r.geometry,
                    )
                    if conflict_props:
                        candidate_feature["properties"].update(conflict_props)
                    _annotate_adaptive_buffer_metadata(
                        candidate_feature,
                        distance_m=adaptive_distance_m,
                        source_reason=src_reason,
                    )
                    candidate_rows.append(candidate_feature)
                    replaceable_rows.append(_buffer_replaceable_row(candidate_feature))
                    failure_business_audit_rows.append(
                        feature(
                            _failure_business_audit_row(
                                segment_id=segment_id,
                                segment_outcome="replaceable",
                                reject_reason=buffer_result.reason,
                                scenario_type=_scenario_type(adaptive_failure_category),
                                failure_business_category=adaptive_failure_category,
                                pair_nodes=pair_nodes,
                                junc_nodes=junc_nodes,
                                relation=relation,
                                junc_audit=adaptive_junc_audit,
                                probe_result=None,
                                root_cause_category=diagnostic.get("root_cause_category"),
                                adaptive_buffer_distance_m=adaptive_distance_m,
                                adaptive_buffer_source_reason=src_reason,
                                adaptive_buffer_recommendation=_adaptive_buffer_recommendation(directionality),
                            ),
                            r.geometry,
                        )
                    )
                    adaptive_high_grade_buffer_retry_count += 1
                    if directionality == "single":
                        adaptive_high_grade_single_buffer_retry_count += 1
                    elif directionality == "dual":
                        adaptive_high_grade_dual_buffer_retry_count += 1
                    adaptive_success = True
                    break
                if adaptive_success:
                    continue
            formal_retry_stats = _append_buffer_extraction_formal_retry_if_safe(
                segment_id=segment_id,
                props=props,
                directionality=directionality,
                directed_swsd_pair_nodes=directed_swsd_pair_nodes,
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                relation=relation,
                failure_business_category=failure_category,
                source_reject_reason=buffer_result.reason,
                probe_result=probe_result,
                pair_anchor_diagnostic=pair_anchor_diagnostic,
                relation_junc_nodes=relation_junc_nodes,
                relation_map=relation_map,
                segment_geometry=segment.get("geometry"),
                sgrade=segment_props.get("sgrade") or props.get("sgrade"),
                buffer_extractor=buffer_extractor,
                graph_retry=graph_retry,
                buffer_config=buffer_config,
                all_base_ids_for_segment=all_base_ids_for_segment,
                unexpected_base_ids_for_segment=unexpected_base_ids_for_segment,
                rcsd_graph_edges=rcsd_graph_edges,
                rcsd_node_canonicalizer=rcsd_node_canonicalizer,
                max_path_to_swsd_length_ratio=max_coarse_length_ratio,
                rcsd_roads=rcsd_roads,
                junc_attach_audit=_junc_attach_audit,
                output_rows=formal_retry_rows,
            )
            if formal_retry_stats.applied:
                adaptive_high_grade_buffer_retry_count += formal_retry_stats.adaptive_high_grade_buffer_retry_count
                adaptive_high_grade_single_buffer_retry_count += (
                    formal_retry_stats.adaptive_high_grade_single_buffer_retry_count
                )
                continue
            rejection_context = locals()
            _append_final_rejection_rows(
                **{name: rejection_context[name] for name in STEP2_REJECTION_CONTEXT_NAMES}
            )

    finalizer_context = locals()
    return _finalize_step2_run(
        **{name: finalizer_context[name] for name in STEP2_FINALIZER_CONTEXT_NAMES}
    )
