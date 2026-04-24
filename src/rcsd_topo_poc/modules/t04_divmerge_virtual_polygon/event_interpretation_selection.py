from __future__ import annotations

from dataclasses import replace

from shapely.geometry.base import BaseGeometry

from .case_models import T04EventUnitResult
from .event_interpretation_shared import (
    _CandidateEvaluation,
    _geometry_present,
    _safe_normalize_geometry,
    _stable_axis_signature,
)


SHARED_EVIDENCE_OVERLAP_AREA_M2 = 8.0
SHARED_EVIDENCE_OVERLAP_RATIO = 0.2
EVENT_REFERENCE_CONFLICT_TOL_M = 5.0
NODE_FALLBACK_AXIS_POSITION_MAX_M = 1.0
NODE_FALLBACK_DISTANCE_MAX_M = 3.0
DEGRADED_REVERSE_DIVSTRIP_MAX_REFERENCE_DISTANCE_M = 60.0
DEGRADED_REVERSE_DIVSTRIP_MAX_MIDDLE_RATIO = 0.10
DEGRADED_REVERSE_DIVSTRIP_MIN_THROAT_RATIO = 0.05
ROAD_SURFACE_FORK_SCOPE = "road_surface_fork"
INVALID_PRIMARY_REASONS = {
    "event_reference_outside_branch_middle",
    "event_reference_axis_conflict_with_prior_unit",
    "missing_event_reference_point",
    "selected_branch_ids_empty",
}


def _has_degraded_pair_local_scope(result: T04EventUnitResult) -> bool:
    return any(
        str(reason).strip() == "degraded_scope:pair_local_scope_roads_empty"
        for reason in result.all_review_reasons()
    )


def _degraded_reverse_divstrip_far_from_throat(
    candidate_summary: dict,
    result: T04EventUnitResult,
) -> bool:
    if str(candidate_summary.get("candidate_scope") or "") != "divstrip_component":
        return False
    if str(result.evidence_source or "") != "reverse_tip_retry":
        return False
    if not _has_degraded_pair_local_scope(result):
        return False
    try:
        reference_distance = float(candidate_summary.get("reference_distance_to_origin_m") or 0.0)
        middle_ratio = float(candidate_summary.get("pair_middle_overlap_ratio") or 0.0)
        throat_ratio = float(candidate_summary.get("throat_overlap_ratio") or 0.0)
    except (TypeError, ValueError):
        return False
    return bool(
        reference_distance > DEGRADED_REVERSE_DIVSTRIP_MAX_REFERENCE_DISTANCE_M
        and middle_ratio < DEGRADED_REVERSE_DIVSTRIP_MAX_MIDDLE_RATIO
        and throat_ratio < DEGRADED_REVERSE_DIVSTRIP_MIN_THROAT_RATIO
    )


def _event_axis_signature(event_unit: T04EventUnitResult) -> str | None:
    candidate_axis_signature = str(event_unit.selected_candidate_summary.get("axis_signature") or "").strip()
    if candidate_axis_signature:
        return candidate_axis_signature
    return _stable_axis_signature(
        event_unit.event_axis_branch_id,
        event_unit.unit_envelope.branch_road_memberships,
    )


def _candidate_axis_position(event_unit: T04EventUnitResult) -> tuple[str | None, float | None]:
    summary = event_unit.selected_candidate_summary
    basis = str(summary.get("axis_position_basis") or "").strip() or None
    position = summary.get("axis_position_m")
    try:
        numeric_position = None if position is None else float(position)
    except (TypeError, ValueError):
        numeric_position = None
    return basis, numeric_position


