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
from .rcsd_alignment import RCSD_ALIGNMENT_NONE, RCSD_ALIGNMENT_SEMANTIC_JUNCTION


def _candidate_state_key(summary: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(summary.get("candidate_id") or ""),
        str(summary.get("layer_label") or summary.get("layer") or ""),
        str(summary.get("local_region_id") or ""),
        str(summary.get("point_signature") or ""),
    )


def _node_id_from_local_rcsd_unit(unit_id: str | None) -> str:
    text = str(unit_id or "").strip()
    if ":node:" not in text:
        return ""
    return text.rsplit(":node:", 1)[-1].strip()


def _incident_rcsd_road_ids(case_bundle: T04CaseBundle, node_id: str) -> tuple[str, ...]:
    if not node_id:
        return ()
    incident: list[str] = []
    for road in case_bundle.rcsd_roads:
        road_id = str(getattr(road, "road_id", "") or "").strip()
        if not road_id:
            continue
        endpoint_ids = {
            str(getattr(road, "snodeid", "") or "").strip(),
            str(getattr(road, "enodeid", "") or "").strip(),
        }
        if node_id in endpoint_ids:
            incident.append(road_id)
    return tuple(dict.fromkeys(incident))


def _rcsd_node_geometry(case_bundle: T04CaseBundle, node_id: str):
    if not node_id:
        return None
    for node in case_bundle.rcsd_nodes:
        if str(getattr(node, "node_id", "") or "").strip() == node_id:
            return getattr(node, "geometry", None)
    return None


