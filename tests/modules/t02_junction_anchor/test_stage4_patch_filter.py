from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_divmerge_virtual_polygon import (
    run_t02_stage4_divmerge_virtual_polygon,
)


def _write_stage4_patch_filter_fixture(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(6.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
            {"properties": {"id": "road_noise_patch2", "snodeid": "500", "enodeid": "501", "direction": 2, "patchid": "p2"}, "geometry": LineString([(35.0, 42.0), (62.0, 42.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {"properties": {"patchid": "p1"}, "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)])},
            {"properties": {"patchid": "p2"}, "geometry": box(30.0, 34.0, 70.0, 50.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {"properties": {"id": "divstrip_p1", "patchid": "p1"}, "geometry": box(18.0, -4.0, 30.0, 4.0)},
            {"properties": {"id": "divstrip_p2", "patchid": "p2"}, "geometry": box(36.0, 38.0, 48.0, 46.0)},
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
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def test_stage4_uses_only_same_patch_roads_drivezone_and_divstripzone(tmp_path: Path) -> None:
    fixture = _write_stage4_patch_filter_fixture(tmp_path)

    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="same_patch_only",
        **fixture,
    )

    assert artifacts.status_doc is not None
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "review_required"
    counts = status_doc["counts"]
    assert counts["current_patch_id"] == "p1"
    assert counts["selected_road_count"] == 3
    assert status_doc["step2_context"]["patch_divstrip_feature_count"] == 1


def test_stage4_keeps_multi_patch_features_when_current_patch_is_in_membership(tmp_path: Path) -> None:
    fixture = _write_stage4_patch_filter_fixture(tmp_path)

    write_vector(
        fixture["roads_path"],
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2, "patchid": "p1"}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
            {"properties": {"id": "road_east_shared", "snodeid": "100", "enodeid": "401", "direction": 2, "patchid": "p0,p1"}, "geometry": LineString([(0.0, 0.0), (65.0, 6.0)])},
            {"properties": {"id": "road_noise_patch2", "snodeid": "500", "enodeid": "501", "direction": 2, "patchid": "p2"}, "geometry": LineString([(35.0, 42.0), (62.0, 42.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        fixture["drivezone_path"],
        [
            {"properties": {"patchid": "p1"}, "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)])},
            {"properties": {"patchid": "p0,p1"}, "geometry": box(0.0, -2.0, 72.0, 14.0)},
            {"properties": {"patchid": "p2"}, "geometry": box(30.0, 34.0, 70.0, 50.0)},
        ],
        crs_text="EPSG:3857",
    )

    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out_multi_patch",
        run_id="keep_multi_patch_membership",
        **fixture,
    )

    assert artifacts.status_doc is not None
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "review_required"
    counts = status_doc["counts"]
    assert counts["current_patch_id"] == "p1"
    assert counts["selected_road_count"] == 4
