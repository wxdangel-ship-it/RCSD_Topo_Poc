from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_inference import _decode_operations


def _geometry(valid: bool) -> np.ndarray:
    value = np.zeros((1, 3, 16, 2), dtype=np.float32)
    if not valid:
        value[0, 0, 0, 0] = np.nan
    return value


def test_generic_constraint_replaces_illegal_free_action_without_content_repair() -> None:
    logits = np.asarray([[0.0, 1.0, 5.0, 0.5, 0.2]], dtype=np.float32)
    parent = [LineString([(0.0, 0.0), (10.0, 0.0)])]
    free, constrained, interventions, free_legal = _decode_operations(
        logits, parent, np.asarray([[0.5, 0.0]], dtype=np.float32), _geometry(valid=False))
    assert free.tolist() == [2]
    assert constrained.tolist() == [1]
    assert free_legal.tolist() == [False]
    assert interventions[0]["constraint_code"] == "CHILD_GEOMETRY_INVALID"
    assert interventions[0]["content_repair"] is False


def test_valid_free_action_is_not_changed() -> None:
    logits = np.asarray([[0.0, 5.0, 1.0, 0.5, 0.2]], dtype=np.float32)
    parent = [LineString([(0.0, 0.0), (10.0, 0.0)])]
    free, constrained, interventions, free_legal = _decode_operations(
        logits, parent, np.asarray([[0.5, 0.0]], dtype=np.float32), _geometry(valid=True))
    assert free.tolist() == constrained.tolist() == [1]
    assert free_legal.tolist() == [True]
    assert interventions == []
