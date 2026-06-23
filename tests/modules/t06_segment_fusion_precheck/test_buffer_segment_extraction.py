from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.adaptive_buffer_retry import (
    high_grade_adaptive_buffer_retry_plan,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentExtractor,
    is_advance_right_turn_road,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationCheck


def _road(road_id: str, snode: int, enode: int, coords: list[tuple[float, float]], **props):
    payload = {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": 0}
    payload.update(props)
    return {"properties": payload, "geometry": LineString(coords)}


def _node(node_id: int, x: float, y: float, *, mainnodeid: int = 0, subnodeid=None, kind: int = 0):
    return {
        "properties": {"id": node_id, "mainnodeid": mainnodeid, "subnodeid": subnodeid if subnodeid is not None else [], "kind": kind},
        "geometry": Point(x, y),
    }


def test_advance_right_turn_uses_formway_bit() -> None:
    assert is_advance_right_turn_road({"formway": 128})
    assert is_advance_right_turn_road({"formway": 129})
    assert is_advance_right_turn_road({"formway": 384})
    assert not is_advance_right_turn_road({"formway": 256})
    assert not is_advance_right_turn_road({})


def test_buffer_extraction_keeps_intersecting_roads_and_excludes_advance_right() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (100, 0)]),
            _road("right_turn", 10, 99, [(0, 0), (0, -20)], formway=128),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0), _node(99, 0, -20)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2, min_road_overlap_length_m=1.0),
    )

    assert result.ok
    assert result.retained_road_ids == ["main_a", "main_b"]
    assert set(result.candidate_node_ids) == {"10", "20", "30"}
    assert result.excluded_advance_right_turn_road_ids == ["right_turn"]
    assert result.required_rcsd_nodes == ["10", "20"]
    assert result.optional_allowed_rcsd_nodes == ["30"]


def test_buffer_extraction_prefers_reference_corridor_over_shortcut() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("corridor_a", 10, 30, [(0, 0), (50, 20)], direction=2),
            _road("corridor_b", 30, 20, [(50, 20), (100, 0)], direction=2),
            _road("shortcut", 10, 20, [(0, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 20)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (50, 20), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=50, min_road_overlap_ratio=0.2, min_road_overlap_length_m=1.0),
    )

    assert result.ok
    assert result.retained_road_ids == ["corridor_a", "corridor_b"]


def test_retained_road_must_satisfy_buffer_overlap_ratio() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("detour", 10, 20, [(0, 0), (0, 100), (100, 100), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2, min_road_overlap_length_m=1.0),
    )

    assert not result.ok
    assert result.reason == "retained_road_buffer_overlap_insufficient"
    assert result.retained_road_ids == ["detour"]
    assert result.low_buffer_overlap_road_ids == ["detour"]
    assert result.min_retained_road_buffer_overlap_ratio is not None
    assert result.min_retained_road_buffer_overlap_ratio < 0.2


