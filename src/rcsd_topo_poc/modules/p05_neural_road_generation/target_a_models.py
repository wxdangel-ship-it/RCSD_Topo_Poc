from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


TARGET_A_SCHEMA_VERSION = "p05-target-a-joint-roadgraph-v1"


class _TextEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AnchorStatus(_TextEnum):
    SUCCESS = "SUCCESS"
    NO_EVIDENCE = "NO_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    ABSTAIN = "ABSTAIN"
    UNSUPPORTED_COMPOSITE_ANCHOR = "UNSUPPORTED_COMPOSITE_ANCHOR"


class SegmentDecision(_TextEnum):
    USE_RCSD = "USE_RCSD"
    KEEP_SWSD = "KEEP_SWSD"
    T06_MAIN_RCSD_ATTACHED_SWSD = "T06_MAIN_RCSD_ATTACHED_SWSD"
    ADVANCE_RIGHT_MIXED_SPLICE = "ADVANCE_RIGHT_MIXED_SPLICE"
    ABSTAIN = "ABSTAIN"


class RoadSource(_TextEnum):
    RCSD = "RCSD"
    SWSD = "SWSD"


class RoadRole(_TextEnum):
    MAIN = "MAIN"
    INTERNAL_CONNECTOR = "INTERNAL_CONNECTOR"
    ATTACHED_SWSD = "ATTACHED_SWSD"
    ADVANCE_RIGHT = "ADVANCE_RIGHT"
    JUNCTION_CONNECTIVITY = "JUNCTION_CONNECTIVITY"


class FallbackScope(_TextEnum):
    NONE = "NONE"
    SEGMENT = "SEGMENT"
    JUNCTION = "JUNCTION"


