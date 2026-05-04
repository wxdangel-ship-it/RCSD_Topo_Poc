from __future__ import annotations

import pytest
from shapely.geometry import Point, Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step23_contracts import Stage4BranchResult
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step3_topology_skeleton import (
    _build_stage4_topology_skeleton,
    _build_swsd_semantic_junction,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import BranchEvidence

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import (
    REAL_ANCHOR_2_ROOT,
    build_case_result,
    load_case_bundle,
    load_case_specs,
    _parsed_node,
    _parsed_road,
)


DRIVEZONE = Polygon([(-120, -120), (120, -120), (120, 120), (-120, 120), (-120, -120)])


def _skeleton(nodes, roads, *, representative_id: str = "j0", group_ids: tuple[str, ...] = ("j0",)):
    node_by_id = {node.node_id: node for node in nodes}
    return _build_stage4_topology_skeleton(
        representative_node=node_by_id[representative_id],
        group_nodes=[node_by_id[node_id] for node_id in group_ids],
        local_nodes=list(nodes),
        local_roads=list(roads),
        drivezone_union=DRIVEZONE,
        support_center=node_by_id[representative_id].geometry,
    )


def _arm_by_road(junction, road_id: str):
    for arm in junction.semantic_arms:
        if road_id in set(arm.first_road_ids) or road_id in set(arm.inter_junction_connector_road_ids):
            return arm
    raise AssertionError(f"missing semantic arm containing road {road_id}")


def test_swsd_semantic_junction_splits_intra_and_connector_roads() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("j1", 3, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("a", -30, 0),
        _parsed_node("b", 40, 30),
        _parsed_node("c", 40, -30),
    ]
    roads = [
        _parsed_road("r0", [(0, 0), (3, 0)], snodeid="j0", enodeid="j1"),
        _parsed_road("r1", [(-30, 0), (0, 0)], snodeid="a", enodeid="j0"),
        _parsed_road("r2", [(3, 0), (40, 30)], snodeid="j1", enodeid="b"),
        _parsed_road("r3", [(3, 0), (40, -30)], snodeid="j1", enodeid="c"),
    ]

    junction = _skeleton(nodes, roads, group_ids=("j0", "j1")).swsd_semantic_junction

    assert junction.junction_id == "j0"
    assert junction.member_node_ids == ("j0", "j1")
    assert junction.intra_junction_road_ids == ("r0",)
    connector_ids = {
        road_id
        for arm in junction.semantic_arms
        for road_id in arm.inter_junction_connector_road_ids
    }
    assert connector_ids == {"r1", "r2", "r3"}
    assert set(junction.intra_junction_road_ids).isdisjoint(connector_ids)
    assert len(junction.semantic_arms) == 3


def test_swsd_semantic_arm_stops_at_degree3_semantic_boundary() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("m", 20, 0),
        _parsed_node("t", 45, 0),
        _parsed_node("side", 20, 20),
        _parsed_node("u", 0, 35),
        _parsed_node("d", 0, -35),
    ]
    roads = [
        _parsed_road("r_main", [(0, 0), (20, 0)], snodeid="j0", enodeid="m"),
        _parsed_road("r_continue", [(20, 0), (45, 0)], snodeid="m", enodeid="t"),
        _parsed_road("r_side", [(20, 0), (20, 20)], snodeid="m", enodeid="side"),
        _parsed_road("r_up", [(0, 0), (0, 35)], snodeid="j0", enodeid="u"),
        _parsed_road("r_down", [(0, 0), (0, -35)], snodeid="j0", enodeid="d"),
    ]

    arm = _arm_by_road(_skeleton(nodes, roads).swsd_semantic_junction, "r_main")

    assert arm.inter_junction_connector_road_ids == ("r_main",)
    assert arm.terminal_node_id == "m"
    assert arm.terminal_kind == "semantic_neighbor"
    assert arm.neighbor_semantic_junction_id == "m"
    assert arm.continuation_through_micro_junction is False


