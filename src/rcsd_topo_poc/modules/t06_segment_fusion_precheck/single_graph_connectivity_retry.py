from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .adaptive_buffer_retry import (
    CONNECTIVITY_BUFFER_RETRY_REASONS,
    DUAL_DIRECTION_BUFFER_RETRY_REASONS,
    GEOMETRY_BUFFER_RETRY_REASONS,
)
from .buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentResult,
    _build_undirected_graph,
    _canonical_ids,
    _effective_directed_pair_nodes,
    _feature_road_id,
    _nodes_from_edges,
    _retained_geometry_buffer_coverage_status,
    _retained_status,
    _shortest_directed_path_covering_nodes,
)
from .graph_builders import Edge, NodeCanonicalizer
from .relation_mapping import RelationCheck
from .road_attributes import is_advance_right_turn_road


LONGITUDINAL_RETRY_RECOMMENDATION = "single_graph_first_longitudinal_retry"
DUAL_GRAPH_FIRST_RETRY_RECOMMENDATION = "dual_graph_first_bidirectional_retry"


@dataclass(frozen=True)
class SingleGraphConnectivityRetryOutcome:
    buffer_result: BufferSegmentResult
    reference_distance_m: float
    source_reason: str
    path_length_m: float
    base_buffer_overlap_length_m: float
    base_buffer_overlap_ratio: float
    path_to_swsd_length_ratio: float


