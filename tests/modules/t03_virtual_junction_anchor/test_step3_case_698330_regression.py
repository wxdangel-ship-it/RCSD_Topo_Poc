from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_698330_node_fallback_no_longer_forces_review() -> None:
    _context, template_result, case_result = load_real_case_bundle("698330")
    audit_doc = case_result.audit_doc

    assert template_result.template_class == "single_sided_t_mouth"
    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["rules"]["B"]["node_fallback_used"] is True
    assert audit_doc["review_signals"] == []
    assert audit_doc["rules"]["D"]["passed"] is True
    assert audit_doc["rules"]["E"]["passed"] is True
    assert audit_doc["cleanup_dependency"] is False
