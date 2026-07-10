from __future__ import annotations

from dataclasses import fields, is_dataclass
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from shapely.geometry.base import BaseGeometry


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RestorationStrategy(_StrEnum):
    RESTRICTION_ONLY_V1 = "restriction_only_v1"
    MULTI_EVIDENCE_V2 = "multi_evidence_v2"


class DecisionStatus(_StrEnum):
    PROHIBITED = "prohibited"
    SUPPORTED = "supported"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    CONFLICT = "conflict"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    UNVERIFIED = "unverified"


class DecisionSource(_StrEnum):
    RESTRICTION = "restriction"
    LANEINFO = "laneinfo"
    SPECIAL_CARRIER = "special_carrier"
    TOPOLOGY = "topology"
    NONE = "none"


class RuleScope(_StrEnum):
    ARM_TO_ARM = "arm_to_arm"
    ROAD_TO_ROAD = "road_to_road"
    ROAD_TO_ARM = "road_to_arm"
    ROAD_DIRECTION_EXCLUSION = "road_direction_exclusion"
    SPECIAL_CARRIER = "special_carrier"
    CORE_JUNCTION_DISPLACEMENT = "core_junction_displacement"


class EvidencePriority(_StrEnum):
    RESTRICTION = "restriction"
    LANEINFO = "laneinfo"
    SPECIAL_CARRIER = "special_carrier"


class VerificationStatus(_StrEnum):
    VERIFIED_SWSD = "verified_swsd"
    VERIFIED_FRCSD = "verified_frcsd"
    UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO = "unverified_due_to_missing_frcsd_laneinfo"
    NOT_REQUIRED = "not_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


def normalize_restoration_strategy(value: str | RestorationStrategy) -> RestorationStrategy:
    if isinstance(value, RestorationStrategy):
        return value
    try:
        return RestorationStrategy(str(value).strip())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in RestorationStrategy)
        raise ValueError(f"Unsupported T09 strategy_version {value!r}; expected one of: {allowed}") from exc


