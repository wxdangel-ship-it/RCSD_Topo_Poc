from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
)


def _frozen_ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        str(value)
        for value in values
        if value is not None and str(value).strip()
    )


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value)
                for value in values
                if value is not None and str(value).strip()
            }
        )
    )


def derive_stage3_step5_foreign_subtype(
    acceptance_reason: str | None,
    *,
    foreign_overlap_metric_m: float | None = None,
    foreign_tail_length_m: float | None = None,
    foreign_strip_extent_m: float | None = None,
    foreign_overlap_zero_but_tail_present: bool | None = None,
    single_sided_unrelated_opposite_lane_trim_applied: bool = False,
    soft_excluded_rc_corridor_trim_applied: bool = False,
    foreign_overlap_by_id: Mapping[str, float] | None = None,
    foreign_semantic_node_ids: Iterable[str] = (),
    foreign_road_arm_corridor_ids: Iterable[str] = (),
    foreign_rc_context_ids: Iterable[str] = (),
) -> str | None:
    if acceptance_reason == "foreign_tail_after_opposite_lane_trim":
        return "tail_after_opposite_lane_trim"
    if acceptance_reason == "foreign_corridor_intrusion":
        return "corridor_intrusion"
    if acceptance_reason == "foreign_semantic_road_overlap":
        return "semantic_road_overlap"
    if acceptance_reason == "foreign_outside_drivezone_soft_excluded":
        return "outside_drivezone_or_corridor"
    overlap_by_id = {
        str(road_id): float(length)
        for road_id, length in (foreign_overlap_by_id or {}).items()
        if road_id is not None
    }
    if (foreign_tail_length_m is not None and foreign_tail_length_m > 0.0) or (
        foreign_overlap_zero_but_tail_present
    ):
        return "tail_after_opposite_lane_trim"
    if overlap_by_id or (foreign_overlap_metric_m is not None and foreign_overlap_metric_m > 0.0):
        if single_sided_unrelated_opposite_lane_trim_applied or tuple(foreign_road_arm_corridor_ids):
            return "corridor_intrusion"
        return "semantic_road_overlap"
    if tuple(foreign_semantic_node_ids) or tuple(foreign_rc_context_ids):
        return "semantic_road_overlap"
    if soft_excluded_rc_corridor_trim_applied:
        return "outside_drivezone_or_corridor"
    return None


def derive_stage3_step5_blocking_foreign_established(
    acceptance_reason: str | None,
    *,
    foreign_subtype: str | None,
    foreign_tail_length_m: float | None = None,
    foreign_overlap_zero_but_tail_present: bool | None = None,
    single_sided_unrelated_opposite_lane_trim_applied: bool = False,
    soft_excluded_rc_corridor_trim_applied: bool = False,
    foreign_semantic_node_ids: Iterable[str] = (),
    foreign_road_arm_corridor_ids: Iterable[str] = (),
    foreign_rc_context_ids: Iterable[str] = (),
) -> bool:
    explicit_foreign_reasons = {
        "foreign_tail_after_opposite_lane_trim",
        "foreign_corridor_intrusion",
        "foreign_semantic_road_overlap",
        "foreign_outside_drivezone_soft_excluded",
    }
    if acceptance_reason in explicit_foreign_reasons:
        return True
    has_hard_corridor_context = bool(
        tuple(foreign_road_arm_corridor_ids)
        or single_sided_unrelated_opposite_lane_trim_applied
    )
    has_hard_tail_context = bool(
        (foreign_tail_length_m is not None and foreign_tail_length_m > 0.0)
        or foreign_overlap_zero_but_tail_present
        or single_sided_unrelated_opposite_lane_trim_applied
    )
    if foreign_subtype == "corridor_intrusion":
        return has_hard_corridor_context
    if foreign_subtype == "outside_drivezone_or_corridor":
        return bool(soft_excluded_rc_corridor_trim_applied or has_hard_corridor_context)
    if foreign_subtype == "tail_after_opposite_lane_trim":
        return has_hard_tail_context
    # Overlap/strip/context residuals remain provenance unless they are backed
    # by an explicit foreign verdict or a hard corridor/tail signal.
    return False


def _step5_reason_from_subtype(foreign_subtype: str | None) -> str | None:
    if foreign_subtype == "tail_after_opposite_lane_trim":
        return "foreign_tail_after_opposite_lane_trim"
    if foreign_subtype == "corridor_intrusion":
        return "foreign_corridor_intrusion"
    if foreign_subtype == "semantic_road_overlap":
        return "foreign_semantic_road_overlap"
    if foreign_subtype == "outside_drivezone_or_corridor":
        return "foreign_outside_drivezone_soft_excluded"
    return None


