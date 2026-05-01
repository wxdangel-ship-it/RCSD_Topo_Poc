from __future__ import annotations

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.surface_scenario import (
    MAIN_EVIDENCE_NONE,
    MAIN_EVIDENCE_ROAD_SURFACE_FORK,
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
    classify_surface_scenario,
)


def test_divstrip_with_rcsd_junction_classifies_as_main_evidence_with_rcsd() -> None:
    scenario = classify_surface_scenario(
        evidence_source="divstrip_direct",
        selected_evidence_summary={"upper_evidence_kind": "divstrip"},
        required_rcsd_node="rcsd-node-1",
    )

    assert scenario.has_main_evidence is True
    assert scenario.main_evidence_type == "divstrip"
    assert scenario.reference_point_present is True
    assert scenario.reference_point_source == "divstrip"
    assert scenario.section_reference_source == SECTION_REFERENCE_POINT_AND_RCSD
    assert scenario.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
    assert scenario.surface_generation_mode == SURFACE_MODE_MAIN_EVIDENCE


def test_road_surface_fork_with_rcsd_junction_classifies_as_main_evidence_with_rcsd() -> None:
    scenario = classify_surface_scenario(
        evidence_source="road_surface_fork",
        selected_evidence_summary={"candidate_scope": "road_surface_fork"},
        required_rcsd_node="rcsd-node-1",
    )

    assert scenario.has_main_evidence is True
    assert scenario.main_evidence_type == MAIN_EVIDENCE_ROAD_SURFACE_FORK
    assert scenario.reference_point_source == MAIN_EVIDENCE_ROAD_SURFACE_FORK
    assert scenario.section_reference_source == SECTION_REFERENCE_POINT_AND_RCSD
    assert scenario.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD


def test_divstrip_with_rcsdroad_fallback_classifies_as_main_evidence_with_fallback() -> None:
    scenario = classify_surface_scenario(
        evidence_source="divstrip_direct",
        selected_evidence_summary={"upper_evidence_kind": "divstrip"},
        first_hit_rcsdroad_ids=("road-1",),
    )

    assert scenario.has_main_evidence is True
    assert scenario.rcsd_match_type == "rcsdroad_fallback"
    assert scenario.fallback_rcsdroad_ids == ("road-1",)
    assert scenario.section_reference_source == SECTION_REFERENCE_POINT
    assert scenario.surface_scenario_type == SCENARIO_MAIN_WITH_RCSDROAD


def test_road_surface_fork_without_rcsd_classifies_as_main_evidence_without_rcsd() -> None:
    scenario = classify_surface_scenario(
        evidence_source="road_surface_fork",
        selected_evidence_summary={"candidate_scope": "road_surface_fork"},
    )

    assert scenario.has_main_evidence is True
    assert scenario.rcsd_match_type == "none"
    assert scenario.section_reference_source == SECTION_REFERENCE_POINT
    assert scenario.surface_scenario_type == SCENARIO_MAIN_WITHOUT_RCSD


def test_road_surface_fork_no_support_published_roads_do_not_create_fallback() -> None:
    scenario = classify_surface_scenario(
        evidence_source="road_surface_fork",
        selected_evidence_summary={"candidate_scope": "road_surface_fork"},
        positive_rcsd_audit={
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": "road_surface_fork_structure_only_no_rcsd",
            "published_rcsdroad_ids": ["road-1", "road-2"],
            "first_hit_rcsdroad_ids": ["road-3"],
        },
    )

    assert scenario.has_main_evidence is True
    assert scenario.rcsd_match_type == "none"
    assert scenario.fallback_rcsdroad_ids == ()
    assert scenario.surface_scenario_type == SCENARIO_MAIN_WITHOUT_RCSD


def test_rcsd_anchored_reverse_recovered_divstrip_is_main_evidence_with_rcsd() -> None:
    scenario = classify_surface_scenario(
        evidence_source="rcsd_anchored_reverse",
        selected_evidence_summary={
            "upper_evidence_kind": "divstrip",
            "candidate_scope": "divstrip_component",
            "rcsd_anchored_reverse_recovered_evidence": True,
        },
        rcsd_selection_mode="rcsd_anchored_reverse:aggregated_node_centric_from_first_hit",
        required_rcsd_node="rcsd-node-1",
        fact_reference_point_present=True,
    )

    assert scenario.has_main_evidence is True
    assert scenario.main_evidence_type == "divstrip"
    assert scenario.reference_point_present is True
    assert scenario.reference_point_source == "divstrip"
    assert scenario.section_reference_source == SECTION_REFERENCE_POINT_AND_RCSD
    assert scenario.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
    assert scenario.surface_generation_mode == SURFACE_MODE_MAIN_EVIDENCE


