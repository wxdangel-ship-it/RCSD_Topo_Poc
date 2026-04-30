from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import Point, Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.polygon_assembly import (
    build_step6_polygon_assembly,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain import (
    T04Step5CaseResult,
    T04Step5UnitResult,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.surface_scenario import (
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SECTION_REFERENCE_SWSD,
    SURFACE_MODE_SWSD_WINDOW,
)


REAL_ANCHOR_2_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor_2")


def _case_result() -> SimpleNamespace:
    drivezone = Polygon([(-10, -30), (50, -30), (50, 30), (-10, 30), (-10, -30)])
    return SimpleNamespace(
        case_spec=SimpleNamespace(case_id="706629_synthetic"),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(20, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )


def _swsd_only_step5_result() -> T04Step5CaseResult:
    junction_window = Polygon([(0, -6), (40, -6), (40, 6), (0, 6), (0, -6)])
    unit = T04Step5UnitResult(
        event_unit_id="event_unit_01",
        event_type="continuous_complex",
        review_state="STEP4_OK",
        positive_rcsd_consistency_level="C",
        positive_rcsd_support_level="no_support",
        required_rcsd_node=None,
        legacy_step5_ready=True,
        legacy_step5_reasons=(),
        localized_evidence_core_geometry=None,
        fact_reference_patch_geometry=None,
        required_rcsd_node_patch_geometry=None,
        target_b_node_patch_geometry=None,
        fallback_support_strip_geometry=None,
        unit_must_cover_domain=junction_window,
        unit_allowed_growth_domain=junction_window,
        unit_forbidden_domain=None,
        unit_terminal_cut_constraints=None,
        unit_terminal_window_domain=None,
        terminal_support_corridor_geometry=None,
        junction_full_road_fill_domain=junction_window,
        surface_fill_mode="junction_window",
        surface_fill_axis_half_width_m=20.0,
        surface_scenario_type=SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
        section_reference_source=SECTION_REFERENCE_SWSD,
        surface_generation_mode=SURFACE_MODE_SWSD_WINDOW,
        reference_point_present=False,
        support_domain_from_reference_kind=SECTION_REFERENCE_SWSD,
        no_virtual_reference_point_guard=True,
        forbidden_domain_kept=False,
        swsd_only_entity_support_domain=True,
    )
    return T04Step5CaseResult(
        case_id="706629_synthetic",
        unit_results=(unit,),
        case_must_cover_domain=junction_window,
        case_allowed_growth_domain=junction_window,
        case_forbidden_domain=None,
        case_terminal_cut_constraints=None,
        case_terminal_window_domain=None,
        case_terminal_support_corridor_geometry=None,
        case_bridge_zone_geometry=None,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=None,
        unrelated_rcsd_mask_geometry=None,
        divstrip_void_mask_geometry=None,
        drivezone_outside_enforced_by_allowed_domain=True,
        surface_section_forward_m=20.0,
        surface_section_backward_m=20.0,
        surface_lateral_limit_m=20.0,
        no_virtual_reference_point_guard=True,
        forbidden_domain_kept=False,
        divstrip_negative_mask_present=False,
    )


def test_swsd_only_step6_uses_junction_window_without_reference_or_b_node() -> None:
    result = build_step6_polygon_assembly(_case_result(), _swsd_only_step5_result())
    status = result.to_status_doc()

    assert result.final_case_polygon is not None
    assert not result.final_case_polygon.is_empty
    assert status["surface_scenario_type"] == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
    assert status["section_reference_source"] == SECTION_REFERENCE_SWSD
    assert status["surface_generation_mode"] == SURFACE_MODE_SWSD_WINDOW
    assert status["reference_point_present"] is False
    assert status["no_surface_reference_guard"] is False
    assert status["final_polygon_suppressed_by_no_surface_reference"] is False
    assert status["b_node_gate_applicable"] is False
    assert status["b_node_gate_skip_reason"] == "swsd_only_without_b_target"
    assert status["b_node_target_covered"] is True
    assert status["section_reference_window_covered"] is True
    assert "b_node_not_covered" not in status["review_reasons"]
    assert status["post_cleanup_allowed_growth_ok"] is True
    assert status["post_cleanup_forbidden_ok"] is True
    assert status["post_cleanup_terminal_cut_ok"] is True


@pytest.mark.smoke
def test_real_706629_swsd_only_accepts_without_virtual_reference_point(tmp_path: Path) -> None:
    if not (REAL_ANCHOR_2_ROOT / "706629").is_dir():
        pytest.skip(f"missing real Anchor_2 case: {REAL_ANCHOR_2_ROOT / '706629'}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["706629"],
        out_root=tmp_path / "out",
        run_id="real_706629_swsd_only",
    )
    case_dir = run_root / "cases" / "706629"
    step4_status = json.loads((case_dir / "step4_event_interpretation.json").read_text(encoding="utf-8"))
    step5_status = json.loads((case_dir / "step5_status.json").read_text(encoding="utf-8"))
    step6_status = json.loads((case_dir / "step6_status.json").read_text(encoding="utf-8"))
    step7_status = json.loads((case_dir / "step7_status.json").read_text(encoding="utf-8"))
    unit_step5 = step5_status["unit_results"][0]

    assert step4_status["event_units"][0]["surface_scenario_type"] == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
    assert step4_status["event_units"][0]["section_reference_source"] == SECTION_REFERENCE_SWSD
    assert step4_status["event_units"][0]["reference_point_present"] is False
    assert unit_step5["swsd_only_entity_support_domain"] is True
    assert unit_step5["unit_must_cover_domain"]["present"] is True
    assert unit_step5["unit_allowed_growth_domain"]["present"] is True
    assert step6_status["final_case_polygon"]["present"] is True
    assert step6_status["b_node_gate_applicable"] is False
    assert step6_status["b_node_gate_skip_reason"] == "swsd_only_without_b_target"
    assert step6_status["section_reference_window_covered"] is True
    assert "b_node_not_covered" not in step6_status["review_reasons"]
    assert step6_status["post_cleanup_allowed_growth_ok"] is True
    assert step6_status["post_cleanup_forbidden_ok"] is True
    assert step6_status["post_cleanup_terminal_cut_ok"] is True
    assert step6_status["post_cleanup_lateral_limit_ok"] is True
    assert step6_status["no_surface_reference_guard"] is False
    assert step6_status["final_polygon_suppressed_by_no_surface_reference"] is False
    assert step7_status["final_state"] == "accepted"
