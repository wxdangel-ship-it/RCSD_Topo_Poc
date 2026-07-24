from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p2_audit import (
    build_object_source_route,
    classify_business_outcome,
    reinterpret_probe_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p2_models import (
    CLUE_MISS_ONLY,
    ROAD_CARRIER_UNSAFE,
    SAFE_AND_VISIBLE,
)


def _row(
    *,
    accepted: bool,
    proposal_correct: bool = True,
    anomaly_target: bool = False,
    review_target: bool = False,
    truth_target: str = "KEEP_SWSD",
) -> dict[str, object]:
    return {
        "probe": "SHALLOW_MLP",
        "fold": 0,
        "accepted": accepted,
        "proposal_correct": proposal_correct,
        "anomaly_target": anomaly_target,
        "review_target": review_target,
        "truth_target": truth_target,
    }


def test_correct_keep_with_missed_anomaly_is_clue_only_not_carrier_error() -> None:
    row = _row(accepted=True, anomaly_target=True)

    assert classify_business_outcome(row) == CLUE_MISS_ONLY


def test_wrong_candidate_is_carrier_unsafe_even_when_anomaly_is_true() -> None:
    row = _row(accepted=True, proposal_correct=False, anomaly_target=True)

    assert classify_business_outcome(row) == ROAD_CARRIER_UNSAFE


def test_safe_visible_object_stays_separate() -> None:
    assert classify_business_outcome(_row(accepted=True)) == SAFE_AND_VISIBLE


def test_metric_reinterpretation_separates_carrier_safety_and_clue_visibility() -> None:
    rows = [
        _row(accepted=False, proposal_correct=False, anomaly_target=True),
        _row(accepted=True, anomaly_target=True),
        _row(accepted=True, truth_target="USE_RCSD"),
        _row(accepted=False, review_target=True),
    ]
    metrics = reinterpret_probe_metrics(
        rows,
        expected_fold_count=1,
        minimum_safe_coverage=0.50,
        minimum_use_rcsd_safe_coverage=0.50,
    )[0]["overall_metrics"]

    assert metrics["carrier_wrong_accepted_count"] == 0
    assert metrics["carrier_safety_recall"] == 1.0
    assert metrics["clue_miss_only_count"] == 1
    assert metrics["clue_recall"] == 0.5
    assert metrics["gate_pass"] is True


def test_empty_carrier_unsafe_denominator_is_vacuously_safe() -> None:
    metrics = reinterpret_probe_metrics(
        [_row(accepted=True, truth_target="USE_RCSD")],
        expected_fold_count=1,
        minimum_safe_coverage=0.50,
        minimum_use_rcsd_safe_coverage=0.50,
    )[0]["overall_metrics"]

    assert metrics["carrier_unsafe_count"] == 0
    assert metrics["carrier_safety_recall"] == 1.0


def test_missing_use_candidate_routes_to_safe_keep_and_separate_clue_head() -> None:
    attribution = {
        **_row(accepted=True, anomaly_target=True),
        "case_key": "T10:1",
        "group_id": "group",
        "object_id": "segment",
        "population": "RESIDUAL_UNSAFE_ACCEPTED",
        "proposal_target": "KEEP_SWSD",
        "truth_target": "KEEP_SWSD",
        "direct_cause_code": "T06_RCSD_CARRIER_ROAD_MISSING",
        "lineage": [],
    }

    route = build_object_source_route(
        attribution, ["KEEP_SWSD", "REVIEW_FALLBACK"]
    )

    assert route["candidate_truth_reachable"] is True
    assert route["source_route"] == "CANDIDATE_ABSENCE_SAFE_KEEP_PLUS_CLUE_HEAD"
    assert route["label_only_promoted_to_inference"] is False


def test_mixed_carrier_truth_is_reachable_without_using_t06_as_inference() -> None:
    attribution = {
        **_row(accepted=True, proposal_correct=False),
        "case_key": "T10-Error-2:1",
        "group_id": "group",
        "object_id": "segment",
        "population": "AGREED_WRONG",
        "proposal_target": "KEEP_SWSD",
        "truth_target": "MIXED_CARRIER",
        "direct_cause_code": "T06_SEGMENT_RELATION_CARRIER_TRUTH",
        "lineage": [],
    }

    route = build_object_source_route(
        attribution, ["KEEP_SWSD", "MIXED_CARRIER", "REVIEW_FALLBACK"]
    )

    assert route["candidate_truth_reachable"] is True
    assert route["source_route"] == "MIXED_CARRIER_CANDIDATE_SCORING"
    assert "T06_MIXED_CARRIER_LABEL" in route["supervision_only_sources"]
    assert route["label_only_promoted_to_inference"] is False
