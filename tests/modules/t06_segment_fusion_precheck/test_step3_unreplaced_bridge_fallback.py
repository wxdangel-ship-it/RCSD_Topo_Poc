from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import feature
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_unreplaced_bridge_fallback as fallback
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_unreplaced_bridge_fallback import (
    SECOND_DEGREE_BRIDGE_RISK,
    apply_unreplaced_second_degree_bridge_fallback,
)


def test_geometry_match_reuses_one_unit_buffer_for_multiple_candidate_roads(monkeypatch) -> None:
    original_buffer = BaseGeometry.buffer
    buffer_calls = 0

    def counted_buffer(self, *args, **kwargs):
        nonlocal buffer_calls
        buffer_calls += 1
        return original_buffer(self, *args, **kwargs)

    monkeypatch.setattr(BaseGeometry, "buffer", counted_buffer)
    unit_geometry = LineString([(0.0, 0.0), (20.0, 0.0)])
    unit_buffer_cache: list[BaseGeometry] = []
    for offset in (0.0, 1.0):
        assert fallback._road_geometry_matches_unit(
            {"geometry": LineString([(0.0, offset), (20.0, offset)])},
            unit_geometry,
            unit_buffer_cache=unit_buffer_cache,
        )

    assert buffer_calls == 1


@dataclass
class _Unit:
    segment_id: str
    rcsd_road_ids: list[str]
    rcsd_pair_nodes: list[str] = field(default_factory=list)
    rcsd_junc_nodes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    status: str = "passed"


