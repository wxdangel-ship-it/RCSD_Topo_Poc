from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from .buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentExtractor,
    BufferSegmentResult,
    _build_undirected_graph,
    _edge_direction,
    _edge_geometry,
    _edge_weight,
    _nodes_from_edges,
    _path_reference_buffer,
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
MAX_UNCOVERED_AUGMENTATION_ITERATIONS = 256


@dataclass(frozen=True)
class _RoadGeometryEntry:
    road_id: str
    geometry: BaseGeometry
    length: float


@dataclass(frozen=True)
class _RoadGeometryIndex:
    entries: tuple[_RoadGeometryEntry, ...]
    tree: STRtree | None
    geometry_index_by_id: dict[int, int]

    @classmethod
    def build(cls, rcsd_road_by_id: dict[str, dict[str, Any]]) -> "_RoadGeometryIndex":
        entries = tuple(_road_geometry_entries(rcsd_road_by_id))
        geometries = [entry.geometry for entry in entries]
        return cls(
            entries=entries,
            tree=STRtree(geometries) if geometries else None,
            geometry_index_by_id={id(geometry): index for index, geometry in enumerate(geometries)},
        )

    def query(self, geometry: BaseGeometry) -> tuple[_RoadGeometryEntry, ...]:
        if self.tree is None or geometry.is_empty:
            return ()
        result: list[_RoadGeometryEntry] = []
        for item in self.tree.query(geometry):
            index = _strtree_query_index(item, self.geometry_index_by_id)
            if index is None or index < 0 or index >= len(self.entries):
                continue
            result.append(self.entries[index])
        return tuple(result)


@dataclass(frozen=True)
class _DirectedStep:
    target: str
    edge: Edge


class _PathWeightContext:
    def __init__(self, reference_geometry: BaseGeometry | None, required_nodes: set[str]) -> None:
        self.reference_geometry = reference_geometry
        self.reference_geometry_empty = reference_geometry is None or reference_geometry.is_empty
        self.reference_buffer_geometry = _path_reference_buffer(reference_geometry)
        self.reference_buffer_bounds = self.reference_buffer_geometry.bounds if self.reference_buffer_geometry is not None else None
        self.required_nodes = required_nodes
        self._weight_by_edge_identity: dict[int, float] = {}

    def weight(self, edge: Edge) -> float:
        key = id(edge)
        cached = self._weight_by_edge_identity.get(key)
        if cached is not None:
            return cached
        weight = _edge_weight(
            edge,
            reference_geometry=self.reference_geometry,
            reference_geometry_empty=self.reference_geometry_empty,
            reference_buffer_geometry=self.reference_buffer_geometry,
            reference_buffer_bounds=self.reference_buffer_bounds,
            required_nodes=self.required_nodes,
        )
        self._weight_by_edge_identity[key] = weight
        return weight


