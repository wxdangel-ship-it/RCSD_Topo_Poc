from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from ._step4_arbiter_models import T04Step4Candidate
from .rcsd_alignment import (
    RCSD_ALIGNMENT_AMBIGUOUS,
    RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES,
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_ROAD_ONLY,
)


SWSD_TREND_SCORE_WEIGHT = 0.30
RCSD_ROLE_SCORE_WEIGHT = 0.25
REFERENCE_DISTANCE_SCORE_WEIGHT = 0.25
CROSS_SEMANTIC_OBJECT_PENALTY_WEIGHT = -0.10
CLOSER_ALTERNATIVE_CANDIDATE_PENALTY_WEIGHT = -0.10

_TREND_CONFLICT_FLAGS = frozenset(
    {
        "explicit_trend_conflict",
        "trend_conflict",
        "swsd_rcsd_trend_conflict",
    }
)
_ROLE_CONFLICT_FLAGS = frozenset(
    {
        "explicit_role_conflict",
        "role_conflict",
        "rcsd_role_conflict",
    }
)
_REFERENCE_CONFLICT_FLAGS = frozenset(
    {
        "explicit_reference_geometry_conflict",
        "reference_geometry_conflict",
        "reference_point_conflict",
    }
)


def _clamp(value: float, lower: float, upper: float) -> float:
    if not math.isfinite(value):
        return lower
    return max(lower, min(upper, value))


def _has_any_flag(flags: Iterable[str], expected: frozenset[str]) -> bool:
    return bool({str(flag or "").strip() for flag in flags} & expected)


def _support_score(candidate: T04Step4Candidate) -> float:
    support = str(candidate.support_level or "").strip()
    if support == "primary_support":
        return 1.0
    if support == "secondary_support":
        return 0.65
    if support == "no_support":
        return 0.0
    if candidate.required_rcsd_node:
        return 0.75
    if candidate.rcsdnode_ids:
        return 0.60
    if candidate.rcsdroad_ids:
        return 0.35
    return -0.25


def _consistency_score(candidate: T04Step4Candidate) -> float:
    consistency = str(candidate.consistency_level or "").strip().upper()
    if consistency == "A":
        return 1.0
    if consistency == "B":
        return 0.65
    if consistency == "C":
        return 0.15
    if candidate.rcsd_alignment_type in RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES:
        return 0.75
    if candidate.rcsd_alignment_type == RCSD_ALIGNMENT_ROAD_ONLY:
        return 0.35
    return -0.15


def _alignment_trend_score(candidate: T04Step4Candidate) -> float:
    if candidate.reject_reason:
        return -1.0
    if _has_any_flag(candidate.conflict_flags, _TREND_CONFLICT_FLAGS):
        return -1.0
    if candidate.rcsd_alignment_type == RCSD_ALIGNMENT_AMBIGUOUS:
        return -0.75
    if candidate.rcsd_alignment_type in RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES:
        return 1.0
    if candidate.rcsd_alignment_type == RCSD_ALIGNMENT_ROAD_ONLY:
        return 0.45
    if candidate.rcsd_alignment_type == RCSD_ALIGNMENT_NONE:
        return -0.25
    return 0.0


def _role_score(candidate: T04Step4Candidate) -> float:
    if _has_any_flag(candidate.conflict_flags, _ROLE_CONFLICT_FLAGS):
        return -1.0
    return _clamp((_support_score(candidate) + _consistency_score(candidate)) / 2.0, -1.0, 1.0)


def _reference_score(candidate: T04Step4Candidate) -> float:
    if _has_any_flag(candidate.conflict_flags, _REFERENCE_CONFLICT_FLAGS):
        return 0.0
    if candidate.reference_point is not None and not candidate.reference_point.is_empty:
        if candidate.required_rcsd_node:
            return 1.0
        if candidate.rcsdnode_ids:
            return 0.75
        if candidate.rcsdroad_ids:
            return 0.55
    if candidate.required_rcsd_node:
        return 0.65
    if candidate.rcsdroad_ids:
        return 0.35
    return 0.0


