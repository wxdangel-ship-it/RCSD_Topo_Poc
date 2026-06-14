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
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .pair_anchor_auto_retry import high_confidence_pair_anchor_relation as _high_confidence_pair_anchor_relation
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list, unique_preserve_order
from .pair_anchor_diagnostics import PairAnchorIssueDiagnostic, build_pair_anchor_issue_diagnostic
from .pair_anchor_relation_retry import (
    append_buffer_extraction_formal_retry_if_safe as _append_buffer_extraction_formal_retry_if_safe,
    append_relation_mapping_formal_retry_if_safe as _append_relation_mapping_formal_retry_if_safe,
)
from .rejected_context import annotate_rejected_swsd_context as _annotate_rejected_swsd_context
from .relation_mapping import RelationCheck, RelationRecord, accepted_base_ids, build_relation_map, check_segment_relations
from .single_graph_connectivity_retry import SingleGraphConnectivityRetry as _SGR
from .step2_output_rows import (
    buffer_candidate_row as _buffer_candidate_row,
    buffer_replaceable_row as _buffer_replaceable_row,
    buffer_segment_row as _buffer_segment_row,
)
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
    STEP2_REPAIR_CANDIDATE_FIELDS,
    STEP2_REPAIR_CANDIDATES_STEM,
    STEP2_REJECTED_FIELDS,
    STEP2_REJECTED_STEM,
    STEP2_REPLACEABLE_FIELDS,
    STEP2_REPLACEABLE_STEM,
    STEP2_SPECIAL_JUNCTION_GROUP_FIELDS,
    STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
    STEP2_SUMMARY,
    T06Step2Artifacts,
    feature,
)

