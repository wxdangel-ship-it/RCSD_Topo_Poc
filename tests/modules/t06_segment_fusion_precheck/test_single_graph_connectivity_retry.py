from __future__ import annotations

from shapely.geometry import GeometryCollection, LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentResult,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationCheck
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.single_graph_connectivity_retry import (
    DUAL_GRAPH_FIRST_RETRY_RECOMMENDATION,
    LONGITUDINAL_RETRY_RECOMMENDATION,
    SingleGraphConnectivityRetry,
)


def test_single_graph_retry_keeps_original_pair_and_uses_50m_core() -> None:
    retry = SingleGraphConnectivityRetry(
        rcsd_road_features=[
            {
                "properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 2},
                "geometry": LineString([(0, 0), (100, 80)]),
            }
        ],
        rcsd_node_features=_nodes([10, 20]),
    )

    outcome = retry.retry(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        set(),
        ["10", "20"],
        "0-1单",
        "single",
        _failed_result("retained_geometry_outside_swsd_buffer_scope"),
        {},
        BufferExtractionConfig(),
        2.5,
    )

    assert outcome is not None
    assert outcome.buffer_result.retained_road_ids == ["rr1"]
    assert outcome.buffer_result.directed_rcsd_pair_nodes == ["10", "20"]
    assert outcome.reference_distance_m == 75.0
    assert outcome.source_reason == f"{LONGITUDINAL_RETRY_RECOMMENDATION}:retained_geometry_outside_swsd_buffer_scope"
    assert outcome.base_buffer_overlap_length_m >= 50.0

    directed_missing_outcome = retry.retry(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        set(),
        ["10", "20"],
        "0-1单",
        "single",
        _failed_result("rcsd_directed_path_missing"),
        {"full_graph_status": "required_nodes_connected", "directional_status": "full=directed_path_present;candidate=directed_path_missing"},
        BufferExtractionConfig(),
        2.5,
    )

    assert directed_missing_outcome is not None
    assert directed_missing_outcome.source_reason == f"{LONGITUDINAL_RETRY_RECOMMENDATION}:rcsd_directed_path_missing"

    missing_required_node_outcome = retry.retry(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        set(),
        ["10", "20"],
        "0-1单",
        "single",
        _failed_result("required_semantic_nodes_missing_from_buffer_graph"),
        {"full_graph_status": "required_nodes_connected", "directional_status": "full=directed_path_present;candidate=directed_path_missing"},
        BufferExtractionConfig(),
        2.5,
    )

    assert missing_required_node_outcome is not None
    assert missing_required_node_outcome.source_reason == (
        f"{LONGITUDINAL_RETRY_RECOMMENDATION}:required_semantic_nodes_missing_from_buffer_graph"
    )


def test_single_graph_retry_rejects_long_detour_even_when_path_touches_50m_buffer() -> None:
    retry = SingleGraphConnectivityRetry(
        rcsd_road_features=[
            {
                "properties": {"id": "rr_core", "snodeid": 10, "enodeid": 11, "direction": 2},
                "geometry": LineString([(0, 0), (50, 0)]),
            },
            {
                "properties": {"id": "rr_detour", "snodeid": 11, "enodeid": 20, "direction": 2},
                "geometry": LineString([(50, 0), (1000, 0)]),
            },
        ],
        rcsd_node_features=_nodes([10, 11, 20]),
    )

    outcome = retry.retry(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        set(),
        ["10", "20"],
        "0-1单",
        "single",
        _failed_result("required_semantic_nodes_not_connected_in_buffer"),
        {"full_graph_status": "required_nodes_connected", "directional_status": "full=directed_path_present;candidate=directed_path_missing"},
        BufferExtractionConfig(),
        2.5,
    )

    assert outcome is None


def test_single_graph_retry_does_not_bypass_required_junction_nodes() -> None:
    retry = SingleGraphConnectivityRetry(
        rcsd_road_features=[
            {
                "properties": {"id": "direct", "snodeid": 10, "enodeid": 20, "direction": 2},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"id": "junc_stub", "snodeid": 10, "enodeid": 30, "direction": 2},
                "geometry": LineString([(0, 0), (50, 10)]),
            },
        ],
        rcsd_node_features=_nodes([10, 20, 30]),
    )

    outcome = retry.retry(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], ["30"]),
        [],
        set(),
        ["10", "20"],
        "0-1单",
        "single",
        _failed_result("retained_geometry_outside_swsd_buffer_scope"),
        {},
        BufferExtractionConfig(),
        2.5,
    )

    assert outcome is None


