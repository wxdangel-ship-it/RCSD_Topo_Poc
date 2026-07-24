from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_models import (
    SchemeAP2P3P2Config,
)


SCHEME_A_P2_P3_P9_SCHEMA = (
    "p05-scheme-a-p2-p3-p9-carrier-only-source-adapter-v1"
)
DECISION_CARRIER_MODEL_GO_CLUE_BLOCKED = (
    "P05_SCHEME_A_P2_P3_P9_CARRIER_MODEL_GO_CLUE_BLOCKED"
)
DECISION_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED = (
    "P05_SCHEME_A_P2_P3_P9_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED"
)
DECISION_PROMOTION_MODEL_NO_GO = (
    "P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P9_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P9Config:
    engine_config: SchemeAP2P3P2Config
    p5_run_root: Path
    p7_run_root: Path
    p8_run_root: Path
    scheme_a_baseline_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_feature_count: int = 602
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_case_count: int = 51
    expected_source_applicable_count: int = 504
    expected_source_not_applicable_count: int = 5_771
    expected_promotion_field_count: int = 39
    expected_access_gate_count: int = 40
    adapter_hidden_dim: int = 96
    adapter_bottleneck_dim: int = 48
    adapter_dropout: float = 0.10
    adapter_learning_rate: float = 0.003
    adapter_weight_decay: float = 0.0002
    adapter_max_epochs: int = 40
    adapter_patience: int = 7
    adapter_batch_group_count: int = 512
    adapter_max_parameter_count: int = 300_000
    total_max_parameter_count: int = 3_200_000
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        base = self.engine_config.base_config
        if base.device != "cpu":
            raise ValueError("P9 formal training must use CPU")
        if base.expected_evidence_dim != self.expected_feature_count:
            raise ValueError("P9 Control evidence dimension differs")
        if len(base.model_seeds) != 3 or base.expected_fold_count != 5:
            raise ValueError("P9 requires exactly 3 seeds x 5 Case folds")
        if self.expected_eligible_count != (
            self.expected_source_applicable_count
            + self.expected_source_not_applicable_count
        ):
            raise ValueError("P9 source applicability denominators do not close")
        if min(
            self.adapter_hidden_dim,
            self.adapter_bottleneck_dim,
            self.adapter_max_epochs,
            self.adapter_patience,
            self.adapter_batch_group_count,
        ) < 1:
            raise ValueError("P9 adapter dimensions and limits must be positive")
        if not 0.0 <= self.adapter_dropout < 1.0:
            raise ValueError("adapter_dropout must be in [0, 1)")


def choose_p9_decision(
    *,
    audit_gate: bool,
    promotion_gate: bool,
    full_carrier_gate: bool,
) -> str:
    if not audit_gate:
        return DECISION_AUDIT_NO_GO
    if not promotion_gate:
        return DECISION_PROMOTION_MODEL_NO_GO
    if not full_carrier_gate:
        return DECISION_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED
    return DECISION_CARRIER_MODEL_GO_CLUE_BLOCKED


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_CARRIER_MODEL_GO_CLUE_BLOCKED",
    "DECISION_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED",
    "DECISION_PROMOTION_MODEL_NO_GO",
    "SCHEME_A_P2_P3_P9_SCHEMA",
    "SchemeAP2P3P9Config",
    "choose_p9_decision",
]
