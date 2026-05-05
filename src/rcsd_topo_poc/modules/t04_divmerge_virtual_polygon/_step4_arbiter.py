from __future__ import annotations

import math
import os
from dataclasses import fields, replace
from typing import Any, Iterable, Mapping

from shapely.geometry.base import BaseGeometry

from ._step4_arbiter_models import (
    ARBITER_FINAL_FIELD_NAMES,
    T04ArbiterCaseContext,
    T04ArbitrationDecision,
    T04Step4Candidate,
    T04Step4CandidateLedger,
)
from ._step4_candidate_scoring import score_step4_candidates
from .case_models import T04EventUnitResult
from .rcsd_alignment import (
    RCSD_ALIGNMENT_AMBIGUOUS,
    RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES,
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_POSITIVE_TYPES,
    RCSD_ALIGNMENT_ROAD_ONLY,
)
from .surface_scenario import classify_surface_scenario, classify_surface_scenario_from_alignment


_SUPPORT_RANK = {
    "primary_support": 3,
    "secondary_support": 2,
    "no_support": 1,
}
_CONSISTENCY_RANK = {
    "A": 3,
    "B": 2,
    "C": 1,
}
_MAIN_EVIDENCE_REPLACEMENT_REASONS = frozenset(
    {
        "divstrip_primary_over_wide_road_surface_fork",
        "recovery_flip",
        "cleanup_clear",
    }
)
_TRUE_TEXT = frozenset({"1", "true", "yes", "on"})


