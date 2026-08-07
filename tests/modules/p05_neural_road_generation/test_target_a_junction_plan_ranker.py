from __future__ import annotations

from types import SimpleNamespace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_plan_ranker import (
    JunctionCompletePlanRanker,
    JunctionPlanCandidateBatch,
    JunctionPlanGraphReranker,
    JunctionPlanTeacherAdapter,
    collate_junction_plan_candidates,
    generate_junction_plan_candidates,
    select_diverse_plan_shortlist,
)
from tests.modules.p05_neural_road_generation.test_target_a_junction_joint_network import (
    _batch,
)


def test_complete_plan_ranker_scores_and_decodes_whole_sets() -> None:
    batch = _batch()
    plans = JunctionPlanCandidateBatch(
        candidate_sets=torch.tensor(
            [
                [[True, False, False], [True, True, False], [False, True, True]],
                [[True, False, False], [False, True, False], [True, False, True]],
            ]
        ),
        candidate_mask=torch.tensor(
            [[True, True, True], [True, True, False]]
        ),
        inference_candidate_mask=torch.tensor(
            [[True, True, True], [True, True, False]]
        ),
        positive_mask=torch.tensor(
            [[False, True, False], [False, True, False]]
        ),
    )
    member_hidden = torch.randn(2, 3, 64, requires_grad=True)
    context = torch.randn(2, 64, requires_grad=True)
    ranker = JunctionCompletePlanRanker(64, dropout=0.0)
    logits = ranker(member_hidden, context, batch, plans)
    assert logits.shape == (2, 3)
    assert torch.isneginf(logits[1, 2])
    loss = ranker.loss_by_row(logits, plans).mean()
    assert torch.isfinite(loss)
    loss.backward()
    assert member_hidden.grad is not None
    prediction = ranker.decode(logits.detach(), plans)
    assert prediction.shape == batch.member_mask.shape


def test_candidate_generation_is_truth_independent_and_keeps_disconnected_pairs() -> None:
    base = {
        "member_ids": ("NODE:1", "NODE:2", "ROAD:3", "ROAD:4"),
        "candidate_ids": ("NODE:1", "ROAD:3|4"),
        "member_features": torch.tensor(
            [
                [0.0, 0.10] + [0.0] * 10,
                [0.0, 0.20] + [0.0] * 10,
                [1.0, 0.05] + [0.0] * 10,
                [1.0, 0.30] + [0.0] * 10,
            ]
        ),
        "member_relation_edges": (),
        "member_incidence_edges": (),
    }
    first = SimpleNamespace(**base, member_acceptable_sets=((0, 1),))
    second = SimpleNamespace(**base, member_acceptable_sets=((2,),))
    first_candidates = generate_junction_plan_candidates(first)
    second_candidates = generate_junction_plan_candidates(second)
    assert first_candidates == second_candidates
    assert frozenset((0, 1)) in first_candidates
    assert frozenset((2, 3)) in first_candidates

    training = collate_junction_plan_candidates((first,), training=True)
    inference = collate_junction_plan_candidates((first,), training=False)
    assert bool(training.positive_mask.any())
    assert not bool(inference.positive_mask.any()) is False
    positive_index = int(training.positive_mask[0].nonzero()[0])
    assert training.candidate_sets[0, positive_index, [0, 1]].all()


def test_one_way_branch_exposes_only_object_side_latents() -> None:
    from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_network import (
        JunctionJointConfig,
        JunctionJointNetwork,
    )

    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        business_plan_count=3,
        one_way_object_branch=True,
        one_way_object_hidden_dim=96,
        one_way_object_num_heads=4,
    )
    outputs = JunctionJointNetwork(config)(_batch())
    assert outputs["object_member_hidden"].shape == (2, 3, 96)
    assert outputs["object_decoder_context"].shape == (2, 96)