def derive_stage3_step5_canonical_foreign_reason(
    acceptance_reason: str | None,
    *,
    foreign_subtype: str | None,
    blocking_foreign_established: bool,
) -> str | None:
    if not blocking_foreign_established:
        return None
    explicit_foreign_reasons = {
        "foreign_tail_after_opposite_lane_trim",
        "foreign_corridor_intrusion",
        "foreign_semantic_road_overlap",
        "foreign_outside_drivezone_soft_excluded",
    }
    if acceptance_reason in explicit_foreign_reasons:
        return str(acceptance_reason)
    return _step5_reason_from_subtype(foreign_subtype)


def derive_stage3_step5_foreign_baseline_established(
    acceptance_reason: str | None,
    *,
    foreign_subtype: str | None,
    foreign_overlap_metric_m: float | None = None,
    foreign_tail_length_m: float | None = None,
    foreign_strip_extent_m: float | None = None,
    foreign_overlap_zero_but_tail_present: bool | None = None,
    foreign_overlap_by_id: Mapping[str, float] | None = None,
    foreign_semantic_node_ids: Iterable[str] = (),
    foreign_road_arm_corridor_ids: Iterable[str] = (),
    foreign_rc_context_ids: Iterable[str] = (),
) -> bool:
    if foreign_subtype is not None:
        return True
    if acceptance_reason is not None and "foreign" in str(acceptance_reason):
        return True
    if foreign_overlap_by_id:
        return True
    if foreign_overlap_metric_m is not None and foreign_overlap_metric_m > 0.0:
        return True
    if foreign_tail_length_m is not None and foreign_tail_length_m > 0.0:
        return True
    if foreign_strip_extent_m is not None and foreign_strip_extent_m > 0.0:
        return True
    if foreign_overlap_zero_but_tail_present:
        return True
    if tuple(foreign_semantic_node_ids):
        return True
    if tuple(foreign_road_arm_corridor_ids):
        return True
    if tuple(foreign_rc_context_ids):
        return True
    return False


@dataclass(frozen=True)
class Stage3Step5ForeignModelInputs:
    foreign_semantic_node_ids: Iterable[str]
    foreign_road_arm_corridor_ids: Iterable[str]
    foreign_rc_context_ids: Iterable[str]
    acceptance_reason: str | None
    foreign_overlap_metric_m: float | None
    foreign_tail_length_m: float | None
    foreign_strip_extent_m: float | None
    foreign_overlap_zero_but_tail_present: bool | None
    single_sided_unrelated_opposite_lane_trim_applied: bool
    soft_excluded_rc_corridor_trim_applied: bool
    foreign_overlap_by_id: Mapping[str, float]


@dataclass(frozen=True)
class Stage3Step5ContractDecision:
    foreign_baseline_established: bool
    foreign_subtype: str | None
    canonical_foreign_established: bool
    canonical_foreign_reason: str | None
    residual_foreign_present: bool
    audit_facts: tuple[str, ...] = ()


def _step5_has_hard_blocking_context(
    step5_result: Stage3Step5ForeignModelResult,
) -> bool:
    if step5_result.single_sided_unrelated_opposite_lane_trim_applied:
        return True
    if step5_result.foreign_tail_length_m is not None and step5_result.foreign_tail_length_m > 0.0:
        return True
    if step5_result.foreign_overlap_zero_but_tail_present:
        return True
    return bool(step5_result.foreign_road_arm_corridor_ids)


def stage3_step6_has_remaining_foreign_residue(
    step6_result: Stage3Step6GeometrySolveResult | None,
) -> bool:
    if step6_result is None:
        return False
    if step6_result.remaining_foreign_semantic_node_ids:
        return True
    if step6_result.remaining_foreign_road_arm_corridor_ids:
        return True
    if (
        step6_result.foreign_overlap_metric_m is not None
        and step6_result.foreign_overlap_metric_m > 0.0
    ):
        return True
    if (
        step6_result.foreign_tail_length_m is not None
        and step6_result.foreign_tail_length_m > 0.0
    ):
        return True
    return bool(step6_result.foreign_overlap_zero_but_tail_present)


