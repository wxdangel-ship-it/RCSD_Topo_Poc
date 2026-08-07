from __future__ import annotations

from dataclasses import replace

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AccessDirectionRole,
    AccessStructuralRole,
    AttachmentEndpoint,
    AttachmentInstruction,
    AttachmentTargetKind,
    FrozenSegmentAccessContract,
    GeometryJoinMode,
    GeometrySlice,
    MaterializationError,
    NodeRecipe,
    NodeRecipeKind,
    RoadInstruction,
    SegmentAccessBinding,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
    SourceNodeRecord,
    SourceRoadRecord,
    materialize_target_a_roadgraph as _materialize_target_a_roadgraph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    RoadRole,
    RoadSource,
    SegmentDecision,
)


CRS = "EPSG:3857"


def _road(
    source: RoadSource,
    road_id: str,
    start: str,
    end: str,
    coordinates: list[tuple[float, float]],
) -> SourceRoadRecord:
    return SourceRoadRecord(
        source,
        road_id,
        LineString(coordinates),
        start,
        end,
        2,
        CRS,
    )


def _node(
    source: RoadSource,
    node_id: str,
    x: float,
    y: float = 0.0,
) -> SourceNodeRecord:
    return SourceNodeRecord(source, node_id, Point(x, y), CRS)


def _copy(source: RoadSource, node_id: str) -> NodeRecipe:
    return NodeRecipe(NodeRecipeKind.COPY_SOURCE_NODE, source, source_node_id=node_id)


def _interpolate(
    source: RoadSource,
    road_id: str,
    position_m: float,
) -> NodeRecipe:
    return NodeRecipe(
        NodeRecipeKind.INTERPOLATE_SOURCE_ROAD,
        source,
        source_road_id=road_id,
        position_m=position_m,
    )


def _instruction(
    instruction_id: str,
    segment_id: str,
    source: RoadSource,
    road_id: str,
    start_node: NodeRecipe,
    end_node: NodeRecipe,
    *,
    start_m: float = 0.0,
    end_m: float | None = None,
    role: RoadRole = RoadRole.MAIN,
) -> RoadInstruction:
    return RoadInstruction(
        instruction_id,
        segment_id,
        role,
        2,
        (GeometrySlice(source, road_id, start_m, end_m),),
        start_node,
        end_node,
    )


def _standard(
    segment_id: str,
    road: RoadInstruction,
    *,
    decision: SegmentDecision = SegmentDecision.USE_RCSD,
    fallback: bool = False,
) -> SegmentMaterializationInstruction:
    source_junction_id = _recipe_key(road.source_node_recipe)
    target_junction_id = _recipe_key(road.target_node_recipe)
    return SegmentMaterializationInstruction(
        segment_id,
        SegmentMaterializationType.STANDARD,
        decision,
        (road,),
        (
            SegmentAccessBinding(
                f"{segment_id}@{source_junction_id}",
                segment_id,
                source_junction_id,
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.EXIT,
                (road.instruction_id,),
                (road.source_node_recipe,),
            ),
            SegmentAccessBinding(
                f"{segment_id}@{target_junction_id}",
                segment_id,
                target_junction_id,
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.ENTER,
                (road.instruction_id,),
                (road.target_node_recipe,),
            ),
        ),
        fallback_applied=fallback,
    )


def _recipe_key(recipe: NodeRecipe) -> str:
    if recipe.source_node_id:
        return recipe.source_node_id
    return f"{recipe.source_road_id}@{recipe.position_m}"


def _contracts(
    plans: tuple[SegmentMaterializationInstruction, ...],
) -> tuple[FrozenSegmentAccessContract, ...]:
    return tuple(
        FrozenSegmentAccessContract(
            binding.binding_id,
            binding.segment_id,
            binding.access_node_id,
            binding.structural_role,
            binding.direction_role,
        )
        for plan in plans
        for binding in plan.access_bindings
    )


def materialize_target_a_roadgraph(**kwargs: object):
    plans = tuple(kwargs["segment_instructions"])
    return _materialize_target_a_roadgraph(
        **kwargs,
        frozen_access_contracts=_contracts(plans),
    )


