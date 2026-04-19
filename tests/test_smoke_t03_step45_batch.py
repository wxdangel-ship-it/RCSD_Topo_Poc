from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_batch_runner import (
    run_t03_step45_rcsd_association_batch,
)
from tests.modules.t03_virtual_junction_anchor._step45_helpers import build_center_case_a


@pytest.mark.smoke
def test_smoke_t03_step45_batch_writes_flat_review_outputs(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    out_root = tmp_path / "outputs"
    build_center_case_a(case_root, step3_root, case_id="100001")

    run_root = run_t03_step45_rcsd_association_batch(
        case_root=case_root,
        step3_root=step3_root,
        out_root=out_root,
        run_id="smoke_t03_step45",
        workers=1,
    )

    assert run_root == out_root / "smoke_t03_step45"
    assert (run_root / "preflight.json").is_file()
    assert (run_root / "summary.json").is_file()
    assert (run_root / "step45_review_index.csv").is_file()

    case_dir = run_root / "cases" / "100001"
    for rel_path in (
        "step45_required_rcsdnode.gpkg",
        "step45_required_rcsdroad.gpkg",
        "step45_support_rcsdnode.gpkg",
        "step45_support_rcsdroad.gpkg",
        "step45_excluded_rcsdnode.gpkg",
        "step45_excluded_rcsdroad.gpkg",
        "step45_required_hook_zone.gpkg",
        "step45_foreign_swsd_context.gpkg",
        "step45_foreign_rcsd_context.gpkg",
        "step45_status.json",
        "step45_audit.json",
        "step45_review.png",
    ):
        assert (case_dir / rel_path).is_file()

    flat_dir = run_root / "step45_review_flat"
    flat_entries = sorted(flat_dir.iterdir())
    assert flat_entries
    assert all(entry.is_file() for entry in flat_entries)
    assert not any(entry.is_dir() for entry in flat_entries)
    assert len([entry for entry in flat_entries if entry.suffix.lower() == ".png"]) == 1

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))
    assert summary_doc["total_case_count"] == 1
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert summary_doc["tri_state_sum"] == 1
    assert summary_doc["failed_case_ids"] == []
    assert preflight_doc["excluded_case_ids"] == []
    assert preflight_doc["missing_case_ids"] == []
    assert preflight_doc["failed_case_ids"] == []

    with (run_root / "step45_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "100001"