def _shadow_mode_from_env() -> bool:
    return _clean_text(os.environ.get("STEP4_ARBITER_SHADOW_MODE")).lower() in _TRUE_TEXT


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseGeometry):
        return _geometry_doc(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _geometry_doc(geometry: BaseGeometry | None) -> dict[str, Any]:
    if geometry is None:
        return {"present": False}
    return {
        "present": not geometry.is_empty,
        "geom_type": getattr(geometry, "geom_type", None),
    }


def _unit_final_fields(unit: T04EventUnitResult) -> dict[str, Any]:
    scenario = unit.surface_scenario_doc()
    return {
        "selected_rcsdroad_ids": tuple(unit.selected_rcsdroad_ids),
        "selected_rcsdnode_ids": tuple(unit.selected_rcsdnode_ids),
        "required_rcsd_node": unit.required_rcsd_node,
        "required_rcsd_node_source": unit.required_rcsd_node_source,
        "positive_rcsd_present": bool(unit.positive_rcsd_present),
        "positive_rcsd_present_reason": unit.positive_rcsd_present_reason,
        "positive_rcsd_support_level": unit.positive_rcsd_support_level,
        "positive_rcsd_consistency_level": unit.positive_rcsd_consistency_level,
        "rcsd_alignment_type": scenario["rcsd_alignment_type"],
        "rcsd_match_type": scenario["rcsd_match_type"],
        "rcsd_selection_mode": unit.rcsd_selection_mode,
        "selected_evidence_summary": dict(unit.selected_evidence_summary),
        "selected_candidate_summary": dict(unit.selected_candidate_summary),
        "fact_reference_point": unit.fact_reference_point,
        "review_materialized_point": unit.review_materialized_point,
        "surface_scenario_published": bool(unit.surface_scenario_published),
        "has_main_evidence": bool(scenario["has_main_evidence"]),
        "main_evidence_type": scenario["main_evidence_type"],
        "reference_point_present": bool(scenario["reference_point_present"]),
        "reference_point_source": scenario["reference_point_source"],
        "surface_scenario_type": scenario["surface_scenario_type"],
        "section_reference_source": scenario["section_reference_source"],
        "swsd_junction_present": bool(scenario["swsd_junction_present"]),
        "fallback_rcsdroad_ids": tuple(scenario["fallback_rcsdroad_ids"]),
        "surface_generation_mode": scenario["surface_generation_mode"],
        "no_reference_point_reason": scenario["no_reference_point_reason"],
    }


def _snapshot(unit: T04EventUnitResult) -> dict[str, Any]:
    return _json_safe(_unit_final_fields(unit))


def _candidate_unit_snapshot(candidate: T04Step4Candidate) -> dict[str, Any]:
    snapshot = candidate.source_audit_blob.get("unit_snapshot")
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _main_evidence_present(candidate: T04Step4Candidate, unit: T04EventUnitResult) -> bool:
    if candidate.main_evidence_type and candidate.main_evidence_type != "none":
        return True
    return bool(unit.surface_scenario_doc()["has_main_evidence"])


def _current_main_evidence_type(unit: T04EventUnitResult) -> str:
    summary = dict(unit.selected_evidence_summary or unit.selected_candidate_summary or {})
    upper_kind = _clean_text(summary.get("upper_evidence_kind"))
    if upper_kind:
        return upper_kind
    candidate_scope = _clean_text(summary.get("candidate_scope"))
    if candidate_scope.startswith("divstrip"):
        return "divstrip"
    scenario_main = _clean_text(unit.surface_scenario_doc()["main_evidence_type"])
    return scenario_main if scenario_main != "none" else ""


def _candidate_matches_main_evidence(candidate: T04Step4Candidate, main_evidence_type: str) -> bool:
    if not main_evidence_type:
        return False
    candidate_main = _clean_text(candidate.main_evidence_type)
    if candidate_main == main_evidence_type:
        return True
    if main_evidence_type == "divstrip":
        return candidate.source_stage == "divstrip" or candidate.replacement_reason == "divstrip_primary_over_wide_road_surface_fork"
    return False


def _main_evidence_rearbitration_pool(
    unit: T04EventUnitResult,
    candidates: tuple[T04Step4Candidate, ...],
) -> tuple[tuple[T04Step4Candidate, ...], dict[str, Any] | None]:
    summary = dict(unit.selected_evidence_summary or unit.selected_candidate_summary or {})
    replacement_reason = _clean_text(summary.get("decision_reason"))
    if replacement_reason not in _MAIN_EVIDENCE_REPLACEMENT_REASONS:
        return candidates, None
    main_evidence_type = _current_main_evidence_type(unit)
    matched = tuple(
        candidate
        for candidate in candidates
        if _candidate_matches_main_evidence(candidate, main_evidence_type)
    )
    if not matched:
        return candidates, {
            "event": "main_evidence_rearbitration_no_matching_candidate",
            "main_evidence_type": main_evidence_type,
            "replacement_reason": replacement_reason,
        }
    return matched, {
        "event": "main_evidence_rearbitration_pool",
        "main_evidence_type": main_evidence_type,
        "replacement_reason": replacement_reason,
        "candidate_ids": [candidate.candidate_id for candidate in matched],
    }


def _candidate_scenario_doc(candidate: T04Step4Candidate, unit: T04EventUnitResult) -> dict[str, Any]:
    candidate_snapshot = _candidate_unit_snapshot(candidate)
    selected_evidence_summary = dict(
        candidate_snapshot.get("selected_evidence_summary") or unit.selected_evidence_summary
    )
    return classify_surface_scenario(
        evidence_source=_clean_text(candidate_snapshot.get("evidence_source")) or candidate.evidence_type,
        selected_evidence_summary=selected_evidence_summary,
        rcsd_selection_mode=_clean_text(candidate_snapshot.get("rcsd_selection_mode")) or candidate.source_stage,
        required_rcsd_node=candidate.required_rcsd_node,
        first_hit_rcsdroad_ids=unit.first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=candidate.rcsdroad_ids,
        positive_rcsd_audit=unit.positive_rcsd_audit,
        fact_reference_point_present=candidate.reference_point is not None and not candidate.reference_point.is_empty,
        rcsd_alignment_type=candidate.rcsd_alignment_type,
    ).to_doc()


def _scenario_decision_kwargs(scenario_doc: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "surface_scenario_published": True,
        "has_main_evidence": bool(scenario_doc["has_main_evidence"]),
        "main_evidence_type": scenario_doc["main_evidence_type"],
        "reference_point_present": bool(scenario_doc["reference_point_present"]),
        "reference_point_source": scenario_doc["reference_point_source"],
        "surface_scenario_type": scenario_doc["surface_scenario_type"],
        "section_reference_source": scenario_doc["section_reference_source"],
        "swsd_junction_present": bool(scenario_doc["swsd_junction_present"]),
        "fallback_rcsdroad_ids": tuple(scenario_doc["fallback_rcsdroad_ids"]),
        "surface_generation_mode": scenario_doc["surface_generation_mode"],
        "no_reference_point_reason": scenario_doc["no_reference_point_reason"],
        "rcsd_match_type": scenario_doc["rcsd_match_type"],
    }


def _decision_kwargs_from_unit_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "surface_scenario_published": True,
        "has_main_evidence": bool(fields["has_main_evidence"]),
        "main_evidence_type": fields["main_evidence_type"],
        "reference_point_present": bool(fields["reference_point_present"]),
        "reference_point_source": fields["reference_point_source"],
        "surface_scenario_type": fields["surface_scenario_type"],
        "section_reference_source": fields["section_reference_source"],
        "swsd_junction_present": bool(fields["swsd_junction_present"]),
        "fallback_rcsdroad_ids": tuple(fields["fallback_rcsdroad_ids"]),
        "surface_generation_mode": fields["surface_generation_mode"],
        "no_reference_point_reason": fields["no_reference_point_reason"],
        "rcsd_match_type": fields["rcsd_match_type"],
    }


