from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_member_set_decoder import (
    decode_anchor_member_sets,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
)


def test_atomic_decoder_selects_typed_top_k_complete_set() -> None:
    road = [0.0] * 64
    road[27] = 1.0
    example = AnchorPretrainExample(
        sample_id="atomic",
        case_key="T10:case",
        anchor_id="anchor",
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("ROAD:r1", "ROAD:r2", "ROAD:r3"),
        candidate_features=(tuple(road), tuple(road), tuple(road)),
        status_label=0,
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=0.7,
        input_hashes=(("input", "hash"),),
        label_reason="member-only",
        structural_member_ids=("ROAD:r1", "ROAD:r2", "ROAD:r3"),
        member_arm_features=((), (), ()),
        member_acceptable_sets=((0, 2),),
        member_supervised=True,
    )
    batch = collate_anchor_pretrain_batch((example,))
    outputs = {
        "anchor_member_logits": torch.tensor([[[3.0, -3.0, 2.0]]]),
        "anchor_type_logits": torch.tensor([[[-5.0, 5.0]]]),
        "anchor_cardinality_logits": torch.tensor(
            [[[[0.0, 0.0, 0.0, 0.0], [0.0, 5.0, 0.0, 0.0]]]]
        ),
    }

    decoded = decode_anchor_member_sets(outputs, batch.tensors)

    assert decoded.selected_members.tolist() == [[[True, False, True]]]
    assert decoded.cardinality_prediction.tolist() == [[2]]
    assert decoded.type_prediction.tolist() == [[1]]
    assert float(decoded.confidence.item()) > 0.9

    threshold_decoded = decode_anchor_member_sets(
        {
            **outputs,
            "anchor_cardinality_logits": torch.tensor(
                [[[[0.0, 0.0, 0.0, 0.0], [5.0, 0.0, 0.0, 0.0]]]]
            ),
        },
        batch.tensors,
        member_probability_threshold=0.5,
    )
    assert threshold_decoded.selected_members.tolist() == [
        [[True, False, True]]
    ]
    assert threshold_decoded.cardinality_prediction.tolist() == [[2]]
