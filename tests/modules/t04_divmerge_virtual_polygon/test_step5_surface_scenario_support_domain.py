from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain import (
    _build_fallback_support_strip,
    _build_step5_unit_result,
    derive_step5_surface_window_config,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.surface_scenario import (
    SCENARIO_MAIN_WITHOUT_RCSD,
    SCENARIO_MAIN_WITH_RCSD,
    SCENARIO_MAIN_WITH_RCSDROAD,
    SCENARIO_NO_MAIN_WITH_RCSD,
    SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SCENARIO_NO_SURFACE_REFERENCE,
    SECTION_REFERENCE_NONE,
    SECTION_REFERENCE_POINT,
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
    SECTION_REFERENCE_SWSD,
    SURFACE_MODE_MAIN_EVIDENCE,
    SURFACE_MODE_NO_SURFACE,
    SURFACE_MODE_RCSD_WINDOW,
    SURFACE_MODE_SWSD_WINDOW,
    SURFACE_MODE_SWSD_WITH_RCSDROAD,
)


def _scenario_doc(
    *,
    scenario_type: str,
    section_reference_source: str,
    surface_generation_mode: str,
    reference_point_present: bool,
    has_main_evidence: bool,
    fallback_rcsdroad_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "surface_scenario_type": scenario_type,
        "section_reference_source": section_reference_source,
        "surface_generation_mode": surface_generation_mode,
        "reference_point_present": reference_point_present,
        "has_main_evidence": has_main_evidence,
        "fallback_rcsdroad_ids": list(fallback_rcsdroad_ids),
    }


@pytest.mark.parametrize(
    ("scenario_doc", "expected_reference", "expected_mode", "fallback_localized"),
    [
        (
            _scenario_doc(
                scenario_type=SCENARIO_MAIN_WITH_RCSD,
                section_reference_source=SECTION_REFERENCE_POINT_AND_RCSD,
                surface_generation_mode=SURFACE_MODE_MAIN_EVIDENCE,
                reference_point_present=True,
                has_main_evidence=True,
            ),
            SECTION_REFERENCE_POINT_AND_RCSD,
            SURFACE_MODE_MAIN_EVIDENCE,
            False,
        ),
        (
            _scenario_doc(
                scenario_type=SCENARIO_MAIN_WITH_RCSDROAD,
                section_reference_source=SECTION_REFERENCE_POINT,
                surface_generation_mode=SURFACE_MODE_MAIN_EVIDENCE,
                reference_point_present=True,
                has_main_evidence=True,
                fallback_rcsdroad_ids=("r1",),
            ),
            SECTION_REFERENCE_POINT,
            SURFACE_MODE_MAIN_EVIDENCE,
            True,
        ),
        (
            _scenario_doc(
                scenario_type=SCENARIO_MAIN_WITHOUT_RCSD,
                section_reference_source=SECTION_REFERENCE_POINT,
                surface_generation_mode=SURFACE_MODE_MAIN_EVIDENCE,
                reference_point_present=True,
                has_main_evidence=True,
            ),
            SECTION_REFERENCE_POINT,
            SURFACE_MODE_MAIN_EVIDENCE,
            False,
        ),
        (
            _scenario_doc(
                scenario_type=SCENARIO_NO_MAIN_WITH_RCSD,
                section_reference_source=SECTION_REFERENCE_RCSD,
                surface_generation_mode=SURFACE_MODE_RCSD_WINDOW,
                reference_point_present=False,
                has_main_evidence=False,
            ),
            SECTION_REFERENCE_RCSD,
            SURFACE_MODE_RCSD_WINDOW,
            False,
        ),
        (
            _scenario_doc(
                scenario_type=SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
                section_reference_source=SECTION_REFERENCE_SWSD,
                surface_generation_mode=SURFACE_MODE_SWSD_WITH_RCSDROAD,
                reference_point_present=False,
                has_main_evidence=False,
                fallback_rcsdroad_ids=("r2",),
            ),
            SECTION_REFERENCE_SWSD,
            SURFACE_MODE_SWSD_WITH_RCSDROAD,
            True,
        ),
        (
            _scenario_doc(
                scenario_type=SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
                section_reference_source=SECTION_REFERENCE_SWSD,
                surface_generation_mode=SURFACE_MODE_SWSD_WINDOW,
                reference_point_present=False,
                has_main_evidence=False,
            ),
            SECTION_REFERENCE_SWSD,
            SURFACE_MODE_SWSD_WINDOW,
            False,
        ),
        (
            _scenario_doc(
                scenario_type=SCENARIO_NO_SURFACE_REFERENCE,
                section_reference_source=SECTION_REFERENCE_NONE,
                surface_generation_mode=SURFACE_MODE_NO_SURFACE,
                reference_point_present=False,
                has_main_evidence=False,
            ),
            SECTION_REFERENCE_NONE,
            SURFACE_MODE_NO_SURFACE,
            False,
        ),
    ],
)
def test_step5_window_config_covers_surface_scenarios(
    scenario_doc: dict[str, object],
    expected_reference: str,
    expected_mode: str,
    fallback_localized: bool,
) -> None:
    config = derive_step5_surface_window_config(scenario_doc)

    assert config.section_reference_source == expected_reference
    assert config.surface_generation_mode == expected_mode
    assert config.surface_section_forward_m == pytest.approx(20.0)
    assert config.surface_section_backward_m == pytest.approx(20.0)
    assert config.surface_lateral_limit_m == pytest.approx(20.0)
    assert config.support_domain_from_reference_kind == expected_reference
    assert config.fallback_rcsdroad_localized is fallback_localized
    assert config.no_virtual_reference_point_guard is True
    if scenario_doc["has_main_evidence"]:
        assert config.reference_point_present is True
    else:
        assert config.reference_point_present is False


def test_step5_rejects_virtual_reference_point_in_no_main_evidence_config() -> None:
    config = derive_step5_surface_window_config(
        _scenario_doc(
            scenario_type=SCENARIO_NO_MAIN_WITH_RCSD,
            section_reference_source=SECTION_REFERENCE_RCSD,
            surface_generation_mode=SURFACE_MODE_RCSD_WINDOW,
            reference_point_present=True,
            has_main_evidence=False,
        )
    )

    assert config.no_virtual_reference_point_guard is False


def test_step5_fallback_strip_is_localized_around_swsd_section_reference() -> None:
    legacy_bridge = SimpleNamespace(
        event_axis_unit_vector=(1.0, 0.0),
        event_axis_centerline=None,
        event_origin_point=None,
        selected_event_roads=(),
        selected_roads=(),
    )
    unit_result = SimpleNamespace(
        fact_reference_point=Point(-100.0, 0.0),
        review_materialized_point=Point(10.0, 0.0),
        interpretation=SimpleNamespace(legacy_step5_bridge=legacy_bridge),
        surface_scenario_doc=lambda: _scenario_doc(
            scenario_type=SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
            section_reference_source=SECTION_REFERENCE_SWSD,
            surface_generation_mode=SURFACE_MODE_SWSD_WITH_RCSDROAD,
            reference_point_present=False,
            has_main_evidence=False,
            fallback_rcsdroad_ids=("r2",),
        ),
    )
    drivezone = Polygon([(-30, -30), (50, -30), (50, 30), (-30, 30), (-30, -30)])

    strip = _build_fallback_support_strip(unit_result, drivezone_union=drivezone)

    assert strip is not None
    assert strip.bounds[0] == pytest.approx(-10.0, abs=1e-6)
    assert strip.bounds[2] == pytest.approx(30.0, abs=1e-6)
    assert strip.bounds[3] - strip.bounds[1] == pytest.approx(6.0, abs=1e-6)
    assert not strip.covers(Point(-90.0, 0.0))


def test_step5_main_evidence_with_rcsd_uses_scenario_not_evidence_source_for_full_fill() -> None:
    legacy_bridge = SimpleNamespace(
        event_axis_unit_vector=(1.0, 0.0),
        event_axis_centerline=LineString([(0.0, 0.0), (40.0, 0.0)]),
        event_origin_point=Point(0.0, 0.0),
        selected_event_roads=(),
        selected_roads=(),
        selected_road_ids=(),
        selected_event_road_ids=(),
    )
    unit_result = SimpleNamespace(
        spec=SimpleNamespace(event_unit_id="event_unit_01", event_type="diverge"),
        interpretation=SimpleNamespace(
            legacy_step5_bridge=legacy_bridge,
            legacy_step5_readiness=SimpleNamespace(ready=True, reasons=()),
            kind_resolution=SimpleNamespace(operational_kind_2=8),
        ),
        review_state="STEP4_REVIEW",
        all_review_reasons=lambda: (),
        positive_rcsd_consistency_level="A",
        positive_rcsd_support_level="primary_support",
        required_rcsd_node="rcsd-node-1",
        required_rcsd_node_geometry=Point(20.0, 0.0),
        selected_rcsdroad_ids=("rcsd-road-1",),
        selected_rcsdnode_ids=("rcsd-node-1",),
        fact_reference_point=Point(0.0, 0.0),
        review_materialized_point=Point(0.0, 0.0),
        localized_evidence_core_geometry=Point(0.0, 0.0).buffer(2.0),
        selected_candidate_region_geometry=Point(0.0, 0.0).buffer(3.0),
        selected_component_union_geometry=Point(0.0, 0.0).buffer(3.0),
        pair_local_structure_face_geometry=None,
        evidence_source="reverse_tip_retry",
        surface_scenario_doc=lambda: _scenario_doc(
            scenario_type=SCENARIO_MAIN_WITH_RCSD,
            section_reference_source=SECTION_REFERENCE_POINT_AND_RCSD,
            surface_generation_mode=SURFACE_MODE_MAIN_EVIDENCE,
            reference_point_present=True,
            has_main_evidence=True,
        ),
    )
    drivezone = Polygon([(-20, -20), (60, -20), (60, 20), (-20, 20), (-20, -20)])

    step5_unit = _build_step5_unit_result(
        unit_result,
        drivezone_union=drivezone,
        case_external_forbidden_geometry=None,
        other_unit_core_occupancy_geometry=None,
        divstrip_negative_mask_present=False,
    )

    assert step5_unit.surface_fill_mode == "junction_full_road_fill"
    assert step5_unit.junction_full_road_fill_domain is not None
    assert step5_unit.must_cover_components["junction_full_road_fill_domain"] is True
    assert step5_unit.positive_rcsd_road_ids == ("rcsd-road-1",)


def test_step5_main_evidence_with_rcsd_keeps_standard_fill_for_continuous_chain() -> None:
    legacy_bridge = SimpleNamespace(
        event_axis_unit_vector=(1.0, 0.0),
        event_axis_centerline=LineString([(0.0, 0.0), (40.0, 0.0)]),
        event_origin_point=Point(0.0, 0.0),
        selected_event_roads=(),
        selected_roads=(),
        selected_road_ids=(),
        selected_event_road_ids=(),
    )
    unit_result = SimpleNamespace(
        spec=SimpleNamespace(event_unit_id="event_unit_01", event_type="diverge"),
        interpretation=SimpleNamespace(
            legacy_step5_bridge=legacy_bridge,
            legacy_step5_readiness=SimpleNamespace(ready=True, reasons=()),
            kind_resolution=SimpleNamespace(operational_kind_2=8),
        ),
        review_state="STEP4_REVIEW",
        all_review_reasons=lambda: ("continuous_chain_review",),
        positive_rcsd_consistency_level="A",
        positive_rcsd_support_level="primary_support",
        required_rcsd_node="rcsd-node-1",
        required_rcsd_node_geometry=Point(20.0, 0.0),
        selected_rcsdroad_ids=("rcsd-road-1",),
        selected_rcsdnode_ids=("rcsd-node-1",),
        fact_reference_point=Point(0.0, 0.0),
        review_materialized_point=Point(0.0, 0.0),
        localized_evidence_core_geometry=Point(0.0, 0.0).buffer(2.0),
        selected_candidate_region_geometry=Point(0.0, 0.0).buffer(3.0),
        selected_component_union_geometry=Point(0.0, 0.0).buffer(3.0),
        pair_local_structure_face_geometry=None,
        evidence_source="reverse_tip_retry",
        surface_scenario_doc=lambda: _scenario_doc(
            scenario_type=SCENARIO_MAIN_WITH_RCSD,
            section_reference_source=SECTION_REFERENCE_POINT_AND_RCSD,
            surface_generation_mode=SURFACE_MODE_MAIN_EVIDENCE,
            reference_point_present=True,
            has_main_evidence=True,
        ),
    )
    drivezone = Polygon([(-20, -20), (60, -20), (60, 20), (-20, 20), (-20, -20)])

    step5_unit = _build_step5_unit_result(
        unit_result,
        drivezone_union=drivezone,
        case_external_forbidden_geometry=None,
        other_unit_core_occupancy_geometry=None,
        divstrip_negative_mask_present=False,
    )

    assert step5_unit.surface_fill_mode == "standard"
    assert step5_unit.junction_full_road_fill_domain is None
    assert step5_unit.must_cover_components["junction_full_road_fill_domain"] is False
    assert step5_unit.positive_rcsd_road_ids == ("rcsd-road-1",)


def test_step5_no_surface_reference_builds_no_entity_domain_and_keeps_audit() -> None:
    legacy_bridge = SimpleNamespace(
        event_axis_unit_vector=(1.0, 0.0),
        event_axis_centerline=None,
        event_origin_point=None,
        selected_event_roads=(),
        selected_roads=(),
        selected_road_ids=(),
        selected_event_road_ids=(),
    )
    unit_result = SimpleNamespace(
        spec=SimpleNamespace(event_unit_id="event_unit_01", event_type="diverge"),
        interpretation=SimpleNamespace(
            legacy_step5_bridge=legacy_bridge,
            legacy_step5_readiness=SimpleNamespace(ready=False, reasons=("no_surface_reference",)),
        ),
        review_state="STEP4_REVIEW",
        positive_rcsd_consistency_level="",
        positive_rcsd_support_level="",
        required_rcsd_node=None,
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        fact_reference_point=Point(0.0, 0.0),
        surface_scenario_doc=lambda: _scenario_doc(
            scenario_type=SCENARIO_NO_SURFACE_REFERENCE,
            section_reference_source=SECTION_REFERENCE_NONE,
            surface_generation_mode=SURFACE_MODE_NO_SURFACE,
            reference_point_present=False,
            has_main_evidence=False,
        ),
    )
    forbidden = Point(0.0, 0.0).buffer(1.0)

    step5_unit = _build_step5_unit_result(
        unit_result,
        drivezone_union=None,
        case_external_forbidden_geometry=forbidden,
        other_unit_core_occupancy_geometry=None,
        divstrip_negative_mask_present=True,
    )
    status = step5_unit.to_status_doc()
    audit = step5_unit.to_audit_doc()

    assert status["surface_scenario_type"] == SCENARIO_NO_SURFACE_REFERENCE
    assert status["unit_must_cover_domain"]["present"] is False
    assert status["unit_allowed_growth_domain"]["present"] is False
    assert status["fact_reference_patch_geometry"]["present"] is False
    assert status["unit_forbidden_domain"]["present"] is True
    assert status["forbidden_domain_kept"] is True
    assert status["divstrip_negative_mask_present"] is True
    assert audit["no_virtual_reference_point_guard"] is True
    assert "final_state" not in status
    assert "final_state" not in audit
