from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_709632_suppresses_rcsd_proxy_that_overlaps_current_branch() -> None:
    _context, _template_result, case_result = load_real_case_bundle("709632")
    audit_doc = case_result.audit_doc

    assert "5396159040979360" not in audit_doc["opposite_rcsdroad_ids"]
    assert set(audit_doc["selected_road_ids"]) == {"49232144", "624152536", "969176"}
    assert audit_doc["must_cover_result"]["missing_node_ids"] == []
    assert case_result.reason != "must_cover_failed"
