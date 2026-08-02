from __future__ import annotations

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import (
    NodeRecord,
    RoadRecord,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_raw_topology_guard import (
    evaluate_raw_topology_guard,
)


def _node(
    node_id: str,
    x: float,
    y: float,
    *,
    mainnodeid: str | None = None,
) -> NodeRecord:
    return NodeRecord(
        feature_index=0,
        node_id=node_id,
        mainnodeid=mainnodeid,
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
        geometry=Point(x, y),
    )


def _road(
    road_id: str,
    start: str,
    end: str,
    coordinates: list[tuple[float, float]],
    *,
    direction: int = 2,
) -> RoadRecord:
    return RoadRecord(
        feature_index=0,
        road_id=road_id,
        snodeid=start,
        enodeid=end,
        direction=direction,
        geometry=LineString(coordinates),
    )


def _evaluate(
    *,
    targets: tuple[NodeRecord, ...],
    swsd_roads: tuple[RoadRecord, ...],
    rcsd_roads: tuple[RoadRecord, ...],
    rcsd_nodes: tuple[NodeRecord, ...],
    support_ids: tuple[str, ...],
    required_road_ids: tuple[str, ...] = (),
    association_class: str = "B",
    required_gate: dict | None = None,
    drivezone=None,
) -> dict:
    return evaluate_raw_topology_guard(
        template_class="single_sided_t_mouth",
        association_class=association_class,
        target_nodes=targets,
        swsd_roads=swsd_roads,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_road_ids=support_ids,
        required_road_ids=required_road_ids,
        required_node_gate_audit=required_gate,
        drivezone_input_audit={"invalid_feature_count": 0},
        drivezone_geometry=drivezone,
    )


def test_unmatched_support_component_is_blocking_topology_evidence() -> None:
    targets = (_node("t0", 2, 0), _node("t1", 4, 0))
    rcsd_nodes = (
        _node("a", 0, 0),
        _node("b", 10, 0),
        _node("c", 0, 20),
        _node("d", 10, 20),
        _node("e", 20, 20),
    )
    rcsd_roads = (
        _road("r0", "a", "b", [(0, 0), (10, 0)]),
        _road("r1", "c", "d", [(0, 20), (10, 20)]),
        _road("r2", "d", "e", [(10, 20), (20, 20)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=("r0", "r1", "r2"),
    )

    assert audit["blocked"] is True
    assert audit["reason"] == "association_raw_multi_component_unmatched_support"
    assert audit["target_projection_component_ids"] == [0]
    assert audit["unmatched_support_component_ids"] == [1]


def test_unowned_full_local_bridge_is_audit_only_not_ownership_evidence() -> None:
    targets = (_node("t0", 2, 0), _node("t1", 4, 0))
    rcsd_nodes = (
        _node("a", 0, 0),
        _node("b", 10, 0),
        _node("c", 0, 20),
        _node("d", 10, 20),
        _node("e", 20, 20),
    )
    rcsd_roads = (
        _road("r0", "a", "b", [(0, 0), (10, 0)]),
        _road("r1", "c", "d", [(0, 20), (10, 20)]),
        _road("r2", "d", "e", [(10, 20), (20, 20)]),
        _road("nearby_bridge", "b", "c", [(10, 0), (0, 20)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=("r0", "r1", "r2"),
    )

    assert audit["alternate_full_local_raw_carrier"] is True
    assert audit["alternate_canonical_alias_portal"] is False
    assert audit["alternate_raw_carrier"] is True
    assert audit["blocked"] is True
    assert audit["reason"] == "association_raw_multi_component_unmatched_support"


def test_compact_alias_group_rejects_one_sided_directional_terminal() -> None:
    targets = (_node("t0", 0, 0), _node("t1", 0, 5))
    swsd_roads = (
        _road("sw_in", "outside_in", "t0", [(-10, 0), (0, 0)]),
        _road("sw_out", "t1", "outside_out", [(0, 5), (10, 5)]),
    )
    rcsd_nodes = (
        _node("left", -10, 2),
        _node("right", 10, 2),
        _node("merge", 0, 2),
    )
    rcsd_roads = (
        _road("in0", "left", "merge", [(-10, 2), (0, 2)]),
        _road("in1", "right", "merge", [(10, 2), (0, 2)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=swsd_roads,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=("in0", "in1"),
    )

    assert audit["blocked"] is True
    assert (
        audit["reason"]
        == "association_raw_compact_alias_directional_terminal_mismatch"
    )
    assert audit["source_incoming_count"] == 1
    assert audit["source_outgoing_count"] == 1


def test_connected_multi_member_core_and_dropped_core_is_nonunique() -> None:
    targets = (_node("t0", 0, 0), _node("t1", 0, 8))
    rcsd_nodes = (
        _node("keep0", 0, 0),
        _node("keep1", 0, 8),
        _node("drop0", 0, 20),
    )
    rcsd_roads = (
        _road("connector", "drop0", "keep1", [(0, 20), (0, 8)]),
    )
    gate = {
        "keep": {
            "gate_decision": "retained",
            "member_rcsdnode_ids": ["keep0", "keep1"],
        },
        "drop": {
            "gate_decision": "dropped",
            "gate_reason": (
                "single_sided_t_mouth_overflow_after_strong_pair_selection"
            ),
            "member_rcsdnode_ids": ["drop0"],
            "intersects_current_swsd_surface": True,
            "intersects_allowed_space": True,
            "effective_degree": 3,
        },
    }

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=(),
        association_class="A",
        required_gate=gate,
    )

    assert audit["blocked"] is True
    assert audit["reason"] == "association_raw_connected_semantic_core_ambiguity"
    assert audit["connected_semantic_core_rows"][0][
        "connecting_rcsdroad_ids"
    ] == ["connector"]


def test_shared_terminal_is_audit_only_without_t03_topology_contradiction() -> None:
    targets = (_node("t0", 0, 5), _node("t1", 0, 10))
    rcsd_nodes = (_node("a", 0, -10), _node("terminal", 0, 10))
    rcsd_roads = (
        _road("raw", "a", "terminal", [(0, -10), (0, 10)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=(),
    )

    assert audit["terminal_collapse"] is True
    assert audit["blocked"] is False
    assert audit["reason"] is None


def test_directional_canonical_alias_portal_explains_raw_support_components() -> None:
    targets = (_node("t0", 2, 0), _node("t1", 4, 0))
    rcsd_nodes = (
        _node("a", 0, 0),
        _node("b", 10, 0, mainnodeid="junction"),
        _node("c", 15, 0, mainnodeid="junction"),
        _node("d", 25, 0),
        _node("e", 35, 0),
    )
    rcsd_roads = (
        _road("r0", "a", "b", [(0, 0), (10, 0)]),
        _road("r1", "c", "d", [(15, 0), (25, 0)]),
        _road("r2", "d", "e", [(25, 0), (35, 0)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=("r0", "r1", "r2"),
        drivezone=box(-1, -2, 36, 2),
    )

    assert audit["blocked"] is False
    assert audit["alternate_canonical_alias_portal"] is True
    portal = audit["canonical_alias_portal_audit"]
    assert portal["all_support_components_reachable"] is True
    assert portal["portal_rows"][0]["direction_compatible"] is True
    assert portal["portal_rows"][0]["directed_transition_compatible"] is True
    assert portal["portal_rows"][0]["target_anchor_compatible"] is True
    assert portal["portal_rows"][0]["drivezone_coverage_ratio"] == 1.0


def test_remote_canonical_alias_portal_does_not_claim_current_junction() -> None:
    targets = (_node("t0", 0, 0), _node("t1", 0, 5))
    rcsd_nodes = (
        _node("a", 0, 0),
        _node("b", 100, 0, mainnodeid="remote_junction"),
        _node("c", 105, 0, mainnodeid="remote_junction"),
        _node("d", 115, 0),
        _node("e", 125, 0),
    )
    rcsd_roads = (
        _road("r0", "a", "b", [(0, 0), (100, 0)]),
        _road("r1", "c", "d", [(105, 0), (115, 0)]),
        _road("r2", "d", "e", [(115, 0), (125, 0)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=("r0", "r1", "r2"),
        drivezone=box(-1, -2, 126, 2),
    )

    portal = audit["canonical_alias_portal_audit"]["portal_rows"][0]
    assert portal["target_anchor_distance_m"] == 100.0
    assert portal["target_anchor_compatible"] is False
    assert portal["accepted"] is False
    assert audit["alternate_canonical_alias_portal"] is False
    assert audit["blocked"] is True


def test_class_a_required_carrier_is_not_overridden_by_support_shape() -> None:
    targets = (_node("t0", 2, 0), _node("t1", 4, 0))
    rcsd_nodes = (
        _node("a", 0, 0),
        _node("b", 10, 0),
        _node("c", 0, 20),
        _node("d", 10, 20),
        _node("e", 20, 20),
    )
    rcsd_roads = (
        _road("r0", "a", "b", [(0, 0), (10, 0)]),
        _road("r1", "c", "d", [(0, 20), (10, 20)]),
        _road("r2", "d", "e", [(10, 20), (20, 20)]),
    )

    audit = _evaluate(
        targets=targets,
        swsd_roads=(),
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        support_ids=("r0", "r1", "r2"),
        association_class="A",
        required_gate={
            "required": {
                "gate_decision": "retained",
                "member_rcsdnode_ids": ["a", "b"],
            }
        },
        required_road_ids=("r0",),
    )

    assert audit["unmatched_support"] is False
    assert audit["retained_required_group_ids"] == ["required"]
    assert audit["blocked"] is False
