from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_decoder import (
    FallbackDirective,
    StructuredRoadGraphDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorDecision,
    AnchorStatus,
    FallbackScope,
    PlanCandidate,
    RoadRole,
    RoadSource,
    RoadUse,
    ScoredPlan,
    SegmentDecision,
)


def _road(segment: str, road_id: str, source: RoadSource) -> RoadUse:
    return RoadUse(
        source_kind=source,
        source_road_id=road_id,
        role=RoadRole.MAIN,
        owner_segment_id=segment,
        direction=2,
    )


def _ordinary(
    segment: str,
    plan_id: str,
    road_id: str,
    *,
    source: RoadSource = RoadSource.RCSD,
    anchor: str = "a",
) -> ScoredPlan:
    decision = (
        SegmentDecision.USE_RCSD
        if source is RoadSource.RCSD
        else SegmentDecision.KEEP_SWSD
    )
    return ScoredPlan(
        PlanCandidate(
            plan_id=plan_id,
            segment_id=segment,
            decision=decision,
            roads=(_road(segment, road_id, source),),
            source_access_road_id=road_id,
            target_access_road_id=road_id,
            required_anchor_ids=(anchor,),
        ),
        score=1.0,
    )


def test_decoder_enforces_unique_final_road_piece_ownership() -> None:
    candidates = {
        "s1": [_ordinary("s1", "p1", "shared")],
        "s2": [_ordinary("s2", "p2", "shared")],
    }
    anchors = {"a": AnchorDecision("a", AnchorStatus.SUCCESS, "c")}
    result = StructuredRoadGraphDecoder().decode(
        ordinary_candidates=candidates,
        advance_right_candidates={},
        anchor_decisions=anchors,
    )
    assert sum(row.automatic for row in result.ordinary) == 1
    assert len(result.fallback_segment_ids) == 1


def test_decoder_does_not_allow_road_score_to_bypass_anchor() -> None:
    candidates = {"s1": [_ordinary("s1", "p1", "r1")]}
    result = StructuredRoadGraphDecoder().decode(
        ordinary_candidates=candidates,
        advance_right_candidates={},
        anchor_decisions={"a": AnchorDecision("a", AnchorStatus.AMBIGUOUS)},
    )
    assert result.ordinary[0].selected_plan.decision is SegmentDecision.ABSTAIN
    assert result.ordinary[0].reason == "NO_CONFLICT_FREE_COMPLETE_PLAN"


def test_decoder_conditions_advance_right_on_locked_ordinary_access() -> None:
    ordinary = {
        "left": [_ordinary("left", "left-p", "left-r", source=RoadSource.RCSD)],
        "right": [_ordinary("right", "right-p", "right-r", source=RoadSource.RCSD)],
    }
    ar_plan = PlanCandidate(
        plan_id="ar-p",
        segment_id="ar",
        decision=SegmentDecision.USE_RCSD,
        roads=(
            RoadUse(
                RoadSource.RCSD,
                "ar-r",
                RoadRole.ADVANCE_RIGHT,
                "ar",
                2,
            ),
        ),
        source_access_road_id="left-r",
        target_access_road_id="right-r",
        node_recipes=(
            {"source_segment_id": "left", "target_segment_id": "right"},
        ),
        source_condition=(RoadSource.RCSD, RoadSource.RCSD),
    )
    result = StructuredRoadGraphDecoder().decode(
        ordinary_candidates=ordinary,
        advance_right_candidates={"ar": [ScoredPlan(ar_plan, 2.0)]},
        anchor_decisions={"a": AnchorDecision("a", AnchorStatus.SUCCESS, "c")},
    )
    assert result.advance_right[0].automatic
    assert result.advance_right[0].selected_plan.plan_id == "ar-p"


def test_advance_right_mixed_splice_is_a_dedicated_conditioned_plan() -> None:
    plan = PlanCandidate(
        plan_id="ar-mixed",
        segment_id="ar",
        decision=SegmentDecision.ADVANCE_RIGHT_MIXED_SPLICE,
        roads=(
            RoadUse(
                RoadSource.RCSD,
                "ar-rcsd",
                RoadRole.ADVANCE_RIGHT,
                "ar",
                2,
            ),
            RoadUse(
                RoadSource.SWSD,
                "ar-swsd",
                RoadRole.ADVANCE_RIGHT,
                "ar",
                2,
            ),
        ),
        source_access_road_id="left-rcsd",
        target_access_road_id="right-swsd",
        source_condition=(RoadSource.RCSD, RoadSource.SWSD),
    )
    plan.validate(advance_right=True)
    with pytest.raises(
        ValueError,
        match="cannot describe an ordinary Segment",
    ):
        plan.validate()