class MovementApplicability(_StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    TOPOLOGY_IMPOSSIBLE = "topology_impossible"
    DIRECTION_INCOMPATIBLE = "direction_incompatible"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class ProhibitionStatus(_StrEnum):
    FULLY_PROHIBITED = "fully_prohibited"
    PARTIALLY_PROHIBITED = "partially_prohibited"
    CORE_JUNCTION_DISPLACED = "core_junction_displaced"
    NO_PROHIBITION_EVIDENCE = "no_prohibition_evidence"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_A_TRAFFIC_RULE = "not_a_traffic_rule"


class ProhibitionReason(_StrEnum):
    EXPLICIT_RESTRICTION = "explicit_restriction"
    COMPLETE_ARROW_EXCLUSION = "complete_arrow_exclusion"
    SPECIAL_CARRIER_DISPLACEMENT = "special_carrier_displacement"
    TOPOLOGY_NOT_APPLICABLE = "topology_not_applicable"
    DIRECTION_NOT_APPLICABLE = "direction_not_applicable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class InferenceLevel(_StrEnum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    WEAK_DERIVED = "weak_derived"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class EvidenceType(_StrEnum):
    RESTRICTION = "restriction"
    ARROW = "arrow"
    COMPLETE_ARROW_EXCLUSION = "complete_arrow_exclusion"
    SPECIAL_CARRIER = "special_carrier"
    TOPOLOGY_NOT_APPLICABLE = "topology_not_applicable"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class OverrideChainEntry:
    winner_evidence_id: str
    winner_source: DecisionSource
    overridden_evidence_id: str
    overridden_source: DecisionSource
    reason: str
    decision_status: DecisionStatus
    risk_flags: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class RoadPair:
    from_road_id: str
    to_road_id: str


@dataclass(frozen=True)
class EvidenceProvenance:
    source_type: str
    source_id: str
    matched_object_ids: tuple[str, ...] = tuple()
    match_method: str = ""
    field_audit: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class T09SwsdArm:
    junction_id: str
    arm_id: str
    member_node_ids: tuple[str, ...] = tuple()
    internal_road_ids: tuple[str, ...] = tuple()
    seed_road_ids: tuple[str, ...] = tuple()
    connector_road_ids: tuple[str, ...] = tuple()
    segment_ids: tuple[str, ...] = tuple()
    t01_segment_ids: tuple[str, ...] = tuple()
    segment_membership_status: str = "missing"
    inbound_road_ids: tuple[str, ...] = tuple()
    outbound_road_ids: tuple[str, ...] = tuple()
    bidirectional_road_ids: tuple[str, ...] = tuple()
    approach_road_ids: tuple[str, ...] = tuple()
    exit_road_ids: tuple[str, ...] = tuple()
    trunk_road_ids: tuple[str, ...] = tuple()
    parallel_branch_road_ids: tuple[str, ...] = tuple()
    advance_left_road_ids: tuple[str, ...] = tuple()
    advance_right_road_ids: tuple[str, ...] = tuple()
    auxiliary_right_turn_road_ids: tuple[str, ...] = tuple()
    advance_right_turn_relation_ids: tuple[str, ...] = tuple()
    angle_deg: float | None = None
    terminal_node_id: str | None = None
    terminal_kind: str | None = None
    build_status: str = "built"
    risk_flags: tuple[str, ...] = tuple()
    audit_refs: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class T09ArmMovement:
    junction_id: str
    movement_id: str
    from_arm_id: str
    to_arm_id: str
    movement_type: str
    movement_applicability: MovementApplicability = MovementApplicability.APPLICABLE
    candidate_road_pair_count: int = 0
    carrier_universe_status: str = "not_evaluated"
    prohibition_status: ProhibitionStatus = ProhibitionStatus.UNKNOWN
    prohibition_reason: ProhibitionReason = ProhibitionReason.INSUFFICIENT_EVIDENCE
    prohibition_confidence: float = 0.0
    restriction_coverage: str = "unknown"
    partial_basis: str = "not_applicable"
    remaining_restriction_status: str = "unknown"
    arrow_direction_status: str = "no_arrow_evidence"
    arrow_lane_summary: dict[str, Any] = field(default_factory=dict)
    advance_left_status: str = "not_applicable"
    advance_right_status: str = "not_applicable"
    evidence_item_ids: tuple[str, ...] = tuple()
    risk_flags: tuple[str, ...] = tuple()
    carrier_road_pairs: tuple[RoadPair, ...] = tuple()
    strategy_version: RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1
    decision_status: DecisionStatus = DecisionStatus.UNKNOWN
    decision_source: DecisionSource = DecisionSource.NONE
    decision_scope: RuleScope | None = None
    evidence_priority: EvidencePriority | None = None
    verification_status: VerificationStatus = VerificationStatus.NOT_REQUIRED
    override_chain: tuple[OverrideChainEntry, ...] = tuple()


@dataclass(frozen=True)
class T09EvidenceItem:
    evidence_id: str
    evidence_type: EvidenceType
    junction_id: str
    movement_id: str | None
    road_pair: RoadPair | None
    evidence_status: str
    prohibition_reason: ProhibitionReason
    inference_level: InferenceLevel
    confidence: float
    provenance: EvidenceProvenance
    supports_prohibition: bool = False
    risk_flags: tuple[str, ...] = tuple()
    decision_status: DecisionStatus = DecisionStatus.UNKNOWN
    decision_scope: RuleScope | None = None
    evidence_priority: EvidencePriority | None = None
    verification_status: VerificationStatus = VerificationStatus.NOT_REQUIRED
    from_road_ids: tuple[str, ...] = tuple()
    to_road_ids: tuple[str, ...] = tuple()
    condition_type: str | None = None
    condition_payload: dict[str, Any] = field(default_factory=dict)
    condition_identity: str = ""
    condition_semantics_status: str = "not_applicable"


@dataclass(frozen=True)
class T09RestoredFieldRule:
    junction_id: str
    from_arm_id: str
    to_arm_id: str
    movement_type: str
    field_rule_status: ProhibitionStatus
    rule_scope: str
    supporting_evidence_ids: tuple[str, ...] = tuple()
    conflicting_evidence_ids: tuple[str, ...] = tuple()
    inference_level: InferenceLevel = InferenceLevel.UNKNOWN
    confidence: float = 0.0
    risk_flags: tuple[str, ...] = tuple()
    rule_id: str = ""
    movement_id: str = ""
    strategy_version: RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1
    decision_status: DecisionStatus = DecisionStatus.UNKNOWN
    decision_source: DecisionSource = DecisionSource.NONE
    decision_scope: RuleScope | None = None
    evidence_priority: EvidencePriority | None = None
    verification_status: VerificationStatus = VerificationStatus.NOT_REQUIRED
    override_chain: tuple[OverrideChainEntry, ...] = tuple()
    from_road_ids: tuple[str, ...] = tuple()
    to_road_ids: tuple[str, ...] = tuple()
    road_pairs: tuple[RoadPair, ...] = tuple()
    source_restriction_ids: tuple[str, ...] = tuple()
    condition_type: str | None = None
    condition_payload: tuple[dict[str, Any], ...] = tuple()
    condition_identity: str = ""
    condition_semantics_status: str = "not_applicable"
    scope_promotion_status: str = "not_evaluated"
    scope_promotion_reason: str = ""
    scope_promotion_audit: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RestorationResult:
    arms: tuple[T09SwsdArm, ...]
    movements: tuple[T09ArmMovement, ...]
    evidence_items: tuple[T09EvidenceItem, ...]
    restored_rules: tuple[T09RestoredFieldRule, ...]
    summary: dict[str, Any]


@dataclass(frozen=True)
class SWSDRoadInput:
    road_id: str
    snodeid: str
    enodeid: str
    direction: int
    kind: str | None = None
    formway: int = 0
    segment_ids: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class SWSDSegmentInput:
    segment_id: str
    pair_nodes: tuple[str, ...] = tuple()
    junc_nodes: tuple[str, ...] = tuple()
    road_ids: tuple[str, ...] = tuple()
    sgrade: str | None = None


@dataclass(frozen=True)
class RestrictionInput:
    restriction_id: str
    in_link_id: str
    out_link_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    geometry: BaseGeometry | None = None
    condition_type: str | None = None
    condition_payload: dict[str, Any] = field(default_factory=dict)
    condition_identity: str = ""
    condition_semantics_status: str = "unknown"


@dataclass(frozen=True)
class ArrowInput:
    arrow_id: str
    road_id: str
    lane_codes: tuple[str, ...]
    direction_matched: bool = True
    lane_sequence_complete: bool = True
    geometry_match_method: str = "road_id"
    properties: dict[str, Any] = field(default_factory=dict)
    source_feature_id: str | None = None
    geometry: BaseGeometry | None = None
    lane_dir: int | None = None
    road_direction: int | None = None
    seq_start: int | None = None
    seq_end: int | None = None
    source_arrow_dir: str | None = None
    sequence_metadata_status: str = "not_provided"


@dataclass(frozen=True)
class RoadAttributes:
    road_id: str
    kind: str | None = None
    formway: int = 0


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, BaseGeometry):
        return value.wkt
    return value
