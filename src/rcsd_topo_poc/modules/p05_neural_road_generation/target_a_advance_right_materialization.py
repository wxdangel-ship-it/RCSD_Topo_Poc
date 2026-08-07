from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_full_chain_ledger import (
    PreparedAutomaticInstruction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AttachmentEndpoint,
    AttachmentInstruction,
    AttachmentTargetKind,
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
class LockedEndpointAttachment:
    """One model-selected endpoint attachment for an AdvanceRight side."""

    side: AttachmentEndpoint
    parent_access_binding_id: str
    parent_source_road_id: str
    child_source_road_id: str
    child_endpoint: AttachmentEndpoint


def prepare_locked_endpoint_advance_right_instruction(
    *,
    plan: PlanCandidate,
    fallback_instruction: SegmentMaterializationInstruction,
    ordinary_instructions: Mapping[str, SegmentMaterializationInstruction],
    locked_attachments: Sequence[LockedEndpointAttachment],
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    coordinate_tolerance_m: float = 0.05,
) -> PreparedAutomaticInstruction:
    """Compile an endpoint-only AdvanceRight decision without choosing objects.

    The model has already selected the complete child Road set, both adjacent
    ordinary access Roads, both access bindings and both child endpoints. This
    compiler only copies whole source Roads and makes coincident endpoint
    attachment recipes executable. Interior parent splits, child Road pieces
    and mixed middle splices are deliberately rejected for a later
    split-capable compiler; the caller must then locally fallback this
    AdvanceRight Segment.
    """

    if coordinate_tolerance_m < 0:
        raise ValueError("coordinate tolerance must not be negative")
    plan.validate(advance_right=True)
    if plan.decision not in {
        SegmentDecision.USE_RCSD,
        SegmentDecision.KEEP_SWSD,
    }:
        raise ValueError(
            "endpoint AdvanceRight compiler does not implement a mixed splice"
        )
    if (
        fallback_instruction.segment_id != plan.segment_id
        or fallback_instruction.segment_type
        is not SegmentMaterializationType.ADVANCE_RIGHT
    ):
        raise ValueError(
            "fallback instruction does not describe this AdvanceRight Segment"
        )
    if not fallback_instruction.fallback_applied:
        raise ValueError(
            "AdvanceRight compiler requires an executed T01 fallback recipe"
        )

    adjacent = _adjacent_segment_ids(plan)
    by_side = _locked_attachments_by_side(locked_attachments)
    expected_access_ids = {
        AttachmentEndpoint.SOURCE: plan.source_access_road_id,
        AttachmentEndpoint.TARGET: plan.target_access_road_id,
    }
    source_condition = plan.source_condition
    if source_condition is None:
        raise ValueError("AdvanceRight plan lacks locked source conditions")
    expected_sources = {
        AttachmentEndpoint.SOURCE: source_condition[0],
        AttachmentEndpoint.TARGET: source_condition[1],
    }

    child_by_source: dict[tuple[RoadSource, str], RoadInstruction] = {}
    for road_use in plan.roads:
        if road_use.piece_id or road_use.split_position_m is not None:
            raise ValueError(
                "AdvanceRight Road pieces require a split-capable compiler"
            )
        source_key = (road_use.source_kind, road_use.source_road_id)
        source_road = source_roads.get(source_key)
        if source_road is None:
            raise ValueError(f"selected source Road is absent: {source_key}")
        if source_key in child_by_source:
            raise ValueError("selected AdvanceRight source Road is repeated")
        _require_source_endpoints(
            source_road,
            source_kind=road_use.source_kind,
            source_nodes=source_nodes,
        )
        instruction = RoadInstruction(
            instruction_id=(
                f"model-ar:{plan.segment_id}:{road_use.source_kind.value}:"
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
        child_by_source[source_key] = instruction

    attachment_instructions: list[AttachmentInstruction] = []
    claimed_child_endpoints: set[tuple[str, AttachmentEndpoint]] = set()
    for side in (AttachmentEndpoint.SOURCE, AttachmentEndpoint.TARGET):
        locked = by_side[side]
        expected_access_id = expected_access_ids[side]
        if (
            not expected_access_id
            or locked.parent_source_road_id != expected_access_id
        ):
            raise ValueError(
                "locked parent Road differs from the decoder-selected access Road"
            )
        adjacent_segment_id = (
            adjacent[0]
            if side is AttachmentEndpoint.SOURCE
            else adjacent[1]
        )
        ordinary = ordinary_instructions.get(adjacent_segment_id)
        if (
            ordinary is None
            or ordinary.segment_type is not SegmentMaterializationType.STANDARD
        ):
            raise ValueError(
                "locked AdvanceRight side lacks its adjacent ordinary instruction"
            )
        binding = _selected_binding(
            ordinary,
            binding_id=locked.parent_access_binding_id,
        )
        parent = _selected_parent_road(
            ordinary,
            binding=binding,
            source_road_id=locked.parent_source_road_id,
        )
        parent_source = _whole_source_kind(parent)
        if parent_source is not expected_sources[side]:
            raise ValueError(
                "locked parent Road source differs from the decoder condition"
            )
        parent_recipe, parent_position_m = _parent_endpoint(
            parent,
            binding=binding,
            source_roads=source_roads,
        )

        child_matches = [
            (source_key, instruction)
            for source_key, instruction in child_by_source.items()
            if source_key[1] == locked.child_source_road_id
        ]
        if len(child_matches) != 1:
            raise ValueError(
                "locked child endpoint does not identify one selected Road"
            )
        child_key, child = child_matches[0]
        child_claim = (child.instruction_id, locked.child_endpoint)
        if child_claim in claimed_child_endpoints:
            raise ValueError(
                "both AdvanceRight sides cannot claim the same child endpoint"
            )
        claimed_child_endpoints.add(child_claim)
        _validate_coincident_endpoint(
            child_key=child_key,
            child_endpoint=locked.child_endpoint,
            parent_recipe=parent_recipe,
            source_roads=source_roads,
            source_nodes=source_nodes,
            coordinate_tolerance_m=coordinate_tolerance_m,
        )
        child = _replace_endpoint_recipe(
            child,
            endpoint=locked.child_endpoint,
            recipe=parent_recipe,
        )
        child_by_source[child_key] = child

        if parent_source is RoadSource.RCSD:
            attachment = AttachmentInstruction(
                side=side,
                parent_access_binding_id=binding.binding_id,
                child_road_instruction_id=child.instruction_id,
                child_segment_id=plan.segment_id,
                child_endpoint=locked.child_endpoint,
                target_kind=AttachmentTargetKind.ROAD_POSITION,
                parent_road_instruction_id=parent.instruction_id,
                parent_position_m=parent_position_m,
            )
        else:
            if not parent_recipe.output_node_id:
                raise ValueError(
                    "SWSD side must reuse an explicit frozen access Node id"
                )
            attachment = AttachmentInstruction(
                side=side,
                parent_access_binding_id=binding.binding_id,
                child_road_instruction_id=child.instruction_id,
                child_segment_id=plan.segment_id,
                child_endpoint=locked.child_endpoint,
                target_kind=AttachmentTargetKind.FROZEN_ACCESS_NODE,
                target_node_id=parent_recipe.output_node_id,
            )
        attachment_instructions.append(attachment)

    ordered_children = tuple(
        child_by_source[key] for key in child_by_source
    )
    instruction = SegmentMaterializationInstruction(
        segment_id=plan.segment_id,
        segment_type=SegmentMaterializationType.ADVANCE_RIGHT,
        decision=plan.decision,
        roads=ordered_children,
        attachments=tuple(attachment_instructions),
        fallback_applied=False,
    )
    return PreparedAutomaticInstruction(plan.plan_id, instruction)


def _adjacent_segment_ids(plan: PlanCandidate) -> tuple[str, str]:
    pairs = {
        (
            str(recipe.get("source_segment_id") or ""),
            str(recipe.get("target_segment_id") or ""),
        )
        for recipe in plan.node_recipes
        if recipe.get("source_segment_id") or recipe.get("target_segment_id")
    }
    if len(pairs) != 1:
        raise ValueError(
            "AdvanceRight plan must identify one adjacent Segment pair"
        )
    source, target = next(iter(pairs))
    if not source or not target or source == target:
        raise ValueError("AdvanceRight adjacent Segment pair is invalid")
    return source, target


def _locked_attachments_by_side(
    rows: Sequence[LockedEndpointAttachment],
) -> dict[AttachmentEndpoint, LockedEndpointAttachment]:
    result: dict[AttachmentEndpoint, LockedEndpointAttachment] = {}
    for row in rows:
        if row.side in result:
            raise ValueError("AdvanceRight locked attachment side is duplicated")
        if (
            not row.parent_access_binding_id
            or not row.parent_source_road_id
            or not row.child_source_road_id
        ):
            raise ValueError("AdvanceRight locked attachment is incomplete")
        result[row.side] = row
    expected = {AttachmentEndpoint.SOURCE, AttachmentEndpoint.TARGET}
    if set(result) != expected:
        raise ValueError("AdvanceRight requires one locked attachment per side")
    return result


def _selected_binding(
    ordinary: SegmentMaterializationInstruction,
    *,
    binding_id: str,
) -> SegmentAccessBinding:
    rows = [
        binding
        for binding in ordinary.access_bindings
        if binding.binding_id == binding_id
    ]
    if len(rows) != 1 or rows[0].segment_id != ordinary.segment_id:
        raise ValueError(
            "locked parent binding is absent from the adjacent ordinary Segment"
        )
    return rows[0]


def _selected_parent_road(
    ordinary: SegmentMaterializationInstruction,
    *,
    binding: SegmentAccessBinding,
    source_road_id: str,
) -> RoadInstruction:
    rows = [
        road
        for road in ordinary.roads
        if road.instruction_id in binding.road_instruction_ids
        and source_road_id in _road_aliases(road)
    ]
    if len(rows) != 1:
        raise ValueError(
            "model-selected parent Road is not unique in the access binding"
        )
    return rows[0]


def _road_aliases(road: RoadInstruction) -> set[str]:
    return {
        value
        for value in (
            road.instruction_id,
            road.output_road_id,
            *(row.source_road_id for row in road.geometry_slices),
        )
        if value
    }


def _whole_source_kind(road: RoadInstruction) -> RoadSource:
    if (
        len(road.geometry_slices) != 1
        or road.join_modes
        or road.geometry_slices[0].start_position_m != 0.0
        or road.geometry_slices[0].end_position_m is not None
        or road.geometry_slices[0].reverse_geometry
    ):
        raise ValueError(
            "endpoint compiler requires a whole, non-reversed parent Road"
        )
    return road.geometry_slices[0].source_kind


def _parent_endpoint(
    road: RoadInstruction,
    *,
    binding: SegmentAccessBinding,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
) -> tuple[NodeRecipe, float]:
    source_match = road.source_node_recipe in binding.node_recipes
    target_match = road.target_node_recipe in binding.node_recipes
    if source_match == target_match:
        raise ValueError(
            "selected parent Road does not have one endpoint in the access binding"
        )
    source_slice = road.geometry_slices[0]
    source = source_roads.get(source_slice.source_key)
    if source is None:
        raise ValueError("selected parent source Road is absent")
    if source_match:
        return road.source_node_recipe, 0.0
    return road.target_node_recipe, float(source.geometry.length)


def _validate_coincident_endpoint(
    *,
    child_key: tuple[RoadSource, str],
    child_endpoint: AttachmentEndpoint,
    parent_recipe: NodeRecipe,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    coordinate_tolerance_m: float,
) -> None:
    if parent_recipe.kind is not NodeRecipeKind.COPY_SOURCE_NODE:
        raise ValueError(
            "endpoint compiler requires a copied parent access Node"
        )
    parent_node = source_nodes.get(
        (parent_recipe.source_kind, parent_recipe.source_node_id)
    )
    child_road = source_roads[child_key]
    child_node_id = (
        child_road.start_node_id
        if child_endpoint is AttachmentEndpoint.SOURCE
        else child_road.end_node_id
    )
    child_node = source_nodes.get((child_key[0], child_node_id))
    if parent_node is None or child_node is None:
        raise ValueError("attachment endpoint source Node is absent")
    if (
        parent_node.geometry.distance(child_node.geometry)
        > coordinate_tolerance_m
    ):
        raise ValueError(
            "endpoint attachment is not geometrically coincident"
        )


def _replace_endpoint_recipe(
    road: RoadInstruction,
    *,
    endpoint: AttachmentEndpoint,
    recipe: NodeRecipe,
) -> RoadInstruction:
    if endpoint is AttachmentEndpoint.SOURCE:
        return replace(road, source_node_recipe=recipe)
    return replace(road, target_node_recipe=recipe)


def _require_source_endpoints(
    road: SourceRoadRecord,
    *,
    source_kind: RoadSource,
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
) -> None:
    for node_id in (road.start_node_id, road.end_node_id):
        if (source_kind, node_id) not in source_nodes:
            raise ValueError(
                f"selected source Road endpoint Node is absent: {node_id}"
            )


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
    "LockedEndpointAttachment",
    "prepare_locked_endpoint_advance_right_instruction",
]
