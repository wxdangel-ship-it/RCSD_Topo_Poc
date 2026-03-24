from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import run_t02_virtual_intersection_poc


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _write_poc_inputs(
    tmp_path: Path,
    *,
    representative_overrides: dict[str, object] | None = None,
    rc_west_inside: bool = True,
    include_rc_group: bool = True,
) -> dict[str, Path]:
    representative_props = {
        "id": "100",
        "mainnodeid": "100",
        "has_evd": "yes",
        "is_anchor": "no",
        "kind_2": 2048,
        "grade_2": 1,
    }
    if representative_overrides:
        representative_props.update(representative_overrides)

    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": representative_props,
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (0.0, 60.0)]),
            },
            {
                "properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2},
                "geometry": LineString([(0.0, -60.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (55.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    drivezone_geometry = unary_union(
        [
            box(-12.0, -70.0, 12.0, 70.0),
            box(0.0, -12.0, 75.0, 12.0),
            box(-25.0, -8.0, 0.0, 8.0),
        ]
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": drivezone_geometry}],
        crs_text="EPSG:3857",
    )

    west_geometry = LineString([(-18.0, 0.0), (0.0, 0.0)]) if rc_west_inside else LineString([(-40.0, 30.0), (-20.0, 30.0)])
    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (0.0, 55.0)]),
            },
            {
                "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2},
                "geometry": LineString([(0.0, -55.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (45.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_west", "snodeid": "904", "enodeid": "100", "direction": 2},
                "geometry": west_geometry,
            },
        ],
        crs_text="EPSG:3857",
    )

    rcsdnode_features = [
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        {"properties": {"id": "904", "mainnodeid": None}, "geometry": Point(-18.0 if rc_west_inside else -40.0, 0.0 if rc_west_inside else 30.0)},
    ]
    if include_rc_group:
        rcsdnode_features.insert(0, {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)})
    write_vector(rcsdnode_path, rcsdnode_features, crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def test_virtual_intersection_poc_fails_when_mainnodeid_missing(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="missing", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit_doc[0]["reason"] == "mainnodeid_not_found"


def test_virtual_intersection_poc_fails_when_target_out_of_scope(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"is_anchor": "yes"})
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "mainnodeid_out_of_scope"


def test_virtual_intersection_poc_generates_polygon_branch_evidence_and_rc_associations(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon = shape(polygon_doc["features"][0]["geometry"])
    assert polygon.area > 100.0

    branch_doc = json.loads(artifacts.branch_evidence_json_path.read_text(encoding="utf-8"))
    road_branches = branch_doc["branches"]
    assert len(road_branches) >= 3
    assert sum(1 for item in road_branches if item["is_main_direction"]) == 2
    assert any(item["evidence_level"] in {"arm_partial", "arm_full_rc"} for item in road_branches if not item["is_main_direction"])

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert {"rc_north", "rc_south", "rc_east"} <= associated_road_ids
    assert "rc_west" not in associated_road_ids

    associated_nodes_doc = _load_vector_doc(artifacts.associated_rcsdnode_path)
    associated_node_ids = {feature["properties"]["id"] for feature in associated_nodes_doc["features"]}
    assert {"100", "901", "902", "903"} <= associated_node_ids


def test_virtual_intersection_poc_errors_when_rc_outside_drivezone(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit_doc[0]["reason"] == "rc_outside_drivezone"


def test_virtual_intersection_poc_without_rc_group_returns_surface_only(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, include_rc_group=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"surface_only", "no_valid_rc_connection"}
