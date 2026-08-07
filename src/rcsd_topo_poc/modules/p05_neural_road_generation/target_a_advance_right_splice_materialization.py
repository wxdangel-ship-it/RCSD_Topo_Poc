from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_full_chain_ledger import (
    PreparedAutomaticInstruction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessStructuralRole,
    AttachmentEndpoint,
    AttachmentInstruction,
    AttachmentTargetKind,
    GeometryJoinMode,
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
    RoadRole,
    RoadSource,
    SegmentDecision,
)


class AttachmentOperation(str, Enum):
    REUSE_ENDPOINT = "REUSE_ENDPOINT"
    SPLIT_ROAD = "SPLIT_ROAD"


class ParentPiece(str, Enum):
    SOURCE_PART = "SOURCE_PART"
    TARGET_PART = "TARGET_PART"


@dataclass(frozen=True)
class LockedRoadAttachment:
    """One model-selected parent Road position and child endpoint."""

    side: AttachmentEndpoint
    parent_access_binding_id: str
    parent_source_road_id: str
    parent_fraction: float
    operation: AttachmentOperation
    parent_piece: ParentPiece | None
    child_source_kind: RoadSource
    child_source_road_id: str
    child_endpoint: AttachmentEndpoint


@dataclass(frozen=True)
class LockedMiddleSplice:
    """Model-selected RCSD/SWSD Road pair, positions and final direction."""

    rcsd_source_road_id: str
    swsd_source_road_id: str
    rcsd_fraction: float
    swsd_fraction: float
    direction: int


@dataclass(frozen=True)
class PreparedMixedSpliceExecution:
    """AdvanceRight instruction plus adjacent ordinary split replacements."""

    advance_right: PreparedAutomaticInstruction
    ordinary_replacements: tuple[
        tuple[str, SegmentMaterializationInstruction], ...
    ]


@dataclass(frozen=True)
class _ParentContext:
    ordinary: SegmentMaterializationInstruction
    binding: SegmentAccessBinding
    parent_road: RoadInstruction
    parent_position_m: float
    final_node_recipe: NodeRecipe
    source_kind: RoadSource


