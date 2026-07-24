from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    JSGP2DatasetConfig,
    JSGP2OOFConfig,
    P2LinearModel,
)


def test_p2_configs_reject_empty_run_id() -> None:
    with pytest.raises(ValueError, match="run_id"):
        JSGP2DatasetConfig(Path("c"), Path("o"), Path("m"), Path("out"), "")
    with pytest.raises(ValueError, match="run_id"):
        JSGP2OOFConfig(
            Path("d"), Path("c"), Path("o"), Path("p0"), Path("r2"), Path("out"), ""
        )


def test_linear_model_score_and_signature_are_stable() -> None:
    model = P2LinearModel(
        held_out_fold=0,
        bias=-1.0,
        feature_weights={"a": 2.0, "b": -1.0},
        smoothing=1.0,
        train_case_keys=("case-b",),
        held_out_case_keys=("case-a",),
        train_weighted_positive=1.0,
        train_weighted_negative=2.0,
        dataset_manifest_sha256="abc",
    )
    assert model.score(["b", "a", "a"]) == -0.5
    assert model.model_signature == model.model_signature
    assert model.to_dict()["held_out_fold"] == 0