@dataclass(frozen=True)
class _DirectedPathTopology:
    adjacency: dict[str, tuple[_DirectedStep, ...]]

    @classmethod
    def build(cls, edges: list[Edge]) -> "_DirectedPathTopology":
        adjacency: dict[str, list[_DirectedStep]] = {}
        for edge in edges:
            direction = _edge_direction(edge)
            if direction in {0, 1, 2}:
                adjacency.setdefault(edge.source, []).append(_DirectedStep(edge.target, edge))
            if direction in {0, 1, 3}:
                adjacency.setdefault(edge.target, []).append(_DirectedStep(edge.source, edge))
        return cls({node: tuple(steps) for node, steps in adjacency.items()})

    def shortest_path(
        self,
        source: str,
        target: str,
        *,
        weight_context: _PathWeightContext,
    ) -> list[str] | None:
        queue: list[tuple[float, int, str]] = []
        sequence = 0
        heapq.heappush(queue, (0.0, sequence, source))
        distances: dict[str, float] = {source: 0.0}
        previous: dict[str, tuple[str, str]] = {}

        while queue:
            distance, _sequence, node = heapq.heappop(queue)
            if distance > distances.get(node, float("inf")):
                continue
            if node == target:
                break
            for step in self.adjacency.get(node, ()):
                next_distance = distance + weight_context.weight(step.edge)
                if next_distance >= distances.get(step.target, float("inf")):
                    continue
                distances[step.target] = next_distance
                previous[step.target] = (node, step.edge.edge_id)
                sequence += 1
                heapq.heappush(queue, (next_distance, sequence, step.target))

        if target not in distances:
            return None

        path: list[str] = []
        node = target
        while node != source:
            prev = previous.get(node)
            if prev is None:
                return None
            node, edge_id = prev
            path.append(edge_id)
        path.reverse()
        return path


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
    replaceable_road_ids_by_segment = _replaceable_road_ids_by_segment(replaceable_rows)
    rejected_reason_by_segment = _rejected_reason_by_segment(rejected_rows)
    node_to_segments = _node_to_segments(segment_by_id)
    base_to_targets = _accepted_base_to_targets(relation_map, rcsd_node_canonicalizer)
    relation_base_ids = set(base_to_targets)
    graph_edges = _build_undirected_graph(rcsd_roads, node_canonicalizer=rcsd_node_canonicalizer).edges
    edge_by_id = {edge.edge_id: edge for edge in graph_edges}
    path_topology = _DirectedPathTopology.build(graph_edges)
    rcsd_road_by_id = _index_features(rcsd_roads)
    rcsd_road_index = _RoadGeometryIndex.build(rcsd_road_by_id)
    group_probe_extractor = (
        BufferSegmentExtractor(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_nodes)
        if rcsd_nodes is not None
        else None
    )
    group_probe_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

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
            path_topology=path_topology,
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
        source_path_corridor_blocked = (
            []
            if _is_source_path_corridor_carrier(
                segment=segment,
                path_geometry=path_geometry,
            )
            else [segment_id]
        )
        path_corridor_rejected = [sid for sid in path_corridor_external_segment_ids if sid in rejected_reason_by_segment]
        path_corridor_outside_step1 = [sid for sid in path_corridor_external_segment_ids if sid not in fusion_segment_ids]
        blocker_reasons = _blocker_reasons(rejected_in_group, outside_step1, rejected_reason_by_segment)
        path_corridor_blocker_reasons = unique_preserve_order(
            [
                *[f"{sid}:source_segment_not_path_corridor_carrier" for sid in source_path_corridor_blocked],
                *_blocker_reasons(path_corridor_rejected, path_corridor_outside_step1, rejected_reason_by_segment),
            ]
        )
        path_corridor_blocked_segment_ids = unique_preserve_order(
            [*source_path_corridor_blocked, *path_corridor_rejected, *path_corridor_outside_step1]
        )
        path_corridor_probe_segment_ids = [
            sid for sid in path_corridor_segment_ids if sid not in set(path_corridor_blocked_segment_ids)
        ]
        audit_status = _audit_status(path_infos, unexpected_targets, rejected_in_group, outside_step1)
        corridor_audit_status = _audit_status(path_infos, unexpected_targets, path_corridor_rejected, path_corridor_outside_step1)
        source_directionality = directionality_from_sgrade(segment_props.get("sgrade") or props.get("swsd_sgrade")) or ""
        if corridor_audit_status == "candidate_group_closure_ready":
            probe_key = _group_probe_cache_key(
                segment_ids=path_corridor_probe_segment_ids,
                rcsd_pair_nodes=rcsd_pair_nodes,
                allowed_base_ids=allowed_base_ids,
                source_directionality=source_directionality,
                buffer_config=buffer_config,
            )
            cached_probe = group_probe_cache.get(probe_key)
            if cached_probe is None:
                group_probe = _group_union_probe(
                    extractor=group_probe_extractor,
                    segment_ids=path_corridor_probe_segment_ids,
                    segment_by_id=segment_by_id,
                    rcsd_pair_nodes=rcsd_pair_nodes,
                    allowed_base_ids=allowed_base_ids,
                    relation_base_ids=relation_base_ids,
                    source_directionality=source_directionality,
                    buffer_config=buffer_config,
                    replaceable_road_ids_by_segment=replaceable_road_ids_by_segment,
                    rcsd_road_by_id=rcsd_road_by_id,
                    rcsd_road_index=rcsd_road_index,
                )
                group_probe_cache[probe_key] = _clone_group_probe(group_probe)
            else:
                group_probe = _clone_group_probe(cached_probe)
        else:
            group_probe = _group_probe_row(
                "not_evaluated",
                f"{corridor_audit_status}_not_probeable",
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
                    "path_corridor_blocked_segment_ids": path_corridor_blocked_segment_ids,
                    "path_corridor_blocker_reasons": path_corridor_blocker_reasons,
                    "path_corridor_probe_segment_ids": path_corridor_probe_segment_ids,
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
            group_segment_ids = parse_id_list(props.get("path_corridor_group_segment_ids"), allow_empty=True)
            blocked_segment_ids = set(parse_id_list(props.get("path_corridor_blocked_segment_ids"), allow_empty=True))
            result.extend(segment_id for segment_id in group_segment_ids if segment_id not in blocked_segment_ids)
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
    path_topology: _DirectedPathTopology,
    edge_by_id: dict[str, Edge],
    required_nodes: list[str],
    segment_geometry: BaseGeometry | None,
) -> list[dict[str, Any]]:
    if len(set(required_nodes)) != 2:
        return []
    source, target = required_nodes
    weight_context = _PathWeightContext(segment_geometry, set(required_nodes))
    result: list[dict[str, Any]] = []
    for label, start, end in (("forward", source, target), ("reverse", target, source)):
        edge_ids = path_topology.shortest_path(start, end, weight_context=weight_context)
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


