from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Stage4CandidateAdmission:
    admitted: bool
    reason: str | None
    detail: str | None
    source_kind: int | None
    source_kind_2: int | None


@dataclass(frozen=True)
class Stage4RepresentativeFields:
    mainnodeid: str
    kind: int | None
    source_kind: int | None
    source_kind_2: int | None
    kind_2: int | None
    grade_2: int | None


@dataclass(frozen=True)
class Stage4AcceptanceDecision:
    acceptance_class: str
    acceptance_reason: str
    success: bool
    flow_success: bool
    review_reasons: tuple[str, ...]
    hard_rejection_reasons: tuple[str, ...]


def _dedupe_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        text = str(reason).strip()
        if not text or text in seen:
            continue
        deduped.append(text)
        seen.add(text)
    return tuple(deduped)


def resolve_stage4_output_kind(*, source_kind: int | None, source_kind_2: int | None) -> int | None:
    return source_kind if source_kind is not None else source_kind_2


def build_stage4_representative_fields(
    *,
    mainnodeid: str,
    source_kind: int | None,
    source_kind_2: int | None,
    kind_2: int | None,
    grade_2: int | None,
) -> Stage4RepresentativeFields:
    return Stage4RepresentativeFields(
        mainnodeid=mainnodeid,
        kind=resolve_stage4_output_kind(source_kind=source_kind, source_kind_2=source_kind_2),
        source_kind=source_kind,
        source_kind_2=source_kind_2,
        kind_2=kind_2,
        grade_2=grade_2,
    )


def evaluate_stage4_candidate_admission(
    *,
    has_evd: str | None,
    is_anchor: str | None,
    source_kind: int | None,
    source_kind_2: int | None,
    supported_kind: bool,
    out_of_scope_reason: str,
) -> Stage4CandidateAdmission:
    if has_evd == "yes" and is_anchor == "no" and supported_kind:
        return Stage4CandidateAdmission(
            admitted=True,
            reason=None,
            detail=None,
            source_kind=source_kind,
            source_kind_2=source_kind_2,
        )
    return Stage4CandidateAdmission(
        admitted=False,
        reason=out_of_scope_reason,
        detail=(
            "Stage4 candidate admission rejected: "
            f"has_evd={has_evd}, is_anchor={is_anchor}, kind={source_kind}, kind_2={source_kind_2}."
        ),
        source_kind=source_kind,
        source_kind_2=source_kind_2,
    )


def finalize_stage4_acceptance(
    *,
    review_reasons: Sequence[str],
    hard_rejection_reasons: Sequence[str] = (),
    flow_success: bool = True,
) -> Stage4AcceptanceDecision:
    normalized_reviews = _dedupe_reasons(review_reasons)
    normalized_rejections = _dedupe_reasons(hard_rejection_reasons)
    if normalized_rejections:
        return Stage4AcceptanceDecision(
            acceptance_class="rejected",
            acceptance_reason=normalized_rejections[0],
            success=False,
            flow_success=flow_success,
            review_reasons=normalized_reviews,
            hard_rejection_reasons=normalized_rejections,
        )
    if normalized_reviews:
        return Stage4AcceptanceDecision(
            acceptance_class="review_required",
            acceptance_reason=normalized_reviews[0],
            success=False,
            flow_success=flow_success,
            review_reasons=normalized_reviews,
            hard_rejection_reasons=normalized_rejections,
        )
    return Stage4AcceptanceDecision(
        acceptance_class="accepted",
        acceptance_reason="stable",
        success=True,
        flow_success=flow_success,
        review_reasons=normalized_reviews,
        hard_rejection_reasons=normalized_rejections,
    )