def _candidate_positive(candidate: T04Step4Candidate) -> bool:
    if candidate.reject_reason:
        return False
    if candidate.rcsd_alignment_type == RCSD_ALIGNMENT_AMBIGUOUS:
        return False
    if candidate.rcsd_alignment_type in RCSD_ALIGNMENT_POSITIVE_TYPES:
        return True
    return bool(candidate.required_rcsd_node or candidate.rcsdnode_ids or candidate.rcsdroad_ids)


def _candidate_sort_key(candidate: T04Step4Candidate, context: T04ArbiterCaseContext) -> tuple[float, int, int, int, str]:
    score = candidate.aggregate_consistency_score
    aggregate = -1.0 if score is None else float(score)
    return (
        aggregate,
        _SUPPORT_RANK.get(_clean_text(candidate.support_level), 0),
        _CONSISTENCY_RANK.get(_clean_text(candidate.consistency_level).upper(), 0),
        -context.source_stage_rank(candidate.source_stage),
        candidate.candidate_id,
    )


def _decision_from_unit(
    unit: T04EventUnitResult,
    *,
    trace: tuple[dict[str, Any], ...],
    aggregate_score: float | None = None,
    downgrade_from: dict[str, Any] | None = None,
    downgrade_to: dict[str, Any] | None = None,
    downgrade_reason: str = "",
    suppressed_rcsd_snapshot: dict[str, Any] | None = None,
) -> T04ArbitrationDecision:
    fields = _unit_final_fields(unit)
    return T04ArbitrationDecision(
        selected_rcsdroad_ids=fields["selected_rcsdroad_ids"],
        selected_rcsdnode_ids=fields["selected_rcsdnode_ids"],
        required_rcsd_node=fields["required_rcsd_node"],
        required_rcsd_node_source=fields["required_rcsd_node_source"],
        positive_rcsd_present=fields["positive_rcsd_present"],
        positive_rcsd_present_reason=fields["positive_rcsd_present_reason"],
        positive_rcsd_support_level=fields["positive_rcsd_support_level"],
        positive_rcsd_consistency_level=fields["positive_rcsd_consistency_level"],
        rcsd_alignment_type=fields["rcsd_alignment_type"],
        rcsd_selection_mode=fields["rcsd_selection_mode"],
        selected_evidence_summary=fields["selected_evidence_summary"],
        selected_candidate_summary=fields["selected_candidate_summary"],
        fact_reference_point=fields["fact_reference_point"],
        review_materialized_point=fields["review_materialized_point"],
        **_decision_kwargs_from_unit_fields(fields),
        decision_trace=trace,
        downgrade_from=downgrade_from,
        downgrade_to=downgrade_to,
        downgrade_reason=downgrade_reason,
        suppressed_rcsd_snapshot=dict(suppressed_rcsd_snapshot or {}),
        aggregate_rcsd_consistency_score=aggregate_score,
    )


