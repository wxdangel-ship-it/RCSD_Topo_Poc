from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_unique_junction import (
    audit_unique_junction_contract,
    evaluate_unique_junction_predictions,
    unique_junction_promotion_decision,
)


def _example(
    sample_id: str,
    status: AnchorStatus,
    *,
    supervised: bool = True,
    weight: float = 1.0,
) -> AnchorPretrainExample:
    success = status is AnchorStatus.SUCCESS
    return AnchorPretrainExample(
        sample_id=sample_id,
        case_key=f"T10:{sample_id.split(':')[0]}",
        anchor_id=sample_id,
        fold=0,
        object_features=(0.0,) * TARGET_A_FEATURE_DIM,
        candidate_ids=("NODE:1",),
        candidate_features=((0.0,) * TARGET_A_FEATURE_DIM,),
        status_label=list(AnchorStatus).index(status),
        candidate_acceptable_indices=(0,) if success else (),
        preferred_candidate_index=0 if success else -1,
        candidate_supervised=success,
        sample_weight=weight,
        input_hashes=(),
        label_reason="TEST",
        dependency_anchor_ids=(sample_id,),
        status_supervised=supervised,
    )


def _prediction(
    example: AnchorPretrainExample,
    predicted: AnchorStatus,
) -> dict[str, object]:
    return {
        "sample_id": example.sample_id,
        "predicted_index": list(AnchorStatus).index(predicted),
        "candidate_acceptable_exact": (
            predicted is AnchorStatus.SUCCESS
            and example.status_label
            == list(AnchorStatus).index(AnchorStatus.SUCCESS)
        ),
    }


def test_unique_junction_contract_has_one_group_per_key() -> None:
    examples = (
        _example("case:a", AnchorStatus.SUCCESS),
        _example("case:b", AnchorStatus.NO_EVIDENCE),
    )
    result = audit_unique_junction_contract(examples)
    assert result["passed"] is True
    assert result["unique_key_count"] == 2
    assert result["dependency_group_count"] == 2
    assert result["occurrence_forward_count"] == 0


def test_business_exact_requires_success_object_and_counts_unknown() -> None:
    success = _example("case:a", AnchorStatus.SUCCESS)
    no_evidence = _example("case:b", AnchorStatus.NO_EVIDENCE)
    unknown = _example(
        "case:c",
        AnchorStatus.ABSTAIN,
        supervised=False,
        weight=0.7,
    )
    result = evaluate_unique_junction_predictions(
        (
            _prediction(success, AnchorStatus.SUCCESS),
            _prediction(no_evidence, AnchorStatus.ABSTAIN),
            _prediction(unknown, AnchorStatus.SUCCESS),
        ),
        (success, no_evidence, unknown),
    )
    assert result["business_exact"] == {
        "correct": 1,
        "count": 2,
        "rate": 0.5,
    }
    assert result["unknown_automatic_count"] == 1
    assert result["no_evidence_exact"]["correct"] == 0


def test_promotion_requires_both_exact_improvements_and_safety() -> None:
    baseline = {
        "business_exact": {"rate": 0.7},
        "gold": {"business_exact": {"rate": 0.8}},
        "success_object_exact": {"rate": 0.7},
        "no_evidence_exact": {"rate": 0.6},
        "dangerous_automatic_count": 2,
        "unknown_automatic_count": 5,
        "duplicate_prediction_count": 0,
    }
    candidate = {
        "business_exact": {"rate": 0.71},
        "gold": {"business_exact": {"rate": 0.81}},
        "success_object_exact": {"rate": 0.7},
        "no_evidence_exact": {"rate": 0.6},
        "dangerous_automatic_count": 2,
        "unknown_automatic_count": 5,
        "duplicate_prediction_count": 0,
    }
    assert unique_junction_promotion_decision(
        baseline, candidate
    )["decision"] == "UNIQUE_JUNCTION_CANARY_PROMOTE"
    candidate["unknown_automatic_count"] = 6
    assert unique_junction_promotion_decision(
        baseline, candidate
    )["decision"] == "UNIQUE_JUNCTION_CANARY_NO_GO"
