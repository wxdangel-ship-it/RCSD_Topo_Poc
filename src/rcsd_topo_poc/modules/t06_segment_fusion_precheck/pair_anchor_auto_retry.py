from __future__ import annotations

from .buffer_only_probe import BufferOnlyProbeResult
from .pair_anchor_diagnostics import PairAnchorIssueDiagnostic
from .relation_mapping import RelationCheck, RelationRecord


def high_confidence_pair_anchor_relation(
    *,
    probe_result: BufferOnlyProbeResult,
    relation: RelationCheck,
    pair_anchor_diagnostic: PairAnchorIssueDiagnostic | None,
    failure_business_category: str,
    pair_nodes: list[str],
    relation_junc_nodes: list[str],
    relation_map: dict[str, RelationRecord],
    allow_single_missing_candidate_anchor_mismatch: bool = False,
) -> RelationCheck | None:
    if failure_business_category != "pair_anchor_mismatch":
        return None
    if probe_result.status not in {"corridor_found", "corridor_found_with_anchor_mismatch"}:
        return None
    if not probe_result.candidate_pair_sets:
        return None
    candidate_pair = [str(item) for item in probe_result.candidate_pair_sets[0]]
    if len(candidate_pair) != 2 or len(set(candidate_pair)) != 2:
        return None
    effective_pair = _single_missing_pair_completion(candidate_pair, relation=relation, pair_nodes=pair_nodes)
    if effective_pair is not None:
        if not _single_missing_pair_completion_probe_is_safe(probe_result):
            return None
    else:
        effective_pair = (
            _single_missing_candidate_anchor_mismatch_completion(
                candidate_pair,
                relation=relation,
                pair_nodes=pair_nodes,
                diagnostic=pair_anchor_diagnostic,
            )
            if allow_single_missing_candidate_anchor_mismatch
            else None
        )
        if effective_pair is not None:
            if not _fully_missing_pair_completion_probe_is_safe(probe_result, pair_anchor_diagnostic):
                return None
        else:
            effective_pair = _fully_missing_pair_completion(candidate_pair, relation=relation, pair_nodes=pair_nodes)
            if effective_pair is not None:
                if not _fully_missing_pair_completion_probe_is_safe(probe_result, pair_anchor_diagnostic):
                    return None
            else:
                if relation.failed_pair_nodes or len(relation.rcsd_pair_nodes) != 2:
                    return None
                if probe_result.manual_review_required or probe_result.repair_recommendation != "high_confidence_pair_anchor_candidate":
                    return None
                if not _pair_anchor_auto_repair_is_safe(pair_anchor_diagnostic):
                    return None
                effective_pair = candidate_pair
    if len(effective_pair) != 2 or len(set(effective_pair)) != 2:
        return None
    failed_junc_nodes, failed_junc_reasons = _failed_relation_nodes(relation_junc_nodes, relation_map)
    return RelationCheck(
        True,
        effective_pair,
        _accepted_base_ids_for_nodes_ordered(relation_junc_nodes, relation_map),
        failed_junc_nodes=failed_junc_nodes,
        failed_junc_reasons=failed_junc_reasons,
    )


def _single_missing_pair_completion(
    candidate_pair: list[str],
    *,
    relation: RelationCheck,
    pair_nodes: list[str],
) -> list[str] | None:
    failed_pair_nodes = [str(item) for item in (relation.failed_pair_nodes or [])]
    known_nodes = [str(item).strip() for item in relation.rcsd_pair_nodes if str(item).strip()]
    if len(pair_nodes) != 2 or len(failed_pair_nodes) != 1 or len(known_nodes) != 1:
        return None
    known_node = known_nodes[0]
    if known_node not in candidate_pair:
        return None
    inferred_nodes = [node for node in candidate_pair if node != known_node]
    if len(inferred_nodes) != 1:
        return None
    try:
        missing_index = [str(item) for item in pair_nodes].index(failed_pair_nodes[0])
    except ValueError:
        return None
    known_index = 1 - missing_index
    completed = ["", ""]
    completed[known_index] = known_node
    completed[missing_index] = inferred_nodes[0]
    return completed


def _single_missing_pair_completion_probe_is_safe(probe_result: BufferOnlyProbeResult) -> bool:
    if probe_result.status != "corridor_found":
        return False
    if probe_result.connectivity_score < 1.0 or probe_result.directionality_score < 1.0:
        return False
    return probe_result.shape_similarity_score >= 0.95