def test_dual_graph_retry_keeps_two_directed_corridors_that_cross_50m_core() -> None:
    retry = SingleGraphConnectivityRetry(
        rcsd_road_features=[
            {"properties": {"id": "f1", "snodeid": 10, "enodeid": 11, "direction": 2}, "geometry": LineString([(0, 0), (50, 0)])},
            {"properties": {"id": "f2", "snodeid": 11, "enodeid": 20, "direction": 2}, "geometry": LineString([(50, 0), (100, 0)])},
            {"properties": {"id": "r1", "snodeid": 20, "enodeid": 12, "direction": 2}, "geometry": LineString([(100, 40), (50, 40)])},
            {"properties": {"id": "r2", "snodeid": 12, "enodeid": 10, "direction": 2}, "geometry": LineString([(50, 40), (0, 40)])},
        ],
        rcsd_node_features=_nodes([10, 11, 12, 20]),
    )

    outcome = retry.retry_dual_bidirectional(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        set(),
        "0-0双",
        _failed_result("rcsd_not_bidirectional_for_swsd_dual"),
        {"full_graph_status": "required_nodes_connected", "directional_status": "full=bidirectional;candidate=forward_only"},
        BufferExtractionConfig(),
        2.5,
    )

    assert outcome is not None
    assert set(outcome.buffer_result.retained_road_ids) == {"f1", "f2", "r1", "r2"}
    assert outcome.buffer_result.directed_rcsd_pair_nodes == []
    assert outcome.source_reason == f"{DUAL_GRAPH_FIRST_RETRY_RECOMMENDATION}:rcsd_not_bidirectional_for_swsd_dual"


def test_dual_graph_retry_avoids_external_semantic_nodes_when_clean_path_exists() -> None:
    retry = SingleGraphConnectivityRetry(
        rcsd_road_features=[
            {"properties": {"id": "dirty_a", "snodeid": 10, "enodeid": 30, "direction": 2}, "geometry": LineString([(0, 0), (50, 0)])},
            {"properties": {"id": "dirty_b", "snodeid": 30, "enodeid": 20, "direction": 2}, "geometry": LineString([(50, 0), (100, 0)])},
            {"properties": {"id": "clean_a", "snodeid": 10, "enodeid": 11, "direction": 2}, "geometry": LineString([(0, 10), (50, 10)])},
            {"properties": {"id": "clean_b", "snodeid": 11, "enodeid": 20, "direction": 2}, "geometry": LineString([(50, 10), (100, 10)])},
            {"properties": {"id": "reverse_a", "snodeid": 20, "enodeid": 12, "direction": 2}, "geometry": LineString([(100, 20), (50, 20)])},
            {"properties": {"id": "reverse_b", "snodeid": 12, "enodeid": 10, "direction": 2}, "geometry": LineString([(50, 20), (0, 20)])},
        ],
        rcsd_node_features=_nodes([10, 11, 12, 20, 30]),
    )

    outcome = retry.retry_dual_bidirectional(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        {"30"},
        "0-0双",
        _failed_result("rcsd_not_bidirectional_for_swsd_dual"),
        {"full_graph_status": "required_nodes_connected", "directional_status": "full=bidirectional;candidate=reverse_only"},
        BufferExtractionConfig(),
        2.5,
    )

    assert outcome is not None
    assert set(outcome.buffer_result.retained_road_ids) == {"clean_a", "clean_b", "reverse_a", "reverse_b"}
    assert outcome.buffer_result.unexpected_mapped_semantic_node_ids == []


def test_dual_graph_retry_rejects_reverse_detour_over_length_ratio() -> None:
    retry = SingleGraphConnectivityRetry(
        rcsd_road_features=[
            {"properties": {"id": "f1", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])},
            {"properties": {"id": "r1", "snodeid": 20, "enodeid": 30, "direction": 2}, "geometry": LineString([(100, 0), (1000, 0)])},
            {"properties": {"id": "r2", "snodeid": 30, "enodeid": 10, "direction": 2}, "geometry": LineString([(1000, 0), (0, 0)])},
        ],
        rcsd_node_features=_nodes([10, 20, 30]),
    )

    outcome = retry.retry_dual_bidirectional(
        LineString([(0, 0), (100, 0)]),
        RelationCheck(True, ["10", "20"], []),
        [],
        set(),
        "0-0双",
        _failed_result("rcsd_not_bidirectional_for_swsd_dual"),
        {"full_graph_status": "required_nodes_connected", "directional_status": "full=bidirectional;candidate=forward_only"},
        BufferExtractionConfig(),
        2.5,
    )

    assert outcome is None


def _nodes(node_ids: list[int]) -> list[dict[str, object]]:
    return [{"properties": {"id": node_id}, "geometry": Point(float(node_id), 0.0)} for node_id in node_ids]


def _failed_result(reason: str) -> BufferSegmentResult:
    return BufferSegmentResult(
        ok=False,
        reason=reason,
        required_rcsd_nodes=["10", "20"],
        optional_allowed_rcsd_nodes=[],
        directed_rcsd_pair_nodes=["10", "20"],
        candidate_road_ids=[],
        candidate_node_ids=[],
        retained_road_ids=[],
        excluded_advance_right_turn_road_ids=[],
        retained_node_ids=[],
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
        candidate_node_count=0,
        retained_node_count=0,
        geometry=GeometryCollection(),
    )
