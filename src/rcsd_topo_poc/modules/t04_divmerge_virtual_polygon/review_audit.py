from __future__ import annotations

from typing import Any

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from .event_interpretation_selection import (
    EVENT_REFERENCE_CONFLICT_TOL_M,
    SHARED_EVIDENCE_OVERLAP_AREA_M2,
    SHARED_EVIDENCE_OVERLAP_RATIO,
    _candidate_axis_position,
    _event_axis_signature,
)
from .event_interpretation_shared import _geometry_present, _safe_normalize_geometry


REFERENCE_ZONE_ORDER = {
    "throat": 4,
    "middle": 3,
    "edge": 2,
    "outside": 1,
    "missing": 0,
}


def _reference_point(event_unit: T04EventUnitResult):
    return event_unit.fact_reference_point or event_unit.review_materialized_point


def _classify_reference_zone(
    *,
    point_geometry,
    throat_core_geometry,
    pair_middle_geometry,
    pair_local_region_geometry,
) -> str:
    if not _geometry_present(point_geometry):
        return "missing"
    point = point_geometry
    if getattr(point, "geom_type", None) != "Point":
        point = point.representative_point()
    if not _geometry_present(point):
        return "missing"
    for zone_name, zone_geometry in (
        ("throat", throat_core_geometry),
        ("middle", pair_middle_geometry),
        ("edge", pair_local_region_geometry),
    ):
        if not _geometry_present(zone_geometry):
            continue
        if zone_geometry.buffer(1e-6).covers(point):
            return zone_name
    return "outside"


def _geometry_overlap_ratio(geometry, scope_geometry) -> float:
    if not _geometry_present(geometry) or not _geometry_present(scope_geometry):
        return 0.0
    try:
        overlap = geometry.intersection(scope_geometry)
    except Exception:
        return 0.0
    overlap_area = float(getattr(overlap, "area", 0.0) or 0.0)
    geometry_area = float(getattr(geometry, "area", 0.0) or 0.0)
    if geometry_area <= 1e-6 or overlap_area <= 1e-6:
        return 0.0
    return overlap_area / geometry_area


def _classify_evidence_membership(
    *,
    evidence_geometry,
    pair_middle_geometry,
    structure_face_geometry,
    pair_local_region_geometry,
) -> str:
    if not _geometry_present(evidence_geometry):
        return "missing"
    if _geometry_present(pair_middle_geometry) and pair_middle_geometry.buffer(1e-6).covers(evidence_geometry):
        return "inside_middle"
    if _geometry_overlap_ratio(evidence_geometry, pair_middle_geometry) >= 0.5:
        return "mostly_middle"
    if _geometry_present(structure_face_geometry) and structure_face_geometry.buffer(1e-6).covers(evidence_geometry):
        return "inside_structure_face"
    if _geometry_present(pair_local_region_geometry) and pair_local_region_geometry.buffer(1e-6).covers(evidence_geometry):
        return "inside_pair_region"
    if _geometry_overlap_ratio(evidence_geometry, pair_local_region_geometry) > 0.0:
        return "partial_outside_pair_region"
    return "outside_pair_region"


def _signal_units_from_reasons(event_unit: T04EventUnitResult, prefix: str) -> set[str]:
    result: set[str] = set()
    for reason in event_unit.all_review_reasons():
        text = str(reason)
        if not text.startswith(prefix):
            continue
        _, _, unit_id = text.partition(":")
        unit_id = unit_id.strip()
        if unit_id:
            result.add(unit_id)
    return result


