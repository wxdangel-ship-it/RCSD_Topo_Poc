from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "t06_run_step3_segment_replacement.py"


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def test_step3_script_consumes_step2_outputs_and_writes_summary(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [{"properties": {"id": "sr1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 1, "kind": 4, "grade": 1, "kind_2": 4, "grade_2": 1, "closed_con": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 2, "mainnodeid": 2, "kind": 4, "grade": 1, "kind_2": 4, "grade_2": 1, "closed_con": 0}, "geometry": Point(2, 0)},
        ],
    )
    t05_root = tmp_path / "t05_phase2"
    rcsdroad = _write(
        t05_root / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    rcsdnode = _write(
        t05_root / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 10}, "geometry": Point(1, 0)},
            {"properties": {"id": 20, "mainnodeid": 20}, "geometry": Point(2, 0)},
        ],
    )
    t06_run_root = tmp_path / "t06" / "run"
    replaceable = _write(
        t06_run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                },
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in [segment, swsd_roads, swsd_nodes, rcsdroad, rcsdnode, replaceable]}

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--t06-run-root",
            str(t06_run_root),
            "--swsd-segment",
            str(segment),
            "--swsd-roads",
            str(swsd_roads),
            "--swsd-nodes",
            str(swsd_nodes),
            "--t05-phase2-root",
            str(t05_root),
            "--no-progress",
        ],
        check=True,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in [segment, swsd_roads, swsd_nodes, rcsdroad, rcsdnode, replaceable]}
    assert after == before
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["step3"]["input_replaceable_count"] == 1
    assert payload["step3"]["replacement_unit_success_count"] == 1
    assert Path(payload["step3"]["frcsd_road"]).is_file()
    assert Path(payload["step3"]["frcsd_node"]).is_file()
