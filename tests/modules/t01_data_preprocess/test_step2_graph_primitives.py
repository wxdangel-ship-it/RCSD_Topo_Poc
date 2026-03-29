from __future__ import annotations

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import TraversalEdge
from rcsd_topo_poc.modules.t01_data_preprocess.step2_graph_primitives import (
    _collect_components,
    _count_components,
    _find_bridge_road_ids,
    _path_exists_directed,
    _path_exists_undirected,
)


def test_graph_primitives_collect_components_and_paths() -> None:
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r45": ("4", "5"),
    }

    components = _collect_components({"r45", "r23", "r12"}, road_endpoints=road_endpoints)

    assert components == [
        (("r12", "r23"), ("1", "2", "3")),
        (("r45",), ("4", "5")),
    ]
    assert _count_components({"r45", "r23", "r12"}, road_endpoints) == 2
    assert _path_exists_undirected("1", "3", road_ids={"r12", "r23"}, road_endpoints=road_endpoints) is True
    assert _path_exists_undirected("1", "5", road_ids={"r12", "r23", "r45"}, road_endpoints=road_endpoints) is False


def test_graph_primitives_find_bridge_road_ids_on_cycle_with_tail() -> None:
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r31": ("3", "1"),
        "r24": ("2", "4"),
    }

    assert _find_bridge_road_ids(
        {"r12", "r23", "r31", "r24"},
        road_endpoints=road_endpoints,
    ) == {"r24"}



def test_path_exists_directed_follows_adjacency_orientation() -> None:
    adjacency = {
        "A": (TraversalEdge("ab", "A", "B"),),
        "B": (TraversalEdge("bc", "B", "C"),),
        "C": (),
    }

    assert _path_exists_directed("A", "C", adjacency=adjacency) is True
    assert _path_exists_directed("C", "A", adjacency=adjacency) is False
