from __future__ import annotations

import importlib
from collections.abc import Callable
from enum import Enum
from types import SimpleNamespace
from typing import Any

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import surface_scenario
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step23_contracts import (
    SWSDSemanticArm,
    SWSDSemanticJunction,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad


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


def _parsed_rcsd_node(node_id: str, x: float, y: float, mainnodeid: str | None = None) -> ParsedNode:
    return ParsedNode(
        feature_index=0,
        properties={"id": node_id},
        geometry=Point(x, y),
        node_id=node_id,
        mainnodeid=mainnodeid,
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )


def _parsed_rcsd_road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    coords: list[tuple[float, float]],
) -> ParsedRoad:
    return ParsedRoad(
        feature_index=0,
        properties={"id": road_id},
        geometry=LineString(coords),
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=2,
    )


def _swsd_junction(arm_rows: tuple[tuple[str, float], ...]) -> SWSDSemanticJunction:
    return SWSDSemanticJunction(
        junction_id="swsd_junction",
        member_node_ids=("swsd_center",),
        intra_junction_road_ids=(),
        semantic_arms=tuple(
            SWSDSemanticArm(
                arm_id=arm_id,
                direction="unknown",
                angle_deg=angle_deg,
                first_branch_id=f"{arm_id}_branch",
                first_road_ids=(f"{arm_id}_road",),
                inter_junction_connector_road_ids=(f"{arm_id}_road",),
                terminal_node_id=f"{arm_id}_terminal",
                terminal_kind="dead_end",
                neighbor_semantic_junction_id=None,
                continuation_through_micro_junction=False,
            )
            for arm_id, angle_deg in arm_rows
        ),
        unstable_reasons=(),
    )


def _rcsd_unit_result(*, road_ids: tuple[str, ...]) -> Any:
    local_rcsd_nodes = (
        _parsed_rcsd_node("rc0", 0.0, 0.0, "rc_main"),
        _parsed_rcsd_node("rc_e", 10.0, 0.0),
        _parsed_rcsd_node("rc_n", 0.0, 10.0),
        _parsed_rcsd_node("rc_s", 0.0, -10.0),
    )
    local_rcsd_roads = (
        _parsed_rcsd_road("rc_east", "rc0", "rc_e", [(0.0, 0.0), (10.0, 0.0)]),
        _parsed_rcsd_road("rc_north", "rc0", "rc_n", [(0.0, 0.0), (0.0, 10.0)]),
        _parsed_rcsd_road("rc_south", "rc0", "rc_s", [(0.0, 0.0), (0.0, -10.0)]),
    )
    return SimpleNamespace(
        selected_rcsdnode_ids=("rc0",),
        selected_rcsdroad_ids=road_ids,
        required_rcsd_node="rc0",
        aggregated_rcsd_unit_id="rcsd_junction:rc0",
        aggregated_rcsd_unit_ids=("rcsd_junction:rc0",),
        positive_rcsd_audit={
            "aggregated_rcsd_units": [
                {
                    "unit_id": "rcsd_junction:rc0",
                    "node_ids": ["rc0"],
                    "required_node_id": "rc0",
                    "road_ids": list(road_ids),
                }
            ]
        },
        unit_context=SimpleNamespace(
            local_context=SimpleNamespace(
                local_rcsd_nodes=local_rcsd_nodes,
                local_rcsd_roads=local_rcsd_roads,
            )
        ),
    )


def _rcsd_road_only_unit_result(
    *,
    local_rcsd_nodes: tuple[ParsedNode, ...],
    local_rcsd_roads: tuple[ParsedRoad, ...],
    road_ids: tuple[str, ...],
) -> Any:
    return SimpleNamespace(
        selected_rcsdnode_ids=(),
        selected_rcsdroad_ids=road_ids,
        first_hit_rcsdroad_ids=road_ids,
        required_rcsd_node=None,
        positive_rcsd_audit={},
        unit_context=SimpleNamespace(
            local_context=SimpleNamespace(
                local_rcsd_nodes=local_rcsd_nodes,
                local_rcsd_roads=local_rcsd_roads,
            )
        ),
    )


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


