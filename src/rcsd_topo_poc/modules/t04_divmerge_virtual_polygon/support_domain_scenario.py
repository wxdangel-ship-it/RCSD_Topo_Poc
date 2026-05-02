from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .surface_scenario import (
    SCENARIO_NO_SURFACE_REFERENCE,
    SECTION_REFERENCE_NONE,
    SURFACE_MODE_NO_SURFACE,
)


STEP5_POINT_PATCH_RADIUS_M = 2.5
STEP5_REQUIRED_NODE_PATCH_RADIUS_M = 2.5
STEP5_B_NODE_TARGET_PATCH_RADIUS_M = 2.5
STEP5_FALLBACK_STRIP_HALF_LENGTH_M = 20.0
STEP5_FALLBACK_STRIP_HALF_WIDTH_M = 3.0
STEP5_SUPPORT_ROAD_BUFFER_M = 6.0
STEP5_BRIDGE_HALF_WIDTH_M = 3.0
STEP5_NEGATIVE_MASK_BUFFER_M = 1.0
STEP5_TERMINAL_CUT_HALF_WIDTH_M = 12.0
STEP5_TERMINAL_CUT_WINDOW_MARGIN_M = 20.0
STEP5_SUPPORT_GRAPH_PAD_M = 2.0
STEP5_TERMINAL_WINDOW_FALLBACK_HALF_WIDTH_M = 240.0
STEP5_TERMINAL_AXIS_ANCHOR_TOLERANCE_M = 15.0
STEP5_TERMINAL_MIN_ANCHOR_SPAN_M = 1.0
STEP5_JUNCTION_WINDOW_HALF_LENGTH_M = 20.0
STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M = 20.0
STEP5_FULL_FILL_BRIDGE_MAX_DISTANCE_M = 8.0
STEP5_FULL_FILL_BRIDGE_MAX_EXISTING_OVERLAP_M2 = 25.0
STEP5_SURFACE_SECTION_FORWARD_M = 20.0
STEP5_SURFACE_SECTION_BACKWARD_M = 20.0
STEP5_SURFACE_LATERAL_LIMIT_M = 20.0
STEP5_JUNCTION_WINDOW_EVIDENCE_SOURCES = {
    "swsd_junction_window",
    "rcsd_junction_window",
}


@dataclass(frozen=True)
class Step5SurfaceWindowConfig:
    surface_scenario_type: str
    section_reference_source: str
    surface_generation_mode: str
    reference_point_present: bool
    has_main_evidence: bool
    surface_scenario_missing: bool
    support_domain_from_reference_kind: str
    fallback_rcsdroad_ids: tuple[str, ...]
    fallback_local_window_m: float | None
    fallback_rcsdroad_localized: bool
    no_virtual_reference_point_guard: bool
    surface_section_forward_m: float = STEP5_SURFACE_SECTION_FORWARD_M
    surface_section_backward_m: float = STEP5_SURFACE_SECTION_BACKWARD_M
    surface_lateral_limit_m: float = STEP5_SURFACE_LATERAL_LIMIT_M

    @property
    def entity_support_enabled(self) -> bool:
        return (
            self.surface_scenario_type != SCENARIO_NO_SURFACE_REFERENCE
            and self.section_reference_source != SECTION_REFERENCE_NONE
            and self.surface_generation_mode != SURFACE_MODE_NO_SURFACE
        )

    def to_doc(self) -> dict[str, Any]:
        return {
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "has_main_evidence": self.has_main_evidence,
            "surface_scenario_missing": self.surface_scenario_missing,
            "support_domain_from_reference_kind": self.support_domain_from_reference_kind,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_local_window_m": self.fallback_local_window_m,
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
        }


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _clean_ids(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    ids: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in ids:
            ids.append(text)
    return tuple(ids)


def derive_step5_surface_window_config(
    surface_scenario: Mapping[str, Any] | None,
    *,
    surface_scenario_missing: bool = False,
) -> Step5SurfaceWindowConfig:
    scenario_doc = dict(surface_scenario or {})
    scenario_type = _clean_text(
        scenario_doc.get("surface_scenario_type"),
        SCENARIO_NO_SURFACE_REFERENCE,
    )
    section_reference_source = _clean_text(
        scenario_doc.get("section_reference_source"),
        SECTION_REFERENCE_NONE,
    )
    surface_generation_mode = _clean_text(
        scenario_doc.get("surface_generation_mode"),
        SURFACE_MODE_NO_SURFACE,
    )
    has_main_evidence = bool(scenario_doc.get("has_main_evidence", False))
    reference_point_present = bool(scenario_doc.get("reference_point_present", False))
    fallback_rcsdroad_ids = _clean_ids(scenario_doc.get("fallback_rcsdroad_ids"))
    no_virtual_reference_point_guard = not (reference_point_present and not has_main_evidence)
    fallback_rcsdroad_localized = (
        bool(fallback_rcsdroad_ids)
        and scenario_type != SCENARIO_NO_SURFACE_REFERENCE
        and surface_generation_mode != SURFACE_MODE_NO_SURFACE
    )
    return Step5SurfaceWindowConfig(
        surface_scenario_type=scenario_type,
        section_reference_source=section_reference_source,
        surface_generation_mode=surface_generation_mode,
        reference_point_present=reference_point_present,
        has_main_evidence=has_main_evidence,
        surface_scenario_missing=surface_scenario_missing,
        support_domain_from_reference_kind=section_reference_source,
        fallback_rcsdroad_ids=fallback_rcsdroad_ids,
        fallback_local_window_m=STEP5_JUNCTION_WINDOW_HALF_LENGTH_M if fallback_rcsdroad_ids else None,
        fallback_rcsdroad_localized=fallback_rcsdroad_localized,
        no_virtual_reference_point_guard=no_virtual_reference_point_guard,
    )


__all__ = [
    "STEP5_B_NODE_TARGET_PATCH_RADIUS_M",
    "STEP5_BRIDGE_HALF_WIDTH_M",
    "STEP5_FALLBACK_STRIP_HALF_LENGTH_M",
    "STEP5_FALLBACK_STRIP_HALF_WIDTH_M",
    "STEP5_FULL_FILL_BRIDGE_MAX_DISTANCE_M",
    "STEP5_FULL_FILL_BRIDGE_MAX_EXISTING_OVERLAP_M2",
    "STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M",
    "STEP5_JUNCTION_WINDOW_EVIDENCE_SOURCES",
    "STEP5_JUNCTION_WINDOW_HALF_LENGTH_M",
    "STEP5_NEGATIVE_MASK_BUFFER_M",
    "STEP5_POINT_PATCH_RADIUS_M",
    "STEP5_REQUIRED_NODE_PATCH_RADIUS_M",
    "STEP5_SUPPORT_GRAPH_PAD_M",
    "STEP5_SUPPORT_ROAD_BUFFER_M",
    "STEP5_SURFACE_LATERAL_LIMIT_M",
    "STEP5_SURFACE_SECTION_BACKWARD_M",
    "STEP5_SURFACE_SECTION_FORWARD_M",
    "STEP5_TERMINAL_AXIS_ANCHOR_TOLERANCE_M",
    "STEP5_TERMINAL_CUT_HALF_WIDTH_M",
    "STEP5_TERMINAL_CUT_WINDOW_MARGIN_M",
    "STEP5_TERMINAL_MIN_ANCHOR_SPAN_M",
    "STEP5_TERMINAL_WINDOW_FALLBACK_HALF_WIDTH_M",
    "Step5SurfaceWindowConfig",
    "derive_step5_surface_window_config",
]
