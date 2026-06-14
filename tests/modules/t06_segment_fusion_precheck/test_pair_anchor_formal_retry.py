from __future__ import annotations

from shapely.geometry import GeometryCollection, LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_only_probe import BufferOnlyProbeResult
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentResult,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.pair_anchor_formal_retry import pair_anchor_formal_retry
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationCheck
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.single_graph_connectivity_retry import (
    SingleGraphConnectivityRetryOutcome,
)


def test_multi_anchor_formal_retry_accepts_unique_reversed_candidate() -> None:
    outcome = pair_anchor_formal_retry(
        probe_result=_probe([["A", "B"], ["C", "D"]]),
        relation=RelationCheck(False, [], [], reject_reason="invalid_pair_relation_status"),
        failure_business_category="multi_anchor_ambiguous",
        source_reject_reason="invalid_pair_relation_status",
        pair_nodes=["s1", "s2"],
        relation_junc_nodes=[],
        junc_kind2_exempt_nodes=[],
        relation_map={},
        segment_geometry=LineString([(0, 0), (100, 0)]),
        sgrade="0-1单",
        directionality="single",
        directed_swsd_pair_nodes=["s1", "s2"],
        buffer_extractor=_FakeExtractor({("B", "A")}),
        graph_retry=_NoGraphRetry(),
        buffer_config=BufferExtractionConfig(),
        all_base_ids_for_segment=set(),
        unexpected_base_ids_for_segment=set(),
        rcsd_graph_edges=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        max_path_to_swsd_length_ratio=2.5,
        allow_multi_anchor_ambiguous=True,
    )

    assert outcome is not None
    assert outcome.relation.rcsd_pair_nodes == ["B", "A"]
    assert outcome.buffer_result.directed_rcsd_pair_nodes == ["B", "A"]


def test_multi_anchor_formal_retry_rejects_multiple_valid_candidates() -> None:
    outcome = pair_anchor_formal_retry(
        probe_result=_probe([["A", "B"], ["C", "D"]]),
        relation=RelationCheck(False, [], [], reject_reason="invalid_pair_relation_status"),
        failure_business_category="multi_anchor_ambiguous",
        source_reject_reason="invalid_pair_relation_status",
        pair_nodes=["s1", "s2"],
        relation_junc_nodes=[],
        junc_kind2_exempt_nodes=[],
        relation_map={},
        segment_geometry=LineString([(0, 0), (100, 0)]),
        sgrade="0-1单",
        directionality="single",
        directed_swsd_pair_nodes=["s1", "s2"],
        buffer_extractor=_FakeExtractor({("B", "A"), ("D", "C")}),
        graph_retry=_NoGraphRetry(),
        buffer_config=BufferExtractionConfig(),
        all_base_ids_for_segment=set(),
        unexpected_base_ids_for_segment=set(),
        rcsd_graph_edges=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        max_path_to_swsd_length_ratio=2.5,
        allow_multi_anchor_ambiguous=True,
    )

    assert outcome is None


def test_multi_anchor_formal_retry_filters_orientation_with_reversed_endpoint_side() -> None:
    outcome = pair_anchor_formal_retry(
        probe_result=_probe([["A", "B"], ["C", "D"]]),
        relation=RelationCheck(False, [], [], reject_reason="invalid_pair_relation_status"),
        failure_business_category="multi_anchor_ambiguous",
        source_reject_reason="invalid_pair_relation_status",
        pair_nodes=["s1", "s2"],
        relation_junc_nodes=[],
        junc_kind2_exempt_nodes=[],
        relation_map={},
        segment_geometry=LineString([(0, 0), (100, 0)]),
        sgrade="0-1单",
        directionality="single",
        directed_swsd_pair_nodes=["s1", "s2"],
        buffer_extractor=_FakeExtractorWithNodes(
            {("B", "A"), ("C", "D")},
            {
                "B": Point(0, 0),
                "A": Point(100, 0),
                "C": Point(90, 0),
                "D": Point(10, 0),
            },
        ),
        graph_retry=_NoGraphRetry(),
        buffer_config=BufferExtractionConfig(),
        all_base_ids_for_segment=set(),
        unexpected_base_ids_for_segment=set(),
        rcsd_graph_edges=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        max_path_to_swsd_length_ratio=2.5,
        allow_multi_anchor_ambiguous=True,
    )

    assert outcome is not None
    assert outcome.relation.rcsd_pair_nodes == ["B", "A"]


