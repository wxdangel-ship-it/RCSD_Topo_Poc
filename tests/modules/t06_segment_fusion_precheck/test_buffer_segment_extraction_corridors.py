from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.adaptive_buffer_retry import (
    high_grade_adaptive_buffer_retry_plan,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentExtractor,
    Edge,
    _include_visual_gap_candidate_components,
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


def test_dual_corridor_retains_internal_edge_after_supplement_expands_nodes() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)], direction=2),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)], direction=2),
            _road("reverse", 20, 10, [(100, 2), (0, 2)], direction=2),
            _road("supplement_carrier_a", 30, 40, [(50, 0), (50, 2)], direction=2),
            _road("supplement_carrier_b", 40, 10, [(50, 2), (0, 2)], direction=2),
            _road("internal_after_supplement", 30, 40, [(50, 0), (50, 5), (50, 2)], direction=2),
            _road("outside_after_supplement", 30, 40, [(50, 60), (70, 70), (50, 65)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 50, 0),
            _node(40, 50, 2),
        ],
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
    assert "supplement_carrier_a" in result.retained_road_ids
    assert "supplement_carrier_b" in result.retained_road_ids
    assert "internal_after_supplement" in result.retained_road_ids
    assert "outside_after_supplement" not in result.retained_road_ids


def test_directed_corridor_retains_parallel_internal_edge_between_required_junctions() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (40, 0)], direction=2),
            _road("main_b", 30, 40, [(40, 0), (60, 0)], direction=2),
            _road("main_c", 40, 20, [(60, 0), (100, 0)], direction=2),
            _road("parallel_internal", 30, 40, [(40, 0), (50, 5), (60, 0)], direction=2),
            _road("outside_parallel", 30, 40, [(40, 60), (50, 70), (60, 60)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 40, 0),
            _node(40, 60, 0),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30", "40"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert "parallel_internal" in result.retained_road_ids
    assert "outside_parallel" not in result.retained_road_ids


def test_dual_corridor_supplements_connected_carrier_inside_narrow_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (100, 0)], direction=2),
            _road("forward_b", 30, 20, [(100, 0), (200, 0)], direction=2),
            _road("reverse_a", 20, 40, [(200, 2), (100, 2)], direction=2),
            _road("reverse_b", 40, 10, [(100, 2), (0, 2)], direction=2),
            _road("carrier_a", 40, 50, [(100, 2), (60, 1)], direction=2),
            _road("carrier_b", 50, 30, [(60, 1), (100, 0)], direction=2),
            _road("carrier_c", 50, 10, [(60, 1), (0, 0)], direction=2),
            _road("side_branch", 30, 60, [(100, 0), (100, 20)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 100, 0),
            _node(40, 100, 2),
            _node(50, 60, 1, kind=16),
            _node(60, 100, 20),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {
        "forward_a",
        "forward_b",
        "reverse_a",
        "reverse_b",
        "carrier_a",
        "carrier_b",
        "carrier_c",
    }
    assert "side_branch" not in result.retained_road_ids
    assert "50" in result.retained_node_ids
    assert "50" not in result.out_node_ids


def test_dual_corridor_supplements_optional_junction_carrier_inside_reference_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward", 10, 20, [(0, 0), (200, 0)], direction=2),
            _road("reverse_a", 20, 30, [(200, 2), (100, 2)], direction=2),
            _road("reverse_b", 30, 10, [(100, 2), (0, 2)], direction=2),
            _road("optional_carrier_a", 30, 50, [(100, 2), (70, 3)], direction=2),
            _road("optional_carrier_b", 50, 60, [(70, 3), (20, 4)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 100, 2, kind=16),
            _node(50, 70, 3),
            _node(60, 20, 4),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30"],
        all_relation_base_ids={"10", "20", "30"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {
        "forward",
        "reverse_a",
        "reverse_b",
        "optional_carrier_a",
        "optional_carrier_b",
    }
    assert "60" in result.retained_node_ids
    assert result.unexpected_endpoint_node_ids == []


def test_dual_corridor_does_not_supplement_optional_junction_carrier_outside_reference_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward", 10, 20, [(0, 0), (200, 0)], direction=2),
            _road("reverse_a", 20, 30, [(200, 2), (100, 2)], direction=2),
            _road("reverse_b", 30, 10, [(100, 2), (0, 2)], direction=2),
            _road("far_optional_carrier", 30, 50, [(100, 2), (100, 35)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 100, 2, kind=16),
            _node(50, 100, 35),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30"],
        all_relation_base_ids={"10", "20", "30"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=50),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward", "reverse_a", "reverse_b"}
    assert "far_optional_carrier" not in result.retained_road_ids
    assert "50" not in result.retained_node_ids


def test_single_corridor_does_not_supplement_unselected_parallel_carrier() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (100, 0)], direction=2),
            _road("forward_b", 30, 20, [(100, 0), (200, 0)], direction=2),
            _road("carrier_a", 30, 50, [(100, 0), (60, 1)], direction=2),
            _road("carrier_b", 50, 10, [(60, 1), (0, 0)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 100, 0),
            _node(50, 60, 1, kind=16),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward_a", "forward_b"}
    assert not {"carrier_a", "carrier_b"} & set(result.retained_road_ids)


def test_single_corridor_supplements_semantic_junction_bridge_inside_reference_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (80, 0)], direction=2),
            _road("main_b", 30, 40, [(80, 0), (120, 0)], direction=2),
            _road("main_c", 40, 20, [(120, 0), (200, 0)], direction=2),
            _road("sibling_bridge_a", 30, 50, [(80, 0), (120, 3)], direction=2),
            _road("sibling_bridge_b", 50, 20, [(120, 3), (200, 0)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 80, 0, kind=16),
            _node(40, 120, 0),
            _node(50, 120, 3),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {
        "main_a",
        "main_b",
        "main_c",
        "sibling_bridge_a",
        "sibling_bridge_b",
    }
    assert result.unexpected_endpoint_node_ids == []


def test_single_corridor_supplements_selected_required_pair_parallel_sibling_edge() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main", 10, 20, [(0, 0), (100, 0)], direction=2),
            _road("parallel_sibling", 11, 21, [(0, 2), (100, 2)], direction=2),
            _road("reverse_only_sibling", 12, 22, [(0, 4), (100, 4)], direction=3),
            _road("shortcut_branch", 10, 30, [(0, 0), (50, 20)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0, mainnodeid=10, subnodeid=[11, 12]),
            _node(11, 0, 2, mainnodeid=10),
            _node(12, 0, 4, mainnodeid=10),
            _node(20, 100, 0, mainnodeid=20, subnodeid=[21, 22]),
            _node(21, 100, 2, mainnodeid=20),
            _node(22, 100, 4, mainnodeid=20),
            _node(30, 50, 20),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"main", "parallel_sibling"}


def test_single_corridor_supplements_semantic_junction_bridge_with_blocked_side_branch() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (80, 0)], direction=2),
            _road("main_b", 30, 40, [(80, 0), (120, 0)], direction=2),
            _road("main_c", 40, 20, [(120, 0), (200, 0)], direction=2),
            _road("sibling_bridge_a", 30, 50, [(80, 0), (120, 3)], direction=2),
            _road("sibling_bridge_b", 50, 20, [(120, 3), (200, 0)], direction=2),
            _road("blocked_side_branch", 50, 60, [(120, 3), (120, 8)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 80, 0, kind=16),
            _node(40, 120, 0),
            _node(50, 120, 3),
            _node(60, 120, 8),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "60"},
        unexpected_relation_base_ids={"60"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert {"sibling_bridge_a", "sibling_bridge_b"} <= set(result.retained_road_ids)
    assert "blocked_side_branch" not in result.retained_road_ids


def test_single_corridor_does_not_supplement_semantic_junction_bridge_outside_reference_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("main_a", 10, 30, [(0, 0), (80, 0)], direction=2),
            _road("main_b", 30, 40, [(80, 0), (120, 0)], direction=2),
            _road("main_c", 40, 20, [(120, 0), (200, 0)], direction=2),
            _road("far_bridge_a", 30, 50, [(80, 0), (120, 40)], direction=2),
            _road("far_bridge_b", 50, 20, [(120, 40), (200, 0)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 80, 0, kind=16),
            _node(40, 120, 0),
            _node(50, 120, 40),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=60, visual_consistency_buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"main_a", "main_b", "main_c"}
    assert not {"far_bridge_a", "far_bridge_b"} & set(result.retained_road_ids)


def test_dual_corridor_supplements_retained_boundary_bridge_without_required_endpoint() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (100, 0)], direction=2),
            _road("forward_b", 30, 20, [(100, 0), (200, 0)], direction=2),
            _road("reverse_a", 20, 40, [(200, 2), (100, 2)], direction=2),
            _road("reverse_b", 40, 10, [(100, 2), (0, 2)], direction=2),
            _road("carrier_a", 40, 50, [(100, 2), (60, 1)], direction=2),
            _road("carrier_b", 50, 30, [(60, 1), (100, 0)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 100, 0),
            _node(40, 100, 2),
            _node(50, 60, 1, kind=16),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {
        "forward_a",
        "forward_b",
        "reverse_a",
        "reverse_b",
        "carrier_a",
        "carrier_b",
    }


def test_dual_corridor_does_not_supplement_bridge_with_external_mapped_node() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (100, 0)], direction=2),
            _road("forward_b", 30, 20, [(100, 0), (200, 0)], direction=2),
            _road("reverse_a", 20, 40, [(200, 2), (100, 2)], direction=2),
            _road("reverse_b", 40, 10, [(100, 2), (0, 2)], direction=2),
            _road("carrier_a", 40, 50, [(100, 2), (60, 1)], direction=2),
            _road("carrier_b", 50, 30, [(60, 1), (100, 0)], direction=2),
            _road("mapped_side_branch", 50, 60, [(60, 1), (60, 12)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 200, 0),
            _node(30, 100, 0),
            _node(40, 100, 2),
            _node(50, 60, 1),
            _node(60, 60, 12, kind=16),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (200, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "60"},
        unexpected_relation_base_ids={"60"},
        require_bidirectional=True,
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"forward_a", "forward_b", "reverse_a", "reverse_b"}
    assert not {"carrier_a", "carrier_b", "mapped_side_branch"} & set(result.retained_road_ids)


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


