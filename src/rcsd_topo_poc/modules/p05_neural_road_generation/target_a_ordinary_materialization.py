from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_full_chain_ledger import (
    PreparedAutomaticInstruction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    GeometrySlice,
    NodeRecipe,
    NodeRecipeKind,
    RoadInstruction,
    SegmentAccessBinding,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
    SourceNodeRecord,
    SourceRoadRecord,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    PlanCandidate,
    RoadSource,
    SegmentDecision,
)


@dataclass(frozen=True)
class LockedAccessNode:
    """A Node object already selected by the independent anchor model."""

    source_kind: RoadSource
    source_node_id: str


def prepare_locked_node_ordinary_instruction(
    *,
    plan: PlanCandidate,
    fallback_instruction: SegmentMaterializationInstruction,
    locked_access_nodes: Mapping[str, tuple[LockedAccessNode, ...]],
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
) -> PreparedAutomaticInstruction:
    """Compile an anchored whole-Road ordinary plan into an executable recipe.

    This compiler covers the no-break path: every final Road is one complete
    source Road and every frozen access relation is represented by Node objects
    already locked by the anchor model. It does not infer anchor objects,
    choose Roads, split geometry or repair incomplete evidence.
    """

    plan.validate()
    if plan.decision not in {
        SegmentDecision.USE_RCSD,
        SegmentDecision.T06_MAIN_RCSD_ATTACHED_SWSD,
    }:
        raise ValueError("locked-Node compiler requires an automatic RCSD plan")
    if (
        fallback_instruction.segment_id != plan.segment_id
        or fallback_instruction.segment_type
        is not SegmentMaterializationType.STANDARD
    ):
        raise ValueError("fallback instruction does not describe this ordinary Segment")
    if not fallback_instruction.fallback_applied:
        raise ValueError("ordinary compiler requires an executed T01 fallback recipe")
    expected_access = {
        binding.access_node_id for binding in fallback_instruction.access_bindings
    }
    if set(locked_access_nodes) != expected_access:
        raise ValueError(
            "locked access Nodes differ from the frozen access relations: "
            f"missing={sorted(expected_access - set(locked_access_nodes))}, "
            f"extra={sorted(set(locked_access_nodes) - expected_access)}"
        )

    road_instructions = []
    instruction_by_source: dict[
        tuple[RoadSource, str], RoadInstruction
    ] = {}
    for road_use in plan.roads:
        if road_use.piece_id or road_use.split_position_m is not None:
            raise ValueError(
                "Road split requires an explicit split-capable compiler"
            )
        source_key = (road_use.source_kind, road_use.source_road_id)
        source_road = source_roads.get(source_key)
        if source_road is None:
            raise ValueError(
                f"selected source Road is absent: {source_key}"
            )
        if source_key in instruction_by_source:
            raise ValueError("selected source Road is repeated in the plan")
        for node_id in (source_road.start_node_id, source_road.end_node_id):
            if (road_use.source_kind, node_id) not in source_nodes:
                raise ValueError(
                    f"selected source Road endpoint Node is absent: {node_id}"
                )
        instruction = RoadInstruction(
            instruction_id=(
                f"model:{plan.segment_id}:{road_use.source_kind.value}:"
                f"{road_use.source_road_id}"
            ),
            owner_segment_id=road_use.owner_segment_id,
            role=road_use.role,
            direction=source_road.direction,
            geometry_slices=(
                GeometrySlice(
                    source_kind=road_use.source_kind,
                    source_road_id=road_use.source_road_id,
                ),
            ),
            source_node_recipe=_copy_node_recipe(
                road_use.source_kind,
                source_road.start_node_id,
            ),
            target_node_recipe=_copy_node_recipe(
                road_use.source_kind,
                source_road.end_node_id,
            ),
            output_road_id=road_use.source_road_id,
        )
        road_instructions.append(instruction)
        instruction_by_source[source_key] = instruction

    fallback_by_access = {
        binding.access_node_id: binding
        for binding in fallback_instruction.access_bindings
    }
    access_bindings = []
    for access_node_id in sorted(expected_access):
        locked_nodes = locked_access_nodes[access_node_id]
        if not locked_nodes or len(locked_nodes) != len(set(locked_nodes)):
            raise ValueError("locked access Node set must be nonempty and unique")
        missing_nodes = [
            node
            for node in locked_nodes
            if (node.source_kind, node.source_node_id) not in source_nodes
        ]
        if missing_nodes:
            raise ValueError(
                f"locked access Node is absent: {missing_nodes[0]}"
            )
        incident_instruction_ids = []
        covered_nodes: set[LockedAccessNode] = set()
        for road_use in plan.roads:
            source_road = source_roads[
                (road_use.source_kind, road_use.source_road_id)
            ]
            incident_nodes = {
                LockedAccessNode(
                    road_use.source_kind,
                    source_road.start_node_id,
                ),
                LockedAccessNode(
                    road_use.source_kind,
                    source_road.end_node_id,
                ),
            }
            overlap = incident_nodes & set(locked_nodes)
            if not overlap:
                continue
            covered_nodes.update(overlap)
            incident_instruction_ids.append(
                instruction_by_source[
                    (road_use.source_kind, road_use.source_road_id)
                ].instruction_id
            )
        if covered_nodes != set(locked_nodes):
            raise ValueError(
                "a locked access Node is not incident to the selected Road plan"
            )
        frozen_binding = fallback_by_access[access_node_id]
        access_bindings.append(
            SegmentAccessBinding(
                binding_id=frozen_binding.binding_id,
                segment_id=plan.segment_id,
                access_node_id=access_node_id,
                structural_role=frozen_binding.structural_role,
                direction_role=frozen_binding.direction_role,
                road_instruction_ids=tuple(sorted(incident_instruction_ids)),
                node_recipes=tuple(
                    _copy_node_recipe(node.source_kind, node.source_node_id)
                    for node in locked_nodes
                ),
            )
        )
    instruction = SegmentMaterializationInstruction(
        segment_id=plan.segment_id,
        segment_type=SegmentMaterializationType.STANDARD,
        decision=plan.decision,
        roads=tuple(road_instructions),
        access_bindings=tuple(access_bindings),
        fallback_applied=False,
    )
    return PreparedAutomaticInstruction(plan.plan_id, instruction)


def _copy_node_recipe(
    source_kind: RoadSource,
    node_id: str,
) -> NodeRecipe:
    return NodeRecipe(
        kind=NodeRecipeKind.COPY_SOURCE_NODE,
        source_kind=source_kind,
        source_node_id=node_id,
    )


__all__ = [
    "LockedAccessNode",
    "prepare_locked_node_ordinary_instruction",
]