def test_multi_anchor_formal_retry_requires_explicit_enablement() -> None:
    outcome = pair_anchor_formal_retry(
        probe_result=_probe([["A", "B"]]),
        relation=RelationCheck(False, [], [], reject_reason="invalid_pair_relation_status"),
        failure_business_category="multi_anchor_ambiguous",
        source_reject_reason="invalid_pair_relation_status",
        pair_nodes=["s1", "s2"],
        relation_junc_nodes=[],
        junc_kind2_exempt_nodes=[],
        relation_map={},
        segment_geometry=LineString([(0, 0), (100, 0)]),
        sgrade="0-1单",
        directionality="single",
        directed_swsd_pair_nodes=["s1", "s2"],
        buffer_extractor=_FakeExtractor({("B", "A")}),
        graph_retry=_NoGraphRetry(),
        buffer_config=BufferExtractionConfig(),
        all_base_ids_for_segment=set(),
        unexpected_base_ids_for_segment=set(),
        rcsd_graph_edges=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        max_path_to_swsd_length_ratio=2.5,
    )

    assert outcome is None


def test_directionality_mismatch_formal_retry_uses_single_graph_first_path() -> None:
    outcome = pair_anchor_formal_retry(
        probe_result=_corridor_probe([["A", "B"]]),
        relation=RelationCheck(True, ["X", "Y"], [], reject_reason=""),
        failure_business_category="directionality_mismatch_fixable",
        source_reject_reason="rcsd_directed_path_missing",
        pair_nodes=["s1", "s2"],
        relation_junc_nodes=[],
        junc_kind2_exempt_nodes=[],
        relation_map={},
        segment_geometry=LineString([(0, 0), (100, 0)]),
        sgrade="0-1单",
        directionality="single",
        directed_swsd_pair_nodes=["s1", "s2"],
        buffer_extractor=_FakeExtractor(set()),
        graph_retry=_FakeGraphRetry({("B", "A")}),
        buffer_config=BufferExtractionConfig(),
        all_base_ids_for_segment=set(),
        unexpected_base_ids_for_segment=set(),
        rcsd_graph_edges=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        max_path_to_swsd_length_ratio=2.5,
    )

    assert outcome is not None
    assert outcome.relation.rcsd_pair_nodes == ["B", "A"]
    assert outcome.buffer_result.directed_rcsd_pair_nodes == ["B", "A"]
    assert outcome.adaptive_source_reason == "single_graph_first_longitudinal_retry:rcsd_directed_path_missing"


class _FakeExtractor:
    def __init__(self, passing_pairs: set[tuple[str, str]]) -> None:
        self.passing_pairs = passing_pairs

    def extract(self, **kwargs: object) -> BufferSegmentResult:
        relation = kwargs["relation"]
        pair = tuple(relation.rcsd_pair_nodes)
        ok = pair in self.passing_pairs
        return _buffer_result(
            ok=ok,
            reason="ok" if ok else "rcsd_directed_path_missing",
            pair=list(pair),
            directed_pair=list(kwargs.get("directed_pair_nodes") or []),
        )


class _FakeExtractorWithNodes(_FakeExtractor):
    def __init__(self, passing_pairs: set[tuple[str, str]], node_points: dict[str, Point]) -> None:
        super().__init__(passing_pairs)
        features = [{"properties": {"id": node_id}, "geometry": point} for node_id, point in node_points.items()]
        self.node_index = _NodeIndex(features)
        self.node_canonicalizer = NodeCanonicalizer.from_node_features(features)


