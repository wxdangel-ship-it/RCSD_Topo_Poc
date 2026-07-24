from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_training import (
    P3GroupExample,
    build_fold_vocabulary,
    select_inner_validation_cases,
)


def _group(case_key: str, fold: int, token: str) -> P3GroupExample:
    return P3GroupExample(
        case_key=case_key,
        fold=fold,
        domain="JSG",
        group_id=f"group:{case_key}",
        object_type="JUNCTION",
        candidate_ids=("a", "b"),
        candidate_tokens=((token, "payload:state=REVIEW"), ("shared",)),
        feature_signatures=("fa", "fb"),
        context_tokens=(f"ctx:{token}",),
        context_signature="context",
        truth_index=0,
        sample_weight=0.7,
    )


def test_inner_validation_never_overlaps_outer_heldout() -> None:
    folds = {f"case-{index}": index % 3 for index in range(9)}
    train, inner, held = select_inner_validation_cases(
        folds, held_out_fold=1, seed=17, ratio=0.2
    )
    assert not set(train) & set(inner)
    assert not (set(train) | set(inner)) & set(held)
    assert set(train) | set(inner) | set(held) == set(folds)


def test_vocabulary_does_not_include_inner_or_heldout_only_tokens() -> None:
    groups = [_group("train", 0, "train-only"), _group("inner", 1, "inner-only"), _group("held", 2, "held-only")]
    vocabulary = build_fold_vocabulary(
        groups,
        train_case_keys=("train",),
        inner_validation_case_keys=("inner",),
        held_out_case_keys=("held",),
        dataset_manifest_sha256="dataset",
    )
    assert "train-only" in vocabulary.candidate_tokens
    assert "inner-only" not in vocabulary.candidate_tokens
    assert "held-only" not in vocabulary.candidate_tokens