def test_single_corridor_does_not_skip_ordered_required_junction_nodes() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("direct_pair_path", 10, 20, [(0, 0), (100, 0)], direction=2),
            _road("ordered_a", 10, 30, [(0, 4), (30, 4)], direction=2),
            _road("ordered_b", 30, 40, [(30, 4), (70, 4)], direction=2),
            _road("ordered_c", 40, 20, [(70, 4), (100, 4)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 30, 4),
            _node(40, 70, 4),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30", "40"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert set(result.retained_road_ids) == {"ordered_a", "ordered_b", "ordered_c"}
    assert "direct_pair_path" not in result.retained_road_ids


def test_single_corridor_rejects_reversed_required_junction_order() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("reverse_a", 10, 40, [(0, 0), (70, 0)], direction=2),
            _road("reverse_b", 40, 30, [(70, 0), (30, 0)], direction=2),
            _road("reverse_c", 30, 20, [(30, 0), (100, 0)], direction=2),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 30, 0),
            _node(40, 70, 0),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30", "40"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30", "40"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert not result.ok
    assert result.reason == "rcsd_directed_path_missing"
    assert result.retained_road_ids == []


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
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30"],
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
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30"],
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


def test_non_bidirectional_optional_terminal_supplements_connected_corridor() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("direct", 10, 20, [(0, 0), (100, 0)]),
            _road("branch_a", 10, 30, [(0, 0), (50, 5)]),
            _road("branch_b", 30, 20, [(50, 5), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 5)],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], ["30"]),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20", "30"},
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.reason == "passed"
    assert result.retained_road_ids == ["branch_a", "branch_b"]
    assert result.unexpected_endpoint_node_ids == []


