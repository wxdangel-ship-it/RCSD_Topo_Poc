from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.polygon_assembly import (
    build_step6_polygon_assembly,
    check_post_cleanup_constraints,
    derive_step6_guard_context,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain import (
    T04Step5CaseResult,
    T04Step5UnitResult,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.surface_scenario import (
    SCENARIO_MAIN_WITH_RCSDROAD,
    SCENARIO_NO_SURFACE_REFERENCE,
    SECTION_REFERENCE_NONE,
    SECTION_REFERENCE_POINT,
    SURFACE_MODE_MAIN_EVIDENCE,
    SURFACE_MODE_NO_SURFACE,
)


def _case_result(
    case_id: str = "guard_case",
    drivezone: Polygon | None = None,
    case_alignment_aggregate: dict | None = None,
) -> SimpleNamespace:
    drivezone = drivezone or Polygon([(-20, -20), (80, -20), (80, 20), (-20, 20), (-20, -20)])
    result = SimpleNamespace(
        case_spec=SimpleNamespace(case_id=case_id),
        case_bundle=SimpleNamespace(
            representative_node=SimpleNamespace(geometry=Point(0, 0)),
            drivezone_features=(SimpleNamespace(geometry=drivezone),),
        ),
    )
    if case_alignment_aggregate is not None:
        result.case_alignment_aggregate_doc = lambda: dict(case_alignment_aggregate)
    return result


def _unit(
    *,
    event_unit_id: str = "event_unit_01",
    must_cover: Polygon | None = None,
    allowed: Polygon | None = None,
    fallback: Polygon | None = None,
    scenario_type: str = SCENARIO_MAIN_WITH_RCSDROAD,
    section_reference_source: str = SECTION_REFERENCE_POINT,
    surface_generation_mode: str = SURFACE_MODE_MAIN_EVIDENCE,
    reference_point_present: bool = True,
    fallback_ids: tuple[str, ...] = (),
    fallback_localized: bool = False,
) -> T04Step5UnitResult:
    return T04Step5UnitResult(
        event_unit_id=event_unit_id,
        event_type="diverge",
        review_state="STEP4_OK",
        positive_rcsd_consistency_level="B",
        positive_rcsd_support_level="secondary_support",
        required_rcsd_node=None,
        legacy_step5_ready=True,
        legacy_step5_reasons=(),
        localized_evidence_core_geometry=must_cover,
        fact_reference_patch_geometry=None,
        required_rcsd_node_patch_geometry=None,
        target_b_node_patch_geometry=None,
        fallback_support_strip_geometry=fallback,
        unit_must_cover_domain=must_cover,
        unit_allowed_growth_domain=allowed,
        unit_forbidden_domain=None,
        unit_terminal_cut_constraints=None,
        unit_terminal_window_domain=None,
        terminal_support_corridor_geometry=None,
        surface_scenario_type=scenario_type,
        section_reference_source=section_reference_source,
        surface_generation_mode=surface_generation_mode,
        reference_point_present=reference_point_present,
        surface_lateral_limit_m=20.0,
        fallback_rcsdroad_ids=fallback_ids,
        fallback_rcsdroad_localized=fallback_localized,
        no_virtual_reference_point_guard=not (reference_point_present and scenario_type == SCENARIO_NO_SURFACE_REFERENCE),
        forbidden_domain_kept=True,
    )


def _step5_result(
    *,
    units: tuple[T04Step5UnitResult, ...],
    must_cover: Polygon | None,
    allowed: Polygon | None,
    forbidden: Polygon | None = None,
    terminal_cut: LineString | None = None,
    bridge_zone: Polygon | None = None,
    unrelated_swsd_mask: Polygon | None = None,
    unrelated_rcsd_mask: Polygon | None = None,
    divstrip_body_mask: Polygon | None = None,
    divstrip_mask: Polygon | None = None,
) -> T04Step5CaseResult:
    return T04Step5CaseResult(
        case_id="guard_case",
        unit_results=units,
        case_must_cover_domain=must_cover,
        case_allowed_growth_domain=allowed,
        case_forbidden_domain=forbidden,
        case_terminal_cut_constraints=terminal_cut,
        case_terminal_window_domain=None,
        case_terminal_support_corridor_geometry=None,
        case_bridge_zone_geometry=bridge_zone,
        case_support_graph_geometry=None,
        unrelated_swsd_mask_geometry=unrelated_swsd_mask,
        unrelated_rcsd_mask_geometry=unrelated_rcsd_mask,
        divstrip_body_mask_geometry=divstrip_body_mask,
        divstrip_void_mask_geometry=divstrip_mask,
        drivezone_outside_enforced_by_allowed_domain=True,
        surface_lateral_limit_m=20.0,
        no_virtual_reference_point_guard=True,
        forbidden_domain_kept=forbidden is not None,
        divstrip_negative_mask_present=divstrip_mask is not None,
    )


def test_step6_no_surface_reference_suppresses_final_polygon() -> None:
    unit = _unit(
        must_cover=None,
        allowed=None,
        scenario_type=SCENARIO_NO_SURFACE_REFERENCE,
        section_reference_source=SECTION_REFERENCE_NONE,
        surface_generation_mode=SURFACE_MODE_NO_SURFACE,
        reference_point_present=False,
    )
    step5 = _step5_result(units=(unit,), must_cover=None, allowed=None)

    result = build_step6_polygon_assembly(_case_result(), step5)
    status = result.to_status_doc()

    assert result.final_case_polygon is None
    assert status["no_surface_reference_guard"] is True
    assert status["final_polygon_suppressed_by_no_surface_reference"] is True
    assert status["assembly_state"] == "assembly_failed"
    assert "no_surface_reference" in status["review_reasons"]
    assert "final_state" not in status


def test_step6_post_cleanup_recheck_flags_allowed_forbidden_and_terminal_cut() -> None:
    allowed = Polygon([(0, -5), (20, -5), (20, 5), (0, 5), (0, -5)])
    forbidden = Point(10, 0).buffer(2.0)
    terminal_cut = LineString([(18, -10), (18, 10)]).buffer(0.75, cap_style=2)
    final_polygon = Polygon([(0, -4), (24, -4), (24, 4), (0, 4), (0, -4)])
    unit = _unit(must_cover=Point(2, 0).buffer(1.0), allowed=allowed)
    step5 = _step5_result(
        units=(unit,),
        must_cover=Point(2, 0).buffer(1.0),
        allowed=allowed,
        forbidden=forbidden,
    )
    context = derive_step6_guard_context(step5)

    audit = check_post_cleanup_constraints(
        final_case_polygon=final_polygon,
        step5_result=step5,
        cut_barrier_geometry=terminal_cut,
        hard_seed_geometry=Point(2, 0).buffer(1.0),
        guard_context=context,
    )

    assert audit["post_cleanup_recheck_performed"] is True
    assert audit["post_cleanup_allowed_growth_ok"] is False
    assert audit["post_cleanup_forbidden_ok"] is False
    assert audit["post_cleanup_terminal_cut_ok"] is False
    assert audit["post_cleanup_lateral_limit_ok"] is False
    assert audit["lateral_limit_check_mode"] == "via_allowed_growth"


def test_step6_guard_audit_carries_lateral_and_negative_mask_fields() -> None:
    allowed = Polygon([(0, -10), (30, -10), (30, 10), (0, 10), (0, -10)])
    divstrip_mask = Point(12, 0).buffer(2.0)
    unit = _unit(must_cover=Point(5, 0).buffer(2.0), allowed=allowed)
    step5 = _step5_result(
        units=(unit,),
        must_cover=Point(5, 0).buffer(2.0),
        allowed=allowed,
        forbidden=divstrip_mask,
        divstrip_mask=divstrip_mask,
    )

    result = build_step6_polygon_assembly(_case_result(drivezone=allowed.buffer(5)), step5)
    status = result.to_status_doc()
    audit = result.to_audit_doc()

    assert status["surface_lateral_limit_m"] == pytest.approx(20.0)
    assert status["post_cleanup_recheck_performed"] is True
    assert status["post_cleanup_forbidden_ok"] is True
    assert audit["negative_mask_check_mode"] == "per_channel_negative_mask_overlap"
    assert audit["relief_constraint_audit_entries"] == []
    assert status["divstrip_negative_mask_present"] is True
    assert status["divstrip_negative_overlap_area_m2"] == pytest.approx(0.0, abs=1e-6)


def test_step6_post_cleanup_overlap_audit_is_split_by_mask_channel() -> None:
    allowed = Polygon([(0, -5), (40, -5), (40, 5), (0, 5), (0, -5)])
    final_polygon = Polygon([(0, -4), (30, -4), (30, 4), (0, 4), (0, -4)])
    unrelated_swsd_mask = Point(10, 0).buffer(1.0)
    unrelated_rcsd_mask = Point(50, 0).buffer(1.0)
    divstrip_body_mask = Point(15, 0).buffer(1.0)
    divstrip_void_mask = Point(20, 0).buffer(1.0)
    terminal_cut = LineString([(25, -10), (25, 10)]).buffer(0.75, cap_style=2)
    unit = _unit(must_cover=Point(2, 0).buffer(1.0), allowed=allowed)
    step5 = _step5_result(
        units=(unit,),
        must_cover=Point(2, 0).buffer(1.0),
        allowed=allowed,
        forbidden=unary_union([unrelated_swsd_mask, divstrip_void_mask]),
        terminal_cut=terminal_cut,
        unrelated_swsd_mask=unrelated_swsd_mask,
        unrelated_rcsd_mask=unrelated_rcsd_mask,
        divstrip_body_mask=divstrip_body_mask,
        divstrip_mask=divstrip_void_mask,
    )
    context = derive_step6_guard_context(step5)

    audit = check_post_cleanup_constraints(
        final_case_polygon=final_polygon,
        step5_result=step5,
        cut_barrier_geometry=terminal_cut,
        hard_seed_geometry=Point(2, 0).buffer(1.0),
        guard_context=context,
    )
    channels = audit["negative_mask_channel_overlaps"]

    assert set(channels) == {
        "unrelated_swsd",
        "unrelated_rcsd",
        "divstrip_body",
        "divstrip_void",
        "forbidden_domain",
        "terminal_cut",
    }
    assert channels["unrelated_swsd"]["overlap_area_m2"] > 0.0
    assert channels["unrelated_swsd"]["ok"] is False
    assert channels["unrelated_rcsd"]["overlap_area_m2"] == pytest.approx(0.0, abs=1e-6)
    assert channels["unrelated_rcsd"]["ok"] is True
    assert channels["divstrip_body"]["applied_to_forbidden_domain"] is False
    assert channels["divstrip_body"]["overlap_area_m2"] > 0.0
    assert channels["divstrip_void"]["overlap_area_m2"] > 0.0
    assert channels["terminal_cut"]["overlap_area_m2"] > 0.0


def test_step6_bridge_negative_mask_crossing_is_audited_by_channel() -> None:
    allowed = Polygon([(0, -5), (40, -5), (40, 5), (0, 5), (0, -5)])
    bridge_zone = Polygon([(5, -1), (25, -1), (25, 1), (5, 1), (5, -1)])
    unrelated_swsd_mask = Point(10, 0).buffer(1.0)
    unrelated_rcsd_mask = Point(50, 0).buffer(1.0)
    unit = _unit(must_cover=Point(2, 0).buffer(1.0), allowed=allowed)
    step5 = _step5_result(
        units=(unit,),
        must_cover=Point(2, 0).buffer(1.0),
        allowed=allowed,
        bridge_zone=bridge_zone,
        unrelated_swsd_mask=unrelated_swsd_mask,
        unrelated_rcsd_mask=unrelated_rcsd_mask,
    )
    context = derive_step6_guard_context(step5)

    audit = check_post_cleanup_constraints(
        final_case_polygon=allowed,
        step5_result=step5,
        cut_barrier_geometry=None,
        hard_seed_geometry=Point(2, 0).buffer(1.0),
        guard_context=context,
    )
    channels = audit["bridge_negative_mask_channel_overlaps"]

    assert audit["bridge_negative_mask_crossing_detected"] is True
    assert channels["unrelated_swsd"]["overlap_area_m2"] > 0.0
    assert channels["unrelated_swsd"]["ok"] is False
    assert channels["unrelated_rcsd"]["overlap_area_m2"] == pytest.approx(0.0, abs=1e-6)
    assert channels["unrelated_rcsd"]["ok"] is True


def test_step6_fallback_overexpansion_guard_uses_allowed_growth() -> None:
    allowed = Polygon([(0, -4), (20, -4), (20, 4), (0, 4), (0, -4)])
    fallback = Polygon([(0, -2), (20, -2), (20, 2), (0, 2), (0, -2)])
    final_polygon = Polygon([(0, -4), (30, -4), (30, 4), (0, 4), (0, -4)])
    unit = _unit(
        must_cover=Point(2, 0).buffer(1.0),
        allowed=allowed,
        fallback=fallback,
        fallback_ids=("road_1",),
        fallback_localized=True,
    )
    step5 = _step5_result(units=(unit,), must_cover=Point(2, 0).buffer(1.0), allowed=allowed)
    context = derive_step6_guard_context(step5)

    audit = check_post_cleanup_constraints(
        final_case_polygon=final_polygon,
        step5_result=step5,
        cut_barrier_geometry=None,
        hard_seed_geometry=Point(2, 0).buffer(1.0),
        guard_context=context,
    )

    assert context.fallback_rcsdroad_localized is True
    assert audit["fallback_domain_contained_by_allowed_growth"] is True
    assert audit["fallback_overexpansion_detected"] is True
    assert audit["fallback_overexpansion_area_m2"] > 0.0


def test_step6_multi_unit_case_records_case_level_merge_audit() -> None:
    left = Point(5, 0).buffer(2.0)
    right = Point(25, 0).buffer(2.0)
    allowed = unary_union(
        [
            left,
            right,
            Polygon([(5, -1), (25, -1), (25, 1), (5, 1), (5, -1)]),
        ]
    )
    unit_1 = _unit(event_unit_id="event_unit_01", must_cover=left, allowed=allowed)
    unit_2 = _unit(event_unit_id="event_unit_02", must_cover=right, allowed=allowed)
    step5 = _step5_result(units=(unit_1, unit_2), must_cover=unary_union([left, right]), allowed=allowed)

    result = build_step6_polygon_assembly(_case_result(drivezone=allowed.buffer(10)), step5)
    status = result.to_status_doc()

    assert status["unit_surface_count"] == 2
    assert status["unit_surface_merge_performed"] is False
    assert status["merge_mode"] == "case_level_assembly"
    assert status["final_case_polygon_component_count"] == status["component_count"]
    assert status["single_connected_case_surface_ok"] == (status["component_count"] == 1)


def test_step6_ambiguous_case_alignment_blocks_silent_merge() -> None:
    seed = Point(5, 0).buffer(2.0)
    allowed = Polygon([(0, -6), (20, -6), (20, 6), (0, 6), (0, -6)])
    unit = _unit(must_cover=seed, allowed=allowed)
    step5 = _step5_result(units=(unit,), must_cover=seed, allowed=allowed)
    case_result = _case_result(
        drivezone=allowed.buffer(10),
        case_alignment_aggregate={"ambiguous_event_unit_ids": ["event_unit_01"]},
    )

    result = build_step6_polygon_assembly(case_result, step5)
    status = result.to_status_doc()

    assert status["assembly_state"] == "assembly_failed"
    assert "ambiguous_case_rcsd_alignment" in status["review_reasons"]
    assert status["case_alignment_review_reasons"] == ["ambiguous_case_rcsd_alignment"]
    assert status["case_alignment_ambiguous_event_unit_ids"] == ["event_unit_01"]
