from __future__ import annotations

from pathlib import Path

from tests.modules.t03_virtual_junction_anchor._step45_helpers import (
    build_center_case_degree2_connector,
    build_center_case_foreign_selected_surface_overlap,
    build_center_case_multi_surface_filter,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import load_step45_case_specs, load_step45_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import build_step45_case_result


def test_step45_true_foreign_nodes_stay_audit_only_without_polygon_context(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector(case_root, step3_root, case_id="100001")

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100001"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert "rc_far" in result.extra_status_fields["excluded_rcsdnode_ids"]
    assert "rc_far" in result.extra_status_fields["true_foreign_rcsdnode_ids"]
    assert result.output_geometries.foreign_rcsd_context_geometry is None
    assert result.audit_doc["step5"]["hard_negative_mask_sources"] == ["excluded_rcsdroad_geometry"]
    assert result.audit_doc["step5"]["audit_only_node_sources"] == [
        "excluded_rcsdnode_ids",
        "true_foreign_rcsdnode_ids",
    ]


def test_step45_connector_nodes_are_audited_separately_from_true_foreign_nodes(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector(case_root, step3_root, case_id="100004")

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100004"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert result.extra_status_fields["nonsemantic_connector_rcsdnode_ids"] == ["rc_connector"]
    assert result.extra_status_fields["true_foreign_rcsdnode_ids"] == ["rc_far"]
    assert result.audit_doc["step5"]["connector_incident_retained_rcsdroad_ids"] == {
        "rc_connector": ["rc_r_connector", "rc_r_tail"]
    }


def test_step45_no_longer_builds_hard_foreign_swsd_context(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_multi_surface_filter(case_root, step3_root, case_id="100005")

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100005"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert result.output_geometries.foreign_swsd_context_geometry is None
    assert result.audit_doc["step5"]["foreign_swsd_road_ids"] == []
    assert result.audit_doc["step5"]["foreign_swsd_group_ids"] == []
    assert result.audit_doc["step5"]["foreign_mask_normalization_mode"] == "road_like_1m_mask_in_step6"


def test_step45_selected_surface_overlap_case_no_longer_uses_selected_surface_protection_patch(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_foreign_selected_surface_overlap(case_root, step3_root, case_id="100007")

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100007"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert result.output_geometries.foreign_swsd_context_geometry is None
    assert result.audit_doc["step5"]["selected_surface_foreign_protection_applied"] is False
    assert result.audit_doc["step5"]["selected_surface_protection_buffer_m"] == 0.0
    assert result.audit_doc["step5"]["foreign_swsd_context_area_before_selected_surface_protection_m2"] == 0.0
    assert result.audit_doc["step5"]["foreign_swsd_context_area_after_selected_surface_protection_m2"] == 0.0
