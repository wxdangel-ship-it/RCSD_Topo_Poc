from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .rcsd_alignment import (
    RCSD_ALIGNMENT_AMBIGUOUS,
    RCSD_ALIGNMENT_JUNCTION_PARTIAL,
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_ROAD_ONLY,
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
    normalize_rcsd_alignment_type,
    rcsd_alignment_type_from_selection,
    rcsd_match_type_for_alignment,
)


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
_SWSD_WINDOW_NO_RCSD_REASON = "swsd_junction_window_no_rcsd"
_WEAK_ROAD_SURFACE_FORK_LOCAL_BINDING = "road_surface_fork_rcsd_junction_local_unit_binding"
_WEAK_ROAD_SURFACE_FORK_LOCAL_REQUIRED_NODE_MAX_DISTANCE_M = 60.0
_RCSD_JUNCTION_WINDOW_MAX_SEMANTIC_ANCHOR_DISTANCE_M = 60.0
_WEAK_DIVSTRIP_SWSD_REASONS = {
    "aggregated_axis_polarity_inverted_without_required_node",
    "aggregated_road_only_without_required_node",
    "positive_rcsd_absent_after_local_units",
    "role_mapping_partial_axis_polarity_inverted",
}


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


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


def _support_level(
    *,
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
) -> str:
    return _clean_text(
        (positive_rcsd_audit or {}).get("positive_rcsd_support_level")
        or (selected_evidence_summary or {}).get("positive_rcsd_support_level")
    )


def _consistency_level(
    *,
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
) -> str:
    return _clean_text(
        (positive_rcsd_audit or {}).get("positive_rcsd_consistency_level")
        or (selected_evidence_summary or {}).get("positive_rcsd_consistency_level")
    )


def _weak_road_surface_fork_local_binding(
    *,
    rcsd_selection_mode: str,
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
) -> bool:
    if rcsd_selection_mode != _WEAK_ROAD_SURFACE_FORK_LOCAL_BINDING:
        return False
    binding = (positive_rcsd_audit or {}).get("road_surface_fork_binding") or (
        selected_evidence_summary or {}
    ).get("road_surface_fork_binding")
    if not isinstance(binding, Mapping):
        return False
    return bool(
        binding.get("preserved_surface_main_evidence") is True
        and _clean_text(binding.get("selected_rcsd_scope")) == "required_node_local_unit"
        and _clean_text(binding.get("rcsd_decision_reason")) == "role_mapping_partial_relaxed_aggregated"
        and _support_level(
            selected_evidence_summary=selected_evidence_summary,
            positive_rcsd_audit=positive_rcsd_audit,
        )
        == "secondary_support"
        and _consistency_level(
            selected_evidence_summary=selected_evidence_summary,
            positive_rcsd_audit=positive_rcsd_audit,
        )
        == "B"
    )


def _weak_road_surface_fork_required_node_is_local(distance_m: float | None) -> bool:
    if distance_m is None:
        return False
    return float(distance_m) <= _WEAK_ROAD_SURFACE_FORK_LOCAL_REQUIRED_NODE_MAX_DISTANCE_M


def _weak_divstrip_swsd_window_candidate(
    *,
    evidence_source: str,
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
) -> bool:
    if evidence_source not in _MAIN_DIVSTRIP_SOURCES:
        return False
    if _clean_text((selected_evidence_summary or {}).get("upper_evidence_kind")) != MAIN_EVIDENCE_DIVSTRIP:
        return False
    if bool((selected_evidence_summary or {}).get("primary_eligible")):
        return False
    reason = _clean_text(
        (positive_rcsd_audit or {}).get("rcsd_decision_reason")
        or (positive_rcsd_audit or {}).get("positive_rcsd_present_reason")
        or (selected_evidence_summary or {}).get("positive_rcsd_present_reason")
    )
    if reason in _WEAK_DIVSTRIP_SWSD_REASONS:
        return True
    aggregated_units = (positive_rcsd_audit or {}).get("aggregated_rcsd_units") or ()
    for unit in aggregated_units:
        if not isinstance(unit, Mapping):
            continue
        member_kinds = {_clean_text(item) for item in (unit.get("member_unit_kinds") or ())}
        if (
            member_kinds
            and member_kinds <= {"road_only"}
            and not _clean_text(unit.get("required_node_id"))
            and _clean_text(unit.get("support_level")) == "secondary_support"
            and _clean_text(unit.get("consistency_level")) == "B"
        ):
            return True
    return False


