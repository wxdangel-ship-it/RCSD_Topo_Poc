from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_decoder_audit import (
    dependency_conflict_components,
    ordinary_business_exact,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    ScoredPlan,
    SegmentDecision,
)


def _candidate(case: str, segment: str, road: str) -> ScoredPlan:
    del case
    return ScoredPlan(
        PlanCandidate(
            plan_id=f"p:{segment}",
            segment_id=segment,
            decision=SegmentDecision.USE_RCSD,
            roads=(
                RoadUse(
                    RoadSource.RCSD,
                    road,
                    RoadRole.MAIN,
                    segment,
                    0,
                ),
            ),
            source_access_road_id=road,
            target_access_road_id=road,
        ),
        1.0,
    )


def test_decoder_components_use_only_shared_road_ownership() -> None:
    candidates = {
        ("case", "s1"): _candidate("case", "s1", "shared"),
        ("case", "s2"): _candidate("case", "s2", "shared"),
        ("case", "s3"): _candidate("case", "s3", "other"),
    }
    assert dependency_conflict_components(candidates) == [
        (("case", "s1"), ("case", "s2")),
        (("case", "s3"),),
    ]


def test_business_exact_accepts_any_formal_complete_road_target() -> None:
    state = {
        "raw_carrier_decision": "USE_RCSD",
        "complete_road_ids": ["r2", "r1"],
    }
    label = {
        "training_task_mask": True,
        "acceptable_complete_road_targets": [
            {"decision": "KEEP_SWSD", "road_ids": ["s"]},
            {"decision": "USE_RCSD", "road_ids": ["r1", "r2"]},
        ],
    }
    assert ordinary_business_exact(state, label)
    assert ordinary_business_exact(
        state,
        {"training_task_mask": False},
    ) is None
