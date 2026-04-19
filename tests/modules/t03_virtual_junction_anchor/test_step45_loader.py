from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import load_step45_case_specs, load_step45_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import build_step45_case_result
from tests.modules.t03_virtual_junction_anchor._step45_helpers import build_center_case_a, write_step3_prerequisite, write_step45_case_package


def test_step45_loader_reads_step3_prerequisites_and_selected_roads(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")

    specs, preflight = load_step45_case_specs(case_root=case_root, exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)

    assert preflight["raw_case_count"] == 1
    assert context.step1_context.case_spec.case_id == "100001"
    assert context.template_result.template_class == "center_junction"
    assert context.step3_status_doc["step3_state"] == "established"
    assert context.selected_road_ids == ("road_h", "road_v")
    assert context.step3_allowed_space_geometry is not None
    assert context.prerequisite_issues == ()


def test_step45_loader_blocks_when_selected_road_ids_missing(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100001")
    write_step3_prerequisite(
        step3_root,
        "100001",
        template_class="center_junction",
        selected_road_ids=[],
    )

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100001"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert context.selected_road_ids == ()
    assert context.current_swsd_surface_geometry is None
    assert "step45_missing_selected_road_ids" in context.prerequisite_issues
    assert result.association_class == "C"
    assert result.step45_state == "not_established"
    assert result.reason == "step45_missing_selected_road_ids"
    assert result.extra_status_fields["association_blocker"] == "step45_missing_selected_road_ids"


def test_step45_loader_blocks_when_step3_case_dir_missing(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    write_step45_case_package(case_root / "100009", "100009")

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100009"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert "step45_missing_step3_case_dir" in context.prerequisite_issues
    assert result.association_class == "C"
    assert result.step45_state == "not_established"
    assert result.reason == "step45_missing_step3_case_dir"


def test_step45_loader_blocks_when_step3_status_json_missing(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_center_case_a(case_root, step3_root, case_id="100010")
    (step3_root / "cases" / "100010" / "step3_status.json").unlink()

    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=["100010"], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    result = build_step45_case_result(context)

    assert "step45_missing_step3_status_json" in context.prerequisite_issues
    assert result.step45_state == "not_established"
    assert result.reason == "step45_missing_step3_status_json"
