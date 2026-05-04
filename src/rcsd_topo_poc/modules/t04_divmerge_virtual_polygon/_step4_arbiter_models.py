from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry.base import BaseGeometry

from .rcsd_alignment import RCSD_ALIGNMENT_NONE


DEFAULT_STEP4_SOURCE_STAGE_PRIORITY: tuple[str, ...] = (
    "forward_bind",
    "promotion",
    "recovery",
    "divstrip",
    "swsd_rcsdroad",
    "anchored_reverse",
    "final_conflict_resolver",
)

DESTRUCTIVE_DOWNGRADE_REASON_WHITELIST: tuple[str, ...] = (
    "explicit_role_conflict",
    "explicit_trend_conflict",
    "explicit_reference_geometry_conflict",
    "case_level_arbitrated_replacement",
)

ARBITER_FINAL_FIELD_NAMES: tuple[str, ...] = (
    "selected_rcsdroad_ids",
    "selected_rcsdnode_ids",
    "required_rcsd_node",
    "required_rcsd_node_source",
    "positive_rcsd_present",
    "positive_rcsd_present_reason",
    "positive_rcsd_support_level",
    "positive_rcsd_consistency_level",
    "rcsd_alignment_type",
    "rcsd_match_type",
    "rcsd_selection_mode",
    "selected_evidence_summary",
    "selected_candidate_summary",
    "fact_reference_point",
    "review_materialized_point",
    "surface_scenario_published",
    "has_main_evidence",
    "main_evidence_type",
    "reference_point_present",
    "reference_point_source",
    "surface_scenario_type",
    "section_reference_source",
    "swsd_junction_present",
    "fallback_rcsdroad_ids",
    "surface_generation_mode",
    "no_reference_point_reason",
)


