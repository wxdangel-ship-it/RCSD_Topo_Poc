from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_692723_keeps_related_roads_out_of_opposite_and_foreign_masks() -> None:
    _context, _template_result, case_result = load_real_case_bundle("692723")
    audit_doc = case_result.audit_doc

    protected_road_ids = {"518881575", "528884634", "622002086", "527732066", "530508010"}
    cut_road_ids = {item["road_id"] for item in audit_doc["adjacent_junction_cuts"]}
    masked_road_ids = {
        item["road_id"]
        for item in audit_doc["foreign_object_masks"]
        if item.get("mode") in {"road_buffer", "opposite_road_buffer"}
    }

    assert cut_road_ids == set()
    assert protected_road_ids.isdisjoint(set(audit_doc["excluded_road_ids"]))
    assert protected_road_ids.isdisjoint(masked_road_ids)
    assert {"518881575", "528884634", "622002086"}.issubset(set(audit_doc["selected_road_ids"]))
    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert audit_doc["lane_guard_status"] == "proxy_only_not_modeled"
    assert "rule_d_50m_cap_used" not in audit_doc["review_signals"]
    assert any(item["cap_hit"] is True for item in audit_doc["growth_limits"])
