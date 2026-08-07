from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    audit_anchor_store_leakage,
    collate_anchor_pretrain_batch,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)


def test_anchor_store_keeps_features_and_labels_physically_separate() -> None:
    features = [
        {
            "sample_id": "s1",
            "case_key": "T03:1",
            "object_features": [0.0],
            "candidate_features": [[0.0]],
        }
    ]
    labels = [{"sample_id": "s1", "status_label": 0, "sample_weight": 1.0}]
    assert audit_anchor_store_leakage(features, labels)["passed"]


def test_anchor_store_leakage_audit_rejects_terminal_label_feature() -> None:
    features = [{"sample_id": "s1", "status_label": 0}]
    labels = [{"sample_id": "s1"}]
    result = audit_anchor_store_leakage(features, labels)
    assert not result["passed"]
    assert result["feature_forbidden_keys"] == ["status_label"]


def test_anchor_store_round_trip_preserves_separate_join(tmp_path: Path) -> None:
    candidate_features = [1.0] * 64
    candidate_features[27] = 0.0
    example = AnchorPretrainExample(
        sample_id="s1",
        case_key="T03:1",
        anchor_id="semantic-junction-1",
        fold=2,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:rcsd-node-1",),
        candidate_features=(tuple(candidate_features),),
        status_label=0,
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=1.0,
        input_hashes=(("nodes", "abc"),),
        label_reason="confirmed",
        dependency_anchor_ids=("semantic-junction-1",),
        status_supervised=False,
        gate_label=1,
        gate_supervised=True,
        structural_member_ids=("NODE:rcsd-node-1",),
        member_arm_features=((),),
        member_acceptable_sets=((0,),),
        member_supervised=True,
    )
    store = write_anchor_pretraining_stores(
        [example],
        output_root=tmp_path,
        run_id="round_trip",
    )
    assert read_anchor_pretraining_stores(store) == [example]
    batch = collate_anchor_pretrain_batch(
        (example,),
        include_candidate_relations=True,
    )
    assert batch.tensors.anchor_candidate_relations is not None
    assert batch.tensors.anchor_candidate_relations.shape == (1, 1, 1, 1, 8)
    assert batch.tensors.anchor_member_features is not None
    assert batch.tensors.anchor_member_features.shape == (1, 1, 1, 64)
    assert batch.tensors.anchor_candidate_membership is not None
    assert batch.tensors.anchor_candidate_membership.tolist() == [[[[True]]]]
    assert batch.targets.anchor_status_mask.tolist() == [[False]]
    assert batch.tensors.teacher_anchor_success.tolist() == [[False]]
    assert batch.targets.anchor_gate is not None
    assert batch.targets.anchor_gate.tolist() == [[1]]
    assert batch.targets.anchor_gate_mask is not None
    assert batch.targets.anchor_gate_mask.tolist() == [[True]]
    assert batch.targets.anchor_member_acceptable_sets is not None
    assert batch.targets.anchor_member_acceptable_sets.tolist() == [
        [[[True]]]
    ]
    assert batch.targets.anchor_member_acceptable_set_mask is not None
    assert batch.targets.anchor_member_acceptable_set_mask.tolist() == [
        [[True]]
    ]
    assert batch.targets.anchor_member_task_mask is not None
    assert batch.targets.anchor_member_task_mask.tolist() == [[True]]


def test_anchor_structural_evidence_round_trip_and_collate(
    tmp_path: Path,
) -> None:
    candidate_features = [0.0] * 64
    candidate_features[27] = 0.0
    arm = (0.0, 1.0, 0.25, 1.0, 0.0, 0.0, 0.0)
    example = AnchorPretrainExample(
        sample_id="s-structural",
        case_key="T03:1",
        anchor_id="semantic-junction-1",
        fold=2,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:rcsd-node-1",),
        candidate_features=(tuple(candidate_features),),
        status_label=0,
        candidate_acceptable_indices=(0,),
        preferred_candidate_index=0,
        candidate_supervised=True,
        sample_weight=1.0,
        input_hashes=(("nodes", "abc"),),
        label_reason="confirmed",
        dependency_anchor_ids=("semantic-junction-1",),
        structural_member_ids=("NODE:rcsd-node-1",),
        swsd_arm_features=(arm,),
        member_arm_features=((arm,),),
        member_local_features=((0.0,) * 12,),
    )
    store = write_anchor_pretraining_stores(
        [example],
        output_root=tmp_path,
        run_id="structural_round_trip",
    )

    assert read_anchor_pretraining_stores(store) == [example]
    batch = collate_anchor_pretrain_batch((example,))
    tensors = batch.tensors
    assert tensors.anchor_swsd_arm_features is not None
    assert tensors.anchor_swsd_arm_features.shape == (1, 1, 1, 7)
    assert tensors.anchor_swsd_arm_mask is not None
    assert tensors.anchor_swsd_arm_mask.tolist() == [[[True]]]
    assert tensors.anchor_member_arm_features is not None
    assert tensors.anchor_member_arm_features.shape == (1, 1, 1, 1, 7)
    assert tensors.anchor_member_arm_mask is not None
    assert tensors.anchor_member_arm_mask.tolist() == [[[[True]]]]
    assert tensors.anchor_member_local_features is not None
    assert tensors.anchor_member_local_features.shape == (1, 1, 1, 12)
    assert tensors.anchor_member_relation_features is not None
    assert tensors.anchor_member_relation_features.shape == (
        1,
        1,
        1,
        1,
        7,
    )
    assert tensors.anchor_member_relation_mask is not None
    assert not tensors.anchor_member_relation_mask.any()
