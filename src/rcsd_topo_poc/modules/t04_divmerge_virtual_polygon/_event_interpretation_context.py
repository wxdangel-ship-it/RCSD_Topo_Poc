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


def _singleton_group(node) -> tuple:
    return (node,)


def _seed_union(*, representative_node, group_nodes, local_context):
    seed_geometries: list[BaseGeometry] = [
        representative_node.geometry,
        *[node.geometry for node in group_nodes],
        *[node.geometry for node in local_context.exact_target_rc_nodes],
    ]
    return unary_union(seed_geometries)


def _prepare_unit_context(
    *,
    case_bundle: T04CaseBundle,
    representative_node_id: str,
    singleton_group: bool,
) -> T04UnitContext:
    representative_node = next(node for node in case_bundle.nodes if node.node_id == representative_node_id)
    if singleton_group:
        group_nodes = _singleton_group(representative_node)
    else:
        _resolved_rep, resolved_group_nodes = _resolve_group(
            mainnodeid=normalize_id(representative_node.mainnodeid or representative_node.node_id),
            nodes=list(case_bundle.nodes),
        )
        group_nodes = tuple(resolved_group_nodes)
    admission = build_step1_admission(representative_node=representative_node, group_nodes=group_nodes)
    local_context = build_step2_local_context(
        case_bundle=case_bundle,
        representative_node=representative_node,
        group_nodes=group_nodes,
    )
    topology_skeleton = build_step3_topology(
        representative_node=representative_node,
        group_nodes=group_nodes,
        local_context=local_context,
    )
    return T04UnitContext(
        representative_node=representative_node,
        group_nodes=group_nodes,
        admission=admission,
        local_context=local_context,
        topology_skeleton=topology_skeleton,
    )


def _filter_branch_scope(unit_context: T04UnitContext, selected_side_branch_ids: tuple[str, ...]):
    branch_result = unit_context.topology_skeleton.branch_result
    road_branches = list(branch_result.road_branches)
    if not selected_side_branch_ids:
        return road_branches, list(unit_context.local_context.patch_roads), set(branch_result.main_branch_ids)

    allowed_branch_ids = set(branch_result.main_branch_ids) | {str(item) for item in selected_side_branch_ids}
    filtered_branches = [
        branch
        for branch in road_branches
        if str(branch.branch_id) in allowed_branch_ids
    ]
    if len(filtered_branches) < 2:
        return road_branches, list(unit_context.local_context.patch_roads), set(branch_result.main_branch_ids)

    allowed_road_ids = {
        str(road_id)
        for branch in filtered_branches
        for road_id in branch.road_ids
    }
    filtered_roads = [
        road
        for road in unit_context.local_context.patch_roads
        if str(road.road_id) in allowed_road_ids
    ]
    return filtered_branches, filtered_roads, set(branch_result.main_branch_ids) & {
        str(branch.branch_id) for branch in filtered_branches
    }


def _positive_rcsd_geometry(geometries: Iterable[BaseGeometry | None]):
    valid = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not valid:
        return GeometryCollection()
    return unary_union(valid)


def _sorted_id_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if str(value)}))


