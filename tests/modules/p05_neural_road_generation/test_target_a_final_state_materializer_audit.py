from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_final_state_materializer_audit import (
    prepare_positive_swsd_instruction,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    GeometrySlice,
    NodeRecipe,
    NodeRecipeKind,
    RoadInstruction,
    RoadRole,
    RoadSource,
    SegmentDecision,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
)


def _fallback() -> SegmentMaterializationInstruction:
    roads = tuple(
        RoadInstruction(
            instruction_id=f"instruction-{road_id}",
            owner_segment_id="advance",
            role=RoadRole.ADVANCE_RIGHT,
            direction=2,
            geometry_slices=(
                GeometrySlice(
                    source_kind=RoadSource.SWSD,
                    source_road_id=road_id,
                    start_position_m=0.0,
                ),
            ),
            source_node_recipe=NodeRecipe(
                kind=NodeRecipeKind.COPY_SOURCE_NODE,
                source_kind=RoadSource.SWSD,
                source_node_id=f"{road_id}-start",
            ),
            target_node_recipe=NodeRecipe(
                kind=NodeRecipeKind.COPY_SOURCE_NODE,
                source_kind=RoadSource.SWSD,
                source_node_id=f"{road_id}-end",
            ),
        )
        for road_id in ("a", "b")
    )
    return SegmentMaterializationInstruction(
        segment_id="advance",
        segment_type=SegmentMaterializationType.ADVANCE_RIGHT,
        decision=SegmentDecision.ABSTAIN,
        roads=roads,
        fallback_applied=True,
    )


def test_exact_swsd_selection_only_reclassifies_fallback_status() -> None:
    fallback = _fallback()
    positive = prepare_positive_swsd_instruction(
        fallback,
        selected_road_ids=["b", "a"],
    )
    assert positive.decision is SegmentDecision.KEEP_SWSD
    assert not positive.fallback_applied
    assert positive.roads == fallback.roads


def test_partial_swsd_selection_cannot_become_positive() -> None:
    with pytest.raises(
        ValueError,
        match="selected SWSD Roads differ",
    ):
        prepare_positive_swsd_instruction(
            _fallback(),
            selected_road_ids=["a"],
        )
