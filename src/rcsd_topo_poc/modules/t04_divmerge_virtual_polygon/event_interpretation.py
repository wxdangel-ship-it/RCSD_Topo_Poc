from __future__ import annotations

from dataclasses import replace

from ._event_interpretation_core import (
    _CandidateEvaluation,
    _PreparedUnitInputs,
    _apply_evidence_ownership_guards,
    _build_candidate_pool,
    _empty_selected_evidence_summary,
    _evaluate_unit_candidate,
    _prepare_unit_context,
    _prepare_unit_inputs,
    _rank_candidate_pool,
    _select_case_assignment,
)
from .admission import build_step1_admission
from .case_models import T04CandidateAuditEntry, T04CaseBundle, T04CaseResult, T04UnitContext
from .event_units import build_event_unit_specs

def build_case_result(case_bundle: T04CaseBundle) -> T04CaseResult:
    admission = build_step1_admission(
        representative_node=case_bundle.representative_node,
        group_nodes=case_bundle.group_nodes,
    )
    base_context = _prepare_unit_context(
        case_bundle=case_bundle,
        representative_node_id=case_bundle.representative_node.node_id,
        singleton_group=False,
    )
    event_unit_specs = build_event_unit_specs(case_bundle=case_bundle, unit_context=base_context)
    unit_context_cache: dict[tuple[str, bool], T04UnitContext] = {
        (base_context.representative_node.node_id, False): base_context,
    }
    prepared_units: list[_PreparedUnitInputs] = []
    for event_unit_spec in event_unit_specs:
        singleton_group = event_unit_spec.split_mode == "complex_one_node_one_unit"
        cache_key = (event_unit_spec.representative_node_id, singleton_group)
        if cache_key not in unit_context_cache:
            unit_context_cache[cache_key] = _prepare_unit_context(
                case_bundle=case_bundle,
                representative_node_id=event_unit_spec.representative_node_id,
                singleton_group=singleton_group,
            )
        prepared_units.append(
            _prepare_unit_inputs(
                case_bundle=case_bundle,
                unit_context=unit_context_cache[cache_key],
                event_unit_spec=event_unit_spec,
            )
        )
    candidate_pools: list[list[_CandidateEvaluation]] = []
    for prepared in prepared_units:
        raw_candidates = _build_candidate_pool(prepared)
        evaluations = _rank_candidate_pool(
            [_evaluate_unit_candidate(prepared, candidate) for candidate in raw_candidates]
        )
        candidate_pools.append(evaluations)
    assignment_by_unit_index = _select_case_assignment(candidate_pools)

    event_units: list[T04EventUnitResult] = []
    for pool_index, evaluations in enumerate(candidate_pools):
        if not evaluations:
            continue
        selected_eval = assignment_by_unit_index[pool_index]
        selected_candidate_id = (
            str(selected_eval.result.selected_candidate_summary.get("candidate_id") or "")
            if selected_eval is not None
            else ""
        )
        selection_rank = next(
            (
                rank
                for rank, item in enumerate(evaluations, start=1)
                if item.result.selected_candidate_summary.get("candidate_id")
                == selected_candidate_id
            ),
            None,
        )
        alternative_candidates_list: list[dict[str, Any]] = []
        candidate_audit_entries: list[T04CandidateAuditEntry] = []
        for pool_rank, item in enumerate(evaluations, start=1):
            candidate_id = str(item.result.selected_candidate_summary.get("candidate_id") or "")
            candidate_summary = dict(item.result.selected_candidate_summary)
            candidate_summary["pool_rank"] = pool_rank
            candidate_summary["priority_score"] = int(item.priority_score)
            if selected_eval is not None and candidate_id == selected_candidate_id:
                selection_status = "selected"
                decision_reason = (
                    "selected_after_case_reselection"
                    if selection_rank is not None and selection_rank > 1
                    else "top_rank_selected"
                )
            elif assignment_by_unit_index[pool_index] is None:
                selection_status = "alternative"
                decision_reason = "not_selected_no_valid_primary_evidence"
            elif selection_rank is not None and pool_rank < selection_rank:
                selection_status = "alternative"
                decision_reason = "higher_raw_rank_rejected_in_case_reselection"
            else:
                selection_status = "alternative"
                decision_reason = "lower_priority_than_selected"
            candidate_summary["selection_status"] = selection_status
            candidate_summary["decision_reason"] = decision_reason
            if candidate_id != selected_candidate_id:
                alternative_candidates_list.append(dict(candidate_summary))
            candidate_audit_entries.append(
                T04CandidateAuditEntry(
                    candidate_id=candidate_id,
                    pool_rank=pool_rank,
                    priority_score=int(item.priority_score),
                    selection_status=selection_status,
                    decision_reason=decision_reason,
                    candidate_summary=dict(candidate_summary),
                    review_state=item.result.review_state,
                    review_reasons=item.result.all_review_reasons(),
                    evidence_source=item.result.evidence_source,
                    position_source=item.result.position_source,
                    reverse_tip_used=bool(item.result.reverse_tip_used),
                    rcsd_consistency_result=item.result.rcsd_consistency_result,
                    positive_rcsd_support_level=item.result.positive_rcsd_support_level,
                    positive_rcsd_consistency_level=item.result.positive_rcsd_consistency_level,
                    required_rcsd_node=item.result.required_rcsd_node,
                    candidate_region_geometry=item.result.selected_evidence_region_geometry,
                    fact_reference_point=item.result.fact_reference_point,
                    review_materialized_point=item.result.review_materialized_point,
                    localized_evidence_core_geometry=item.result.localized_evidence_core_geometry,
                    selected_component_union_geometry=item.result.selected_component_union_geometry,
                )
            )
        alternative_candidates = tuple(alternative_candidates_list)
        if selected_eval is None:
            template_result = evaluations[0].result
            empty_summary = _empty_selected_evidence_summary(
                decision_reason="no_selected_evidence_after_reselection"
            )
            review_state = (
                "STEP4_FAIL"
                if all(item.result.review_state == "STEP4_FAIL" for item in evaluations)
                else "STEP4_REVIEW"
            )
            finalized_result = replace(
                template_result,
                review_state=review_state,
                evidence_source="none",
                position_source="none",
                rcsd_consistency_result="missing_positive_rcsd",
                selected_component_union_geometry=None,
                localized_evidence_core_geometry=None,
                coarse_anchor_zone_geometry=None,
                selected_evidence_region_geometry=None,
                fact_reference_point=None,
                review_materialized_point=None,
                pair_local_rcsd_scope_geometry=None,
                first_hit_rcsd_road_geometry=None,
                local_rcsd_unit_geometry=None,
                positive_rcsd_geometry=None,
                positive_rcsd_road_geometry=None,
                positive_rcsd_node_geometry=None,
                primary_main_rc_node_geometry=None,
                required_rcsd_node_geometry=None,
                selected_branch_ids=(),
                selected_event_branch_ids=(),
                selected_component_ids=(),
                first_hit_rcsdroad_ids=(),
                selected_rcsdroad_ids=(),
                selected_rcsdnode_ids=(),
                primary_main_rc_node_id=None,
                local_rcsd_unit_id=None,
                local_rcsd_unit_kind=None,
                aggregated_rcsd_unit_id=None,
                aggregated_rcsd_unit_ids=(),
                positive_rcsd_present=False,
                positive_rcsd_present_reason="no_selected_evidence_after_reselection",
                axis_polarity_inverted=False,
                rcsd_selection_mode="no_selected_evidence",
                positive_rcsd_support_level="no_support",
                positive_rcsd_consistency_level="C",
                required_rcsd_node=None,
                required_rcsd_node_source=None,
                event_axis_branch_id=None,
                event_chosen_s_m=None,
                positive_rcsd_audit={
                    "pair_local_rcsd_empty": bool(template_result.pair_local_rcsd_empty),
                    "pair_local_rcsd_road_ids": list(template_result.pair_local_rcsd_road_ids),
                    "pair_local_rcsd_node_ids": list(template_result.pair_local_rcsd_node_ids),
                    "first_hit_rcsdroad_ids": [],
                    "local_rcsd_units": [],
                    "aggregated_rcsd_units": [],
                    "positive_rcsd_present": False,
                    "positive_rcsd_present_reason": "no_selected_evidence_after_reselection",
                    "axis_polarity_inverted": False,
                    "required_rcsd_node_source": None,
                    "rcsd_role_map": {},
                    "rcsd_decision_reason": "no_selected_evidence_after_reselection",
                },
                selected_candidate_summary=dict(empty_summary),
                selected_evidence_summary=dict(empty_summary),
                alternative_candidate_summaries=alternative_candidates,
                candidate_audit_entries=tuple(candidate_audit_entries),
                extra_review_notes=tuple(
                    dict.fromkeys(
                        [*template_result.extra_review_notes, "no_selected_evidence_after_reselection"]
                    )
                ),
            )
        else:
            selected_candidate_summary = dict(selected_eval.result.selected_candidate_summary)
            selected_candidate_summary["selection_rank"] = selection_rank
            selected_candidate_summary["pool_rank"] = selection_rank
            selected_candidate_summary["priority_score"] = int(selected_eval.priority_score)
            selected_candidate_summary["selected_after_reselection"] = bool(
                selection_rank is not None and selection_rank > 1
            )
            selected_candidate_summary["selection_status"] = "selected"
            selected_candidate_summary["decision_reason"] = (
                "selected_after_case_reselection"
                if selection_rank is not None and selection_rank > 1
                else "top_rank_selected"
            )
            finalized_result = replace(
                selected_eval.result,
                selected_candidate_summary=selected_candidate_summary,
                selected_evidence_summary=dict(selected_candidate_summary),
                alternative_candidate_summaries=alternative_candidates,
                candidate_audit_entries=tuple(candidate_audit_entries),
            )
            if selection_rank is not None and selection_rank > 1:
                finalized_result = replace(
                    finalized_result,
                    extra_review_notes=tuple(
                        dict.fromkeys([*finalized_result.extra_review_notes, "reselected_within_case"])
                    ),
                )
        event_units.append(finalized_result)
    guarded_units = _apply_evidence_ownership_guards(event_units)
    case_review_state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in guarded_units):
        case_review_state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in guarded_units):
        case_review_state = "STEP4_REVIEW"
    case_review_reasons = tuple(
        dict.fromkeys(
            reason
            for unit in guarded_units
            for reason in unit.all_review_reasons()
        )
    )
    return T04CaseResult(
        case_spec=case_bundle.case_spec,
        case_bundle=case_bundle,
        admission=admission,
        base_context=base_context,
        event_units=guarded_units,
        case_review_state=case_review_state,
        case_review_reasons=case_review_reasons,
    )
