from __future__ import annotations

from typing import Mapping

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
    ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
    TargetABatchTensors,
)


ORDINARY_ANCHOR_UNRESOLVED = 0
ORDINARY_ANCHOR_SUCCESS = 1
ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE = 2

ADVANCE_RIGHT_LOCAL_FALLBACK = 0
ADVANCE_RIGHT_SWSD_ONLY = 1
ADVANCE_RIGHT_RCSD_ONLY = 2
ADVANCE_RIGHT_MIXED_SPLICE = 3

ADVANCE_RIGHT_PLAN_TYPE_NAMES: Mapping[int, str] = {
    ADVANCE_RIGHT_LOCAL_FALLBACK: "LOCAL_FALLBACK",
    ADVANCE_RIGHT_SWSD_ONLY: "SWSD_ONLY",
    ADVANCE_RIGHT_RCSD_ONLY: "RCSD_ONLY",
    ADVANCE_RIGHT_MIXED_SPLICE: "MIXED_SPLICE",
}


def ordinary_free_run_business_states(
    outputs: Mapping[str, torch.Tensor],
    batch: TargetABatchTensors,
    ordinary_decision_probabilities: torch.Tensor,
    *,
    anchor_gate_pass_threshold: float,
    no_evidence_probability_threshold: float,
) -> dict[str, torch.Tensor]:
    """Apply anchoring as the hard gate for ordinary carrier decisions."""
    if not 0.0 < anchor_gate_pass_threshold < 1.0:
        raise ValueError("anchor gate threshold must be within (0, 1)")
    if not 0.0 <= no_evidence_probability_threshold <= 1.0:
        raise ValueError("NO_EVIDENCE threshold must be within [0, 1]")
    expected = (
        *batch.ordinary_plan_mask.shape[:2],
        3,
    )
    if ordinary_decision_probabilities.shape != expected:
        raise ValueError("ordinary decision probability shape differs")

    effective_status = outputs.get("anchor_outcome_effective_status")
    if effective_status is not None:
        if effective_status.shape != outputs["anchor_status_logits"].shape[:2]:
            raise ValueError("anchor outcome effective status shape differs")
        success = effective_status.eq(
            ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        )
        no_evidence = effective_status.eq(
            ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
        )
    else:
        status_probabilities = torch.softmax(
            outputs["anchor_status_logits"],
            dim=-1,
        )
        predicted_status = status_probabilities.argmax(dim=-1)
        success = predicted_status.eq(
            ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        )
        gate_logits = outputs.get("anchor_gate_logits")
        if gate_logits is not None:
            gate_pass = torch.softmax(gate_logits, dim=-1)[..., 1].ge(
                anchor_gate_pass_threshold
            )
            success = success & gate_pass
        no_evidence_index = ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
        no_evidence = (
            predicted_status.eq(no_evidence_index)
            & status_probabilities[..., no_evidence_index].ge(
                no_evidence_probability_threshold
            )
        )

    required = batch.ordinary_required_anchor_indices
    if required.ndim != 3 or required.shape[:2] != expected[:2]:
        raise ValueError("ordinary required-anchor index shape differs")
    valid = required.ge(0)
    if valid.any() and int(required[valid].max().item()) >= success.shape[1]:
        raise ValueError("ordinary required-anchor index is outside anchors")
    required_success = _gather_anchor_flags(success, required)
    required_no_evidence = _gather_anchor_flags(no_evidence, required)
    resolved = required_success | required_no_evidence
    has_required = valid.any(dim=-1)
    all_resolved = (resolved | ~valid).all(dim=-1) & has_required
    all_success = (required_success | ~valid).all(dim=-1) & has_required
    proven_no_evidence = (
        all_resolved
        & (required_no_evidence & valid).any(dim=-1)
    )
    anchor_state = torch.full_like(
        all_success,
        ORDINARY_ANCHOR_UNRESOLVED,
        dtype=torch.long,
    )
    anchor_state = torch.where(
        all_success,
        torch.full_like(anchor_state, ORDINARY_ANCHOR_SUCCESS),
        anchor_state,
    )
    anchor_state = torch.where(
        proven_no_evidence,
        torch.full_like(
            anchor_state,
            ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
        ),
        anchor_state,
    )
    return ordinary_business_states_from_anchor_state(
        anchor_state,
        ordinary_decision_probabilities,
    )


