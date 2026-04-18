from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import CaseSpec
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_models import Step45Context
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
    road_surfaces = [
        road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2)
        for road in step1_context.roads
        if road.road_id in set(selected_road_ids)
    ]
    if not road_surfaces:
        return _clean_geometry(step1_context.representative_node.geometry.buffer(ROAD_BUFFER_M * 2.0).intersection(step1_context.drivezone_geometry))
    merged = unary_union(road_surfaces).intersection(step1_context.drivezone_geometry)
    return _clean_geometry(merged)


def _stable_ids(values: Any) -> tuple[str, ...]:
    ids = [str(value) for value in (values or []) if value is not None and str(value) != ""]
    return tuple(sorted(set(ids), key=lambda item: (0, int(item)) if item.isdigit() else (1, item)))


def load_step45_context(*, case_spec: CaseSpec, step3_root: str | Path) -> Step45Context:
    step1_context = build_step1_context(case_spec)
    template_result = classify_step2_template(step1_context)
    resolved_step3_root = normalize_runtime_path(step3_root)
    step3_case_dir = resolved_step3_root / "cases" / case_spec.case_id
    if not step3_case_dir.is_dir():
        raise ValueError(f"missing step3 case directory for case_id={case_spec.case_id}: {step3_case_dir}")

    allowed_space_path = step3_case_dir / "step3_allowed_space.gpkg"
    status_path = step3_case_dir / "step3_status.json"
    audit_path = step3_case_dir / "step3_audit.json"
    for required_path in (allowed_space_path, status_path, audit_path):
        if not required_path.exists():
            raise ValueError(f"missing step3 prerequisite for case_id={case_spec.case_id}: {required_path}")

    step3_status_doc = _read_json(status_path)
    step3_audit_doc = _read_json(audit_path)
    selected_road_ids = _stable_ids(
        step3_status_doc.get("selected_road_ids")
        or step3_audit_doc.get("selected_road_ids")
        or sorted(step1_context.target_road_ids)
    )
    excluded_road_ids = _stable_ids(
        step3_status_doc.get("excluded_road_ids")
        or step3_audit_doc.get("excluded_road_ids")
    )
    return Step45Context(
        step1_context=step1_context,
        template_result=template_result,
        step3_run_root=resolved_step3_root,
        step3_case_dir=step3_case_dir,
        step3_allowed_space_geometry=_read_union_geometry(allowed_space_path),
        current_swsd_surface_geometry=_build_current_swsd_surface_geometry(step1_context, selected_road_ids),
        step3_status_doc=step3_status_doc,
        step3_audit_doc=step3_audit_doc,
        selected_road_ids=selected_road_ids,
        step3_excluded_road_ids=excluded_road_ids,
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
