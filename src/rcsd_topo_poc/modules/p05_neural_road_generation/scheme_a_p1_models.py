from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)


SCHEME_A_P1_CANDIDATE_SCHEMA = "p05-scheme-a-p1-candidate-v1"
SCHEME_A_P1_DATASET_SCHEMA = "p05-scheme-a-p1-dataset-v1"


@dataclass(frozen=True)
class SchemeAP1CandidateConfig:
    scheme_a_baseline_run_root: Path
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
class SchemeAP1DatasetConfig:
    candidate_run_root: Path
    scheme_a_baseline_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    expected_fold_count: int = 5
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")


@dataclass(frozen=True)
class SchemeAP1OOFConfig:
    dataset_run_root: Path
    candidate_run_root: Path
    scheme_a_baseline_run_root: Path
    output_root: Path
    run_id: str
    seeds: tuple[int, ...] = (17, 29, 43)
    expected_roadgraph_failures: tuple[tuple[str, str, str], ...] = (
        ("T10:74155468", "953982", "953982->47348378"),
        ("T10:609214532", "987665", "987665->987661"),
    )
    expected_case_count: int = 51
    expected_fold_count: int = 5
    embedding_dim: int = 160
    hidden_dim: int = 384
    type_embedding_dim: int = 48
    numeric_dim: int = 8
    dropout: float = 0.10
    learning_rate: float = 0.002
    weight_decay: float = 0.0001
    max_epochs: int = 40
    patience: int = 6
    inner_validation_ratio: float = 0.15
    anomaly_loss_weight: float = 0.5
    max_anomaly_threshold: float = 0.10
    batch_group_count: int = 512
    min_parameter_count: int = 1_000_000
    max_parameter_count: int = 5_000_000
    device: str = "auto"
    torch_num_threads: int = 8
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        expected_failure_cases = [row[0] for row in self.expected_roadgraph_failures]
        if len(expected_failure_cases) != len(set(expected_failure_cases)) or any(
            not case_key or not node_id or not directed_edge
            for case_key, node_id, directed_edge in self.expected_roadgraph_failures
        ):
            raise ValueError("invalid expected RoadGraph failure manifest")
        if len(expected_failure_cases) >= self.expected_case_count:
            raise ValueError("expected RoadGraph failures must not consume the Case scope")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if min(
            self.embedding_dim,
            self.hidden_dim,
            self.type_embedding_dim,
            self.numeric_dim,
        ) < 1:
            raise ValueError("model dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid optimizer configuration")
        if self.max_epochs < 1 or self.patience < 1:
            raise ValueError("training limits must be positive")
        if not 0.0 < self.inner_validation_ratio < 0.5:
            raise ValueError("inner_validation_ratio must be in (0, 0.5)")
        if self.anomaly_loss_weight < 0:
            raise ValueError("anomaly_loss_weight must be non-negative")
        if not 0.0 < self.max_anomaly_threshold <= 1.0:
            raise ValueError("max_anomaly_threshold must be in (0, 1]")
        if self.batch_group_count < 1:
            raise ValueError("batch_group_count must be positive")
        if not 0 < self.min_parameter_count <= self.max_parameter_count:
            raise ValueError("invalid parameter count bounds")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto/cpu/cuda")


@dataclass(frozen=True)
class SchemeAP1Candidate:
    case_key: str
    family: str
    business_id: str
    object_type: str
    object_id: str
    group_id: str
    candidate_id: str
    candidate_target: str
    target_kind: str
    target_payload: tuple[str, ...]
    source_kinds: tuple[str, ...]
    object_tokens: tuple[str, ...]
    candidate_tokens: tuple[str, ...]
    context_tokens: tuple[str, ...]
    numeric_features: tuple[float, ...]
    payload_artifacts: tuple[tuple[str, str, str], ...]
    payload_artifact_by_id: tuple[tuple[str, str, str, str], ...] = ()
    hard_unsafe: bool = False
    truth_derived: bool = False
    feature_uses_truth: bool = False
    absolute_coordinate_feature_count: int = 0
    schema_version: str = SCHEME_A_P1_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        if self.object_type not in {"SEGMENT", "MOVEMENT"}:
            raise ValueError(f"unsupported object type: {self.object_type}")
        if self.target_kind not in {"ROAD", "NODE", "UNKNOWN"}:
            raise ValueError(f"unsupported target kind: {self.target_kind}")
        if len(self.numeric_features) != 8:
            raise ValueError("numeric_features must contain exactly eight values")
        if self.truth_derived or self.feature_uses_truth:
            raise ValueError("P1 candidate features must be truth-free")
        if self.absolute_coordinate_feature_count:
            raise ValueError("absolute coordinates are forbidden model features")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        *,
        case_key: str,
        family: str,
        business_id: str,
        object_type: str,
        object_id: str,
        candidate_target: str,
        target_kind: str,
        target_payload: tuple[str, ...],
        source_kinds: tuple[str, ...],
        object_tokens: tuple[str, ...],
        candidate_tokens: tuple[str, ...],
        context_tokens: tuple[str, ...],
        numeric_features: tuple[float, ...],
        payload_artifacts: tuple[tuple[str, str, str], ...],
        payload_artifact_by_id: tuple[tuple[str, str, str, str], ...] = (),
        hard_unsafe: bool = False,
    ) -> "SchemeAP1Candidate":
        group_id = f"SCHEME_A_P1:{object_type}:{case_key}:{object_id}"
        candidate_id = "sap1:" + canonical_sha256(
            {
                "case_key": case_key,
                "object_type": object_type,
                "object_id": object_id,
                "candidate_target": candidate_target,
                "target_kind": target_kind,
                "target_payload": sorted(target_payload),
                "source_kinds": sorted(source_kinds),
                "payload_artifact_by_id": sorted(payload_artifact_by_id),
            }
        )[:24]
        return cls(
            case_key=case_key,
            family=family,
            business_id=business_id,
            object_type=object_type,
            object_id=object_id,
            group_id=group_id,
            candidate_id=candidate_id,
            candidate_target=candidate_target,
            target_kind=target_kind,
            target_payload=tuple(sorted(target_payload)),
            source_kinds=tuple(sorted(source_kinds)),
            object_tokens=tuple(sorted(set(object_tokens))),
            candidate_tokens=tuple(sorted(set(candidate_tokens))),
            context_tokens=tuple(sorted(set(context_tokens))),
            numeric_features=numeric_features,
            payload_artifacts=tuple(sorted(set(payload_artifacts))),
            payload_artifact_by_id=tuple(sorted(set(payload_artifact_by_id))),
            hard_unsafe=hard_unsafe,
        )


def candidate_group_signature(rows: list[SchemeAP1Candidate]) -> str:
    return canonical_sha256(
        [
            {
                "candidate_id": row.candidate_id,
                "candidate_target": row.candidate_target,
                "target_kind": row.target_kind,
                "target_payload": list(row.target_payload),
                "source_kinds": list(row.source_kinds),
            }
            for row in sorted(rows, key=lambda item: item.candidate_id)
        ]
    )


__all__ = [
    "SCHEME_A_P1_CANDIDATE_SCHEMA",
    "SCHEME_A_P1_DATASET_SCHEMA",
    "SchemeAP1Candidate",
    "SchemeAP1CandidateConfig",
    "SchemeAP1DatasetConfig",
    "SchemeAP1OOFConfig",
    "candidate_group_signature",
]