def _aggregate(
    *,
    swsd_trend_score: float,
    rcsd_role_score: float,
    reference_distance_score: float,
    cross_semantic_object_penalty: float,
    closer_alternative_candidate_penalty: float,
) -> float:
    return (
        SWSD_TREND_SCORE_WEIGHT * swsd_trend_score
        + RCSD_ROLE_SCORE_WEIGHT * rcsd_role_score
        + REFERENCE_DISTANCE_SCORE_WEIGHT * reference_distance_score
        + CROSS_SEMANTIC_OBJECT_PENALTY_WEIGHT * cross_semantic_object_penalty
        + CLOSER_ALTERNATIVE_CANDIDATE_PENALTY_WEIGHT * closer_alternative_candidate_penalty
    )


def score_step4_candidate(candidate: T04Step4Candidate) -> T04Step4Candidate:
    swsd_trend_score = _clamp(
        (
            candidate.swsd_branch_trend_vs_rcsd_road_trend_score
            if candidate.swsd_branch_trend_vs_rcsd_road_trend_score is not None
            else candidate.swsd_trend_score
            if candidate.swsd_trend_score is not None
            else _alignment_trend_score(candidate)
        ),
        -1.0,
        1.0,
    )
    rcsd_role_score = _clamp(
        (
            candidate.entering_exiting_arms_consistency_score
            if candidate.entering_exiting_arms_consistency_score is not None
            else candidate.rcsd_role_score
            if candidate.rcsd_role_score is not None
            else _role_score(candidate)
        ),
        -1.0,
        1.0,
    )
    reference_distance_score = _clamp(
        (
            candidate.reference_point_to_rcsd_junction_distance_score
            if candidate.reference_point_to_rcsd_junction_distance_score is not None
            else candidate.reference_distance_score
            if candidate.reference_distance_score is not None
            else _reference_score(candidate)
        ),
        0.0,
        1.0,
    )
    cross_semantic_object_penalty = _clamp(candidate.cross_semantic_object_penalty, 0.0, 1.0)
    closer_alternative_candidate_penalty = _clamp(candidate.closer_alternative_candidate_penalty, 0.0, 1.0)
    aggregate_consistency_score = (
        _clamp(candidate.aggregate_consistency_score, -1.0, 1.0)
        if candidate.aggregate_consistency_score is not None
        else _aggregate(
            swsd_trend_score=swsd_trend_score,
            rcsd_role_score=rcsd_role_score,
            reference_distance_score=reference_distance_score,
            cross_semantic_object_penalty=cross_semantic_object_penalty,
            closer_alternative_candidate_penalty=closer_alternative_candidate_penalty,
        )
    )
    return replace(
        candidate,
        swsd_trend_score=swsd_trend_score,
        rcsd_role_score=rcsd_role_score,
        reference_distance_score=reference_distance_score,
        swsd_branch_trend_vs_rcsd_road_trend_score=swsd_trend_score,
        entering_exiting_arms_consistency_score=rcsd_role_score,
        reference_point_to_rcsd_junction_distance_score=reference_distance_score,
        cross_semantic_object_penalty=cross_semantic_object_penalty,
        closer_alternative_candidate_penalty=closer_alternative_candidate_penalty,
        aggregate_consistency_score=aggregate_consistency_score,
    )


def score_step4_candidates(candidates: Iterable[T04Step4Candidate]) -> tuple[T04Step4Candidate, ...]:
    return tuple(score_step4_candidate(candidate) for candidate in candidates)


__all__ = [
    "CLOSER_ALTERNATIVE_CANDIDATE_PENALTY_WEIGHT",
    "CROSS_SEMANTIC_OBJECT_PENALTY_WEIGHT",
    "RCSD_ROLE_SCORE_WEIGHT",
    "REFERENCE_DISTANCE_SCORE_WEIGHT",
    "SWSD_TREND_SCORE_WEIGHT",
    "score_step4_candidate",
    "score_step4_candidates",
]
