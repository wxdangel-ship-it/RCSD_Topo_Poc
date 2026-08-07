from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    CompletePlanScoreOutput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionPredictionError,
    JunctionResultPrediction,
    QualityState,
    Step1DriveZoneState,
    SurfacePlan,
)


@dataclass(frozen=True)
class FrozenBusinessDecision:
    """Stage decisions that structured decoding may consume but never rewrite."""

    junction_key: str
    step1_drivezone_state: Step1DriveZoneState
    surface_plan: SurfacePlan
    anchor_result: AnchorResult
    quality_state: QualityState
    review_reason: str = ""

    def validate(self) -> None:
        if not self.junction_key.strip():
            raise JunctionPredictionError("frozen decision junction_key is blank")
        self.surface_plan.validate()
        self.anchor_result.validate()
        if self.quality_state != QualityState.NORMAL and not self.review_reason.strip():
            raise JunctionPredictionError(
                "non-normal frozen decision requires a review reason"
            )
        if (
            self.anchor_result.state == AnchorState.SUCCESS
            and self.step1_drivezone_state == Step1DriveZoneState.ABSTAIN
        ):
            raise JunctionPredictionError(
                "successful frozen anchor cannot bypass an abstained Step1"
            )

    def matches(self, candidate: CandidatePlan) -> bool:
        return (
            candidate.step1_drivezone_state == self.step1_drivezone_state
            and candidate.surface_plan == self.surface_plan
            and candidate.anchor_result == self.anchor_result
            and candidate.quality_state == self.quality_state
            and candidate.review_reason == self.review_reason
        )


class CandidateConstrainedDecoder:
    """Selects only among plans bound to an already frozen business decision."""

    def __init__(
        self,
        *,
        minimum_confidence: float = 0.5,
        minimum_margin: float = 0.05,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be within [0, 1]")
        if not 0.0 <= minimum_margin <= 1.0:
            raise ValueError("minimum_margin must be within [0, 1]")
        self.minimum_confidence = float(minimum_confidence)
        self.minimum_margin = float(minimum_margin)

    @staticmethod
    def _validate_scores(
        binding: CandidateBinding,
        plan_confidences: Mapping[str, float],
        component_confidences: Mapping[str, float],
    ) -> None:
        known_plan_ids = {plan.plan_id for plan in binding.plans}
        unexpected = sorted(set(plan_confidences) - known_plan_ids)
        if unexpected:
            raise JunctionPredictionError(
                "decoder score refers to an unbound candidate: "
                + ", ".join(unexpected)
            )
        all_values = tuple(plan_confidences.values()) + tuple(
            component_confidences.values()
        )
        if any(
            not math.isfinite(float(value)) or value < 0.0 or value > 1.0
            for value in all_values
        ):
            raise JunctionPredictionError("decoder confidence is outside [0, 1]")

    @staticmethod
    def _abstain(
        frozen: FrozenBusinessDecision,
        reason: str,
        component_confidences: Mapping[str, float],
    ) -> JunctionResultPrediction:
        return JunctionResultPrediction.abstained(
            junction_key=frozen.junction_key,
            review_reason=reason,
            component_confidences=component_confidences,
        )

    def decode(
        self,
        *,
        binding: CandidateBinding,
        frozen: FrozenBusinessDecision,
        plan_confidences: Mapping[str, float],
        component_confidences: Mapping[str, float],
    ) -> JunctionResultPrediction:
        binding.validate()
        frozen.validate()
        if binding.junction_key != frozen.junction_key:
            raise JunctionPredictionError(
                "candidate binding and frozen decision identities differ"
            )
        self._validate_scores(binding, plan_confidences, component_confidences)

        if frozen.step1_drivezone_state == Step1DriveZoneState.ABSTAIN:
            return self._abstain(
                frozen,
                "FROZEN_STEP1_ABSTAIN",
                component_confidences,
            )
        if frozen.anchor_result.state == AnchorState.ABSTAIN:
            return self._abstain(
                frozen,
                "FROZEN_ANCHOR_ABSTAIN",
                component_confidences,
            )

        compatible = tuple(
            plan
            for plan in binding.plans
            if frozen.matches(plan) and plan.plan_id in plan_confidences
        )
        if not compatible:
            return self._abstain(
                frozen,
                "NO_CANDIDATE_FOR_FROZEN_BUSINESS_DECISION",
                component_confidences,
            )
        ranked = sorted(
            compatible,
            key=lambda plan: (-float(plan_confidences[plan.plan_id]), plan.plan_id),
        )
        selected = ranked[0]
        selected_confidence = float(plan_confidences[selected.plan_id])
        if selected_confidence < self.minimum_confidence:
            return self._abstain(
                frozen,
                "LOW_COMPLETE_PLAN_CONFIDENCE",
                component_confidences,
            )
        if len(ranked) > 1:
            second_confidence = float(plan_confidences[ranked[1].plan_id])
            if selected_confidence - second_confidence < self.minimum_margin:
                return self._abstain(
                    frozen,
                    "AMBIGUOUS_COMPLETE_PLAN_MARGIN",
                    component_confidences,
                )

        prediction = JunctionResultPrediction.from_candidate(
            junction_key=frozen.junction_key,
            candidate=selected,
            complete_plan_confidence=selected_confidence,
            component_confidences=component_confidences,
        )
        prediction.validate(binding)
        return prediction

    def decode_from_model_output(
        self,
        *,
        binding: CandidateBinding,
        frozen: FrozenBusinessDecision,
        complete_plan_scores: CompletePlanScoreOutput,
        batch_index: int,
        component_confidences: Mapping[str, float],
    ) -> JunctionResultPrediction:
        indices = tuple(
            index
            for index in range(len(complete_plan_scores.plan_ids))
            if int(complete_plan_scores.plan_batch_indices[index]) == batch_index
        )
        plan_ids = tuple(complete_plan_scores.plan_ids[index] for index in indices)
        if len(set(plan_ids)) != len(plan_ids):
            raise JunctionPredictionError(
                "model emitted duplicate complete plan IDs for one Junction"
            )
        if set(plan_ids) != {plan.plan_id for plan in binding.plans}:
            raise JunctionPredictionError(
                "model complete-plan scores do not cover the bound candidate set"
            )
        confidences = torch.sigmoid(
            complete_plan_scores.logits[
                torch.tensor(
                    indices,
                    dtype=torch.long,
                    device=complete_plan_scores.logits.device,
                )
            ]
        )
        return self.decode(
            binding=binding,
            frozen=frozen,
            plan_confidences={
                plan_id: float(confidence.detach())
                for plan_id, confidence in zip(plan_ids, confidences)
            },
            component_confidences=component_confidences,
        )
