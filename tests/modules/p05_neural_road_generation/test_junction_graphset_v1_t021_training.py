from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t021_training import (
    pack_record_indices,
)


def test_dynamic_batch_packing_respects_record_and_token_budgets() -> None:
    batches = pack_record_indices(
        (4, 5, 6, 3, 2),
        maximum_records=2,
        maximum_tokens=10,
    )

    assert batches == ((0, 1), (2, 3), (4,))


def test_oversized_junction_is_kept_as_one_atomic_forward() -> None:
    batches = pack_record_indices(
        (20, 2, 3),
        maximum_records=4,
        maximum_tokens=10,
    )

    assert batches == ((0,), (1, 2))


def test_batch_packing_rejects_negative_counts_and_invalid_budgets() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        pack_record_indices((-1,), maximum_records=1, maximum_tokens=1)
    with pytest.raises(ValueError, match="positive"):
        pack_record_indices((1,), maximum_records=0, maximum_tokens=1)
