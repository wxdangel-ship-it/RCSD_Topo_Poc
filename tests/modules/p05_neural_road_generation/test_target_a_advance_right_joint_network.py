from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_joint_network import (
    TargetAAdvanceRightJointAccessDecoder,
)


def _inputs() -> dict[str, torch.Tensor]:
    return {
        "candidate_values": torch.randn(2, 4, 50),
        "candidate_mask": torch.tensor(
            [[True, True, False, False], [True, True, True, True]]
        ),
        "source_object_values": torch.randn(2, 64),
        "source_road_values": torch.randn(2, 5, 40),
        "source_road_mask": torch.tensor(
            [[True, True, False, False, False], [True] * 5]
        ),
        "source_access_values": torch.randn(2, 3, 64),
        "source_access_mask": torch.tensor(
            [[True, True, False], [True, True, True]]
        ),
        "target_object_values": torch.randn(2, 64),
        "target_road_values": torch.randn(2, 4, 40),
        "target_road_mask": torch.tensor(
            [[True, False, False, False], [True] * 4]
        ),
        "target_access_values": torch.randn(2, 2, 64),
        "target_access_mask": torch.tensor(
            [[True, False], [True, True]]
        ),
    }


def test_joint_access_decoder_shapes_and_masks() -> None:
    model = TargetAAdvanceRightJointAccessDecoder(dropout=0.0)
    outputs = model(**_inputs())
    assert outputs["candidate_logits"].shape == (2, 4)
    assert outputs["plan_type_logits"].shape == (2, 5)
    assert outputs["cardinality_logits"].shape == (2, 10)
    assert outputs["source_side_source_logits"].shape == (2, 3)
    assert outputs["source_side_road_logits"].shape == (2, 5)
    assert outputs["source_side_road_cardinality_logits"].shape == (2, 65)
    assert torch.isneginf(outputs["candidate_logits"][0, 2:]).all()
    assert torch.isneginf(outputs["source_side_access_logits"][0, 2])
    assert outputs["source_side_road_logits"][0, 2:].eq(0).all()


def test_teacher_lock_does_not_change_side_predictions() -> None:
    torch.manual_seed(3)
    model = TargetAAdvanceRightJointAccessDecoder(dropout=0.0)
    inputs = _inputs()
    raw = model(**inputs)
    teacher = model(
        **inputs,
        teacher_source_source=torch.tensor([0, 1]),
        teacher_source_road_mask=torch.tensor(
            [
                [True, False, False, False, False],
                [False, True, True, False, False],
            ]
        ),
        teacher_source_access_mask=torch.tensor(
            [[True, False, False], [False, True, False]]
        ),
        teacher_target_source=torch.tensor([1, 0]),
        teacher_target_road_mask=torch.tensor(
            [[True, False, False, False], [False, True, False, False]]
        ),
        teacher_target_access_mask=torch.tensor(
            [[True, False], [False, True]]
        ),
    )
    assert torch.equal(
        raw["source_side_source_logits"],
        teacher["source_side_source_logits"],
    )
    assert torch.equal(
        raw["source_side_road_logits"],
        teacher["source_side_road_logits"],
    )
    assert not torch.equal(
        raw["candidate_logits"],
        teacher["candidate_logits"],
    )


def test_ordinary_loader_accepts_role_aware_checkpoint_superset() -> None:
    model = TargetAAdvanceRightJointAccessDecoder(
        road_cardinality_count=67,
        dropout=0.0,
    )
    expected = {
        key: torch.full_like(value, 0.125)
        for key, value in model.ordinary_road_decoder.state_dict().items()
    }
    role_aware = {
        **expected,
        "ownership_head.0.weight": torch.randn(3, 4),
        "business_role_head.0.weight": torch.randn(4, 4),
    }
    model.load_ordinary_road_state_dict(role_aware)
    actual = model.ordinary_road_decoder.state_dict()
    assert set(actual) == set(expected)
    assert all(torch.equal(actual[key], value) for key, value in expected.items())


def test_role_overlay_changes_only_shared_ordinary_encoders() -> None:
    model = TargetAAdvanceRightJointAccessDecoder(dropout=0.0)
    before = {
        key: value.clone()
        for key, value in model.ordinary_road_decoder.state_dict().items()
    }
    role_aware = {
        key: torch.full_like(value, 0.25)
        for key, value in before.items()
    }
    model.load_ordinary_encoder_state_dict(role_aware)
    after = model.ordinary_road_decoder.state_dict()
    for key, value in after.items():
        if key.startswith(("object_encoder.", "candidate_encoder.")):
            assert torch.equal(value, role_aware[key])
        else:
            assert torch.equal(value, before[key])


def test_count_aware_joint_decoder_exposes_side_count_outputs() -> None:
    model = TargetAAdvanceRightJointAccessDecoder(
        road_cardinality_count=67,
        ordinary_decoder_kind="COUNT_AWARE_SET",
        dropout=0.0,
    )
    outputs = model(**_inputs())
    assert outputs[
        "source_side_road_cardinality_ordinal_logits"
    ].shape == (2, 66)
    assert outputs["source_side_soft_member_count"].shape == (2,)
    assert outputs[
        "target_side_road_cardinality_ordinal_logits"
    ].shape == (2, 66)
