from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "t06_run_innernet_precheck.py"


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _write_crs84_relation(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "name": path.stem,
        "crs": {"type": "name", "properties": {"name": "CRS84"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"target_id": 1, "base_id": 10, "status": 0, "level": 1, "is_highway": 0},
                "geometry": {"type": "Point", "coordinates": [1.0, 0.0]},
            },
            {
                "type": "Feature",
                "properties": {"target_id": 2, "base_id": 20, "status": 0, "level": 1, "is_highway": 0},
                "geometry": {"type": "Point", "coordinates": [2.0, 0.0]},
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_innernet_script_runs_t06_precheck_with_explicit_paths(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(1, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(2, 0)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [{"properties": {"id": "sr1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    t05_root = tmp_path / "t05_phase2"
    relation = _write_crs84_relation(t05_root / "intersection_match_all.geojson")
    rcsdnode = _write(
        t05_root / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(2, 0)},
        ],
    )
    rcsdroad = _write(
        t05_root / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in [segment, nodes, swsd_roads, relation, rcsdnode, rcsdroad]}

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--swsd-segment",
            str(segment),
            "--swsd-roads",
            str(swsd_roads),
            "--swsd-nodes",
            str(nodes),
            "--t05-phase2-root",
            str(t05_root),
            "--out-root",
            str(tmp_path / "out"),
            "--run-id",
            "run",
            "--no-progress",
        ],
        check=True,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in [segment, nodes, swsd_roads, relation, rcsdnode, rcsdroad]}
    assert after == before
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["step1"]["swsd_candidate_count"] == 1
    assert payload["step1"]["final_fusion_unit_count"] == 1
    assert payload["step1"]["swsd_final_fusion_unit_count"] == 1
    assert Path(payload["step1"]["swsd_candidates"]).is_file()
    assert Path(payload["step1"]["swsd_final_fusion_units"]).is_file()
    assert payload["step2"]["replaceable_count"] == 1
    assert Path(payload["step2"]["replaceable"]).is_file()
