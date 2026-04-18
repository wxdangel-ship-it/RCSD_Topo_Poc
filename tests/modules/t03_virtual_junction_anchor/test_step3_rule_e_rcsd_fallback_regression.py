from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_885744_disables_rcsd_fallback_when_swsd_opposite_exists() -> None:
    _context, _template_result, case_result = load_real_case_bundle("885744")
    audit_doc = case_result.audit_doc

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["opposite_road_ids"] == ["608416634", "621962864"]
    assert "5396102501303369" not in audit_doc["opposite_rcsdroad_ids"]
    assert "5396182697052296" not in audit_doc["opposite_rcsdroad_ids"]
    assert audit_doc["rcsd_opposite_fallback_enabled"] is False
    assert audit_doc["rcsd_opposite_fallback_reason"] == "disabled_swsd_opposite_present"


def test_case_520394575_disables_rcsd_fallback_when_swsd_opposite_exists() -> None:
    _context, _template_result, case_result = load_real_case_bundle("520394575")
    audit_doc = case_result.audit_doc

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["opposite_road_ids"] == ["15647534", "512479415", "527279354"]
    assert "5395681561940686" not in audit_doc["opposite_rcsdroad_ids"]
    assert audit_doc["rcsd_opposite_fallback_enabled"] is False
    assert audit_doc["rcsd_opposite_fallback_reason"] == "disabled_swsd_opposite_present"
