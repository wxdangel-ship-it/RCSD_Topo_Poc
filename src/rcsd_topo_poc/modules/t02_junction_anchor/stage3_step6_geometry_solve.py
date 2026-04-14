from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step6GeometrySolveResult,
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


@dataclass(frozen=True)
class Stage3Step6GeometrySolveInputs:
    primary_solved_geometry: Any | None
    geometry_established: bool
    max_selected_side_branch_covered_length_m: float | None
    selected_node_repair_attempted: bool
    selected_node_repair_applied: bool
    selected_node_repair_discarded_due_to_extra_roads: bool
    introduced_extra_local_road_ids: Iterable[str]
    polygon_aspect_ratio: float | None
    polygon_compactness: float | None
    polygon_bbox_fill_ratio: float | None
    uncovered_selected_endpoint_node_ids: Iterable[str]
    foreign_semantic_node_ids: Iterable[str]
    foreign_road_arm_corridor_ids: Iterable[str]
    foreign_overlap_metric_m: float | None
    foreign_tail_length_m: float | None
    foreign_overlap_zero_but_tail_present: bool | None
    residual_step5_blocking_foreign_required: bool = False
    late_single_sided_branch_cap_cleanup_applied: bool = False
    late_post_soft_overlap_trim_applied: bool = False
    late_final_foreign_residue_trim_applied: bool = False
    late_single_sided_partial_branch_strip_cleanup_applied: bool = False
    late_single_sided_corridor_mask_cleanup_applied: bool = False
    late_single_sided_tail_clip_cleanup_applied: bool = False
    optimizer_events: Iterable[str] = ()
    geometry_review_reason: str | None = None
    final_validation_flags: Iterable[str] = ()


