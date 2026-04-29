from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import association_render as association_render_module
from tests.modules.t03_virtual_junction_anchor._association_helpers import (
    build_center_case_degree2_connector,
    build_center_case_degree2_connector_with_true_foreign_node,
    build_center_case_b,
    build_center_case_foreign_selected_surface_overlap,
    build_center_case_multi_surface_filter,
    write_association_case_package,
    write_step3_prerequisite,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import load_association_case_specs, load_association_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import build_association_case_result
from tests.modules.t03_virtual_junction_anchor._case_helpers import node_feature, road_feature


def _build_related_outside_scope_case(case_root: Path, step3_root: Path, case_id: str) -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-20.0, 0.0), (25.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -20.0), (0.0, 20.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_core", 0.0, 0.0, mainnodeid="rc_core", kind_2=4),
        node_feature("rc_connector", 15.0, 0.0, mainnodeid="rc_connector", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_local_same_path", "rc_core", "rc_connector", [(0.0, 0.0), (15.0, 0.0)]),
        road_feature("rc_outside_same_path", "rc_connector", "rc_far", [(15.0, 0.0), (30.0, 0.0)]),
        road_feature("rc_unrelated_foreign", "rc_foreign_a", "rc_foreign_b", [(0.0, 16.0), (30.0, 16.0)]),
    ]
    write_association_case_package(
        case_root / case_id,
        case_id,
        roads=roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        drivezone_geometry=box(-25.0, -25.0, 35.0, 25.0),
    )
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-8.0, -8.0, 8.0, 8.0),
    )


def _build_related_multinode_group_case(case_root: Path, step3_root: Path, case_id: str) -> None:
    roads = [
        road_feature("road_h", case_id, "n2", [(-30.0, 0.0), (120.0, 0.0)]),
        road_feature("road_v", "n3", case_id, [(0.0, -30.0), (0.0, 30.0)]),
    ]
    rcsd_nodes = [
        node_feature("rc_group_a", 80.0, 0.0, mainnodeid="rc_group", kind_2=4),
        node_feature("rc_group_b", 80.0, 1.0, mainnodeid="rc_group", kind_2=4),
        node_feature("rc_group_c", 85.0, 1.0, mainnodeid="rc_group", kind_2=4),
    ]
    rcsd_roads = [
        road_feature("rc_local_h", "rc_left", "rc_group_a", [(0.0, 0.0), (80.0, 0.0)]),
        road_feature("rc_local_v", "rc_group_b", "rc_up", [(0.0, 1.0), (80.0, 1.0)]),
        road_feature("rc_group_side", "rc_group_c", "rc_far", [(85.0, 1.0), (105.0, 0.0)]),
        road_feature("rc_unrelated_foreign", "rc_foreign_a", "rc_foreign_b", [(0.0, 16.0), (30.0, 16.0)]),
    ]
    write_association_case_package(
        case_root / case_id,
        case_id,
        roads=roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        drivezone_geometry=box(-35.0, -25.0, 130.0, 25.0),
    )
    write_step3_prerequisite(
        step3_root,
        case_id,
        template_class="center_junction",
        selected_road_ids=["road_h", "road_v"],
        allowed_geometry=box(-8.0, -8.0, 8.0, 8.0),
    )


