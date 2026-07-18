from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    REQUIRED_NODE_FIELDS,
    REQUIRED_ROAD_FIELDS,
    _prepare_nodes,
    _prepare_roads,
    _validate_required_fields,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    _initialize_node_properties,
    _initialize_road_properties,
)


def test_t01_step1_parses_mixed_case_external_node_and_road_fields() -> None:
    node_feature = {
        "properties": {
            "ID": "n1",
            "mainNodeId": "n1",
            "Kind": 4,
            "Grade": 1,
            "Kind_2": 4,
            "Grade_2": 1,
            "Closed_Con": 2,
        },
        "geometry": Point(0.0, 0.0),
    }
    road_feature = {
        "properties": {
            "ID": "r1",
            "snodeId": "n1",
            "enodeId": "n2",
            "Direction": 2,
            "formWay": 0,
            "Road_Kind": 0,
        },
        "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
    }

    assert _validate_required_fields([node_feature], REQUIRED_NODE_FIELDS, layer_label="node") == []
    assert _validate_required_fields([road_feature], REQUIRED_ROAD_FIELDS, layer_label="road") == []

    nodes = _prepare_nodes([node_feature], [])
    roads = _prepare_roads([road_feature], [])

    assert nodes["n1"].mainnodeid == "n1"
    assert nodes["n1"].kind_2 == 4
    assert roads["r1"].snodeid == "n1"
    assert roads["r1"].enodeid == "n2"
    assert roads["r1"].direction == 2


def test_t01_working_layer_publishes_canonical_copy_without_mutating_input() -> None:
    raw_node = {"ID": "n1", "mainNodeId": "n1", "Grade": 1, "Kind": 4}
    raw_road = {"ID": "r1", "snodeId": "n1", "enodeId": "n2", "Direction": 2}

    node = _initialize_node_properties(raw_node)
    road = _initialize_road_properties(raw_road)

    assert raw_node == {"ID": "n1", "mainNodeId": "n1", "Grade": 1, "Kind": 4}
    assert raw_road == {"ID": "r1", "snodeId": "n1", "enodeId": "n2", "Direction": 2}
    assert node["id"] == "n1"
    assert node["mainnodeid"] == "n1"
    assert node["grade_2"] == 1
    assert node["kind_2"] == 4
    assert road["id"] == "r1"
    assert road["snodeid"] == "n1"
    assert road["enodeid"] == "n2"
    assert road["direction"] == 2
    assert "ID" not in node
    assert "snodeId" not in road
