from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
)
from rcsd_topo_poc.modules.t01_data_preprocess.segment_shape_control import apply_segment_shape_control
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import get_road_segmentid


def _node(node_id: str, *, kind_2: int = 4, grade_2: int = 1, closed_con: int = 2) -> NodeFeatureRecord:
    return NodeFeatureRecord(
        node_id=node_id,
        mainnodeid=node_id,
        semantic_node_id=node_id,
        grade=grade_2,
        kind=kind_2,
        properties={
            "id": node_id,
            "working_mainnodeid": node_id,
            "grade_2": grade_2,
            "kind_2": kind_2,
            "closed_con": closed_con,
        },
        geometry=Point(0, 0),
    )


def _road(
    road_id: str,
    a_node_id: str,
    b_node_id: str,
    coords: list[tuple[float, float]],
    *,
    segmentid: str | None = "A_B",
    kind: int = 600,
) -> RoadFeatureRecord:
    properties = {
        "id": road_id,
        "snodeid": a_node_id,
        "enodeid": b_node_id,
        "direction": 0,
        "road_kind": 2,
        "kind": kind,
        "sgrade": "0-0双",
        "segmentid": segmentid,
    }
    return RoadFeatureRecord(
        road_id=road_id,
        snodeid=a_node_id,
        enodeid=b_node_id,
        direction=0,
        formway=None,
        road_kind=2,
        properties=properties,
        geometry=LineString(coords),
    )


def _run_shape_control(roads: list[RoadFeatureRecord]) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    nodes = [_node("A"), _node("J"), _node("B"), _node("C"), _node("D")]
    node_properties_map = {node.node_id: dict(node.properties) for node in nodes}
    road_properties_map = {road.road_id: dict(road.properties) for road in roads}
    mainnode_groups = {
        node.node_id: MainnodeGroup(
            mainnode_id=node.node_id,
            representative_node_id=node.node_id,
            member_node_ids=(node.node_id,),
            grade_old=node.grade,
            kind_old=node.kind,
        )
        for node in nodes
    }
    physical_to_semantic = {node.node_id: node.node_id for node in nodes}
    used_segmentids = {
        segmentid
        for props in road_properties_map.values()
        for segmentid in (get_road_segmentid(props),)
        if segmentid is not None
    }
    summary = apply_segment_shape_control(
        nodes=nodes,
        roads=roads,
        node_properties_map=node_properties_map,
        road_properties_map=road_properties_map,
        mainnode_groups=mainnode_groups,
        physical_to_semantic=physical_to_semantic,
        used_segmentids=used_segmentids,
    )
    return summary, road_properties_map


def test_shape_control_splits_dual_segment_at_internal_turn_junction() -> None:
    roads = [
        _road("r1", "A", "J", [(0, 0), (1, 0)]),
        _road("r2", "J", "B", [(1, 0), (1, 1)]),
        _road("r3", "J", "C", [(1, 0), (2, 0)], segmentid=None),
    ]

    summary, road_properties_map = _run_shape_control(roads)

    assert summary["split_segment_count"] == 1
    assert summary["split_road_count"] == 2
    assert get_road_segmentid(road_properties_map["r1"]) == "A_J"
    assert get_road_segmentid(road_properties_map["r2"]) == "B_J"
    assert road_properties_map["r1"]["pre_shape_control_segmentid"] == "A_B"
    assert road_properties_map["r1"]["shape_control_split_reason"] == "internal_turn_angle_conflict"


def test_shape_control_keeps_same_level_straight_dual_segment() -> None:
    roads = [
        _road("r1", "A", "J", [(0, 0), (1, 0)]),
        _road("r2", "J", "B", [(1, 0), (2, 0)]),
        _road("r3", "J", "C", [(1, 0), (1, 1)], segmentid=None),
    ]

    summary, road_properties_map = _run_shape_control(roads)

    assert summary["split_segment_count"] == 0
    assert get_road_segmentid(road_properties_map["r1"]) == "A_B"
    assert get_road_segmentid(road_properties_map["r2"]) == "A_B"


def test_shape_control_splits_dual_segment_at_internal_kind_level_change() -> None:
    roads = [
        _road("r1", "A", "J", [(0, 0), (1, 0)], kind=800),
        _road("r2", "J", "B", [(1, 0), (2, 0)], kind=600),
        _road("r3", "J", "C", [(1, 0), (1, 1)], segmentid=None, kind=600),
    ]

    summary, road_properties_map = _run_shape_control(roads)

    assert summary["split_segment_count"] == 1
    assert get_road_segmentid(road_properties_map["r1"]) == "A_J"
    assert get_road_segmentid(road_properties_map["r2"]) == "B_J"
    assert road_properties_map["r2"]["shape_control_split_reason"] == "internal_road_kind_level_conflict"


def test_shape_control_keeps_multi_road_segment_with_only_kind_level_change() -> None:
    roads = [
        _road("r1", "A", "D", [(0, 0), (1, 0)], kind=800),
        _road("r2", "D", "J", [(1, 0), (2, 0)], kind=800),
        _road("r3", "J", "B", [(2, 0), (3, 0)], kind=600),
        _road("r4", "J", "C", [(2, 0), (2, 1)], segmentid=None, kind=600),
    ]

    summary, road_properties_map = _run_shape_control(roads)

    assert summary["split_segment_count"] == 0
    assert get_road_segmentid(road_properties_map["r1"]) == "A_B"
    assert get_road_segmentid(road_properties_map["r2"]) == "A_B"
    assert get_road_segmentid(road_properties_map["r3"]) == "A_B"
