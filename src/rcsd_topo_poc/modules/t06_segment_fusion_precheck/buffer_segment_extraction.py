from __future__ import annotations

import heapq
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection, LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .graph_builders import Edge, NodeCanonicalizer
from .parsing import ParseError, normalize_id
from .relation_mapping import RelationCheck
from .road_attributes import is_advance_right_turn_road


PATH_REFERENCE_BUFFER_M = 15.0
PATH_OFF_REFERENCE_PENALTY_MULTIPLIER = 6.0
CONNECTED_CORRIDOR_SUPPLEMENT_BUFFER_M = PATH_REFERENCE_BUFFER_M
CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_RATIO = 0.1
CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_LENGTH_M = 20.0
VISUAL_GAP_SUPPLEMENT_MAX_OUTSIDE_RATIO = 0.25
VISUAL_GAP_SUPPLEMENT_MIN_COVERAGE_M = 1.0


from .buffer_segment_models import (
    BufferExtractionConfig,
    BufferSegmentResult,
    _CandidateContext,
    _GeometryMetrics,
    _CandidateGraph,
    _SeedGroup,
    _PrunedGraph,
    _GeometryCoverageStatus,
    _GEOMETRY_METRICS_CACHE,
    _PATH_REFERENCE_BUFFER_CACHE,
)

from .buffer_segment_results import (
    _mismatch_exceeds_threshold,
    _nodes_from_edges,
    _retained_status,
    _retained_buffer_overlap_issues,
    _retained_geometry_buffer_coverage_status,
    _visual_consistency_status,
    _is_soft_visual_consistency_issue,
    _unexpected_endpoint_nodes,
    _leaf_nodes,
    _required_nodes_connected,
    _pair_nodes_bidirectionally_reachable,
    _pair_nodes_reachable_in_order,
    _ordered_required_rcsd_nodes,
    _ordered_anchor_pairs,
    _effective_directed_pair_nodes,
    _directed_adjacency_from_edges,
    _directed_reachable,
    _coerce_int,
    _adjacency_from_edges,
    _result,
    _empty_result,
    _edge_geometry,
    _road_ids,
    _feature_road_id,
    _node_ids,
    _unique_ids,
    _canonical_ids,
    _endpoint_in_buffer,
    _first_present,
)

from .buffer_segment_graph import (
    _select_candidate_roads,
    _restore_required_corridor_advance_roads,
    _non_advance_endpoint_counts,
    _has_second_degree_non_advance_link,
    _selected_graph_satisfies_required_corridor,
    _feature_canonical_endpoints,
    _select_candidate_nodes,
    _build_undirected_graph,
    _connected_components,
    _select_component,
    _prune_component_seed_based,
    _seed_group_allowed_terminal_corridor_nodes,
    _seed_groups,
    _seed_group_leaves,
    _trim_unprotected_leaves,
    _include_reachable_optional_terminal_paths,
    _minimum_terminal_edge_paths,
    _shortest_edge_path,
    _best_undirected_ordered_anchor_path,
    _ordered_edge_path_covering_nodes,
    _shortest_anchor_edge_path,
    _shortest_directed_path_covering_nodes,
    _node_mask,
    _weighted_adjacency,
    _path_weight,
    _edge_weight,
    _path_reference_buffer,
    _off_reference_penalty,
    _edge_geometry_metrics,
    _bounds_intersect,
    _required_shortcut_penalty,
)

from .buffer_segment_supplement import (
    _build_corridor_subgraph,
    _include_internal_corridor_edges,
    _has_direction_compatible_selected_parallel_edge,
    _directed_travel_pairs,
    _include_connected_corridor_supplement_edges,
    _include_required_leaf_attach_edges,
    _include_visual_gap_candidate_components,
    _include_parallel_visual_corridor_edges,
    _retained_visual_gap_exceeds_threshold,
    _directed_parallel_corridor_path,
    _path_sufficiently_covers_reference,
    _directed_edge_connects_boundary_to_path,
    _component_touches_blocked_node,
    _edge_within_visual_gap_scope,
    _visual_consistency_edges,
    _include_directed_semantic_junction_bridge_edges,
    _edge_within_buffer_scope,
)

