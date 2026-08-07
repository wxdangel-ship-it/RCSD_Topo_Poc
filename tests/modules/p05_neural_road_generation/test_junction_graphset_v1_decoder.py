from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_decoder import (
    CandidateConstrainedDecoder,
    FrozenBusinessDecision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    CompletePlanScoreOutput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionPredictionError,
    QualityState,
    Step1DriveZoneState,
    SurfaceMode,
    SurfacePlan,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


NODE_1 = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
NODE_2 = ObjectRef(EvidenceRole.RCSD_NODE, "N2")
ROAD_1 = ObjectRef(EvidenceRole.RCSD_ROAD, "R1")
SURFACE_1 = ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1")
JUNCTION_KEY = "T03:fixture|S1"
SURFACE = SurfacePlan(
    mode=SurfaceMode.EXISTING_RCSD_INTERSECTION,
    selected_rcsdintersection_refs=(SURFACE_1,),
)
ANCHOR_1 = AnchorResult(
    state=AnchorState.SUCCESS,
    associated_rcsd_node_refs=(NODE_1,),
    associated_rcsd_road_refs=(ROAD_1,),
    selected_main_anchor=NODE_1,
)
ANCHOR_2 = replace(ANCHOR_1, associated_rcsd_node_refs=(NODE_2,), selected_main_anchor=NODE_2)


def _plan(plan_id: str, anchor: AnchorResult = ANCHOR_1) -> CandidatePlan:
    return CandidatePlan(
        plan_id=plan_id,
        step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
        surface_plan=SURFACE,
        anchor_result=anchor,
        quality_state=QualityState.NORMAL,
        review_reason="",
        planned_topology_signature=f"topology:{plan_id}",
    )


def _binding(*plans: CandidatePlan) -> CandidateBinding:
    return CandidateBinding(
        junction_key=JUNCTION_KEY,
        allowed_object_refs=(NODE_1, NODE_2, ROAD_1, SURFACE_1),
        plans=plans,
    )


def _frozen(anchor: AnchorResult = ANCHOR_1) -> FrozenBusinessDecision:
    return FrozenBusinessDecision(
        junction_key=JUNCTION_KEY,
        step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
        surface_plan=SURFACE,
        anchor_result=anchor,
        quality_state=QualityState.NORMAL,
    )


def test_later_plan_score_cannot_override_frozen_anchor() -> None:
    matching = _plan("matching", ANCHOR_1)
    different_anchor = _plan("different-anchor", ANCHOR_2)
    prediction = CandidateConstrainedDecoder().decode(
        binding=_binding(matching, different_anchor),
        frozen=_frozen(),
        plan_confidences={"matching": 0.72, "different-anchor": 0.99},
        component_confidences={"anchor": 0.91},
    )
    assert prediction.selected_plan_id == "matching"
    assert prediction.anchor_result == ANCHOR_1
    assert not prediction.abstain


def test_no_bound_plan_for_frozen_decision_abstains() -> None:
    prediction = CandidateConstrainedDecoder().decode(
        binding=_binding(_plan("different-anchor", ANCHOR_2)),
        frozen=_frozen(),
        plan_confidences={"different-anchor": 0.99},
        component_confidences={},
    )
    assert prediction.abstain
    assert prediction.review_reason == "NO_CANDIDATE_FOR_FROZEN_BUSINESS_DECISION"


@pytest.mark.parametrize(
    ("scores", "reason"),
    [
        ({"one": 0.49, "two": 0.10}, "LOW_COMPLETE_PLAN_CONFIDENCE"),
        ({"one": 0.81, "two": 0.80}, "AMBIGUOUS_COMPLETE_PLAN_MARGIN"),
    ],
)
def test_low_confidence_or_close_plan_margin_abstains(scores, reason) -> None:
    plans = (_plan("one"), _plan("two"))
    prediction = CandidateConstrainedDecoder(
        minimum_confidence=0.5,
        minimum_margin=0.05,
    ).decode(
        binding=_binding(*plans),
        frozen=_frozen(),
        plan_confidences=scores,
        component_confidences={},
    )
    assert prediction.abstain
    assert prediction.review_reason == reason


def test_unbound_plan_score_is_rejected_instead_of_expanding_candidates() -> None:
    with pytest.raises(JunctionPredictionError, match="unbound candidate"):
        CandidateConstrainedDecoder().decode(
            binding=_binding(_plan("known")),
            frozen=_frozen(),
            plan_confidences={"known": 0.8, "invented": 0.99},
            component_confidences={},
        )


def test_frozen_anchor_abstain_cannot_be_rewritten_to_success() -> None:
    frozen = FrozenBusinessDecision(
        junction_key=JUNCTION_KEY,
        step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
        surface_plan=SurfacePlan(mode=SurfaceMode.ABSTAIN),
        anchor_result=AnchorResult(state=AnchorState.ABSTAIN),
        quality_state=QualityState.REVIEW,
        review_reason="ANCHOR_UNCERTAIN",
    )
    prediction = CandidateConstrainedDecoder().decode(
        binding=_binding(_plan("success")),
        frozen=frozen,
        plan_confidences={"success": 0.99},
        component_confidences={},
    )
    assert prediction.abstain
    assert prediction.review_reason == "FROZEN_ANCHOR_ABSTAIN"


def test_decoder_consumes_complete_plan_logits_without_external_score_source() -> None:
    matching = _plan("matching", ANCHOR_1)
    different_anchor = _plan("different-anchor", ANCHOR_2)
    prediction = CandidateConstrainedDecoder().decode_from_model_output(
        binding=_binding(matching, different_anchor),
        frozen=_frozen(),
        complete_plan_scores=CompletePlanScoreOutput(
            plan_ids=("matching", "different-anchor"),
            plan_batch_indices=torch.tensor((0, 0), dtype=torch.long),
            logits=torch.tensor((2.0, 4.0)),
        ),
        batch_index=0,
        component_confidences={"anchor": 0.9},
    )
    assert prediction.selected_plan_id == "matching"
    assert prediction.anchor_result == ANCHOR_1
