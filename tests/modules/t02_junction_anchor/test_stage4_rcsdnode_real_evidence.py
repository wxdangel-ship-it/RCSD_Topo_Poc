from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_rcsdnode_real_evidence import (
    REAL_EVIDENCE_SOURCE_CORRIDOR,
    REAL_EVIDENCE_SOURCE_EXACT_COVER,
    apply_selected_rcsdroad_real_evidence_tolerance,
    suppress_weak_evidence_risks_for_real_rcsdnode_evidence,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedNode,
    ParsedRoad,
)


def _node(node_id: str, point: Point) -> ParsedNode:
    return ParsedNode(
        feature_index=0,
        properties={"id": node_id, "mainnodeid": "0"},
        geometry=point,
        node_id=node_id,
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )


def _road(road_id: str, snodeid: str, enodeid: str, line: LineString) -> ParsedRoad:
    return ParsedRoad(
        feature_index=0,
        properties={"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": 2},
        geometry=line,
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=2,
    )


def test_selected_rcsdroad_endpoint_exact_cover_overrides_out_of_window() -> None:
    primary_node = _node("rc_node", Point(30.0, 0.0))
    selected_rcsdroad = _road(
        "rc_road",
        "rc_node",
        "rc_other",
        LineString([(30.0, 0.0), (45.0, 0.0)]),
    )

    result = apply_selected_rcsdroad_real_evidence_tolerance(
        polygon_geometry=box(29.0, -1.0, 31.0, 1.0),
        primary_main_rc_node=primary_node,
        primary_rcsdnode_tolerance={
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "out_of_window",
            "rcsdnode_offset_m": 26.0,
            "rcsdnode_lateral_dist_m": 0.1,
            "reason": "rcsdnode_main_out_of_window",
            "extended_polygon_geometry": box(29.0, -1.0, 31.0, 1.0),
            "covered": False,
        },
        selected_rcsd_roads=[selected_rcsdroad],
        drivezone_union=box(0.0, -10.0, 60.0, 10.0),
        rcsdnode_seed_mode="inferred_local_trunk_window",
    )

    assert result["reason"] is None
    assert result["covered"] is True
    assert result["rcsdnode_coverage_mode"] == "exact_cover"
    assert result["rcsdnode_real_evidence_source"] == REAL_EVIDENCE_SOURCE_EXACT_COVER


def test_selected_rcsdroad_endpoint_corridor_can_extend_off_trunk_polygon() -> None:
    primary_node = _node("rc_node", Point(10.0, 10.0))
    selected_rcsdroad = _road(
        "rc_road",
        "rc_node",
        "rc_other",
        LineString([(10.0, 10.0), (10.0, -10.0)]),
    )

    result = apply_selected_rcsdroad_real_evidence_tolerance(
        polygon_geometry=box(8.0, -2.0, 12.0, 2.0),
        primary_main_rc_node=primary_node,
        primary_rcsdnode_tolerance={
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "off_trunk",
            "rcsdnode_offset_m": 0.0,
            "rcsdnode_lateral_dist_m": 10.0,
            "reason": "rcsdnode_main_off_trunk",
            "extended_polygon_geometry": box(8.0, -2.0, 12.0, 2.0),
            "covered": False,
        },
        selected_rcsd_roads=[selected_rcsdroad],
        drivezone_union=box(0.0, -20.0, 20.0, 20.0),
        rcsdnode_seed_mode="inferred_local_trunk_window",
    )

    assert result["reason"] is None
    assert result["covered"] is True
    assert result["rcsdnode_tolerance_applied"] is True
    assert result["rcsdnode_coverage_mode"] == "selected_road_corridor_tolerated"
    assert result["rcsdnode_real_evidence_source"] == REAL_EVIDENCE_SOURCE_CORRIDOR
    assert result["extended_polygon_geometry"].covers(primary_node.geometry)


def test_selected_rcsdroad_endpoint_corridor_does_not_extend_out_of_window_polygon() -> None:
    primary_node = _node("rc_node", Point(10.0, 10.0))
    selected_rcsdroad = _road(
        "rc_road",
        "rc_node",
        "rc_other",
        LineString([(10.0, 10.0), (10.0, -10.0)]),
    )

    result = apply_selected_rcsdroad_real_evidence_tolerance(
        polygon_geometry=box(8.0, -2.0, 12.0, 2.0),
        primary_main_rc_node=primary_node,
        primary_rcsdnode_tolerance={
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "out_of_window",
            "rcsdnode_offset_m": 28.0,
            "rcsdnode_lateral_dist_m": 1.5,
            "reason": "rcsdnode_main_out_of_window",
            "extended_polygon_geometry": box(8.0, -2.0, 12.0, 2.0),
            "covered": False,
        },
        selected_rcsd_roads=[selected_rcsdroad],
        drivezone_union=box(0.0, -20.0, 20.0, 20.0),
        rcsdnode_seed_mode="inferred_local_trunk_window",
    )

    assert result["reason"] == "rcsdnode_main_out_of_window"
    assert result["covered"] is False
    assert "rcsdnode_real_evidence_source" not in result


