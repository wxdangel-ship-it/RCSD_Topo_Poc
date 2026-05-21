from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import build_road_graph
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_candidate_extraction import extract_rcsd_candidates


def _road(road_id: str, snode: int, enode: int, direction: int):
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": direction},
        "geometry": LineString([(snode, 0), (enode, 0)]),
    }


def test_dual_swsd_requires_rcsd_bidirectional() -> None:
    dual = extract_rcsd_candidates(graph=build_road_graph([_road("r1", 10, 20, 0)]), source_node="10", target_node="20", swsd_directionality="dual")
    one_way = extract_rcsd_candidates(graph=build_road_graph([_road("r1", 10, 20, 2)]), source_node="10", target_node="20", swsd_directionality="dual")

    assert len(dual.candidates) == 1
    assert dual.candidates[0].directionality == "dual"
    assert one_way.reject_reason == "rcsd_not_bidirectional_for_swsd_dual"


def test_single_swsd_rejects_reverse_and_bidirectional_rcsd() -> None:
    forward = extract_rcsd_candidates(graph=build_road_graph([_road("r1", 10, 20, 2)]), source_node="10", target_node="20", swsd_directionality="single")
    reverse = extract_rcsd_candidates(graph=build_road_graph([_road("r1", 10, 20, 3)]), source_node="10", target_node="20", swsd_directionality="single")
    bidir = extract_rcsd_candidates(graph=build_road_graph([_road("r1", 10, 20, 0)]), source_node="10", target_node="20", swsd_directionality="single")

    assert len(forward.candidates) == 1
    assert reverse.reject_reason == "oneway_direction_mismatch"
    assert bidir.reject_reason == "directionality_mismatch_rcsd_bidirectional_for_swsd_oneway"
