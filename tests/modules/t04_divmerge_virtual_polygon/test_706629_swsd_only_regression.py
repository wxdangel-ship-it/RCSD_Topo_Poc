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
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_road_surface_fork_rcsd import (
    _junction_window_aggregate,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.surface_scenario import (
    SCENARIO_MAIN_WITHOUT_RCSD,
    SCENARIO_MAIN_WITH_RCSD,
    SCENARIO_MAIN_WITH_RCSDROAD,
    SCENARIO_NO_MAIN_WITH_RCSD,
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
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


def test_partial_aggregated_rcsd_is_not_a_junction_window_semantic_match() -> None:
    audit = {
        "first_hit_rcsdroad_ids": ["road-a", "road-b"],
        "aggregated_rcsd_units": [
            {
                "unit_id": "agg-partial",
                "decision_reason": "role_mapping_partial_aggregated",
                "support_level": "secondary_support",
                "consistency_level": "B",
                "primary_node_id": "node-a",
                "required_node_id": "node-b",
                "road_ids": ["road-a", "road-b", "road-c"],
                "node_ids": ["node-a", "node-b"],
                "member_unit_ids": ["unit:node:node-b", "unit:road_only:01"],
            }
        ],
    }

    assert _junction_window_aggregate(audit) is None


def test_relaxed_partial_rcsd_still_supports_junction_window_when_roles_are_present() -> None:
    audit = {
        "first_hit_rcsdroad_ids": ["road-a"],
        "aggregated_rcsd_units": [
            {
                "unit_id": "agg-relaxed",
                "decision_reason": "role_mapping_partial_relaxed_aggregated",
                "support_level": "secondary_support",
                "consistency_level": "B",
                "primary_node_id": "node-a",
                "required_node_id": "node-a",
                "road_ids": ["road-a", "road-b"],
                "node_ids": ["node-a", "node-b"],
                "normalized_event_side_labels": ["right"],
                "role_assignments": [
                    {"road_id": "road-a", "role": "entering", "first_hit": True},
                    {"road_id": "road-b", "role": "exiting", "first_hit": False},
                ],
                "member_unit_ids": ["unit:node:node-a", "unit:road_only:01"],
            }
        ],
    }

    assert _junction_window_aggregate(audit)["unit_id"] == "agg-relaxed"


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


@pytest.mark.smoke
def test_real_rcsd_window_and_no_support_fallback_regressions(tmp_path: Path) -> None:
    required_cases = [
        "699870",
        "760984",
        "760256",
        "724081",
        "788824",
        "706347",
        "760230",
        "760277",
        "698389",
        "765170",
        "768680",
    ]
    missing = [case_id for case_id in required_cases if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing:
        pytest.skip(f"missing real Anchor_2 cases: {', '.join(missing)}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=required_cases,
        out_root=tmp_path / "out_rcsd_window_regressions",
        run_id="real_rcsd_window_regressions",
    )

    def _docs(case_id: str) -> tuple[dict, dict, dict, dict]:
        case_dir = run_root / "cases" / case_id
        return (
            json.loads((case_dir / "step4_event_interpretation.json").read_text(encoding="utf-8")),
            json.loads((case_dir / "step5_status.json").read_text(encoding="utf-8")),
            json.loads((case_dir / "step6_status.json").read_text(encoding="utf-8")),
            json.loads((case_dir / "step7_status.json").read_text(encoding="utf-8")),
        )

    for case_id, min_area in {
        "699870": 1000.0,
        "760256": 900.0,
    }.items():
        step4, _step5, step6, step7 = _docs(case_id)
        unit4 = step4["event_units"][0]
        assert step7["final_state"] == "accepted"
        assert unit4["evidence_source"] == "rcsd_anchored_reverse"
        assert unit4["surface_scenario_type"] == SCENARIO_MAIN_WITH_RCSD
        assert unit4["section_reference_source"] == SECTION_REFERENCE_POINT_AND_RCSD
        assert unit4["main_evidence_type"] == "divstrip"
        assert unit4["reference_point_present"] is True
        assert unit4["selected_evidence"]["rcsd_anchored_reverse_recovered_evidence"] is True
        assert step6["final_case_polygon"]["area_m2"] > min_area

    for case_id, min_area in {
        "760984": 300.0,
        "788824": 500.0,
    }.items():
        step4, step5, step6, step7 = _docs(case_id)
        unit4 = step4["event_units"][0]
        unit5 = step5["unit_results"][0]
        assert step7["final_state"] == "accepted"
        assert unit4["surface_scenario_type"] == SCENARIO_NO_MAIN_WITH_RCSD
        assert unit4["section_reference_source"] == SECTION_REFERENCE_RCSD
        assert unit4["reference_point_present"] is False
        assert unit5["section_reference_patch_geometry"]["present"] is True
        assert step6["final_case_polygon"]["area_m2"] > min_area

    step4_706347, step5_706347, step6_706347, step7_706347 = _docs("706347")
    unit4_706347 = step4_706347["event_units"][0]
    unit5_706347 = step5_706347["unit_results"][0]
    assert step7_706347["final_state"] == "accepted"
    assert unit4_706347["surface_scenario_type"] == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
    assert unit4_706347["section_reference_source"] == SECTION_REFERENCE_SWSD
    assert unit4_706347["reference_point_present"] is False
    assert unit4_706347["evidence_source"] == "swsd_junction_window"
    assert unit4_706347["selected_evidence"]["rcsd_decision_reason"] == "swsd_junction_window_no_rcsd"
    assert unit5_706347["swsd_only_entity_support_domain"] is True
    assert step6_706347["b_node_gate_applicable"] is False
    assert step6_706347["b_node_gate_skip_reason"] == "swsd_only_without_b_target"
    assert step6_706347["section_reference_window_covered"] is True
    assert step6_706347["final_case_polygon"]["present"] is True

    step4_724081, step5_724081, step6_724081, step7_724081 = _docs("724081")
    unit4_724081 = step4_724081["event_units"][0]
    unit5_724081 = step5_724081["unit_results"][0]
    assert step7_724081["final_state"] == "accepted"
    assert unit4_724081["surface_scenario_type"] == SCENARIO_MAIN_WITHOUT_RCSD
    assert unit4_724081["fallback_rcsdroad_ids"] == []
    assert unit5_724081["fallback_rcsdroad_localized"] is False
    assert unit5_724081["fallback_support_strip_geometry"]["present"] is False
    assert 300.0 < step6_724081["final_case_polygon"]["area_m2"] < 390.0

    step4_698389, step5_698389, step6_698389, step7_698389 = _docs("698389")
    unit4_698389 = step4_698389["event_units"][0]
    unit5_698389 = step5_698389["unit_results"][0]
    assert step7_698389["final_state"] == "accepted"
    assert unit4_698389["main_evidence_type"] == "divstrip"
    assert unit4_698389["reference_point_source"] == "divstrip"
    assert unit4_698389["surface_scenario_type"] == SCENARIO_MAIN_WITH_RCSD
    assert unit4_698389["section_reference_source"] == SECTION_REFERENCE_POINT_AND_RCSD
    assert unit4_698389["resolution_reason"] == "divstrip_primary_over_wide_road_surface_fork"
    assert unit4_698389["selected_evidence"]["candidate_id"] == "event_unit_01:divstrip:1:01"
    assert unit4_698389["selected_evidence"]["selected_divstrip_component_index"] == 1
    assert unit5_698389["junction_full_road_fill_domain"]["present"] is False
    assert unit5_698389["unit_allowed_growth_domain"]["area_m2"] < 1000.0
    assert 750.0 < step6_698389["final_case_polygon"]["area_m2"] < 1000.0
    assert step6_698389["final_case_polygon_component_count"] == 1
    assert step6_698389["hole_count"] == 0

    for case_id, required_node in {
        "760230": "5381293925340534",
        "760277": "5396321846626659",
    }.items():
        step4, step5, step6, step7 = _docs(case_id)
        unit4 = step4["event_units"][0]
        unit5 = step5["unit_results"][0]
        assert step7["final_state"] == "accepted"
        assert unit4["surface_scenario_type"] == SCENARIO_MAIN_WITH_RCSD
        assert unit4["main_evidence_type"] == "road_surface_fork"
        assert unit4["rcsd_match_type"] == "rcsd_junction"
        assert unit4["section_reference_source"] == SECTION_REFERENCE_POINT_AND_RCSD
        assert unit4["required_rcsd_node"] == required_node
        assert unit4["positive_rcsd_support_level"] == "primary_support"
        assert unit4["positive_rcsd_consistency_level"] == "A"
        assert unit5["junction_full_road_fill_domain"]["present"] is True
        assert step6["final_case_polygon_component_count"] == 1

    for case_id, expected_unit_count in {"765170": 2, "768680": 3}.items():
        step4, step5, step6, step7 = _docs(case_id)
        assert step7["final_state"] == "accepted"
        assert len(step4["event_units"]) == expected_unit_count
        assert step5["case_bridge_zone_geometry"]["present"] is True
        assert step6["assembly_state"] == "assembled"
        assert step6["final_case_polygon_component_count"] == 1
        assert step6["single_connected_case_surface_ok"] is True
        assert step6["post_cleanup_allowed_growth_ok"] is True
        assert step6["post_cleanup_forbidden_ok"] is True
        assert step6["post_cleanup_terminal_cut_ok"] is True

    step4_765170, _step5_765170, step6_765170, _step7_765170 = _docs("765170")
    assert {unit["surface_scenario_type"] for unit in step4_765170["event_units"]} == {
        SCENARIO_MAIN_WITH_RCSD
    }
    assert step6_765170["unit_surface_count"] == 2
    assert step6_765170["hole_count"] == 0
    assert step6_765170["unexpected_hole_count"] == 0
    assert step6_765170["final_case_polygon"]["area_m2"] > 4160.0

    step4_768680, step5_768680, step6_768680, _step7_768680 = _docs("768680")
    assert {unit["surface_scenario_type"] for unit in step4_768680["event_units"]} == {
        SCENARIO_MAIN_WITH_RCSD,
        SCENARIO_MAIN_WITH_RCSDROAD,
    }
    fallback_units = [
        unit
        for unit in step5_768680["unit_results"]
        if unit["surface_scenario_type"] == SCENARIO_MAIN_WITH_RCSDROAD
    ]
    assert len(fallback_units) == 1
    assert fallback_units[0]["fallback_rcsdroad_localized"] is True
    assert step6_768680["unit_surface_count"] == 3