def test_retained_geometry_must_stay_inside_swsd_buffer_scope() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("overlong", 10, 20, [(0, 0), (100, 0), (180, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 180, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2),
    )

    assert not result.ok
    assert result.reason == "retained_geometry_outside_swsd_buffer_scope"
    assert result.geometry_buffer_coverage_issue == "retained_geometry_outside_swsd_buffer_scope"
    assert result.rcsd_outside_swsd_buffer_length_m > 30
    assert result.rcsd_outside_swsd_buffer_ratio > 0.1


def test_retained_geometry_rejects_absolute_outside_length_when_ratio_is_low() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("slightly_overlong", 10, 20, [(0, 0), (1035, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 1035, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (1000, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2),
    )

    assert not result.ok
    assert result.reason == "retained_geometry_outside_swsd_buffer_scope"
    assert result.rcsd_outside_swsd_buffer_length_m > 20
    assert result.rcsd_outside_swsd_buffer_ratio < 0.1


def test_retained_geometry_rejects_outside_ratio_when_length_is_low() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("slightly_overlong", 10, 20, [(0, 0), (125, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 125, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2),
    )

    assert not result.ok
    assert result.reason == "retained_geometry_outside_swsd_buffer_scope"
    assert result.rcsd_outside_swsd_buffer_length_m < 20
    assert result.rcsd_outside_swsd_buffer_ratio > 0.1


def test_swsd_geometry_must_be_covered_by_retained_rcsd_buffer_scope() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("too_short", 10, 20, [(0, 0), (50, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 50, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (150, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2),
    )

    assert not result.ok
    assert result.reason == "swsd_geometry_not_covered_by_retained_rcsd"
    assert result.geometry_buffer_coverage_issue == "swsd_geometry_not_covered_by_retained_rcsd"
    assert result.swsd_uncovered_by_rcsd_length_m > 30
    assert result.swsd_uncovered_by_rcsd_ratio > 0.1


def test_swsd_geometry_rejects_absolute_uncovered_length_when_ratio_is_low() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("slightly_short", 10, 20, [(0, 0), (965, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 965, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (1000, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2),
    )

    assert not result.ok
    assert result.reason == "swsd_geometry_not_covered_by_retained_rcsd"
    assert result.swsd_uncovered_by_rcsd_length_m > 20
    assert result.swsd_uncovered_by_rcsd_ratio < 0.1


def test_swsd_geometry_rejects_uncovered_ratio_when_length_is_low() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("slightly_short", 10, 20, [(0, 0), (75, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 75, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10, min_road_overlap_ratio=0.2),
    )

    assert not result.ok
    assert result.reason == "swsd_geometry_not_covered_by_retained_rcsd"
    assert result.swsd_uncovered_by_rcsd_length_m < 20
    assert result.swsd_uncovered_by_rcsd_ratio > 0.1


def test_visual_consistency_records_narrow_gap_without_rejecting() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("visually_short", 10, 20, [(0, 0), (70, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(
            buffer_distance_m=50,
            visual_consistency_buffer_distance_m=15,
            min_road_overlap_ratio=0.2,
        ),
    )

    assert result.ok
    assert result.reason == "passed"
    assert result.geometry_buffer_coverage_issue == "swsd_visual_continuity_not_covered_by_retained_rcsd"
    assert result.swsd_uncovered_by_rcsd_length_m < 20
    assert result.swsd_uncovered_by_rcsd_ratio > 0.1


def test_visual_consistency_records_retained_outside_without_rejecting_when_swsd_is_covered() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("with_local_detour", 10, 20, [(0, 0), (45, 0), (45, 30), (45, 0), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(
            buffer_distance_m=50,
            visual_consistency_buffer_distance_m=15,
            min_road_overlap_ratio=0.2,
        ),
    )

    assert result.ok
    assert result.reason == "passed"
    assert result.geometry_buffer_coverage_issue == "retained_geometry_outside_swsd_visual_consistency_scope"
    assert result.rcsd_outside_swsd_buffer_ratio > 0.1
    assert result.swsd_uncovered_by_rcsd_length_m == 0


def test_visual_consistency_retained_outside_is_audit_risk_when_base_scope_is_covered() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("offset", 10, 20, [(0, 30), (70, 30)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(
            buffer_distance_m=50,
            visual_consistency_buffer_distance_m=15,
            min_road_overlap_ratio=0.2,
        ),
    )

    assert result.ok
    assert result.reason == "passed"
    assert result.geometry_buffer_coverage_issue == "retained_geometry_outside_swsd_visual_consistency_scope"
    assert result.swsd_uncovered_by_rcsd_length_m > 20


def test_visual_consistency_failure_is_not_adaptive_retryable() -> None:
    plan = high_grade_adaptive_buffer_retry_plan(
        sgrade="0-1单",
        directionality="single",
        buffer_result=SimpleNamespace(reason="swsd_visual_continuity_not_covered_by_retained_rcsd"),
        diagnostic={
            "full_graph_status": "required_nodes_connected",
            "directional_status": "full=directed_path_present",
        },
        base_buffer_distance_m=50.0,
    )

    assert plan is None


def test_buffer_extraction_keeps_advance_right_when_second_degree_linked() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (40, 0)], direction=2),
            _road("advance_bridge", 30, 40, [(40, 0), (60, 0)], direction=2, formway=128),
            _road("main_b", 40, 20, [(60, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 40, 0), _node(40, 60, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.retained_road_ids == ["main_a", "advance_bridge", "main_b"]
    assert result.excluded_advance_right_turn_road_ids == []


def test_buffer_extraction_keeps_advance_right_when_required_corridor_bridge() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (35, 0)], direction=2),
            _road("advance_a", 30, 40, [(35, 0), (50, 0)], direction=2, formway=128),
            _road("advance_b", 40, 50, [(50, 0), (65, 0)], direction=2, formway=128),
            _road("main_b", 50, 20, [(65, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 35, 0),
            _node(40, 50, 0),
            _node(50, 65, 0),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"main_a", "advance_a", "advance_b", "main_b"}
    assert result.excluded_advance_right_turn_road_ids == []


def test_dual_buffer_extraction_restores_advance_right_for_reverse_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward", 10, 20, [(0, 0), (100, 0)], direction=2),
            _road("reverse_a", 20, 30, [(100, 2), (70, 2)], direction=2),
            _road("advance_reverse_b", 30, 40, [(70, 2), (30, 2)], direction=2, formway=128),
            _road("advance_reverse_c", 40, 10, [(30, 2), (0, 2)], direction=2, formway=128),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 70, 2), _node(40, 30, 2)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward", "reverse_a", "advance_reverse_b", "advance_reverse_c"}
    assert result.excluded_advance_right_turn_road_ids == []


def test_junc_kind2_optional_nodes_are_not_required() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[_road("main", 10, 20, [(0, 0), (100, 0)])],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30"],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.optional_allowed_rcsd_nodes == ["30"]
    assert result.missing_required_node_ids == []


def test_missing_optional_junc_nodes_do_not_fail_pair_component_coverage() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[_road("main", 10, 20, [(0, 0), (100, 0)])],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.required_rcsd_nodes == ["10", "20"]
    assert result.optional_allowed_rcsd_nodes == ["30"]
    assert result.missing_required_node_ids == []


def test_seed_pruning_allows_inner_extra_mapped_semantic_nodes_on_required_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        unexpected_relation_base_ids={"30"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.inner_node_ids == ["30"]
    assert result.out_node_ids == []
    assert result.retained_road_ids == ["main_a", "main_b"]
    assert result.unexpected_mapped_semantic_node_ids == []


def test_global_rcsd_semantic_node_without_relation_can_be_internal_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0, kind=4)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.inner_node_ids == ["30"]
    assert result.unexpected_mapped_semantic_node_ids == []


def test_dual_swsd_requires_bidirectional_rcsd_connectivity() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("oneway", 10, 20, [(0, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert not result.ok
    assert result.reason == "rcsd_not_bidirectional_for_swsd_dual"
    assert result.retained_road_ids == ["oneway"]


def test_dual_corridor_uses_complete_reverse_road_over_short_required_shortcut() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward", 10, 20, [(0, 0), (100, 0)], direction=2),
            _road("short_reverse_connector", 20, 10, [(95, 0), (100, 0)], direction=2),
            _road("full_reverse", 20, 10, [(100, 1), (0, 1)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.retained_road_ids == ["forward", "full_reverse"]


def test_dual_pruning_protects_both_directed_pair_corridors() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)], direction=2),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)], direction=2),
            _road("reverse_a", 20, 40, [(100, 2), (50, 2)], direction=2),
            _road("reverse_b", 40, 10, [(50, 2), (0, 2)], direction=2),
            _road("side", 30, 50, [(50, 0), (50, 20)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 50, 0, kind=4),
            _node(40, 50, 2, kind=4),
            _node(50, 50, 20, kind=4),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward_a", "forward_b", "reverse_a", "reverse_b"}
    assert result.inner_node_ids == ["30", "40"]
    assert result.out_node_ids == ["50"]


def test_dual_corridor_flattens_chained_mainnode_aliases_before_pruning() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward", 10, 20, [(0, 0), (100, 0)], direction=2),
            _road("reverse_a", 20, 30, [(100, 2), (60, 2)], direction=2),
            _road("reverse_b", 30, 31, [(60, 2), (40, 2)], direction=2),
            _road("reverse_c", 40, 10, [(40, 2), (0, 2)], direction=2),
            _road("side", 30, 50, [(60, 2), (60, 20)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0, mainnodeid=10),
            _node(20, 100, 0, mainnodeid=20),
            _node(30, 60, 2, kind=4),
            _node(31, 40, 2, mainnodeid=40),
            _node(40, 40, 2, mainnodeid=40, subnodeid=[31], kind=16),
            _node(50, 60, 20, kind=4),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30", "40"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40", "50"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward", "reverse_a", "reverse_b", "reverse_c"}
    assert "50" in result.out_node_ids


def test_dual_corridor_retains_internal_uturn_between_retained_nodes() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)], direction=2),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)], direction=2),
            _road("reverse_a", 20, 40, [(100, 2), (50, 2)], direction=2),
            _road("reverse_b", 40, 10, [(50, 2), (0, 2)], direction=2),
            _road("middle_uturn", 30, 40, [(50, 0), (50, 2)], direction=2, formway=1024),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0), _node(40, 50, 2)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward_a", "forward_b", "reverse_a", "reverse_b", "middle_uturn"}
    assert "middle_uturn" in result.retained_road_ids


def test_dual_corridor_retains_internal_non_uturn_edge_between_retained_nodes() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)], direction=2),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)], direction=2),
            _road("reverse_a", 20, 40, [(100, 2), (50, 2)], direction=2),
            _road("reverse_b", 40, 10, [(50, 2), (0, 2)], direction=2),
            _road("middle_link", 30, 40, [(50, 0), (50, 2)], direction=2, formway=1),
            _road("side_branch", 30, 50, [(50, 0), (50, 20)], direction=2, formway=1),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0), _node(40, 50, 2), _node(50, 50, 20)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward_a", "forward_b", "reverse_a", "reverse_b", "middle_link"}
    assert "side_branch" not in result.retained_road_ids


