from __future__ import annotations

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step3_topology_skeleton import (
    _build_stage4_topology_skeleton,
)


def build_step3_topology(
    *,
    representative_node,
    group_nodes,
    local_context,
):
    return _build_stage4_topology_skeleton(
        representative_node=representative_node,
        group_nodes=list(group_nodes),
        local_nodes=list(local_context.local_nodes),
        local_roads=list(local_context.local_roads),
        drivezone_union=local_context.drivezone_union,
        support_center=local_context.seed_center,
    )


def build_step3_status_doc(*, admission, topology_skeleton) -> dict:
    branch_result = topology_skeleton.branch_result
    road_branches = list(branch_result.road_branches)
    input_branch_ids = sorted(str(branch.branch_id) for branch in road_branches if getattr(branch, "has_incoming_support", False))
    output_branch_ids = sorted(str(branch.branch_id) for branch in road_branches if getattr(branch, "has_outgoing_support", False))
    unstable_reasons = tuple(topology_skeleton.stability.unstable_reasons)
    return {
        "scope": "t04_step3_topology_skeleton",
        "mainnodeid": admission.mainnodeid,
        "representative_node_id": admission.representative_node_id,
        "branch_count": len(branch_result.road_branches),
        "member_node_ids": list(branch_result.member_node_ids),
        "augmented_member_node_ids": list(branch_result.augmented_member_node_ids),
        "passthrough_node_ids": list(branch_result.through_node_candidate_ids),
        "branch_ids": list(branch_result.road_branch_ids),
        "main_branch_ids": list(branch_result.main_branch_ids),
        "input_branch_ids": input_branch_ids,
        "output_branch_ids": output_branch_ids,
        "is_in_continuous_chain": topology_skeleton.chain_context.is_in_continuous_chain,
        "related_mainnodeids": list(topology_skeleton.chain_context.related_mainnodeids),
        "unstable_reasons": list(unstable_reasons),
        "step3_state": "review_required" if unstable_reasons else "ready",
    }

