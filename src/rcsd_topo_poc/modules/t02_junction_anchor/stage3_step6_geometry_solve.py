from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step6GeometrySolveResult,
)

logger = logging.getLogger(__name__)

_REGULARIZATION_REVIEW_REASON = (
    "nonstable_center_junction_extreme_geometry_anomaly"
)
_STABLE_OVERLAP_REVIEW_REASON = "stable_overlap_requires_review"
_CLUSTER_CANONICAL_REASONS = {
    "nonstable_center_junction_extreme_geometry_anomaly": (
        "center_junction_extreme_geometry_cluster"
    ),
    "stable_compound_center_requires_review": (
        "center_junction_compound_center_cluster"
    ),
}


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


def _cluster_canonical_facts(
    *,
    geometry_review_reason: str | None,
    optimizer_events: Iterable[str],
) -> tuple[str, ...]:
    cluster_name = _CLUSTER_CANONICAL_REASONS.get(geometry_review_reason)
    if cluster_name is None:
        return ()
    optimizer_event_set = {str(value) for value in optimizer_events if value}
    facts = [
        f"step6_cluster_path={cluster_name}",
        f"step6_cluster_canonical_review_reason={geometry_review_reason}",
        "step6_cluster_canonical_result_owned",
    ]
    if "bounded_regularization_applied" in optimizer_event_set:
        facts.append("step6_cluster_regularization_selected")
    return _sorted_unique(facts)


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
    resolved_geometry = inputs.primary_solved_geometry
    bounded_optimizer_geometry = None
    resolved_aspect_ratio = inputs.polygon_aspect_ratio
    resolved_compactness = inputs.polygon_compactness
    resolved_bbox_fill_ratio = inputs.polygon_bbox_fill_ratio
    resolved_geometry_review_reason = inputs.geometry_review_reason
    resolved_residual_step5_blocking_foreign_required = (
        inputs.residual_step5_blocking_foreign_required
    )
    resolved_remaining_foreign_semantic_node_ids = frozenset(
        remaining_foreign_semantic_node_ids
    )
    resolved_remaining_foreign_road_arm_corridor_ids = frozenset(
        remaining_foreign_road_arm_corridor_ids
    )
    resolved_foreign_overlap_metric_m = inputs.foreign_overlap_metric_m
    resolved_foreign_tail_length_m = inputs.foreign_tail_length_m
    resolved_foreign_overlap_zero_but_tail_present = (
        inputs.foreign_overlap_zero_but_tail_present
    )
    resolved_final_validation_flags = _sorted_unique(inputs.final_validation_flags)

    if (
        inputs.geometry_review_reason == _STABLE_OVERLAP_REVIEW_REASON
        and inputs.geometry_established
        and inputs.primary_solved_geometry is not None
    ):
        try:
            from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step5_foreign_model import (
                STEP5_SMALL_RESIDUAL_FOREIGN_OVERLAP_M,
            )
            from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_polygon_solver import (
                select_surplus_trunk_tail_trim_candidate,
            )

            accepted, final_geom, cand_metrics = select_surplus_trunk_tail_trim_candidate(
                original_geometry=inputs.primary_solved_geometry,
                original_aspect_ratio=inputs.polygon_aspect_ratio,
                original_compactness=inputs.polygon_compactness,
                original_bbox_fill_ratio=inputs.polygon_bbox_fill_ratio,
            )
            if accepted and final_geom is not None and cand_metrics is not None:
                bounded_optimizer_geometry = final_geom
                resolved_geometry = final_geom
                resolved_aspect_ratio = cand_metrics.aspect_ratio
                resolved_compactness = cand_metrics.compactness
                resolved_bbox_fill_ratio = cand_metrics.bbox_fill_ratio
                resolved_geometry_review_reason = None
                resolved_residual_step5_blocking_foreign_required = False
                resolved_remaining_foreign_semantic_node_ids = frozenset()
                resolved_remaining_foreign_road_arm_corridor_ids = frozenset()
                resolved_foreign_overlap_metric_m = min(
                    float(inputs.foreign_overlap_metric_m or 0.0),
                    STEP5_SMALL_RESIDUAL_FOREIGN_OVERLAP_M - 0.001,
                )
                resolved_foreign_tail_length_m = 0.0
                resolved_foreign_overlap_zero_but_tail_present = False
                optimizer_events = _sorted_unique(
                    list(optimizer_events)
                    + [
                        "surplus_trunk_tail_trim_applied",
                        "surplus_trunk_tail_residual_released",
                    ]
                )
                resolved_final_validation_flags = _sorted_unique(
                    [
                        flag
                        for flag in resolved_final_validation_flags
                        if not str(flag).startswith("step6_geometry_review_reason=")
                        and str(flag) != "step6_residual_step5_blocking_foreign_required"
                    ]
                    + [
                        "step6_geometry_review_resolved=stable_overlap_requires_review",
                        "step6_surplus_trunk_tail_trim_resolved",
                    ]
                )
                logger.debug(
                    "surplus_trunk_tail_trim_applied: "
                    "aspect %.3f->%.3f  compactness %.3f->%.3f  bbox_fill %.3f->%.3f",
                    inputs.polygon_aspect_ratio or 0.0,
                    resolved_aspect_ratio or 0.0,
                    inputs.polygon_compactness or 0.0,
                    resolved_compactness or 0.0,
                    inputs.polygon_bbox_fill_ratio or 0.0,
                    resolved_bbox_fill_ratio or 0.0,
                )
        except Exception:
            logger.debug(
                "surplus trunk tail trim skipped due to exception",
                exc_info=True,
            )

    if (
        resolved_geometry_review_reason == _REGULARIZATION_REVIEW_REASON
        and inputs.geometry_established
        and resolved_geometry is not None
        and not resolved_residual_step5_blocking_foreign_required
    ):
        try:
            from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_polygon_solver import (
                _attempt_bounded_regularization_candidate,
                select_regularization_candidate,
            )

            candidate = _attempt_bounded_regularization_candidate(
                resolved_geometry,
            )
            accepted, final_geom, cand_metrics = select_regularization_candidate(
                original_geometry=resolved_geometry,
                candidate_geometry=candidate,
                original_uncovered_endpoint_count=len(
                    remaining_uncovered_selected_endpoint_node_ids
                ),
                original_foreign_semantic_node_ids=(
                    resolved_remaining_foreign_semantic_node_ids
                ),
                original_compactness=resolved_compactness,
                original_bbox_fill_ratio=resolved_bbox_fill_ratio,
            )
            if accepted and final_geom is not None and cand_metrics is not None:
                bounded_optimizer_geometry = final_geom
                resolved_geometry = final_geom
                resolved_aspect_ratio = cand_metrics.aspect_ratio
                resolved_compactness = cand_metrics.compactness
                resolved_bbox_fill_ratio = cand_metrics.bbox_fill_ratio
                optimizer_events = _sorted_unique(
                    list(optimizer_events)
                    + ["bounded_regularization_applied"]
                )
                logger.debug(
                    "bounded_regularization_applied: "
                    "compactness %.3f->%.3f  bbox_fill %.3f->%.3f",
                    inputs.polygon_compactness or 0.0,
                    resolved_compactness or 0.0,
                    inputs.polygon_bbox_fill_ratio or 0.0,
                    resolved_bbox_fill_ratio or 0.0,
                )
        except Exception:
            logger.debug(
                "bounded_regularization skipped due to exception",
                exc_info=True,
            )

    cluster_canonical_facts = _cluster_canonical_facts(
        geometry_review_reason=resolved_geometry_review_reason,
        optimizer_events=optimizer_events,
    )
    geometry_problem_flags = _sorted_unique(
        [
            (
                f"polygon_aspect_ratio={resolved_aspect_ratio:.3f}"
                if resolved_aspect_ratio is not None
                else None
            ),
            (
                f"polygon_compactness={resolved_compactness:.3f}"
                if resolved_compactness is not None
                else None
            ),
            (
                f"polygon_bbox_fill_ratio={resolved_bbox_fill_ratio:.3f}"
                if resolved_bbox_fill_ratio is not None
                else None
            ),
        ]
    )
    foreign_exclusion_validation = _sorted_unique(
        [
            (
                "foreign_semantic_node_ids="
                + ",".join(sorted(resolved_remaining_foreign_semantic_node_ids))
                if resolved_remaining_foreign_semantic_node_ids
                else None
            ),
            (
                "foreign_road_arm_corridor_ids="
                + ",".join(sorted(resolved_remaining_foreign_road_arm_corridor_ids))
                if resolved_remaining_foreign_road_arm_corridor_ids
                else None
            ),
            (
                f"foreign_overlap_metric_m={float(resolved_foreign_overlap_metric_m):.3f}"
                if resolved_foreign_overlap_metric_m is not None
                else None
            ),
            (
                f"post_trim_non_target_tail_length_m={float(resolved_foreign_tail_length_m):.3f}"
                if resolved_foreign_tail_length_m is not None
                and resolved_foreign_tail_length_m > 0.0
                else None
            ),
            (
                "foreign_overlap_zero_but_tail_present"
                if resolved_foreign_overlap_zero_but_tail_present
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
                if resolved_residual_step5_blocking_foreign_required
                else None
            ),
            *optimizer_events,
            *must_cover_validation,
            *foreign_exclusion_validation,
            *resolved_final_validation_flags,
            *geometry_problem_flags,
            *cluster_canonical_facts,
        ]
    )

    return Stage3Step6GeometrySolveResult(
        seed_geometry=inputs.primary_solved_geometry,
        primary_solved_geometry=resolved_geometry,
        bounded_optimizer_geometry=bounded_optimizer_geometry,
        geometry_established=inputs.geometry_established,
        geometry_review_reason=resolved_geometry_review_reason,
        residual_step5_blocking_foreign_required=(
            resolved_residual_step5_blocking_foreign_required
        ),
        max_selected_side_branch_covered_length_m=(
            inputs.max_selected_side_branch_covered_length_m
        ),
        polygon_aspect_ratio=resolved_aspect_ratio,
        polygon_compactness=resolved_compactness,
        polygon_bbox_fill_ratio=resolved_bbox_fill_ratio,
        selected_node_repair_attempted=inputs.selected_node_repair_attempted,
        selected_node_repair_applied=inputs.selected_node_repair_applied,
        selected_node_repair_discarded_due_to_extra_roads=(
            inputs.selected_node_repair_discarded_due_to_extra_roads
        ),
        introduced_extra_local_road_ids=introduced_extra_local_road_ids,
        remaining_uncovered_selected_endpoint_node_ids=frozenset(
            remaining_uncovered_selected_endpoint_node_ids
        ),
        remaining_foreign_semantic_node_ids=resolved_remaining_foreign_semantic_node_ids,
        remaining_foreign_road_arm_corridor_ids=(
            resolved_remaining_foreign_road_arm_corridor_ids
        ),
        optimizer_events=optimizer_events,
        must_cover_validation=must_cover_validation,
        foreign_exclusion_validation=foreign_exclusion_validation,
        final_validation_flags=resolved_final_validation_flags,
        foreign_overlap_metric_m=resolved_foreign_overlap_metric_m,
        foreign_tail_length_m=resolved_foreign_tail_length_m,
        foreign_overlap_zero_but_tail_present=(
            resolved_foreign_overlap_zero_but_tail_present
        ),
        geometry_problem_flags=geometry_problem_flags,
        audit_facts=audit_facts,
    )