def _normalize_unique_local_rcsd_junction(
    unit_result,
    *,
    case_bundle: T04CaseBundle,
):
    if unit_result.rcsd_alignment_type != RCSD_ALIGNMENT_SEMANTIC_JUNCTION:
        return unit_result
    local_node_id = _node_id_from_local_rcsd_unit(unit_result.local_rcsd_unit_id)
    if not local_node_id or unit_result.local_rcsd_unit_kind != "node_centric":
        return unit_result
    incident_road_ids = set(_incident_rcsd_road_ids(case_bundle, local_node_id))
    selected_road_ids = {
        str(road_id).strip()
        for road_id in unit_result.selected_rcsdroad_ids
        if str(road_id).strip()
    }
    if len(incident_road_ids) < 3 or not selected_road_ids or not selected_road_ids <= incident_road_ids:
        return unit_result
    if unit_result.required_rcsd_node == local_node_id:
        return unit_result

    node_geometry = _rcsd_node_geometry(case_bundle, local_node_id)
    audit = dict(unit_result.positive_rcsd_audit or {})
    audit["required_rcsd_node_before_unique_local_junction"] = unit_result.required_rcsd_node
    audit["required_rcsd_node_after_unique_local_junction"] = local_node_id
    audit["required_rcsd_node_source"] = "unique_local_rcsd_semantic_junction"
    audit["unique_local_rcsd_semantic_junction_node_id"] = local_node_id
    return replace(
        unit_result,
        required_rcsd_node=local_node_id,
        required_rcsd_node_source="unique_local_rcsd_semantic_junction",
        required_rcsd_node_geometry=node_geometry,
        positive_rcsd_audit=audit,
    )


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
        selected_candidate_key = (
            _candidate_state_key(selected_eval.result.selected_candidate_summary)
            if selected_eval is not None
            else ("", "", "", "")
        )
        selected_candidate_id = selected_candidate_key[0]
        selection_rank = next(
            (
                rank
                for rank, item in enumerate(evaluations, start=1)
                if _candidate_state_key(item.result.selected_candidate_summary) == selected_candidate_key
            ),
            None,
        )
        alternative_candidates_list: list[dict[str, Any]] = []
        candidate_audit_entries: list[T04CandidateAuditEntry] = []
        for pool_rank, item in enumerate(evaluations, start=1):
            candidate_key = _candidate_state_key(item.result.selected_candidate_summary)
            candidate_id = candidate_key[0]
            candidate_summary = dict(item.result.selected_candidate_summary)
            candidate_summary["pool_rank"] = pool_rank
            candidate_summary["priority_score"] = int(item.priority_score)
            if selected_eval is not None and candidate_key == selected_candidate_key:
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
            if candidate_key != selected_candidate_key:
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
                    rcsd_alignment_type=item.result.surface_scenario_doc()["rcsd_alignment_type"],
                    required_rcsd_node=item.result.required_rcsd_node,
                    candidate_region_geometry=item.result.selected_evidence_region_geometry,
                    fact_reference_point=item.result.fact_reference_point,
                    review_materialized_point=item.result.review_materialized_point,
                    localized_evidence_core_geometry=item.result.localized_evidence_core_geometry,
                    selected_component_union_geometry=item.result.selected_component_union_geometry,
                    selected_candidate_region=item.result.selected_candidate_region,
                    selected_evidence_region_geometry=item.result.selected_evidence_region_geometry,
                    selected_branch_ids=item.result.selected_branch_ids,
                    selected_event_branch_ids=item.result.selected_event_branch_ids,
                    selected_component_ids=item.result.selected_component_ids,
                    pair_local_rcsd_road_ids=item.result.pair_local_rcsd_road_ids,
                    pair_local_rcsd_node_ids=item.result.pair_local_rcsd_node_ids,
                    first_hit_rcsdroad_ids=item.result.first_hit_rcsdroad_ids,
                    selected_rcsdroad_ids=item.result.selected_rcsdroad_ids,
                    selected_rcsdnode_ids=item.result.selected_rcsdnode_ids,
                    primary_main_rc_node_id=item.result.primary_main_rc_node_id,
                    local_rcsd_unit_id=item.result.local_rcsd_unit_id,
                    local_rcsd_unit_kind=item.result.local_rcsd_unit_kind,
                    aggregated_rcsd_unit_id=item.result.aggregated_rcsd_unit_id,
                    aggregated_rcsd_unit_ids=item.result.aggregated_rcsd_unit_ids,
                    positive_rcsd_present=item.result.positive_rcsd_present,
                    positive_rcsd_present_reason=item.result.positive_rcsd_present_reason,
                    axis_polarity_inverted=bool(item.result.axis_polarity_inverted),
                    rcsd_selection_mode=item.result.rcsd_selection_mode,
                    pair_local_rcsd_empty=bool(item.result.pair_local_rcsd_empty),
                    required_rcsd_node_source=item.result.required_rcsd_node_source,
                    event_axis_branch_id=item.result.event_axis_branch_id,
                    event_chosen_s_m=item.result.event_chosen_s_m,
                    positive_rcsd_audit=dict(item.result.positive_rcsd_audit),
                    pair_local_rcsd_scope_geometry=item.result.pair_local_rcsd_scope_geometry,
                    first_hit_rcsd_road_geometry=item.result.first_hit_rcsd_road_geometry,
                    local_rcsd_unit_geometry=item.result.local_rcsd_unit_geometry,
                    positive_rcsd_geometry=item.result.positive_rcsd_geometry,
                    positive_rcsd_road_geometry=item.result.positive_rcsd_road_geometry,
                    positive_rcsd_node_geometry=item.result.positive_rcsd_node_geometry,
                    primary_main_rc_node_geometry=item.result.primary_main_rc_node_geometry,
                    required_rcsd_node_geometry=item.result.required_rcsd_node_geometry,
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
                    "rcsd_alignment_type": RCSD_ALIGNMENT_NONE,
                    "rcsd_role_map": {},
                    "rcsd_decision_reason": "no_selected_evidence_after_reselection",
                },
                rcsd_alignment_type=RCSD_ALIGNMENT_NONE,
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
            finalized_result = _normalize_unique_local_rcsd_junction(
                finalized_result,
                case_bundle=case_bundle,
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
