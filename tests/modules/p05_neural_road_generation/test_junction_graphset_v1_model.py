from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
    JunctionTrainingOverlay,
    PairConstraint,
    RoadBreakSetTarget,
    RoadBreakTarget,
    _required_coverage_ranking_loss,
    compute_multitask_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorNodeRef,
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionEvidenceExample,
    JunctionPredictionError,
    ObjectTokenSpan,
    QualityState,
    RoadBreakOperation,
    Step1DriveZoneState,
    SurfaceMode,
    SurfacePlan,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_surface import (
    ConstraintState,
    SurfaceConstraint,
)


SWSD = ObjectRef(EvidenceRole.SWSD_JUNCTION, "S1")
DRIVEZONE = ObjectRef(EvidenceRole.DRIVEZONE, "D1")
INTERSECTION = ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1")
NODE_1 = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
NODE_2 = ObjectRef(EvidenceRole.RCSD_NODE, "N2")
ROAD_1 = ObjectRef(EvidenceRole.RCSD_ROAD, "R1")
ALL_REFS = (SWSD, DRIVEZONE, INTERSECTION, NODE_1, NODE_2, ROAD_1)


def _example(
    *,
    case_key: str = "T03:fixture",
    semantic_id: str = "S1",
    refs: tuple[ObjectRef, ...] = ALL_REFS,
) -> JunctionEvidenceExample:
    token_by_ref = {
        ref: torch.arange(index * 21, (index + 1) * 21, dtype=torch.float32) / 100.0
        for index, ref in enumerate(ALL_REFS)
    }
    tokens = torch.stack(tuple(token_by_ref[ref] for ref in refs))
    junction_key = f"{case_key}|{semantic_id}"
    plans = (
        CandidatePlan(
            plan_id="plan:a",
            step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
            surface_plan=SurfacePlan(
                mode=SurfaceMode.EXISTING_RCSD_INTERSECTION,
                selected_rcsdintersection_refs=(INTERSECTION,),
            ),
            anchor_result=AnchorResult(
                state=AnchorState.SUCCESS,
                associated_rcsd_node_refs=(NODE_1, NODE_2),
                associated_rcsd_road_refs=(ROAD_1,),
                selected_main_anchor=AnchorNodeRef.source_node(NODE_1),
                road_break_operations=(RoadBreakOperation(ROAD_1, (0.5,)),),
            ),
            quality_state=QualityState.NORMAL,
            review_reason="",
            planned_topology_signature="topology:a",
        ),
        CandidatePlan(
            plan_id="plan:b",
            step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
            surface_plan=SurfacePlan(
                mode=SurfaceMode.EXISTING_RCSD_INTERSECTION,
                selected_rcsdintersection_refs=(INTERSECTION,),
            ),
            anchor_result=AnchorResult(
                state=AnchorState.SUCCESS,
                associated_rcsd_node_refs=(NODE_1, NODE_2),
                associated_rcsd_road_refs=(ROAD_1,),
                selected_main_anchor=AnchorNodeRef.source_node(NODE_2),
                road_break_operations=(
                    RoadBreakOperation(ROAD_1, (0.25, 0.75)),
                ),
            ),
            quality_state=QualityState.NORMAL,
            review_reason="",
            planned_topology_signature="topology:b",
        ),
    )
    return JunctionEvidenceExample(
        junction_key=junction_key,
        case_key=case_key,
        semantic_junction_id=semantic_id,
        geometry_tokens=tokens,
        object_spans=tuple(
            ObjectTokenSpan(ref, index, index + 1)
            for index, ref in enumerate(refs)
        ),
        topology_edge_indices=torch.zeros((2, 0), dtype=torch.long),
        topology_edge_features=torch.zeros((0, 8), dtype=torch.float32),
        candidate_binding=CandidateBinding(
            junction_key=junction_key,
            allowed_object_refs=refs,
            plans=plans,
        ),
    )


def _scores_by_ref(refs, logits) -> dict[ObjectRef, float]:
    return {
        ref: float(logits[index].detach())
        for index, ref in enumerate(refs)
    }


