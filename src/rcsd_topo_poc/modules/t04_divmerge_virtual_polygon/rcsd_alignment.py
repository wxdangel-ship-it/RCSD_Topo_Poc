from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, TypeAlias


# Keep these values aligned with the T04 module interface contract.
RCSD_ALIGNMENT_SEMANTIC_JUNCTION = "rcsd_semantic_junction"
RCSD_ALIGNMENT_JUNCTION_PARTIAL = "rcsd_junction_partial_alignment"
RCSD_ALIGNMENT_ROAD_ONLY = "rcsdroad_only_alignment"
RCSD_ALIGNMENT_NONE = "no_rcsd_alignment"
RCSD_ALIGNMENT_AMBIGUOUS = "ambiguous_rcsd_alignment"

RCSDAlignmentType: TypeAlias = Literal[
    "rcsd_semantic_junction",
    "rcsd_junction_partial_alignment",
    "rcsdroad_only_alignment",
    "no_rcsd_alignment",
    "ambiguous_rcsd_alignment",
]

RCSD_ALIGNMENT_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_AMBIGUOUS,
)

RCSD_ALIGNMENT_POSITIVE_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
)
RCSD_ALIGNMENT_FALLBACK_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
RCSD_ALIGNMENT_NO_POSITIVE_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_NONE,
)
RCSD_ALIGNMENT_BLOCKING_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_AMBIGUOUS,
)
RCSD_ALIGNMENT_RENDER_RCSDROAD_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
RCSD_ALIGNMENT_SECTION_REFERENCE_TYPES: tuple[RCSDAlignmentType, ...] = (
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
)

RCSD_ALIGNMENT_SCOPE_EVENT_UNIT = "event_unit"
RCSD_ALIGNMENT_SCOPE_CASE = "case"

RCSDAlignmentScope: TypeAlias = Literal["event_unit", "case"]

