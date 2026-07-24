from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


JSG_SCHEMA_VERSION = "p05-jsg-case-truth-v1"


class _TextEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ObjectState(_TextEnum):
    PUBLISHABLE = "PUBLISHABLE"
    REVIEW = "REVIEW"
    UNKNOWN = "UNKNOWN"


class JunctionType(_TextEnum):
    NORMAL = "NORMAL"
    ROUNDABOUT = "ROUNDABOUT"
    COMPLEX_DIVMERGE = "COMPLEX_DIVMERGE"
    TERMINAL_DEAD_END = "TERMINAL_DEAD_END"
    TERMINAL_DATA_BOUNDARY = "TERMINAL_DATA_BOUNDARY"
    TERMINAL_UNKNOWN = "TERMINAL_UNKNOWN"


class StructuralRole(_TextEnum):
    ENDPOINT = "ENDPOINT"
    THROUGH = "THROUGH"


class DirectionRole(_TextEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    BOTH = "BOTH"
    UNKNOWN = "UNKNOWN"


class DirectionStructure(_TextEnum):
    DIRECTED = "DIRECTED"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidenceRef:
    role: str
    path: str
    sha256: str
    object_id: str = ""


@dataclass(frozen=True)
class JunctionUnit:
    junction_id: str
    junction_type: JunctionType
    growth_level: str
    evidence_refs: tuple[EvidenceRef, ...]
    state: ObjectState


@dataclass(frozen=True)
class StandardSegmentUnit:
    segment_id: str
    endpoint_positions: tuple[str, str]
    attached_junctions: tuple[str, ...]
    direction_structure: DirectionStructure
    growth_level: str
    road_grade: str
    carrier_road_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    explicit_loop: bool
    state: ObjectState


@dataclass(frozen=True)
class JunctionSegmentRelation:
    junction_id: str
    segment_id: str
    structural_role: StructuralRole
    direction_role: DirectionRole
    access_legs: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    state: ObjectState


@dataclass(frozen=True)
class PhysicalMovement:
    movement_id: str
    junction_id: str
    from_segment_access: str
    to_segment_access: str
    physical_reachable: bool
    carrier_road_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    state: ObjectState


@dataclass(frozen=True)
class SegmentConnector:
    connector_id: str
    source_segment_access: str
    target_segment_access: str
    direction: str
    carrier_road_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    state: ObjectState


@dataclass(frozen=True)
class CarrierRealization:
    r2_oracle_run_manifest: str
    r2_case_sample_id: str
    road_edits_path: str
    node_edits_path: str
    expected_truth_road: str
    expected_truth_node: str
    artifact_hashes: tuple[tuple[str, str], ...]
    label_only: bool = True


@dataclass(frozen=True)
class JSGAnomaly:
    code: str
    object_type: str
    object_id: str
    message: str
    severity: str = "REVIEW"


@dataclass(frozen=True)
class JSGCaseTruth:
    case_key: str
    family: str
    business_id: str
    crs: str
    source_manifest: str
    source_hashes: tuple[tuple[str, str], ...]
    junction_units: tuple[JunctionUnit, ...]
    standard_segments: tuple[StandardSegmentUnit, ...]
    junction_segment_relations: tuple[JunctionSegmentRelation, ...]
    physical_movements: tuple[PhysicalMovement, ...]
    segment_connectors: tuple[SegmentConnector, ...]
    carrier_realization: CarrierRealization
    anomalies: tuple[JSGAnomaly, ...]
    schema_version: str = JSG_SCHEMA_VERSION
    label_only: bool = True
    content_repair: bool = False
    silent_fix: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "JSGCaseTruth":
        def evidence(rows: Any) -> tuple[EvidenceRef, ...]:
            return tuple(EvidenceRef(**dict(row)) for row in rows or [])

        junctions = tuple(
            JunctionUnit(
                junction_id=str(row["junction_id"]),
                junction_type=JunctionType(row["junction_type"]),
                growth_level=str(row.get("growth_level") or ""),
                evidence_refs=evidence(row.get("evidence_refs")),
                state=ObjectState(row["state"]),
            )
            for row in raw.get("junction_units") or []
        )
        segments = tuple(
            StandardSegmentUnit(
                segment_id=str(row["segment_id"]),
                endpoint_positions=tuple(str(item) for item in row["endpoint_positions"]),  # type: ignore[arg-type]
                attached_junctions=tuple(str(item) for item in row.get("attached_junctions") or []),
                direction_structure=DirectionStructure(row["direction_structure"]),
                growth_level=str(row.get("growth_level") or ""),
                road_grade=str(row.get("road_grade") or "UNSPECIFIED"),
                carrier_road_ids=tuple(str(item) for item in row.get("carrier_road_ids") or []),
                evidence_refs=evidence(row.get("evidence_refs")),
                explicit_loop=bool(row.get("explicit_loop")),
                state=ObjectState(row["state"]),
            )
            for row in raw.get("standard_segments") or []
        )
        relations = tuple(
            JunctionSegmentRelation(
                junction_id=str(row["junction_id"]),
                segment_id=str(row["segment_id"]),
                structural_role=StructuralRole(row["structural_role"]),
                direction_role=DirectionRole(row["direction_role"]),
                access_legs=tuple(str(item) for item in row.get("access_legs") or []),
                evidence_refs=evidence(row.get("evidence_refs")),
                state=ObjectState(row["state"]),
            )
            for row in raw.get("junction_segment_relations") or []
        )
        movements = tuple(
            PhysicalMovement(
                movement_id=str(row["movement_id"]),
                junction_id=str(row["junction_id"]),
                from_segment_access=str(row["from_segment_access"]),
                to_segment_access=str(row["to_segment_access"]),
                physical_reachable=bool(row["physical_reachable"]),
                carrier_road_ids=tuple(str(item) for item in row.get("carrier_road_ids") or []),
                evidence_refs=evidence(row.get("evidence_refs")),
                state=ObjectState(row["state"]),
            )
            for row in raw.get("physical_movements") or []
        )
        connectors = tuple(
            SegmentConnector(
                connector_id=str(row["connector_id"]),
                source_segment_access=str(row.get("source_segment_access") or ""),
                target_segment_access=str(row.get("target_segment_access") or ""),
                direction=str(row.get("direction") or "FORWARD"),
                carrier_road_ids=tuple(str(item) for item in row.get("carrier_road_ids") or []),
                evidence_refs=evidence(row.get("evidence_refs")),
                state=ObjectState(row["state"]),
            )
            for row in raw.get("segment_connectors") or []
        )
        carrier_raw = dict(raw["carrier_realization"])
        carrier = CarrierRealization(
            r2_oracle_run_manifest=str(carrier_raw["r2_oracle_run_manifest"]),
            r2_case_sample_id=str(carrier_raw["r2_case_sample_id"]),
            road_edits_path=str(carrier_raw["road_edits_path"]),
            node_edits_path=str(carrier_raw["node_edits_path"]),
            expected_truth_road=str(carrier_raw["expected_truth_road"]),
            expected_truth_node=str(carrier_raw["expected_truth_node"]),
            artifact_hashes=tuple((str(key), str(value)) for key, value in carrier_raw["artifact_hashes"]),
            label_only=bool(carrier_raw.get("label_only", True)),
        )
        anomalies = tuple(JSGAnomaly(**dict(row)) for row in raw.get("anomalies") or [])
        return cls(
            case_key=str(raw["case_key"]),
            family=str(raw["family"]),
            business_id=str(raw["business_id"]),
            crs=str(raw["crs"]),
            source_manifest=str(raw["source_manifest"]),
            source_hashes=tuple((str(key), str(value)) for key, value in raw.get("source_hashes") or []),
            junction_units=junctions,
            standard_segments=segments,
            junction_segment_relations=relations,
            physical_movements=movements,
            segment_connectors=connectors,
            carrier_realization=carrier,
            anomalies=anomalies,
            schema_version=str(raw.get("schema_version") or JSG_SCHEMA_VERSION),
            label_only=bool(raw.get("label_only", True)),
            content_repair=bool(raw.get("content_repair", False)),
            silent_fix=bool(raw.get("silent_fix", False)),
        )

    def semantic_signature(self) -> str:
        payload = self.to_dict()
        for key in ("source_manifest", "source_hashes", "carrier_realization", "anomalies"):
            payload.pop(key, None)
        _remove_evidence_refs(payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def provenance_signature(self) -> str:
        payload = {
            "case_key": self.case_key,
            "source_manifest": self.source_manifest,
            "source_hashes": self.source_hashes,
            "carrier_realization": _json_value(asdict(self.carrier_realization)),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JSGP0Config:
    r2_oracle_run_root: Path
    output_root: Path
    run_id: str
    pto_candidate_run_root: Path | None = None
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


def segment_access(segment_id: str, junction_id: str) -> str:
    return f"{segment_id}@{junction_id}"


def split_segment_access(value: str) -> tuple[str, str]:
    segment_id, separator, junction_id = value.rpartition("@")
    if not separator or not segment_id or not junction_id:
        raise ValueError(f"invalid segment access: {value}")
    return segment_id, junction_id


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _remove_evidence_refs(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("evidence_refs", None)
        for item in value.values():
            _remove_evidence_refs(item)
    elif isinstance(value, list):
        for item in value:
            _remove_evidence_refs(item)


__all__ = [
    "CarrierRealization",
    "DirectionRole",
    "DirectionStructure",
    "EvidenceRef",
    "JSGAnomaly",
    "JSGCaseTruth",
    "JSGP0Config",
    "JSG_SCHEMA_VERSION",
    "JunctionSegmentRelation",
    "JunctionType",
    "JunctionUnit",
    "ObjectState",
    "PhysicalMovement",
    "SegmentConnector",
    "StandardSegmentUnit",
    "StructuralRole",
    "segment_access",
    "split_segment_access",
]
