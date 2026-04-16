"""Focused tests for Stage3 Step6 geometry controller.

Covers the nonstable_center_junction_extreme_geometry_anomaly path
and guards against regression on stable / T-mouth / non-center paths.
"""
from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_controller import (
    Stage3Step6GeometryControllerInputs,
    derive_stage3_step6_geometry_controller_decision,
)

_DEFAULTS = dict(
    template_class="center_junction",
    status="ambiguous_rc_match",
    geometry_established=True,
    step5_canonical_foreign_established=False,
    can_soft_exclude_outside_rc=False,
    rc_outside_drivezone_present=False,
    max_target_group_foreign_semantic_road_overlap_m=0.0,
    max_selected_side_branch_covered_length_m=0.0,
    max_nonmain_branch_polygon_length_m=0.0,
    min_invalid_rc_distance_to_center_m=None,
    associated_rc_road_count=0,
    associated_rc_node_count=0,
    effective_associated_rc_node_count=0,
    excluded_rc_road_count=0,
    positive_rc_group_count=0,
    negative_rc_group_count=0,
    local_node_count=3,
    local_road_count=4,
    polygon_aspect_ratio=5.0,
    polygon_compactness=0.15,
    polygon_bbox_fill_ratio=0.18,
    single_sided_unrelated_opposite_lane_trim_applied=False,
    soft_excluded_rc_corridor_trim_applied=False,
    foreign_tail_length_m=0.0,
    foreign_overlap_zero_but_tail_present=False,
    compound_center_applied=False,
)


def _make(**overrides) -> Stage3Step6GeometryControllerInputs:
    return Stage3Step6GeometryControllerInputs(**{**_DEFAULTS, **overrides})


class TestNonstableCenterJunctionExtremeGeometry:
    """center_junction + non-stable + extreme geometry -> reason populated."""

    def test_extreme_geometry_produces_reason(self):
        decision = derive_stage3_step6_geometry_controller_decision(_make())
        assert decision.geometry_review_reason is not None
        assert decision.geometry_review_reason == (
            "nonstable_center_junction_extreme_geometry_anomaly"
        )

    def test_extreme_geometry_populates_flags(self):
        decision = derive_stage3_step6_geometry_controller_decision(_make())
        reason_flags = [
            f for f in decision.final_validation_flags if "geometry_review_reason" in f
        ]
        assert len(reason_flags) == 1
        assert "nonstable_center_junction_extreme_geometry_anomaly" in reason_flags[0]
        assert (
            "step6_cluster_canonical_review_reason="
            "nonstable_center_junction_extreme_geometry_anomaly"
        ) in decision.final_validation_flags
        assert "step6_cluster_canonical_result_owned" in decision.final_validation_flags

    @pytest.mark.parametrize(
        "status",
        ["ambiguous_rc_match", "no_valid_rc_connection", "weak_branch_support"],
    )
    def test_fires_for_all_nonstable_statuses(self, status: str):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(status=status)
        )
        assert decision.geometry_review_reason == (
            "nonstable_center_junction_extreme_geometry_anomaly"
        )

    def test_does_not_fire_when_compactness_above_threshold(self):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(polygon_compactness=0.50)
        )
        assert decision.geometry_review_reason is None

    def test_does_not_fire_when_bbox_fill_above_threshold(self):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(polygon_bbox_fill_ratio=0.60)
        )
        assert decision.geometry_review_reason is None

    def test_does_not_fire_when_metrics_are_none(self):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(polygon_compactness=None, polygon_bbox_fill_ratio=None)
        )
        assert decision.geometry_review_reason is None

    def test_does_not_set_residual_step5_blocking(self):
        decision = derive_stage3_step6_geometry_controller_decision(_make())
        assert decision.residual_step5_blocking_foreign_required is False


class TestStableCompoundCenterNoRegression:
    """stable + compound_center -> existing reason preserved."""

    def test_stable_compound_center_reason_unchanged(self):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(
                status="stable",
                compound_center_applied=True,
                polygon_compactness=0.15,
                polygon_bbox_fill_ratio=0.18,
            )
        )
        assert decision.geometry_review_reason == "stable_compound_center_requires_review"
        assert (
            "step6_cluster_canonical_review_reason="
            "stable_compound_center_requires_review"
        ) in decision.final_validation_flags


class TestNonCenterNonTMouthNoSideEffect:
    """Non-center, non-T-mouth template -> no accidental reason."""

    def test_other_template_nonstable_extreme_geometry_stays_silent(self):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(
                template_class="some_other_template",
                polygon_compactness=0.10,
                polygon_bbox_fill_ratio=0.10,
            )
        )
        assert decision.geometry_review_reason is None


class TestTMouthNoSideEffect:
    """single_sided_t_mouth paths are not affected by the new branch."""

    def test_t_mouth_nonstable_extreme_geometry_stays_silent(self):
        decision = derive_stage3_step6_geometry_controller_decision(
            _make(
                template_class="single_sided_t_mouth",
                polygon_compactness=0.10,
                polygon_bbox_fill_ratio=0.10,
            )
        )
        assert decision.geometry_review_reason is None