def _structural_required_rcsd_handoff_detail(
    *,
    decision: Any,
    positive_audit: dict[str, Any],
    selected_aggregate_doc: dict[str, Any],
    semantic_anchor_distance_m: float | None,
    degraded_reasons: Iterable[Any],
    exact_aggregate_without_exact_local: bool,
    relaxed_aggregate_too_far: bool,
    relaxed_multi_group_single_first_hit: bool,
) -> dict[str, Any] | None:
    required_node = str(getattr(decision, "required_rcsd_node", None) or "").strip()
    if not (
        getattr(decision, "positive_rcsd_present", False)
        and required_node
        and str(getattr(decision, "required_rcsd_node_source", "") or "").strip()
        == "aggregated_structural_required"
    ):
        return None
    if str(getattr(decision, "positive_rcsd_consistency_level", "") or "").strip().upper() not in (
        _STRUCTURAL_REQUIRED_MIN_CONSISTENCY_LEVELS
    ):
        return None
    support_level = str(selected_aggregate_doc.get("support_level") or "").strip()
    if support_level not in _STRUCTURAL_REQUIRED_MIN_SUPPORT_LEVELS:
        return None
    semantic_group_ids = _sorted_id_tuple(selected_aggregate_doc.get("semantic_group_ids") or ())
    if len(semantic_group_ids) != 1 or required_node not in semantic_group_ids:
        return None
    if str(selected_aggregate_doc.get("required_node_id") or "").strip() != required_node:
        return None
    if semantic_anchor_distance_m is None:
        return None
    if semantic_anchor_distance_m > ROAD_SURFACE_RELAXED_RCSD_MAX_SEMANTIC_DISTANCE_M:
        return None
    if exact_aggregate_without_exact_local or relaxed_aggregate_too_far or relaxed_multi_group_single_first_hit:
        return None
    degraded_texts = {
        str(reason or "").strip()
        for reason in degraded_reasons
        if str(reason or "").strip()
    }
    if any("outside_drivezone" in reason for reason in degraded_texts):
        return None
    published_roads = _sorted_id_tuple(
        positive_audit.get("published_rcsdroad_ids")
        or selected_aggregate_doc.get("road_ids")
        or getattr(decision, "selected_rcsdroad_ids", ())
    )
    published_nodes = _sorted_id_tuple(
        positive_audit.get("published_rcsdnode_ids")
        or selected_aggregate_doc.get("node_ids")
        or getattr(decision, "selected_rcsdnode_ids", ())
    )
    if not published_roads or required_node not in published_nodes:
        return None
    assignments = [
        assignment
        for assignment in (
            positive_audit.get("selected_unit_role_assignments")
            or selected_aggregate_doc.get("role_assignments")
            or ()
        )
        if isinstance(assignment, dict)
    ]
    assignment_roles = {
        str(assignment.get("role") or "").strip()
        for assignment in assignments
        if str(assignment.get("role") or "").strip()
    }
    if not {"entering", "exiting"}.issubset(assignment_roles):
        return None
    semantic_junction = positive_audit.get("rcsd_semantic_junction")
    paired_swsd_arm_count = None
    if isinstance(semantic_junction, dict):
        if semantic_junction.get("pairing_ambiguous_arm_ids"):
            return None
        if semantic_junction.get("alignment_partial_missing_swsd_arm_ids"):
            return None
        mapping = semantic_junction.get("paired_swsd_arm_mapping")
        if isinstance(mapping, dict):
            paired_swsd_arm_count = len(
                {
                    str(swsd_arm_id or "").strip()
                    for swsd_arm_id in mapping.values()
                    if str(swsd_arm_id or "").strip()
                }
            )
            if paired_swsd_arm_count < 2:
                return None
    return {
        "reason": ROAD_SURFACE_STRUCTURAL_REQUIRED_HANDOFF_REASON,
        "required_rcsd_node": required_node,
        "required_rcsd_node_source": "aggregated_structural_required",
        "semantic_group_ids": list(semantic_group_ids),
        "semantic_anchor_distance_m": round(float(semantic_anchor_distance_m), 6),
        "max_semantic_anchor_distance_m": ROAD_SURFACE_RELAXED_RCSD_MAX_SEMANTIC_DISTANCE_M,
        "support_level": support_level,
        "consistency_level": str(
            getattr(decision, "positive_rcsd_consistency_level", "") or ""
        ).strip().upper(),
        "published_rcsdroad_ids": list(published_roads),
        "published_rcsdnode_ids": list(published_nodes),
        "role_assignment_count": len(assignments),
        "assignment_roles": sorted(assignment_roles),
        "paired_swsd_arm_count": paired_swsd_arm_count,
        "degraded_reasons": sorted(degraded_texts),
    }