def test_rcsd_semantic_junction_pairs_all_swsd_arms() -> None:
    module = _load_alignment_module()
    result = module.build_rcsd_semantic_junction(
        unit_result=_rcsd_unit_result(road_ids=("rc_east", "rc_north", "rc_south")),
        swsd_semantic_junction=_swsd_junction(
            (
                ("arm_east", 0.0),
                ("arm_north", 90.0),
                ("arm_south", 270.0),
            )
        ),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            positive_rcsdroad_ids=("rc_east", "rc_north", "rc_south"),
            positive_rcsdnode_ids=("rc0",),
        ),
    )

    assert result is not None
    assert result.junction_id == "rcsd_junction:rc0"
    assert result.member_rcsdnode_ids == ("rc0",)
    assert [arm.arm_id for arm in result.semantic_arms] == [
        "rcsd_arm_01",
        "rcsd_arm_02",
        "rcsd_arm_03",
    ]
    assert result.paired_swsd_arm_mapping == {
        "rcsd_arm_01": "arm_east",
        "rcsd_arm_02": "arm_north",
        "rcsd_arm_03": "arm_south",
    }
    assert result.alignment_partial_missing_swsd_arm_ids == ()


def test_rcsd_semantic_junction_keeps_published_single_node_group_scope() -> None:
    module = _load_alignment_module()
    local_rcsd_nodes = (
        _parsed_rcsd_node("rc0", 0.0, 0.0),
        _parsed_rcsd_node("rc_neighbor", 10.0, 0.0),
        _parsed_rcsd_node("rc_n", 0.0, 10.0),
        _parsed_rcsd_node("rc_s", 0.0, -10.0),
    )
    local_rcsd_roads = (
        _parsed_rcsd_road(
            "rc_to_neighbor",
            "rc0",
            "rc_neighbor",
            [(0.0, 0.0), (10.0, 0.0)],
        ),
        _parsed_rcsd_road("rc_north", "rc0", "rc_n", [(0.0, 0.0), (0.0, 10.0)]),
        _parsed_rcsd_road("rc_south", "rc0", "rc_s", [(0.0, 0.0), (0.0, -10.0)]),
    )
    unit_result = SimpleNamespace(
        selected_rcsdnode_ids=("rc0",),
        selected_rcsdroad_ids=("rc_to_neighbor", "rc_north", "rc_south"),
        required_rcsd_node="rc0",
        aggregated_rcsd_unit_id="rcsd_junction:rc0+neighbor",
        aggregated_rcsd_unit_ids=("rcsd_junction:rc0+neighbor",),
        positive_rcsd_audit={
            "published_rcsdnode_ids": ["rc0"],
            "published_member_unit_ids": ["event_unit_01:node:rc0"],
            "selected_unit_role_assignments": [
                {"road_id": "rc_to_neighbor", "role": "exiting"},
                {"road_id": "rc_north", "role": "exiting"},
                {"road_id": "rc_south", "role": "entering"},
            ],
            "aggregated_rcsd_units": [
                {
                    "unit_id": "rcsd_junction:rc0+neighbor",
                    "node_ids": ["rc0", "rc_neighbor"],
                    "required_node_id": "rc0",
                    "road_ids": ["rc_to_neighbor", "rc_north", "rc_south"],
                }
            ],
        },
        unit_context=SimpleNamespace(
            local_context=SimpleNamespace(
                local_rcsd_nodes=local_rcsd_nodes,
                local_rcsd_roads=local_rcsd_roads,
            )
        ),
    )

    result = module.build_rcsd_semantic_junction(
        unit_result=unit_result,
        swsd_semantic_junction=_swsd_junction(
            (
                ("arm_east", 0.0),
                ("arm_north", 90.0),
                ("arm_south", 270.0),
            )
        ),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            positive_rcsdroad_ids=("rc_to_neighbor", "rc_north", "rc_south"),
            positive_rcsdnode_ids=("rc0",),
        ),
    )

    assert result is not None
    assert result.member_rcsdnode_ids == ("rc0",)
    assert result.intra_junction_rcsdroad_ids == ()
    assert [arm.first_rcsdroad_ids for arm in result.semantic_arms] == [
        ("rc_to_neighbor",),
        ("rc_north",),
        ("rc_south",),
    ]
    assert result.paired_swsd_arm_mapping == {
        "rcsd_arm_01": "arm_east",
        "rcsd_arm_02": "arm_north",
        "rcsd_arm_03": "arm_south",
    }
    assert result.alignment_partial_missing_swsd_arm_ids == ()


