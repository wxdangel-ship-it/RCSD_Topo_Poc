from __future__ import annotations

import json
from pathlib import Path

from tests.modules.t03_virtual_junction_anchor._case_helpers import write_case_package
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.batch_runner import run_t03_step3_legal_space_batch


def test_batch_runner_summary_includes_acceptance_fields(tmp_path: Path) -> None:
    case_root = tmp_path / "case_root"
    out_root = tmp_path / "out_root"
    write_case_package(case_root / "100001", "100001")

    run_root = run_t03_step3_legal_space_batch(case_root=case_root, out_root=out_root, run_id="summary_case", workers=1)
    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))

    assert summary_doc["expected_case_count"] == 1
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert summary_doc["tri_state_sum"] == 1
    assert summary_doc["tri_state_sum_matches_total"] is True
    assert summary_doc["missing_case_ids"] == []
    assert summary_doc["failed_case_ids"] == []
    assert summary_doc["rerun_cleaned_before_write"] is False
