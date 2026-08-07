from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


GEOMETRY_TOKEN_DIM = 21
TOPOLOGY_EDGE_DIM = 8


class JunctionPredictionError(ValueError):
    """Raised when a batch, candidate, or complete prediction is invalid."""


class Step1DriveZoneState(str, Enum):
    EVIDENCE = "EVIDENCE"
    NO_EVIDENCE = "NO_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    ABSTAIN = "ABSTAIN"


class SurfaceMode(str, Enum):
    EXISTING_RCSD_INTERSECTION = "EXISTING_RCSD_INTERSECTION"
    VIRTUAL_SURFACE = "VIRTUAL_SURFACE"
    NO_VALID_SURFACE = "NO_VALID_SURFACE"
    AMBIGUOUS = "AMBIGUOUS"
    ABSTAIN = "ABSTAIN"


class AnchorState(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RCSD_EVIDENCE = "NO_RCSD_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    ABSTAIN = "ABSTAIN"


class AnchorNodeKind(str, Enum):
    SOURCE_RCSD_NODE = "SOURCE_RCSD_NODE"
    ROAD_BREAK_POINT = "ROAD_BREAK_POINT"


class QualityState(str, Enum):
    NORMAL = "NORMAL"
    NO_EVIDENCE = "NO_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    REVIEW = "REVIEW"
    UNTRAINED = "UNTRAINED"


@dataclass(frozen=True)
class VirtualSurfaceRecipe:
    recipe_type: str
    parameters: tuple[tuple[str, float], ...]

    def validate(self) -> None:
        if not self.recipe_type.strip():
            raise JunctionPredictionError("virtual surface recipe_type is blank")
        names = tuple(name for name, _ in self.parameters)
        if len(set(names)) != len(names) or any(not name.strip() for name in names):
            raise JunctionPredictionError("virtual surface parameters are invalid")
        if not all(math.isfinite(float(value)) for _, value in self.parameters):
            raise JunctionPredictionError("virtual surface parameter is not finite")


@dataclass(frozen=True)
class SurfacePlan:
    mode: SurfaceMode
    selected_rcsdintersection_refs: tuple[ObjectRef, ...] = ()
    virtual_member_refs: tuple[ObjectRef, ...] = ()
    virtual_surface_recipe: VirtualSurfaceRecipe | None = None

    def validate(self) -> None:
        if len(set(self.selected_rcsdintersection_refs)) != len(
            self.selected_rcsdintersection_refs
        ):
            raise JunctionPredictionError("surface plan contains duplicate objects")
        if any(
            ref.role != EvidenceRole.RCSD_INTERSECTION
            for ref in self.selected_rcsdintersection_refs
        ):
            raise JunctionPredictionError(
                "surface plan can only select RCSD_INTERSECTION objects"
            )
        if len(set(self.virtual_member_refs)) != len(self.virtual_member_refs):
            raise JunctionPredictionError("virtual surface contains duplicate members")
        if any(
            ref.role not in {EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}
            for ref in self.virtual_member_refs
        ):
            raise JunctionPredictionError(
                "virtual surface members must be RCSD Nodes or Roads"
            )
        if self.mode == SurfaceMode.EXISTING_RCSD_INTERSECTION:
            if not self.selected_rcsdintersection_refs:
                raise JunctionPredictionError(
                    "existing surface plan requires an RCSDIntersection object"
                )
            if self.virtual_surface_recipe is not None:
                raise JunctionPredictionError(
                    "existing surface plan cannot include a virtual recipe"
                )
            if self.virtual_member_refs:
                raise JunctionPredictionError(
                    "existing surface plan cannot carry virtual members"
                )
        elif self.mode == SurfaceMode.VIRTUAL_SURFACE:
            if self.selected_rcsdintersection_refs:
                raise JunctionPredictionError(
                    "virtual surface plan cannot select an existing surface"
                )
            if self.virtual_surface_recipe is None:
                raise JunctionPredictionError("virtual surface recipe is required")
            self.virtual_surface_recipe.validate()
        elif (
            self.selected_rcsdintersection_refs
            or self.virtual_member_refs
            or self.virtual_surface_recipe is not None
        ):
            raise JunctionPredictionError(
                f"surface mode {self.mode.value} cannot carry a surface selection"
            )


@dataclass(frozen=True)
class RoadBreakOperation:
    road_ref: ObjectRef
    fractions: tuple[float, ...]

    def validate(self) -> None:
        if self.road_ref.role != EvidenceRole.RCSD_ROAD:
            raise JunctionPredictionError("Road break must target an RCSD Road")
        normalized = tuple(float(value) for value in self.fractions)
        if not normalized or tuple(sorted(set(normalized))) != normalized:
            raise JunctionPredictionError(
                "Road break fractions must be non-empty, unique, and sorted"
            )
        if any(not math.isfinite(value) or value <= 0.0 or value >= 1.0 for value in normalized):
            raise JunctionPredictionError("Road break fraction must be within (0, 1)")


@dataclass(frozen=True)
class AnchorNodeRef:
    kind: AnchorNodeKind
    node_ref: ObjectRef | None = None
    road_ref: ObjectRef | None = None
    break_rank: int | None = None

    @classmethod
    def source_node(cls, node_ref: ObjectRef) -> AnchorNodeRef:
        return cls(kind=AnchorNodeKind.SOURCE_RCSD_NODE, node_ref=node_ref)

    @classmethod
    def road_break_point(
        cls,
        road_ref: ObjectRef,
        break_rank: int,
    ) -> AnchorNodeRef:
        return cls(
            kind=AnchorNodeKind.ROAD_BREAK_POINT,
            road_ref=road_ref,
            break_rank=break_rank,
        )

    @property
    def key(self) -> str:
        if self.kind == AnchorNodeKind.SOURCE_RCSD_NODE and self.node_ref is not None:
            return f"NODE:{self.node_ref.object_id}"
        if (
            self.kind == AnchorNodeKind.ROAD_BREAK_POINT
            and self.road_ref is not None
            and self.break_rank is not None
        ):
            return f"BREAK:ROAD:{self.road_ref.object_id}#{self.break_rank}"
        return "INVALID_ANCHOR_NODE_REF"

    @property
    def referenced_objects(self) -> frozenset[ObjectRef]:
        refs = tuple(ref for ref in (self.node_ref, self.road_ref) if ref is not None)
        return frozenset(refs)

    def validate(self) -> None:
        if self.kind == AnchorNodeKind.SOURCE_RCSD_NODE:
            if (
                self.node_ref is None
                or self.node_ref.role != EvidenceRole.RCSD_NODE
                or self.road_ref is not None
                or self.break_rank is not None
            ):
                raise JunctionPredictionError(
                    "SOURCE_RCSD_NODE requires exactly one RCSD Node"
                )
            return
        if self.kind == AnchorNodeKind.ROAD_BREAK_POINT:
            if (
                self.road_ref is None
                or self.road_ref.role != EvidenceRole.RCSD_ROAD
                or self.node_ref is not None
                or self.break_rank is None
                or self.break_rank < 0
            ):
                raise JunctionPredictionError(
                    "ROAD_BREAK_POINT requires one RCSD Road and non-negative rank"
                )
            return
        raise JunctionPredictionError("unknown AnchorNodeRef kind")


@dataclass(frozen=True)
class NodeEquivalenceClass:
    node_refs: tuple[AnchorNodeRef, ...]

    def validate(self) -> None:
        if not self.node_refs or len(set(self.node_refs)) != len(self.node_refs):
            raise JunctionPredictionError(
                "Node equivalence class requires at least one unique node"
            )
        for ref in self.node_refs:
            ref.validate()


@dataclass(frozen=True)
class AnchorResult:
    state: AnchorState
    associated_rcsd_node_refs: tuple[ObjectRef, ...] = ()
    associated_rcsd_road_refs: tuple[ObjectRef, ...] = ()
    selected_main_anchor: AnchorNodeRef | None = None
    node_equivalence_classes: tuple[NodeEquivalenceClass, ...] = ()
    road_break_operations: tuple[RoadBreakOperation, ...] = ()

    def validate(self) -> None:
        if len(set(self.associated_rcsd_node_refs)) != len(
            self.associated_rcsd_node_refs
        ):
            raise JunctionPredictionError("anchor result contains duplicate RCSD Nodes")
        if len(set(self.associated_rcsd_road_refs)) != len(
            self.associated_rcsd_road_refs
        ):
            raise JunctionPredictionError("anchor result contains duplicate RCSD Roads")
        if any(
            ref.role != EvidenceRole.RCSD_NODE
            for ref in self.associated_rcsd_node_refs
        ):
            raise JunctionPredictionError("associated Node set contains a non-Node")
        if any(
            ref.role != EvidenceRole.RCSD_ROAD
            for ref in self.associated_rcsd_road_refs
        ):
            raise JunctionPredictionError("associated Road set contains a non-Road")

        carried_refs = set(self.associated_rcsd_node_refs) | set(
            self.associated_rcsd_road_refs
        )
        if self.state == AnchorState.SUCCESS:
            if not carried_refs or self.selected_main_anchor is None:
                raise JunctionPredictionError(
                    "SUCCESS requires a complete object set and one main anchor"
                )
            self.selected_main_anchor.validate()
            self._validate_anchor_node_ref(self.selected_main_anchor)
            equivalence_members: set[AnchorNodeRef] = set()
            for equivalence_class in self.node_equivalence_classes:
                equivalence_class.validate()
                if equivalence_members.intersection(equivalence_class.node_refs):
                    raise JunctionPredictionError(
                        "Anchor Node belongs to multiple equivalence classes"
                    )
                equivalence_members.update(equivalence_class.node_refs)
                for node_ref in equivalence_class.node_refs:
                    self._validate_anchor_node_ref(node_ref)
            break_roads: set[ObjectRef] = set()
            for operation in self.road_break_operations:
                operation.validate()
                if operation.road_ref not in self.associated_rcsd_road_refs:
                    raise JunctionPredictionError(
                        "Road break refers outside the associated Road set"
                    )
                if operation.road_ref in break_roads:
                    raise JunctionPredictionError(
                        "one RCSD Road has multiple break-operation records"
                    )
                break_roads.add(operation.road_ref)
        elif (
            carried_refs
            or self.selected_main_anchor is not None
            or self.node_equivalence_classes
            or self.road_break_operations
        ):
            raise JunctionPredictionError(
                f"anchor state {self.state.value} cannot carry a success object plan"
            )

    def _validate_anchor_node_ref(self, node_ref: AnchorNodeRef) -> None:
        if node_ref.kind == AnchorNodeKind.SOURCE_RCSD_NODE:
            if node_ref.node_ref not in self.associated_rcsd_node_refs:
                raise JunctionPredictionError(
                    "anchor Node refers outside associated RCSD Nodes"
                )
            return
        operation = next(
            (
                item
                for item in self.road_break_operations
                if item.road_ref == node_ref.road_ref
            ),
            None,
        )
        if (
            operation is None
            or node_ref.break_rank is None
            or node_ref.break_rank >= len(operation.fractions)
        ):
            raise JunctionPredictionError(
                "anchor break point does not resolve to a Road-break operation"
            )


@dataclass(frozen=True)
class CandidatePlan:
    plan_id: str
    step1_drivezone_state: Step1DriveZoneState
    surface_plan: SurfacePlan
    anchor_result: AnchorResult
    quality_state: QualityState
    review_reason: str
    planned_topology_signature: str

    def validate(self) -> None:
        if not self.plan_id.strip():
            raise JunctionPredictionError("candidate plan_id is blank")
        self.surface_plan.validate()
        self.anchor_result.validate()
        if self.anchor_result.state == AnchorState.SUCCESS:
            if self.step1_drivezone_state == Step1DriveZoneState.ABSTAIN:
                raise JunctionPredictionError(
                    "successful anchor cannot bypass an abstained Step1 state"
                )
            if not self.planned_topology_signature.strip():
                raise JunctionPredictionError(
                    "successful candidate requires a planned topology signature"
                )
        if self.quality_state != QualityState.NORMAL and not self.review_reason.strip():
            raise JunctionPredictionError(
                "non-normal candidate requires a review reason"
            )

    @property
    def referenced_objects(self) -> frozenset[ObjectRef]:
        refs = set(self.surface_plan.selected_rcsdintersection_refs)
        refs.update(self.surface_plan.virtual_member_refs)
        refs.update(self.anchor_result.associated_rcsd_node_refs)
        refs.update(self.anchor_result.associated_rcsd_road_refs)
        if self.anchor_result.selected_main_anchor is not None:
            refs.update(self.anchor_result.selected_main_anchor.referenced_objects)
        for equivalence_class in self.anchor_result.node_equivalence_classes:
            for node_ref in equivalence_class.node_refs:
                refs.update(node_ref.referenced_objects)
        for operation in self.anchor_result.road_break_operations:
            refs.add(operation.road_ref)
        return frozenset(refs)


@dataclass(frozen=True)
class CandidateBinding:
    junction_key: str
    allowed_object_refs: tuple[ObjectRef, ...]
    plans: tuple[CandidatePlan, ...]

    def validate(self) -> None:
        if not self.junction_key.strip():
            raise JunctionPredictionError("candidate binding junction_key is blank")
        if len(set(self.allowed_object_refs)) != len(self.allowed_object_refs):
            raise JunctionPredictionError("allowed object refs contain duplicates")
        plan_ids = tuple(plan.plan_id for plan in self.plans)
        if len(set(plan_ids)) != len(plan_ids):
            raise JunctionPredictionError("candidate plan IDs contain duplicates")
        allowed = set(self.allowed_object_refs)
        for plan in self.plans:
            plan.validate()
            unexpected = sorted(plan.referenced_objects - allowed)
            if unexpected:
                raise JunctionPredictionError(
                    "candidate plan refers outside the bound object set: "
                    + ", ".join(ref.key for ref in unexpected)
                )

    def plan(self, plan_id: str) -> CandidatePlan:
        for plan in self.plans:
            if plan.plan_id == plan_id:
                return plan
        raise JunctionPredictionError(f"unknown candidate plan_id: {plan_id}")


@dataclass(frozen=True)
class JunctionResultPrediction:
    junction_key: str
    selected_plan_id: str | None
    step1_drivezone_state: Step1DriveZoneState
    surface_plan: SurfacePlan
    anchor_result: AnchorResult
    post_materialization_topology_signature: str | None
    quality_state: QualityState
    review_reason: str
    component_confidences: tuple[tuple[str, float], ...]
    complete_plan_confidence: float
    abstain: bool

    @classmethod
    def abstained(
        cls,
        *,
        junction_key: str,
        review_reason: str,
        component_confidences: Mapping[str, float] | None = None,
    ) -> JunctionResultPrediction:
        return cls(
            junction_key=junction_key,
            selected_plan_id=None,
            step1_drivezone_state=Step1DriveZoneState.ABSTAIN,
            surface_plan=SurfacePlan(mode=SurfaceMode.ABSTAIN),
            anchor_result=AnchorResult(state=AnchorState.ABSTAIN),
            post_materialization_topology_signature=None,
            quality_state=QualityState.UNTRAINED,
            review_reason=review_reason,
            component_confidences=tuple(
                sorted((component_confidences or {}).items())
            ),
            complete_plan_confidence=0.0,
            abstain=True,
        )

    @classmethod
    def from_candidate(
        cls,
        *,
        junction_key: str,
        candidate: CandidatePlan,
        complete_plan_confidence: float,
        component_confidences: Mapping[str, float],
    ) -> JunctionResultPrediction:
        return cls(
            junction_key=junction_key,
            selected_plan_id=candidate.plan_id,
            step1_drivezone_state=candidate.step1_drivezone_state,
            surface_plan=candidate.surface_plan,
            anchor_result=candidate.anchor_result,
            post_materialization_topology_signature=(
                candidate.planned_topology_signature
            ),
            quality_state=candidate.quality_state,
            review_reason=candidate.review_reason,
            component_confidences=tuple(sorted(component_confidences.items())),
            complete_plan_confidence=float(complete_plan_confidence),
            abstain=False,
        )

    def validate(self, binding: CandidateBinding) -> None:
        if self.junction_key != binding.junction_key:
            raise JunctionPredictionError("prediction/binding junction keys differ")
        confidences = tuple(value for _, value in self.component_confidences)
        confidence_names = tuple(name for name, _ in self.component_confidences)
        if len(set(confidence_names)) != len(confidence_names):
            raise JunctionPredictionError("component confidence names contain duplicates")
        if any(
            not math.isfinite(float(value)) or value < 0.0 or value > 1.0
            for value in confidences + (self.complete_plan_confidence,)
        ):
            raise JunctionPredictionError("prediction confidence is outside [0, 1]")
        self.surface_plan.validate()
        self.anchor_result.validate()
        if self.abstain:
            if (
                self.selected_plan_id is not None
                or self.step1_drivezone_state != Step1DriveZoneState.ABSTAIN
                or self.surface_plan.mode != SurfaceMode.ABSTAIN
                or self.anchor_result.state != AnchorState.ABSTAIN
                or self.post_materialization_topology_signature is not None
                or not self.review_reason.strip()
            ):
                raise JunctionPredictionError("ABSTAIN prediction carries a business plan")
            return
        if self.selected_plan_id is None:
            raise JunctionPredictionError("non-ABSTAIN prediction requires selected_plan_id")
        candidate = binding.plan(self.selected_plan_id)
        expected = JunctionResultPrediction.from_candidate(
            junction_key=self.junction_key,
            candidate=candidate,
            complete_plan_confidence=self.complete_plan_confidence,
            component_confidences=dict(self.component_confidences),
        )
        if self != expected:
            raise JunctionPredictionError(
                "prediction changed the immutable bound candidate plan"
            )


@dataclass(frozen=True)
class ObjectTokenSpan:
    object_ref: ObjectRef
    start: int
    end: int

    def validate(self, token_count: int) -> None:
        if self.start < 0 or self.end <= self.start or self.end > token_count:
            raise JunctionPredictionError(
                f"invalid token span for {self.object_ref.key}: {self.start}:{self.end}"
            )


@dataclass(frozen=True)
class JunctionEvidenceExample:
    junction_key: str
    case_key: str
    semantic_junction_id: str
    geometry_tokens: torch.Tensor
    object_spans: tuple[ObjectTokenSpan, ...]
    topology_edge_indices: torch.Tensor
    topology_edge_features: torch.Tensor
    candidate_binding: CandidateBinding

    @classmethod
    def empty(
        cls,
        *,
        case_key: str,
        semantic_junction_id: str,
    ) -> JunctionEvidenceExample:
        junction_key = f"{case_key}|{semantic_junction_id}"
        return cls(
            junction_key=junction_key,
            case_key=case_key,
            semantic_junction_id=semantic_junction_id,
            geometry_tokens=torch.zeros((0, GEOMETRY_TOKEN_DIM), dtype=torch.float32),
            object_spans=(),
            topology_edge_indices=torch.zeros((2, 0), dtype=torch.long),
            topology_edge_features=torch.zeros(
                (0, TOPOLOGY_EDGE_DIM), dtype=torch.float32
            ),
            candidate_binding=CandidateBinding(
                junction_key=junction_key,
                allowed_object_refs=(),
                plans=(),
            ),
        )

    def validate(self) -> None:
        if (
            not self.case_key.strip()
            or not self.semantic_junction_id.strip()
            or self.junction_key != f"{self.case_key}|{self.semantic_junction_id}"
        ):
            raise JunctionPredictionError("example business identity is invalid")
        if self.geometry_tokens.ndim != 2 or tuple(self.geometry_tokens.shape[1:]) != (
            GEOMETRY_TOKEN_DIM,
        ):
            raise JunctionPredictionError("geometry_tokens must have shape [N, 21]")
        if not torch.isfinite(self.geometry_tokens).all().item():
            raise JunctionPredictionError("geometry_tokens contains non-finite values")
        token_count = int(self.geometry_tokens.shape[0])
        ordered_spans = tuple(sorted(self.object_spans, key=lambda span: span.start))
        if ordered_spans != self.object_spans:
            raise JunctionPredictionError("object token spans must be ordered")
        if len({span.object_ref for span in self.object_spans}) != len(self.object_spans):
            raise JunctionPredictionError("object token spans contain duplicate objects")
        cursor = 0
        for span in self.object_spans:
            span.validate(token_count)
            if span.start != cursor:
                raise JunctionPredictionError("object token spans must be contiguous")
            cursor = span.end
        if cursor != token_count:
            raise JunctionPredictionError("object token spans do not cover all tokens")
        if (
            self.topology_edge_indices.dtype != torch.long
            or self.topology_edge_indices.ndim != 2
            or int(self.topology_edge_indices.shape[0]) != 2
        ):
            raise JunctionPredictionError("topology_edge_indices must have shape [2, E]")
        edge_count = int(self.topology_edge_indices.shape[1])
        if tuple(self.topology_edge_features.shape) != (
            edge_count,
            TOPOLOGY_EDGE_DIM,
        ):
            raise JunctionPredictionError(
                "topology_edge_features must have shape [E, 8]"
            )
        if not torch.isfinite(self.topology_edge_features).all().item():
            raise JunctionPredictionError(
                "topology_edge_features contains non-finite values"
            )
        if edge_count and (
            int(self.topology_edge_indices.min()) < 0
            or int(self.topology_edge_indices.max()) >= token_count
        ):
            raise JunctionPredictionError("topology edge index is outside token range")
        self.candidate_binding.validate()
        if self.candidate_binding.junction_key != self.junction_key:
            raise JunctionPredictionError("example candidate binding has another identity")
        span_refs = {span.object_ref for span in self.object_spans}
        if not set(self.candidate_binding.allowed_object_refs).issubset(span_refs):
            raise JunctionPredictionError(
                "candidate binding refers outside the example object spans"
            )


@dataclass(frozen=True)
class JunctionEvidenceBatch:
    examples: tuple[JunctionEvidenceExample, ...]
    geometry_tokens: torch.Tensor
    example_token_offsets: torch.Tensor
    topology_edge_indices: torch.Tensor
    topology_edge_features: torch.Tensor
    example_edge_offsets: torch.Tensor

    @classmethod
    def from_examples(
        cls,
        examples: Sequence[JunctionEvidenceExample],
    ) -> JunctionEvidenceBatch:
        normalized = tuple(examples)
        for example in normalized:
            example.validate()
        if len({example.junction_key for example in normalized}) != len(normalized):
            raise JunctionPredictionError("batch contains duplicate Junction identities")

        token_offsets = [0]
        edge_offsets = [0]
        token_parts: list[torch.Tensor] = []
        edge_index_parts: list[torch.Tensor] = []
        edge_feature_parts: list[torch.Tensor] = []
        for example in normalized:
            token_parts.append(example.geometry_tokens.to(dtype=torch.float32))
            edge_index_parts.append(
                example.topology_edge_indices + token_offsets[-1]
            )
            edge_feature_parts.append(
                example.topology_edge_features.to(dtype=torch.float32)
            )
            token_offsets.append(
                token_offsets[-1] + int(example.geometry_tokens.shape[0])
            )
            edge_offsets.append(
                edge_offsets[-1] + int(example.topology_edge_features.shape[0])
            )
        geometry_tokens = (
            torch.cat(token_parts, dim=0)
            if token_parts
            else torch.zeros((0, GEOMETRY_TOKEN_DIM), dtype=torch.float32)
        )
        topology_edge_indices = (
            torch.cat(edge_index_parts, dim=1)
            if edge_index_parts
            else torch.zeros((2, 0), dtype=torch.long)
        )
        topology_edge_features = (
            torch.cat(edge_feature_parts, dim=0)
            if edge_feature_parts
            else torch.zeros((0, TOPOLOGY_EDGE_DIM), dtype=torch.float32)
        )
        return cls(
            examples=normalized,
            geometry_tokens=geometry_tokens,
            example_token_offsets=torch.tensor(token_offsets, dtype=torch.long),
            topology_edge_indices=topology_edge_indices,
            topology_edge_features=topology_edge_features,
            example_edge_offsets=torch.tensor(edge_offsets, dtype=torch.long),
        )

    def __len__(self) -> int:
        return len(self.examples)


class RandomInitializedJunctionFreeRun(nn.Module):
    """Untrained chain skeleton; its hard safety lock only permits ABSTAIN."""

    def __init__(self, *, hidden_dim: int = 32, seed: int = 20260807) -> None:
        super().__init__()
        if hidden_dim < 1:
            raise ValueError("hidden_dim must be positive")
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.plan_probe = nn.Sequential(
                nn.Linear(GEOMETRY_TOKEN_DIM, hidden_dim),
                nn.Tanh(),
                nn.Linear(hidden_dim, 1),
            )
        self.safety_locked = True

    @property
    def parameter_count(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters())

    def forward(
        self,
        batch: JunctionEvidenceBatch,
    ) -> tuple[JunctionResultPrediction, ...]:
        predictions: list[JunctionResultPrediction] = []
        for index, example in enumerate(batch.examples):
            start = int(batch.example_token_offsets[index])
            end = int(batch.example_token_offsets[index + 1])
            if end > start:
                pooled = batch.geometry_tokens[start:end].mean(dim=0)
            else:
                pooled = batch.geometry_tokens.new_zeros((GEOMETRY_TOKEN_DIM,))
            untrained_score = float(torch.sigmoid(self.plan_probe(pooled)).item())
            predictions.append(
                JunctionResultPrediction.abstained(
                    junction_key=example.junction_key,
                    review_reason="UNTRAINED_MODEL",
                    component_confidences={
                        "untrained_plan_probe": untrained_score,
                    },
                )
            )
        return tuple(predictions)


def validate_free_run_output(
    batch: JunctionEvidenceBatch,
    predictions: Sequence[JunctionResultPrediction],
) -> dict[str, int]:
    normalized = tuple(predictions)
    if len(normalized) != len(batch):
        raise JunctionPredictionError(
            f"prediction count differs from batch: {len(normalized)} != {len(batch)}"
        )
    invalid_count = 0
    abstain_count = 0
    for example, prediction in zip(batch.examples, normalized):
        try:
            prediction.validate(example.candidate_binding)
        except JunctionPredictionError:
            invalid_count += 1
            continue
        abstain_count += int(prediction.abstain)
    return {
        "example_count": len(batch),
        "valid_count": len(batch) - invalid_count,
        "invalid_count": invalid_count,
        "abstain_count": abstain_count,
        "non_abstain_count": len(batch) - abstain_count - invalid_count,
    }


@dataclass(frozen=True)
class JunctionIdentity:
    case_key: str
    semantic_junction_id: str

    @property
    def junction_key(self) -> str:
        return f"{self.case_key}|{self.semantic_junction_id}"


def run_untrained_identity_audit(
    identities: Sequence[JunctionIdentity],
    *,
    batch_size: int = 512,
    seed: int = 20260807,
) -> dict[str, int | str | bool]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    normalized = tuple(identities)
    junction_keys = tuple(identity.junction_key for identity in normalized)
    if any(
        not identity.case_key.strip() or not identity.semantic_junction_id.strip()
        for identity in normalized
    ):
        raise JunctionPredictionError("identity contains a blank business key")
    if len(set(junction_keys)) != len(junction_keys):
        raise JunctionPredictionError("identity audit contains duplicate Junction keys")
    model = RandomInitializedJunctionFreeRun(seed=seed)
    model.eval()
    valid_count = 0
    abstain_count = 0
    invalid_count = 0
    with torch.no_grad():
        for start in range(0, len(normalized), batch_size):
            chunk = normalized[start : start + batch_size]
            batch = JunctionEvidenceBatch.from_examples(
                [
                    JunctionEvidenceExample.empty(
                        case_key=identity.case_key,
                        semantic_junction_id=identity.semantic_junction_id,
                    )
                    for identity in chunk
                ]
            )
            audit = validate_free_run_output(batch, model(batch))
            valid_count += audit["valid_count"]
            abstain_count += audit["abstain_count"]
            invalid_count += audit["invalid_count"]
    payload = "".join(f"{key}\n" for key in sorted(junction_keys)).encode("utf-8")
    return {
        "identity_count": len(normalized),
        "identity_sha256": hashlib.sha256(payload).hexdigest(),
        "valid_prediction_count": valid_count,
        "abstain_count": abstain_count,
        "non_abstain_count": len(normalized) - abstain_count - invalid_count,
        "invalid_prediction_count": invalid_count,
        "model_parameter_count": model.parameter_count,
        "safety_locked": model.safety_locked,
    }