def test_swsd_semantic_arm_uses_mainnode_group_boundary_degree() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("m_a", 20, 0, mainnodeid="m"),
        _parsed_node("m_b", 20, 20, mainnodeid="m"),
        _parsed_node("t", 45, 0),
        _parsed_node("side", 45, 20),
        _parsed_node("u", 0, 35),
        _parsed_node("d", 0, -35),
    ]
    roads = [
        _parsed_road("r_main", [(0, 0), (20, 0)], snodeid="j0", enodeid="m_a"),
        _parsed_road("r_continue", [(20, 0), (45, 0)], snodeid="m_a", enodeid="t"),
        _parsed_road("r_side", [(20, 20), (45, 20)], snodeid="m_b", enodeid="side"),
        _parsed_road("r_up", [(0, 0), (0, 35)], snodeid="j0", enodeid="u"),
        _parsed_road("r_down", [(0, 0), (0, -35)], snodeid="j0", enodeid="d"),
    ]

    arm = _arm_by_road(_skeleton(nodes, roads).swsd_semantic_junction, "r_main")

    assert arm.inter_junction_connector_road_ids == ("r_main",)
    assert arm.terminal_node_id == "m_a"
    assert arm.terminal_kind == "semantic_neighbor"
    assert arm.neighbor_semantic_junction_id == "m"


def test_swsd_semantic_arm_allows_degree2_mainnode_group_passthrough() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("m_a", 20, 0, mainnodeid="m"),
        _parsed_node("t", 45, 0),
        _parsed_node("u", 0, 35),
        _parsed_node("d", 0, -35),
    ]
    roads = [
        _parsed_road("r_main", [(0, 0), (20, 0)], snodeid="j0", enodeid="m_a"),
        _parsed_road("r_continue", [(20, 0), (45, 0)], snodeid="m_a", enodeid="t"),
        _parsed_road("r_up", [(0, 0), (0, 35)], snodeid="j0", enodeid="u"),
        _parsed_road("r_down", [(0, 0), (0, -35)], snodeid="j0", enodeid="d"),
    ]

    arm = _arm_by_road(_skeleton(nodes, roads).swsd_semantic_junction, "r_main")

    assert arm.inter_junction_connector_road_ids == ("r_main", "r_continue")
    assert arm.terminal_node_id == "t"
    assert arm.terminal_kind == "dead_end"


def test_swsd_semantic_arm_dead_end_terminal() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("t", 30, 0),
    ]
    roads = [_parsed_road("r_dead", [(0, 0), (30, 0)], snodeid="j0", enodeid="t")]

    arm = _arm_by_road(_skeleton(nodes, roads).swsd_semantic_junction, "r_dead")

    assert arm.inter_junction_connector_road_ids == ("r_dead",)
    assert arm.terminal_node_id == "t"
    assert arm.terminal_kind == "dead_end"


def test_swsd_semantic_arm_connector_contains_all_first_road_ids() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("split", 12, 0),
        _parsed_node("left", 30, 8),
        _parsed_node("right", 30, -8),
    ]
    roads = [
        _parsed_road("r_seed", [(0, 0), (12, 0)], snodeid="j0", enodeid="split"),
        _parsed_road("r_first_extra", [(12, 0), (30, 8)], snodeid="split", enodeid="left"),
        _parsed_road("r_other", [(12, 0), (30, -8)], snodeid="split", enodeid="right"),
    ]
    branch_result = Stage4BranchResult(
        member_node_ids=("j0",),
        augmented_member_node_ids=("j0",),
        road_branches=(
            BranchEvidence(
                branch_id="road_1",
                angle_deg=0.0,
                branch_type="road",
                road_ids=["r_seed", "r_first_extra"],
                has_outgoing_support=True,
            ),
        ),
        road_branch_ids=("road_1",),
        road_to_branch={},
        road_branches_by_id={},
        main_branch_ids=("road_1",),
        through_node_policy="degree2_passthrough_does_not_break_branch",
        through_node_candidate_ids=(),
    )

    junction = _build_swsd_semantic_junction(branch_result, roads, nodes, nodes[0])

    assert junction.semantic_arms[0].first_road_ids == ("r_seed", "r_first_extra")
    assert junction.semantic_arms[0].inter_junction_connector_road_ids == ("r_seed",)
    assert junction.semantic_arms[0].terminal_kind == "semantic_neighbor"


def test_swsd_semantic_arm_patch_boundary_keeps_only_patch_road_ids() -> None:
    nodes = [_parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16)]
    roads = [_parsed_road("r_patch", [(0, 0), (50, 0)], snodeid="j0", enodeid="outside_patch")]

    arm = _arm_by_road(_skeleton(nodes, roads).swsd_semantic_junction, "r_patch")

    assert arm.inter_junction_connector_road_ids == ("r_patch",)
    assert arm.terminal_node_id == "outside_patch"
    assert arm.terminal_kind == "patch_boundary"
    assert arm.neighbor_semantic_junction_id is None