def ordinary_business_states_from_anchor_state(
    anchor_state: torch.Tensor,
    ordinary_decision_probabilities: torch.Tensor,
) -> dict[str, torch.Tensor]:
    """Apply a frozen independent anchor result as the carrier hard gate."""
    if ordinary_decision_probabilities.shape != (*anchor_state.shape, 3):
        raise ValueError("ordinary decision probability shape differs")
    if bool(
        (
            (anchor_state < ORDINARY_ANCHOR_UNRESOLVED)
            | (anchor_state > ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE)
        ).any()
    ):
        raise ValueError("ordinary anchor business state is unsupported")
    raw_decision = ordinary_decision_probabilities.argmax(dim=-1)
    empty = ordinary_decision_probabilities.sum(dim=-1).le(0.0)
    raw_decision = raw_decision.masked_fill(
        empty,
        ORDINARY_DECISION_ABSTAIN,
    )
    effective_decision = torch.full_like(
        raw_decision,
        ORDINARY_DECISION_ABSTAIN,
    )
    keep_allowed = raw_decision.eq(ORDINARY_DECISION_KEEP_SWSD) & (
        anchor_state.eq(ORDINARY_ANCHOR_SUCCESS)
        | anchor_state.eq(ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE)
    )
    use_allowed = (
        raw_decision.eq(ORDINARY_DECISION_USE_RCSD)
        & anchor_state.eq(ORDINARY_ANCHOR_SUCCESS)
    )
    effective_decision = effective_decision.masked_fill(
        keep_allowed,
        ORDINARY_DECISION_KEEP_SWSD,
    )
    effective_decision = effective_decision.masked_fill(
        use_allowed,
        ORDINARY_DECISION_USE_RCSD,
    )
    return {
        "anchor_state": anchor_state,
        "raw_decision": raw_decision,
        "effective_decision": effective_decision,
        "all_required_anchors_success": anchor_state.eq(
            ORDINARY_ANCHOR_SUCCESS
        ),
        "proven_no_evidence": anchor_state.eq(
            ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE
        ),
    }


def advance_right_plan_type_from_ordinary(
    source_decision: torch.Tensor,
    target_decision: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Derive the only legal T06 plan type from locked ordinary states."""
    if source_decision.shape != target_decision.shape:
        raise ValueError("AdvanceRight side decision shapes differ")
    ready = (
        source_decision.ne(ORDINARY_DECISION_ABSTAIN)
        & target_decision.ne(ORDINARY_DECISION_ABSTAIN)
    )
    both_keep = (
        source_decision.eq(ORDINARY_DECISION_KEEP_SWSD)
        & target_decision.eq(ORDINARY_DECISION_KEEP_SWSD)
    )
    both_use = (
        source_decision.eq(ORDINARY_DECISION_USE_RCSD)
        & target_decision.eq(ORDINARY_DECISION_USE_RCSD)
    )
    plan_type = torch.full_like(
        source_decision,
        ADVANCE_RIGHT_LOCAL_FALLBACK,
    )
    plan_type = plan_type.masked_fill(
        ready & both_keep,
        ADVANCE_RIGHT_SWSD_ONLY,
    )
    plan_type = plan_type.masked_fill(
        ready & both_use,
        ADVANCE_RIGHT_RCSD_ONLY,
    )
    plan_type = plan_type.masked_fill(
        ready & ~both_keep & ~both_use,
        ADVANCE_RIGHT_MIXED_SPLICE,
    )
    return plan_type, ready


def advance_right_business_plan_mask(
    plan_features: torch.Tensor,
    plan_mask: torch.Tensor,
    plan_type: torch.Tensor,
) -> torch.Tensor:
    """Mask plans that contradict the ordinary free-run final state."""
    if (
        plan_features.ndim != 4
        or plan_mask.shape != plan_features.shape[:3]
        or plan_type.shape != plan_features.shape[:2]
        or plan_mask.dtype != torch.bool
    ):
        raise ValueError("AdvanceRight business-plan tensors differ")
    swsd = plan_features[
        ...,
        ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX,
    ].gt(0.5)
    rcsd = plan_features[
        ...,
        ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
    ].gt(0.5)
    if bool((plan_mask & swsd.eq(rcsd)).any()):
        raise ValueError("AdvanceRight plan source marker is invalid")
    legal_swsd = plan_type.eq(ADVANCE_RIGHT_SWSD_ONLY).unsqueeze(-1)
    legal_rcsd = (
        plan_type.eq(ADVANCE_RIGHT_RCSD_ONLY)
        | plan_type.eq(ADVANCE_RIGHT_MIXED_SPLICE)
    ).unsqueeze(-1)
    return plan_mask & (
        (legal_swsd & swsd)
        | (legal_rcsd & rcsd)
    )


def apply_advance_right_business_mask(
    logits: torch.Tensor,
    business_mask: torch.Tensor,
) -> torch.Tensor:
    if logits.shape != business_mask.shape or business_mask.dtype != torch.bool:
        raise ValueError("AdvanceRight business logit/mask shapes differ")
    return logits.masked_fill(~business_mask, float("-inf"))


def _gather_anchor_flags(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    if values.ndim != 2 or indices.ndim != 3:
        raise ValueError("required-anchor gather shape differs")
    safe = indices.clamp_min(0)
    batch_indices = torch.arange(
        values.shape[0],
        device=values.device,
    )[:, None, None]
    return values[batch_indices, safe] & indices.ge(0)


__all__ = [
    "ADVANCE_RIGHT_LOCAL_FALLBACK",
    "ADVANCE_RIGHT_MIXED_SPLICE",
    "ADVANCE_RIGHT_PLAN_TYPE_NAMES",
    "ADVANCE_RIGHT_RCSD_ONLY",
    "ADVANCE_RIGHT_SWSD_ONLY",
    "ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE",
    "ORDINARY_ANCHOR_SUCCESS",
    "ORDINARY_ANCHOR_UNRESOLVED",
    "advance_right_business_plan_mask",
    "advance_right_plan_type_from_ordinary",
    "apply_advance_right_business_mask",
    "ordinary_business_states_from_anchor_state",
    "ordinary_free_run_business_states",
]
