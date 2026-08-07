from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_network import (
    JunctionJointConfig,
    JunctionJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    TASK_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_training import (
    _decode_object_sets,
    compute_junction_joint_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_ROLE_INDEX,
)
from tests.modules.p05_neural_road_generation.test_target_a_junction_joint_network import (
    _batch,
)


def test_structured_member_decoder_outputs_complete_set_and_teacher_loss() -> None:
    batch = _batch()
    batch.member_acceptable_sets[0, 0, 0] = True
    batch.member_acceptable_sets[1, 0, 1:] = True
    batch.object_acceptable_sets[0, 0, 2] = True
    batch.object_acceptable_sets[1, 0, 2:] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_member_decoder=True,
        structured_member_max_steps=4,
    )
    model = JunctionJointNetwork(config)
    outputs = model(
        batch,
        teacher_forcing_ratio=0.0,
        teacher_member_sets=batch.member_acceptable_sets,
        teacher_member_set_mask=batch.member_acceptable_set_mask,
        teacher_member_task_mask=batch.member_task_mask,
    )
    assert outputs["structured_member_prediction"].shape == batch.member_mask.shape
    assert outputs["structured_member_stopped"].shape == (2,)
    assert outputs["structured_member_loss_by_row"].shape == (2,)
    assert torch.isfinite(outputs["structured_member_loss_by_row"]).all()
    decoded = _decode_object_sets(outputs, batch)
    assert decoded.shape == batch.selectable_object_mask.shape
    assert not bool((decoded & ~batch.selectable_object_mask).any())
    loss, metrics = compute_junction_joint_loss(outputs, batch)
    assert metrics["structured_member_loss"] > 0.0
    loss.backward()
    assert model.structured_member_decoder is not None
    assert any(
        parameter.grad is not None
        for parameter in model.structured_member_decoder.parameters()
    )


def test_structured_member_teacher_requires_complete_tensor_group() -> None:
    batch = _batch()
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_member_decoder=True,
    )
    model = JunctionJointNetwork(config)
    try:
        model(
            batch,
            teacher_member_sets=batch.member_acceptable_sets,
        )
    except ValueError as error:
        assert "teacher tensors are incomplete" in str(error)
    else:
        raise AssertionError("partial structured teacher tensors must fail")


def test_structured_relation_decoder_enforces_action_kind_and_empty_failure() -> None:
    batch = _batch()
    batch.task_labels["junctionization_action"][:] = torch.tensor(
        [
            TASK_INDEX["junctionization_action"]["direct_relation"],
            TASK_INDEX["junctionization_action"]["failure_relation"],
        ]
    )
    batch.object_acceptable_sets[0, 0, 2] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_relation_decoder=True,
        structured_relation_max_steps=12,
    )
    model = JunctionJointNetwork(config)
    outputs = model(
        batch,
        teacher_labels=batch.task_labels,
        teacher_masks=batch.task_masks,
        teacher_forcing_ratio=1.0,
        teacher_relation_sets=batch.object_acceptable_sets,
        teacher_relation_set_mask=batch.object_acceptable_set_mask,
        teacher_relation_task_mask=batch.object_task_mask,
    )
    prediction = outputs["structured_relation_prediction"]
    assert prediction.shape == batch.selectable_object_mask.shape
    assert int(prediction[0].sum()) == 1
    assert bool(prediction[0, 2])
    assert int(prediction[1].sum()) == 0
    assert bool(outputs["structured_relation_feasible"].all())
    assert torch.isfinite(outputs["structured_relation_loss_by_row"]).all()
    loss, metrics = compute_junction_joint_loss(outputs, batch)
    assert metrics["structured_relation_loss"] > 0.0
    loss.backward()
    assert model.structured_relation_decoder is not None
    assert any(
        parameter.grad is not None
        for parameter in model.structured_relation_decoder.parameters()
    )


