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
            road_feature("road_west_opposite", case_id, "200001", [(0.0, 0.0), (-25.0, 0.0)], direction=2),
        ],
        extra_nodes=[
            node_feature("110001", 25.0, 0.0, mainnodeid="110001"),
            node_feature("110002", 55.0, 0.0, mainnodeid="110002"),
            node_feature("200001", -25.0, 0.0, mainnodeid="200001"),
        ],
        rcsd_roads=[
            road_feature("corridor_west", "r1", "r2", [(-10.0, 10.0), (-40.0, 10.0)], direction=2),
        ],
        rcsd_nodes=[
            node_feature("rcsd_opp", -20.0, 8.0, mainnodeid="rcsd_opp"),
        ],
    )

    _context, template_result, case_result = run_case_bundle(suite_root, case_id)
    audit_doc = case_result.audit_doc

    assert template_result.template_class == "single_sided_t_mouth"
    assert "road_west_opposite" in audit_doc["opposite_road_ids"]
    assert "corridor_west" in audit_doc["opposite_rcsdroad_ids"]
    assert "rcsd_opp" in audit_doc["opposite_semantic_node_ids"]
    assert "road_west_opposite" not in audit_doc["selected_road_ids"]
    assert audit_doc["lane_guard_status"] == "proxy_only_not_modeled"
    assert audit_doc["corridor_guard_status"] == "hard_blocked_by_rcsdroad_mask"
    assert any(item["reason"] == "single_sided_opposite_road" for item in audit_doc["blocked_directions"])