def test_encoder_parameter_count_is_in_preregistered_range() -> None:
    model = JunctionGraphSetModel(dropout=0.0)
    assert 5_000_000 <= model.encoder.parameter_count <= 8_000_000
    assert model.encoder.parameter_count == 6_726_401


def test_object_order_is_equivariant_and_query_outputs_are_invariant() -> None:
    torch.manual_seed(17)
    model = JunctionGraphSetModel(dropout=0.0).eval()
    first = model((_example(),))
    second = model((_example(refs=tuple(reversed(ALL_REFS))),))

    assert torch.allclose(first.step1_logits, second.step1_logits, atol=1e-5)
    assert torch.allclose(first.surface.mode_logits, second.surface.mode_logits, atol=1e-5)
    assert torch.allclose(first.anchor_state_logits, second.anchor_state_logits, atol=1e-5)
    assert torch.allclose(
        first.surface.virtual_cardinality_logits,
        second.surface.virtual_cardinality_logits,
        atol=1e-5,
    )
    assert torch.equal(
        first.surface.virtual_cardinality_valid_mask,
        second.surface.virtual_cardinality_valid_mask,
    )
    assert _scores_by_ref(first.anchor_member_refs, first.anchor_member_logits) == pytest.approx(
        _scores_by_ref(second.anchor_member_refs, second.anchor_member_logits), abs=1e-5
    )
    assert torch.allclose(
        first.complete_plan.logits,
        second.complete_plan.logits,
        atol=1e-5,
    )


def test_variable_and_empty_examples_emit_every_head_without_padding() -> None:
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    empty = JunctionEvidenceExample.empty(
        case_key="T04:empty",
        semantic_junction_id="J-empty",
    )
    output = model((_example(), empty))

    assert output.junction_keys == ("T03:fixture|S1", "T04:empty|J-empty")
    assert tuple(output.step1_logits.shape) == (2, 4)
    assert tuple(output.surface.mode_logits.shape) == (2, 5)
    assert tuple(output.anchor_state_logits.shape) == (2, 5)
    assert tuple(output.quality_logits.shape) == (2, 6)
    assert output.anchor_member_refs == (NODE_1, NODE_2, ROAD_1)
    assert tuple(output.anchor_member_logits.shape) == (3,)
    assert output.anchor_member_cardinality_valid_mask.tolist() == [
        [True, True, True, True],
        [True, False, False, False],
    ]
    assert int(output.anchor_member_cardinality[1]) == 0
    assert output.node_equivalence.pair_refs == ((NODE_1, NODE_2),)
    assert output.road_break.road_refs == (ROAD_1,)
    assert tuple(output.road_break.fractions.shape) == (1,)
    assert output.complete_plan.plan_ids == ("plan:a", "plan:b")
    assert output.complete_plan.plan_batch_indices.tolist() == [0, 0]
    assert tuple(output.complete_plan.logits.shape) == (2,)


def test_teacher_conditions_follow_step1_then_surface_then_anchor_order() -> None:
    torch.manual_seed(23)
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    first = model(
        (_example(),),
        step1_state_indices=torch.tensor((0,), dtype=torch.long),
        surface_mode_indices=torch.tensor((0,), dtype=torch.long),
    )
    changed_step1 = model(
        (_example(),),
        step1_state_indices=torch.tensor((1,), dtype=torch.long),
        surface_mode_indices=torch.tensor((0,), dtype=torch.long),
    )
    changed_surface = model(
        (_example(),),
        step1_state_indices=torch.tensor((0,), dtype=torch.long),
        surface_mode_indices=torch.tensor((1,), dtype=torch.long),
    )

    assert torch.allclose(first.step1_logits, changed_step1.step1_logits)
    assert not torch.allclose(
        first.surface.mode_logits,
        changed_step1.surface.mode_logits,
    )
    assert torch.allclose(first.surface.mode_logits, changed_surface.surface.mode_logits)
    assert not torch.allclose(
        first.anchor_state_logits,
        changed_surface.anchor_state_logits,
    )
    assert first.conditioned_step1_indices.tolist() == [0]
    assert first.conditioned_surface_mode_indices.tolist() == [0]


