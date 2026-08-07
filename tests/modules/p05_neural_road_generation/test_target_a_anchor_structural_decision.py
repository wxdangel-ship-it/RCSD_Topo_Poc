from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_decision import (
    ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM,
    AnchorMemberReleaseProposal,
    TargetAAnchorStructuralBatch,
    TargetAAnchorStructuralConfig,
    TargetAAnchorStructuralDecoder,
    TargetAAnchorStructuralJointHead,
    apply_anchor_cardinality_consistency_gate,
    build_anchor_structural_batch_from_joint,
    decode_expected_floor_cardinality,
    decode_threshold_cardinality,
    ordinal_cardinality_probabilities,
)


def _batch() -> TargetAAnchorStructuralBatch:
    return TargetAAnchorStructuralBatch(
        object_features=torch.randn(2, 8),
        member_features=torch.randn(
            2,
            4,
            ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM,
        ),
        member_mask=torch.tensor(
            [[True, True, True, False], [True, True, True, True]]
        ),
        member_is_road=torch.tensor(
            [[False, True, True, False], [True, True, False, False]]
        ),
        edge_src=torch.tensor([1, 2, 4, 5], dtype=torch.long),
        edge_dst=torch.tensor([2, 1, 5, 4], dtype=torch.long),
        edge_features=torch.randn(4, 7),
    )


def test_structural_decoder_has_joint_truth_free_outputs() -> None:
    config = TargetAAnchorStructuralConfig(
        object_feature_dim=8,
        hidden_dim=32,
        num_heads=4,
        feedforward_dim=64,
        graph_layers=1,
        set_layers=1,
        dropout=0.0,
        max_cardinality=8,
    )
    model = TargetAAnchorStructuralDecoder(config).eval()

    with torch.no_grad():
        output = model(_batch())

    assert output.relation_logits.shape == (2, 3)
    assert output.object_type_logits.shape == (2, 2)
    assert output.cardinality_logits.shape == (2, 8)
    assert output.ordinal_cardinality_logits.shape == (2, 7)
    assert output.member_logits.shape == (2, 4)
    assert output.decision_context.shape == (2, 35)
    assert torch.isneginf(output.member_logits[0, 3])
    assert torch.isfinite(output.member_logits[_batch().member_mask]).all()


def test_structural_batch_contract_excludes_training_truth() -> None:
    names = {field.name for field in fields(TargetAAnchorStructuralBatch)}

    assert names == {
        "object_features",
        "member_features",
        "member_mask",
        "member_is_road",
        "edge_src",
        "edge_dst",
        "edge_features",
    }
    assert not names.intersection(
        {
            "relation_target",
            "type_target",
            "cardinality_target",
            "member_target",
            "acceptable_sets",
        }
    )


def test_structural_decoder_cannot_select_an_unavailable_object_type() -> None:
    batch = _batch()
    batch = TargetAAnchorStructuralBatch(
        object_features=batch.object_features[:1],
        member_features=batch.member_features[:1],
        member_mask=torch.tensor([[True, True, True, False]]),
        member_is_road=torch.tensor([[True, True, True, False]]),
        edge_src=batch.edge_src[:2],
        edge_dst=batch.edge_dst[:2],
        edge_features=batch.edge_features[:2],
    )
    config = TargetAAnchorStructuralConfig(
        object_feature_dim=8,
        hidden_dim=32,
        num_heads=4,
        feedforward_dim=64,
        graph_layers=1,
        set_layers=1,
        dropout=0.0,
        max_cardinality=8,
    )

    with torch.no_grad():
        output = TargetAAnchorStructuralDecoder(config).eval()(batch)

    assert torch.isneginf(output.object_type_logits[0, 0])
    assert torch.isfinite(output.object_type_logits[0, 1])
    assert output.object_type_logits.argmax(dim=-1).tolist() == [1]


