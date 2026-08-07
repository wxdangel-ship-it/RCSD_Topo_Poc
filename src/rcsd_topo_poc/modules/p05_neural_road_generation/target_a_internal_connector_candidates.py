from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

import networkx as nx


@dataclass(frozen=True)
class InternalConnectorTreeProof:
    main_road_ids: tuple[str, ...]
    connector_road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    leaf_node_ids: tuple[str, ...]
    attachment_node_ids: tuple[str, ...]
    external_leaf_node_ids: tuple[str, ...]
    physical_edge_count: int
    raw_road_count: int
    hard_valid: bool
    invalid_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "main_road_ids": list(self.main_road_ids),
            "connector_road_ids": list(self.connector_road_ids),
            "node_ids": list(self.node_ids),
            "leaf_node_ids": list(self.leaf_node_ids),
            "attachment_node_ids": list(self.attachment_node_ids),
            "external_leaf_node_ids": list(self.external_leaf_node_ids),
            "physical_edge_count": self.physical_edge_count,
            "raw_road_count": self.raw_road_count,
            "aggregated_parallel_road_count": (
                self.raw_road_count - self.physical_edge_count
            ),
            "hard_valid": self.hard_valid,
            "invalid_reason": self.invalid_reason,
        }


def prove_internal_connector_tree(
    *,
    main_road_ids: Sequence[str],
    connector_road_ids: Sequence[str],
    road_endpoints: Mapping[str, tuple[str, str]],
) -> InternalConnectorTreeProof:
    """Prove the confirmed connector-tree business condition."""
    main_ids = tuple(sorted({str(value) for value in main_road_ids}))
    connector_ids = tuple(
        sorted({str(value) for value in connector_road_ids})
    )
    missing = sorted(
        road_id
        for road_id in (*main_ids, *connector_ids)
        if road_id not in road_endpoints
    )
    if not main_ids:
        return _invalid_proof(
            main_ids,
            connector_ids,
            "main_road_set_empty",
        )
    if not connector_ids:
        return _invalid_proof(
            main_ids,
            connector_ids,
            "connector_road_set_empty",
        )
    if set(main_ids) & set(connector_ids):
        return _invalid_proof(
            main_ids,
            connector_ids,
            "main_connector_role_overlap",
        )
    if missing:
        return _invalid_proof(
            main_ids,
            connector_ids,
            "road_endpoint_missing",
        )

    graph = nx.Graph()
    for road_id in connector_ids:
        source, target = road_endpoints[road_id]
        if not source or not target or source == target:
            return _invalid_proof(
                main_ids,
                connector_ids,
                "connector_self_loop_or_empty_endpoint",
            )
        graph.add_edge(source, target)
    main_nodes = {
        node_id
        for road_id in main_ids
        for node_id in road_endpoints[road_id]
    }
    leaves = {node_id for node_id, degree in graph.degree() if degree == 1}
    external = leaves - main_nodes
    if not nx.is_connected(graph):
        reason = "connector_forest_not_single_tree"
    elif not nx.is_tree(graph):
        reason = "connector_cycle_after_aggregation"
    elif not leaves:
        reason = "connector_tree_has_no_leaf"
    elif external:
        reason = "connector_tree_has_external_leaf"
    else:
        reason = ""
    return InternalConnectorTreeProof(
        main_road_ids=main_ids,
        connector_road_ids=connector_ids,
        node_ids=tuple(sorted(graph.nodes)),
        leaf_node_ids=tuple(sorted(leaves)),
        attachment_node_ids=tuple(sorted(leaves & main_nodes)),
        external_leaf_node_ids=tuple(sorted(external)),
        physical_edge_count=graph.number_of_edges(),
        raw_road_count=len(connector_ids),
        hard_valid=not reason,
        invalid_reason=reason,
    )


