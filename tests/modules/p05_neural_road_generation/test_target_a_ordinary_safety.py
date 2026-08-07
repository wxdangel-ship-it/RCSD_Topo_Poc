import math

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_safety import (
    migrate_legacy_ordinary_arm_projection,
    truth_free_junction_neighbor_context,
    zero_unsafe_calibration_threshold,
)


def test_legacy_arm_projection_migration_preserves_global_halves() -> None:
    old = torch.arange(64, dtype=torch.float32).reshape(2, 32)
    target = torch.full((2, 44), -1.0)
    migrated = migrate_legacy_ordinary_arm_projection(
        {"ordinary_plan_arm_projection.0.weight": old},
        {"ordinary_plan_arm_projection.0.weight": target},
    )["ordinary_plan_arm_projection.0.weight"]

    assert migrated.shape == (2, 44)
    assert torch.equal(migrated[:, :16], old[:, :16])
    assert torch.equal(migrated[:, 22:38], old[:, 16:])
    assert torch.count_nonzero(migrated[:, 16:22]) == 0
    assert torch.count_nonzero(migrated[:, 38:44]) == 0


def test_matching_arm_projection_requires_no_migration() -> None:
    weight = torch.randn(2, 44)
    result = migrate_legacy_ordinary_arm_projection(
        {"ordinary_plan_arm_projection.0.weight": weight},
        {"ordinary_plan_arm_projection.0.weight": torch.zeros_like(weight)},
    )
    assert result["ordinary_plan_arm_projection.0.weight"] is weight


def test_zero_unsafe_threshold_is_strictly_above_inner_unsafe() -> None:
    threshold, reason = zero_unsafe_calibration_threshold(
        [
            {"safe": True, "safety_score": 0.95},
            {"safe": False, "safety_score": 0.81},
            {"safe": False, "safety_score": 0.72},
        ]
    )
    assert threshold > 0.81
    assert math.nextafter(0.81, 1.0) == threshold
    assert reason == "ABOVE_MAX_INNER_UNSAFE"


def test_calibration_without_unsafe_rejects_all_use() -> None:
    threshold, reason = zero_unsafe_calibration_threshold(
        [{"safe": True, "safety_score": 0.99}]
    )
    assert threshold == 1.0
    assert reason == "NO_UNSAFE_IN_INNER_CALIBRATION"


def test_neighbor_context_uses_all_truth_free_standard_groups() -> None:
    def group(
        segment_id: str,
        *,
        anchor: str,
        value: float,
        segment_type: str = "STANDARD",
    ) -> dict:
        return {
            "case_key": "T10:case",
            "segment_id": segment_id,
            "segment_type": segment_type,
            "required_anchor_ids": [anchor],
            "object_features": [value] * 64,
            "candidates": [
                {
                    "decision": "USE_RCSD",
                    "hard_valid": True,
                    "features": [value] * 64,
                }
            ],
        }

    targets = [
        {
            "sample_id": "T10:case:segment-a",
            "case_key": "T10:case",
            "segment_id": "segment-a",
            "required_anchor_ids": ["junction-1"],
        }
    ]
    first = truth_free_junction_neighbor_context(
        targets,
        [
            group("segment-a", anchor="junction-1", value=0.1),
            group("segment-b", anchor="junction-1", value=0.8),
            group(
                "advance",
                anchor="junction-1",
                value=1.0,
                segment_type="ADVANCE_RIGHT",
            ),
        ],
    )["T10:case:segment-a"]
    second = truth_free_junction_neighbor_context(
        targets,
        [
            group(
                "advance",
                anchor="junction-1",
                value=1.0,
                segment_type="ADVANCE_RIGHT",
            ),
            group("segment-b", anchor="junction-1", value=0.8),
            group("segment-a", anchor="junction-1", value=0.1),
        ],
    )["T10:case:segment-a"]

    assert first == second
    assert len(first) == 116
    assert first[1] == 0.8
    assert first[59] == 0.8
    assert min(first) >= 0.0