def resolve_stage3_step5_contract_decision(
    *,
    step5_result: Stage3Step5ForeignModelResult | None,
    step6_result: Stage3Step6GeometrySolveResult | None,
) -> Stage3Step5ContractDecision:
    if step5_result is None:
        return Stage3Step5ContractDecision(
            foreign_baseline_established=False,
            foreign_subtype=None,
            canonical_foreign_established=False,
            canonical_foreign_reason=None,
            residual_foreign_present=stage3_step6_has_remaining_foreign_residue(
                step6_result
            ),
            audit_facts=(),
        )

    residual_present = stage3_step6_has_remaining_foreign_residue(step6_result)
    if not residual_present and step6_result is None:
        residual_present = bool(step5_result.canonical_foreign_established)

    decision_audit_facts: list[str] = []
    canonical_foreign_established = bool(step5_result.canonical_foreign_established)
    canonical_foreign_reason = step5_result.canonical_foreign_reason
    if (
        step5_result.foreign_subtype is not None
        and not step5_result.canonical_foreign_established
    ):
        decision_audit_facts.append("step5_result_provenance_only")
    if (
        canonical_foreign_established
        and not residual_present
        and not _step5_has_hard_blocking_context(step5_result)
        and step5_result.foreign_subtype in {"semantic_road_overlap", "outside_drivezone_or_corridor"}
    ):
        canonical_foreign_established = False
        canonical_foreign_reason = None
        decision_audit_facts.append(
            "step5_canonical_downgraded_after_step6_final_state"
        )
    if (
        not canonical_foreign_established
        and residual_present
        and step6_result is not None
        and step5_result.foreign_subtype in {"semantic_road_overlap", "outside_drivezone_or_corridor"}
        and step6_result.residual_step5_blocking_foreign_required
    ):
        canonical_foreign_established = True
        canonical_foreign_reason = "foreign_outside_drivezone_soft_excluded"
        decision_audit_facts.append(
            "step5_canonical_escalated_from_step6_residual_overlap"
        )
    if residual_present and not step5_result.canonical_foreign_established:
        decision_audit_facts.append("step5_residual_present_but_nonblocking")
    if (
        step5_result.foreign_baseline_established
        and not canonical_foreign_established
    ):
        decision_audit_facts.append("step5_baseline_retained_but_nonblocking")
        if not residual_present:
            decision_audit_facts.append("step5_baseline_cleared_by_step6_final_state")

    return Stage3Step5ContractDecision(
        foreign_baseline_established=bool(step5_result.foreign_baseline_established),
        foreign_subtype=step5_result.foreign_subtype,
        canonical_foreign_established=canonical_foreign_established,
        canonical_foreign_reason=canonical_foreign_reason,
        residual_foreign_present=residual_present,
        audit_facts=_sorted_unique(decision_audit_facts),
    )


