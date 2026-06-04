from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.text_bundle import (
    run_t03_decode_text_bundle,
    run_t03_export_text_bundle,
    run_t04_decode_text_bundle,
    run_t04_export_text_bundle,
)


def _write_bundle_inputs(root: Path) -> dict[str, Path]:
    nodes_path = root / "nodes.gpkg"
    roads_path = root / "roads.gpkg"
    drivezone_path = root / "drivezone.gpkg"
    divstripzone_path = root / "divstripzone.gpkg"
    rcsdroad_path = root / "rcsdroad.gpkg"
    rcsdnode_path = root / "rcsdnode.gpkg"

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
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north_100", "snodeid": "100", "enodeid": "9001", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_east_100", "snodeid": "100", "enodeid": "9002", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
            {"properties": {"id": "road_north_200", "snodeid": "200", "enodeid": "9003", "direction": 2}, "geometry": LineString([(220.0, 0.0), (220.0, 60.0)])},
            {"properties": {"id": "road_east_200", "snodeid": "200", "enodeid": "9004", "direction": 2}, "geometry": LineString([(220.0, 0.0), (275.0, 0.0)])},
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
                        box(-15.0, -15.0, 75.0, 75.0),
                        box(205.0, -15.0, 295.0, 75.0),
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
            {"properties": {"id": "rc_east_100", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
            {"properties": {"id": "rc_north_200", "snodeid": "200", "enodeid": "911", "direction": 2}, "geometry": LineString([(220.0, 0.0), (220.0, 55.0)])},
            {"properties": {"id": "rc_east_200", "snodeid": "200", "enodeid": "913", "direction": 2}, "geometry": LineString([(220.0, 0.0), (265.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
            {"properties": {"id": "200", "mainnodeid": "200"}, "geometry": Point(220.0, 0.0)},
            {"properties": {"id": "911", "mainnodeid": None}, "geometry": Point(220.0, 55.0)},
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


def test_t03_text_bundle_exports_split_and_decodes_t04_ready_case_packages(tmp_path: Path) -> None:
    inputs = _write_bundle_inputs(tmp_path)
    out_txt = tmp_path / "bundle.txt"

    artifacts = run_t03_export_text_bundle(
        **inputs,
        mainnodeid=["100", "200"],
        out_txt=out_txt,
        max_text_size_bytes=12_000,
    )

    assert artifacts.success
    assert artifacts.module_name == "t03"
    assert artifacts.part_txt_paths
    assert all(path.is_file() for path in artifacts.part_txt_paths)
    assert all(path.stat().st_size <= 12_000 for path in artifacts.part_txt_paths)

    decoded = run_t03_decode_text_bundle(bundle_txt=out_txt, out_dir=tmp_path / "decoded")

    assert decoded.success
    assert decoded.split_bundle is not None
    assert {path.name for path in decoded.case_dirs} == {"100", "200"}
    assert (decoded.out_dir / "100" / "manifest.json").is_file()
    assert (decoded.out_dir / "100" / "divstripzone.gpkg").is_file()
    manifest = json.loads((decoded.out_dir / "100" / "manifest.json").read_text(encoding="utf-8"))
    assert "divstripzone.gpkg" in manifest["file_list"]


def test_t04_text_bundle_alias_uses_same_common_payload(tmp_path: Path) -> None:
    inputs = _write_bundle_inputs(tmp_path)
    out_txt = tmp_path / "t04_bundle.txt"

    artifacts = run_t04_export_text_bundle(
        **inputs,
        mainnodeid="100",
        out_txt=out_txt,
        max_text_size_bytes=256_000,
    )
    decoded = run_t04_decode_text_bundle(bundle_txt=out_txt, out_dir=tmp_path / "decoded_t04")

    assert artifacts.success
    assert artifacts.module_name == "t04"
    assert decoded.module_name == "t04"
    assert decoded.case_dirs == (decoded.out_dir,)
    assert (decoded.out_dir / "divstripzone.gpkg").is_file()