def test_single_swsd_requires_at_least_one_directed_pair_path() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("toward_start", 30, 10, [(50, 0), (0, 0)], direction=2),
            _road("toward_end", 30, 20, [(50, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert not result.ok
    assert result.reason == "rcsd_directed_path_missing"
    assert result.retained_road_ids == []


def test_single_corridor_uses_one_directed_path_covering_required_nodes() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("start", 10, 30, [(0, 0), (30, 0)], direction=2),
            _road("upper_a", 50, 30, [(30, 0), (50, 5)], direction=2),
            _road("upper_b", 40, 50, [(50, 5), (70, 0)], direction=2),
            _road("lower_a", 30, 60, [(30, 0), (50, -5)], direction=2),
            _road("lower_b", 60, 40, [(50, -5), (70, 0)], direction=2),
            _road("end", 40, 20, [(70, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 30, 0), _node(40, 70, 0), _node(50, 50, 5), _node(60, 50, -5)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30", "40"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40"},
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"start", "lower_a", "lower_b", "end"}
    assert not {"upper_a", "upper_b"} & set(result.retained_road_ids)
    assert result.retained_node_ids == ["10", "20", "30", "40", "60"]


def test_single_corridor_uses_supplied_directed_pair_order() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)], direction=2),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)], direction=2),
            _road("reverse_a", 20, 40, [(100, 2), (50, 2)], direction=2),
            _road("reverse_b", 40, 10, [(50, 2), (0, 2)], direction=2),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0), _node(40, 50, 2)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        directed_pair_nodes=["20", "10"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.directed_rcsd_pair_nodes == ["20", "10"]
    assert set(result.retained_road_ids) == {"reverse_a", "reverse_b"}
    assert not {"forward_a", "forward_b"} & set(result.retained_road_ids)


def test_corridor_construction_removes_closed_loop_noise() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (100, 0)]),
            _road("loop_a", 30, 40, [(50, 0), (50, 10)]),
            _road("loop_b", 40, 50, [(50, 10), (60, 10)]),
            _road("loop_c", 50, 30, [(60, 10), (50, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0), _node(40, 50, 10), _node(50, 60, 10)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=20),
    )

    assert result.ok
    assert result.retained_road_ids == ["main_a", "main_b"]
    assert result.retained_node_ids == ["10", "20", "30"]


