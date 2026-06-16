from __future__ import annotations

from typing import Any

from shapely.geometry.base import BaseGeometry

from .buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentExtractor,
    BufferSegmentResult,
    _build_undirected_graph,
    _edge_geometry,
    _nodes_from_edges,
    _shortest_directed_path_covering_nodes,
)
from .graph_builders import Edge, NodeCanonicalizer
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list, unique_preserve_order
from .relation_mapping import RelationCheck, RelationRecord
from .schemas import feature

GROUP_AUDIT_FAILURE_CATEGORIES = {"directionality_mismatch_fixable", "pair_anchor_mismatch"}
GROUP_AUDIT_REJECT_REASONS = {
    "rcsd_not_bidirectional_for_swsd_dual",
    "required_semantic_nodes_not_connected_in_buffer",
    "rcsd_directed_path_missing",
}
PATH_CORRIDOR_NARROW_BUFFER_M = 15.0
PATH_CORRIDOR_WIDE_BUFFER_M = 50.0
PATH_CORRIDOR_MIN_NARROW_OVERLAP_RATIO = 0.5
PATH_CORRIDOR_MIN_WIDE_OVERLAP_RATIO = 0.75
GROUP_PROBE_BUFFER_DISTANCES_M = (50.0, 75.0, 100.0, 150.0)