def test_structured_relation_decoder_learns_from_selected_object_graph() -> None:
    batch = _batch()
    batch.task_labels["junctionization_action"][:] = TASK_INDEX[
        "junctionization_action"
    ]["split_rcsdroad_generate_rcsdnode"]
    batch.geometry_object_roles[:, 2:] = GEOMETRY_ROLE_INDEX["RCSD_ROAD"]
    batch.object_acceptable_sets[:, 0, 2:] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_relation_decoder=True,
        structured_relation_graph_conditioning=True,
    )
    model = JunctionJointNetwork(config)
    outputs = model(
        batch,
        teacher_labels=batch.task_labels,
        teacher_masks=batch.task_masks,
        teacher_forcing_ratio=1.0,
        teacher_relation_sets=batch.object_acceptable_sets,
        teacher_relation_set_mask=batch.object_acceptable_set_mask,
        teacher_relation_task_mask=batch.object_task_mask,
    )
    loss, metrics = compute_junction_joint_loss(outputs, batch)
    assert metrics["structured_relation_loss"] > 0.0
    loss.backward()
    assert model.structured_relation_decoder is not None
    assert model.structured_relation_decoder.relation_stem is not None
    relation_gradient = sum(
        float(parameter.grad.abs().sum())
        for parameter in model.structured_relation_decoder.relation_stem.parameters()
        if parameter.grad is not None
    )
    assert relation_gradient > 0.0


def test_relation_graph_conditioning_requires_relation_decoder() -> None:
    try:
        JunctionJointConfig(
            structured_relation_graph_conditioning=True,
        ).validate()
    except ValueError as error:
        assert "requires its decoder" in str(error)
    else:
        raise AssertionError("relation graph conditioning without decoder must fail")


def test_structured_decoder_keeps_zero_supervision_batch_trainable() -> None:
    batch = _batch()
    batch.member_task_mask[:] = False
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_member_decoder=True,
    )
    model = JunctionJointNetwork(config)
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(name.startswith("structured_member_decoder."))
    outputs = model(
        batch,
        teacher_member_sets=batch.member_acceptable_sets,
        teacher_member_set_mask=batch.member_acceptable_set_mask,
        teacher_member_task_mask=batch.member_task_mask,
    )
    loss, metrics = compute_junction_joint_loss(outputs, batch)
    assert metrics["structured_member_loss"] == 0.0
    loss.backward()
    assert model.structured_member_decoder is not None
    assert any(
        parameter.grad is not None
        for parameter in model.structured_member_decoder.parameters()
    )


def test_one_way_object_loss_cannot_rewrite_business_plan_parameters() -> None:
    batch = _batch()
    batch.member_acceptable_sets[0, 0, 0] = True
    batch.member_acceptable_sets[1, 0, 1:] = True
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
    model = JunctionJointNetwork(config)
    outputs = model(
        batch,
        teacher_member_sets=batch.member_acceptable_sets,
        teacher_member_set_mask=batch.member_acceptable_set_mask,
        teacher_member_task_mask=batch.member_task_mask,
    )
    assert outputs["structured_member_prediction"].shape == batch.member_mask.shape
    object_loss = (
        outputs["structured_member_loss_by_row"].mean()
        + 0.01 * outputs["object_logits"].square().mean()
        + 0.01 * outputs["break_presence_logits"].square().mean()
    )
    object_loss.backward()
    assert model.one_way_object_decoder is not None
    assert any(
        parameter.grad is not None
        for parameter in model.one_way_object_decoder.parameters()
    )
    assert model.business_plan_head is not None
    assert all(
        parameter.grad is None for parameter in model.business_plan_head.parameters()
    )


def test_one_way_and_shared_structured_decoders_are_mutually_exclusive() -> None:
    try:
        JunctionJointConfig(
            business_plan_count=3,
            structured_member_decoder=True,
            one_way_object_branch=True,
        ).validate()
    except ValueError as error:
        assert "mutually exclusive" in str(error)
    else:
        raise AssertionError("two structured object decoders must not coexist")

    try:
        JunctionJointConfig(
            structured_member_decoder=True,
            structured_relation_decoder=True,
        ).validate()
    except ValueError as error:
        assert "mutually exclusive" in str(error)
    else:
        raise AssertionError("member and relation decoders must not coexist")