def _selected_aggregate_semantic_anchor_distance_m(
    positive_rcsd_audit: Mapping[str, Any] | None,
) -> float | None:
    if not positive_rcsd_audit:
        return None
    selected_unit_id = _clean_text(positive_rcsd_audit.get("aggregated_rcsd_unit_id"))
    if not selected_unit_id:
        return None
    for unit in positive_rcsd_audit.get("aggregated_rcsd_units") or ():
        if not isinstance(unit, Mapping):
            continue
        if _clean_text(unit.get("unit_id")) != selected_unit_id:
            continue
        value = unit.get("semantic_anchor_distance_m")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _unit_doc_by_id(
    units: Sequence[Any] | None,
    unit_id: str,
) -> Mapping[str, Any] | None:
    if not unit_id:
        return None
    for unit in units or ():
        if not isinstance(unit, Mapping):
            continue
        if _clean_text(unit.get("unit_id")) == unit_id:
            return unit
    return None


def _road_ids_from_unit(unit: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not unit:
        return ()
    return _tuple_str(unit.get("road_ids"))


def _unique_swsd_window_fallback_roads(
    positive_rcsd_audit: Mapping[str, Any],
) -> tuple[str, ...]:
    local_units = tuple(
        unit for unit in (positive_rcsd_audit.get("local_rcsd_units") or ()) if isinstance(unit, Mapping)
    )
    aggregate_units = tuple(
        unit for unit in (positive_rcsd_audit.get("aggregated_rcsd_units") or ()) if isinstance(unit, Mapping)
    )
    member_ids = _tuple_str(positive_rcsd_audit.get("published_member_unit_ids"))
    if len(member_ids) == 1:
        member_unit = _unit_doc_by_id(local_units, member_ids[0]) or _unit_doc_by_id(
            aggregate_units,
            member_ids[0],
        )
        member_roads = _road_ids_from_unit(member_unit)
        if member_roads:
            return member_roads

    aggregate_id = _clean_text(positive_rcsd_audit.get("aggregated_rcsd_unit_id"))
    aggregate = _unit_doc_by_id(aggregate_units, aggregate_id)
    if aggregate:
        primary_unit_id = _clean_text(aggregate.get("primary_local_unit_id"))
        primary_roads = _road_ids_from_unit(_unit_doc_by_id(local_units, primary_unit_id))
        if primary_roads:
            return primary_roads
        aggregate_member_ids = _tuple_str(aggregate.get("member_unit_ids"))
        if len(aggregate_member_ids) == 1:
            member_roads = _road_ids_from_unit(_unit_doc_by_id(local_units, aggregate_member_ids[0]))
            if member_roads:
                return member_roads

    positive_local_units = tuple(
        unit for unit in local_units if bool(unit.get("positive_rcsd_present"))
    )
    if len(positive_local_units) == 1:
        return _road_ids_from_unit(positive_local_units[0])
    return ()


def _main_evidence_type(
    *,
    evidence_source: str,
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
    rcsd_selection_mode: str,
) -> str:
    if evidence_source in _NON_MAIN_REFERENCE_SOURCES:
        return MAIN_EVIDENCE_NONE
    if _weak_road_surface_fork_local_binding(
        rcsd_selection_mode=rcsd_selection_mode,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
    ):
        return MAIN_EVIDENCE_NONE
    if _weak_divstrip_swsd_window_candidate(
        evidence_source=evidence_source,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
    ):
        return MAIN_EVIDENCE_NONE
    source_mode = _clean_text((selected_evidence_summary or {}).get("source_mode"))
    if "swsd_junction_window" in rcsd_selection_mode or source_mode in _SWSD_JUNCTION_SOURCES:
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
    if _weak_road_surface_fork_local_binding(
        rcsd_selection_mode=rcsd_selection_mode,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
    ):
        return True
    if _weak_divstrip_swsd_window_candidate(
        evidence_source=evidence_source,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
    ):
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
        published_roads = _tuple_str(positive_rcsd_audit.get("published_rcsdroad_ids"))
        audit_reasons = {
            _clean_text(positive_rcsd_audit.get("positive_rcsd_present_reason")),
            _clean_text(positive_rcsd_audit.get("rcsd_decision_reason")),
        }
        audit_reasons.discard("")
        swsd_window_rcsdroad_alignment = bool(
            published_roads and _SWSD_WINDOW_NO_RCSD_REASON in audit_reasons
        )
        audit_is_non_fallback = (
            positive_rcsd_audit.get("positive_rcsd_present") is False
            and (
                bool(audit_reasons & _NON_FALLBACK_RCSD_REASONS)
                or bool(audit_reasons & _WEAK_DIVSTRIP_SWSD_REASONS)
                or any(bool(positive_rcsd_audit.get(key)) for key in _NON_FALLBACK_RCSD_REASONS)
            )
            and not swsd_window_rcsdroad_alignment
        ) or (
            bool(audit_reasons & _WEAK_DIVSTRIP_SWSD_REASONS)
            and not _clean_text(positive_rcsd_audit.get("required_rcsd_node"))
            and _clean_text(positive_rcsd_audit.get("local_rcsd_unit_kind")) == "road_only"
            and not swsd_window_rcsdroad_alignment
        )
        if audit_is_non_fallback:
            return ()
        if swsd_window_rcsdroad_alignment:
            audit_roads = _unique_swsd_window_fallback_roads(positive_rcsd_audit)
        elif not audit_is_non_fallback:
            audit_roads = published_roads or positive_rcsd_audit.get("first_hit_rcsdroad_ids")
    return _tuple_str([*(_tuple_str(selected_rcsdroad_ids)), *(_tuple_str(first_hit_rcsdroad_ids)), *(_tuple_str(audit_roads))])


def _rcsd_match_type(
    *,
    evidence_source: str,
    rcsd_selection_mode: str,
    required_rcsd_node: Any,
    fallback_rcsdroad_ids: tuple[str, ...],
    selected_evidence_summary: Mapping[str, Any] | None,
    positive_rcsd_audit: Mapping[str, Any] | None,
    required_rcsd_node_distance_to_representative_m: float | None,
) -> str:
    if _weak_road_surface_fork_local_binding(
        rcsd_selection_mode=rcsd_selection_mode,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
    ):
        if _clean_text(required_rcsd_node) and _weak_road_surface_fork_required_node_is_local(
            required_rcsd_node_distance_to_representative_m
        ):
            return RCSD_MATCH_JUNCTION
        return RCSD_MATCH_NONE
    if _weak_divstrip_swsd_window_candidate(
        evidence_source=evidence_source,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
    ):
        return RCSD_MATCH_ROAD_FALLBACK if fallback_rcsdroad_ids else RCSD_MATCH_NONE
    if evidence_source in _RCSD_JUNCTION_SOURCES or rcsd_selection_mode == "rcsd_junction_window":
        semantic_anchor_distance_m = _selected_aggregate_semantic_anchor_distance_m(positive_rcsd_audit)
        if (
            semantic_anchor_distance_m is not None
            and semantic_anchor_distance_m > _RCSD_JUNCTION_WINDOW_MAX_SEMANTIC_ANCHOR_DISTANCE_M
        ):
            return RCSD_MATCH_NONE
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
    rcsd_alignment_type: str
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
            "rcsd_alignment_type": self.rcsd_alignment_type,
            "rcsd_match_type": self.rcsd_match_type,
            "swsd_junction_present": self.swsd_junction_present,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "surface_generation_mode": self.surface_generation_mode,
            "no_reference_point_reason": self.no_reference_point_reason,
        }


