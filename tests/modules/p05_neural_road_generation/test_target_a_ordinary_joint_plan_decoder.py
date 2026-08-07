from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    FallbackScope,
    RoadRole,
    SegmentDecision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_plan_decoder import (
    adapt_joint_plan_prediction,
    decode_joint_plan_candidates,
    multi_plan_conflict_components,
)


def _alternative(
    *,
    proposal_id: str,
    road_id: str,
    probability: float,
    ownership: str = "OWNER_CURRENT_SEGMENT",
    role: str = "MAIN",
) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "decision": "USE_RCSD",
        "road_ids": [road_id],
        "road_business_assignments": [
            {
                "road_id": road_id,
                "source": "RCSD",
                "start_node_id": "a",
                "end_node_id": "b",
                "ownership": ownership,
                "business_role": role,
            }
        ],
        "probability": probability,
    }


def _prediction(
    segment_id: str,
    alternatives: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "case_key": "T10:case",
        "segment_id": segment_id,
        "accepted": True,
        "top_plan_candidates": alternatives,
    }


def test_adapter_keeps_ownership_and_role_as_separate_outputs() -> None:
    valid, failures = adapt_joint_plan_prediction(
        _prediction(
            "s1",
            [
                {
                    "proposal_id": "valid",
                    "decision": "USE_RCSD",
                    "road_ids": ["r1", "r2"],
                    "road_business_assignments": [
                        {
                            "road_id": "r1",
                            "source": "RCSD",
                            "start_node_id": "a",
                            "end_node_id": "b",
                            "ownership": "OWNER_CURRENT_SEGMENT",
                            "business_role": "MAIN",
                        },
                        {
                            "road_id": "r2",
                            "source": "RCSD",
                            "start_node_id": "b",
                            "end_node_id": "c",
                            "ownership": "OWNER_CURRENT_SEGMENT",
                            "business_role": "INTERNAL_CONNECTOR",
                        },
                    ],
                    "probability": 0.8,
                },
                _alternative(
                    proposal_id="no-owner",
                    road_id="r3",
                    probability=0.7,
                    ownership="NO_OWNER_JUNCTION_CONNECTIVITY",
                ),
            ],
        ),
        required_anchor_ids=("a1",),
        release_top_k=2,
    )

    assert [row.plan.plan_id for row in valid] == ["valid"]
    assert valid[0].plan.roads[1].role is RoadRole.INTERNAL_CONNECTOR
    assert valid[0].plan.roads[0].owner_segment_id == "s1"
    assert any("lacks current-Segment ownership" in row for row in failures)


def test_explicit_attached_swsd_promotes_only_formal_t06_mixed() -> None:
    prediction = _prediction(
        "s1",
        [
            {
                "proposal_id": "mixed",
                "decision": "USE_RCSD",
                "road_ids": ["r1", "s1"],
                "road_business_assignments": [
                    {
                        "road_id": "r1",
                        "source": "RCSD",
                        "start_node_id": "a",
                        "end_node_id": "b",
                        "ownership": "OWNER_CURRENT_SEGMENT",
                        "business_role": "MAIN",
                    },
                    {
                        "road_id": "s1",
                        "source": "SWSD",
                        "start_node_id": "c",
                        "end_node_id": "d",
                        "ownership": "OWNER_CURRENT_SEGMENT",
                        "business_role": "ATTACHED_SWSD",
                    },
                ],
                "probability": 0.9,
            }
        ],
    )

    plans, failures = adapt_joint_plan_prediction(
        prediction,
        required_anchor_ids=(),
    )

    assert not failures
    assert (
        plans[0].plan.decision
        is SegmentDecision.T06_MAIN_RCSD_ATTACHED_SWSD
    )


def test_invalid_top1_does_not_release_unqualified_top2() -> None:
    prediction = _prediction(
        "s1",
        [
            _alternative(
                proposal_id="invalid-top1",
                road_id="r1",
                probability=0.9,
                ownership="NO_OWNER_JUNCTION_CONNECTIVITY",
            ),
            _alternative(
                proposal_id="unqualified-top2",
                road_id="r2",
                probability=0.8,
            ),
        ],
    )

    plans, failures = adapt_joint_plan_prediction(
        prediction,
        required_anchor_ids=(),
    )
    diagnostic_plans, _ = adapt_joint_plan_prediction(
        prediction,
        required_anchor_ids=(),
        release_top_k=2,
    )

    assert not plans
    assert failures
    assert [
        value.plan.plan_id for value in diagnostic_plans
    ] == ["unqualified-top2"]


def test_conflict_component_decoder_falls_back_only_losing_segment() -> None:
    first, _ = adapt_joint_plan_prediction(
        _prediction(
            "s1",
            [_alternative(
                proposal_id="p1",
                road_id="shared",
                probability=0.9,
            )],
        ),
        required_anchor_ids=(),
    )
    second, _ = adapt_joint_plan_prediction(
        _prediction(
            "s2",
            [_alternative(
                proposal_id="p2",
                road_id="shared",
                probability=0.8,
            )],
        ),
        required_anchor_ids=(),
    )
    third, _ = adapt_joint_plan_prediction(
        _prediction(
            "s3",
            [_alternative(
                proposal_id="p3",
                road_id="isolated",
                probability=0.7,
            )],
        ),
        required_anchor_ids=(),
    )
    candidates = {
        ("T10:case", "s1"): first,
        ("T10:case", "s2"): second,
        ("T10:case", "s3"): third,
    }

    components = multi_plan_conflict_components(candidates)
    decoded, rows = decode_joint_plan_candidates(candidates)

    assert components == (
        (("T10:case", "s1"), ("T10:case", "s2")),
        (("T10:case", "s3"),),
    ) or components == [
        (("T10:case", "s1"), ("T10:case", "s2")),
        (("T10:case", "s3"),),
    ]
    assert decoded[("T10:case", "s1")].automatic
    assert (
        decoded[("T10:case", "s2")].fallback_scope
        is FallbackScope.SEGMENT
    )
    assert decoded[("T10:case", "s3")].automatic
    assert max(row["segment_count"] for row in rows) == 2