def enumerate_internal_connector_trees(
    graph: nx.MultiGraph,
    *,
    main_road_ids: Sequence[str],
    maximum_candidates: int = 8,
) -> tuple[InternalConnectorTreeProof, ...]:
    """Enumerate label-free connector trees whose leaves all touch MAIN."""
    if maximum_candidates < 1:
        raise ValueError("internal connector candidate limit must be positive")
    endpoints = _road_endpoints(graph)
    main_ids = tuple(
        sorted(
            {
                str(road_id)
                for road_id in main_road_ids
                if str(road_id) in endpoints
            }
        )
    )
    if not main_ids:
        return ()
    main_nodes = {
        node_id for road_id in main_ids for node_id in endpoints[road_id]
    }
    main_physical_edges = {
        _physical_edge(*endpoints[road_id]) for road_id in main_ids
    }
    connector_graph = nx.Graph()
    for source, target, _, data in graph.edges(keys=True, data=True):
        road_id = str(data["road_id"])
        physical_edge = _physical_edge(str(source), str(target))
        if road_id in main_ids or physical_edge in main_physical_edges:
            continue
        weight = float(data.get("weight") or 1.0)
        if connector_graph.has_edge(*physical_edge):
            edge = connector_graph.edges[physical_edge]
            edge["road_ids"] = tuple(
                sorted({*edge["road_ids"], road_id})
            )
            edge["weight"] = min(float(edge["weight"]), weight)
        else:
            connector_graph.add_edge(
                *physical_edge,
                road_ids=(road_id,),
                weight=weight,
            )

    proofs: dict[tuple[str, ...], InternalConnectorTreeProof] = {}
    for node_set in nx.connected_components(connector_graph):
        component = connector_graph.subgraph(node_set).copy()
        attachments = sorted(set(component.nodes) & main_nodes)
        if len(attachments) < 2:
            continue
        _record_proof(
            proofs,
            main_ids=main_ids,
            connector_ids=_component_road_ids(component),
            endpoints=endpoints,
        )
        for source, target in combinations(attachments, 2):
            node_path = nx.shortest_path(
                component,
                source,
                target,
                weight="weight",
            )
            connector_ids = tuple(
                sorted(
                    {
                        road_id
                        for first, second in zip(node_path, node_path[1:])
                        for road_id in component.edges[first, second][
                            "road_ids"
                        ]
                    }
                )
            )
            _record_proof(
                proofs,
                main_ids=main_ids,
                connector_ids=connector_ids,
                endpoints=endpoints,
            )
    ordered = sorted(
        proofs.values(),
        key=lambda row: (
            len(row.connector_road_ids),
            len(row.leaf_node_ids),
            row.connector_road_ids,
        ),
    )
    return tuple(ordered[:maximum_candidates])


def _record_proof(
    proofs: dict[tuple[str, ...], InternalConnectorTreeProof],
    *,
    main_ids: Sequence[str],
    connector_ids: Sequence[str],
    endpoints: Mapping[str, tuple[str, str]],
) -> None:
    proof = prove_internal_connector_tree(
        main_road_ids=main_ids,
        connector_road_ids=connector_ids,
        road_endpoints=endpoints,
    )
    if proof.hard_valid:
        proofs.setdefault(proof.connector_road_ids, proof)


def _road_endpoints(
    graph: nx.MultiGraph,
) -> dict[str, tuple[str, str]]:
    return {
        str(data["road_id"]): (str(source), str(target))
        for source, target, _, data in graph.edges(keys=True, data=True)
    }


def _component_road_ids(graph: nx.Graph) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                road_id
                for _, _, data in graph.edges(data=True)
                for road_id in data["road_ids"]
            }
        )
    )


def _physical_edge(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def _invalid_proof(
    main_ids: tuple[str, ...],
    connector_ids: tuple[str, ...],
    reason: str,
) -> InternalConnectorTreeProof:
    return InternalConnectorTreeProof(
        main_road_ids=main_ids,
        connector_road_ids=connector_ids,
        node_ids=(),
        leaf_node_ids=(),
        attachment_node_ids=(),
        external_leaf_node_ids=(),
        physical_edge_count=0,
        raw_road_count=len(connector_ids),
        hard_valid=False,
        invalid_reason=reason,
    )


__all__ = [
    "InternalConnectorTreeProof",
    "enumerate_internal_connector_trees",
    "prove_internal_connector_tree",
]