def test_rcsd_junction_partial_alignment_records_missing_swsd_arm() -> None:
    module = _load_alignment_module()
    result = module.build_rcsd_semantic_junction(
        unit_result=_rcsd_unit_result(road_ids=("rc_east", "rc_north")),
        swsd_semantic_junction=_swsd_junction(
            (
                ("arm_east", 0.0),
                ("arm_north", 90.0),
                ("arm_south", 270.0),
            )
        ),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_JUNCTION_PARTIAL,
            positive_rcsdroad_ids=("rc_east", "rc_north"),
            positive_rcsdnode_ids=("rc0",),
        ),
    )

    assert result is not None
    assert result.paired_swsd_arm_mapping == {
        "rcsd_arm_01": "arm_east",
        "rcsd_arm_02": "arm_north",
    }
    assert result.alignment_partial_missing_swsd_arm_ids == ("arm_south",)


def test_rcsd_semantic_junction_records_ambiguous_swsd_arm_pairing() -> None:
    module = _load_alignment_module()
    result = module.build_rcsd_semantic_junction(
        unit_result=_rcsd_unit_result(road_ids=("rc_east",)),
        swsd_semantic_junction=_swsd_junction(
            (
                ("arm_east_a", 5.0),
                ("arm_east_b", 10.0),
            )
        ),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            positive_rcsdroad_ids=("rc_east",),
            positive_rcsdnode_ids=("rc0",),
        ),
    )

    assert result is not None
    assert result.paired_swsd_arm_mapping == {"rcsd_arm_01": None}
    assert result.pairing_ambiguous_arm_ids == ("rcsd_arm_01",)
    assert result.to_doc()["paired_swsd_arm_mapping"] == {"rcsd_arm_01": None}


def test_rcsd_semantic_junction_stops_connector_at_degree3_boundary() -> None:
    module = _load_alignment_module()
    local_rcsd_nodes = (
        _parsed_rcsd_node("rc0", 0.0, 0.0, "rc_main"),
        _parsed_rcsd_node("mid_a", 10.0, 0.0, "mid_group"),
        _parsed_rcsd_node("mid_b", 10.0, 10.0, "mid_group"),
        _parsed_rcsd_node("after", 20.0, 0.0),
        _parsed_rcsd_node("side", 20.0, 10.0),
        _parsed_rcsd_node("north", 0.0, 10.0),
        _parsed_rcsd_node("south", 0.0, -10.0),
    )
    local_rcsd_roads = (
        _parsed_rcsd_road("rc_main", "rc0", "mid_a", [(0.0, 0.0), (10.0, 0.0)]),
        _parsed_rcsd_road("rc_after", "mid_a", "after", [(10.0, 0.0), (20.0, 0.0)]),
        _parsed_rcsd_road("rc_side", "mid_b", "side", [(10.0, 10.0), (20.0, 10.0)]),
        _parsed_rcsd_road("rc_north", "rc0", "north", [(0.0, 0.0), (0.0, 10.0)]),
        _parsed_rcsd_road("rc_south", "rc0", "south", [(0.0, 0.0), (0.0, -10.0)]),
    )
    unit_result = SimpleNamespace(
        selected_rcsdnode_ids=("rc0",),
        selected_rcsdroad_ids=("rc_main", "rc_north", "rc_south"),
        required_rcsd_node="rc0",
        aggregated_rcsd_unit_id="rcsd_junction:rc0",
        aggregated_rcsd_unit_ids=("rcsd_junction:rc0",),
        positive_rcsd_audit={
            "aggregated_rcsd_units": [
                {
                    "unit_id": "rcsd_junction:rc0",
                    "node_ids": ["rc0"],
                    "required_node_id": "rc0",
                    "road_ids": ["rc_main", "rc_north", "rc_south"],
                }
            ]
        },
        unit_context=SimpleNamespace(
            local_context=SimpleNamespace(
                local_rcsd_nodes=local_rcsd_nodes,
                local_rcsd_roads=local_rcsd_roads,
            )
        ),
    )

    result = module.build_rcsd_semantic_junction(
        unit_result=unit_result,
        swsd_semantic_junction=_swsd_junction((("arm_east", 0.0),)),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
            positive_rcsdroad_ids=("rc_main", "rc_north", "rc_south"),
            positive_rcsdnode_ids=("rc0",),
        ),
    )

    assert result is not None
    main_arm = next(arm for arm in result.semantic_arms if arm.first_rcsdroad_ids == ("rc_main",))
    assert main_arm.inter_junction_connector_rcsdroad_ids == ("rc_main",)
    assert main_arm.terminal_rcsdnode_id == "mid_a"
    assert main_arm.terminal_kind == "semantic_neighbor"
    assert main_arm.neighbor_rcsd_junction_id == "mid_group"