def test_materializer_copies_complete_plan_and_writes_directed_topology() -> None:
    roads = {
        (RoadSource.RCSD, "r"): _road(
            RoadSource.RCSD, "r", "n0", "n1", [(0, 0), (10, 0)]
        )
    }
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.RCSD, "n1"): _node(RoadSource.RCSD, "n1", 10),
    }
    instruction = _instruction(
        "s:r", "s", RoadSource.RCSD, "r", _copy(RoadSource.RCSD, "n0"), _copy(RoadSource.RCSD, "n1")
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("s",),
        segment_instructions=(_standard("s", instruction),),
        source_roads=roads,
        source_nodes=nodes,
    )
    assert len(graph.roads) == 1
    assert len(graph.nodes) == 2
    assert graph.directed_edges == (
        (graph.roads[0].source_node_id, graph.roads[0].target_node_id),
    )
    assert graph.skeleton_mutation_count == 0
    assert graph.silent_fix is False


def test_nonoverlapping_split_pieces_share_the_same_generated_break_node() -> None:
    road = _road(RoadSource.RCSD, "r", "n0", "n1", [(0, 0), (10, 0)])
    roads = {(RoadSource.RCSD, "r"): road}
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.RCSD, "n1"): _node(RoadSource.RCSD, "n1", 10),
    }
    break_node = _interpolate(RoadSource.RCSD, "r", 5.0)
    left = _instruction(
        "left:r",
        "left",
        RoadSource.RCSD,
        "r",
        _copy(RoadSource.RCSD, "n0"),
        break_node,
        end_m=5.0,
    )
    right = _instruction(
        "right:r",
        "right",
        RoadSource.RCSD,
        "r",
        break_node,
        _copy(RoadSource.RCSD, "n1"),
        start_m=5.0,
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right"),
        segment_instructions=(
            _standard("left", left),
            _standard("right", right),
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    shared = set(
        (graph.roads[0].source_node_id, graph.roads[0].target_node_id)
    ) & set((graph.roads[1].source_node_id, graph.roads[1].target_node_id))
    assert len(shared) == 1
    assert len(graph.nodes) == 3


def test_overlapping_final_pieces_are_a_hard_failure() -> None:
    road = _road(RoadSource.RCSD, "r", "n0", "n1", [(0, 0), (10, 0)])
    roads = {(RoadSource.RCSD, "r"): road}
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.RCSD, "n1"): _node(RoadSource.RCSD, "n1", 10),
    }
    left = _instruction(
        "left:r",
        "left",
        RoadSource.RCSD,
        "r",
        _copy(RoadSource.RCSD, "n0"),
        _interpolate(RoadSource.RCSD, "r", 6.0),
        end_m=6.0,
    )
    right = _instruction(
        "right:r",
        "right",
        RoadSource.RCSD,
        "r",
        _interpolate(RoadSource.RCSD, "r", 5.0),
        _copy(RoadSource.RCSD, "n1"),
        start_m=5.0,
    )
    with pytest.raises(MaterializationError, match="overlap"):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("left", "right"),
            segment_instructions=(
                _standard("left", left),
                _standard("right", right),
            ),
            source_roads=roads,
            source_nodes=nodes,
        )


