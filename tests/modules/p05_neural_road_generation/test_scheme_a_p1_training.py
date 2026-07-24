from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
    build_fold_vocabulary,
    encode_groups,
    select_inner_validation_cases,
    select_thresholds,
)


def _group(case_key: str, fold: int, target: str = "USE_RCSD") -> P1GroupExample:
    candidates = (
        P1CandidateExample("a", "USE_RCSD", ("SOURCE:PROPOSAL",), (1.0,) * 8),
        P1CandidateExample("b", "REVIEW_FALLBACK", ("SOURCE:FALLBACK",), (0.0,) * 8),
    )
    truth_index = 0 if target == "USE_RCSD" else 1
    return P1GroupExample(
        case_key=case_key,
        fold=fold,
        group_id=f"g:{case_key}",
        object_type="SEGMENT",
        object_id="join-only-id",
        object_tokens=("OBJECT:SEGMENT",),
        context_tokens=("DEGREE:2",),
        candidates=candidates,
        truth_index=truth_index,
        truth_target=target,
        anomaly_target=target == "REVIEW_FALLBACK",
        sample_weight=1.0,
        hard_unsafe=False,
    )


def test_scheme_a_p1_split_and_unknown_token() -> None:
    groups = [_group(f"case-{index}", index % 5) for index in range(10)]
    folds = {group.case_key: group.fold for group in groups}
    train, inner, held = select_inner_validation_cases(
        folds, held_out_fold=0, seed=17, ratio=0.2
    )
    assert not (set(train) & set(inner) or set(train) & set(held) or set(inner) & set(held))
    vocabulary = build_fold_vocabulary(
        groups,
        train_case_keys=train,
        inner_validation_case_keys=inner,
        held_out_case_keys=held,
        dataset_manifest_sha256="0" * 64,
    )
    unseen = _group("unseen", 0)
    unseen = P1GroupExample(
        **{**unseen.__dict__, "object_tokens": ("NEVER_SEEN",)}
    )
    encoded = encode_groups([unseen], vocabulary)[0]
    assert encoded.object_token_ids == (0,)


def test_scheme_a_p1_thresholds_are_precision_first() -> None:
    groups = [
        _group("safe-a", 0),
        _group("safe-b", 1),
        _group("unsafe", 2, "REVIEW_FALLBACK"),
    ]
    scores = [[3.0, 0.0], [2.0, 0.0], [1.0, 2.0]]
    probabilities = [[0.95, 0.05], [0.90, 0.10], [0.25, 0.75]]
    thresholds = select_thresholds(groups, scores, probabilities, [0.05, 0.10, 0.95])
    assert thresholds["inner_accepted_precision"] >= 0.95
    assert thresholds["inner_fallback_recall"] >= 0.98


def test_scheme_a_p1_anomaly_threshold_respects_safety_cap() -> None:
    groups = [
        _group("safe-a", 0),
        _group("safe-b", 1),
        _group("unsafe", 2, "REVIEW_FALLBACK"),
    ]
    thresholds = select_thresholds(
        groups,
        [[3.0, 0.0], [2.0, 0.0], [1.0, 2.0]],
        [[0.95, 0.05], [0.90, 0.10], [0.25, 0.75]],
        [0.01, 0.02, 0.90],
        max_anomaly_threshold=0.10,
    )
    assert thresholds["anomaly_threshold"] <= 0.10