class SingleGraphConnectivityRetry:
    def __init__(self, *, rcsd_road_features: list[dict[str, Any]], rcsd_node_features: list[dict[str, Any]]) -> None:
        self.node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
        self.road_features = list(rcsd_road_features)
        self.all_edges = _build_undirected_graph(
            self.road_features,
            node_canonicalizer=self.node_canonicalizer,
        ).edges
        non_advance_roads = [
            feature
            for feature in self.road_features
            if not is_advance_right_turn_road(dict(feature.get("properties") or {}))
        ]
        self.non_advance_edges = _build_undirected_graph(
            non_advance_roads,
            node_canonicalizer=self.node_canonicalizer,
        ).edges

    def retry(
        self,
        segment_geometry: BaseGeometry | None,
        relation: RelationCheck,
        optional_allowed_rcsd_nodes: list[str],
        unexpected_relation_base_ids: set[str] | None,
        directed_pair_nodes: list[str],
        sgrade: Any,
        directionality: str,
        buffer_result: BufferSegmentResult,
        diagnostic: dict[str, Any],
        config: BufferExtractionConfig,
        max_path_to_swsd_length_ratio: float,
    ) -> SingleGraphConnectivityRetryOutcome | None:
        if not self._eligible(
            sgrade=sgrade,
            directionality=directionality,
            relation=relation,
            buffer_result=buffer_result,
            diagnostic=diagnostic,
        ):
            return None
        if segment_geometry is None or segment_geometry.is_empty:
            return None

        required_nodes = _canonical_ids(relation.rcsd_pair_nodes, self.node_canonicalizer)
        directed_nodes = _effective_directed_pair_nodes(
            required_nodes,
            _canonical_ids(directed_pair_nodes, self.node_canonicalizer),
        )
        if len(set(required_nodes)) != 2 or len(directed_nodes) != 2:
            return None

        path_edges = self._directed_path_edges(
            directed_source=directed_nodes[0],
            directed_target=directed_nodes[1],
            required_nodes=required_nodes,
            segment_geometry=segment_geometry,
        )
        if not path_edges:
            return None

        base_buffer_geometry = segment_geometry.buffer(config.buffer_distance_m)
        path_geometry = _edge_geometry(path_edges)
        path_length = float(path_geometry.length) if not path_geometry.is_empty else 0.0
        segment_length = float(segment_geometry.length)
        if path_length <= 0.0 or segment_length <= 0.0:
            return None
        path_to_segment_ratio = path_length / segment_length
        if path_to_segment_ratio > max_path_to_swsd_length_ratio:
            return None

        overlap_length = _overlap_length(path_edges, base_buffer_geometry)
        min_core_overlap = min(config.buffer_distance_m, segment_length * 0.5)
        if overlap_length + 1e-9 < min_core_overlap:
            return None
        if _outside_terminal_length(path_edges, base_buffer_geometry, before=True) > config.buffer_distance_m:
            return None
        if _outside_terminal_length(path_edges, base_buffer_geometry, before=False) > config.buffer_distance_m:
            return None

        coverage_status = None
        reference_distance_m = None
        for distance_m in _reference_distances(config.buffer_distance_m):
            status = _retained_geometry_buffer_coverage_status(
                path_edges,
                segment_geometry,
                segment_geometry.buffer(distance_m),
                buffer_distance_m=distance_m,
                max_mismatch_ratio=config.max_geometry_buffer_mismatch_ratio,
                min_mismatch_length_m=config.min_geometry_buffer_mismatch_length_m,
            )
            if status.issue is None:
                coverage_status = status
                reference_distance_m = distance_m
                break
        if coverage_status is None or reference_distance_m is None:
            return None

        optional_nodes = _canonical_ids([*relation.rcsd_junc_nodes, *optional_allowed_rcsd_nodes], self.node_canonicalizer)
        retained_nodes = _nodes_from_edges(path_edges)
        unexpected_base_ids = (
            set(_canonical_ids(list(unexpected_relation_base_ids or set()), self.node_canonicalizer))
            - set(required_nodes)
            - set(optional_nodes)
        )
        unexpected_mapped_nodes = sorted(unexpected_base_ids & retained_nodes)
        ok, reason, unexpected_endpoint_nodes = _retained_status(
            retained_nodes,
            path_edges,
            required_nodes,
            required_nodes,
            directed_nodes,
            unexpected_mapped_semantic_nodes=unexpected_mapped_nodes,
            require_directed_pair=True,
            require_bidirectional=False,
        )
        if not ok:
            return None

        retained_road_ids = _unique_road_ids(path_edges)
        retained_node_ids = sorted(retained_nodes)
        base_overlap_ratio = overlap_length / path_length if path_length > 0 else 0.0
        result = BufferSegmentResult(
            ok=True,
            reason=reason,
            required_rcsd_nodes=required_nodes,
            optional_allowed_rcsd_nodes=optional_nodes,
            directed_rcsd_pair_nodes=directed_nodes,
            candidate_road_ids=retained_road_ids,
            candidate_node_ids=retained_node_ids,
            retained_road_ids=retained_road_ids,
            excluded_advance_right_turn_road_ids=[],
            retained_node_ids=retained_node_ids,
            inner_node_ids=sorted(set(optional_nodes) & retained_nodes),
            out_node_ids=[],
            unexpected_endpoint_node_ids=unexpected_endpoint_nodes,
            unexpected_mapped_semantic_node_ids=unexpected_mapped_nodes,
            low_buffer_overlap_road_ids=[],
            min_retained_road_buffer_overlap_ratio=base_overlap_ratio,
            geometry_buffer_coverage_issue=None,
            rcsd_outside_swsd_buffer_length_m=coverage_status.rcsd_outside_length_m,
            rcsd_outside_swsd_buffer_ratio=coverage_status.rcsd_outside_ratio,
            swsd_uncovered_by_rcsd_length_m=coverage_status.swsd_uncovered_length_m,
            swsd_uncovered_by_rcsd_ratio=coverage_status.swsd_uncovered_ratio,
            missing_required_node_ids=[],
            selected_component_id=0,
            candidate_road_count=len(retained_road_ids),
            retained_road_count=len(retained_road_ids),
            candidate_node_count=len(retained_node_ids),
            retained_node_count=len(retained_node_ids),
            geometry=path_geometry,
        )
        return SingleGraphConnectivityRetryOutcome(
            buffer_result=result,
            reference_distance_m=reference_distance_m,
            source_reason=f"{LONGITUDINAL_RETRY_RECOMMENDATION}:{buffer_result.reason}",
            path_length_m=path_length,
            base_buffer_overlap_length_m=overlap_length,
            base_buffer_overlap_ratio=base_overlap_ratio,
            path_to_swsd_length_ratio=path_to_segment_ratio,
        )

    def retry_dual_bidirectional(
        self,
        segment_geometry: BaseGeometry | None,
        relation: RelationCheck,
        optional_allowed_rcsd_nodes: list[str],
        unexpected_relation_base_ids: set[str] | None,
        sgrade: Any,
        buffer_result: BufferSegmentResult,
        diagnostic: dict[str, Any],
        config: BufferExtractionConfig,
        max_path_to_swsd_length_ratio: float,
    ) -> SingleGraphConnectivityRetryOutcome | None:
        if not self._dual_eligible(
            sgrade=sgrade,
            relation=relation,
            buffer_result=buffer_result,
            diagnostic=diagnostic,
        ):
            return None
        if segment_geometry is None or segment_geometry.is_empty:
            return None

        required_nodes = _canonical_ids(relation.rcsd_pair_nodes, self.node_canonicalizer)
        if len(set(required_nodes)) != 2:
            return None
        source, target = required_nodes
        forward_edges = self._directed_path_edges(
            directed_source=source,
            directed_target=target,
            required_nodes=required_nodes,
            segment_geometry=segment_geometry,
        )
        reverse_edges = self._directed_path_edges(
            directed_source=target,
            directed_target=source,
            required_nodes=required_nodes,
            segment_geometry=segment_geometry,
        )
        if not forward_edges or not reverse_edges:
            return None

        base_buffer_geometry = segment_geometry.buffer(config.buffer_distance_m)
        if not _dual_path_guard(forward_edges, segment_geometry, base_buffer_geometry, config, max_path_to_swsd_length_ratio):
            return None
        if not _dual_path_guard(reverse_edges, segment_geometry, base_buffer_geometry, config, max_path_to_swsd_length_ratio):
            return None

        path_edges = _unique_edges([*forward_edges, *reverse_edges])
        optional_nodes = _canonical_ids([*relation.rcsd_junc_nodes, *optional_allowed_rcsd_nodes], self.node_canonicalizer)
        retained_nodes = _nodes_from_edges(path_edges)
        unexpected_base_ids = (
            set(_canonical_ids(list(unexpected_relation_base_ids or set()), self.node_canonicalizer))
            - set(required_nodes)
            - set(optional_nodes)
        )
        unexpected_mapped_nodes = sorted(unexpected_base_ids & retained_nodes)
        ok, reason, unexpected_endpoint_nodes = _retained_status(
            retained_nodes,
            path_edges,
            required_nodes,
            required_nodes,
            [],
            unexpected_mapped_semantic_nodes=unexpected_mapped_nodes,
            require_directed_pair=False,
            require_bidirectional=True,
        )
        if not ok:
            return None

        retained_road_ids = _unique_road_ids(path_edges)
        retained_node_ids = sorted(retained_nodes)
        path_geometry = _edge_geometry(path_edges)
        path_length = float(path_geometry.length) if not path_geometry.is_empty else 0.0
        segment_length = float(segment_geometry.length)
        base_overlap_length = _overlap_length(path_edges, base_buffer_geometry)
        base_overlap_ratio = base_overlap_length / path_length if path_length > 0 else 0.0
        result = BufferSegmentResult(
            ok=True,
            reason=reason,
            required_rcsd_nodes=required_nodes,
            optional_allowed_rcsd_nodes=optional_nodes,
            directed_rcsd_pair_nodes=[],
            candidate_road_ids=retained_road_ids,
            candidate_node_ids=retained_node_ids,
            retained_road_ids=retained_road_ids,
            excluded_advance_right_turn_road_ids=[],
            retained_node_ids=retained_node_ids,
            inner_node_ids=sorted(set(optional_nodes) & retained_nodes),
            out_node_ids=[],
            unexpected_endpoint_node_ids=unexpected_endpoint_nodes,
            unexpected_mapped_semantic_node_ids=unexpected_mapped_nodes,
            low_buffer_overlap_road_ids=[],
            min_retained_road_buffer_overlap_ratio=base_overlap_ratio,
            geometry_buffer_coverage_issue=None,
            rcsd_outside_swsd_buffer_length_m=0.0,
            rcsd_outside_swsd_buffer_ratio=0.0,
            swsd_uncovered_by_rcsd_length_m=0.0,
            swsd_uncovered_by_rcsd_ratio=0.0,
            missing_required_node_ids=[],
            selected_component_id=0,
            candidate_road_count=len(retained_road_ids),
            retained_road_count=len(retained_road_ids),
            candidate_node_count=len(retained_node_ids),
            retained_node_count=len(retained_node_ids),
            geometry=path_geometry,
        )
        return SingleGraphConnectivityRetryOutcome(
            buffer_result=result,
            reference_distance_m=config.buffer_distance_m,
            source_reason=f"{DUAL_GRAPH_FIRST_RETRY_RECOMMENDATION}:{buffer_result.reason}",
            path_length_m=path_length,
            base_buffer_overlap_length_m=base_overlap_length,
            base_buffer_overlap_ratio=base_overlap_ratio,
            path_to_swsd_length_ratio=path_length / segment_length if segment_length > 0 else 0.0,
        )

    @staticmethod
    def _eligible(
        *,
        sgrade: Any,
        directionality: str,
        relation: RelationCheck,
        buffer_result: BufferSegmentResult,
        diagnostic: dict[str, Any],
    ) -> bool:
        if directionality != "single" or not _is_high_grade_sgrade(sgrade):
            return False
        if not relation.ok or len(set(relation.rcsd_pair_nodes)) != 2:
            return False
        if buffer_result.ok:
            return False
        if buffer_result.reason in GEOMETRY_BUFFER_RETRY_REASONS:
            return True
        return buffer_result.reason in CONNECTIVITY_BUFFER_RETRY_REASONS and _full_graph_supports_directed_retry(diagnostic)

    @staticmethod
    def _dual_eligible(
        *,
        sgrade: Any,
        relation: RelationCheck,
        buffer_result: BufferSegmentResult,
        diagnostic: dict[str, Any],
    ) -> bool:
        if not _is_high_grade_sgrade(sgrade):
            return False
        if not relation.ok or len(set(relation.rcsd_pair_nodes)) != 2:
            return False
        if buffer_result.ok:
            return False
        if buffer_result.reason not in DUAL_DIRECTION_BUFFER_RETRY_REASONS:
            return False
        return _full_graph_supports_bidirectional_retry(diagnostic)

    def _directed_path_edges(
        self,
        *,
        directed_source: str,
        directed_target: str,
        required_nodes: list[str],
        segment_geometry: BaseGeometry,
    ) -> list[Edge]:
        for edges in (self.non_advance_edges, self.all_edges):
            path = _shortest_directed_path_covering_nodes(
                edges,
                directed_source,
                directed_target,
                required_nodes,
                reference_geometry=segment_geometry,
            )
            if path is None:
                continue
            edge_by_id = {edge.edge_id: edge for edge in edges}
            return [edge_by_id[edge_id] for edge_id in path if edge_id in edge_by_id]
        return []


