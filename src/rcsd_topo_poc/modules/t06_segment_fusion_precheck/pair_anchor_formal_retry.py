from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry.base import BaseGeometry

from .buffer_failure_diagnostics import buffer_failure_diagnostic
from .buffer_only_probe import BufferOnlyProbeResult
from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor, BufferSegmentResult
from .graph_builders import NodeCanonicalizer
from .parsing import unique_preserve_order
from .relation_mapping import RelationCheck, RelationRecord
from .single_graph_connectivity_retry import SingleGraphConnectivityRetry, SingleGraphConnectivityRetryOutcome


@dataclass(frozen=True)
class PairAnchorFormalRetryOutcome:
    relation: RelationCheck
    buffer_result: BufferSegmentResult
    diagnostic: dict[str, Any]
    adaptive_distance_m: float | None = None
    adaptive_source_reason: str = ""


def pair_anchor_formal_retry(
    *,
    probe_result: BufferOnlyProbeResult,
    relation: RelationCheck,
    failure_business_category: str,
    source_reject_reason: str,
    pair_nodes: list[str],
    relation_junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    relation_map: dict[str, RelationRecord],
    segment_geometry: BaseGeometry | None,
    sgrade: Any,
    directionality: str,
    directed_swsd_pair_nodes: list[str],
    buffer_extractor: BufferSegmentExtractor,
    graph_retry: SingleGraphConnectivityRetry,
    buffer_config: BufferExtractionConfig,
    all_base_ids_for_segment: set[str],
    unexpected_base_ids_for_segment: set[str],
    rcsd_graph_edges: list[tuple[str, str, str, int | None]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    max_path_to_swsd_length_ratio: float,
    allow_multi_anchor_ambiguous: bool = False,
) -> PairAnchorFormalRetryOutcome | None:
    if not _eligible(
        probe_result=probe_result,
        failure_business_category=failure_business_category,
        source_reject_reason=source_reject_reason,
        directionality=directionality,
        allow_multi_anchor_ambiguous=allow_multi_anchor_ambiguous,
    ):
        return None
    candidate_pairs = _candidate_pairs_for_retry(
        probe_result,
        include_all=allow_multi_anchor_ambiguous and failure_business_category == "multi_anchor_ambiguous",
    )
    if not candidate_pairs:
        return None
    require_segment_axis_alignment = allow_multi_anchor_ambiguous and failure_business_category == "multi_anchor_ambiguous"

    outcomes: dict[tuple[str, str], PairAnchorFormalRetryOutcome] = {}
    attempted: set[tuple[str, str]] = set()
    for candidate_pair in candidate_pairs:
        for oriented_pair in (candidate_pair, list(reversed(candidate_pair))):
            key = (oriented_pair[0], oriented_pair[1])
            if key in attempted:
                continue
            attempted.add(key)
            outcome = _try_oriented_pair(
                candidate_pair=oriented_pair,
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
                require_segment_axis_alignment=require_segment_axis_alignment,
            )
            if outcome is None:
                continue
            outcomes[key] = outcome
    if len(outcomes) != 1:
        return None
    return next(iter(outcomes.values()))


def _eligible(
    *,
    probe_result: BufferOnlyProbeResult,
    failure_business_category: str,
    source_reject_reason: str,
    directionality: str,
    allow_multi_anchor_ambiguous: bool,
) -> bool:
    if directionality != "single":
        return False
    if failure_business_category == "pair_anchor_mismatch":
        if source_reject_reason != "required_semantic_nodes_not_connected_in_buffer":
            return False
        if probe_result.manual_review_required:
            return False
        return probe_result.repair_recommendation == "high_confidence_pair_anchor_candidate"
    if failure_business_category == "directionality_mismatch_fixable":
        if source_reject_reason != "rcsd_directed_path_missing":
            return False
        if probe_result.status not in {"corridor_found", "corridor_found_with_anchor_mismatch"}:
            return False
        if probe_result.manual_review_required:
            return False
        if probe_result.repair_recommendation != "high_confidence_pair_anchor_candidate":
            return False
        return probe_result.directionality_score >= 1.0 and probe_result.connectivity_score >= 1.0
    if not allow_multi_anchor_ambiguous or failure_business_category != "multi_anchor_ambiguous":
        return False
    if source_reject_reason not in {"invalid_pair_relation_status", "invalid_pair_base_id", "missing_pair_relation"}:
        return False
    if probe_result.status != "ambiguous_corridor":
        return False
    if probe_result.candidate_score < 0.95 or probe_result.geometry_overlap_ratio < 0.85:
        return False
    if probe_result.directionality_score < 1.0 or probe_result.connectivity_score < 1.0:
        return False
    return probe_result.shape_similarity_score >= 0.95


def _candidate_pairs_for_retry(probe_result: BufferOnlyProbeResult, *, include_all: bool) -> list[list[str]]:
    values = probe_result.candidate_pair_sets if include_all else probe_result.candidate_pair_sets[:1]
    result: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        pair = [str(item) for item in value]
        if len(pair) != 2 or len(set(pair)) != 2:
            continue
        key = (pair[0], pair[1])
        if key in seen:
            continue
        seen.add(key)
        result.append(pair)
    return result


def _try_oriented_pair(
    *,
    candidate_pair: list[str],
    pair_nodes: list[str],
    relation_junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    relation_map: dict[str, RelationRecord],
    segment_geometry: BaseGeometry | None,
    sgrade: Any,
    directionality: str,
    directed_swsd_pair_nodes: list[str],
    buffer_extractor: BufferSegmentExtractor,
    graph_retry: SingleGraphConnectivityRetry,
    buffer_config: BufferExtractionConfig,
    all_base_ids_for_segment: set[str],
    unexpected_base_ids_for_segment: set[str],
    rcsd_graph_edges: list[tuple[str, str, str, int | None]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    max_path_to_swsd_length_ratio: float,
    require_segment_axis_alignment: bool = False,
) -> PairAnchorFormalRetryOutcome | None:
    candidate_relation = _candidate_relation(
        candidate_pair=candidate_pair,
        relation_junc_nodes=relation_junc_nodes,
        relation_map=relation_map,
    )
    directed_rcsd_pair_nodes = _map_directed_swsd_pair_to_rcsd(
        pair_nodes=pair_nodes,
        rcsd_pair_nodes=candidate_relation.rcsd_pair_nodes,
        directed_swsd_pair_nodes=directed_swsd_pair_nodes,
    )
    if len(directed_rcsd_pair_nodes) != 2:
        return None
    if require_segment_axis_alignment and not _oriented_pair_matches_segment_axis(
        candidate_pair=candidate_relation.rcsd_pair_nodes,
        pair_nodes=pair_nodes,
        directed_swsd_pair_nodes=directed_swsd_pair_nodes,
        segment_geometry=segment_geometry,
        directionality=directionality,
        buffer_extractor=buffer_extractor,
    ):
        return None

    optional_allowed = _optional_allowed_rcsd_nodes(
        relation=candidate_relation,
        relation_junc_nodes=relation_junc_nodes,
        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
        relation_map=relation_map,
    )
    result = buffer_extractor.extract(
        segment_geometry=segment_geometry,
        relation=candidate_relation,
        optional_allowed_rcsd_nodes=optional_allowed,
        all_relation_base_ids=all_base_ids_for_segment,
        unexpected_relation_base_ids=unexpected_base_ids_for_segment,
        directed_pair_nodes=directed_rcsd_pair_nodes,
        require_directed_pair=True,
        require_bidirectional=False,
        config=buffer_config,
    )
    diagnostic = buffer_failure_diagnostic(
        result=result,
        directionality=directionality,
        rcsd_pair_nodes=candidate_relation.rcsd_pair_nodes,
        rcsd_graph_edges=rcsd_graph_edges,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    if result.ok:
        return PairAnchorFormalRetryOutcome(candidate_relation, result, diagnostic)

    graph_outcome = graph_retry.retry(
        segment_geometry=segment_geometry,
        relation=candidate_relation,
        optional_allowed_rcsd_nodes=optional_allowed,
        unexpected_relation_base_ids=unexpected_base_ids_for_segment,
        directed_pair_nodes=directed_rcsd_pair_nodes,
        sgrade=sgrade,
        directionality=directionality,
        buffer_result=result,
        diagnostic=diagnostic,
        config=buffer_config,
        max_path_to_swsd_length_ratio=max_path_to_swsd_length_ratio,
    )
    if graph_outcome is None:
        return None
    return _graph_outcome(candidate_relation, diagnostic, graph_outcome)


def _oriented_pair_matches_segment_axis(
    *,
    candidate_pair: list[str],
    pair_nodes: list[str],
    directed_swsd_pair_nodes: list[str],
    segment_geometry: BaseGeometry | None,
    directionality: str,
    buffer_extractor: BufferSegmentExtractor,
) -> bool:
    if directionality != "single" or segment_geometry is None or segment_geometry.is_empty:
        return True
    if len(candidate_pair) != 2 or len(pair_nodes) != 2 or len(directed_swsd_pair_nodes) != 2:
        return True
    if directed_swsd_pair_nodes == pair_nodes:
        expected_forward = True
    elif directed_swsd_pair_nodes == list(reversed(pair_nodes)):
        expected_forward = False
    else:
        return True

    node_geometries = _buffer_extractor_node_geometries(buffer_extractor)
    source_geometry = node_geometries.get(candidate_pair[0])
    target_geometry = node_geometries.get(candidate_pair[1])
    if source_geometry is None or target_geometry is None:
        return True
    try:
        source_measure = float(segment_geometry.project(source_geometry))
        target_measure = float(segment_geometry.project(target_geometry))
    except Exception:
        return True
    tolerance = max(1.0, min(10.0, float(segment_geometry.length or 0.0) * 0.02))
    if abs(source_measure - target_measure) <= tolerance:
        return True
    return source_measure < target_measure if expected_forward else source_measure > target_measure


def _buffer_extractor_node_geometries(buffer_extractor: BufferSegmentExtractor) -> dict[str, BaseGeometry]:
    node_index = getattr(buffer_extractor, "node_index", None)
    features = getattr(node_index, "features", None)
    canonicalizer = getattr(buffer_extractor, "node_canonicalizer", None)
    if not features or canonicalizer is None:
        return {}
    result: dict[str, BaseGeometry] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry")
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty:
            continue
        node_id = props.get("id")
        if node_id is None:
            continue
        result.setdefault(canonicalizer.canonicalize(node_id), geometry)
    return result


def _graph_outcome(
    relation: RelationCheck,
    diagnostic: dict[str, Any],
    graph_outcome: SingleGraphConnectivityRetryOutcome,
) -> PairAnchorFormalRetryOutcome:
    return PairAnchorFormalRetryOutcome(
        relation=relation,
        buffer_result=graph_outcome.buffer_result,
        diagnostic=diagnostic,
        adaptive_distance_m=graph_outcome.reference_distance_m,
        adaptive_source_reason=graph_outcome.source_reason,
    )


def _candidate_relation(
    *,
    candidate_pair: list[str],
    relation_junc_nodes: list[str],
    relation_map: dict[str, RelationRecord],
) -> RelationCheck:
    failed_junc_nodes, failed_junc_reasons = _failed_relation_nodes(relation_junc_nodes, relation_map)
    return RelationCheck(
        True,
        candidate_pair,
        _accepted_base_ids_for_nodes_ordered(relation_junc_nodes, relation_map),
        failed_junc_nodes=failed_junc_nodes,
        failed_junc_reasons=failed_junc_reasons,
    )


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


def _optional_allowed_rcsd_nodes(
    *,
    relation: RelationCheck,
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
