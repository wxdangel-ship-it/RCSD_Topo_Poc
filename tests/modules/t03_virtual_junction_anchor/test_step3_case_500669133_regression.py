from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_500669133_resolves_single_sided_direction_from_semantic_horizontal_pair() -> None:
    _context, _template_result, case_result = load_real_case_bundle("500669133")
    audit_doc = case_result.audit_doc

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["review_signals"] == []
    assert set(audit_doc["selected_road_ids"]) == {"514177622", "521947418", "611950483"}
    assert set(audit_doc["excluded_road_ids"]) == {"611117890"}
    assert audit_doc["single_sided_horizontal_pair_detected"] is True
    assert set(audit_doc["single_sided_horizontal_pair_road_ids"]) == {"514177622", "521947418"}