def _apply_positive_rcsd_audit_to_summary(
    summary: dict[str, Any],
    *,
    decision,
) -> dict[str, Any]:
    merged = dict(summary)
    merged.update(
        {
            "pair_local_rcsd_empty": bool(decision.pair_local_rcsd_empty),
            "pair_local_rcsd_road_ids": list(decision.pair_local_rcsd_road_ids),
            "pair_local_rcsd_node_ids": list(decision.pair_local_rcsd_node_ids),
            "first_hit_rcsdroad_ids": list(decision.first_hit_rcsdroad_ids),
            "local_rcsd_unit_id": decision.local_rcsd_unit_id,
            "local_rcsd_unit_kind": decision.local_rcsd_unit_kind,
            "aggregated_rcsd_unit_id": decision.aggregated_rcsd_unit_id,
            "aggregated_rcsd_unit_ids": list(decision.aggregated_rcsd_unit_ids),
            "rcsd_selection_mode": decision.rcsd_selection_mode,
            "positive_rcsd_present": bool(decision.positive_rcsd_present),
            "positive_rcsd_present_reason": decision.positive_rcsd_present_reason,
            "positive_rcsd_support_level": decision.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": decision.positive_rcsd_consistency_level,
            "required_rcsd_node": decision.required_rcsd_node,
            "required_rcsd_node_source": decision.required_rcsd_node_source,
            "axis_polarity_inverted": bool(decision.axis_polarity_inverted),
            "rcsd_decision_reason": decision.rcsd_decision_reason,
            "positive_rcsd_audit": dict(decision.positive_rcsd_audit),
        }
    )
    return merged


def _point_signature(
    *,
    point_geometry: BaseGeometry | None,
    event_axis_signature: str | None,
    axis_position_basis: str | None,
    axis_position_m: float | None,
    event_axis_branch_id: str | None,
    axis_origin_point: BaseGeometry | None,
    axis_unit_vector: tuple[float, float] | None,
) -> str:
    if point_geometry is None or point_geometry.is_empty:
        return ""
    point = point_geometry
    if getattr(point, "geom_type", None) != "Point":
        representative_point = point.representative_point()
        if representative_point is None or representative_point.is_empty:
            return ""
        point = representative_point
    if event_axis_signature is not None and axis_position_m is not None:
        if axis_position_basis and axis_position_basis != event_axis_signature:
            return f"{event_axis_signature}:{axis_position_basis}:{round(float(axis_position_m), 1)}"
        return f"{event_axis_signature}:{round(float(axis_position_m), 1)}"
    if (
        (event_axis_signature is not None or event_axis_branch_id is not None)
        and axis_origin_point is not None
        and not axis_origin_point.is_empty
        and axis_unit_vector is not None
    ):
        dx = float(point.x) - float(axis_origin_point.x)
        dy = float(point.y) - float(axis_origin_point.y)
        projection = dx * float(axis_unit_vector[0]) + dy * float(axis_unit_vector[1])
        axis_identity = event_axis_signature or event_axis_branch_id
        return f"{axis_identity}:{round(float(projection), 1)}"
    return f"{round(float(point.x), 1)}:{round(float(point.y), 1)}"


def _candidate_layer(
    *,
    region_geometry: BaseGeometry | None,
    reference_point: BaseGeometry | None,
    pair_middle_geometry: BaseGeometry | None,
    throat_core_geometry: BaseGeometry | None,
) -> tuple[int, float, float, str]:
    middle_ratio = _area_ratio(region_geometry, pair_middle_geometry)
    throat_ratio = _area_ratio(region_geometry, throat_core_geometry)
    point_in_middle = bool(
        _geometry_present(pair_middle_geometry)
        and reference_point is not None
        and not reference_point.is_empty
        and pair_middle_geometry.buffer(1e-6).covers(reference_point)
    )
    point_in_throat = bool(
        _geometry_present(throat_core_geometry)
        and reference_point is not None
        and not reference_point.is_empty
        and throat_core_geometry.buffer(1e-6).covers(reference_point)
    )
    if (point_in_throat or throat_ratio >= 0.35) and middle_ratio >= 0.6:
        return 1, middle_ratio, throat_ratio, "throat_core_plus_pair_middle"
    if point_in_middle or middle_ratio >= 0.45:
        return 2, middle_ratio, throat_ratio, "pair_middle_stable"
    return 3, middle_ratio, throat_ratio, "weak_edge_contact"


