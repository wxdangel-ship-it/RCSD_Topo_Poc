from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import EvidenceRef


SCHEME_A_SCHEMA_VERSION = "p05-scheme-a-frozen-case-v1"


class _TextEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class SegmentType(_TextEnum):
    STANDARD = "STANDARD"
    ADVANCE_RIGHT = "ADVANCE_RIGHT"


class StrategyOutcome(_TextEnum):
    SUCCESS_DIRECT = "SUCCESS_DIRECT"
    SUCCESS_WITH_FALLBACK = "SUCCESS_WITH_FALLBACK"
    FAIL = "FAIL"


class CarrierTarget(_TextEnum):
    USE_RCSD = "USE_RCSD"
    KEEP_SWSD = "KEEP_SWSD"
    MIXED_CARRIER = "MIXED_CARRIER"
    REVIEW_FALLBACK = "REVIEW_FALLBACK"


class CarrierKind(_TextEnum):
    ROAD = "ROAD"
    NODE = "NODE"
    UNKNOWN = "UNKNOWN"


class ClueScope(_TextEnum):
    MOVEMENT = "MOVEMENT"
    SEGMENT = "SEGMENT"
    JUNCTION = "JUNCTION"


class FallbackUnit(_TextEnum):
    MOVEMENT = "MOVEMENT"
    SEGMENT = "SEGMENT"
    JUNCTION = "JUNCTION"


class FallbackOutcome(_TextEnum):
    SUCCESS_WITH_FALLBACK = "SUCCESS_WITH_FALLBACK"
    FAIL = "FAIL"


@dataclass(frozen=True)
class FrozenSegment:
    segment_id: str
    segment_type: SegmentType
    pair_nodes: tuple[str, ...]
    junc_nodes: tuple[str, ...]
    swsd_road_ids: tuple[str, ...]
    direction_structure: str
    independent_road_valid: bool
    source_segment_access: str
    target_segment_access: str
    access_valid: bool
    evidence_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class FrozenJunctionSegmentRelation:
    junction_id: str
    segment_id: str
    structural_role: str
    direction_role: str
    access_node_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class FrozenJunction:
    junction_id: str
    junction_type: str
    related_segment_ids: tuple[str, ...]
    mainnode_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class FrozenPhysicalMovement:
    movement_id: str
    junction_id: str
    from_segment_access: str
    to_segment_access: str
    carrier_kind: CarrierKind
    carrier_ids: tuple[str, ...]
    carrier_exclusive: bool
    affects_shared_junction_unit: bool
    evidence_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class FrozenSchemeACase:
    case_key: str
    family: str
    business_id: str
    sample_id: str
    fold: int
    crs: str
    source_manifest: str
    source_hashes: tuple[tuple[str, str], ...]
    junctions: tuple[FrozenJunction, ...]
    segments: tuple[FrozenSegment, ...]
    junction_segment_relations: tuple[FrozenJunctionSegmentRelation, ...]
    physical_movements: tuple[FrozenPhysicalMovement, ...]
    schema_version: str = SCHEME_A_SCHEMA_VERSION
    content_repair: bool = False
    silent_fix: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = _json_value(asdict(self))
        payload["skeleton_signature"] = self.skeleton_signature()
        return payload

    def skeleton_signature(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "case_key": self.case_key,
            "family": self.family,
            "business_id": self.business_id,
            "junctions": [
                {
                    "junction_id": item.junction_id,
                    "junction_type": item.junction_type,
                    "related_segment_ids": sorted(item.related_segment_ids),
                }
                for item in sorted(self.junctions, key=lambda value: value.junction_id)
            ],
            "segments": [
                {
                    "segment_id": item.segment_id,
                    "segment_type": item.segment_type.value,
                    "pair_nodes": list(item.pair_nodes),
                    "junc_nodes": list(item.junc_nodes),
                    "swsd_road_ids": list(item.swsd_road_ids),
                    "direction_structure": item.direction_structure,
                    "source_segment_access": item.source_segment_access,
                    "target_segment_access": item.target_segment_access,
                    "access_valid": item.access_valid,
                }
                for item in sorted(self.segments, key=lambda value: value.segment_id)
            ],
            "junction_segment_relations": [
                {
                    "junction_id": item.junction_id,
                    "segment_id": item.segment_id,
                    "structural_role": item.structural_role,
                    "direction_role": item.direction_role,
                    "access_node_ids": list(item.access_node_ids),
                }
                for item in sorted(
                    self.junction_segment_relations,
                    key=lambda value: (value.junction_id, value.segment_id),
                )
            ],
            "physical_movements": [
                {
                    "movement_id": item.movement_id,
                    "junction_id": item.junction_id,
                    "from_segment_access": item.from_segment_access,
                    "to_segment_access": item.to_segment_access,
                }
                for item in sorted(self.physical_movements, key=lambda value: value.movement_id)
            ],
        }
        return canonical_sha256(payload)


