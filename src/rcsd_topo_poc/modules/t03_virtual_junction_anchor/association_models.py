from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import Step1Context, Step2TemplateResult


@dataclass(frozen=True)
class Step45Context:
    step1_context: Step1Context
    template_result: Step2TemplateResult
    step3_run_root: Path
    step3_case_dir: Path
    step3_allowed_space_geometry: BaseGeometry | None
    current_swsd_surface_geometry: BaseGeometry | None
    step3_status_doc: dict[str, Any]
    step3_audit_doc: dict[str, Any]
    selected_road_ids: tuple[str, ...]
    step3_excluded_road_ids: tuple[str, ...]
    prerequisite_issues: tuple[str, ...]


@dataclass(frozen=True)
class Step45OutputGeometries:
    required_rcsdnode_geometry: BaseGeometry | None
    required_rcsdroad_geometry: BaseGeometry | None
    support_rcsdnode_geometry: BaseGeometry | None
    support_rcsdroad_geometry: BaseGeometry | None
    excluded_rcsdnode_geometry: BaseGeometry | None
    excluded_rcsdroad_geometry: BaseGeometry | None
    required_hook_zone_geometry: BaseGeometry | None
    foreign_swsd_context_geometry: BaseGeometry | None
    foreign_rcsd_context_geometry: BaseGeometry | None


@dataclass(frozen=True)
class Step45ForeignResult:
    excluded_rcsdnode_ids: tuple[str, ...]
    excluded_rcsdroad_ids: tuple[str, ...]
    nonsemantic_connector_rcsdnode_ids: tuple[str, ...]
    true_foreign_rcsdnode_ids: tuple[str, ...]
    excluded_rcsdnode_geometry: BaseGeometry | None
    excluded_rcsdroad_geometry: BaseGeometry | None
    foreign_swsd_context_geometry: BaseGeometry | None
    foreign_rcsd_context_geometry: BaseGeometry | None
    audit_doc: dict[str, Any]


@dataclass(frozen=True)
class Step45CaseResult:
    case_id: str
    template_class: str | None
    association_class: str
    step45_state: str
    step45_established: bool
    reason: str
    visual_review_class: str
    root_cause_layer: str | None
    root_cause_type: str | None
    output_geometries: Step45OutputGeometries
    key_metrics: dict[str, Any]
    audit_doc: dict[str, Any]
    extra_status_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Step45ReviewIndexRow:
    case_id: str
    template_class: str | None
    association_class: str
    step45_state: str
    reason: str
    image_name: str
    image_path: str
    visual_review_class: str | None = None
    root_cause_layer: str | None = None
    root_cause_type: str | None = None
