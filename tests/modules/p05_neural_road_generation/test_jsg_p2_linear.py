import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_linear import (
    fit_additive_linear_model,
    fit_oof_additive_models,
)


def _rows():
    return [
        {"case_key": "a", "fold": 0, "feature_tokens": ["heldout"], "truth_equivalent": True, "sample_weight": 1.0},
        {"case_key": "b", "fold": 1, "feature_tokens": ["good"], "truth_equivalent": True, "sample_weight": 1.0},
        {"case_key": "b", "fold": 1, "feature_tokens": ["bad"], "truth_equivalent": False, "sample_weight": 1.0},
        {"case_key": "c", "fold": 2, "feature_tokens": ["good"], "truth_equivalent": True, "sample_weight": 1.0},
        {"case_key": "c", "fold": 2, "feature_tokens": ["bad"], "truth_equivalent": False, "sample_weight": 1.0},
    ]


def test_linear_fit_excludes_held_out_tokens_and_is_explainable() -> None:
    model = fit_additive_linear_model(
        _rows(),
        held_out_fold=0,
        smoothing=1.0,
        dataset_manifest_sha256="dataset",
        all_case_folds={"a": 0, "b": 1, "c": 2},
    )
    assert "heldout" not in model.feature_weights
    assert model.score(["good"]) > model.score(["bad"])
    assert model.held_out_case_keys == ("a",)
    assert not set(model.train_case_keys) & set(model.held_out_case_keys)


def test_linear_fit_rejects_missing_train_case() -> None:
    with pytest.raises(ValueError, match="training Case scope"):
        fit_additive_linear_model(
            _rows()[:-2],
            held_out_fold=0,
            smoothing=1.0,
            dataset_manifest_sha256="dataset",
            all_case_folds={"a": 0, "b": 1, "c": 2},
        )


def test_optimized_oof_fit_does_not_leak_heldout_only_vocabulary() -> None:
    models = fit_oof_additive_models(
        _rows(),
        fold_count=3,
        smoothing=1.0,
        dataset_manifest_sha256="dataset",
        all_case_folds={"a": 0, "b": 1, "c": 2},
    )

    assert "heldout" not in models[0].feature_weights
    assert models[0].score(["heldout"]) == models[0].bias