def build_stage3_step6_geometry_solve_result(
    inputs: Stage3Step6GeometrySolveInputs,
) -> Stage3Step6GeometrySolveResult:
    remaining_uncovered_selected_endpoint_node_ids = tuple(
        str(node_id) for node_id in inputs.uncovered_selected_endpoint_node_ids
    )
    remaining_foreign_semantic_node_ids = tuple(
        str(node_id) for node_id in inputs.foreign_semantic_node_ids
    )
    remaining_foreign_road_arm_corridor_ids = tuple(
        str(road_id) for road_id in inputs.foreign_road_arm_corridor_ids
    )
    introduced_extra_local_road_ids = _sorted_unique(inputs.introduced_extra_local_road_ids)
    optimizer_events = _sorted_unique(
        inputs.optimizer_events
        or (
            name
            for name, applied in (
                ("late_single_sided_branch_cap_cleanup_applied", inputs.late_single_sided_branch_cap_cleanup_applied),
                ("late_post_soft_overlap_trim_applied", inputs.late_post_soft_overlap_trim_applied),
                ("late_final_foreign_residue_trim_applied", inputs.late_final_foreign_residue_trim_applied),
                ("late_single_sided_partial_branch_strip_cleanup_applied", inputs.late_single_sided_partial_branch_strip_cleanup_applied),
                ("late_single_sided_corridor_mask_cleanup_applied", inputs.late_single_sided_corridor_mask_cleanup_applied),
                ("late_single_sided_tail_clip_cleanup_applied", inputs.late_single_sided_tail_clip_cleanup_applied),
            )
            if applied
        )
    )
    geometry_problem_flags = _sorted_unique(
        [
            (
                f"polygon_aspect_ratio={inputs.polygon_aspect_ratio:.3f}"
                if inputs.polygon_aspect_ratio is not None
                else None
            ),
            (
                f"polygon_compactness={inputs.polygon_compactness:.3f}"
                if inputs.polygon_compactness is not None
                else None
            ),
            (
                f"polygon_bbox_fill_ratio={inputs.polygon_bbox_fill_ratio:.3f}"
                if inputs.polygon_bbox_fill_ratio is not None
                else None
            ),
        ]
    )
    must_cover_validation = _sorted_unique(
        [
            (
                "final_uncovered_selected_endpoint_node_ids="
                + ",".join(sorted(remaining_uncovered_selected_endpoint_node_ids))
                if remaining_uncovered_selected_endpoint_node_ids
                else None
            ),
            (
                "selected_node_repair_attempted"
                if inputs.selected_node_repair_attempted
                else None
            ),
            (
                "selected_node_repair_applied"
                if inputs.selected_node_repair_applied
                else None
            ),
            (
                "selected_node_repair_discarded_due_to_extra_roads"
                if inputs.selected_node_repair_discarded_due_to_extra_roads
                else None
            ),
        ]
    )
    foreign_exclusion_validation = _sorted_unique(
        [
            (
                "foreign_semantic_node_ids="
                + ",".join(sorted(str(node_id) for node_id in inputs.foreign_semantic_node_ids))
                if tuple(inputs.foreign_semantic_node_ids)
                else None
            ),
            (
                "foreign_road_arm_corridor_ids="
                + ",".join(sorted(str(road_id) for road_id in inputs.foreign_road_arm_corridor_ids))
                if tuple(inputs.foreign_road_arm_corridor_ids)
                else None
            ),
            (
                f"foreign_overlap_metric_m={float(inputs.foreign_overlap_metric_m):.3f}"
                if inputs.foreign_overlap_metric_m is not None
                else None
            ),
            (
                f"post_trim_non_target_tail_length_m={float(inputs.foreign_tail_length_m):.3f}"
                if inputs.foreign_tail_length_m is not None and inputs.foreign_tail_length_m > 0.0
                else None
            ),
            (
                "foreign_overlap_zero_but_tail_present"
                if inputs.foreign_overlap_zero_but_tail_present
                else None
            ),
            (
                "introduced_extra_local_road_ids="
                + ",".join(introduced_extra_local_road_ids)
                if introduced_extra_local_road_ids
                else None
            ),
        ]
    )
    audit_facts = _sorted_unique(
        [
            "geometry_established" if inputs.geometry_established else "geometry_missing",
            (
                "step6_residual_step5_blocking_foreign_required"
                if inputs.residual_step5_blocking_foreign_required
                else None
            ),
            *optimizer_events,
            *must_cover_validation,
            *foreign_exclusion_validation,
            *_sorted_unique(inputs.final_validation_flags),
            *geometry_problem_flags,
        ]
    )
    return Stage3Step6GeometrySolveResult(
        primary_solved_geometry=inputs.primary_solved_geometry,
        geometry_established=inputs.geometry_established,
        geometry_review_reason=inputs.geometry_review_reason,
        residual_step5_blocking_foreign_required=(
            inputs.residual_step5_blocking_foreign_required
        ),
        max_selected_side_branch_covered_length_m=(
            inputs.max_selected_side_branch_covered_length_m
        ),
        polygon_aspect_ratio=inputs.polygon_aspect_ratio,
        polygon_compactness=inputs.polygon_compactness,
        polygon_bbox_fill_ratio=inputs.polygon_bbox_fill_ratio,
        selected_node_repair_attempted=inputs.selected_node_repair_attempted,
        selected_node_repair_applied=inputs.selected_node_repair_applied,
        selected_node_repair_discarded_due_to_extra_roads=(
            inputs.selected_node_repair_discarded_due_to_extra_roads
        ),
        introduced_extra_local_road_ids=introduced_extra_local_road_ids,
        remaining_uncovered_selected_endpoint_node_ids=frozenset(
            remaining_uncovered_selected_endpoint_node_ids
        ),
        remaining_foreign_semantic_node_ids=frozenset(
            remaining_foreign_semantic_node_ids
        ),
        remaining_foreign_road_arm_corridor_ids=frozenset(
            remaining_foreign_road_arm_corridor_ids
        ),
        optimizer_events=optimizer_events,
        must_cover_validation=must_cover_validation,
        foreign_exclusion_validation=foreign_exclusion_validation,
        final_validation_flags=_sorted_unique(inputs.final_validation_flags),
        foreign_overlap_metric_m=inputs.foreign_overlap_metric_m,
        foreign_tail_length_m=inputs.foreign_tail_length_m,
        foreign_overlap_zero_but_tail_present=(
            inputs.foreign_overlap_zero_but_tail_present
        ),
        geometry_problem_flags=geometry_problem_flags,
        audit_facts=audit_facts,
    )