def test_step5_true_foreign_nodes_stay_audit_only_without_polygon_context(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector_with_true_foreign_node(case_root, step3_root, case_id="100001")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100001"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert "rc_true_foreign" in result.extra_status_fields["excluded_rcsdnode_ids"]
    assert "rc_true_foreign" in result.extra_status_fields["true_foreign_rcsdnode_ids"]
    assert result.output_geometries.foreign_rcsd_context_geometry is None
    assert result.audit_doc["step5"]["hard_negative_mask_sources"] == ["excluded_rcsdroad_geometry"]
    assert result.audit_doc["step5"]["audit_only_node_sources"] == [
        "excluded_rcsdnode_ids",
        "true_foreign_rcsdnode_ids",
    ]


def test_step5_connector_nodes_are_audited_separately_from_true_foreign_nodes(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector_with_true_foreign_node(case_root, step3_root, case_id="100004")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100004"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.extra_status_fields["nonsemantic_connector_rcsdnode_ids"] == ["rc_connector"]
    assert result.extra_status_fields["true_foreign_rcsdnode_ids"] == ["rc_true_foreign"]
    assert result.audit_doc["step5"]["connector_incident_retained_rcsdroad_ids"] == {
        "rc_connector": ["rc_r_connector", "rc_r_tail"]
    }


def test_step5_remote_outside_scope_road_is_hard_foreign_mask(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    _build_related_outside_scope_case(case_root, step3_root, case_id="100012")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100012"], exclude_case_ids=[])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []
    assert "rc_outside_same_path" not in result.extra_status_fields["related_rcsdroad_ids"]
    assert result.extra_status_fields["foreign_mask_source_rcsdroad_ids"] == [
        "rc_outside_same_path",
        "rc_unrelated_foreign",
    ]
    assert result.extra_status_fields["excluded_rcsdroad_ids"] == [
        "rc_outside_same_path",
        "rc_unrelated_foreign",
    ]
    assert result.output_geometries.excluded_rcsdroad_geometry is not None
    outside_road = next(road for road in context.step1_context.rcsd_roads if road.road_id == "rc_outside_same_path")
    assert not result.output_geometries.excluded_rcsdroad_geometry.intersection(outside_road.geometry).is_empty


def test_step5_support_only_multinode_group_does_not_promote_support_into_related(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    _build_related_multinode_group_case(case_root, step3_root, case_id="100014")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100014"], exclude_case_ids=[])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.association_class == "B"
    assert result.extra_status_fields["required_rcsdroad_ids"] == []
    assert result.extra_status_fields["support_rcsdroad_ids"] == [
        "rc_local_h",
        "rc_local_v",
    ]
    assert result.extra_status_fields["related_rcsdnode_ids"] == []
    assert result.extra_status_fields["related_group_rcsdroad_ids"] == []
    assert result.extra_status_fields["related_rcsdroad_ids"] == []
    assert "rc_group_side" not in result.extra_status_fields["related_rcsdroad_ids"]
    assert "rc_group_side" in result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert "rc_unrelated_foreign" in result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert result.audit_doc["step4"]["related_rcsdnode_group_audit"] == {}


def test_association_render_draws_related_rcsdroad_as_deep_red(tmp_path: Path, monkeypatch) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector(case_root, step3_root, case_id="100013")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100013"], exclude_case_ids=[])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)
    required_edge_calls = []

    def _capture_draw_line(draw, geometry, bounds, *, fill, width):
        if fill == association_render_module.REQUIRED_EDGE:
            required_edge_calls.append(geometry)

    monkeypatch.setattr(association_render_module, "_draw_line", _capture_draw_line)

    association_render_module.render_association_review_png(
        out_path=tmp_path / "association_review.png",
        context=context,
        case_result=result,
    )

    related_geometry = result.output_geometries.related_rcsdroad_geometry
    assert related_geometry is not None
    assert any(geometry is not None and geometry.equals(related_geometry) for geometry in required_edge_calls)


def test_association_render_keeps_support_only_road_out_of_deep_red(tmp_path: Path, monkeypatch) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_b(case_root, step3_root, case_id="100015")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100015"], exclude_case_ids=[])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)
    required_edge_calls = []
    support_edge_calls = []

    def _capture_draw_line(draw, geometry, bounds, *, fill, width):
        if fill == association_render_module.REQUIRED_EDGE:
            required_edge_calls.append(geometry)
        if fill == association_render_module.SUPPORT_EDGE:
            support_edge_calls.append(geometry)

    monkeypatch.setattr(association_render_module, "_draw_line", _capture_draw_line)

    association_render_module.render_association_review_png(
        out_path=tmp_path / "association_review.png",
        context=context,
        case_result=result,
    )

    support_geometry = result.output_geometries.support_rcsdroad_geometry
    assert support_geometry is not None
    assert any(geometry is not None and geometry.equals(support_geometry) for geometry in support_edge_calls)
    assert not any(geometry is not None and geometry.equals(support_geometry) for geometry in required_edge_calls)


def test_step5_no_longer_builds_hard_foreign_swsd_context(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_multi_surface_filter(case_root, step3_root, case_id="100005")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100005"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.output_geometries.foreign_swsd_context_geometry is None
    assert result.audit_doc["step5"]["foreign_swsd_road_ids"] == []
    assert result.audit_doc["step5"]["foreign_swsd_group_ids"] == []
    assert result.audit_doc["step5"]["foreign_mask_normalization_mode"] == "road_like_1m_mask_in_step6"


def test_step5_selected_surface_overlap_case_no_longer_uses_selected_surface_protection_patch(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_foreign_selected_surface_overlap(case_root, step3_root, case_id="100007")

    specs, _ = load_association_case_specs(case_root=case_root, case_ids=["100007"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    result = build_association_case_result(context)

    assert result.output_geometries.foreign_swsd_context_geometry is None
    assert result.audit_doc["step5"]["selected_surface_foreign_protection_applied"] is False
    assert result.audit_doc["step5"]["selected_surface_protection_buffer_m"] == 0.0
    assert result.audit_doc["step5"]["foreign_swsd_context_area_before_selected_surface_protection_m2"] == 0.0
    assert result.audit_doc["step5"]["foreign_swsd_context_area_after_selected_surface_protection_m2"] == 0.0
