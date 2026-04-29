from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import load_association_case_specs, load_association_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import build_association_case_result
from tests.modules.t03_virtual_junction_anchor._case_helpers import node_feature, road_feature
from tests.modules.t03_virtual_junction_anchor._association_helpers import (
    build_center_case_a,
    build_center_case_b,
    build_center_case_c,
    build_center_case_degree2_connector,
    build_center_case_degree2_turn_connector,
    build_center_case_multi_surface_filter,
    build_single_sided_parallel_support_case,
    write_association_case_package,
    write_step3_prerequisite,
)


def _run_case(case_root: Path, step3_root: Path, case_id: str):
    specs, _ = load_association_case_specs(case_root=case_root, case_ids=[case_id], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    return build_association_case_result(context)


def _road_with_formway(feature: dict, value: int, *, field_name: str = "formway") -> dict:
    feature["properties"][field_name] = value
    return feature


def test_association_classifies_case_a(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")

    result = _run_case(case_root, step3_root, "100001")

    assert result.association_class == "A"
    assert result.association_state == "established"
    assert result.key_metrics["required_rcsdnode_count"] == 1
    assert result.key_metrics["required_rcsdroad_count"] >= 1


def test_association_classifies_case_b_and_hook_zone_not_full_road(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_b(case_root, step3_root, case_id="100002")

    result = _run_case(case_root, step3_root, "100002")

    assert result.association_class == "B"
    assert result.association_state == "review"
    assert result.extra_status_fields["related_rcsdroad_ids"] == []
    assert result.output_geometries.support_rcsdroad_geometry is not None
    assert result.output_geometries.related_rcsdroad_geometry is None
    assert result.output_geometries.support_rcsdroad_geometry.length < 120.0
    assert result.output_geometries.required_hook_zone_geometry is not None


def test_association_classifies_case_c(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_c(case_root, step3_root, case_id="100003")

    result = _run_case(case_root, step3_root, "100003")

    assert result.association_class == "C"
    assert result.association_state == "established"
    assert result.key_metrics["required_rcsdnode_count"] == 0
    assert result.key_metrics["support_rcsdroad_count"] == 0


def test_association_degree2_connector_node_is_not_promoted_into_semantic_core(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector(case_root, step3_root, case_id="100004")

    result = _run_case(case_root, step3_root, "100004")

    assert result.association_class == "A"
    assert "rc_core" in result.extra_status_fields["required_rcsdnode_ids"]
    assert "rc_connector" not in result.extra_status_fields["required_rcsdnode_ids"]
    assert "rc_connector" not in result.extra_status_fields["support_rcsdnode_ids"]
    assert result.extra_status_fields["nonsemantic_connector_rcsdnode_ids"] == ["rc_connector"]
    assert result.extra_status_fields["true_foreign_rcsdnode_ids"] == []
    assert result.extra_status_fields["ignored_outside_current_swsd_surface_rcsdnode_ids"] == ["rc_far"]
    assert result.audit_doc["step4"]["degree2_connector_candidate_rcsdnode_ids"] == ["rc_connector"]


def test_association_degree2_connector_chain_expands_required_rcsdroad_even_without_angle_filter(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_turn_connector(case_root, step3_root, case_id="100008")

    result = _run_case(case_root, step3_root, "100008")

    assert result.association_class == "A"
    assert result.extra_status_fields["required_rcsdroad_ids"] == [
        "rc_r_connector",
        "rc_r_down",
        "rc_r_left",
        "rc_r_turn",
    ]
    assert result.extra_status_fields["excluded_rcsdroad_ids"] == []
    assert result.audit_doc["step4"]["degree2_merged_rcsdroad_groups"] == {
        "rc_r_connector": ["rc_r_connector", "rc_r_turn"]
    }


def test_association_same_path_degree2_chain_is_not_filtered_as_u_turn(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    case_id = "100010"
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (30.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_left", -10.0, 0.0, mainnodeid="rc_left", kind_2=4),
        node_feature("rc_mid", 0.0, 0.0, mainnodeid="rc_mid", kind_2=4),
        node_feature("rc_right", 10.0, 0.0, mainnodeid="rc_right", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_left_tail", "rc_left", "rc_left_far", [(-10.0, 0.0), (-20.0, 0.0)]),
        road_feature("rc_left_side", "rc_left", "rc_left_side_end", [(-10.0, 0.0), (-10.0, 8.0)]),
        road_feature("rc_chain_left", "rc_left", "rc_mid", [(-10.0, 0.0), (0.0, 0.0)]),
        road_feature("rc_chain_right", "rc_mid", "rc_right", [(0.0, 0.0), (10.0, 0.0)]),
        road_feature("rc_right_tail", "rc_right", "rc_right_far", [(10.0, 0.0), (20.0, 0.0)]),
        road_feature("rc_right_side", "rc_right", "rc_right_side_end", [(10.0, 0.0), (10.0, 8.0)]),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-22.0, -8.0, 22.0, 10.0),
    )

    result = _run_case(case_root, step3_root, case_id)

    assert result.association_class == "A"
    assert result.extra_status_fields["u_turn_candidate_rcsdroad_ids"] == []
    assert result.extra_status_fields["u_turn_rcsdroad_ids"] == []
    assert result.extra_status_fields["u_turn_rejected_by_same_path_chain_ids"] == []
    assert result.extra_status_fields["same_path_chain_protected_rcsdroad_ids"] == ["rc_chain_left", "rc_chain_right"]
    assert result.extra_status_fields["same_path_chain_terminal_rcsdnode_ids"] == ["rc_left", "rc_right"]
    assert "rc_chain_left" in result.extra_status_fields["required_rcsdroad_ids"]
    assert "rc_chain_right" in result.extra_status_fields["required_rcsdroad_ids"]


def test_association_true_u_turn_road_is_filtered_from_current_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    case_id = "100011"
    roads = [
        road_feature("road_h", case_id, "n2", [(-20.0, 0.0), (20.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -20.0), (0.0, 20.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_u_a", 0.0, -8.0, mainnodeid="rc_u_a", kind_2=4),
        node_feature("rc_u_b", 0.0, 8.0, mainnodeid="rc_u_b", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_a_in", "rc_a_west", "rc_u_a", [(-20.0, -8.0), (0.0, -8.0)], direction=2),
        road_feature("rc_a_out", "rc_u_a", "rc_a_east", [(0.0, -8.0), (20.0, -8.0)], direction=2),
        road_feature("rc_u_turn", "rc_u_a", "rc_u_b", [(0.0, -8.0), (0.0, 8.0)]),
        road_feature("rc_b_in", "rc_b_east", "rc_u_b", [(20.0, 8.0), (0.0, 8.0)], direction=2),
        road_feature("rc_b_out", "rc_u_b", "rc_b_west", [(0.0, 8.0), (-20.0, 8.0)], direction=2),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-8.0, -24.0, 8.0, 24.0),
    )

    result = _run_case(case_root, step3_root, case_id)

    assert result.extra_status_fields["u_turn_candidate_rcsdroad_ids"] == ["rc_u_turn"]
    assert result.extra_status_fields["u_turn_rcsdroad_ids"] == ["rc_u_turn"]
    assert result.extra_status_fields["u_turn_suspect_rcsdroad_ids"] == []
    assert result.extra_status_fields["u_turn_rejected_by_same_path_chain_ids"] == []
    assert "rc_u_turn" not in result.extra_status_fields["required_rcsdroad_ids"]
    assert "rc_u_turn" not in result.extra_status_fields["support_rcsdroad_ids"]
    assert "rc_u_turn" not in result.extra_status_fields["excluded_rcsdroad_ids"]
    assert (
        result.audit_doc["step4"]["u_turn_candidate_rcsdroad_audit"]["rc_u_turn"]["reason"]
        == "effective_degree3_parallel_trunks_opposite_flow"
    )


def test_association_geometry_u_turn_without_trusted_direction_is_audit_only(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    case_id = "100013"
    roads = [
        road_feature("road_h", case_id, "n2", [(-20.0, 0.0), (20.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -20.0), (0.0, 20.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_u_a", 0.0, -8.0, mainnodeid="rc_u_a", kind_2=4),
        node_feature("rc_u_b", 0.0, 8.0, mainnodeid="rc_u_b", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_a_in", "rc_a_west", "rc_u_a", [(-20.0, -8.0), (0.0, -8.0)], direction=0),
        road_feature("rc_a_out", "rc_u_a", "rc_a_east", [(0.0, -8.0), (20.0, -8.0)], direction=0),
        road_feature("rc_u_turn", "rc_u_a", "rc_u_b", [(0.0, -8.0), (0.0, 8.0)]),
        road_feature("rc_b_in", "rc_b_east", "rc_u_b", [(20.0, 8.0), (0.0, 8.0)], direction=0),
        road_feature("rc_b_out", "rc_u_b", "rc_b_west", [(0.0, 8.0), (-20.0, 8.0)], direction=0),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-8.0, -24.0, 8.0, 24.0),
    )

    result = _run_case(case_root, step3_root, case_id)

    assert result.extra_status_fields["u_turn_candidate_rcsdroad_ids"] == ["rc_u_turn"]
    assert result.extra_status_fields["u_turn_rcsdroad_ids"] == []
    assert result.extra_status_fields["u_turn_suspect_rcsdroad_ids"] == ["rc_u_turn"]
    assert "rc_u_turn" in result.extra_status_fields["required_rcsdroad_ids"]
    assert (
        result.audit_doc["step4"]["u_turn_suspect_rcsdroad_audit"]["rc_u_turn"]["reason"]
        == "direction_unavailable_or_untrusted"
    )


def test_association_formway_bit_is_authoritative_for_u_turn_filter(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    case_id = "100012"
    roads = [
        road_feature("road_h", case_id, "n2", [(-20.0, 0.0), (20.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -20.0), (0.0, 20.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_u_a", 0.0, -8.0, mainnodeid="rc_u_a", kind_2=4),
        node_feature("rc_u_b", 0.0, 8.0, mainnodeid="rc_u_b", kind_2=4),
    ]
    rcsd_roads = [
        _road_with_formway(
            road_feature("rc_lower_path", "rc_lower_far", "rc_u_a", [(0.0, -22.0), (0.0, -8.0)]),
            0,
            field_name="FORMWAY",
        ),
        _road_with_formway(
            road_feature("rc_geometry_like_u_turn", "rc_u_a", "rc_u_b", [(0.0, -8.0), (0.0, 8.0)]),
            0,
            field_name="FORMWAY",
        ),
        _road_with_formway(
            road_feature("rc_upper_path", "rc_u_b", "rc_upper_far", [(0.0, 8.0), (0.0, 22.0)]),
            0,
            field_name="FORMWAY",
        ),
        _road_with_formway(
            road_feature("rc_formway_u_turn", "rc_field_a", "rc_field_b", [(-6.0, -6.0), (-4.0, -5.0)]),
            1024,
            field_name="FORMWAY",
        ),
    ]
    write_association_case_package(case_root / case_id, case_id, roads=roads, rcsd_nodes=rcsd_nodes, rcsd_roads=rcsd_roads)
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-8.0, -24.0, 8.0, 24.0),
    )

    result = _run_case(case_root, step3_root, case_id)

    assert result.extra_status_fields["u_turn_detection_mode"] == "formway_bit"
    assert result.extra_status_fields["u_turn_formway_bit"] == 1024
    assert result.extra_status_fields["u_turn_candidate_rcsdroad_ids"] == ["rc_formway_u_turn"]
    assert result.extra_status_fields["u_turn_rcsdroad_ids"] == ["rc_formway_u_turn"]
    assert "rc_geometry_like_u_turn" not in result.extra_status_fields["u_turn_candidate_rcsdroad_ids"]
    assert "rc_formway_u_turn" not in result.extra_status_fields["required_rcsdroad_ids"]
    assert result.audit_doc["step4"]["u_turn_candidate_rcsdroad_audit"]["rc_formway_u_turn"]["formway"] == 1024


def test_association_ignores_rcsd_outside_current_swsd_surface(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_multi_surface_filter(case_root, step3_root, case_id="100005")

    result = _run_case(case_root, step3_root, "100005")

    assert result.association_class == "A"
    assert "rc_r_far" not in result.extra_status_fields["excluded_rcsdroad_ids"]
    assert "rc_n_far" not in result.extra_status_fields["excluded_rcsdnode_ids"]
    assert result.extra_status_fields["ignored_outside_current_swsd_surface_rcsdroad_ids"] == ["rc_r_far"]
    assert result.extra_status_fields["ignored_outside_current_swsd_surface_rcsdnode_ids"] == ["rc_n_far"]
    assert result.audit_doc["step4"]["active_rcsdroad_ids"] == ["rc_r_1", "rc_r_2", "rc_r_3"]


def test_association_single_sided_support_prunes_parallel_duplicate_by_vertical_exit_side(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_single_sided_parallel_support_case(case_root, step3_root, case_id="100006")

    result = _run_case(case_root, step3_root, "100006")

    assert result.association_class == "A"
    assert result.extra_status_fields["support_rcsdroad_ids"] == ["rc_support_exit_side"]
    assert result.extra_status_fields["related_rcsdroad_ids"] == ["rc_required"]
    assert "rc_support_exit_side" not in result.extra_status_fields["related_rcsdroad_ids"]
    assert "rc_support_exit_side" not in result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert result.extra_status_fields["parallel_support_duplicate_dropped_rcsdroad_ids"] == ["rc_support_parallel"]
    assert result.audit_doc["step4"]["parallel_support_duplicate_dropped_rcsdroad_ids"] == ["rc_support_parallel"]