def _decision_from_candidate(
    unit: T04EventUnitResult,
    candidate: T04Step4Candidate,
    *,
    trace: tuple[dict[str, Any], ...],
) -> T04ArbitrationDecision:
    candidate_snapshot = _candidate_unit_snapshot(candidate)
    scenario_doc = _candidate_scenario_doc(candidate, unit)
    selected_evidence_summary = dict(
        candidate_snapshot.get("selected_evidence_summary") or unit.selected_evidence_summary
    )
    selected_candidate_summary = dict(
        candidate_snapshot.get("selected_candidate_summary") or unit.selected_candidate_summary
    )
    positive_present = bool(
        candidate_snapshot.get("positive_rcsd_present")
        if "positive_rcsd_present" in candidate_snapshot
        else _candidate_positive(candidate)
    )
    positive_reason = _clean_text(
        candidate_snapshot.get("positive_rcsd_present_reason")
        or selected_evidence_summary.get("positive_rcsd_present_reason")
        or selected_candidate_summary.get("positive_rcsd_present_reason")
        or candidate.replacement_reason
        or candidate.source_stage
    )
    required_rcsd_node_source = _clean_text(
        candidate_snapshot.get("required_rcsd_node_source")
        or selected_evidence_summary.get("required_rcsd_node_source")
        or selected_candidate_summary.get("required_rcsd_node_source")
    )
    return T04ArbitrationDecision(
        selected_rcsdroad_ids=candidate.rcsdroad_ids,
        selected_rcsdnode_ids=candidate.rcsdnode_ids,
        required_rcsd_node=candidate.required_rcsd_node,
        positive_rcsd_present=positive_present,
        positive_rcsd_present_reason=positive_reason,
        positive_rcsd_support_level=candidate.support_level,
        positive_rcsd_consistency_level=candidate.consistency_level,
        rcsd_alignment_type=candidate.rcsd_alignment_type or RCSD_ALIGNMENT_NONE,
        rcsd_selection_mode=(
            _clean_text(candidate_snapshot.get("rcsd_selection_mode"))
            or _clean_text(selected_evidence_summary.get("rcsd_selection_mode"))
            or _clean_text(selected_candidate_summary.get("rcsd_selection_mode"))
            or candidate.source_stage
        ),
        required_rcsd_node_source=required_rcsd_node_source or candidate.source_stage,
        selected_evidence_summary=selected_evidence_summary,
        selected_candidate_summary=selected_candidate_summary,
        fact_reference_point=(
            candidate.reference_point if candidate.reference_point is not None else unit.fact_reference_point
        ),
        review_materialized_point=(
            candidate.reference_point if candidate.reference_point is not None else unit.review_materialized_point
        ),
        **_scenario_decision_kwargs(scenario_doc),
        decision_trace=trace,
        rcsd_replacement_due_to_main_evidence=candidate.replacement_reason in _MAIN_EVIDENCE_REPLACEMENT_REASONS,
        aggregate_rcsd_consistency_score=candidate.aggregate_consistency_score,
    )


def _trace_docs(
    scored_candidates: tuple[T04Step4Candidate, ...],
    *,
    selected_candidate_id: str,
    context: T04ArbiterCaseContext,
) -> tuple[dict[str, Any], ...]:
    ranked = sorted(scored_candidates, key=lambda item: _candidate_sort_key(item, context), reverse=True)
    docs: list[dict[str, Any]] = []
    for rank, candidate in enumerate(ranked, start=1):
        docs.append(
            {
                "rank": rank,
                "selected": candidate.candidate_id == selected_candidate_id,
                "candidate": candidate.to_doc(),
                "sort_key": list(_candidate_sort_key(candidate, context)),
                "is_positive_candidate": _candidate_positive(candidate),
                "shadow_mode": context.shadow_mode,
            }
        )
    return tuple(docs)


def _strong_positive(fields: Mapping[str, Any]) -> bool:
    return bool(
        fields.get("positive_rcsd_present")
        and _clean_text(fields.get("required_rcsd_node"))
        and _clean_text(fields.get("rcsd_alignment_type")) in RCSD_ALIGNMENT_JUNCTION_LEVEL_TYPES
    )


def _downgraded(pre_fields: Mapping[str, Any], post_fields: Mapping[str, Any]) -> bool:
    return _strong_positive(pre_fields) and not _strong_positive(post_fields)


def _downgrade_reason(candidate: T04Step4Candidate | None) -> str:
    if candidate is None:
        return ""
    return (
        _clean_text(candidate.replacement_reason)
        or _clean_text(candidate.reject_reason)
        or next((_clean_text(flag) for flag in candidate.conflict_flags if _clean_text(flag)), "")
    )