def test_unexpected_relation_target_on_allowed_base_is_allowed() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[_road("main", 10, 20, [(0, 0), (100, 0)])],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        unexpected_relation_base_ids={"10"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.unexpected_mapped_semantic_node_ids == []


def test_unexpected_relation_alias_on_required_mainnode_is_allowed() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[_road("main", 10, 20, [(0, 0), (100, 0)])],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(9, 0, 0, mainnodeid=10),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"9", "10", "20"},
        unexpected_relation_base_ids={"9"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.required_rcsd_nodes == ["10", "20"]
    assert result.unexpected_mapped_semantic_node_ids == []


def test_seed_pruning_removes_out_semantic_branch_and_keeps_clean_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("direct", 10, 20, [(0, 0), (100, 0)]),
            _road("side", 10, 30, [(0, 0), (0, 20)]),
            _road("side_leaf", 30, 40, [(0, 20), (0, 40)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 0, 20), _node(40, 0, 40)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40"},
        config=BufferExtractionConfig(buffer_distance_m=45),
    )

    assert result.ok
    assert result.inner_node_ids == []
    assert result.out_node_ids == ["30", "40"]
    assert result.retained_road_ids == ["direct"]


def test_optional_junc_leaf_endpoint_is_pruned_without_rejecting_main_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("direct", 10, 20, [(0, 0), (100, 0)]),
            _road("junc_branch", 10, 30, [(0, 0), (0, 20)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 0, 20)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert result.reason == "passed"
    assert result.required_rcsd_nodes == ["10", "20"]
    assert result.optional_allowed_rcsd_nodes == ["30"]
    assert result.out_node_ids == ["30"]
    assert result.unexpected_endpoint_node_ids == []
    assert result.retained_road_ids == ["direct"]


def test_seed_pruning_keeps_required_corridor_and_removes_out_branch() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (100, 0)]),
            _road("side", 30, 40, [(50, 0), (50, 20)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0), _node(40, 50, 20)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40"},
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert result.inner_node_ids == ["30"]
    assert result.out_node_ids == ["40"]
    assert result.retained_road_ids == ["main_a", "main_b"]


def test_optional_allowed_semantic_nodes_can_be_retained() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30"],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.inner_node_ids == ["30"]
    assert result.retained_road_ids == ["main_a", "main_b"]


def test_buffer_graph_canonicalizes_subnodes_to_semantic_mainnode() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[_road("main", 101, 20, [(0, 0), (100, 0)])],
        rcsd_node_features=[_node(10, 0, 0, mainnodeid=10, subnodeid=[101]), _node(20, 100, 0, mainnodeid=20)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.required_rcsd_nodes == ["10", "20"]
    assert result.retained_node_ids == ["10", "20"]
    assert result.retained_road_ids == ["main"]
