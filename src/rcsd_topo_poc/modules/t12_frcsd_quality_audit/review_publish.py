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
        automatic = _automatic_decision(candidate)
        row.update(automatic)
        row["automatic_review_status"] = automatic["review_status"]
        row["automatic_issue_type"] = automatic["issue_type"]
        row["automatic_decision_rule"] = automatic["decision_rule"]
        decision = decisions.get(candidate["candidate_id"])
        if decision is not None:
            row.update(decision)
            row["decision_source"] = "external_review_override"
            row["decision_rule"] = "external_review_override"
        row["candidate_status"] = "candidate_decided"
        reviewed.append(row)
        if row["review_status"] == "confirmed_frcsd_quality_issue":
            confirmed.append(row)
        elif row["review_status"] == "excluded_false_positive":
            exclusions.append(row)
        else:
            manual.append(row)
    return reviewed, confirmed, exclusions, manual


def _automatic_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("candidate_kind") == "unexpected_reverse_carrier":
        return _automatic_unexpected_reverse_decision(candidate)
    equivalent = bool(candidate.get("automatic_all_directions_equivalent"))
    anchor_confidence = str(candidate.get("anchor_confidence") or "insufficient")
    if equivalent:
        equivalence_basis = str(
            candidate.get("automatic_equivalence_basis") or "raw_carrier"
        )
        if equivalence_basis == "portal_constrained_semantic_carrier":
            reason = (
                "All SWSD-required directions have an equivalent "
                "portal-constrained semantic local directed FRCSD carrier."
            )
            rule = "equivalent_portal_constrained_semantic_carrier"
        elif equivalence_basis == "t07_road_surface_carrier":
            reason = (
                "All SWSD-required directions have an equivalent T07 "
                "Road-surface local directed FRCSD carrier; distance gates "
                "are retained as audit-only evidence."
            )
            rule = "equivalent_t07_road_surface_carrier"
        else:
            reason = (
                "All SWSD-required directions have an equivalent raw local "
                "directed FRCSD carrier."
            )
            rule = "equivalent_raw_carrier"
        return {
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "review_reason": reason,
            "review_source": "t12_automatic_high_confidence",
            "reviewed_at_utc": "",
            "decision_source": "automatic_high_confidence",
            "decision_rule": rule,
        }
    if anchor_confidence == "insufficient":
        return {
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "review_reason": (
                "Raw carrier evidence is not attributable to FRCSD with the "
                "required T07 standard-surface or dual-T03 anchor confidence."
            ),
            "review_source": "t12_automatic_high_confidence",
            "reviewed_at_utc": "",
            "decision_source": "automatic_high_confidence",
            "decision_rule": "insufficient_anchor_confidence",
        }
    issue_type = str(candidate.get("suggested_issue_type") or "")
    if issue_type not in ISSUE_TYPES:
        raise T12ContractError(
            "automatic confirmed candidate has no valid issue_type: "
            f"{candidate.get('candidate_id', '')}"
        )
    return {
        "review_status": "confirmed_frcsd_quality_issue",
        "issue_type": issue_type,
        "review_reason": (
            "A SWSD-required direction lacks an equivalent trusted local "
            "FRCSD carrier after raw, portal-constrained semantic, and T07 "
            "Road-surface checks "
            f"with {anchor_confidence} anchor evidence."
        ),
        "review_source": "t12_automatic_high_confidence",
        "reviewed_at_utc": "",
        "decision_source": "automatic_high_confidence",
        "decision_rule": "raw_carrier_missing_trusted_anchor",
    }


def _automatic_unexpected_reverse_decision(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    swsd_evidence = candidate.get("unexpected_reverse_swsd") or {}
    if bool(swsd_evidence.get("accepted_equivalent_carrier")):
        return {
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "review_reason": (
                "SWSD has an equivalent reverse full-graph carrier, so the "
                "FRCSD reverse carrier is not proven unexpected."
            ),
            "review_source": "t12_automatic_high_confidence",
            "reviewed_at_utc": "",
            "decision_source": "automatic_high_confidence",
            "decision_rule": "unexpected_reverse_swsd_equivalent",
        }
    if not bool(candidate.get("unexpected_reverse_high_precision_anchor")):
        return {
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "review_reason": (
                "The reverse carrier is retained as audit evidence but lacks "
                "dual unique T07 standard-surface anchors required by the "
                "precision-first publication policy."
            ),
            "review_source": "t12_automatic_high_confidence",
            "reviewed_at_utc": "",
            "decision_source": "automatic_high_confidence",
            "decision_rule": (
                "unexpected_reverse_insufficient_high_precision_evidence"
            ),
        }
    ownership = candidate.get("unexpected_reverse_segment_ownership") or {}
    if not bool(ownership.get("accepted_current_segment_owner")):
        other_segment_ids = ownership.get("other_segment_ids") or []
        if other_segment_ids:
            return {
                "review_status": "excluded_false_positive",
                "issue_type": "",
                "review_reason": (
                    "The reverse raw FRCSD path is more strongly covered by "
                    "another SWSD Segment and is not owned by the current "
                    "Segment: "
                    + "|".join(str(value) for value in other_segment_ids)
                ),
                "review_source": "t12_automatic_high_confidence",
                "reviewed_at_utc": "",
                "decision_source": "automatic_high_confidence",
                "decision_rule": "unexpected_reverse_other_segment_covered",
            }
        return {
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "review_reason": (
                "The inter-anchor reverse raw FRCSD Road ownership is "
                "ambiguous, so the path cannot be attributed uniquely to "
                "the current Segment."
            ),
            "review_source": "t12_automatic_high_confidence",
            "reviewed_at_utc": "",
            "decision_source": "automatic_high_confidence",
            "decision_rule": (
                "unexpected_reverse_segment_ownership_ambiguous"
            ),
        }
    anchor_interval = candidate.get("unexpected_reverse_anchor_interval") or {}
    if not bool(anchor_interval.get("accepted_anchor_interval")):
        return {
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "review_reason": (
                "The reverse raw FRCSD path does not prove physical Road "
                "contact between both current Segment T07 standard-surface "
                "anchors."
            ),
            "review_source": "t12_automatic_high_confidence",
            "reviewed_at_utc": "",
            "decision_source": "automatic_high_confidence",
            "decision_rule": "unexpected_reverse_anchor_interval_unproven",
        }
    frcsd_evidence = candidate.get("unexpected_reverse_frcsd") or {}
    if not bool(frcsd_evidence.get("accepted_equivalent_carrier")):
        raise T12ContractError(
            "unexpected reverse candidate lacks an equivalent raw FRCSD "
            f"carrier: {candidate.get('candidate_id', '')}"
        )
    return {
        "review_status": "confirmed_frcsd_quality_issue",
        "issue_type": "unexpected_reverse_carrier",
        "review_reason": (
            "A one-way SWSD Segment has an equivalent reverse raw local FRCSD "
            "carrier, no equivalent SWSD reverse full-graph carrier, and dual "
            "unique T07 standard-surface anchors; the path physically spans "
            "the two anchors and is uniquely owned by the current Segment."
        ),
        "review_source": "t12_automatic_high_confidence",
        "reviewed_at_utc": "",
        "decision_source": "automatic_high_confidence",
        "decision_rule": (
            "unexpected_reverse_raw_carrier_dual_t07_segment_scoped"
        ),
    }


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