@dataclass(frozen=True)
class TargetAConfig:
    feature_dim: int = 64
    hidden_dim: int = 352
    num_heads: int = 8
    graph_layers: int = 5
    set_layers: int = 2
    feedforward_dim: int = 1_408
    dropout: float = 0.10
    anchor_status_count: int = len(AnchorStatus)
    fallback_scope_count: int = len(FallbackScope)
    clue_class_count: int = 2
    min_parameter_count: int = 10_000_000
    max_parameter_count: int = 20_000_000
    learning_rate: float = 2e-4
    weight_decay: float = 2e-4
    preferred_loss_weight: float = 0.10
    anchor_status_class_weights: tuple[float, ...] = ()
    learned_anchor_gate: bool = False
    anchor_gate_class_weights: tuple[float, ...] = ()
    anchor_gate_loss_weight: float = 1.0
    anchor_type_loss_weight: float = 1.0
    anchor_gate_pass_threshold: float = 0.5
    anchor_status_use_selected_candidate: bool = False
    hierarchical_anchor_decoder: bool = False
    anchor_type_hard_lock: bool = True
    anchor_type_prior_weight: float = 1.0
    anchor_raw_evidence_type_decoder: bool = False
    anchor_raw_evidence_candidate_decoder: bool = False
    structured_anchor_object_decoder: bool = False
    compositional_anchor_object_decoder: bool = False
    compositional_anchor_candidate_residual: bool = False
    cardinality_conditioned_anchor_decoder: bool = False
    anchor_cardinality_hard_lock: bool = True
    anchor_cardinality_prior_weight: float = 1.0
    anchor_cardinality_count: int = 128
    anchor_candidate_validity_loss_weight: float = 0.50
    anchor_member_loss_weight: float = 0.0
    anchor_structural_evidence_encoder: bool = False
    anchor_structural_candidate_context_fusion: bool = True
    anchor_structural_member_local_encoder: bool = False
    anchor_structural_candidate_residual_context: bool = False
    ordinary_oof_anchor_condition_encoder: bool = False
    hierarchical_ordinary_plan_decoder: bool = False
    ordinary_plan_member_encoder: bool = False
    ordinary_plan_member_within_decision_only: bool = False
    ordinary_plan_arm_encoder: bool = False
    ordinary_decision_loss_weight: float = 0.0
    ordinary_decision_validity_loss_weight: float = 0.0
    separate_ordinary_decision_validity_head: bool = False
    ordinary_candidate_validity_loss_weight: float = 0.0
    separate_ordinary_candidate_validity_head: bool = False
    max_epochs: int = 80
    patience: int = 10
    torch_num_threads: int = 2
    stop_gradient_between_stages: bool = True

    def validate(self) -> None:
        integer_values = (
            self.feature_dim,
            self.hidden_dim,
            self.num_heads,
            self.graph_layers,
            self.set_layers,
            self.feedforward_dim,
            self.anchor_status_count,
            self.fallback_scope_count,
            self.clue_class_count,
            self.min_parameter_count,
            self.max_parameter_count,
            self.max_epochs,
            self.patience,
            self.torch_num_threads,
            self.anchor_cardinality_count,
        )
        if min(integer_values) <= 0:
            raise ValueError("Target A dimensions and limits must be positive")
        if self.hidden_dim % self.num_heads:
            raise ValueError("hidden_dim must be divisible by num_heads")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.min_parameter_count > self.max_parameter_count:
            raise ValueError("parameter count gate is invalid")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("optimizer configuration is invalid")
        if self.preferred_loss_weight < 0:
            raise ValueError("preferred loss weight must not be negative")
        if self.anchor_gate_loss_weight < 0:
            raise ValueError("anchor gate loss weight must not be negative")
        if self.anchor_type_loss_weight < 0:
            raise ValueError("anchor type loss weight must not be negative")
        if self.anchor_type_prior_weight < 0:
            raise ValueError("anchor type prior weight must not be negative")
        if self.anchor_cardinality_prior_weight < 0:
            raise ValueError(
                "anchor cardinality prior weight must not be negative"
            )
        if not 0.0 < self.anchor_gate_pass_threshold < 1.0:
            raise ValueError("anchor gate pass threshold must be in (0, 1)")
        if self.anchor_candidate_validity_loss_weight < 0:
            raise ValueError(
                "anchor candidate validity loss weight must not be negative"
            )
        if self.ordinary_candidate_validity_loss_weight < 0:
            raise ValueError(
                "ordinary candidate validity loss weight must not be negative"
            )
        if (
            self.separate_ordinary_candidate_validity_head
            and self.ordinary_candidate_validity_loss_weight <= 0
        ):
            raise ValueError(
                "separate ordinary candidate validity head requires a "
                "positive validity loss weight"
            )
        if self.ordinary_decision_loss_weight < 0:
            raise ValueError(
                "ordinary decision loss weight must not be negative"
            )
        if self.ordinary_decision_validity_loss_weight < 0:
            raise ValueError(
                "ordinary decision validity loss weight must not be negative"
            )
        if (
            self.separate_ordinary_decision_validity_head
            and self.ordinary_decision_validity_loss_weight <= 0
        ):
            raise ValueError(
                "separate ordinary decision validity head requires a "
                "positive validity loss weight"
            )
        if (
            self.ordinary_decision_validity_loss_weight > 0
            and not self.separate_ordinary_decision_validity_head
        ):
            raise ValueError(
                "ordinary decision validity loss requires its separate head"
            )
        if (
            (
                self.ordinary_decision_loss_weight
                or self.ordinary_decision_validity_loss_weight
            )
            and not self.hierarchical_ordinary_plan_decoder
        ):
            raise ValueError(
                "ordinary decision losses require hierarchical decoding"
            )
        if (
            self.ordinary_plan_member_within_decision_only
            and (
                not self.ordinary_plan_member_encoder
                or not self.hierarchical_ordinary_plan_decoder
            )
        ):
            raise ValueError(
                "decision-local ordinary member evidence requires the member "
                "encoder and hierarchical decoding"
            )
        if (
            self.ordinary_plan_arm_encoder
            and not self.hierarchical_ordinary_plan_decoder
        ):
            raise ValueError(
                "ordinary arm matching requires hierarchical decoding"
            )
        if self.anchor_member_loss_weight < 0:
            raise ValueError("anchor member loss weight must not be negative")
        if self.anchor_status_class_weights and (
            len(self.anchor_status_class_weights) != self.anchor_status_count
            or min(self.anchor_status_class_weights) < 0
            or not any(self.anchor_status_class_weights)
        ):
            raise ValueError("anchor status class weights are invalid")
        if self.anchor_gate_class_weights and (
            len(self.anchor_gate_class_weights) != 2
            or min(self.anchor_gate_class_weights) < 0
            or not any(self.anchor_gate_class_weights)
        ):
            raise ValueError("anchor gate class weights are invalid")
        if not self.learned_anchor_gate and self.anchor_gate_class_weights:
            raise ValueError("anchor gate class weights require learned gating")
        if (
            self.hierarchical_anchor_decoder
            and self.anchor_status_use_selected_candidate
        ):
            raise ValueError(
                "hierarchical anchor evidence must not observe selected candidates"
            )
        if (
            self.anchor_raw_evidence_type_decoder
            and self.anchor_raw_evidence_candidate_decoder
        ):
            raise ValueError(
                "raw anchor type and candidate decoders are mutually exclusive"
            )
        if (
            (
                self.anchor_raw_evidence_type_decoder
                or self.anchor_raw_evidence_candidate_decoder
            )
            and not self.hierarchical_anchor_decoder
        ):
            raise ValueError(
                "raw anchor evidence decoding requires hierarchical anchoring"
            )
        if (
            self.structured_anchor_object_decoder
            and not self.hierarchical_anchor_decoder
        ):
            raise ValueError(
                "structured anchor object decoder requires hierarchical anchoring"
            )
        if (
            self.compositional_anchor_object_decoder
            and not self.hierarchical_anchor_decoder
        ):
            raise ValueError(
                "compositional anchor object decoder requires hierarchical anchoring"
            )
        if (
            self.compositional_anchor_object_decoder
            and self.structured_anchor_object_decoder
        ):
            raise ValueError(
                "compositional and pairwise structured anchor decoders conflict"
            )
        if (
            self.compositional_anchor_candidate_residual
            and not self.compositional_anchor_object_decoder
        ):
            raise ValueError(
                "anchor composition residual requires compositional decoding"
            )
        if (
            self.anchor_member_loss_weight
            and not self.compositional_anchor_object_decoder
        ):
            raise ValueError(
                "anchor member loss requires compositional decoding"
            )
        if (
            self.anchor_structural_evidence_encoder
            and not self.compositional_anchor_object_decoder
        ):
            raise ValueError(
                "anchor structural evidence requires compositional decoding"
            )
        if (
            self.anchor_structural_member_local_encoder
            and not self.anchor_structural_evidence_encoder
        ):
            raise ValueError(
                "anchor member-local encoder requires structural evidence"
            )
        if (
            self.anchor_structural_candidate_residual_context
            and (
                not self.anchor_structural_evidence_encoder
                or not self.compositional_anchor_candidate_residual
            )
        ):
            raise ValueError(
                "anchor candidate structural residual context requires "
                "structural evidence and a composition residual"
            )
        if (
            self.cardinality_conditioned_anchor_decoder
            and not self.hierarchical_anchor_decoder
        ):
            raise ValueError(
                "anchor cardinality conditioning requires hierarchical anchoring"
            )


