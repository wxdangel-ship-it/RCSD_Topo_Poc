from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.review_publish import (
    apply_review_decisions,
)


def _candidate(
    candidate_id: str,
    *,
    equivalent: bool = False,
    anchor_confidence: str = "t07_standard_surface",
    equivalence_basis: str = "raw_carrier",
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "segment_id": candidate_id,
        "candidate_status": "candidate_pending_decision",
        "automatic_all_directions_equivalent": equivalent,
        "automatic_equivalence_basis": equivalence_basis if equivalent else "",
        "failed_directions": [] if equivalent else ["pair0_to_pair1"],
        "suggested_issue_type": (
            "" if equivalent else "directed_carrier_missing"
        ),
        "anchor_confidence": anchor_confidence,
    }


def _write_decisions(path: Path, rows: list[dict[str, str]]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _decision(candidate_id: str, status: str) -> dict[str, str]:
    return {
        "run_id": "run",
        "candidate_id": candidate_id,
        "review_status": status,
        "issue_type": (
            "directed_carrier_missing"
            if status == "confirmed_frcsd_quality_issue"
            else ""
        ),
        "review_reason": "evidence reviewed",
        "review_source": "unit-test",
        "reviewed_at_utc": "2026-07-18T00:00:00Z",
    }


def test_automatic_decisions_are_published_without_review() -> None:
    reviewed, confirmed, exclusions, manual = apply_review_decisions(
        [
            _candidate("confirmed"),
            _candidate("equivalent", equivalent=True),
            _candidate("insufficient", anchor_confidence="insufficient"),
        ],
        run_id="run",
        review_decisions_path=None,
    )

    assert len(reviewed) == 3
    assert [row["candidate_id"] for row in confirmed] == ["confirmed"]
    assert [row["candidate_id"] for row in exclusions] == [
        "equivalent",
        "insufficient",
    ]
    assert manual == []
    assert confirmed[0]["decision_source"] == "automatic_high_confidence"
    assert exclusions[0]["decision_rule"] == "equivalent_raw_carrier"
    assert exclusions[1]["decision_rule"] == "insufficient_anchor_confidence"


def test_portal_constrained_semantic_equivalence_has_distinct_audit_rule() -> None:
    reviewed, confirmed, exclusions, manual = apply_review_decisions(
        [
            _candidate(
                "semantic-equivalent",
                equivalent=True,
                equivalence_basis="portal_constrained_semantic_carrier",
            )
        ],
        run_id="run",
        review_decisions_path=None,
    )

    assert confirmed == []
    assert manual == []
    assert reviewed == exclusions
    assert exclusions[0]["decision_rule"] == (
        "equivalent_portal_constrained_semantic_carrier"
    )
    assert "portal-constrained semantic" in exclusions[0]["review_reason"]


def test_t07_road_surface_equivalence_has_distinct_audit_rule() -> None:
    reviewed, confirmed, exclusions, manual = apply_review_decisions(
        [
            _candidate(
                "surface-equivalent",
                equivalent=True,
                equivalence_basis="t07_road_surface_carrier",
            )
        ],
        run_id="run",
        review_decisions_path=None,
    )

    assert confirmed == []
    assert manual == []
    assert reviewed == exclusions
    assert exclusions[0]["decision_rule"] == (
        "equivalent_t07_road_surface_carrier"
    )
    assert "Road-surface" in exclusions[0]["review_reason"]


def test_review_states_override_automatic_decisions_and_missing_keeps_automatic(
    tmp_path: Path,
) -> None:
    decisions = _write_decisions(
        tmp_path / "review.csv",
        [
            _decision("confirmed", "confirmed_frcsd_quality_issue"),
            _decision("excluded", "excluded_false_positive"),
        ],
    )

    reviewed, confirmed, exclusions, manual = apply_review_decisions(
        [
            _candidate("confirmed", equivalent=True),
            _candidate("excluded"),
            _candidate("automatic"),
        ],
        run_id="run",
        review_decisions_path=decisions,
    )

    assert len(reviewed) == 3
    assert [row["candidate_id"] for row in confirmed] == [
        "confirmed",
        "automatic",
    ]
    assert [row["candidate_id"] for row in exclusions] == ["excluded"]
    assert [row["candidate_id"] for row in manual] == []
    assert next(
        row for row in reviewed if row["candidate_id"] == "automatic"
    )["decision_source"] == "automatic_high_confidence"
    assert next(
        row for row in reviewed if row["candidate_id"] == "confirmed"
    )["decision_source"] == "external_review_override"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(candidate_id="unknown"), "unknown review candidate_id"),
        (lambda row: row.update(run_id="other"), "review run_id mismatch"),
        (lambda row: row.update(review_reason=""), "review_reason is required"),
    ],
)
def test_invalid_review_contract_is_blocked(tmp_path: Path, mutate, message: str) -> None:
    row = _decision("candidate", "confirmed_frcsd_quality_issue")
    mutate(row)
    path = _write_decisions(tmp_path / "review.csv", [row])

    with pytest.raises(T12ContractError, match=message):
        apply_review_decisions(
            [_candidate("candidate")],
            run_id="run",
            review_decisions_path=path,
        )


def test_duplicate_review_candidate_is_blocked(tmp_path: Path) -> None:
    row = _decision("candidate", "excluded_false_positive")
    path = _write_decisions(tmp_path / "review.csv", [row, row])

    with pytest.raises(T12ContractError, match="duplicate review candidate_id"):
        apply_review_decisions(
            [_candidate("candidate")],
            run_id="run",
            review_decisions_path=path,
        )