def build_stage3_step5_foreign_model_result(
    inputs: Stage3Step5ForeignModelInputs,
) -> Stage3Step5ForeignModelResult:
    foreign_semantic_node_ids = _frozen_ids(inputs.foreign_semantic_node_ids)
    foreign_road_arm_corridor_ids = _frozen_ids(inputs.foreign_road_arm_corridor_ids)
    foreign_rc_context_ids = _frozen_ids(inputs.foreign_rc_context_ids)
    foreign_subtype = derive_stage3_step5_foreign_subtype(
        inputs.acceptance_reason,
        foreign_overlap_metric_m=inputs.foreign_overlap_metric_m,
        foreign_tail_length_m=inputs.foreign_tail_length_m,
        foreign_strip_extent_m=inputs.foreign_strip_extent_m,
        foreign_overlap_zero_but_tail_present=inputs.foreign_overlap_zero_but_tail_present,
        single_sided_unrelated_opposite_lane_trim_applied=(
            inputs.single_sided_unrelated_opposite_lane_trim_applied
        ),
        soft_excluded_rc_corridor_trim_applied=inputs.soft_excluded_rc_corridor_trim_applied,
        foreign_overlap_by_id=inputs.foreign_overlap_by_id,
        foreign_semantic_node_ids=foreign_semantic_node_ids,
        foreign_road_arm_corridor_ids=foreign_road_arm_corridor_ids,
        foreign_rc_context_ids=foreign_rc_context_ids,
    )
    blocking_foreign_established = derive_stage3_step5_blocking_foreign_established(
        inputs.acceptance_reason,
        foreign_subtype=foreign_subtype,
        foreign_tail_length_m=inputs.foreign_tail_length_m,
        foreign_overlap_zero_but_tail_present=inputs.foreign_overlap_zero_but_tail_present,
        single_sided_unrelated_opposite_lane_trim_applied=(
            inputs.single_sided_unrelated_opposite_lane_trim_applied
        ),
        soft_excluded_rc_corridor_trim_applied=inputs.soft_excluded_rc_corridor_trim_applied,
        foreign_semantic_node_ids=foreign_semantic_node_ids,
        foreign_road_arm_corridor_ids=foreign_road_arm_corridor_ids,
        foreign_rc_context_ids=foreign_rc_context_ids,
    )
    canonical_foreign_reason = derive_stage3_step5_canonical_foreign_reason(
        inputs.acceptance_reason,
        foreign_subtype=foreign_subtype,
        blocking_foreign_established=blocking_foreign_established,
    )
    canonical_foreign_established = canonical_foreign_reason is not None
    foreign_baseline_established = derive_stage3_step5_foreign_baseline_established(
        inputs.acceptance_reason,
        foreign_subtype=foreign_subtype,
        foreign_overlap_metric_m=inputs.foreign_overlap_metric_m,
        foreign_tail_length_m=inputs.foreign_tail_length_m,
        foreign_strip_extent_m=inputs.foreign_strip_extent_m,
        foreign_overlap_zero_but_tail_present=inputs.foreign_overlap_zero_but_tail_present,
        foreign_overlap_by_id=inputs.foreign_overlap_by_id,
        foreign_semantic_node_ids=foreign_semantic_node_ids,
        foreign_road_arm_corridor_ids=foreign_road_arm_corridor_ids,
        foreign_rc_context_ids=foreign_rc_context_ids,
    )

    foreign_tail_records = []
    if inputs.foreign_tail_length_m and inputs.foreign_tail_length_m > 0.0:
        foreign_tail_records.append(
            f"post_trim_non_target_tail_length_m={float(inputs.foreign_tail_length_m):.3f}"
        )
    if inputs.foreign_overlap_zero_but_tail_present:
        foreign_tail_records.append("foreign_overlap_zero_but_tail_present")

    foreign_overlap_records = [
        f"foreign_overlap:{road_id}={float(length):.3f}"
        for road_id, length in sorted(inputs.foreign_overlap_by_id.items())
    ]
    if inputs.single_sided_unrelated_opposite_lane_trim_applied:
        foreign_overlap_records.append(
            "single_sided_unrelated_opposite_lane_trim_applied"
        )
    if inputs.soft_excluded_rc_corridor_trim_applied:
        foreign_overlap_records.append("soft_excluded_rc_corridor_trim_applied")

    audit_facts = _sorted_unique(
        [
            (
                f"foreign_subtype={foreign_subtype}"
                if foreign_subtype
                else None
            ),
            (
                "foreign_baseline_established"
                if foreign_baseline_established
                else "foreign_baseline_established=false"
            ),
            (
                "blocking_foreign_established"
                if blocking_foreign_established
                else "blocking_foreign_established=false"
            ),
            (
                "canonical_foreign_established"
                if canonical_foreign_established
                else "canonical_foreign_established=false"
            ),
            (
                f"canonical_foreign_reason={canonical_foreign_reason}"
                if canonical_foreign_reason
                else None
            ),
            (
                f"foreign_semantic_node_count={len(foreign_semantic_node_ids)}"
                if foreign_semantic_node_ids
                else None
            ),
            (
                f"foreign_road_arm_corridor_count={len(foreign_road_arm_corridor_ids)}"
                if foreign_road_arm_corridor_ids
                else None
            ),
            (
                f"foreign_rc_context_count={len(foreign_rc_context_ids)}"
                if foreign_rc_context_ids
                else None
            ),
            (
                f"foreign_overlap_metric_m={float(inputs.foreign_overlap_metric_m):.3f}"
                if inputs.foreign_overlap_metric_m is not None
                else None
            ),
            *foreign_tail_records,
            *foreign_overlap_records,
        ]
    )

    return Stage3Step5ForeignModelResult(
        foreign_semantic_node_ids=foreign_semantic_node_ids,
        foreign_road_arm_corridor_ids=foreign_road_arm_corridor_ids,
        foreign_rc_context_ids=foreign_rc_context_ids,
        foreign_baseline_established=foreign_baseline_established,
        blocking_foreign_established=blocking_foreign_established,
        canonical_foreign_established=canonical_foreign_established,
        canonical_foreign_reason=canonical_foreign_reason,
        foreign_subtype=foreign_subtype,
        foreign_overlap_metric_m=inputs.foreign_overlap_metric_m,
        foreign_tail_length_m=inputs.foreign_tail_length_m,
        foreign_strip_extent_m=inputs.foreign_strip_extent_m,
        foreign_overlap_zero_but_tail_present=inputs.foreign_overlap_zero_but_tail_present,
        single_sided_unrelated_opposite_lane_trim_applied=(
            inputs.single_sided_unrelated_opposite_lane_trim_applied
        ),
        soft_excluded_rc_corridor_trim_applied=(
            inputs.soft_excluded_rc_corridor_trim_applied
        ),
        foreign_tail_records=_sorted_unique(foreign_tail_records),
        foreign_overlap_records=_sorted_unique(foreign_overlap_records),
        audit_facts=audit_facts,
    )
