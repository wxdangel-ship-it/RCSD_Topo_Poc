from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_batch_runner import (
    run_t03_step67_batch,
)
from tests.modules.t03_virtual_junction_anchor._step45_helpers import (
    build_center_case_a,
    build_center_case_b,
    write_step3_prerequisite,
    write_step45_case_package,
)


def test_step67_batch_runner_writes_gallery_summary_and_preflight(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    out_root = tmp_path / "out"
    build_center_case_a(case_root, step3_root, case_id="100001")
    build_center_case_b(case_root, step3_root, case_id="100002")
    build_center_case_a(case_root, step3_root, case_id="100003")
    write_step3_prerequisite(
        step3_root,
        "100003",
        template_class="center_junction",
        selected_road_ids=[],
    )
    write_step45_case_package(case_root / "922217", "922217")

    run_root = run_t03_step67_batch(
        case_root=case_root,
        step3_root=step3_root,
        out_root=out_root,
        run_id="step67_summary_case",
        workers=2,
    )

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    preflight_doc = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))

    assert summary_doc["raw_case_count"] == 4
    assert summary_doc["default_formal_case_count"] == 3
    assert summary_doc["effective_case_ids"] == ["100001", "100002", "100003"]
    assert summary_doc["step7_accepted_count"] == 2
    assert summary_doc["step7_rejected_count"] == 1
    assert summary_doc["visual_v1_count"] == 2
    assert summary_doc["visual_v2_count"] == 0
    assert summary_doc["failed_case_ids"] == []
    assert summary_doc["excluded_case_ids"] == ["922217"]
    assert preflight_doc["effective_case_ids"] == ["100001", "100002", "100003"]
    assert preflight_doc["excluded_case_ids"] == ["922217"]

    flat_dir = run_root / "step67_review_flat"
    accepted_dir = run_root / "step67_review_accepted"
    rejected_dir = run_root / "step67_review_rejected"
    v2_risk_dir = run_root / "step67_review_v2_risk"

    flat_entries = sorted(entry.name for entry in flat_dir.iterdir())
    assert flat_entries == [
        "0001_100001_accepted_center_junction.png",
        "0002_100002_accepted_center_junction.png",
        "0003_100003_rejected_step67_blocked_by_step45.png",
    ]
    assert sorted(entry.name for entry in accepted_dir.iterdir()) == [
        "0001_100001_accepted_center_junction.png",
        "0002_100002_accepted_center_junction.png",
    ]
    assert sorted(entry.name for entry in rejected_dir.iterdir()) == ["0003_100003_rejected_step67_blocked_by_step45.png"]
    assert list(v2_risk_dir.iterdir()) == []