def test_rcsdroad_only_chain_records_closed_between_two_rcsd_junctions_and_direction_match() -> None:
    module = _load_alignment_module()
    nodes = (
        _parsed_rcsd_node("j1", 0.0, 0.0),
        _parsed_rcsd_node("mid", 10.0, 0.0),
        _parsed_rcsd_node("j2", 20.0, 0.0),
        _parsed_rcsd_node("j1_s1", 0.0, 10.0),
        _parsed_rcsd_node("j1_s2", 0.0, -10.0),
        _parsed_rcsd_node("j2_s1", 20.0, 10.0),
        _parsed_rcsd_node("j2_s2", 20.0, -10.0),
    )
    roads = (
        _parsed_rcsd_road("chain_a", "j1", "mid", [(0.0, 0.0), (10.0, 0.0)]),
        _parsed_rcsd_road("chain_b", "mid", "j2", [(10.0, 0.0), (20.0, 0.0)]),
        _parsed_rcsd_road("j1_spur_1", "j1", "j1_s1", [(0.0, 0.0), (0.0, 10.0)]),
        _parsed_rcsd_road("j1_spur_2", "j1", "j1_s2", [(0.0, 0.0), (0.0, -10.0)]),
        _parsed_rcsd_road("j2_spur_1", "j2", "j2_s1", [(20.0, 0.0), (20.0, 10.0)]),
        _parsed_rcsd_road("j2_spur_2", "j2", "j2_s2", [(20.0, 0.0), (20.0, -10.0)]),
    )

    result = module.build_rcsdroad_only_chain(
        unit_result=_rcsd_road_only_unit_result(
            local_rcsd_nodes=nodes,
            local_rcsd_roads=roads,
            road_ids=("chain_a", "chain_b"),
        ),
        swsd_semantic_junction=_swsd_junction((("arm_east", 0.0),)),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_ROAD_ONLY,
            positive_rcsdroad_ids=("chain_a", "chain_b"),
        ),
    )

    assert result is not None
    assert result.chain_road_ids == ("chain_a", "chain_b")
    assert result.chain_endpoint_node_ids == ("j1", "j2")
    assert result.chain_endpoint_kinds == (
        "rcsd_semantic_junction_member",
        "rcsd_semantic_junction_member",
    )
    assert result.closure_status == "closed_between_two_rcsd_junctions"
    assert result.swsd_direction_consistent is True
    assert result.swsd_direction_evidence["matched_swsd_arm_id"] == "arm_east"
    assert result.selection_uniqueness_proof["selected_chain_component_count"] == 1
    assert result.selection_uniqueness_proof["angle_tolerance_deg"] == module.BRANCH_MATCH_TOLERANCE_DEG


def test_rcsdroad_only_chain_endpoint_uses_mainnode_group_boundary_degree() -> None:
    module = _load_alignment_module()
    nodes = (
        _parsed_rcsd_node("j1_a", 0.0, 0.0, "j1"),
        _parsed_rcsd_node("j1_b", 0.0, 10.0, "j1"),
        _parsed_rcsd_node("j1_exit", -10.0, 0.0),
        _parsed_rcsd_node("j1_side", -10.0, 10.0),
        _parsed_rcsd_node("j2_a", 20.0, 0.0, "j2"),
        _parsed_rcsd_node("j2_b", 20.0, 10.0, "j2"),
        _parsed_rcsd_node("j2_exit", 30.0, 0.0),
        _parsed_rcsd_node("j2_side", 30.0, 10.0),
    )
    roads = (
        _parsed_rcsd_road("chain", "j1_a", "j2_a", [(0.0, 0.0), (20.0, 0.0)]),
        _parsed_rcsd_road("j1_exit_road", "j1_a", "j1_exit", [(0.0, 0.0), (-10.0, 0.0)]),
        _parsed_rcsd_road("j1_side_road", "j1_b", "j1_side", [(0.0, 10.0), (-10.0, 10.0)]),
        _parsed_rcsd_road("j2_exit_road", "j2_a", "j2_exit", [(20.0, 0.0), (30.0, 0.0)]),
        _parsed_rcsd_road("j2_side_road", "j2_b", "j2_side", [(20.0, 10.0), (30.0, 10.0)]),
    )

    result = module.build_rcsdroad_only_chain(
        unit_result=_rcsd_road_only_unit_result(
            local_rcsd_nodes=nodes,
            local_rcsd_roads=roads,
            road_ids=("chain",),
        ),
        swsd_semantic_junction=_swsd_junction((("arm_east", 0.0),)),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_ROAD_ONLY,
            positive_rcsdroad_ids=("chain",),
        ),
    )

    assert result is not None
    assert result.chain_endpoint_node_ids == ("j1_a", "j2_a")
    assert result.chain_endpoint_kinds == (
        "rcsd_semantic_junction_member",
        "rcsd_semantic_junction_member",
    )
    assert result.closure_status == "closed_between_two_rcsd_junctions"