def test_teacher_adapter_is_identity_at_initialization_and_training_only() -> None:
    members = torch.randn(2, 3, 64)
    context = torch.randn(2, 64)
    mask = torch.tensor([[True, True, False], [True, True, True]])
    adapter = JunctionPlanTeacherAdapter(64, dropout=0.0)
    adapted_members, adapted_context = adapter(members, context, mask)
    assert torch.allclose(adapted_members[mask], members[mask])
    assert torch.allclose(adapted_context, context)
    assert torch.count_nonzero(adapted_members[~mask]) == 0


def test_training_candidate_limit_does_not_remove_gold_supervision() -> None:
    row = SimpleNamespace(
        member_ids=("NODE:1", "NODE:2", "ROAD:3", "ROAD:4"),
        candidate_ids=("NODE:1", "NODE:2", "ROAD:3", "ROAD:4"),
        member_features=torch.tensor(
            [
                [0.0, 0.10] + [0.0] * 10,
                [0.0, 0.20] + [0.0] * 10,
                [1.0, 0.05] + [0.0] * 10,
                [1.0, 0.30] + [0.0] * 10,
            ]
        ),
        member_relation_edges=(),
        member_incidence_edges=(),
        member_acceptable_sets=((0, 1, 2, 3),),
    )
    plans = collate_junction_plan_candidates(
        (row,), training=True, max_training_candidates=2
    )
    assert int(plans.inference_candidate_mask.sum()) == 2
    assert bool(plans.positive_mask.any())


def test_graph_reranker_uses_truth_independent_diverse_shortlist() -> None:
    batch = _batch()
    batch.member_features[:, :, 0] = torch.tensor([0.0, 0.0, 1.0])
    plans = JunctionPlanCandidateBatch(
        candidate_sets=torch.tensor(
            [
                [[True, False, False], [False, True, False], [True, True, False], [False, False, True]],
                [[True, False, False], [False, True, False], [True, False, True], [False, True, True]],
            ]
        ),
        candidate_mask=torch.ones(2, 4, dtype=torch.bool),
        inference_candidate_mask=torch.ones(2, 4, dtype=torch.bool),
        positive_mask=torch.tensor(
            [[False, False, True, False], [False, False, False, True]]
        ),
    )
    base_logits = torch.tensor([[4.0, 3.0, 2.0, 1.0], [1.0, 2.0, 3.0, 4.0]])
    shortlist, shortlist_base = select_diverse_plan_shortlist(
        base_logits,
        plans,
        batch,
        include_training_positives=True,
        overall_count=1,
        per_cardinality_count=1,
        per_role_count=1,
        max_candidates=3,
    )
    assert (shortlist.positive_mask & shortlist.candidate_mask).any(dim=1).all()
    member_hidden = torch.randn(2, 3, 64, requires_grad=True)
    context = torch.randn(2, 64, requires_grad=True)
    reranker = JunctionPlanGraphReranker(64, dropout=0.0)
    logits = reranker(member_hidden, context, batch, shortlist, shortlist_base)
    assert logits.shape == shortlist.candidate_mask.shape
    assert torch.isfinite(logits[shortlist.candidate_mask]).all()
    loss = reranker.loss_by_row(logits, shortlist).mean()
    loss.backward()
    assert member_hidden.grad is not None
    assert torch.isfinite(member_hidden.grad).all()
    assert all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in reranker.parameters()
    )

    changed_truth = JunctionPlanCandidateBatch(
        candidate_sets=plans.candidate_sets,
        candidate_mask=plans.candidate_mask,
        inference_candidate_mask=plans.inference_candidate_mask,
        positive_mask=~plans.positive_mask,
    )
    first, _ = select_diverse_plan_shortlist(
        base_logits,
        plans,
        batch,
        include_training_positives=False,
        overall_count=1,
        per_cardinality_count=1,
        per_role_count=1,
        max_candidates=3,
    )
    second, _ = select_diverse_plan_shortlist(
        base_logits,
        changed_truth,
        batch,
        include_training_positives=False,
        overall_count=1,
        per_cardinality_count=1,
        per_role_count=1,
        max_candidates=3,
    )
    assert torch.equal(first.candidate_sets, second.candidate_sets)
