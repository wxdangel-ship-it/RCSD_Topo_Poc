from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t02_junction_anchor.shared import LoadedFeature
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step2_step3_contract import (
    Stage4LocalContext,
    Stage4TopologySkeleton,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_contract import (
    Stage4EventInterpretationResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedNode,
    ParsedRoad,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class T04CaseSpec:
    case_id: str
    mainnodeid: str
    case_root: Path
    manifest: dict[str, Any]
    size_report: dict[str, Any]
    input_paths: dict[str, Path]


@dataclass(frozen=True)
class T04CaseBundle:
    case_spec: T04CaseSpec
    nodes: tuple[ParsedNode, ...]
    roads: tuple[ParsedRoad, ...]
    rcsd_roads: tuple[ParsedRoad, ...]
    rcsd_nodes: tuple[ParsedNode, ...]
    drivezone_features: tuple[LoadedFeature, ...]
    divstrip_features: tuple[LoadedFeature, ...]
    representative_node: ParsedNode
    group_nodes: tuple[ParsedNode, ...]


@dataclass(frozen=True)
class T04AdmissionResult:
    mainnodeid: str
    representative_node_id: str
    group_node_ids: tuple[str, ...]
    admitted: bool
    reason: str | None
    detail: str | None
    source_kind: int | None
    source_kind_2: int | None
    output_kind: int | None
    grade_2: int | None

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "scope": "t04_step1_admission",
            "mainnodeid": self.mainnodeid,
            "representative_node_id": self.representative_node_id,
            "group_node_ids": list(self.group_node_ids),
            "admitted": self.admitted,
            "reason": self.reason,
            "detail": self.detail,
            "source_kind": self.source_kind,
            "source_kind_2": self.source_kind_2,
            "output_kind": self.output_kind,
            "grade_2": self.grade_2,
        }


@dataclass(frozen=True)
class T04UnitContext:
    representative_node: ParsedNode
    group_nodes: tuple[ParsedNode, ...]
    admission: T04AdmissionResult
    local_context: Stage4LocalContext
    topology_skeleton: Stage4TopologySkeleton

    @property
    def mainnodeid(self) -> str:
        return self.admission.mainnodeid


@dataclass(frozen=True)
class T04EventUnitSpec:
    event_unit_id: str
    event_type: str
    split_mode: str
    representative_node_id: str
    selected_side_branch_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class T04UnitEnvelope:
    topology_scope: str
    unit_population_node_ids: tuple[str, ...]
    context_augmented_node_ids: tuple[str, ...]
    event_branch_ids: tuple[str, ...]
    boundary_branch_ids: tuple[str, ...]
    preferred_axis_branch_id: str | None
    branch_ids: tuple[str, ...] = ()
    main_branch_ids: tuple[str, ...] = ()
    input_branch_ids: tuple[str, ...] = ()
    output_branch_ids: tuple[str, ...] = ()
    branch_road_memberships: dict[str, tuple[str, ...]] = field(default_factory=dict)
    branch_bridge_node_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    degraded_scope_reason: str | None = None

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "topology_scope": self.topology_scope,
            "unit_population_node_ids": list(self.unit_population_node_ids),
            "context_augmented_node_ids": list(self.context_augmented_node_ids),
            "branch_ids": list(self.branch_ids),
            "main_branch_ids": list(self.main_branch_ids),
            "input_branch_ids": list(self.input_branch_ids),
            "output_branch_ids": list(self.output_branch_ids),
            "event_branch_ids": list(self.event_branch_ids),
            "boundary_branch_ids": list(self.boundary_branch_ids),
            "preferred_axis_branch_id": self.preferred_axis_branch_id,
            "branch_road_memberships": {
                str(branch_id): list(road_ids)
                for branch_id, road_ids in self.branch_road_memberships.items()
            },
            "branch_bridge_node_ids": {
                str(branch_id): list(node_ids)
                for branch_id, node_ids in self.branch_bridge_node_ids.items()
            },
            "degraded_scope_reason": self.degraded_scope_reason,
        }


