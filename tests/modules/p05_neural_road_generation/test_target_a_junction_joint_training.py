from __future__ import annotations

from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_business_plan import (
    WILDCARD,
    BusinessPlanTemplate,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_network import (
    JunctionJointConfig,
    JunctionJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_training import (
    _acceptable_positive_loss,
    _exact_relation_task_mask,
    _training_batches,
    audit_joint_supervision_cohort,
    build_cost_batches,
    compute_junction_joint_loss,
    teacher_forcing_ratio,
)
from tests.modules.p05_neural_road_generation.test_target_a_junction_joint_data import (
    _write_store,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    read_junction_joint_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_ROLE_INDEX,
)
from tests.modules.p05_neural_road_generation.test_target_a_junction_joint_network import (
    _batch,
)


def test_joint_loss_is_finite_and_backpropagates() -> None:
    batch = _batch()
    batch.object_acceptable_sets[:, 0, 2] = True
    batch.object_acceptable_sets[:, 0, 3] = True
    batch.member_acceptable_sets[:, 0, 0] = True
    batch.candidate_acceptable[:, 0, 0] = True
    batch.break_target_mask[:, 3, 0] = True
    batch.break_fraction_targets[:, 3, 0] = 0.5
    batch.break_road_length_m[:, 3] = 50.0
    batch.main_object_target[:, 2] = True
    batch.main_object_task_mask[:] = True
    batch.geometry_object_roles[:, 1] = GEOMETRY_ROLE_INDEX["RCSD_INTERSECTION"]
    batch.surface_object_acceptable_sets[:, 0, 1] = True
    batch.surface_object_acceptable_set_mask[:, 0] = True
    batch.surface_object_task_mask[:] = True
    batch.geometry_tokens[:, :, 7:9] = 0.0
    batch.virtual_surface_carrier_acceptable_sets[:, 0, 0] = True
    batch.virtual_surface_carrier_acceptable_sets[:, 0, 2] = True
    batch.virtual_surface_carrier_acceptable_set_mask[:, 0] = True
    batch.virtual_surface_carrier_task_mask[:] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
    )
    model = JunctionJointNetwork(config)
    outputs = model(batch, teacher_forcing_ratio=0.0)
    loss, metrics = compute_junction_joint_loss(outputs, batch)
    assert torch.isfinite(loss)
    assert metrics["total_loss"] > 0.0
    assert metrics["surface_object_loss"] > 0.0
    assert metrics["surface_object_cardinality_loss"] > 0.0
    assert metrics["virtual_surface_carrier_loss"] > 0.0
    assert metrics["virtual_surface_carrier_cardinality_loss"] > 0.0
    loss.backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
    assert any(
        parameter.grad is not None
        for parameter in model.surface_object_score.parameters()
    )
    assert any(
        parameter.grad is not None
        for parameter in model.virtual_surface_carrier_score.parameters()
    )


def test_teacher_forcing_schedule_reaches_zero() -> None:
    assert teacher_forcing_ratio(1, 5) == 0.9
    assert teacher_forcing_ratio(5, 5) == 0.0


def test_t10_partial_object_truth_does_not_create_false_negatives() -> None:
    logits = torch.tensor([[0.0, -20.0, 20.0]], requires_grad=True)
    acceptable = torch.tensor([[[True, False, False]]])
    loss = _acceptable_positive_loss(
        logits,
        valid_mask=torch.ones_like(logits, dtype=torch.bool),
        acceptable_sets=acceptable,
        acceptable_set_mask=torch.ones(1, 1, dtype=torch.bool),
        task_mask=torch.ones(1, dtype=torch.bool),
        sample_weights=torch.ones(1),
    )
    loss.backward()
    assert logits.grad is not None
    assert logits.grad[0, 0] < 0.0
    assert logits.grad[0, 1] == 0.0
    assert logits.grad[0, 2] == 0.0


def test_structured_relation_teacher_mask_excludes_t10_partial_truth() -> None:
    batch = _batch()
    batch.complete_junction_task_mask[:] = torch.tensor([True, False])
    assert _exact_relation_task_mask(batch).tolist() == [True, False]


def test_structured_relation_teacher_mask_includes_t10_complete_truth() -> None:
    batch = _batch()
    batch.complete_junction_task_mask[:] = True
    assert _exact_relation_task_mask(batch).tolist() == [True, True]


def test_t10_partial_loss_is_routed_to_independent_weak_evidence_branch() -> None:
    batch = _batch()
    batch.complete_junction_task_mask[:] = torch.tensor([True, False])
    batch.object_acceptable_sets[0, 0, 2] = True
    batch.object_acceptable_sets[1, 0, 3] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        weak_evidence_branch=True,
        weak_evidence_hidden_dim=96,
        weak_evidence_num_heads=4,
    )
    model = JunctionJointNetwork(config)
    loss, metrics = compute_junction_joint_loss(
        model(batch, teacher_forcing_ratio=0.0),
        batch,
    )
    assert metrics["weak_object_positive_loss"] > 0.0
    loss.backward()
    assert model.weak_evidence_encoder is not None
    assert any(
        parameter.grad is not None and bool(parameter.grad.count_nonzero())
        for parameter in model.weak_evidence_encoder.parameters()
    )


