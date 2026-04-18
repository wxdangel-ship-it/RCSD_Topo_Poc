from __future__ import annotations

import json
from pathlib import Path

from tests.modules.t03_virtual_junction_anchor._case_helpers import write_case_package
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.batch_runner import run_t03_step3_legal_space_batch


def test_batch_runner_summary_includes_acceptance_fields(tmp_path: Path) -> None:
    case_root = tmp_path / "case_root"
    out_root = tmp_path / "out_root"
    write_case_package(case_root / "100001", "100001")
    write_case_package(case_root / "922217", "922217")

    run_root = run_t03_step3_legal_space_batch(case_root=case_root, out_root=out_root, run_id="summary_case", workers=1)
    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))

    assert summary_doc["expected_case_count"] == 1
    assert summary_doc["raw_case_count"] == 2
    assert summary_doc["raw_case_ids"] == ["100001", "922217"]
    assert summary_doc["default_formal_case_count"] == 1
    assert summary_doc["default_formal_case_ids"] == ["100001"]
    assert summary_doc["formal_full_batch_case_count"] == 1
    assert summary_doc["formal_full_batch_case_ids"] == ["100001"]
    assert summary_doc["effective_case_count"] == 1
    assert summary_doc["effective_case_ids"] == ["100001"]
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert summary_doc["tri_state_sum"] == 1
    assert summary_doc["tri_state_sum_matches_total"] is True
    assert summary_doc["default_full_batch_excluded_case_count"] == 3
    assert summary_doc["default_full_batch_excluded_case_ids"] == ["922217", "54265667", "502058682"]
    assert summary_doc["excluded_case_count"] == 1
    assert summary_doc["excluded_case_ids"] == ["922217"]
    assert summary_doc["applied_excluded_case_count"] == 1
    assert summary_doc["applied_excluded_case_ids"] == ["922217"]
    assert summary_doc["explicit_case_selection"] is False
    assert summary_doc["missing_case_ids"] == []
    assert summary_doc["failed_case_ids"] == []
    assert summary_doc["rerun_cleaned_before_write"] is False
    assert preflight_doc["raw_case_count"] == 2
    assert preflight_doc["raw_case_ids"] == ["100001", "922217"]
    assert preflight_doc["default_formal_case_count"] == 1
    assert preflight_doc["default_formal_case_ids"] == ["100001"]
    assert preflight_doc["formal_full_batch_case_count"] == 1
    assert preflight_doc["formal_full_batch_case_ids"] == ["100001"]
    assert preflight_doc["effective_case_count"] == 1
    assert preflight_doc["effective_case_ids"] == ["100001"]
    assert preflight_doc["default_full_batch_excluded_case_count"] == 3
    assert preflight_doc["applied_excluded_case_ids"] == ["922217"]
    assert preflight_doc["applied_excluded_case_count"] == 1
    assert preflight_doc["formal_acceptance_scope"] == "default_full_batch"


def test_batch_runner_explicit_case_id_keeps_hard_stop_case_available(tmp_path: Path) -> None:
    case_root = tmp_path / "case_root"
    out_root = tmp_path / "out_root"
    write_case_package(case_root / "922217", "922217")

    run_root = run_t03_step3_legal_space_batch(
        case_root=case_root,
        case_ids=["922217"],
        out_root=out_root,
        run_id="explicit_case",
        workers=1,
    )
    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))

    assert summary_doc["raw_case_count"] == 1
    assert summary_doc["default_formal_case_count"] == 0
    assert summary_doc["formal_full_batch_case_count"] == 0
    assert summary_doc["effective_case_ids"] == ["922217"]
    assert summary_doc["default_full_batch_excluded_case_count"] == 3
    assert summary_doc["default_full_batch_excluded_case_ids"] == ["922217", "54265667", "502058682"]
    assert summary_doc["excluded_case_ids"] == []
    assert summary_doc["applied_excluded_case_ids"] == []
    assert summary_doc["explicit_case_selection"] is True
    assert preflight_doc["explicit_case_selection"] is True
    assert preflight_doc["applied_excluded_case_ids"] == []
    assert preflight_doc["effective_case_ids"] == ["922217"]
    assert preflight_doc["formal_acceptance_scope"] == "explicit_case_selection"
