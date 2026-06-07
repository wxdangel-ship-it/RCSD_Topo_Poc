from __future__ import annotations

from typing import Any

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    Step1GraphContext,
    _normalize_mainnodeid,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
)


MAX_DUAL_CARRIAGEWAY_NEAR_GATE_RELAXATION_M = 10.0


def _semantic_node_internal_width_m(node_id: str, context: Step1GraphContext) -> float:
    semantic_node = context.semantic_nodes.get(node_id)
    if semantic_node is None or len(semantic_node.member_node_ids) < 2:
        return 0.0
    geometries = [
        context.physical_nodes[member_node_id].geometry
        for member_node_id in semantic_node.member_node_ids
        if member_node_id in context.physical_nodes
    ]
    max_distance_m = 0.0
    for index, left_geometry in enumerate(geometries):
        for right_geometry in geometries[index + 1 :]:
            max_distance_m = max(max_distance_m, float(left_geometry.distance(right_geometry)))
    return max_distance_m


def _dual_separation_gate_limit_m(pair: PairRecord, context: Step1GraphContext) -> float:
    return max(
        MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
        _semantic_node_internal_width_m(pair.a_node_id, context),
        _semantic_node_internal_width_m(pair.b_node_id, context),
    )


def _dual_separation_support_info(
    candidate: Any,
    *,
    gate_limit_m: float = MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
) -> dict[str, Any]:
    return {
        "dual_carriageway_separation_gate_limit_m": gate_limit_m,
        "dual_carriageway_base_gate_limit_m": MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
        "dual_carriageway_max_separation_m": (
            candidate.max_dual_carriageway_separation_m if candidate is not None else None
        ),
    }


def _semantic_group_node_id(node_id: str, context: Step1GraphContext) -> str:
    node = context.semantic_nodes.get(node_id)
    if node is None:
        return node_id
    return _normalize_mainnodeid(node.raw_properties.get("mainnodeid")) or node_id


def _split_pair_support_near_gate_candidates(
    pair: PairRecord,
    candidates: list[Any],
    *,
    gate_limit_m: float,
) -> tuple[list[Any], list[Any]]:
    support_road_ids = set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids)
    if not support_road_ids:
        return [], candidates
    relaxed_limit_m = gate_limit_m + MAX_DUAL_CARRIAGEWAY_NEAR_GATE_RELAXATION_M
    passed: list[Any] = []
    failed: list[Any] = []
    for candidate in candidates:
        if set(candidate.road_ids) == support_road_ids and candidate.max_dual_carriageway_separation_m <= relaxed_limit_m:
            passed.append(candidate)
        else:
            failed.append(candidate)
    return passed, failed
