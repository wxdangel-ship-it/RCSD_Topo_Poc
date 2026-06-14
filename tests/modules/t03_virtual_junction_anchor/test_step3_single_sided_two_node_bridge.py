from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString
from shapely.geometry import box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import step3_engine
from tests.modules.t03_virtual_junction_anchor._case_helpers import (
    node_feature,
    road_feature,
    run_case_bundle,
    write_case_package,
)
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


def test_single_sided_target_near_drivezone_edge_keeps_inside_component(
    tmp_path: Path,
    monkeypatch,
) -> None:
    suite_root = tmp_path / "suite"
    case_id = "edge_touch"
    write_case_package(
        suite_root / case_id,
        case_id,
        kind_2=2048,
        drivezone_geometry=box(-5.0, 1.015, 15.0, 30.0),
        extra_nodes=[
            node_feature("edge_touch_b", 8.0, 0.0, mainnodeid=case_id, kind_2=0),
            node_feature("north_a", 0.0, 20.0, mainnodeid="north_a", kind_2=4),
            node_feature("north_b", 8.0, 20.0, mainnodeid="north_b", kind_2=4),
        ],
        roads=[
            road_feature("road_a", case_id, "north_a", [(0.0, 0.0), (0.0, 20.0)]),
            road_feature("road_b", "edge_touch_b", "north_b", [(8.0, 0.0), (8.0, 20.0)]),
        ],
    )

    monkeypatch.setattr(
        step3_engine,
        "_build_branch_frontier",
        lambda context, through_node_ids=None: ({"road_a", "road_b"}, set(), []),
    )
    monkeypatch.setattr(
        step3_engine,
        "_build_candidate_roads_for_single_sided",
        lambda context, protected_road_ids=None: ({"road_a", "road_b"}, set(), False, None, {}),
    )
    monkeypatch.setattr(step3_engine, "_build_single_sided_exclusions", lambda *args, **kwargs: (set(), set()))
    monkeypatch.setattr(step3_engine, "_build_adjacent_junction_masks", lambda *args, **kwargs: (None, [], [], set()))
    monkeypatch.setattr(step3_engine, "_build_foreign_mst_masks", lambda context: (None, []))
    monkeypatch.setattr(step3_engine, "_build_single_sided_blockers", lambda *args, **kwargs: (None, [], []))
    monkeypatch.setattr(step3_engine, "_build_foreign_object_masks", lambda *args, **kwargs: (None, [], False))

    def _fake_build_reachable_road_support(
        context,
        *,
        allowed_road_ids=None,
        blocker_geometry=None,
        force_bidirectional_road_ids=None,
        cap_m=50.0,
        case_cache=None,
    ):
        return box(-2.0, 1.015, 10.0, 5.0), [], {"road_a", "road_b"}, []

    monkeypatch.setattr(step3_engine, "_build_reachable_road_support", _fake_build_reachable_road_support)

    context, template_result, case_result = run_case_bundle(suite_root, case_id)

    assert template_result.template_class == "single_sided_t_mouth"
    assert case_result.step3_state == "established"
    assert case_result.allowed_space_geometry is not None
    assert case_result.allowed_space_geometry.difference(context.drivezone_geometry).area <= 1e-6
    assert case_result.audit_doc["target_edge_touch_enabled"] is True
    assert case_result.audit_doc["target_edge_touch_reason"] == "single_sided_target_near_drivezone_with_incident_support"
    assert case_result.audit_doc["target_edge_touch_tolerance_m"] == 1.5
    assert case_result.audit_doc["must_cover_result"]["missing_node_ids"] == []
