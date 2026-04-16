from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def _tuple_str(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        items.append(str(value))
    return tuple(items)


def _tuple_mapping(values: Sequence[Mapping[str, Any]] | None) -> tuple[dict[str, Any], ...]:
    if not values:
        return ()
    return tuple(dict(value) for value in values)


def _geometry_present(geometry: Any) -> bool:
    return bool(geometry is not None and not geometry.is_empty)


def _geometry_area(geometry: Any) -> float:
    if not _geometry_present(geometry):
        return 0.0
    return float(geometry.area)


def _mask_popcount(mask: Any) -> int:
    if mask is None:
        return 0
    if hasattr(mask, "sum"):
        return int(mask.sum())
    return 0


def _snapshot_summary(snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    return {
        "start_offset_m": snapshot.get("start_offset_m"),
        "end_offset_m": snapshot.get("end_offset_m"),
        "candidate_offset_count": snapshot.get("candidate_offset_count"),
        "expansion_source": snapshot.get("expansion_source"),
        "semantic_prev_boundary_offset_m": snapshot.get("semantic_prev_boundary_offset_m"),
        "semantic_next_boundary_offset_m": snapshot.get("semantic_next_boundary_offset_m"),
        "semantic_protected_start_m": snapshot.get("semantic_protected_start_m"),
        "semantic_protected_end_m": snapshot.get("semantic_protected_end_m"),
    }


@dataclass(frozen=True)
class Stage4SpanWindow:
    base: Mapping[str, Any]
    after_chain: Mapping[str, Any]
    after_semantic: Mapping[str, Any]
    after_divstrip_complex: Mapping[str, Any]
    after_divstrip_simple: Mapping[str, Any]
    final: Mapping[str, Any]
    recall_limit_mode: str = "step2_bounded"

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "scope": "span_window",
            "recall_limit_mode": self.recall_limit_mode,
            "base": _snapshot_summary(self.base),
            "after_chain": _snapshot_summary(self.after_chain),
            "after_semantic": _snapshot_summary(self.after_semantic),
            "after_divstrip_complex": _snapshot_summary(self.after_divstrip_complex),
            "after_divstrip_simple": _snapshot_summary(self.after_divstrip_simple),
            "final": _snapshot_summary(self.final),
        }


@dataclass(frozen=True)
class Stage4ExclusionGeometryContext:
    source_priority: tuple[str, ...]
    parallel_excluded_road_ids: tuple[str, ...]
    parallel_side_sign: int | None
    parallel_centerline_road_id: str | None
    parallel_competitor_present: bool
    selected_support_corridor_applied: bool
    divstrip_exclusion_source: str
    divstrip_event_window_present: bool
    local_surface_clip_present: bool
    geometry_window_clamped: bool
    negative_exclusion_applied: bool
    preferred_clip_mode: str
    event_side_clip_mode: str
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "scope": "negative_exclusion_geometry",
            "source_priority": list(self.source_priority),
            "parallel_excluded_road_ids": list(self.parallel_excluded_road_ids),
            "parallel_side_sign": self.parallel_side_sign,
            "parallel_centerline_road_id": self.parallel_centerline_road_id,
            "parallel_competitor_present": self.parallel_competitor_present,
            "selected_support_corridor_applied": self.selected_support_corridor_applied,
            "divstrip_exclusion_source": self.divstrip_exclusion_source,
            "divstrip_event_window_present": self.divstrip_event_window_present,
            "local_surface_clip_present": self.local_surface_clip_present,
            "geometry_window_clamped": self.geometry_window_clamped,
            "negative_exclusion_applied": self.negative_exclusion_applied,
            "preferred_clip_mode": self.preferred_clip_mode,
            "event_side_clip_mode": self.event_side_clip_mode,
        }


