from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import load_step45_case_specs, load_step45_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import build_step45_case_result
from tests.modules.t03_virtual_junction_anchor._step45_helpers import (
    build_center_case_a,
    build_center_case_b,
    build_center_case_c,
    build_center_case_degree2_connector,
    build_center_case_multi_surface_filter,
    build_single_sided_parallel_support_case,
)


def _run_case(case_root: Path, step3_root: Path, case_id: str):
    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=[case_id], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    return build_step45_case_result(context)


def test_step45_association_classifies_case_a(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")

    result = _run_case(case_root, step3_root, "100001")

    assert result.association_class == "A"
    assert result.step45_state == "established"
    assert result.key_metrics["required_rcsdnode_count"] == 1
    assert result.key_metrics["required_rcsdroad_count"] >= 1


def test_step45_association_classifies_case_b_and_hook_zone_not_full_road(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_b(case_root, step3_root, case_id="100002")

    result = _run_case(case_root, step3_root, "100002")

    assert result.association_class == "B"
    assert result.step45_state == "review"
    assert result.output_geometries.support_rcsdroad_geometry is not None
    assert result.output_geometries.support_rcsdroad_geometry.length < 120.0
    assert result.output_geometries.required_hook_zone_geometry is not None


def test_step45_association_classifies_case_c(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_c(case_root, step3_root, case_id="100003")

    result = _run_case(case_root, step3_root, "100003")

    assert result.association_class == "C"
    assert result.step45_state == "established"
    assert result.key_metrics["required_rcsdnode_count"] == 0
    assert result.key_metrics["support_rcsdroad_count"] == 0


def test_step45_degree2_connector_node_is_not_promoted_into_semantic_core(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_degree2_connector(case_root, step3_root, case_id="100004")

    result = _run_case(case_root, step3_root, "100004")

    assert result.association_class == "A"
    assert "rc_core" in result.extra_status_fields["required_rcsdnode_ids"]
    assert "rc_connector" not in result.extra_status_fields["required_rcsdnode_ids"]
    assert "rc_connector" not in result.extra_status_fields["support_rcsdnode_ids"]
    assert result.extra_status_fields["nonsemantic_connector_rcsdnode_ids"] == ["rc_connector"]
    assert result.extra_status_fields["true_foreign_rcsdnode_ids"] == ["rc_far"]
    assert result.audit_doc["step4"]["degree2_connector_candidate_rcsdnode_ids"] == ["rc_connector"]


def test_step45_ignores_rcsd_outside_current_swsd_surface(tmp_path: Path) -> None:
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


def test_step45_single_sided_support_prunes_parallel_duplicate_by_vertical_exit_side(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_single_sided_parallel_support_case(case_root, step3_root, case_id="100006")

    result = _run_case(case_root, step3_root, "100006")

    assert result.association_class == "A"
    assert result.extra_status_fields["support_rcsdroad_ids"] == ["rc_support_exit_side"]
    assert result.extra_status_fields["parallel_support_duplicate_dropped_rcsdroad_ids"] == ["rc_support_parallel"]
    assert result.audit_doc["step4"]["parallel_support_duplicate_dropped_rcsdroad_ids"] == ["rc_support_parallel"]
