from __future__ import annotations

import importlib
from collections.abc import Callable
from enum import Enum
from types import SimpleNamespace
from typing import Any

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import surface_scenario


EXPECTED_ALIGNMENT_TYPES = {
    "rcsd_semantic_junction",
    "rcsd_junction_partial_alignment",
    "rcsdroad_only_alignment",
    "no_rcsd_alignment",
    "ambiguous_rcsd_alignment",
}


def _load_alignment_module() -> Any:
    module_name = "rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.rcsd_alignment"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        pytest.fail(f"expected future module {module_name}", pytrace=False)


def _alignment_values_from_api(module: Any) -> set[str]:
    enum_type = getattr(module, "RcsdAlignmentType", None)
    if enum_type is not None and issubclass(enum_type, Enum):
        return {str(item.value) for item in enum_type}

    values = getattr(module, "RCSD_ALIGNMENT_TYPES", None)
    if values is not None:
        return {str(item.value if isinstance(item, Enum) else item) for item in values}

    pytest.fail(
        "expected RcsdAlignmentType enum or RCSD_ALIGNMENT_TYPES constant",
        pytrace=False,
    )


def _surface_mapper() -> Callable[..., Any]:
    mapper = getattr(surface_scenario, "classify_surface_scenario_from_alignment", None)
    if mapper is None:
        pytest.fail(
            "expected pure surface_scenario.classify_surface_scenario_from_alignment(...)",
            pytrace=False,
        )
    return mapper


def _field(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name)


def test_rcsd_alignment_type_value_domain_is_explicit() -> None:
    module = _load_alignment_module()

    assert _alignment_values_from_api(module) == EXPECTED_ALIGNMENT_TYPES


def test_rcsd_alignment_result_serializes_positive_candidate_and_ambiguity_fields() -> None:
    module = _load_alignment_module()
    result = module.RCSDAlignmentResult(
        scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
        scope_id="event_unit_01",
        rcsd_alignment_type=module.RCSD_ALIGNMENT_AMBIGUOUS,
        positive_rcsdroad_ids=("r1",),
        positive_rcsdnode_ids=("n1",),
        unrelated_rcsdroad_ids=("r2",),
        unrelated_rcsdnode_ids=("n2",),
        candidate_rcsdroad_ids=("r1", "r2"),
        candidate_rcsdnode_ids=("n1", "n2"),
        candidate_alignment_ids=("candidate-a", "candidate-b"),
        ambiguity_reasons=("multi_rcsd_semantic_junction",),
        conflict_reasons=("unrelated_rcsd_conflict",),
        decision_reason="ambiguous_rcsd_alignment",
    )

    doc = result.to_doc()

    assert doc["scope"] == "event_unit"
    assert doc["scope_id"] == "event_unit_01"
    assert doc["rcsd_alignment_type"] == "ambiguous_rcsd_alignment"
    assert doc["positive_rcsdroad_ids"] == ["r1"]
    assert doc["positive_rcsdnode_ids"] == ["n1"]
    assert doc["unrelated_rcsdroad_ids"] == ["r2"]
    assert doc["unrelated_rcsdnode_ids"] == ["n2"]
    assert doc["candidate_rcsdroad_ids"] == ["r1", "r2"]
    assert doc["candidate_rcsdnode_ids"] == ["n1", "n2"]
    assert doc["candidate_alignment_ids"] == ["candidate-a", "candidate-b"]
    assert doc["ambiguity_reasons"] == ["multi_rcsd_semantic_junction"]
    assert doc["conflict_reasons"] == ["unrelated_rcsd_conflict"]
    assert doc["source"] == "step4_frozen_result"


def _case_alignment_doc(unit_docs: list[dict[str, Any]]) -> dict[str, Any]:
    from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_models import T04CaseResult

    units = [
        SimpleNamespace(
            spec=SimpleNamespace(event_unit_id=f"event_unit_{index:02d}"),
            rcsd_alignment_result_doc=lambda doc=doc: dict(doc),
        )
        for index, doc in enumerate(unit_docs, start=1)
    ]
    case_result = T04CaseResult(
        case_spec=SimpleNamespace(case_id="alignment_case"),
        case_bundle=SimpleNamespace(),
        admission=SimpleNamespace(),
        base_context=SimpleNamespace(),
        event_units=units,
        case_review_state="ok",
        case_review_reasons=(),
    )
    return case_result.case_alignment_aggregate_doc()


