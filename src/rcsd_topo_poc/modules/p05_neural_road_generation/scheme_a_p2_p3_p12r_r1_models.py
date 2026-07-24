from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class P12RR1Config:
    expected_object_count: int = 474
    expected_case_count: int = 6
    fold_count: int = 5
    local_distance_m: float = 5.0
    sequential_gap_m: float = 1.0
    parallel_endpoint_gap_m: float = 5.0
    owner_carrier_distance_m: float = 10.0
    orientation_tie_epsilon_m: float = 1e-6
    min_overall_oracle_recall: float = 0.95
    min_worst_fold_oracle_recall: float = 0.90
    max_candidate_count_p95: int = 10
    max_candidate_count_per_object: int = 32
    max_wall_seconds: float = 300.0
    max_peak_rss_bytes: int = 1024**3

    def validate(self) -> None:
        if self.expected_object_count <= 0:
            raise ValueError("expected_object_count must be positive")
        if self.expected_case_count <= 0:
            raise ValueError("expected_case_count must be positive")
        if self.fold_count <= 0:
            raise ValueError("fold_count must be positive")
        for name, value in (
            ("local_distance_m", self.local_distance_m),
            ("sequential_gap_m", self.sequential_gap_m),
            ("parallel_endpoint_gap_m", self.parallel_endpoint_gap_m),
            ("owner_carrier_distance_m", self.owner_carrier_distance_m),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.orientation_tie_epsilon_m < 0:
            raise ValueError(
                "orientation_tie_epsilon_m must be non-negative"
            )
        if not 0 < self.min_overall_oracle_recall <= 1:
            raise ValueError("min_overall_oracle_recall is invalid")
        if not 0 < self.min_worst_fold_oracle_recall <= 1:
            raise ValueError("min_worst_fold_oracle_recall is invalid")
        if self.max_candidate_count_p95 <= 0:
            raise ValueError("max_candidate_count_p95 must be positive")
        if self.max_candidate_count_per_object <= 0:
            raise ValueError(
                "max_candidate_count_per_object must be positive"
            )
