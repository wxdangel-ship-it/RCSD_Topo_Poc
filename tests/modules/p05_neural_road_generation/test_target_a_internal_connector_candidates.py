from __future__ import annotations

import networkx as nx

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_internal_connector_candidates import (
    enumerate_internal_connector_trees,
    prove_internal_connector_tree,
)


def test_connector_tree_requires_every_leaf_to_touch_main() -> None:
    endpoints = {
        "m1": ("a", "b"),
        "m2": ("c", "d"),
        "c1": ("b", "x"),
        "c2": ("x", "c"),
    }

    proof = prove_internal_connector_tree(
        main_road_ids=("m1", "m2"),
        connector_road_ids=("c1", "c2"),
        road_endpoints=endpoints,
    )

    assert proof.hard_valid is True
    assert proof.leaf_node_ids == ("b", "c")
    assert proof.attachment_node_ids == ("b", "c")
    assert proof.external_leaf_node_ids == ()


def test_connector_tree_rejects_external_leaf() -> None:
    proof = prove_internal_connector_tree(
        main_road_ids=("m1",),
        connector_road_ids=("c1",),
        road_endpoints={
            "m1": ("a", "b"),
            "c1": ("b", "outside"),
        },
    )

    assert proof.hard_valid is False
    assert proof.invalid_reason == "connector_tree_has_external_leaf"
    assert proof.external_leaf_node_ids == ("outside",)


def test_connector_tree_aggregates_parallel_directional_roads() -> None:
    proof = prove_internal_connector_tree(
        main_road_ids=("m1", "m2"),
        connector_road_ids=("c_forward", "c_reverse"),
        road_endpoints={
            "m1": ("a", "b"),
            "m2": ("c", "d"),
            "c_forward": ("b", "c"),
            "c_reverse": ("c", "b"),
        },
    )

    assert proof.hard_valid is True
    assert proof.physical_edge_count == 1
    assert proof.raw_road_count == 2
    assert proof.as_dict()["aggregated_parallel_road_count"] == 1


def test_connector_tree_rejects_cycle_after_aggregation() -> None:
    proof = prove_internal_connector_tree(
        main_road_ids=("m1", "m2"),
        connector_road_ids=("c1", "c2", "c3"),
        road_endpoints={
            "m1": ("a", "b"),
            "m2": ("c", "d"),
            "c1": ("b", "x"),
            "c2": ("x", "c"),
            "c3": ("c", "b"),
        },
    )

    assert proof.hard_valid is False
    assert proof.invalid_reason == "connector_cycle_after_aggregation"


def test_enumerator_prunes_external_branch_but_keeps_main_to_main_path() -> None:
    graph = nx.MultiGraph()
    _edge(graph, "a", "b", "m1")
    _edge(graph, "c", "d", "m2")
    _edge(graph, "b", "x", "c1")
    _edge(graph, "x", "c", "c2")
    _edge(graph, "x", "outside", "branch")

    proofs = enumerate_internal_connector_trees(
        graph,
        main_road_ids=("m1", "m2"),
    )

    assert [proof.connector_road_ids for proof in proofs] == [
        ("c1", "c2"),
    ]
    assert all(proof.hard_valid for proof in proofs)
    assert all("branch" not in proof.connector_road_ids for proof in proofs)


def test_enumerator_does_not_relabel_parallel_main_edge_as_connector() -> None:
    graph = nx.MultiGraph()
    _edge(graph, "a", "b", "main")
    _edge(graph, "b", "a", "parallel")

    proofs = enumerate_internal_connector_trees(
        graph,
        main_road_ids=("main",),
    )

    assert proofs == ()


def _edge(
    graph: nx.MultiGraph,
    source: str,
    target: str,
    road_id: str,
) -> None:
    graph.add_edge(
        source,
        target,
        key=road_id,
        road_id=road_id,
        weight=1.0,
    )
