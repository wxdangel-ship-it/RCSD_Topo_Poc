from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_segment_extraction import (
    BufferExtractionConfig,
    BufferSegmentExtractor,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationCheck
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.single_direction_reality import (
    SINGLE_RCSD_BIDIRECTIONAL_ACTION,
    SINGLE_RCSD_BIDIRECTIONAL_CONFLICT,
    SingleDirectionRealityContext,
    resolve_single_rcsd_bidirectional_reality,
)


def _road(road_id: str, snode: int, enode: int, coords: list[tuple[float, float]], **props):
    payload = {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": 2}
    payload.update(props)
    return {"properties": payload, "geometry": LineString(coords)}


def _node(node_id: int, x: float, y: float):
    return {"properties": {"id": node_id, "mainnodeid": 0}, "geometry": Point(x, y)}


def test_single_swsd_with_bidirectional_rcsd_replaces_full_closure() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)]),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)]),
            _road("reverse_a", 20, 40, [(100, 1), (50, 1)]),
            _road("reverse_b", 40, 10, [(50, 1), (0, 1)]),
        ],
        rcsd_node_features=[
            _node(10, 0, 0),
            _node(20, 100, 0),
            _node(30, 50, 0),
            _node(40, 50, 1),
        ],
    )
    relation = RelationCheck(True, ["10", "20"], [])
    config = BufferExtractionConfig(buffer_distance_m=10)
    base_result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=relation,
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=config,
    )

    resolved_result, conflict_props = resolve_single_rcsd_bidirectional_reality(
        SingleDirectionRealityContext(extractor, LineString([(0, 0), (100, 0)]), {"10", "20"}, set(), config),
        "single",
        relation,
        [],
        ["10", "20"],
        base_result,
    )

    assert base_result.ok
    assert base_result.retained_road_ids == ["forward_a", "forward_b"]
    assert set(resolved_result.retained_road_ids) == {"forward_a", "forward_b", "reverse_a", "reverse_b"}
    assert resolved_result.directed_rcsd_pair_nodes == ["10", "20"]
    assert conflict_props["directionality_conflict_status"] == SINGLE_RCSD_BIDIRECTIONAL_CONFLICT
    assert conflict_props["directionality_conflict_action"] == SINGLE_RCSD_BIDIRECTIONAL_ACTION
    assert conflict_props["forward_rcsd_road_ids"] == ["forward_a", "forward_b"]
    assert set(conflict_props["reverse_or_extra_rcsd_road_ids"]) == {"reverse_a", "reverse_b"}


def test_single_swsd_without_bidirectional_rcsd_keeps_base_result() -> None:
    extractor = BufferSegmentExtractor(
        rcsd_road_features=[
            _road("forward_a", 10, 30, [(0, 0), (50, 0)]),
            _road("forward_b", 30, 20, [(50, 0), (100, 0)]),
        ],
        rcsd_node_features=[_node(10, 0, 0), _node(20, 100, 0), _node(30, 50, 0)],
    )
    relation = RelationCheck(True, ["10", "20"], [])
    config = BufferExtractionConfig(buffer_distance_m=10)
    base_result = extractor.extract(
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=relation,
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        directed_pair_nodes=["10", "20"],
        require_directed_pair=True,
        config=config,
    )

    resolved_result, conflict_props = resolve_single_rcsd_bidirectional_reality(
        SingleDirectionRealityContext(extractor, LineString([(0, 0), (100, 0)]), {"10", "20"}, set(), config),
        "single",
        relation,
        [],
        ["10", "20"],
        base_result,
    )

    assert resolved_result is base_result
    assert conflict_props == {}
