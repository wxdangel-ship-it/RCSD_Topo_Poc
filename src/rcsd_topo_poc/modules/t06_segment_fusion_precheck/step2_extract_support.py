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
        visual_consistency_buffer_distance_m=config.visual_consistency_buffer_distance_m,
        max_visual_consistency_mismatch_ratio=config.max_visual_consistency_mismatch_ratio,
        min_visual_consistency_mismatch_length_m=config.min_visual_consistency_mismatch_length_m,
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
    if reason in {
        "retained_geometry_outside_swsd_buffer_scope",
        "swsd_geometry_not_covered_by_retained_rcsd",
        "retained_geometry_outside_swsd_visual_consistency_scope",
        "swsd_visual_continuity_not_covered_by_retained_rcsd",
    }:
        return "geometry_shape_mismatch"
    if diagnostic.get("full_graph_status") == "required_nodes_connected":
        return "rcsd_graph_break_inside_buffer"
    return "evidence_slice_incomplete"


def _adaptive_buffer_recommendation(directionality: str) -> str:
    if directionality == "dual":
        return "adaptive_high_grade_dual_buffer_retry"
    return "single_graph_first_longitudinal_retry"


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


def _order_swsd_junc_nodes_by_connectivity(
    *,
    pair_nodes: list[str],
    junc_nodes: list[str],
    road_ids: list[str],
    swsd_roads: dict[str, dict[str, Any]],
    swsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    if len(pair_nodes) != 2 or len(junc_nodes) <= 1 or not road_ids:
        return junc_nodes
    adjacency: dict[str, set[str]] = defaultdict(set)
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
        adjacency[source].add(target)
        adjacency[target].add(source)
    try:
        source = swsd_node_canonicalizer.canonicalize(pair_nodes[0])
        target = swsd_node_canonicalizer.canonicalize(pair_nodes[1])
        junc_canonical = [swsd_node_canonicalizer.canonicalize(node_id) for node_id in junc_nodes]
    except ParseError:
        return junc_nodes
    path = _shortest_node_path(adjacency, source, target)
    if not path:
        return junc_nodes
    path_index = {node_id: index for index, node_id in enumerate(path)}
    if any(node_id not in path_index for node_id in junc_canonical):
        return junc_nodes
    return [
        node_id
        for _index, node_id in sorted(
            ((path_index[canonical], node_id) for node_id, canonical in zip(junc_nodes, junc_canonical)),
            key=lambda item: item[0],
        )
    ]


def _shortest_node_path(adjacency: dict[str, set[str]], source: str, target: str) -> list[str]:
    seen = {source}
    previous: dict[str, str] = {}
    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        if node == target:
            break
        for neighbor in sorted(adjacency.get(node, set())):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            previous[neighbor] = node
            queue.append(neighbor)
    if target not in seen:
        return []
    path = [target]
    node = target
    while node != source:
        node = previous.get(node, "")
        if not node:
            return []
        path.append(node)
    path.reverse()
    return path


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
    _ = relation, relation_junc_nodes
    return unique_preserve_order(
        [
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
