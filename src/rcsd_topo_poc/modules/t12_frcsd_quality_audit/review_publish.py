from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from .carrier_graph import field_name, normalize_id
from .models import ISSUE_TYPES, REVIEW_STATUSES, T12ContractError


def apply_review_decisions(
    candidates: list[dict[str, Any]],
    *,
    run_id: str,
    review_decisions_path: Path | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    candidate_ids = {row["candidate_id"] for row in candidates}
    decisions = (
        _load_decisions(review_decisions_path, run_id, candidate_ids)
        if review_decisions_path is not None
        else {}
    )
    reviewed: list[dict[str, Any]] = []
    confirmed: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for candidate in candidates:
        row = deepcopy(candidate)
        decision = decisions.get(candidate["candidate_id"])
        if decision is None:
            row.update(
                {
                    "review_status": "manual_review_required",
                    "review_reason": "No review decision was provided for this candidate.",
                    "issue_type": "",
                    "review_source": "",
                    "reviewed_at_utc": "",
                }
            )
        else:
            row.update(decision)
        reviewed.append(row)
        if row["review_status"] == "confirmed_frcsd_quality_issue":
            confirmed.append(row)
        elif row["review_status"] == "excluded_false_positive":
            exclusions.append(row)
        else:
            manual.append(row)
    return reviewed, confirmed, exclusions, manual


def _load_decisions(
    path: Path,
    run_id: str,
    candidate_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise T12ContractError(f"review decisions do not exist: {path}")
    frame = pd.read_csv(path, dtype=str).fillna("")
    fields = {
        name: field_name(frame, name)
        for name in (
            "run_id",
            "candidate_id",
            "review_status",
            "issue_type",
            "review_reason",
            "review_source",
            "reviewed_at_utc",
        )
    }
    result: dict[str, dict[str, Any]] = {}
    for _, source in frame.iterrows():
        decision_run_id = normalize_id(source[fields["run_id"]])
        candidate_id = normalize_id(source[fields["candidate_id"]])
        status = normalize_id(source[fields["review_status"]])
        issue_type = normalize_id(source[fields["issue_type"]])
        reason = str(source[fields["review_reason"]]).strip()
        if decision_run_id != run_id:
            raise T12ContractError(
                f"review run_id mismatch: expected={run_id} actual={decision_run_id}"
            )
        if candidate_id not in candidate_ids:
            raise T12ContractError(f"unknown review candidate_id: {candidate_id}")
        if candidate_id in result:
            raise T12ContractError(f"duplicate review candidate_id: {candidate_id}")
        if status not in REVIEW_STATUSES:
            raise T12ContractError(f"invalid review_status for {candidate_id}: {status}")
        if status in {
            "confirmed_frcsd_quality_issue",
            "excluded_false_positive",
        } and not reason:
            raise T12ContractError(f"review_reason is required for {candidate_id}")
        if status == "confirmed_frcsd_quality_issue" and issue_type not in ISSUE_TYPES:
            raise T12ContractError(
                f"confirmed issue_type is invalid for {candidate_id}: {issue_type}"
            )
        if status != "confirmed_frcsd_quality_issue" and issue_type:
            raise T12ContractError(
                f"issue_type is only allowed for confirmed candidates: {candidate_id}"
            )
        result[candidate_id] = {
            "review_status": status,
            "issue_type": issue_type,
            "review_reason": reason,
            "review_source": normalize_id(source[fields["review_source"]]),
            "reviewed_at_utc": normalize_id(source[fields["reviewed_at_utc"]]),
        }
    return result
