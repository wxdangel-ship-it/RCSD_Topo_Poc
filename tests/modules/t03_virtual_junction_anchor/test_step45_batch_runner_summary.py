from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_batch_runner import run_t03_step45_rcsd_association_batch
from tests.modules.t03_virtual_junction_anchor._step45_helpers import build_center_case_a, build_center_case_b, write_step3_prerequisite, write_step45_case_package


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
    assert preflight_doc["excluded_case_ids"] == ["922217"]
    assert preflight_doc["effective_case_ids"] == ["100001"]
    assert preflight_doc["missing_case_ids"] == []
    assert preflight_doc["failed_case_ids"] == []
    assert preflight_doc["formal_full_batch_case_ids"] == ["100001"]
    assert preflight_doc["selected_case_count"] == 1
    assert preflight_doc["step3_root"] == str(step3_root)


def test_step45_batch_runner_keeps_blocked_cases_out_of_failed_case_ids(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    out_root = tmp_path / "out"
    build_center_case_a(case_root, step3_root, case_id="100001")
    build_center_case_b(case_root, step3_root, case_id="100002")
    write_step3_prerequisite(
        step3_root,
        "100002",
        template_class="center_junction",
        selected_road_ids=[],
    )

    run_root = run_t03_step45_rcsd_association_batch(
        case_root=case_root,
        step3_root=step3_root,
        out_root=out_root,
        run_id="blocked_case",
        workers=1,
    )

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))
    blocked_status = json.loads((run_root / "cases" / "100002" / "step45_status.json").read_text(encoding="utf-8"))

    assert summary_doc["effective_case_ids"] == ["100001", "100002"]
    assert summary_doc["failed_case_ids"] == []
    assert summary_doc["missing_case_ids"] == []
    assert preflight_doc["failed_case_ids"] == []
    assert preflight_doc["missing_case_ids"] == []
    assert blocked_status["step45_state"] == "not_established"
    assert blocked_status["association_blocker"] == "step45_missing_selected_road_ids"


def test_step45_batch_runner_parallel_smoke_keeps_summary_and_index_stable(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    out_root = tmp_path / "out"
    build_center_case_a(case_root, step3_root, case_id="100001")
    build_center_case_b(case_root, step3_root, case_id="100002")
    write_step45_case_package(case_root / "100003", "100003")
    write_step3_prerequisite(
        step3_root,
        "100003",
        template_class="center_junction",
        selected_road_ids=[],
    )

    run_root = run_t03_step45_rcsd_association_batch(
        case_root=case_root,
        step3_root=step3_root,
        out_root=out_root,
        run_id="parallel_case",
        workers=2,
    )

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))
    index_rows = (run_root / "step45_review_index.csv").read_text(encoding="utf-8-sig").strip().splitlines()

    assert summary_doc["effective_case_ids"] == ["100001", "100002", "100003"]
    assert summary_doc["failed_case_ids"] == []
    assert preflight_doc["failed_case_ids"] == []
    assert preflight_doc["effective_case_ids"] == ["100001", "100002", "100003"]
    assert len(index_rows) == 4
