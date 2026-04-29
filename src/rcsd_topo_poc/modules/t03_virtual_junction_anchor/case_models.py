from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    mainnodeid: str
    case_root: Path
    manifest: dict[str, Any]
    size_report: dict[str, Any]
    input_paths: dict[str, Path]


@dataclass(frozen=True)
class NodeRecord:
    feature_index: int
    node_id: str
    mainnodeid: str | None
    has_evd: str | None
    is_anchor: str | None
    kind_2: int | None
    grade_2: int | None
    geometry: BaseGeometry


@dataclass(frozen=True)
class RoadRecord:
    feature_index: int
    road_id: str
    snodeid: str | None
    enodeid: str | None
    direction: int | None
    geometry: BaseGeometry
    formway: int | None = None


@dataclass(frozen=True)
class SemanticGroup:
    group_id: str
    nodes: tuple[NodeRecord, ...]


@dataclass(frozen=True)
class Step1Context:
    case_spec: CaseSpec
    representative_node: NodeRecord
    target_group: SemanticGroup
    all_nodes: tuple[NodeRecord, ...]
    foreign_groups: tuple[SemanticGroup, ...]
    roads: tuple[RoadRecord, ...]
    rcsd_roads: tuple[RoadRecord, ...]
    rcsd_nodes: tuple[NodeRecord, ...]
    drivezone_geometry: BaseGeometry
    target_road_ids: frozenset[str]


@dataclass(frozen=True)
class Step2TemplateResult:
    template_class: str | None
    supported: bool
    reason: str | None


@dataclass(frozen=True)
class Step3NegativeMasks:
    adjacent_junction_geometry: BaseGeometry | None
    foreign_objects_geometry: BaseGeometry | None
    foreign_mst_geometry: BaseGeometry | None
    adjacent_junction_records: tuple[dict[str, Any], ...] = ()
    foreign_object_records: tuple[dict[str, Any], ...] = ()
    foreign_mst_records: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Step3CaseResult:
    case_id: str
    template_class: str | None
    step3_state: str
    step3_established: bool
    reason: str
    visual_review_class: str
    root_cause_layer: str | None
    root_cause_type: str | None
    allowed_space_geometry: BaseGeometry | None
    allowed_drivezone_geometry: BaseGeometry | None
    negative_masks: Step3NegativeMasks
    key_metrics: dict[str, Any]
    audit_doc: dict[str, Any]
    review_signals: tuple[str, ...] = ()
    blocked_directions: tuple[dict[str, Any], ...] = ()
    extra_status_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewIndexRow:
    case_id: str
    template_class: str | None
    step3_state: str
    reason: str
    image_name: str
    image_path: str
    visual_review_class: str | None = None
    root_cause_layer: str | None = None
    root_cause_type: str | None = None