RCSD_ALIGNMENT_SCOPES: tuple[RCSDAlignmentScope, ...] = (
    RCSD_ALIGNMENT_SCOPE_EVENT_UNIT,
    RCSD_ALIGNMENT_SCOPE_CASE,
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_ids(values: Iterable[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def normalize_rcsd_alignment_type(
    value: Any,
    *,
    default: RCSDAlignmentType = RCSD_ALIGNMENT_NONE,
) -> RCSDAlignmentType:
    text = _clean_text(value)
    if text in RCSD_ALIGNMENT_TYPES:
        return text  # type: ignore[return-value]
    return default


def rcsd_match_type_for_alignment(rcsd_alignment_type: Any) -> str:
    alignment = normalize_rcsd_alignment_type(rcsd_alignment_type)
    if alignment == RCSD_ALIGNMENT_SEMANTIC_JUNCTION:
        return "rcsd_junction"
    if alignment in RCSD_ALIGNMENT_FALLBACK_TYPES:
        return "rcsdroad_fallback"
    return "none"


def rcsd_alignment_type_from_selection(
    *,
    positive_rcsd_present: bool,
    required_rcsd_node: Any = None,
    selected_rcsdroad_ids: Iterable[Any] | None = None,
    fallback_rcsdroad_ids: Iterable[Any] | None = None,
    local_rcsd_unit_kind: Any = None,
    positive_rcsd_support_level: Any = None,
    positive_rcsd_consistency_level: Any = None,
    rcsd_decision_reason: Any = None,
    rcsd_selection_mode: Any = None,
) -> RCSDAlignmentType:
    reason = _clean_text(rcsd_decision_reason)
    mode = _clean_text(rcsd_selection_mode)
    support_level = _clean_text(positive_rcsd_support_level)
    consistency_level = _clean_text(positive_rcsd_consistency_level)
    unit_kind = _clean_text(local_rcsd_unit_kind)
    selected_roads = _clean_ids(selected_rcsdroad_ids)
    fallback_roads = _clean_ids(fallback_rcsdroad_ids)
    required_node = _clean_text(required_rcsd_node)
    decision_text = f"{reason}|{mode}".lower()

    if "ambiguous" in decision_text:
        return RCSD_ALIGNMENT_AMBIGUOUS
    if positive_rcsd_present:
        if required_node:
            if "junction_partial" in decision_text or "partial_alignment" in decision_text:
                return RCSD_ALIGNMENT_JUNCTION_PARTIAL
            if len(selected_roads) >= 3:
                return RCSD_ALIGNMENT_SEMANTIC_JUNCTION
            if (
                "partial" in decision_text
                or support_level == "secondary_support"
                or consistency_level == "B"
            ):
                return RCSD_ALIGNMENT_JUNCTION_PARTIAL
            return RCSD_ALIGNMENT_SEMANTIC_JUNCTION
        if selected_roads or unit_kind == "road_only":
            return RCSD_ALIGNMENT_ROAD_ONLY
    if reason in {"positive_rcsd_absent_after_local_units", "local_rcsd_unit_not_constructed"}:
        return RCSD_ALIGNMENT_NONE
    if fallback_roads:
        return RCSD_ALIGNMENT_ROAD_ONLY
    return RCSD_ALIGNMENT_NONE


@dataclass(frozen=True)
class RCSDAlignmentSelection:
    selected_rcsdnode_ids: tuple[str, ...] = ()
    selected_rcsdroad_ids: tuple[str, ...] = ()
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    selected_rcsd_group_id: str | None = None
    required_rcsd_node: str | None = None


@dataclass(frozen=True)
class RCSDAlignmentDecision:
    scope: RCSDAlignmentScope
    scope_id: str
    rcsd_alignment_type: RCSDAlignmentType
    selection: RCSDAlignmentSelection = field(default_factory=RCSDAlignmentSelection)
    decision_reason: str = ""
    candidate_ids: tuple[str, ...] = ()
    audit_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RCSDAlignmentResult:
    scope: RCSDAlignmentScope
    scope_id: str
    rcsd_alignment_type: RCSDAlignmentType
    positive_rcsdroad_ids: tuple[str, ...] = ()
    positive_rcsdnode_ids: tuple[str, ...] = ()
    unrelated_rcsdroad_ids: tuple[str, ...] = ()
    unrelated_rcsdnode_ids: tuple[str, ...] = ()
    candidate_rcsdroad_ids: tuple[str, ...] = ()
    candidate_rcsdnode_ids: tuple[str, ...] = ()
    candidate_alignment_ids: tuple[str, ...] = ()
    ambiguity_reasons: tuple[str, ...] = ()
    conflict_reasons: tuple[str, ...] = ()
    decision_reason: str = ""
    source: str = "step4_frozen_result"

    def to_doc(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "rcsd_alignment_type": self.rcsd_alignment_type,
            "positive_rcsdroad_ids": list(self.positive_rcsdroad_ids),
            "positive_rcsdnode_ids": list(self.positive_rcsdnode_ids),
            "unrelated_rcsdroad_ids": list(self.unrelated_rcsdroad_ids),
            "unrelated_rcsdnode_ids": list(self.unrelated_rcsdnode_ids),
            "candidate_rcsdroad_ids": list(self.candidate_rcsdroad_ids),
            "candidate_rcsdnode_ids": list(self.candidate_rcsdnode_ids),
            "candidate_alignment_ids": list(self.candidate_alignment_ids),
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "conflict_reasons": list(self.conflict_reasons),
            "decision_reason": self.decision_reason,
            "source": self.source,
        }


__all__ = [
    "RCSDAlignmentDecision",
    "RCSDAlignmentResult",
    "RCSDAlignmentScope",
    "RCSDAlignmentSelection",
    "RCSDAlignmentType",
    "RCSD_ALIGNMENT_AMBIGUOUS",
    "RCSD_ALIGNMENT_BLOCKING_TYPES",
    "RCSD_ALIGNMENT_FALLBACK_TYPES",
    "RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES",
    "RCSD_ALIGNMENT_JUNCTION_PARTIAL",
    "RCSD_ALIGNMENT_NONE",
    "RCSD_ALIGNMENT_NO_POSITIVE_TYPES",
    "RCSD_ALIGNMENT_POSITIVE_TYPES",
    "RCSD_ALIGNMENT_RENDER_RCSDROAD_TYPES",
    "RCSD_ALIGNMENT_ROAD_ONLY",
    "RCSD_ALIGNMENT_SCOPE_CASE",
    "RCSD_ALIGNMENT_SCOPE_EVENT_UNIT",
    "RCSD_ALIGNMENT_SCOPES",
    "RCSD_ALIGNMENT_SECTION_REFERENCE_TYPES",
    "RCSD_ALIGNMENT_SEMANTIC_JUNCTION",
    "RCSD_ALIGNMENT_TYPES",
    "normalize_rcsd_alignment_type",
    "rcsd_alignment_type_from_selection",
    "rcsd_match_type_for_alignment",
]
