from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_members import (
    anchor_candidate_member_tensors,
    anchor_member_set_confidence,
)


def _feature(value: float, *, road: bool = False) -> tuple[float, ...]:
    row = [value] * 64
    row[27] = float(road)
    return tuple(row)


def test_anchor_members_preserve_typed_candidate_composition() -> None:
    result = anchor_candidate_member_tensors(
        (
            "NODE:n1",
            "NODE:n2",
            "NODE:n1|n2",
            "ROAD:r1",
            "ROAD:r1|r2",
        ),
        (
            _feature(1.0),
            _feature(2.0),
            _feature(3.0),
            _feature(4.0, road=True),
            _feature(5.0, road=True),
        ),
    )

    assert result.member_features.shape == (4, 64)
    assert result.member_is_road.tolist() == [False, False, True, True]
    assert result.candidate_membership.tolist() == [
        [True, False, False, False],
        [False, True, False, False],
        [True, True, False, False],
        [False, False, True, False],
        [False, False, True, True],
    ]
    assert result.member_features[:, 0].tolist() == [1.0, 2.0, 4.0, 5.0]


def test_anchor_members_do_not_merge_equal_raw_ids_across_types() -> None:
    result = anchor_candidate_member_tensors(
        ("NODE:shared", "ROAD:shared"),
        (_feature(1.0), _feature(2.0, road=True)),
    )

    assert result.member_is_road.tolist() == [False, True]
    assert torch.equal(
        result.candidate_membership,
        torch.eye(2, dtype=torch.bool),
    )


def test_anchor_member_set_confidence_scores_exact_typed_set() -> None:
    logits = torch.logit(torch.tensor([0.9, 0.1, 0.8]))
    confidence = anchor_member_set_confidence(
        logits,
        torch.tensor([True, True, True]),
        torch.tensor([False, False, True]),
        torch.tensor(
            [
                [True, False, False],
                [True, True, False],
                [False, False, True],
            ]
        ),
        torch.tensor(0),
    )
    assert confidence.min_included_probability.item() == pytest.approx(0.9)
    assert confidence.max_excluded_probability.item() == pytest.approx(0.1)
    assert confidence.inclusion_margin.item() == pytest.approx(0.8)
    assert confidence.selected_member_count.item() == 1
    assert confidence.expected_member_count.item() == pytest.approx(1.0)
    assert confidence.cardinality_residual.item() == pytest.approx(0.0)


def test_anchor_member_set_confidence_rejects_cross_type_candidate() -> None:
    with pytest.raises(ValueError, match="mixes Node and Road"):
        anchor_member_set_confidence(
            torch.zeros(2),
            torch.tensor([True, True]),
            torch.tensor([False, True]),
            torch.tensor([[True, True]]),
            torch.tensor(0),
        )
