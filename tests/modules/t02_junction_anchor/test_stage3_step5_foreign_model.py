from __future__ import annotations

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step5_foreign_model import (
    resolve_stage3_step5_contract_decision,
)


def test_step5_contract_downgrades_small_residual_outside_rc_overlap_to_nonblocking() -> None:
    decision = resolve_stage3_step5_contract_decision(
        step5_result=Stage3Step5ForeignModelResult(
            foreign_baseline_established=True,
            blocking_foreign_established=True,
            canonical_foreign_established=True,
            canonical_foreign_reason="foreign_outside_drivezone_soft_excluded",
            foreign_subtype="outside_drivezone_or_corridor",
            soft_excluded_rc_corridor_trim_applied=True,
        ),
        step6_result=Stage3Step6GeometrySolveResult(
            geometry_established=True,
            geometry_review_reason="outside_rc_gap_requires_review",
            residual_step5_blocking_foreign_required=False,
            foreign_overlap_metric_m=1.95,
            remaining_foreign_semantic_node_ids=frozenset(),
            remaining_foreign_road_arm_corridor_ids=frozenset(),
            foreign_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
        ),
    )

    assert decision.foreign_baseline_established is True
    assert decision.residual_foreign_present is True
    assert decision.canonical_foreign_established is False
    assert decision.canonical_foreign_reason is None
    assert (
        "step5_canonical_downgraded_after_step6_small_residual_overlap"
        in decision.audit_facts
    )


def test_step5_contract_keeps_tail_context_blocking_even_with_small_residual_overlap() -> None:
    decision = resolve_stage3_step5_contract_decision(
        step5_result=Stage3Step5ForeignModelResult(
            foreign_baseline_established=True,
            blocking_foreign_established=True,
            canonical_foreign_established=True,
            canonical_foreign_reason="foreign_tail_after_opposite_lane_trim",
            foreign_subtype="tail_after_opposite_lane_trim",
            foreign_tail_length_m=2.0,
            foreign_overlap_zero_but_tail_present=True,
        ),
        step6_result=Stage3Step6GeometrySolveResult(
            geometry_established=True,
            geometry_review_reason="outside_rc_gap_requires_review",
            residual_step5_blocking_foreign_required=False,
            foreign_overlap_metric_m=1.5,
            remaining_foreign_semantic_node_ids=frozenset(),
            remaining_foreign_road_arm_corridor_ids=frozenset(),
            foreign_tail_length_m=1.0,
            foreign_overlap_zero_but_tail_present=True,
        ),
    )

    assert decision.canonical_foreign_established is True
    assert decision.canonical_foreign_reason == "foreign_tail_after_opposite_lane_trim"
