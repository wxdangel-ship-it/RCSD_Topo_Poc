from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_splice_materialization import (
    AttachmentOperation,
    LockedMiddleSplice,
    LockedRoadAttachment,
    ParentPiece,
    prepare_mixed_splice_advance_right_execution,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessDirectionRole,
    AccessStructuralRole,
    AttachmentEndpoint,
    FrozenSegmentAccessContract,
    GeometrySlice,
    NodeRecipe,
    NodeRecipeKind,
    RoadInstruction,
    SegmentAccessBinding,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
    SourceNodeRecord,
    SourceRoadRecord,
    materialize_target_a_roadgraph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    SegmentDecision,
)


CRS = "EPSG:3857"


def _node(
    source: RoadSource,
    node_id: str,
    x: float,
    y: float,
) -> SourceNodeRecord:
    return SourceNodeRecord(source, node_id, Point(x, y), CRS)


def _road(
    source: RoadSource,
    road_id: str,
    start_node_id: str,
    end_node_id: str,
    coordinates: list[tuple[float, float]],
) -> SourceRoadRecord:
    return SourceRoadRecord(
        source,
        road_id,
        LineString(coordinates),
        start_node_id,
        end_node_id,
        2,
        CRS,
    )


def _copy(
    source: RoadSource,
    node_id: str,
    *,
    output_node_id: str = "",
) -> NodeRecipe:
    return NodeRecipe(
        NodeRecipeKind.COPY_SOURCE_NODE,
        source,
        source_node_id=node_id,
        output_node_id=output_node_id,
    )


def _ordinary(
    *,
    segment_id: str,
    source: RoadSource,
    road_id: str,
    source_node_id: str,
    target_node_id: str,
    attachment_at_source: bool,
    decision: SegmentDecision,
    attachment_direction: AccessDirectionRole | None = None,
) -> SegmentMaterializationInstruction:
    source_recipe = _copy(
        source,
        source_node_id,
        output_node_id=source_node_id if source is RoadSource.SWSD else "",
    )
    target_recipe = _copy(
        source,
        target_node_id,
        output_node_id=target_node_id if source is RoadSource.SWSD else "",
    )
    road_instruction = RoadInstruction(
        instruction_id=f"ordinary:{segment_id}:{road_id}",
        owner_segment_id=segment_id,
        role=RoadRole.MAIN,
        direction=2,
        geometry_slices=(GeometrySlice(source, road_id),),
        source_node_recipe=source_recipe,
        target_node_recipe=target_recipe,
        output_road_id=road_id,
    )
    attachment_recipe = (
        source_recipe if attachment_at_source else target_recipe
    )
    if attachment_direction is None:
        attachment_direction = (
            AccessDirectionRole.EXIT
            if attachment_at_source
            else AccessDirectionRole.ENTER
        )
    return SegmentMaterializationInstruction(
        segment_id=segment_id,
        segment_type=SegmentMaterializationType.STANDARD,
        decision=decision,
        roads=(road_instruction,),
        access_bindings=(
            SegmentAccessBinding(
                f"{segment_id}@source",
                segment_id,
                f"{segment_id}-source-junction",
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.EXIT,
                (road_instruction.instruction_id,),
                (source_recipe,),
            ),
            SegmentAccessBinding(
                f"{segment_id}@target",
                segment_id,
                f"{segment_id}-target-junction",
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.ENTER,
                (road_instruction.instruction_id,),
                (target_recipe,),
            ),
            SegmentAccessBinding(
                f"{segment_id}@ar",
                segment_id,
                f"{segment_id}-ar-access",
                AccessStructuralRole.ADVANCE_RIGHT_ATTACHMENT,
                attachment_direction,
                (road_instruction.instruction_id,),
                (attachment_recipe,),
            ),
        ),
        fallback_applied=False,
    )


def _contracts(
    *instructions: SegmentMaterializationInstruction,
) -> tuple[FrozenSegmentAccessContract, ...]:
    return tuple(
        FrozenSegmentAccessContract(
            binding.binding_id,
            binding.segment_id,
            binding.access_node_id,
            binding.structural_role,
            binding.direction_role,
        )
        for instruction in instructions
        for binding in instruction.access_bindings
    )