@dataclass(frozen=True)
class RoadUse:
    source_kind: RoadSource
    source_road_id: str
    role: RoadRole
    owner_segment_id: str
    direction: int
    piece_id: str = ""
    split_position_m: float | None = None

    @property
    def ownership_key(self) -> str:
        return self.piece_id or self.source_road_id

    def validate(self, segment_id: str) -> None:
        if not self.source_road_id:
            raise ValueError("RoadUse source_road_id must not be empty")
        if self.role is RoadRole.JUNCTION_CONNECTIVITY:
            if self.owner_segment_id:
                raise ValueError("Junction connectivity Road must not have a Segment owner")
        elif self.owner_segment_id != segment_id:
            raise ValueError("owned Road must use the plan Segment as owner")
        if self.direction not in {0, 1, 2, 3}:
            raise ValueError("Road direction is outside the formal enum")
        if self.split_position_m is not None and self.split_position_m < 0:
            raise ValueError("Road split position must not be negative")


@dataclass(frozen=True)
class Attachment:
    child_segment_id: str
    road_piece_id: str
    position_m: float

    def validate(self) -> None:
        if not self.child_segment_id or not self.road_piece_id:
            raise ValueError("attachment references must not be empty")
        if self.position_m < 0:
            raise ValueError("attachment position must not be negative")


