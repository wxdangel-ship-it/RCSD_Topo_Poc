from __future__ import annotations

import json
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_divmerge_virtual_polygon import (
    _cover_check,
    run_t02_stage4_divmerge_virtual_polygon,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _write_fixture(
    tmp_path: Path,
    *,
    kind_2: int,
    rcsdroad_outside_drivezone: bool = False,
    rcsdnode_outside_drivezone: bool = False,
) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(6.0, 2.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    rcsdnode_features = [
        {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
    ]
    if rcsdroad_outside_drivezone:
        rcsdroad_path = tmp_path / "rcsdroad_outside.gpkg"
        write_vector(
            rcsdroad_path,
            [
                {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 155.0)])},
                {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
                {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
            ],
            crs_text="EPSG:3857",
        )
        rcsdnode_features[1] = {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 155.0)}
    elif rcsdnode_outside_drivezone:
        rcsdnode_features[1] = {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 155.0)}
    write_vector(rcsdnode_path, rcsdnode_features, crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


@pytest.mark.parametrize("kind_2", [8, 16])
def test_stage4_accepts_kind_8_and_16_and_writes_independent_outputs(tmp_path: Path, kind_2: int) -> None:
    paths = _write_fixture(tmp_path, kind_2=kind_2)
    original_nodes = _load_vector_doc(paths["nodes_path"])
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id=f"kind_{kind_2}",
        **paths,
    )

    assert artifacts.success is True
    assert artifacts.virtual_polygon_path.is_file()
    assert artifacts.node_link_json_path.is_file()
    assert artifacts.rcsdnode_link_json_path.is_file()
    assert artifacts.audit_json_path.is_file()
    assert not (artifacts.out_root / "nodes.gpkg").exists()

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    assert len(polygon_doc["features"]) == 1
    assert polygon_doc["features"][0]["properties"]["mainnodeid"] == "100"
    assert polygon_doc["features"][0]["properties"]["acceptance_class"] == "accepted"

    node_link = json.loads(artifacts.node_link_json_path.read_text(encoding="utf-8"))
    rcsdnode_link = json.loads(artifacts.rcsdnode_link_json_path.read_text(encoding="utf-8"))
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))

    assert node_link["mainnodeid"] == "100"
    assert node_link["target_node_ids"] == ["100", "101"]
    assert rcsdnode_link["mainnodeid"] == "100"
    assert "100" in rcsdnode_link["linked_node_ids"]
    assert audit_doc["audit_count"] == 1
    assert audit_doc["rows"][0]["reason"] == "stable"
    assert _load_vector_doc(paths["nodes_path"]) == original_nodes


def test_stage4_rejects_when_rcsdnode_or_rcsdroad_leaves_drivezone(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, kind_2=8, rcsdroad_outside_drivezone=True)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="outside_drivezone",
        **paths,
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["success"] is False
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsd_outside_drivezone"


def test_stage4_rejects_when_rcsdnode_leaves_drivezone(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, kind_2=16, rcsdnode_outside_drivezone=True)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="rcsdnode_outside_drivezone",
        **paths,
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["success"] is False
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsd_outside_drivezone"


def test_cover_check_requires_true_geometric_coverage() -> None:
    missing_ids = _cover_check(
        box(0.0, 0.0, 1.0, 1.0),
        [
            ParsedNode(
                feature_index=0,
                properties={},
                geometry=Point(0.5, 0.5),
                node_id="inside",
                mainnodeid="100",
                has_evd="yes",
                is_anchor="no",
                kind_2=8,
                grade_2=1,
            ),
            ParsedNode(
                feature_index=1,
                properties={},
                geometry=Point(1.2, 0.5),
                node_id="near_outside",
                mainnodeid=None,
                has_evd=None,
                is_anchor=None,
                kind_2=None,
                grade_2=None,
            ),
        ],
    )

    assert missing_ids == ["near_outside"]
