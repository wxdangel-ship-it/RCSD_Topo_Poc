from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.review_publish import (
    apply_review_decisions,
)


def _candidate(candidate_id: str) -> dict[str, object]:
    return {"candidate_id": candidate_id, "segment_id": candidate_id}


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


def test_review_states_are_mutually_exclusive_and_missing_is_manual(tmp_path: Path) -> None:
    decisions = _write_decisions(
        tmp_path / "review.csv",
        [
            _decision("confirmed", "confirmed_frcsd_quality_issue"),
            _decision("excluded", "excluded_false_positive"),
        ],
    )

    reviewed, confirmed, exclusions, manual = apply_review_decisions(
        [_candidate("confirmed"), _candidate("excluded"), _candidate("manual")],
        run_id="run",
        review_decisions_path=decisions,
    )

    assert len(reviewed) == 3
    assert [row["candidate_id"] for row in confirmed] == ["confirmed"]
    assert [row["candidate_id"] for row in exclusions] == ["excluded"]
    assert [row["candidate_id"] for row in manual] == ["manual"]


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
