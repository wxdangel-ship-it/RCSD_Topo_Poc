from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_consensus import (
    _apply_fold_excluded_consensus_gate,
    _build_consensus_rows,
)


def _seed_row(
    *,
    sample_id: str,
    fold: int,
    predicted: str,
    candidate_index: int,
    score: float,
    acceptable: tuple[int, ...],
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "case_key": f"T10:case-{fold}",
        "fold": fold,
        "label": "SUCCESS",
        "label_index": 0,
        "candidate_supervised": True,
        "candidate_acceptable_indices": list(acceptable),
        "predicted": predicted,
        "candidate_predicted_index": candidate_index,
        "candidate_type": "NODE",
        "candidate_confidence_score": score,
    }


def test_consensus_requires_success_and_identical_candidate() -> None:
    groups = [
        [
            _seed_row(
                sample_id="agree",
                fold=0,
                predicted="SUCCESS",
                candidate_index=1,
                score=0.9,
                acceptable=(1,),
            ),
            _seed_row(
                sample_id="disagree",
                fold=1,
                predicted="SUCCESS",
                candidate_index=index,
                score=0.8,
                acceptable=(1,),
            ),
        ]
        for index in (1, 2, 1)
    ]

    rows = {row["sample_id"]: row for row in _build_consensus_rows(groups)}

    assert rows["agree"]["consensus_raw_success"] is True
    assert rows["agree"]["consensus_proven_safe_anchor"] is True
    assert rows["agree"]["consensus_confidence_score"] == 0.9
    assert rows["disagree"]["candidate_agreement"] is False
    assert rows["disagree"]["consensus_raw_success"] is False


def test_consensus_gate_calibrates_only_on_other_folds() -> None:
    rows = [
        {
            "sample_id": "safe-0",
            "fold": 0,
            "consensus_candidate_type": "NODE",
            "consensus_raw_success": True,
            "consensus_confidence_score": 0.90,
            "consensus_proven_safe_anchor": True,
            "consensus_raw_unsafe_success": False,
        },
        {
            "sample_id": "unsafe-0",
            "fold": 0,
            "consensus_candidate_type": "NODE",
            "consensus_raw_success": True,
            "consensus_confidence_score": 0.72,
            "consensus_proven_safe_anchor": False,
            "consensus_raw_unsafe_success": True,
        },
        {
            "sample_id": "safe-1",
            "fold": 1,
            "consensus_candidate_type": "NODE",
            "consensus_raw_success": True,
            "consensus_confidence_score": 0.85,
            "consensus_proven_safe_anchor": True,
            "consensus_raw_unsafe_success": False,
        },
        {
            "sample_id": "unsafe-1",
            "fold": 1,
            "consensus_candidate_type": "NODE",
            "consensus_raw_success": True,
            "consensus_confidence_score": 0.70,
            "consensus_proven_safe_anchor": False,
            "consensus_raw_unsafe_success": True,
        },
    ]

    gated, thresholds = _apply_fold_excluded_consensus_gate(rows)

    assert thresholds["0"]["NODE"] == 0.70
    assert thresholds["1"]["NODE"] == 0.72
    by_id = {row["sample_id"]: row for row in gated}
    assert by_id["safe-0"]["consensus_safety_accepted"] is True
    assert by_id["unsafe-0"]["consensus_safety_accepted"] is True
    assert by_id["safe-1"]["consensus_safety_accepted"] is True
    assert by_id["unsafe-1"]["consensus_safety_accepted"] is False
