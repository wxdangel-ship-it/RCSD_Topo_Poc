from __future__ import annotations

import json
import hashlib
from collections import defaultdict, deque
from itertools import combinations
from typing import Any

from shapely import buffer as vectorized_buffer
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list, unique_preserve_order
from .road_attributes import is_advance_right_turn_road
from .schemas import feature
from .step3_topology_supplement import TOPOLOGY_SUPPLEMENT_SPLIT_REASON


STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM = "t06_step3_topology_connectivity_audit"
STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS = [
    "audit_layer",
    "audit_status",
    "audit_reason",
    "recommended_owner",
    "swsd_segment_id",
    "swsd_segment_ids",
    "swsd_node_id",
    "swsd_road_id",
    "frcsd_road_id",
    "frcsd_node_ids",
    "relation_status",
    "source_mix",
    "directionality",
    "pair_nodes",
    "path_forward",
    "path_reverse",
    "undirected_connected",
    "mapped_node_count",
    "missing_mapping_count",
    "max_pairwise_distance_m",
    "coverage_buffer_m",
    "uncovered_ratio",
    "uncovered_length_m",
    "corridor_buffer_m",
    "corridor_uncovered_ratio",
    "corridor_uncovered_length_m",
    "final_path_forward",
    "final_path_reverse",
    "final_undirected_connected",
    "final_corridor_uncovered_ratio",
    "final_corridor_uncovered_length_m",
    "projected_gap_m",
    "action",
    "action_reason",
]
TOPOLOGY_CONNECTIVITY_AUDIT_LAYERS = [
    "final_road_node_integrity",
    "formal_replacement_source_consistency",
    "segment_internal_connectivity",
    "segment_road_connectivity",
    "retained_swsd_endpoint_closure",
    "segment_junction_connectivity",
    "patch_road_attachment",
    "advance_right_endpoint_connectivity",
]
TOPOLOGY_CONNECTIVITY_AUDIT_STATUSES = ["pass", "warn", "fail"]

JUNCTION_WARN_DISTANCE_M = 1.0
JUNCTION_FAIL_DISTANCE_M = 5.0
ATTACHMENT_FAIL_DISTANCE_M = 1.0
SEGMENT_COVERAGE_BUFFER_M = 5.0
SEGMENT_ROAD_COVERAGE_BUFFER_M = 2.0
SEGMENT_CORRIDOR_BUFFER_M = 15.0
SEGMENT_MAX_UNCOVERED_RATIO = 0.05
SEGMENT_CORRIDOR_MANUAL_REVIEW_MAX_UNCOVERED_RATIO = 0.2
SEGMENT_MIN_UNCOVERED_LENGTH_M = 20.0
JUNCTION_SURFACE_COVERAGE_RELEASE_RISK = "junction_surface_coverage_release"
SWSD_BUFFER_CORRIDOR_RELEASE_RISK = "swsd_buffer_corridor_controlled_release"
CoverageCacheKey = tuple[float, tuple[tuple[str, str, str], ...]]
CoverageCache = dict[CoverageCacheKey, BaseGeometry]
RoadSignature = tuple[tuple[str, str, str], ...]
RoadSignatureCache = dict[tuple[int, ...], tuple[tuple[dict[str, Any], ...], RoadSignature]]
UncoveredMetric = tuple[float | None, float | None]
UncoveredMetricKey = tuple[str, float, RoadSignature]
_MAX_UNCOVERED_METRICS = 200_000
_METRIC_PREWARM_BATCH_SIZE = 64


