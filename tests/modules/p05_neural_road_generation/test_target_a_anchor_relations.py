from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_relations import (
    ANCHOR_CANDIDATE_RELATION_DIM,
    anchor_candidate_relation_matrix,
)


def test_anchor_candidate_relations_encode_member_structure_without_ids() -> None:
    relations = anchor_candidate_relation_matrix(
        (
            "ROAD:a",
            "ROAD:a|b",
            "ROAD:c",
            "NODE:a",
        )
    )

    assert relations.shape == (4, 4, ANCHOR_CANDIDATE_RELATION_DIM)
    assert relations[0, 1, 2].item() == 1.0
    assert relations[1, 0, 3].item() == 1.0
    assert relations[0, 2, 4].item() == 0.0
    assert relations[0, 3, 0].item() == 0.0
    assert torch.allclose(relations.diagonal(dim1=0, dim2=1)[1], torch.ones(4))