def test_rcsd_anchored_reverse_without_recovered_evidence_is_not_main_evidence() -> None:
    scenario = classify_surface_scenario(
        evidence_source="rcsd_anchored_reverse",
        selected_evidence_summary={
            "upper_evidence_kind": "rcsd_anchor",
            "candidate_scope": "rcsd_anchored_axis_projection",
        },
        rcsd_selection_mode="rcsd_anchored_reverse:aggregated_node_centric_from_first_hit",
        required_rcsd_node="rcsd-node-1",
        fact_reference_point_present=True,
    )

    assert scenario.has_main_evidence is False
    assert scenario.main_evidence_type == MAIN_EVIDENCE_NONE
    assert scenario.reference_point_present is False
    assert scenario.section_reference_source == SECTION_REFERENCE_RCSD
    assert scenario.surface_scenario_type == SCENARIO_NO_MAIN_WITH_RCSD


def test_no_evidence_with_rcsd_junction_uses_rcsd_section_reference_only() -> None:
    scenario = classify_surface_scenario(
        evidence_source="rcsd_junction_window",
        rcsd_selection_mode="rcsd_junction_window",
        required_rcsd_node="rcsd-node-1",
        fact_reference_point_present=True,
    )

    assert scenario.has_main_evidence is False
    assert scenario.main_evidence_type == MAIN_EVIDENCE_NONE
    assert scenario.reference_point_present is False
    assert scenario.reference_point_source == MAIN_EVIDENCE_NONE
    assert scenario.no_reference_point_reason == "no_main_evidence"
    assert scenario.section_reference_source == SECTION_REFERENCE_RCSD
    assert scenario.surface_scenario_type == SCENARIO_NO_MAIN_WITH_RCSD
    assert scenario.surface_generation_mode == SURFACE_MODE_RCSD_WINDOW


def test_no_evidence_with_rcsdroad_fallback_and_swsd_uses_swsd_section_reference() -> None:
    scenario = classify_surface_scenario(
        evidence_source="swsd_junction_window",
        first_hit_rcsdroad_ids=("road-1", "road-2"),
    )

    assert scenario.has_main_evidence is False
    assert scenario.reference_point_present is False
    assert scenario.rcsd_match_type == "rcsdroad_fallback"
    assert scenario.swsd_junction_present is True
    assert scenario.fallback_rcsdroad_ids == ("road-1", "road-2")
    assert scenario.section_reference_source == SECTION_REFERENCE_SWSD
    assert scenario.surface_scenario_type == SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD
    assert scenario.surface_generation_mode == SURFACE_MODE_SWSD_WITH_RCSDROAD


def test_no_evidence_with_swsd_only_classifies_as_swsd_only() -> None:
    scenario = classify_surface_scenario(evidence_source="swsd_junction_window")

    assert scenario.has_main_evidence is False
    assert scenario.rcsd_match_type == "none"
    assert scenario.swsd_junction_present is True
    assert scenario.reference_point_present is False
    assert scenario.section_reference_source == SECTION_REFERENCE_SWSD
    assert scenario.surface_scenario_type == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
    assert scenario.surface_generation_mode == SURFACE_MODE_SWSD_WINDOW


def test_no_evidence_no_rcsd_no_swsd_classifies_as_no_surface_reference() -> None:
    scenario = classify_surface_scenario(evidence_source="none", fact_reference_point_present=True)

    assert scenario.has_main_evidence is False
    assert scenario.reference_point_present is False
    assert scenario.reference_point_source == MAIN_EVIDENCE_NONE
    assert scenario.section_reference_source == SECTION_REFERENCE_NONE
    assert scenario.surface_scenario_type == SCENARIO_NO_SURFACE_REFERENCE
    assert scenario.surface_generation_mode == SURFACE_MODE_NO_SURFACE
    assert scenario.no_reference_point_reason == "no_surface_reference"


def test_no_main_evidence_never_generates_reference_point_even_with_rcsd_or_swsd() -> None:
    for evidence_source in ("rcsd_junction_window", "swsd_junction_window", "rcsd_anchored_reverse"):
        scenario = classify_surface_scenario(
            evidence_source=evidence_source,
            required_rcsd_node="rcsd-node-1",
            fact_reference_point_present=True,
        )

        assert scenario.has_main_evidence is False
        assert scenario.reference_point_present is False
        assert scenario.reference_point_source == MAIN_EVIDENCE_NONE


def test_rcsd_or_swsd_window_does_not_inherit_candidate_scope_as_main_evidence() -> None:
    for evidence_source in ("rcsd_junction_window", "swsd_junction_window"):
        scenario = classify_surface_scenario(
            evidence_source=evidence_source,
            selected_evidence_summary={"candidate_scope": "road_surface_fork"},
        )

        assert scenario.main_evidence_type == MAIN_EVIDENCE_NONE
        assert scenario.has_main_evidence is False