def test_swsd_semantic_junction_uses_augmented_members_without_unit_envelope_mutation() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("sibling", 5, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("out", 30, 0),
    ]
    roads = [
        _parsed_road("r_internal", [(0, 0), (5, 0)], snodeid="j0", enodeid="sibling"),
        _parsed_road("r_out", [(5, 0), (30, 0)], snodeid="sibling", enodeid="out"),
    ]
    branch_result = Stage4BranchResult(
        member_node_ids=("j0",),
        augmented_member_node_ids=("j0", "sibling"),
        road_branches=(
            BranchEvidence(
                branch_id="road_1",
                angle_deg=0.0,
                branch_type="road",
                road_ids=["r_out"],
                has_outgoing_support=True,
            ),
        ),
        road_branch_ids=("road_1",),
        road_to_branch={},
        road_branches_by_id={},
        main_branch_ids=("road_1",),
        through_node_policy="degree2_passthrough_does_not_break_branch",
        through_node_candidate_ids=(),
    )

    junction = _build_swsd_semantic_junction(branch_result, roads, nodes, nodes[0])

    assert junction.member_node_ids == ("j0", "sibling")
    assert junction.intra_junction_road_ids == ("r_internal",)


def test_swsd_semantic_arm_angle_reuses_branch_evidence_value_exactly() -> None:
    nodes = [
        _parsed_node("j0", 0, 0, mainnodeid="j0", kind_2=16),
        _parsed_node("a", 30, 0),
        _parsed_node("b", 0, 30),
        _parsed_node("c", 0, -30),
    ]
    roads = [
        _parsed_road("r1", [(0, 0), (30, 0)], snodeid="j0", enodeid="a"),
        _parsed_road("r2", [(0, 0), (0, 30)], snodeid="j0", enodeid="b"),
        _parsed_road("r3", [(0, 0), (0, -30)], snodeid="j0", enodeid="c"),
    ]
    skeleton = _skeleton(nodes, roads)
    branch_angle_by_id = {
        str(branch.branch_id): branch.angle_deg
        for branch in skeleton.branch_result.road_branches
    }

    for arm in skeleton.swsd_semantic_junction.semantic_arms:
        assert arm.angle_deg == branch_angle_by_id[arm.first_branch_id]


def test_named_anchor2_swsd_semantic_junction_snapshots() -> None:
    expected_snapshots = {
        "724067": {
            "junction_id": "724067",
            "intra_junction_road_ids": (),
            "connector_road_ids": ("18386573", "611600880", "71629388"),
        },
        "758784": {
            "junction_id": "758784",
            "intra_junction_road_ids": (),
            "connector_road_ids": ("39119257", "618801962", "627455843"),
        },
        "760213": {
            "junction_id": "760213",
            "intra_junction_road_ids": ("41808703",),
            "connector_road_ids": ("55009919", "989396", "992474", "992475"),
        },
        "698380": {
            "junction_id": "698380",
            "intra_junction_road_ids": (),
            "connector_road_ids": ("109815705", "612199387", "973749"),
        },
        "706243": {
            "junction_id": "706243",
            "intra_junction_road_ids": (),
            "connector_road_ids": ("500994564", "607948942", "608954744"),
        },
        "724081": {
            "junction_id": "724081",
            "intra_junction_road_ids": (),
            "connector_road_ids": ("516803728", "518742522", "5415248413000846"),
        },
        "785731": {
            "junction_id": "785731",
            "intra_junction_road_ids": (),
            "connector_road_ids": ("33027407", "33027442", "981884"),
        },
        "17943587": {
            "junction_id": "17943587",
            "intra_junction_road_ids": ("41727506", "502953712", "607951495"),
            "connector_road_ids": (
                "510969745",
                "528620938",
                "529824990",
                "605949403",
                "607962170",
                "620950831",
            ),
        },
    }
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    missing_cases = [
        case_id for case_id in expected_snapshots if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_snapshots),
    )

    for spec in specs:
        case_result = build_case_result(load_case_bundle(spec))
        junction = case_result.base_context.topology_skeleton.swsd_semantic_junction
        connector_road_ids = tuple(
            sorted(
                {
                    road_id
                    for arm in junction.semantic_arms
                    for road_id in arm.inter_junction_connector_road_ids
                }
            )
        )
        assert {
            "junction_id": junction.junction_id,
            "intra_junction_road_ids": tuple(junction.intra_junction_road_ids),
            "connector_road_ids": connector_road_ids,
        } == expected_snapshots[spec.case_id]