def _is_source_path_corridor_carrier(
    *,
    segment: dict[str, Any] | None,
    path_geometry: BaseGeometry | None,
) -> bool:
    if path_geometry is None or path_geometry.is_empty:
        return False
    geometry = (segment or {}).get("geometry")
    if not isinstance(geometry, BaseGeometry) or geometry.is_empty:
        return False
    return _is_path_corridor_carrier(geometry, path_geometry)


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
    replaceable_road_ids_by_segment: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_index: _RoadGeometryIndex,
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
            visual_consistency_buffer_distance_m=base_config.visual_consistency_buffer_distance_m,
            max_visual_consistency_mismatch_ratio=base_config.max_visual_consistency_mismatch_ratio,
            min_visual_consistency_mismatch_length_m=base_config.min_visual_consistency_mismatch_length_m,
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
            road_ids = _augment_probe_with_uncovered_segment_geometry(
                result.retained_road_ids,
                segment_ids=segment_ids,
                segment_by_id=segment_by_id,
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_road_index=rcsd_road_index,
            )
            return _group_probe_row(
                "passed",
                result.reason,
                buffer_distance_m=distance_m,
                result=result,
                repair_owner="T06_path_corridor_group_replacement",
                rcsd_road_ids=road_ids,
            )
        augmented_probe = _augmented_standard_replacement_probe(
            result=result,
            segment_ids=segment_ids,
            group_geometry=group_geometry,
            replaceable_road_ids_by_segment=replaceable_road_ids_by_segment,
            rcsd_road_by_id=rcsd_road_by_id,
            config=cfg,
        )
        if augmented_probe is not None:
            road_ids = _augment_probe_with_uncovered_segment_geometry(
                augmented_probe["rcsd_road_ids"],
                segment_ids=segment_ids,
                segment_by_id=segment_by_id,
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_road_index=rcsd_road_index,
            )
            augmented_probe["rcsd_road_ids"] = road_ids
            augmented_probe["rcsd_road_count"] = len(road_ids)
            return augmented_probe
    return _group_probe_row(
        "failed",
        last_result.reason if last_result is not None else "no_probe_result",
        buffer_distance_m=GROUP_PROBE_BUFFER_DISTANCES_M[-1],
        result=last_result,
        repair_owner="upstream_anchor_or_rcsd_data_required",
    )


