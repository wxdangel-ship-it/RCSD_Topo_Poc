from __future__ import annotations

import csv
from pathlib import Path

from rcsd_topo_poc.modules.t10_e2e_orchestration.case_runner import _compare_feedback_iteration_outputs


def test_feedback_regression_guard_treats_group_plan_members_as_covered(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    _write_replacement_plan(
        baseline,
        [
            {
                "swsd_segment_id": "s2",
                "execution_scope": "standard_segment",
                "group_segment_ids": "['s2']",
            }
        ],
    )
    _write_replacement_plan(
        final,
        [
            {
                "swsd_segment_id": "group_owner",
                "execution_scope": "path_corridor_group",
                "group_segment_ids": "['group_owner', 's1', 's2']",
            }
        ],
    )

    comparison = _compare_feedback_iteration_outputs(baseline_run_root=baseline, final_run_root=final)

    assert comparison["removed_replacement_plan_segment_ids"] == []
    assert comparison["added_replacement_plan_segment_ids"] == ["group_owner", "s1"]


def _write_replacement_plan(run_root: Path, rows: list[dict[str, str]]) -> None:
    path = run_root / "cases" / "case1" / "t06_step12" / "t06" / "step2_extract_rcsd_segments" / "t06_segment_replacement_plan.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["swsd_segment_id", "execution_scope", "group_segment_ids"])
        writer.writeheader()
        writer.writerows(rows)
