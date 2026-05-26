from __future__ import annotations

from shapely.geometry import LineString, Point

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


def _node(node_id: int, x: float, y: float, *, mainnodeid: int = 0, subnodeid=None):
    return {
        "properties": {"id": node_id, "mainnodeid": mainnodeid, "subnodeid": subnodeid if subnodeid is not None else []},
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
            _road("main_a", 10, 30, [(-30, 0), (50, 0)]),
            _road("main_b", 30, 20, [(50, 0), (130, 0)]),
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
    assert result.required_rcsd_nodes == ["10", "20", "30"]


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


def test_missing_required_nodes_fail_component_coverage() -> None:
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

    assert not result.ok
    assert result.reason == "required_semantic_nodes_missing_from_buffer_graph"
    assert result.missing_required_node_ids == ["30"]


def test_seed_pruning_keeps_inner_semantic_nodes_between_required_nodes() -> None:
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
        config=BufferExtractionConfig(buffer_distance_m=10),
    )

    assert result.ok
    assert result.inner_node_ids == ["30"]
    assert result.out_node_ids == []
    assert result.retained_road_ids == ["main_a", "main_b"]


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


def test_seed_pruning_fails_when_out_semantic_branch_disconnects_required_nodes() -> None:
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

    assert not result.ok
    assert result.reason == "buffer_pruned_to_empty"
    assert result.inner_node_ids == []
    assert result.out_node_ids == ["30", "40"]


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
    assert result.inner_node_ids == []
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