def _clean_id_tuple(values: Iterable[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _clean_flag_tuple(values: Iterable[Any] | None) -> tuple[str, ...]:
    return _clean_id_tuple(values)


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseGeometry):
        return _geometry_audit_doc(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _geometry_audit_doc(geometry: BaseGeometry | None) -> dict[str, Any]:
    if geometry is None:
        return {"present": False}
    return {
        "present": not geometry.is_empty,
        "geom_type": getattr(geometry, "geom_type", None),
    }


@dataclass(frozen=True)
class T04Step4Candidate:
    candidate_id: str
    source_stage: str
    evidence_type: str = ""
    main_evidence_type: str = "none"
    reference_point: BaseGeometry | None = None
    rcsd_alignment_type: str = RCSD_ALIGNMENT_NONE
    rcsdroad_ids: tuple[str, ...] = ()
    rcsdnode_ids: tuple[str, ...] = ()
    required_rcsd_node: str | None = None
    support_level: str = ""
    consistency_level: str = ""
    swsd_trend_score: float | None = None
    rcsd_role_score: float | None = None
    reference_distance_score: float | None = None
    swsd_branch_trend_vs_rcsd_road_trend_score: float | None = None
    entering_exiting_arms_consistency_score: float | None = None
    reference_point_to_rcsd_junction_distance_score: float | None = None
    cross_semantic_object_penalty: float = 0.0
    closer_alternative_candidate_penalty: float = 0.0
    aggregate_consistency_score: float | None = None
    conflict_flags: tuple[str, ...] = ()
    reject_reason: str = ""
    replacement_reason: str = ""
    source_audit_blob: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", str(self.candidate_id or "").strip())
        object.__setattr__(self, "source_stage", str(self.source_stage or "").strip())
        object.__setattr__(self, "evidence_type", str(self.evidence_type or "").strip())
        object.__setattr__(self, "main_evidence_type", str(self.main_evidence_type or "none").strip() or "none")
        object.__setattr__(self, "rcsd_alignment_type", str(self.rcsd_alignment_type or RCSD_ALIGNMENT_NONE).strip())
        object.__setattr__(self, "rcsdroad_ids", _clean_id_tuple(self.rcsdroad_ids))
        object.__setattr__(self, "rcsdnode_ids", _clean_id_tuple(self.rcsdnode_ids))
        object.__setattr__(self, "conflict_flags", _clean_flag_tuple(self.conflict_flags))
        object.__setattr__(self, "source_audit_blob", dict(self.source_audit_blob))

    def with_scores(
        self,
        *,
        swsd_trend_score: float | None = None,
        rcsd_role_score: float | None = None,
        reference_distance_score: float | None = None,
        cross_semantic_object_penalty: float | None = None,
        closer_alternative_candidate_penalty: float | None = None,
        aggregate_consistency_score: float | None = None,
    ) -> "T04Step4Candidate":
        return replace(
            self,
            swsd_trend_score=self.swsd_trend_score if swsd_trend_score is None else swsd_trend_score,
            rcsd_role_score=self.rcsd_role_score if rcsd_role_score is None else rcsd_role_score,
            reference_distance_score=(
                self.reference_distance_score
                if reference_distance_score is None
                else reference_distance_score
            ),
            cross_semantic_object_penalty=(
                self.cross_semantic_object_penalty
                if cross_semantic_object_penalty is None
                else cross_semantic_object_penalty
            ),
            closer_alternative_candidate_penalty=(
                self.closer_alternative_candidate_penalty
                if closer_alternative_candidate_penalty is None
                else closer_alternative_candidate_penalty
            ),
            aggregate_consistency_score=(
                self.aggregate_consistency_score
                if aggregate_consistency_score is None
                else aggregate_consistency_score
            ),
        )

    def to_doc(self) -> dict[str, Any]:
        swsd_trend_score = (
            self.swsd_branch_trend_vs_rcsd_road_trend_score
            if self.swsd_branch_trend_vs_rcsd_road_trend_score is not None
            else self.swsd_trend_score
        )
        rcsd_role_score = (
            self.entering_exiting_arms_consistency_score
            if self.entering_exiting_arms_consistency_score is not None
            else self.rcsd_role_score
        )
        reference_distance_score = (
            self.reference_point_to_rcsd_junction_distance_score
            if self.reference_point_to_rcsd_junction_distance_score is not None
            else self.reference_distance_score
        )
        return _json_safe(
            {
                "candidate_id": self.candidate_id,
                "source_stage": self.source_stage,
                "evidence_type": self.evidence_type,
                "main_evidence_type": self.main_evidence_type,
                "reference_point": _geometry_audit_doc(self.reference_point),
                "rcsd_alignment_type": self.rcsd_alignment_type,
                "rcsdroad_ids": list(self.rcsdroad_ids),
                "rcsdnode_ids": list(self.rcsdnode_ids),
                "required_rcsd_node": self.required_rcsd_node,
                "support_level": self.support_level,
                "consistency_level": self.consistency_level,
                "swsd_trend_score": self.swsd_trend_score,
                "rcsd_role_score": self.rcsd_role_score,
                "reference_distance_score": self.reference_distance_score,
                "swsd_branch_trend_vs_rcsd_road_trend_score": swsd_trend_score,
                "entering_exiting_arms_consistency_score": rcsd_role_score,
                "reference_point_to_rcsd_junction_distance_score": reference_distance_score,
                "cross_semantic_object_penalty": self.cross_semantic_object_penalty,
                "closer_alternative_candidate_penalty": self.closer_alternative_candidate_penalty,
                "aggregate_consistency_score": self.aggregate_consistency_score,
                "conflict_flags": list(self.conflict_flags),
                "reject_reason": self.reject_reason,
                "replacement_reason": self.replacement_reason,
                "source_audit_blob": dict(self.source_audit_blob),
            }
        )


@dataclass(frozen=True)
class T04Step4CandidateLedger:
    unit_id: str
    case_id: str
    candidates: tuple[T04Step4Candidate, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_id", str(self.unit_id or "").strip())
        object.__setattr__(self, "case_id", str(self.case_id or "").strip())
        object.__setattr__(self, "candidates", tuple(self.candidates))
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("duplicate_step4_candidate_id")

    def append(self, candidate: T04Step4Candidate) -> "T04Step4CandidateLedger":
        if not candidate.candidate_id:
            raise ValueError("missing_step4_candidate_id")
        if any(existing.candidate_id == candidate.candidate_id for existing in self.candidates):
            raise ValueError(f"duplicate_step4_candidate_id: {candidate.candidate_id}")
        return T04Step4CandidateLedger(
            unit_id=self.unit_id,
            case_id=self.case_id,
            candidates=(*self.candidates, candidate),
        )

    def extend(self, candidates: Sequence[T04Step4Candidate]) -> "T04Step4CandidateLedger":
        ledger = self
        for candidate in candidates:
            ledger = ledger.append(candidate)
        return ledger

    def to_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "unit_id": self.unit_id,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_doc() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class T04ArbiterCaseContext:
    case_id: str
    unit_id: str
    mainnodeid: str = ""
    shadow_mode: bool = True
    source_stage_priority: tuple[str, ...] = DEFAULT_STEP4_SOURCE_STAGE_PRIORITY
    downgrade_reason_whitelist: tuple[str, ...] = DESTRUCTIVE_DOWNGRADE_REASON_WHITELIST
    case_audit_blob: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", str(self.case_id or "").strip())
        object.__setattr__(self, "unit_id", str(self.unit_id or "").strip())
        object.__setattr__(self, "mainnodeid", str(self.mainnodeid or "").strip())
        object.__setattr__(self, "source_stage_priority", _clean_id_tuple(self.source_stage_priority))
        object.__setattr__(self, "downgrade_reason_whitelist", _clean_id_tuple(self.downgrade_reason_whitelist))
        object.__setattr__(self, "case_audit_blob", dict(self.case_audit_blob))

    def source_stage_rank(self, source_stage: str) -> int:
        source_stage = str(source_stage or "").strip()
        try:
            return self.source_stage_priority.index(source_stage)
        except ValueError:
            return len(self.source_stage_priority)

    def to_doc(self) -> dict[str, Any]:
        return _json_safe(
            {
                "case_id": self.case_id,
                "unit_id": self.unit_id,
                "mainnodeid": self.mainnodeid,
                "shadow_mode": self.shadow_mode,
                "source_stage_priority": list(self.source_stage_priority),
                "downgrade_reason_whitelist": list(self.downgrade_reason_whitelist),
                "case_audit_blob": dict(self.case_audit_blob),
            }
        )


@dataclass(frozen=True)
class T04ArbitrationDecision:
    selected_rcsdroad_ids: tuple[str, ...] = ()
    selected_rcsdnode_ids: tuple[str, ...] = ()
    required_rcsd_node: str | None = None
    required_rcsd_node_source: str | None = None
    positive_rcsd_present: bool = False
    positive_rcsd_present_reason: str = ""
    positive_rcsd_support_level: str = ""
    positive_rcsd_consistency_level: str = ""
    rcsd_alignment_type: str = RCSD_ALIGNMENT_NONE
    rcsd_match_type: str = "none"
    rcsd_selection_mode: str = ""
    selected_evidence_summary: dict[str, Any] = field(default_factory=dict)
    selected_candidate_summary: dict[str, Any] = field(default_factory=dict)
    fact_reference_point: BaseGeometry | None = None
    review_materialized_point: BaseGeometry | None = None
    surface_scenario_published: bool = True
    has_main_evidence: bool = False
    main_evidence_type: str = "none"
    reference_point_present: bool = False
    reference_point_source: str = "none"
    surface_scenario_type: str = "no_surface_reference"
    section_reference_source: str = "none"
    swsd_junction_present: bool = False
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    surface_generation_mode: str = "no_surface"
    no_reference_point_reason: str = "no_surface_reference"
    decision_trace: tuple[dict[str, Any], ...] = ()
    downgrade_from: dict[str, Any] | None = None
    downgrade_to: dict[str, Any] | None = None
    downgrade_reason: str = ""
    suppressed_rcsd_snapshot: dict[str, Any] = field(default_factory=dict)
    rcsd_replacement_due_to_main_evidence: bool = False
    aggregate_rcsd_consistency_score: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_rcsdroad_ids", _clean_id_tuple(self.selected_rcsdroad_ids))
        object.__setattr__(self, "selected_rcsdnode_ids", _clean_id_tuple(self.selected_rcsdnode_ids))
        object.__setattr__(self, "rcsd_alignment_type", str(self.rcsd_alignment_type or RCSD_ALIGNMENT_NONE).strip())
        object.__setattr__(self, "rcsd_match_type", str(self.rcsd_match_type or "none").strip() or "none")
        object.__setattr__(self, "main_evidence_type", str(self.main_evidence_type or "none").strip() or "none")
        object.__setattr__(
            self,
            "reference_point_source",
            str(self.reference_point_source or "none").strip() or "none",
        )
        object.__setattr__(self, "surface_scenario_type", str(self.surface_scenario_type or "").strip())
        object.__setattr__(
            self,
            "section_reference_source",
            str(self.section_reference_source or "none").strip() or "none",
        )
        object.__setattr__(self, "fallback_rcsdroad_ids", _clean_id_tuple(self.fallback_rcsdroad_ids))
        object.__setattr__(
            self,
            "surface_generation_mode",
            str(self.surface_generation_mode or "no_surface").strip() or "no_surface",
        )
        object.__setattr__(
            self,
            "no_reference_point_reason",
            str(self.no_reference_point_reason or "no_surface_reference").strip() or "no_surface_reference",
        )
        object.__setattr__(self, "selected_evidence_summary", dict(self.selected_evidence_summary))
        object.__setattr__(self, "selected_candidate_summary", dict(self.selected_candidate_summary))
        object.__setattr__(self, "decision_trace", tuple(dict(item) for item in self.decision_trace))
        object.__setattr__(self, "suppressed_rcsd_snapshot", dict(self.suppressed_rcsd_snapshot))

    def as_field_kwargs(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in ARBITER_FINAL_FIELD_NAMES}

    def to_audit_doc(self) -> dict[str, Any]:
        return _json_safe(
            {
                "final_fields": self.as_field_kwargs(),
                "decision_trace": list(self.decision_trace),
                "downgrade_from": self.downgrade_from,
                "downgrade_to": self.downgrade_to,
                "downgrade_reason": self.downgrade_reason,
                "suppressed_rcsd_snapshot": dict(self.suppressed_rcsd_snapshot),
                "rcsd_replacement_due_to_main_evidence": self.rcsd_replacement_due_to_main_evidence,
                "aggregate_rcsd_consistency_score": self.aggregate_rcsd_consistency_score,
            }
        )

    def review_index_fields(self) -> dict[str, Any]:
        return {
            "rcsd_decision_history_count": len(self.decision_trace),
            "rcsd_replacement_due_to_main_evidence": int(self.rcsd_replacement_due_to_main_evidence),
            "aggregate_rcsd_consistency_score": self.aggregate_rcsd_consistency_score,
        }


__all__ = [
    "ARBITER_FINAL_FIELD_NAMES",
    "DEFAULT_STEP4_SOURCE_STAGE_PRIORITY",
    "DESTRUCTIVE_DOWNGRADE_REASON_WHITELIST",
    "T04ArbiterCaseContext",
    "T04ArbitrationDecision",
    "T04Step4Candidate",
    "T04Step4CandidateLedger",
]
