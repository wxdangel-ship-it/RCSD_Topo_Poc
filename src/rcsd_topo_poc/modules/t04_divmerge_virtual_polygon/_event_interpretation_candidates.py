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

def _build_candidate_pool(prepared: _PreparedUnitInputs) -> list[dict[str, Any]]:
    pair_region = prepared.pair_local_region_geometry or prepared.pair_local_structure_face_geometry
    structure_face = prepared.pair_local_structure_face_geometry or pair_region
    throat_core = prepared.pair_local_throat_core_geometry
    pair_middle = prepared.pair_local_middle_geometry or structure_face
    axis_origin = prepared.pair_local_axis_origin_point or prepared.unit_context.representative_node.geometry
    axis_unit_vector = prepared.pair_local_axis_unit_vector
    axis_signature = _stable_axis_signature(
        prepared.preferred_axis_branch_id,
        prepared.branch_road_memberships,
    )
    case_road_lookup = _road_lookup(prepared.case_bundle.roads)
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def _append_candidate(
        *,
        candidate_id: str,
        source_mode: str,
        upper_evidence_kind: str,
        upper_evidence_object_id: str,
        candidate_scope: str,
        region_geometry: BaseGeometry | None,
        feature_index: int,
        properties: dict[str, Any] | None,
        reference_strategy: str = "nearest",
        force_empty_divstrip: bool = False,
        require_surface_fork_apex: bool = False,
    ) -> None:
        normalized_region = _safe_normalize_geometry(region_geometry)
        if normalized_region is None:
            return
        reference_detail: dict[str, Any] = {}
        if candidate_scope == ROAD_SURFACE_FORK_SCOPE and reference_strategy == "road_surface_fork_apex":
            reference_point, reference_detail = _road_surface_fork_apex_reference(
                surface_domain=normalized_region,
                axis_origin=axis_origin,
                pair_local_summary=prepared.pair_local_summary,
                case_road_lookup=case_road_lookup,
            )
            if reference_point is None and require_surface_fork_apex:
                return
            try:
                reference_distance = float(reference_detail.get("road_surface_fork_reference_distance_m"))
            except (TypeError, ValueError):
                reference_distance = None
            if (
                require_surface_fork_apex
                and reference_distance is not None
                and reference_distance > SIMPLE_SURFACE_FORK_MAX_REFERENCE_DISTANCE_M
            ):
                return
        else:
            reference_point = _reference_point_from_region(
                region_geometry=normalized_region,
                axis_origin_point=axis_origin,
                reference_strategy=reference_strategy,
            )
        axis_position_basis, axis_position_m = _stable_axis_position(
            point_geometry=reference_point,
            branch_id=prepared.preferred_axis_branch_id,
            branch_road_memberships=prepared.branch_road_memberships,
            road_lookup=case_road_lookup,
        )
        local_region_id = f"{prepared.event_unit_spec.event_unit_id}:{upper_evidence_kind}:{upper_evidence_object_id}:{len(candidates) + 1:02d}"
        summary = _candidate_summary(
            candidate_id=candidate_id,
            source_mode=source_mode,
            upper_evidence_kind=upper_evidence_kind,
            upper_evidence_object_id=upper_evidence_object_id,
            candidate_scope=candidate_scope,
            local_region_id=local_region_id,
            region_geometry=normalized_region,
            reference_point=reference_point,
            pair_middle_geometry=pair_middle,
            throat_core_geometry=throat_core,
            event_axis_signature=axis_signature,
            axis_position_basis=axis_position_basis,
            axis_position_m=axis_position_m,
            event_axis_branch_id=prepared.preferred_axis_branch_id,
            axis_origin_point=axis_origin,
            axis_unit_vector=axis_unit_vector,
        )
        if reference_detail:
            summary.update(reference_detail)
        dedupe_key = (
            str(summary["upper_evidence_object_id"]),
            str(summary["point_signature"]),
            str(summary["layer"]),
        )
        if dedupe_key in seen_keys:
            return
        seen_keys.add(dedupe_key)
        synthetic_features: tuple[LoadedFeature, ...]
        if force_empty_divstrip:
            synthetic_features = ()
        else:
            synthetic_features = (
                LoadedFeature(
                    feature_index=int(feature_index),
                    properties={} if properties is None else dict(properties),
                    geometry=normalized_region,
                ),
            )
        candidates.append(
            {
                "summary": summary,
                "region_geometry": normalized_region,
                "reference_point": reference_point,
                "divstrip_features": synthetic_features,
            }
        )

    for feature in prepared.pair_local_scope_divstrip_features:
        upper_id = str(feature.properties.get("id") or feature.feature_index)
        clipped_geometry = _clip_geometry_to_scope(
            feature.geometry,
            scope_geometry=pair_region,
            pad_m=0.0,
        )
        for index, component in enumerate(_explode_polygon_geometries(clipped_geometry), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:divstrip:{upper_id}:{index:02d}",
                source_mode="pair_local_divstrip",
                upper_evidence_kind="divstrip",
                upper_evidence_object_id=upper_id,
                candidate_scope="divstrip_component",
                region_geometry=component,
                feature_index=feature.feature_index,
                properties={
                    **dict(feature.properties),
                    "candidate_id": f"{prepared.event_unit_spec.event_unit_id}:divstrip:{upper_id}:{index:02d}",
                    "upper_evidence_object_id": upper_id,
                },
                reference_strategy="representative",
            )

    has_primary_candidate = any(bool(item["summary"].get("primary_eligible")) for item in candidates)
    allow_additional_surface_fork = (
        prepared.event_unit_spec.split_mode == "complex_one_node_one_unit"
        and len(prepared.explicit_event_branch_ids) >= 2
    )
    allow_simple_surface_fork = (
        prepared.event_unit_spec.split_mode == "one_case_one_unit"
        and _boundary_pair_road_ids_from_summary(prepared.pair_local_summary) is not None
        and not has_primary_candidate
    )
    if allow_simple_surface_fork and structure_face is not None and not structure_face.is_empty:
        for index, component in enumerate(_explode_polygon_geometries(structure_face), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:road_surface_fork:surface:{index:02d}",
                source_mode="pair_local_structure_mode",
                upper_evidence_kind="structure_face",
                upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                candidate_scope=ROAD_SURFACE_FORK_SCOPE,
                region_geometry=component,
                feature_index=-10,
                properties={"candidate_scope": ROAD_SURFACE_FORK_SCOPE},
                reference_strategy="road_surface_fork_apex",
                force_empty_divstrip=True,
                require_surface_fork_apex=True,
            )
    if (
        throat_core is not None
        and not throat_core.is_empty
        and (not candidates or (allow_additional_surface_fork and not has_primary_candidate))
    ):
        for index, component in enumerate(_explode_polygon_geometries(throat_core), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:road_surface_fork:{index:02d}",
                source_mode="pair_local_structure_mode",
                upper_evidence_kind="structure_face",
                upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                candidate_scope=ROAD_SURFACE_FORK_SCOPE,
                region_geometry=component,
                feature_index=-10,
                properties={"candidate_scope": ROAD_SURFACE_FORK_SCOPE},
                force_empty_divstrip=True,
            )

    if throat_core is not None and not throat_core.is_empty:
        for index, component in enumerate(_explode_polygon_geometries(throat_core), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:throat:{index:02d}",
                source_mode="pair_local_structure_mode",
                upper_evidence_kind="structure_face",
                upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                candidate_scope="throat_core",
                region_geometry=component,
                feature_index=-1,
                properties={"candidate_scope": "throat_core"},
                force_empty_divstrip=True,
            )
    if structure_face is not None and not structure_face.is_empty:
        body_geometry = pair_middle
        if body_geometry is not None and not body_geometry.is_empty and throat_core is not None and not throat_core.is_empty:
            body_geometry = _safe_normalize_geometry(
                body_geometry.difference(
                    throat_core.buffer(STRUCTURE_BODY_THROAT_EXCLUSION_M, join_style=2)
                )
            )
        for index, component in enumerate(_explode_polygon_geometries(body_geometry), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:body:{index:02d}",
                source_mode="pair_local_structure_mode",
                upper_evidence_kind="structure_face",
                upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                candidate_scope="pair_middle_body",
                region_geometry=component,
                feature_index=-2,
                properties={"candidate_scope": "pair_middle_body"},
                reference_strategy="representative",
                force_empty_divstrip=True,
            )
        if throat_core is not None and not throat_core.is_empty:
            edge_geometry = _safe_normalize_geometry(
                structure_face.difference(
                    throat_core.buffer(max(PAIR_LOCAL_REGION_PAD_M * 0.5, 1.0), join_style=2)
                )
            )
            if edge_geometry is not None:
                for index, component in enumerate(_explode_polygon_geometries(edge_geometry), start=1):
                    _append_candidate(
                        candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:edge:{index:02d}",
                        source_mode="pair_local_structure_mode",
                        upper_evidence_kind="structure_face",
                        upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                        candidate_scope="edge_band",
                        region_geometry=component,
                        feature_index=-3,
                        properties={"candidate_scope": "edge_band"},
                        reference_strategy="representative",
                        force_empty_divstrip=True,
                    )

    if not candidates:
        fallback_geometry = pair_region or prepared.unit_context.representative_node.geometry.buffer(
            PAIR_LOCAL_SCOPE_PAD_M,
            join_style=2,
        )
        _append_candidate(
            candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:fallback:01",
            source_mode="pair_local_structure_mode",
            upper_evidence_kind="structure_face",
            upper_evidence_object_id=prepared.pair_local_summary["region_id"],
            candidate_scope="fallback",
            region_geometry=fallback_geometry,
            feature_index=-9,
            properties={"candidate_scope": "fallback"},
            force_empty_divstrip=True,
        )

    ranked_candidates = sorted(
        candidates,
        key=lambda item: (
            int(item["summary"]["layer"]),
            -float(item["summary"]["pair_middle_overlap_ratio"]),
            -float(item["summary"]["throat_overlap_ratio"]),
            -float(getattr(item["region_geometry"], "area", 0.0) or 0.0),
            str(item["summary"]["candidate_id"]),
        ),
    )
    return ranked_candidates[:MAX_CANDIDATES_PER_UNIT]