def prepare_mixed_splice_advance_right_execution(
    *,
    plan: PlanCandidate,
    fallback_instruction: SegmentMaterializationInstruction,
    ordinary_instructions: Mapping[str, SegmentMaterializationInstruction],
    locked_attachments: Sequence[LockedRoadAttachment],
    middle_splice: LockedMiddleSplice,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    coordinate_tolerance_m: float = 0.05,
) -> PreparedMixedSpliceExecution:
    """Execute the model-defined AdvanceRight mixed-source splice recipe.

    The model supplies both source Roads, both retained fractions, both parent
    access Roads and positions, the final parent piece at an interior split,
    both child endpoints and the final direction. This compiler may partition
    the already selected ordinary carrier Road and write straight connectors
    between those declared positions. It never chooses an object or changes a
    Segment, role, owner, source condition or fallback scope.
    """

    if coordinate_tolerance_m < 0:
        raise ValueError("coordinate tolerance must not be negative")
    plan.validate(advance_right=True)
    if plan.decision is not SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE:
        raise ValueError("mixed splice compiler requires its dedicated decision")
    if (
        fallback_instruction.segment_id != plan.segment_id
        or fallback_instruction.segment_type
        is not SegmentMaterializationType.ADVANCE_RIGHT
        or not fallback_instruction.fallback_applied
    ):
        raise ValueError(
            "fallback instruction does not describe this AdvanceRight Segment"
        )
    if middle_splice.direction not in {0, 1, 2, 3}:
        raise ValueError("mixed splice final direction is outside the formal enum")

    adjacent = _adjacent_segment_ids(plan)
    by_side = _attachments_by_side(locked_attachments)
    expected_access_ids = {
        AttachmentEndpoint.SOURCE: plan.source_access_road_id,
        AttachmentEndpoint.TARGET: plan.target_access_road_id,
    }
    source_condition = plan.source_condition
    if source_condition is None or set(source_condition) != {
        RoadSource.RCSD,
        RoadSource.SWSD,
    }:
        raise ValueError("mixed splice requires one RCSD and one SWSD access side")
    expected_sources = {
        AttachmentEndpoint.SOURCE: source_condition[0],
        AttachmentEndpoint.TARGET: source_condition[1],
    }

    updated_ordinary = {
        segment_id: instruction
        for segment_id, instruction in ordinary_instructions.items()
    }
    parent_contexts: dict[AttachmentEndpoint, _ParentContext] = {}
    for side in (AttachmentEndpoint.SOURCE, AttachmentEndpoint.TARGET):
        locked = by_side[side]
        if locked.parent_source_road_id != expected_access_ids[side]:
            raise ValueError(
                "locked parent Road differs from the decoder-selected access Road"
            )
        adjacent_segment_id = (
            adjacent[0]
            if side is AttachmentEndpoint.SOURCE
            else adjacent[1]
        )
        ordinary = updated_ordinary.get(adjacent_segment_id)
        if ordinary is None:
            raise ValueError(
                "mixed splice lacks an adjacent ordinary instruction"
            )
        context = _prepare_parent_context(
            ordinary,
            locked=locked,
            expected_source=expected_sources[side],
            source_roads=source_roads,
            coordinate_tolerance_m=coordinate_tolerance_m,
        )
        updated_ordinary[adjacent_segment_id] = context.ordinary
        parent_contexts[side] = context

    plan_road_keys = {
        (road.source_kind, road.source_road_id): road for road in plan.roads
    }
    if len(plan_road_keys) != len(plan.roads):
        raise ValueError("mixed splice plan repeats a source Road")
    rcsd_key = (RoadSource.RCSD, middle_splice.rcsd_source_road_id)
    swsd_key = (RoadSource.SWSD, middle_splice.swsd_source_road_id)
    if rcsd_key not in plan_road_keys or swsd_key not in plan_road_keys:
        raise ValueError("middle splice Roads differ from the selected plan")
    for source_key in plan_road_keys:
        source = source_roads.get(source_key)
        if source is None:
            raise ValueError(f"selected source Road is absent: {source_key}")
        _require_source_endpoints(
            source,
            source_kind=source_key[0],
            source_nodes=source_nodes,
        )

    for side, source_key in (
        (AttachmentEndpoint.SOURCE, _side_child_key(by_side, AttachmentEndpoint.SOURCE)),
        (AttachmentEndpoint.TARGET, _side_child_key(by_side, AttachmentEndpoint.TARGET)),
    ):
        expected_key = (
            rcsd_key
            if expected_sources[side] is RoadSource.RCSD
            else swsd_key
        )
        if source_key != expected_key:
            raise ValueError(
                "locked child Road differs from its source-conditioned splice Road"
            )

    source_attachment = by_side[AttachmentEndpoint.SOURCE]
    target_attachment = by_side[AttachmentEndpoint.TARGET]
    first_key = _side_child_key(by_side, AttachmentEndpoint.SOURCE)
    second_key = _side_child_key(by_side, AttachmentEndpoint.TARGET)
    first_fraction = _splice_fraction(first_key[0], middle_splice)
    second_fraction = _splice_fraction(second_key[0], middle_splice)
    first_slice = _slice_from_endpoint_to_fraction(
        first_key,
        endpoint=source_attachment.child_endpoint,
        fraction=first_fraction,
        source_roads=source_roads,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    second_slice = _slice_from_fraction_to_endpoint(
        second_key,
        endpoint=target_attachment.child_endpoint,
        fraction=second_fraction,
        source_roads=source_roads,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    source_context = parent_contexts[AttachmentEndpoint.SOURCE]
    target_context = parent_contexts[AttachmentEndpoint.TARGET]
    source_join_mode = _endpoint_join_mode(
        child_key=first_key,
        child_endpoint=source_attachment.child_endpoint,
        parent_recipe=source_context.final_node_recipe,
        source_roads=source_roads,
        source_nodes=source_nodes,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    target_join_mode = _endpoint_join_mode(
        child_key=second_key,
        child_endpoint=target_attachment.child_endpoint,
        parent_recipe=target_context.final_node_recipe,
        source_roads=source_roads,
        source_nodes=source_nodes,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    composite_id = (
        f"model-ar-splice:{plan.segment_id}:"
        f"{middle_splice.rcsd_source_road_id}:"
        f"{middle_splice.swsd_source_road_id}"
    )
    composite = RoadInstruction(
        instruction_id=composite_id,
        owner_segment_id=plan.segment_id,
        role=RoadRole.ADVANCE_RIGHT,
        direction=middle_splice.direction,
        geometry_slices=(first_slice, second_slice),
        source_node_recipe=source_context.final_node_recipe,
        target_node_recipe=target_context.final_node_recipe,
        join_modes=(GeometryJoinMode.STRAIGHT_CONNECTOR,),
        source_endpoint_join_mode=source_join_mode,
        target_endpoint_join_mode=target_join_mode,
    )

    remaining = []
    for source_key, road_use in plan_road_keys.items():
        if source_key in {rcsd_key, swsd_key}:
            continue
        source = source_roads[source_key]
        remaining.append(
            RoadInstruction(
                instruction_id=(
                    f"model-ar:{plan.segment_id}:{source_key[0].value}:"
                    f"{source_key[1]}"
                ),
                owner_segment_id=road_use.owner_segment_id,
                role=road_use.role,
                direction=source.direction,
                geometry_slices=(GeometrySlice(*source_key),),
                source_node_recipe=_copy_node_recipe(
                    source_key[0],
                    source.start_node_id,
                ),
                target_node_recipe=_copy_node_recipe(
                    source_key[0],
                    source.end_node_id,
                ),
                output_road_id=source_key[1],
            )
        )

    attachments = tuple(
        _attachment_instruction(
            side=side,
            child_instruction_id=composite_id,
            child_endpoint=(
                AttachmentEndpoint.SOURCE
                if side is AttachmentEndpoint.SOURCE
                else AttachmentEndpoint.TARGET
            ),
            child_segment_id=plan.segment_id,
            context=parent_contexts[side],
        )
        for side in (AttachmentEndpoint.SOURCE, AttachmentEndpoint.TARGET)
    )
    instruction = SegmentMaterializationInstruction(
        segment_id=plan.segment_id,
        segment_type=SegmentMaterializationType.ADVANCE_RIGHT,
        decision=plan.decision,
        roads=(composite, *remaining),
        attachments=attachments,
        fallback_applied=False,
    )
    replacements = tuple(
        (segment_id, updated_ordinary[segment_id])
        for segment_id in adjacent
        if updated_ordinary[segment_id]
        != ordinary_instructions[segment_id]
    )
    return PreparedMixedSpliceExecution(
        advance_right=PreparedAutomaticInstruction(plan.plan_id, instruction),
        ordinary_replacements=replacements,
    )


def _prepare_parent_context(
    ordinary: SegmentMaterializationInstruction,
    *,
    locked: LockedRoadAttachment,
    expected_source: RoadSource,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    coordinate_tolerance_m: float,
) -> _ParentContext:
    if ordinary.segment_type is not SegmentMaterializationType.STANDARD:
        raise ValueError("AdvanceRight parent must be an ordinary Segment")
    binding = _selected_binding(
        ordinary,
        binding_id=locked.parent_access_binding_id,
    )
    parent = _selected_parent_road(
        ordinary,
        binding=binding,
        source_road_id=locked.parent_source_road_id,
    )
    source_kind, source = _whole_source_record(
        parent,
        source_roads=source_roads,
    )
    if source_kind is not expected_source:
        raise ValueError(
            "locked parent Road source differs from the decoder condition"
        )
    fraction = float(locked.parent_fraction)
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("parent attachment fraction is outside [0, 1]")
    position = fraction * float(source.geometry.length)
    endpoint_tolerance = max(
        coordinate_tolerance_m,
        float(source.geometry.length) * 1e-9,
    )
    at_source = position <= endpoint_tolerance
    at_target = (
        float(source.geometry.length) - position <= endpoint_tolerance
    )
    if at_source or at_target:
        if locked.operation is not AttachmentOperation.REUSE_ENDPOINT:
            raise ValueError("endpoint attachment must use REUSE_ENDPOINT")
        if locked.parent_piece is not None:
            raise ValueError("endpoint attachment must not select a split piece")
        recipe = (
            parent.source_node_recipe
            if at_source
            else parent.target_node_recipe
        )
        if recipe not in binding.node_recipes:
            raise ValueError(
                "selected parent endpoint is outside its access binding"
            )
        return _ParentContext(
            ordinary,
            binding,
            parent,
            0.0 if at_source else float(source.geometry.length),
            recipe,
            source_kind,
        )

    if locked.operation is not AttachmentOperation.SPLIT_ROAD:
        raise ValueError("interior parent attachment must use SPLIT_ROAD")
    if source_kind is not RoadSource.RCSD:
        raise ValueError("SWSD parent side must reuse a frozen endpoint")
    if locked.parent_piece is None:
        raise ValueError("interior split must select its final parent piece")
    if binding.structural_role is not AccessStructuralRole.ADVANCE_RIGHT_ATTACHMENT:
        raise ValueError(
            "interior split requires a frozen AdvanceRight attachment relation"
        )
    split_recipe = NodeRecipe(
        kind=NodeRecipeKind.INTERPOLATE_SOURCE_ROAD,
        source_kind=source_kind,
        source_road_id=source.source_road_id,
        position_m=position,
    )
    source_piece, target_piece = _split_parent_road(
        parent,
        split_recipe=split_recipe,
        position_m=position,
    )
    updated_bindings = tuple(
        _replace_parent_in_binding(
            row,
            selected_binding_id=binding.binding_id,
            original=parent,
            source_piece=source_piece,
            target_piece=target_piece,
            split_recipe=split_recipe,
        )
        for row in ordinary.access_bindings
    )
    updated_roads = []
    for row in ordinary.roads:
        if row.instruction_id == parent.instruction_id:
            updated_roads.extend((source_piece, target_piece))
        else:
            updated_roads.append(row)
    updated = replace(
        ordinary,
        roads=tuple(updated_roads),
        access_bindings=updated_bindings,
    )
    updated_binding = _selected_binding(
        updated,
        binding_id=binding.binding_id,
    )
    selected_parent = (
        source_piece
        if locked.parent_piece is ParentPiece.SOURCE_PART
        else target_piece
    )
    selected_position = (
        position
        if locked.parent_piece is ParentPiece.SOURCE_PART
        else 0.0
    )
    return _ParentContext(
        updated,
        updated_binding,
        selected_parent,
        selected_position,
        split_recipe,
        source_kind,
    )


def _split_parent_road(
    original: RoadInstruction,
    *,
    split_recipe: NodeRecipe,
    position_m: float,
) -> tuple[RoadInstruction, RoadInstruction]:
    source_slice = original.geometry_slices[0]
    token = f"{position_m:.6f}".replace(".", "_")
    source_piece = replace(
        original,
        instruction_id=f"{original.instruction_id}:split:source:{token}",
        geometry_slices=(
            GeometrySlice(
                source_slice.source_kind,
                source_slice.source_road_id,
                end_position_m=position_m,
            ),
        ),
        target_node_recipe=split_recipe,
        target_endpoint_join_mode=GeometryJoinMode.COINCIDENT_ONLY,
        output_road_id="",
    )
    target_piece = replace(
        original,
        instruction_id=f"{original.instruction_id}:split:target:{token}",
        geometry_slices=(
            GeometrySlice(
                source_slice.source_kind,
                source_slice.source_road_id,
                start_position_m=position_m,
            ),
        ),
        source_node_recipe=split_recipe,
        source_endpoint_join_mode=GeometryJoinMode.COINCIDENT_ONLY,
        output_road_id="",
    )
    return source_piece, target_piece


def _replace_parent_in_binding(
    binding: SegmentAccessBinding,
    *,
    selected_binding_id: str,
    original: RoadInstruction,
    source_piece: RoadInstruction,
    target_piece: RoadInstruction,
    split_recipe: NodeRecipe,
) -> SegmentAccessBinding:
    if original.instruction_id not in binding.road_instruction_ids:
        return binding
    if binding.binding_id == selected_binding_id:
        replacement_ids = (
            source_piece.instruction_id,
            target_piece.instruction_id,
        )
        return replace(
            binding,
            road_instruction_ids=_replace_instruction_id(
                binding.road_instruction_ids,
                original.instruction_id,
                replacement_ids,
            ),
            node_recipes=(split_recipe,),
        )
    source_match = original.source_node_recipe in binding.node_recipes
    target_match = original.target_node_recipe in binding.node_recipes
    if not source_match and not target_match:
        raise ValueError(
            "parent split cannot preserve another access binding"
        )
    replacement_ids = tuple(
        row.instruction_id
        for row, include in (
            (source_piece, source_match),
            (target_piece, target_match),
        )
        if include
    )
    return replace(
        binding,
        road_instruction_ids=_replace_instruction_id(
            binding.road_instruction_ids,
            original.instruction_id,
            replacement_ids,
        ),
    )


def _replace_instruction_id(
    values: Sequence[str],
    original_id: str,
    replacement_ids: Sequence[str],
) -> tuple[str, ...]:
    result = []
    for value in values:
        if value == original_id:
            result.extend(replacement_ids)
        else:
            result.append(value)
    if len(result) != len(set(result)):
        raise ValueError("parent split creates duplicate access Road references")
    return tuple(result)


def _attachment_instruction(
    *,
    side: AttachmentEndpoint,
    child_instruction_id: str,
    child_endpoint: AttachmentEndpoint,
    child_segment_id: str,
    context: _ParentContext,
) -> AttachmentInstruction:
    if context.source_kind is RoadSource.RCSD:
        return AttachmentInstruction(
            side=side,
            parent_access_binding_id=context.binding.binding_id,
            child_road_instruction_id=child_instruction_id,
            child_segment_id=child_segment_id,
            child_endpoint=child_endpoint,
            target_kind=AttachmentTargetKind.ROAD_POSITION,
            parent_road_instruction_id=context.parent_road.instruction_id,
            parent_position_m=context.parent_position_m,
        )
    if not context.final_node_recipe.output_node_id:
        raise ValueError(
            "SWSD side must reuse an explicit frozen access Node id"
        )
    return AttachmentInstruction(
        side=side,
        parent_access_binding_id=context.binding.binding_id,
        child_road_instruction_id=child_instruction_id,
        child_segment_id=child_segment_id,
        child_endpoint=child_endpoint,
        target_kind=AttachmentTargetKind.FROZEN_ACCESS_NODE,
        target_node_id=context.final_node_recipe.output_node_id,
    )


def _slice_from_endpoint_to_fraction(
    source_key: tuple[RoadSource, str],
    *,
    endpoint: AttachmentEndpoint,
    fraction: float,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    coordinate_tolerance_m: float,
) -> GeometrySlice:
    source = source_roads[source_key]
    position = _interior_position(
        source,
        fraction=fraction,
        endpoint=endpoint,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    if endpoint is AttachmentEndpoint.SOURCE:
        return GeometrySlice(*source_key, end_position_m=position)
    return GeometrySlice(
        *source_key,
        start_position_m=position,
        reverse_geometry=True,
    )


def _slice_from_fraction_to_endpoint(
    source_key: tuple[RoadSource, str],
    *,
    endpoint: AttachmentEndpoint,
    fraction: float,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    coordinate_tolerance_m: float,
) -> GeometrySlice:
    source = source_roads[source_key]
    position = _interior_position(
        source,
        fraction=fraction,
        endpoint=endpoint,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    if endpoint is AttachmentEndpoint.TARGET:
        return GeometrySlice(*source_key, start_position_m=position)
    return GeometrySlice(
        *source_key,
        end_position_m=position,
        reverse_geometry=True,
    )


def _interior_position(
    source: SourceRoadRecord,
    *,
    fraction: float,
    endpoint: AttachmentEndpoint,
    coordinate_tolerance_m: float,
) -> float:
    value = float(fraction)
    if not 0.0 <= value <= 1.0:
        raise ValueError("middle splice fraction is outside [0, 1]")
    position = value * float(source.geometry.length)
    endpoint_position = (
        0.0
        if endpoint is AttachmentEndpoint.SOURCE
        else float(source.geometry.length)
    )
    if abs(position - endpoint_position) <= coordinate_tolerance_m:
        raise ValueError("middle splice would create a zero-length retained part")
    return position


def _endpoint_join_mode(
    *,
    child_key: tuple[RoadSource, str],
    child_endpoint: AttachmentEndpoint,
    parent_recipe: NodeRecipe,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
    coordinate_tolerance_m: float,
) -> GeometryJoinMode:
    parent_point = _node_recipe_point(
        parent_recipe,
        source_roads=source_roads,
        source_nodes=source_nodes,
    )
    child = source_roads[child_key]
    child_node_id = (
        child.start_node_id
        if child_endpoint is AttachmentEndpoint.SOURCE
        else child.end_node_id
    )
    child_node = source_nodes.get((child_key[0], child_node_id))
    if child_node is None:
        raise ValueError("mixed splice child endpoint Node is absent")
    return (
        GeometryJoinMode.COINCIDENT_ONLY
        if parent_point.distance(child_node.geometry)
        <= coordinate_tolerance_m
        else GeometryJoinMode.STRAIGHT_CONNECTOR
    )


def _node_recipe_point(
    recipe: NodeRecipe,
    *,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
    source_nodes: Mapping[tuple[RoadSource, str], SourceNodeRecord],
):
    if recipe.kind is NodeRecipeKind.COPY_SOURCE_NODE:
        node = source_nodes.get((recipe.source_kind, recipe.source_node_id))
        if node is None:
            raise ValueError("parent access Node is absent")
        return node.geometry
    if recipe.kind is NodeRecipeKind.INTERPOLATE_SOURCE_ROAD:
        road = source_roads.get((recipe.source_kind, recipe.source_road_id))
        if road is None or recipe.position_m is None:
            raise ValueError("parent split Node recipe is incomplete")
        return road.geometry.interpolate(float(recipe.position_m))
    raise ValueError("unsupported parent access Node recipe")


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


def _attachments_by_side(
    rows: Sequence[LockedRoadAttachment],
) -> dict[AttachmentEndpoint, LockedRoadAttachment]:
    result: dict[AttachmentEndpoint, LockedRoadAttachment] = {}
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


def _whole_source_record(
    road: RoadInstruction,
    *,
    source_roads: Mapping[tuple[RoadSource, str], SourceRoadRecord],
) -> tuple[RoadSource, SourceRoadRecord]:
    if (
        len(road.geometry_slices) != 1
        or road.join_modes
        or road.geometry_slices[0].start_position_m != 0.0
        or road.geometry_slices[0].end_position_m is not None
        or road.geometry_slices[0].reverse_geometry
    ):
        raise ValueError(
            "split compiler requires a whole, non-reversed parent Road"
        )
    source_slice = road.geometry_slices[0]
    source = source_roads.get(source_slice.source_key)
    if source is None:
        raise ValueError("selected parent source Road is absent")
    return source_slice.source_kind, source


def _side_child_key(
    by_side: Mapping[AttachmentEndpoint, LockedRoadAttachment],
    side: AttachmentEndpoint,
) -> tuple[RoadSource, str]:
    row = by_side[side]
    return row.child_source_kind, row.child_source_road_id


def _splice_fraction(
    source_kind: RoadSource,
    middle_splice: LockedMiddleSplice,
) -> float:
    return (
        middle_splice.rcsd_fraction
        if source_kind is RoadSource.RCSD
        else middle_splice.swsd_fraction
    )


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
    "AttachmentOperation",
    "LockedMiddleSplice",
    "LockedRoadAttachment",
    "ParentPiece",
    "PreparedMixedSpliceExecution",
    "prepare_mixed_splice_advance_right_execution",
]
