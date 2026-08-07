from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessDirectionRole,
    AccessStructuralRole,
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
    RoadUse,
    SegmentDecision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_materialization import (
    LockedAccessNode,
    prepare_locked_node_ordinary_instruction,
)


def _fallback() -> SegmentMaterializationInstruction:
    road = RoadInstruction(
        instruction_id="swsd:s1:r0",
        owner_segment_id="s1",
        role=RoadRole.MAIN,
        direction=2,
        geometry_slices=(GeometrySlice(RoadSource.SWSD, "r0"),),
        source_node_recipe=NodeRecipe(
            NodeRecipeKind.COPY_SOURCE_NODE,
            RoadSource.SWSD,
            source_node_id="n0",
        ),
        target_node_recipe=NodeRecipe(
            NodeRecipeKind.COPY_SOURCE_NODE,
            RoadSource.SWSD,
            source_node_id="n1",
        ),
    )
    bindings = tuple(
        SegmentAccessBinding(
            binding_id=f"s1@{node_id}",
            segment_id="s1",
            access_node_id=node_id,
            structural_role=AccessStructuralRole.ENDPOINT,
            direction_role=direction,
            road_instruction_ids=(road.instruction_id,),
            node_recipes=(
                NodeRecipe(
                    NodeRecipeKind.COPY_SOURCE_NODE,
                    RoadSource.SWSD,
                    source_node_id=source_node_id,
                ),
            ),
        )
        for node_id, source_node_id, direction in (
            ("left", "n0", AccessDirectionRole.EXIT),
            ("right", "n1", AccessDirectionRole.ENTER),
        )
    )
    return SegmentMaterializationInstruction(
        segment_id="s1",
        segment_type=SegmentMaterializationType.STANDARD,
        decision=SegmentDecision.ABSTAIN,
        roads=(road,),
        access_bindings=bindings,
        fallback_applied=True,
    )


def _source_graph():
    roads = {
        (RoadSource.RCSD, "r1"): SourceRoadRecord(
            RoadSource.RCSD,
            "r1",
            LineString([(0.0, 0.0), (1.0, 0.0)]),
            "a",
            "b",
            2,
            "EPSG:3857",
        ),
        (RoadSource.RCSD, "r2"): SourceRoadRecord(
            RoadSource.RCSD,
            "r2",
            LineString([(1.0, 0.0), (2.0, 0.0)]),
            "b",
            "c",
            2,
            "EPSG:3857",
        ),
    }
    nodes = {
        (RoadSource.RCSD, node_id): SourceNodeRecord(
            RoadSource.RCSD,
            node_id,
            Point(float(index), 0.0),
            "EPSG:3857",
        )
        for index, node_id in enumerate(("a", "b", "c"))
    }
    return roads, nodes


def _plan() -> PlanCandidate:
    return PlanCandidate(
        plan_id="use:s1",
        segment_id="s1",
        decision=SegmentDecision.USE_RCSD,
        roads=tuple(
            RoadUse(
                RoadSource.RCSD,
                road_id,
                RoadRole.MAIN,
                "s1",
                0,
            )
            for road_id in ("r1", "r2")
        ),
        source_access_road_id="r1",
        target_access_road_id="r2",
    )


def test_compiler_uses_locked_nodes_and_all_incident_selected_roads() -> None:
    roads, nodes = _source_graph()
    prepared = prepare_locked_node_ordinary_instruction(
        plan=_plan(),
        fallback_instruction=_fallback(),
        locked_access_nodes={
            "left": (LockedAccessNode(RoadSource.RCSD, "a"),),
            "right": (LockedAccessNode(RoadSource.RCSD, "c"),),
        },
        source_roads=roads,
        source_nodes=nodes,
    )
    instruction = prepared.instruction
    assert prepared.plan_id == "use:s1"
    assert instruction.decision is SegmentDecision.USE_RCSD
    assert not instruction.fallback_applied
    assert {
        road.geometry_slices[0].source_road_id
        for road in instruction.roads
    } == {"r1", "r2"}
    bindings = {
        binding.access_node_id: binding
        for binding in instruction.access_bindings
    }
    assert bindings["left"].road_instruction_ids == (
        "model:s1:RCSD:r1",
    )
    assert bindings["right"].road_instruction_ids == (
        "model:s1:RCSD:r2",
    )
    assert bindings["left"].node_recipes[0].source_node_id == "a"
    assert bindings["right"].node_recipes[0].source_node_id == "c"


def test_compiler_refuses_to_infer_missing_or_nonincident_anchor_nodes() -> None:
    roads, nodes = _source_graph()
    with pytest.raises(ValueError, match="frozen access relations"):
        prepare_locked_node_ordinary_instruction(
            plan=_plan(),
            fallback_instruction=_fallback(),
            locked_access_nodes={
                "left": (LockedAccessNode(RoadSource.RCSD, "a"),),
            },
            source_roads=roads,
            source_nodes=nodes,
        )
    nodes[(RoadSource.RCSD, "detached")] = SourceNodeRecord(
        RoadSource.RCSD,
        "detached",
        Point(5.0, 0.0),
        "EPSG:3857",
    )
    with pytest.raises(ValueError, match="not incident"):
        prepare_locked_node_ordinary_instruction(
            plan=_plan(),
            fallback_instruction=_fallback(),
            locked_access_nodes={
                "left": (LockedAccessNode(RoadSource.RCSD, "a"),),
                "right": (
                    LockedAccessNode(RoadSource.RCSD, "detached"),
                ),
            },
            source_roads=roads,
            source_nodes=nodes,
        )


def test_compiler_does_not_silently_execute_a_split_plan() -> None:
    roads, nodes = _source_graph()
    split_plan = PlanCandidate(
        plan_id="split:s1",
        segment_id="s1",
        decision=SegmentDecision.USE_RCSD,
        roads=(
            RoadUse(
                RoadSource.RCSD,
                "r1",
                RoadRole.MAIN,
                "s1",
                0,
                piece_id="r1:left",
                split_position_m=0.5,
            ),
        ),
        source_access_road_id="r1:left",
        target_access_road_id="r1:left",
    )
    with pytest.raises(ValueError, match="split-capable"):
        prepare_locked_node_ordinary_instruction(
            plan=split_plan,
            fallback_instruction=_fallback(),
            locked_access_nodes={
                "left": (LockedAccessNode(RoadSource.RCSD, "a"),),
                "right": (LockedAccessNode(RoadSource.RCSD, "b"),),
            },
            source_roads=roads,
            source_nodes=nodes,
        )
