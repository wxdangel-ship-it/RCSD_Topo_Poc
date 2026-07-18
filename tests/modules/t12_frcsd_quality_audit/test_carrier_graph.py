from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    build_graph,
    build_node_context,
    path_metrics,
    shortest_path_between_sets,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import AuditConfig


def test_zero_length_path_is_reachable_and_equivalent() -> None:
    path = shortest_path_between_sets({}, ["same"], ["same"])

    assert path is not None
    assert path.node_ids == ("same",)
    assert path.road_ids == ()
    assert path.length_m == 0.0
    assert path_metrics(
        path,
        {},
        LineString([(0, 0), (10, 0)]),
        10.0,
        AuditConfig(),
    )["accepted_equivalent_carrier"] is True


def test_camel_case_main_and_subnode_fields_are_canonicalized() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": ["main", "child"],
            "mainNodeId": ["100", "100"],
            "subNodeId": ['["main","child"]', ""],
            "geometry": [Point(0, 0), Point(1, 0)],
        },
        crs="EPSG:3857",
    )

    canonicalizer, groups, _ = build_node_context(nodes)

    assert canonicalizer.canonicalize("main") == "100"
    assert canonicalizer.canonicalize("child") == "100"
    assert groups["100"] == ("child", "main")


@pytest.mark.parametrize(
    ("direction", "forward", "reverse"),
    [(0, True, True), (1, True, True), (2, True, False), (3, False, True)],
)
def test_frcsd_direction_semantics(
    direction: int,
    forward: bool,
    reverse: bool,
) -> None:
    nodes = gpd.GeoDataFrame(
        {"id": ["a", "b"], "geometry": [Point(0, 0), Point(10, 0)]},
        crs="EPSG:3857",
    )
    canonicalizer, _, _ = build_node_context(nodes)
    roads = gpd.GeoDataFrame(
        {
            "id": ["r"],
            "snodeid": ["a"],
            "enodeid": ["b"],
            "direction": [direction],
            "source": [2],
            "geometry": [LineString([(0, 0), (10, 0)])],
        },
        crs="EPSG:3857",
    )
    graph = build_graph(roads, canonicalizer)

    assert (shortest_path_between_sets(graph.directed, ["a"], ["b"]) is not None) is forward
    assert (shortest_path_between_sets(graph.directed, ["b"], ["a"]) is not None) is reverse


def test_shortest_path_tie_is_deterministic() -> None:
    adjacency = {
        "a": (("b", "road_b", 1.0), ("c", "road_c", 1.0)),
        "b": (("z", "road_z1", 1.0),),
        "c": (("z", "road_z2", 1.0),),
    }

    first = shortest_path_between_sets(adjacency, ["a"], ["z"])
    second = shortest_path_between_sets(adjacency, ["a"], ["z"])

    assert first == second
    assert first is not None
    assert first.road_ids == ("road_b", "road_z1")