def _apply_destructive_downgrade_guard(
    unit: T04EventUnitResult,
    decision: T04ArbitrationDecision,
    *,
    winner: T04Step4Candidate | None,
    context: T04ArbiterCaseContext,
) -> T04ArbitrationDecision:
    pre_fields = _snapshot(unit)
    post_fields = _json_safe(decision.as_field_kwargs())
    if not _downgraded(pre_fields, post_fields):
        return decision
    reason = _downgrade_reason(winner)
    if reason in set(context.downgrade_reason_whitelist):
        return T04ArbitrationDecision(
            **decision.as_field_kwargs(),
            decision_trace=(
                *decision.decision_trace,
                {
                    "event": "destructive_downgrade_allowed",
                    "reason": reason,
                    "whitelist": list(context.downgrade_reason_whitelist),
                },
            ),
            downgrade_from=pre_fields,
            downgrade_to=post_fields,
            downgrade_reason=reason,
            suppressed_rcsd_snapshot={},
            rcsd_replacement_due_to_main_evidence=decision.rcsd_replacement_due_to_main_evidence,
            aggregate_rcsd_consistency_score=decision.aggregate_rcsd_consistency_score,
        )
    return _decision_from_unit(
        unit,
        trace=(
            *decision.decision_trace,
            {
                "event": "STEP4_REVIEW",
                "reason": "rcsd_destructive_downgrade_blocked",
                "blocked_reason": reason,
                "whitelist": list(context.downgrade_reason_whitelist),
            },
        ),
        aggregate_score=decision.aggregate_rcsd_consistency_score,
        downgrade_from=pre_fields,
        downgrade_to=post_fields,
        downgrade_reason="rcsd_destructive_downgrade_blocked",
        suppressed_rcsd_snapshot=post_fields,
    )


def arbitrate_step4_unit(
    unit: T04EventUnitResult,
    ledger: T04Step4CandidateLedger,
    *,
    case_context: T04ArbiterCaseContext,
) -> T04ArbitrationDecision:
    scored_candidates = score_step4_candidates(ledger.candidates)
    if not scored_candidates:
        trace = (
            {
                "event": "no_step4_candidates",
                "case_id": case_context.case_id,
                "unit_id": case_context.unit_id,
                "shadow_mode": case_context.shadow_mode,
            },
        )
        return _decision_from_unit(unit, trace=trace)

    positive_candidates = tuple(candidate for candidate in scored_candidates if _candidate_positive(candidate))
    if positive_candidates:
        arbitration_pool, rearbitration_note = _main_evidence_rearbitration_pool(unit, positive_candidates)
        ranked = sorted(
            arbitration_pool,
            key=lambda item: _candidate_sort_key(item, case_context),
            reverse=True,
        )
        winner = ranked[0]
        trace = _trace_docs(scored_candidates, selected_candidate_id=winner.candidate_id, context=case_context)
        if rearbitration_note is not None:
            trace = (*trace, rearbitration_note)
        decision = _decision_from_candidate(unit, winner, trace=trace)
        return _apply_destructive_downgrade_guard(unit, decision, winner=winner, context=case_context)

    trace = (
        *_trace_docs(scored_candidates, selected_candidate_id="", context=case_context),
        {
            "event": "no_positive_step4_candidate",
            "case_id": case_context.case_id,
            "unit_id": case_context.unit_id,
            "shadow_mode": case_context.shadow_mode,
        },
    )
    unit_scenario_doc = unit.surface_scenario_doc()
    fallback_rcsdroad_ids = _clean_ids(unit_scenario_doc.get("fallback_rcsdroad_ids"))
    if (
        _clean_text(unit_scenario_doc.get("rcsd_alignment_type")) == RCSD_ALIGNMENT_ROAD_ONLY
        and bool(fallback_rcsdroad_ids)
        and bool(unit_scenario_doc.get("swsd_junction_present"))
    ):
        event_name = (
            "preserve_main_evidence_rcsdroad_fallback_without_positive_candidate"
            if bool(unit_scenario_doc.get("has_main_evidence"))
            else "preserve_swsd_rcsdroad_fallback_without_positive_candidate"
        )
        decision = _decision_from_unit(
            unit,
            trace=(
                *trace,
                {
                    "event": event_name,
                    "case_id": case_context.case_id,
                    "unit_id": case_context.unit_id,
                    "fallback_rcsdroad_ids": list(fallback_rcsdroad_ids),
                },
            ),
        )
        return _apply_destructive_downgrade_guard(unit, decision, winner=None, context=case_context)

    scenario_doc = classify_surface_scenario_from_alignment(
        has_main_evidence=bool(unit_scenario_doc["has_main_evidence"]),
        rcsd_alignment_type=RCSD_ALIGNMENT_NONE,
        swsd_junction_present=bool(unit_scenario_doc["swsd_junction_present"]),
        main_evidence_type=unit_scenario_doc["main_evidence_type"],
        reference_point_present=unit.fact_reference_point is not None,
    ).to_doc()
    decision = T04ArbitrationDecision(
        selected_evidence_summary=dict(unit.selected_evidence_summary),
        selected_candidate_summary=dict(unit.selected_candidate_summary),
        fact_reference_point=unit.fact_reference_point,
        review_materialized_point=unit.review_materialized_point,
        **_scenario_decision_kwargs(scenario_doc),
        decision_trace=trace,
    )
    return _apply_destructive_downgrade_guard(unit, decision, winner=None, context=case_context)