def test_selected_rcsdroad_real_evidence_requires_incident_endpoint() -> None:
    primary_node = _node("rc_node", Point(10.0, 10.0))
    unrelated_rcsdroad = _road(
        "rc_road",
        "other_a",
        "other_b",
        LineString([(10.0, 10.0), (10.0, -10.0)]),
    )

    result = apply_selected_rcsdroad_real_evidence_tolerance(
        polygon_geometry=box(8.0, -2.0, 12.0, 2.0),
        primary_main_rc_node=primary_node,
        primary_rcsdnode_tolerance={
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "off_trunk",
            "reason": "rcsdnode_main_off_trunk",
            "extended_polygon_geometry": box(8.0, -2.0, 12.0, 2.0),
            "covered": False,
        },
        selected_rcsd_roads=[unrelated_rcsdroad],
        drivezone_union=box(0.0, -20.0, 20.0, 20.0),
        rcsdnode_seed_mode="inferred_local_trunk_window",
    )

    assert result["reason"] == "rcsdnode_main_off_trunk"
    assert result["covered"] is False
    assert "rcsdnode_real_evidence_source" not in result


def test_real_rcsdnode_evidence_suppresses_only_weak_step4_risks() -> None:
    result = suppress_weak_evidence_risks_for_real_rcsdnode_evidence(
        risk_signals=("reverse_tip_used", "fallback_to_weak_evidence", "other_review"),
        primary_rcsdnode_tolerance={
            "reason": None,
            "rcsdnode_coverage_mode": "exact_cover",
            "rcsdnode_real_evidence_source": REAL_EVIDENCE_SOURCE_EXACT_COVER,
        },
        rcsdnode_seed_mode="inferred_local_trunk_window",
    )

    assert result == ("other_review",)


def test_weak_step4_risks_remain_without_real_rcsdnode_evidence() -> None:
    result = suppress_weak_evidence_risks_for_real_rcsdnode_evidence(
        risk_signals=("reverse_tip_used", "fallback_to_weak_evidence"),
        primary_rcsdnode_tolerance={
            "reason": "rcsdnode_main_out_of_window",
            "rcsdnode_coverage_mode": "out_of_window",
        },
        rcsdnode_seed_mode="inferred_local_trunk_window",
    )

    assert result == ("reverse_tip_used", "fallback_to_weak_evidence")


def test_direct_mainnodeid_group_does_not_apply_inferred_real_evidence_tolerance() -> None:
    primary_node = _node("rc_node", Point(30.0, 0.0))
    selected_rcsdroad = _road(
        "rc_road",
        "rc_node",
        "rc_other",
        LineString([(30.0, 0.0), (45.0, 0.0)]),
    )

    result = apply_selected_rcsdroad_real_evidence_tolerance(
        polygon_geometry=box(29.0, -1.0, 31.0, 1.0),
        primary_main_rc_node=primary_node,
        primary_rcsdnode_tolerance={
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "out_of_window",
            "reason": "rcsdnode_main_out_of_window",
            "extended_polygon_geometry": box(29.0, -1.0, 31.0, 1.0),
            "covered": False,
        },
        selected_rcsd_roads=[selected_rcsdroad],
        drivezone_union=box(0.0, -10.0, 60.0, 10.0),
        rcsdnode_seed_mode="direct_mainnodeid_group",
    )

    assert result["reason"] == "rcsdnode_main_out_of_window"
    assert result["covered"] is False
    assert "rcsdnode_real_evidence_source" not in result


def test_direct_mainnodeid_group_keeps_weak_step4_risks() -> None:
    result = suppress_weak_evidence_risks_for_real_rcsdnode_evidence(
        risk_signals=("reverse_tip_used", "fallback_to_weak_evidence"),
        primary_rcsdnode_tolerance={
            "reason": None,
            "rcsdnode_coverage_mode": "exact_cover",
            "rcsdnode_real_evidence_source": REAL_EVIDENCE_SOURCE_EXACT_COVER,
        },
        rcsdnode_seed_mode="direct_mainnodeid_group",
    )

    assert result == ("reverse_tip_used", "fallback_to_weak_evidence")
