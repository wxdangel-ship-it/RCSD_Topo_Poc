from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry
from .support_domain_common import _geometry_summary
from .support_domain_scenario import (
    STEP5_SURFACE_LATERAL_LIMIT_M,
    STEP5_SURFACE_SECTION_BACKWARD_M,
    STEP5_SURFACE_SECTION_FORWARD_M,
)
from .surface_scenario import (
    SCENARIO_NO_SURFACE_REFERENCE,
    SECTION_REFERENCE_NONE,
    SURFACE_MODE_NO_SURFACE,
)


@dataclass(frozen=True)
class T04Step5UnitResult:
    event_unit_id: str
    event_type: str
    review_state: str
    positive_rcsd_consistency_level: str
    positive_rcsd_support_level: str
    required_rcsd_node: str | None
    legacy_step5_ready: bool
    legacy_step5_reasons: tuple[str, ...]
    localized_evidence_core_geometry: BaseGeometry | None
    fact_reference_patch_geometry: BaseGeometry | None
    required_rcsd_node_patch_geometry: BaseGeometry | None
    target_b_node_patch_geometry: BaseGeometry | None
    fallback_support_strip_geometry: BaseGeometry | None
    unit_must_cover_domain: BaseGeometry | None
    unit_allowed_growth_domain: BaseGeometry | None
    unit_forbidden_domain: BaseGeometry | None
    unit_terminal_cut_constraints: BaseGeometry | None
    unit_terminal_window_domain: BaseGeometry | None
    terminal_support_corridor_geometry: BaseGeometry | None
    axis_lateral_band_geometry: BaseGeometry | None = None
    section_reference_patch_geometry: BaseGeometry | None = None
    junction_full_road_fill_domain: BaseGeometry | None = None
    surface_fill_mode: str = "standard"
    surface_fill_axis_half_width_m: float | None = None
    single_component_surface_seed: bool = False
    support_road_ids: tuple[str, ...] = ()
    support_event_road_ids: tuple[str, ...] = ()
    positive_rcsd_road_ids: tuple[str, ...] = ()
    positive_rcsd_node_ids: tuple[str, ...] = ()
    must_cover_components: dict[str, bool] = field(default_factory=dict)
    surface_scenario_type: str = SCENARIO_NO_SURFACE_REFERENCE
    section_reference_source: str = SECTION_REFERENCE_NONE
    surface_generation_mode: str = SURFACE_MODE_NO_SURFACE
    reference_point_present: bool = False
    surface_scenario_missing: bool = False
    support_domain_from_reference_kind: str = SECTION_REFERENCE_NONE
    surface_section_forward_m: float = STEP5_SURFACE_SECTION_FORWARD_M
    surface_section_backward_m: float = STEP5_SURFACE_SECTION_BACKWARD_M
    surface_lateral_limit_m: float = STEP5_SURFACE_LATERAL_LIMIT_M
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    fallback_local_window_m: float | None = None
    fallback_support_strip_area_m2: float = 0.0
    fallback_rcsdroad_localized: bool = False
    no_virtual_reference_point_guard: bool = True
    divstrip_negative_mask_present: bool = False
    forbidden_domain_kept: bool = False
    swsd_only_entity_support_domain: bool = False
    swsd_only_negative_mask_relief_applied: bool = False

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "event_unit_id": self.event_unit_id,
            "event_type": self.event_type,
            "review_state": self.review_state,
            "positive_rcsd_support_level": self.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": self.positive_rcsd_consistency_level,
            "required_rcsd_node": self.required_rcsd_node,
            "legacy_step5_readiness": {
                "ready": self.legacy_step5_ready,
                "reasons": list(self.legacy_step5_reasons),
            },
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "surface_scenario_missing": self.surface_scenario_missing,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "support_domain_from_reference_kind": self.support_domain_from_reference_kind,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_local_window_m": self.fallback_local_window_m,
            "fallback_support_strip_area_m2": self.fallback_support_strip_area_m2,
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "swsd_only_entity_support_domain": self.swsd_only_entity_support_domain,
            "swsd_only_negative_mask_relief_applied": self.swsd_only_negative_mask_relief_applied,
            "surface_fill_mode": self.surface_fill_mode,
            "surface_fill_axis_half_width_m": self.surface_fill_axis_half_width_m,
            "single_component_surface_seed": self.single_component_surface_seed,
            "must_cover_components": dict(self.must_cover_components),
            "unit_must_cover_domain": _geometry_summary(self.unit_must_cover_domain),
            "unit_allowed_growth_domain": _geometry_summary(self.unit_allowed_growth_domain),
            "unit_forbidden_domain": _geometry_summary(self.unit_forbidden_domain),
            "unit_terminal_cut_constraints": _geometry_summary(self.unit_terminal_cut_constraints),
            "unit_terminal_window_domain": _geometry_summary(self.unit_terminal_window_domain),
            "axis_lateral_band_geometry": _geometry_summary(self.axis_lateral_band_geometry),
            "section_reference_patch_geometry": _geometry_summary(self.section_reference_patch_geometry),
            "junction_full_road_fill_domain": _geometry_summary(self.junction_full_road_fill_domain),
            "localized_evidence_core_geometry": _geometry_summary(self.localized_evidence_core_geometry),
            "fact_reference_patch_geometry": _geometry_summary(self.fact_reference_patch_geometry),
            "required_rcsd_node_patch_geometry": _geometry_summary(self.required_rcsd_node_patch_geometry),
            "target_b_node_patch_geometry": _geometry_summary(self.target_b_node_patch_geometry),
            "fallback_support_strip_geometry": _geometry_summary(self.fallback_support_strip_geometry),
            "terminal_support_corridor_geometry": _geometry_summary(self.terminal_support_corridor_geometry),
        }

    def to_audit_doc(self) -> dict[str, Any]:
        return {
            "event_unit_id": self.event_unit_id,
            "support_road_ids": list(self.support_road_ids),
            "support_event_road_ids": list(self.support_event_road_ids),
            "positive_rcsd_road_ids": list(self.positive_rcsd_road_ids),
            "positive_rcsd_node_ids": list(self.positive_rcsd_node_ids),
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "surface_scenario_missing": self.surface_scenario_missing,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "support_domain_from_reference_kind": self.support_domain_from_reference_kind,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_local_window_m": self.fallback_local_window_m,
            "fallback_support_strip_area_m2": self.fallback_support_strip_area_m2,
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "swsd_only_entity_support_domain": self.swsd_only_entity_support_domain,
            "swsd_only_negative_mask_relief_applied": self.swsd_only_negative_mask_relief_applied,
            "surface_fill_mode": self.surface_fill_mode,
            "surface_fill_axis_half_width_m": self.surface_fill_axis_half_width_m,
            "single_component_surface_seed": self.single_component_surface_seed,
            "must_cover_components": dict(self.must_cover_components),
            "unit_terminal_window_domain": _geometry_summary(self.unit_terminal_window_domain),
            "axis_lateral_band_geometry": _geometry_summary(self.axis_lateral_band_geometry),
            "section_reference_patch_geometry": _geometry_summary(self.section_reference_patch_geometry),
            "junction_full_road_fill_domain": _geometry_summary(self.junction_full_road_fill_domain),
            "terminal_support_corridor_geometry": _geometry_summary(self.terminal_support_corridor_geometry),
        }

