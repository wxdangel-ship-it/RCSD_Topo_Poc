from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t01_data_preprocess.refresh_node_retyping import (
    evaluate_mainnode_bootstrap_retype,
    evaluate_mainnode_refresh_retype,
    summarize_mainnode_retype_topology,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import RoadFeatureRecord


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    *,
    direction: int = 0,
    formway: int = 0,
) -> RoadFeatureRecord:
    return RoadFeatureRecord(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=direction,
        formway=formway,
        road_kind=0,
        properties={
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
        },
        geometry=LineString([(0.0, 0.0), (1.0, 1.0)]),
    )


def _node_props(grade_2: int, kind_2: int) -> dict[str, int]:
    return {"grade_2": grade_2, "kind_2": kind_2}


def test_refresh_retypes_single_side_family_to_grade2_kind2048() -> None:
    associated_roads = [
        _road("seg", "1019769", "1030081"),
        _road("left", "997356", "1019769", direction=2),
        _road("right", "1019769", "1035968", direction=2),
    ]
    topology = summarize_mainnode_retype_topology(
        member_node_ids=("1019769",),
        associated_roads=associated_roads,
        road_properties_map={
            "seg": {"segmentid": "old_pair"},
            "left": {},
            "right": {},
        },
        physical_to_semantic={
            "1019769": "1019769",
            "1030081": "1030081",
            "997356": "997356",
            "1035968": "1035968",
        },
        right_turn_formway_bit=7,
    )

    decision = evaluate_mainnode_refresh_retype(
        current_grade_2=1,
        current_kind_2=4,
        topology=topology,
    )

    assert topology.total_neighbor_family_count == 3
    assert topology.segment_neighbor_family_count == 1
    assert topology.residual_neighbor_family_count == 2
    assert topology.simple_residual_neighbor_family_count == 2
    assert decision is not None
    assert decision.grade_2 == 2
    assert decision.kind_2 == 2048


def test_refresh_retypes_mixed_side_family_to_grade2_kind4() -> None:
    associated_roads = [
        _road("seg", "1019769", "1030081"),
        _road("mix_a1", "side_a_left", "1019769", direction=2),
        _road("mix_a2", "1019769", "side_a_right", direction=2),
        _road("side_b", "1019769", "1035968", direction=2),
    ]
    topology = summarize_mainnode_retype_topology(
        member_node_ids=("1019769",),
        associated_roads=associated_roads,
        road_properties_map={
            "seg": {"segmentid": "old_pair"},
            "mix_a1": {},
            "mix_a2": {},
            "side_b": {},
        },
        physical_to_semantic={
            "1019769": "1019769",
            "1030081": "1030081",
            "side_a_left": "side_a",
            "side_a_right": "side_a",
            "1035968": "side_b",
        },
        right_turn_formway_bit=7,
    )

    decision = evaluate_mainnode_refresh_retype(
        current_grade_2=1,
        current_kind_2=4,
        topology=topology,
    )

    assert topology.total_neighbor_family_count == 3
    assert topology.segment_neighbor_family_count == 1
    assert topology.residual_neighbor_family_count == 2
    assert topology.simple_residual_neighbor_family_count == 1
    assert decision is not None
    assert decision.grade_2 == 2
    assert decision.kind_2 == 4


def test_refresh_does_not_retype_multibranch_intersection() -> None:
    associated_roads = [
        _road("seg", "39546395", "1026960"),
        _road("a", "1020116", "39546395", direction=2),
        _road("b", "1001055", "39546395", direction=2),
        _road("c", "39546395", "1029571", direction=2),
        _road("d", "39546395", "994177", direction=2),
        _road("e", "39546395", "26219678", direction=2),
    ]
    topology = summarize_mainnode_retype_topology(
        member_node_ids=("39546395",),
        associated_roads=associated_roads,
        road_properties_map={
            "seg": {"segmentid": "old_pair"},
            "a": {},
            "b": {},
            "c": {},
            "d": {},
            "e": {},
        },
        physical_to_semantic={
            "39546395": "39546395",
            "1026960": "1026960",
            "1020116": "1020116",
            "1001055": "1001055",
            "1029571": "1029571",
            "994177": "994177",
            "26219678": "26219678",
        },
        right_turn_formway_bit=7,
    )

    decision = evaluate_mainnode_refresh_retype(
        current_grade_2=1,
        current_kind_2=4,
        topology=topology,
    )

    assert topology.total_neighbor_family_count == 6
    assert decision is None


