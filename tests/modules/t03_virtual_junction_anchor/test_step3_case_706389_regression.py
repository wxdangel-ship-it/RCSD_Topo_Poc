from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_706389_uses_near_corridor_rcsd_proxy_instead_of_full_opposite_side_block() -> None:
    _context, _template_result, case_result = load_real_case_bundle("706389")
    audit_doc = case_result.audit_doc

    assert case_result.step3_state == "review"
    assert case_result.reason == "single_sided_direction_ambiguous"
    assert set(audit_doc["selected_road_ids"]) == {"58163436", "617732646", "629431331"}
    assert set(audit_doc["opposite_road_ids"]) == {"529751673", "58163412"}
    assert set(audit_doc["opposite_rcsdroad_ids"]) == {"5395781419598853", "5395781419598870"}
    assert set(audit_doc["opposite_semantic_node_ids"]) == {"5395732498089990", "5395732498090166"}
    assert audit_doc["rules"]["E"]["blocked_count"] == 4
    assert audit_doc["rules"]["F"]["passed"] is True