def test_straight_splice_requires_an_explicit_join_recipe() -> None:
    roads = {
        (RoadSource.RCSD, "a"): _road(
            RoadSource.RCSD, "a", "n0", "n1", [(0, 0), (5, 0)]
        ),
        (RoadSource.SWSD, "b"): _road(
            RoadSource.SWSD, "b", "n2", "n3", [(10, 0), (15, 0)]
        ),
    }
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.SWSD, "n3"): _node(RoadSource.SWSD, "n3", 15),
    }
    base = RoadInstruction(
        "splice",
        "s",
        RoadRole.ADVANCE_RIGHT,
        2,
        (
            GeometrySlice(RoadSource.RCSD, "a"),
            GeometrySlice(RoadSource.SWSD, "b"),
        ),
        _copy(RoadSource.RCSD, "n0"),
        _copy(RoadSource.SWSD, "n3"),
        (GeometryJoinMode.COINCIDENT_ONLY,),
    )
    plan = _standard(
        "s",
        base,
        decision=SegmentDecision.T06_MAIN_RCSD_ATTACHED_SWSD,
    )
    with pytest.raises(MaterializationError, match="nonzero gap"):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("s",),
            segment_instructions=(plan,),
            source_roads=roads,
            source_nodes=nodes,
        )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("s",),
        segment_instructions=(
            replace(
                plan,
                roads=(
                    replace(
                        base,
                        join_modes=(GeometryJoinMode.STRAIGHT_CONNECTOR,),
                    ),
                ),
            ),
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    assert list(graph.roads[0].geometry.coords) == [
        (0.0, 0.0),
        (5.0, 0.0),
        (10.0, 0.0),
        (15.0, 0.0),
    ]


def test_endpoint_connector_requires_an_explicit_model_recipe() -> None:
    roads = {
        (RoadSource.RCSD, "ar"): _road(
            RoadSource.RCSD,
            "ar",
            "ar-source",
            "target",
            [(1, 0), (10, 0)],
        )
    }
    nodes = {
        (RoadSource.RCSD, "junction"): _node(
            RoadSource.RCSD, "junction", 0
        ),
        (RoadSource.RCSD, "target"): _node(
            RoadSource.RCSD, "target", 10
        ),
    }
    base = RoadInstruction(
        "ar",
        "s",
        RoadRole.MAIN,
        2,
        (GeometrySlice(RoadSource.RCSD, "ar"),),
        _copy(RoadSource.RCSD, "junction"),
        _copy(RoadSource.RCSD, "target"),
    )
    plan = _standard("s", base)
    with pytest.raises(
        MaterializationError,
        match="declared source Node does not match Road geometry",
    ):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("s",),
            segment_instructions=(plan,),
            source_roads=roads,
            source_nodes=nodes,
        )

    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("s",),
        segment_instructions=(
            replace(
                plan,
                roads=(
                    replace(
                        base,
                        source_endpoint_join_mode=(
                            GeometryJoinMode.STRAIGHT_CONNECTOR
                        ),
                    ),
                ),
                access_bindings=tuple(
                    replace(
                        binding,
                        road_instruction_ids=("ar",),
                    )
                    for binding in plan.access_bindings
                ),
            ),
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    assert list(graph.roads[0].geometry.coords) == [
        (0.0, 0.0),
        (1.0, 0.0),
        (10.0, 0.0),
    ]
    assert not graph.silent_fix
    assert not graph.content_repair


def test_advance_right_references_but_does_not_own_ordinary_access() -> None:
    roads = {
        (RoadSource.RCSD, "left"): _road(
            RoadSource.RCSD, "left", "n0", "n1", [(0, 0), (10, 0)]
        ),
        (RoadSource.RCSD, "right"): _road(
            RoadSource.RCSD, "right", "n2", "n3", [(20, 0), (30, 0)]
        ),
        (RoadSource.RCSD, "ar"): _road(
            RoadSource.RCSD, "ar", "n1", "n2", [(10, 0), (20, 0)]
        ),
    }
    nodes = {
        (RoadSource.RCSD, node_id): _node(RoadSource.RCSD, node_id, x)
        for node_id, x in (("n0", 0), ("n1", 10), ("n2", 20), ("n3", 30))
    }
    left = _instruction(
        "left:i", "left", RoadSource.RCSD, "left", _copy(RoadSource.RCSD, "n0"), _copy(RoadSource.RCSD, "n1")
    )
    right = _instruction(
        "right:i", "right", RoadSource.RCSD, "right", _copy(RoadSource.RCSD, "n2"), _copy(RoadSource.RCSD, "n3")
    )
    ar = _instruction(
        "ar:i",
        "ar",
        RoadSource.RCSD,
        "ar",
        _copy(RoadSource.RCSD, "n1"),
        _copy(RoadSource.RCSD, "n2"),
        role=RoadRole.ADVANCE_RIGHT,
    )
    ar_plan = SegmentMaterializationInstruction(
        "ar",
        SegmentMaterializationType.ADVANCE_RIGHT,
        SegmentDecision.USE_RCSD,
        (ar,),
        attachments=(
            AttachmentInstruction(
                side=AttachmentEndpoint.SOURCE,
                parent_access_binding_id="left@n1",
                child_road_instruction_id="ar:i",
                child_segment_id="ar",
                child_endpoint=AttachmentEndpoint.SOURCE,
                target_kind=AttachmentTargetKind.ROAD_POSITION,
                parent_road_instruction_id="left:i",
                parent_position_m=10.0,
            ),
            AttachmentInstruction(
                side=AttachmentEndpoint.TARGET,
                parent_access_binding_id="right@n2",
                child_road_instruction_id="ar:i",
                child_segment_id="ar",
                child_endpoint=AttachmentEndpoint.TARGET,
                target_kind=AttachmentTargetKind.ROAD_POSITION,
                parent_road_instruction_id="right:i",
                parent_position_m=0.0,
            ),
        ),
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right", "ar"),
        segment_instructions=(
            _standard("left", left),
            _standard("right", right),
            ar_plan,
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    assert {
        row.parent_access_binding_id for row in graph.attachments
    } == {"left@n1", "right@n2"}
    assert {
        graph.access_bindings[row.parent_access_binding_id].segment_id
        for row in graph.attachments
    } == {"left", "right"}


def test_advance_right_cannot_own_an_access_binding() -> None:
    road = _road(RoadSource.RCSD, "ar", "n0", "n1", [(0, 0), (10, 0)])
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.RCSD, "n1"): _node(RoadSource.RCSD, "n1", 10),
    }
    ar = _instruction(
        "ar:i",
        "ar",
        RoadSource.RCSD,
        "ar",
        _copy(RoadSource.RCSD, "n0"),
        _copy(RoadSource.RCSD, "n1"),
        role=RoadRole.ADVANCE_RIGHT,
    )
    plan = SegmentMaterializationInstruction(
        "ar",
        SegmentMaterializationType.ADVANCE_RIGHT,
        SegmentDecision.USE_RCSD,
        (ar,),
        access_bindings=(
            SegmentAccessBinding(
                "ar@n0",
                "ar",
                "n0",
                AccessStructuralRole.ENDPOINT,
                AccessDirectionRole.EXIT,
                ("ar:i",),
                (_copy(RoadSource.RCSD, "n0"),),
            ),
        ),
    )
    with pytest.raises(MaterializationError, match="only ordinary"):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("ar",),
            segment_instructions=(plan,),
            source_roads={(RoadSource.RCSD, "ar"): road},
            source_nodes=nodes,
        )


