from __future__ import annotations

from types import SimpleNamespace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_outcome_review import (
    ANCHOR_OUTCOME_FALLBACK,
    AnchorOutcomeReviewConfig,
    AnchorOutcomeReviewHead,
    compute_anchor_outcome_review_loss,
    decode_anchor_outcome_review,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
    ordinary_free_run_business_states,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_USE_RCSD,
)


def test_anchor_outcome_head_uses_same_forward_anchor_evidence() -> None:
    hidden_dim = 8
    outputs = {
        "locked_anchor_embeddings": torch.randn(1, 3, hidden_dim),
        "anchor_status_logits": torch.randn(1, 3, 5),
        "anchor_candidate_logits": torch.randn(1, 3, 4),
        "anchor_selection_success": torch.tensor([[True, False, True]]),
        "anchor_gate_logits": torch.randn(1, 3, 2),
        "anchor_type_logits": torch.randn(1, 3, 2),
        "anchor_cardinality_logits": torch.randn(1, 3, 2, 5),
    }
    batch = SimpleNamespace(
        anchor_candidate_mask=torch.tensor(
            [[[True, True, False, False], [True] * 4, [True, False, False, False]]]
        )
    )
    head = AnchorOutcomeReviewHead(
        AnchorOutcomeReviewConfig(
            hidden_dim=hidden_dim,
            head_hidden_dim=12,
            dropout=0.0,
        )
    )

    result = head(outputs, batch)

    assert result["anchor_outcome_logits"].shape == (1, 3, 3)
    assert result["_anchor_outcome_runtime_features"].shape == (1, 3, 24)
    assert result["anchor_outcome_effective_status"].shape == (1, 3)


def test_anchor_outcome_decode_only_releases_agreed_positive_outcomes() -> None:
    success = ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
    no_evidence = ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
    ambiguous = ANCHOR_STATUS_INDEX[AnchorStatus.AMBIGUOUS]
    logits = torch.tensor(
        [[[8.0, 0.0, 0.0], [0.0, 8.0, 0.0], [0.0, 0.0, 8.0], [8.0, 0.0, 0.0]]]
    )
    status_logits = torch.full((1, 4, 5), -8.0)
    status_logits[0, 0, success] = 8.0
    status_logits[0, 1, no_evidence] = 8.0
    status_logits[0, 2, ambiguous] = 8.0
    status_logits[0, 3, no_evidence] = 8.0
    gate_logits = torch.tensor([[[0.0, 8.0]] * 4])

    result = decode_anchor_outcome_review(
        logits,
        status_logits=status_logits,
        selection_success=torch.ones((1, 4), dtype=torch.bool),
        gate_logits=gate_logits,
        positive_release_threshold=0.5,
        fallback_threshold=0.5,
    )

    assert result["anchor_outcome_effective_status"].tolist() == [
        [
            success,
            no_evidence,
            ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN],
            ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN],
        ]
    ]
    assert result["anchor_outcome_explicit_fallback"].tolist() == [
        [False, False, True, False]
    ]
    assert result["anchor_outcome_review"].tolist() == [
        [False, False, False, True]
    ]
    assert int(result["anchor_outcome_predictions"][0, 2]) == (
        ANCHOR_OUTCOME_FALLBACK
    )


def test_anchor_outcome_loss_masks_unknown_truth() -> None:
    logits = torch.tensor(
        [[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]]],
        requires_grad=True,
    )
    outputs = {"anchor_outcome_logits": logits}
    status = torch.tensor(
        [[
            ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
            ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
            ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN],
        ]]
    )

    loss = compute_anchor_outcome_review_loss(
        outputs,
        anchor_status=status,
        anchor_status_mask=torch.tensor([[True, True, False]]),
        sample_weights=torch.ones((1, 3)),
    )
    loss.backward()

    assert torch.isfinite(loss)
    assert bool(logits.grad[0, :2].abs().sum().gt(0.0))
    assert torch.equal(logits.grad[0, 2], torch.zeros(3))


def test_outcome_review_is_a_hard_anchor_gate_for_ordinary_carrier() -> None:
    batch = SimpleNamespace(
        ordinary_plan_mask=torch.ones((1, 1, 1), dtype=torch.bool),
        ordinary_required_anchor_indices=torch.tensor([[[0]]]),
    )
    ordinary_probabilities = torch.tensor([[[0.0, 1.0, 0.0]]])
    status_logits = torch.full((1, 1, 5), -8.0)
    status_logits[0, 0, ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]] = 8.0
    outputs = {
        "anchor_status_logits": status_logits,
        "anchor_outcome_effective_status": torch.tensor(
            [[ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]]]
        ),
    }

    blocked = ordinary_free_run_business_states(
        outputs,
        batch,
        ordinary_probabilities,
        anchor_gate_pass_threshold=0.5,
        no_evidence_probability_threshold=0.5,
    )
    assert int(blocked["anchor_state"][0, 0]) == ORDINARY_ANCHOR_UNRESOLVED
    assert int(blocked["effective_decision"][0, 0]) == ORDINARY_DECISION_ABSTAIN

    outputs["anchor_outcome_effective_status"] = torch.tensor(
        [[ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]]]
    )
    released = ordinary_free_run_business_states(
        outputs,
        batch,
        ordinary_probabilities,
        anchor_gate_pass_threshold=0.5,
        no_evidence_probability_threshold=0.5,
    )
    assert int(released["anchor_state"][0, 0]) == ORDINARY_ANCHOR_SUCCESS
    assert int(released["effective_decision"][0, 0]) == ORDINARY_DECISION_USE_RCSD


def test_anchor_outcome_head_is_disabled_for_existing_checkpoints() -> None:
    config = TargetAEndToEndOrdinarySetConfig(hidden_dim=32)

    assert config.anchor_outcome_enabled is False
