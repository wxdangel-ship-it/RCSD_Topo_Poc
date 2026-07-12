from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from shapely.geometry import LineString, mapping

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import feature
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_unreplaced_bridge_fallback import (
    GEOMETRY_COMPONENT_RISK,
    apply_unreplaced_second_degree_bridge_fallback,
)


@dataclass
class _Unit:
    segment_id: str
    rcsd_road_ids: list[str]
    geometry: LineString
    rcsd_pair_nodes: list[str] = field(default_factory=list)
    rcsd_junc_nodes: list[str] = field(default_factory=list)
    retained_node_ids: list[str] = field(default_factory=list)
    optional_allowed_rcsd_nodes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    status: str = "passed"


def test_geometry_component_adds_chain_closed_by_existing_road_and_unit_node() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
        geometry=LineString([(0, 0), (20, 0)]),
    )
    added = defaultdict(list, {"left": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", [(0, 0), (10, 0)]),
            _road("missing", "T1", "B", [(10, 0), (20, 0)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["geometry_component_added_group_count"] == 1
    assert stats["geometry_component_added_road_count"] == 1
    assert unit.rcsd_road_ids == ["left"]
    assert added["missing"] == ["seg"]
    assert GEOMETRY_COMPONENT_RISK in unit.risk_flags


def test_geometry_component_blocks_open_tail() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
        geometry=LineString([(0, 0), (20, 0)]),
    )
    added = defaultdict(list, {"left": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", [(0, 0), (10, 0)]),
            _road("tail", "T1", "X", [(10, 0), (20, 0)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["geometry_component_blocked_open_component_count"] == 1
    assert stats["geometry_component_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["left"]
    assert "tail" not in added


def test_geometry_component_blocks_existing_direct_boundary_parallel() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["seed"],
        geometry=LineString([(0, 0), (20, 0)]),
    )
    added = defaultdict(list, {"seed": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("seed", "T1", "T2", [(0, 0), (20, 0)]),
            _road("parallel", "T1", "T2", [(0, 1), (20, 1)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["geometry_component_blocked_existing_boundary_count"] == 1
    assert stats["geometry_component_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["seed"]
    assert "parallel" not in added


def test_geometry_component_requires_strong_segment_geometry_match() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
        geometry=LineString([(0, 0), (20, 0)]),
    )
    added = defaultdict(list, {"left": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", [(0, 0), (10, 0)]),
            _road("far", "T1", "B", [(10, 10), (20, 10)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["geometry_component_candidate_road_count"] == 0
    assert stats["geometry_component_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["left"]
    assert "far" not in added


def test_geometry_component_accepts_geojson_mapping_unit_geometry() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
        geometry=mapping(LineString([(0, 0), (20, 0)])),
    )
    added = defaultdict(list, {"left": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", [(0, 0), (10, 0)]),
            _road("missing", "T1", "B", [(10, 0), (20, 0)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
    )

    assert stats["geometry_component_added_road_count"] == 1
    assert unit.rcsd_road_ids == ["left"]
    assert added["missing"] == ["seg"]


def test_geometry_component_excludes_blocked_plan_roads() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
        geometry=LineString([(0, 0), (20, 0)]),
    )
    added = defaultdict(list, {"left": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", [(0, 0), (10, 0)]),
            _road("blocked", "T1", "B", [(10, 0), (20, 0)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
        blocked_road_ids={"blocked"},
    )

    assert stats["geometry_component_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["left"]
    assert "blocked" not in added


def test_geometry_component_excludes_blocked_roads_from_plan_rows() -> None:
    unit = _Unit(
        segment_id="seg",
        rcsd_road_ids=["left"],
        rcsd_pair_nodes=["A", "B"],
        geometry=LineString([(0, 0), (20, 0)]),
    )
    added = defaultdict(list, {"left": ["seg"]})

    stats = apply_unreplaced_second_degree_bridge_fallback(
        [unit],
        rcsd_roads=[
            _road("left", "A", "T1", [(0, 0), (10, 0)]),
            _road("blocked", "T1", "B", [(10, 0), (20, 0)]),
        ],
        canonicalizer=NodeCanonicalizer({}, frozenset()),
        added_road_to_segments=added,
        replacement_plan_rows=[
            {"properties": {"plan_status": "blocked", "rcsd_road_ids": ["blocked"]}},
        ],
    )

    assert stats["geometry_component_added_road_count"] == 0
    assert unit.rcsd_road_ids == ["left"]
    assert "blocked" not in added


def _road(road_id: str, source: str, target: str, points: list[tuple[float, float]]) -> dict:
    return feature(
        {"id": road_id, "snodeid": source, "enodeid": target, "direction": 0},
        LineString(points),
    )
