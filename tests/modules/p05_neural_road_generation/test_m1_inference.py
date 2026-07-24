from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_dataset import OPERATION_NAMES
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_inference import _decode_child, _generated_id
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_models import M1EvaluationConfig


def test_evaluation_config_guards_fixed_test_and_model_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="model_run_root"):
        M1EvaluationConfig(tmp_path, tmp_path, "run", "validation")
    with pytest.raises(ValueError, match="allow_fixed_test"):
        M1EvaluationConfig(tmp_path, tmp_path, "run", "test", prediction_mode="keep_all")


def test_child_decode_and_ids_are_deterministic() -> None:
    parent = LineString([(100.0, 200.0), (110.0, 200.0)])
    normalized = np.asarray([[-0.5, 0.0], [0.0, 0.1], [0.5, 0.0]], dtype=np.float32)
    child = _decode_child(parent, normalized)
    assert child.length > 10.0
    assert _generated_id("p05r", "sample", "road", 0) == _generated_id("p05r", "sample", "road", 0)
    assert _generated_id("p05r", "sample", "road", 0) != _generated_id("p05r", "sample", "road", 1)


def test_operation_contract_and_invalid_split_are_hard_failures() -> None:
    assert OPERATION_NAMES == ("DROP", "KEEP", "SPLIT_1", "SPLIT_2", "SPLIT_3")
    parent = LineString([(0.0, 0.0), (1.0, 0.0)])
    with pytest.raises(ValueError, match="zero-length"):
        _decode_child(parent, np.zeros((16, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="finite"):
        _decode_child(parent, np.full((16, 2), np.nan, dtype=np.float32))
