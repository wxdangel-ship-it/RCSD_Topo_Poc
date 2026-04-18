from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_batch_runner import run_t03_step45_rcsd_association_batch
from tests.modules.t03_virtual_junction_anchor._step45_helpers import build_center_case_a, write_step45_case_package, write_step3_prerequisite


def test_step45_batch_runner_summary_includes_acceptance_fields(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    out_root = tmp_path / "out"
    build_center_case_a(case_root, step3_root, case_id="100001")
    write_step45_case_package(case_root / "922217", "922217")

    run_root = run_t03_step45_rcsd_association_batch(
        case_root=case_root,
        step3_root=step3_root,
        out_root=out_root,
        run_id="summary_case",
        workers=1,
    )
    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))

    assert summary_doc["expected_case_count"] == 1
    assert summary_doc["raw_case_count"] == 2
    assert summary_doc["default_formal_case_count"] == 1
    assert summary_doc["effective_case_count"] == 1
    assert summary_doc["effective_case_ids"] == ["100001"]
    assert summary_doc["default_full_batch_excluded_case_ids"] == ["922217", "54265667", "502058682"]
    assert summary_doc["excluded_case_ids"] == ["922217"]
    assert summary_doc["failed_case_ids"] == []
    assert preflight_doc["default_formal_case_count"] == 1
    assert preflight_doc["effective_case_ids"] == ["100001"]
    assert preflight_doc["step3_root"] == str(step3_root)