def _same_axis_separated(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> bool:
    lhs_axis = _event_axis_signature(lhs)
    rhs_axis = _event_axis_signature(rhs)
    lhs_basis, lhs_position = _candidate_axis_position(lhs)
    rhs_basis, rhs_position = _candidate_axis_position(rhs)
    lhs_s = lhs_position if lhs_position is not None else (None if lhs.event_chosen_s_m is None else float(lhs.event_chosen_s_m))
    rhs_s = rhs_position if rhs_position is not None else (None if rhs.event_chosen_s_m is None else float(rhs.event_chosen_s_m))
    return bool(
        lhs_axis is not None
        and rhs_axis is not None
        and lhs_axis == rhs_axis
        and lhs_s is not None
        and rhs_s is not None
        and (lhs_basis is None or rhs_basis is None or lhs_basis == rhs_basis)
        and abs(lhs_s - rhs_s) > EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9
    )


def _has_region_overlap(lhs_geometry, rhs_geometry) -> bool:
    if not _geometry_present(lhs_geometry) or not _geometry_present(rhs_geometry):
        return False
    overlap = _safe_normalize_geometry(lhs_geometry.intersection(rhs_geometry))
    overlap_area = float(getattr(overlap, "area", 0.0) or 0.0) if overlap is not None else 0.0
    lhs_area = float(getattr(lhs_geometry, "area", 0.0) or 0.0)
    rhs_area = float(getattr(rhs_geometry, "area", 0.0) or 0.0)
    smaller_area = min(lhs_area, rhs_area)
    overlap_ratio = 0.0 if smaller_area <= 1e-6 else overlap_area / smaller_area
    return overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2 or overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO


def _candidate_entry_reference_zone(
    *,
    event_unit: T04EventUnitResult,
    candidate_entry: T04CandidateAuditEntry,
) -> str:
    return _classify_reference_zone(
        point_geometry=candidate_entry.fact_reference_point or candidate_entry.review_materialized_point,
        throat_core_geometry=event_unit.pair_local_throat_core_geometry,
        pair_middle_geometry=event_unit.pair_local_middle_geometry,
        pair_local_region_geometry=event_unit.pair_local_region_geometry,
    )


def _select_candidate_shortlist(
    event_unit: T04EventUnitResult,
    *,
    limit: int = 4,
) -> tuple[T04CandidateAuditEntry, ...]:
    entries = list(event_unit.candidate_audit_entries)
    if not entries:
        return ()
    selected_id = str(event_unit.selected_evidence_summary.get("candidate_id") or "")
    selected_entry = next((entry for entry in entries if entry.candidate_id == selected_id), entries[0])
    other_entries = [entry for entry in entries if entry.candidate_id != selected_entry.candidate_id]
    other_entries.sort(
        key=lambda entry: (
            int(entry.pool_rank),
            int(entry.candidate_summary.get("layer", 9) or 9),
            -int(entry.priority_score),
            entry.candidate_id,
        )
    )
    shortlist: list[T04CandidateAuditEntry] = [selected_entry]
    seen_candidate_ids = {selected_entry.candidate_id}
    for entry in other_entries:
        if len(shortlist) >= limit:
            break
        if entry.candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(entry.candidate_id)
        shortlist.append(entry)
    return tuple(shortlist)


def _best_alternative_signal(
    event_unit: T04EventUnitResult,
    shortlist: tuple[T04CandidateAuditEntry, ...],
) -> tuple[bool, str, T04CandidateAuditEntry | None]:
    selected_id = str(event_unit.selected_evidence_summary.get("candidate_id") or "")
    selected_rank = event_unit.selected_evidence_summary.get("selection_rank")
    selected_layer = int(event_unit.selected_evidence_summary.get("layer", 9) or 9)
    selected_priority = next(
        (
            entry.priority_score
            for entry in event_unit.candidate_audit_entries
            if entry.candidate_id == selected_id
        ),
        0,
    )
    selected_zone = _classify_reference_zone(
        point_geometry=_reference_point(event_unit),
        throat_core_geometry=event_unit.pair_local_throat_core_geometry,
        pair_middle_geometry=event_unit.pair_local_middle_geometry,
        pair_local_region_geometry=event_unit.pair_local_region_geometry,
    )
    alternatives = [entry for entry in shortlist if entry.candidate_id != selected_id]
    if not alternatives:
        return False, "", None
    best_alt = alternatives[0]
    alt_layer = int(best_alt.candidate_summary.get("layer", 9) or 9)
    alt_zone = _candidate_entry_reference_zone(event_unit=event_unit, candidate_entry=best_alt)
    alt_zone_rank = REFERENCE_ZONE_ORDER.get(alt_zone, 0)
    selected_zone_rank = REFERENCE_ZONE_ORDER.get(selected_zone, 0)
    if isinstance(selected_rank, int) and best_alt.pool_rank < selected_rank:
        return True, "higher_raw_rank_rejected_in_case_reselection", best_alt
    if alt_layer < selected_layer:
        return True, "higher_layer_alternative_exists", best_alt
    if alt_layer == selected_layer and alt_zone_rank > selected_zone_rank and best_alt.priority_score >= selected_priority - 60:
        return True, "same_layer_alternative_closer_to_throat_or_middle", best_alt
    if alt_layer == selected_layer and best_alt.priority_score > selected_priority + 40:
        return True, "same_layer_priority_gap", best_alt
    return False, "", best_alt


def _key_reason(event_unit: T04EventUnitResult, focus_reasons: list[str], better_alt_reason: str) -> str:
    if event_unit.all_review_reasons():
        return str(event_unit.all_review_reasons()[0])
    if better_alt_reason:
        return better_alt_reason
    if focus_reasons:
        return focus_reasons[0]
    return str(event_unit.selected_evidence_summary.get("layer_reason") or "")


def build_case_review_audit(case_result: T04CaseResult) -> dict[str, dict[str, Any]]:
    event_units = {unit.spec.event_unit_id: unit for unit in case_result.event_units}
    shared_object_units: dict[str, set[str]] = {unit_id: set() for unit_id in event_units}
    shared_region_units: dict[str, set[str]] = {unit_id: set() for unit_id in event_units}
    shared_point_units: dict[str, set[str]] = {unit_id: set() for unit_id in event_units}

    object_key_to_units: dict[tuple[str, str], list[str]] = {}
    for unit in case_result.event_units:
        kind = str(unit.selected_evidence_summary.get("upper_evidence_kind") or "")
        object_id = str(unit.selected_evidence_summary.get("upper_evidence_object_id") or "")
        if kind and object_id:
            object_key_to_units.setdefault((kind, object_id), []).append(unit.spec.event_unit_id)

    for unit_ids in object_key_to_units.values():
        if len(unit_ids) < 2:
            continue
        for unit_id in unit_ids:
            shared_object_units[unit_id].update(other for other in unit_ids if other != unit_id)

    ordered_units = list(case_result.event_units)
    for left_index, lhs in enumerate(ordered_units):
        for rhs in ordered_units[left_index + 1 :]:
            if _same_axis_separated(lhs, rhs):
                continue
            if (
                str(lhs.selected_evidence_summary.get("point_signature") or "")
                and str(lhs.selected_evidence_summary.get("point_signature") or "")
                == str(rhs.selected_evidence_summary.get("point_signature") or "")
            ):
                shared_point_units[lhs.spec.event_unit_id].add(rhs.spec.event_unit_id)
                shared_point_units[rhs.spec.event_unit_id].add(lhs.spec.event_unit_id)
            if _has_region_overlap(lhs.selected_component_union_geometry, rhs.selected_component_union_geometry) or _has_region_overlap(
                lhs.localized_evidence_core_geometry,
                rhs.localized_evidence_core_geometry,
            ):
                shared_region_units[lhs.spec.event_unit_id].add(rhs.spec.event_unit_id)
                shared_region_units[rhs.spec.event_unit_id].add(lhs.spec.event_unit_id)

    summaries: dict[str, dict[str, Any]] = {}
    for unit in case_result.event_units:
        unit_id = unit.spec.event_unit_id
        shortlist = _select_candidate_shortlist(unit)
        better_alt_signal, better_alt_reason, best_alt = _best_alternative_signal(unit, shortlist)
        selected_reference_zone = _classify_reference_zone(
            point_geometry=_reference_point(unit),
            throat_core_geometry=unit.pair_local_throat_core_geometry,
            pair_middle_geometry=unit.pair_local_middle_geometry,
            pair_local_region_geometry=unit.pair_local_region_geometry,
        )
        evidence_geometry = (
            unit.localized_evidence_core_geometry
            or unit.selected_component_union_geometry
            or unit.selected_evidence_region_geometry
            or unit.selected_candidate_region_geometry
        )
        selected_evidence_membership = _classify_evidence_membership(
            evidence_geometry=evidence_geometry,
            pair_middle_geometry=unit.pair_local_middle_geometry,
            structure_face_geometry=unit.pair_local_structure_face_geometry,
            pair_local_region_geometry=unit.pair_local_region_geometry,
        )
        reason_region_units = (
            _signal_units_from_reasons(unit, "shared_divstrip_component_with:")
            | _signal_units_from_reasons(unit, "shared_event_core_segment_with:")
        )
        reason_point_units = _signal_units_from_reasons(unit, "shared_event_reference_with:")
        shared_region_ids = sorted(shared_region_units[unit_id] | reason_region_units)
        shared_point_ids = sorted(shared_point_units[unit_id] | reason_point_units)
        shared_object_ids = sorted(shared_object_units[unit_id])

        focus_reasons: list[str] = []
        if unit.review_state != "STEP4_OK":
            focus_reasons.append(f"review_state:{unit.review_state}")
        if selected_reference_zone in {"edge", "outside", "missing"}:
            focus_reasons.append(f"selected_reference_zone:{selected_reference_zone}")
        if selected_evidence_membership in {"partial_outside_pair_region", "outside_pair_region", "missing"}:
            focus_reasons.append(f"selected_evidence_membership:{selected_evidence_membership}")
        if better_alt_signal and better_alt_reason:
            focus_reasons.append(f"better_alternative_signal:{better_alt_reason}")
        if shared_point_ids:
            focus_reasons.append("shared_point_signal")
        elif shared_region_ids:
            focus_reasons.append("shared_region_signal")
        elif shared_object_ids:
            focus_reasons.append("shared_object_signal")
        if bool(unit.selected_evidence_summary.get("selected_after_reselection")):
            focus_reasons.append("selected_after_reselection")

        conflict_signal_level = "none"
        if shared_object_ids:
            conflict_signal_level = "object"
        if shared_region_ids:
            conflict_signal_level = "region"
        if shared_point_ids:
            conflict_signal_level = "point"

        summaries[unit_id] = {
            "case_id": case_result.case_spec.case_id,
            "event_unit_id": unit_id,
            "event_type": unit.spec.event_type,
            "split_mode": unit.spec.split_mode,
            "boundary_pair_signature": str(unit.pair_local_summary.get("boundary_pair_signature") or ""),
            "positive_rcsd_support_level": unit.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": unit.positive_rcsd_consistency_level,
            "positive_rcsd_present": bool(unit.positive_rcsd_present),
            "positive_rcsd_present_reason": str(unit.positive_rcsd_present_reason or ""),
            "pair_local_rcsd_empty": bool(unit.pair_local_rcsd_empty),
            "rcsd_selection_mode": str(unit.rcsd_selection_mode or ""),
            "local_rcsd_unit_kind": str(unit.local_rcsd_unit_kind or ""),
            "local_rcsd_unit_id": str(unit.local_rcsd_unit_id or ""),
            "aggregated_rcsd_unit_id": str(unit.aggregated_rcsd_unit_id or ""),
            "aggregated_rcsd_unit_ids": list(unit.aggregated_rcsd_unit_ids),
            "axis_polarity_inverted": bool(unit.axis_polarity_inverted),
            "first_hit_rcsdroad_ids": list(unit.first_hit_rcsdroad_ids),
            "selected_rcsdroad_count": len(unit.selected_rcsdroad_ids),
            "selected_rcsdnode_count": len(unit.selected_rcsdnode_ids),
            "primary_main_rc_node": str(unit.primary_main_rc_node_id or ""),
            "required_rcsd_node": str(unit.required_rcsd_node or ""),
            "required_rcsd_node_source": str(unit.required_rcsd_node_source or ""),
            "rcsd_decision_reason": str(unit.positive_rcsd_audit.get("rcsd_decision_reason") or ""),
            "selected_candidate_region": str(unit.selected_candidate_region or ""),
            "axis_position_m": unit.selected_evidence_summary.get("axis_position_m"),
            "reference_distance_to_origin_m": unit.selected_evidence_summary.get("reference_distance_to_origin_m"),
            "upper_evidence_object_id": str(unit.selected_evidence_summary.get("upper_evidence_object_id") or ""),
            "selected_reference_zone": selected_reference_zone,
            "selected_evidence_membership": selected_evidence_membership,
            "has_alternative_candidates": bool(unit.alternative_candidate_summaries),
            "candidate_pool_size": len(unit.candidate_audit_entries),
            "candidate_shortlist_ids": [entry.candidate_id for entry in shortlist],
            "better_alternative_signal": bool(better_alt_signal),
            "best_alternative_candidate_id": "" if best_alt is None else best_alt.candidate_id,
            "best_alternative_layer": "" if best_alt is None else str(best_alt.candidate_summary.get("layer_label") or ""),
            "best_alternative_reason": better_alt_reason,
            "shared_object_signal": bool(shared_object_ids),
            "shared_region_signal": bool(shared_region_ids),
            "shared_point_signal": bool(shared_point_ids),
            "shared_object_unit_ids": shared_object_ids,
            "shared_region_unit_ids": shared_region_ids,
            "shared_point_unit_ids": shared_point_ids,
            "conflict_signal_level": conflict_signal_level,
            "related_unit_ids": sorted({*shared_object_ids, *shared_region_ids, *shared_point_ids}),
            "needs_manual_review_focus": bool(focus_reasons),
            "focus_reasons": focus_reasons,
            "key_reason": _key_reason(unit, focus_reasons, better_alt_reason),
        }
    return summaries
