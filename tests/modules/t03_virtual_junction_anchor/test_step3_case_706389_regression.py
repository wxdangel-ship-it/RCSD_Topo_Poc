from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_706389_uses_near_corridor_rcsd_proxy_instead_of_full_opposite_side_block() -> None:
    _context, _template_result, case_result = load_real_case_bundle("706389")
    audit_doc = case_result.audit_doc

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["review_signals"] == []
    assert set(audit_doc["selected_road_ids"]) == {"58163436", "617732646", "629431331"}
    assert set(audit_doc["selected_road_ids"]).isdisjoint(set(audit_doc["opposite_road_ids"]))
    assert set(audit_doc["selected_road_ids"]).isdisjoint(
        {item["object_id"] for item in audit_doc["blocked_directions"] if item["layer"] == "road"}
    )
    assert audit_doc["single_sided_horizontal_pair_detected"] is True
    assert set(audit_doc["single_sided_horizontal_pair_road_ids"]) == {"58163436", "629431331"}
    assert audit_doc["rules"]["E"]["blocked_count"] >= 4
    assert audit_doc["rules"]["F"]["passed"] is True
