from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import (
    R2DatasetConfig,
    R2OOFConfig,
)


def test_r2_dataset_and_oof_configs_validate_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        R2DatasetConfig(oracle_run_root=tmp_path, output_root=tmp_path, run_id="")
    with pytest.raises(ValueError, match="run_id"):
        R2OOFConfig(dataset_run_root=tmp_path, output_root=tmp_path, run_id="")


def test_r2_oof_config_requires_all_five_folds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="folds"):
        R2OOFConfig(
            dataset_run_root=tmp_path,
            output_root=tmp_path,
            run_id="run",
            folds=(0, 1),
        )
