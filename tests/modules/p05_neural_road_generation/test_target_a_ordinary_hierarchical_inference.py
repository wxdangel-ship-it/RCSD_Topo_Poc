from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_hierarchical_inference import (
    hierarchical_access_consistent,
)


def test_access_must_belong_to_complete_carrier() -> None:
    assert hierarchical_access_consistent(["r1", "r2"], ["r2"])
    assert not hierarchical_access_consistent(["r1"], ["r2"])
    assert not hierarchical_access_consistent([], [])
