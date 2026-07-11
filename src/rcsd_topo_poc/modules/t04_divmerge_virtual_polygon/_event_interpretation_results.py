from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_core import (
    PAIR_LOCAL_BRANCH_MAX_LENGTH_M,
    _explode_component_geometries,
    _node_source_kind_2,
    _resolve_branch_centerline,
    _resolve_event_axis_branch,
    _resolve_scan_axis_unit_vector,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_base import (
    _build_pair_local_slice_diagnostic,
    _pick_cross_section_boundary_branches,
    _resolve_event_axis_unit_vector,
    _resolve_event_cross_half_len,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_kernel import (
    _build_stage4_event_interpretation,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    ParsedRoad,
    _resolve_group,
)

from ._step4_dual_write import append_dual_write_candidate, replace_step4_pre_arbiter_candidate
from .admission import build_step1_admission
from .case_models import (
    T04CandidateAuditEntry,
    T04CaseBundle,
    T04CaseResult,
    T04EventUnitResult,
    T04UnitEnvelope,
    T04UnitContext,
)
from .event_units import build_event_unit_specs
from .event_interpretation_branch_variants import (
    _build_complex_executable_branch_variants,
    _build_direct_adjacency_branch_set,
)
from .event_interpretation_selection import (
    _apply_evidence_ownership_guards,
    _candidate_priority_score,
    _merge_candidate_evaluation,
    _rank_candidate_pool,
    _select_case_assignment,
)
from .event_interpretation_shared import (
    _CandidateEvaluation,
    _ExecutableBranchSet,
    _PreparedUnitInputs,
    _area_ratio,
    _clip_geometry_to_scope,
    _explode_polygon_geometries,
    _filter_divstrip_features_to_scope,
    _filter_nodes_to_scope,
    _filter_roads_to_scope,
    _geometry_present,
    _road_lookup,
    _safe_normalize_geometry,
    _stable_axis_position,
    _stable_axis_signature,
    _stable_boundary_pair_signature,
)
from .rcsd_alignment import RCSD_ALIGNMENT_NONE, build_rcsd_semantic_junction, build_rcsdroad_only_chain

from ._event_interpretation_unit_preparation import (
    DIVSTRIP_EVIDENCE_TIP_RADIUS_M,
    MAX_CANDIDATES_PER_UNIT,
    NODE_FALLBACK_AXIS_POSITION_MAX_M,
    NODE_FALLBACK_DISTANCE_MAX_M,
    PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    PAIR_LOCAL_REGION_PAD_M,
    PAIR_LOCAL_SCOPE_PAD_M,
    ROAD_SURFACE_FORK_SCOPE,
    STRUCTURE_BODY_THROAT_EXCLUSION_M,
    _degraded_scope_metadata,
    _effective_complex_kind_hint,
    _materialize_prepared_unit_inputs,
)
from .local_context import build_step2_local_context
from .rcsd_selection import resolve_positive_rcsd_selection


ROAD_SURFACE_RELAXED_RCSD_MAX_SEMANTIC_DISTANCE_M = 60.0
ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON = (
    "road_surface_fork_structural_required_rcsd_handoff"
)
_STRUCTURAL_REQUIRED_MIN_CONSISTENCY_LEVELS = {"A", "B"}
_STRUCTURAL_REQUIRED_MIN_SUPPORT_LEVELS = {"primary_support", "secondary_support"}
from .step4_road_surface_fork_geometry import (
    _ordered_line_from_point,
    _surface_fork_boundary_apex_point,
)
from .topology import build_step3_topology
from .variant_ranking import (
    _pair_interval_variant_metrics_from_data,
    _prepared_variant_rank,
)

SIMPLE_SURFACE_FORK_MAX_REFERENCE_DISTANCE_M = 80.0



from ._event_interpretation_context import (
    _apply_positive_rcsd_audit_to_summary,
    _boundary_pair_road_ids_from_summary,
    _candidate_layer,
    _candidate_summary,
    _filter_branch_scope,
    _materialize_event_anchor_geometry,
    _materialize_event_reference_point,
    _materialize_selected_divstrip_geometry,
    _point_signature,
    _positive_rcsd_geometry,
    _prepare_unit_context,
    _reference_point_from_region,
    _road_linestring,
    _road_surface_fork_apex_reference,
    _seed_union,
    _singleton_group,
    _sorted_id_tuple,
    _structural_required_rcsd_handoff_detail,
)

from ._event_interpretation_candidates import (
    _build_candidate_pool,
    _build_unit_envelope,
)

def _build_result_from_interpretation(
    *,
    prepared: _PreparedUnitInputs,
    interpretation,
    selected_candidate_summary: dict[str, Any],
    selected_evidence_region_geometry: BaseGeometry | None,
    selected_reference_point: BaseGeometry | None,
) -> T04EventUnitResult:
    bridge = interpretation.legacy_step5_bridge
    candidate_scope = str(selected_candidate_summary.get("candidate_scope") or "")
    road_surface_fork_candidate = candidate_scope == ROAD_SURFACE_FORK_SCOPE
    selected_component_union_geometry = bridge.divstrip_context.constraint_geometry
    localized_evidence_core_geometry = _materialize_selected_divstrip_geometry(
        interpretation=interpretation,
        selected_divstrip_geometry=selected_component_union_geometry,
        localized_divstrip_geometry=bridge.localized_divstrip_reference_geometry,
    )
    if road_surface_fork_candidate and _geometry_present(selected_evidence_region_geometry):
        selected_component_union_geometry = selected_evidence_region_geometry
        localized_evidence_core_geometry = selected_evidence_region_geometry
    coarse_anchor_zone_geometry = _materialize_event_anchor_geometry(
        interpretation=interpretation,
        selected_divstrip_geometry=localized_evidence_core_geometry,
        drivezone_union=prepared.pair_local_drivezone_union,
    )
    display_reference_geometry = selected_evidence_region_geometry or localized_evidence_core_geometry or selected_component_union_geometry
    display_reference_point = None
    if str(selected_candidate_summary.get("upper_evidence_kind") or "") == "divstrip":
        display_reference_point = _reference_point_from_region(
            region_geometry=display_reference_geometry,
            axis_origin_point=prepared.pair_local_axis_origin_point or prepared.unit_context.representative_node.geometry,
            reference_strategy="formation",
        )
    fact_reference_point = display_reference_point or selected_reference_point or bridge.event_origin_point
    review_materialized_point = _materialize_event_reference_point(
        interpretation=interpretation,
        selected_divstrip_geometry=localized_evidence_core_geometry,
    )
    rcsd_axis_vector = prepared.pair_local_axis_unit_vector
    if (
        rcsd_axis_vector is not None
        and str(prepared.pair_local_summary.get("pair_local_direction") or "") == "reverse_fallback"
    ):
        rcsd_axis_vector = (-float(rcsd_axis_vector[0]), -float(rcsd_axis_vector[1]))
    positive_rcsd_decision = resolve_positive_rcsd_selection(
        event_unit_id=prepared.event_unit_spec.event_unit_id,
        operational_kind_hint=prepared.operational_kind_hint,
        representative_node=prepared.unit_context.representative_node,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=fact_reference_point,
        pair_local_region_geometry=prepared.pair_local_region_geometry,
        pair_local_middle_geometry=prepared.pair_local_middle_geometry,
        scoped_rcsd_roads=prepared.scoped_rcsd_roads,
        scoped_rcsd_nodes=prepared.scoped_rcsd_nodes,
        pair_local_scope_rcsd_roads=prepared.pair_local_scope_rcsd_roads,
        pair_local_scope_rcsd_nodes=prepared.pair_local_scope_rcsd_nodes,
        scoped_roads=prepared.scoped_roads,
        boundary_branch_ids=prepared.boundary_branch_ids,
        preferred_axis_branch_id=prepared.preferred_axis_branch_id,
        scoped_input_branch_ids=prepared.scoped_input_branch_ids,
        scoped_output_branch_ids=prepared.scoped_output_branch_ids,
        branch_road_memberships=prepared.branch_road_memberships,
        axis_vector=rcsd_axis_vector,
        allow_semantic_endpoint_expansion=road_surface_fork_candidate,
    )
    positive_rcsd_support_level = positive_rcsd_decision.positive_rcsd_support_level
    positive_rcsd_consistency_level = positive_rcsd_decision.positive_rcsd_consistency_level
    rcsd_consistency_result = positive_rcsd_decision.rcsd_consistency_result
    required_rcsd_node = positive_rcsd_decision.required_rcsd_node
    selected_candidate_summary = _apply_positive_rcsd_audit_to_summary(
        selected_candidate_summary,
        decision=positive_rcsd_decision,
    )
    review_reasons: list[str] = list(interpretation.review_signals)
    fail_reasons: list[str] = list(interpretation.hard_rejection_signals)
    fail_reasons.extend(interpretation.legacy_step5_readiness.reasons)
    if bridge.event_origin_point is None:
        fail_reasons.append("missing_event_reference_point")
    if not bridge.selected_branch_ids:
        fail_reasons.append("selected_branch_ids_empty")
    if rcsd_consistency_result != "positive_rcsd_strong_consistent":
        review_reasons.append(rcsd_consistency_result)
    if interpretation.evidence_decision.fallback_used and not road_surface_fork_candidate:
        review_reasons.append("fallback_to_weak_evidence")
    if prepared.degraded_scope_reason:
        review_reasons.append(f"degraded_scope:{prepared.degraded_scope_reason}")
        if str(prepared.pair_local_summary.get("degraded_scope_severity") or "") == "hard":
            fail_reasons.append("hard_degraded_scope")
    if road_surface_fork_candidate:
        fail_reasons = [
            reason
            for reason in fail_reasons
            if str(reason) not in {"event_reference_outside_branch_middle"}
        ]
        review_reasons = [
            reason
            for reason in review_reasons
            if str(reason) not in {"event_reference_outside_branch_middle", "fallback_to_weak_evidence"}
        ]
    if fail_reasons:
        review_state = "STEP4_FAIL"
        all_reasons = tuple(dict.fromkeys([*fail_reasons, *review_reasons]))
    elif review_reasons:
        review_state = "STEP4_REVIEW"
        all_reasons = tuple(dict.fromkeys(review_reasons))
    else:
        review_state = "STEP4_OK"
        all_reasons = ()
    selected_candidate_region_geometry = (
        prepared.pair_local_region_geometry
        or prepared.pair_local_structure_face_geometry
        or prepared.pair_local_middle_geometry
    )
    selected_candidate_region = str(prepared.pair_local_summary.get("region_id") or "").strip() or None
    event_chosen_s_m = interpretation.event_reference.event_chosen_s_m
    if road_surface_fork_candidate and event_chosen_s_m is None:
        try:
            event_chosen_s_m = float(selected_candidate_summary.get("axis_position_m"))
        except (TypeError, ValueError):
            event_chosen_s_m = None
    result = T04EventUnitResult(
        spec=prepared.event_unit_spec,
        unit_context=prepared.unit_context,
        unit_envelope=_build_unit_envelope(prepared),
        interpretation=interpretation,
        review_state=review_state,
        review_reasons=all_reasons,
        evidence_source=(
            "road_surface_fork"
            if road_surface_fork_candidate
            else interpretation.evidence_decision.primary_source
        ),
        position_source=(
            "road_surface_fork"
            if road_surface_fork_candidate
            else interpretation.event_reference.event_position_source
        ),
        reverse_tip_used=interpretation.reverse_tip_decision.used,
        rcsd_consistency_result=rcsd_consistency_result,
        selected_component_union_geometry=selected_component_union_geometry,
        localized_evidence_core_geometry=localized_evidence_core_geometry,
        coarse_anchor_zone_geometry=coarse_anchor_zone_geometry,
        pair_local_region_geometry=prepared.pair_local_region_geometry,
        pair_local_structure_face_geometry=prepared.pair_local_structure_face_geometry,
        pair_local_middle_geometry=prepared.pair_local_middle_geometry,
        pair_local_throat_core_geometry=prepared.pair_local_throat_core_geometry,
        selected_candidate_region=selected_candidate_region,
        selected_candidate_region_geometry=selected_candidate_region_geometry,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        fact_reference_point=fact_reference_point,
        review_materialized_point=review_materialized_point,
        pair_local_rcsd_scope_geometry=positive_rcsd_decision.pair_local_rcsd_scope_geometry,
        first_hit_rcsd_road_geometry=positive_rcsd_decision.first_hit_rcsd_road_geometry,
        local_rcsd_unit_geometry=positive_rcsd_decision.local_rcsd_unit_geometry,
        positive_rcsd_geometry=positive_rcsd_decision.positive_rcsd_geometry,
        positive_rcsd_road_geometry=positive_rcsd_decision.positive_rcsd_road_geometry,
        positive_rcsd_node_geometry=positive_rcsd_decision.positive_rcsd_node_geometry,
        primary_main_rc_node_geometry=positive_rcsd_decision.primary_main_rc_node_geometry,
        required_rcsd_node_geometry=positive_rcsd_decision.required_rcsd_node_geometry,
        selected_branch_ids=tuple(bridge.selected_branch_ids),
        selected_event_branch_ids=tuple(bridge.selected_event_branch_ids),
        selected_component_ids=tuple(bridge.divstrip_context.selected_component_ids),
        pair_local_rcsd_road_ids=positive_rcsd_decision.pair_local_rcsd_road_ids,
        pair_local_rcsd_node_ids=positive_rcsd_decision.pair_local_rcsd_node_ids,
        first_hit_rcsdroad_ids=positive_rcsd_decision.first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=positive_rcsd_decision.selected_rcsdroad_ids,
        selected_rcsdnode_ids=positive_rcsd_decision.selected_rcsdnode_ids,
        primary_main_rc_node_id=positive_rcsd_decision.primary_main_rc_node_id,
        local_rcsd_unit_id=positive_rcsd_decision.local_rcsd_unit_id,
        local_rcsd_unit_kind=positive_rcsd_decision.local_rcsd_unit_kind,
        aggregated_rcsd_unit_id=positive_rcsd_decision.aggregated_rcsd_unit_id,
        aggregated_rcsd_unit_ids=positive_rcsd_decision.aggregated_rcsd_unit_ids,
        positive_rcsd_present=positive_rcsd_decision.positive_rcsd_present,
        positive_rcsd_present_reason=positive_rcsd_decision.positive_rcsd_present_reason,
        axis_polarity_inverted=positive_rcsd_decision.axis_polarity_inverted,
        rcsd_selection_mode=positive_rcsd_decision.rcsd_selection_mode,
        pair_local_rcsd_empty=positive_rcsd_decision.pair_local_rcsd_empty,
        positive_rcsd_support_level=positive_rcsd_support_level,
        positive_rcsd_consistency_level=positive_rcsd_consistency_level,
        required_rcsd_node=required_rcsd_node,
        required_rcsd_node_source=positive_rcsd_decision.required_rcsd_node_source,
        rcsd_alignment_type=positive_rcsd_decision.rcsd_alignment_type,
        event_axis_branch_id=bridge.event_axis_branch_id,
        event_chosen_s_m=event_chosen_s_m,
        pair_local_summary=dict(prepared.pair_local_summary),
        selected_candidate_summary=dict(selected_candidate_summary),
        positive_rcsd_audit=dict(positive_rcsd_decision.positive_rcsd_audit),
        selected_evidence_summary=dict(selected_candidate_summary),
    )
    positive_audit = dict(positive_rcsd_decision.positive_rcsd_audit or {})
    selected_local_unit_id = str(positive_audit.get("local_rcsd_unit_id") or "").strip()
    selected_local_unit_exact = False
    for local_unit_doc in positive_audit.get("local_rcsd_units") or ():
        if not isinstance(local_unit_doc, dict):
            continue
        if str(local_unit_doc.get("unit_id") or "").strip() != selected_local_unit_id:
            continue
        selected_local_unit_exact = str(local_unit_doc.get("role_match_result") or "").strip() == "exact"
        break
    rcsd_decision_reason = str(positive_audit.get("rcsd_decision_reason") or "").strip()
    exact_aggregate_without_exact_local = bool(
        rcsd_decision_reason == "role_mapping_exact_aggregated"
        and not selected_local_unit_exact
    )
    selected_aggregate_id = str(positive_audit.get("aggregated_rcsd_unit_id") or "").strip()
    selected_aggregate_doc = next(
        (
            aggregate_doc
            for aggregate_doc in positive_audit.get("aggregated_rcsd_units") or ()
            if isinstance(aggregate_doc, dict)
            and str(aggregate_doc.get("unit_id") or "").strip() == selected_aggregate_id
        ),
        {},
    )
    try:
        aggregate_semantic_anchor_distance = float(
            selected_aggregate_doc.get("semantic_anchor_distance_m")
        )
    except (TypeError, ValueError):
        aggregate_semantic_anchor_distance = None
    selected_aggregate_semantic_group_count = len(
        {
            str(group_id).strip()
            for group_id in selected_aggregate_doc.get("semantic_group_ids") or ()
            if str(group_id).strip()
        }
    )
    selected_aggregate_first_hit_count = len(
        {
            str(road_id).strip()
            for road_id in positive_audit.get("first_hit_rcsdroad_ids") or ()
            if str(road_id).strip()
        }
    )
    relaxed_aggregate_too_far = bool(
        rcsd_decision_reason
        in {"role_mapping_partial_relaxed_aggregated", "role_mapping_partial_missing_arms"}
        and aggregate_semantic_anchor_distance is not None
        and aggregate_semantic_anchor_distance > ROAD_SURFACE_RELAXED_RCSD_MAX_SEMANTIC_DISTANCE_M
    )
    relaxed_multi_group_single_first_hit = bool(
        rcsd_decision_reason == "role_mapping_partial_relaxed_aggregated"
        and selected_aggregate_semantic_group_count > 1
        and selected_aggregate_first_hit_count < 2
    )
    structural_required_handoff_detail = _structural_required_rcsd_handoff_detail(
        decision=positive_rcsd_decision,
        positive_audit=positive_audit,
        selected_aggregate_doc=selected_aggregate_doc,
        semantic_anchor_distance_m=aggregate_semantic_anchor_distance,
        degraded_reasons=prepared.pair_local_summary.get("degraded_reasons") or (),
        exact_aggregate_without_exact_local=exact_aggregate_without_exact_local,
        relaxed_aggregate_too_far=relaxed_aggregate_too_far,
        relaxed_multi_group_single_first_hit=relaxed_multi_group_single_first_hit,
    )
    node_centric_bound_to_junction = bool(
        positive_rcsd_decision.positive_rcsd_present
        and positive_rcsd_decision.required_rcsd_node
        and positive_rcsd_decision.required_rcsd_node_source == "aggregated_node_centric"
        and str(positive_rcsd_decision.positive_rcsd_consistency_level or "").strip().upper() == "B"
        and not exact_aggregate_without_exact_local
        and not relaxed_aggregate_too_far
        and not relaxed_multi_group_single_first_hit
    )
    positive_rcsd_bound_to_junction = bool(
        node_centric_bound_to_junction or structural_required_handoff_detail
    )
    if structural_required_handoff_detail:
        review_reasons = list(result.all_review_reasons())
        if ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON not in review_reasons:
            review_reasons.append(ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON)
        summary = dict(result.selected_candidate_summary)
        summary.update(
            {
                "road_surface_fork_structural_required_rcsd_handoff": structural_required_handoff_detail,
                "rcsd_relation_handoff_reason": ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON,
                "review_reasons": review_reasons,
            }
        )
        rcsd_audit = dict(result.positive_rcsd_audit)
        rcsd_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
        rcsd_audit["road_surface_fork_structural_required_rcsd_handoff"] = (
            structural_required_handoff_detail
        )
        rcsd_audit["rcsd_relation_handoff_reason"] = ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON
        result = replace_step4_pre_arbiter_candidate(
            result,
            review_reasons=tuple(review_reasons),
            selected_candidate_summary=summary,
            selected_evidence_summary=dict(summary),
            positive_rcsd_audit=rcsd_audit,
        )
        result = append_dual_write_candidate(
            result,
            case_id=prepared.case_bundle.case_spec.case_id,
            source_stage="event_interpretation_structural_required_rcsd_handoff",
            source_audit_blob=structural_required_handoff_detail,
            replacement_reason=ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON,
        )
    no_bound_target_rcsd = bool(
        road_surface_fork_candidate
        and not positive_rcsd_bound_to_junction
        and not prepared.unit_context.local_context.direct_target_rc_nodes
        and not prepared.unit_context.local_context.exact_target_rc_nodes
        and prepared.unit_context.local_context.primary_main_rc_node is None
    )
    if no_bound_target_rcsd:
        filtered_partial_rcsd = bool(
            positive_rcsd_decision.pair_local_rcsd_node_ids
            and "pair_local_scope_rcsdnode_outside_drivezone_filtered"
            in {
                str(reason or "").strip()
                for reason in prepared.pair_local_summary.get("degraded_reasons") or ()
                if str(reason or "").strip()
            }
        )
        review_reasons = list(result.all_review_reasons())
        if filtered_partial_rcsd and "positive_rcsd_partial_consistent" not in review_reasons:
            review_reasons.append("positive_rcsd_partial_consistent")
        summary = dict(result.selected_candidate_summary)
        summary.update(
            {
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "road_surface_fork_without_bound_target_rcsd",
                "positive_rcsd_support_level": "no_support",
                "positive_rcsd_consistency_level": "C",
                "required_rcsd_node": None,
                "required_rcsd_node_source": None,
                "rcsd_selection_mode": "road_surface_fork_without_bound_target_rcsd",
                "rcsd_alignment_type": RCSD_ALIGNMENT_NONE,
                "rcsd_decision_reason": "road_surface_fork_without_bound_target_rcsd",
                "review_reasons": review_reasons,
            }
        )
        rcsd_audit = dict(result.positive_rcsd_audit)
        rcsd_audit["road_surface_fork_without_bound_target_rcsd"] = True
        rcsd_audit["rcsd_decision_reason"] = "road_surface_fork_without_bound_target_rcsd"
        rcsd_audit["rcsd_alignment_type"] = RCSD_ALIGNMENT_NONE
        result = replace_step4_pre_arbiter_candidate(
            result,
            review_reasons=tuple(review_reasons),
            rcsd_consistency_result="road_surface_fork_without_bound_target_rcsd",
            pair_local_rcsd_scope_geometry=positive_rcsd_decision.pair_local_rcsd_scope_geometry,
            first_hit_rcsd_road_geometry=positive_rcsd_decision.first_hit_rcsd_road_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            first_hit_rcsdroad_ids=(),
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            positive_rcsd_present=False,
            positive_rcsd_present_reason="road_surface_fork_without_bound_target_rcsd",
            rcsd_selection_mode="road_surface_fork_without_bound_target_rcsd",
            pair_local_rcsd_empty=False,
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            rcsd_alignment_type=RCSD_ALIGNMENT_NONE,
            selected_candidate_summary=summary,
            selected_evidence_summary=dict(summary),
            positive_rcsd_audit=rcsd_audit,
        )
        result = append_dual_write_candidate(
            result,
            case_id=prepared.case_bundle.case_spec.case_id,
            source_stage="event_interpretation_no_bound_target_rcsd",
            source_audit_blob={
                "no_bound_target_rcsd": True,
                "filtered_partial_rcsd": filtered_partial_rcsd,
                "rcsd_decision_reason": "road_surface_fork_without_bound_target_rcsd",
            },
            replacement_reason="road_surface_fork_without_bound_target_rcsd",
        )
    if not bool(selected_candidate_summary.get("primary_eligible")):
        extra_review_notes = list(result.extra_review_notes)
        if bool(selected_candidate_summary.get("node_fallback_only")):
            extra_review_notes.append("node_fallback_candidate_not_primary_eligible")
        else:
            extra_review_notes.append("layer3_candidate_not_primary_eligible")
        result = replace(
            result,
            review_state="STEP4_REVIEW" if result.review_state == "STEP4_OK" else result.review_state,
            extra_review_notes=tuple(dict.fromkeys(extra_review_notes)),
        )
    rcsd_semantic_junction = build_rcsd_semantic_junction(
        unit_result=result,
        swsd_semantic_junction=result.unit_context.topology_skeleton.swsd_semantic_junction,
        rcsd_alignment_result=result.rcsd_alignment_result(),
    )
    if rcsd_semantic_junction is not None:
        rcsd_audit = dict(result.positive_rcsd_audit)
        rcsd_audit["rcsd_semantic_junction"] = rcsd_semantic_junction.to_doc()
        if rcsd_semantic_junction.pairing_ambiguous_arm_ids:
            rcsd_audit["pairing_ambiguous_arm_ids"] = list(
                rcsd_semantic_junction.pairing_ambiguous_arm_ids
            )
        result = replace(
            result,
            rcsd_semantic_junction=rcsd_semantic_junction,
            positive_rcsd_audit=rcsd_audit,
        )
    rcsdroad_only_chain = build_rcsdroad_only_chain(
        unit_result=result,
        swsd_semantic_junction=result.unit_context.topology_skeleton.swsd_semantic_junction,
        rcsd_alignment_result=result.rcsd_alignment_result(),
    )
    if rcsdroad_only_chain is not None:
        rcsd_audit = dict(result.positive_rcsd_audit)
        rcsd_audit["rcsdroad_only_chain"] = rcsdroad_only_chain.to_doc()
        result = replace(
            result,
            rcsdroad_only_chain=rcsdroad_only_chain,
            positive_rcsd_audit=rcsd_audit,
        )
    return result


def _evaluate_unit_candidate(
    prepared: _PreparedUnitInputs,
    candidate: dict[str, Any],
) -> _CandidateEvaluation:
    local_context = prepared.unit_context.local_context
    direct_target_rc_nodes = _filter_nodes_to_scope(
        local_context.direct_target_rc_nodes,
        scope_geometry=prepared.pair_local_region_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    )
    exact_target_rc_nodes = _filter_nodes_to_scope(
        local_context.exact_target_rc_nodes,
        scope_geometry=prepared.pair_local_region_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    )
    primary_main_rc_node = local_context.primary_main_rc_node
    if primary_main_rc_node is not None:
        scoped_primary = _filter_nodes_to_scope(
            [primary_main_rc_node],
            scope_geometry=prepared.pair_local_region_geometry,
            pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
        )
        primary_main_rc_node = scoped_primary[0] if scoped_primary else None
    interpretation_kwargs = {
        "representative_node": prepared.effective_representative_node,
        "representative_source_kind_2": prepared.effective_source_kind_2,
        "mainnodeid_norm": prepared.unit_context.admission.mainnodeid,
        "seed_union": _seed_union(
            representative_node=prepared.effective_representative_node,
            group_nodes=prepared.unit_context.group_nodes,
            local_context=local_context,
        ),
        "group_nodes": list(prepared.unit_context.group_nodes),
        "patch_size_m": float(prepared.pair_local_patch_size_m),
        "seed_center": local_context.seed_center,
        "drivezone_union": prepared.pair_local_drivezone_union,
        "local_roads": list(prepared.pair_local_scope_roads),
        "local_rcsd_roads": list(prepared.pair_local_scope_rcsd_roads),
        "local_rcsd_nodes": list(prepared.pair_local_scope_rcsd_nodes),
        "local_divstrip_features": list(candidate["divstrip_features"]),
        "road_branches": list(prepared.scoped_branches),
        "main_branch_ids": set(prepared.scoped_main_branch_ids),
        "member_node_ids": {str(node_id) for node_id in prepared.unit_population_node_ids},
        "direct_target_rc_nodes": list(direct_target_rc_nodes),
        "exact_target_rc_nodes": list(exact_target_rc_nodes),
        "primary_main_rc_node": primary_main_rc_node,
        "rcsdnode_seed_mode": local_context.rcsdnode_seed_mode,
        "chain_context": prepared.unit_context.topology_skeleton.chain_context.to_legacy_dict(),
        "event_branch_ids": set(prepared.explicit_event_branch_ids),
        "boundary_branch_ids": tuple(prepared.boundary_branch_ids),
        "preferred_axis_branch_id": prepared.preferred_axis_branch_id,
        "context_augmented_node_ids": set(prepared.context_augmented_node_ids),
        "degraded_scope_reason": prepared.degraded_scope_reason,
    }
    interpretation = _build_stage4_event_interpretation(
        **{
            key: value
            for key, value in interpretation_kwargs.items()
            if key in inspect.signature(_build_stage4_event_interpretation).parameters
        }
    )
    base_result = _build_result_from_interpretation(
        prepared=prepared,
        interpretation=interpretation,
        selected_candidate_summary=dict(candidate["summary"]),
        selected_evidence_region_geometry=candidate["region_geometry"],
        selected_reference_point=candidate.get("reference_point"),
    )
    merged_candidate_summary = _merge_candidate_evaluation(
        candidate["summary"],
        base_result,
    )
    extra_review_notes = tuple(
        note
        for note in base_result.extra_review_notes
        if not (
            bool(merged_candidate_summary.get("primary_eligible"))
            and note in {"layer3_candidate_not_primary_eligible", "node_fallback_candidate_not_primary_eligible"}
        )
    )
    result = replace_step4_pre_arbiter_candidate(
        base_result,
        selected_candidate_summary=merged_candidate_summary,
        selected_evidence_summary=dict(merged_candidate_summary),
        extra_review_notes=extra_review_notes,
    )
    return _CandidateEvaluation(
        result=result,
        priority_score=_candidate_priority_score(merged_candidate_summary, result),
    )


def _empty_selected_evidence_summary(*, decision_reason: str) -> dict[str, Any]:
    return {
        "candidate_id": "",
        "source_mode": "",
        "upper_evidence_kind": "",
        "upper_evidence_object_id": "",
        "candidate_scope": "",
        "local_region_id": "",
        "ownership_signature": "",
        "point_signature": "",
        "axis_signature": "",
        "axis_position_basis": "",
        "axis_position_m": None,
        "reference_distance_to_origin_m": None,
        "node_fallback_only": False,
        "layer": 0,
        "layer_label": "Layer 0",
        "layer_reason": "no_selected_evidence",
        "pair_middle_overlap_ratio": 0.0,
        "throat_overlap_ratio": 0.0,
        "primary_eligible": False,
        "selected_after_reselection": False,
        "selection_rank": None,
        "pool_rank": None,
        "priority_score": 0,
        "selection_status": "none",
        "decision_reason": decision_reason,
    }
