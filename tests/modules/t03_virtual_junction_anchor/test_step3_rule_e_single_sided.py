from __future__ import annotations

from pathlib import Path

from tests.modules.t03_virtual_junction_anchor._case_helpers import (
    node_feature,
    road_feature,
    run_case_bundle,
    write_case_package,
)


def test_rule_e_single_sided_blocks_opposite_side_before_growth(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100001"
    write_case_package(
        suite_root / case_id,
        case_id,
        kind_2=2048,
        roads=[
            road_feature("road_east_1", case_id, "110001", [(0.0, 0.0), (25.0, 0.0)], direction=2),
            road_feature("road_east_2", "110001", "110002", [(25.0, 0.0), (55.0, 0.0)], direction=2),
            road_feature("road_west_opposite", "200001", "200002", [(-20.0, 0.0), (-50.0, 0.0)], direction=2),
        ],
        extra_nodes=[
            node_feature("110001", 25.0, 0.0, mainnodeid="110001"),
            node_feature("110002", 55.0, 0.0, mainnodeid="110002"),
            node_feature("200001", -25.0, 0.0, mainnodeid="200001"),
            node_feature("200002", -50.0, 0.0, mainnodeid="200002"),
        ],
        rcsd_roads=[
            road_feature("corridor_west", "r1", "r2", [(-10.0, 10.0), (-40.0, 10.0)], direction=2),
            road_feature("corridor_far_west", "r3", "r4", [(-10.0, 35.0), (-40.0, 35.0)], direction=2),
        ],
        rcsd_nodes=[
            node_feature("rcsd_opp", -20.0, 8.0, mainnodeid="rcsd_opp"),
        ],
    )

    _context, template_result, case_result = run_case_bundle(suite_root, case_id)
    audit_doc = case_result.audit_doc

    assert template_result.template_class == "single_sided_t_mouth"
    assert "corridor_west" in audit_doc["opposite_rcsdroad_ids"]
    assert "corridor_far_west" not in audit_doc["opposite_rcsdroad_ids"]
    assert "rcsd_opp" in audit_doc["opposite_semantic_node_ids"]
    assert "road_east_1" in audit_doc["selected_road_ids"]
    assert "road_west_opposite" not in audit_doc["selected_road_ids"]
    assert audit_doc["lane_guard_status"] == "proxy_only_not_modeled"
    assert audit_doc["corridor_guard_status"] == "hard_blocked_by_rcsdroad_mask"
    assert audit_doc["rules"]["E"]["template_only"] is True
    assert any(item["reason"] == "single_sided_opposite_corridor" for item in audit_doc["blocked_directions"])


def test_rule_e_keeps_junction_related_and_second_degree_roads_out_of_opposite(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100002"
    write_case_package(
        suite_root / case_id,
        case_id,
        kind_2=2048,
        roads=[
            road_feature("road_target", case_id, "200001", [(0.0, 0.0), (-25.0, 0.0)], direction=2),
            road_feature("road_second_degree", "200001", "200002", [(-25.0, 0.0), (-55.0, 0.0)], direction=2),
            road_feature("road_opposite_seed", case_id, "300001", [(0.0, 0.0), (20.0, 15.0)], direction=2),
            road_feature("road_opposite", "300001", "300002", [(20.0, 15.0), (55.0, 35.0)], direction=2),
        ],
        extra_nodes=[
            node_feature("200001", -25.0, 0.0, mainnodeid="200001"),
            node_feature("200002", -55.0, 0.0, mainnodeid="200002"),
            node_feature("300001", 25.0, 20.0, mainnodeid="300001"),
            node_feature("300002", 55.0, 35.0, mainnodeid="300002"),
        ],
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)
    audit_doc = case_result.audit_doc
    masked_road_ids = {
        item["road_id"]
        for item in audit_doc["foreign_object_masks"]
        if item.get("mode") in {"road_buffer", "opposite_road_buffer"}
    }

    assert "road_target" not in audit_doc["excluded_road_ids"]
    assert "road_second_degree" not in audit_doc["excluded_road_ids"]
    assert "road_target" not in masked_road_ids
    assert "road_second_degree" not in masked_road_ids


def test_rule_e_suppresses_rcsd_proxy_when_it_overlaps_current_branch(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100003"
    write_case_package(
        suite_root / case_id,
        case_id,
        kind_2=2048,
        roads=[
            road_feature("road_target_east", case_id, "110001", [(0.0, 0.0), (25.0, 0.0)], direction=2),
            road_feature("road_target_west", "120001", case_id, [(-25.0, 0.0), (0.0, 0.0)], direction=2),
            road_feature("road_opposite", "200001", "200002", [(-15.0, -10.0), (-45.0, -10.0)], direction=2),
        ],
        extra_nodes=[
            node_feature("110001", 25.0, 0.0, mainnodeid="110001"),
            node_feature("120001", -25.0, 0.0, mainnodeid="120001"),
            node_feature("200001", -15.0, -10.0, mainnodeid="200001"),
            node_feature("200002", -45.0, -10.0, mainnodeid="200002"),
        ],
        rcsd_roads=[
            road_feature("corridor_overlap_current", "r1", "r2", [(-20.0, 0.0), (20.0, 0.0)], direction=2),
            road_feature("corridor_true_opposite", "r3", "r4", [(-15.0, -10.0), (-45.0, -10.0)], direction=2),
        ],
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)
    audit_doc = case_result.audit_doc

    assert "corridor_overlap_current" not in audit_doc["opposite_rcsdroad_ids"]
    assert set(audit_doc["selected_road_ids"]) >= {"road_target_east", "road_target_west"}