def test_second_degree_bridge_adds_linear_unreplaced_group_between_replaced_roads() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left", "right"],
        rcsd_pair_nodes=["A", "B"],
        rcsd_junc_nodes=["J"],
    )
    added = defaultdict(list, {"left": ["seg"], "right": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", 0, 0),
            _road("bridge1", "T1", "M", 10, 0),
            _road("bridge2", "M", "T2", 20, 0),
            _road("right", "T2", "B", 30, 0),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_added_group_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 2
    assert unit.rcsd_road_ids == ["left", "right"]
    assert added["bridge1"] == ["seg"]
    assert added["bridge2"] == ["seg"]
    assert SECOND_DEGREE_BRIDGE_RISK in unit.risk_flags


def test_second_degree_bridge_blocks_when_terminal_is_pair_or_junc_node() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left", "right"],
        rcsd_pair_nodes=["A", "B"],
        rcsd_junc_nodes=["T1"],
    )
    added = defaultdict(list, {"left": ["seg"], "right": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", 0, 0),
            _road("bridge", "T1", "T2", 10, 0),
            _road("right", "T2", "B", 20, 0),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_blocked_anchor_endpoint_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["left", "right"]
    assert "bridge" not in added


def test_second_degree_bridge_adds_cross_segment_terminal_attachments() -> None:
    left_unit = _Unit(
        segment_id="left_seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
    )
    right_unit = _Unit(
        segment_id="right_seg",
        rcsd_road_ids=["right"],
        rcsd_pair_nodes=["C", "D"],
    )
    added = {"left": ["left_seg"], "right": ["right_seg"]}

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [left_unit, right_unit],
        rcsd_roads=[
            _road("left", "A", "T1", 0, 0),
            _road("bridge", "T1", "T2", 10, 0),
            _road("right", "T2", "D", 20, 0),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_added_group_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 1
    assert stats["second_degree_bridge_added_segment_count"] == 2
    assert left_unit.rcsd_road_ids == ["left"]
    assert right_unit.rcsd_road_ids == ["right"]
    assert added["bridge"] == ["left_seg", "right_seg"]
    assert SECOND_DEGREE_BRIDGE_RISK in left_unit.risk_flags
    assert SECOND_DEGREE_BRIDGE_RISK in right_unit.risk_flags


def test_second_degree_bridge_blocks_non_linear_unreplaced_component() -> None:
    unit = _Unit(segment_id="seg", rcsd_road_ids=["left", "right"])
    added = defaultdict(list, {"left": ["seg"], "right": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", 0, 0),
            _road("bridge1", "T1", "M", 10, 0),
            _road("bridge2", "M", "T2", 20, 0),
            _road("branch", "M", "X", 20, 10),
            _road("right", "T2", "B", 30, 0),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_blocked_non_linear_component_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["left", "right"]


def test_second_degree_bridge_adds_direct_bridge_inside_non_linear_component() -> None:
    left_unit = _Unit(segment_id="left_seg", rcsd_road_ids=["left"])
    right_unit = _Unit(segment_id="right_seg", rcsd_road_ids=["right"])
    added = {"left": ["left_seg"], "right": ["right_seg"]}

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [left_unit, right_unit],
        rcsd_roads=[
            _road("left", "A", "T1", 0, 0),
            _road("direct_bridge", "T1", "T2", 10, 0),
            _road("right", "T2", "D", 20, 0),
            _road("branch1", "M", "T1", 10, 10),
            _road("branch2", "M", "X", 20, 10),
            _road("branch3", "M", "Y", 20, 20),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_added_group_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 1
    assert stats["second_degree_bridge_blocked_non_linear_component_count"] == 0
    assert left_unit.rcsd_road_ids == ["left"]
    assert right_unit.rcsd_road_ids == ["right"]
    assert added["direct_bridge"] == ["left_seg", "right_seg"]
    assert "branch1" not in added


def test_second_degree_bridge_prefers_single_segment_boundary_over_shared_carrier() -> None:
    left_unit = _Unit(segment_id="left_seg", rcsd_road_ids=["left", "shared_left"])
    right_unit = _Unit(segment_id="right_seg", rcsd_road_ids=["right", "shared_right"])
    side_unit = _Unit(segment_id="side_seg", rcsd_road_ids=["shared_left", "shared_right"])
    added = {
        "left": ["left_seg"],
        "shared_left": ["left_seg", "side_seg"],
        "right": ["right_seg"],
        "shared_right": ["right_seg", "side_seg"],
    }

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [left_unit, right_unit, side_unit],
        rcsd_roads=[
            _road("left", "A", "T1", 0, 0),
            _road("shared_left", "X", "T1", 0, 10),
            _road("bridge", "T1", "T2", 10, 0),
            _road("right", "T2", "D", 20, 0),
            _road("shared_right", "T2", "Y", 20, 10),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_added_group_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 1
    assert left_unit.rcsd_road_ids == ["left", "shared_left"]
    assert right_unit.rcsd_road_ids == ["right", "shared_right"]
    assert side_unit.rcsd_road_ids == ["shared_left", "shared_right"]
    assert added["bridge"] == ["left_seg", "right_seg"]


def test_second_degree_bridge_blocks_ambiguous_segment_candidates() -> None:
    unit1 = _Unit(segment_id="seg1", rcsd_road_ids=["left1", "right1"])
    unit2 = _Unit(segment_id="seg2", rcsd_road_ids=["left2", "right2"])
    added = defaultdict(
        list,
        {
            "left1": ["seg1"],
            "right1": ["seg1"],
            "left2": ["seg2"],
            "right2": ["seg2"],
        },
    )

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit1, unit2],
        rcsd_roads=[
            _road("left1", "A1", "T1", 0, 0),
            _road("right1", "T2", "B1", 30, 0),
            _road("left2", "A2", "T1", 0, 10),
            _road("right2", "T2", "B2", 30, 10),
            _road("bridge", "T1", "T2", 10, 0),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_blocked_ambiguous_segment_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 0
    assert unit1.rcsd_road_ids == ["left1", "right1"]
    assert unit2.rcsd_road_ids == ["left2", "right2"]


def test_second_degree_bridge_blocks_single_replaced_boundary_road() -> None:
    unit = _Unit(segment_id="seg", rcsd_road_ids=["seed"])
    added = defaultdict(list, {"seed": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("seed", "T1", "T2", 0, 0),
            _road("parallel", "T1", "T2", 0, 1),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["second_degree_bridge_blocked_single_boundary_road_count"] == 1
    assert stats["second_degree_bridge_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["seed"]
    assert "parallel" not in added


def _road(road_id: str, source: str, target: str, x: float, y: float) -> dict:
    return feature(
        {"id": road_id, "snodeid": source, "enodeid": target, "direction": 0},
        LineString([(x, y), (x + 10, y)]),
    )