def test_positive_keep_and_fallback_swsd_are_separately_reported() -> None:
    roads = {
        (RoadSource.SWSD, "keep"): _road(
            RoadSource.SWSD, "keep", "k0", "k1", [(0, 0), (5, 0)]
        ),
        (RoadSource.SWSD, "fallback"): _road(
            RoadSource.SWSD, "fallback", "f0", "f1", [(10, 0), (15, 0)]
        ),
    }
    nodes = {
        (RoadSource.SWSD, node_id): _node(RoadSource.SWSD, node_id, x)
        for node_id, x in (("k0", 0), ("k1", 5), ("f0", 10), ("f1", 15))
    }
    keep = _instruction(
        "keep:i", "keep", RoadSource.SWSD, "keep", _copy(RoadSource.SWSD, "k0"), _copy(RoadSource.SWSD, "k1")
    )
    fallback = _instruction(
        "fallback:i", "fallback", RoadSource.SWSD, "fallback", _copy(RoadSource.SWSD, "f0"), _copy(RoadSource.SWSD, "f1")
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("keep", "fallback"),
        segment_instructions=(
            _standard("keep", keep, decision=SegmentDecision.KEEP_SWSD),
            _standard(
                "fallback",
                fallback,
                decision=SegmentDecision.ABSTAIN,
                fallback=True,
            ),
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    assert graph.positive_keep_segment_ids == ("keep",)
    assert graph.fallback_segment_ids == ("fallback",)


def test_identical_no_owner_junction_road_can_be_shared_without_duplication() -> None:
    roads = {
        (RoadSource.RCSD, "left"): _road(
            RoadSource.RCSD, "left", "l0", "l1", [(0, 0), (5, 0)]
        ),
        (RoadSource.RCSD, "right"): _road(
            RoadSource.RCSD, "right", "r0", "r1", [(10, 0), (15, 0)]
        ),
        (RoadSource.RCSD, "junction"): _road(
            RoadSource.RCSD, "junction", "l1", "r0", [(5, 0), (10, 0)]
        ),
    }
    nodes = {
        (RoadSource.RCSD, node_id): _node(RoadSource.RCSD, node_id, x)
        for node_id, x in (("l0", 0), ("l1", 5), ("r0", 10), ("r1", 15))
    }
    left = _instruction(
        "left:i", "left", RoadSource.RCSD, "left", _copy(RoadSource.RCSD, "l0"), _copy(RoadSource.RCSD, "l1")
    )
    right = _instruction(
        "right:i", "right", RoadSource.RCSD, "right", _copy(RoadSource.RCSD, "r0"), _copy(RoadSource.RCSD, "r1")
    )
    shared = _instruction(
        "junction:i",
        "",
        RoadSource.RCSD,
        "junction",
        _copy(RoadSource.RCSD, "l1"),
        _copy(RoadSource.RCSD, "r0"),
        role=RoadRole.JUNCTION_CONNECTIVITY,
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("left", "right"),
        segment_instructions=(
            replace(
                _standard("left", left),
                roads=(left, shared),
            ),
            replace(
                _standard("right", right),
                roads=(right, shared),
            ),
        ),
        source_roads=roads,
        source_nodes=nodes,
    )
    assert len(graph.roads) == 3
    assert sum(
        road.role is RoadRole.JUNCTION_CONNECTIVITY for road in graph.roads
    ) == 1


def test_materializer_rejects_skeleton_or_crs_drift() -> None:
    source = _road(
        RoadSource.RCSD, "r", "n0", "n1", [(0, 0), (10, 0)]
    )
    instruction = _instruction(
        "s:i", "s", RoadSource.RCSD, "r", _copy(RoadSource.RCSD, "n0"), _copy(RoadSource.RCSD, "n1")
    )
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.RCSD, "n1"): _node(RoadSource.RCSD, "n1", 10),
    }
    with pytest.raises(MaterializationError, match="skeleton"):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("s", "missing"),
            segment_instructions=(_standard("s", instruction),),
            source_roads={(RoadSource.RCSD, "r"): source},
            source_nodes=nodes,
        )
    with pytest.raises(MaterializationError, match="CRS"):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("s",),
            segment_instructions=(_standard("s", instruction),),
            source_roads={
                (RoadSource.RCSD, "r"): replace(source, crs="EPSG:4326")
            },
            source_nodes=nodes,
        )


def test_declared_node_must_match_the_materialized_road_endpoint() -> None:
    source = _road(
        RoadSource.RCSD, "r", "n0", "n1", [(0, 0), (10, 0)]
    )
    nodes = {
        (RoadSource.RCSD, "n0"): _node(RoadSource.RCSD, "n0", 0),
        (RoadSource.RCSD, "n1"): _node(RoadSource.RCSD, "n1", 9),
    }
    instruction = _instruction(
        "s:i", "s", RoadSource.RCSD, "r", _copy(RoadSource.RCSD, "n0"), _copy(RoadSource.RCSD, "n1")
    )
    with pytest.raises(MaterializationError, match="target Node"):
        materialize_target_a_roadgraph(
            frozen_segment_ids=("s",),
            segment_instructions=(_standard("s", instruction),),
            source_roads={(RoadSource.RCSD, "r"): source},
            source_nodes=nodes,
        )
