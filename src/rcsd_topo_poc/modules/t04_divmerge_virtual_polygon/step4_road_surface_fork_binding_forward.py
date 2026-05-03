from __future__ import annotations

from dataclasses import replace
from typing import Any

from shapely.geometry import Point

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from .rcsd_alignment import rcsd_alignment_type_from_selection
from .step4_road_surface_fork_binding_shared import _build_surface_summary, _candidate_entries_with_selection
from .step4_road_surface_fork_geometry import (
    ROAD_SURFACE_FORK_BINDING_REASON,
    _dedupe,
    _node_geometries,
    _point_geometry,
    _road_geometries,
    _road_surface_fork_reference_point,
    _union_geometries,
)
from .step4_road_surface_fork_rcsd import _strong_aggregated_unit


def _bind_strong_rcsd_to_surface(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    selected_summary = event_unit.selected_candidate_summary
    bind_detail = selected_summary.get("road_surface_fork_binding")
    allow_recovered_same_side_fork = bool(
        str(selected_summary.get("candidate_id") or "").endswith(":recovered")
        or (
            isinstance(bind_detail, dict)
            and bool(bind_detail.get("source_node_fallback_only"))
        )
    )
    aggregate = _strong_aggregated_unit(
        event_unit.positive_rcsd_audit,
        allow_entering_exiting_role_support=allow_recovered_same_side_fork,
    )
    if aggregate is None:
        return None, None

    required_node = str(aggregate.get("required_node_id") or "").strip()
    primary_node = str(aggregate.get("primary_node_id") or "").strip() or None
    road_ids = tuple(str(item) for item in aggregate.get("road_ids") or () if str(item))
    node_ids = tuple(str(item) for item in aggregate.get("node_ids") or () if str(item))
    selected_roads = tuple(str(item) for item in event_unit.positive_rcsd_audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = tuple(str(item) for item in event_unit.positive_rcsd_audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = tuple(str(item) for item in event_unit.positive_rcsd_audit.get("first_hit_rcsdroad_ids") or ())
    required_geometry = _point_geometry(case_result, required_node)
    if required_geometry is None:
        return None, None
    reference_point, reference_detail = _road_surface_fork_reference_point(case_result, event_unit)
    if reference_point is None:
        reference_point = event_unit.fact_reference_point if isinstance(event_unit.fact_reference_point, Point) else None
    review_point = reference_point if reference_point is not None else event_unit.review_materialized_point

    support_level = str(aggregate.get("support_level") or "primary_support")
    consistency_level = str(aggregate.get("consistency_level") or "A")
    selection_mode = "road_surface_fork_forward_rcsd_binding"
    decision_reason = str(aggregate.get("decision_reason") or "")
    alignment_type = rcsd_alignment_type_from_selection(
        positive_rcsd_present=True,
        required_rcsd_node=required_node,
        selected_rcsdroad_ids=selected_roads,
        local_rcsd_unit_kind="node_centric",
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        rcsd_decision_reason=decision_reason,
        rcsd_selection_mode=selection_mode,
    )
    bind_detail = {
        "action": "bound_forward_rcsd_to_road_surface_fork",
        "aggregated_rcsd_unit_id": str(aggregate.get("unit_id") or ""),
        "required_rcsd_node": required_node,
        "rcsd_decision_reason": decision_reason,
        "rcsd_alignment_type": alignment_type,
        "reference_point": dict(reference_detail),
    }
    summary = _build_surface_summary(
        T04CandidateAuditEntry(
            candidate_id=str(event_unit.selected_candidate_summary.get("candidate_id") or ""),
            pool_rank=int(event_unit.selected_candidate_summary.get("pool_rank") or 0),
            priority_score=int(event_unit.selected_candidate_summary.get("priority_score") or 0),
            selection_status="selected",
            decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
            candidate_summary=dict(event_unit.selected_candidate_summary),
            review_state=event_unit.review_state,
            review_reasons=event_unit.all_review_reasons(),
            evidence_source=event_unit.evidence_source,
            position_source=event_unit.position_source,
            reverse_tip_used=False,
            rcsd_consistency_result=event_unit.rcsd_consistency_result,
            positive_rcsd_support_level=support_level,
            positive_rcsd_consistency_level=consistency_level,
            required_rcsd_node=required_node,
            candidate_region_geometry=event_unit.selected_evidence_region_geometry,
            fact_reference_point=reference_point,
            review_materialized_point=review_point,
            localized_evidence_core_geometry=event_unit.localized_evidence_core_geometry,
            selected_component_union_geometry=event_unit.selected_component_union_geometry,
        ),
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        bind_detail=bind_detail,
    )
    if isinstance(reference_point, Point):
        summary.update(
            {
                **reference_detail,
                "point_signature": f"road_surface_fork:{float(reference_point.x):.3f}:{float(reference_point.y):.3f}",
                "reference_distance_to_origin_m": reference_detail.get("road_surface_fork_reference_distance_m"),
            }
        )
    summary.update(
        {
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_forward_rcsd_present",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": required_node,
            "required_rcsd_node_source": "road_surface_fork_forward_rcsd",
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "rcsd_selection_mode": selection_mode,
            "rcsd_alignment_type": alignment_type,
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "road_surface_fork_binding": bind_detail,
            "road_surface_fork_reference_point": dict(reference_detail),
            "rcsd_decision_reason": decision_reason,
            "rcsd_alignment_type": alignment_type,
            "required_rcsd_node_source": "road_surface_fork_forward_rcsd",
        }
    )
    review_reasons = _dedupe([*event_unit.all_review_reasons(), ROAD_SURFACE_FORK_BINDING_REASON])
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_strong_consistent",
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
        required_rcsd_node_geometry=required_geometry,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=str(event_unit.positive_rcsd_audit.get("local_rcsd_unit_id") or aggregate.get("unit_id") or ""),
        local_rcsd_unit_kind="node_centric",
        aggregated_rcsd_unit_id=str(aggregate.get("unit_id") or event_unit.positive_rcsd_audit.get("aggregated_rcsd_unit_id") or ""),
        aggregated_rcsd_unit_ids=tuple(str(item) for item in event_unit.positive_rcsd_audit.get("aggregated_rcsd_unit_ids") or ()),
        fact_reference_point=reference_point,
        review_materialized_point=review_point,
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_forward_rcsd_present",
        rcsd_selection_mode=selection_mode,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=required_node,
        required_rcsd_node_source="road_surface_fork_forward_rcsd",
        rcsd_alignment_type=alignment_type,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=str(summary.get("candidate_id") or ""),
        post_required_rcsd_node=required_node,
        resolution_reason=ROAD_SURFACE_FORK_BINDING_REASON,
    )
    return updated, bind_detail
