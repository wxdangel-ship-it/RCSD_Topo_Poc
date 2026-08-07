from __future__ import annotations

from dataclasses import replace

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_materialization import (
    LockedEndpointAttachment,
    prepare_locked_endpoint_advance_right_instruction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessDirectionRole,
    AccessStructuralRole,
    AttachmentEndpoint,
    AttachmentInstruction,
    AttachmentTargetKind,
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


def _node(
    source: RoadSource,
    node_id: str,
    x: float,
    y: float,
) -> SourceNodeRecord:
    return SourceNodeRecord(
        source,
        node_id,
        Point(x, y),
        "EPSG:3857",
    )


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
        "EPSG:3857",
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
    access_node_id: str,
    access_at_source: bool,
    binding_id: str,
    decision: SegmentDecision,
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
    access_recipe = source_recipe if access_at_source else target_recipe
    return SegmentMaterializationInstruction(
        segment_id,
        SegmentMaterializationType.STANDARD,
        decision,
        (road_instruction,),
        access_bindings=(
            SegmentAccessBinding(
                f"{segment_id}@source-endpoint",
                segment_id,
                f"{segment_id}-source-t01",
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.EXIT,
                (road_instruction.instruction_id,),
                (source_recipe,),
            ),
            SegmentAccessBinding(
                f"{segment_id}@target-endpoint",
                segment_id,
                f"{segment_id}-target-t01",
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.ENTER,
                (road_instruction.instruction_id,),
                (target_recipe,),
            ),
            SegmentAccessBinding(
                binding_id,
                segment_id,
                access_node_id,
                AccessStructuralRole.ADVANCE_RIGHT_ATTACHMENT,
                (
                    AccessDirectionRole.EXIT
                    if access_at_source
                    else AccessDirectionRole.ENTER
                ),
                (road_instruction.instruction_id,),
                (access_recipe,),
            ),
        ),
        fallback_applied=False,
    )


def _contracts(
    *ordinary_instructions: SegmentMaterializationInstruction,
) -> tuple[FrozenSegmentAccessContract, ...]:
    return tuple(
        FrozenSegmentAccessContract(
            binding.binding_id,
            binding.segment_id,
            binding.access_node_id,
            binding.structural_role,
            binding.direction_role,
        )
        for instruction in ordinary_instructions
        for binding in instruction.access_bindings
    )


def _ar_fallback() -> SegmentMaterializationInstruction:
    return SegmentMaterializationInstruction(
        "ar",
        SegmentMaterializationType.ADVANCE_RIGHT,
        SegmentDecision.ABSTAIN,
        (
            RoadInstruction(
                "fallback:ar",
                "ar",
                RoadRole.ADVANCE_RIGHT,
                2,
                (GeometrySlice(RoadSource.SWSD, "ar-swsd"),),
                _copy(RoadSource.SWSD, "f0", output_node_id="f0"),
                _copy(RoadSource.SWSD, "f1", output_node_id="f1"),
                output_road_id="ar-swsd",
            ),
        ),
        attachments=(
            AttachmentInstruction(
                AttachmentEndpoint.SOURCE,
                "left@access",
                "fallback:ar",
                "ar",
                AttachmentEndpoint.SOURCE,
                AttachmentTargetKind.FROZEN_ACCESS_NODE,
                target_node_id="left-frozen",
            ),
            AttachmentInstruction(
                AttachmentEndpoint.TARGET,
                "right@access",
                "fallback:ar",
                "ar",
                AttachmentEndpoint.TARGET,
                AttachmentTargetKind.FROZEN_ACCESS_NODE,
                target_node_id="right-frozen",
            ),
        ),
        fallback_applied=True,
    )


def _plan() -> PlanCandidate:
    return PlanCandidate(
        plan_id="ar-plan",
        segment_id="ar",
        decision=SegmentDecision.USE_RCSD,
        roads=(
            RoadUse(
                RoadSource.RCSD,
                "ar-rcsd",
                RoadRole.ADVANCE_RIGHT,
                "ar",
                2,
            ),
        ),
        source_access_road_id="left-rcsd",
        target_access_road_id="right-rcsd",
        node_recipes=(
            {
                "source_segment_id": "left",
                "target_segment_id": "right",
            },
        ),
        source_condition=(RoadSource.RCSD, RoadSource.RCSD),
    )


def _source_graph():
    roads = {
        (RoadSource.RCSD, "left-rcsd"): _road(
            RoadSource.RCSD,
            "left-rcsd",
            "l0",
            "shared-left",
            [(0, 0), (10, 0)],
        ),
        (RoadSource.RCSD, "right-rcsd"): _road(
            RoadSource.RCSD,
            "right-rcsd",
            "shared-right",
            "r1",
            [(20, 10), (30, 10)],
        ),
        (RoadSource.RCSD, "ar-rcsd"): _road(
            RoadSource.RCSD,
            "ar-rcsd",
            "ar-left",
            "ar-right",
            [(10, 0), (20, 10)],
        ),
    }
    nodes = {
        (RoadSource.RCSD, "l0"): _node(RoadSource.RCSD, "l0", 0, 0),
        (RoadSource.RCSD, "shared-left"): _node(
            RoadSource.RCSD, "shared-left", 10, 0
        ),
        (RoadSource.RCSD, "shared-right"): _node(
            RoadSource.RCSD, "shared-right", 20, 10
        ),
        (RoadSource.RCSD, "r1"): _node(RoadSource.RCSD, "r1", 30, 10),
        (RoadSource.RCSD, "ar-left"): _node(
            RoadSource.RCSD, "ar-left", 10, 0
        ),
        (RoadSource.RCSD, "ar-right"): _node(
            RoadSource.RCSD, "ar-right", 20, 10
        ),
    }
    return roads, nodes


def test_compiler_materializes_rcsd_and_swsd_conditioned_endpoint_attachments() -> None:
    roads, nodes = _source_graph()
    left = _ordinary(
        segment_id="left",
        source=RoadSource.RCSD,
        road_id="left-rcsd",
        source_node_id="l0",
        target_node_id="shared-left",
        access_node_id="left-t01",
        access_at_source=False,
        binding_id="left@access",
        decision=SegmentDecision.USE_RCSD,
    )
    right = _ordinary(
        segment_id="right",
        source=RoadSource.RCSD,
        road_id="right-rcsd",
        source_node_id="shared-right",
        target_node_id="r1",
        access_node_id="right-t01",
        access_at_source=True,
        binding_id="right@access",
        decision=SegmentDecision.USE_RCSD,
    )
    prepared = prepare_locked_endpoint_advance_right_instruction(
        plan=_plan(),
        fallback_instruction=_ar_fallback(),
        ordinary_instructions={"left": left, "right": right},
        locked_attachments=(
            LockedEndpointAttachment(
                AttachmentEndpoint.SOURCE,
                "left@access",
                "left-rcsd",
                "ar-rcsd",
                AttachmentEndpoint.SOURCE,
            ),
            LockedEndpointAttachment(
                AttachmentEndpoint.TARGET,
                "right@access",
                "right-rcsd",
                "ar-rcsd",
                AttachmentEndpoint.TARGET,
            ),
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right", "ar"),
        frozen_access_contracts=_contracts(left, right),
        segment_instructions=(left, right, prepared.instruction),
        source_roads=roads,
        source_nodes=nodes,
    )
    attachments = {row.side: row for row in graph.attachments}
    assert (
        attachments[AttachmentEndpoint.SOURCE].target_kind
        is AttachmentTargetKind.ROAD_POSITION
    )
    assert (
        attachments[AttachmentEndpoint.TARGET].target_kind
        is AttachmentTargetKind.ROAD_POSITION
    )
    ar_road = next(row for row in graph.roads if row.owner_segment_id == "ar")
    left_access = graph.access_bindings["left@access"]
    right_access = graph.access_bindings["right@access"]
    assert ar_road.source_node_id in left_access.node_ids
    assert ar_road.target_node_id in right_access.node_ids
    assert all(row.owner_segment_id != "ar" for row in graph.roads if row.road_id != "ar-rcsd")
    assert graph.skeleton_mutation_count == 0
    assert not graph.silent_fix
    assert not graph.content_repair


def test_compiler_rejects_noncoincident_endpoint_without_repair() -> None:
    roads, nodes = _source_graph()
    left = _ordinary(
        segment_id="left",
        source=RoadSource.RCSD,
        road_id="left-rcsd",
        source_node_id="l0",
        target_node_id="shared-left",
        access_node_id="left-t01",
        access_at_source=False,
        binding_id="left@access",
        decision=SegmentDecision.USE_RCSD,
    )
    right = _ordinary(
        segment_id="right",
        source=RoadSource.RCSD,
        road_id="right-rcsd",
        source_node_id="shared-right",
        target_node_id="r1",
        access_node_id="right-t01",
        access_at_source=True,
        binding_id="right@access",
        decision=SegmentDecision.USE_RCSD,
    )
    nodes[(RoadSource.RCSD, "ar-right")] = replace(
        nodes[(RoadSource.RCSD, "ar-right")],
        geometry=Point(25, 10),
    )
    with pytest.raises(ValueError, match="not geometrically coincident"):
        prepare_locked_endpoint_advance_right_instruction(
            plan=_plan(),
            fallback_instruction=_ar_fallback(),
            ordinary_instructions={"left": left, "right": right},
            locked_attachments=(
                LockedEndpointAttachment(
                    AttachmentEndpoint.SOURCE,
                    "left@access",
                    "left-rcsd",
                    "ar-rcsd",
                    AttachmentEndpoint.SOURCE,
                ),
                LockedEndpointAttachment(
                    AttachmentEndpoint.TARGET,
                    "right@access",
                    "right-rcsd",
                    "ar-rcsd",
                    AttachmentEndpoint.TARGET,
                ),
            ),
            source_roads=roads,
            source_nodes=nodes,
        )


def test_compiler_rejects_parent_road_not_selected_by_decoder() -> None:
    roads, nodes = _source_graph()
    left = _ordinary(
        segment_id="left",
        source=RoadSource.RCSD,
        road_id="left-rcsd",
        source_node_id="l0",
        target_node_id="shared-left",
        access_node_id="left-t01",
        access_at_source=False,
        binding_id="left@access",
        decision=SegmentDecision.USE_RCSD,
    )
    right = _ordinary(
        segment_id="right",
        source=RoadSource.RCSD,
        road_id="right-rcsd",
        source_node_id="shared-right",
        target_node_id="r1",
        access_node_id="right-t01",
        access_at_source=True,
        binding_id="right@access",
        decision=SegmentDecision.USE_RCSD,
    )
    with pytest.raises(ValueError, match="decoder-selected access Road"):
        prepare_locked_endpoint_advance_right_instruction(
            plan=_plan(),
            fallback_instruction=_ar_fallback(),
            ordinary_instructions={"left": left, "right": right},
            locked_attachments=(
                LockedEndpointAttachment(
                    AttachmentEndpoint.SOURCE,
                    "left@access",
                    "wrong-parent",
                    "ar-rcsd",
                    AttachmentEndpoint.SOURCE,
                ),
                LockedEndpointAttachment(
                    AttachmentEndpoint.TARGET,
                    "right@access",
                    "right-rcsd",
                    "ar-rcsd",
                    AttachmentEndpoint.TARGET,
                ),
            ),
            source_roads=roads,
            source_nodes=nodes,
        )
