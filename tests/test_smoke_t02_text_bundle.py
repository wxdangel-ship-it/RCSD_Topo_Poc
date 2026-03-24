from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc import cli
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


@pytest.mark.smoke
def test_smoke_t02_text_bundle_roundtrip() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_text_bundle") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    decoded_dir = root / "decoded"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"
    bundle_path = outputs_dir / "smoke_case.txt"

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
            }
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

    export_exit_code = cli.main(
        [
            "t02-export-text-bundle",
            "--nodes-path",
            str(nodes_path),
            "--roads-path",
            str(roads_path),
            "--drivezone-path",
            str(drivezone_path),
            "--rcsdroad-path",
            str(rcsdroad_path),
            "--rcsdnode-path",
            str(rcsdnode_path),
            "--mainnodeid",
            "100",
            "--out-txt",
            str(bundle_path),
        ]
    )
    assert export_exit_code == 0
    assert bundle_path.is_file()
    assert bundle_path.stat().st_size <= 300 * 1024

    decode_exit_code = cli.main(
        [
            "t02-decode-text-bundle",
            "--bundle-txt",
            str(bundle_path),
            "--out-dir",
            str(decoded_dir),
        ]
    )
    assert decode_exit_code == 0

    manifest_path = decoded_dir / "manifest.json"
    size_report_path = decoded_dir / "size_report.json"
    assert manifest_path.is_file()
    assert size_report_path.is_file()
    assert (decoded_dir / "drivezone_mask.png").is_file()
    assert (decoded_dir / "nodes.gpkg").is_file()
    assert (decoded_dir / "roads.gpkg").is_file()
    assert (decoded_dir / "rcsdroad.gpkg").is_file()
    assert (decoded_dir / "rcsdnode.gpkg").is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    size_report = json.loads(size_report_path.read_text(encoding="utf-8"))
    assert manifest["mainnodeid"] == "100"
    assert size_report["within_limit"] is True
