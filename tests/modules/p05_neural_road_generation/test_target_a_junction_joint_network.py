from __future__ import annotations

from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    MAX_BREAKS_PER_ROAD,
    TASK_CLASSES,
    JunctionJointBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_network import (
    JunctionJointConfig,
    JunctionJointNetwork,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RELATION_DIM,
    GEOMETRY_TOKEN_DIM,
    MEMBER_FEATURE_DIM,
    OBJECT_FEATURE_DIM,
    SURFACE_GRID_SIZE,
)


def test_joint_network_outputs_complete_hierarchy() -> None:
    batch = _batch()
    model = JunctionJointNetwork(JunctionJointConfig(dropout=0.0))
    outputs = model(batch, teacher_forcing_ratio=0.0)
    assert 10_000_000 <= parameter_count(model) <= 20_000_000
    for task, classes in TASK_CLASSES.items():
        assert outputs[f"{task}_logits"].shape == (2, len(classes))
    assert outputs["surface_logits"].shape == (
        2,
        SURFACE_GRID_SIZE,
        SURFACE_GRID_SIZE,
    )
    assert outputs["object_logits"].shape == (2, 4)
    assert outputs["surface_object_logits"].shape == (2, 4)
    assert outputs["surface_object_cardinality_logits"].shape == (2, 4)
    assert outputs["action_object_logits"].shape == (
        2,
        len(TASK_CLASSES["junctionization_action"]),
        4,
    )
    assert outputs["object_role_cardinality_logits"].shape == (2, 2, 16)
    assert outputs["candidate_logits"].shape == (2, 3)
    assert outputs["member_logits"].shape == (2, 3)
    assert outputs["object_main_logits"].shape == (2, 4)
    assert outputs["break_presence_logits"].shape == (2, 4, MAX_BREAKS_PER_ROAD)
    assert outputs["break_fractions"].shape == (2, 4, MAX_BREAKS_PER_ROAD)
    assert torch.allclose(outputs["break_fractions"], torch.full((2, 4, 2), 0.4))


def test_teacher_forcing_does_not_backpropagate_through_stage_conditions() -> None:
    batch = _batch()
    model = JunctionJointNetwork(JunctionJointConfig(dropout=0.0))
    outputs = model(
        batch,
        teacher_labels=batch.task_labels,
        teacher_masks=batch.task_masks,
        teacher_forcing_ratio=0.5,
    )
    outputs["final_state_logits"].sum().backward()
    step1_grad = sum(
        float(parameter.grad.abs().sum())
        for parameter in model.step1_head.parameters()
        if parameter.grad is not None
    )
    assert step1_grad == 0.0


def test_surface_refinement_starts_as_identity_residual() -> None:
    model = JunctionJointNetwork(JunctionJointConfig(dropout=0.0))
    assert torch.count_nonzero(model.surface_refinement[-1].weight) == 0
    assert torch.count_nonzero(model.surface_refinement[-1].bias) == 0


def test_structured_surface_decoder_outputs_explicit_boundary_recipe() -> None:
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
    outputs = JunctionJointNetwork(config)(_batch(), teacher_forcing_ratio=0.0)
    assert outputs["surface_logits"].shape == (2, 128, 128)
    assert outputs["surface_row_left_logits"].shape == (2, 128, 128)
    assert outputs["surface_row_presence_logits"].shape == (2, 128)
    assert outputs["surface_column_top_logits"].shape == (2, 128, 128)
    assert outputs["surface_column_presence_logits"].shape == (2, 128)
    assert torch.isfinite(outputs["surface_logits"]).all()


def test_high_resolution_role_evidence_refinement_starts_as_identity() -> None:
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        high_resolution_surface_evidence=True,
    )
    model = JunctionJointNetwork(config)
    outputs = model(_batch(), teacher_forcing_ratio=0.0)
    assert model.surface_high_resolution_refinement is not None
    assert torch.count_nonzero(
        model.surface_high_resolution_refinement[-1].weight
    ) == 0
    assert torch.allclose(outputs["surface_logits"], outputs["surface_pixel_logits"])


def test_business_plan_head_conditions_complete_object_decoder() -> None:
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        business_plan_count=3,
    )
    model = JunctionJointNetwork(config)
    outputs = model(_batch(), teacher_forcing_ratio=0.0)
    assert outputs["business_plan_logits"].shape == (2, 3)
    assert model.business_plan_condition is not None


def test_member_graph_changes_member_and_mapped_object_decoding() -> None:
    torch.manual_seed(7)
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        member_graph_layers=2,
    )
    model = JunctionJointNetwork(config).eval()
    batch = _batch()
    with_graph = model(batch, teacher_forcing_ratio=0.0)
    without_edges = model(
        replace(
            batch,
            member_relation_mask=torch.zeros_like(batch.member_relation_mask),
            member_incidence_mask=torch.zeros_like(batch.member_incidence_mask),
        ),
        teacher_forcing_ratio=0.0,
    )
    assert not torch.allclose(with_graph["member_logits"], without_edges["member_logits"])
    assert not torch.allclose(with_graph["object_logits"], without_edges["object_logits"])