@dataclass(frozen=True)
class PlanCandidate:
    plan_id: str
    segment_id: str
    decision: SegmentDecision
    roads: tuple[RoadUse, ...]
    source_access_road_id: str
    target_access_road_id: str
    required_anchor_ids: tuple[str, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    node_recipes: tuple[Mapping[str, Any], ...] = ()
    hard_valid: bool = True
    unsupported_reason: str = ""
    source_condition: tuple[RoadSource, RoadSource] | None = None

    def validate(self, *, advance_right: bool = False) -> None:
        if not self.plan_id or not self.segment_id:
            raise ValueError("plan and Segment ids must not be empty")
        for road in self.roads:
            road.validate(self.segment_id)
        for attachment in self.attachments:
            attachment.validate()
        roles = {road.role for road in self.roads}
        sources = {
            road.source_kind
            for road in self.roads
            if road.role in {RoadRole.MAIN, RoadRole.ADVANCE_RIGHT}
        }
        if self.decision is SegmentDecision.KEEP_SWSD:
            if not self.roads or any(road.source_kind is not RoadSource.SWSD for road in self.roads):
                raise ValueError("KEEP_SWSD must contain a complete SWSD Road plan")
        elif self.decision is SegmentDecision.USE_RCSD:
            if RoadSource.RCSD not in sources:
                raise ValueError("USE_RCSD must contain RCSD MAIN Road")
            if any(road.source_kind is RoadSource.SWSD for road in self.roads):
                raise ValueError("USE_RCSD must not retain any SWSD Road")
        elif self.decision is SegmentDecision.T06_MAIN_RCSD_ATTACHED_SWSD:
            if RoadSource.RCSD not in sources:
                raise ValueError("T06 mixed plan requires RCSD MAIN Road")
            attached_swsd = [
                road
                for road in self.roads
                if road.source_kind is RoadSource.SWSD
            ]
            if not attached_swsd or any(
                road.role is not RoadRole.ATTACHED_SWSD
                for road in attached_swsd
            ):
                raise ValueError(
                    "T06 mixed plan only permits explicit attached/side SWSD Roads"
                )
        elif self.decision is SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE:
            if not advance_right:
                raise ValueError(
                    "AdvanceRight mixed splice cannot describe an ordinary Segment"
                )
            if {road.source_kind for road in self.roads} != {
                RoadSource.RCSD,
                RoadSource.SWSD,
            }:
                raise ValueError(
                    "AdvanceRight mixed splice requires both RCSD and SWSD sources"
                )
            if not self.roads or any(
                road.role is not RoadRole.ADVANCE_RIGHT
                or road.owner_segment_id != self.segment_id
                for road in self.roads
            ):
                raise ValueError(
                    "AdvanceRight mixed splice only contains owned ADVANCE_RIGHT Roads"
                )
        elif self.roads:
            raise ValueError("ABSTAIN must not hide a Road plan")
        if RoadRole.INTERNAL_CONNECTOR in roles and RoadSource.RCSD not in sources:
            raise ValueError("internal connector tree cannot prove a main replacement")
        if advance_right:
            if self.decision is SegmentDecision.USE_RCSD and RoadRole.ADVANCE_RIGHT not in roles:
                raise ValueError("AdvanceRight USE_RCSD plan requires an independent Road")
            if self.source_condition is None:
                raise ValueError("AdvanceRight plan must declare both locked source conditions")
            expected_decision = {
                (RoadSource.RCSD, RoadSource.RCSD): SegmentDecision.USE_RCSD,
                (RoadSource.SWSD, RoadSource.SWSD): SegmentDecision.KEEP_SWSD,
                (
                    RoadSource.RCSD,
                    RoadSource.SWSD,
                ): SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE,
                (
                    RoadSource.SWSD,
                    RoadSource.RCSD,
                ): SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE,
            }.get(self.source_condition)
            if expected_decision is None or self.decision is not expected_decision:
                raise ValueError(
                    "AdvanceRight decision differs from its locked source condition"
                )


@dataclass(frozen=True)
class AnchorDecision:
    anchor_id: str
    status: AnchorStatus
    selected_candidate_id: str = ""
    selected_rcsd_junction_ids: tuple[str, ...] = ()
    selected_rcsd_road_ids: tuple[str, ...] = ()
    break_recipes: tuple[Mapping[str, Any], ...] = ()
    confidence: float = 0.0
    clue: bool = False
    affected_object_ids: tuple[str, ...] = ()

    @property
    def locked_success(self) -> bool:
        return self.status is AnchorStatus.SUCCESS and bool(self.selected_candidate_id)


@dataclass(frozen=True)
class ScoredPlan:
    plan: PlanCandidate
    score: float


@dataclass(frozen=True)
class SegmentPlanDecision:
    segment_id: str
    selected_plan: PlanCandidate
    score: float
    fallback_scope: FallbackScope = FallbackScope.NONE
    reason: str = ""

    @property
    def automatic(self) -> bool:
        return (
            self.fallback_scope is FallbackScope.NONE
            and self.selected_plan.decision is not SegmentDecision.ABSTAIN
        )


@dataclass(frozen=True)
class DecisionLedger:
    input_manifest_sha256: str
    model_checkpoint_sha256: str
    anchor_decisions: tuple[AnchorDecision, ...]
    ordinary_decisions: tuple[SegmentPlanDecision, ...]
    advance_right_decisions: tuple[SegmentPlanDecision, ...]
    clue_object_ids: tuple[str, ...]
    skeleton_mutation_count: int = 0
    silent_fix: bool = False
    schema_version: str = TARGET_A_SCHEMA_VERSION


@dataclass(frozen=True)
class TargetARunConfig:
    poc_data_root: Path
    full_baseline_root: Path
    six_case_baseline_root: Path
    output_root: Path
    run_id: str
    model: TargetAConfig = field(default_factory=TargetAConfig)
    excluded_case_keys: tuple[str, ...] = ("T10-Error:1213556_1263661",)
    folds: int = 5
    seeds: tuple[int, ...] = (17, 29, 43)
    strict_hashes: bool = True

    def validate(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.folds < 2:
            raise ValueError("Target A requires at least two Case folds")
        if len(self.seeds) != len(set(self.seeds)) or not self.seeds:
            raise ValueError("Target A seeds must be nonempty and unique")
        if len(self.excluded_case_keys) != len(set(self.excluded_case_keys)):
            raise ValueError("Target A exclusions must be unique")
        self.model.validate()


__all__ = [
    "AnchorDecision",
    "AnchorStatus",
    "Attachment",
    "DecisionLedger",
    "FallbackScope",
    "PlanCandidate",
    "RoadRole",
    "RoadSource",
    "RoadUse",
    "ScoredPlan",
    "SegmentDecision",
    "SegmentPlanDecision",
    "TARGET_A_SCHEMA_VERSION",
    "TargetAConfig",
    "TargetARunConfig",
]
