from __future__ import annotations

from dataclasses import replace

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_decoder import (
    DecodeResult,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_full_chain_ledger import (
    PreparedAutomaticInstruction,
    assemble_full_chain_materialization_ledger,
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
    FallbackScope,
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    SegmentDecision,
    SegmentPlanDecision,
)


def _node_recipe(source: RoadSource, node_id: str) -> NodeRecipe:
    return NodeRecipe(
        kind=NodeRecipeKind.COPY_SOURCE_NODE,
        source_kind=source,
        source_node_id=node_id,
    )


def _standard_instruction(
    *,
    segment_id: str,
    source: RoadSource,
    road_id: str,
    start_node_id: str,
    end_node_id: str,
    decision: SegmentDecision,
    fallback: bool,
) -> SegmentMaterializationInstruction:
    instruction_id = f"{source.value.lower()}:{segment_id}:{road_id}"
    road = RoadInstruction(
        instruction_id=instruction_id,
        owner_segment_id=segment_id,
        role=RoadRole.MAIN,
        direction=2,
        geometry_slices=(GeometrySlice(source, road_id),),
        source_node_recipe=_node_recipe(source, start_node_id),
        target_node_recipe=_node_recipe(source, end_node_id),
        output_road_id=road_id,
    )
    bindings = (
        SegmentAccessBinding(
            binding_id=f"{segment_id}@left",
            segment_id=segment_id,
            access_node_id="left",
            structural_role=AccessStructuralRole.ENDPOINT,
            direction_role=AccessDirectionRole.EXIT,
            road_instruction_ids=(instruction_id,),
            node_recipes=(_node_recipe(source, start_node_id),),
        ),
        SegmentAccessBinding(
            binding_id=f"{segment_id}@right",
            segment_id=segment_id,
            access_node_id="right",
            structural_role=AccessStructuralRole.ENDPOINT,
            direction_role=AccessDirectionRole.ENTER,
            road_instruction_ids=(instruction_id,),
            node_recipes=(_node_recipe(source, end_node_id),),
        ),
    )
    return SegmentMaterializationInstruction(
        segment_id=segment_id,
        segment_type=SegmentMaterializationType.STANDARD,
        decision=decision,
        roads=(road,),
        access_bindings=bindings,
        fallback_applied=fallback,
    )


def _advance_right_instruction(
    *,
    segment_id: str,
    source: RoadSource,
    road_id: str,
    decision: SegmentDecision,
    fallback: bool,
) -> SegmentMaterializationInstruction:
    instruction_id = f"{source.value.lower()}:{segment_id}:{road_id}"
    road = RoadInstruction(
        instruction_id=instruction_id,
        owner_segment_id=segment_id,
        role=RoadRole.ADVANCE_RIGHT,
        direction=2,
        geometry_slices=(GeometrySlice(source, road_id),),
        source_node_recipe=_node_recipe(source, "ar-source"),
        target_node_recipe=_node_recipe(source, "ar-target"),
        output_road_id=road_id,
    )
    return SegmentMaterializationInstruction(
        segment_id=segment_id,
        segment_type=SegmentMaterializationType.ADVANCE_RIGHT,
        decision=decision,
        roads=(road,),
        attachments=(
            AttachmentInstruction(
                AttachmentEndpoint.SOURCE,
                "left@access",
                instruction_id,
                segment_id,
                AttachmentEndpoint.SOURCE,
                AttachmentTargetKind.FROZEN_ACCESS_NODE,
                target_node_id="left-node",
            ),
            AttachmentInstruction(
                AttachmentEndpoint.TARGET,
                "right@access",
                instruction_id,
                segment_id,
                AttachmentEndpoint.TARGET,
                AttachmentTargetKind.FROZEN_ACCESS_NODE,
                target_node_id="right-node",
            ),
        ),
        fallback_applied=fallback,
    )


def _plan(
    *,
    segment_id: str,
    decision: SegmentDecision,
    source: RoadSource,
    road_id: str,
    plan_id: str,
) -> PlanCandidate:
    return PlanCandidate(
        plan_id=plan_id,
        segment_id=segment_id,
        decision=decision,
        roads=(
            RoadUse(
                source_kind=source,
                source_road_id=road_id,
                role=RoadRole.MAIN,
                owner_segment_id=segment_id,
                direction=0,
            ),
        ),
        source_access_road_id=road_id,
        target_access_road_id=road_id,
    )


def _decision(plan: PlanCandidate) -> SegmentPlanDecision:
    return SegmentPlanDecision(plan.segment_id, plan, 0.9)


def _fallback_decision(segment_id: str) -> SegmentPlanDecision:
    plan = PlanCandidate(
        plan_id=f"abstain:{segment_id}",
        segment_id=segment_id,
        decision=SegmentDecision.ABSTAIN,
        roads=(),
        source_access_road_id="",
        target_access_road_id="",
    )
    return SegmentPlanDecision(
        segment_id,
        plan,
        0.0,
        FallbackScope.SEGMENT,
        "MODEL_ABSTAIN",
    )


def test_positive_keep_is_distinct_from_executed_fallback() -> None:
    segment_id = "s1"
    fallback = _standard_instruction(
        segment_id=segment_id,
        source=RoadSource.SWSD,
        road_id="swsd-1",
        start_node_id="swsd-a",
        end_node_id="swsd-b",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    keep = _decision(
        _plan(
            segment_id=segment_id,
            decision=SegmentDecision.KEEP_SWSD,
            source=RoadSource.SWSD,
            road_id="swsd-1",
            plan_id="keep:s1",
        )
    )
    ledger = assemble_full_chain_materialization_ledger(
        frozen_segment_ids=(segment_id,),
        decode_result=DecodeResult((keep,), (), ("swsd-1",), ()),
        fallback_instructions={segment_id: fallback},
        automatic_instructions={},
    )
    instruction = ledger.segment_instructions[0]
    assert instruction.decision is SegmentDecision.KEEP_SWSD
    assert not instruction.fallback_applied
    assert ledger.positive_keep_segment_ids == (segment_id,)
    assert ledger.fallback_segment_ids == ()


def test_advance_right_positive_keep_requires_conditional_recipe() -> None:
    segment_id = "ar"
    fallback = _advance_right_instruction(
        segment_id=segment_id,
        source=RoadSource.SWSD,
        road_id="swsd-ar",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    plan = PlanCandidate(
        plan_id="keep:ar",
        segment_id=segment_id,
        decision=SegmentDecision.KEEP_SWSD,
        roads=(
            RoadUse(
                RoadSource.SWSD,
                "swsd-ar",
                RoadRole.ADVANCE_RIGHT,
                segment_id,
                0,
            ),
        ),
        source_access_road_id="left-swsd",
        target_access_road_id="right-swsd",
        node_recipes=(
            {"source_segment_id": "left", "target_segment_id": "right"},
        ),
        source_condition=(RoadSource.SWSD, RoadSource.SWSD),
    )
    with pytest.raises(ValueError, match="conditional executable recipe"):
        assemble_full_chain_materialization_ledger(
            frozen_segment_ids=(segment_id,),
            decode_result=DecodeResult(
                (),
                (_decision(plan),),
                ("swsd-ar",),
                (),
            ),
            fallback_instructions={segment_id: fallback},
            automatic_instructions={},
        )


def test_advance_right_recipe_does_not_own_adjacent_access_roads() -> None:
    segment_id = "ar"
    fallback = _advance_right_instruction(
        segment_id=segment_id,
        source=RoadSource.SWSD,
        road_id="swsd-ar",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    automatic = _advance_right_instruction(
        segment_id=segment_id,
        source=RoadSource.RCSD,
        road_id="rcsd-ar",
        decision=SegmentDecision.USE_RCSD,
        fallback=False,
    )
    plan = PlanCandidate(
        plan_id="use:ar",
        segment_id=segment_id,
        decision=SegmentDecision.USE_RCSD,
        roads=(
            RoadUse(
                RoadSource.RCSD,
                "rcsd-ar",
                RoadRole.ADVANCE_RIGHT,
                segment_id,
                0,
            ),
        ),
        source_access_road_id="left-ordinary-road",
        target_access_road_id="right-ordinary-road",
        node_recipes=(
            {"source_segment_id": "left", "target_segment_id": "right"},
        ),
        source_condition=(RoadSource.RCSD, RoadSource.SWSD),
    )
    ledger = assemble_full_chain_materialization_ledger(
        frozen_segment_ids=(segment_id,),
        decode_result=DecodeResult(
            (),
            (_decision(plan),),
            ("rcsd-ar",),
            (),
        ),
        fallback_instructions={segment_id: fallback},
        automatic_instructions={
            segment_id: PreparedAutomaticInstruction(
                plan.plan_id,
                automatic,
            )
        },
    )
    assert ledger.automatic_segment_ids == (segment_id,)
    assert (
        ledger.segment_instructions[0].roads[0].geometry_slices[0].source_road_id
        == "rcsd-ar"
    )


def test_automatic_recipe_must_match_the_exact_selected_plan() -> None:
    fallback = _standard_instruction(
        segment_id="s1",
        source=RoadSource.SWSD,
        road_id="swsd-1",
        start_node_id="swsd-a",
        end_node_id="swsd-b",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    automatic = _standard_instruction(
        segment_id="s1",
        source=RoadSource.RCSD,
        road_id="rcsd-1",
        start_node_id="rcsd-a",
        end_node_id="rcsd-b",
        decision=SegmentDecision.USE_RCSD,
        fallback=False,
    )
    selected = _decision(
        _plan(
            segment_id="s1",
            decision=SegmentDecision.USE_RCSD,
            source=RoadSource.RCSD,
            road_id="rcsd-1",
            plan_id="use:s1",
        )
    )
    with pytest.raises(ValueError, match="another model plan"):
        assemble_full_chain_materialization_ledger(
            frozen_segment_ids=("s1",),
            decode_result=DecodeResult((selected,), (), ("rcsd-1",), ()),
            fallback_instructions={"s1": fallback},
            automatic_instructions={
                "s1": PreparedAutomaticInstruction("wrong-plan", automatic)
            },
        )
    changed = replace(
        automatic,
        roads=(
            replace(
                automatic.roads[0],
                role=RoadRole.INTERNAL_CONNECTOR,
            ),
        ),
    )
    with pytest.raises(ValueError, match="source/role/ownership"):
        assemble_full_chain_materialization_ledger(
            frozen_segment_ids=("s1",),
            decode_result=DecodeResult((selected,), (), ("rcsd-1",), ()),
            fallback_instructions={"s1": fallback},
            automatic_instructions={
                "s1": PreparedAutomaticInstruction("use:s1", changed)
            },
        )


def test_full_chain_materializes_one_auto_rcsd_and_one_local_fallback() -> None:
    s1_fallback = _standard_instruction(
        segment_id="s1",
        source=RoadSource.SWSD,
        road_id="swsd-1",
        start_node_id="swsd-a",
        end_node_id="swsd-b",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    s2_fallback = _standard_instruction(
        segment_id="s2",
        source=RoadSource.SWSD,
        road_id="swsd-2",
        start_node_id="swsd-c",
        end_node_id="swsd-d",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    s1_automatic = _standard_instruction(
        segment_id="s1",
        source=RoadSource.RCSD,
        road_id="rcsd-1",
        start_node_id="rcsd-a",
        end_node_id="rcsd-b",
        decision=SegmentDecision.USE_RCSD,
        fallback=False,
    )
    s1_plan = _plan(
        segment_id="s1",
        decision=SegmentDecision.USE_RCSD,
        source=RoadSource.RCSD,
        road_id="rcsd-1",
        plan_id="use:s1",
    )
    ledger = assemble_full_chain_materialization_ledger(
        frozen_segment_ids=("s1", "s2"),
        decode_result=DecodeResult(
            (_decision(s1_plan), _fallback_decision("s2")),
            (),
            ("rcsd-1",),
            ("s2",),
        ),
        fallback_instructions={"s1": s1_fallback, "s2": s2_fallback},
        automatic_instructions={
            "s1": PreparedAutomaticInstruction("use:s1", s1_automatic)
        },
    )
    source_roads = {
        (RoadSource.RCSD, "rcsd-1"): SourceRoadRecord(
            RoadSource.RCSD,
            "rcsd-1",
            LineString([(0.0, 0.0), (1.0, 0.0)]),
            "rcsd-a",
            "rcsd-b",
            2,
            "EPSG:3857",
        ),
        (RoadSource.SWSD, "swsd-2"): SourceRoadRecord(
            RoadSource.SWSD,
            "swsd-2",
            LineString([(2.0, 0.0), (3.0, 0.0)]),
            "swsd-c",
            "swsd-d",
            2,
            "EPSG:3857",
        ),
    }
    source_nodes = {
        (RoadSource.RCSD, "rcsd-a"): SourceNodeRecord(
            RoadSource.RCSD, "rcsd-a", Point(0.0, 0.0), "EPSG:3857"
        ),
        (RoadSource.RCSD, "rcsd-b"): SourceNodeRecord(
            RoadSource.RCSD, "rcsd-b", Point(1.0, 0.0), "EPSG:3857"
        ),
        (RoadSource.SWSD, "swsd-c"): SourceNodeRecord(
            RoadSource.SWSD, "swsd-c", Point(2.0, 0.0), "EPSG:3857"
        ),
        (RoadSource.SWSD, "swsd-d"): SourceNodeRecord(
            RoadSource.SWSD, "swsd-d", Point(3.0, 0.0), "EPSG:3857"
        ),
    }
    contracts = tuple(
        FrozenSegmentAccessContract(
            binding_id=f"{segment_id}@{access_node_id}",
            segment_id=segment_id,
            access_node_id=access_node_id,
            structural_role=AccessStructuralRole.ENDPOINT,
            direction_role=direction,
        )
        for segment_id in ("s1", "s2")
        for access_node_id, direction in (
            ("left", AccessDirectionRole.EXIT),
            ("right", AccessDirectionRole.ENTER),
        )
    )
    graph = materialize_target_a_roadgraph(
        frozen_segment_ids=("s1", "s2"),
        frozen_access_contracts=contracts,
        segment_instructions=ledger.segment_instructions,
        source_roads=source_roads,
        source_nodes=source_nodes,
    )
    assert {road.source_references for road in graph.roads} == {
        ((RoadSource.RCSD, "rcsd-1"),),
        ((RoadSource.SWSD, "swsd-2"),),
    }
    assert graph.fallback_segment_ids == ("s2",)
    assert graph.skeleton_mutation_count == 0
    assert not graph.silent_fix
    assert not graph.content_repair


def test_unused_automatic_recipe_cannot_override_fallback() -> None:
    fallback = _standard_instruction(
        segment_id="s1",
        source=RoadSource.SWSD,
        road_id="swsd-1",
        start_node_id="swsd-a",
        end_node_id="swsd-b",
        decision=SegmentDecision.ABSTAIN,
        fallback=True,
    )
    automatic = _standard_instruction(
        segment_id="s1",
        source=RoadSource.RCSD,
        road_id="rcsd-1",
        start_node_id="rcsd-a",
        end_node_id="rcsd-b",
        decision=SegmentDecision.USE_RCSD,
        fallback=False,
    )
    with pytest.raises(ValueError, match="non-automatic"):
        assemble_full_chain_materialization_ledger(
            frozen_segment_ids=("s1",),
            decode_result=DecodeResult(
                (_fallback_decision("s1"),),
                (),
                (),
                ("s1",),
            ),
            fallback_instructions={"s1": fallback},
            automatic_instructions={
                "s1": PreparedAutomaticInstruction("use:s1", automatic)
            },
        )


def test_preflight_hard_mask_falls_back_only_the_rejected_segment() -> None:
    fallbacks = {
        segment_id: _standard_instruction(
            segment_id=segment_id,
            source=RoadSource.SWSD,
            road_id=f"swsd-{segment_id}",
            start_node_id=f"{segment_id}-a",
            end_node_id=f"{segment_id}-b",
            decision=SegmentDecision.ABSTAIN,
            fallback=True,
        )
        for segment_id in ("s1", "s2")
    }
    selected = tuple(
        _decision(
            _plan(
                segment_id=segment_id,
                decision=SegmentDecision.USE_RCSD,
                source=RoadSource.RCSD,
                road_id=f"rcsd-{segment_id}",
                plan_id=f"use:{segment_id}",
            )
        )
        for segment_id in ("s1", "s2")
    )
    s2_automatic = _standard_instruction(
        segment_id="s2",
        source=RoadSource.RCSD,
        road_id="rcsd-s2",
        start_node_id="s2-ra",
        end_node_id="s2-rb",
        decision=SegmentDecision.USE_RCSD,
        fallback=False,
    )
    ledger = assemble_full_chain_materialization_ledger(
        frozen_segment_ids=("s1", "s2"),
        decode_result=DecodeResult(
            selected,
            (),
            ("rcsd-s1", "rcsd-s2"),
            (),
        ),
        fallback_instructions=fallbacks,
        automatic_instructions={
            "s2": PreparedAutomaticInstruction("use:s2", s2_automatic)
        },
        preflight_fallback_reasons={
            "s1": "ACCESS_DIRECTION_ROLE_MISMATCH",
        },
    )
    assert ledger.automatic_segment_ids == ("s2",)
    assert ledger.fallback_segment_ids == ("s1",)
    assert ledger.preflight_rejected_segment_ids == ("s1",)
    assert ledger.preflight_fallback_reasons == (
        ("s1", "ACCESS_DIRECTION_ROLE_MISMATCH"),
    )
    instructions = {
        row.segment_id: row for row in ledger.segment_instructions
    }
    assert instructions["s1"].fallback_applied
    assert not instructions["s2"].fallback_applied