def test_joint_adapter_reuses_shared_object_embeddings_and_raw_structure() -> None:
    member_mask = torch.tensor([[[True, True, True]]])
    member_is_road = torch.tensor([[[False, True, True]]])
    relation_mask = torch.zeros((1, 1, 3, 3), dtype=torch.bool)
    relation_mask[0, 0, 1, 2] = True
    relation_features = torch.zeros((1, 1, 3, 3, 7))
    relation_features[0, 0, 1, 2, 0] = 1.0
    batch = SimpleNamespace(
        anchor_object_indices=torch.tensor([[1]], dtype=torch.long),
        anchor_member_mask=member_mask,
        anchor_member_is_road=member_is_road,
        anchor_member_arm_features=torch.randn(1, 1, 3, 2, 7),
        anchor_member_arm_mask=torch.tensor(
            [[[[True, True], [True, False], [False, False]]]]
        ),
        anchor_member_local_features=torch.randn(1, 1, 3, 12),
        anchor_member_relation_features=relation_features,
        anchor_member_relation_mask=relation_mask,
    )
    shared = torch.randn(1, 3, 8)

    structural = build_anchor_structural_batch_from_joint(
        batch,  # type: ignore[arg-type]
        shared_object_embeddings=shared,
    )

    assert structural.object_features.shape == (1, 8)
    assert torch.equal(structural.object_features[0], shared[0, 1])
    assert structural.member_features.shape == (
        1,
        3,
        ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM,
    )
    assert structural.edge_src.tolist() == [1]
    assert structural.edge_dst.tolist() == [2]
    assert structural.edge_features[0, 0].item() == 1.0


def test_joint_head_outputs_one_decision_per_anchor() -> None:
    member_mask = torch.tensor([[[True, True]]])
    batch = SimpleNamespace(
        anchor_object_indices=torch.tensor([[0]], dtype=torch.long),
        anchor_member_mask=member_mask,
        anchor_member_is_road=torch.tensor([[[False, True]]]),
        anchor_member_arm_features=torch.zeros(1, 1, 2, 1, 7),
        anchor_member_arm_mask=torch.ones(
            1,
            1,
            2,
            1,
            dtype=torch.bool,
        ),
        anchor_member_local_features=torch.zeros(1, 1, 2, 12),
        anchor_member_relation_features=torch.zeros(1, 1, 2, 2, 7),
        anchor_member_relation_mask=torch.zeros(
            1,
            1,
            2,
            2,
            dtype=torch.bool,
        ),
    )
    config = TargetAAnchorStructuralConfig(
        object_feature_dim=8,
        hidden_dim=32,
        num_heads=4,
        feedforward_dim=64,
        graph_layers=1,
        set_layers=1,
        dropout=0.0,
        max_cardinality=8,
    )
    head = TargetAAnchorStructuralJointHead(config).eval()

    with torch.no_grad():
        output = head(
            batch,  # type: ignore[arg-type]
            torch.randn(1, 1, 8),
        )

    assert output.relation_logits.shape == (1, 1, 3)
    assert output.object_type_logits.shape == (1, 1, 2)
    assert output.cardinality_logits.shape == (1, 1, 8)
    assert output.ordinal_cardinality_logits.shape == (1, 1, 7)
    assert output.member_logits.shape == (1, 1, 2)


def test_joint_head_ignores_padded_anchor_groups_and_scatters_outputs() -> None:
    member_mask = torch.tensor(
        [
            [[True, True], [False, False]],
            [[True, True], [True, False]],
        ]
    )
    batch = SimpleNamespace(
        anchor_object_indices=torch.tensor(
            [[0, -1], [1, 2]],
            dtype=torch.long,
        ),
        anchor_member_mask=member_mask,
        anchor_member_is_road=torch.tensor(
            [
                [[False, True], [False, False]],
                [[True, True], [False, False]],
            ]
        ),
        anchor_member_arm_features=torch.zeros(2, 2, 2, 1, 7),
        anchor_member_arm_mask=member_mask.unsqueeze(-1),
        anchor_member_local_features=torch.zeros(2, 2, 2, 12),
        anchor_member_relation_features=torch.zeros(2, 2, 2, 2, 7),
        anchor_member_relation_mask=torch.zeros(
            2,
            2,
            2,
            2,
            dtype=torch.bool,
        ),
    )
    config = TargetAAnchorStructuralConfig(
        object_feature_dim=8,
        hidden_dim=32,
        num_heads=4,
        feedforward_dim=64,
        graph_layers=1,
        set_layers=1,
        dropout=0.0,
        max_cardinality=8,
    )

    with torch.no_grad():
        output = TargetAAnchorStructuralJointHead(config).eval()(
            batch,  # type: ignore[arg-type]
            torch.randn(2, 3, 8),
        )

    assert output.relation_logits.shape == (2, 2, 3)
    assert torch.equal(
        output.relation_logits[0, 1],
        torch.zeros_like(output.relation_logits[0, 1]),
    )
    assert torch.isfinite(output.relation_logits[0, 0]).all()
    assert torch.isfinite(output.relation_logits[1, 0]).all()
    assert torch.isfinite(output.relation_logits[1, 1]).all()
    assert torch.equal(
        output.member_logits[0, 1],
        torch.zeros_like(output.member_logits[0, 1]),
    )