def test_bootstrap_retypes_strict_t_mistag_to_grade2_kind2048() -> None:
    associated_roads = [
        _road("main_in", "1030077", "1019769", direction=2),
        _road("main_out", "1019769", "1030081", direction=2),
        _road("side_in", "997356", "1019769", direction=2),
        _road("side_out", "1019769", "1035968", direction=2),
    ]
    topology = summarize_mainnode_retype_topology(
        member_node_ids=("1019769", "1030080"),
        associated_roads=associated_roads,
        road_properties_map={road.road_id: {} for road in associated_roads},
        physical_to_semantic={
            "1019769": "1019769",
            "1030080": "1019769",
            "1030077": "1030081",
            "1030081": "1030081",
            "997356": "997356",
            "1035968": "1035968",
        },
        right_turn_formway_bit=7,
        node_properties_map={
            "1019769": _node_props(1, 4),
            "1030080": _node_props(0, 0),
            "1030077": _node_props(0, 0),
            "1030081": _node_props(1, 4),
            "997356": _node_props(1, 4),
            "1035968": _node_props(3, 2048),
        },
    )

    decision = evaluate_mainnode_bootstrap_retype(
        current_grade_2=1,
        current_kind_2=4,
        topology=topology,
    )

    assert topology.total_neighbor_family_count == 3
    assert topology.segment_neighbor_family_count == 0
    assert topology.residual_neighbor_family_count == 3
    assert decision is not None
    assert decision.grade_2 == 2
    assert decision.kind_2 == 2048


def test_bootstrap_does_not_retype_without_adjacent_kind2048_family() -> None:
    associated_roads = [
        _road("through", "768595", "509144398", direction=0),
        _road("side_in", "763111", "767768", direction=2),
        _road("side_out", "768595", "787129", direction=2),
    ]
    topology = summarize_mainnode_retype_topology(
        member_node_ids=("767768", "768595"),
        associated_roads=associated_roads,
        road_properties_map={road.road_id: {} for road in associated_roads},
        physical_to_semantic={
            "767768": "768595",
            "768595": "768595",
            "509144398": "509144398",
            "763111": "763111",
            "787129": "787129",
        },
        right_turn_formway_bit=7,
        node_properties_map={
            "767768": _node_props(0, 0),
            "768595": _node_props(1, 4),
            "509144398": _node_props(1, 4),
            "763111": _node_props(1, 4),
            "787129": _node_props(2, 4),
        },
    )

    decision = evaluate_mainnode_bootstrap_retype(
        current_grade_2=1,
        current_kind_2=4,
        topology=topology,
    )

    assert topology.total_neighbor_family_count == 3
    assert decision is None


def test_bootstrap_does_not_retype_multibranch_intersection() -> None:
    associated_roads = [
        _road("a", "1020116", "39546395", direction=2),
        _road("b", "1001055", "39546395", direction=2),
        _road("c", "39546395", "1029571", direction=2),
        _road("d", "39546395", "994177", direction=2),
        _road("e", "39546395", "26219678", direction=2),
    ]
    topology = summarize_mainnode_retype_topology(
        member_node_ids=("1019751", "1019752", "39546395"),
        associated_roads=associated_roads,
        road_properties_map={road.road_id: {} for road in associated_roads},
        physical_to_semantic={
            "1019751": "39546395",
            "1019752": "39546395",
            "39546395": "39546395",
            "1020116": "1020116",
            "1001055": "1001055",
            "1029571": "1029571",
            "994177": "994177",
            "26219678": "26219678",
        },
        right_turn_formway_bit=7,
        node_properties_map={
            "1019751": _node_props(0, 0),
            "1019752": _node_props(0, 0),
            "39546395": _node_props(1, 4),
            "1020116": _node_props(3, 1),
            "1001055": _node_props(2, 8),
            "1029571": _node_props(3, 4),
            "994177": _node_props(2, 8),
            "26219678": _node_props(2, 2048),
        },
    )

    decision = evaluate_mainnode_bootstrap_retype(
        current_grade_2=1,
        current_kind_2=4,
        topology=topology,
    )

    assert topology.total_neighbor_family_count == 5
    assert decision is None