@dataclass
class T04CandidateAuditEntry:
    candidate_id: str
    pool_rank: int
    priority_score: int
    selection_status: str
    decision_reason: str
    candidate_summary: dict[str, Any]
    review_state: str
    review_reasons: tuple[str, ...]
    evidence_source: str
    position_source: str
    reverse_tip_used: bool
    rcsd_consistency_result: str
    positive_rcsd_support_level: str
    positive_rcsd_consistency_level: str
    required_rcsd_node: str | None
    candidate_region_geometry: BaseGeometry | None
    fact_reference_point: BaseGeometry | None
    review_materialized_point: BaseGeometry | None
    localized_evidence_core_geometry: BaseGeometry | None
    selected_component_union_geometry: BaseGeometry | None

    def to_doc(self) -> dict[str, Any]:
        return _json_safe({
            "candidate_id": self.candidate_id,
            "pool_rank": self.pool_rank,
            "priority_score": self.priority_score,
            "selection_status": self.selection_status,
            "decision_reason": self.decision_reason,
            "candidate_summary": dict(self.candidate_summary),
            "review_state": self.review_state,
            "review_reasons": list(self.review_reasons),
            "evidence_source": self.evidence_source,
            "position_source": self.position_source,
            "reverse_tip_used": self.reverse_tip_used,
            "rcsd_consistency_result": self.rcsd_consistency_result,
            "positive_rcsd_support_level": self.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": self.positive_rcsd_consistency_level,
            "required_rcsd_node": self.required_rcsd_node,
        })


@dataclass
class T04EventUnitResult:
    spec: T04EventUnitSpec
    unit_context: T04UnitContext
    unit_envelope: T04UnitEnvelope
    interpretation: Stage4EventInterpretationResult
    review_state: str
    review_reasons: tuple[str, ...]
    evidence_source: str
    position_source: str
    reverse_tip_used: bool
    rcsd_consistency_result: str
    selected_component_union_geometry: BaseGeometry | None
    localized_evidence_core_geometry: BaseGeometry | None
    coarse_anchor_zone_geometry: BaseGeometry | None
    pair_local_region_geometry: BaseGeometry | None
    pair_local_structure_face_geometry: BaseGeometry | None
    pair_local_middle_geometry: BaseGeometry | None
    pair_local_throat_core_geometry: BaseGeometry | None
    selected_candidate_region: str | None
    selected_candidate_region_geometry: BaseGeometry | None
    selected_evidence_region_geometry: BaseGeometry | None
    fact_reference_point: BaseGeometry | None
    review_materialized_point: BaseGeometry | None
    pair_local_rcsd_scope_geometry: BaseGeometry | None
    first_hit_rcsd_road_geometry: BaseGeometry | None
    local_rcsd_unit_geometry: BaseGeometry | None
    positive_rcsd_geometry: BaseGeometry | None
    positive_rcsd_road_geometry: BaseGeometry | None
    positive_rcsd_node_geometry: BaseGeometry | None
    primary_main_rc_node_geometry: BaseGeometry | None
    required_rcsd_node_geometry: BaseGeometry | None
    selected_branch_ids: tuple[str, ...]
    selected_event_branch_ids: tuple[str, ...]
    selected_component_ids: tuple[str, ...]
    pair_local_rcsd_road_ids: tuple[str, ...]
    pair_local_rcsd_node_ids: tuple[str, ...]
    first_hit_rcsdroad_ids: tuple[str, ...]
    selected_rcsdroad_ids: tuple[str, ...]
    selected_rcsdnode_ids: tuple[str, ...]
    primary_main_rc_node_id: str | None
    local_rcsd_unit_id: str | None
    local_rcsd_unit_kind: str | None
    aggregated_rcsd_unit_id: str | None
    aggregated_rcsd_unit_ids: tuple[str, ...]
    positive_rcsd_present: bool
    positive_rcsd_present_reason: str
    axis_polarity_inverted: bool
    rcsd_selection_mode: str
    pair_local_rcsd_empty: bool
    positive_rcsd_support_level: str
    positive_rcsd_consistency_level: str
    required_rcsd_node: str | None
    required_rcsd_node_source: str | None
    event_axis_branch_id: str | None
    event_chosen_s_m: float | None
    pair_local_summary: dict[str, Any]
    selected_candidate_summary: dict[str, Any]
    positive_rcsd_audit: dict[str, Any] = field(default_factory=dict)
    selected_evidence_summary: dict[str, Any] = field(default_factory=dict)
    alternative_candidate_summaries: tuple[dict[str, Any], ...] = ()
    candidate_audit_entries: tuple[T04CandidateAuditEntry, ...] = ()
    extra_review_notes: tuple[str, ...] = ()
    source_png_path: str = ""
    compare_png_path: str = ""
    image_name: str = ""
    image_path: str = ""

    @property
    def selected_divstrip_geometry(self) -> BaseGeometry | None:
        return self.localized_evidence_core_geometry

    @property
    def event_anchor_geometry(self) -> BaseGeometry | None:
        return self.coarse_anchor_zone_geometry

    @property
    def event_reference_point(self) -> BaseGeometry | None:
        return self.review_materialized_point

    def all_review_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = [*self.review_reasons, *self.extra_review_notes]
        deduped: list[str] = []
        seen: set[str] = set()
        for reason in reasons:
            text = str(reason).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return tuple(deduped)

    @property
    def selected_evidence_state(self) -> str:
        candidate_id = str(self.selected_evidence_summary.get("candidate_id") or "").strip()
        return "found" if candidate_id else "none"

    def to_summary_doc(self) -> dict[str, Any]:
        return _json_safe({
            "event_unit_id": self.spec.event_unit_id,
            "event_type": self.spec.event_type,
            "split_mode": self.spec.split_mode,
            "representative_node_id": self.spec.representative_node_id,
            "unit_envelope": self.unit_envelope.to_status_doc(),
            "review_state": self.review_state,
            "review_reasons": list(self.all_review_reasons()),
            "evidence_source": self.evidence_source,
            "position_source": self.position_source,
            "reverse_tip_used": self.reverse_tip_used,
            "rcsd_consistency_result": self.rcsd_consistency_result,
            "pair_local_rcsd_road_ids": list(self.pair_local_rcsd_road_ids),
            "pair_local_rcsd_node_ids": list(self.pair_local_rcsd_node_ids),
            "first_hit_rcsdroad_ids": list(self.first_hit_rcsdroad_ids),
            "selected_rcsdroad_ids": list(self.selected_rcsdroad_ids),
            "selected_rcsdnode_ids": list(self.selected_rcsdnode_ids),
            "primary_main_rc_node": self.primary_main_rc_node_id,
            "local_rcsd_unit_id": self.local_rcsd_unit_id,
            "local_rcsd_unit_kind": self.local_rcsd_unit_kind,
            "aggregated_rcsd_unit_id": self.aggregated_rcsd_unit_id,
            "aggregated_rcsd_unit_ids": list(self.aggregated_rcsd_unit_ids),
            "positive_rcsd_present": self.positive_rcsd_present,
            "positive_rcsd_present_reason": self.positive_rcsd_present_reason,
            "axis_polarity_inverted": self.axis_polarity_inverted,
            "rcsd_selection_mode": self.rcsd_selection_mode,
            "pair_local_rcsd_empty": self.pair_local_rcsd_empty,
            "positive_rcsd_support_level": self.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": self.positive_rcsd_consistency_level,
            "required_rcsd_node": self.required_rcsd_node,
            "required_rcsd_node_source": self.required_rcsd_node_source,
            "selected_branch_ids": list(self.selected_branch_ids),
            "selected_event_branch_ids": list(self.selected_event_branch_ids),
            "selected_component_ids": list(self.selected_component_ids),
            "event_axis_branch_id": self.event_axis_branch_id,
            "event_chosen_s_m": self.event_chosen_s_m,
            "pair_local_summary": dict(self.pair_local_summary),
            "positive_rcsd_audit": _json_safe(dict(self.positive_rcsd_audit)),
            "selected_candidate_region": self.selected_candidate_region,
            "selected_evidence_state": self.selected_evidence_state,
            "selected_evidence": dict(self.selected_evidence_summary),
            "selected_candidate": dict(self.selected_candidate_summary),
            "alternative_candidates": [dict(item) for item in self.alternative_candidate_summaries],
            "candidate_audit_entries": [item.to_doc() for item in self.candidate_audit_entries],
            "interpretation": self.interpretation.to_audit_summary(),
        })


