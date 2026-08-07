from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionEvidenceBatch,
    JunctionEvidenceExample,
    JunctionIdentity,
    JunctionPredictionError,
    JunctionResultPrediction,
    NodeEquivalenceClass,
    ObjectTokenSpan,
    QualityState,
    RandomInitializedJunctionFreeRun,
    RoadBreakOperation,
    Step1DriveZoneState,
    SurfaceMode,
    SurfacePlan,
    run_untrained_identity_audit,
    validate_free_run_output,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


NODE_1 = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
NODE_2 = ObjectRef(EvidenceRole.RCSD_NODE, "N2")
ROAD_1 = ObjectRef(EvidenceRole.RCSD_ROAD, "R1")
SURFACE_1 = ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1")


def _candidate_plan() -> CandidatePlan:
    return CandidatePlan(
        plan_id="plan:complete:1",
        step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
        surface_plan=SurfacePlan(
            mode=SurfaceMode.EXISTING_RCSD_INTERSECTION,
            selected_rcsdintersection_refs=(SURFACE_1,),
        ),
        anchor_result=AnchorResult(
            state=AnchorState.SUCCESS,
            associated_rcsd_node_refs=(NODE_1, NODE_2),
            associated_rcsd_road_refs=(ROAD_1,),
            selected_main_anchor=NODE_1,
            node_equivalence_classes=(NodeEquivalenceClass((NODE_1, NODE_2)),),
            road_break_operations=(RoadBreakOperation(ROAD_1, (0.5,)),),
        ),
        quality_state=QualityState.NORMAL,
        review_reason="",
        planned_topology_signature="topology:fixture:1",
    )


def _example(*, case_key: str = "T03:fixture", semantic_id: str = "J1"):
    junction_key = f"{case_key}|{semantic_id}"
    plan = _candidate_plan()
    binding = CandidateBinding(
        junction_key=junction_key,
        allowed_object_refs=(NODE_1, NODE_2, ROAD_1, SURFACE_1),
        plans=(plan,),
    )
    return JunctionEvidenceExample(
        junction_key=junction_key,
        case_key=case_key,
        semantic_junction_id=semantic_id,
        geometry_tokens=torch.zeros((4, 21), dtype=torch.float32),
        object_spans=(
            ObjectTokenSpan(NODE_1, 0, 1),
            ObjectTokenSpan(NODE_2, 1, 2),
            ObjectTokenSpan(ROAD_1, 2, 3),
            ObjectTokenSpan(SURFACE_1, 3, 4),
        ),
        topology_edge_indices=torch.tensor([[0, 2], [2, 1]], dtype=torch.long),
        topology_edge_features=torch.zeros((2, 8), dtype=torch.float32),
        candidate_binding=binding,
    )


def test_complete_candidate_and_prediction_contract() -> None:
    example = _example()
    example.validate()
    candidate = example.candidate_binding.plan("plan:complete:1")
    prediction = JunctionResultPrediction.from_candidate(
        junction_key=example.junction_key,
        candidate=candidate,
        complete_plan_confidence=0.9,
        component_confidences={"anchor": 0.95, "surface": 0.92},
    )
    prediction.validate(example.candidate_binding)

    changed_anchor = replace(
        prediction.anchor_result,
        selected_main_anchor=ROAD_1,
    )
    changed_prediction = replace(prediction, anchor_result=changed_anchor)
    with pytest.raises(JunctionPredictionError, match="immutable bound"):
        changed_prediction.validate(example.candidate_binding)


def test_candidate_binding_rejects_out_of_scope_objects() -> None:
    binding = CandidateBinding(
        junction_key="T03:fixture|J1",
        allowed_object_refs=(NODE_1, NODE_2, SURFACE_1),
        plans=(_candidate_plan(),),
    )
    with pytest.raises(JunctionPredictionError, match="outside the bound"):
        binding.validate()


def test_non_success_anchor_cannot_carry_success_objects() -> None:
    anchor = AnchorResult(
        state=AnchorState.AMBIGUOUS,
        associated_rcsd_node_refs=(NODE_1,),
        selected_main_anchor=NODE_1,
    )
    with pytest.raises(JunctionPredictionError, match="cannot carry"):
        anchor.validate()


def test_variable_and_empty_batch_are_packed_without_padding() -> None:
    populated = _example()
    empty = JunctionEvidenceExample.empty(
        case_key="T04:empty",
        semantic_junction_id="J-empty",
    )
    batch = JunctionEvidenceBatch.from_examples((populated, empty))
    assert tuple(batch.geometry_tokens.shape) == (4, 21)
    assert batch.example_token_offsets.tolist() == [0, 4, 4]
    assert tuple(batch.topology_edge_features.shape) == (2, 8)
    assert batch.example_edge_offsets.tolist() == [0, 2, 2]

    empty_batch = JunctionEvidenceBatch.from_examples(())
    assert len(empty_batch) == 0
    assert tuple(empty_batch.geometry_tokens.shape) == (0, 21)
    assert tuple(empty_batch.topology_edge_features.shape) == (0, 8)


def test_random_initialized_free_run_is_safety_locked_to_abstain() -> None:
    batch = JunctionEvidenceBatch.from_examples(
        (
            _example(),
            JunctionEvidenceExample.empty(
                case_key="T04:empty",
                semantic_junction_id="J-empty",
            ),
        )
    )
    first_model = RandomInitializedJunctionFreeRun(seed=7)
    second_model = RandomInitializedJunctionFreeRun(seed=7)
    first = first_model(batch)
    second = second_model(batch)

    assert first == second
    assert first_model.parameter_count == 737
    assert all(prediction.abstain for prediction in first)
    assert all(prediction.selected_plan_id is None for prediction in first)
    assert validate_free_run_output(batch, first) == {
        "example_count": 2,
        "valid_count": 2,
        "invalid_count": 0,
        "abstain_count": 2,
        "non_abstain_count": 0,
    }


def test_invalid_edge_and_duplicate_batch_identity_are_blocked() -> None:
    invalid_edge = replace(
        _example(),
        topology_edge_indices=torch.tensor([[0], [99]], dtype=torch.long),
        topology_edge_features=torch.zeros((1, 8), dtype=torch.float32),
    )
    with pytest.raises(JunctionPredictionError, match="outside token range"):
        invalid_edge.validate()
    with pytest.raises(JunctionPredictionError, match="duplicate Junction"):
        JunctionEvidenceBatch.from_examples((_example(), _example()))


def test_prediction_count_mismatch_is_blocked() -> None:
    batch = JunctionEvidenceBatch.from_examples((_example(),))
    with pytest.raises(JunctionPredictionError, match="prediction count"):
        validate_free_run_output(batch, ())


def test_all_4288_development_denominator_can_safely_free_run() -> None:
    identities = [
        JunctionIdentity("STRONG_GOLD", f"strong:{index:04d}")
        for index in range(602)
    ] + [
        JunctionIdentity("T10_WEAK", f"weak:{index:04d}")
        for index in range(3686)
    ]
    audit = run_untrained_identity_audit(identities, batch_size=257, seed=11)
    assert audit["identity_count"] == 4288
    assert audit["valid_prediction_count"] == 4288
    assert audit["abstain_count"] == 4288
    assert audit["non_abstain_count"] == 0
    assert audit["invalid_prediction_count"] == 0
    assert audit["safety_locked"] is True
