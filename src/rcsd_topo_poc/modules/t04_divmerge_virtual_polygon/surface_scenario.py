from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


MAIN_EVIDENCE_DIVSTRIP = "divstrip"
MAIN_EVIDENCE_ROAD_SURFACE_FORK = "road_surface_fork"
MAIN_EVIDENCE_NONE = "none"

RCSD_MATCH_JUNCTION = "rcsd_junction"
RCSD_MATCH_ROAD_FALLBACK = "rcsdroad_fallback"
RCSD_MATCH_NONE = "none"

SECTION_REFERENCE_POINT = "reference_point"
SECTION_REFERENCE_POINT_AND_RCSD = "reference_point_and_rcsd_junction"
SECTION_REFERENCE_RCSD = "rcsd_junction"
SECTION_REFERENCE_SWSD = "swsd_junction"
SECTION_REFERENCE_NONE = "none"

SCENARIO_MAIN_WITH_RCSD = "main_evidence_with_rcsd_junction"
SCENARIO_MAIN_WITH_RCSDROAD = "main_evidence_with_rcsdroad_fallback"
SCENARIO_MAIN_WITHOUT_RCSD = "main_evidence_without_rcsd"
SCENARIO_NO_MAIN_WITH_RCSD = "no_main_evidence_with_rcsd_junction"
SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD = "no_main_evidence_with_rcsdroad_fallback_and_swsd"
SCENARIO_NO_MAIN_WITH_SWSD_ONLY = "no_main_evidence_with_swsd_only"
SCENARIO_NO_SURFACE_REFERENCE = "no_surface_reference"

SURFACE_MODE_MAIN_EVIDENCE = "main_evidence_driven"
SURFACE_MODE_RCSD_WINDOW = "rcsd_junction_window"
SURFACE_MODE_SWSD_WINDOW = "swsd_junction_window"
SURFACE_MODE_SWSD_WITH_RCSDROAD = "swsd_with_rcsdroad_fallback"
SURFACE_MODE_NO_SURFACE = "no_surface"