@dataclass
class T04CaseResult:
    case_spec: T04CaseSpec
    case_bundle: T04CaseBundle
    admission: T04AdmissionResult
    base_context: T04UnitContext
    event_units: list[T04EventUnitResult]
    case_review_state: str
    case_review_reasons: tuple[str, ...]

    def to_case_meta_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_spec.case_id,
            "mainnodeid": self.case_spec.mainnodeid,
            "case_root": str(self.case_spec.case_root),
            "representative_node_id": self.case_bundle.representative_node.node_id,
            "group_node_ids": [node.node_id for node in self.case_bundle.group_nodes],
            "input_paths": {key: str(value) for key, value in self.case_spec.input_paths.items()},
        }


@dataclass
class T04ReviewIndexRow:
    case_id: str
    event_unit_id: str
    event_type: str
    review_state: str
    evidence_source: str
    position_source: str
    reverse_tip_used: bool
    rcsd_consistency_result: str
    positive_rcsd_support_level: str = ""
    positive_rcsd_consistency_level: str = ""
    positive_rcsd_present: bool = False
    positive_rcsd_present_reason: str = ""
    pair_local_rcsd_empty: bool = False
    rcsd_selection_mode: str = ""
    local_rcsd_unit_kind: str = ""
    local_rcsd_unit_id: str = ""
    aggregated_rcsd_unit_id: str = ""
    aggregated_rcsd_unit_ids: str = ""
    axis_polarity_inverted: bool = False
    first_hit_rcsdroad_ids: str = ""
    selected_rcsdroad_ids: str = ""
    selected_rcsdnode_ids: str = ""
    primary_main_rc_node: str = ""
    required_rcsd_node: str = ""
    required_rcsd_node_source: str = ""
    selected_candidate_region: str = ""
    selected_evidence_state: str = ""
    selected_evidence_kind: str = ""
    primary_candidate_id: str = ""
    primary_candidate_layer: str = ""
    primary_candidate_layer_reason: str = ""
    axis_position_m: str = ""
    reference_distance_to_origin_m: str = ""
    has_alternative_candidates: bool = False
    candidate_pool_size: int = 0
    selected_reference_zone: str = ""
    selected_evidence_membership: str = ""
    better_alternative_signal: bool = False
    best_alternative_candidate_id: str = ""
    best_alternative_layer: str = ""
    best_alternative_reason: str = ""
    shared_object_signal: bool = False
    shared_region_signal: bool = False
    shared_point_signal: bool = False
    conflict_signal_level: str = ""
    related_unit_ids: str = ""
    key_reason: str = ""
    needs_manual_review_focus: bool = False
    focus_reasons: str = ""
    ownership_signature: str = ""
    upper_evidence_object_id: str = ""
    local_region_id: str = ""
    point_signature: str = ""
    image_name: str = ""
    image_path: str = ""
    compare_image_name: str = ""
    compare_image_path: str = ""
    sequence_no: int = 0
    case_overview_path: str = ""

    def to_csv_row(self) -> dict[str, Any]:
        return {
            "sequence_no": self.sequence_no,
            "case_id": self.case_id,
            "event_unit_id": self.event_unit_id,
            "event_type": self.event_type,
            "review_state": self.review_state,
            "evidence_source": self.evidence_source,
            "position_source": self.position_source,
            "reverse_tip_used": int(self.reverse_tip_used),
            "rcsd_consistency_result": self.rcsd_consistency_result,
            "positive_rcsd_support_level": self.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": self.positive_rcsd_consistency_level,
            "positive_rcsd_present": int(self.positive_rcsd_present),
            "positive_rcsd_present_reason": self.positive_rcsd_present_reason,
            "pair_local_rcsd_empty": int(self.pair_local_rcsd_empty),
            "rcsd_selection_mode": self.rcsd_selection_mode,
            "local_rcsd_unit_kind": self.local_rcsd_unit_kind,
            "local_rcsd_unit_id": self.local_rcsd_unit_id,
            "aggregated_rcsd_unit_id": self.aggregated_rcsd_unit_id,
            "aggregated_rcsd_unit_ids": self.aggregated_rcsd_unit_ids,
            "axis_polarity_inverted": int(self.axis_polarity_inverted),
            "first_hit_rcsdroad_ids": self.first_hit_rcsdroad_ids,
            "selected_rcsdroad_ids": self.selected_rcsdroad_ids,
            "selected_rcsdnode_ids": self.selected_rcsdnode_ids,
            "primary_main_rc_node": self.primary_main_rc_node,
            "required_rcsd_node": self.required_rcsd_node,
            "required_rcsd_node_source": self.required_rcsd_node_source,
            "selected_candidate_region": self.selected_candidate_region,
            "selected_evidence_state": self.selected_evidence_state,
            "selected_evidence_kind": self.selected_evidence_kind,
            "primary_candidate_id": self.primary_candidate_id,
            "primary_candidate_layer": self.primary_candidate_layer,
            "primary_candidate_layer_reason": self.primary_candidate_layer_reason,
            "axis_position_m": self.axis_position_m,
            "reference_distance_to_origin_m": self.reference_distance_to_origin_m,
            "has_alternative_candidates": int(self.has_alternative_candidates),
            "candidate_pool_size": self.candidate_pool_size,
            "selected_reference_zone": self.selected_reference_zone,
            "selected_evidence_membership": self.selected_evidence_membership,
            "better_alternative_signal": int(self.better_alternative_signal),
            "best_alternative_candidate_id": self.best_alternative_candidate_id,
            "best_alternative_layer": self.best_alternative_layer,
            "best_alternative_reason": self.best_alternative_reason,
            "shared_object_signal": int(self.shared_object_signal),
            "shared_region_signal": int(self.shared_region_signal),
            "shared_point_signal": int(self.shared_point_signal),
            "conflict_signal_level": self.conflict_signal_level,
            "related_unit_ids": self.related_unit_ids,
            "key_reason": self.key_reason,
            "needs_manual_review_focus": int(self.needs_manual_review_focus),
            "focus_reasons": self.focus_reasons,
            "ownership_signature": self.ownership_signature,
            "upper_evidence_object_id": self.upper_evidence_object_id,
            "local_region_id": self.local_region_id,
            "point_signature": self.point_signature,
            "image_name": self.image_name,
            "image_path": self.image_path,
            "compare_image_name": self.compare_image_name,
            "compare_image_path": self.compare_image_path,
            "case_overview_path": self.case_overview_path,
        }
