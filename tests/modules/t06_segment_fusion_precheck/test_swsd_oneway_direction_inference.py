from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.direction_inference import infer_swsd_oneway_direction


def _road(road_id: str, snode: int, enode: int, direction: int):
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": direction},
        "geometry": LineString([(snode, 0), (enode, 0)]),
    }


def test_infers_unique_a_to_b_and_b_to_a_without_pair_order_dependency() -> None:
    forward = infer_swsd_oneway_direction(pair_nodes=["1", "2"], segment_road_ids=["r1"], swsd_road_features=[_road("r1", 1, 2, 2)])
    reverse = infer_swsd_oneway_direction(pair_nodes=["2", "1"], segment_road_ids=["r1"], swsd_road_features=[_road("r1", 1, 2, 2)])

    assert (forward.status, forward.source_node, forward.target_node) == ("unique", "1", "2")
    assert (reverse.status, reverse.source_node, reverse.target_node) == ("unique", "1", "2")


def test_rejects_bidirectional_like_disconnected_and_missing_body() -> None:
    bidir = infer_swsd_oneway_direction(pair_nodes=["1", "2"], segment_road_ids=["r1"], swsd_road_features=[_road("r1", 1, 2, 0)])
    disconnected = infer_swsd_oneway_direction(pair_nodes=["1", "2"], segment_road_ids=["r1"], swsd_road_features=[_road("r1", 3, 4, 2)])
    missing = infer_swsd_oneway_direction(pair_nodes=["1", "2"], segment_road_ids=["missing"], swsd_road_features=[_road("r1", 1, 2, 2)])

    assert bidir.reject_reason == "swsd_oneway_body_bidirectional_like"
    assert disconnected.reject_reason == "swsd_oneway_body_not_connected"
    assert missing.reject_reason == "missing_swsd_oneway_direction"