class SpatialFeatureIndex:
    def __init__(self, features: list[dict[str, Any]]) -> None:
        self.features: list[dict[str, Any]] = []
        self.geometries: list[BaseGeometry] = []
        for feature in features:
            geometry = feature.get("geometry")
            if isinstance(geometry, BaseGeometry) and not geometry.is_empty:
                self.features.append(feature)
                self.geometries.append(geometry)
        self.tree = STRtree(self.geometries) if self.geometries else None

    def query(self, geometry: BaseGeometry) -> list[dict[str, Any]]:
        if self.tree is None:
            return []
        return [self.features[int(index)] for index in self.tree.query(geometry)]


class BufferSegmentExtractor:
    def __init__(self, *, rcsd_road_features: list[dict[str, Any]], rcsd_node_features: list[dict[str, Any]]) -> None:
        self.road_index = SpatialFeatureIndex(rcsd_road_features)
        self.node_index = SpatialFeatureIndex(rcsd_node_features)
        self.node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
        self._candidate_cache: dict[tuple[int, float, float, float, int], _CandidateContext] = {}
        self._canonical_relation_base_cache: dict[frozenset[str], frozenset[str]] = {}

    def extract(
        self,
        *,
        segment_geometry: BaseGeometry | None,
        relation: RelationCheck,
        optional_allowed_rcsd_nodes: list[str],
        all_relation_base_ids: set[str],
        unexpected_relation_base_ids: set[str] | None = None,
        directed_pair_nodes: list[str] | None = None,
        require_directed_pair: bool = False,
        require_bidirectional: bool = False,
        config: BufferExtractionConfig | None = None,
    ) -> BufferSegmentResult:
        cfg = config or BufferExtractionConfig()
        pair_nodes = _canonical_ids(relation.rcsd_pair_nodes, self.node_canonicalizer)
        directed_nodes = _effective_directed_pair_nodes(pair_nodes, _canonical_ids(directed_pair_nodes or [], self.node_canonicalizer))
        junc_nodes = _canonical_ids(relation.rcsd_junc_nodes, self.node_canonicalizer)
        ordered_corridor_nodes = _ordered_required_rcsd_nodes(
            pair_nodes,
            junc_nodes,
            directed_nodes=directed_nodes,
            require_directed_pair=require_directed_pair,
        )
        required_nodes = pair_nodes
        optional_nodes = _canonical_ids([*junc_nodes, *optional_allowed_rcsd_nodes], self.node_canonicalizer)
        protected_optional_nodes: set[str] = set(junc_nodes)
        relation_base_ids = self._canonical_relation_base_ids(all_relation_base_ids)
        unexpected_base_ids = (
            set(_canonical_ids(list(unexpected_relation_base_ids or set()), self.node_canonicalizer))
            - set(required_nodes)
            - set(optional_nodes)
        )
        if segment_geometry is None or segment_geometry.is_empty:
            return _empty_result("missing_swsd_geometry", required_nodes, optional_nodes)

        candidate_context = self._candidate_context(segment_geometry, cfg)
        buffer_geometry = candidate_context.buffer_geometry
        candidate_nodes = list(candidate_context.candidate_nodes)
        candidate_roads = list(candidate_context.candidate_roads)
        excluded_roads = list(candidate_context.excluded_roads)
        candidate_roads, excluded_roads = _restore_required_corridor_advance_roads(
            selected_roads=candidate_roads,
            excluded_roads=excluded_roads,
            required_nodes=ordered_corridor_nodes,
            pair_nodes=pair_nodes,
            directed_pair_nodes=directed_nodes,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
            node_canonicalizer=self.node_canonicalizer,
            reference_geometry=segment_geometry,
        )
        graph = _build_undirected_graph(candidate_roads, node_canonicalizer=self.node_canonicalizer)
        components = _connected_components(graph.adjacency)
        selected = _select_component(components, required_nodes)
        if selected is None:
            graph_nodes = set(graph.adjacency)
            missing = [node for node in required_nodes if node not in graph_nodes]
            reason = "required_semantic_nodes_missing_from_buffer_graph" if missing else "required_semantic_nodes_not_connected_in_buffer"
            return _result(
                ok=False,
                reason=reason,
                required_nodes=required_nodes,
                optional_nodes=optional_nodes,
                directed_nodes=directed_nodes if require_directed_pair else [],
                candidate_roads=candidate_roads,
                candidate_nodes=candidate_nodes,
                retained_edges=[],
                excluded_roads=excluded_roads,
                retained_nodes=[],
                inner_nodes=[],
                out_nodes=[],
                unexpected_endpoint_nodes=[],
                unexpected_mapped_semantic_nodes=[],
                missing_required_nodes=missing,
                selected_component_id=None,
            )

        selected_nodes = components[selected]
        selected_edges = [edge for edge in graph.edges if edge.source in selected_nodes and edge.target in selected_nodes]
        semantic_nodes = (relation_base_ids | set(self.node_canonicalizer.semantic_node_ids)) & selected_nodes
        allowed_nodes = set(required_nodes) | set(optional_nodes)
        pruned = _prune_component_seed_based(
            component_nodes=selected_nodes,
            edges=selected_edges,
            required_nodes=set(required_nodes),
            optional_nodes=set(optional_nodes),
            protected_optional_nodes=protected_optional_nodes,
            semantic_nodes=semantic_nodes,
            pair_nodes=pair_nodes,
            directed_pair_nodes=directed_nodes,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
            reference_geometry=segment_geometry,
        )
        internal_visual_buffer_geometry: BaseGeometry | None = None
        visual_buffer_distance = cfg.visual_consistency_buffer_distance_m
        if (
            segment_geometry is not None
            and not segment_geometry.is_empty
            and visual_buffer_distance is not None
            and 0 < visual_buffer_distance < cfg.buffer_distance_m
        ):
            internal_visual_buffer_geometry = segment_geometry.buffer(visual_buffer_distance)
        corridor_anchor_nodes = ordered_corridor_nodes
        corridor_edges = _build_corridor_subgraph(
            pruned.retained_edges,
            corridor_anchor_nodes,
            pair_nodes,
            directed_nodes,
            reference_geometry=segment_geometry,
            reference_buffer_geometry=buffer_geometry,
            max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
            min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
        )
        if not require_directed_pair and not corridor_edges and corridor_anchor_nodes != required_nodes:
            corridor_anchor_nodes = required_nodes
            corridor_edges = _build_corridor_subgraph(
                pruned.retained_edges,
                corridor_anchor_nodes,
                pair_nodes,
                directed_nodes,
                reference_geometry=segment_geometry,
                reference_buffer_geometry=buffer_geometry,
                max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
                min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
                require_directed_pair=require_directed_pair,
                require_bidirectional=require_bidirectional,
            )
        corridor_edges = _include_reachable_optional_terminal_paths(
            pruned.retained_edges,
            corridor_edges,
            optional_nodes=protected_optional_nodes,
            reference_geometry=segment_geometry,
        )
        if require_directed_pair:
            corridor_edges = _include_directed_semantic_junction_bridge_edges(
                selected_edges,
                corridor_edges,
                required_nodes=set(required_nodes),
                optional_nodes=set(junc_nodes),
                pair_nodes=set(pair_nodes),
                blocked_nodes=unexpected_base_ids - set(pruned.inner_nodes),
                reference_geometry=segment_geometry,
            )
        pre_supplement_nodes = _nodes_from_edges(corridor_edges)
        allowed_supplement_endpoint_nodes: set[str] = set()
        if not require_directed_pair:
            corridor_edges, allowed_supplement_endpoint_nodes = _include_connected_corridor_supplement_edges(
                selected_edges,
                corridor_edges,
                required_nodes=set(required_nodes),
                optional_nodes=set(optional_nodes),
                blocked_nodes=unexpected_base_ids - set(pruned.inner_nodes),
                reference_geometry=segment_geometry,
                require_optional_terminal=not require_bidirectional,
                allow_single_optional_boundary=require_bidirectional,
            )
        internal_touch_nodes: set[str] | None = None
        if not require_directed_pair:
            internal_touch_nodes = _nodes_from_edges(corridor_edges) - pre_supplement_nodes
        corridor_edges = _include_internal_corridor_edges(
            selected_edges,
            corridor_edges,
            required_nodes=set(corridor_anchor_nodes),
            ordered_anchor_pairs=_ordered_anchor_pairs(corridor_anchor_nodes) if len(corridor_anchor_nodes) > 2 else set(),
            allowed_touch_nodes=internal_touch_nodes,
            reference_buffer_geometry=buffer_geometry,
            reference_visual_buffer_geometry=internal_visual_buffer_geometry,
            max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
            min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
            max_visual_mismatch_ratio=cfg.max_visual_consistency_mismatch_ratio,
            min_visual_mismatch_length_m=cfg.min_visual_consistency_mismatch_length_m,
            allow_selected_required_pair_parallel_edges=require_directed_pair,
            allow_retained_node_self_loop_edges=not require_directed_pair,
        )
        corridor_edges, parallel_corridor_endpoint_nodes = _include_parallel_visual_corridor_edges(
            selected_edges,
            corridor_edges,
            required_nodes=set(required_nodes),
            directed_pair_nodes=directed_nodes,
            require_directed_pair=require_directed_pair,
            blocked_nodes=unexpected_base_ids - set(pruned.inner_nodes),
            reference_geometry=segment_geometry,
            reference_buffer_geometry=internal_visual_buffer_geometry,
            visual_buffer_distance_m=cfg.visual_consistency_buffer_distance_m,
            max_mismatch_ratio=cfg.max_visual_consistency_mismatch_ratio,
            min_mismatch_length_m=cfg.min_visual_consistency_mismatch_length_m,
        )
        allowed_supplement_endpoint_nodes.update(parallel_corridor_endpoint_nodes)
        visual_gap_endpoint_nodes: set[str] = set()
        if not require_directed_pair:
            corridor_edges, visual_gap_endpoint_nodes = _include_visual_gap_candidate_components(
                graph.edges,
                corridor_edges,
                blocked_nodes=unexpected_base_ids - set(pruned.inner_nodes),
                reference_geometry=segment_geometry,
                reference_buffer_geometry=internal_visual_buffer_geometry,
                max_mismatch_ratio=cfg.max_visual_consistency_mismatch_ratio,
                min_mismatch_length_m=cfg.min_visual_consistency_mismatch_length_m,
            )
        required_leaf_endpoint_nodes: set[str] = set()
        if not require_directed_pair:
            corridor_edges, required_leaf_endpoint_nodes = _include_required_leaf_attach_edges(
                selected_edges,
                corridor_edges,
                required_nodes=set(required_nodes),
                pair_nodes=set(pair_nodes),
                blocked_nodes=unexpected_base_ids - set(pruned.inner_nodes),
                reference_buffer_geometry=buffer_geometry,
                max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
                min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
            )
        corridor_nodes = _nodes_from_edges(corridor_edges)
        unexpected_mapped_semantic_nodes = sorted((unexpected_base_ids - set(pruned.inner_nodes)) & corridor_nodes)
        ok, reason, unexpected_endpoint_nodes = _retained_status(
            corridor_nodes,
            corridor_edges,
            required_nodes,
            pair_nodes,
            directed_nodes,
            unexpected_mapped_semantic_nodes=unexpected_mapped_semantic_nodes,
            allowed_endpoint_nodes=allowed_supplement_endpoint_nodes | protected_optional_nodes | required_leaf_endpoint_nodes | visual_gap_endpoint_nodes,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
        )
        low_overlap_road_ids, min_overlap_ratio = _retained_buffer_overlap_issues(
            corridor_edges,
            buffer_geometry,
            cfg.min_road_overlap_ratio,
        )
        if ok and low_overlap_road_ids:
            ok = False
            reason = "retained_road_buffer_overlap_insufficient"
        coverage_status = _retained_geometry_buffer_coverage_status(
            corridor_edges,
            segment_geometry,
            buffer_geometry,
            buffer_distance_m=cfg.buffer_distance_m,
            max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
            min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
        )
        visual_buffer_distance = cfg.visual_consistency_buffer_distance_m
        soft_visual_consistency_issue = False
        if (
            ok
            and coverage_status.issue is None
            and visual_buffer_distance is not None
            and 0 < visual_buffer_distance < cfg.buffer_distance_m
        ):
            visual_status = _retained_geometry_buffer_coverage_status(
                _visual_consistency_edges(corridor_edges),
                segment_geometry,
                segment_geometry.buffer(visual_buffer_distance),
                buffer_distance_m=visual_buffer_distance,
                max_mismatch_ratio=cfg.max_visual_consistency_mismatch_ratio,
                min_mismatch_length_m=cfg.min_visual_consistency_mismatch_length_m,
            )
            if visual_status.issue is not None:
                coverage_status = _visual_consistency_status(visual_status)
                soft_visual_consistency_issue = _is_soft_visual_consistency_issue(coverage_status)
        return _result(
            ok=ok,
            reason=reason,
            required_nodes=required_nodes,
            optional_nodes=optional_nodes,
            directed_nodes=directed_nodes if require_directed_pair else [],
            candidate_roads=candidate_roads,
            candidate_nodes=candidate_nodes,
            retained_edges=corridor_edges,
            excluded_roads=excluded_roads,
            retained_nodes=sorted(corridor_nodes),
            inner_nodes=sorted(set(pruned.inner_nodes) & corridor_nodes),
            out_nodes=sorted(set(pruned.out_nodes) - corridor_nodes),
            unexpected_endpoint_nodes=unexpected_endpoint_nodes,
            unexpected_mapped_semantic_nodes=unexpected_mapped_semantic_nodes,
            low_overlap_road_ids=low_overlap_road_ids,
            min_overlap_ratio=min_overlap_ratio,
            coverage_status=coverage_status,
            missing_required_nodes=[],
            selected_component_id=selected,
        )

    def _candidate_context(self, segment_geometry: BaseGeometry, cfg: BufferExtractionConfig) -> _CandidateContext:
        key = (
            id(segment_geometry),
            cfg.buffer_distance_m,
            cfg.min_road_overlap_ratio,
            cfg.min_road_overlap_length_m,
            cfg.advance_right_formway_bit,
        )
        cached = self._candidate_cache.get(key)
        if cached is not None and cached.source_geometry is segment_geometry:
            return cached
        buffer_geometry = segment_geometry.buffer(cfg.buffer_distance_m)
        candidate_nodes = _select_candidate_nodes(self.node_index.query(buffer_geometry), buffer_geometry)
        candidate_roads, excluded_roads = _select_candidate_roads(
            self.road_index.query(buffer_geometry),
            buffer_geometry,
            cfg,
            node_canonicalizer=self.node_canonicalizer,
        )
        if len(self._candidate_cache) >= 512:
            self._candidate_cache.clear()
        context = _CandidateContext(
            source_geometry=segment_geometry,
            buffer_geometry=buffer_geometry,
            candidate_nodes=candidate_nodes,
            candidate_roads=candidate_roads,
            excluded_roads=excluded_roads,
        )
        self._candidate_cache[key] = context
        return context

    def _canonical_relation_base_ids(self, values: set[str]) -> frozenset[str]:
        key = frozenset(values)
        cached = self._canonical_relation_base_cache.get(key)
        if cached is not None:
            return cached
        canonical = frozenset(_canonical_ids(list(key), self.node_canonicalizer))
        if len(self._canonical_relation_base_cache) >= 32:
            self._canonical_relation_base_cache.pop(next(iter(self._canonical_relation_base_cache)))
        self._canonical_relation_base_cache[key] = canonical
        return canonical
