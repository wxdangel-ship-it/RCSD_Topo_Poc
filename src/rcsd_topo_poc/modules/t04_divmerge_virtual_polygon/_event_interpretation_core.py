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

from ._event_interpretation_results import (
    _build_result_from_interpretation,
    _empty_selected_evidence_summary,
    _evaluate_unit_candidate,
)

def _prepare_unit_inputs(
    *,
    case_bundle: T04CaseBundle,
    unit_context: T04UnitContext,
    event_unit_spec,
) -> _PreparedUnitInputs:
    effective_representative_node, effective_source_kind_2 = _effective_complex_kind_hint(
        case_bundle=case_bundle,
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
    )
    filtered_branches, filtered_roads, main_branch_ids = _filter_branch_scope(
        unit_context,
        event_unit_spec.selected_side_branch_ids,
    )
    if event_unit_spec.split_mode == "one_case_one_unit" and len(filtered_branches) == 2:
        direct_adjacency_branch_set = _build_direct_adjacency_branch_set(
            unit_context=unit_context,
            filtered_roads=list(filtered_roads),
        )
        if direct_adjacency_branch_set is not None:
            return _materialize_prepared_unit_inputs(
                case_bundle=case_bundle,
                unit_context=unit_context,
                event_unit_spec=event_unit_spec,
                effective_representative_node=effective_representative_node,
                effective_source_kind_2=effective_source_kind_2,
                filtered_branches=list(filtered_branches),
                filtered_roads=list(filtered_roads),
                main_branch_ids=set(main_branch_ids),
                executable_branch_set=direct_adjacency_branch_set,
                slice_diagnostic_builder=_build_pair_local_slice_diagnostic,
            )
    if event_unit_spec.split_mode == "complex_one_node_one_unit":
        executable_branch_variants = _build_complex_executable_branch_variants(
            unit_context=unit_context,
            filtered_roads=list(filtered_roads),
            selected_event_branch_ids=tuple(event_unit_spec.selected_side_branch_ids),
        )
        best_prepared: _PreparedUnitInputs | None = None
        best_rank: tuple[int, ...] | None = None
        for executable_branch_set in executable_branch_variants:
            prepared = _materialize_prepared_unit_inputs(
                case_bundle=case_bundle,
                unit_context=unit_context,
                event_unit_spec=event_unit_spec,
                effective_representative_node=effective_representative_node,
                effective_source_kind_2=effective_source_kind_2,
                filtered_branches=list(filtered_branches),
                filtered_roads=list(filtered_roads),
                main_branch_ids=set(main_branch_ids),
                executable_branch_set=executable_branch_set,
                slice_diagnostic_builder=_build_pair_local_slice_diagnostic,
            )
            raw_candidates = _build_candidate_pool(prepared)
            evaluations = _rank_candidate_pool(
                [_evaluate_unit_candidate(prepared, candidate) for candidate in raw_candidates]
            )
            rank = _prepared_variant_rank(prepared, evaluations)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_prepared = prepared
        if best_prepared is not None:
            return best_prepared
    return _materialize_prepared_unit_inputs(
        case_bundle=case_bundle,
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
        effective_representative_node=effective_representative_node,
        effective_source_kind_2=effective_source_kind_2,
        filtered_branches=list(filtered_branches),
        filtered_roads=list(filtered_roads),
        main_branch_ids=set(main_branch_ids),
        executable_branch_set=None,
        slice_diagnostic_builder=_build_pair_local_slice_diagnostic,
    )
