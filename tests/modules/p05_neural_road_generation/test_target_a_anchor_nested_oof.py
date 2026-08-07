from __future__ import annotations

from types import SimpleNamespace

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_nested_oof import (
    _inner_fold_for_outer,
    _strict_nested_split,
)


def test_strict_nested_inner_fold_never_equals_outer_fold() -> None:
    folds = [0, 1, 2, 3, 4]
    assert [_inner_fold_for_outer(folds, fold) for fold in folds] == [
        1,
        2,
        3,
        4,
        0,
    ]


def test_strict_nested_split_keeps_outer_labels_out_of_all_fits() -> None:
    examples = [
        SimpleNamespace(sample_id=f"sample-{fold}", fold=fold)
        for fold in range(5)
    ]
    inner_train, inner_validation, outer_train, outer_validation = (
        _strict_nested_split(
            examples,
            outer_fold=2,
            inner_fold=3,
        )
    )
    assert {row.fold for row in inner_train} == {0, 1, 4}
    assert {row.fold for row in inner_validation} == {3}
    assert {row.fold for row in outer_train} == {0, 1, 3, 4}
    assert {row.fold for row in outer_validation} == {2}
