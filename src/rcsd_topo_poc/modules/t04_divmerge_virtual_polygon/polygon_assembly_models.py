from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry


def _geometry_summary(geometry: BaseGeometry | None) -> dict[str, Any]:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return {
            "present": False,
            "geometry_type": "",
            "area_m2": 0.0,
            "length_m": 0.0,
        }
    return {
        "present": True,
        "geometry_type": str(normalized.geom_type),
        "area_m2": float(getattr(normalized, "area", 0.0) or 0.0),
        "length_m": float(getattr(normalized, "length", 0.0) or 0.0),
    }


@dataclass(frozen=True)
class T04Step6Result:
    case_id: str
    final_case_polygon: BaseGeometry | None
    final_case_holes: BaseGeometry | None
    final_case_cut_lines: BaseGeometry | None
    final_case_forbidden_overlap: BaseGeometry | None
    assembly_canvas_geometry: BaseGeometry | None
    hard_seed_geometry: BaseGeometry | None
    weak_seed_geometry: BaseGeometry | None
    component_count: int
    hole_count: int
    business_hole_count: int
    unexpected_hole_count: int
    hard_must_cover_ok: bool
    b_node_target_covered: bool
    forbidden_overlap_area_m2: float
    cut_violation: bool
    assembly_state: str
    review_reasons: tuple[str, ...]
    hard_connect_notes: tuple[str, ...]
    optional_connect_notes: tuple[str, ...]
    hole_details: tuple[dict[str, Any], ...]
    relief_constraint_audit_entries: tuple[dict[str, Any], ...] = ()
    post_cleanup_allowed_growth_ok: bool = True
    post_cleanup_forbidden_ok: bool = True
    post_cleanup_terminal_cut_ok: bool = True
    post_cleanup_lateral_limit_ok: bool = True
    post_cleanup_negative_mask_ok: bool = True
    post_cleanup_must_cover_ok: bool = True
    post_cleanup_recheck_performed: bool = False
    surface_scenario_type: str = "missing"
    section_reference_source: str = "missing"
    surface_generation_mode: str = "missing"
    reference_point_present: bool = False
    surface_section_forward_m: float | None = None
    surface_section_backward_m: float | None = None
    surface_lateral_limit_m: float | None = None
    surface_scenario_missing: bool = True
    no_surface_reference_guard: bool = False
    final_polygon_suppressed_by_no_surface_reference: bool = False
    no_virtual_reference_point_guard: bool = True
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    fallback_rcsdroad_localized: bool = False
    fallback_domain_contained_by_allowed_growth: bool = True
    fallback_overexpansion_detected: bool = False
    fallback_overexpansion_area_m2: float = 0.0
    lateral_limit_check_mode: str = "via_allowed_growth"
    negative_mask_check_mode: str = "total_forbidden_plus_divstrip_mask"
    negative_mask_channel_overlaps: dict[str, dict[str, Any]] | None = None
    negative_mask_conflict_channel_names: tuple[str, ...] = ()
    bridge_negative_mask_channel_overlaps: dict[str, dict[str, Any]] | None = None
    bridge_negative_mask_crossing_detected: bool = False
    case_alignment_review_reasons: tuple[str, ...] = ()
    case_alignment_ambiguous_event_unit_ids: tuple[str, ...] = ()
    forbidden_domain_kept: bool = False
    divstrip_negative_mask_present: bool = False
    divstrip_negative_overlap_area_m2: float = 0.0
    allowed_growth_outside_area_m2: float = 0.0
    terminal_cut_overlap_area_m2: float = 0.0
    unit_surface_count: int = 0
    unit_surface_merge_performed: bool = False
    merge_mode: str = "case_level_assembly"
    merged_case_surface_component_count: int = 0
    final_case_polygon_component_count: int = 0
    single_connected_case_surface_ok: bool = False
    barrier_separated_case_surface_ok: bool = False
    b_node_gate_applicable: bool = True
    b_node_gate_skip_reason: str = ""
    section_reference_window_covered: bool = True

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "assembly_state": self.assembly_state,
            "review_reasons": list(self.review_reasons),
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "surface_scenario_missing": self.surface_scenario_missing,
            "no_surface_reference_guard": self.no_surface_reference_guard,
            "final_polygon_suppressed_by_no_surface_reference": self.final_polygon_suppressed_by_no_surface_reference,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "component_count": self.component_count,
            "hole_count": self.hole_count,
            "business_hole_count": self.business_hole_count,
            "unexpected_hole_count": self.unexpected_hole_count,
            "hard_must_cover_ok": self.hard_must_cover_ok,
            "b_node_target_covered": self.b_node_target_covered,
            "b_node_gate_applicable": self.b_node_gate_applicable,
            "b_node_gate_skip_reason": self.b_node_gate_skip_reason,
            "section_reference_window_covered": self.section_reference_window_covered,
            "forbidden_overlap_area_m2": self.forbidden_overlap_area_m2,
            "cut_violation": self.cut_violation,
            "post_cleanup_allowed_growth_ok": self.post_cleanup_allowed_growth_ok,
            "post_cleanup_forbidden_ok": self.post_cleanup_forbidden_ok,
            "post_cleanup_terminal_cut_ok": self.post_cleanup_terminal_cut_ok,
            "post_cleanup_lateral_limit_ok": self.post_cleanup_lateral_limit_ok,
            "post_cleanup_negative_mask_ok": self.post_cleanup_negative_mask_ok,
            "post_cleanup_must_cover_ok": self.post_cleanup_must_cover_ok,
            "post_cleanup_recheck_performed": self.post_cleanup_recheck_performed,
            "lateral_limit_check_mode": self.lateral_limit_check_mode,
            "negative_mask_check_mode": self.negative_mask_check_mode,
            "negative_mask_channel_overlaps": self.negative_mask_channel_overlaps or {},
            "negative_mask_conflict_channel_names": list(self.negative_mask_conflict_channel_names),
            "bridge_negative_mask_channel_overlaps": self.bridge_negative_mask_channel_overlaps or {},
            "bridge_negative_mask_crossing_detected": self.bridge_negative_mask_crossing_detected,
            "case_alignment_review_reasons": list(self.case_alignment_review_reasons),
            "case_alignment_ambiguous_event_unit_ids": list(self.case_alignment_ambiguous_event_unit_ids),
            "relief_constraint_audit_count": len(self.relief_constraint_audit_entries),
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "fallback_domain_contained_by_allowed_growth": self.fallback_domain_contained_by_allowed_growth,
            "fallback_overexpansion_detected": self.fallback_overexpansion_detected,
            "fallback_overexpansion_area_m2": self.fallback_overexpansion_area_m2,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "divstrip_negative_overlap_area_m2": self.divstrip_negative_overlap_area_m2,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "unit_surface_count": self.unit_surface_count,
            "unit_surface_merge_performed": self.unit_surface_merge_performed,
            "merge_mode": self.merge_mode,
            "merged_case_surface_component_count": self.merged_case_surface_component_count,
            "final_case_polygon_component_count": self.final_case_polygon_component_count,
            "single_connected_case_surface_ok": self.single_connected_case_surface_ok,
            "barrier_separated_case_surface_ok": self.barrier_separated_case_surface_ok,
            "final_case_polygon": _geometry_summary(self.final_case_polygon),
            "final_case_holes": _geometry_summary(self.final_case_holes),
            "final_case_cut_lines": _geometry_summary(self.final_case_cut_lines),
            "final_case_forbidden_overlap": _geometry_summary(self.final_case_forbidden_overlap),
        }

    def to_audit_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "assembly_canvas_geometry": _geometry_summary(self.assembly_canvas_geometry),
            "hard_seed_geometry": _geometry_summary(self.hard_seed_geometry),
            "weak_seed_geometry": _geometry_summary(self.weak_seed_geometry),
            "hard_connect_notes": list(self.hard_connect_notes),
            "optional_connect_notes": list(self.optional_connect_notes),
            "relief_constraint_audit_entries": [dict(item) for item in self.relief_constraint_audit_entries],
            "hole_details": [dict(item) for item in self.hole_details],
            "post_cleanup_allowed_growth_ok": self.post_cleanup_allowed_growth_ok,
            "post_cleanup_forbidden_ok": self.post_cleanup_forbidden_ok,
            "post_cleanup_terminal_cut_ok": self.post_cleanup_terminal_cut_ok,
            "post_cleanup_lateral_limit_ok": self.post_cleanup_lateral_limit_ok,
            "post_cleanup_negative_mask_ok": self.post_cleanup_negative_mask_ok,
            "post_cleanup_must_cover_ok": self.post_cleanup_must_cover_ok,
            "post_cleanup_recheck_performed": self.post_cleanup_recheck_performed,
            "allowed_growth_outside_area_m2": self.allowed_growth_outside_area_m2,
            "terminal_cut_overlap_area_m2": self.terminal_cut_overlap_area_m2,
            "lateral_limit_check_mode": self.lateral_limit_check_mode,
            "negative_mask_check_mode": self.negative_mask_check_mode,
            "negative_mask_channel_overlaps": self.negative_mask_channel_overlaps or {},
            "negative_mask_conflict_channel_names": list(self.negative_mask_conflict_channel_names),
            "bridge_negative_mask_channel_overlaps": self.bridge_negative_mask_channel_overlaps or {},
            "bridge_negative_mask_crossing_detected": self.bridge_negative_mask_crossing_detected,
            "case_alignment_review_reasons": list(self.case_alignment_review_reasons),
            "case_alignment_ambiguous_event_unit_ids": list(self.case_alignment_ambiguous_event_unit_ids),
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "b_node_gate_applicable": self.b_node_gate_applicable,
            "b_node_gate_skip_reason": self.b_node_gate_skip_reason,
            "section_reference_window_covered": self.section_reference_window_covered,
            "surface_scenario_missing": self.surface_scenario_missing,
            "no_surface_reference_guard": self.no_surface_reference_guard,
            "final_polygon_suppressed_by_no_surface_reference": self.final_polygon_suppressed_by_no_surface_reference,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "fallback_domain_contained_by_allowed_growth": self.fallback_domain_contained_by_allowed_growth,
            "fallback_overexpansion_detected": self.fallback_overexpansion_detected,
            "fallback_overexpansion_area_m2": self.fallback_overexpansion_area_m2,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "divstrip_negative_overlap_area_m2": self.divstrip_negative_overlap_area_m2,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "unit_surface_count": self.unit_surface_count,
            "unit_surface_merge_performed": self.unit_surface_merge_performed,
            "merge_mode": self.merge_mode,
            "merged_case_surface_component_count": self.merged_case_surface_component_count,
            "final_case_polygon_component_count": self.final_case_polygon_component_count,
            "single_connected_case_surface_ok": self.single_connected_case_surface_ok,
            "barrier_separated_case_surface_ok": self.barrier_separated_case_surface_ok,
        }


__all__ = ["T04Step6Result"]
