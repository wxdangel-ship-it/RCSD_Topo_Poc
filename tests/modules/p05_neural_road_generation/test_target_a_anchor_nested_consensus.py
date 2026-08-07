from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_nested_consensus import (
    _consensus_rows,
    _thresholds_from_inner_calibration,
)


def _row(
    *,
    sample_id: str,
    candidate_id: str,
    score: float,
    safe: bool,
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "case_key": "T10:1",
        "anchor_id": f"anchor-{sample_id}",
        "fold": 0,
        "outer_fold": 0,
        "inner_validation_fold": 1,
        "label": "SUCCESS" if safe else "ABSTAIN",
        "predicted": "SUCCESS",
        "candidate_supervised": safe,
        "candidate_predicted_index": 0,
        "candidate_predicted_id": candidate_id,
        "candidate_acceptable_ids": [candidate_id] if safe else [],
        "candidate_type": "NODE",
        "candidate_confidence_score": score,
    }


def test_strict_nested_threshold_uses_inner_consensus_only() -> None:
    seed_one = [
        _row(sample_id="safe", candidate_id="NODE:1", score=0.8, safe=True),
        _row(sample_id="unsafe", candidate_id="NODE:2", score=0.7, safe=False),
    ]
    seed_two = [
        _row(sample_id="safe", candidate_id="NODE:1", score=0.9, safe=True),
        _row(sample_id="unsafe", candidate_id="NODE:2", score=0.75, safe=False),
    ]
    rows = _consensus_rows([seed_one, seed_two])
    thresholds = _thresholds_from_inner_calibration(rows)
    assert thresholds == {"NODE": 0.7}


def test_strict_nested_consensus_requires_same_candidate_object() -> None:
    first = [_row(sample_id="x", candidate_id="NODE:1", score=0.9, safe=True)]
    second = [_row(sample_id="x", candidate_id="NODE:2", score=0.9, safe=True)]
    second[0]["candidate_acceptable_ids"] = ["NODE:1"]
    [row] = _consensus_rows([first, second])
    assert not row["candidate_agreement"]
    assert not row["consensus_raw_success"]