class _ReusableCoverageCache(dict[CoverageCacheKey, BaseGeometry]):
    """Release buffered geometries between validations while retaining compact metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.uncovered_metrics: dict[UncoveredMetricKey, UncoveredMetric] = {}


def _coverage_cache_needs_prewarm(coverage_cache: CoverageCache) -> bool:
    return not isinstance(coverage_cache, _ReusableCoverageCache) or not coverage_cache.uncovered_metrics


def _relation_roads(props: dict[str, Any], road_index: "_RoadIndex") -> list[dict[str, Any]]:
    road_ids = _as_id_list(props.get("frcsd_road_ids"))
    source_values = {_source_text(value) for value in _as_id_list(props.get("frcsd_road_source_values"))}
    source_values.discard("")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for road_id in road_ids:
        for source_value, road in road_index.roads_for_id(road_id):
            if source_values and source_value not in source_values:
                continue
            key = (source_value, road_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(road)
    return result


class _DirectedRoadGraph:
    def __init__(self, roads: list[dict[str, Any]], *, canonicalizer: NodeCanonicalizer) -> None:
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.undirected: dict[str, set[str]] = defaultdict(set)
        for road in roads:
            endpoints = _road_endpoint_node_ids(road)
            if len(endpoints) < 2:
                continue
            source = canonicalizer.canonicalize(endpoints[0])
            target = canonicalizer.canonicalize(endpoints[-1])
            direction = _coerce_int((road.get("properties") or {}).get("direction"))
            if direction in {0, 1, 2}:
                self.forward[source].add(target)
            if direction in {0, 1, 3}:
                self.forward[target].add(source)
            self.undirected[source].add(target)
            self.undirected[target].add(source)
        self.undirected_component_by_node = _undirected_component_index(self.undirected)

    def reachable_any(self, starts: list[str], targets: list[str]) -> bool:
        return _reachable_any(self.forward, starts, targets)

    def undirected_reachable_any(self, starts: list[str], targets: list[str]) -> bool:
        if not starts or not targets:
            return False
        target_components = {
            self.undirected_component_by_node.get(node, node)
            for node in targets
        }
        return any(
            self.undirected_component_by_node.get(node, node) in target_components
            for node in starts
        )


class _RoadIndex:
    def __init__(self, roads: list[dict[str, Any]], *, source_field_name: str) -> None:
        self.by_id: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        self.incident_nodes: set[tuple[str, str]] = set()
        self.materialized_source_road_ids: set[tuple[str, str]] = set()
        for road in roads:
            road_id = _feature_id(road)
            props = dict(road.get("properties") or {})
            source = _source_text(props.get(source_field_name))
            self.by_id[road_id].append((source, road))
            for source_road_id in (_safe_text(props.get("source_road_id")), _safe_text(props.get("t06_split_original_road_id"))):
                if source_road_id:
                    self.materialized_source_road_ids.add((source, source_road_id))
            for node_id in _road_endpoint_node_ids(road):
                self.incident_nodes.add((source, node_id))

    def roads_for_id(self, road_id: str) -> list[tuple[str, dict[str, Any]]]:
        return self.by_id.get(str(road_id), [])

    def has_incident_road(self, source: str, node_id: str) -> bool:
        return (str(source), str(node_id)) in self.incident_nodes

    def has_materialized_source_road(self, source: str, source_road_id: str) -> bool:
        return (str(source), str(source_road_id)) in self.materialized_source_road_ids


class _RoadLineSpatialIndex:
    def __init__(self, roads: list[dict[str, Any]]) -> None:
        self._lines = [
            line
            for road in roads
            for line in [_feature_line(road)]
            if line is not None and not line.is_empty
        ]
        self._tree = STRtree(self._lines) if self._lines else None

    def query_intersecting(self, geometry: BaseGeometry) -> list[LineString]:
        if self._tree is None:
            return []
        return [self._lines[int(index)] for index in self._tree.query(geometry, predicate="intersects")]


class _NodeIndex:
    def __init__(self, nodes: list[dict[str, Any]], *, source_field_name: str) -> None:
        self.source_field_name = source_field_name
        self.by_source_id: dict[tuple[str, str], dict[str, Any]] = {}
        self.by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        canonicalizer = NodeCanonicalizer.from_node_features(nodes)
        self.by_source_canonical: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            node_id = _feature_id(node)
            source = _source_text((node.get("properties") or {}).get(source_field_name))
            self.by_source_id[(source, node_id)] = node
            self.by_id[node_id].append(node)
            try:
                self.by_source_canonical[(source, canonicalizer.canonicalize(node_id))].append(node)
            except ParseError:
                pass

    def node_for_ref(self, ref: "_NodeRef") -> dict[str, Any] | None:
        node = self.by_source_id.get((ref.source, ref.node_id))
        if node is None:
            candidates = self.by_source_canonical.get((ref.source, ref.node_id), [])
            node = candidates[0] if candidates else None
        if node is None:
            candidates = self.by_id.get(ref.node_id, [])
            node = candidates[0] if candidates else None
        return node

    def exact_node(self, source: str, node_id: str) -> dict[str, Any] | None:
        try:
            normalized_node_id = normalize_id(node_id)
        except ParseError:
            normalized_node_id = str(node_id)
        node = self.by_source_id.get((_source_text(source), normalized_node_id))
        if node is not None:
            return node
        candidates = self.by_id.get(normalized_node_id, [])
        return candidates[0] if len(candidates) == 1 else None

    def point_for_ref(self, ref: "_NodeRef") -> Point | None:
        node = self.node_for_ref(ref)
        geometry = node.get("geometry") if node is not None else None
        return geometry if isinstance(geometry, Point) else None

    def node_ids_for_source(self, source: str) -> list[str]:
        return [node_id for item_source, node_id in self.by_source_id if item_source == source]

    def mainnode_root_for_ref(self, ref: "_NodeRef") -> str | None:
        node = self.node_for_ref(ref)
        if node is None:
            return None
        current = _feature_id(node)
        source = _source_text((node.get("properties") or {}).get(self.source_field_name)) or ref.source
        seen: set[tuple[str, str]] = set()
        while current and (source, current) not in seen:
            seen.add((source, current))
            current_node = self.by_source_id.get((source, current))
            if current_node is None:
                candidates = self.by_id.get(current, [])
                current_node = candidates[0] if candidates else None
            if current_node is None:
                return current
            props = dict(current_node.get("properties") or {})
            source = _source_text(props.get(self.source_field_name)) or source
            next_id = _safe_text(props.get("mainnodeid"))
            if not next_id or next_id == "0" or next_id == current:
                return current
            current = next_id
        return current or None


class _NodeRef:
    def __init__(self, source: str, node_id: str) -> None:
        self.source = source
        self.node_id = node_id


def _node_map_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [dict(item) for item in parsed if isinstance(item, dict)]
    return []


def _segment_uncovered_metrics(
    segment: dict[str, Any] | None,
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
    coverage_cache: CoverageCache | None = None,
    road_signature_cache: RoadSignatureCache | None = None,
) -> tuple[float | None, float | None]:
    segment_geometry = (segment or {}).get("geometry")
    if not isinstance(segment_geometry, BaseGeometry) or segment_geometry.is_empty or segment_geometry.length <= 0:
        return None, None
    metric_cache = (
        coverage_cache.uncovered_metrics
        if isinstance(coverage_cache, _ReusableCoverageCache)
        else None
    )
    metric_key: UncoveredMetricKey | None = None
    if metric_cache is not None:
        metric_key = _uncovered_metric_key(
            segment_geometry,
            buffer_m=buffer_m,
            road_signature=_road_signature(roads, signature_cache=road_signature_cache),
        )
        cached_metric = metric_cache.get(metric_key)
        if cached_metric is not None:
            return cached_metric
    buffered_roads = _buffered_road_union(
        roads,
        buffer_m=buffer_m,
        coverage_cache=coverage_cache,
        road_signature_cache=road_signature_cache,
    )
    if buffered_roads is None:
        result = (1.0, float(segment_geometry.length))
    else:
        uncovered = segment_geometry.difference(buffered_roads)
        length = float(uncovered.length)
        result = (length / float(segment_geometry.length), length)
    if metric_cache is not None and metric_key is not None:
        _remember_uncovered_metric(metric_cache, metric_key, result)
    return result


def _buffered_road_union(
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
    coverage_cache: CoverageCache | None,
    road_signature_cache: RoadSignatureCache | None = None,
) -> BaseGeometry | None:
    key = _road_buffer_cache_key(
        roads,
        buffer_m=buffer_m,
        road_signature_cache=road_signature_cache,
    )
    if coverage_cache is not None and key in coverage_cache:
        return coverage_cache[key]
    road_geometries = [
        line
        for road in roads
        for line in [_feature_line(road)]
        if line is not None and not line.is_empty
    ]
    if not road_geometries:
        return None
    buffered = unary_union(road_geometries).buffer(buffer_m)
    if coverage_cache is not None:
        coverage_cache[key] = buffered
    return buffered


def _prewarm_relation_coverage_cache(
    relation_props: list[dict[str, Any]],
    *,
    road_index: "_RoadIndex",
    coverage_cache: CoverageCache,
    signature_cache: RoadSignatureCache,
    swsd_segment_by_id: dict[str, dict[str, Any]] | None = None,
    swsd_road_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    if isinstance(coverage_cache, _ReusableCoverageCache) and swsd_segment_by_id is not None:
        _prewarm_relation_uncovered_metrics(
            relation_props,
            road_index=road_index,
            coverage_cache=coverage_cache,
            signature_cache=signature_cache,
            swsd_segment_by_id=swsd_segment_by_id,
            swsd_road_by_id=swsd_road_by_id or {},
        )
        return
    buffer_sizes = (
        SEGMENT_ROAD_COVERAGE_BUFFER_M,
        SEGMENT_COVERAGE_BUFFER_M,
        SEGMENT_CORRIDOR_BUFFER_M,
    )
    unions_by_signature: dict[RoadSignature, BaseGeometry] = {}
    seen_signatures: set[RoadSignature] = set()
    for props in relation_props:
        roads = _relation_roads(props, road_index)
        signature = _road_signature(roads, signature_cache=signature_cache)
        if not signature or signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        if all((float(buffer_m), signature) in coverage_cache for buffer_m in buffer_sizes):
            continue
        road_geometries = [
            line
            for road in roads
            for line in [_feature_line(road)]
            if line is not None and not line.is_empty
        ]
        if road_geometries:
            unions_by_signature[signature] = unary_union(road_geometries)
    if not unions_by_signature:
        return

    signatures = list(unions_by_signature)
    unions = [unions_by_signature[signature] for signature in signatures]
    for buffer_m in buffer_sizes:
        pending = [
            (signature, geometry)
            for signature, geometry in zip(signatures, unions)
            if (float(buffer_m), signature) not in coverage_cache
        ]
        if not pending:
            continue
        buffered = vectorized_buffer(
            [geometry for _, geometry in pending],
            buffer_m,
            quad_segs=16,
        )
        for (signature, _), geometry in zip(pending, buffered):
            coverage_cache[(float(buffer_m), signature)] = geometry


def _prewarm_relation_uncovered_metrics(
    relation_props: list[dict[str, Any]],
    *,
    road_index: "_RoadIndex",
    coverage_cache: _ReusableCoverageCache,
    signature_cache: RoadSignatureCache,
    swsd_segment_by_id: dict[str, dict[str, Any]],
    swsd_road_by_id: dict[str, dict[str, Any]],
) -> None:
    tasks_by_signature: dict[
        RoadSignature,
        tuple[list[dict[str, Any]], dict[UncoveredMetricKey, BaseGeometry]],
    ] = {}

    def add_metric_tasks(
        feature_item: dict[str, Any] | None,
        *,
        road_signature: RoadSignature,
        task_by_key: dict[UncoveredMetricKey, BaseGeometry],
        buffer_sizes: tuple[float, ...],
    ) -> None:
        geometry = _feature_line(feature_item or {})
        if geometry is None or geometry.is_empty or geometry.length <= 0:
            return
        for buffer_m in buffer_sizes:
            key = _uncovered_metric_key(
                geometry,
                buffer_m=buffer_m,
                road_signature=road_signature,
            )
            if key not in coverage_cache.uncovered_metrics:
                task_by_key[key] = geometry

    for props in relation_props:
        roads = _relation_roads(props, road_index)
        signature = _road_signature(roads, signature_cache=signature_cache)
        _, task_by_key = tasks_by_signature.setdefault(signature, (roads, {}))
        segment_id = str(props.get("swsd_segment_id") or "")
        segment = swsd_segment_by_id.get(segment_id)
        add_metric_tasks(
            segment,
            road_signature=signature,
            task_by_key=task_by_key,
            buffer_sizes=(SEGMENT_COVERAGE_BUFFER_M, SEGMENT_CORRIDOR_BUFFER_M),
        )
        if str(props.get("relation_status") or "") in {"", "failed", "retained_swsd"}:
            continue
        segment_props = dict((segment or {}).get("properties") or {})
        semantic_node_ids = set(
            unique_preserve_order(
                [
                    *_as_id_list(segment_props.get("pair_nodes")),
                    *_as_id_list(segment_props.get("junc_nodes")),
                ]
            )
        )
        road_ids = _as_id_list(props.get("swsd_road_ids")) or _as_id_list(segment_props.get("roads"))
        for road_id in road_ids:
            swsd_road = swsd_road_by_id.get(road_id)
            endpoints = _road_endpoint_node_ids(swsd_road or {})
            if len(endpoints) < 2 or not all(endpoint in semantic_node_ids for endpoint in endpoints[:2]):
                continue
            add_metric_tasks(
                swsd_road,
                road_signature=signature,
                task_by_key=task_by_key,
                buffer_sizes=(SEGMENT_ROAD_COVERAGE_BUFFER_M, SEGMENT_CORRIDOR_BUFFER_M),
            )

    entries = list(tasks_by_signature.items())
    for start in range(0, len(entries), _METRIC_PREWARM_BATCH_SIZE):
        union_entries: list[
            tuple[RoadSignature, dict[UncoveredMetricKey, BaseGeometry], BaseGeometry]
        ] = []
        for signature, (roads, task_by_key) in entries[start : start + _METRIC_PREWARM_BATCH_SIZE]:
            road_geometries = [
                geometry
                for road in roads
                for geometry in [_feature_line(road)]
                if geometry is not None and not geometry.is_empty
            ]
            if not road_geometries:
                for key, geometry in task_by_key.items():
                    _remember_uncovered_metric(
                        coverage_cache.uncovered_metrics,
                        key,
                        (1.0, float(geometry.length)),
                    )
                continue
            union_entries.append((signature, task_by_key, unary_union(road_geometries)))
        for buffer_m in (
            SEGMENT_ROAD_COVERAGE_BUFFER_M,
            SEGMENT_COVERAGE_BUFFER_M,
            SEGMENT_CORRIDOR_BUFFER_M,
        ):
            pending = [
                (task_by_key, union_geometry)
                for _, task_by_key, union_geometry in union_entries
                if any(key[1] == float(buffer_m) for key in task_by_key)
            ]
            if not pending:
                continue
            buffered_unions = vectorized_buffer(
                [union_geometry for _, union_geometry in pending],
                buffer_m,
                quad_segs=16,
            )
            for (task_by_key, _), buffered_union in zip(pending, buffered_unions):
                for key, geometry in task_by_key.items():
                    if key[1] != float(buffer_m):
                        continue
                    uncovered_length = float(geometry.difference(buffered_union).length)
                    _remember_uncovered_metric(
                        coverage_cache.uncovered_metrics,
                        key,
                        (uncovered_length / float(geometry.length), uncovered_length),
                    )


def _uncovered_metric_key(
    geometry: BaseGeometry,
    *,
    buffer_m: float,
    road_signature: RoadSignature,
) -> UncoveredMetricKey:
    return (
        hashlib.blake2b(geometry.wkb, digest_size=16).hexdigest(),
        float(buffer_m),
        road_signature,
    )


def _remember_uncovered_metric(
    metric_cache: dict[UncoveredMetricKey, UncoveredMetric],
    key: UncoveredMetricKey,
    value: UncoveredMetric,
) -> None:
    if key in metric_cache or len(metric_cache) >= _MAX_UNCOVERED_METRICS:
        return
    metric_cache[key] = value


def _road_buffer_cache_key(
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
    road_signature_cache: RoadSignatureCache | None = None,
) -> CoverageCacheKey:
    return float(buffer_m), _road_signature(roads, signature_cache=road_signature_cache)


def _road_signature(
    roads: list[dict[str, Any]],
    *,
    signature_cache: RoadSignatureCache | None,
) -> RoadSignature:
    identity_key = tuple(id(road) for road in roads)
    if signature_cache is not None:
        cached = signature_cache.get(identity_key)
        if cached is not None and len(cached[0]) == len(roads) and all(
            cached_road is road for cached_road, road in zip(cached[0], roads)
        ):
            return cached[1]
    signature = tuple(
        sorted(
            (
                _source_text((road.get("properties") or {}).get("source")),
                _feature_id(road),
                _feature_line_digest(road),
            )
            for road in roads
        )
    )
    if signature_cache is not None:
        signature_cache[identity_key] = (tuple(roads), signature)
    return signature


def _feature_line_digest(feature_item: dict[str, Any]) -> str:
    line = _feature_line(feature_item)
    if line is None or line.is_empty:
        return ""
    return hashlib.blake2b(line.wkb, digest_size=16).hexdigest()


def _segment_nearby_uncovered_metrics(
    segment: dict[str, Any] | None,
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
    road_spatial_index: _RoadLineSpatialIndex | None = None,
) -> tuple[float | None, float | None]:
    segment_geometry = (segment or {}).get("geometry")
    if not isinstance(segment_geometry, BaseGeometry) or segment_geometry.is_empty or segment_geometry.length <= 0:
        return None, None
    search_geometry = segment_geometry.buffer(buffer_m)
    if road_spatial_index is not None:
        road_geometries = road_spatial_index.query_intersecting(search_geometry)
    else:
        segment_bounds = search_geometry.bounds
        road_geometries = []
        for road in roads:
            line = _feature_line(road)
            if line is None or line.is_empty:
                continue
            if not _bounds_intersect(segment_bounds, line.bounds):
                continue
            if line.intersects(search_geometry):
                road_geometries.append(line)
    if not road_geometries:
        return 1.0, float(segment_geometry.length)
    road_union = unary_union(road_geometries)
    uncovered = segment_geometry.difference(road_union.buffer(buffer_m))
    length = float(uncovered.length)
    return length / float(segment_geometry.length), length


def _coverage_failed(ratio: float | None, length: float | None) -> bool:
    if ratio is None or length is None:
        return False
    return ratio > SEGMENT_MAX_UNCOVERED_RATIO and length > SEGMENT_MIN_UNCOVERED_LENGTH_M


def _coverage_manual_review(ratio: float | None, length: float | None) -> bool:
    if ratio is None or length is None:
        return False
    return (
        ratio <= SEGMENT_CORRIDOR_MANUAL_REVIEW_MAX_UNCOVERED_RATIO
        and length > SEGMENT_MIN_UNCOVERED_LENGTH_M
    )


def _bounds_intersect(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _reachable_any(graph: dict[str, set[str]], starts: list[str], targets: list[str]) -> bool:
    target_set = set(targets)
    if not starts or not target_set:
        return False
    queue = deque(starts)
    seen = set(starts)
    while queue:
        node = queue.popleft()
        if node in target_set:
            return True
        for next_node in graph.get(node, set()):
            if next_node in seen:
                continue
            seen.add(next_node)
            queue.append(next_node)
    return False


def _undirected_component_index(graph: dict[str, set[str]]) -> dict[str, str]:
    component_by_node: dict[str, str] = {}
    for start in graph:
        if start in component_by_node:
            continue
        queue = deque([start])
        component_by_node[start] = start
        while queue:
            node = queue.popleft()
            for next_node in graph.get(node, set()):
                if next_node in component_by_node:
                    continue
                component_by_node[next_node] = start
                queue.append(next_node)
    return component_by_node


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return unique_preserve_order(result)


def _road_endpoint_node_id_pair(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return result


def _road_endpoint_points(road: dict[str, Any]) -> list[Point]:
    line = _feature_line(road)
    if line is None or line.is_empty:
        return []
    coords = list(line.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _max_endpoint_node_distance(
    *,
    source: str,
    endpoints: list[str],
    endpoint_points: list[Point],
    node_index: "_NodeIndex",
) -> float | None:
    distances: list[float] = []
    for node_id, endpoint_point in zip(endpoints[:2], endpoint_points[:2]):
        node = node_index.exact_node(source, node_id)
        geometry = node.get("geometry") if node is not None else None
        if isinstance(geometry, Point):
            distances.append(float(endpoint_point.distance(geometry)))
    return max(distances) if distances else None


def _feature_line(feature_value: dict[str, Any] | None) -> LineString | None:
    if feature_value is None:
        return None
    geometry = feature_value.get("geometry")
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        parts = [item for item in geometry.geoms if isinstance(item, LineString)]
        return max(parts, key=lambda item: item.length) if parts else None
    if hasattr(geometry, "geoms"):
        parts = [item for item in geometry.geoms if isinstance(item, LineString)]
        return max(parts, key=lambda item: item.length) if parts else None
    return None


def _as_id_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _is_replaced_relation(props: dict[str, Any] | None) -> bool:
    if props is None:
        return False
    return str(props.get("relation_status") or "") != "retained_swsd"


def _is_group_path_corridor_relation(props: dict[str, Any]) -> bool:
    return (
        props.get("relation_reason") == "group_path_corridor_replacement"
        or "group_path_corridor_replacement" in _as_id_list(props.get("risk_flags"))
    )


def _max_pairwise_distance(points: list[Point]) -> float | None:
    if len(points) < 2:
        return 0.0 if points else None
    return max(float(a.distance(b)) for a, b in combinations(points, 2))


def _points_geometry(points: list[Point]) -> Point | MultiPoint | None:
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    return MultiPoint(points)


def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))


def _source_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _safe_text(value: Any) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    return str(value)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _round_length(value: float | None) -> float | None:
    return round(float(value), 3) if value is not None else None


def _round_ratio(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _id_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
