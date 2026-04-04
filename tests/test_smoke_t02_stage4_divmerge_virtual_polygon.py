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
def test_smoke_t02_stage4_divmerge_virtual_polygon() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_stage4_divmerge_virtual_polygon") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    divstripzone_path = inputs_dir / "divstripzone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 8,
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
                    "kind_2": 8,
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
        divstripzone_path,
        [{"properties": {"id": "divstrip_0"}, "geometry": box(18.0, -4.0, 30.0, 4.0)}],
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

    exit_code = cli.main(
        [
            "t02-stage4-divmerge-virtual-polygon",
            "--nodes_path",
            str(nodes_path),
            "--roads_path",
            str(roads_path),
            "--drivezone_path",
            str(drivezone_path),
            "--divstripzone_path",
            str(divstripzone_path),
            "--rcsdroad_path",
            str(rcsdroad_path),
            "--rcsdnode_path",
            str(rcsdnode_path),
            "--mainnodeid",
            "100",
            "--out_dir",
            str(outputs_dir),
            "--run-id",
            "smoke_case",
            "--debug",
        ]
    )

    assert exit_code == 0
    run_dir = outputs_dir / "smoke_case"
    assert (run_dir / "stage4_virtual_polygon.gpkg").is_file()
    assert (run_dir / "stage4_node_link.json").is_file()
    assert (run_dir / "stage4_rcsdnode_link.json").is_file()
    assert (run_dir / "stage4_audit.json").is_file()
    assert (run_dir / "stage4_debug" / "100.png").is_file()

    status_doc = json.loads((run_dir / "stage4_status.json").read_text(encoding="utf-8"))
    assert status_doc["success"] is True
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["divstrip_component_count"] == 1
    assert status_doc["multibranch"]["multibranch_enabled"] is False
    assert status_doc["multibranch"]["event_candidate_count"] == 0
    assert isinstance(status_doc["reverse_tip"]["reverse_tip_attempted"], bool)
    assert isinstance(status_doc["reverse_tip"]["reverse_tip_used"], bool)
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is False
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_1"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_rule"] == "merge_main_seed_on_post_trunk_le_20m"
    assert isinstance(status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"], bool)
