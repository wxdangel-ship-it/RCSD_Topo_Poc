from __future__ import annotations

import csv
import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import load_association_case_specs, load_association_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import build_association_case_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_outputs import CASE_REQUIRED_OUTPUTS, write_case_outputs, write_review_index, write_summary
from tests.modules.t03_virtual_junction_anchor._association_helpers import build_center_case_a


def test_association_outputs_keeps_flat_dir_flat_and_summary_stable(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    run_root = tmp_path / "run"
    build_center_case_a(case_root, step3_root, case_id="100001")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100001"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    case_result = build_association_case_result(context)
    row = write_case_outputs(run_root=run_root, context=context, case_result=case_result)
    write_review_index(run_root, [row])
    write_summary(
        run_root,
        [row],
        expected_case_ids=["100001"],
        raw_case_count=1,
        default_formal_case_count=1,
        effective_case_ids=["100001"],
        failed_case_ids=[],
        rerun_cleaned_before_write=False,
    )

    case_dir = run_root / "cases" / "100001"
    for rel_path in CASE_REQUIRED_OUTPUTS:
        assert (case_dir / rel_path).is_file()

    flat_dir = run_root / "association_review_flat"
    flat_entries = list(flat_dir.iterdir())
    assert flat_entries == [flat_dir / "100001__established.png"]
    assert all(entry.is_file() for entry in flat_entries)
    assert not any(entry.is_dir() for entry in flat_entries)

    with (run_root / "association_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "100001"
    assert rows[0]["image_name"] == "100001__established.png"

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary_doc["raw_case_count"] == 1
    assert summary_doc["default_formal_case_count"] == 1
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert summary_doc["association_established_count"] == 1
    assert summary_doc["association_review_count"] == 0
    assert summary_doc["association_not_established_count"] == 0
    assert summary_doc["tri_state_sum"] == 1
