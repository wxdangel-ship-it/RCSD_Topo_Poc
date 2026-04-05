from __future__ import annotations

import json
import os
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import (
    LEGACY_TEXT_BUNDLE_CHECKSUM,
    LEGACY_TEXT_BUNDLE_END_PAYLOAD,
    LEGACY_TEXT_BUNDLE_META,
    LEGACY_TEXT_BUNDLE_PAYLOAD,
    OPTIONAL_BUNDLE_FILES,
    TEXT_BUNDLE_BEGIN,
    TEXT_BUNDLE_CHECKSUM,
    TEXT_BUNDLE_END,
    TEXT_BUNDLE_PAYLOAD,
    TEXT_BUNDLE_META,
    REQUIRED_BUNDLE_FILES,
    run_t02_decode_text_bundle,
    run_t02_export_text_bundle,
)


def _vector_feature_count(path: Path) -> int:
    with fiona.open(path) as src:
        return len(src)


def _vector_bounds(path: Path) -> tuple[float, float, float, float]:
    with fiona.open(path) as src:
        return tuple(float(value) for value in src.bounds)


def _vector_has_crs(path: Path) -> bool:
    with fiona.open(path) as src:
        return bool(src.crs) or bool(src.crs_wkt)


def _write_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
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
                    "kind_2": 2048,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": None,
                    "is_anchor": None,
                    "kind_2": 2048,
                    "grade_2": 1,
                },
                "geometry": Point(6.0, 0.0),
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
        divstripzone_path,
        [
            {
                "properties": {"patchid": "p1", "name": "divstrip"},
                "geometry": box(-3.0, -4.0, 14.0, 4.0),
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


def _write_multi_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": "101", "mainnodeid": "100", "has_evd": None, "is_anchor": None, "kind_2": 2048, "grade_2": 1},
                "geometry": Point(6.0, 0.0),
            },
            {
                "properties": {"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1},
                "geometry": Point(220.0, 0.0),
            },
            {
                "properties": {"id": "201", "mainnodeid": "200", "has_evd": None, "is_anchor": None, "kind_2": 2048, "grade_2": 1},
                "geometry": Point(226.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north_100", "snodeid": "100", "enodeid": "2001", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south_100", "snodeid": "3001", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east_100", "snodeid": "100", "enodeid": "4001", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
            {"properties": {"id": "road_north_200", "snodeid": "200", "enodeid": "2002", "direction": 2}, "geometry": LineString([(220.0, 0.0), (220.0, 60.0)])},
            {"properties": {"id": "road_south_200", "snodeid": "3002", "enodeid": "200", "direction": 2}, "geometry": LineString([(220.0, -60.0), (220.0, 0.0)])},
            {"properties": {"id": "road_east_200", "snodeid": "200", "enodeid": "4002", "direction": 2}, "geometry": LineString([(220.0, 0.0), (275.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union(
                    [
                        box(-12.0, -70.0, 12.0, 70.0),
                        box(0.0, -12.0, 75.0, 12.0),
                        box(-25.0, -8.0, 0.0, 8.0),
                        box(208.0, -70.0, 232.0, 70.0),
                        box(220.0, -12.0, 295.0, 12.0),
                        box(195.0, -8.0, 220.0, 8.0),
                    ]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {"properties": {"patchid": "100", "name": "divstrip_100"}, "geometry": box(-3.0, -4.0, 14.0, 4.0)},
            {"properties": {"patchid": "200", "name": "divstrip_200"}, "geometry": box(217.0, -4.0, 236.0, 4.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north_100", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south_100", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east_100", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
            {"properties": {"id": "rc_north_200", "snodeid": "200", "enodeid": "911", "direction": 2}, "geometry": LineString([(220.0, 0.0), (220.0, 55.0)])},
            {"properties": {"id": "rc_south_200", "snodeid": "912", "enodeid": "200", "direction": 2}, "geometry": LineString([(220.0, -55.0), (220.0, 0.0)])},
            {"properties": {"id": "rc_east_200", "snodeid": "200", "enodeid": "913", "direction": 2}, "geometry": LineString([(220.0, 0.0), (265.0, 0.0)])},
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
            {"properties": {"id": "200", "mainnodeid": "200"}, "geometry": Point(220.0, 0.0)},
            {"properties": {"id": "911", "mainnodeid": None}, "geometry": Point(220.0, 55.0)},
            {"properties": {"id": "912", "mainnodeid": None}, "geometry": Point(220.0, -55.0)},
            {"properties": {"id": "913", "mainnodeid": None}, "geometry": Point(265.0, 0.0)},
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


def _write_patch_filtered_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": None, "is_anchor": None, "kind_2": 2048, "grade_2": 1}, "geometry": Point(6.0, 0.0)},
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
            {"properties": {"patchid": "p1", "name": "divstrip_1"}, "geometry": box(-3.0, -4.0, 14.0, 4.0)},
            {"properties": {"patchid": "p2", "name": "divstrip_2"}, "geometry": box(32.0, 38.0, 46.0, 46.0)},
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


def _write_far_branch_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
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
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_west", "snodeid": "001", "enodeid": "100", "direction": 2}, "geometry": LineString([(-60.0, 0.0), (0.0, 0.0)])},
            {"properties": {"id": "road_main", "snodeid": "100", "enodeid": "900", "direction": 2}, "geometry": LineString([(0.0, 0.0), (320.0, 0.0)])},
            {"properties": {"id": "road_branch_up", "snodeid": "901", "enodeid": "902", "direction": 2}, "geometry": LineString([(230.0, 0.0), (230.0, 70.0)])},
            {"properties": {"id": "road_branch_down", "snodeid": "903", "enodeid": "904", "direction": 2}, "geometry": LineString([(230.0, 0.0), (230.0, -70.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz_far"},
                "geometry": unary_union(
                    [
                        box(-70.0, -12.0, 330.0, 12.0),
                        box(220.0, -82.0, 240.0, 82.0),
                    ]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {"properties": {"name": "divstrip_far"}, "geometry": box(214.0, -5.0, 242.0, 5.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_main", "snodeid": "100", "enodeid": "900", "direction": 2}, "geometry": LineString([(0.0, 0.0), (320.0, 0.0)])},
            {"properties": {"id": "rc_up", "snodeid": "905", "enodeid": "906", "direction": 2}, "geometry": LineString([(230.0, 0.0), (230.0, 60.0)])},
            {"properties": {"id": "rc_down", "snodeid": "907", "enodeid": "908", "direction": 2}, "geometry": LineString([(230.0, 0.0), (230.0, -60.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "905", "mainnodeid": None}, "geometry": Point(230.0, 60.0)},
            {"properties": {"id": "907", "mainnodeid": None}, "geometry": Point(230.0, -60.0)},
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


def _write_complex_branch_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "500", "mainnodeid": "500", "has_evd": "yes", "is_anchor": "no", "kind_2": 128, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "501", "mainnodeid": "500", "has_evd": None, "is_anchor": None, "kind_2": 0, "grade_2": 0}, "geometry": Point(180.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_chain_main", "snodeid": "500", "enodeid": "999", "direction": 2}, "geometry": LineString([(0.0, 0.0), (380.0, 0.0)])},
            {"properties": {"id": "road_chain_up_a", "snodeid": "510", "enodeid": "511", "direction": 2}, "geometry": LineString([(120.0, 0.0), (120.0, 70.0)])},
            {"properties": {"id": "road_chain_up_b", "snodeid": "520", "enodeid": "521", "direction": 2}, "geometry": LineString([(320.0, 0.0), (320.0, 75.0)])},
            {"properties": {"id": "road_chain_down_b", "snodeid": "522", "enodeid": "523", "direction": 2}, "geometry": LineString([(350.0, 0.0), (350.0, -75.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz_complex"},
                "geometry": unary_union(
                    [
                        box(-20.0, -12.0, 390.0, 12.0),
                        box(112.0, 0.0, 128.0, 82.0),
                        box(312.0, 0.0, 328.0, 85.0),
                        box(342.0, -85.0, 358.0, 0.0),
                    ]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {"properties": {"name": "divstrip_complex_a"}, "geometry": box(112.0, -5.0, 130.0, 5.0)},
            {"properties": {"name": "divstrip_complex_b"}, "geometry": box(314.0, -5.0, 356.0, 5.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_chain_main", "snodeid": "500", "enodeid": "999", "direction": 2}, "geometry": LineString([(0.0, 0.0), (380.0, 0.0)])},
            {"properties": {"id": "rc_chain_up_b", "snodeid": "524", "enodeid": "525", "direction": 2}, "geometry": LineString([(320.0, 0.0), (320.0, 70.0)])},
            {"properties": {"id": "rc_chain_down_b", "snodeid": "526", "enodeid": "527", "direction": 2}, "geometry": LineString([(350.0, 0.0), (350.0, -70.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "500", "mainnodeid": "500"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "524", "mainnodeid": None}, "geometry": Point(320.0, 70.0)},
            {"properties": {"id": "526", "mainnodeid": None}, "geometry": Point(350.0, -70.0)},
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


def _write_multihop_branch_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "700", "mainnodeid": "700", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_seg_1", "snodeid": "700", "enodeid": "710", "direction": 2}, "geometry": LineString([(0.0, 0.0), (120.0, 0.0)])},
            {"properties": {"id": "road_seg_2", "snodeid": "710", "enodeid": "720", "direction": 2}, "geometry": LineString([(120.0, 0.0), (240.0, 0.0)])},
            {"properties": {"id": "road_seg_3", "snodeid": "720", "enodeid": "730", "direction": 2}, "geometry": LineString([(240.0, 0.0), (360.0, 0.0)])},
            {"properties": {"id": "road_far_branch", "snodeid": "731", "enodeid": "732", "direction": 2}, "geometry": LineString([(350.0, 0.0), (350.0, 90.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz_multihop"},
                "geometry": unary_union([box(-20.0, -12.0, 380.0, 12.0), box(342.0, 0.0, 358.0, 100.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {"properties": {"name": "divstrip_multihop"}, "geometry": box(330.0, -5.0, 360.0, 5.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_far_branch", "snodeid": "733", "enodeid": "734", "direction": 2}, "geometry": LineString([(350.0, 0.0), (350.0, 80.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "700", "mainnodeid": "700"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "733", "mainnodeid": None}, "geometry": Point(350.0, 80.0)},
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


def test_export_text_bundle_fails_when_mainnodeid_missing(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    artifacts = run_t02_export_text_bundle(mainnodeid="missing", out_txt=tmp_path / "case.txt", **paths)
    assert artifacts.success is False
    assert artifacts.failure_reason == "mainnodeid_not_found"
    assert not artifacts.bundle_txt_path.exists()


def test_export_text_bundle_roundtrip_restores_required_files(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)
    assert artifacts.success is True
    assert bundle_path.is_file()
    assert artifacts.bundle_size_bytes <= 300 * 1024

    bundle_text = bundle_path.read_text(encoding="utf-8")
    assert bundle_text.startswith(TEXT_BUNDLE_BEGIN)
    assert TEXT_BUNDLE_END in bundle_text
    assert f"\n{TEXT_BUNDLE_META}" in bundle_text
    assert f"\n{TEXT_BUNDLE_PAYLOAD}\n" in bundle_text
    assert f"\n{TEXT_BUNDLE_CHECKSUM}" in bundle_text
    assert "END_PAYLOAD" not in bundle_text

    decode_dir = tmp_path / "decoded"
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=decode_dir)
    assert decode_artifacts.success is True
    for name in REQUIRED_BUNDLE_FILES:
        assert (decode_dir / name).is_file()
    assert (decode_dir / "divstripzone.gpkg").is_file()

    manifest = json.loads((decode_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mainnodeid"] == "100"
    assert manifest["bundle_version"] == "1"
    assert set(REQUIRED_BUNDLE_FILES) <= set(manifest["file_list"])
    assert "divstripzone.gpkg" in manifest["file_list"]

    size_report = json.loads((decode_dir / "size_report.json").read_text(encoding="utf-8"))
    assert size_report["within_limit"] is True
    assert size_report["total_text_size_bytes"] <= 300 * 1024

    png_header = (decode_dir / "drivezone_mask.png").read_bytes()[:8]
    assert png_header == b"\x89PNG\r\n\x1a\n"

    assert _vector_feature_count(decode_dir / "nodes.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "drivezone.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "divstripzone.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "roads.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "rcsdroad.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "rcsdnode.gpkg") >= 1
    assert _vector_has_crs(decode_dir / "nodes.gpkg")
    assert _vector_has_crs(decode_dir / "roads.gpkg")
    assert _vector_bounds(decode_dir / "nodes.gpkg") == (0.0, 0.0, 6.0, 0.0)

    decoded_manifest = json.loads((decode_dir / "manifest.json").read_text(encoding="utf-8"))
    assert decoded_manifest["decoded_output"]["vector_crs"] == "EPSG:3857"
    assert decoded_manifest["decoded_output"]["vector_coordinates"] == "absolute_epsg3857"


def test_decode_text_bundle_defaults_to_bundle_stem_directory(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "765003.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)
    assert artifacts.success is True

    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path)
    assert decode_artifacts.success is True
    assert decode_artifacts.out_dir == tmp_path / "765003"
    for name in REQUIRED_BUNDLE_FILES:
        assert (decode_artifacts.out_dir / name).is_file()
    assert (decode_artifacts.out_dir / "divstripzone.gpkg").is_file()


def test_export_text_bundle_roundtrip_supports_multiple_mainnodeids(tmp_path: Path) -> None:
    paths = _write_multi_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "multi_case.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid=["100", "200"], out_txt=bundle_path, **paths)
    assert artifacts.success is True
    assert bundle_path.is_file()

    decode_root = tmp_path / "decode_here"
    decode_root.mkdir(parents=True, exist_ok=True)
    current_dir = Path.cwd()
    try:
        os.chdir(decode_root)
        decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path)
    finally:
        os.chdir(current_dir)

    assert decode_artifacts.success is True
    assert decode_artifacts.out_dir == decode_root
    assert decode_artifacts.case_dirs == (decode_root / "100", decode_root / "200")

    bundle_manifest_path = decode_root / "multi_case.bundle_manifest.json"
    assert bundle_manifest_path.is_file()
    bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    assert bundle_manifest["bundle_mode"] == "multi_case"
    assert bundle_manifest["mainnodeids"] == ["100", "200"]

    for case_id in ("100", "200"):
        case_dir = decode_root / case_id
        for name in REQUIRED_BUNDLE_FILES:
            assert (case_dir / name).is_file()
        assert (case_dir / "divstripzone.gpkg").is_file()
        case_manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
        assert case_manifest["bundle_mode"] == "single_case"
        assert case_manifest["mainnodeid"] == case_id
        assert case_manifest["decoded_output"]["vector_crs"] == "EPSG:3857"
        assert _vector_has_crs(case_dir / "nodes.gpkg")

    assert _vector_bounds(decode_root / "100" / "nodes.gpkg") == (0.0, 0.0, 6.0, 0.0)
    assert _vector_bounds(decode_root / "200" / "nodes.gpkg") == (220.0, 0.0, 226.0, 0.0)


def test_decode_text_bundle_accepts_legacy_wrapper_format(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)
    assert artifacts.success is True

    bundle_lines = bundle_path.read_text(encoding="utf-8").splitlines()
    checksum_index = next(index for index, line in enumerate(bundle_lines) if line.startswith(TEXT_BUNDLE_CHECKSUM))

    legacy_lines = []
    for index, line in enumerate(bundle_lines):
        if index == 1 and line.startswith(TEXT_BUNDLE_META):
            legacy_lines.append(LEGACY_TEXT_BUNDLE_META + line[len(TEXT_BUNDLE_META) :])
        elif line == TEXT_BUNDLE_PAYLOAD:
            legacy_lines.append(LEGACY_TEXT_BUNDLE_PAYLOAD)
        elif line.startswith(TEXT_BUNDLE_CHECKSUM):
            legacy_lines.append(LEGACY_TEXT_BUNDLE_CHECKSUM + line[len(TEXT_BUNDLE_CHECKSUM) :])
        else:
            legacy_lines.append(line)
        if index == checksum_index - 1:
            legacy_lines.append(LEGACY_TEXT_BUNDLE_END_PAYLOAD)

    bundle_path.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path)
    assert decode_artifacts.success is True
    assert (decode_artifacts.out_dir / "manifest.json").is_file()


def test_export_text_bundle_fails_with_size_report_when_limit_exceeded(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"
    artifacts = run_t02_export_text_bundle(
        mainnodeid="100",
        out_txt=bundle_path,
        max_text_size_bytes=200,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.failure_reason == "bundle_too_large"
    assert artifacts.size_report_path is not None
    assert artifacts.size_report_path.is_file()
    report = json.loads(artifacts.size_report_path.read_text(encoding="utf-8"))
    assert report["within_limit"] is False
    assert report["total_text_size_bytes"] > 200
    assert report["dominant_size_source"] in (*REQUIRED_BUNDLE_FILES, *OPTIONAL_BUNDLE_FILES)


def test_export_text_bundle_preserves_cross_patch_local_context(tmp_path: Path) -> None:
    paths = _write_patch_filtered_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"

    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)

    assert artifacts.success is True
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded")
    assert decode_artifacts.success is True

    manifest = json.loads((decode_artifacts.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["current_patch_id"] == "p1"
    assert manifest["patch_filter_mode"] == "current_patch_hint_only"

    with fiona.open(decode_artifacts.out_dir / "roads.gpkg") as src:
        road_ids = [feature["properties"]["id"] for feature in src]
    assert sorted(road_ids) == ["road_east", "road_noise_patch2", "road_north", "road_south"]

    with fiona.open(decode_artifacts.out_dir / "drivezone.gpkg") as src:
        drivezone_patch_ids = [feature["properties"].get("patchid") for feature in src]
    assert drivezone_patch_ids == ["p1", "p2"]

    with fiona.open(decode_artifacts.out_dir / "divstripzone.gpkg") as src:
        divstrip_patch_ids = [feature["properties"].get("patchid") for feature in src]
    assert divstrip_patch_ids == ["p1", "p2"]


def test_export_text_bundle_expands_to_far_divmerge_branch_roads(tmp_path: Path) -> None:
    paths = _write_far_branch_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "far_case.txt"

    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)

    assert artifacts.success is True
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_far")
    assert decode_artifacts.success is True

    with fiona.open(decode_artifacts.out_dir / "roads.gpkg") as src:
        road_ids = sorted(feature["properties"]["id"] for feature in src)
    assert road_ids == ["road_branch_down", "road_branch_up", "road_main", "road_west"]

    manifest = json.loads((decode_artifacts.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["feature_counts"]["roads"] == 4


def test_export_text_bundle_expands_to_complex_associated_roads(tmp_path: Path) -> None:
    paths = _write_complex_branch_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "complex_case.txt"

    artifacts = run_t02_export_text_bundle(mainnodeid="500", out_txt=bundle_path, **paths)

    assert artifacts.success is True
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_complex")
    assert decode_artifacts.success is True

    with fiona.open(decode_artifacts.out_dir / "roads.gpkg") as src:
        road_ids = sorted(feature["properties"]["id"] for feature in src)
    assert road_ids == ["road_chain_down_b", "road_chain_main", "road_chain_up_a", "road_chain_up_b"]

    manifest = json.loads((decode_artifacts.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["feature_counts"]["roads"] == 4


def test_export_text_bundle_iteratively_expands_multihop_connected_roads(tmp_path: Path) -> None:
    paths = _write_multihop_branch_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "multihop_case.txt"

    artifacts = run_t02_export_text_bundle(mainnodeid="700", out_txt=bundle_path, **paths)

    assert artifacts.success is True
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_multihop")
    assert decode_artifacts.success is True

    with fiona.open(decode_artifacts.out_dir / "roads.gpkg") as src:
        road_ids = sorted(feature["properties"]["id"] for feature in src)
    assert road_ids == ["road_far_branch", "road_seg_1", "road_seg_2", "road_seg_3"]

    manifest = json.loads((decode_artifacts.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["feature_counts"]["roads"] == 4
