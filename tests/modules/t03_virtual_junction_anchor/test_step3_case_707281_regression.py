from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_707281_local_adjacent_cuts_no_longer_force_cleanup_dependency() -> None:
    _context, _template_result, case_result = load_real_case_bundle("707281")
    audit_doc = case_result.audit_doc

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert case_result.allowed_space_geometry is not None
    assert case_result.allowed_space_geometry.geom_type == "Polygon"
    assert "rule_d_50m_cap_used" not in audit_doc["review_signals"]
    assert any(item["cap_hit"] is True for item in audit_doc["growth_limits"])
    assert set(audit_doc["selected_road_ids"]) == {"611950335", "960090", "960091"}
    assert set(item["road_id"] for item in audit_doc["adjacent_junction_cuts"]) == {"611950335", "960090", "960091"}
    assert audit_doc["rules"]["F"]["passed"] is True
    assert audit_doc["rules"]["F"]["hard_path_passed"] is True
    assert audit_doc["rules"]["F"]["cleanup_preview_passed"] is True