def test_cardinality_decoders_reproduce_target_like_disagreement() -> None:
    probabilities = torch.tensor(
        [[0.74, 0.73, 0.72, 0.71, 0.70, 0.05, 0.01]]
    )
    available = torch.tensor([8])

    release = decode_threshold_cardinality(
        probabilities,
        threshold=0.80,
        available_cardinality=available,
    )
    expected = decode_expected_floor_cardinality(
        probabilities,
        available_cardinality=available,
    )

    assert release.tolist() == [1]
    assert expected.tolist() == [4]


def test_ordinal_probabilities_are_monotonic() -> None:
    logits = torch.tensor([[0.0, 2.0, -1.0, 3.0]])

    probabilities = ordinal_cardinality_probabilities(logits)

    assert probabilities.shape == (1, 4)
    assert bool(
        (probabilities[:, 1:] <= probabilities[:, :-1]).all()
    )


def test_cardinality_gate_accepts_agreement_without_rewriting() -> None:
    proposal = AnchorMemberReleaseProposal(
        anchor_id="1633165",
        relation_state="rcsd_present_not_junction",
        object_type="ROAD",
        member_ids=(
            "ROAD:5391329551450177",
            "ROAD:5391329551450189",
        ),
    )

    decision = apply_anchor_cardinality_consistency_gate(
        proposal,
        expected_floor_cardinality=2,
        upstream_accepted=True,
    )

    assert decision.accepted
    assert decision.reason == "CARDINALITY_DECODERS_AGREE"
    assert decision.proposal is proposal
    assert decision.proposal.member_ids == proposal.member_ids


def test_cardinality_gate_only_downgrades_disagreement() -> None:
    proposal = AnchorMemberReleaseProposal(
        anchor_id="1633165",
        relation_state="rcsd_present_not_junction",
        object_type="ROAD",
        member_ids=("ROAD:5391329551450265",),
    )

    decision = apply_anchor_cardinality_consistency_gate(
        proposal,
        expected_floor_cardinality=6,
        upstream_accepted=True,
    )

    assert not decision.accepted
    assert decision.reason == "CARDINALITY_DECODER_DISAGREEMENT"
    assert decision.release_cardinality == 1
    assert decision.expected_floor_cardinality == 6
    assert decision.proposal is proposal
    assert decision.proposal.member_ids == ("ROAD:5391329551450265",)


def test_cardinality_gate_cannot_upgrade_upstream_abstain() -> None:
    proposal = AnchorMemberReleaseProposal(
        anchor_id="1",
        relation_state="success_required_rcsd_junction",
        object_type="NODE",
        member_ids=("NODE:2",),
    )

    decision = apply_anchor_cardinality_consistency_gate(
        proposal,
        expected_floor_cardinality=1,
        upstream_accepted=False,
    )

    assert not decision.accepted
    assert decision.reason == "UPSTREAM_NOT_ACCEPTED"


def test_release_proposal_rejects_mixed_object_types() -> None:
    proposal = AnchorMemberReleaseProposal(
        anchor_id="1",
        relation_state="rcsd_present_not_junction",
        object_type="ROAD",
        member_ids=("ROAD:2", "NODE:3"),
    )

    with pytest.raises(ValueError, match="mixes object types"):
        proposal.validate()