def test_scheduled_masks_mix_teacher_and_model_conditions_per_record() -> None:
    torch.manual_seed(29)
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    examples = (
        _example(case_key="T03:scheduled-a"),
        _example(case_key="T03:scheduled-b"),
    )
    free = model(examples)
    step1_gold = torch.tensor(
        (
            (int(free.conditioned_step1_indices[0]) + 1)
            % len(Step1DriveZoneState),
            (int(free.conditioned_step1_indices[1]) + 1)
            % len(Step1DriveZoneState),
        ),
        dtype=torch.long,
    )
    surface_gold = torch.tensor(
        (
            (int(free.conditioned_surface_mode_indices[0]) + 1)
            % len(SurfaceMode),
            (int(free.conditioned_surface_mode_indices[1]) + 1)
            % len(SurfaceMode),
        ),
        dtype=torch.long,
    )
    mixed = model(
        examples,
        step1_state_indices=step1_gold,
        surface_mode_indices=surface_gold,
        step1_teacher_mask=torch.tensor((True, False)),
        surface_teacher_mask=torch.tensor((True, False)),
    )

    assert int(mixed.conditioned_step1_indices[0]) == int(step1_gold[0])
    assert int(mixed.conditioned_step1_indices[1]) == int(
        free.conditioned_step1_indices[1]
    )
    assert int(mixed.conditioned_surface_mode_indices[0]) == int(surface_gold[0])
    assert int(mixed.conditioned_surface_mode_indices[1]) == int(
        free.conditioned_surface_mode_indices[1]
    )


def test_scheduled_mask_requires_bool_batch_shape_and_teacher_indices() -> None:
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    example = (_example(case_key="T03:scheduled-invalid"),)

    with pytest.raises(JunctionPredictionError, match="requires teacher"):
        model(example, step1_teacher_mask=torch.tensor((True,)))
    with pytest.raises(JunctionPredictionError, match="BoolTensor"):
        model(
            example,
            step1_state_indices=torch.tensor((0,), dtype=torch.long),
            step1_teacher_mask=torch.tensor((1,), dtype=torch.long),
        )


def test_multitask_loss_supports_separate_surface_and_anchor_gold() -> None:
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0)
    output = model((_example(),))
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=1.0,
        step1_acceptable_indices=(0,),
        surface_mode_acceptable_indices=(0, 1),
        anchor_state_acceptable_indices=(0,),
        quality_acceptable_indices=(0,),
        acceptable_complete_plan_ids=("plan:a",),
        existing_surface_constraints=(
            SurfaceConstraint(INTERSECTION, ConstraintState.REQUIRED, 1.0),
        ),
        virtual_surface_constraints=(
            SurfaceConstraint(NODE_1, ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(NODE_2, ConstraintState.UNKNOWN, 0.0),
            SurfaceConstraint(ROAD_1, ConstraintState.FORBIDDEN, 1.0),
        ),
        virtual_surface_cardinality_target=1,
        anchor_member_constraints=(
            SurfaceConstraint(NODE_1, ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(NODE_2, ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(ROAD_1, ConstraintState.REQUIRED, 1.0),
        ),
        anchor_member_cardinality_target=3,
        acceptable_main_anchor_refs=(
            AnchorNodeRef.source_node(NODE_1),
            AnchorNodeRef.source_node(NODE_2),
        ),
        pair_constraints=(
            PairConstraint(NODE_1, NODE_2, ConstraintState.REQUIRED, 1.0),
        ),
        road_break_targets=(RoadBreakTarget(ROAD_1, True, 0.5, 1.0),),
        road_break_set_targets=(RoadBreakSetTarget(ROAD_1, (0.5,), 1.0),),
    )
    losses = compute_multitask_loss(output, (overlay,))

    assert set(losses) == {
        "step1",
        "surface_mode",
        "anchor_state",
        "quality",
        "existing_surface_object",
        "virtual_surface_member",
        "virtual_surface_cardinality",
        "virtual_surface_required_coverage",
        "anchor_member",
        "anchor_member_cardinality",
        "main_anchor",
        "node_equivalence",
        "road_break_presence",
        "road_break_fraction",
        "road_break_count",
        "road_break_set_fraction",
        "complete_plan",
        "total",
    }
    assert all(torch.isfinite(loss).item() for loss in losses.values())
    losses["total"].backward()
    assert model.encoder.token_projection.weight.grad is not None
    assert torch.isfinite(model.encoder.token_projection.weight.grad).all().item()
    assert model.encoder.summary_kind_embedding.grad is not None
    assert model.heads.member_head.cardinality_score[0].weight.grad is not None
    assert model.heads.break_head.count_head.weight.grad is not None
    assert model.heads.break_head.gap_head.weight.grad is not None
    assert model.heads.complete_plan_scorer.break_point_encoder[0].weight.grad is not None


def test_required_coverage_ranking_keeps_unknown_out_of_binary_gold() -> None:
    logits = torch.tensor((0.0, 3.0, -2.0), requires_grad=True)
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=1.0,
        virtual_surface_constraints=(
            SurfaceConstraint(NODE_1, ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(NODE_2, ConstraintState.UNKNOWN, 0.0),
            SurfaceConstraint(ROAD_1, ConstraintState.FORBIDDEN, 1.0),
        ),
        virtual_surface_cardinality_target=1,
    )

    loss = _required_coverage_ranking_loss(
        logits=logits,
        refs=(NODE_1, NODE_2, ROAD_1),
        batch_indices=torch.zeros((3,), dtype=torch.long),
        overlays=(overlay,),
        constraints_getter=lambda row: row.virtual_surface_constraints,
        acceptable_cardinality_getter=lambda row: (
            (row.virtual_surface_cardinality_target,)
            if row.virtual_surface_cardinality_target is not None
            else ()
        ),
    )

    assert float(loss.detach()) > 0.0
    loss.backward()
    assert float(logits.grad[0]) < 0.0
    assert float(logits.grad[1]) > 0.0
    assert float(logits.grad[2]) > 0.0


def test_missing_tasks_and_zero_weight_rows_have_zero_loss() -> None:
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0)
    output = model((_example(),))
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=0.0,
    )
    losses = compute_multitask_loss(output, (overlay,))
    assert float(losses["total"].detach()) == 0.0