SPECIAL_JUNCTION_KIND_TYPES = {64: "roundabout", 128: "complex"}


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
) -> T06Step2Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP2_DIR)
    fusion_units = read_features(swsd_fusion_units_path)
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
    all_base_ids = accepted_base_ids(relation_map)

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
        segment = segments.get(segment_id, unit)
        segment_props = dict(segment.get("properties") or {})
        pair_nodes, junc_nodes, junc_kind2_exempt_nodes, _roads, parse_reason = _parse_unit_lists(props, segment_props)
        if parse_reason is not None:
            rejected_rows.append(_reject(segment_id, None, "parse", parse_reason))
            continue
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
        unexpected_base_ids_for_segment = _unexpected_base_ids_for_segment([*pair_nodes, *junc_nodes], relation_map)
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
        junc_audit = _junc_attach_audit(
            junc_nodes=relation_junc_nodes,
            relation=relation,
            relation_map=relation_map,
            buffer_result=buffer_result,
            rcsd_roads=rcsd_roads,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
        if buffer_result.ok:
            buffer_feature = feature(_buffer_segment_row(segment_id, buffer_result), buffer_result.geometry)
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
            auto_relation = _high_confidence_pair_anchor_relation(
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
                auto_junc_audit = _junc_attach_audit(
                    junc_nodes=relation_junc_nodes,
                    relation=auto_relation,
                    relation_map=relation_map,
                    buffer_result=auto_buffer_result,
                    rcsd_roads=rcsd_roads,
                    rcsd_node_canonicalizer=rcsd_node_canonicalizer,
                )
                if auto_buffer_result.ok:
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
                for adaptive_distance_m in adaptive_plan.distances_m:
                    src_reason = buffer_result.reason
                    if directionality == "single":
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
                        r = buffer_extractor.extract(
                            segment_geometry=segment.get("geometry"),
                            relation=relation,
                            optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
                            all_relation_base_ids=all_base_ids_for_segment,
                            unexpected_relation_base_ids=unexpected_base_ids_for_segment,
                            directed_pair_nodes=directed_rcsd_pair_nodes,
                            require_directed_pair=False,
                            require_bidirectional=True,
                            config=_buffer_config_with_distance(buffer_config, adaptive_distance_m),
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

    special_group_rows, blocked_segment_ids, removed_replaceable_segment_ids, blocking_groups_by_segment = _special_junction_gate(
        special_junction_segments=special_junction_segments,
        special_swsd_junction_types=special_swsd_junction_types,
        replaceable_rows=replaceable_rows,
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
    if removed_replaceable_segment_ids:
        candidate_props_by_segment = {
            str((row.get("properties") or {}).get("swsd_segment_id")): dict(row.get("properties") or {})
            for row in candidate_rows
            if (row.get("properties") or {}).get("swsd_segment_id") is not None
        }
        replaceable_rows = [
            row for row in replaceable_rows if (row.get("properties") or {}).get("swsd_segment_id") not in removed_replaceable_segment_ids
        ]
        for segment_id in sorted(removed_replaceable_segment_ids):
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "special_junction_group_gate",
                    "special_junction_group_not_fully_replaceable",
                    failed_metric_name="special_junction_group_ids",
                    failed_metric_value=blocking_groups_by_segment.get(segment_id, []),
                    notes="roundabout or complex junction group has at least one associated Segment that is not replaceable",
                )
            )
            props = candidate_props_by_segment.get(segment_id, {})
            failure_business_audit_rows.append(
                feature(
                    {
                        "swsd_segment_id": segment_id,
                        "segment_outcome": "special_gate_removed",
                        "reject_reason": "special_junction_group_not_fully_replaceable",
                        "scenario_type": "B",
                        "buffer_only_candidate_status": "corridor_found",
                        "failure_business_category": "multi_anchor_ambiguous",
                        "auto_fix_candidate": False,
                        "manual_review_required": True,
                        "repair_recommendation": "manual_review_required",
                        "swsd_pair_nodes": props.get("swsd_pair_nodes", []),
                        "swsd_junc_nodes": props.get("swsd_junc_nodes", []),
                        "original_rcsd_pair_nodes": props.get("rcsd_pair_nodes", []),
                        "rcsd_pair_nodes": props.get("rcsd_pair_nodes", []),
                        "rcsd_junc_nodes": props.get("rcsd_junc_nodes", []),
                        "required_rcsd_nodes": props.get("required_rcsd_nodes", []),
                        "optional_junc_nodes": props.get("optional_junc_nodes", []),
                        "optional_junc_rcsd_nodes": props.get("optional_junc_rcsd_nodes", []),
                        "dropped_junc_nodes": props.get("dropped_junc_nodes", []),
                        "dropped_junc_relation_nodes": props.get("dropped_junc_relation_nodes", []),
                        "lost_attach_road_ids": props.get("lost_attach_road_ids", []),
                        "isolated_attach_loss_count": props.get("isolated_attach_loss_count", 0),
                        "junc_attach_loss_reason": props.get("junc_attach_loss_reason", ""),
                        "candidate_rcsd_pair_node_sets": [props.get("rcsd_pair_nodes", [])],
                        "candidate_score": 0.0,
                        "geometry_overlap_ratio": 0.0,
                        "directionality_score": 0.0,
                        "connectivity_score": 0.0,
                        "shape_similarity_score": 0.0,
                        "root_cause_category": "special_junction_group_gate",
                        "upstream_issue_owner": "T06",
                    },
                    None,
                )
            )

    attach_promotion_stats = _promote_isolated_attach_roads(
        candidate_rows=candidate_rows,
        replaceable_rows=replaceable_rows,
        failure_business_audit_rows=failure_business_audit_rows,
    )
    _annotate_rejected_swsd_context(rejected_rows, fusion_units=fusion_units, segments=segments)
    _normalize_repair_candidate_rows_from_business_audit(repair_candidate_rows, failure_business_audit_rows)
    candidate_paths = write_feature_triplet(step_root=step_root, stem=STEP2_CANDIDATES_STEM, features=candidate_rows, fieldnames=STEP2_CANDIDATE_FIELDS)
    replaceable_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REPLACEABLE_STEM, features=replaceable_rows, fieldnames=STEP2_REPLACEABLE_FIELDS)
    rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REJECTED_STEM, features=rejected_rows, fieldnames=STEP2_REJECTED_FIELDS)
    buffer_segment_paths = write_feature_triplet(step_root=step_root, stem=STEP2_BUFFER_SEGMENTS_STEM, features=buffer_segment_rows, fieldnames=STEP2_BUFFER_SEGMENT_FIELDS)
    buffer_rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_BUFFER_REJECTED_STEM, features=buffer_rejected_rows, fieldnames=STEP2_BUFFER_REJECTED_FIELDS)
    buffer_only_probe_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP2_BUFFER_ONLY_PROBE_STEM,
        features=buffer_only_probe_rows,
        fieldnames=STEP2_BUFFER_ONLY_PROBE_FIELDS,
    )
    repair_candidate_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP2_REPAIR_CANDIDATES_STEM,
        features=repair_candidate_rows,
        fieldnames=STEP2_REPAIR_CANDIDATE_FIELDS,
    )
    failure_business_audit_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP2_FAILURE_BUSINESS_AUDIT_STEM,
        features=failure_business_audit_rows,
        fieldnames=STEP2_FAILURE_BUSINESS_AUDIT_FIELDS,
    )
    special_group_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
        features=special_group_rows,
        fieldnames=STEP2_SPECIAL_JUNCTION_GROUP_FIELDS,
    )
    rcsd_road_stats = _rcsd_road_coverage_stats(rcsd_roads=rcsd_roads, replaceable_rows=replaceable_rows)
    business_stats = _business_audit_stats(failure_business_audit_rows, replaceable_rows, input_count=len(fusion_units))
    summary_path = step_root / STEP2_SUMMARY
    write_json(
        summary_path,
        {
            "run_id": resolved_run_id,
            "input_paths": {
                "swsd_fusion_units_path": str(swsd_fusion_units_path),
                "swsd_segment_path": str(swsd_segment_path),
                "swsd_roads_path": str(swsd_roads_path),
                "swsd_nodes_path": str(swsd_nodes_path),
                "intersection_match_path": str(intersection_match_path),
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
            "special_junction_group_blocked_count": sum(1 for item in special_group_rows if item["properties"].get("gate_status") == "blocked"),
            "special_junction_blocked_segment_count": len(blocked_segment_ids),
            "special_junction_gate_removed_replaceable_count": len(removed_replaceable_segment_ids),
            "special_junction_group_type_counts": dict(Counter(item["properties"].get("special_junction_type") for item in special_group_rows)),
            "buffer_only_probe_count": len(buffer_only_probe_rows),
            "repair_candidate_count": len(repair_candidate_rows),
            "failure_business_audit_count": len(failure_business_audit_rows),
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
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "buffer-based RCSD Segment graph uses canonicalized RCSD semantic nodes, explicit component coverage checks and special junction group gating",
                "geometry_semantics": "SWSD geometry defines the buffer window; RCSD geometry is used for intersects/overlap candidate selection and retained output geometry",
                "audit_traceability": "input paths, params, counts, reasons, adaptive buffer retry distance and outputs recorded",
                "performance_verifiable": "input counts, candidate counts and output sizes are reproducible from summary",
            },
        },
    )
    return T06Step2Artifacts(resolved_run_id, run_root, step_root, candidate_paths["gpkg"], replaceable_paths["gpkg"], rejected_paths["gpkg"], summary_path)


