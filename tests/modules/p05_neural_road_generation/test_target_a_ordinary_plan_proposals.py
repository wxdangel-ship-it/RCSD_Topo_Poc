from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    PLAN_PROPOSAL_FEATURE_DIM,
    STATIC_PLAN_FEATURE_DIM,
    StaticOrdinaryPlan,
    build_ordinary_plan_proposal_example,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISION_INDEX,
    OrdinaryRoadSetExample,
)


def _example(
    *,
    road_ids: tuple[str, ...],
    sources: tuple[str, ...],
    target_indices: tuple[int, ...],
) -> OrdinaryRoadSetExample:
    count = len(road_ids)
    return OrdinaryRoadSetExample(
        case_key="T10:case",
        segment_id="segment",
        fold=2,
        object_features=(1.0,),
        road_ids=road_ids,
        sources=sources,
        start_node_ids=tuple(f"n{index}a" for index in range(count)),
        end_node_ids=tuple(f"n{index}b" for index in range(count)),
        anchor_features=((1.0,),),
        teacher_anchor_relations=tuple(((1.0,),) for _ in road_ids),
        oof_anchor_relations=tuple(((1.0,),) for _ in road_ids),
        teacher_features=tuple((float(index),) for index in range(count)),
        oof_features=tuple((float(index),) for index in range(count)),
        decision=DECISION_INDEX["USE_RCSD"],
        target_indices=target_indices,
        ownership_targets=(0,) * count,
        ownership_task_mask=(False,) * count,
        business_role_targets=(0,) * count,
        business_role_task_mask=(False,) * count,
        sample_weight=0.7,
        oof_anchor_release_ready=True,
    )


def _base_prediction(
    row: OrdinaryRoadSetExample,
    probabilities: tuple[float, ...],
) -> dict[str, object]:
    return {
        "candidate_road_ids": list(row.road_ids),
        "candidate_sources": list(row.sources),
        "candidate_member_probabilities": list(probabilities),
        "predicted_decision": "USE_RCSD",
        "predicted_cardinality": 1,
        "decision_confidence": 0.8,
    }


def test_static_and_member_prefix_proposals_reach_complete_target() -> None:
    row = _example(
        road_ids=("s0", "r0", "r1"),
        sources=("SWSD", "RCSD", "RCSD"),
        target_indices=(1, 2),
    )
    static = (
        StaticOrdinaryPlan(
            plan_id="static-use-one",
            decision="USE_RCSD",
            road_ids=("r0",),
            features=(0.25,) * STATIC_PLAN_FEATURE_DIM,
        ),
        StaticOrdinaryPlan(
            plan_id="static-keep",
            decision="KEEP_SWSD",
            road_ids=("s0",),
            features=(0.5,) * STATIC_PLAN_FEATURE_DIM,
        ),
    )

    result = build_ordinary_plan_proposal_example(
        row=row,
        base_prediction=_base_prediction(row, (0.1, 0.9, 0.8)),
        static_plans=static,
        maximum_prefix_cardinality=3,
    )

    assert result.proposal_decisions[0] == "ABSTAIN"
    assert result.target_reachable
    assert result.acceptable_indices != (0,)
    assert {
        (
            result.proposal_decisions[index],
            result.proposal_road_ids[index],
        )
        for index in result.acceptable_indices
    } == {("USE_RCSD", ("r0", "r1"))}
    assert all(
        len(values) == PLAN_PROPOSAL_FEATURE_DIM
        for values in result.proposal_features
    )
    assert len(result.proposal_ids) == len(set(result.proposal_ids))


def test_unreachable_target_teaches_explicit_abstain() -> None:
    row = _example(
        road_ids=("r0", "r1", "r2"),
        sources=("RCSD", "RCSD", "RCSD"),
        target_indices=(0, 2),
    )

    result = build_ordinary_plan_proposal_example(
        row=row,
        base_prediction=_base_prediction(row, (0.8, 0.9, 0.7)),
        static_plans=(),
        maximum_prefix_cardinality=3,
    )

    assert not result.target_reachable
    assert result.acceptable_indices == (0,)
    assert result.proposal_decisions[0] == "ABSTAIN"
    assert result.proposal_road_ids[0] == ()
