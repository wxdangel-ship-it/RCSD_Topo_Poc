from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_object_decoder import (
    PointerSetHead,
    PointerSetOutput,
    RoadBreakSetHead,
    decode_pointer_set,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


ROADS = tuple(ObjectRef(EvidenceRole.RCSD_ROAD, f"R{index}") for index in range(4))


def test_pointer_set_head_predicts_dynamic_discrete_count_and_object_logits() -> None:
    torch.manual_seed(211)
    head = PointerSetHead(16)
    query = torch.randn(2, 16, requires_grad=True)
    objects = torch.randn(4, 16, requires_grad=True)
    batches = torch.tensor((0, 0, 0, 1), dtype=torch.long)
    output = head(
        query_embeddings=query,
        object_embeddings=objects,
        object_batch_indices=batches,
        object_refs=ROADS,
        roles=frozenset({EvidenceRole.RCSD_ROAD}),
    )

    assert output.object_refs == ROADS
    assert tuple(output.logits.shape) == (4,)
    assert tuple(output.cardinality_logits.shape) == (2, 4)
    assert output.cardinality_valid_mask.tolist() == [
        [True, True, True, True],
        [True, True, False, False],
    ]
    assert tuple(output.predicted_cardinality.shape) == (2,)
    assert output.predicted_cardinality.dtype == torch.long
    assert int(output.predicted_cardinality[0]) <= 3
    assert int(output.predicted_cardinality[1]) <= 1
    (
        output.logits.sum()
        + output.cardinality_logits[output.cardinality_valid_mask].sum()
    ).backward()
    assert query.grad is not None
    assert objects.grad is not None


def test_pointer_set_decode_uses_predicted_count_then_top_k() -> None:
    output = PointerSetOutput(
        object_refs=ROADS,
        object_batch_indices=torch.tensor((0, 0, 0, 1), dtype=torch.long),
        logits=torch.tensor((0.1, 2.0, 1.0, 9.0)),
        cardinality_logits=torch.tensor(
            (
                (0.0, 1.0, 5.0, 0.5),
                (0.0, 4.0, -torch.inf, -torch.inf),
            )
        ),
        cardinality_valid_mask=torch.tensor(
            (
                (True, True, True, True),
                (True, True, False, False),
            )
        ),
    )

    assert decode_pointer_set(output, batch_index=0) == (ROADS[1], ROADS[2])
    assert decode_pointer_set(output, batch_index=1) == (ROADS[3],)


def test_pointer_set_count_support_masks_classes_above_local_candidates() -> None:
    head = PointerSetHead(8)
    output = head(
        query_embeddings=torch.zeros((2, 8)),
        object_embeddings=torch.zeros((1, 8)),
        object_batch_indices=torch.tensor((0,), dtype=torch.long),
        object_refs=(ROADS[0],),
        roles=frozenset({EvidenceRole.RCSD_ROAD}),
    )

    assert output.cardinality_valid_mask.tolist() == [
        [True, True],
        [True, False],
    ]
    assert int(output.predicted_cardinality[1]) == 0


def test_road_break_set_head_outputs_count_overflow_and_ordered_locations() -> None:
    torch.manual_seed(223)
    head = RoadBreakSetHead(16, max_break_points=4)
    query = torch.randn(1, 16, requires_grad=True)
    objects = torch.randn(4, 16, requires_grad=True)
    batches = torch.zeros((4,), dtype=torch.long)
    output = head(
        query_embeddings=query,
        object_embeddings=objects,
        object_batch_indices=batches,
        object_refs=ROADS,
    )

    assert tuple(output.count_logits.shape) == (4, 6)
    assert output.overflow_class_index == 5
    assert tuple(output.fraction_slots.shape) == (4, 4)
    assert torch.all(output.fraction_slots > 0.0)
    assert torch.all(output.fraction_slots < 1.0)
    assert torch.all(output.fraction_slots[:, 1:] > output.fraction_slots[:, :-1])
    assert tuple(output.presence_logits.shape) == (4,)
    assert tuple(output.fractions.shape) == (4,)
    (output.count_logits.sum() + output.fraction_slots.sum()).backward()
    assert query.grad is not None
    assert objects.grad is not None
