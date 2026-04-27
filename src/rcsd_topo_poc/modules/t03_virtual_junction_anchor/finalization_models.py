from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import (
    AssociationCaseResult,
    AssociationContext,
)


@dataclass(frozen=True)
class FinalizationContext:
    association_context: AssociationContext
    association_case_result: AssociationCaseResult


@dataclass(frozen=True)
class Step6OutputGeometries:
    polygon_seed_geometry: BaseGeometry | None
    polygon_final_geometry: BaseGeometry | None
    foreign_mask_geometry: BaseGeometry | None
    must_cover_geometry: BaseGeometry | None


@dataclass(frozen=True)
class Step6Result:
    step6_state: str
    geometry_established: bool
    problem_geometry: bool
    reason: str
    primary_root_cause: str | None
    secondary_root_cause: str | None
    review_signals: tuple[str, ...]
    output_geometries: Step6OutputGeometries
    key_metrics: dict[str, Any]
    audit_doc: dict[str, Any]
    extra_status_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Step7Result:
    step7_state: str
    accepted: bool
    reason: str
    visual_review_class: str
    root_cause_layer: str | None
    root_cause_type: str | None
    note: str | None
    key_metrics: dict[str, Any]
    audit_doc: dict[str, Any]
    extra_status_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalizationCaseResult:
    case_id: str
    template_class: str | None
    association_class: str
    association_state: str
    step6_result: Step6Result
    step7_result: Step7Result


@dataclass(frozen=True)
class FinalizationReviewIndexRow:
    case_id: str
    template_class: str | None
    association_class: str
    association_state: str
    step6_state: str
    step7_state: str
    visual_class: str
    reason: str
    note: str
    source_png_path: str
    sequence_no: int | None = None
    image_name: str | None = None
    image_path: str | None = None
