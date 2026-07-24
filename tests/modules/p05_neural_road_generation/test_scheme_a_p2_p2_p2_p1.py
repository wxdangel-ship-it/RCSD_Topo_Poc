from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p1_audit import (
    POPULATION_AGREED_WRONG,
    POPULATION_RESIDUAL_UNSAFE,
    POPULATION_REVIEW,
    classify_direct_cause,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p1_models import (
    INFERENCE_EVIDENCE_AVAILABLE,
    SOURCE_FACT_BLOCKED,
    UNOBSERVABLE_FALLBACK,
)


def test_review_access_failure_is_existing_inference_hard_gate() -> None:
    result = classify_direct_cause(
        population=POPULATION_REVIEW,
        access_valid=False,
        in_truth_conditioned_junction_override=False,
        truth_target="REVIEW_FALLBACK",
        clue_codes=(),
        t06_direct_role_present=False,
    )

    assert result["terminal_class"] == INFERENCE_EVIDENCE_AVAILABLE
    assert result["direct_cause_code"] == "T01_ADVANCE_RIGHT_ACCESS_INVALID"
    assert result["inference_available"] is True


def test_truth_conditioned_junction_fallback_remains_source_fact_blocked() -> None:
    result = classify_direct_cause(
        population=POPULATION_AGREED_WRONG,
        access_valid=True,
        in_truth_conditioned_junction_override=True,
        truth_target="KEEP_SWSD",
        clue_codes=(),
        t06_direct_role_present=True,
    )

    assert result["terminal_class"] == SOURCE_FACT_BLOCKED
    assert result["direct_cause_code"] == "TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE"
    assert result["inference_available"] is False


def test_t06_mixed_carrier_truth_is_not_promoted_to_inference() -> None:
    result = classify_direct_cause(
        population=POPULATION_AGREED_WRONG,
        access_valid=True,
        in_truth_conditioned_junction_override=False,
        truth_target="MIXED_CARRIER",
        clue_codes=(),
        t06_direct_role_present=True,
    )

    assert result["terminal_class"] == SOURCE_FACT_BLOCKED
    assert result["direct_cause_code"] == "T06_SEGMENT_RELATION_CARRIER_TRUTH"


def test_t06_missing_carrier_clue_is_not_promoted_to_inference() -> None:
    result = classify_direct_cause(
        population=POPULATION_RESIDUAL_UNSAFE,
        access_valid=True,
        in_truth_conditioned_junction_override=False,
        truth_target="KEEP_SWSD",
        clue_codes=("RCSD_CARRIER_ROAD_MISSING",),
        t06_direct_role_present=True,
    )

    assert result["terminal_class"] == SOURCE_FACT_BLOCKED
    assert result["direct_cause_code"] == "T06_RCSD_CARRIER_ROAD_MISSING"


def test_auxiliary_correlation_cannot_hide_unobservable_direct_cause() -> None:
    result = classify_direct_cause(
        population=POPULATION_RESIDUAL_UNSAFE,
        access_valid=True,
        in_truth_conditioned_junction_override=False,
        truth_target="KEEP_SWSD",
        clue_codes=(),
        t06_direct_role_present=False,
    )

    assert result["terminal_class"] == UNOBSERVABLE_FALLBACK
    assert result["direct_cause_code"] == "NO_DIRECT_OBSERVABLE_SOURCE"