def _segment_index(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for feature in features:
        try:
            result[normalize_id((feature.get("properties") or {}).get("id"))] = feature
        except ParseError:
            continue
    return result


def _normalize_repair_candidate_rows_from_business_audit(
    repair_candidate_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
) -> None:
    auto_repair_by_segment: dict[str, str] = {}
    for row in failure_business_audit_rows:
        props = row.get("properties") or {}
        recommendation = props.get("repair_recommendation")
        if props.get("segment_outcome") != "replaceable":
            continue
        if recommendation not in {"high_confidence_pair_anchor_candidate", "side_preserving_missing_pair_anchor_completion"}:
            continue
        auto_repair_by_segment[str(props.get("swsd_segment_id"))] = str(recommendation)
    for row in repair_candidate_rows:
        props = row.get("properties") or {}
        recommendation = auto_repair_by_segment.get(str(props.get("swsd_segment_id")))
        if recommendation is None:
            continue
        props["manual_review_required"] = False
        props["repair_recommendation"] = recommendation


def _buffer_config_with_distance(config: BufferExtractionConfig, distance_m: float) -> BufferExtractionConfig:
    return BufferExtractionConfig(
        buffer_distance_m=distance_m,
        min_road_overlap_ratio=config.min_road_overlap_ratio,
        min_road_overlap_length_m=config.min_road_overlap_length_m,
        advance_right_formway_bit=config.advance_right_formway_bit,
        max_geometry_buffer_mismatch_ratio=config.max_geometry_buffer_mismatch_ratio,
        min_geometry_buffer_mismatch_length_m=config.min_geometry_buffer_mismatch_length_m,
    )


def _annotate_adaptive_buffer_metadata(
    row: dict[str, Any],
    *,
    distance_m: float,
    source_reason: str,
) -> None:
    props = row.setdefault("properties", {})
    props["adaptive_buffer_status"] = "applied"
    props["adaptive_buffer_distance_m"] = distance_m
    props["adaptive_buffer_source_reason"] = source_reason


def _adaptive_buffer_failure_category(reason: str, diagnostic: dict[str, Any]) -> str:
    if reason in {"retained_geometry_outside_swsd_buffer_scope", "swsd_geometry_not_covered_by_retained_rcsd"}:
        return "geometry_shape_mismatch"
    if diagnostic.get("full_graph_status") == "required_nodes_connected":
        return "rcsd_graph_break_inside_buffer"
    return "evidence_slice_incomplete"


def _adaptive_buffer_recommendation(directionality: str) -> str:
    if directionality == "dual":
        return "adaptive_high_grade_dual_buffer_retry"
    return "single_graph_first_longitudinal_retry"


def _special_swsd_junction_types(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, str]:
    by_node: dict[str, set[str]] = defaultdict(set)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            semantic_id = canonicalizer.canonicalize(props.get("id"))
        except ParseError:
            continue
        kind_2 = _coerce_int(props.get("kind_2"))
        special_type = SPECIAL_JUNCTION_KIND_TYPES.get(kind_2)
        if special_type is not None:
            by_node[semantic_id].add(special_type)
    return {
        node_id: next(iter(types)) if len(types) == 1 else "mixed"
        for node_id, types in by_node.items()
    }


def _segment_special_junction_ids(
    semantic_node_ids: list[str],
    special_swsd_junction_types: dict[str, str],
    canonicalizer: NodeCanonicalizer,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for node_id in semantic_node_ids:
        try:
            semantic_id = canonicalizer.canonicalize(node_id)
        except ParseError:
            continue
        if semantic_id not in special_swsd_junction_types or semantic_id in seen:
            continue
        seen.add(semantic_id)
        result.append(semantic_id)
    return result


def _special_gate_applies_to_segment(pair_nodes: list[str]) -> bool:
    return len(set(pair_nodes)) >= 2


def _rcsd_semantic_node_ids(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            node_id = normalize_id(props.get("id"))
            semantic_id = canonicalizer.canonicalize(node_id)
        except ParseError:
            continue
        if node_id not in result[semantic_id]:
            result[semantic_id].append(node_id)
    return dict(result)


def _rcsd_internal_road_ids(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source != target or road_id in result[source]:
            continue
        result[source].append(road_id)
    return dict(result)


def _rcsd_graph_edges(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> list[tuple[str, str, str, int | None]]:
    edges: list[tuple[str, str, str, int | None]] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source == target:
            continue
        edges.append((road_id, source, target, _coerce_int(props.get("direction"))))
    return edges


def _special_junction_gate(
    *,
    special_junction_segments: dict[str, list[str]],
    special_swsd_junction_types: dict[str, str],
    replaceable_rows: list[dict[str, Any]],
    relation_map: dict[str, RelationRecord],
    rcsd_junction_node_ids: dict[str, list[str]],
    rcsd_junction_road_ids: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], set[str], set[str], dict[str, list[str]]]:
    replaceable_segment_ids = {
        str((row.get("properties") or {}).get("swsd_segment_id"))
        for row in replaceable_rows
        if (row.get("properties") or {}).get("swsd_segment_id") is not None
    }
    rows: list[dict[str, Any]] = []
    blocked_segment_ids: set[str] = set()
    removed_replaceable_segment_ids: set[str] = set()
    blocking_groups_by_segment: dict[str, list[str]] = defaultdict(list)

    for special_junction_id, associated_segment_ids in sorted(special_junction_segments.items()):
        associated = unique_preserve_order(associated_segment_ids)
        replaceable = [segment_id for segment_id in associated if segment_id in replaceable_segment_ids]
        missing = [segment_id for segment_id in associated if segment_id not in replaceable_segment_ids]
        gate_status = "passed" if not missing else "blocked"
        if missing:
            blocked_segment_ids.update(associated)
            for segment_id in associated:
                if special_junction_id not in blocking_groups_by_segment[segment_id]:
                    blocking_groups_by_segment[segment_id].append(special_junction_id)
            removed_replaceable_segment_ids.update(segment_id for segment_id in associated if segment_id in replaceable_segment_ids)

        relation = relation_map.get(special_junction_id)
        rcsd_junction_id = ""
        relation_status = "missing_relation"
        if relation is not None:
            if relation.status == 0 and relation.base_id > 0:
                rcsd_junction_id = str(relation.base_id)
                relation_status = "accepted"
            else:
                relation_status = "invalid_relation_status"
        rows.append(
            feature(
                {
                    "special_junction_id": special_junction_id,
                    "special_junction_type": special_swsd_junction_types.get(special_junction_id, "unknown"),
                    "gate_status": gate_status,
                    "relation_status": relation_status,
                    "rcsd_junction_id": rcsd_junction_id,
                    "associated_segment_ids": associated,
                    "associated_segment_count": len(associated),
                    "replaceable_segment_ids": replaceable,
                    "replaceable_segment_count": len(replaceable),
                    "missing_replaceable_segment_ids": missing,
                    "removed_replaceable_segment_ids": [segment_id for segment_id in associated if segment_id in removed_replaceable_segment_ids],
                    "rcsd_junction_node_ids": rcsd_junction_node_ids.get(rcsd_junction_id, []),
                    "rcsd_junction_road_ids": rcsd_junction_road_ids.get(rcsd_junction_id, []),
                    "notes": "all associated Segments are replaceable" if gate_status == "passed" else "at least one associated Segment is not replaceable",
                },
                None,
            )
        )
    return rows, blocked_segment_ids, removed_replaceable_segment_ids, dict(blocking_groups_by_segment)


def _annotate_special_junction_gate(
    rows: list[dict[str, Any]],
    *,
    segment_special_junctions: dict[str, list[str]],
    special_swsd_junction_types: dict[str, str],
    blocked_segment_ids: set[str],
    blocking_groups_by_segment: dict[str, list[str]],
) -> None:
    for row in rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        group_ids = segment_special_junctions.get(segment_id, [])
        if not group_ids:
            gate_status = "not_applicable"
        elif segment_id in blocked_segment_ids:
            gate_status = "blocked"
        else:
            gate_status = "passed"
        props["special_junction_group_ids"] = group_ids
        props["special_junction_group_types"] = [special_swsd_junction_types.get(group_id, "unknown") for group_id in group_ids]
        props["special_junction_gate_status"] = gate_status
        props["special_junction_blocking_group_ids"] = blocking_groups_by_segment.get(segment_id, [])
        row["properties"] = props


def _rcsd_road_coverage_stats(*, rcsd_roads: list[dict[str, Any]], replaceable_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rcsd_road_by_id = _segment_index(rcsd_roads)
    replaceable_reference_ids: list[str] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        try:
            replaceable_reference_ids.extend(parse_id_list(props.get("rcsd_road_ids"), allow_empty=True))
        except ParseError:
            continue
    replaceable_unique_ids = unique_preserve_order(
        road_id for road_id in replaceable_reference_ids if road_id in rcsd_road_by_id
    )
    return {
        "rcsd_road_total_count": len(rcsd_road_by_id),
        "rcsd_road_total_length_m": _round_length(sum(_feature_length(feature) for feature in rcsd_road_by_id.values())),
        "replaceable_rcsd_road_unique_count": len(replaceable_unique_ids),
        "replaceable_rcsd_road_unique_length_m": _round_length(
            sum(_feature_length(rcsd_road_by_id[road_id]) for road_id in replaceable_unique_ids)
        ),
        "replaceable_rcsd_road_reference_count": len(replaceable_reference_ids),
        "replaceable_rcsd_road_reference_length_m": _round_length(
            sum(_feature_length(rcsd_road_by_id[road_id]) for road_id in replaceable_reference_ids if road_id in rcsd_road_by_id)
        ),
        "replaceable_rcsd_road_missing_count": sum(1 for road_id in replaceable_reference_ids if road_id not in rcsd_road_by_id),
        "rcsd_road_coverage_stats_basis": "unique_count_and_length_from_final_replaceable_rcsd_road_ids",
    }


def _feature_length(feature: dict[str, Any]) -> float:
    geometry = feature.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)


def _parse_unit_lists(props: dict[str, Any], segment_props: dict[str, Any]) -> tuple[list[str], list[str], list[str], list[str], str | None]:
    try:
        pair_nodes = parse_id_list(props.get("pair_nodes", segment_props.get("pair_nodes")), allow_empty=False)
        if len(pair_nodes) != 2:
            return [], [], [], [], "invalid_pair_nodes"
    except ParseError:
        return [], [], [], [], "invalid_pair_nodes"
    try:
        junc_nodes = parse_id_list(props.get("junc_nodes", segment_props.get("junc_nodes")), allow_empty=True)
    except ParseError:
        return [], [], [], [], "invalid_junc_nodes"
    try:
        junc_kind2_exempt_nodes = parse_id_list(props.get("junc_kind2_exempt_nodes"), allow_empty=True)
    except ParseError:
        junc_kind2_exempt_nodes = []
    try:
        roads = parse_id_list(props.get("roads", segment_props.get("roads")), allow_empty=True)
    except ParseError:
        roads = []
    return pair_nodes, junc_nodes, junc_kind2_exempt_nodes, roads, None


def _resolve_swsd_single_directed_pair(
    *,
    pair_nodes: list[str],
    road_ids: list[str],
    swsd_roads: dict[str, dict[str, Any]],
    swsd_node_canonicalizer: NodeCanonicalizer,
) -> tuple[list[str], str | None]:
    if len(pair_nodes) != 2:
        return [], "invalid_pair_nodes"

    canonical_pair_nodes = _canonical_swsd_pair_nodes(pair_nodes, swsd_node_canonicalizer)
    adjacency: dict[str, set[str]] = defaultdict(set)
    resolved_edge_count = 0
    for road_id in road_ids:
        road = swsd_roads.get(road_id)
        if road is None:
            continue
        endpoints = _swsd_road_canonical_endpoints(road, swsd_node_canonicalizer)
        if endpoints is None:
            continue
        source, target = endpoints
        if source == target:
            continue
        direction = _coerce_int((road.get("properties") or {}).get("direction"))
        added = False
        if direction in {0, 1, 2}:
            adjacency[source].add(target)
            added = True
        if direction in {0, 1, 3}:
            adjacency[target].add(source)
            added = True
        if added:
            resolved_edge_count += 1

    if resolved_edge_count == 0:
        return [], "swsd_single_direction_unresolved"

    first, second = canonical_pair_nodes
    forward = _directed_reachable(adjacency, first, second)
    reverse = _directed_reachable(adjacency, second, first)
    if forward and not reverse:
        return [pair_nodes[0], pair_nodes[1]], None
    if reverse and not forward:
        return [pair_nodes[1], pair_nodes[0]], None
    if forward and reverse:
        return [], "swsd_single_direction_ambiguous"
    return [], "swsd_single_direction_unresolved"


def _canonical_swsd_pair_nodes(pair_nodes: list[str], swsd_node_canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    for node_id in pair_nodes:
        try:
            result.append(swsd_node_canonicalizer.canonicalize(node_id))
        except ParseError:
            result.append(node_id)
    return result


def _swsd_road_canonical_endpoints(
    road: dict[str, Any],
    swsd_node_canonicalizer: NodeCanonicalizer,
) -> tuple[str, str] | None:
    props = dict(road.get("properties") or {})
    try:
        source = swsd_node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
        target = swsd_node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
    except (KeyError, ParseError):
        return None
    return source, target


def _map_directed_swsd_pair_to_rcsd(
    *,
    pair_nodes: list[str],
    rcsd_pair_nodes: list[str],
    directed_swsd_pair_nodes: list[str],
) -> list[str]:
    if len(pair_nodes) != 2 or len(rcsd_pair_nodes) != 2 or len(directed_swsd_pair_nodes) != 2:
        return []
    mapping = {pair_nodes[0]: rcsd_pair_nodes[0], pair_nodes[1]: rcsd_pair_nodes[1]}
    result: list[str] = []
    for node_id in directed_swsd_pair_nodes:
        rcsd_node = mapping.get(node_id)
        if rcsd_node is None:
            return []
        result.append(rcsd_node)
    return result


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props.get(name) is not None:
            return props[name]
    raise KeyError(names[0])


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _directed_reachable(adjacency: dict[str, set[str]], source: str, target: str) -> bool:
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        if node == target:
            return True
        for neighbor in adjacency.get(node, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return False


def _relation_required_junc_nodes(junc_nodes: list[str], junc_kind2_exempt_nodes: list[str]) -> list[str]:
    exempt = set(junc_kind2_exempt_nodes)
    return [node_id for node_id in junc_nodes if node_id not in exempt]


def _accepted_base_ids_for_nodes(node_ids: list[str], relation_map: dict[str, RelationRecord]) -> set[str]:
    result: set[str] = set()
    for node_id in node_ids:
        relation = relation_map.get(node_id)
        if relation is None or relation.status != 0 or relation.base_id <= 0:
            continue
        result.add(str(relation.base_id))
    return result


def _accepted_base_ids_for_nodes_ordered(node_ids: list[str], relation_map: dict[str, RelationRecord]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        relation = relation_map.get(node_id)
        if relation is None or relation.status != 0 or relation.base_id <= 0:
            continue
        base_id = str(relation.base_id)
        if base_id in seen:
            continue
        seen.add(base_id)
        result.append(base_id)
    return result


def _unexpected_base_ids_for_segment(allowed_node_ids: list[str], relation_map: dict[str, RelationRecord]) -> set[str]:
    allowed = set(allowed_node_ids)
    result: set[str] = set()
    for target_id, relation in relation_map.items():
        if target_id in allowed or relation.status != 0 or relation.base_id <= 0:
            continue
        result.add(str(relation.base_id))
    return result


def _junc_attach_audit(
    *,
    junc_nodes: list[str],
    relation: Any,
    relation_map: dict[str, RelationRecord],
    buffer_result: BufferSegmentResult,
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> dict[str, Any]:
    swsd_to_rcsd: dict[str, str] = {}
    for node_id in junc_nodes:
        item = relation_map.get(node_id)
        if item is None or item.status != 0 or item.base_id <= 0:
            continue
        try:
            swsd_to_rcsd[node_id] = rcsd_node_canonicalizer.canonicalize(str(item.base_id))
        except ParseError:
            swsd_to_rcsd[node_id] = str(item.base_id)

    optional_junc_nodes = list(swsd_to_rcsd)
    optional_junc_rcsd_nodes = unique_preserve_order(list(swsd_to_rcsd.values()))
    out_nodes = set(buffer_result.out_node_ids)
    retained_nodes = set(buffer_result.retained_node_ids)
    dropped_relation_nodes = [
        node_id
        for node_id in optional_junc_rcsd_nodes
        if node_id in out_nodes or (buffer_result.ok and node_id not in retained_nodes)
    ]
    dropped_junc_nodes = unique_preserve_order(
        [
            *(relation.failed_junc_nodes or []),
            *[swsd_id for swsd_id, rcsd_id in swsd_to_rcsd.items() if rcsd_id in dropped_relation_nodes],
        ]
    )
    lost_attach_road_ids = _lost_attach_road_ids(
        dropped_relation_nodes=dropped_relation_nodes,
        buffer_result=buffer_result,
        rcsd_roads=rcsd_roads,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    reasons: list[str] = []
    if relation.failed_junc_nodes:
        reasons.append("junc_relation_missing_or_invalid")
    if dropped_relation_nodes:
        reasons.append("isolated_optional_junc_pruned")
    return {
        "optional_junc_nodes": optional_junc_nodes,
        "optional_junc_rcsd_nodes": optional_junc_rcsd_nodes,
        "dropped_junc_nodes": dropped_junc_nodes,
        "dropped_junc_relation_nodes": dropped_relation_nodes,
        "lost_attach_road_ids": lost_attach_road_ids,
        "isolated_attach_loss_count": len(dropped_junc_nodes),
        "junc_attach_loss_reason": ";".join(reasons),
    }


def _optional_allowed_rcsd_nodes(
    *,
    relation: Any,
    relation_junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    relation_map: dict[str, RelationRecord],
) -> list[str]:
    return unique_preserve_order(
        [
            *relation.rcsd_junc_nodes,
            *_accepted_base_ids_for_nodes_ordered(relation_junc_nodes, relation_map),
            *_accepted_base_ids_for_nodes_ordered(junc_kind2_exempt_nodes, relation_map),
        ]
    )


def _pair_anchor_issue_diagnostic(
    *,
    probe_result: BufferOnlyProbeResult,
    relation: Any,
    failure_business_category: str,
    pair_nodes: list[str],
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> PairAnchorIssueDiagnostic | None:
    return build_pair_anchor_issue_diagnostic(
        probe_result=probe_result,
        relation=relation,
        failure_business_category=failure_business_category,
        pair_nodes=pair_nodes,
        rcsd_road_features=rcsd_roads,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )


def _pair_anchor_issue_audit_kwargs(diagnostic: PairAnchorIssueDiagnostic | None) -> dict[str, Any]:
    if diagnostic is None:
        return {}
    return {
        "original_rcsd_pair_nodes": diagnostic.original_rcsd_pair_nodes,
        "pair_anchor_error_swsd_nodes": diagnostic.error_swsd_pair_nodes,
        "pair_anchor_error_original_rcsd_nodes": diagnostic.error_original_rcsd_nodes,
        "pair_anchor_error_candidate_rcsd_nodes": diagnostic.error_candidate_rcsd_nodes,
        "pair_anchor_endpoint_cluster_nodes": diagnostic.endpoint_cluster_nodes,
        "pair_anchor_bridge_road_ids": diagnostic.endpoint_bridge_road_ids,
        "pair_anchor_bridge_length_m": diagnostic.endpoint_bridge_length_m,
        "pair_anchor_diagnostic_source": diagnostic.diagnostic_source,
        "pair_anchor_diagnostic_reason": diagnostic.diagnostic_reason,
    }


def _lost_attach_road_ids(
    *,
    dropped_relation_nodes: list[str],
    buffer_result: BufferSegmentResult,
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    dropped = set(dropped_relation_nodes)
    if not dropped:
        return []
    candidate_ids = set(buffer_result.candidate_road_ids)
    retained_ids = set(buffer_result.retained_road_ids)
    result: list[str] = []
    for road in rcsd_roads:
        props = dict(road.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = rcsd_node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = rcsd_node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if road_id not in candidate_ids or road_id in retained_ids:
            continue
        if source in dropped or target in dropped:
            result.append(road_id)
    return unique_preserve_order(result)


def _buffer_rejected_row(segment_id: str, result: BufferSegmentResult, diagnostic: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostic = diagnostic or {}
    return feature(
        {
            "swsd_segment_id": segment_id,
            "reject_stage": "buffer_segment_extraction",
            "reject_reason": result.reason,
            "root_cause_category": diagnostic.get("root_cause_category"),
            "full_graph_status": diagnostic.get("full_graph_status"),
            "candidate_graph_status": diagnostic.get("candidate_graph_status"),
            "directional_status": diagnostic.get("directional_status"),
            "required_rcsd_nodes": result.required_rcsd_nodes,
            "optional_allowed_rcsd_nodes": result.optional_allowed_rcsd_nodes,
            "directed_rcsd_pair_nodes": result.directed_rcsd_pair_nodes,
            "missing_required_node_ids": result.missing_required_node_ids,
            "retained_rcsd_road_ids": result.retained_road_ids,
            "candidate_rcsd_road_ids": result.candidate_road_ids,
            "candidate_rcsd_node_ids": result.candidate_node_ids,
            "excluded_advance_right_turn_road_ids": result.excluded_advance_right_turn_road_ids,
            "retained_node_ids": result.retained_node_ids,
            "inner_node_ids": result.inner_node_ids,
            "out_node_ids": result.out_node_ids,
            "unexpected_endpoint_node_ids": result.unexpected_endpoint_node_ids,
            "unexpected_mapped_semantic_node_ids": result.unexpected_mapped_semantic_node_ids,
            "selected_component_id": result.selected_component_id,
            "candidate_road_count": result.candidate_road_count,
            "retained_road_count": result.retained_road_count,
            "candidate_node_count": result.candidate_node_count,
            "retained_node_count": result.retained_node_count,
            "notes": diagnostic.get("diagnostic_notes"),
        },
        None,
    )


def _reject(
    segment_id: str,
    candidate_id: str | None,
    stage: str,
    reason: str,
    *,
    failed_pair_nodes: list[str] | None = None,
    failed_junc_nodes: list[str] | None = None,
    junc_kind2_exempt_nodes: list[str] | None = None,
    failed_metric_name: str | None = None,
    failed_metric_value: Any = None,
    threshold_value: Any = None,
    root_cause_category: str | None = None,
    full_graph_status: str | None = None,
    candidate_graph_status: str | None = None,
    directional_status: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return feature(
        {
            "swsd_segment_id": segment_id,
            "rcsd_candidate_id": candidate_id,
            "reject_stage": stage,
            "reject_reason": reason,
            "root_cause_category": root_cause_category,
            "full_graph_status": full_graph_status,
            "candidate_graph_status": candidate_graph_status,
            "directional_status": directional_status,
            "failed_pair_nodes": failed_pair_nodes or [],
            "failed_junc_nodes": failed_junc_nodes or [],
            "junc_kind2_exempt_nodes": junc_kind2_exempt_nodes or [],
            "failed_metric_name": failed_metric_name,
            "failed_metric_value": failed_metric_value,
            "threshold_value": threshold_value,
            "notes": notes,
        },
        None,
    )