def _allows_shared_axis_reference(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> bool:
    if str(lhs.spec.representative_node_id or "") != str(rhs.spec.representative_node_id or ""):
        return False
    lhs_axis = str(lhs.event_axis_branch_id or "").strip()
    rhs_axis = str(rhs.event_axis_branch_id or "").strip()
    if not lhs_axis or not rhs_axis or lhs_axis != rhs_axis:
        return False
    lhs_event_branches = {str(branch_id) for branch_id in lhs.selected_event_branch_ids if str(branch_id)}
    rhs_event_branches = {str(branch_id) for branch_id in rhs.selected_event_branch_ids if str(branch_id)}
    if not lhs_event_branches or not rhs_event_branches:
        return False
    return lhs_event_branches != rhs_event_branches


def _merge_candidate_evaluation(candidate_summary: dict, result: T04EventUnitResult) -> dict:
    merged = dict(candidate_summary)
    road_surface_fork_candidate = str(merged.get("candidate_scope") or "") == ROAD_SURFACE_FORK_SCOPE
    event_axis_signature = str(merged.get("axis_signature") or result.event_axis_branch_id or "").strip()
    axis_position_basis = str(merged.get("axis_position_basis") or "").strip()
    axis_position_m = merged.get("axis_position_m")
    try:
        axis_position_m = None if axis_position_m is None else float(axis_position_m)
    except (TypeError, ValueError):
        axis_position_m = None
    if result.event_chosen_s_m is not None:
        axis_position_m = round(float(result.event_chosen_s_m), 1)
        merged["axis_position_m"] = axis_position_m
        if event_axis_signature:
            if axis_position_basis and axis_position_basis != event_axis_signature:
                merged["point_signature"] = f"{event_axis_signature}:{axis_position_basis}:{axis_position_m}"
            else:
                merged["point_signature"] = f"{event_axis_signature}:{axis_position_m}"
    reference_distance_to_origin_m = merged.get("reference_distance_to_origin_m")
    try:
        numeric_reference_distance = (
            None if reference_distance_to_origin_m is None else float(reference_distance_to_origin_m)
        )
    except (TypeError, ValueError):
        numeric_reference_distance = None
    node_fallback_only = False
    if not road_surface_fork_candidate:
        node_fallback_only = bool(
            (
                numeric_reference_distance is not None
                and numeric_reference_distance <= NODE_FALLBACK_DISTANCE_MAX_M + 1e-9
            )
            or (
                numeric_reference_distance is None
                and axis_position_m is not None
                and abs(axis_position_m) <= NODE_FALLBACK_AXIS_POSITION_MAX_M + 1e-9
            )
        )
    merged["node_fallback_only"] = node_fallback_only
    merged["primary_eligible"] = bool(int(merged.get("layer", 3) or 3) in {1, 2} and not node_fallback_only)
    layer_reason = str(merged.get("layer_reason") or "")
    if node_fallback_only and "node_fallback_only" not in layer_reason:
        merged["layer_reason"] = f"{layer_reason}|node_fallback_only" if layer_reason else "node_fallback_only"
    elif not node_fallback_only and "node_fallback_only" in layer_reason:
        merged["layer_reason"] = layer_reason.replace("|node_fallback_only", "").replace("node_fallback_only|", "").replace("node_fallback_only", "")
    invalid_primary_reasons = set(INVALID_PRIMARY_REASONS)
    if road_surface_fork_candidate:
        invalid_primary_reasons.discard("event_reference_outside_branch_middle")
    if any(str(reason) in invalid_primary_reasons for reason in result.all_review_reasons()):
        merged["primary_eligible"] = False
    if _degraded_reverse_divstrip_far_from_throat(merged, result):
        merged["primary_eligible"] = False
        merged["degraded_reverse_divstrip_far_from_throat"] = True
        review_reasons = list(merged.get("review_reasons") or result.all_review_reasons())
        review_reasons.append("degraded_reverse_divstrip_far_from_throat")
        merged["review_reasons"] = list(dict.fromkeys(str(reason) for reason in review_reasons))
    support_level = result.positive_rcsd_support_level
    consistency_level = result.positive_rcsd_consistency_level
    decision_reason = str(result.positive_rcsd_audit.get("rcsd_decision_reason") or "")
    if (
        merged.get("degraded_reverse_divstrip_far_from_throat") is True
        and bool(result.positive_rcsd_present)
        and str(consistency_level or "C") == "A"
    ):
        support_level = "secondary_support"
        consistency_level = "B"
        decision_reason = "role_mapping_partial_relaxed_aggregated"
    merged.update(
        {
            "review_state": result.review_state,
            "review_reasons": list(merged.get("review_reasons") or result.all_review_reasons()),
            "evidence_source": result.evidence_source,
            "position_source": result.position_source,
            "reverse_tip_used": bool(result.reverse_tip_used),
            "rcsd_consistency_result": result.rcsd_consistency_result,
            "pair_local_rcsd_empty": bool(result.pair_local_rcsd_empty),
            "pair_local_rcsd_road_ids": list(result.pair_local_rcsd_road_ids),
            "pair_local_rcsd_node_ids": list(result.pair_local_rcsd_node_ids),
            "first_hit_rcsdroad_ids": list(result.first_hit_rcsdroad_ids),
            "local_rcsd_unit_id": result.local_rcsd_unit_id,
            "local_rcsd_unit_kind": result.local_rcsd_unit_kind,
            "aggregated_rcsd_unit_id": result.aggregated_rcsd_unit_id,
            "aggregated_rcsd_unit_ids": list(result.aggregated_rcsd_unit_ids),
            "rcsd_selection_mode": result.rcsd_selection_mode,
            "positive_rcsd_present": bool(result.positive_rcsd_present),
            "positive_rcsd_present_reason": result.positive_rcsd_present_reason,
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": result.required_rcsd_node,
            "required_rcsd_node_source": result.required_rcsd_node_source,
            "axis_polarity_inverted": bool(result.axis_polarity_inverted),
            "rcsd_decision_reason": decision_reason,
        }
    )
    return merged


def _primary_evidence_invalid(
    result: T04EventUnitResult,
    *,
    allowed_invalid_reasons: set[str] | None = None,
) -> bool:
    allowed = set() if allowed_invalid_reasons is None else set(allowed_invalid_reasons)
    for reason in result.all_review_reasons():
        text = str(reason).strip()
        if text in allowed:
            continue
        if text in INVALID_PRIMARY_REASONS:
            return True
        if text.startswith("shared_event_reference_with:"):
            return True
        if text.startswith("shared_event_core_segment_with:"):
            return True
        if text.startswith("shared_divstrip_component_with:"):
            return True
    return False


def _candidate_priority_score(candidate_summary: dict, result: T04EventUnitResult) -> int:
    road_surface_fork_candidate = str(candidate_summary.get("candidate_scope") or "") == ROAD_SURFACE_FORK_SCOPE
    allowed_invalid_reasons = (
        {"event_reference_outside_branch_middle"}
        if road_surface_fork_candidate
        else set()
    )
    if _primary_evidence_invalid(result, allowed_invalid_reasons=allowed_invalid_reasons):
        return -1000
    if not bool(candidate_summary.get("primary_eligible")):
        return -100
    layer = int(candidate_summary.get("layer", 3) or 3)
    primary_bonus = 1000
    layer_bonus = {1: 300, 2: 200, 3: 50}.get(layer, 0)
    state_bonus = {"STEP4_OK": 120, "STEP4_REVIEW": 60, "STEP4_FAIL": -80}.get(result.review_state, 0)
    middle_bonus = int(round(float(candidate_summary.get("pair_middle_overlap_ratio", 0.0)) * 100.0))
    throat_bonus = int(round(float(candidate_summary.get("throat_overlap_ratio", 0.0)) * 50.0))
    rcsd_bonus = {
        "A": 160,
        "B": 60,
        "C": 0,
    }.get(str(result.positive_rcsd_consistency_level or "C"), 0)
    evidence_bonus = 40 if (
        (result.localized_evidence_core_geometry is not None and not result.localized_evidence_core_geometry.is_empty)
        or (result.selected_component_union_geometry is not None and not result.selected_component_union_geometry.is_empty)
    ) else 0
    node_penalty = 220 if bool(candidate_summary.get("node_fallback_only")) else 0
    return int(
        primary_bonus
        + layer_bonus
        + state_bonus
        + middle_bonus
        + throat_bonus
        + rcsd_bonus
        + evidence_bonus
        - node_penalty
    )


def _result_conflicts(lhs: T04EventUnitResult, rhs: T04EventUnitResult) -> bool:
    shared_axis_reference_allowed = _allows_shared_axis_reference(lhs, rhs)
    lhs_axis = _event_axis_signature(lhs)
    rhs_axis = _event_axis_signature(rhs)
    lhs_basis, lhs_position = _candidate_axis_position(lhs)
    rhs_basis, rhs_position = _candidate_axis_position(rhs)
    lhs_s = lhs_position if lhs_position is not None else (None if lhs.event_chosen_s_m is None else float(lhs.event_chosen_s_m))
    rhs_s = rhs_position if rhs_position is not None else (None if rhs.event_chosen_s_m is None else float(rhs.event_chosen_s_m))
    same_axis_separated = bool(
        lhs_axis is not None
        and rhs_axis is not None
        and lhs_s is not None
        and rhs_s is not None
        and lhs_axis == rhs_axis
        and (lhs_basis is None or rhs_basis is None or lhs_basis == rhs_basis)
        and abs(lhs_s - rhs_s) > EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9
    )
    lhs_point_signature = str(lhs.selected_candidate_summary.get("point_signature") or "")
    rhs_point_signature = str(rhs.selected_candidate_summary.get("point_signature") or "")
    if (
        not shared_axis_reference_allowed
        and lhs_point_signature
        and rhs_point_signature
        and lhs_point_signature == rhs_point_signature
    ):
        return True
    if (
        not shared_axis_reference_allowed
        and
        lhs_axis is not None
        and rhs_axis is not None
        and lhs_axis == rhs_axis
        and lhs_s is not None
        and rhs_s is not None
        and (lhs_basis is None or rhs_basis is None or lhs_basis == rhs_basis)
    ):
        if abs(lhs_s - rhs_s) <= EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9:
            return True
    if same_axis_separated:
        return False
    if shared_axis_reference_allowed:
        return False
    for lhs_geometry, rhs_geometry in (
        (lhs.selected_component_union_geometry, rhs.selected_component_union_geometry),
        (lhs.localized_evidence_core_geometry, rhs.localized_evidence_core_geometry),
    ):
        if not _geometry_present(lhs_geometry) or not _geometry_present(rhs_geometry):
            continue
        overlap = _safe_normalize_geometry(lhs_geometry.intersection(rhs_geometry))
        overlap_area = float(getattr(overlap, "area", 0.0) or 0.0) if overlap is not None else 0.0
        lhs_area = float(getattr(lhs_geometry, "area", 0.0) or 0.0)
        rhs_area = float(getattr(rhs_geometry, "area", 0.0) or 0.0)
        smaller_area = min(lhs_area, rhs_area)
        overlap_ratio = 0.0 if smaller_area <= 1e-6 else overlap_area / smaller_area
        if overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2 or overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO:
            return True
    return False


def _rank_candidate_pool(evaluations: list[_CandidateEvaluation]) -> list[_CandidateEvaluation]:
    return sorted(
        evaluations,
        key=lambda item: (
            -{"A": 3, "B": 2, "C": 1}.get(str(item.result.positive_rcsd_consistency_level or "C"), 1),
            -int(item.priority_score),
            str(item.result.selected_candidate_summary.get("candidate_id") or ""),
        ),
    )


def _select_case_assignment(
    candidate_pools: list[list[_CandidateEvaluation]],
) -> list[_CandidateEvaluation | None]:
    ordered_unit_indices = sorted(
        range(len(candidate_pools)),
        key=lambda index: (len(candidate_pools[index]), index),
    )
    best_assignment_score = -1
    best_assignment_by_order: list[_CandidateEvaluation | None] = [None] * len(ordered_unit_indices)

    def _search(order_pos: int, chosen: list[_CandidateEvaluation | None], score: int) -> None:
        nonlocal best_assignment_score, best_assignment_by_order
        if order_pos >= len(ordered_unit_indices):
            if score > best_assignment_score:
                best_assignment_score = score
                best_assignment_by_order = list(chosen)
            return
        pool_index = ordered_unit_indices[order_pos]
        options: list[_CandidateEvaluation | None] = [*candidate_pools[pool_index], None]
        for candidate_eval in options:
            if candidate_eval is not None:
                if any(
                    prior is not None and _result_conflicts(candidate_eval.result, prior.result)
                    for prior in chosen
                ):
                    continue
                _search(
                    order_pos + 1,
                    [*chosen, candidate_eval],
                    score + int(candidate_eval.priority_score),
                )
            else:
                _search(order_pos + 1, [*chosen, None], score)

    _search(0, [], 0)

    assignment_by_unit_index: list[_CandidateEvaluation | None] = [None] * len(candidate_pools)
    for order_pos, pool_index in enumerate(ordered_unit_indices):
        assignment_by_unit_index[pool_index] = best_assignment_by_order[order_pos]
    return assignment_by_unit_index


def _apply_evidence_ownership_guards(
    event_units: list[T04EventUnitResult],
) -> list[T04EventUnitResult]:
    seen_units: dict[str, T04EventUnitResult] = {}
    seen_records: list[
        tuple[str, BaseGeometry | None, BaseGeometry | None, str | None, float | None]
    ] = []
    seen_positions: dict[str, list[tuple[str, float]]] = {}
    guarded: list[T04EventUnitResult] = []
    for event_unit in event_units:
        extra_review_notes = list(event_unit.extra_review_notes)
        hard_fail = False
        current_component_geometry = event_unit.selected_component_union_geometry
        current_core_geometry = event_unit.localized_evidence_core_geometry
        conflict_unit_ids: set[str] = set()

        axis_branch_id = _event_axis_signature(event_unit)
        axis_position_basis, axis_position_m = _candidate_axis_position(event_unit)
        chosen_s = axis_position_m if axis_position_m is not None else (None if event_unit.event_chosen_s_m is None else float(event_unit.event_chosen_s_m))
        position_key = None if axis_branch_id is None else f"{axis_branch_id}|{axis_position_basis or '*'}"
        if position_key is not None and chosen_s is not None:
            for prior_unit_id, prior_s in seen_positions.get(position_key, []):
                prior_unit = seen_units.get(prior_unit_id)
                if prior_unit is not None and _allows_shared_axis_reference(event_unit, prior_unit):
                    continue
                if abs(float(prior_s) - chosen_s) <= EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9:
                    hard_fail = True
                    conflict_unit_ids.add(prior_unit_id)
                    extra_review_notes.append(f"shared_event_reference_with:{prior_unit_id}")

        if (
            (current_component_geometry is not None and not current_component_geometry.is_empty)
            or (current_core_geometry is not None and not current_core_geometry.is_empty)
        ):
            current_component_area = float(getattr(current_component_geometry, "area", 0.0) or 0.0)
            current_core_area = float(getattr(current_core_geometry, "area", 0.0) or 0.0)
            for (
                prior_unit_id,
                prior_component_geometry,
                prior_core_geometry,
                prior_axis_branch_id,
                prior_chosen_s,
            ) in seen_records:
                prior_unit = seen_units.get(prior_unit_id)
                if prior_unit is not None and _allows_shared_axis_reference(event_unit, prior_unit):
                    continue
                same_axis_separated = bool(
                    position_key is not None
                    and chosen_s is not None
                    and prior_axis_branch_id is not None
                    and prior_chosen_s is not None
                    and str(prior_axis_branch_id) == position_key
                    and abs(float(prior_chosen_s) - chosen_s)
                    > EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9
                )
                if (
                    current_component_geometry is not None
                    and not current_component_geometry.is_empty
                    and prior_component_geometry is not None
                    and not prior_component_geometry.is_empty
                ):
                    overlap_geometry = current_component_geometry.intersection(prior_component_geometry).buffer(0)
                    overlap_area = float(getattr(overlap_geometry, "area", 0.0) or 0.0)
                    prior_area = float(getattr(prior_component_geometry, "area", 0.0) or 0.0)
                    smaller_area = min(current_component_area, prior_area)
                    overlap_ratio = 0.0 if smaller_area <= 1e-6 else overlap_area / smaller_area
                    if (
                        not same_axis_separated
                        and (
                            overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2
                            or overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO
                        )
                    ):
                        hard_fail = True
                        conflict_unit_ids.add(prior_unit_id)
                        extra_review_notes.append(f"shared_divstrip_component_with:{prior_unit_id}")
                if (
                    not same_axis_separated
                    and current_core_geometry is not None
                    and not current_core_geometry.is_empty
                    and prior_core_geometry is not None
                    and not prior_core_geometry.is_empty
                ):
                    core_overlap = current_core_geometry.intersection(prior_core_geometry).buffer(0)
                    core_overlap_area = float(getattr(core_overlap, "area", 0.0) or 0.0)
                    prior_core_area = float(getattr(prior_core_geometry, "area", 0.0) or 0.0)
                    smaller_core_area = min(current_core_area, prior_core_area)
                    core_overlap_ratio = (
                        0.0
                        if smaller_core_area <= 1e-6
                        else core_overlap_area / smaller_core_area
                    )
                    if (
                        core_overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2
                        or core_overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO
                    ):
                        hard_fail = True
                        conflict_unit_ids.add(prior_unit_id)
                        extra_review_notes.append(f"shared_event_core_segment_with:{prior_unit_id}")
            seen_records.append(
                (
                    event_unit.spec.event_unit_id,
                    current_component_geometry,
                    current_core_geometry,
                    None if axis_branch_id is None else f"{axis_branch_id}|{axis_position_basis or '*'}",
                    chosen_s,
                )
            )

        if position_key is not None and chosen_s is not None:
            seen_positions.setdefault(position_key, []).append((event_unit.spec.event_unit_id, chosen_s))
        seen_units[event_unit.spec.event_unit_id] = event_unit

        if extra_review_notes:
            guarded.append(
                replace(
                    event_unit,
                    review_state="STEP4_FAIL" if hard_fail else ("STEP4_REVIEW" if event_unit.review_state == "STEP4_OK" else event_unit.review_state),
                    extra_review_notes=tuple(extra_review_notes),
                )
            )
            continue
        guarded.append(event_unit)
    return guarded
