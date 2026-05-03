from __future__ import annotations

from dataclasses import replace
from typing import Any

from .case_models import T04CaseResult, T04EventUnitResult
from .rcsd_alignment import RCSD_ALIGNMENT_NONE, RCSD_ALIGNMENT_ROAD_ONLY
from .step4_road_surface_fork_geometry import _dedupe
from .surface_scenario import (
    MAIN_EVIDENCE_NONE,
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SECTION_REFERENCE_SWSD,
)


SHARED_RCSDROAD_MAX_ROAD_DISTANCE_M = 8.0
SHARED_RCSDROAD_MAX_UNIT_DISTANCE_M = 8.0
SHARED_RCSDROAD_MIN_SWSD_ROAD_SUPPORT = 3
SHARED_RCSDROAD_REASON = "complex_swsd_shared_rcsdroad_alignment"
SWSD_WINDOW_NO_RCSD_MODE = "swsd_junction_window_no_rcsd"


def _clean_ids(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _road_lookup(case_result: T04CaseResult) -> dict[str, Any]:
    return {str(road.road_id): road for road in case_result.case_bundle.roads}


def _rcsd_road_lookup(case_result: T04CaseResult) -> dict[str, Any]:
    return {str(road.road_id): road for road in case_result.case_bundle.rcsd_roads}


def _unit_branch_road_ids(unit: T04EventUnitResult) -> tuple[str, ...]:
    ids: list[str] = []
    for road_ids in (unit.unit_envelope.branch_road_memberships or {}).values():
        for road_id in _clean_ids(road_ids):
            if road_id not in ids:
                ids.append(road_id)
    return tuple(ids)


def _eligible_complex_swsd_only_units(case_result: T04CaseResult) -> tuple[T04EventUnitResult, ...]:
    complex_units = tuple(
        unit
        for unit in case_result.event_units
        if unit.spec.split_mode == "complex_one_node_one_unit"
    )
    if len(complex_units) < 2 or len(complex_units) != len(case_result.event_units):
        return ()
    eligible: list[T04EventUnitResult] = []
    for unit in complex_units:
        scenario = unit.surface_scenario_doc()
        if scenario.get("main_evidence_type") != MAIN_EVIDENCE_NONE:
            return ()
        if scenario.get("rcsd_alignment_type") != RCSD_ALIGNMENT_NONE:
            return ()
        if scenario.get("surface_scenario_type") != SCENARIO_NO_MAIN_WITH_SWSD_ONLY:
            return ()
        if scenario.get("section_reference_source") != SECTION_REFERENCE_SWSD:
            return ()
        if not _unit_branch_road_ids(unit):
            return ()
        eligible.append(unit)
    return tuple(eligible)


def _related_swsd_roads(
    case_result: T04CaseResult,
    units: tuple[T04EventUnitResult, ...],
) -> tuple[Any, ...]:
    roads_by_id = _road_lookup(case_result)
    road_ids: list[str] = []
    for unit in units:
        for road_id in _unit_branch_road_ids(unit):
            if road_id not in road_ids:
                road_ids.append(road_id)
    return tuple(
        road
        for road_id in road_ids
        for road in (roads_by_id.get(road_id),)
        if road is not None
        and getattr(road, "geometry", None) is not None
        and not road.geometry.is_empty
    )


def _unit_points(units: tuple[T04EventUnitResult, ...]) -> tuple[Any, ...]:
    points: list[Any] = []
    for unit in units:
        representative_node = getattr(unit.unit_context, "representative_node", None)
        geometry = getattr(representative_node, "geometry", None)
        if geometry is not None and not geometry.is_empty:
            points.append(geometry)
    return tuple(points)


def _score_shared_rcsdroad(
    case_result: T04CaseResult,
    units: tuple[T04EventUnitResult, ...],
) -> dict[str, Any] | None:
    related_roads = _related_swsd_roads(case_result, units)
    unit_points = _unit_points(units)
    if not related_roads or len(unit_points) != len(units):
        return None

    scores: list[dict[str, Any]] = []
    for road in case_result.case_bundle.rcsd_roads:
        geometry = getattr(road, "geometry", None)
        if geometry is None or geometry.is_empty:
            continue
        road_distances = [float(geometry.distance(swsd.geometry)) for swsd in related_roads]
        supported_road_distances = [
            distance
            for distance in road_distances
            if distance <= SHARED_RCSDROAD_MAX_ROAD_DISTANCE_M
        ]
        unit_distances = [float(geometry.distance(point)) for point in unit_points]
        supported_unit_distances = [
            distance
            for distance in unit_distances
            if distance <= SHARED_RCSDROAD_MAX_UNIT_DISTANCE_M
        ]
        if not supported_road_distances:
            continue
        scores.append(
            {
                "road": road,
                "road_id": str(road.road_id),
                "road_support_count": len(supported_road_distances),
                "unit_support_count": len(supported_unit_distances),
                "mean_supported_road_distance_m": sum(supported_road_distances) / len(supported_road_distances),
                "min_road_distance_m": min(road_distances),
                "max_unit_distance_m": max(unit_distances) if unit_distances else None,
            }
        )
    if not scores:
        return None

    scores.sort(
        key=lambda item: (
            -int(item["road_support_count"]),
            -int(item["unit_support_count"]),
            float(item["mean_supported_road_distance_m"]),
            float(item["min_road_distance_m"]),
            str(item["road_id"]),
        )
    )
    best = scores[0]
    min_road_support = min(
        max(SHARED_RCSDROAD_MIN_SWSD_ROAD_SUPPORT, len(units)),
        len(related_roads),
    )
    if int(best["road_support_count"]) < min_road_support:
        return None
    if int(best["unit_support_count"]) < len(units):
        return None
    if len(scores) > 1:
        second = scores[1]
        same_support = (
            int(second["road_support_count"]) == int(best["road_support_count"])
            and int(second["unit_support_count"]) == int(best["unit_support_count"])
        )
        if same_support:
            return None
    return best


def _shared_rcsdroad_audit(
    *,
    unit: T04EventUnitResult,
    road_id: str,
    score: dict[str, Any],
) -> dict[str, Any]:
    unit_id = f"{unit.spec.event_unit_id}:shared_rcsdroad:{road_id}"
    return {
        **dict(unit.positive_rcsd_audit or {}),
        "rcsd_alignment_type": RCSD_ALIGNMENT_ROAD_ONLY,
        "pair_local_rcsd_empty": bool(unit.pair_local_rcsd_empty),
        "first_hit_rcsdroad_ids": [road_id],
        "local_rcsd_units": [
            {
                "unit_id": unit_id,
                "unit_kind": "road_only",
                "road_ids": [road_id],
                "node_ids": [],
                "positive_rcsd_present": True,
                "positive_rcsd_present_reason": SHARED_RCSDROAD_REASON,
                "decision_reason": SHARED_RCSDROAD_REASON,
                "road_support_count": int(score["road_support_count"]),
                "unit_support_count": int(score["unit_support_count"]),
            }
        ],
        "aggregated_rcsd_units": [],
        "local_rcsd_unit_id": unit_id,
        "local_rcsd_unit_kind": "road_only",
        "aggregated_rcsd_unit_id": "",
        "aggregated_rcsd_unit_ids": [unit_id],
        "published_rcsdroad_ids": [road_id],
        "published_rcsdnode_ids": [],
        "published_member_unit_ids": [unit_id],
        "published_rcsd_selection_mode": "complex_swsd_shared_rcsdroad",
        "positive_rcsd_present": False,
        "positive_rcsd_present_reason": SWSD_WINDOW_NO_RCSD_MODE,
        "positive_rcsd_support_level": "no_support",
        "positive_rcsd_consistency_level": "C",
        "required_rcsd_node_source": None,
        "rcsd_decision_reason": SWSD_WINDOW_NO_RCSD_MODE,
        "rcsd_selection_mode": SWSD_WINDOW_NO_RCSD_MODE,
        "swsd_junction_window_no_rcsd": True,
        "complex_swsd_shared_rcsdroad_alignment": {
            "road_id": road_id,
            "road_support_count": int(score["road_support_count"]),
            "unit_support_count": int(score["unit_support_count"]),
            "mean_supported_road_distance_m": round(float(score["mean_supported_road_distance_m"]), 6),
            "max_unit_distance_m": (
                round(float(score["max_unit_distance_m"]), 6)
                if score.get("max_unit_distance_m") is not None
                else None
            ),
        },
    }


def _promote_unit_to_shared_rcsdroad(
    unit: T04EventUnitResult,
    *,
    road_id: str,
    road_geometry: Any,
    score: dict[str, Any],
) -> T04EventUnitResult:
    review_reasons = _dedupe([*unit.all_review_reasons(), SHARED_RCSDROAD_REASON])
    summary = {
        **dict(unit.selected_evidence_summary or unit.selected_candidate_summary or {}),
        "source_mode": "swsd_junction_window",
        "candidate_scope": "",
        "upper_evidence_kind": "",
        "positive_rcsd_present": False,
        "positive_rcsd_present_reason": SWSD_WINDOW_NO_RCSD_MODE,
        "positive_rcsd_support_level": "no_support",
        "positive_rcsd_consistency_level": "C",
        "rcsd_alignment_type": RCSD_ALIGNMENT_ROAD_ONLY,
        "rcsd_selection_mode": SWSD_WINDOW_NO_RCSD_MODE,
        "rcsd_decision_reason": SWSD_WINDOW_NO_RCSD_MODE,
        "fallback_rcsdroad_ids": [road_id],
        "complex_swsd_shared_rcsdroad_alignment": {
            "road_id": road_id,
            "road_support_count": int(score["road_support_count"]),
            "unit_support_count": int(score["unit_support_count"]),
        },
        "review_reasons": list(review_reasons),
    }
    return replace(
        unit,
        review_state="STEP4_REVIEW" if unit.review_state != "STEP4_FAIL" else unit.review_state,
        review_reasons=review_reasons,
        evidence_source="swsd_junction_window",
        position_source="swsd_junction_window",
        rcsd_consistency_result=SWSD_WINDOW_NO_RCSD_MODE,
        first_hit_rcsd_road_geometry=road_geometry,
        local_rcsd_unit_geometry=road_geometry,
        positive_rcsd_geometry=road_geometry,
        positive_rcsd_road_geometry=road_geometry,
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
        first_hit_rcsdroad_ids=(road_id,),
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=f"{unit.spec.event_unit_id}:shared_rcsdroad:{road_id}",
        local_rcsd_unit_kind="road_only",
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(f"{unit.spec.event_unit_id}:shared_rcsdroad:{road_id}",),
        positive_rcsd_present=False,
        positive_rcsd_present_reason=SWSD_WINDOW_NO_RCSD_MODE,
        rcsd_selection_mode=SWSD_WINDOW_NO_RCSD_MODE,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        positive_rcsd_audit=_shared_rcsdroad_audit(unit=unit, road_id=road_id, score=score),
        rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
    )


def _replace_case_units(
    case_result: T04CaseResult,
    replacements: dict[str, T04EventUnitResult],
) -> T04CaseResult:
    units = [
        replacements.get(unit.spec.event_unit_id, unit)
        for unit in case_result.event_units
    ]
    state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in units):
        state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in units):
        state = "STEP4_REVIEW"
    reasons = _dedupe(reason for unit in units for reason in unit.all_review_reasons())
    return replace(case_result, event_units=units, case_review_state=state, case_review_reasons=reasons)