def _fallback() -> SegmentMaterializationInstruction:
    return SegmentMaterializationInstruction(
        segment_id="ar",
        segment_type=SegmentMaterializationType.ADVANCE_RIGHT,
        decision=SegmentDecision.ABSTAIN,
        roads=(),
        fallback_applied=True,
    )


def _plan() -> PlanCandidate:
    return PlanCandidate(
        plan_id="mixed-plan",
        segment_id="ar",
        decision=SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE,
        roads=(
            RoadUse(
                RoadSource.RCSD,
                "ar-rcsd",
                RoadRole.ADVANCE_RIGHT,
                "ar",
                2,
            ),
            RoadUse(
                RoadSource.SWSD,
                "ar-swsd",
                RoadRole.ADVANCE_RIGHT,
                "ar",
                2,
            ),
        ),
        source_access_road_id="left-parent",
        target_access_road_id="right-parent",
        node_recipes=(
            {
                "source_segment_id": "left",
                "target_segment_id": "right",
            },
        ),
        source_condition=(RoadSource.RCSD, RoadSource.SWSD),
    )


def _source_graph() -> tuple[
    dict[tuple[RoadSource, str], SourceRoadRecord],
    dict[tuple[RoadSource, str], SourceNodeRecord],
]:
    roads = {
        (RoadSource.RCSD, "left-parent"): _road(
            RoadSource.RCSD,
            "left-parent",
            "left-0",
            "left-1",
            [(0, 0), (10, 0)],
        ),
        (RoadSource.SWSD, "right-parent"): _road(
            RoadSource.SWSD,
            "right-parent",
            "right-0",
            "right-1",
            [(20, 10), (30, 10)],
        ),
        (RoadSource.RCSD, "ar-rcsd"): _road(
            RoadSource.RCSD,
            "ar-rcsd",
            "ar-r0",
            "ar-r1",
            [(8, 1), (14, 1)],
        ),
        (RoadSource.SWSD, "ar-swsd"): _road(
            RoadSource.SWSD,
            "ar-swsd",
            "ar-s0",
            "ar-s1",
            [(12, 3), (20, 10)],
        ),
    }
    nodes = {
        (RoadSource.RCSD, "left-0"): _node(
            RoadSource.RCSD, "left-0", 0, 0
        ),
        (RoadSource.RCSD, "left-1"): _node(
            RoadSource.RCSD, "left-1", 10, 0
        ),
        (RoadSource.SWSD, "right-0"): _node(
            RoadSource.SWSD, "right-0", 20, 10
        ),
        (RoadSource.SWSD, "right-1"): _node(
            RoadSource.SWSD, "right-1", 30, 10
        ),
        (RoadSource.RCSD, "ar-r0"): _node(
            RoadSource.RCSD, "ar-r0", 8, 1
        ),
        (RoadSource.RCSD, "ar-r1"): _node(
            RoadSource.RCSD, "ar-r1", 14, 1
        ),
        (RoadSource.SWSD, "ar-s0"): _node(
            RoadSource.SWSD, "ar-s0", 12, 3
        ),
        (RoadSource.SWSD, "ar-s1"): _node(
            RoadSource.SWSD, "ar-s1", 20, 10
        ),
    }
    return roads, nodes


def _locked_attachments(
    *,
    parent_piece: ParentPiece | None = ParentPiece.SOURCE_PART,
) -> tuple[LockedRoadAttachment, ...]:
    return (
        LockedRoadAttachment(
            side=AttachmentEndpoint.SOURCE,
            parent_access_binding_id="left@ar",
            parent_source_road_id="left-parent",
            parent_fraction=0.6,
            operation=AttachmentOperation.SPLIT_ROAD,
            parent_piece=parent_piece,
            child_source_kind=RoadSource.RCSD,
            child_source_road_id="ar-rcsd",
            child_endpoint=AttachmentEndpoint.SOURCE,
        ),
        LockedRoadAttachment(
            side=AttachmentEndpoint.TARGET,
            parent_access_binding_id="right@ar",
            parent_source_road_id="right-parent",
            parent_fraction=0.0,
            operation=AttachmentOperation.REUSE_ENDPOINT,
            parent_piece=None,
            child_source_kind=RoadSource.SWSD,
            child_source_road_id="ar-swsd",
            child_endpoint=AttachmentEndpoint.TARGET,
        ),
    )