class _NodeIndex:
    def __init__(self, features: list[dict[str, object]]) -> None:
        self.features = features


class _NoGraphRetry:
    def retry(self, *args: object, **kwargs: object) -> None:
        return None


class _FakeGraphRetry:
    def __init__(self, passing_pairs: set[tuple[str, str]]) -> None:
        self.passing_pairs = passing_pairs

    def retry(self, **kwargs: object) -> SingleGraphConnectivityRetryOutcome | None:
        relation = kwargs["relation"]
        pair = tuple(relation.rcsd_pair_nodes)
        if pair not in self.passing_pairs:
            return None
        directed_pair = list(kwargs.get("directed_pair_nodes") or [])
        return SingleGraphConnectivityRetryOutcome(
            buffer_result=_buffer_result(
                ok=True,
                reason="ok",
                pair=list(pair),
                directed_pair=directed_pair,
            ),
            reference_distance_m=75.0,
            source_reason="single_graph_first_longitudinal_retry:rcsd_directed_path_missing",
            path_length_m=100.0,
            base_buffer_overlap_length_m=50.0,
            base_buffer_overlap_ratio=0.5,
            path_to_swsd_length_ratio=1.0,
        )


def _probe(candidate_pairs: list[list[str]]) -> BufferOnlyProbeResult:
    return BufferOnlyProbeResult(
        status="ambiguous_corridor",
        candidate_pair_sets=candidate_pairs,
        candidate_score=0.96,
        geometry_overlap_ratio=0.90,
        directionality_score=1.0,
        connectivity_score=1.0,
        shape_similarity_score=0.96,
        candidate_road_ids=[],
        candidate_node_ids=[],
        candidate_component_count=len(candidate_pairs),
        manual_review_required=False,
        repair_recommendation="manual_multi_anchor_review",
        geometry=GeometryCollection(),
        notes="",
    )


def _corridor_probe(candidate_pairs: list[list[str]]) -> BufferOnlyProbeResult:
    return BufferOnlyProbeResult(
        status="corridor_found",
        candidate_pair_sets=candidate_pairs,
        candidate_score=0.90,
        geometry_overlap_ratio=0.74,
        directionality_score=1.0,
        connectivity_score=1.0,
        shape_similarity_score=0.95,
        candidate_road_ids=[],
        candidate_node_ids=[],
        candidate_component_count=1,
        manual_review_required=False,
        repair_recommendation="high_confidence_pair_anchor_candidate",
        geometry=GeometryCollection(),
        notes="",
    )


def _buffer_result(*, ok: bool, reason: str, pair: list[str], directed_pair: list[str]) -> BufferSegmentResult:
    return BufferSegmentResult(
        ok=ok,
        reason=reason,
        required_rcsd_nodes=pair,
        optional_allowed_rcsd_nodes=[],
        directed_rcsd_pair_nodes=directed_pair,
        candidate_road_ids=[],
        candidate_node_ids=pair,
        retained_road_ids=[],
        excluded_advance_right_turn_road_ids=[],
        retained_node_ids=pair if ok else [],
        inner_node_ids=[],
        out_node_ids=[],
        unexpected_endpoint_node_ids=[],
        unexpected_mapped_semantic_node_ids=[],
        low_buffer_overlap_road_ids=[],
        min_retained_road_buffer_overlap_ratio=None,
        geometry_buffer_coverage_issue=None,
        rcsd_outside_swsd_buffer_length_m=0.0,
        rcsd_outside_swsd_buffer_ratio=0.0,
        swsd_uncovered_by_rcsd_length_m=0.0,
        swsd_uncovered_by_rcsd_ratio=0.0,
        missing_required_node_ids=[],
        selected_component_id=None,
        candidate_road_count=0,
        retained_road_count=0,
        candidate_node_count=len(pair),
        retained_node_count=len(pair) if ok else 0,
        geometry=GeometryCollection(),
    )
