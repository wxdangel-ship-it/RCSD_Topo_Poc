from __future__ import annotations

from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_data import (
    build_case_joint_examples,
    build_focal_ordinary_dependency_examples,
    build_segment_joint_examples,
    case_joint_data_contract,
    collate_case_joint_batch,
    focal_joint_anchor_repeat_counts,
    pack_case_joint_batches,
    segment_joint_anchor_repeat_counts,
    without_case_joint_teacher_forcing,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_network import (
    TargetACaseJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
)


def _features(value: float = 0.0) -> tuple[float, ...]:
    return (value,) * 64


def _anchor(
    anchor_id: str,
    *,
    success: bool = True,
    dependency_ids: tuple[str, ...] = (),
) -> AnchorPretrainExample:
    return AnchorPretrainExample(
        sample_id=f"CASE:{anchor_id}",
        case_key="CASE",
        anchor_id=anchor_id,
        fold=2,
        object_features=_features(0.1),
        candidate_ids=(f"NODE:{anchor_id}:A", f"NODE:{anchor_id}:B"),
        candidate_features=(_features(0.2), _features(0.3)),
        status_label=ANCHOR_STATUS_INDEX[
            AnchorStatus.SUCCESS if success else AnchorStatus.AMBIGUOUS
        ],
        candidate_acceptable_indices=((1,) if success else ()),
        preferred_candidate_index=(1 if success else -1),
        candidate_supervised=success,
        sample_weight=1.0,
        input_hashes=(),
        label_reason="TEST",
        dependency_anchor_ids=dependency_ids or (anchor_id,),
        status_supervised=True,
        gate_label=int(success),
        gate_supervised=True,
    )


def _ordinary(
    segment_id: str,
    required_anchor_ids: tuple[str, ...],
) -> OrdinaryPlanTrainingExample:
    return OrdinaryPlanTrainingExample(
        sample_id=f"CASE:{segment_id}",
        case_key="CASE",
        segment_id=segment_id,
        fold=2,
        object_features=_features(0.4),
        required_anchor_ids=required_anchor_ids,
        arm_anchor_ids=(),
        candidate_ids=("KEEP", "USE"),
        candidate_decisions=("KEEP_SWSD", "USE_RCSD"),
        candidate_road_ids=(("swsd",), ("rcsd",)),
        candidate_member_ids=((), ()),
        candidate_member_endpoint_ids=((), ()),
        candidate_member_features=((), ()),
        candidate_arm_road_ids=((), ()),
        candidate_arm_node_ids=((), ()),
        candidate_arm_features=((), ()),
        candidate_features=(_features(0.5), _features(0.6)),
        acceptable_indices=(1,),
        preferred_index=1,
        preferred_decision="USE_RCSD",
        sample_weight=1.0,
        clue_label=0,
        clue_task_mask=True,
        fallback_scope_label=0,
        fallback_scope_task_mask=True,
    )


def test_case_joint_batch_maps_hard_anchor_gate_and_graph() -> None:
    anchors = (
        _anchor("A", dependency_ids=("A", "B")),
        _anchor("B", success=False, dependency_ids=("A", "B")),
    )
    ordinary = (
        _ordinary("S1", ("A",)),
        _ordinary("S2", ("A", "B")),
        _ordinary("S3", ("MISSING",)),
    )
    examples = build_case_joint_examples(anchors, ordinary)
    assert len(examples) == 1

    case_batch = collate_case_joint_batch(
        examples[0],
        teacher_forcing=True,
    )
    tensors = case_batch.training_batch.tensors
    targets = case_batch.training_batch.targets

    assert tensors.object_features.shape == (1, 5, 64)
    assert tensors.anchor_object_indices.tolist() == [[0, 1]]
    assert tensors.ordinary_object_indices.tolist() == [[2, 3, 4]]
    assert tensors.ordinary_required_anchor_indices.tolist() == [
        [[0, -1], [0, 1], [-1, -1]]
    ]
    assert tensors.adjacency[0, 0, 1]
    assert tensors.adjacency[0, 2, 0]
    assert not tensors.adjacency[0, 0, 2]
    assert not tensors.adjacency[0, 1, 4]
    assert targets.ordinary_task_mask.tolist() == [[True, False, False]]
    assert tensors.teacher_anchor_candidate_indices.tolist() == [[1, 0]]
    assert tensors.teacher_anchor_success.tolist() == [[True, False]]

    contract = case_joint_data_contract(examples)
    assert contract["ordinary_training_ready_count"] == 1
    assert contract["ordinary_missing_required_anchor_count"] == 1
    assert contract["ordinary_unresolved_required_anchor_count"] == 1
    assert contract["store_read_pass_count"] == 1


def test_proven_no_evidence_allows_positive_keep_training_only() -> None:
    no_evidence = replace(
        _anchor("A", success=False),
        status_label=ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
        status_supervised=True,
        gate_supervised=True,
    )
    keep = replace(
        _ordinary("KEEP", ("A",)),
        acceptable_indices=(0,),
        preferred_index=0,
        preferred_decision="KEEP_SWSD",
    )
    use = _ordinary("USE", ("A",))
    examples = build_case_joint_examples((no_evidence,), (keep, use))
    batch = collate_case_joint_batch(
        examples[0],
        teacher_forcing=True,
    ).training_batch
    assert batch.targets.ordinary_task_mask.tolist() == [[True, False]]
    assert batch.tensors.teacher_anchor_success.tolist() == [[False]]
    contract = case_joint_data_contract(examples)
    assert contract["ordinary_training_ready_count"] == 1
    assert contract["ordinary_unresolved_required_anchor_count"] == 1


def test_case_joint_free_run_removes_all_teacher_choices() -> None:
    example = build_case_joint_examples(
        (_anchor("A"),),
        (_ordinary("S", ("A",)),),
    )[0]
    training = collate_case_joint_batch(
        example,
        teacher_forcing=True,
    ).training_batch
    free = without_case_joint_teacher_forcing(training)
    assert free.tensors.teacher_anchor_candidate_indices is None
    assert free.tensors.teacher_anchor_success is None
    assert free.tensors.teacher_ordinary_plan_indices is None


def test_ordinary_loss_observes_same_forward_anchor_candidate_evidence() -> None:
    example = build_case_joint_examples(
        (_anchor("A"),),
        (_ordinary("S", ("A",)),),
    )[0]
    training = collate_case_joint_batch(
        example,
        teacher_forcing=True,
    ).training_batch
    anchor_features = (
        training.tensors.anchor_candidate_features.clone().requires_grad_(True)
    )
    tensors = replace(
        training.tensors,
        anchor_candidate_features=anchor_features,
    )
    config = TargetAConfig(
        hidden_dim=32,
        num_heads=4,
        graph_layers=1,
        set_layers=1,
        feedforward_dim=64,
        dropout=0.0,
        min_parameter_count=1,
        max_parameter_count=2_000_000,
        max_epochs=2,
        patience=1,
        stop_gradient_between_stages=False,
    )
    model = TargetAJointNetwork(config)
    outputs = model(tensors)
    ordinary_loss = -torch.log_softmax(
        outputs["ordinary_plan_logits"][0, 0],
        dim=-1,
    )[1]
    ordinary_loss.backward()
    assert anchor_features.grad is not None
    assert float(anchor_features.grad.abs().sum()) > 0.0


def test_segment_joint_subgraph_stops_after_direct_anchor_dependencies() -> None:
    anchors = (
        _anchor("A", dependency_ids=("A", "B")),
        _anchor("B", dependency_ids=("B", "C")),
        _anchor("C", dependency_ids=("C",)),
    )
    ordinary = (
        _ordinary("S1", ("A",)),
        _ordinary("S2", ("A",)),
    )
    examples = build_segment_joint_examples(anchors, ordinary)
    assert len(examples) == 2
    assert [row.anchor_id for row in examples[0].anchors] == ["A", "B"]
    assert all(
        len(row.ordinary_segments) == 1
        for row in examples
    )

    repeats = segment_joint_anchor_repeat_counts(examples)
    assert repeats[("CASE", "A")] == 2
    batch = collate_case_joint_batch(
        examples[0],
        teacher_forcing=True,
        anchor_repeat_counts=repeats,
    ).training_batch
    assert batch.targets.anchor_status_mask.tolist() == [[True, False]]
    assert batch.targets.anchor_candidate_task_mask.tolist() == [
        [True, False]
    ]
    assert batch.targets.anchor_sample_weights.tolist() == [[0.5, 1.0]]


def test_focal_ordinary_graph_stops_at_immediate_junction_neighbors() -> None:
    anchors = (
        _anchor("A", dependency_ids=("A", "B")),
        _anchor("B", dependency_ids=("B", "C")),
        _anchor("C", dependency_ids=("C",)),
        _anchor("D", dependency_ids=("D",)),
    )
    ordinary = (
        _ordinary("FOCAL", ("A",)),
        _ordinary("SHARES_A", ("A", "D")),
        _ordinary("SHARES_B", ("B", "C")),
        _ordinary("TRANSITIVE_C", ("C",)),
        _ordinary("TRANSITIVE_D", ("D",)),
    )

    examples = build_focal_ordinary_dependency_examples(
        anchors,
        ordinary,
        lightweight_context_segments=True,
    )
    focal = next(
        row
        for row in examples
        if row.ordinary_segments[0].segment_id == "FOCAL"
    )

    assert [row.anchor_id for row in focal.anchors] == ["A", "B"]
    assert [row.segment_id for row in focal.ordinary_segments] == [
        "FOCAL",
        "SHARES_A",
        "SHARES_B",
    ]
    assert focal.ordinary_segments[0].candidate_ids != (
        "CONTEXT_ONLY:FOCAL",
    )
    assert focal.ordinary_segments[1].candidate_ids == (
        "CONTEXT_ONLY:SHARES_A",
    )
    assert focal.ordinary_segments[2].candidate_ids == (
        "CONTEXT_ONLY:SHARES_B",
    )
    assert all(
        not row.carrier_task_mask
        for row in focal.ordinary_segments[1:]
    )

    repeats = focal_joint_anchor_repeat_counts(examples)
    batch = collate_case_joint_batch(
        focal,
        teacher_forcing=False,
        anchor_repeat_counts=repeats,
        focal_only_supervision=True,
        bidirectional_segment_anchor_context=False,
        segment_peer_context=True,
    ).training_batch
    adjacency = batch.tensors.adjacency[0]
    assert bool(adjacency[2, 0])
    assert not bool(adjacency[0, 2])
    assert not bool(adjacency[0, 3])
    assert not bool(adjacency[1, 4])
    assert bool(adjacency[2, 3])
    assert bool(adjacency[3, 2])
    assert bool(adjacency[2, 4])
    assert bool(adjacency[4, 2])
    assert batch.targets.anchor_status_mask.tolist() == [[True, False]]
    assert batch.targets.ordinary_task_mask.tolist() == [
        [True, False, False]
    ]
    assert batch.targets.clue_task_mask[:, 1:].sum().item() == 0
    assert batch.targets.fallback_scope_task_mask[:, 1:].sum().item() == 0
    assert batch.targets.ordinary_sample_weights.tolist() == [
        [1.0, 0.0, 0.0]
    ]


def test_focal_graph_includes_reverse_direct_anchor_dependency_only() -> None:
    anchors = (
        _anchor("A", dependency_ids=("A",)),
        _anchor("B", dependency_ids=("B", "A")),
        _anchor("C", dependency_ids=("C", "B")),
    )
    ordinary = (_ordinary("FOCAL", ("A",)),)

    example = build_focal_ordinary_dependency_examples(
        anchors,
        ordinary,
        lightweight_context_segments=True,
    )[0]

    assert [row.anchor_id for row in example.anchors] == ["A", "B"]


def test_case_joint_packing_pads_independent_subgraphs() -> None:
    first = build_segment_joint_examples(
        (_anchor("A"),),
        (_ordinary("S1", ("A",)),),
    )
    second = build_segment_joint_examples(
        (
            _anchor("B", dependency_ids=("B", "C")),
            _anchor("C", dependency_ids=("C",)),
        ),
        (_ordinary("S2", ("B",)),),
    )
    rows = [
        collate_case_joint_batch(row, teacher_forcing=True)
        for row in (*first, *second)
    ]
    packed = pack_case_joint_batches(
        rows,
        max_batch_size=2,
        max_anchor_groups=4,
    )
    assert len(packed) == 1
    training = packed[0].training_batch
    assert training.tensors.object_features.shape == (2, 3, 64)
    assert training.tensors.anchor_candidate_features.shape[:2] == (2, 2)
    assert training.tensors.object_mask.tolist() == [
        [True, True, False],
        [True, True, True],
    ]
    assert training.targets.ordinary_task_mask.tolist() == [[True], [True]]


def test_anchor_output_is_independent_of_focal_carrier_features() -> None:
    first = _ordinary("S1", ("A",))
    second = replace(
        _ordinary("S2", ("A",)),
        object_features=_features(9.0),
    )
    examples = build_segment_joint_examples(
        (_anchor("A"),),
        (first, second),
    )
    rows = [
        collate_case_joint_batch(row, teacher_forcing=False)
        for row in examples
    ]
    packed = pack_case_joint_batches(
        rows,
        max_batch_size=2,
        max_anchor_groups=2,
    )[0].training_batch
    config = TargetAConfig(
        hidden_dim=32,
        num_heads=4,
        graph_layers=1,
        set_layers=1,
        feedforward_dim=64,
        dropout=0.0,
        min_parameter_count=1,
        max_parameter_count=2_000_000,
        max_epochs=2,
        patience=1,
        stop_gradient_between_stages=False,
    )
    model = TargetAJointNetwork(config).eval()
    with torch.no_grad():
        outputs = model(packed.tensors)
    assert torch.equal(
        outputs["anchor_status_logits"][0, 0],
        outputs["anchor_status_logits"][1, 0],
    )
    assert torch.equal(
        outputs["anchor_candidate_logits"][0, 0],
        outputs["anchor_candidate_logits"][1, 0],
    )


def test_case_joint_network_adds_explicit_anchor_plan_compatibility() -> None:
    example = build_segment_joint_examples(
        (_anchor("A"),),
        (_ordinary("S", ("A",)),),
    )[0]
    batch = collate_case_joint_batch(
        example,
        teacher_forcing=True,
    ).training_batch
    config = TargetAConfig(
        hidden_dim=32,
        num_heads=4,
        graph_layers=1,
        set_layers=1,
        feedforward_dim=64,
        dropout=0.0,
        min_parameter_count=1,
        max_parameter_count=2_000_000,
        max_epochs=2,
        patience=1,
        stop_gradient_between_stages=False,
    )
    model = TargetACaseJointNetwork(config)
    tensors = replace(
        batch.tensors,
        ordinary_plan_mask=torch.tensor([[[True, False]]]),
    )
    outputs = model(tensors)
    assert outputs["anchor_plan_compatibility_logits"].shape == (1, 1, 2)
    assert torch.isfinite(outputs["anchor_plan_compatibility_logits"][0, 0, 0])
    assert torch.isneginf(
        outputs["anchor_plan_compatibility_logits"][0, 0, 1]
    )
    assert float(outputs["anchor_plan_compatibility_scale"].item()) > 0.0
    loss = outputs["ordinary_plan_logits"][0, 0, 0]
    loss.backward()
    assert model.case_joint_anchor_projection.weight.grad is not None
    assert model.case_joint_plan_projection.weight.grad is not None
    assert torch.isfinite(model.case_joint_compatibility_scale.grad)


def test_auxiliary_only_compatibility_does_not_change_plan_logits() -> None:
    example = build_segment_joint_examples(
        (_anchor("A"),),
        (_ordinary("S", ("A",)),),
    )[0]
    batch = collate_case_joint_batch(
        example,
        teacher_forcing=True,
    ).training_batch
    config = TargetAConfig(
        hidden_dim=32,
        num_heads=4,
        graph_layers=1,
        set_layers=1,
        feedforward_dim=64,
        dropout=0.0,
        min_parameter_count=1,
        max_parameter_count=2_000_000,
        max_epochs=2,
        patience=1,
        stop_gradient_between_stages=False,
    )
    model = TargetACaseJointNetwork(
        config,
        apply_compatibility_to_plan_logits=False,
    ).eval()
    baseline = TargetAJointNetwork(config).eval()
    baseline.load_state_dict(
        {
            key: value
            for key, value in model.state_dict().items()
            if key in baseline.state_dict()
        }
    )
    with torch.no_grad():
        base_outputs = baseline(batch.tensors)
        joint_outputs = model(batch.tensors)
    assert torch.equal(
        base_outputs["ordinary_plan_logits"],
        joint_outputs["ordinary_plan_logits"],
    )
    assert "anchor_plan_compatibility_logits" in joint_outputs
