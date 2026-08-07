from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_ROAD_RELATION_DIM,
    EndToEndOrdinarySetBatch,
    collate_ordinary_set_pretraining_batch,
    read_anchor_oof_business_predictions,
    read_truth_free_ordinary_segment_road_pools,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetConfig,
    TargetAEndToEndOrdinarySetNetwork,
    compute_end_to_end_ordinary_set_loss,
    decode_ordinary_road_cardinality,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_set_expansion import (
    compute_order_free_set_expansion_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)


def test_ordinary_segment_pool_removes_selected_anchor_state(
    tmp_path: Path,
) -> None:
    row = {
        "case_key": "T10:case",
        "segment_id": "s1",
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "object_feature_values": [0.0] * 64,
        "candidate_rows": [
            {
                "road_id": "r1",
                "source": "RCSD",
                "oof_feature_values": [1.0] * 40,
                "oof_anchor_relation_values": [
                    [1.0, 2.0, 3.0, 4.0],
                ],
            }
        ],
        "oof_anchor_release_ready": True,
        "road_relation_rows": [],
    }
    path = tmp_path / "ordinary_road_member_features.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    (tmp_path / "ordinary_road_member_labels.jsonl").write_text(
        json.dumps(
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "acceptable_road_ids": ["r1", "retained_swsd"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    pools = read_truth_free_ordinary_segment_road_pools(
        tmp_path,
        required_keys={("T10:case", "s1")},
    )
    pool = pools[("T10:case", "s1")]
    values = pool.road_feature_values[0]
    assert values[:32] == (1.0,) * 32
    assert values[32:] == (0.0,) * 8
    assert pool.acceptable_road_ids == ("r1", "retained_swsd")
    assert pool.oof_anchor_release_ready
    assert pool.oof_anchor_relations == (((1.0, 2.0, 3.0, 4.0),),)


def test_oof_anchor_reader_uses_only_inference_business_state(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "case_key": "T10:case",
            "anchor_id": "a1",
            "candidate_predicted_id": "ROAD:r1",
            "predicted": "SUCCESS",
            "gate_passed": True,
            "proven_safe_anchor": False,
        },
        {
            "case_key": "T10:case",
            "anchor_id": "a2",
            "predicted": "NO_EVIDENCE",
            "gate_passed": True,
            "proven_safe_anchor": True,
        },
        {
            "case_key": "T10:case",
            "anchor_id": "a3",
            "predicted": "NO_EVIDENCE",
            "gate_passed": True,
            "no_evidence_proof_passed": True,
        },
        {
            "case_key": "T10:case",
            "anchor_id": "a4",
            "candidate_predicted_id": "ROAD:r4",
            "predicted": "SUCCESS",
            "gate_passed": False,
            "proven_safe_anchor": True,
        },
    ]
    (tmp_path / "oof_predictions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    predictions = read_anchor_oof_business_predictions(tmp_path)
    assert predictions[("T10:case", "a1")].business_state == (
        ORDINARY_ANCHOR_SUCCESS
    )
    assert predictions[("T10:case", "a1")].candidate_id == "ROAD:r1"
    assert predictions[("T10:case", "a2")].business_state == (
        ORDINARY_ANCHOR_UNRESOLVED
    )
    assert predictions[("T10:case", "a3")].business_state == (
        ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE
    )
    assert predictions[("T10:case", "a4")].business_state == (
        ORDINARY_ANCHOR_UNRESOLVED
    )


def test_ordinary_road_cardinality_supports_ordered_count_decoding() -> None:
    logits = torch.tensor(
        [[4.0, 2.0, -1.0, 3.0], [-1.0, 4.0, 3.0, 2.0]]
    )
    assert decode_ordinary_road_cardinality(
        logits,
        mode="categorical",
    ).tolist() == [0, 1]
    assert decode_ordinary_road_cardinality(
        logits,
        mode="ordinal",
    ).tolist() == [2, 0]


def test_ordinary_set_network_applies_free_run_hard_chain() -> None:
    hidden_dim = 16
    tensors = _batch_tensors()
    ordinary_set = _ordinary_set_batch()
    model = TargetAEndToEndOrdinarySetNetwork(
        _FakeBase(hidden_dim),
        TargetAEndToEndOrdinarySetConfig(
            hidden_dim=hidden_dim,
            road_hidden_dim=8,
            access_hidden_dim=8,
            road_set_layers=1,
            road_set_heads=2,
            max_road_cardinality=4,
            dropout=0.0,
        ),
    )
    final_decision = model.decision_head[-1]
    nn.init.zeros_(final_decision.weight)
    final_decision.bias.data.copy_(torch.tensor([0.0, 8.0, -8.0]))
    side_inputs = []
    handle = model.side_context.register_forward_pre_hook(
        lambda _module, args: side_inputs.append(args[0].detach().clone())
    )
    outputs = model(tensors, ordinary_set)
    handle.remove()
    assert torch.equal(
        side_inputs[0][..., :hidden_dim],
        torch.zeros((1, 2, hidden_dim)),
    )
    assert outputs["advance_right_business_ready"].item()
    assert outputs["advance_right_business_plan_type"].item() == 2
    assert torch.isneginf(
        outputs["advance_right_business_plan_logits"][0, 0, 0]
    )
    assert torch.isfinite(
        outputs["advance_right_business_plan_logits"][0, 0, 1]
    )
    hierarchical_batch = replace(
        ordinary_set,
        side_precomputed_anchor_context=torch.zeros((1, 2, 2, 8)),
        side_precomputed_anchor_state=torch.tensor([[1, 0]]),
        side_required_anchor_indices=torch.zeros(
            (1, 2, 1),
            dtype=torch.long,
        ),
        side_anchor_candidate_relation_values=torch.zeros(
            (1, 2, 2, 1, 1, 4)
        ),
        side_anchor_candidate_mask=torch.ones(
            (1, 2, 1, 1),
            dtype=torch.bool,
        ),
    )
    hierarchical_outputs = model(tensors, hierarchical_batch)
    assert not hierarchical_outputs[
        "advance_right_business_ready"
    ].item()
    hierarchical_outputs = model(
        tensors,
        replace(
            hierarchical_batch,
            side_precomputed_anchor_state=torch.ones(
                (1, 2),
                dtype=torch.long,
            ),
        ),
    )
    assert hierarchical_outputs[
        "advance_right_business_ready"
    ].item()
    loss, parts = compute_end_to_end_ordinary_set_loss(
        outputs,
        ordinary_set,
    )
    assert torch.isfinite(loss)
    assert set(parts) == {
        "ordinary_side_access_loss",
        "ordinary_side_business_role_loss",
        "ordinary_side_cardinality_loss",
        "ordinary_side_decision_loss",
        "ordinary_side_member_loss",
        "ordinary_side_ownership_loss",
    }
    expansion_loss, expansion_parts = (
        compute_order_free_set_expansion_loss(
            model,
            outputs,
            ordinary_set,
            seed=7,
            state_count=4,
        )
    )
    assert torch.isfinite(expansion_loss)
    assert expansion_parts["ordinary_expansion_task_count"].item() == 2
    selected = torch.zeros((1, 2, 2), dtype=torch.bool)
    selected[0, 0, 0] = True
    next_outputs = model.decode_ordinary_next(
        outputs,
        ordinary_set,
        selected,
    )
    assert next_outputs["next_road_logits"].shape == (1, 2, 1, 2)
    assert next_outputs["stop_logits"].shape == (1, 2, 1)
    assert next_outputs["next_road_logits"][0, 0, 0, 0] < -1e20

    nn.init.zeros_(model.next_road_head[-1].weight)
    nn.init.zeros_(model.next_road_head[-1].bias)
    nn.init.zeros_(model.stop_head[-1].weight)
    model.stop_head[-1].bias.data.fill_(-8.0)
    greedy = model.greedy_decode_ordinary_set(
        outputs,
        ordinary_set,
        torch.ones((1, 2), dtype=torch.long),
    )
    assert greedy["selected_mask"].all()
    assert greedy["stopped"].all()


def test_ordinary_set_pretraining_batch_removes_selected_anchor_state() -> None:
    example = OrdinaryRoadSetExample(
        case_key="T10:case",
        segment_id="s1",
        fold=1,
        object_features=(0.0,) * 64,
        road_ids=("r1", "r2"),
        sources=("RCSD", "SWSD"),
        start_node_ids=("n1", "n2"),
        end_node_ids=("n2", "n3"),
        anchor_features=(),
        teacher_anchor_relations=((), ()),
        oof_anchor_relations=(
            ((1.0, 2.0, 3.0, 4.0), (3.0, 4.0, 5.0, 6.0)),
            ((0.0, 1.0, 0.0, 1.0),),
        ),
        teacher_features=((1.0,) * 40, (2.0,) * 40),
        oof_features=((1.0,) * 40, (2.0,) * 40),
        decision=1,
        target_indices=(0,),
        ownership_targets=(1, 0),
        ownership_task_mask=(True, True),
        business_role_targets=(1, 0),
        business_role_task_mask=(True, True),
        sample_weight=0.7,
        oof_anchor_release_ready=True,
        road_relations=(
            (0, 1, (1.0,) * ORDINARY_SET_ROAD_RELATION_DIM),
        ),
    )
    batch = collate_ordinary_set_pretraining_batch((example,))
    assert batch.decision_task_mask.tolist() == [[True, False]]
    assert batch.side_road_values[0, 0, 0, :32].tolist() == [1.0] * 32
    assert batch.side_road_values[0, 0, 0, 32:].tolist() == [0.0] * 8
    assert batch.road_member_targets[0, 0].tolist() == [True, False]
    assert batch.side_road_relation_values[0, 0, 0, 1].sum().item() > 0
    assert batch.side_precomputed_anchor_context is not None
    assert batch.side_precomputed_anchor_context[0, 0, 0].tolist() == [
        2.0,
        3.0,
        4.0,
        5.0,
        3.0,
        4.0,
        5.0,
        6.0,
    ]
    assert batch.side_precomputed_anchor_context[0, 0, 1].tolist() == [
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        1.0,
    ]
    assert batch.road_ownership_targets is not None
    assert batch.road_ownership_targets[0, 0].tolist() == [1, 0]
    assert batch.road_business_role_targets is not None
    assert batch.road_business_role_targets[0, 0].tolist() == [1, 0]


def test_business_boundary_stop_gradient_keeps_stage_heads_trainable() -> None:
    hidden_dim = 16
    base = _GradientBase(hidden_dim)
    model = TargetAEndToEndOrdinarySetNetwork(
        base,
        TargetAEndToEndOrdinarySetConfig(
            hidden_dim=hidden_dim,
            road_hidden_dim=8,
            access_hidden_dim=8,
            road_set_layers=1,
            road_set_heads=2,
            max_road_cardinality=4,
            dropout=0.0,
            stop_gradient_at_business_boundaries=True,
        ),
    )
    outputs = model(_batch_tensors(), _ordinary_set_batch())
    loss = (
        outputs["ordinary_side_decision_logits"].sum()
        + outputs["advance_right_conditional_plan_logits"].sum()
    )
    loss.backward()
    assert base.embedding.grad is None
    assert model.decision_head[-1].weight.grad is not None
    assert model.advance_residual_head[-1].weight.grad is not None


def test_same_forward_anchor_selection_conditions_each_road() -> None:
    relations = torch.zeros((1, 2, 2, 1, 2, 4))
    relations[0, 0, 0, 0, 1] = 1.0
    batch = replace(
        _ordinary_set_batch(),
        side_required_anchor_indices=torch.zeros(
            (1, 2, 1),
            dtype=torch.long,
        ),
        side_anchor_candidate_relation_values=relations,
        side_anchor_candidate_mask=torch.ones(
            (1, 2, 1, 2),
            dtype=torch.bool,
        ),
    )
    context = (
        TargetAEndToEndOrdinarySetNetwork
        ._same_forward_road_anchor_context(
            batch,
            anchor_outputs={
                "anchor_selected_candidate_indices": torch.tensor([[1]]),
                "anchor_selection_success": torch.tensor([[True]]),
            },
        )
    )
    assert context.shape == (1, 2, 2, 8)
    assert context[0, 0, 0].tolist() == [1.0] * 8
    assert context[0, 0, 1].tolist() == [0.0] * 8


class _FakeBase(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim

    def forward(
        self,
        batch: TargetABatchTensors,
        **_: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        success_index = ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        status = torch.full((1, 2, len(ANCHOR_STATUS_INDEX)), -8.0)
        status[..., success_index] = 8.0
        return {
            "locked_ordinary_embeddings": torch.full(
                (1, 2, self.hidden_dim),
                99.0,
            ),
            "object_embeddings": torch.zeros((1, 1, self.hidden_dim)),
            "anchor_status_logits": status,
            "advance_right_conditional_plan_logits": torch.tensor(
                [[[0.5, 0.25]]]
            ),
        }


class _GradientBase(_FakeBase):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__(hidden_dim)
        self.embedding = nn.Parameter(torch.ones(hidden_dim))

    def forward(
        self,
        batch: TargetABatchTensors,
        **_: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        outputs = super().forward(batch)
        outputs["object_embeddings"] = self.embedding.view(
            1,
            1,
            -1,
        )
        outputs["advance_right_conditional_plan_logits"] = (
            self.embedding[0].expand(1, 1, 2)
        )
        return outputs


def _batch_tensors() -> TargetABatchTensors:
    plan_features = torch.zeros((1, 1, 2, TARGET_A_FEATURE_DIM))
    plan_features[0, 0, 0, 60] = 1.0
    plan_features[0, 0, 1, 61] = 1.0
    return TargetABatchTensors(
        object_features=torch.zeros((1, 1, TARGET_A_FEATURE_DIM)),
        object_types=torch.zeros((1, 1), dtype=torch.long),
        object_mask=torch.ones((1, 1), dtype=torch.bool),
        adjacency=torch.ones((1, 1, 1), dtype=torch.bool),
        anchor_object_indices=torch.zeros((1, 2), dtype=torch.long),
        anchor_candidate_features=torch.zeros(
            (1, 2, 1, TARGET_A_FEATURE_DIM)
        ),
        anchor_candidate_mask=torch.ones((1, 2, 1), dtype=torch.bool),
        ordinary_object_indices=torch.zeros((1, 2), dtype=torch.long),
        ordinary_required_anchor_indices=torch.tensor([[[0], [1]]]),
        ordinary_plan_features=torch.zeros(
            (1, 2, 1, TARGET_A_FEATURE_DIM)
        ),
        ordinary_plan_mask=torch.ones((1, 2, 1), dtype=torch.bool),
        advance_right_object_indices=torch.zeros((1, 1), dtype=torch.long),
        advance_right_source_indices=torch.tensor([[0]]),
        advance_right_target_indices=torch.tensor([[1]]),
        advance_right_plan_features=plan_features,
        advance_right_plan_mask=torch.ones((1, 1, 2), dtype=torch.bool),
    )


def _ordinary_set_batch() -> EndToEndOrdinarySetBatch:
    return EndToEndOrdinarySetBatch(
        case_keys=("T10:case",),
        advance_right_ids=("ar1",),
        side_segment_ids=(("s1", "s2"),),
        side_group_indices=torch.tensor([[0, 1]]),
        side_object_values=torch.zeros((1, 2, 64)),
        side_road_values=torch.zeros((1, 2, 2, 40)),
        side_road_mask=torch.ones((1, 2, 2), dtype=torch.bool),
        side_road_source_indices=torch.ones((1, 2, 2), dtype=torch.long),
        side_road_relation_values=torch.zeros(
            (1, 2, 2, 2, ORDINARY_SET_ROAD_RELATION_DIM)
        ),
        side_access_values=torch.zeros((1, 2, 1, 64)),
        side_access_mask=torch.ones((1, 2, 1), dtype=torch.bool),
        decision_targets=torch.ones((1, 2), dtype=torch.long),
        decision_task_mask=torch.ones((1, 2), dtype=torch.bool),
        road_member_targets=torch.tensor(
            [[[[True, False], [True, False]]]]
        ).reshape(1, 2, 2),
        road_task_mask=torch.ones((1, 2), dtype=torch.bool),
        road_cardinality_targets=torch.ones((1, 2), dtype=torch.long),
        access_targets=torch.ones((1, 2, 1), dtype=torch.bool),
        access_task_mask=torch.ones((1, 2), dtype=torch.bool),
        sample_weights=torch.ones((1, 2)),
        candidate_reachable=torch.ones((1, 2), dtype=torch.bool),
        road_ids=((("r1", "r2"), ("r3", "r4")),),
        access_road_ids=((("r1",), ("r3",)),),
        road_ownership_targets=torch.tensor(
            [[[1, 0], [1, 0]]],
            dtype=torch.long,
        ),
        road_ownership_task_mask=torch.ones(
            (1, 2, 2),
            dtype=torch.bool,
        ),
        road_business_role_targets=torch.tensor(
            [[[1, 0], [1, 0]]],
            dtype=torch.long,
        ),
        road_business_role_task_mask=torch.ones(
            (1, 2, 2),
            dtype=torch.bool,
        ),
        road_ownership_sample_weights=torch.ones((1, 2)),
        road_business_role_sample_weights=torch.ones((1, 2)),
    )
