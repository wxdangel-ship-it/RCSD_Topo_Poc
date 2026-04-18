from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.internal_full_input_runner import (
    run_t03_step67_internal_full_input,
)


def test_internal_full_input_runner_prepares_case_packages_and_runs_step67(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    out_root = tmp_path / "out"
    visual_check_dir = tmp_path / "visual_checks"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100001",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
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
            {
                "properties": {"id": "road_h", "snodeid": "100001", "enodeid": "n2", "direction": 2},
                "geometry": LineString([(-30.0, 0.0), (30.0, 0.0)]),
            },
            {
                "properties": {"id": "road_v", "snodeid": "n3", "enodeid": "100001", "direction": 2},
                "geometry": LineString([(0.0, -30.0), (0.0, 30.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": box(-60.0, -60.0, 60.0, 60.0)}],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rc_r_1", "snodeid": "rc_a", "enodeid": "rc_n_1", "direction": 2},
                "geometry": LineString([(-12.0, 2.0), (12.0, 2.0)]),
            },
            {
                "properties": {"id": "rc_r_2", "snodeid": "rc_n_1", "enodeid": "rc_b", "direction": 2},
                "geometry": LineString([(2.0, -12.0), (2.0, 12.0)]),
            },
            {
                "properties": {"id": "rc_r_3", "snodeid": "rc_n_1", "enodeid": "rc_c", "direction": 2},
                "geometry": LineString([(2.0, 2.0), (12.0, 12.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {
                "properties": {"id": "rc_n_1", "mainnodeid": "rc_g_1"},
                "geometry": Point(2.0, 2.0),
            }
        ],
        crs_text="EPSG:3857",
    )

    artifacts = run_t03_step67_internal_full_input(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id="internal_full_input_case",
        workers=1,
        max_cases=1,
        debug=False,
        review_mode=True,
        visual_check_dir=visual_check_dir,
    )

    case_dir = artifacts.case_root / "100001"
    step3_case_dir = artifacts.step3_run_root / "cases" / "100001"
    step67_case_dir = artifacts.run_root / "cases" / "100001"
    summary_doc = json.loads((artifacts.run_root / "summary.json").read_text(encoding="utf-8"))
    internal_manifest = json.loads((artifacts.internal_root / "internal_full_input_manifest.json").read_text(encoding="utf-8"))
    internal_progress = json.loads((artifacts.internal_root / "internal_full_input_progress.json").read_text(encoding="utf-8"))
    case_progress = json.loads((artifacts.internal_root / "case_progress" / "100001.json").read_text(encoding="utf-8"))
    watch_status = json.loads((step67_case_dir / "step67_watch_status.json").read_text(encoding="utf-8"))

    assert artifacts.selected_case_ids == ("100001",)
    assert (case_dir / "manifest.json").is_file()
    assert (step3_case_dir / "step3_status.json").is_file()
    assert (step67_case_dir / "step7_status.json").is_file()
    assert (step67_case_dir / "step67_watch_status.json").is_file()
    assert summary_doc["effective_case_ids"] == ["100001"]
    assert summary_doc["flat_png_count"] == 1
    assert sorted(path.name for path in visual_check_dir.glob("*.png")) == [
        "0001_100001_accepted_center_junction.png"
    ]
    assert internal_progress["phase"] == "completed"
    assert internal_progress["status"] == "completed"
    assert case_progress["state"] == "step3_ready"
    assert watch_status["state"] == "accepted"
    assert watch_status["current_stage"] == "completed"
    assert internal_manifest["review_mode_requested"] is True
    assert internal_manifest["review_mode_effective"] is False
