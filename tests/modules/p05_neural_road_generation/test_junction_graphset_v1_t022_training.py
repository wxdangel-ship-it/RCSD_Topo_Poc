from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t022_training import (
    _LOSS_STAGE_KEYS,
    _stage_diagnostics,
    deterministic_teacher_masks,
    teacher_forcing_ratio,
)


def test_preregistered_schedule_reaches_full_free_at_epoch_eight() -> None:
    assert [teacher_forcing_ratio(epoch, 8) for epoch in range(1, 9)] == [
        0.875,
        0.75,
        0.625,
        0.5,
        0.375,
        0.25,
        0.125,
        0.0,
    ]
    assert teacher_forcing_ratio(12, 8) == 0.0
    with pytest.raises(ValueError, match="positive"):
        teacher_forcing_ratio(0, 8)


def test_teacher_masks_are_deterministic_independent_and_bounded() -> None:
    first = deterministic_teacher_masks(
        64,
        ratio=0.5,
        seed=20_260_821,
        epoch=3,
        batch_index=7,
        device=torch.device("cpu"),
    )
    second = deterministic_teacher_masks(
        64,
        ratio=0.5,
        seed=20_260_821,
        epoch=3,
        batch_index=7,
        device=torch.device("cpu"),
    )

    assert torch.equal(first[0], second[0])
    assert torch.equal(first[1], second[1])
    assert not torch.equal(first[0], first[1])
    assert deterministic_teacher_masks(
        3,
        ratio=0.0,
        seed=1,
        epoch=1,
        batch_index=0,
        device=torch.device("cpu"),
    )[0].tolist() == [False, False, False]
    assert deterministic_teacher_masks(
        3,
        ratio=1.0,
        seed=1,
        epoch=1,
        batch_index=0,
        device=torch.device("cpu"),
    )[1].tolist() == [True, True, True]


def test_stage_diagnostics_separate_surface_and_step1_propagation() -> None:
    keys = tuple(key for values in _LOSS_STAGE_KEYS.values() for key in values)
    teacher = {key: 1.0 for key in keys}
    surface_free = {key: 2.0 for key in keys}
    full_free = {key: 4.0 for key in keys}

    diagnostics = _stage_diagnostics(teacher, surface_free, full_free)

    assert diagnostics["surface_prediction_gap_with_teacher_step1"]["step1"] == 1.0
    assert diagnostics["additional_step1_propagation_gap"]["step1"] == 2.0
    assert diagnostics["teacher_to_full_free_gap"]["surface"] == 3.0 * len(
        _LOSS_STAGE_KEYS["surface"]
    )
