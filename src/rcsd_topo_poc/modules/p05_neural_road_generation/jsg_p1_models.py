from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import EvidenceRef


JSG_P1_CANDIDATE_SCHEMA_VERSION = "p05-jsg-p1-candidate-v1"


class _TextEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class P1Stage(_TextEnum):
    PTO_A = "PTO_A"
    PTO_B = "PTO_B"


class P1ObjectType(_TextEnum):
    JUNCTION = "JUNCTION"
    STANDARD_SEGMENT = "STANDARD_SEGMENT"
    RELATION = "RELATION"
    PHYSICAL_MOVEMENT = "PHYSICAL_MOVEMENT"
    SEGMENT_CONNECTOR = "SEGMENT_CONNECTOR"
    ROADGRAPH_CARRIER = "ROADGRAPH_CARRIER"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class JSGP1Candidate:
    candidate_id: str
    case_key: str
    stage: P1Stage
    object_type: P1ObjectType
    object_key: str
    group_id: str
    group_mode: str
    payload: Mapping[str, Any]
    payload_sha256: str
    dependencies: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    source_kinds: tuple[str, ...]
    truth_derived: bool = False
    label_only: bool = False
    schema_version: str = JSG_P1_CANDIDATE_SCHEMA_VERSION

    @classmethod
    def build(
        cls,
        *,
        case_key: str,
        stage: P1Stage,
        object_type: P1ObjectType,
        object_key: str,
        group_id: str,
        payload: Mapping[str, Any],
        dependencies: tuple[str, ...] = (),
        evidence_refs: tuple[EvidenceRef, ...] = (),
        source_kinds: tuple[str, ...] = (),
        group_mode: str = "EXACTLY_ONE",
    ) -> "JSGP1Candidate":
        normalized_payload = _json_value(dict(payload))
        payload_sha = canonical_sha256(normalized_payload)
        identity = {
            "case_key": case_key,
            "stage": stage.value,
            "object_type": object_type.value,
            "object_key": object_key,
            "group_id": group_id,
            "payload_sha256": payload_sha,
            "dependencies": sorted(set(dependencies)),
        }
        return cls(
            candidate_id=f"jsgp1:{canonical_sha256(identity)[:24]}",
            case_key=case_key,
            stage=stage,
            object_type=object_type,
            object_key=object_key,
            group_id=group_id,
            group_mode=group_mode,
            payload=normalized_payload,
            payload_sha256=payload_sha,
            dependencies=tuple(sorted(set(dependencies))),
            evidence_refs=tuple(
                sorted(evidence_refs, key=lambda row: (row.role, row.object_id, row.path, row.sha256))
            ),
            source_kinds=tuple(sorted(set(source_kinds))),
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass(frozen=True)
class JSGP1CandidateConfig:
    pto_candidate_run_root: Path
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


@dataclass(frozen=True)
class JSGP1OracleConfig:
    candidate_run_root: Path
    p0_truth_run_root: Path
    r2_oracle_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    strict_hashes: bool = True
    emit_reconstructed_gpkg: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "JSGP1Candidate",
    "JSGP1CandidateConfig",
    "JSGP1OracleConfig",
    "JSG_P1_CANDIDATE_SCHEMA_VERSION",
    "P1ObjectType",
    "P1Stage",
    "canonical_json_bytes",
    "canonical_sha256",
]
