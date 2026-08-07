from __future__ import annotations

from types import SimpleNamespace

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_coordination import (
    COORDINATION_ACCEPT,
    COORDINATION_FALLBACK,
    ArchClosureSegmentPlan,
    coordinate_arch_closure_plans,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    build_arch_closure_reference_stores,
)


def test_owner_conflict_fallback_stops_at_direct_junction_segments() -> None:
    anchors = {
        "a": SimpleNamespace(
            case_key="T10:1", anchor_id="a", dependency_anchor_ids=("a",)
        ),
        "b": SimpleNamespace(
            case_key="T10:1", anchor_id="b", dependency_anchor_ids=("b",)
        ),
    }
    segments = {
        "s1": SimpleNamespace(segment_id="s1", required_anchor_ids=("a",), fold=1),
        "s2": SimpleNamespace(
            segment_id="s2", required_anchor_ids=("a", "b"), fold=1
        ),
        "s3": SimpleNamespace(segment_id="s3", required_anchor_ids=("b",), fold=1),
    }
    examples = [
        SimpleNamespace(
            joint=SimpleNamespace(
                case_key="T10:1",
                ordinary_segments=(segment,),
                anchors=tuple(anchors.values()),
            ),
            ledger={"segment_id": segment_id},
            road_pool=SimpleNamespace(segment_id=segment_id),
            access_features_by_junction={},
            break_tasks=(),
        )
        for segment_id, segment in segments.items()
    ]
    stores = build_arch_closure_reference_stores(examples)
    plans = (
        ArchClosureSegmentPlan(
            key=("T10:1", "s1"),
            plan_id="p1",
            decision="USE_RCSD",
            road_ids=("shared",),
            owned_road_ids=("shared",),
        ),
        ArchClosureSegmentPlan(
            key=("T10:1", "s2"),
            plan_id="p2",
            decision="USE_RCSD",
            road_ids=("shared", "own2"),
            owned_road_ids=("shared", "own2"),
        ),
        ArchClosureSegmentPlan(
            key=("T10:1", "s3"),
            plan_id="p3",
            decision="KEEP_SWSD",
            road_ids=("own3",),
            owned_road_ids=("own3",),
        ),
    )

    result = coordinate_arch_closure_plans(stores, plans)

    assert result.status_by_segment[("T10:1", "s1")] == COORDINATION_FALLBACK
    assert result.status_by_segment[("T10:1", "s2")] == COORDINATION_FALLBACK
    assert result.status_by_segment[("T10:1", "s3")] == COORDINATION_ACCEPT
    assert result.fallback_segment_keys == (
        ("T10:1", "s1"),
        ("T10:1", "s2"),
    )
    assert result.maximum_fallback_expansion_hops == 1
