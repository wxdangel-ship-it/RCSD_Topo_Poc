from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


JSG_P2_DATASET_SCHEMA_VERSION = "p05-jsg-p2-dataset-v1"
JSG_P2_MODEL_SCHEMA_VERSION = "p05-jsg-p2-linear-model-v1"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class JSGP2DatasetConfig:
    p1_candidate_run_root: Path
    p1_oracle_run_root: Path
    m0_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    expected_fold_count: int = 5
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")
        if self.expected_fold_count < 2:
            raise ValueError("expected_fold_count must be at least two")


@dataclass(frozen=True)
class JSGP2OOFConfig:
    dataset_run_root: Path
    p1_candidate_run_root: Path
    p1_oracle_run_root: Path
    p0_truth_run_root: Path
    r2_oracle_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    expected_fold_count: int = 5
    smoothing: float = 1.0
    strict_hashes: bool = True
    emit_reconstructed_gpkg: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")
        if self.expected_fold_count < 2:
            raise ValueError("expected_fold_count must be at least two")
        if self.smoothing <= 0:
            raise ValueError("smoothing must be positive")


@dataclass(frozen=True)
class P2LinearModel:
    held_out_fold: int
    bias: float
    feature_weights: Mapping[str, float]
    smoothing: float
    train_case_keys: tuple[str, ...]
    held_out_case_keys: tuple[str, ...]
    train_weighted_positive: float
    train_weighted_negative: float
    dataset_manifest_sha256: str
    schema_version: str = JSG_P2_MODEL_SCHEMA_VERSION

    def score(self, tokens: tuple[str, ...] | list[str]) -> float:
        unique = tuple(sorted(set(tokens)))
        if not unique:
            return self.bias
        return self.bias + sum(float(self.feature_weights.get(token, 0.0)) for token in unique) / len(
            unique
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "held_out_fold": self.held_out_fold,
            "bias": self.bias,
            "feature_weights": dict(sorted(self.feature_weights.items())),
            "smoothing": self.smoothing,
            "train_case_keys": list(self.train_case_keys),
            "held_out_case_keys": list(self.held_out_case_keys),
            "train_weighted_positive": self.train_weighted_positive,
            "train_weighted_negative": self.train_weighted_negative,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
        }
        payload["model_signature"] = canonical_sha256(payload)
        return payload

    @property
    def model_signature(self) -> str:
        return str(self.to_dict()["model_signature"])


def output_path(record: Mapping[str, Any]) -> Path:
    return Path(str(record.get("path") or ""))


__all__ = [
    "JSGP2DatasetConfig",
    "JSGP2OOFConfig",
    "JSG_P2_DATASET_SCHEMA_VERSION",
    "JSG_P2_MODEL_SCHEMA_VERSION",
    "P2LinearModel",
    "canonical_json_bytes",
    "canonical_sha256",
]
