from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step3_shadow_frontier import (
    Stage3Step3ShadowFrontierConfig,
    build_stage3_step3_shadow_frontier,
)


def _branch(**kwargs: object) -> SimpleNamespace:
    defaults = {
        "branch_id": "road_1",
        "angle_deg": 0.0,
        "branch_type": "sidearm",
        "is_main_direction": False,
        "selected_for_polygon": True,
        "selected_rc_group": None,
        "road_ids": ("road_1",),
        "road_support_m": 0.0,
        "drivezone_support_m": 110.0,
        "rc_support_m": 0.0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _road(road_id: str, coords: list[tuple[float, float]]) -> SimpleNamespace:
    return SimpleNamespace(road_id=road_id, geometry=LineString(coords))


def _node(node_id: str, *, mainnodeid: str | None = None, x: float = 0.0, y: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(node_id=node_id, mainnodeid=mainnodeid, geometry=Point(x, y))


def test_sidearm_cap_applies_when_nonmain_branch_has_no_projection_support() -> None:
    result = build_stage3_step3_shadow_frontier(
        template_class="single_sided_t_mouth",
        analysis_center=Point(0.0, 0.0),
        drivezone_union=Polygon([(-120.0, -80.0), (120.0, -80.0), (120.0, 80.0), (-120.0, 80.0)]),
        group_nodes=[_node("100", mainnodeid="100")],
        local_nodes=[_node("100", mainnodeid="100")],
        local_roads=[_road("road_1", [(0.0, 0.0), (110.0, 0.0)])],
        selected_rc_roads=[],
        road_branches=[_branch()],
        positive_rc_groups=[],
        analysis_member_node_ids=["100"],
        normalized_mainnodeid="100",
        config=Stage3Step3ShadowFrontierConfig(
            alpha=0.6,
            buffer_m=14.0,
            fallback_strategy="min_drivezone_edge_30m",
            fallback_cap_m=30.0,
            sidearm_cap_m=50.0,
        ),
    )

    record = result.branch_records[0]
    assert record.is_main_direction is False
    assert record.support_projection_m is None
    assert record.neighbor_projection_m is None
    assert record.raw_frontier_length_m is not None and record.raw_frontier_length_m > 50.0
    assert record.frontier_length_m == 50.0
    assert record.fallback_applied is False
    assert record.sidearm_cap_applied is True
    assert record.stop_reasons == ("sidearm_cap_50m",)


def test_sidearm_cap_does_not_override_main_direction_branch() -> None:
    result = build_stage3_step3_shadow_frontier(
        template_class="single_sided_t_mouth",
        analysis_center=Point(0.0, 0.0),
        drivezone_union=Polygon([(-120.0, -80.0), (120.0, -80.0), (120.0, 80.0), (-120.0, 80.0)]),
        group_nodes=[_node("100", mainnodeid="100")],
        local_nodes=[_node("100", mainnodeid="100")],
        local_roads=[_road("road_1", [(0.0, 0.0), (110.0, 0.0)])],
        selected_rc_roads=[],
        road_branches=[_branch(is_main_direction=True, branch_type="trunk", drivezone_support_m=0.0)],
        positive_rc_groups=[],
        analysis_member_node_ids=["100"],
        normalized_mainnodeid="100",
        config=Stage3Step3ShadowFrontierConfig(
            alpha=0.6,
            buffer_m=14.0,
            fallback_strategy="min_drivezone_edge_30m",
            fallback_cap_m=30.0,
            sidearm_cap_m=50.0,
        ),
    )

    record = result.branch_records[0]
    assert record.is_main_direction is True
    assert record.frontier_length_m == record.raw_frontier_length_m
    assert record.sidearm_cap_applied is False
