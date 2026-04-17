from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_single_sided_two_node_shared_two_in_two_out_node_is_treated_as_through_node() -> None:
    _context, template_result, case_result = load_real_case_bundle("851884")
    audit_doc = case_result.audit_doc

    assert template_result.template_class == "single_sided_t_mouth"
    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["review_signals"] == []
    assert audit_doc["shared_two_in_two_out_node_detected"] is True
    assert audit_doc["shared_two_in_two_out_node_id"] == "851885"
    assert audit_doc["shared_two_in_two_out_as_through_node"] is True
    assert audit_doc["frontier_interruption_skipped_by_two_in_two_out"] is True
    assert {"58285198", "506188765", "87963411", "1103051"}.issubset(set(audit_doc["selected_road_ids"]))
    assert all(item["group_id"] != "851885" for item in audit_doc["adjacent_junction_cuts"])
    assert all(item["road_id"] not in {"87963411", "1103051"} for item in audit_doc["adjacent_junction_cuts"])