def _augment_probe_with_uncovered_segment_geometry(
    retained_road_ids: list[str],
    *,
    segment_ids: list[str],
    segment_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_index: _RoadGeometryIndex,
    coverage_buffer_m: float = 5.0,
    candidate_buffer_m: float = 8.0,
    segment_max_uncovered_ratio: float = 0.02,
    segment_min_uncovered_length_m: float = 20.0,
    candidate_min_overlap_length_m: float = 8.0,
    candidate_min_inside_ratio: float = 0.4,
    max_augmentation_iterations: int = MAX_UNCOVERED_AUGMENTATION_ITERATIONS,
) -> list[str]:
    current_ids = unique_preserve_order(retained_road_ids)
    if not current_ids:
        return current_ids

    for _ in range(max_augmentation_iterations):
        selected_geometry = _road_union(current_ids, rcsd_road_by_id)
        if selected_geometry is None or selected_geometry.is_empty:
            return current_ids
        worst = _worst_uncovered_segment(
            segment_ids=segment_ids,
            segment_by_id=segment_by_id,
            selected_geometry=selected_geometry,
            coverage_buffer_m=coverage_buffer_m,
        )
        if worst is None:
            return current_ids
        ratio, uncovered_geometry = worst
        if ratio <= segment_max_uncovered_ratio or uncovered_geometry.length <= segment_min_uncovered_length_m:
            return current_ids
        candidate_id = _best_uncovered_segment_candidate(
            uncovered_geometry,
            current_ids=set(current_ids),
            rcsd_road_index=rcsd_road_index,
            candidate_buffer_m=candidate_buffer_m,
            candidate_min_overlap_length_m=candidate_min_overlap_length_m,
            candidate_min_inside_ratio=candidate_min_inside_ratio,
        )
        if candidate_id is None:
            return current_ids
        current_ids.append(candidate_id)
    return current_ids


def _road_union(road_ids: list[str], rcsd_road_by_id: dict[str, dict[str, Any]]) -> BaseGeometry | None:
    geometries = [
        geometry
        for road_id in road_ids
        for road in [rcsd_road_by_id.get(str(road_id))]
        for geometry in [road.get("geometry") if road is not None else None]
        if isinstance(geometry, BaseGeometry) and not geometry.is_empty
    ]
    if not geometries:
        return None
    from shapely.ops import unary_union

    return unary_union(geometries)


def _worst_uncovered_segment(
    *,
    segment_ids: list[str],
    segment_by_id: dict[str, dict[str, Any]],
    selected_geometry: BaseGeometry,
    coverage_buffer_m: float,
) -> tuple[float, BaseGeometry] | None:
    worst: tuple[float, BaseGeometry] | None = None
    selected_buffer = selected_geometry.buffer(coverage_buffer_m)
    for segment_id in segment_ids:
        segment = segment_by_id.get(segment_id)
        geometry = segment.get("geometry") if segment is not None else None
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty or geometry.length <= 0:
            continue
        uncovered = geometry.difference(selected_buffer)
        ratio = float(uncovered.length) / float(geometry.length)
        if worst is None or ratio > worst[0]:
            worst = (ratio, uncovered)
    return worst


def _best_uncovered_segment_candidate(
    uncovered_geometry: BaseGeometry,
    *,
    current_ids: set[str],
    rcsd_road_index: _RoadGeometryIndex,
    candidate_buffer_m: float,
    candidate_min_overlap_length_m: float,
    candidate_min_inside_ratio: float,
) -> str | None:
    best: tuple[float, float, float, str] | None = None
    candidate_scope = uncovered_geometry.buffer(candidate_buffer_m)
    if candidate_scope.is_empty:
        return None
    for entry in rcsd_road_index.query(candidate_scope):
        road_id = entry.road_id
        if road_id in current_ids:
            continue
        geometry = entry.geometry
        if not geometry.intersects(candidate_scope):
            continue
        overlap = float(geometry.intersection(candidate_scope).length)
        inside_ratio = overlap / entry.length
        if overlap < candidate_min_overlap_length_m or inside_ratio < candidate_min_inside_ratio:
            continue
        score = (overlap, inside_ratio, entry.length, road_id)
        if best is None or score > best:
            best = score
    return best[3] if best is not None else None


