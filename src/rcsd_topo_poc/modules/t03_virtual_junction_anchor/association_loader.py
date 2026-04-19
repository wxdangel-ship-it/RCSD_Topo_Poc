from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import CaseSpec
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_status_doc
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import Step45Context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import Step1Context, Step2TemplateResult, Step3CaseResult
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import ROAD_BUFFER_M


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _read_union_geometry(path: Path):
    layer = read_vector_layer(path)
    geometries = [feature.geometry for feature in layer.features if feature.geometry is not None]
    if not geometries:
        return None
    merged = unary_union(geometries).buffer(0)
    return None if merged.is_empty else merged


def _clean_geometry(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (GeometryCollection, MultiPolygon)):
        parts = [part.buffer(0) for part in geometry.geoms if part is not None and not part.is_empty]
        if not parts:
            return None
        geometry = unary_union(parts)
    cleaned = geometry.buffer(0)
    return None if cleaned.is_empty else cleaned


def _build_current_swsd_surface_geometry(step1_context, selected_road_ids: tuple[str, ...]):
    if not selected_road_ids:
        return None
    road_surfaces = [
        road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2)
        for road in step1_context.roads
        if road.road_id in set(selected_road_ids)
    ]
    if not road_surfaces:
        return None
    merged = unary_union(road_surfaces).intersection(step1_context.drivezone_geometry)
    return _clean_geometry(merged)


def _stable_ids(values: Any) -> tuple[str, ...]:
    ids = [str(value) for value in (values or []) if value is not None and str(value) != ""]
    return tuple(sorted(set(ids), key=lambda item: (0, int(item)) if item.isdigit() else (1, item)))


def _stable_issue_codes(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def load_step45_context(*, case_spec: CaseSpec, step3_root: str | Path) -> Step45Context:
    step1_context = build_step1_context(case_spec)
    template_result = classify_step2_template(step1_context)
    resolved_step3_root = normalize_runtime_path(step3_root)
    step3_case_dir = resolved_step3_root / "cases" / case_spec.case_id
    allowed_space_path = step3_case_dir / "step3_allowed_space.gpkg"
    status_path = step3_case_dir / "step3_status.json"
    audit_path = step3_case_dir / "step3_audit.json"
    prerequisite_issues: list[str] = []
    step3_status_doc: dict[str, Any] = {}
    step3_audit_doc: dict[str, Any] = {}
    step3_allowed_space_geometry = None
    if not step3_case_dir.is_dir():
        prerequisite_issues.append("step45_missing_step3_case_dir")
    else:
        if status_path.exists():
            step3_status_doc = _read_json(status_path)
        else:
            prerequisite_issues.append("step45_missing_step3_status_json")
        if audit_path.exists():
            step3_audit_doc = _read_json(audit_path)
        else:
            prerequisite_issues.append("step45_missing_step3_audit_json")
        if allowed_space_path.exists():
            step3_allowed_space_geometry = _read_union_geometry(allowed_space_path)
            if step3_allowed_space_geometry is None:
                prerequisite_issues.append("step45_empty_step3_allowed_space")
        else:
            prerequisite_issues.append("step45_missing_step3_allowed_space")

    step3_state = str(step3_status_doc.get("step3_state") or "")
    if not step3_state:
        prerequisite_issues.append("step45_missing_step3_state")

    selected_road_ids = _stable_ids(step3_status_doc.get("selected_road_ids"))
    if not selected_road_ids:
        prerequisite_issues.append("step45_missing_selected_road_ids")
    else:
        available_road_ids = {road.road_id for road in step1_context.roads}
        if any(road_id not in available_road_ids for road_id in selected_road_ids):
            prerequisite_issues.append("step45_selected_road_ids_not_in_step1_roads")

    excluded_road_ids = _stable_ids(
        step3_status_doc.get("excluded_road_ids")
        or step3_audit_doc.get("excluded_road_ids")
    )
    current_swsd_surface_geometry = _build_current_swsd_surface_geometry(step1_context, selected_road_ids)
    if selected_road_ids and current_swsd_surface_geometry is None:
        prerequisite_issues.append("step45_missing_current_swsd_surface")
    return Step45Context(
        step1_context=step1_context,
        template_result=template_result,
        step3_run_root=resolved_step3_root,
        step3_case_dir=step3_case_dir,
        step3_allowed_space_geometry=step3_allowed_space_geometry,
        current_swsd_surface_geometry=current_swsd_surface_geometry,
        step3_status_doc=step3_status_doc,
        step3_audit_doc=step3_audit_doc,
        selected_road_ids=selected_road_ids,
        step3_excluded_road_ids=excluded_road_ids,
        prerequisite_issues=_stable_issue_codes(prerequisite_issues),
    )


def build_step45_context_from_step3_case(
    *,
    step1_context: Step1Context,
    template_result: Step2TemplateResult,
    step3_run_root: str | Path,
    step3_case_dir: str | Path,
    step3_case_result: Step3CaseResult,
) -> Step45Context:
    resolved_step3_run_root = normalize_runtime_path(step3_run_root)
    resolved_step3_case_dir = normalize_runtime_path(step3_case_dir)
    step3_status_doc = build_step3_status_doc(step3_case_result)
    step3_audit_doc = dict(step3_case_result.audit_doc)
    prerequisite_issues: list[str] = []

    step3_state = str(step3_status_doc.get("step3_state") or "")
    if not step3_state:
        prerequisite_issues.append("step45_missing_step3_state")

    selected_road_ids = _stable_ids(step3_status_doc.get("selected_road_ids"))
    if not selected_road_ids:
        prerequisite_issues.append("step45_missing_selected_road_ids")
    else:
        available_road_ids = {road.road_id for road in step1_context.roads}
        if any(road_id not in available_road_ids for road_id in selected_road_ids):
            prerequisite_issues.append("step45_selected_road_ids_not_in_step1_roads")

    excluded_road_ids = _stable_ids(
        step3_status_doc.get("excluded_road_ids")
        or step3_audit_doc.get("excluded_road_ids")
    )
    current_swsd_surface_geometry = _build_current_swsd_surface_geometry(step1_context, selected_road_ids)
    if selected_road_ids and current_swsd_surface_geometry is None:
        prerequisite_issues.append("step45_missing_current_swsd_surface")

    return Step45Context(
        step1_context=step1_context,
        template_result=template_result,
        step3_run_root=resolved_step3_run_root,
        step3_case_dir=resolved_step3_case_dir,
        step3_allowed_space_geometry=step3_case_result.allowed_space_geometry,
        current_swsd_surface_geometry=current_swsd_surface_geometry,
        step3_status_doc=step3_status_doc,
        step3_audit_doc=step3_audit_doc,
        selected_road_ids=selected_road_ids,
        step3_excluded_road_ids=excluded_road_ids,
        prerequisite_issues=_stable_issue_codes(prerequisite_issues),
    )


def load_step45_case_specs(
    *,
    case_root: str | Path,
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
    exclude_case_ids: list[str] | tuple[str, ...] | None = None,
):
    return load_case_specs(
        case_root=case_root,
        case_ids=case_ids,
        max_cases=max_cases,
        exclude_case_ids=exclude_case_ids,
    )
