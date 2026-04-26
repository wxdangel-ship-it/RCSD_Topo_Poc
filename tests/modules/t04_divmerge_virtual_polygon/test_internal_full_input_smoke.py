from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_internal_full_input
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import internal_full_input_runner
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_core import (
    REASON_RCS_OUTSIDE_DRIVEZONE,
    Stage4RunError,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.full_input_streamed_results import (
    T04TerminalCaseRecord,
    materialize_streamed_case_visual_check,
)

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
    rejected_index = json.loads((run_root / "step7_rejected_index.json").read_text(encoding="utf-8"))

    assert preflight["selected_case_ids"] == ["1001"]
    for doc in [preflight, summary, consistency, rejected_index]:
        assert doc["produced_at"]
        assert doc["git_sha"]
        assert doc["input_dataset_id"].startswith("input-paths-stat-sha256:")
    assert (run_root / "candidate_mainnodeids.txt").read_text(encoding="utf-8").strip() == "1001"
    assert (run_root / "candidate_manifest.json").is_file()
    assert (run_root / "shared_layers_manifest.json").is_file()
    assert (run_root / "bootstrap_stats.json").is_file()
    assert progress["phase"] == "completed"
    assert progress["status"] == "completed"
    assert progress["entered_case_execution"] is True
    assert summary["accepted_count"] + summary["rejected_count"] == 1
    assert summary["guard_failed_count"] == 0
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
    assert (run_root / "step4_review_flat" / "case__1001__final_review.png").is_file()
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


def test_t04_internal_full_input_streams_final_review_flat_png(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    source_png = run_root / "cases" / "1001" / "final_review.png"
    source_png.parent.mkdir(parents=True, exist_ok=True)
    source_png.write_bytes(b"fake-png")
    record = T04TerminalCaseRecord(
        case_id="1001",
        terminal_state="accepted",
        final_state="accepted",
        reject_reason="",
        reject_reason_detail="",
        step7_status_path=str(run_root / "cases" / "1001" / "step7_status.json"),
        audit_path=str(run_root / "cases" / "1001" / "step7_audit.json"),
        source_image_path=str(source_png),
    )

    result = materialize_streamed_case_visual_check(
        run_root=run_root,
        record=record,
        visual_check_dir=run_root / "visual_checks",
    )

    assert result["copied"] is True
    assert (run_root / "step4_review_flat" / "case__1001__final_review.png").is_file()
    assert (run_root / "visual_checks" / "final_flat" / "case__1001__accepted.png").is_file()
    assert (
        run_root / "visual_checks" / "final_by_state" / "accepted" / "case__1001__accepted.png"
    ).is_file()


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
    assert "guard_failed=0" in result.stdout
    assert "runtime_failed=0" in result.stdout
    assert "[PERF]" in result.stdout


def test_t04_internal_full_input_classifies_resource_guard_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_dir = tmp_path / "full_input_source" / "1001"
    _build_synthetic_case_package(case_dir)

    def raise_grid_guard(*args, **kwargs):
        raise ValueError(
            "step6_grid_too_large: case_id=1001, patch_size_m=2000.000, "
            "resolution_m=0.500, side_cells=4000, max_side_cells=2000"
        )

    monkeypatch.setattr(internal_full_input_runner, "run_single_case_direct", raise_grid_guard)

    run_root = internal_full_input_runner.run_t04_internal_full_input(
        nodes_path=case_dir / "nodes.gpkg",
        roads_path=case_dir / "roads.gpkg",
        drivezone_path=case_dir / "drivezone.gpkg",
        divstripzone_path=case_dir / "divstripzone.gpkg",
        rcsdroad_path=case_dir / "rcsdroad.gpkg",
        rcsdnode_path=case_dir / "rcsdnode.gpkg",
        out_root=tmp_path / "out_guard",
        run_id="t04_internal_resource_guard",
        workers=1,
        max_cases=1,
        resume=False,
        retry_failed=False,
        perf_audit=False,
    ).run_root

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    progress = json.loads((run_root / "t04_internal_full_input_progress.json").read_text(encoding="utf-8"))
    record = json.loads((run_root / "terminal_case_records" / "1001.json").read_text(encoding="utf-8"))

    assert summary["accepted_count"] == 0
    assert summary["rejected_count"] == 0
    assert summary["guard_failed_count"] == 1
    assert summary["resource_guard_failed_count"] == 1
    assert summary["input_guard_failed_count"] == 0
    assert summary["runtime_failed_count"] == 0
    assert progress["guard_failed_case_count"] == 1
    assert progress["runtime_failed_case_count"] == 0
    assert record["terminal_state"] == "guard_failed"
    assert record["guard_type"] == "resource_guard_failed"
    assert record["reject_reason"] == "step6_grid_too_large_resource_guard"


def test_t04_internal_full_input_classifies_rcsdnode_outside_drivezone_as_input_guard() -> None:
    failure = internal_full_input_runner._classify_guard_failure(
        Stage4RunError(REASON_RCS_OUTSIDE_DRIVEZONE, "RCSDNode features are outside DriveZone: 123")
    )

    assert failure is not None
    assert failure.guard_type == "input_guard_failed"
    assert failure.reason == "input_rcsdnode_outside_drivezone"
