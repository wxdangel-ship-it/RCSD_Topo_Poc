from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = "p05-scheme-a-p2-p3-p13-p0-v1"
DECISION_MODEL_GO = "P05_SCHEME_A_P2_P3_P13_P0_MODEL_GO"
DECISION_SELECTION_NO_GO = (
    "P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO"
)
DECISION_SAFETY_NO_GO = (
    "P05_SCHEME_A_P2_P3_P13_P0_SAFETY_NO_GO"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P13_P0_AUDIT_NO_GO"


@dataclass(frozen=True)
class P13P0Config:
    r1_run_root: Path
    p12r_run_root: Path
    scheme_a_baseline_root: Path
    poc_data_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_r1_candidate_signature: str = (
        "84344d11cdc168cea42cdaacd0c36f83f9f4b57e45dd01b802a9c35ce064f734"
    )
    expected_object_count: int = 474
    expected_case_count: int = 6
    expected_fold_count: int = 5
    model_seeds: tuple[int, ...] = (17, 29, 43)
    encoder_hidden_dim: int = 256
    embedding_dim: int = 192
    context_dim: int = 96
    decoder_hidden_dim: int = 512
    decoder_bottleneck_dim: int = 256
    dropout: float = 0.10
    learning_rate: float = 0.002
    weight_decay: float = 0.0002
    max_epochs: int = 80
    patience: int = 10
    batch_group_count: int = 64
    torch_num_threads: int = 2
    min_parameter_count: int = 300_000
    max_parameter_count: int = 1_500_000
    min_raw_exact_accuracy: float = 0.95
    min_worst_fold_raw_exact_accuracy: float = 0.90
    min_candidate_macro_f1: float = 0.90
    min_object_macro_f1: float = 0.90
    min_accepted_coverage: float = 0.50
    min_worst_fold_accepted_coverage: float = 0.30
    max_training_wall_seconds: float = 900.0
    max_peak_rss_bytes: int = 4 * 1024**3

    def validate(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if len(self.model_seeds) != 3 or len(set(self.model_seeds)) != 3:
            raise ValueError("P13-P0 requires three distinct seeds")
        if self.expected_fold_count != 5:
            raise ValueError("P13-P0 requires five Case folds")
        if min(
            self.expected_object_count,
            self.expected_case_count,
            self.encoder_hidden_dim,
            self.embedding_dim,
            self.context_dim,
            self.decoder_hidden_dim,
            self.decoder_bottleneck_dim,
            self.max_epochs,
            self.patience,
            self.batch_group_count,
            self.torch_num_threads,
        ) <= 0:
            raise ValueError("P13-P0 dimensions and counts must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("optimizer configuration is invalid")
        if self.min_parameter_count > self.max_parameter_count:
            raise ValueError("parameter count gate is invalid")
        for name, value in (
            ("min_raw_exact_accuracy", self.min_raw_exact_accuracy),
            (
                "min_worst_fold_raw_exact_accuracy",
                self.min_worst_fold_raw_exact_accuracy,
            ),
            ("min_candidate_macro_f1", self.min_candidate_macro_f1),
            ("min_object_macro_f1", self.min_object_macro_f1),
            ("min_accepted_coverage", self.min_accepted_coverage),
            (
                "min_worst_fold_accepted_coverage",
                self.min_worst_fold_accepted_coverage,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


def choose_decision(
    *,
    audit_gate: bool,
    selection_gate: bool,
    safety_gate: bool,
) -> str:
    if not audit_gate:
        return DECISION_AUDIT_NO_GO
    if not selection_gate:
        return DECISION_SELECTION_NO_GO
    if not safety_gate:
        return DECISION_SAFETY_NO_GO
    return DECISION_MODEL_GO


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_MODEL_GO",
    "DECISION_SAFETY_NO_GO",
    "DECISION_SELECTION_NO_GO",
    "P13P0Config",
    "SCHEMA_VERSION",
    "choose_decision",
]