def test_case_alignment_aggregate_detects_unrelated_positive_rcsd_objects() -> None:
    doc = _case_alignment_doc(
        [
            {
                "rcsd_alignment_type": "rcsd_semantic_junction",
                "positive_rcsdroad_ids": ["r1", "r2", "r3"],
                "positive_rcsdnode_ids": ["n1"],
                "candidate_alignment_ids": ["candidate-a"],
            },
            {
                "rcsd_alignment_type": "rcsd_semantic_junction",
                "positive_rcsdroad_ids": ["r4", "r5", "r6"],
                "positive_rcsdnode_ids": ["n2"],
                "candidate_alignment_ids": ["candidate-b"],
            },
        ]
    )

    assert doc["positive_alignment_object_cluster_count"] == 2
    assert doc["conflict_present"] is True
    assert "cross_unit_unrelated_rcsd_alignment_objects" in doc["conflict_reasons"]
    assert doc["aligned_rcsd_object_ids"] == [
        "roads:r1,r2,r3|nodes:n1",
        "roads:r4,r5,r6|nodes:n2",
    ]


def test_case_alignment_aggregate_does_not_flag_shared_positive_rcsd_object() -> None:
    doc = _case_alignment_doc(
        [
            {
                "rcsd_alignment_type": "rcsd_semantic_junction",
                "positive_rcsdroad_ids": ["r1", "r2", "r3"],
                "positive_rcsdnode_ids": ["n1"],
                "candidate_alignment_ids": ["candidate-a"],
            },
            {
                "rcsd_alignment_type": "rcsd_semantic_junction",
                "positive_rcsdroad_ids": ["r4", "r5", "r6"],
                "positive_rcsdnode_ids": ["n1"],
                "candidate_alignment_ids": ["candidate-b"],
            },
        ]
    )

    assert doc["positive_alignment_object_cluster_count"] == 1
    assert doc["conflict_present"] is False
    assert doc["conflict_reasons"] == []


def test_surface_scenario_maps_from_frozen_alignment() -> None:
    mapper = _surface_mapper()
    rows = [
        (
            True,
            "rcsd_semantic_junction",
            True,
            surface_scenario.SCENARIO_MAIN_WITH_RCSD,
            surface_scenario.SECTION_REFERENCE_POINT_AND_RCSD,
            surface_scenario.SURFACE_MODE_MAIN_EVIDENCE,
        ),
        (
            True,
            "rcsd_junction_partial_alignment",
            True,
            surface_scenario.SCENARIO_MAIN_WITH_RCSDROAD,
            surface_scenario.SECTION_REFERENCE_POINT_AND_RCSD,
            surface_scenario.SURFACE_MODE_MAIN_EVIDENCE,
        ),
        (
            True,
            "rcsdroad_only_alignment",
            True,
            surface_scenario.SCENARIO_MAIN_WITH_RCSDROAD,
            surface_scenario.SECTION_REFERENCE_POINT,
            surface_scenario.SURFACE_MODE_MAIN_EVIDENCE,
        ),
        (
            True,
            "no_rcsd_alignment",
            True,
            surface_scenario.SCENARIO_MAIN_WITHOUT_RCSD,
            surface_scenario.SECTION_REFERENCE_POINT,
            surface_scenario.SURFACE_MODE_MAIN_EVIDENCE,
        ),
        (
            False,
            "rcsd_semantic_junction",
            True,
            surface_scenario.SCENARIO_NO_MAIN_WITH_RCSD,
            surface_scenario.SECTION_REFERENCE_RCSD,
            surface_scenario.SURFACE_MODE_RCSD_WINDOW,
        ),
        (
            False,
            "rcsd_junction_partial_alignment",
            True,
            surface_scenario.SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
            surface_scenario.SECTION_REFERENCE_RCSD,
            surface_scenario.SURFACE_MODE_RCSD_WINDOW,
        ),
        (
            False,
            "rcsdroad_only_alignment",
            True,
            surface_scenario.SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
            surface_scenario.SECTION_REFERENCE_SWSD,
            surface_scenario.SURFACE_MODE_SWSD_WITH_RCSDROAD,
        ),
        (
            False,
            "no_rcsd_alignment",
            True,
            surface_scenario.SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
            surface_scenario.SECTION_REFERENCE_SWSD,
            surface_scenario.SURFACE_MODE_SWSD_WINDOW,
        ),
        (
            False,
            "no_rcsd_alignment",
            False,
            surface_scenario.SCENARIO_NO_SURFACE_REFERENCE,
            surface_scenario.SECTION_REFERENCE_NONE,
            surface_scenario.SURFACE_MODE_NO_SURFACE,
        ),
    ]

    for (
        has_main_evidence,
        rcsd_alignment_type,
        swsd_junction_present,
        expected_scenario,
        expected_section_reference,
        expected_generation_mode,
    ) in rows:
        result = mapper(
            has_main_evidence=has_main_evidence,
            rcsd_alignment_type=rcsd_alignment_type,
            swsd_junction_present=swsd_junction_present,
        )
        case_label = f"{has_main_evidence=}, {rcsd_alignment_type=}, {swsd_junction_present=}"

        assert _field(result, "has_main_evidence") is has_main_evidence, case_label
        assert _field(result, "rcsd_alignment_type") == rcsd_alignment_type, case_label
        assert _field(result, "surface_scenario_type") == expected_scenario, case_label
        assert _field(result, "section_reference_source") == expected_section_reference, case_label
        assert _field(result, "surface_generation_mode") == expected_generation_mode, case_label
        if not has_main_evidence:
            assert _field(result, "reference_point_present") is False, case_label


