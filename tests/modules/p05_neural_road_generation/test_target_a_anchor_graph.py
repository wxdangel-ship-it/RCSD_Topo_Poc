from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_graph import (
    anchor_dependency_contract,
    build_anchor_dependency_groups,
    collate_anchor_dependency_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    compute_target_a_loss,
)


def _example(
    anchor_id: str,
    dependencies: tuple[str, ...],
    *,
    weight: float = 0.7,
) -> AnchorPretrainExample:
    arm = (0.0, 1.0, 0.25, 1.0, 0.0, 0.0, 0.0)
    return AnchorPretrainExample(
        sample_id=f"sample-{anchor_id}",
        case_key="T10:1",
        anchor_id=anchor_id,
        fold=2,
        object_features=(0.0,) * 64,
        candidate_ids=(f"NODE:{anchor_id}",),
        candidate_features=((0.0,) * 64,),
        status_label=0,
        candidate_acceptable_indices=(0,),
        preferred_candidate_index=0,
        candidate_supervised=True,
        sample_weight=weight,
        input_hashes=(("t01_segment", "abc"),),
        label_reason="confirmed",
        dependency_anchor_ids=dependencies,
        structural_member_ids=(f"NODE:{anchor_id}",),
        swsd_arm_features=(arm,),
        member_arm_features=((arm,),),
        member_local_features=((0.0,) * 12,),
    )


def test_anchor_dependency_group_uses_t01_segment_edges() -> None:
    examples = (
        _example("a", ("a", "b")),
        _example("b", ("a", "b")),
        _example("c", ("c",)),
    )

    groups = build_anchor_dependency_groups(examples)

    assert [tuple(row.anchor_id for row in group.examples) for group in groups] == [
        ("a", "b"),
        ("b", "a"),
        ("c",),
    ]
    assert groups[0].adjacency == ((True, True), (True, True))
    assert groups[1].adjacency == ((True, True), (True, True))
    assert groups[2].adjacency == ((True,),)
    assert anchor_dependency_contract(examples)["direct_dependency_edge_count"] == 1


def test_anchor_dependency_collate_preserves_per_anchor_weights() -> None:
    groups = build_anchor_dependency_groups(
        (
            _example("a", ("a", "b"), weight=1.0),
            _example("b", ("a", "b"), weight=0.7),
            _example("c", ("c",), weight=0.7),
        )
    )

    batch = collate_anchor_dependency_groups(
        groups,
        include_candidate_relations=True,
    )

    assert batch.tensors.object_features.shape == (3, 2, 64)
    assert batch.tensors.anchor_candidate_features.shape == (3, 1, 1, 64)
    assert batch.tensors.object_mask.tolist() == [
        [True, True],
        [True, True],
        [True, False],
    ]
    assert batch.tensors.anchor_candidate_mask[:, 0, 0].all()
    assert batch.tensors.anchor_candidate_relations is not None
    assert batch.tensors.anchor_candidate_relations.shape == (3, 1, 1, 1, 8)
    assert batch.tensors.anchor_member_mask is not None
    assert batch.tensors.anchor_member_mask[:, 0, 0].all()
    assert batch.tensors.anchor_swsd_arm_mask is not None
    assert batch.tensors.anchor_swsd_arm_mask[:, 0, 0].all()
    assert batch.tensors.anchor_member_arm_mask is not None
    assert batch.tensors.anchor_member_arm_mask[:, 0, 0, 0].all()
    assert batch.tensors.anchor_member_local_features is not None
    assert batch.tensors.anchor_member_local_features.shape == (3, 1, 1, 12)
    assert batch.tensors.anchor_member_relation_mask is not None
    assert not batch.tensors.anchor_member_relation_mask.any()
    assert batch.targets.anchor_status_mask.tolist() == [
        [True],
        [True],
        [True],
    ]
    assert batch.targets.anchor_sample_weights is not None
    assert (
        batch.targets.anchor_sample_weights.flatten().tolist()
        == pytest.approx([1.0, 0.7, 0.7])
    )


def test_anchor_dependency_forward_and_loss_ignore_padded_anchor() -> None:
    groups = build_anchor_dependency_groups(
        (
            _example("a", ("a", "b"), weight=1.0),
            _example("b", ("a", "b"), weight=0.7),
            _example("c", ("c",), weight=0.7),
        )
    )
    batch = collate_anchor_dependency_groups(groups)
    config = TargetAConfig()

    outputs = TargetAJointNetwork(config)(batch.tensors)
    loss, _ = compute_target_a_loss(outputs, batch, config)

    assert torch.isfinite(loss)
    assert torch.isfinite(outputs["anchor_status_logits"]).all()
    assert torch.isfinite(outputs["object_embeddings"]).all()


def test_anchor_dependency_forward_consumes_structural_evidence() -> None:
    groups = build_anchor_dependency_groups(
        (
            _example("a", ("a", "b"), weight=1.0),
            _example("b", ("a", "b"), weight=0.7),
            _example("c", ("c",), weight=0.7),
        )
    )
    batch = collate_anchor_dependency_groups(groups)
    config = TargetAConfig(
        hierarchical_anchor_decoder=True,
        compositional_anchor_object_decoder=True,
        anchor_structural_evidence_encoder=True,
    )

    outputs = TargetAJointNetwork(config)(batch.tensors)

    assert outputs["anchor_member_structural_context"].shape == (3, 1, 1, 352)
    assert outputs["anchor_candidate_structural_context"].shape == (
        3,
        1,
        1,
        352,
    )
    assert torch.isfinite(outputs["anchor_candidate_logits"]).all()
