from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from rcsd_topo_poc import cli
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_geojson


@pytest.mark.smoke
def test_smoke_t02_stage2_anchor_recognition() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_stage2") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    segment_path = inputs_dir / "segment.geojson"
    nodes_path = inputs_dir / "nodes.geojson"
    intersection_path = inputs_dir / "intersection.geojson"

    write_geojson(
        segment_path,
        [
            {
                "properties": {"id": "seg-1", "pair_nodes": "1,2", "junc_nodes": "", "s_grade": "0-0双"},
                "geometry": None,
            }
        ],
    )
    write_geojson(
        nodes_path,
        [
            {
                "properties": {"id": 1, "mainnodeid": 1, "has_evd": "yes", "kind_2": 4, "grade_2": 1},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": 2, "mainnodeid": None, "has_evd": "yes", "kind_2": 2048, "grade_2": 1},
                "geometry": Point(10.0, 0.0),
            },
            {
                "properties": {"id": 101, "mainnodeid": 1, "has_evd": None, "kind_2": None, "grade_2": None},
                "geometry": Point(10.0, 0.1),
            },
        ],
    )
    write_geojson(
        intersection_path,
        [
            {
                "properties": {"id": "A"},
                "geometry": Polygon(
                    [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)]
                ),
            },
            {
                "properties": {"id": "B"},
                "geometry": Polygon(
                    [(9.5, -0.5), (10.5, -0.5), (10.5, 0.5), (9.5, 0.5), (9.5, -0.5)]
                ),
            },
        ],
    )

    exit_code = cli.main(
        [
            "t02-stage2-anchor-recognition",
            "--segment-path",
            str(segment_path),
            "--nodes-path",
            str(nodes_path),
            "--intersection-path",
            str(intersection_path),
            "--out-root",
            str(outputs_dir),
            "--run-id",
            "smoke_case",
        ]
    )

    assert exit_code == 0
    run_dir = outputs_dir / "smoke_case"
    assert (run_dir / "t02_stage2_summary.json").is_file()
    assert (run_dir / "nodes.geojson").is_file()
    assert (run_dir / "node_error_1.geojson").is_file()
    assert (run_dir / "node_error_1_audit.csv").is_file()
    assert (run_dir / "node_error_1_audit.json").is_file()
    assert (run_dir / "node_error_2.geojson").is_file()
    assert (run_dir / "node_error_2_audit.csv").is_file()
    assert (run_dir / "node_error_2_audit.json").is_file()
    assert (run_dir / "t02_stage2_audit.csv").is_file()
    assert (run_dir / "t02_stage2_audit.json").is_file()
    assert (run_dir / "t02_stage2_progress.json").is_file()
    assert (run_dir / "t02_stage2_perf.json").is_file()
    assert (run_dir / "t02_stage2_perf_markers.jsonl").is_file()

    nodes_doc = json.loads((run_dir / "nodes.geojson").read_text(encoding="utf-8"))
    node_props_by_id = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    assert node_props_by_id["1"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["is_anchor"] == "fail2"
    assert node_props_by_id["101"]["is_anchor"] is None

    summary_doc = json.loads((run_dir / "t02_stage2_summary.json").read_text(encoding="utf-8"))
    assert summary_doc["anchor_summary_by_s_grade"]["0-0双"]["total_segment_count"] == 1
    assert summary_doc["anchor_summary_by_s_grade"]["0-0双"]["pair_nodes_all_anchor_segment_count"] == 0
    assert summary_doc["anchor_summary_by_kind_grade"]["kind2_4_64_grade2_1"]["evidence_junction_count"] == 1
    assert summary_doc["anchor_summary_by_kind_grade"]["kind2_4_64_grade2_1"]["anchored_junction_count"] == 0