def _single_missing_candidate_anchor_mismatch_completion(
    candidate_pair: list[str],
    *,
    relation: RelationCheck,
    pair_nodes: list[str],
    diagnostic: PairAnchorIssueDiagnostic | None,
) -> list[str] | None:
    failed_pair_nodes = [str(item) for item in (relation.failed_pair_nodes or [])]
    known_nodes = [str(item).strip() for item in relation.rcsd_pair_nodes if str(item).strip()]
    if len(pair_nodes) != 2 or len(candidate_pair) != 2 or len(set(candidate_pair)) != 2:
        return None
    if len(failed_pair_nodes) != 1 or len(known_nodes) != 1:
        return None
    known_node = known_nodes[0]
    if known_node in candidate_pair:
        return None
    if diagnostic is None:
        return None
    if diagnostic.diagnostic_source != "buffer_only_candidate_pair" or diagnostic.diagnostic_reason != "candidate_anchor_mismatch":
        return None
    if [str(item) for item in diagnostic.candidate_rcsd_pair_nodes] != candidate_pair:
        return None
    if set(str(item) for item in diagnostic.error_swsd_pair_nodes) != {str(item) for item in pair_nodes}:
        return None
    error_original_nodes = [str(item).strip() for item in diagnostic.error_original_rcsd_nodes]
    if known_node not in error_original_nodes or "" not in error_original_nodes:
        return None
    return candidate_pair


def _fully_missing_pair_completion(
    candidate_pair: list[str],
    *,
    relation: RelationCheck,
    pair_nodes: list[str],
) -> list[str] | None:
    failed_pair_nodes = [str(item) for item in (relation.failed_pair_nodes or [])]
    known_nodes = [str(item).strip() for item in relation.rcsd_pair_nodes if str(item).strip()]
    if len(pair_nodes) != 2 or len(candidate_pair) != 2 or len(set(candidate_pair)) != 2:
        return None
    if known_nodes:
        return None
    if set(failed_pair_nodes) != {str(item) for item in pair_nodes}:
        return None
    return candidate_pair


def _fully_missing_pair_completion_probe_is_safe(
    probe_result: BufferOnlyProbeResult,
    diagnostic: PairAnchorIssueDiagnostic | None,
) -> bool:
    if probe_result.status != "corridor_found":
        return False
    if probe_result.manual_review_required or probe_result.repair_recommendation != "high_confidence_pair_anchor_candidate":
        return False
    if probe_result.connectivity_score < 1.0 or probe_result.directionality_score < 1.0:
        return False
    if probe_result.shape_similarity_score < 0.95:
        return False
    return _pair_anchor_auto_repair_is_safe(diagnostic)


def _pair_anchor_auto_repair_is_safe(diagnostic: PairAnchorIssueDiagnostic | None) -> bool:
    if diagnostic is None:
        return False
    changed_existing_endpoints = [node_id for node_id in diagnostic.error_original_rcsd_nodes if str(node_id).strip()]
    if not changed_existing_endpoints:
        return True
    if diagnostic.diagnostic_source == "buffer_only_endpoint_cluster":
        return True
    return _candidate_anchor_mismatch_auto_repair_is_safe(diagnostic)


def _candidate_anchor_mismatch_auto_repair_is_safe(diagnostic: PairAnchorIssueDiagnostic) -> bool:
    if diagnostic.diagnostic_source != "buffer_only_candidate_pair":
        return False
    if diagnostic.diagnostic_reason != "candidate_anchor_mismatch":
        return False
    if diagnostic.candidate_score < 0.85:
        return False
    return 1 <= len(diagnostic.error_candidate_rcsd_nodes) <= 2


def _accepted_base_ids_for_nodes_ordered(
    node_ids: list[str],
    relation_map: dict[str, RelationRecord],
) -> list[str]:
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


def _failed_relation_nodes(
    node_ids: list[str],
    relation_map: dict[str, RelationRecord],
) -> tuple[list[str], dict[str, str]]:
    failed: list[str] = []
    reasons: dict[str, str] = {}
    for node_id in node_ids:
        relation = relation_map.get(node_id)
        if relation is None:
            failed.append(node_id)
            reasons[node_id] = "missing_junc_relation"
        elif relation.status != 0:
            failed.append(node_id)
            reasons[node_id] = "invalid_junc_relation_status"
        elif relation.base_id <= 0:
            failed.append(node_id)
            reasons[node_id] = "invalid_junc_base_id"
    return failed, reasons
