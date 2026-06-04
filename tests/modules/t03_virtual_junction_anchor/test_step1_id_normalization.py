from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import CaseSpec
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context_from_features


def test_step1_normalizes_integral_float_ids() -> None:
    case_spec = CaseSpec(
        case_id="603308301",
        mainnodeid="603308301",
        case_root=Path("."),
        manifest={},
        size_report={},
        input_paths={},
    )
    context = build_step1_context_from_features(
        case_spec=case_spec,
        node_features=[
            LayerFeature(
                properties={
                    "id": 603308301.0,
                    "mainnodeid": 603308301.0,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4.0,
                    "grade_2": 1.0,
                },
                geometry=Point(0.0, 0.0),
            )
        ],
        road_features=[
            LayerFeature(
                properties={"id": 700001.0, "snodeid": 603308301.0, "enodeid": 603308302.0, "direction": 2.0},
                geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            )
        ],
        drivezone_features=[LayerFeature(properties={"id": "dz"}, geometry=box(-10.0, -10.0, 20.0, 10.0))],
        rcsdroad_features=[
            LayerFeature(
                properties={"id": 800001.0, "snodeid": 900001.0, "enodeid": 900002.0, "direction": 2.0},
                geometry=LineString([(0.0, 1.0), (10.0, 1.0)]),
            )
        ],
        rcsdnode_features=[
            LayerFeature(
                properties={"id": 900001.0, "mainnodeid": 900001.0, "kind_2": 4.0, "grade_2": 1.0},
                geometry=Point(0.0, 1.0),
            )
        ],
    )

    assert context.representative_node.node_id == "603308301"
    assert context.target_group.group_id == "603308301"
    assert context.roads[0].road_id == "700001"
    assert context.roads[0].snodeid == "603308301"
    assert context.roads[0].enodeid == "603308302"
    assert context.rcsd_roads[0].road_id == "800001"
    assert context.rcsd_nodes[0].node_id == "900001"
