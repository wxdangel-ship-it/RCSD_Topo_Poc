from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc import cli
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_geojson


@pytest.mark.smoke
def test_smoke_t02_stage1_drivezone_gate() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_stage1") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    segment_path = inputs_dir / "segment.geojson"
    nodes_path = inputs_dir / "nodes.geojson"
    drivezone_path = inputs_dir / "drivezone.geojson"

    write_geojson(
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
    )
    write_geojson(
        nodes_path,
        [
            {
                "properties": {"id": 1, "mainnodeid": None},
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    write_geojson(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": Polygon(
                    [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)]
                ),
            }
        ],
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
    assert (outputs_dir / "nodes.geojson").is_file()
    assert (outputs_dir / "segment.geojson").is_file()
    assert (outputs_dir / "t02_stage1_summary.json").is_file()
    assert (outputs_dir / "t02_stage1_audit.csv").is_file()

    summary_doc = json.loads((outputs_dir / "t02_stage1_summary.json").read_text(encoding="utf-8"))
    assert summary_doc["success"] is True
    assert summary_doc["counts"]["segment_has_evd_count"] == 1