@dataclass(frozen=True)
class StrategyBaselineRecord:
    case_key: str
    segment_id: str
    relation_status: str
    relation_reason: str
    source_mix: tuple[str, ...]
    outcome: StrategyOutcome
    carrier_target: CarrierTarget
    selected_road_ids: tuple[str, ...]
    swsd_fallback_road_ids: tuple[str, ...]
    lineage: tuple[EvidenceRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass(frozen=True)
class CarrierLabel:
    case_key: str
    object_type: str
    object_id: str
    skeleton_signature: str
    carrier_target: CarrierTarget
    target_kind: CarrierKind
    target_payload: tuple[str, ...]
    label_weight: float
    weight_role: str
    fold: int
    available: bool
    mask_reason: str
    lineage: tuple[EvidenceRef, ...]
    label_only: bool = True
    feature_uses_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass(frozen=True)
class RealityChangeClue:
    clue_id: str
    case_key: str
    scope: ClueScope
    object_id: str
    code: str
    detail: str
    evidence_refs: tuple[EvidenceRef, ...]
    recommended_fallback: FallbackUnit
    status: str = "OPEN"
    skeleton_mutation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))

    @classmethod
    def create(
        cls,
        *,
        case_key: str,
        scope: ClueScope,
        object_id: str,
        code: str,
        detail: str,
        evidence_refs: tuple[EvidenceRef, ...],
        recommended_fallback: FallbackUnit,
    ) -> "RealityChangeClue":
        clue_id = "rcc_" + canonical_sha256(
            {
                "case_key": case_key,
                "scope": scope.value,
                "object_id": object_id,
                "code": code,
                "detail": detail,
            }
        )[:20]
        return cls(
            clue_id=clue_id,
            case_key=case_key,
            scope=scope,
            object_id=object_id,
            code=code,
            detail=detail,
            evidence_refs=evidence_refs,
            recommended_fallback=recommended_fallback,
        )


@dataclass(frozen=True)
class FallbackPlan:
    case_key: str
    trigger: str
    clue_ids: tuple[str, ...]
    unit: FallbackUnit
    junction_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]
    movement_ids: tuple[str, ...]
    retained_swsd_road_ids: tuple[str, ...]
    outcome: FallbackOutcome
    failure_reasons: tuple[str, ...]
    skeleton_mutation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass(frozen=True)
class SchemeABaselineConfig:
    jsg_p0_run_root: Path
    m0_run_root: Path
    output_root: Path
    run_id: str
    poc_data_root: Path = Path(r"E:\TestData\POC_Data")
    excluded_business_ids: tuple[str, ...] = ("1213556_1263661",)
    expected_case_count: int = 51
    strict_hashes: bool = True
    enforce_poc_scope: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "CarrierKind",
    "CarrierLabel",
    "CarrierTarget",
    "ClueScope",
    "FallbackOutcome",
    "FallbackPlan",
    "FallbackUnit",
    "FrozenJunction",
    "FrozenJunctionSegmentRelation",
    "FrozenPhysicalMovement",
    "FrozenSchemeACase",
    "FrozenSegment",
    "RealityChangeClue",
    "SCHEME_A_SCHEMA_VERSION",
    "SchemeABaselineConfig",
    "SegmentType",
    "StrategyBaselineRecord",
    "StrategyOutcome",
    "canonical_sha256",
]