def classify_surface_scenario_from_alignment(
    *,
    has_main_evidence: bool,
    rcsd_alignment_type: str,
    swsd_junction_present: bool,
    main_evidence_type: str | None = None,
    reference_point_present: bool | None = None,
    fallback_rcsdroad_ids: Sequence[Any] | None = None,
    no_reference_point_reason: str | None = None,
) -> SurfaceScenarioClassification:
    alignment_type = normalize_rcsd_alignment_type(rcsd_alignment_type)
    if alignment_type == RCSD_ALIGNMENT_AMBIGUOUS:
        return SurfaceScenarioClassification(
            has_main_evidence=bool(has_main_evidence),
            main_evidence_type=_clean_text(main_evidence_type, MAIN_EVIDENCE_NONE),
            reference_point_present=False,
            reference_point_source=MAIN_EVIDENCE_NONE,
            section_reference_source=SECTION_REFERENCE_NONE,
            surface_scenario_type=SCENARIO_NO_SURFACE_REFERENCE,
            rcsd_alignment_type=alignment_type,
            rcsd_match_type="none",
            swsd_junction_present=bool(swsd_junction_present),
            fallback_rcsdroad_ids=(),
            surface_generation_mode=SURFACE_MODE_NO_SURFACE,
            no_reference_point_reason=RCSD_ALIGNMENT_AMBIGUOUS,
        )
    has_main = bool(has_main_evidence)
    main_type = _clean_text(main_evidence_type, MAIN_EVIDENCE_NONE) if has_main else MAIN_EVIDENCE_NONE
    if has_main and main_type == MAIN_EVIDENCE_NONE:
        main_type = MAIN_EVIDENCE_DIVSTRIP
    ref_present = has_main if reference_point_present is None else bool(reference_point_present and has_main)
    ref_source = main_type if ref_present else MAIN_EVIDENCE_NONE
    if has_main and not ref_present:
        no_ref_reason = "missing_reference_point_geometry"
    elif not has_main:
        no_ref_reason = "no_main_evidence"
    else:
        no_ref_reason = "none"
    if no_reference_point_reason:
        no_ref_reason = str(no_reference_point_reason)

    if has_main:
        if alignment_type == RCSD_ALIGNMENT_SEMANTIC_JUNCTION:
            scenario = SCENARIO_MAIN_WITH_RCSD
            section_reference_source = SECTION_REFERENCE_POINT_AND_RCSD
        elif alignment_type == RCSD_ALIGNMENT_JUNCTION_PARTIAL:
            scenario = SCENARIO_MAIN_WITH_RCSDROAD
            section_reference_source = SECTION_REFERENCE_POINT_AND_RCSD
        elif alignment_type == RCSD_ALIGNMENT_ROAD_ONLY:
            scenario = SCENARIO_MAIN_WITH_RCSDROAD
            section_reference_source = SECTION_REFERENCE_POINT
        else:
            scenario = SCENARIO_MAIN_WITHOUT_RCSD
            section_reference_source = SECTION_REFERENCE_POINT
        surface_generation_mode = SURFACE_MODE_MAIN_EVIDENCE
    elif alignment_type == RCSD_ALIGNMENT_SEMANTIC_JUNCTION:
        scenario = SCENARIO_NO_MAIN_WITH_RCSD
        section_reference_source = SECTION_REFERENCE_RCSD
        surface_generation_mode = SURFACE_MODE_RCSD_WINDOW
    elif alignment_type == RCSD_ALIGNMENT_JUNCTION_PARTIAL:
        scenario = SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD
        section_reference_source = SECTION_REFERENCE_RCSD
        surface_generation_mode = SURFACE_MODE_RCSD_WINDOW
    elif alignment_type == RCSD_ALIGNMENT_ROAD_ONLY and swsd_junction_present:
        scenario = SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD
        section_reference_source = SECTION_REFERENCE_SWSD
        surface_generation_mode = SURFACE_MODE_SWSD_WITH_RCSDROAD
    elif alignment_type == RCSD_ALIGNMENT_NONE and swsd_junction_present:
        scenario = SCENARIO_NO_MAIN_WITH_SWSD_ONLY
        section_reference_source = SECTION_REFERENCE_SWSD
        surface_generation_mode = SURFACE_MODE_SWSD_WINDOW
    else:
        scenario = SCENARIO_NO_SURFACE_REFERENCE
        section_reference_source = SECTION_REFERENCE_NONE
        surface_generation_mode = SURFACE_MODE_NO_SURFACE
        no_ref_reason = "no_surface_reference"

    fallback_ids = _tuple_str(fallback_rcsdroad_ids) if alignment_type == RCSD_ALIGNMENT_ROAD_ONLY else ()
    return SurfaceScenarioClassification(
        has_main_evidence=has_main,
        main_evidence_type=main_type,
        reference_point_present=ref_present,
        reference_point_source=ref_source,
        section_reference_source=section_reference_source,
        surface_scenario_type=scenario,
        rcsd_alignment_type=alignment_type,
        rcsd_match_type=rcsd_match_type_for_alignment(alignment_type),
        swsd_junction_present=bool(swsd_junction_present),
        fallback_rcsdroad_ids=fallback_ids,
        surface_generation_mode=surface_generation_mode,
        no_reference_point_reason=no_ref_reason,
    )


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
    required_rcsd_node_distance_to_representative_m: float | None = None,
    rcsd_alignment_type: str | None = None,
) -> SurfaceScenarioClassification:
    evidence_source = _clean_text(evidence_source)
    rcsd_selection_mode = _clean_text(rcsd_selection_mode)
    main_evidence_type = _main_evidence_type(
        evidence_source=evidence_source,
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
        rcsd_selection_mode=rcsd_selection_mode,
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
        selected_evidence_summary=selected_evidence_summary,
        positive_rcsd_audit=positive_rcsd_audit,
        required_rcsd_node_distance_to_representative_m=required_rcsd_node_distance_to_representative_m,
    )
    raw_alignment_type = (
        rcsd_alignment_type
        or (positive_rcsd_audit or {}).get("rcsd_alignment_type")
        or (selected_evidence_summary or {}).get("rcsd_alignment_type")
    )
    if (
        normalize_rcsd_alignment_type(raw_alignment_type) == RCSD_ALIGNMENT_NONE
        and (
            rcsd_match_type != RCSD_MATCH_NONE
            or (_clean_text(required_rcsd_node) and _tuple_str(selected_rcsdroad_ids))
        )
    ):
        raw_alignment_type = None
    alignment_type = normalize_rcsd_alignment_type(
        raw_alignment_type,
        default=rcsd_alignment_type_from_selection(
            positive_rcsd_present=rcsd_match_type == RCSD_MATCH_JUNCTION,
            required_rcsd_node=required_rcsd_node,
            selected_rcsdroad_ids=selected_rcsdroad_ids,
            fallback_rcsdroad_ids=fallback_ids if rcsd_match_type == RCSD_MATCH_ROAD_FALLBACK else (),
            local_rcsd_unit_kind=(positive_rcsd_audit or {}).get("local_rcsd_unit_kind"),
            positive_rcsd_support_level=_support_level(
                selected_evidence_summary=selected_evidence_summary,
                positive_rcsd_audit=positive_rcsd_audit,
            ),
            positive_rcsd_consistency_level=_consistency_level(
                selected_evidence_summary=selected_evidence_summary,
                positive_rcsd_audit=positive_rcsd_audit,
            ),
            rcsd_decision_reason=(positive_rcsd_audit or {}).get("rcsd_decision_reason"),
            rcsd_selection_mode=rcsd_selection_mode,
        ),
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

    return classify_surface_scenario_from_alignment(
        has_main_evidence=has_main_evidence,
        main_evidence_type=main_evidence_type,
        reference_point_present=reference_point_present,
        rcsd_alignment_type=alignment_type,
        swsd_junction_present=swsd_present,
        no_reference_point_reason=no_reference_point_reason,
        fallback_rcsdroad_ids=fallback_ids,
    )
