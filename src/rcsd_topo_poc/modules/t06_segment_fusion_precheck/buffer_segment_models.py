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


@dataclass(frozen=True)
class BufferExtractionConfig:
    buffer_distance_m: float = 50.0
    min_road_overlap_ratio: float = 0.2
    min_road_overlap_length_m: float = 1.0
    advance_right_formway_bit: int = 128
    max_geometry_buffer_mismatch_ratio: float = 0.1
    min_geometry_buffer_mismatch_length_m: float = 20.0
    visual_consistency_buffer_distance_m: float | None = 15.0
    max_visual_consistency_mismatch_ratio: float = 0.1
    min_visual_consistency_mismatch_length_m: float = 20.0


@dataclass(frozen=True)
class BufferSegmentResult:
    ok: bool
    reason: str
    required_rcsd_nodes: list[str]
    optional_allowed_rcsd_nodes: list[str]
    directed_rcsd_pair_nodes: list[str]
    candidate_road_ids: list[str]
    candidate_node_ids: list[str]
    retained_road_ids: list[str]
    excluded_advance_right_turn_road_ids: list[str]
    retained_node_ids: list[str]
    inner_node_ids: list[str]
    out_node_ids: list[str]
    unexpected_endpoint_node_ids: list[str]
    unexpected_mapped_semantic_node_ids: list[str]
    low_buffer_overlap_road_ids: list[str]
    min_retained_road_buffer_overlap_ratio: float | None
    geometry_buffer_coverage_issue: str | None
    rcsd_outside_swsd_buffer_length_m: float
    rcsd_outside_swsd_buffer_ratio: float
    swsd_uncovered_by_rcsd_length_m: float
    swsd_uncovered_by_rcsd_ratio: float
    missing_required_node_ids: list[str]
    selected_component_id: int | None
    candidate_road_count: int
    retained_road_count: int
    candidate_node_count: int
    retained_node_count: int
    geometry: BaseGeometry


@dataclass(frozen=True)
class _CandidateContext:
    source_geometry: BaseGeometry
    buffer_geometry: BaseGeometry
    candidate_nodes: list[dict[str, Any]]
    candidate_roads: list[dict[str, Any]]
    excluded_roads: list[dict[str, Any]]


@dataclass(frozen=True)
class _GeometryMetrics:
    is_empty: bool
    length: float
    bounds: tuple[float, float, float, float] | None


_GEOMETRY_METRICS_CACHE: dict[int, tuple[BaseGeometry, _GeometryMetrics]] = {}
_PATH_REFERENCE_BUFFER_CACHE: dict[int, tuple[BaseGeometry, BaseGeometry]] = {}


@dataclass
class _CandidateGraph:
    adjacency: dict[str, set[str]]
    edges: list[Edge]


@dataclass(frozen=True)
class _SeedGroup:
    seed_nodes: set[str]
    scope_nodes: set[str]
    leaves: set[str]


@dataclass(frozen=True)
class _PrunedGraph:
    retained_nodes: set[str]
    retained_edges: list[Edge]
    inner_nodes: list[str]
    out_nodes: list[str]


@dataclass(frozen=True)
class _GeometryCoverageStatus:
    issue: str | None
    rcsd_outside_length_m: float
    rcsd_outside_ratio: float
    swsd_uncovered_length_m: float
    swsd_uncovered_ratio: float
