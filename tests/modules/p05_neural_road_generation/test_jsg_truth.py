from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import DirectionRole
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_truth import (
    _direction_role,
    _shortest_road_path,
)


def _road(start: str, end: str, direction: int) -> dict:
    return {"properties": {"snodeid": start, "enodeid": end, "direction": direction}}


def test_direction_role_uses_carrier_direction_not_pair_order() -> None:
    roads = {"r": _road("n2", "n1", 2)}
    assert _direction_role(("r",), ("n1",), roads) is DirectionRole.ENTER
    assert _direction_role(("r",), ("n2",), roads) is DirectionRole.EXIT


def test_bidirectional_carrier_reports_both() -> None:
    roads = {"r": _road("n1", "n2", 1)}
    assert _direction_role(("r",), ("n1",), roads) is DirectionRole.BOTH
    assert _direction_role(("r",), ("n2",), roads) is DirectionRole.BOTH


def test_movement_path_is_limited_to_declared_carrier_roads() -> None:
    edges = {
        "a": [("b", "r1"), ("x", "foreign")],
        "b": [("c", "r2")],
        "x": [("c", "foreign2")],
    }
    assert _shortest_road_path(("a",), ("c",), edges, {"r1", "r2"}) == ["r1", "r2"]
    assert _shortest_road_path(("a",), ("c",), edges, {"foreign", "foreign2"}) == ["foreign", "foreign2"]
    assert _shortest_road_path(("a",), ("c",), edges, {"r1"}) is None
