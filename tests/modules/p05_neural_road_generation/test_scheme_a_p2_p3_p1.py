from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p1_audit import (
    final_decision,
    fold_coverage_feasibility,
    stable_wrong_accepted_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p1_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_EVIDENCE_NO_GO,
    DECISION_MODEL_RESTART_GO,
    SchemeAP2P3P1Config,
)


def _config(tmp_path: Path, **overrides: object) -> SchemeAP2P3P1Config:
    values: dict[str, object] = {
        "p2_p3_p0_run_root": tmp_path,
        "p2_p2_p2_p2_run_root": tmp_path,
        "dataset_p0_run_root": tmp_path,
        "poc_data_root": tmp_path,
        "repository_root": tmp_path,
        "output_root": tmp_path,
        "run_id": "audit",
    }
    values.update(overrides)
    return SchemeAP2P3P1Config(**values)


def test_config_rejects_empty_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        _config(tmp_path, run_id="")


def test_fold2_overall_coverage_gate_is_mathematically_impossible() -> None:
    result = fold_coverage_feasibility(
        object_count=3_037,
        ineligible_count=1_795,
        minimum_safe_coverage=0.50,
    )

    assert result["eligible_count"] == 1_242
    assert result["maximum_overall_safe_coverage"] == pytest.approx(
        1_242 / 3_037
    )
    assert result["overall_coverage_gate_mathematically_feasible"] is False


def test_stable_wrong_accept_requires_two_seeds() -> None:
    evaluations = {
        ("g1", 311): {
            "group_id": "g1",
            "seed": 311,
            "selected_candidate_id": "use",
            "truth_candidate_id": "keep",
        },
        ("g1", 313): {
            "group_id": "g1",
            "seed": 313,
            "selected_candidate_id": "use",
            "truth_candidate_id": "keep",
        },
        ("g1", 317): {
            "group_id": "g1",
            "seed": 317,
            "selected_candidate_id": "keep",
            "truth_candidate_id": "keep",
        },
        ("g2", 311): {
            "group_id": "g2",
            "seed": 311,
            "selected_candidate_id": "use",
            "truth_candidate_id": "keep",
        },
    }
    decisions = {
        key: {"accepted": True} for key in evaluations
    }

    result = stable_wrong_accepted_groups(
        evaluations=evaluations,
        decisions=decisions,
        minimum_seed_count=2,
    )

    assert result == {"g1"}


@pytest.mark.parametrize(
    ("input_gate", "attribution_gate", "role_gate", "evidence", "validation", "expected"),
    [
        (
            False,
            True,
            True,
            1,
            1,
            DECISION_AUDIT_NO_GO,
        ),
        (
            True,
            True,
            True,
            0,
            1,
            DECISION_EVIDENCE_NO_GO,
        ),
        (
            True,
            True,
            True,
            1,
            0,
            DECISION_EVIDENCE_NO_GO,
        ),
        (
            True,
            True,
            True,
            1,
            1,
            DECISION_MODEL_RESTART_GO,
        ),
    ],
)
def test_final_decision_requires_evidence_and_independent_validation(
    input_gate: bool,
    attribution_gate: bool,
    role_gate: bool,
    evidence: int,
    validation: int,
    expected: str,
) -> None:
    assert (
        final_decision(
            input_gate=input_gate,
            attribution_gate=attribution_gate,
            role_gate=role_gate,
            new_direct_evidence_count=evidence,
            independent_validation_count=validation,
        )
        == expected
    )