def _middle_splice() -> LockedMiddleSplice:
    return LockedMiddleSplice(
        rcsd_source_road_id="ar-rcsd",
        swsd_source_road_id="ar-swsd",
        rcsd_fraction=0.75,
        swsd_fraction=0.25,
        direction=2,
    )


def test_mixed_splice_splits_parent_and_materializes_complete_roadgraph() -> None:
    roads, nodes = _source_graph()
    left = _ordinary(
        segment_id="left",
        source=RoadSource.RCSD,
        road_id="left-parent",
        source_node_id="left-0",
        target_node_id="left-1",
        attachment_at_source=False,
        decision=SegmentDecision.USE_RCSD,
        attachment_direction=AccessDirectionRole.BOTH,
    )
    right = _ordinary(
        segment_id="right",
        source=RoadSource.SWSD,
        road_id="right-parent",
        source_node_id="right-0",
        target_node_id="right-1",
        attachment_at_source=True,
        decision=SegmentDecision.KEEP_SWSD,
    )
    prepared = prepare_mixed_splice_advance_right_execution(
        plan=_plan(),
        fallback_instruction=_fallback(),
        ordinary_instructions={"left": left, "right": right},
        locked_attachments=_locked_attachments(),
        middle_splice=_middle_splice(),
        source_roads=roads,
        source_nodes=nodes,
    )
    replacements = dict(prepared.ordinary_replacements)
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right", "ar"),
        frozen_access_contracts=_contracts(left, right),
        segment_instructions=(
            replacements.get("left", left),
            replacements.get("right", right),
            prepared.advance_right.instruction,
        ),
        source_roads=roads,
        source_nodes=nodes,
    )

    left_roads = [
        row
        for row in graph.roads
        if row.owner_segment_id == "left"
    ]
    assert len(left_roads) == 2
    assert {
        tuple(round(value, 6) for value in row.geometry.bounds)
        for row in left_roads
    } == {
        (0.0, 0.0, 6.0, 0.0),
        (6.0, 0.0, 10.0, 0.0),
    }
    ar_road = next(
        row for row in graph.roads if row.owner_segment_id == "ar"
    )
    assert ar_road.role is RoadRole.ADVANCE_RIGHT
    assert ar_road.direction == 2
    assert ar_road.source_references == (
        (RoadSource.RCSD, "ar-rcsd"),
        (RoadSource.SWSD, "ar-swsd"),
    )
    assert tuple(ar_road.geometry.coords)[0] == (6.0, 0.0)
    assert tuple(ar_road.geometry.coords)[-1] == (20.0, 10.0)
    assert ar_road.source_node_id in graph.access_bindings["left@ar"].node_ids
    assert ar_road.target_node_id in graph.access_bindings["right@ar"].node_ids
    assert len(graph.attachments) == 2
    assert graph.skeleton_mutation_count == 0
    assert not graph.silent_fix
    assert not graph.content_repair


def test_mixed_splice_rejects_an_interior_split_without_final_piece() -> None:
    roads, nodes = _source_graph()
    left = _ordinary(
        segment_id="left",
        source=RoadSource.RCSD,
        road_id="left-parent",
        source_node_id="left-0",
        target_node_id="left-1",
        attachment_at_source=False,
        decision=SegmentDecision.USE_RCSD,
        attachment_direction=AccessDirectionRole.BOTH,
    )
    right = _ordinary(
        segment_id="right",
        source=RoadSource.SWSD,
        road_id="right-parent",
        source_node_id="right-0",
        target_node_id="right-1",
        attachment_at_source=True,
        decision=SegmentDecision.KEEP_SWSD,
    )
    with pytest.raises(
        ValueError,
        match="must select its final parent piece",
    ):
        prepare_mixed_splice_advance_right_execution(
            plan=_plan(),
            fallback_instruction=_fallback(),
            ordinary_instructions={"left": left, "right": right},
            locked_attachments=_locked_attachments(parent_piece=None),
            middle_splice=_middle_splice(),
            source_roads=roads,
            source_nodes=nodes,
        )
