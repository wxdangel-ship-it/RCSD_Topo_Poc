from __future__ import annotations

import json
from pathlib import Path

from tests.modules.t03_virtual_junction_anchor._case_helpers import write_case_package
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_batch_runner import run_t03_step3_legal_space_batch


def test_run_root_rerun_cleans_stale_outputs_before_write(tmp_path: Path) -> None:
    case_root = tmp_path / "case_root"
    out_root = tmp_path / "out_root"
    run_id = "rerun_case"
    write_case_package(case_root / "100001", "100001")

    run_root = run_t03_step3_legal_space_batch(case_root=case_root, out_root=out_root, run_id=run_id, workers=1)
    stale_case_dir = run_root / "cases" / "999999"
    stale_case_dir.mkdir(parents=True, exist_ok=True)
    (stale_case_dir / "stale.txt").write_text("stale", encoding="utf-8")
    flat_dir = run_root / "step3_review_flat"
    (flat_dir / "999999__review.png").write_text("stale", encoding="utf-8")

    rerun_root = run_t03_step3_legal_space_batch(case_root=case_root, out_root=out_root, run_id=run_id, workers=1)
    summary_doc = json.loads((rerun_root / "summary.json").read_text(encoding="utf-8"))

    assert rerun_root == run_root
    assert summary_doc["rerun_cleaned_before_write"] is True
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert not (rerun_root / "cases" / "999999").exists()
    assert not (rerun_root / "step3_review_flat" / "999999__review.png").exists()