def test_structured_virtual_surface_carrier_loss_backpropagates() -> None:
    batch = _batch()
    batch.geometry_tokens[:, :, 7:9] = 0.0
    batch.virtual_surface_carrier_acceptable_sets[:, 0, 1] = True
    batch.virtual_surface_carrier_acceptable_sets[:, 0, 3] = True
    batch.virtual_surface_carrier_acceptable_set_mask[:, 0] = True
    batch.virtual_surface_carrier_task_mask[:] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_virtual_surface_carrier_decoder=True,
    )
    model = JunctionJointNetwork(config)
    outputs = model(
        batch,
        teacher_forcing_ratio=0.0,
        teacher_virtual_surface_carrier_sets=(
            batch.virtual_surface_carrier_acceptable_sets
        ),
        teacher_virtual_surface_carrier_set_mask=(
            batch.virtual_surface_carrier_acceptable_set_mask
        ),
        teacher_virtual_surface_carrier_task_mask=(
            batch.virtual_surface_carrier_task_mask
        ),
    )
    loss, metrics = compute_junction_joint_loss(outputs, batch)
    assert metrics["structured_virtual_surface_carrier_loss"] > 0.0
    loss.backward()
    assert model.structured_virtual_surface_carrier_decoder is not None
    assert any(
        parameter.grad is not None
        for parameter in model.structured_virtual_surface_carrier_decoder.parameters()
    )


def test_virtual_surface_geometric_coverage_loss_backpropagates() -> None:
    batch = _batch()
    batch.geometry_tokens[:, :, 7:9] = 0.0
    batch.surface_targets[:, 60:68, 60:68] = 1.0
    batch.virtual_surface_carrier_acceptable_sets[:, 0, 1] = True
    batch.virtual_surface_carrier_acceptable_sets[:, 0, 3] = True
    batch.virtual_surface_carrier_acceptable_set_mask[:, 0] = True
    batch.virtual_surface_carrier_task_mask[:] = True
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        virtual_surface_geometric_coverage_training=True,
    )
    model = JunctionJointNetwork(config)
    loss, metrics = compute_junction_joint_loss(
        model(batch, teacher_forcing_ratio=0.0),
        batch,
    )
    assert metrics["virtual_surface_geometric_coverage_loss"] > 0.0
    loss.backward()
    assert any(
        parameter.grad is not None
        for parameter in model.virtual_surface_carrier_score.parameters()
    )


def test_structured_surface_boundary_loss_backpropagates() -> None:
    batch = _batch()
    batch.surface_targets[:, 58:67, 54:72] = 1.0
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        structured_surface_decoder=True,
    )
    model = JunctionJointNetwork(config)
    loss, metrics = compute_junction_joint_loss(
        model(batch, teacher_forcing_ratio=0.0),
        batch,
    )
    assert metrics["surface_boundary_loss"] > 0.0
    loss.backward()
    assert model.surface_boundary_decoder is not None
    assert any(
        parameter.grad is not None
        for parameter in model.surface_boundary_decoder.parameters()
    )


def test_business_plan_loss_uses_masked_wildcard_template() -> None:
    batch = _batch()
    batch.task_masks["junctionization_action"][1] = False
    catalog = (
        BusinessPlanTemplate(tuple(0 for _ in batch.task_labels)),
        BusinessPlanTemplate(
            tuple(
                WILDCARD if task == "junctionization_action" else 0
                for task in batch.task_labels
            )
        ),
    )
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        business_plan_count=len(catalog),
    )
    model = JunctionJointNetwork(config)
    loss, metrics = compute_junction_joint_loss(
        model(batch, teacher_forcing_ratio=0.0),
        batch,
        business_plan_catalog=catalog,
    )
    assert metrics["business_plan_loss"] > 0.0
    loss.backward()
    assert model.business_plan_head is not None
    assert any(
        parameter.grad is not None for parameter in model.business_plan_head.parameters()
    )


def test_cost_batches_respect_example_budget() -> None:
    assert build_cost_batches(
        (),
        max_examples=2,
        max_tokens=10,
        max_objects=10,
        seed=1,
        shuffle=True,
    ) == ()


def test_source_balanced_batches_crop_weak_volume_without_changing_rows(
    tmp_path,
) -> None:
    row = read_junction_joint_examples(_write_store(tmp_path))[0]
    strong = tuple(replace(row, sample_id=f"strong-{index}") for index in range(2))
    weak = tuple(
        replace(
            row,
            sample_id=f"weak-{index}",
            supervision_source="T10_WEAK",
            sample_weight=0.7,
        )
        for index in range(5)
    )
    batches = _training_batches(
        strong + weak,
        max_examples=1,
        max_tokens=100_000,
        max_objects=100_000,
        seed=7,
        balance_supervision_sources=True,
    )
    sources = [batch[0].supervision_source for batch in batches]
    assert sources.count("STRONG_GOLD") == 2
    assert sources.count("T10_WEAK") == 2


def test_joint_cohort_audit_enforces_source_weights_and_split_isolation(
    tmp_path,
) -> None:
    strong = read_junction_joint_examples(_write_store(tmp_path))[0]
    weak = replace(
        strong,
        sample_id="weak",
        supervision_source="T10_WEAK",
        supervision_group="POC_Data:T10:case-a",
        sample_weight=0.7,
        split="validation",
    )
    audit = audit_joint_supervision_cohort((strong, weak))
    assert audit["status"] == "JOINT_SUPERVISION_COHORT_GO"
    assert audit["source_split_counts"] == {
        "STRONG_GOLD": {"train": 1},
        "T10_WEAK": {"validation": 1},
    }
    try:
        audit_joint_supervision_cohort((replace(weak, sample_weight=1.0),))
    except ValueError as error:
        assert "must be 0.7" in str(error)
    else:
        raise AssertionError("T10 weak weight drift must fail")


def test_joint_cohort_audit_rejects_strong_group_cross_split(tmp_path) -> None:
    row = read_junction_joint_examples(_write_store(tmp_path))[0]
    duplicate = replace(row, sample_id="duplicate", split="validation")
    try:
        audit_joint_supervision_cohort((row, duplicate))
    except ValueError as error:
        assert "crosses frozen splits" in str(error)
    else:
        raise AssertionError("strong Gold split leakage must fail")