def apply_step4_arbitration_to_unit(
    unit: T04EventUnitResult,
    *,
    case_id: str,
    mainnodeid: str = "",
    shadow_mode: bool | None = None,
) -> T04EventUnitResult:
    ledger = unit.step4_candidate_ledger or T04Step4CandidateLedger(
        unit_id=unit.spec.event_unit_id,
        case_id=case_id,
    )
    context = T04ArbiterCaseContext(
        case_id=case_id,
        unit_id=unit.spec.event_unit_id,
        mainnodeid=mainnodeid or unit.spec.representative_node_id,
        shadow_mode=_shadow_mode_from_env() if shadow_mode is None else bool(shadow_mode),
    )
    decision = arbitrate_step4_unit(unit, ledger, case_context=context)
    if context.shadow_mode:
        return unit
    unit_field_names = {field.name for field in fields(unit)}
    field_kwargs = {
        field_name: value
        for field_name, value in decision.as_field_kwargs().items()
        if field_name in unit_field_names
    }
    return replace(unit, **field_kwargs)


def apply_step4_arbitration_to_case_result(
    case_result,
    *,
    shadow_mode: bool | None = None,
):
    units = [
        apply_step4_arbitration_to_unit(
            unit,
            case_id=case_result.case_spec.case_id,
            mainnodeid=case_result.case_spec.mainnodeid,
            shadow_mode=shadow_mode,
        )
        for unit in case_result.event_units
    ]
    if all(unit is original for unit, original in zip(units, case_result.event_units)):
        return case_result
    state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in units):
        state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in units):
        state = "STEP4_REVIEW"
    reasons = tuple(dict.fromkeys(reason for unit in units for reason in unit.all_review_reasons()))
    return replace(case_result, event_units=units, case_review_state=state, case_review_reasons=reasons)


def apply_step4_arbitration_to_case_results(
    case_results: Iterable[Any],
    *,
    shadow_mode: bool | None = None,
) -> list[Any]:
    return [
        apply_step4_arbitration_to_case_result(case_result, shadow_mode=shadow_mode)
        for case_result in case_results
    ]


def shadow_diff_for_unit(unit: T04EventUnitResult, decision: T04ArbitrationDecision) -> dict[str, Any]:
    actual = _json_safe(_unit_final_fields(unit))
    proposed = _json_safe(decision.as_field_kwargs())
    diffs: dict[str, Any] = {}
    for field_name in ARBITER_FINAL_FIELD_NAMES:
        if actual.get(field_name) == proposed.get(field_name):
            continue
        diffs[field_name] = {
            "unit_actual": actual.get(field_name),
            "arbitration_decision_shadow": proposed.get(field_name),
        }
    return diffs


def shadow_actual_fields_for_unit(unit: T04EventUnitResult) -> dict[str, Any]:
    return _json_safe(_unit_final_fields(unit))


__all__ = [
    "apply_step4_arbitration_to_case_result",
    "apply_step4_arbitration_to_case_results",
    "apply_step4_arbitration_to_unit",
    "arbitrate_step4_unit",
    "shadow_actual_fields_for_unit",
    "shadow_diff_for_unit",
]