def _augmented_standard_replacement_probe(
    *,
    result: BufferSegmentResult,
    segment_ids: list[str],
    group_geometry: BaseGeometry,
    replaceable_road_ids_by_segment: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    config: BufferExtractionConfig,
) -> dict[str, Any] | None:
    if result.reason not in {
        "swsd_geometry_not_covered_by_retained_rcsd",
        "swsd_visual_continuity_not_covered_by_retained_rcsd",
        "retained_geometry_outside_swsd_buffer_scope",
        "retained_geometry_outside_swsd_visual_consistency_scope",
    }:
        return None
    standard_road_ids = unique_preserve_order(
        road_id
        for segment_id in segment_ids
        for road_id in replaceable_road_ids_by_segment.get(segment_id, [])
    )
    augmented_road_ids = unique_preserve_order([*result.retained_road_ids, *standard_road_ids])
    if not result.retained_road_ids or len(augmented_road_ids) <= len(result.retained_road_ids):
        return None

    road_geometries: list[BaseGeometry] = []
    for road_id in augmented_road_ids:
        road = rcsd_road_by_id.get(str(road_id))
        geometry = road.get("geometry") if road is not None else None
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty:
            return None
        road_geometries.append(geometry)

    coverage = _augmented_coverage_status(
        road_geometries=road_geometries,
        group_geometry=group_geometry,
        config=config,
        visual_scope="visual" in result.reason,
    )
    if coverage["issue"] is not None and coverage["issue"] != "swsd_visual_continuity_not_covered_by_retained_rcsd":
        return None
    return _group_probe_row(
        "passed",
        "augmented_standard_replacement_coverage_passed",
        buffer_distance_m=config.buffer_distance_m,
        result=result,
        repair_owner="T06_path_corridor_group_replacement",
        rcsd_road_ids=augmented_road_ids,
        swsd_uncovered_ratio=coverage["swsd_uncovered_ratio"],
        rcsd_outside_ratio=coverage["rcsd_outside_ratio"],
    )


def _augmented_coverage_status(
    *,
    road_geometries: list[BaseGeometry],
    group_geometry: BaseGeometry,
    config: BufferExtractionConfig,
    visual_scope: bool,
) -> dict[str, float | str | None]:
    from shapely.ops import unary_union

    road_geometry = unary_union(road_geometries)
    buffer_distance = config.buffer_distance_m
    max_mismatch_ratio = config.max_geometry_buffer_mismatch_ratio
    min_mismatch_length_m = config.min_geometry_buffer_mismatch_length_m
    if visual_scope and config.visual_consistency_buffer_distance_m is not None:
        buffer_distance = config.visual_consistency_buffer_distance_m
        max_mismatch_ratio = config.max_visual_consistency_mismatch_ratio
        min_mismatch_length_m = config.min_visual_consistency_mismatch_length_m

    road_length = float(road_geometry.length) if not road_geometry.is_empty else 0.0
    group_length = float(group_geometry.length) if not group_geometry.is_empty else 0.0
    rcsd_outside_length = (
        float(road_geometry.difference(group_geometry.buffer(buffer_distance)).length)
        if road_length > 0
        else 0.0
    )
    swsd_uncovered_length = (
        float(group_geometry.difference(road_geometry.buffer(buffer_distance)).length)
        if road_length > 0 and group_length > 0
        else 0.0
    )
    rcsd_outside_ratio = rcsd_outside_length / road_length if road_length > 0 else 0.0
    swsd_uncovered_ratio = swsd_uncovered_length / group_length if group_length > 0 else 0.0
    issue = None
    if _mismatch_exceeds_threshold(
        rcsd_outside_length,
        rcsd_outside_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    ):
        issue = (
            "retained_geometry_outside_swsd_visual_consistency_scope"
            if visual_scope
            else "retained_geometry_outside_swsd_buffer_scope"
        )
    elif _mismatch_exceeds_threshold(
        swsd_uncovered_length,
        swsd_uncovered_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    ):
        issue = (
            "swsd_visual_continuity_not_covered_by_retained_rcsd"
            if visual_scope
            else "swsd_geometry_not_covered_by_retained_rcsd"
        )
    return {
        "issue": issue,
        "rcsd_outside_ratio": rcsd_outside_ratio,
        "swsd_uncovered_ratio": swsd_uncovered_ratio,
    }