_RCSD_JUNCTION_SOURCES = {"rcsd_junction_window"}
_SWSD_JUNCTION_SOURCES = {"swsd_junction_window"}
_MAIN_DIVSTRIP_SOURCES = {"divstrip_direct", "multibranch_event", "reverse_tip_retry"}
_NON_MAIN_REFERENCE_SOURCES = {
    "rcsd_junction_window",
    "swsd_junction_window",
    "none",
}
_NON_FALLBACK_RCSD_REASONS = {
    "road_surface_fork_structure_only_no_rcsd",
    "road_surface_fork_without_bound_target_rcsd",
    "unbound_road_surface_fork_without_bifurcation_rcsd",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _tuple_str(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    items: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in items:
            items.append(text)
    return tuple(items)


def _mapping_bool(mapping: Mapping[str, Any] | None, key: str) -> bool:
    if not mapping:
        return False
    return bool(mapping.get(key))


def _main_evidence_type(
    *,
    evidence_source: str,
    selected_evidence_summary: Mapping[str, Any] | None,
) -> str:
    if evidence_source in _NON_MAIN_REFERENCE_SOURCES:
        return MAIN_EVIDENCE_NONE
    candidate_scope = _clean_text((selected_evidence_summary or {}).get("candidate_scope"))
    upper_evidence_kind = _clean_text((selected_evidence_summary or {}).get("upper_evidence_kind"))
    if evidence_source == MAIN_EVIDENCE_ROAD_SURFACE_FORK or candidate_scope == MAIN_EVIDENCE_ROAD_SURFACE_FORK:
        return MAIN_EVIDENCE_ROAD_SURFACE_FORK
    if evidence_source in _MAIN_DIVSTRIP_SOURCES or upper_evidence_kind == MAIN_EVIDENCE_DIVSTRIP:
        return MAIN_EVIDENCE_DIVSTRIP
    return MAIN_EVIDENCE_NONE


def _swsd_junction_present(
    *,
    evidence_source: str,
    rcsd_selection_mode: str,
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
    explicit_swsd_junction_present: bool | None,
) -> bool:
    if explicit_swsd_junction_present is not None:
        return bool(explicit_swsd_junction_present)
    if evidence_source in _SWSD_JUNCTION_SOURCES or "swsd_junction_window" in rcsd_selection_mode:
        return True
    if _mapping_bool(positive_rcsd_audit, "swsd_junction_window_no_rcsd"):
        return True
    source_mode = _clean_text((selected_evidence_summary or {}).get("source_mode"))
    return source_mode in _SWSD_JUNCTION_SOURCES


def _fallback_rcsdroad_ids(
    *,
    first_hit_rcsdroad_ids: Sequence[Any] | None,
    selected_rcsdroad_ids: Sequence[Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    audit_roads: Sequence[Any] | None = None
    if positive_rcsd_audit:
        audit_reason = _clean_text(
            positive_rcsd_audit.get("positive_rcsd_present_reason")
            or positive_rcsd_audit.get("rcsd_decision_reason")
        )
        audit_is_non_fallback = (
            positive_rcsd_audit.get("positive_rcsd_present") is False
            and (
                audit_reason in _NON_FALLBACK_RCSD_REASONS
                or any(bool(positive_rcsd_audit.get(key)) for key in _NON_FALLBACK_RCSD_REASONS)
            )
        )
        if not audit_is_non_fallback:
            audit_roads = positive_rcsd_audit.get("published_rcsdroad_ids") or positive_rcsd_audit.get(
                "first_hit_rcsdroad_ids"
            )
    return _tuple_str([*(_tuple_str(selected_rcsdroad_ids)), *(_tuple_str(first_hit_rcsdroad_ids)), *(_tuple_str(audit_roads))])


def _rcsd_match_type(
    *,
    evidence_source: str,
    rcsd_selection_mode: str,
    required_rcsd_node: Any,
    fallback_rcsdroad_ids: tuple[str, ...],
) -> str:
    if evidence_source in _RCSD_JUNCTION_SOURCES or rcsd_selection_mode == "rcsd_junction_window":
        return RCSD_MATCH_JUNCTION
    if _clean_text(required_rcsd_node):
        return RCSD_MATCH_JUNCTION
    if fallback_rcsdroad_ids:
        return RCSD_MATCH_ROAD_FALLBACK
    return RCSD_MATCH_NONE


@dataclass(frozen=True)
class SurfaceScenarioClassification:
    has_main_evidence: bool
    main_evidence_type: str
    reference_point_present: bool
    reference_point_source: str
    section_reference_source: str
    surface_scenario_type: str
    rcsd_match_type: str
    swsd_junction_present: bool
    fallback_rcsdroad_ids: tuple[str, ...]
    surface_generation_mode: str
    no_reference_point_reason: str

    def to_doc(self) -> dict[str, Any]:
        return {
            "has_main_evidence": self.has_main_evidence,
            "main_evidence_type": self.main_evidence_type,
            "reference_point_present": self.reference_point_present,
            "reference_point_source": self.reference_point_source,
            "section_reference_source": self.section_reference_source,
            "surface_scenario_type": self.surface_scenario_type,
            "rcsd_match_type": self.rcsd_match_type,
            "swsd_junction_present": self.swsd_junction_present,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "surface_generation_mode": self.surface_generation_mode,
            "no_reference_point_reason": self.no_reference_point_reason,
        }


def classify_surface_scenario(
    *,
    evidence_source: str = "",
    selected_evidence_summary: Mapping[str, Any] | None = None,
    rcsd_selection_mode: str = "",
    required_rcsd_node: Any = None,
    first_hit_rcsdroad_ids: Sequence[Any] | None = None,
    selected_rcsdroad_ids: Sequence[Any] | None = None,
    positive_rcsd_audit: Mapping[str, Any] | None = None,
    swsd_junction_present: bool | None = None,
    fact_reference_point_present: bool | None = None,
) -> SurfaceScenarioClassification:
    evidence_source = _clean_text(evidence_source)
    rcsd_selection_mode = _clean_text(rcsd_selection_mode)
    main_evidence_type = _main_evidence_type(
        evidence_source=evidence_source,
        selected_evidence_summary=selected_evidence_summary,
    )
    has_main_evidence = main_evidence_type != MAIN_EVIDENCE_NONE
    fallback_ids = _fallback_rcsdroad_ids(
        first_hit_rcsdroad_ids=first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=selected_rcsdroad_ids,
        positive_rcsd_audit=positive_rcsd_audit,
    )
    rcsd_match_type = _rcsd_match_type(
        evidence_source=evidence_source,
        rcsd_selection_mode=rcsd_selection_mode,
        required_rcsd_node=required_rcsd_node,
        fallback_rcsdroad_ids=fallback_ids,
    )
    swsd_present = _swsd_junction_present(
        evidence_source=evidence_source,
        rcsd_selection_mode=rcsd_selection_mode,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
        explicit_swsd_junction_present=swsd_junction_present,
    )

    reference_point_present = has_main_evidence and fact_reference_point_present is not False
    reference_point_source = main_evidence_type if reference_point_present else MAIN_EVIDENCE_NONE
    if has_main_evidence and not reference_point_present:
        no_reference_point_reason = "missing_reference_point_geometry"
    elif not has_main_evidence:
        no_reference_point_reason = "no_main_evidence"
    else:
        no_reference_point_reason = "none"

    if has_main_evidence:
        if rcsd_match_type == RCSD_MATCH_JUNCTION:
            scenario = SCENARIO_MAIN_WITH_RCSD
            section_reference_source = SECTION_REFERENCE_POINT_AND_RCSD
        elif rcsd_match_type == RCSD_MATCH_ROAD_FALLBACK:
            scenario = SCENARIO_MAIN_WITH_RCSDROAD
            section_reference_source = SECTION_REFERENCE_POINT
        else:
            scenario = SCENARIO_MAIN_WITHOUT_RCSD
            section_reference_source = SECTION_REFERENCE_POINT
        surface_generation_mode = SURFACE_MODE_MAIN_EVIDENCE
    elif rcsd_match_type == RCSD_MATCH_JUNCTION:
        scenario = SCENARIO_NO_MAIN_WITH_RCSD
        section_reference_source = SECTION_REFERENCE_RCSD
        surface_generation_mode = SURFACE_MODE_RCSD_WINDOW
    elif rcsd_match_type == RCSD_MATCH_ROAD_FALLBACK and swsd_present:
        scenario = SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD
        section_reference_source = SECTION_REFERENCE_SWSD
        surface_generation_mode = SURFACE_MODE_SWSD_WITH_RCSDROAD
    elif swsd_present:
        scenario = SCENARIO_NO_MAIN_WITH_SWSD_ONLY
        section_reference_source = SECTION_REFERENCE_SWSD
        surface_generation_mode = SURFACE_MODE_SWSD_WINDOW
    else:
        scenario = SCENARIO_NO_SURFACE_REFERENCE
        section_reference_source = SECTION_REFERENCE_NONE
        surface_generation_mode = SURFACE_MODE_NO_SURFACE
        no_reference_point_reason = "no_surface_reference"

    return SurfaceScenarioClassification(
        has_main_evidence=has_main_evidence,
        main_evidence_type=main_evidence_type,
        reference_point_present=reference_point_present,
        reference_point_source=reference_point_source,
        section_reference_source=section_reference_source,
        surface_scenario_type=scenario,
        rcsd_match_type=rcsd_match_type,
        swsd_junction_present=swsd_present,
        fallback_rcsdroad_ids=fallback_ids if rcsd_match_type == RCSD_MATCH_ROAD_FALLBACK else (),
        surface_generation_mode=surface_generation_mode,
        no_reference_point_reason=no_reference_point_reason,
    )