@dataclass(frozen=True)
class Stage4SurfaceAssemblyResult:
    axis_window_geometry: Any
    parallel_side_geometry: Any
    selected_support_corridor_geometry: Any
    event_side_drivezone_geometry: Any
    cross_section_surface_geometry: Any
    divstrip_event_window: Any
    local_surface_clip_geometry: Any
    event_side_clip_geometry: Any
    cross_section_sample_count: int
    parallel_side_sample_count: int
    allow_full_axis_drivezone_fill: bool
    selected_support_corridor_applied: bool
    full_fill_start_offset_m: float
    full_fill_end_offset_m: float
    component_side_clip_buffer_m: float
    cross_section_support_mode: str
    selected_component_surface_diags: tuple[dict[str, Any], ...]
    complex_multibranch_lobe_diags: tuple[dict[str, Any], ...]
    multi_component_surface_applied: bool
    complex_multibranch_lobe_applied: bool

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "scope": "surface_assembly",
            "axis_window_present": _geometry_present(self.axis_window_geometry),
            "axis_window_area_m2": _geometry_area(self.axis_window_geometry),
            "parallel_side_present": _geometry_present(self.parallel_side_geometry),
            "parallel_side_area_m2": _geometry_area(self.parallel_side_geometry),
            "selected_support_corridor_present": _geometry_present(self.selected_support_corridor_geometry),
            "selected_support_corridor_area_m2": _geometry_area(self.selected_support_corridor_geometry),
            "event_side_drivezone_present": _geometry_present(self.event_side_drivezone_geometry),
            "event_side_drivezone_area_m2": _geometry_area(self.event_side_drivezone_geometry),
            "cross_section_surface_present": _geometry_present(self.cross_section_surface_geometry),
            "cross_section_surface_area_m2": _geometry_area(self.cross_section_surface_geometry),
            "divstrip_event_window_present": _geometry_present(self.divstrip_event_window),
            "divstrip_event_window_area_m2": _geometry_area(self.divstrip_event_window),
            "local_surface_clip_present": _geometry_present(self.local_surface_clip_geometry),
            "local_surface_clip_area_m2": _geometry_area(self.local_surface_clip_geometry),
            "event_side_clip_present": _geometry_present(self.event_side_clip_geometry),
            "event_side_clip_area_m2": _geometry_area(self.event_side_clip_geometry),
            "cross_section_sample_count": self.cross_section_sample_count,
            "parallel_side_sample_count": self.parallel_side_sample_count,
            "allow_full_axis_drivezone_fill": self.allow_full_axis_drivezone_fill,
            "selected_support_corridor_applied": self.selected_support_corridor_applied,
            "full_fill_start_offset_m": self.full_fill_start_offset_m,
            "full_fill_end_offset_m": self.full_fill_end_offset_m,
            "component_side_clip_buffer_m": self.component_side_clip_buffer_m,
            "cross_section_support_mode": self.cross_section_support_mode,
            "selected_component_surface_count": len(
                [
                    item
                    for item in self.selected_component_surface_diags
                    if bool(item.get("ok", False)) and item.get("component_index") != "connector"
                ]
            ),
            "selected_component_surface_diags": [dict(item) for item in self.selected_component_surface_diags],
            "complex_multibranch_lobe_count": len(
                [item for item in self.complex_multibranch_lobe_diags if bool(item.get("ok", False))]
            ),
            "complex_multibranch_lobe_diags": [dict(item) for item in self.complex_multibranch_lobe_diags],
            "multi_component_surface_applied": self.multi_component_surface_applied,
            "complex_multibranch_lobe_applied": self.complex_multibranch_lobe_applied,
        }


@dataclass(frozen=True)
class Stage4GeometricSupportDomain:
    span_window: Stage4SpanWindow
    exclusion_context: Stage4ExclusionGeometryContext
    surface_assembly: Stage4SurfaceAssemblyResult
    selected_roads_geometry: Any
    selected_event_roads_geometry: Any
    selected_rcsd_roads_geometry: Any
    event_seed_union: Any
    axis_window_mask: Any
    parallel_side_mask: Any
    cross_section_surface_mask: Any
    seed_mask: Any
    support_mask: Any
    event_side_support_mask: Any
    drivezone_component_mask: Any
    component_mask: Any
    divstrip_geometry_to_exclude: Any
    event_side_support_geometry_count: int
    component_mask_used_support_fallback: bool
    component_mask_reseeded_after_clip: bool
    component_mask_clipped: bool

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "scope": "geometric_support_domain",
            "span_window": self.span_window.to_audit_summary(),
            "exclusion_context": self.exclusion_context.to_audit_summary(),
            "surface_assembly": self.surface_assembly.to_audit_summary(),
            "selected_roads_geometry_present": _geometry_present(self.selected_roads_geometry),
            "selected_event_roads_geometry_present": _geometry_present(self.selected_event_roads_geometry),
            "selected_rcsd_roads_geometry_present": _geometry_present(self.selected_rcsd_roads_geometry),
            "event_seed_union_present": _geometry_present(self.event_seed_union),
            "support_domain_area_m2": max(
                _geometry_area(self.surface_assembly.event_side_drivezone_geometry),
                _geometry_area(self.surface_assembly.cross_section_surface_geometry),
                _geometry_area(self.surface_assembly.axis_window_geometry),
            ),
            "axis_window_mask_popcount": _mask_popcount(self.axis_window_mask),
            "parallel_side_mask_popcount": _mask_popcount(self.parallel_side_mask),
            "cross_section_surface_mask_popcount": _mask_popcount(self.cross_section_surface_mask),
            "seed_mask_popcount": _mask_popcount(self.seed_mask),
            "support_mask_popcount": _mask_popcount(self.support_mask),
            "event_side_support_mask_popcount": _mask_popcount(self.event_side_support_mask),
            "drivezone_component_mask_popcount": _mask_popcount(self.drivezone_component_mask),
            "component_mask_popcount": _mask_popcount(self.component_mask),
            "divstrip_geometry_to_exclude_present": _geometry_present(self.divstrip_geometry_to_exclude),
            "event_side_support_geometry_count": self.event_side_support_geometry_count,
            "component_mask_used_support_fallback": self.component_mask_used_support_fallback,
            "component_mask_reseeded_after_clip": self.component_mask_reseeded_after_clip,
            "component_mask_clipped": self.component_mask_clipped,
        }


