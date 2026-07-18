from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import CaseSpec
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    _build_road_adjacency,
    feature_enodeid,
    feature_snodeid,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import (
    _parse_roads,
    build_step1_context_from_features,
)


def _case_spec() -> CaseSpec:
    return CaseSpec(
        case_id="100",
        mainnodeid="100",
        case_root=Path("."),
        manifest={},
        size_report={},
        input_paths={},
    )


def test_t03_shared_road_adjacency_accepts_frcsd_camel_case_endpoints() -> None:
    road = LayerFeature(
        properties={"ID": "r1", "snodeId": "n1", "enodeId": "n2", "direction": 2},
        geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
    )

    adjacency = _build_road_adjacency((road,))

    assert feature_snodeid(road) == "n1"
    assert feature_enodeid(road) == "n2"
    assert adjacency == {"n1": (road,), "n2": (road,)}


def test_t03_step1_parses_frcsd_camel_case_fields_like_canonical_fields() -> None:
    context = build_step1_context_from_features(
        case_spec=_case_spec(),
        node_features=[
            LayerFeature(
                properties={
                    "ID": "100",
                    "mainNodeId": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                geometry=Point(0.0, 0.0),
            )
        ],
        road_features=[
            LayerFeature(
                properties={"ID": "s1", "snodeId": "100", "enodeId": "101", "Direction": 2},
                geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            )
        ],
        drivezone_features=[LayerFeature(properties={"ID": "dz"}, geometry=box(-5.0, -5.0, 15.0, 5.0))],
        rcsdroad_features=[
            LayerFeature(
                properties={
                    "ID": "r1",
                    "snodeId": "r-n1",
                    "enodeId": "r-n2",
                    "Direction": 2,
                    "formWay": 8,
                },
                geometry=LineString([(0.0, 1.0), (10.0, 1.0)]),
            )
        ],
        rcsdnode_features=[
            LayerFeature(
                properties={"ID": "r-n1", "mainNodeId": "r-n1", "kind_2": 4, "grade_2": 1},
                geometry=Point(0.0, 1.0),
            )
        ],
    )

    assert context.representative_node.node_id == "100"
    assert context.roads[0].snodeid == "100"
    assert context.roads[0].enodeid == "101"
    assert context.rcsd_roads[0].snodeid == "r-n1"
    assert context.rcsd_roads[0].enodeid == "r-n2"
    assert context.rcsd_roads[0].formway == 8
    assert context.rcsd_nodes[0].mainnodeid == "r-n1"


def test_t03_does_not_silently_accept_missing_logical_road_endpoint() -> None:
    road = LayerFeature(
        properties={"ID": "r1", "snodeId": "n1", "Direction": 2},
        geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
    )

    try:
        _parse_roads([road])
    except ValueError as exc:
        assert "road feature[0]" in str(exc)
        assert "enodeid" in str(exc)
    else:
        raise AssertionError("T03 must reject a road with a missing logical endpoint")
