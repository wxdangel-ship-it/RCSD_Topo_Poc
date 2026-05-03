from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .support_domain import T04Step5CaseResult
from .surface_scenario import SCENARIO_NO_SURFACE_REFERENCE, SURFACE_MODE_NO_SURFACE


def _merged_text(values: Iterable[Any], *, missing_value: str = "missing") -> str:
    texts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in texts:
            texts.append(text)
    if not texts:
        return missing_value
    return texts[0] if len(texts) == 1 else "mixed"


def _step5_units_have_field(step5_result: T04Step5CaseResult, field_name: str) -> bool:
    return bool(step5_result.unit_results) and all(hasattr(unit, field_name) for unit in step5_result.unit_results)


@dataclass(frozen=True)
class Step6GuardContext:
    surface_scenario_type: str
    section_reference_source: str
    surface_generation_mode: str
    reference_point_present: bool
    surface_section_forward_m: float | None
    surface_section_backward_m: float | None
    surface_lateral_limit_m: float | None
    fallback_rcsdroad_ids: tuple[str, ...]
    fallback_rcsdroad_localized: bool
    no_virtual_reference_point_guard: bool
    forbidden_domain_kept: bool
    divstrip_negative_mask_present: bool
    surface_scenario_missing: bool
    no_surface_reference_guard: bool


def derive_step6_guard_context(step5_result: T04Step5CaseResult) -> Step6GuardContext:
    units = tuple(step5_result.unit_results)
    surface_scenario_missing = not (
        _step5_units_have_field(step5_result, "surface_scenario_type")
        and _step5_units_have_field(step5_result, "surface_generation_mode")
    )
    scenario_type = _merged_text(getattr(unit, "surface_scenario_type", "") for unit in units)
    generation_mode = _merged_text(getattr(unit, "surface_generation_mode", "") for unit in units)
    section_reference_source = _merged_text(getattr(unit, "section_reference_source", "") for unit in units)
    fallback_ids: list[str] = []
    for unit in units:
        for road_id in getattr(unit, "fallback_rcsdroad_ids", ()) or ():
            text = str(road_id or "").strip()
            if text and text not in fallback_ids:
                fallback_ids.append(text)
    explicit_no_surface_units = [
        unit
        for unit in units
        if str(getattr(unit, "surface_scenario_type", "") or "") == SCENARIO_NO_SURFACE_REFERENCE
        or str(getattr(unit, "surface_generation_mode", "") or "") == SURFACE_MODE_NO_SURFACE
    ]
    no_surface_reference_guard = bool(units) and len(explicit_no_surface_units) == len(units)
    return Step6GuardContext(
        surface_scenario_type=scenario_type,
        section_reference_source=section_reference_source,
        surface_generation_mode=generation_mode,
        reference_point_present=any(bool(getattr(unit, "reference_point_present", False)) for unit in units),
        surface_section_forward_m=getattr(step5_result, "surface_section_forward_m", None),
        surface_section_backward_m=getattr(step5_result, "surface_section_backward_m", None),
        surface_lateral_limit_m=getattr(step5_result, "surface_lateral_limit_m", None),
        fallback_rcsdroad_ids=tuple(fallback_ids),
        fallback_rcsdroad_localized=any(bool(getattr(unit, "fallback_rcsdroad_localized", False)) for unit in units),
        no_virtual_reference_point_guard=bool(getattr(step5_result, "no_virtual_reference_point_guard", True)),
        forbidden_domain_kept=bool(
            getattr(step5_result, "forbidden_domain_kept", False)
            or step5_result.case_forbidden_domain is not None
        ),
        divstrip_negative_mask_present=bool(
            getattr(step5_result, "divstrip_negative_mask_present", False)
            or step5_result.divstrip_void_mask_geometry is not None
        ),
        surface_scenario_missing=surface_scenario_missing,
        no_surface_reference_guard=no_surface_reference_guard,
    )


__all__ = ["Step6GuardContext", "derive_step6_guard_context"]