def test_geometry_graph_changes_complete_object_decoding() -> None:
    torch.manual_seed(11)
    config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
        geometry_graph_layers=2,
    )
    model = JunctionJointNetwork(config).eval()
    batch = _batch()
    with_graph = model(batch, teacher_forcing_ratio=0.0)
    without_edges = model(
        replace(
            batch,
            geometry_relation_mask=torch.zeros_like(batch.geometry_relation_mask),
        ),
        teacher_forcing_ratio=0.0,
    )
    assert not torch.allclose(with_graph["object_logits"], without_edges["object_logits"])


def test_weak_evidence_branch_starts_as_identity_for_strong_plan() -> None:
    torch.manual_seed(17)
    base_config = JunctionJointConfig(
        hidden_dim=64,
        num_heads=4,
        feedforward_dim=128,
        object_layers=1,
        min_parameter_count=0,
        max_parameter_count=100_000_000,
        dropout=0.0,
    )
    base = JunctionJointNetwork(base_config).eval()
    evidence = JunctionJointNetwork(
        replace(
            base_config,
            weak_evidence_branch=True,
            weak_evidence_hidden_dim=96,
            weak_evidence_num_heads=4,
        )
    ).eval()
    compatibility = evidence.load_state_dict(base.state_dict(), strict=False)
    assert not compatibility.unexpected_keys
    assert all(
        key.startswith(("weak_evidence_encoder.", "weak_evidence_fusion."))
        for key in compatibility.missing_keys
    )
    batch = _batch()
    base_outputs = base(batch, teacher_forcing_ratio=0.0)
    evidence_outputs = evidence(batch, teacher_forcing_ratio=0.0)
    assert "weak_evidence_logits" in evidence_outputs
    for key in (
        "object_logits",
        "object_main_logits",
        "object_cardinality_logits",
        "break_presence_logits",
        "surface_object_logits",
        "junctionization_action_logits",
    ):
        assert torch.allclose(base_outputs[key], evidence_outputs[key])


def test_strong_plan_gradient_cannot_update_weak_evidence_encoder() -> None:
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
    outputs = model(_batch(), teacher_forcing_ratio=0.0)
    outputs["object_logits"].sum().backward()
    assert model.weak_evidence_encoder is not None
    assert model.weak_evidence_fusion is not None
    assert all(
        parameter.grad is None or not bool(parameter.grad.count_nonzero())
        for parameter in model.weak_evidence_encoder.parameters()
    )
    assert any(
        parameter.grad is not None and bool(parameter.grad.count_nonzero())
        for parameter in model.weak_evidence_fusion.parameters()
    )

    model.zero_grad(set_to_none=True)
    outputs = model(_batch(), teacher_forcing_ratio=0.0)
    outputs["weak_evidence_logits"].sum().backward()
    assert any(
        parameter.grad is not None and bool(parameter.grad.count_nonzero())
        for parameter in model.weak_evidence_encoder.parameters()
    )
    assert all(
        parameter.grad is None or not bool(parameter.grad.count_nonzero())
        for parameter in model.weak_evidence_fusion.parameters()
    )