def _reference_point_from_region(
    *,
    region_geometry: BaseGeometry | None,
    axis_origin_point: BaseGeometry | None,
    reference_strategy: str,
) -> BaseGeometry | None:
    if region_geometry is None or region_geometry.is_empty:
        return None
    if reference_strategy == "formation":
        if axis_origin_point is not None and not axis_origin_point.is_empty:
            try:
                return nearest_points(axis_origin_point, region_geometry)[1]
            except Exception:
                pass
        try:
            representative_point = region_geometry.representative_point()
        except Exception:
            representative_point = None
        if representative_point is not None and not representative_point.is_empty:
            return representative_point
    if reference_strategy == "tip" and axis_origin_point is not None and not axis_origin_point.is_empty:
        try:
            boundary = region_geometry.boundary
            boundary_parts = getattr(boundary, "geoms", None) or [boundary]
            best_point = None
            best_distance = -1.0
            for part in boundary_parts:
                for coord in getattr(part, "coords", ()):
                    candidate_point = Point(float(coord[0]), float(coord[1]))
                    candidate_distance = float(axis_origin_point.distance(candidate_point))
                    if candidate_distance > best_distance + 1e-9:
                        best_point = candidate_point
                        best_distance = candidate_distance
            if best_point is not None and not best_point.is_empty:
                return best_point
        except Exception:
            pass
    if reference_strategy == "representative":
        try:
            representative_point = region_geometry.representative_point()
        except Exception:
            representative_point = None
        if representative_point is not None and not representative_point.is_empty:
            return representative_point
    if axis_origin_point is not None and not axis_origin_point.is_empty:
        try:
            return nearest_points(axis_origin_point, region_geometry)[1]
        except Exception:
            pass
    try:
        representative_point = region_geometry.representative_point()
    except Exception:
        return None
    return None if representative_point is None or representative_point.is_empty else representative_point


def _boundary_pair_road_ids_from_summary(summary: dict[str, Any]) -> tuple[str, str] | None:
    signature = str(summary.get("boundary_pair_signature") or "").strip()
    if not signature:
        return None
    parts = tuple(part.strip() for part in signature.split("__") if part.strip())
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _road_linestring(road: ParsedRoad | None) -> LineString | None:
    geometry = getattr(road, "geometry", None)
    if isinstance(geometry, LineString) and not geometry.is_empty and geometry.length > 1e-6:
        return geometry
    parts = [
        part
        for part in getattr(geometry, "geoms", ())
        if isinstance(part, LineString) and not part.is_empty and part.length > 1e-6
    ]
    if not parts:
        return None
    return max(parts, key=lambda part: float(part.length))