def build_group_replacement_audit_rows(
    *,
    fusion_units: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    relation_map: dict[str, RelationRecord],
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]] | None = None,
    rcsd_node_canonicalizer: NodeCanonicalizer,
    replaceable_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
    buffer_config: BufferExtractionConfig | None = None,
) -> list[dict[str, Any]]:
    segment_by_id = _index_features(segments)
    fusion_segment_ids = {_feature_id(row) for row in fusion_units if _feature_id(row)}
    replaceable_segment_ids = {
        str((row.get("properties") or {}).get("swsd_segment_id"))
        for row in replaceable_rows
        if (row.get("properties") or {}).get("swsd_segment_id") is not None
    }
    rejected_reason_by_segment = _rejected_reason_by_segment(rejected_rows)
    node_to_segments = _node_to_segments(segment_by_id)
    base_to_targets = _accepted_base_to_targets(relation_map, rcsd_node_canonicalizer)
    relation_base_ids = set(base_to_targets)
    graph_edges = _build_undirected_graph(rcsd_roads, node_canonicalizer=rcsd_node_canonicalizer).edges
    edge_by_id = {edge.edge_id: edge for edge in graph_edges}
    group_probe_extractor = (
        BufferSegmentExtractor(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_nodes)
        if rcsd_nodes is not None
        else None
    )

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for audit in failure_business_audit_rows:
        props = dict(audit.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id or segment_id in seen:
            continue
        if not _is_group_audit_candidate(props):
            continue
        seen.add(segment_id)
        segment = segment_by_id.get(segment_id)
        segment_props = dict(segment.get("properties") or {}) if segment is not None else {}
        pair_nodes = _parse_list(props.get("swsd_pair_nodes") or segment_props.get("pair_nodes"))
        junc_nodes = _parse_list(props.get("swsd_junc_nodes") or segment_props.get("junc_nodes"))
        junc_kind2_exempt_nodes = _parse_list(props.get("junc_kind2_exempt_nodes") or segment_props.get("junc_kind2_exempt_nodes"))
        rcsd_pair_nodes = _canonical_ids(_parse_list(props.get("rcsd_pair_nodes") or props.get("original_rcsd_pair_nodes")), rcsd_node_canonicalizer)
        allowed_base_ids = _allowed_base_ids(
            swsd_node_ids=unique_preserve_order([*pair_nodes, *junc_nodes, *junc_kind2_exempt_nodes]),
            relation_map=relation_map,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
        allowed_base_ids.update(rcsd_pair_nodes)
        path_infos = _path_infos(
            graph_edges=graph_edges,
            edge_by_id=edge_by_id,
            required_nodes=rcsd_pair_nodes,
            segment_geometry=segment.get("geometry") if segment is not None else None,
        )
        path_node_ids = unique_preserve_order(node_id for info in path_infos for node_id in info["node_ids"])
        unexpected_rcsd_nodes = [node_id for node_id in path_node_ids if node_id in relation_base_ids and node_id not in allowed_base_ids]
        unexpected_targets = unique_preserve_order(
            target_id
            for node_id in unexpected_rcsd_nodes
            for target_id in base_to_targets.get(node_id, [])
            if target_id not in set([*pair_nodes, *junc_nodes, *junc_kind2_exempt_nodes])
        )
        incident_segment_ids = _incident_segments(
            seed_nodes=unexpected_targets,
            node_to_segments=node_to_segments,
            current_segment_id=segment_id,
        )
        group_segment_ids = unique_preserve_order([segment_id, *incident_segment_ids])
        path_geometry = _path_geometry(path_infos)
        path_corridor_incident_segment_ids = _path_corridor_segments(
            segment_ids=incident_segment_ids,
            segment_by_id=segment_by_id,
            path_geometry=path_geometry,
        )
        path_corridor_segment_ids = unique_preserve_order([segment_id, *path_corridor_incident_segment_ids])
        side_incident_segment_ids = [sid for sid in incident_segment_ids if sid not in set(path_corridor_incident_segment_ids)]
        replaceable_in_group = [sid for sid in group_segment_ids if sid in replaceable_segment_ids]
        external_group_segment_ids = [sid for sid in group_segment_ids if sid != segment_id]
        rejected_in_group = [sid for sid in external_group_segment_ids if sid in rejected_reason_by_segment]
        outside_step1 = [sid for sid in external_group_segment_ids if sid not in fusion_segment_ids]
        path_corridor_external_segment_ids = [sid for sid in path_corridor_segment_ids if sid != segment_id]
        path_corridor_rejected = [sid for sid in path_corridor_external_segment_ids if sid in rejected_reason_by_segment]
        path_corridor_outside_step1 = [sid for sid in path_corridor_external_segment_ids if sid not in fusion_segment_ids]
        blocker_reasons = _blocker_reasons(rejected_in_group, outside_step1, rejected_reason_by_segment)
        path_corridor_blocker_reasons = _blocker_reasons(path_corridor_rejected, path_corridor_outside_step1, rejected_reason_by_segment)
        audit_status = _audit_status(path_infos, unexpected_targets, rejected_in_group, outside_step1)
        corridor_audit_status = _audit_status(path_infos, unexpected_targets, path_corridor_rejected, path_corridor_outside_step1)
        group_probe = _group_union_probe(
            extractor=group_probe_extractor,
            segment_ids=path_corridor_segment_ids,
            segment_by_id=segment_by_id,
            rcsd_pair_nodes=rcsd_pair_nodes,
            allowed_base_ids=allowed_base_ids,
            relation_base_ids=relation_base_ids,
            source_directionality=directionality_from_sgrade(segment_props.get("sgrade") or props.get("swsd_sgrade")) or "",
            buffer_config=buffer_config,
        )
        rows.append(
            feature(
                {
                    "swsd_segment_id": segment_id,
                    "audit_status": audit_status,
                    "corridor_audit_status": corridor_audit_status,
                    "source_reject_reason": props.get("reject_reason"),
                    "failure_business_category": props.get("failure_business_category"),
                    "swsd_sgrade": segment_props.get("sgrade") or props.get("swsd_sgrade"),
                    "swsd_directionality": directionality_from_sgrade(segment_props.get("sgrade") or props.get("swsd_sgrade")) or "",
                    "swsd_pair_nodes": pair_nodes,
                    "swsd_junc_nodes": junc_nodes,
                    "rcsd_pair_nodes": rcsd_pair_nodes,
                    "path_direction_count": len(path_infos),
                    "path_rcsd_road_ids": unique_preserve_order(road_id for info in path_infos for road_id in info["road_ids"]),
                    "path_rcsd_node_ids": path_node_ids,
                    "unexpected_mapped_rcsd_node_ids": unexpected_rcsd_nodes,
                    "unexpected_mapped_swsd_target_ids": unexpected_targets,
                    "unexpected_mapped_swsd_target_count": len(unexpected_targets),
                    "group_segment_ids": group_segment_ids,
                    "group_segment_count": len(group_segment_ids),
                    "replaceable_group_segment_ids": replaceable_in_group,
                    "rejected_group_segment_ids": rejected_in_group,
                    "outside_step1_group_segment_ids": outside_step1,
                    "blocked_group_segment_ids": unique_preserve_order([*rejected_in_group, *outside_step1]),
                    "blocker_reasons": blocker_reasons,
                    "path_corridor_group_segment_ids": path_corridor_segment_ids,
                    "path_corridor_group_segment_count": len(path_corridor_segment_ids),
                    "path_corridor_blocked_segment_ids": unique_preserve_order([*path_corridor_rejected, *path_corridor_outside_step1]),
                    "path_corridor_blocker_reasons": path_corridor_blocker_reasons,
                    "side_incident_group_segment_ids": side_incident_segment_ids,
                    "group_probe_status": group_probe["status"],
                    "group_probe_reason": group_probe["reason"],
                    "group_probe_buffer_distance_m": group_probe["buffer_distance_m"],
                    "group_probe_rcsd_road_ids": group_probe["rcsd_road_ids"],
                    "group_probe_rcsd_road_count": group_probe["rcsd_road_count"],
                    "group_probe_swsd_uncovered_ratio": group_probe["swsd_uncovered_ratio"],
                    "group_probe_rcsd_outside_ratio": group_probe["rcsd_outside_ratio"],
                    "group_probe_repair_owner": group_probe["repair_owner"],
                    "repair_recommendation": _repair_recommendation(audit_status, group_probe),
                    "notes": _notes(audit_status, group_probe),
                },
                path_geometry,
            )
        )
    return rows


def path_corridor_group_covered_segment_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: list[str] = []
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("group_probe_status") != "passed":
            continue
        if props.get("group_probe_repair_owner") != "T06_path_corridor_group_replacement":
            continue
        try:
            result.extend(parse_id_list(props.get("path_corridor_group_segment_ids"), allow_empty=True))
        except ParseError:
            continue
    return set(unique_preserve_order(result))


def _is_group_audit_candidate(props: dict[str, Any]) -> bool:
    if props.get("segment_outcome") != "rejected":
        return False
    if props.get("failure_business_category") in GROUP_AUDIT_FAILURE_CATEGORIES:
        return True
    return str(props.get("reject_reason") or "") in GROUP_AUDIT_REJECT_REASONS


def _path_infos(
    *,
    graph_edges: list[Edge],
    edge_by_id: dict[str, Edge],
    required_nodes: list[str],
    segment_geometry: BaseGeometry | None,
) -> list[dict[str, Any]]:
    if len(set(required_nodes)) != 2:
        return []
    source, target = required_nodes
    result: list[dict[str, Any]] = []
    for label, start, end in (("forward", source, target), ("reverse", target, source)):
        edge_ids = _shortest_directed_path_covering_nodes(
            graph_edges,
            start,
            end,
            required_nodes,
            reference_geometry=segment_geometry,
        )
        if not edge_ids:
            continue
        edges = [edge_by_id[edge_id] for edge_id in edge_ids if edge_id in edge_by_id]
        result.append(
            {
                "direction": label,
                "road_ids": unique_preserve_order(edge.road_id for edge in edges),
                "node_ids": sorted(_nodes_from_edges(edges)),
                "geometry": _edge_geometry(edges),
            }
        )
    return result


def _path_geometry(path_infos: list[dict[str, Any]]) -> BaseGeometry | None:
    edges = [info.get("geometry") for info in path_infos if isinstance(info.get("geometry"), BaseGeometry)]
    if not edges:
        return None
    from shapely.ops import unary_union

    return unary_union(edges)


def _path_corridor_segments(
    *,
    segment_ids: list[str],
    segment_by_id: dict[str, dict[str, Any]],
    path_geometry: BaseGeometry | None,
) -> list[str]:
    if path_geometry is None or path_geometry.is_empty:
        return []
    result: list[str] = []
    for segment_id in segment_ids:
        segment = segment_by_id.get(segment_id)
        geometry = segment.get("geometry") if segment is not None else None
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty:
            continue
        if _is_path_corridor_carrier(geometry, path_geometry):
            result.append(segment_id)
    return result


def _is_path_corridor_carrier(segment_geometry: BaseGeometry, path_geometry: BaseGeometry) -> bool:
    length = float(segment_geometry.length or 0.0)
    if length <= 0:
        return False
    narrow_ratio = segment_geometry.intersection(path_geometry.buffer(PATH_CORRIDOR_NARROW_BUFFER_M)).length / length
    wide_ratio = segment_geometry.intersection(path_geometry.buffer(PATH_CORRIDOR_WIDE_BUFFER_M)).length / length
    return (
        narrow_ratio >= PATH_CORRIDOR_MIN_NARROW_OVERLAP_RATIO
        or wide_ratio >= PATH_CORRIDOR_MIN_WIDE_OVERLAP_RATIO
    )


def _group_union_probe(
    *,
    extractor: BufferSegmentExtractor | None,
    segment_ids: list[str],
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_pair_nodes: list[str],
    allowed_base_ids: set[str],
    relation_base_ids: set[str],
    source_directionality: str,
    buffer_config: BufferExtractionConfig | None,
) -> dict[str, Any]:
    if extractor is None:
        return _group_probe_row("not_evaluated", "missing_rcsd_nodes_for_probe")
    if source_directionality != "dual":
        return _group_probe_row("not_applicable", "source_segment_not_dual")
    if len(set(rcsd_pair_nodes)) != 2:
        return _group_probe_row("not_evaluated", "invalid_rcsd_pair_nodes")
    geometries = [
        segment.get("geometry")
        for segment_id in segment_ids
        for segment in [segment_by_id.get(segment_id)]
        if isinstance((segment or {}).get("geometry"), BaseGeometry) and not (segment or {}).get("geometry").is_empty
    ]
    if not geometries:
        return _group_probe_row("not_evaluated", "missing_path_corridor_group_geometry")

    from shapely.ops import unary_union

    group_geometry = unary_union(geometries)
    optional_nodes = sorted(allowed_base_ids - set(rcsd_pair_nodes))
    last_result: BufferSegmentResult | None = None
    base_config = buffer_config or BufferExtractionConfig()
    for distance_m in GROUP_PROBE_BUFFER_DISTANCES_M:
        cfg = BufferExtractionConfig(
            buffer_distance_m=distance_m,
            min_road_overlap_ratio=base_config.min_road_overlap_ratio,
            min_road_overlap_length_m=base_config.min_road_overlap_length_m,
            advance_right_formway_bit=base_config.advance_right_formway_bit,
            max_geometry_buffer_mismatch_ratio=base_config.max_geometry_buffer_mismatch_ratio,
            min_geometry_buffer_mismatch_length_m=base_config.min_geometry_buffer_mismatch_length_m,
        )
        result = extractor.extract(
            segment_geometry=group_geometry,
            relation=RelationCheck(True, rcsd_pair_nodes, optional_nodes, failed_junc_nodes=[], failed_junc_reasons={}),
            optional_allowed_rcsd_nodes=optional_nodes,
            all_relation_base_ids=relation_base_ids,
            unexpected_relation_base_ids=set(),
            directed_pair_nodes=[],
            require_directed_pair=False,
            require_bidirectional=True,
            config=cfg,
        )
        last_result = result
        if result.ok:
            return _group_probe_row(
                "passed",
                result.reason,
                buffer_distance_m=distance_m,
                result=result,
                repair_owner="T06_path_corridor_group_replacement",
            )
    return _group_probe_row(
        "failed",
        last_result.reason if last_result is not None else "no_probe_result",
        buffer_distance_m=GROUP_PROBE_BUFFER_DISTANCES_M[-1],
        result=last_result,
        repair_owner="upstream_anchor_or_rcsd_data_required",
    )


def _group_probe_row(
    status: str,
    reason: str,
    *,
    buffer_distance_m: float | None = None,
    result: BufferSegmentResult | None = None,
    repair_owner: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "buffer_distance_m": buffer_distance_m,
        "rcsd_road_ids": result.retained_road_ids if result is not None else [],
        "rcsd_road_count": len(result.retained_road_ids) if result is not None else 0,
        "swsd_uncovered_ratio": result.swsd_uncovered_by_rcsd_ratio if result is not None else None,
        "rcsd_outside_ratio": result.rcsd_outside_swsd_buffer_ratio if result is not None else None,
        "repair_owner": repair_owner,
    }


def _accepted_base_to_targets(
    relation_map: dict[str, RelationRecord],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for target_id, relation in relation_map.items():
        if relation.status != 0 or relation.base_id <= 0:
            continue
        try:
            base_id = rcsd_node_canonicalizer.canonicalize(str(relation.base_id))
        except ParseError:
            base_id = str(relation.base_id)
        result.setdefault(base_id, []).append(str(target_id))
    return {base_id: unique_preserve_order(targets) for base_id, targets in result.items()}


def _allowed_base_ids(
    *,
    swsd_node_ids: list[str],
    relation_map: dict[str, RelationRecord],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> set[str]:
    result: set[str] = set()
    for node_id in swsd_node_ids:
        relation = relation_map.get(node_id)
        if relation is None or relation.status != 0 or relation.base_id <= 0:
            continue
        try:
            result.add(rcsd_node_canonicalizer.canonicalize(str(relation.base_id)))
        except ParseError:
            result.add(str(relation.base_id))
    return result


def _incident_segments(
    *,
    seed_nodes: list[str],
    node_to_segments: dict[str, list[str]],
    current_segment_id: str,
) -> list[str]:
    result: list[str] = []
    for node_id in seed_nodes:
        for segment_id in node_to_segments.get(node_id, []):
            if segment_id == current_segment_id or segment_id in result:
                continue
            result.append(segment_id)
    return result


def _node_to_segments(segment_by_id: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for segment_id, segment in segment_by_id.items():
        props = dict(segment.get("properties") or {})
        for node_id in unique_preserve_order([*_parse_list(props.get("pair_nodes")), *_parse_list(props.get("junc_nodes"))]):
            result.setdefault(node_id, []).append(segment_id)
    return result


def _rejected_reason_by_segment(rejected_rows: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rejected_rows:
        props = dict(row.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or "")
        if segment_id:
            result[segment_id] = str(props.get("reject_reason") or "")
    return result


def _blocker_reasons(
    rejected_segment_ids: list[str],
    outside_step1_segment_ids: list[str],
    rejected_reason_by_segment: dict[str, str],
) -> list[str]:
    values = [f"{segment_id}:{rejected_reason_by_segment.get(segment_id, '')}" for segment_id in rejected_segment_ids]
    values.extend(f"{segment_id}:outside_step1_fusion_scope" for segment_id in outside_step1_segment_ids)
    return unique_preserve_order(values)


def _audit_status(
    path_infos: list[dict[str, Any]],
    unexpected_targets: list[str],
    rejected_segment_ids: list[str],
    outside_step1_segment_ids: list[str],
) -> str:
    if not path_infos:
        return "blocked_no_rcsd_graph_path"
    if not unexpected_targets:
        return "not_group_required_no_external_anchor"
    if rejected_segment_ids or outside_step1_segment_ids:
        return "blocked_group_closure_incomplete"
    return "candidate_group_closure_ready"


def _repair_recommendation(audit_status: str, group_probe: dict[str, Any] | None = None) -> str:
    probe_status = str((group_probe or {}).get("status") or "")
    probe_reason = str((group_probe or {}).get("reason") or "")
    if probe_status == "passed":
        return "t06_group_replacement_candidate"
    if probe_status == "failed" and probe_reason in {
        "rcsd_not_bidirectional_for_swsd_dual",
        "rcsd_directed_path_missing",
    }:
        return "upstream_anchor_or_rcsd_directionality_required"
    if probe_status == "failed":
        return "upstream_anchor_or_rcsd_data_required"
    if audit_status == "candidate_group_closure_ready":
        return "t06_group_replacement_candidate"
    if audit_status == "blocked_group_closure_incomplete":
        return "upstream_anchor_or_step1_group_scope_required"
    if audit_status == "not_group_required_no_external_anchor":
        return "not_applicable"
    return "manual_review_required"


def _notes(audit_status: str, group_probe: dict[str, Any] | None = None) -> str:
    probe_status = str((group_probe or {}).get("status") or "")
    probe_reason = str((group_probe or {}).get("reason") or "")
    if probe_status == "passed":
        return "path-corridor group union passed formal extractor probe and can be consumed by Step3 group replacement"
    if probe_status == "failed" and probe_reason in {
        "rcsd_not_bidirectional_for_swsd_dual",
        "rcsd_directed_path_missing",
    }:
        return "path-corridor group formal probe still cannot build the required directed/bidirectional RCSD Segment; review upstream anchor grouping and RCSD directionality/data"
    if probe_status == "failed":
        return "path-corridor group formal probe failed; review upstream anchor grouping, RCSD coverage, and source data completeness"
    if audit_status == "candidate_group_closure_ready":
        return "all incident SWSD Segment carriers are already replaceable in Step2; group replacement can be evaluated as a separate policy"
    if audit_status == "blocked_group_closure_incomplete":
        return "RCSD path crosses external accepted anchors, but some incident SWSD Segment carriers are rejected or outside Step1 fusion scope"
    if audit_status == "not_group_required_no_external_anchor":
        return "RCSD graph path does not cross an external accepted SWSD anchor"
    return "RCSD graph path could not be reconstructed from current inputs"


def _index_features(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        item_id = _feature_id(item)
        if item_id:
            result[item_id] = item
    return result


def _feature_id(item: dict[str, Any]) -> str:
    props = dict(item.get("properties") or {})
    try:
        return normalize_id(props.get("swsd_segment_id") or props.get("id"))
    except ParseError:
        return ""


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _canonical_ids(values: list[str], canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    for value in values:
        try:
            result.append(canonicalizer.canonicalize(value))
        except ParseError:
            continue
    return unique_preserve_order(result)
