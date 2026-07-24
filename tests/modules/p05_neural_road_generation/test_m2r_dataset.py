from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_dataset import BASE_INPUT_ROLE_NAMES, _relation_target
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_models import M2RDatasetConfig


def test_dataset_config_rejects_invalid_geometry_and_folds(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        M2RDatasetConfig(tmp_path, tmp_path, "run", image_size=50)
    with pytest.raises(ValueError):
        M2RDatasetConfig(tmp_path, tmp_path, "run", folds=(0, 0))
    with pytest.raises(ValueError):
        M2RDatasetConfig(tmp_path, tmp_path, "run", polyline_points=3)


def test_base_input_roles_exclude_upstream_targets() -> None:
    assert "t03_nodes" not in BASE_INPUT_ROLE_NAMES
    assert "t04_nodes" not in BASE_INPUT_ROLE_NAMES
    assert "t05_rcsdroad_out" not in BASE_INPUT_ROLE_NAMES
    assert "t06_frcsd_road" not in BASE_INPUT_ROLE_NAMES
    assert {"t01_roads", "raw_rcsdroad", "raw_rcsdnode"}.issubset(BASE_INPUT_ROLE_NAMES)


def test_relation_target_keeps_t03_and_t04_class_spaces_separate() -> None:
    assert _relation_target(
        {"target_kind": "relation", "task_name": "T03", "relation_evidence": {"label": {"class_index": 2}}},
        "T03",
    ) == 2
    assert _relation_target(
        {"target_kind": "relation", "task_name": "T04", "relation_evidence": {"label": {"class_index": 1}}},
        "T04",
    ) == 1
    with pytest.raises(ValueError):
        _relation_target(
            {"target_kind": "relation", "task_name": "T04", "relation_evidence": {"label": {"class_index": 2}}},
            "T04",
        )