def _road_surface_fork_apex_reference(
    *,
    surface_domain: BaseGeometry,
    axis_origin: BaseGeometry | None,
    pair_local_summary: dict[str, Any],
    case_road_lookup: dict[str, ParsedRoad],
) -> tuple[Point | None, dict[str, Any]]:
    if not isinstance(axis_origin, Point):
        return None, {"road_surface_fork_reference_point_mode": "apex_origin_unavailable"}
    boundary_pair = _boundary_pair_road_ids_from_summary(pair_local_summary)
    if boundary_pair is None:
        return None, {"road_surface_fork_reference_point_mode": "apex_boundary_pair_unavailable"}
    line_a = _road_linestring(case_road_lookup.get(boundary_pair[0]))
    line_b = _road_linestring(case_road_lookup.get(boundary_pair[1]))
    if line_a is None or line_b is None:
        return None, {
            "road_surface_fork_reference_point_mode": "apex_boundary_road_unavailable",
            "boundary_pair_road_ids": list(boundary_pair),
        }
    seed_point = surface_domain.representative_point()
    apex_point, apex_detail = _surface_fork_boundary_apex_point(
        surface_domain,
        ordered_a=_ordered_line_from_point(line_a, axis_origin),
        ordered_b=_ordered_line_from_point(line_b, axis_origin),
        origin=axis_origin,
    )
    if apex_point is None:
        apex_detail["boundary_pair_road_ids"] = list(boundary_pair)
        return None, apex_detail
    apex_detail["boundary_pair_road_ids"] = list(boundary_pair)
    apex_detail["road_surface_fork_seed_point_xy"] = [
        round(float(seed_point.x), 3),
        round(float(seed_point.y), 3),
    ]
    return apex_point, apex_detail


def _candidate_summary(
    *,
    candidate_id: str,
    source_mode: str,
    upper_evidence_kind: str,
    upper_evidence_object_id: str,
    candidate_scope: str,
    local_region_id: str,
    region_geometry: BaseGeometry | None,
    reference_point: BaseGeometry | None,
    pair_middle_geometry: BaseGeometry | None,
    throat_core_geometry: BaseGeometry | None,
    event_axis_signature: str | None,
    axis_position_basis: str | None,
    axis_position_m: float | None,
    event_axis_branch_id: str | None,
    axis_origin_point: BaseGeometry | None,
    axis_unit_vector: tuple[float, float] | None,
) -> dict[str, Any]:
    layer, middle_ratio, throat_ratio, layer_reason = _candidate_layer(
        region_geometry=region_geometry,
        reference_point=reference_point,
        pair_middle_geometry=pair_middle_geometry,
        throat_core_geometry=throat_core_geometry,
    )
    reference_distance_to_origin_m = None
    if (
        reference_point is not None
        and not reference_point.is_empty
        and axis_origin_point is not None
        and not axis_origin_point.is_empty
    ):
        try:
            reference_distance_to_origin_m = round(float(reference_point.distance(axis_origin_point)), 3)
        except Exception:
            reference_distance_to_origin_m = None
    node_fallback_only = False
    if candidate_scope != ROAD_SURFACE_FORK_SCOPE:
        node_fallback_only = bool(
            (axis_position_m is not None and abs(float(axis_position_m)) <= NODE_FALLBACK_AXIS_POSITION_MAX_M + 1e-9)
            or (
                reference_distance_to_origin_m is not None
                and reference_distance_to_origin_m <= NODE_FALLBACK_DISTANCE_MAX_M + 1e-9
            )
        )
    if node_fallback_only:
        layer_reason = f"{layer_reason}|node_fallback_only"
    point_signature = _point_signature(
        point_geometry=reference_point,
        event_axis_signature=event_axis_signature,
        axis_position_basis=axis_position_basis,
        axis_position_m=axis_position_m,
        event_axis_branch_id=event_axis_branch_id,
        axis_origin_point=axis_origin_point,
        axis_unit_vector=axis_unit_vector,
    )
    ownership_signature = f"{upper_evidence_kind}:{upper_evidence_object_id}:{local_region_id}"
    return {
        "candidate_id": candidate_id,
        "source_mode": source_mode,
        "upper_evidence_kind": upper_evidence_kind,
        "upper_evidence_object_id": upper_evidence_object_id,
        "candidate_scope": candidate_scope,
        "local_region_id": local_region_id,
        "ownership_signature": ownership_signature,
        "point_signature": point_signature,
        "axis_signature": event_axis_signature or event_axis_branch_id or "",
        "axis_position_basis": axis_position_basis or "",
        "axis_position_m": axis_position_m,
        "reference_distance_to_origin_m": reference_distance_to_origin_m,
        "node_fallback_only": node_fallback_only,
        "layer": int(layer),
        "layer_label": f"Layer {int(layer)}",
        "layer_reason": layer_reason,
        "pair_middle_overlap_ratio": round(float(middle_ratio), 4),
        "throat_overlap_ratio": round(float(throat_ratio), 4),
        "primary_eligible": bool(layer in {1, 2} and not node_fallback_only),
        "selected_after_reselection": False,
        "selection_rank": None,
    }