def test_ambiguous_rcsd_alignment_maps_to_blocking_no_surface_reference() -> None:
    mapper = _surface_mapper()

    result = mapper(
        has_main_evidence=True,
        rcsd_alignment_type="ambiguous_rcsd_alignment",
        swsd_junction_present=True,
    )

    assert _field(result, "surface_scenario_type") == surface_scenario.SCENARIO_NO_SURFACE_REFERENCE
    assert _field(result, "surface_generation_mode") == surface_scenario.SURFACE_MODE_NO_SURFACE
    assert _field(result, "section_reference_source") == surface_scenario.SECTION_REFERENCE_NONE
    assert _field(result, "rcsd_alignment_type") == "ambiguous_rcsd_alignment"
    assert _field(result, "no_reference_point_reason") == "ambiguous_rcsd_alignment"


def test_equal_ranked_distinct_rcsd_candidates_are_ambiguous() -> None:
    from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._rcsd_selection_support import (
        _AggregatedRcsdUnit,
    )
    from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.rcsd_selection import (
        _ambiguous_top_aggregated_rcsd_units,
    )

    def unit(unit_id: str, semantic_group_id: str) -> _AggregatedRcsdUnit:
        return _AggregatedRcsdUnit(
            unit_id=unit_id,
            member_unit_ids=(f"{unit_id}:local",),
            member_unit_kinds=("node_centric",),
            semantic_group_ids=(semantic_group_id,),
            semantic_anchor_distance_m=1.0,
            road_ids=(f"{semantic_group_id}:road_a", f"{semantic_group_id}:road_b", f"{semantic_group_id}:road_c"),
            node_ids=(semantic_group_id,),
            entering_road_ids=(f"{semantic_group_id}:road_a",),
            exiting_road_ids=(f"{semantic_group_id}:road_b",),
            event_side_road_ids=(f"{semantic_group_id}:road_a",),
            axis_side_road_ids=(f"{semantic_group_id}:road_c",),
            event_side_labels=("left",),
            normalized_event_side_labels=("left",),
            axis_polarity_inverted=False,
            positive_rcsd_present=True,
            positive_rcsd_present_reason="aggregated_forward_rcsd_present",
            primary_local_unit_id=f"{unit_id}:local",
            primary_node_id=semantic_group_id,
            required_node_id=semantic_group_id,
            required_node_source="aggregated_node_centric",
            consistency_level="A",
            support_level="primary_support",
            decision_reason="role_mapping_exact_aggregated",
            score=(1, 3, 1, 1, 1, 3, 0, -10),
            road_geometry=None,
            node_geometry=None,
            geometry=None,
        )

    ambiguous = _ambiguous_top_aggregated_rcsd_units(
        (unit("u1", "rcsd_a"), unit("u2", "rcsd_b"))
    )

    assert [item.unit_id for item in ambiguous] == ["u1", "u2"]