@dataclass(frozen=True)
class Stage4GeometryState:
    value: str

    def to_audit_summary(self) -> str:
        return self.value


@dataclass(frozen=True)
class Stage4GeometryRiskSignals:
    signals: tuple[str, ...]

    def to_audit_summary(self) -> list[str]:
        return list(self.signals)


@dataclass(frozen=True)
class Stage4LegacyStep7Bridge:
    ready: bool
    reasons: tuple[str, ...]
    polygon_geometry: Any
    support_clip_geometry: Any
    axis_window_geometry: Any
    parallel_side_geometry: Any
    event_side_drivezone_geometry: Any
    preferred_clip_geometry: Any
    divstrip_geometry_to_exclude: Any

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "required": True,
            "ready": self.ready,
            "reasons": list(self.reasons),
            "polygon_geometry_present": _geometry_present(self.polygon_geometry),
            "support_clip_geometry_present": _geometry_present(self.support_clip_geometry),
            "axis_window_geometry_present": _geometry_present(self.axis_window_geometry),
            "parallel_side_geometry_present": _geometry_present(self.parallel_side_geometry),
            "event_side_drivezone_geometry_present": _geometry_present(self.event_side_drivezone_geometry),
            "preferred_clip_geometry_present": _geometry_present(self.preferred_clip_geometry),
            "divstrip_geometry_to_exclude_present": _geometry_present(self.divstrip_geometry_to_exclude),
        }


@dataclass(frozen=True)
class Stage4PolygonAssemblyResult:
    polygon_geometry: Any
    geometry_state: Stage4GeometryState
    geometry_risk_signals: Stage4GeometryRiskSignals
    polygon_built: bool
    expected_continuous_chain_multilobe_geometry: bool
    selected_event_corridor_bridge_applied: bool
    include_event_side_drivezone_in_polygon_union: bool
    selected_support_present: bool
    divstrip_guard_clip_applied: bool
    divstrip_event_window_clip_applied: bool
    divstrip_exclusion_applied: bool
    preferred_clip_mode: str
    preferred_clip_applied: bool
    parallel_side_clip_applied: bool
    full_fill_applied: bool
    regularized: bool
    legacy_step7_bridge: Stage4LegacyStep7Bridge

    def to_audit_summary(self) -> dict[str, Any]:
        area_m2 = float(self.polygon_geometry.area) if _geometry_present(self.polygon_geometry) else 0.0
        return {
            "scope": "polygon_assembly",
            "polygon_built": self.polygon_built,
            "polygon_area_m2": area_m2,
            "geometry_state": self.geometry_state.to_audit_summary(),
            "geometry_risk_signals": self.geometry_risk_signals.to_audit_summary(),
            "expected_continuous_chain_multilobe_geometry": self.expected_continuous_chain_multilobe_geometry,
            "selected_event_corridor_bridge_applied": self.selected_event_corridor_bridge_applied,
            "include_event_side_drivezone_in_polygon_union": self.include_event_side_drivezone_in_polygon_union,
            "selected_support_present": self.selected_support_present,
            "divstrip_guard_clip_applied": self.divstrip_guard_clip_applied,
            "divstrip_event_window_clip_applied": self.divstrip_event_window_clip_applied,
            "divstrip_exclusion_applied": self.divstrip_exclusion_applied,
            "preferred_clip_mode": self.preferred_clip_mode,
            "preferred_clip_applied": self.preferred_clip_applied,
            "parallel_side_clip_applied": self.parallel_side_clip_applied,
            "full_fill_applied": self.full_fill_applied,
            "regularized": self.regularized,
            "legacy_step7_adapter": self.legacy_step7_bridge.to_audit_summary(),
        }