def test_only_frozen_source_weights_are_accepted() -> None:
    output = JunctionGraphSetModel(hidden_dim=64, dropout=0.0)((_example(),))
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=0.3,
    )
    with pytest.raises(JunctionPredictionError, match="source weight"):
        compute_multitask_loss(output, (overlay,))


def test_cardinality_gold_cannot_exceed_visible_candidate_count() -> None:
    output = JunctionGraphSetModel(hidden_dim=64, dropout=0.0)((_example(),))
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=1.0,
        virtual_surface_cardinality_target=4,
    )

    with pytest.raises(JunctionPredictionError, match="exceeds"):
        compute_multitask_loss(output, (overlay,))


def test_virtual_surface_cardinality_accepts_unknown_member_range() -> None:
    output = JunctionGraphSetModel(hidden_dim=64, dropout=0.0)((_example(),))
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=1.0,
        virtual_surface_constraints=(
            SurfaceConstraint(NODE_1, ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(NODE_2, ConstraintState.UNKNOWN, 0.0),
            SurfaceConstraint(ROAD_1, ConstraintState.FORBIDDEN, 1.0),
        ),
        virtual_surface_acceptable_cardinalities=(1, 2),
    )

    losses = compute_multitask_loss(output, (overlay,))
    assert torch.isfinite(losses["virtual_surface_cardinality"]).item()
    assert torch.isfinite(losses["virtual_surface_required_coverage"]).item()


def test_multi_break_set_target_trains_count_and_every_ordered_fraction() -> None:
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0)
    output = model((_example(),))
    overlay = JunctionTrainingOverlay(
        junction_key="T03:fixture|S1",
        source_weight=1.0,
        road_break_set_targets=(
            RoadBreakSetTarget(ROAD_1, (0.25, 0.75), 1.0),
        ),
    )
    losses = compute_multitask_loss(output, (overlay,))

    assert float(losses["road_break_count"].detach()) > 0.0
    assert float(losses["road_break_set_fraction"].detach()) >= 0.0
    (losses["road_break_count"] + losses["road_break_set_fraction"]).backward()
    assert model.heads.break_head.count_head.weight.grad is not None
    assert model.heads.break_head.gap_head.weight.grad is not None
