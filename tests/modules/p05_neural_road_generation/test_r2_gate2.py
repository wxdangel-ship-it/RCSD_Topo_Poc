from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.r2_gate2 import (
    CoordinateFrame,
    classification_metrics,
    resample_geometry,
    slot_topology_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2Gate2Config


def test_resample_geometry_uses_input_coordinate_frame() -> None:
    frame = CoordinateFrame(center_x=10.0, center_y=20.0, scale=20.0)
    result = resample_geometry(mapping(LineString([(0, 20), (20, 20)])), frame, points=5)
    assert result.shape == (5, 2)
    assert np.allclose(result[0], [-0.5, 0.0])
    assert np.allclose(result[-1], [0.5, 0.0])


def test_classification_metrics_reports_macro_f1() -> None:
    metrics = classification_metrics(np.asarray([0, 0, 1, 1]), np.asarray([0, 1, 1, 1]), 2)
    assert metrics["accuracy"] == 0.75
    assert metrics["macro_f1"] == pytest.approx((2 / 3 + 0.8) / 2)


def test_gate2_config_rejects_empty_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        R2Gate2Config(oracle_run_root=tmp_path, output_root=tmp_path, run_id="")


def test_slot_topology_metrics_are_id_rename_invariant() -> None:
    truth_endpoint = np.asarray([[0, 1], [1, 2]])
    truth_direction = np.asarray([0, 1])
    exact = slot_topology_metrics(truth_endpoint, truth_direction, truth_endpoint, truth_direction)
    changed = slot_topology_metrics(
        np.asarray([[0, 2], [1, 2]]), truth_direction, truth_endpoint, truth_direction
    )
    assert exact["f1"] == 1.0
    assert changed["f1"] < 1.0