def test_seed_pruning_keeps_paths_between_optional_terminals_and_prunes_leaf_noise() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("direct", 10, 20, [(0, 0), (100, 0)]),
            _road("attach_a", 10, 30, [(0, 0), (20, 0)]),
            _road("optional_a", 30, 50, [(20, 0), (40, 0)]),
            _road("optional_mid", 50, 60, [(40, 0), (60, 0)]),
            _road("optional_b", 60, 40, [(60, 0), (80, 0)]),
            _road("attach_b", 40, 20, [(80, 0), (100, 0)]),
            _road("leaf_noise", 60, 70, [(60, 0), (60, 10)]),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 20, 0),
            _node(40, 80, 0),
            _node(50, 40, 0),
            _node(60, 60, 0),
            _node(70, 60, 10),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30", "40"],
        all_relation_base_ids={"10", "20", "30", "40", "50", "60", "70"},
        config=BufferExtractionConfig(buffer_distance_m=20),
    )

    assert result.ok
    assert {"attach_a", "optional_a", "optional_mid", "optional_b", "attach_b"}.issubset(set(result.retained_road_ids))
    assert "leaf_noise" not in result.retained_road_ids
    assert result.out_node_ids == ["70"]


def test_optional_terminal_pruning_preserves_required_pair_corridor_in_same_seed_group() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("pair_a", 10, 50, [(0, 0), (35, 0)]),
            _road("pair_b", 50, 60, [(35, 0), (70, 0)]),
            _road("pair_c", 60, 20, [(70, 0), (100, 0)]),
            _road("optional_a", 50, 70, [(35, 0), (50, 8)]),
            _road("optional_b", 70, 30, [(50, 8), (30, 8)]),
            _road("optional_c", 70, 40, [(50, 8), (70, 8)]),
            _road("leaf_noise", 70, 80, [(50, 8), (50, 20)]),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 30, 8),
            _node(40, 70, 8),
            _node(50, 35, 0),
            _node(60, 70, 0),
            _node(70, 50, 8),
            _node(80, 50, 20),
        ],
    )

    result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=["30", "40"],
        all_relation_base_ids={"10", "20", "30", "40", "50", "60", "70", "80"},
        config=BufferExtractionConfig(buffer_distance_m=25),
    )

    assert result.ok
    assert {"pair_a", "pair_b", "pair_c"}.issubset(set(result.retained_road_ids))
    assert not {"optional_a", "optional_b", "optional_c", "leaf_noise"} & set(result.retained_road_ids)


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
