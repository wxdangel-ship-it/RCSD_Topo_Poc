from __future__ import annotations

import json

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step2_extract_rcsd_segments
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step2_progress import Step2Progress


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write(path, features):
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def test_step2_progress_writes_runtime_sidecars(tmp_path):
    progress = Step2Progress(tmp_path, True, total=2, slow_unit_sec=0.0)

    progress.unit(1, "seg_a")
    progress.unit(2, "seg_b")
    progress.group(1, segment_id="seg_group", failure_business_count=3)
    progress.group_done(group_index=1, segment_id="seg_group", group_probe_status="passed")
    progress.stage("replacement_plan")
    progress.finish(replaceable_count=1, replacement_plan_count=1)

    heartbeat = json.loads((tmp_path / "t06_step2_heartbeat.json").read_text(encoding="utf-8"))
    progress_rows = _jsonl(tmp_path / "t06_step2_progress.jsonl")
    slow_rows = _jsonl(tmp_path / "t06_step2_slow_units.jsonl")
    slow_group_rows = _jsonl(tmp_path / "t06_step2_slow_groups.jsonl")

    assert heartbeat["phase"] == "done"
    assert heartbeat["replaceable_count"] == 1
    assert any(row["event"] == "unit_progress" and row["segment_id"] == "seg_a" for row in progress_rows)
    assert any(row["event"] == "group_progress" and row["segment_id"] == "seg_group" for row in progress_rows)
    assert any(row["event"] == "stage" and row["phase"] == "replacement_plan" for row in progress_rows)
    assert {row["segment_id"] for row in slow_rows} == {"seg_a", "seg_b"}
    assert slow_group_rows[0]["event"] == "slow_group"
    assert slow_group_rows[0]["group_probe_status"] == "passed"


def test_step2_progress_disabled_writes_no_sidecars(tmp_path):
    progress = Step2Progress(tmp_path, False, total=1)

    progress.unit(1, "seg_a")
    progress.stage("replacement_plan")
    progress.finish()

    assert not list(tmp_path.iterdir())


def test_step2_runner_progress_writes_sidecars(tmp_path):
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [{"properties": {"swsd_segment_id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 2, "mainnodeid": 0}, "geometry": Point(2, 0)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [{"properties": {"id": "sr1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(1, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(2, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(2, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
        progress=True,
    )

    heartbeat = json.loads((artifacts.step_root / "t06_step2_heartbeat.json").read_text(encoding="utf-8"))
    progress_rows = _jsonl(artifacts.step_root / "t06_step2_progress.jsonl")

    assert heartbeat["phase"] == "done"
    assert heartbeat["replaceable_count"] == 1
    assert any(row["event"] == "stage" and row["phase"] == "replacement_plan" for row in progress_rows)