def _materialize_event_reference_point(
    *,
    interpretation,
    selected_divstrip_geometry,
):
    point = interpretation.legacy_step5_bridge.event_origin_point
    if point is None or point.is_empty:
        return point
    if interpretation.event_reference.event_position_source != "divstrip_ref":
        return point
    preferred_geometry = selected_divstrip_geometry
    if preferred_geometry is None or preferred_geometry.is_empty:
        return point
    if preferred_geometry.buffer(1e-6).covers(point):
        return point
    snapped_point = nearest_points(point, preferred_geometry)[1]
    if snapped_point is None or snapped_point.is_empty:
        return point
    return snapped_point


def _materialize_selected_divstrip_geometry(
    *,
    interpretation,
    selected_divstrip_geometry,
    localized_divstrip_geometry,
):
    preferred_geometry = (
        localized_divstrip_geometry
        if localized_divstrip_geometry is not None and not localized_divstrip_geometry.is_empty
        else selected_divstrip_geometry
    )
    if preferred_geometry is None or preferred_geometry.is_empty:
        return preferred_geometry
    raw_point = interpretation.legacy_step5_bridge.event_origin_point
    if raw_point is None or raw_point.is_empty:
        return preferred_geometry
    polygon_components = [
        component
        for component in _explode_component_geometries(preferred_geometry)
        if getattr(component, "geom_type", None) == "Polygon" and not component.is_empty
    ]
    if polygon_components:
        covering_components = [
            component
            for component in polygon_components
            if component.buffer(1e-6).covers(raw_point)
        ]
        if covering_components:
            preferred_geometry = unary_union(covering_components).buffer(0)
        elif len(polygon_components) > 1:
            preferred_geometry = min(
                polygon_components,
                key=lambda component: float(component.distance(raw_point)),
            )
    support_point = (
        raw_point
        if preferred_geometry.buffer(1e-6).covers(raw_point)
        else nearest_points(raw_point, preferred_geometry)[1]
    )
    if support_point is None or support_point.is_empty:
        return preferred_geometry
    localized_tip_patch = preferred_geometry.intersection(
        support_point.buffer(DIVSTRIP_EVIDENCE_TIP_RADIUS_M, join_style=2)
    ).buffer(0)
    if localized_tip_patch is None or localized_tip_patch.is_empty:
        return preferred_geometry
    return localized_tip_patch


def _materialize_event_anchor_geometry(
    *,
    interpretation,
    selected_divstrip_geometry,
    drivezone_union,
):
    anchor_geometry = interpretation.legacy_step5_bridge.event_anchor_geometry
    if anchor_geometry is None or anchor_geometry.is_empty:
        return anchor_geometry
    if (
        not interpretation.continuous_chain_decision.sequential_ok
        or selected_divstrip_geometry is None
        or selected_divstrip_geometry.is_empty
        or anchor_geometry.intersects(selected_divstrip_geometry)
    ):
        return anchor_geometry
    coarse_anchor = selected_divstrip_geometry.buffer(1.5, join_style=2)
    if drivezone_union is not None and not drivezone_union.is_empty:
        coarse_anchor = coarse_anchor.intersection(drivezone_union).buffer(0)
    return coarse_anchor if coarse_anchor is not None and not coarse_anchor.is_empty else anchor_geometry
