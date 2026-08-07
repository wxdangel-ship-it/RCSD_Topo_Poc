from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    SIDE_ACCESS_FEATURE_DIM,
    SIDE_OBJECT_FEATURE_DIM,
    SIDE_ROAD_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureBatch,
    ArchClosureSegmentContextBatch,
    _model_input,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_network import (
    TargetAArchClosureConfig,
    TargetAArchClosureNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_joint_arch_closure_data import (
    LiveJunctionBatch,
    bind_live_junctions,
    build_joint_arch_closure_components,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_SUCCESS,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_ROAD_RELATION_DIM,
    ORDINARY_SET_SOURCE_RCSD,
    ORDINARY_SET_SOURCE_SWSD,
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetConfig,
    TargetAEndToEndOrdinarySetNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    ACCESS_COLLECTION_FEATURE_DIM,
    BREAK_CANDIDATE_FEATURE_DIM,
    OrdinaryJointAccessBatch,
    OrdinaryJointBreakBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_network import (
    TargetAOrdinaryJointMainlineConfig,
    TargetAOrdinaryJointMainlineNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_structured_data import (
    OrdinaryJointStructuredPlanBatch,
)


def test_source_and_complete_plan_have_one_way_gradient_boundary() -> None:
    model = _model()
    batch = _batch()

    outputs = model(
        batch.model_input,
        teacher_gate_decisions=batch.structured.teacher_gate_decisions,
    )
    road_loss = nn.functional.binary_cross_entropy_with_logits(
        outputs["ordinary_side_road_member_logits"][0, 0, :2],
        batch.ordinary.road_member_targets[0, 0, :2].float(),
    )
    road_loss.backward()

    source_names = (
        "source_evidence_encoder",
        "source_context",
        "decision_head",
    )
    assert all(
        parameter.grad is None or not bool(parameter.grad.ne(0).any())
        for name, parameter in model.named_parameters()
        if name.startswith(source_names)
    )
    assert any(
        parameter.grad is not None and bool(parameter.grad.ne(0).any())
        for name, parameter in model.named_parameters()
        if name.startswith(("plan_evidence_encoder", "member_head"))
    )

    model.zero_grad(set_to_none=True)
    source_loss = nn.functional.cross_entropy(
        outputs["ordinary_side_decision_logits"][0, 0].unsqueeze(0),
        torch.tensor([ORDINARY_DECISION_KEEP_SWSD]),
    )
    source_loss.backward()
    assert all(
        parameter.grad is None or not bool(parameter.grad.ne(0).any())
        for name, parameter in model.named_parameters()
        if name.startswith(("road_stem", "road_set_encoder", "member_head"))
    )


def test_joint_context_keeps_live_junction_gradient() -> None:
    model = _model(detach_junction_embeddings=False)
    batch = _batch()
    live_values = batch.context.junction_embedding_values.clone().requires_grad_()
    context = replace(batch.context, junction_embedding_values=live_values)
    model_input = replace(batch.model_input, context=context)

    outputs = model(model_input)
    loss = nn.functional.cross_entropy(
        outputs["ordinary_side_decision_logits"][0, 0].unsqueeze(0),
        torch.tensor([ORDINARY_DECISION_KEEP_SWSD]),
    )
    loss.backward()

    assert live_values.grad is not None
    assert bool(live_values.grad.ne(0).any())


def test_live_junction_binding_replaces_cache_without_changing_shape() -> None:
    batch = _batch()
    segment_key = batch.keys[0]
    junction_key = (segment_key[0], "j1")
    pool = SimpleNamespace(
        road_ids=("r0", "r1"),
        road_start_node_ids=("n0", "x1"),
        road_end_node_ids=("x0", "n1"),
    )
    stores = SimpleNamespace(
        segments={
            segment_key: SimpleNamespace(
                required_junction_keys=(junction_key,)
            )
        },
        plans={segment_key: SimpleNamespace(road_pool=pool)},
    )
    embeddings = torch.arange(8, dtype=torch.float32).reshape(1, 8)
    embeddings.requires_grad_()
    live = LiveJunctionBatch(
        keys=(junction_key,),
        business_states=torch.tensor([ORDINARY_ANCHOR_SUCCESS]),
        candidate_ids=("NODE:n0",),
        embeddings=embeddings,
        confidence_values=torch.tensor([[0.9, 0.05, 0.95, 0.8]]),
        selected_candidate_indices=torch.tensor([0]),
    )

    result = bind_live_junctions(batch, stores, live)

    assert result.context.junction_embedding_values.shape == (1, 1, 8)
    assert torch.equal(result.context.junction_embedding_values[0, 0], embeddings[0])
    assert int(result.ordinary.side_precomputed_anchor_state[0, 0]) == (
        ORDINARY_ANCHOR_SUCCESS
    )
    assert result.ordinary.side_precomputed_anchor_context[0, 0, 0].tolist() == [
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        1.0,
    ]


def test_joint_components_stop_at_direct_segment_junction_dependencies() -> None:
    case = "T10:1"
    segments = {
        (case, "s1"): SimpleNamespace(
            example=SimpleNamespace(fold=1),
            required_junction_keys=((case, "j1"),),
        ),
        (case, "s2"): SimpleNamespace(
            example=SimpleNamespace(fold=1),
            required_junction_keys=((case, "j1"), (case, "j2")),
        ),
        (case, "s3"): SimpleNamespace(
            example=SimpleNamespace(fold=1),
            required_junction_keys=((case, "j3"),),
        ),
    }
    junctions = {
        (case, value): SimpleNamespace(example=SimpleNamespace(fold=1))
        for value in ("j1", "j2", "j3")
    }

    components = build_joint_arch_closure_components(
        SimpleNamespace(segments=segments, junctions=junctions)
    )

    assert len(components) == 2
    assert sorted(len(row.segment_keys) for row in components) == [1, 2]
    assert sorted(len(row.junction_keys) for row in components) == [1, 2]


def _model(
    *,
    detach_junction_embeddings: bool = True,
) -> TargetAArchClosureNetwork:
    ordinary_config = TargetAEndToEndOrdinarySetConfig(
        hidden_dim=8,
        road_hidden_dim=8,
        access_hidden_dim=8,
        road_set_layers=1,
        road_set_heads=2,
        max_road_cardinality=4,
        dropout=0.0,
    )
    ordinary = TargetAEndToEndOrdinarySetNetwork(
        nn.Identity(),
        ordinary_config,
    )
    template = TargetAOrdinaryJointMainlineNetwork(
        ordinary,
        TargetAOrdinaryJointMainlineConfig(
            hidden_dim=8,
            road_hidden_dim=8,
            access_hidden_dim=8,
            break_hidden_dim=8,
            plan_hidden_dim=8,
            set_heads=2,
            plan_set_heads=2,
            max_access_cardinality=4,
            max_break_cardinality=4,
            dropout=0.0,
        ),
    )
    return TargetAArchClosureNetwork(
        template,
        TargetAArchClosureConfig(
            junction_embedding_dim=8,
            context_set_heads=2,
            detach_junction_embeddings=detach_junction_embeddings,
        ),
    ).eval()


def _batch() -> ArchClosureBatch:
    context = ArchClosureSegmentContextBatch(
        focal_feature_values=torch.zeros((1, TARGET_A_FEATURE_DIM)),
        peer_feature_values=torch.ones((1, 1, TARGET_A_FEATURE_DIM)),
        peer_mask=torch.ones((1, 1), dtype=torch.bool),
        junction_embedding_values=torch.zeros((1, 1, 8)),
        junction_confidence_values=torch.ones((1, 1, 4)),
        junction_state_values=torch.tensor([[ORDINARY_ANCHOR_SUCCESS]]),
        junction_mask=torch.ones((1, 1), dtype=torch.bool),
        peer_junction_relation_mask=torch.ones((1, 1, 1), dtype=torch.bool),
    )
    road_shape = (1, 2, 2)
    road_mask = torch.tensor([[[True, True], [False, False]]])
    member_targets = torch.tensor([[[True, False], [False, False]]])
    ordinary = EndToEndOrdinarySetBatch(
        case_keys=("T10:1",),
        advance_right_ids=("",),
        side_segment_ids=(("s1", ""),),
        side_group_indices=torch.tensor([[0, -1]]),
        side_object_values=torch.zeros((1, 2, SIDE_OBJECT_FEATURE_DIM)),
        side_road_values=torch.zeros((*road_shape, SIDE_ROAD_FEATURE_DIM)),
        side_road_mask=road_mask,
        side_road_source_indices=torch.tensor(
            [[[ORDINARY_SET_SOURCE_SWSD, ORDINARY_SET_SOURCE_RCSD], [0, 0]]]
        ),
        side_road_relation_values=torch.zeros(
            (*road_shape, 2, ORDINARY_SET_ROAD_RELATION_DIM)
        ),
        side_access_values=torch.zeros((1, 2, 1, SIDE_ACCESS_FEATURE_DIM)),
        side_access_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        decision_targets=torch.tensor(
            [[ORDINARY_DECISION_KEEP_SWSD, ORDINARY_DECISION_KEEP_SWSD]]
        ),
        decision_task_mask=torch.tensor([[True, False]]),
        road_member_targets=member_targets,
        road_task_mask=torch.tensor([[True, False]]),
        road_cardinality_targets=torch.tensor([[1, 0]]),
        access_targets=torch.zeros((1, 2, 1), dtype=torch.bool),
        access_task_mask=torch.zeros((1, 2), dtype=torch.bool),
        sample_weights=torch.tensor([[1.0, 0.0]]),
        candidate_reachable=torch.tensor([[True, False]]),
        road_ids=((('swsd', 'rcsd'), ()),),
        access_road_ids=(((), ()),),
        side_precomputed_anchor_context=torch.zeros((*road_shape, 8)),
        side_precomputed_anchor_state=torch.tensor(
            [[ORDINARY_ANCHOR_SUCCESS, 0]]
        ),
    )
    access = OrdinaryJointAccessBatch(
        proposal_values=torch.zeros((1, 2, 1, 1, ACCESS_COLLECTION_FEATURE_DIM)),
        proposal_road_indices=torch.full((1, 2, 1, 1), -1),
        proposal_mask=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        proposal_targets=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        task_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        cardinality_targets=torch.zeros((1, 2, 1), dtype=torch.long),
        sample_weights=torch.zeros((1, 2, 1)),
        junction_ids=(((), ()),),
        proposal_ids=((((),), ((),)),),
    )
    breaks = OrdinaryJointBreakBatch(
        parent_road_indices=torch.full((1, 2, 1), -1),
        parent_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        candidate_values=torch.zeros((1, 2, 1, 1, BREAK_CANDIDATE_FEATURE_DIM)),
        candidate_fractions=torch.zeros((1, 2, 1, 1)),
        candidate_mask=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        candidate_targets=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        task_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        presence_targets=torch.zeros((1, 2, 1), dtype=torch.bool),
        cardinality_targets=torch.zeros((1, 2, 1), dtype=torch.long),
        ownership_targets=torch.zeros((1, 2, 1), dtype=torch.long),
        sample_weights=torch.zeros((1, 2, 1)),
        parent_road_ids=(((), ()),),
    )
    plan_shape = (1, 2, 2)
    plan_membership = torch.zeros((*plan_shape, 2), dtype=torch.bool)
    plan_membership[0, 0, 0, 0] = True
    plan_membership[0, 0, 1, 1] = True
    structured = OrdinaryJointStructuredPlanBatch(
        plan_feature_values=torch.zeros((*plan_shape, TARGET_A_FEATURE_DIM)),
        plan_mask=torch.tensor([[[True, True], [False, False]]]),
        plan_hard_valid=torch.tensor([[[True, True], [False, False]]]),
        plan_decisions=torch.tensor(
            [[[ORDINARY_DECISION_KEEP_SWSD, ORDINARY_DECISION_USE_RCSD], [0, 0]]]
        ),
        plan_base_decisions=torch.tensor(
            [[[ORDINARY_DECISION_KEEP_SWSD, ORDINARY_DECISION_USE_RCSD], [0, 0]]]
        ),
        plan_road_membership=plan_membership,
        plan_role_targets=torch.zeros((*plan_shape, 2), dtype=torch.long),
        plan_ownership_targets=torch.zeros((*plan_shape, 2), dtype=torch.long),
        plan_access_road_membership=torch.zeros((*plan_shape, 2, 2), dtype=torch.bool),
        access_group_arm_indices=torch.tensor([[[-2], [-2]]]),
        acceptable_plan_mask=torch.tensor([[[True, False], [False, False]]]),
        task_mask=torch.tensor([[True, False]]),
        sample_weights=torch.tensor([[1.0, 0.0]]),
        teacher_gate_decisions=torch.tensor(
            [[ORDINARY_DECISION_KEEP_SWSD, -1]]
        ),
        plan_ids=((('keep', 'use'), ()),),
    )
    return ArchClosureBatch(
        keys=(("T10:1", "s1"),),
        model_input=_model_input(
            (("T10:1", "s1"),),
            context=context,
            ordinary=ordinary,
            access=access,
            breaks=breaks,
            structured=structured,
        ),
        context=context,
        ordinary=ordinary,
        access=access,
        breaks=breaks,
        structured=structured,
        examples=(),
    )
