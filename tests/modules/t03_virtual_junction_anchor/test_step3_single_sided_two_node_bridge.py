from __future__ import annotations

from shapely.geometry import LineString

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_single_sided_two_node_target_keeps_bridge_in_allowed_space_main_path() -> None:
    context, template_result, case_result = load_real_case_bundle("851884")
    target_nodes = tuple(sorted(context.target_group.nodes, key=lambda item: item.node_id))
    bridge_midpoint = LineString([target_nodes[0].geometry, target_nodes[1].geometry]).interpolate(0.5, normalized=True)

    assert template_result.template_class == "single_sided_t_mouth"
    assert [node.node_id for node in target_nodes] == ["851884", "851886"]
    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert case_result.allowed_space_geometry is not None
    assert case_result.allowed_space_geometry.buffer(0.5).covers(bridge_midpoint)
    assert {"58285198", "506188765", "87963411", "1103051"}.issubset(set(case_result.audit_doc["selected_road_ids"]))
    assert case_result.audit_doc["two_node_t_bridge_applied"] is True
    assert case_result.audit_doc["two_node_t_bridge_blocked"] is False
    assert case_result.audit_doc["two_node_t_bridge_reason"] == "bridge_applied"
    assert "rule_d_50m_cap_used" not in case_result.audit_doc["review_signals"]