def _is_high_grade_sgrade(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("0-0") or text.startswith("0-1")


def _full_graph_supports_directed_retry(diagnostic: dict[str, Any]) -> bool:
    if diagnostic.get("full_graph_status") != "required_nodes_connected":
        return False
    return "full=directed_path_present" in str(diagnostic.get("directional_status") or "")


def _full_graph_supports_bidirectional_retry(diagnostic: dict[str, Any]) -> bool:
    if diagnostic.get("full_graph_status") != "required_nodes_connected":
        return False
    return "full=bidirectional" in str(diagnostic.get("directional_status") or "")


def _reference_distances(base_buffer_distance_m: float) -> tuple[float, ...]:
    return tuple(distance for distance in (75.0, 100.0) if distance > base_buffer_distance_m)


def _edge_geometry(edges: list[Edge]) -> BaseGeometry:
    geometries = [edge.geometry for edge in edges if edge.geometry is not None and not edge.geometry.is_empty]
    if not geometries:
        return GeometryCollection()
    return unary_union(geometries)


def _overlap_length(edges: list[Edge], buffer_geometry: BaseGeometry) -> float:
    return sum(_edge_overlap_length(edge, buffer_geometry) for edge in edges)


def _edge_overlap_length(edge: Edge, buffer_geometry: BaseGeometry) -> float:
    geometry = edge.geometry
    if geometry is None or geometry.is_empty or not geometry.intersects(buffer_geometry):
        return 0.0
    return float(geometry.intersection(buffer_geometry).length)


def _outside_terminal_length(edges: list[Edge], buffer_geometry: BaseGeometry, *, before: bool) -> float:
    ordered = edges if before else list(reversed(edges))
    total = 0.0
    for edge in ordered:
        if _edge_overlap_length(edge, buffer_geometry) > 0.0:
            return total
        geometry = edge.geometry
        if geometry is not None and not geometry.is_empty:
            total += float(geometry.length)
    return total


def _dual_path_guard(
    edges: list[Edge],
    segment_geometry: BaseGeometry,
    base_buffer_geometry: BaseGeometry,
    config: BufferExtractionConfig,
    max_path_to_swsd_length_ratio: float,
) -> bool:
    path_geometry = _edge_geometry(edges)
    path_length = float(path_geometry.length) if not path_geometry.is_empty else 0.0
    segment_length = float(segment_geometry.length)
    if path_length <= 0.0 or segment_length <= 0.0:
        return False
    if path_length / segment_length > max_path_to_swsd_length_ratio:
        return False
    min_core_overlap = max(config.min_road_overlap_length_m, config.buffer_distance_m * 0.75)
    return _overlap_length(edges, base_buffer_geometry) + 1e-9 >= min_core_overlap


def _unique_edges(edges: list[Edge]) -> list[Edge]:
    result: list[Edge] = []
    seen: set[str] = set()
    for edge in edges:
        if edge.edge_id in seen:
            continue
        seen.add(edge.edge_id)
        result.append(edge)
    return result


def _unique_road_ids(edges: list[Edge]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        road_id = edge.road_id or _feature_road_id({"properties": edge.properties})
        if road_id is None or road_id in seen:
            continue
        seen.add(road_id)
        result.append(road_id)
    return result
