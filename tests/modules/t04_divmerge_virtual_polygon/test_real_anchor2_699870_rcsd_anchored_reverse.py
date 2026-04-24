from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


@pytest.mark.smoke
def test_real_anchor2_699870_uses_rcsd_anchored_reverse_and_reaches_step7(tmp_path: Path) -> None:
    if not (REAL_ANCHOR_2_ROOT / "699870").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '699870'}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["699870"],
        out_root=tmp_path / "anchor2_699870_rcsd_anchored_reverse",
        run_id="anchor2_699870_rcsd_anchored_reverse",
    )

    reverse_doc = json.loads((run_root / "step4_rcsd_anchored_reverse.json").read_text(encoding="utf-8"))
    assert reverse_doc["triggered_count"] == 1
    record = reverse_doc["records"][0]
    assert record["case_id"] == "699870"
    assert record["post_state"] != "none"
    assert record["sample_count"] >= 3
    assert record["post_reverse_conflict_recheck"] == "passed"

    step4_doc = json.loads(
        (run_root / "cases" / "699870" / "step4_event_interpretation.json").read_text(encoding="utf-8")
    )
    unit_doc = step4_doc["event_units"][0]
    assert unit_doc["selected_evidence_state"] != "none"
    assert unit_doc["event_chosen_s_m"] is not None
    assert unit_doc["evidence_source"] == "rcsd_anchored_reverse"
    assert unit_doc["position_source"] == "rcsd_anchored_axis_projection"
    assert unit_doc["required_rcsd_node"] == "5396472305684570"
    assert unit_doc["required_rcsd_node_source"] == "aggregated_structural_required"

    step5_doc = json.loads((run_root / "cases" / "699870" / "step5_status.json").read_text(encoding="utf-8"))
    assert step5_doc["case_must_cover_domain"]["present"] is True

    step7_doc = json.loads((run_root / "cases" / "699870" / "step7_status.json").read_text(encoding="utf-8"))
    assert step7_doc["final_state"] in {"accepted", "rejected"}
    if step7_doc["final_state"] == "rejected":
        evidence_missing_reasons = {
            "no_selected_evidence_after_reselection",
            "missing_event_reference_point",
            "selected_branch_ids_empty",
        }
        assert not (set(step7_doc["reject_reasons"]) & evidence_missing_reasons)
