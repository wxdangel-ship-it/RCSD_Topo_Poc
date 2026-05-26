from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t01_data_preprocess.road_kind_continuity import (
    choose_preferred_continuation_edges,
    road_kind_levels,
    road_kind_tokens,
)


def _road(road_id: str, snodeid: str, enodeid: str, kind: str, coords: list[tuple[float, float]]):
    return SimpleNamespace(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        geometry=LineString(coords),
        raw_properties={"kind": kind},
    )


def _edge(road_id: str, from_node: str, to_node: str):
    return SimpleNamespace(road_id=road_id, from_node=from_node, to_node=to_node)


def test_road_kind_tokens_preserve_multi_kind_levels() -> None:
    road = _road("r1", "a", "b", "0601|0602|0801", [(0.0, 0.0), (1.0, 0.0)])

    assert road_kind_tokens(road) == ("0601", "0602", "0801")
    assert road_kind_levels(road) == ("06", "08")


def test_choose_preferred_edges_keeps_same_road_level() -> None:
    roads = {
        "in": _road("in", "a", "b", "0601", [(0.0, 0.0), (1.0, 0.0)]),
        "same": _road("same", "b", "c", "0602", [(1.0, 0.0), (2.0, 0.0)]),
        "other": _road("other", "b", "d", "0801", [(1.0, 0.0), (1.0, 1.0)]),
    }

    decision = choose_preferred_continuation_edges(
        current_node_id="b",
        incoming_from_node_id="a",
        incoming_road_id="in",
        outgoing_edges=(_edge("other", "b", "d"), _edge("same", "b", "c")),
        roads=roads,
        physical_to_semantic={},
    )

    assert [edge.road_id for edge in decision.edges] == ["same"]
    assert [edge.road_id for edge in decision.pruned_edges] == ["other"]
    assert decision.same_level_applied is True


def test_choose_preferred_edges_uses_angle_inside_same_level_candidates() -> None:
    roads = {
        "in": _road("in", "a", "b", "0601", [(0.0, 0.0), (1.0, 0.0)]),
        "straight": _road("straight", "b", "c", "0602", [(1.0, 0.0), (2.0, 0.0)]),
        "turn": _road("turn", "b", "d", "0603", [(1.0, 0.0), (1.0, 1.0)]),
    }

    decision = choose_preferred_continuation_edges(
        current_node_id="b",
        incoming_from_node_id="a",
        incoming_road_id="in",
        outgoing_edges=(_edge("turn", "b", "d"), _edge("straight", "b", "c")),
        roads=roads,
        physical_to_semantic={},
    )

    assert [edge.road_id for edge in decision.edges] == ["straight"]
    assert [edge.road_id for edge in decision.pruned_edges] == ["turn"]
    assert decision.angle_applied is True
    assert decision.best_angle_deg == 0.0