def _mismatch_exceeds_threshold(
    mismatch_length: float,
    mismatch_ratio: float,
    *,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> bool:
    return mismatch_ratio > max_mismatch_ratio or mismatch_length > min_mismatch_length_m


def _group_probe_row(
    status: str,
    reason: str,
    *,
    buffer_distance_m: float | None = None,
    result: BufferSegmentResult | None = None,
    repair_owner: str = "",
    rcsd_road_ids: list[str] | None = None,
    swsd_uncovered_ratio: float | None = None,
    rcsd_outside_ratio: float | None = None,
) -> dict[str, Any]:
    retained_road_ids = rcsd_road_ids if rcsd_road_ids is not None else (result.retained_road_ids if result is not None else [])
    return {
        "status": status,
        "reason": reason,
        "buffer_distance_m": buffer_distance_m,
        "rcsd_road_ids": retained_road_ids,
        "rcsd_road_count": len(retained_road_ids),
        "swsd_uncovered_ratio": (
            swsd_uncovered_ratio
            if swsd_uncovered_ratio is not None
            else (result.swsd_uncovered_by_rcsd_ratio if result is not None else None)
        ),
        "rcsd_outside_ratio": (
            rcsd_outside_ratio
            if rcsd_outside_ratio is not None
            else (result.rcsd_outside_swsd_buffer_ratio if result is not None else None)
        ),
        "repair_owner": repair_owner,
    }


def _group_probe_cache_key(
    *,
    segment_ids: list[str],
    rcsd_pair_nodes: list[str],
    allowed_base_ids: set[str],
    source_directionality: str,
    buffer_config: BufferExtractionConfig | None,
) -> tuple[Any, ...]:
    cfg = buffer_config or BufferExtractionConfig()
    return (
        tuple(segment_ids),
        tuple(rcsd_pair_nodes),
        tuple(sorted(allowed_base_ids)),
        source_directionality,
        cfg.min_road_overlap_ratio,
        cfg.min_road_overlap_length_m,
        cfg.advance_right_formway_bit,
        cfg.max_geometry_buffer_mismatch_ratio,
        cfg.min_geometry_buffer_mismatch_length_m,
        cfg.visual_consistency_buffer_distance_m,
        cfg.max_visual_consistency_mismatch_ratio,
        cfg.min_visual_consistency_mismatch_length_m,
    )


def _clone_group_probe(row: dict[str, Any]) -> dict[str, Any]:
    clone = dict(row)
    clone["rcsd_road_ids"] = list(row.get("rcsd_road_ids") or [])
    return clone


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


def _replaceable_road_ids_by_segment(replaceable_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        result[segment_id] = _parse_list(props.get("rcsd_road_ids"))
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


def _road_geometry_entries(rcsd_road_by_id: dict[str, dict[str, Any]]) -> list[_RoadGeometryEntry]:
    result: list[_RoadGeometryEntry] = []
    for road_id, road in rcsd_road_by_id.items():
        geometry = road.get("geometry")
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty:
            continue
        length = float(geometry.length or 0.0)
        if length <= 0.0:
            continue
        result.append(_RoadGeometryEntry(str(road_id), geometry, length))
    return result


def _strtree_query_index(item: Any, geometry_index_by_id: dict[int, int]) -> int | None:
    try:
        return int(item)
    except (TypeError, ValueError):
        return geometry_index_by_id.get(id(item))


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
