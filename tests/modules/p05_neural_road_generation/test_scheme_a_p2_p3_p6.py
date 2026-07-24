from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p6_audit import (
    build_clue_error_audit,
    build_dual_layer_metrics,
    build_expected_failure_audit,
    build_object_attribution,
    prove_calibration_problem,
    prove_representation_problem,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p6_models import (
    DECISION_ATTRIBUTION_GO,
    DECISION_AUDIT_NO_GO,
    choose_p6_decision,
)


def test_choose_p6_decision_requires_both_routes_and_audit() -> None:
    assert choose_p6_decision(True, True, True) == DECISION_ATTRIBUTION_GO
    assert choose_p6_decision(True, True, False) == DECISION_AUDIT_NO_GO
    assert choose_p6_decision(False, True, True) == DECISION_AUDIT_NO_GO


def test_object_attribution_separates_scorer_and_publication() -> None:
    row = build_object_attribution(
        {
            "decision": {
                "seed": 311,
                "fold": 2,
                "case_key": "T10:609214532",
                "group_id": "g1",
                "object_id": "s1",
                "clue_predicted": False,
                "clue_threshold": 0.9,
                "accepted": True,
                "reason": "hierarchical_carrier_accept",
            },
            "evaluation": {
                "selected_candidate_id": "use",
                "truth_candidate_id": "keep",
                "selected_target": "USE_RCSD",
                "truth_target": "KEEP_SWSD",
                "review_target": False,
                "clue_target": True,
            },
            "score": {
                "clue_probability": 0.01,
                "candidate_ids": ["keep", "use"],
                "candidate_scores": [1.0, 3.0],
                "candidate_utilities": [0.1, 0.9],
            },
            "effective": {
                "accepted": False,
                "reason": "expected_swsd_baseline_failure",
            },
        }
    )
    assert row["primary_attribution"] == "CARRIER_RANK_WRONG_CLUE_MISSED"
    assert row["publication_attribution"] == "EXPECTED_FAILURE_CASE_ATOMIC_BLOCK"
    assert row["carrier_score_margin_selected_minus_truth"] == 2.0


def test_dual_layer_metrics_do_not_mask_wrong_scorer_accept() -> None:
    rows = [
        _row(
            group_id="wrong",
            correct=False,
            clue_target=True,
            clue_predicted=False,
            scorer_accepted=True,
            final_published=False,
        ),
        _row(
            group_id="right",
            correct=True,
            clue_target=False,
            clue_predicted=False,
            scorer_accepted=True,
            final_published=True,
        ),
    ]
    seed = next(
        row for row in build_dual_layer_metrics(rows) if row["scope"] == "SEED"
    )
    assert seed["scorer_wrong_accepted_count"] == 1
    assert seed["final_wrong_published_count"] == 0
    assert seed["scorer_safe_coverage"] == 0.5
    assert seed["final_safe_coverage"] == 0.5


def test_expected_failure_audit_counts_atomic_block_separately() -> None:
    rows = [
        {
            **_row(
                group_id="g1",
                correct=True,
                clue_target=False,
                clue_predicted=False,
                scorer_accepted=True,
                final_published=False,
            ),
            "case_key": "T10:609214532",
            "expected_failure_atomic_block": True,
        },
        {
            **_row(
                group_id="g2",
                correct=True,
                clue_target=True,
                clue_predicted=True,
                scorer_accepted=False,
                final_published=False,
            ),
            "case_key": "T10:609214532",
            "expected_failure_atomic_block": True,
            "scorer_reason": "dataset_p1_localized_expected_failure",
        },
    ]
    audit = build_expected_failure_audit(rows, {"T10:609214532": 2})
    assert audit["eligible_atomic_block_counts"]["311"] == 2
    assert audit["actual_safe_coverage_mask_counts"]["311"] == 1
    assert audit["localized_failure_group_counts"]["311"] == 1


def test_clue_stability_and_problem_proofs() -> None:
    rows = []
    for seed, threshold in ((311, 0.9995), (313, 0.9996), (317, 0.0004)):
        rows.extend(
            [
                {
                    **_row(
                        seed=seed,
                        group_id="stable-fp",
                        correct=True,
                        clue_target=False,
                        clue_predicted=True,
                        scorer_accepted=False,
                        final_published=False,
                    ),
                    "clue_threshold": threshold,
                    "clue_threshold_margin": 0.001,
                },
                {
                    **_row(
                        seed=seed,
                        group_id="stable-fn",
                        correct=True,
                        clue_target=True,
                        clue_predicted=False,
                        scorer_accepted=True,
                        final_published=True,
                    ),
                    "clue_threshold": threshold,
                    "clue_threshold_margin": -0.001,
                },
            ]
        )
    _, summary = build_clue_error_audit(rows)
    assert summary["stable_false_positive_group_ids"] == ["stable-fp"]
    assert summary["stable_false_negative_group_ids"] == ["stable-fn"]

    expanded = {
        **summary,
        "false_positive_counts": {"311": 1, "313": 2, "317": 2_629},
        "false_negative_counts": {"311": 29, "313": 174, "317": 6},
    }
    assert prove_calibration_problem(rows, expanded)

    expanded["stable_carrier_wrong_accepted_group_ids"] = [
        "SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080"
    ]
    evidence = {
        "stable_group_neighbors": [
            {
                "group_id": expanded[
                    "stable_carrier_wrong_accepted_group_ids"
                ][0],
                "neighbor_count": 20,
                "neighbor_clue_false_count": 20,
                "neighbor_truth_target_counts": {"USE_RCSD": 20},
            }
            for _ in range(3)
        ]
    }
    assert prove_representation_problem(expanded, evidence)


def _row(
    *,
    seed: int = 311,
    group_id: str,
    correct: bool,
    clue_target: bool,
    clue_predicted: bool,
    scorer_accepted: bool,
    final_published: bool,
) -> dict[str, object]:
    return {
        "seed": seed,
        "fold": 2,
        "case_key": "T10:case",
        "family": "T10",
        "group_id": group_id,
        "object_id": group_id,
        "truth_target": "KEEP_SWSD",
        "carrier_selection_correct": correct,
        "review_target": False,
        "clue_target": clue_target,
        "clue_predicted": clue_predicted,
        "clue_probability": 0.5,
        "clue_threshold": 0.5,
        "clue_threshold_margin": 0.0,
        "scorer_accepted": scorer_accepted,
        "scorer_reason": "hierarchical_carrier_accept",
        "final_published": final_published,
        "expected_failure_atomic_block": False,
    }