def test_rcsdroad_only_chain_records_dead_end_and_patch_boundary() -> None:
    module = _load_alignment_module()
    dead_nodes = (
        _parsed_rcsd_node("dead_a", 0.0, 0.0),
        _parsed_rcsd_node("dead_b", 10.0, 0.0),
        _parsed_rcsd_node("dead_s1", 0.0, 10.0),
        _parsed_rcsd_node("dead_s2", 0.0, -10.0),
    )
    dead_roads = (
        _parsed_rcsd_road("dead_chain", "dead_a", "dead_b", [(0.0, 0.0), (10.0, 0.0)]),
        _parsed_rcsd_road("dead_spur_1", "dead_a", "dead_s1", [(0.0, 0.0), (0.0, 10.0)]),
        _parsed_rcsd_road("dead_spur_2", "dead_a", "dead_s2", [(0.0, 0.0), (0.0, -10.0)]),
    )
    dead_chain = module.build_rcsdroad_only_chain(
        unit_result=_rcsd_road_only_unit_result(
            local_rcsd_nodes=dead_nodes,
            local_rcsd_roads=dead_roads,
            road_ids=("dead_chain",),
        ),
        swsd_semantic_junction=_swsd_junction((("arm_east", 0.0),)),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_ROAD_ONLY,
            positive_rcsdroad_ids=("dead_chain",),
        ),
    )

    assert dead_chain is not None
    assert dead_chain.closure_status == "open_dead_end"

    patch_nodes = (
        _parsed_rcsd_node("patch_a", 0.0, 0.0),
        _parsed_rcsd_node("patch_s1", 0.0, 10.0),
        _parsed_rcsd_node("patch_s2", 0.0, -10.0),
    )
    patch_roads = (
        _parsed_rcsd_road("patch_chain", "patch_a", "patch_missing", [(0.0, 0.0), (10.0, 0.0)]),
        _parsed_rcsd_road("patch_spur_1", "patch_a", "patch_s1", [(0.0, 0.0), (0.0, 10.0)]),
        _parsed_rcsd_road("patch_spur_2", "patch_a", "patch_s2", [(0.0, 0.0), (0.0, -10.0)]),
    )
    patch_chain = module.build_rcsdroad_only_chain(
        unit_result=_rcsd_road_only_unit_result(
            local_rcsd_nodes=patch_nodes,
            local_rcsd_roads=patch_roads,
            road_ids=("patch_chain",),
        ),
        swsd_semantic_junction=_swsd_junction((("arm_east", 0.0),)),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_ROAD_ONLY,
            positive_rcsdroad_ids=("patch_chain",),
        ),
    )

    assert patch_chain is not None
    assert patch_chain.closure_status == "open_patch_boundary"


def test_rcsdroad_only_chain_records_direction_inconsistency() -> None:
    module = _load_alignment_module()
    nodes = (
        _parsed_rcsd_node("d_a", 0.0, 0.0),
        _parsed_rcsd_node("d_b", 10.0, 0.0),
    )
    roads = (_parsed_rcsd_road("east_chain", "d_a", "d_b", [(0.0, 0.0), (10.0, 0.0)]),)
    result = module.build_rcsdroad_only_chain(
        unit_result=_rcsd_road_only_unit_result(
            local_rcsd_nodes=nodes,
            local_rcsd_roads=roads,
            road_ids=("east_chain",),
        ),
        swsd_semantic_junction=_swsd_junction((("arm_north", 90.0),)),
        rcsd_alignment_result=module.RCSDAlignmentResult(
            scope=module.RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
            scope_id="event_unit_01",
            rcsd_alignment_type=module.RCSD_ALIGNMENT_ROAD_ONLY,
            positive_rcsdroad_ids=("east_chain",),
        ),
    )

    assert result is not None
    assert result.swsd_direction_consistent is False
    assert result.swsd_direction_evidence["angle_gap_deg"] == 90.0
    assert result.swsd_direction_evidence["consistency_decision_reason"] == "exceeds_branch_match_tolerance"


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
