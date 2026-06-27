from __future__ import annotations

from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    Step1GraphContext,
)


def counterclockwise_mixed_kind_wedge_gate_info(
    pair: PairRecord,
    *,
    candidate: Any,
    context: Step1GraphContext,
) -> Optional[dict[str, Any]]:
    _ = pair
    if candidate.is_bidirectional_minimal_loop or candidate.is_semantic_node_group_closure:
        return None
    if len(candidate.road_ids) != 3:
        return None

    path_lengths = sorted((len(candidate.forward_path.road_ids), len(candidate.reverse_path.road_ids)))
    if path_lengths != [1, 2]:
        return None

    short_path = candidate.forward_path if len(candidate.forward_path.road_ids) == 1 else candidate.reverse_path
    long_path = candidate.reverse_path if short_path is candidate.forward_path else candidate.forward_path
    if len(long_path.node_ids) != 3 or len(set(long_path.node_ids[1:-1])) != 1:
        return None

    short_road_id = short_path.road_ids[0]
    short_road = context.roads.get(short_road_id)
    if short_road is None:
        return None
    short_kind = int(short_road.road_kind or 0)
    if short_kind < 3:
        return None

    long_road_ids = tuple(long_path.road_ids)
    long_road_kinds = []
    for road_id in long_road_ids:
        road = context.roads.get(road_id)
        if road is None:
            return None
        long_road_kinds.append(int(road.road_kind or 0))
    if set(long_road_kinds) != {2}:
        return None

    return {
        "counterclockwise_mixed_kind_wedge_blocked": True,
        "counterclockwise_mixed_kind_wedge_direct_road_id": short_road_id,
        "counterclockwise_mixed_kind_wedge_direct_road_kind": short_kind,
        "counterclockwise_mixed_kind_wedge_detour_road_ids": list(long_road_ids),
        "counterclockwise_mixed_kind_wedge_detour_road_kinds": long_road_kinds,
        "counterclockwise_mixed_kind_wedge_internal_node_id": long_path.node_ids[1],
    }
