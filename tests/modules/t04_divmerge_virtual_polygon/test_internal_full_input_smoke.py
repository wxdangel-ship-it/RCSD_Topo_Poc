from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_internal_full_input

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import (
    _build_synthetic_case_package,
)


@pytest.mark.smoke
def test_t04_internal_full_input_smoke_outputs_final_flat_review(tmp_path: Path) -> None:
    case_dir = tmp_path / "full_input_source" / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_internal_full_input(
        nodes_path=case_dir / "nodes.gpkg",
        roads_path=case_dir / "roads.gpkg",
        drivezone_path=case_dir / "drivezone.gpkg",
        divstripzone_path=case_dir / "divstripzone.gpkg",
        rcsdroad_path=case_dir / "rcsdroad.gpkg",
        rcsdnode_path=case_dir / "rcsdnode.gpkg",
        out_root=tmp_path / "out",
        run_id="t04_internal_smoke",
        workers=1,
        max_cases=1,
        resume=False,
        retry_failed=False,
        perf_audit=True,
        perf_audit_interval_sec=1,
        perf_audit_max_samples=4,
        perf_audit_max_bytes=20_000,
    ).run_root

    preflight = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    progress = json.loads((run_root / "t04_internal_full_input_progress.json").read_text(encoding="utf-8"))
    consistency = json.loads((run_root / "step7_consistency_report.json").read_text(encoding="utf-8"))

    assert preflight["selected_case_ids"] == ["1001"]
    assert (run_root / "candidate_mainnodeids.txt").read_text(encoding="utf-8").strip() == "1001"
    assert (run_root / "candidate_manifest.json").is_file()
    assert (run_root / "shared_layers_manifest.json").is_file()
    assert (run_root / "bootstrap_stats.json").is_file()
    assert progress["phase"] == "completed"
    assert progress["status"] == "completed"
    assert progress["entered_case_execution"] is True
    assert summary["accepted_count"] + summary["rejected_count"] == 1
    assert summary["runtime_failed_count"] == 0
    assert consistency["passed"] is True

    assert (run_root / "divmerge_virtual_anchor_surface.gpkg").is_file()
    assert (run_root / "divmerge_virtual_anchor_surface_rejected.geojson").is_file()
    assert (run_root / "divmerge_virtual_anchor_surface_summary.csv").is_file()
    assert (run_root / "divmerge_virtual_anchor_surface_summary.json").is_file()
    assert (run_root / "divmerge_virtual_anchor_surface_audit.gpkg").is_file()
    assert (run_root / "step7_rejected_index.csv").is_file()
    assert (run_root / "step7_rejected_index.json").is_file()

    visual_root = run_root / "visual_checks"
    assert (visual_root / "final_by_state" / "accepted").is_dir()
    assert (visual_root / "final_by_state" / "rejected").is_dir()
    assert (visual_root / "final_flat").is_dir()
    flat_pngs = sorted((visual_root / "final_flat").glob("*.png"))
    assert len(flat_pngs) == 1
    assert flat_pngs[0].name.startswith("0001__1001__")
    assert flat_pngs[0].name.endswith(".png")
    assert "__review__" not in flat_pngs[0].name

    with (visual_root / "final_index.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "1001"
    assert rows[0]["final_state"] in {"accepted", "rejected"}
    assert Path(rows[0]["image_path"]).is_file()
    assert Path(rows[0]["step7_status_path"]).is_file()
    assert Path(rows[0]["audit_path"]).is_file()
    assert (visual_root / "final_index.json").is_file()


@pytest.mark.smoke
def test_t04_internal_full_input_watch_once(tmp_path: Path) -> None:
    case_dir = tmp_path / "full_input_source" / "1001"
    _build_synthetic_case_package(case_dir)
    artifacts = run_t04_internal_full_input(
        nodes_path=case_dir / "nodes.gpkg",
        roads_path=case_dir / "roads.gpkg",
        drivezone_path=case_dir / "drivezone.gpkg",
        divstripzone_path=case_dir / "divstripzone.gpkg",
        rcsdroad_path=case_dir / "rcsdroad.gpkg",
        rcsdnode_path=case_dir / "rcsdnode.gpkg",
        out_root=tmp_path / "out_watch",
        run_id="t04_internal_watch_smoke",
        workers=1,
        max_cases=1,
        resume=False,
        retry_failed=False,
        perf_audit=False,
    )
    repo_root = Path(__file__).resolve().parents[3]
    env = {
        **os.environ,
        "PYTHON_BIN": sys.executable,
        "RUN_ROOT": str(artifacts.run_root),
        "ONCE": "1",
        "CLEAR_SCREEN": "0",
        "CASE_SCAN": "on",
    }
    result = subprocess.run(
        [str(repo_root / "scripts" / "t04_watch_internal_full_input.sh")],
        cwd=repo_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    assert "[COUNTS]" in result.stdout
    assert "selected=1" in result.stdout
    assert "completed=1" in result.stdout
    assert "runtime_failed=0" in result.stdout
    assert "[PERF]" in result.stdout