def test_keep_is_positive_plan_and_abstain_is_fallback() -> None:
    keep = _ordinary("s1", "keep", "swsd", source=RoadSource.SWSD)
    result = StructuredRoadGraphDecoder().decode(
        ordinary_candidates={"s1": [keep]},
        advance_right_candidates={},
        anchor_decisions={"a": AnchorDecision("a", AnchorStatus.SUCCESS, "c")},
    )
    assert result.ordinary[0].automatic
    assert result.ordinary[0].selected_plan.decision is SegmentDecision.KEEP_SWSD


def test_only_explicit_t06_attached_swsd_plan_may_mix_sources() -> None:
    roads = (
        _road("s1", "rcsd-main", RoadSource.RCSD),
        RoadUse(
            RoadSource.SWSD,
            "swsd-side",
            RoadRole.ATTACHED_SWSD,
            "s1",
            2,
        ),
    )
    mixed = PlanCandidate(
        "mixed",
        "s1",
        SegmentDecision.T06_MAIN_RCSD_ATTACHED_SWSD,
        roads,
        "rcsd-main",
        "rcsd-main",
    )
    mixed.validate()
    generic_use = PlanCandidate(
        "invalid",
        "s1",
        SegmentDecision.USE_RCSD,
        roads,
        "rcsd-main",
        "rcsd-main",
    )
    with pytest.raises(ValueError, match="must not retain any SWSD"):
        generic_use.validate()


def test_segment_fallback_stops_at_the_segment() -> None:
    ordinary = {
        "s1": [_ordinary("s1", "s1-p", "s1-r")],
        "s2": [_ordinary("s2", "s2-p", "s2-r")],
    }
    result = StructuredRoadGraphDecoder().decode(
        ordinary_candidates=ordinary,
        advance_right_candidates={},
        anchor_decisions={"a": AnchorDecision("a", AnchorStatus.SUCCESS, "c")},
        fallback_directives=(
            FallbackDirective(
                "segment:s1",
                FallbackScope.SEGMENT,
                ("s1",),
                reason="SEGMENT_EVIDENCE_CONFLICT",
            ),
        ),
    )
    by_id = {row.segment_id: row for row in result.ordinary}
    assert by_id["s1"].fallback_scope is FallbackScope.SEGMENT
    assert by_id["s2"].automatic


def test_junction_fallback_stops_at_direct_segments_in_chain() -> None:
    ordinary = {
        "s1": [_ordinary("s1", "s1-p", "s1-r")],
        "s2": [_ordinary("s2", "s2-p", "s2-r")],
    }
    result = StructuredRoadGraphDecoder().decode(
        ordinary_candidates=ordinary,
        advance_right_candidates={},
        anchor_decisions={"a": AnchorDecision("a", AnchorStatus.SUCCESS, "c")},
        fallback_directives=(
            FallbackDirective(
                "junction:j1",
                FallbackScope.JUNCTION,
                ("s1",),
                junction_id="j1",
                reason="JUNCTION_TOPOLOGY_CONFLICT",
            ),
        ),
        junction_direct_segments={
            "j1": ("s1",),
            "j2": ("s1", "s2"),
        },
    )
    by_id = {row.segment_id: row for row in result.ordinary}
    assert by_id["s1"].fallback_scope is FallbackScope.JUNCTION
    assert by_id["s2"].automatic


def test_junction_fallback_rejects_cross_boundary_segment() -> None:
    ordinary = {
        "s1": [_ordinary("s1", "s1-p", "s1-r")],
        "s2": [_ordinary("s2", "s2-p", "s2-r")],
    }
    with pytest.raises(ValueError, match="crosses its frozen T01 direct"):
        StructuredRoadGraphDecoder().decode(
            ordinary_candidates=ordinary,
            advance_right_candidates={},
            anchor_decisions={
                "a": AnchorDecision("a", AnchorStatus.SUCCESS, "c")
            },
            fallback_directives=(
                FallbackDirective(
                    "junction:j1",
                    FallbackScope.JUNCTION,
                    ("s1", "s2"),
                    junction_id="j1",
                ),
            ),
            junction_direct_segments={
                "j1": ("s1",),
                "j2": ("s1", "s2"),
            },
        )
