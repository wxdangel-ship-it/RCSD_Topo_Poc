from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc import cli
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


@pytest.mark.smoke
def test_smoke_t02_stage1_drivezone_gate() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_stage1") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    segment_path = inputs_dir / "segment.gpkg"
    nodes_path = inputs_dir / "nodes.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"

    write_vector(
        segment_path,
        [
            {
                "properties": {
                    "id": "seg-1",
                    "pair_nodes": "1",
                    "junc_nodes": "",
                    "sgrade": "0-1双",
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        nodes_path,
        [
            {
                "properties": {"id": 1, "mainnodeid": None, "kind_2": 4, "grade_2": 1},
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": Polygon(
                    [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )

    exit_code = cli.main(
        [
            "t02-stage1-drivezone-gate",
            "--segment-path",
            str(segment_path),
            "--nodes-path",
            str(nodes_path),
            "--drivezone-path",
            str(drivezone_path),
            "--out-root",
            str(outputs_dir),
            "--run-id",
            "smoke_case",
        ]
    )

    assert exit_code == 0
    run_dir = outputs_dir / "smoke_case"
    assert (run_dir / "nodes.gpkg").is_file()
    assert (run_dir / "segment.gpkg").is_file()
    assert (run_dir / "t02_stage1_summary.json").is_file()
    assert (run_dir / "t02_stage1_audit.csv").is_file()
    assert (run_dir / "t02_stage1_progress.json").is_file()
    assert (run_dir / "t02_stage1_perf.json").is_file()
    assert (run_dir / "t02_stage1_perf_markers.jsonl").is_file()

    summary_doc = json.loads((run_dir / "t02_stage1_summary.json").read_text(encoding="utf-8"))
    assert summary_doc["success"] is True
    assert summary_doc["counts"]["segment_has_evd_count"] == 1
    assert summary_doc["summary_by_s_grade"]["all__d_sgrade"] == {
        "segment_count": 1,
        "segment_has_evd_count": 1,
        "junction_count": 1,
        "junction_has_evd_count": 1,
    }
    assert summary_doc["summary_by_kind_grade"] == {
        "kind2_4_64_grade2_1": {
            "junction_count": 1,
            "junction_has_evd_count": 1,
        },
        "kind2_4_64_grade2_0_2_3": {
            "junction_count": 0,
            "junction_has_evd_count": 0,
        },
        "kind2_2048": {
            "junction_count": 0,
            "junction_has_evd_count": 0,
        },
        "kind2_8_16": {
            "junction_count": 0,
            "junction_has_evd_count": 0,
        },
    }