def _batch() -> JunctionJointBatch:
    batch = 2
    tokens = 7
    objects = 4
    candidates = 3
    members = 3
    geometry_tokens = torch.randn(batch, tokens, GEOMETRY_TOKEN_DIM)
    token_object_index = torch.tensor(
        [[0, 0, 1, 2, 2, 3, 3], [0, 1, 1, 2, 3, 3, 3]],
        dtype=torch.long,
    )
    task_labels = {
        task: torch.zeros(batch, dtype=torch.long) for task in TASK_CLASSES
    }
    task_masks = {
        task: torch.ones(batch, dtype=torch.bool) for task in TASK_CLASSES
    }
    return JunctionJointBatch(
        sample_ids=("a", "b"),
        splits=("train", "validation"),
        supervision_sources=("STRONG_GOLD", "T10_WEAK"),
        supervision_groups=("GOLD:a", "T10:b"),
        sample_weights=torch.ones(batch),
        object_features=torch.randn(batch, OBJECT_FEATURE_DIM),
        candidate_features=torch.randn(batch, candidates, OBJECT_FEATURE_DIM),
        candidate_mask=torch.ones(batch, candidates, dtype=torch.bool),
        candidate_acceptable=torch.zeros(batch, 1, candidates, dtype=torch.bool),
        candidate_task_mask=torch.ones(batch, dtype=torch.bool),
        member_features=torch.randn(batch, members, MEMBER_FEATURE_DIM),
        member_mask=torch.ones(batch, members, dtype=torch.bool),
        swsd_arm_features=torch.randn(batch, 2, 7),
        swsd_arm_mask=torch.ones(batch, 2, dtype=torch.bool),
        member_arm_features=torch.randn(batch, members, 2, 7),
        member_arm_mask=torch.ones(batch, members, 2, dtype=torch.bool),
        member_relation_features=torch.randn(batch, members, members, 7),
        member_relation_mask=torch.tensor(
            [
                [[False, True, False], [True, False, True], [False, True, False]],
                [[False, True, True], [True, False, False], [True, False, False]],
            ]
        ),
        member_incidence_features=torch.randn(batch, members, members, 4),
        member_incidence_mask=torch.tensor(
            [
                [[False, True, False], [True, False, False], [False, False, False]],
                [[False, False, True], [False, False, False], [True, False, False]],
            ]
        ),
        member_acceptable_sets=torch.zeros(batch, 1, members, dtype=torch.bool),
        member_acceptable_set_mask=torch.ones(batch, 1, dtype=torch.bool),
        member_task_mask=torch.ones(batch, dtype=torch.bool),
        geometry_tokens=geometry_tokens,
        geometry_token_mask=torch.ones(batch, tokens, dtype=torch.bool),
        geometry_token_object_index=token_object_index,
        geometry_object_mask=torch.ones(batch, objects, dtype=torch.bool),
        geometry_object_roles=torch.tensor([[0, 2, 3, 4], [0, 2, 3, 4]]),
        geometry_object_member_index=torch.tensor(
            [[-1, -1, 0, 1], [-1, -1, 1, 2]],
            dtype=torch.long,
        ),
        geometry_object_anchor_projection_fraction=torch.full((batch, objects), 0.4),
        geometry_object_length_m=torch.full((batch, objects), 50.0),
        geometry_relation_index=torch.tensor(
            [
                [[2, 3], [3, 2], [0, 0]],
                [[2, 3], [3, 2], [0, 0]],
            ],
            dtype=torch.long,
        ),
        geometry_relation_features=torch.randn(
            batch,
            3,
            GEOMETRY_RELATION_DIM,
        ),
        geometry_relation_mask=torch.tensor(
            [[True, True, False], [True, True, False]],
            dtype=torch.bool,
        ),
        selectable_object_mask=torch.tensor(
            [[False, False, True, True], [False, False, True, True]]
        ),
        object_supervision_mask=torch.tensor(
            [[False, False, True, True], [False, False, True, True]]
        ),
        object_role_task_mask=torch.ones(batch, 2, dtype=torch.bool),
        object_acceptable_sets=torch.zeros(batch, 1, objects, dtype=torch.bool),
        object_acceptable_set_mask=torch.ones(batch, 1, dtype=torch.bool),
        object_task_mask=torch.ones(batch, dtype=torch.bool),
        surface_object_acceptable_sets=torch.zeros(
            batch, 1, objects, dtype=torch.bool
        ),
        surface_object_acceptable_set_mask=torch.zeros(
            batch, 1, dtype=torch.bool
        ),
        surface_object_task_mask=torch.zeros(batch, dtype=torch.bool),
        virtual_surface_carrier_acceptable_sets=torch.zeros(
            batch, 1, objects, dtype=torch.bool
        ),
        virtual_surface_carrier_acceptable_set_mask=torch.zeros(
            batch, 1, dtype=torch.bool
        ),
        virtual_surface_carrier_task_mask=torch.zeros(batch, dtype=torch.bool),
        step1_tokens=torch.randn(batch, 3, GEOMETRY_TOKEN_DIM),
        step1_token_mask=torch.ones(batch, 3, dtype=torch.bool),
        step2_tokens=torch.randn(batch, 2, GEOMETRY_TOKEN_DIM),
        step2_token_mask=torch.ones(batch, 2, dtype=torch.bool),
        drivezone_grid=torch.zeros(batch, 1, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE),
        surface_targets=torch.zeros(batch, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE),
        surface_task_mask=torch.ones(batch, dtype=torch.bool),
        break_fraction_targets=torch.zeros(batch, objects, MAX_BREAKS_PER_ROAD),
        break_road_length_m=torch.ones(batch, objects),
        break_target_mask=torch.zeros(
            batch,
            objects,
            MAX_BREAKS_PER_ROAD,
            dtype=torch.bool,
        ),
        break_main_mask=torch.zeros(
            batch,
            objects,
            MAX_BREAKS_PER_ROAD,
            dtype=torch.bool,
        ),
        main_object_target=torch.zeros(batch, objects, dtype=torch.bool),
        main_object_task_mask=torch.zeros(batch, dtype=torch.bool),
        break_main_task_mask=torch.zeros(batch, dtype=torch.bool),
        complete_junction_task_mask=torch.ones(batch, dtype=torch.bool),
        topology_geometry_task_mask=torch.ones(batch, dtype=torch.bool),
        task_labels=task_labels,
        task_masks=task_masks,
    )
