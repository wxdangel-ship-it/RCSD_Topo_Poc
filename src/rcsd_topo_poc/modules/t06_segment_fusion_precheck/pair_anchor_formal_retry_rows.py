from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .buffer_only_probe import BufferOnlyProbeResult
from .failure_business_audit import (
    buffer_only_probe_row,
    failure_business_audit_row,
    repair_candidate_row,
)
from .pair_anchor_diagnostics import PairAnchorIssueDiagnostic
from .pair_anchor_formal_retry import PairAnchorFormalRetryOutcome
from .relation_mapping import RelationCheck
from .schemas import feature
from .step2_output_rows import buffer_candidate_row, buffer_replaceable_row, buffer_segment_row


@dataclass(frozen=True)
class FormalRetryAppendStats:
    adaptive_high_grade_buffer_retry_count: int = 0
    adaptive_high_grade_single_buffer_retry_count: int = 0


def append_pair_anchor_formal_retry_rows(
    *,
    segment_id: str,
    props: dict[str, Any],
    directionality: str,
    directed_swsd_pair_nodes: list[str],
    pair_nodes: list[str],
    junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    original_relation: RelationCheck,
    source_reject_reason: str,
    failure_business_category: str,
    probe_result: BufferOnlyProbeResult,
    pair_anchor_diagnostic: PairAnchorIssueDiagnostic | None,
    retry_outcome: PairAnchorFormalRetryOutcome,
    junc_audit: dict[str, Any],
    buffer_segment_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    replaceable_rows: list[dict[str, Any]],
    buffer_only_probe_rows: list[dict[str, Any]],
    repair_candidate_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
) -> FormalRetryAppendStats:
    buffer_only_probe_rows.append(
        feature(
            buffer_only_probe_row(
                segment_id=segment_id,
                pair_nodes=pair_nodes,
                original_rcsd_pair_nodes=original_relation.rcsd_pair_nodes,
                probe_result=probe_result,
                failure_business_category=failure_business_category,
                source_reject_reason=source_reject_reason,
            ),
            probe_result.geometry,
        )
    )
    repair_candidate_rows.append(
        feature(
            repair_candidate_row(
                segment_id=segment_id,
                pair_nodes=pair_nodes,
                original_rcsd_pair_nodes=original_relation.rcsd_pair_nodes,
                probe_result=probe_result,
                failure_business_category=failure_business_category,
                source_reject_reason=source_reject_reason,
                pair_anchor_diagnostic=pair_anchor_diagnostic,
            ),
            probe_result.geometry,
        )
    )
    buffer_feature = feature(
        buffer_segment_row(segment_id, retry_outcome.buffer_result),
        retry_outcome.buffer_result.geometry,
    )
    candidate_feature = feature(
        buffer_candidate_row(
            segment_id=segment_id,
            props=props,
            directionality=directionality,
            directed_swsd_pair_nodes=directed_swsd_pair_nodes,
            relation=retry_outcome.relation,
            original_rcsd_pair_nodes=original_relation.rcsd_pair_nodes,
            junc_nodes=junc_nodes,
            junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
            junc_audit=junc_audit,
            result=retry_outcome.buffer_result,
        ),
        retry_outcome.buffer_result.geometry,
    )
    stats = FormalRetryAppendStats()
    if retry_outcome.adaptive_distance_m is not None:
        _annotate_adaptive_buffer_metadata(
            buffer_feature,
            distance_m=retry_outcome.adaptive_distance_m,
            source_reason=retry_outcome.adaptive_source_reason,
        )
        _annotate_adaptive_buffer_metadata(
            candidate_feature,
            distance_m=retry_outcome.adaptive_distance_m,
            source_reason=retry_outcome.adaptive_source_reason,
        )
        stats = FormalRetryAppendStats(
            adaptive_high_grade_buffer_retry_count=1,
            adaptive_high_grade_single_buffer_retry_count=1,
        )
    buffer_segment_rows.append(buffer_feature)
    candidate_rows.append(candidate_feature)
    replaceable_rows.append(buffer_replaceable_row(candidate_feature))
    failure_business_audit_rows.append(
        feature(
            failure_business_audit_row(
                segment_id=segment_id,
                segment_outcome="replaceable",
                reject_reason=source_reject_reason,
                scenario_type="B",
                failure_business_category=failure_business_category,
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                relation=retry_outcome.relation,
                junc_audit=junc_audit,
                probe_result=probe_result,
                root_cause_category=retry_outcome.diagnostic.get("root_cause_category"),
                adaptive_buffer_distance_m=retry_outcome.adaptive_distance_m,
                adaptive_buffer_source_reason=retry_outcome.adaptive_source_reason,
                adaptive_buffer_recommendation=_adaptive_buffer_recommendation(directionality),
                **_pair_anchor_issue_audit_kwargs(pair_anchor_diagnostic),
            ),
            retry_outcome.buffer_result.geometry,
        )
    )
    return stats


def _annotate_adaptive_buffer_metadata(row: dict[str, Any], *, distance_m: float, source_reason: str) -> None:
    props = row.setdefault("properties", {})
    props["adaptive_buffer_status"] = "applied"
    props["adaptive_buffer_distance_m"] = distance_m
    props["adaptive_buffer_source_reason"] = source_reason


def _adaptive_buffer_recommendation(directionality: str) -> str:
    if directionality == "dual":
        return "adaptive_high_grade_dual_buffer_retry"
    return "single_graph_first_longitudinal_retry"


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
