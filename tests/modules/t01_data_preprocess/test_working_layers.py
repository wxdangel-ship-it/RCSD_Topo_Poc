from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_geojson
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import initialize_working_layers


def test_initialize_working_layers_creates_runtime_fields(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    out_root = tmp_path / "working"

    write_geojson(
        node_path,
        [
            {
                "properties": {"id": 1, "grade": 2, "kind": 4, "closed_con": 2},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": 2, "grade": 1, "kind": 2048, "closed_con": 2},
                "geometry": Point(1.0, 0.0),
            },
        ],
    )
    write_geojson(
        road_path,
        [
            {
                "properties": {"id": "r1", "snodeid": 1, "enodeid": 2, "direction": 2, "formway": 0},
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            }
        ],
    )

    artifacts = initialize_working_layers(road_path=road_path, node_path=node_path, out_root=out_root)

    nodes_doc = json.loads(artifacts.nodes_path.read_text(encoding="utf-8"))
    roads_doc = json.loads(artifacts.roads_path.read_text(encoding="utf-8"))
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    road_props = {str(feature["properties"]["id"]): feature["properties"] for feature in roads_doc["features"]}

    assert node_props["1"]["grade_2"] == 2
    assert node_props["1"]["kind_2"] == 4
    assert node_props["2"]["grade_2"] == 1
    assert node_props["2"]["kind_2"] == 2048
    assert road_props["r1"]["sgrade"] is None
    assert road_props["r1"]["segmentid"] is None
    assert "s_grade" not in road_props["r1"]


def test_initialize_working_layers_groups_roundabout_roads_by_shared_nodes(tmp_path: Path) -> None:
    node_path = tmp_path / "roundabout_nodes.geojson"
    road_path = tmp_path / "roundabout_roads.geojson"
    out_root = tmp_path / "roundabout_working"

    write_geojson(
        node_path,
        [
            {"properties": {"id": 10, "grade": 7, "kind": 7, "closed_con": 2, "mainnodeid": 999}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": 11, "grade": 7, "kind": 7, "closed_con": 2, "mainnodeid": 998}, "geometry": Point(1.0, 0.0)},
            {"properties": {"id": 12, "grade": 7, "kind": 7, "closed_con": 2}, "geometry": Point(2.0, 0.0)},
            {"properties": {"id": 20, "grade": 8, "kind": 8, "closed_con": 2, "mainnodeid": 997}, "geometry": Point(10.0, 0.0)},
            {"properties": {"id": 21, "grade": 8, "kind": 8, "closed_con": 2}, "geometry": Point(11.0, 0.0)},
        ],
    )
    write_geojson(
        road_path,
        [
            {
                "properties": {
                    "id": "ra",
                    "snodeid": 10,
                    "enodeid": 11,
                    "direction": 2,
                    "formway": 0,
                    "roadtype": 8,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            },
            {
                "properties": {
                    "id": "rb",
                    "snodeid": 11,
                    "enodeid": 12,
                    "direction": 2,
                    "formway": 0,
                    "roadtype": 8,
                },
                "geometry": LineString([(1.0, 0.0), (2.0, 0.0)]),
            },
            {
                "properties": {
                    "id": "rc",
                    "snodeid": 20,
                    "enodeid": 21,
                    "direction": 2,
                    "formway": 0,
                    "roadtype": 8,
                },
                "geometry": LineString([(10.0, 0.0), (11.0, 0.0)]),
            },
        ],
    )

    artifacts = initialize_working_layers(road_path=road_path, node_path=node_path, out_root=out_root, debug=True)

    nodes_doc = json.loads(artifacts.nodes_path.read_text(encoding="utf-8"))
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    roundabout_summary = json.loads(artifacts.roundabout_summary_path.read_text(encoding="utf-8"))

    assert roundabout_summary["roundabout_group_count"] == 2
    assert roundabout_summary["roundabout_mainnode_count"] == 2
    assert roundabout_summary["roundabout_road_count"] == 3
    assert roundabout_summary["roundabout_member_node_count"] == 3
    assert node_props["10"]["grade_2"] == 1
    assert node_props["10"]["kind_2"] == 64
    assert str(node_props["10"]["mainnodeid"]) == "10"
    assert str(node_props["10"]["working_mainnodeid"]) == "10"
    assert node_props["11"]["grade_2"] == 0
    assert node_props["11"]["kind_2"] == 0
    assert str(node_props["11"]["mainnodeid"]) == "10"
    assert str(node_props["11"]["working_mainnodeid"]) == "10"
    assert node_props["12"]["grade_2"] == 0
    assert node_props["12"]["kind_2"] == 0
    assert str(node_props["12"]["mainnodeid"]) == "10"
    assert str(node_props["12"]["working_mainnodeid"]) == "10"
    assert node_props["20"]["grade_2"] == 1
    assert node_props["20"]["kind_2"] == 64
    assert str(node_props["20"]["mainnodeid"]) == "20"
    assert str(node_props["21"]["mainnodeid"]) == "20"
    assert str(node_props["20"]["working_mainnodeid"]) == "20"
    assert str(node_props["21"]["working_mainnodeid"]) == "20"
    assert (out_root / "roundabout_group_roads.geojson").is_file()
    assert (out_root / "roundabout_group_nodes.geojson").is_file()
    assert (out_root / "roundabout_mainnodes.geojson").is_file()
    assert (out_root / "roundabout_group_table.csv").is_file()