def align_complex_swsd_units_to_shared_rcsdroad(
    case_result: T04CaseResult,
) -> tuple[T04CaseResult, list[dict[str, Any]]]:
    units = _eligible_complex_swsd_only_units(case_result)
    if not units:
        return case_result, []
    score = _score_shared_rcsdroad(case_result, units)
    if score is None:
        return case_result, []
    road_id = str(score["road_id"])
    road = _rcsd_road_lookup(case_result).get(road_id)
    if road is None:
        return case_result, []

    replacements = {
        unit.spec.event_unit_id: _promote_unit_to_shared_rcsdroad(
            unit,
            road_id=road_id,
            road_geometry=road.geometry,
            score=score,
        )
        for unit in units
    }
    records = [
        {
            "case_id": case_result.case_spec.case_id,
            "unit_id": unit.spec.event_unit_id,
            "pre_state": unit.selected_evidence_state,
            "post_state": replacements[unit.spec.event_unit_id].selected_evidence_state,
            "pre_evidence_source": unit.evidence_source,
            "post_evidence_source": "swsd_junction_window",
            "action": SHARED_RCSDROAD_REASON,
            "skip_reason": None,
            "required_rcsd_node": None,
            "positive_rcsd_consistency_level": "C",
            "detail": {
                "road_id": road_id,
                "road_support_count": int(score["road_support_count"]),
                "unit_support_count": int(score["unit_support_count"]),
                "mean_supported_road_distance_m": round(float(score["mean_supported_road_distance_m"]), 6),
            },
        }
        for unit in units
    ]
    return _replace_case_units(case_result, replacements), records


__all__ = ["align_complex_swsd_units_to_shared_rcsdroad"]
