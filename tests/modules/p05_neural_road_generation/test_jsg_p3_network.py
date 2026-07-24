import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_network import (
    ContextSetScorer,
    expected_calibration_error,
    group_probabilities,
    listwise_group_loss,
    parameter_count,
)


def test_context_scorer_listwise_loss_has_gradients() -> None:
    model = ContextSetScorer(
        candidate_vocabulary_size=20,
        context_vocabulary_size=20,
        object_type_count=4,
        embedding_dim=8,
        hidden_dim=16,
        type_embedding_dim=4,
        dropout=0.0,
    )
    scores = model(
        candidate_token_ids=torch.tensor([1, 2, 3, 4, 5, 6]),
        candidate_offsets=torch.tensor([0, 2, 4]),
        context_token_ids=torch.tensor([1, 2, 3, 4]),
        context_offsets=torch.tensor([0, 2]),
        candidate_group_index=torch.tensor([0, 0, 1]),
        group_type_ids=torch.tensor([1, 2]),
    )
    loss = listwise_group_loss(
        scores,
        torch.tensor([0, 0, 1]),
        torch.tensor([False, True, True]),
        torch.ones(2),
    )
    loss.backward()
    assert torch.isfinite(loss)
    assert parameter_count(model) > 0
    assert any(parameter.grad is not None for parameter in model.parameters())


def test_probabilities_and_ece_are_well_formed() -> None:
    probabilities = group_probabilities(
        torch.tensor([2.0, 1.0, 0.0]), torch.tensor([0, 0, 1]), 2
    )
    assert probabilities[:2].sum().item() == 1.0
    assert probabilities[2].item() == 1.0
    ece = expected_calibration_error(
        torch.tensor([0.9, 0.6]), torch.tensor([True, False])
    )
    assert 0.0 <= ece <= 1.0
