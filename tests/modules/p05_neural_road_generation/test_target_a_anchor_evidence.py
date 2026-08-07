from __future__ import annotations

import math

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
    build_anchor_structural_evidence,
    build_member_incidence_edges,
)


def test_structural_evidence_keeps_arm_sets_and_exact_topology() -> None:
    members = (
        (False, "node-a"),
        (True, "road-a"),
        (True, "road-b"),
        (True, "road-c"),
    )
    evidence = build_anchor_structural_evidence(
        members,
        swsd_arms=((0.0, 2, 1), (math.pi / 2.0, 3, 2)),
        member_arms={
            (False, "node-a"): ((0.1, 2, 1),),
            (True, "road-a"): ((0.2, 2, 1),),
            (True, "road-b"): ((1.2, 3, 2),),
            (True, "road-c"): ((2.2, 4, 3),),
        },
        road_endpoints={
            "road-a": ("n1", "n2", 1, 2),
            "road-b": ("n2", "n3", 2, 3),
            "road-c": ("n8", "n9", 3, 4),
        },
        member_local_features={
            key: (float(index),) * ANCHOR_MEMBER_LOCAL_FEATURE_DIM
            for index, key in enumerate(members)
        },
    )

    assert evidence.member_ids == (
        "NODE:node-a",
        "ROAD:road-a",
        "ROAD:road-b",
        "ROAD:road-c",
    )
    assert len(evidence.swsd_arm_features) == 2
    assert all(
        len(row) == ANCHOR_ARM_FEATURE_DIM
        for row in evidence.swsd_arm_features
    )
    assert len(evidence.member_local_features) == len(members)
    assert all(
        len(row) == ANCHOR_MEMBER_LOCAL_FEATURE_DIM
        for row in evidence.member_local_features
    )
    edge_pairs = {
        (left, right)
        for left, right, _ in evidence.member_relation_edges
    }
    assert edge_pairs == {(1, 2), (2, 1)}
    forward = next(
        features
        for left, right, features in evidence.member_relation_edges
        if (left, right) == (1, 2)
    )
    assert forward[0] == 1.0
    assert forward[3] == 1.0


def test_structural_evidence_does_not_turn_ids_into_numeric_features() -> None:
    evidence = build_anchor_structural_evidence(
        ((True, "987654321"),),
        swsd_arms=(),
        member_arms={(True, "987654321"): ()},
        road_endpoints={"987654321": ("11", "12", 0, 1)},
    )

    assert evidence.member_ids == ("ROAD:987654321",)
    assert evidence.swsd_arm_features == ()
    assert evidence.member_arm_features == ((),)
    assert evidence.member_local_features == ()
    assert evidence.member_relation_edges == ()


def test_member_incidence_keeps_exact_node_group_and_road_endpoint_roles() -> None:
    edges = build_member_incidence_edges(
        ("NODE:group-a", "ROAD:road-a", "ROAD:road-b"),
        node_members={"group-a": ("n1", "n2")},
        road_endpoints={
            "road-a": ("n1", "n8"),
            "road-b": ("n7", "n2"),
        },
    )

    assert edges == (
        (0, 1, (1.0, 0.0, 1.0, 0.0)),
        (1, 0, (0.0, 1.0, 1.0, 0.0)),
        (0, 2, (1.0, 0.0, 0.0, 1.0)),
        (2, 0, (0.0, 1.0, 0.0, 1.0)),
    )
