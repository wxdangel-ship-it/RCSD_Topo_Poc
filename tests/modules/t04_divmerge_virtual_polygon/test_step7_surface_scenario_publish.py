from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import Point, Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.final_publish import (
    collect_surface_scenario_summary_counts,
    derive_step7_reject_reason_from_step6_guards,
    derive_step7_surface_scenario_publish_audit,
    build_step7_case_artifact,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.polygon_assembly import T04Step6Result


def _polygon() -> Polygon:
    return Polygon([(0, -5), (20, -5), (20, 5), (0, 5), (0, -5)])


def _step6(**overrides: object) -> T04Step6Result:
    polygon = _polygon()
    values: dict[str, object] = {
        "case_id": "step7_case",
        "final_case_polygon": polygon,
        "final_case_holes": None,
        "final_case_cut_lines": None,
        "final_case_forbidden_overlap": None,
        "assembly_canvas_geometry": polygon,
        "hard_seed_geometry": Point(2, 0).buffer(1.0),
        "weak_seed_geometry": None,
        "component_count": 1,
        "hole_count": 0,
        "business_hole_count": 0,
        "unexpected_hole_count": 0,
        "hard_must_cover_ok": True,
        "b_node_target_covered": True,
        "forbidden_overlap_area_m2": 0.0,
        "cut_violation": False,
        "assembly_state": "assembled",
        "review_reasons": (),
        "hard_connect_notes": (),
        "optional_connect_notes": (),
        "hole_details": (),
        "post_cleanup_allowed_growth_ok": True,
        "post_cleanup_forbidden_ok": True,
        "post_cleanup_terminal_cut_ok": True,
        "post_cleanup_lateral_limit_ok": True,
        "post_cleanup_must_cover_ok": True,
        "post_cleanup_recheck_performed": True,
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "reference_point_present": True,
        "surface_lateral_limit_m": 20.0,
        "surface_scenario_missing": False,
        "no_surface_reference_guard": False,
        "final_polygon_suppressed_by_no_surface_reference": False,
        "fallback_rcsdroad_ids": (),
        "fallback_rcsdroad_localized": False,
        "fallback_domain_contained_by_allowed_growth": True,
        "fallback_overexpansion_detected": False,
        "fallback_overexpansion_area_m2": 0.0,
        "divstrip_negative_mask_present": False,
        "divstrip_negative_overlap_area_m2": 0.0,
        "forbidden_domain_kept": True,
        "unit_surface_count": 1,
        "unit_surface_merge_performed": False,
        "merge_mode": "case_level_assembly",
        "final_case_polygon_component_count": 1,
        "single_connected_case_surface_ok": True,
    }
    values.update(overrides)
    return T04Step6Result(**values)  # type: ignore[arg-type]


def _case_result() -> SimpleNamespace:
    return SimpleNamespace(
        case_spec=SimpleNamespace(case_id="step7_case", mainnodeid="step7_case"),
        admission=SimpleNamespace(source_kind_2=16),
        base_context=SimpleNamespace(
            topology_skeleton=SimpleNamespace(
                chain_context=SimpleNamespace(
                    related_mainnodeids=[],
                    is_in_continuous_chain=False,
                )
            )
        ),
        event_units=[
            SimpleNamespace(
                localized_evidence_core_geometry=Point(1, 0).buffer(1.0),
                selected_candidate_region_geometry=Point(1, 0).buffer(2.0),
                fact_reference_point=Point(1, 0),
                required_rcsd_node=None,
                positive_rcsd_consistency_level="B",
                review_state="STEP4_OK",
            )
        ],
    )


def test_step7_no_surface_reference_is_rejected_without_accepted_feature(tmp_path) -> None:
    step6 = _step6(
        final_case_polygon=None,
        assembly_canvas_geometry=None,
        component_count=0,
        assembly_state="assembly_failed",
        review_reasons=("no_surface_reference",),
        surface_scenario_type="no_surface_reference",
        section_reference_source="none",
        surface_generation_mode="no_surface",
        reference_point_present=False,
        no_surface_reference_guard=True,
        final_polygon_suppressed_by_no_surface_reference=True,
        final_case_polygon_component_count=0,
        single_connected_case_surface_ok=False,
    )

    artifact = build_step7_case_artifact(
        run_root=tmp_path,
        case_dir=tmp_path / "cases" / "step7_case",
        case_result=_case_result(),
        step5_result=SimpleNamespace(case_allowed_growth_domain=None),
        step6_result=step6,
    )

    assert artifact.final_state == "rejected"
    assert artifact.accepted_feature is None
    assert artifact.rejected_feature is not None
    assert artifact.status_doc["final_state"] in {"accepted", "rejected"}
    assert artifact.status_doc["no_surface_reference_guard"] is True
    assert artifact.reject_index_doc["reject_reason"] == "final_polygon_missing"
    assert "no_surface_reference" in artifact.reject_index_doc["reject_reason_detail"]
    assert "final_polygon_suppressed_by_no_surface_reference" in artifact.reject_index_doc["reject_reason_detail"]


@pytest.mark.parametrize(
    ("overrides", "expected_reason", "expected_detail"),
    [
        ({"post_cleanup_forbidden_ok": False}, "forbidden_conflict", "forbidden_conflict"),
        ({"post_cleanup_allowed_growth_ok": False}, "allowed_growth_conflict", "allowed_growth_conflict"),
        ({"post_cleanup_terminal_cut_ok": False}, "terminal_cut_conflict", "terminal_cut_conflict"),
        (
            {"post_cleanup_lateral_limit_ok": False},
            "allowed_growth_conflict",
            "lateral_limit_conflict",
        ),
        (
            {
                "fallback_rcsdroad_localized": True,
                "fallback_overexpansion_detected": True,
                "fallback_overexpansion_area_m2": 3.0,
            },
            "allowed_growth_conflict",
            "fallback_overexpansion_detected",
        ),
        (
            {
                "component_count": 2,
                "final_case_polygon_component_count": 2,
                "single_connected_case_surface_ok": False,
            },
            "multi_component_result",
            "multi_component_result",
        ),
    ],
)
def test_step7_reject_reason_mapping_uses_existing_main_reasons(
    overrides: dict[str, object],
    expected_reason: str,
    expected_detail: str,
) -> None:
    result = derive_step7_reject_reason_from_step6_guards(_step6(**overrides))

    assert result["final_state"] == "rejected"
    assert result["reject_reason"] == expected_reason
    assert expected_detail in result["reject_reason_detail"]


def test_step7_guard_audit_and_summary_counts_preserve_surface_fields() -> None:
    step6 = _step6(
        surface_scenario_type="no_main_evidence_with_swsd_only",
        section_reference_source="swsd_junction",
        surface_generation_mode="swsd_junction_window",
        reference_point_present=False,
        fallback_overexpansion_detected=True,
        divstrip_negative_mask_present=True,
    )
    audit = derive_step7_surface_scenario_publish_audit(step6)
    artifact = SimpleNamespace(
        case_id="step7_case",
        final_state="rejected",
        reject_reasons=("allowed_growth_conflict", "fallback_overexpansion_detected"),
        audit_doc={"step6_guard_audit": audit},
    )

    counts = collect_surface_scenario_summary_counts([artifact])

    assert audit["surface_scenario_type"] == "no_main_evidence_with_swsd_only"
    assert audit["section_reference_source"] == "swsd_junction"
    assert audit["surface_generation_mode"] == "swsd_junction_window"
    assert audit["reference_point_present"] is False
    assert counts["surface_scenario_type_counts"] == {"no_main_evidence_with_swsd_only": 1}
    assert counts["section_reference_source_counts"] == {"swsd_junction": 1}
    assert counts["surface_generation_mode_counts"] == {"swsd_junction_window": 1}
    assert counts["fallback_overexpansion_count"] == 1
    assert counts["divstrip_negative_mask_present_count"] == 1
    assert set(counts["step7_final_state_counts"]) <= {"accepted", "rejected"}
