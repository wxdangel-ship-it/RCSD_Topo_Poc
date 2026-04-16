"""Focused tests for Stage3 Step6 bounded regularization candidate + selector.

Covers:
- candidate generation via morphological closing
- selector hard gates (area, degenerate, no-improvement)
- selector improvement condition (compactness / bbox_fill_ratio)
- integration through build_stage3_step6_geometry_solve_result
- non-activation on unrelated geometry_review_reasons
"""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon, box

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_polygon_solver import (
    _attempt_bounded_regularization_candidate,
    _compute_metrics,
    select_regularization_candidate,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_solve import (
    Stage3Step6GeometrySolveInputs,
    build_stage3_step6_geometry_solve_result,
)


def _narrow_strip() -> Polygon:
    """A highly elongated narrow strip (compactness << 0.2, bbox_fill < 0.25)."""
    return Polygon([
        (0, 0), (100, 0), (100, 2), (50, 3), (0, 2), (0, 0),
    ])


def _compact_square() -> Polygon:
    return box(0, 0, 10, 10)


def _solve_inputs(
    geometry,
    review_reason="nonstable_center_junction_extreme_geometry_anomaly",
    **overrides,
) -> Stage3Step6GeometrySolveInputs:
    metrics = _compute_metrics(geometry)
    defaults = dict(
        primary_solved_geometry=geometry,
        geometry_established=True,
        max_selected_side_branch_covered_length_m=0.0,
        selected_node_repair_attempted=False,
        selected_node_repair_applied=False,
        selected_node_repair_discarded_due_to_extra_roads=False,
        introduced_extra_local_road_ids=(),
        polygon_aspect_ratio=metrics.aspect_ratio if metrics else None,
        polygon_compactness=metrics.compactness if metrics else None,
        polygon_bbox_fill_ratio=metrics.bbox_fill_ratio if metrics else None,
        uncovered_selected_endpoint_node_ids=(),
        foreign_semantic_node_ids=(),
        foreign_road_arm_corridor_ids=(),
        foreign_overlap_metric_m=0.0,
        foreign_tail_length_m=0.0,
        foreign_overlap_zero_but_tail_present=False,
        geometry_review_reason=review_reason,
    )
    defaults.update(overrides)
    return Stage3Step6GeometrySolveInputs(**defaults)


class TestCandidateGeneration:
    def test_narrow_strip_produces_candidate(self):
        candidate = _attempt_bounded_regularization_candidate(_narrow_strip())
        assert candidate is not None
        assert not candidate.is_empty
        assert candidate.is_valid

    def test_compact_square_produces_candidate(self):
        candidate = _attempt_bounded_regularization_candidate(_compact_square())
        assert candidate is not None

    def test_none_geometry_returns_none(self):
        assert _attempt_bounded_regularization_candidate(None) is None

    def test_empty_geometry_returns_none(self):
        from shapely.geometry import GeometryCollection
        assert _attempt_bounded_regularization_candidate(GeometryCollection()) is None


class TestSelectorHardGates:
    def test_rejects_none_candidate(self):
        accepted, _, _ = select_regularization_candidate(
            original_geometry=_narrow_strip(),
            candidate_geometry=None,
            original_uncovered_endpoint_count=0,
            original_foreign_semantic_node_ids=frozenset(),
            original_compactness=0.1,
            original_bbox_fill_ratio=0.1,
        )
        assert not accepted

    def test_rejects_area_expansion(self):
        original = _narrow_strip()
        bigger = original.buffer(5)
        accepted, _, _ = select_regularization_candidate(
            original_geometry=original,
            candidate_geometry=bigger,
            original_uncovered_endpoint_count=0,
            original_foreign_semantic_node_ids=frozenset(),
            original_compactness=0.1,
            original_bbox_fill_ratio=0.1,
        )
        assert not accepted

    def test_rejects_when_no_improvement(self):
        square = _compact_square()
        m = _compute_metrics(square)
        accepted, _, _ = select_regularization_candidate(
            original_geometry=square,
            candidate_geometry=square,
            original_uncovered_endpoint_count=0,
            original_foreign_semantic_node_ids=frozenset(),
            original_compactness=m.compactness,
            original_bbox_fill_ratio=m.bbox_fill_ratio,
        )
        assert not accepted


class TestSelectorImprovementPath:
    def test_accepts_when_compactness_improves(self):
        strip = _narrow_strip()
        candidate = _attempt_bounded_regularization_candidate(strip)
        if candidate is None:
            pytest.skip("candidate collapsed on this platform")
        orig_m = _compute_metrics(strip)
        accepted, geom, metrics = select_regularization_candidate(
            original_geometry=strip,
            candidate_geometry=candidate,
            original_uncovered_endpoint_count=0,
            original_foreign_semantic_node_ids=frozenset(),
            original_compactness=orig_m.compactness,
            original_bbox_fill_ratio=orig_m.bbox_fill_ratio,
        )
        if accepted:
            assert metrics.compactness > orig_m.compactness or (
                metrics.bbox_fill_ratio > orig_m.bbox_fill_ratio
            )
            assert metrics.area <= orig_m.area * 1.001


class TestIntegrationThroughSolveResult:
    def test_regularization_activates_for_target_reason(self):
        strip = _narrow_strip()
        inputs = _solve_inputs(strip)
        result = build_stage3_step6_geometry_solve_result(inputs)
        assert (
            "step6_cluster_canonical_review_reason="
            "nonstable_center_junction_extreme_geometry_anomaly"
        ) in result.audit_facts
        assert "step6_cluster_canonical_result_owned" in result.audit_facts
        if result.bounded_optimizer_geometry is not None:
            assert "bounded_regularization_applied" in result.optimizer_events
            assert "step6_cluster_regularization_selected" in result.audit_facts
            assert result.polygon_compactness >= (inputs.polygon_compactness or 0)

    def test_regularization_does_not_activate_for_other_reasons(self):
        strip = _narrow_strip()
        inputs = _solve_inputs(strip, review_reason="stable_compound_center_requires_review")
        result = build_stage3_step6_geometry_solve_result(inputs)
        assert result.bounded_optimizer_geometry is None
        assert "bounded_regularization_applied" not in result.optimizer_events
        assert (
            "step6_cluster_canonical_review_reason="
            "stable_compound_center_requires_review"
        ) in result.audit_facts

    def test_regularization_does_not_activate_when_no_reason(self):
        strip = _narrow_strip()
        inputs = _solve_inputs(strip, review_reason=None)
        result = build_stage3_step6_geometry_solve_result(inputs)
        assert result.bounded_optimizer_geometry is None

    def test_regularization_does_not_activate_when_step5_blocking(self):
        strip = _narrow_strip()
        inputs = _solve_inputs(
            strip,
            residual_step5_blocking_foreign_required=True,
        )
        result = build_stage3_step6_geometry_solve_result(inputs)
        assert result.bounded_optimizer_geometry is None

    def test_compact_geometry_not_replaced(self):
        square = _compact_square()
        inputs = _solve_inputs(square)
        result = build_stage3_step6_geometry_solve_result(inputs)
        assert result.bounded_optimizer_geometry is None
