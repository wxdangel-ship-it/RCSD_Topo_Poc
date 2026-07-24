from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    canonical_sha256,
)


JSG_P3_CONTEXT_SCHEMA_VERSION = "p05-jsg-p3-group-context-v1"
JSG_P3_MODEL_SCHEMA_VERSION = "p05-jsg-p3-context-scorer-v1"


@dataclass(frozen=True)
class JSGP3DatasetConfig:
    p1_candidate_run_root: Path
    p2_dataset_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    expected_fold_count: int = 5
    expected_group_count: int = 191_331
    expected_candidate_count: int = 712_799
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")
        if self.expected_fold_count < 2:
            raise ValueError("expected_fold_count must be at least two")
        if self.expected_group_count < 1 or self.expected_candidate_count < 1:
            raise ValueError("expected group/candidate counts must be positive")


@dataclass(frozen=True)
class JSGP3OOFConfig:
    context_dataset_run_root: Path
    p2_dataset_run_root: Path
    p1_candidate_run_root: Path
    p1_oracle_run_root: Path
    p0_truth_run_root: Path
    r2_oracle_run_root: Path
    output_root: Path
    run_id: str
    seeds: tuple[int, ...] = (17, 29, 43)
    expected_case_count: int = 51
    expected_fold_count: int = 5
    embedding_dim: int = 128
    hidden_dim: int = 256
    type_embedding_dim: int = 32
    dropout: float = 0.10
    learning_rate: float = 0.002
    weight_decay: float = 0.0001
    max_epochs: int = 30
    patience: int = 5
    batch_group_count: int = 1024
    inner_validation_ratio: float = 0.15
    review_weight: float = 3.0
    max_parameter_count: int = 5_000_000
    device: str = "auto"
    torch_num_threads: int = 8
    strict_hashes: bool = True
    emit_reconstructed_gpkg: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if min(self.embedding_dim, self.hidden_dim, self.type_embedding_dim) < 1:
            raise ValueError("model dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid optimizer configuration")
        if min(self.max_epochs, self.patience, self.batch_group_count) < 1:
            raise ValueError("training limits must be positive")
        if not 0.0 < self.inner_validation_ratio < 0.5:
            raise ValueError("inner_validation_ratio must be in (0, 0.5)")
        if self.review_weight < 1.0:
            raise ValueError("review_weight must be at least one")
        if self.max_parameter_count < 1:
            raise ValueError("max_parameter_count must be positive")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto/cpu/cuda")


@dataclass(frozen=True)
class P3FoldVocabulary:
    candidate_tokens: Mapping[str, int]
    context_tokens: Mapping[str, int]
    object_types: Mapping[str, int]
    train_case_keys: tuple[str, ...]
    inner_validation_case_keys: tuple[str, ...]
    held_out_case_keys: tuple[str, ...]
    dataset_manifest_sha256: str
    unknown_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": "p05-jsg-p3-fold-vocabulary-v1",
            "candidate_tokens": dict(sorted(self.candidate_tokens.items())),
            "context_tokens": dict(sorted(self.context_tokens.items())),
            "object_types": dict(sorted(self.object_types.items())),
            "train_case_keys": list(self.train_case_keys),
            "inner_validation_case_keys": list(self.inner_validation_case_keys),
            "held_out_case_keys": list(self.held_out_case_keys),
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "unknown_index": self.unknown_index,
        }
        payload["vocabulary_signature"] = canonical_sha256(payload)
        return payload


__all__ = [
    "JSGP3DatasetConfig",
    "JSGP3OOFConfig",
    "JSG_P3_CONTEXT_SCHEMA_VERSION",
    "JSG_P3_MODEL_SCHEMA_VERSION",
    "P3FoldVocabulary",
]
