import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_cardinality_training import (
    decode_structured_access_outputs,
    structured_multi_solution_loss,
)


def test_structured_loss_rewards_correct_members_and_cardinality() -> None:
    good = structured_multi_solution_loss(
        torch.tensor([4.0, -3.0, 3.0]),
        torch.tensor([-3.0, 4.0, -3.0]),
        [(0, 2)],
    )
    bad = structured_multi_solution_loss(
        torch.tensor([-3.0, 4.0, -3.0]),
        torch.tensor([4.0, -3.0, -3.0]),
        [(0, 2)],
    )

    assert good < bad


def test_decode_selects_exact_top_k_from_cardinality_head() -> None:
    decoded = decode_structured_access_outputs(
        [
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "junction_id": "junction",
                "proposal_ids": ["p0", "p1", "p2"],
                "road_ids": ["r0", "r1", "r2"],
                "member_logits": [3.0, -2.0, 2.0],
                "member_probabilities": [0.95, 0.1, 0.9],
                "cardinality_probabilities": [0.1, 0.8, 0.1],
                "acceptable_index_sets": [[0, 2]],
                "oof_anchor_release_ready": True,
                "upstream_plan_release_blocked": False,
            }
        ]
    )

    assert decoded[0]["predicted_indices"] == [0, 2]
    assert decoded[0]["predicted_cardinality"] == 2
    assert decoded[0]["cardinality_exact"]
    assert decoded[0]["raw_set_exact"]