@dataclass(frozen=True)
class T04Step5CaseResult:
    case_id: str
    unit_results: tuple[T04Step5UnitResult, ...]
    case_must_cover_domain: BaseGeometry | None
    case_allowed_growth_domain: BaseGeometry | None
    case_forbidden_domain: BaseGeometry | None
    case_terminal_cut_constraints: BaseGeometry | None
    case_terminal_window_domain: BaseGeometry | None
    case_terminal_support_corridor_geometry: BaseGeometry | None
    case_bridge_zone_geometry: BaseGeometry | None
    case_support_graph_geometry: BaseGeometry | None
    unrelated_swsd_mask_geometry: BaseGeometry | None = None
    unrelated_rcsd_mask_geometry: BaseGeometry | None = None
    divstrip_body_mask_geometry: BaseGeometry | None = None
    divstrip_void_mask_geometry: BaseGeometry | None = None
    drivezone_outside_enforced_by_allowed_domain: bool = True
    related_swsd_road_ids: tuple[str, ...] = ()
    related_rcsd_road_ids: tuple[str, ...] = ()
    unrelated_swsd_road_ids: tuple[str, ...] = ()
    unrelated_swsd_node_ids: tuple[str, ...] = ()
    unrelated_rcsd_road_ids: tuple[str, ...] = ()
    unrelated_rcsd_node_ids: tuple[str, ...] = ()
    surface_section_forward_m: float = STEP5_SURFACE_SECTION_FORWARD_M
    surface_section_backward_m: float = STEP5_SURFACE_SECTION_BACKWARD_M
    surface_lateral_limit_m: float = STEP5_SURFACE_LATERAL_LIMIT_M
    no_virtual_reference_point_guard: bool = True
    forbidden_domain_kept: bool = False
    divstrip_negative_mask_present: bool = False

    def unit_result_by_id(self, event_unit_id: str) -> T04Step5UnitResult:
        for unit_result in self.unit_results:
            if unit_result.event_unit_id == event_unit_id:
                return unit_result
        raise KeyError(event_unit_id)

    def to_status_doc(self) -> dict[str, Any]:
        ready_count = sum(1 for unit in self.unit_results if unit.legacy_step5_ready)
        return {
            "case_id": self.case_id,
            "unit_count": len(self.unit_results),
            "legacy_step5_ready_unit_count": ready_count,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "case_must_cover_domain": _geometry_summary(self.case_must_cover_domain),
            "case_allowed_growth_domain": _geometry_summary(self.case_allowed_growth_domain),
            "case_forbidden_domain": _geometry_summary(self.case_forbidden_domain),
            "case_terminal_cut_constraints": _geometry_summary(self.case_terminal_cut_constraints),
            "case_terminal_window_domain": _geometry_summary(self.case_terminal_window_domain),
            "case_terminal_support_corridor_geometry": _geometry_summary(self.case_terminal_support_corridor_geometry),
            "case_bridge_zone_geometry": _geometry_summary(self.case_bridge_zone_geometry),
            "negative_mask_channels": self.negative_mask_channel_status(),
            "unit_results": [unit.to_status_doc() for unit in self.unit_results],
        }

    def negative_mask_channel_status(self) -> dict[str, Any]:
        return {
            "unrelated_swsd": {
                "road_ids": list(self.unrelated_swsd_road_ids),
                "node_ids": list(self.unrelated_swsd_node_ids),
                "geometry": _geometry_summary(self.unrelated_swsd_mask_geometry),
                "applied_to_forbidden_domain": self.unrelated_swsd_mask_geometry is not None,
            },
            "unrelated_rcsd": {
                "road_ids": list(self.unrelated_rcsd_road_ids),
                "node_ids": list(self.unrelated_rcsd_node_ids),
                "geometry": _geometry_summary(self.unrelated_rcsd_mask_geometry),
                "applied_to_forbidden_domain": self.unrelated_rcsd_mask_geometry is not None,
            },
            "divstrip_body": {
                "geometry": _geometry_summary(self.divstrip_body_mask_geometry),
                "applied_to_forbidden_domain": False,
            },
            "divstrip_void": {
                "geometry": _geometry_summary(self.divstrip_void_mask_geometry),
                "applied_to_forbidden_domain": self.divstrip_void_mask_geometry is not None,
            },
            "forbidden_domain": {
                "geometry": _geometry_summary(self.case_forbidden_domain),
                "applied_to_forbidden_domain": self.case_forbidden_domain is not None,
            },
            "terminal_cut": {
                "geometry": _geometry_summary(self.case_terminal_cut_constraints),
                "applied_to_forbidden_domain": self.case_terminal_cut_constraints is not None,
            },
        }

    def to_audit_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "drivezone_outside_enforced_by_allowed_domain": self.drivezone_outside_enforced_by_allowed_domain,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "case_support_graph_geometry": _geometry_summary(self.case_support_graph_geometry),
            "unrelated_swsd_mask_geometry": _geometry_summary(self.unrelated_swsd_mask_geometry),
            "unrelated_rcsd_mask_geometry": _geometry_summary(self.unrelated_rcsd_mask_geometry),
            "divstrip_body_mask_geometry": _geometry_summary(self.divstrip_body_mask_geometry),
            "divstrip_void_mask_geometry": _geometry_summary(self.divstrip_void_mask_geometry),
            "case_terminal_window_domain": _geometry_summary(self.case_terminal_window_domain),
            "case_terminal_support_corridor_geometry": _geometry_summary(self.case_terminal_support_corridor_geometry),
            "related_swsd_road_ids": list(self.related_swsd_road_ids),
            "related_rcsd_road_ids": list(self.related_rcsd_road_ids),
            "unrelated_swsd_road_ids": list(self.unrelated_swsd_road_ids),
            "unrelated_swsd_node_ids": list(self.unrelated_swsd_node_ids),
            "unrelated_rcsd_road_ids": list(self.unrelated_rcsd_road_ids),
            "unrelated_rcsd_node_ids": list(self.unrelated_rcsd_node_ids),
            "negative_mask_channels": self.negative_mask_channel_status(),
            "unit_results": [unit.to_audit_doc() for unit in self.unit_results],
        }

    def to_vector_features(self) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []

        def append_feature(
            *,
            scope: str,
            event_unit_id: str,
            domain_role: str,
            component_role: str,
            geometry: BaseGeometry | None,
        ) -> None:
            normalized = _normalize_geometry(geometry)
            if normalized is None:
                return
            features.append(
                {
                    "properties": {
                        "case_id": self.case_id,
                        "scope": scope,
                        "event_unit_id": event_unit_id,
                        "domain_role": domain_role,
                        "component_role": component_role,
                    },
                    "geometry": normalized,
                }
            )

        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_must_cover_domain",
            component_role="case_must_cover_domain",
            geometry=self.case_must_cover_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_allowed_growth_domain",
            component_role="case_allowed_growth_domain",
            geometry=self.case_allowed_growth_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_forbidden_domain",
            component_role="case_forbidden_domain",
            geometry=self.case_forbidden_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_forbidden_domain",
            component_role="unrelated_swsd_mask_geometry",
            geometry=self.unrelated_swsd_mask_geometry,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_forbidden_domain",
            component_role="unrelated_rcsd_mask_geometry",
            geometry=self.unrelated_rcsd_mask_geometry,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_forbidden_domain",
            component_role="divstrip_void_mask_geometry",
            geometry=self.divstrip_void_mask_geometry,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_audit_reference",
            component_role="divstrip_body_mask_geometry",
            geometry=self.divstrip_body_mask_geometry,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_terminal_cut_constraints",
            component_role="case_terminal_cut_constraints",
            geometry=self.case_terminal_cut_constraints,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_terminal_window_domain",
            component_role="case_terminal_window_domain",
            geometry=self.case_terminal_window_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_allowed_growth_domain",
            component_role="case_terminal_support_corridor_geometry",
            geometry=self.case_terminal_support_corridor_geometry,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_allowed_growth_domain",
            component_role="case_bridge_zone_geometry",
            geometry=self.case_bridge_zone_geometry,
        )

        for unit in self.unit_results:
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="unit_must_cover_domain",
                geometry=unit.unit_must_cover_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="unit_allowed_growth_domain",
                geometry=unit.unit_allowed_growth_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_forbidden_domain",
                component_role="unit_forbidden_domain",
                geometry=unit.unit_forbidden_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_terminal_cut_constraints",
                component_role="unit_terminal_cut_constraints",
                geometry=unit.unit_terminal_cut_constraints,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_terminal_window_domain",
                component_role="unit_terminal_window_domain",
                geometry=unit.unit_terminal_window_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="axis_lateral_band_geometry",
                geometry=unit.axis_lateral_band_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="junction_full_road_fill_domain",
                geometry=unit.junction_full_road_fill_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="terminal_support_corridor_geometry",
                geometry=unit.terminal_support_corridor_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="localized_evidence_core_geometry",
                geometry=unit.localized_evidence_core_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="fact_reference_patch_geometry",
                geometry=unit.fact_reference_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="section_reference_patch_geometry",
                geometry=unit.section_reference_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="required_rcsd_node_patch_geometry",
                geometry=unit.required_rcsd_node_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="target_b_node_patch_geometry",
                geometry=unit.target_b_node_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="fallback_support_strip_geometry",
                geometry=unit.fallback_support_strip_geometry,
            )
        return features