def _build_unit_envelope(prepared: _PreparedUnitInputs) -> T04UnitEnvelope:
    return T04UnitEnvelope(
        topology_scope=(
            "single_node_event_input"
            if prepared.event_unit_spec.split_mode == "complex_one_node_one_unit"
            else (
                "multi_divmerge_case_input"
                if prepared.event_unit_spec.split_mode == "multi_divmerge_adjacent_pair"
                else "case_coordination"
            )
        ),
        unit_population_node_ids=tuple(prepared.unit_population_node_ids),
        context_augmented_node_ids=tuple(prepared.context_augmented_node_ids),
        branch_ids=tuple(str(branch.branch_id) for branch in prepared.scoped_branches),
        main_branch_ids=tuple(sorted(str(branch_id) for branch_id in prepared.scoped_main_branch_ids)),
        input_branch_ids=tuple(prepared.scoped_input_branch_ids),
        output_branch_ids=tuple(prepared.scoped_output_branch_ids),
        event_branch_ids=tuple(prepared.explicit_event_branch_ids),
        boundary_branch_ids=tuple(prepared.boundary_branch_ids),
        preferred_axis_branch_id=prepared.preferred_axis_branch_id,
        branch_road_memberships=dict(prepared.branch_road_memberships),
        branch_bridge_node_ids=dict(prepared.branch_bridge_node_ids),
        degraded_scope_reason=prepared.degraded_scope_reason,
        degraded_scope_severity=prepared.pair_local_summary.get("degraded_scope_severity"),
        degraded_scope_fallback_used=bool(prepared.pair_local_summary.get("degraded_scope_fallback_used")),
    )
