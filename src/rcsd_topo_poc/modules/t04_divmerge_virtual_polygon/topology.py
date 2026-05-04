from __future__ import annotations

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step3_topology_skeleton import (
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
    status_doc = build_unit_step3_status_doc(
        admission=admission,
        topology_skeleton=topology_skeleton,
        topology_scope="case_coordination",
        unit_population_node_ids=tuple(topology_skeleton.branch_result.member_node_ids),
        context_augmented_node_ids=tuple(
            node_id
            for node_id in topology_skeleton.branch_result.augmented_member_node_ids
            if node_id not in set(topology_skeleton.branch_result.member_node_ids)
        ),
        event_branch_ids=(),
        boundary_branch_ids=(),
        preferred_axis_branch_id=None,
        degraded_scope_reason=None,
    )
    status_doc["swsd_semantic_junction"] = topology_skeleton.swsd_semantic_junction.to_status_doc()
    return status_doc


def _swsd_arm_view_for_unit(
    *,
    topology_skeleton,
    event_branch_ids,
    boundary_branch_ids,
) -> tuple[str, list[str], list[str]]:
    swsd_junction = topology_skeleton.swsd_semantic_junction
    active_branch_ids = {
        str(branch_id)
        for branch_id in (*tuple(event_branch_ids or ()), *tuple(boundary_branch_ids or ()))
        if str(branch_id)
    }
    unit_owned_arm_ids: list[str] = []
    sibling_unit_arm_ids: list[str] = []
    for arm in swsd_junction.semantic_arms:
        target = unit_owned_arm_ids if str(arm.first_branch_id) in active_branch_ids else sibling_unit_arm_ids
        target.append(str(arm.arm_id))
    return (
        str(swsd_junction.junction_id),
        sorted(unit_owned_arm_ids),
        sorted(sibling_unit_arm_ids),
    )


def build_unit_step3_status_doc(
    *,
    admission,
    topology_skeleton,
    topology_scope: str,
    unit_population_node_ids,
    context_augmented_node_ids,
    event_branch_ids,
    boundary_branch_ids,
    preferred_axis_branch_id,
    degraded_scope_reason,
    explicit_branch_ids=None,
    explicit_main_branch_ids=None,
    explicit_input_branch_ids=None,
    explicit_output_branch_ids=None,
    branch_road_memberships=None,
    branch_bridge_node_ids=None,
) -> dict:
    branch_result = topology_skeleton.branch_result
    road_branches = list(branch_result.road_branches)
    branch_ids = (
        list(explicit_branch_ids)
        if explicit_branch_ids is not None
        else list(branch_result.road_branch_ids)
    )
    main_branch_ids = (
        list(explicit_main_branch_ids)
        if explicit_main_branch_ids is not None
        else list(branch_result.main_branch_ids)
    )
    input_branch_ids = (
        list(explicit_input_branch_ids)
        if explicit_input_branch_ids is not None
        else sorted(str(branch.branch_id) for branch in road_branches if getattr(branch, "has_incoming_support", False))
    )
    output_branch_ids = (
        list(explicit_output_branch_ids)
        if explicit_output_branch_ids is not None
        else sorted(str(branch.branch_id) for branch in road_branches if getattr(branch, "has_outgoing_support", False))
    )
    unstable_reasons = tuple(topology_skeleton.stability.unstable_reasons)
    swsd_junction_ref, unit_owned_arm_ids, sibling_unit_arm_ids = _swsd_arm_view_for_unit(
        topology_skeleton=topology_skeleton,
        event_branch_ids=event_branch_ids,
        boundary_branch_ids=boundary_branch_ids,
    )
    return {
        "scope": "t04_step3_topology_skeleton",
        "topology_scope": topology_scope,
        "mainnodeid": admission.mainnodeid,
        "representative_node_id": admission.representative_node_id,
        "branch_count": len(branch_ids),
        "member_node_ids": list(branch_result.member_node_ids),
        "unit_population_node_ids": list(unit_population_node_ids),
        "context_augmented_node_ids": list(context_augmented_node_ids),
        "augmented_member_node_ids": list(branch_result.augmented_member_node_ids),
        "passthrough_node_ids": list(branch_result.through_node_candidate_ids),
        "branch_ids": list(branch_ids),
        "main_branch_ids": list(main_branch_ids),
        "input_branch_ids": input_branch_ids,
        "output_branch_ids": output_branch_ids,
        "event_branch_ids": list(event_branch_ids),
        "boundary_branch_ids": list(boundary_branch_ids),
        "preferred_axis_branch_id": preferred_axis_branch_id,
        "branch_road_memberships": {
            str(branch_id): list(road_ids)
            for branch_id, road_ids in (branch_road_memberships or {}).items()
        },
        "branch_bridge_node_ids": {
            str(branch_id): list(node_ids)
            for branch_id, node_ids in (branch_bridge_node_ids or {}).items()
        },
        "is_in_continuous_chain": topology_skeleton.chain_context.is_in_continuous_chain,
        "related_mainnodeids": list(topology_skeleton.chain_context.related_mainnodeids),
        "unstable_reasons": list(unstable_reasons),
        "degraded_scope_reason": degraded_scope_reason,
        "swsd_junction_ref": swsd_junction_ref,
        "unit_owned_arm_ids": unit_owned_arm_ids,
        "sibling_unit_arm_ids": sibling_unit_arm_ids,
        "step3_state": "review_required" if unstable_reasons else "ready",
    }
