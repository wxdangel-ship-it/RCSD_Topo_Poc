from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from shapely.geometry.base import BaseGeometry

from .buffer_only_probe import BufferOnlyProbeResult
from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor
from .graph_builders import NodeCanonicalizer
from .pair_anchor_diagnostics import PairAnchorIssueDiagnostic
from .pair_anchor_formal_retry import pair_anchor_formal_retry
from .pair_anchor_formal_retry_rows import append_pair_anchor_formal_retry_rows
from .relation_mapping import RelationCheck, RelationRecord
from .single_graph_connectivity_retry import SingleGraphConnectivityRetry


@dataclass(frozen=True)
class RelationMappingFormalRetryStats:
    applied: bool = False
    adaptive_high_grade_buffer_retry_count: int = 0
    adaptive_high_grade_single_buffer_retry_count: int = 0


FormalRetryRows = tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]


def append_relation_mapping_formal_retry_if_safe(
    *,
    segment_id: str,
    props: dict[str, Any],
    directionality: str,
    pair_nodes: list[str],
    road_ids: list[str],
    junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    relation: RelationCheck,
    failure_business_category: str,
    probe_result: BufferOnlyProbeResult,
    pair_anchor_diagnostic: PairAnchorIssueDiagnostic | None,
    relation_junc_nodes: list[str],
    relation_map: dict[str, RelationRecord],
    segment_geometry: BaseGeometry | None,
    sgrade: Any,
    swsd_roads: dict[str, dict[str, Any]],
    swsd_node_canonicalizer: NodeCanonicalizer,
    buffer_extractor: BufferSegmentExtractor,
    graph_retry: SingleGraphConnectivityRetry,
    buffer_config: BufferExtractionConfig,
    all_base_ids_for_segment: set[str],
    unexpected_base_ids_for_segment: set[str],
    rcsd_graph_edges: list[tuple[str, str, str, int | None]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    max_path_to_swsd_length_ratio: float,
    rcsd_roads: list[dict[str, Any]],
    resolve_swsd_single_directed_pair: Callable[..., tuple[list[str], str | None]],
    junc_attach_audit: Callable[..., dict[str, Any]],
    output_rows: FormalRetryRows,
) -> RelationMappingFormalRetryStats:
    if directionality != "single":
        return RelationMappingFormalRetryStats()
    directed_swsd_pair_nodes, direction_reason = resolve_swsd_single_directed_pair(
        pair_nodes=pair_nodes,
        road_ids=road_ids,
        swsd_roads=swsd_roads,
        swsd_node_canonicalizer=swsd_node_canonicalizer,
    )
    if direction_reason is not None:
        return RelationMappingFormalRetryStats()
    source_reason = relation.reject_reason or "relation_mapping_failed"
    retry = pair_anchor_formal_retry(
        probe_result=probe_result,
        relation=relation,
        failure_business_category=failure_business_category,
        source_reject_reason=source_reason,
        pair_nodes=pair_nodes,
        relation_junc_nodes=relation_junc_nodes,
        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
        relation_map=relation_map,
        segment_geometry=segment_geometry,
        sgrade=sgrade,
        directionality=directionality,
        directed_swsd_pair_nodes=directed_swsd_pair_nodes,
        buffer_extractor=buffer_extractor,
        graph_retry=graph_retry,
        buffer_config=buffer_config,
        all_base_ids_for_segment=all_base_ids_for_segment,
        unexpected_base_ids_for_segment=unexpected_base_ids_for_segment,
        rcsd_graph_edges=rcsd_graph_edges,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        max_path_to_swsd_length_ratio=max_path_to_swsd_length_ratio,
        allow_multi_anchor_ambiguous=True,
    )
    if retry is None:
        return RelationMappingFormalRetryStats()
    (
        buffer_segment_rows,
        candidate_rows,
        replaceable_rows,
        buffer_only_probe_rows,
        repair_candidate_rows,
        failure_business_audit_rows,
    ) = output_rows
    junc_audit = junc_attach_audit(
        junc_nodes=relation_junc_nodes,
        relation=retry.relation,
        relation_map=relation_map,
        buffer_result=retry.buffer_result,
        rcsd_roads=rcsd_roads,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    row_stats = append_pair_anchor_formal_retry_rows(
        segment_id=segment_id,
        props=props,
        directionality=directionality,
        directed_swsd_pair_nodes=directed_swsd_pair_nodes,
        pair_nodes=pair_nodes,
        junc_nodes=junc_nodes,
        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
        original_relation=relation,
        source_reject_reason=source_reason,
        failure_business_category=failure_business_category,
        probe_result=probe_result,
        pair_anchor_diagnostic=pair_anchor_diagnostic,
        retry_outcome=retry,
        junc_audit=junc_audit,
        buffer_segment_rows=buffer_segment_rows,
        candidate_rows=candidate_rows,
        replaceable_rows=replaceable_rows,
        buffer_only_probe_rows=buffer_only_probe_rows,
        repair_candidate_rows=repair_candidate_rows,
        failure_business_audit_rows=failure_business_audit_rows,
    )
    return RelationMappingFormalRetryStats(
        applied=True,
        adaptive_high_grade_buffer_retry_count=row_stats.adaptive_high_grade_buffer_retry_count,
        adaptive_high_grade_single_buffer_retry_count=row_stats.adaptive_high_grade_single_buffer_retry_count,
    )


def append_buffer_extraction_formal_retry_if_safe(
    *,
    segment_id: str,
    props: dict[str, Any],
    directionality: str,
    directed_swsd_pair_nodes: list[str],
    pair_nodes: list[str],
    junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    relation: RelationCheck,
    failure_business_category: str,
    source_reject_reason: str,
    probe_result: BufferOnlyProbeResult,
    pair_anchor_diagnostic: PairAnchorIssueDiagnostic | None,
    relation_junc_nodes: list[str],
    relation_map: dict[str, RelationRecord],
    segment_geometry: BaseGeometry | None,
    sgrade: Any,
    buffer_extractor: BufferSegmentExtractor,
    graph_retry: SingleGraphConnectivityRetry,
    buffer_config: BufferExtractionConfig,
    all_base_ids_for_segment: set[str],
    unexpected_base_ids_for_segment: set[str],
    rcsd_graph_edges: list[tuple[str, str, str, int | None]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    max_path_to_swsd_length_ratio: float,
    rcsd_roads: list[dict[str, Any]],
    junc_attach_audit: Callable[..., dict[str, Any]],
    output_rows: FormalRetryRows,
) -> RelationMappingFormalRetryStats:
    retry = pair_anchor_formal_retry(
        probe_result=probe_result,
        relation=relation,
        failure_business_category=failure_business_category,
        source_reject_reason=source_reject_reason,
        pair_nodes=pair_nodes,
        relation_junc_nodes=relation_junc_nodes,
        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
        relation_map=relation_map,
        segment_geometry=segment_geometry,
        sgrade=sgrade,
        directionality=directionality,
        directed_swsd_pair_nodes=directed_swsd_pair_nodes,
        buffer_extractor=buffer_extractor,
        graph_retry=graph_retry,
        buffer_config=buffer_config,
        all_base_ids_for_segment=all_base_ids_for_segment,
        unexpected_base_ids_for_segment=unexpected_base_ids_for_segment,
        rcsd_graph_edges=rcsd_graph_edges,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        max_path_to_swsd_length_ratio=max_path_to_swsd_length_ratio,
    )
    if retry is None:
        return RelationMappingFormalRetryStats()
    (
        buffer_segment_rows,
        candidate_rows,
        replaceable_rows,
        buffer_only_probe_rows,
        repair_candidate_rows,
        failure_business_audit_rows,
    ) = output_rows
    junc_audit = junc_attach_audit(
        junc_nodes=relation_junc_nodes,
        relation=retry.relation,
        relation_map=relation_map,
        buffer_result=retry.buffer_result,
        rcsd_roads=rcsd_roads,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    row_stats = append_pair_anchor_formal_retry_rows(
        segment_id=segment_id,
        props=props,
        directionality=directionality,
        directed_swsd_pair_nodes=directed_swsd_pair_nodes,
        pair_nodes=pair_nodes,
        junc_nodes=junc_nodes,
        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
        original_relation=relation,
        source_reject_reason=source_reject_reason,
        failure_business_category=failure_business_category,
        probe_result=probe_result,
        pair_anchor_diagnostic=pair_anchor_diagnostic,
        retry_outcome=retry,
        junc_audit=junc_audit,
        buffer_segment_rows=buffer_segment_rows,
        candidate_rows=candidate_rows,
        replaceable_rows=replaceable_rows,
        buffer_only_probe_rows=buffer_only_probe_rows,
        repair_candidate_rows=repair_candidate_rows,
        failure_business_audit_rows=failure_business_audit_rows,
    )
    return RelationMappingFormalRetryStats(
        applied=True,
        adaptive_high_grade_buffer_retry_count=row_stats.adaptive_high_grade_buffer_retry_count,
        adaptive_high_grade_single_buffer_retry_count=row_stats.adaptive_high_grade_single_buffer_retry_count,
    )
