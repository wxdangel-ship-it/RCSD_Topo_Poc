from __future__ import annotations

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.outputs import _candidate_fields


def test_candidate_contract_has_review_layers_without_probability_fields() -> None:
    fields = set(_candidate_fields())

    assert {"candidate_status", "review_status", "issue_type"} <= fields
    assert "drivezone_in_road_ratio" in fields
    assert {
        "candidate_kind",
        "raw_failed_directions",
        "directional_portal_status",
        "portal_constrained_semantic_status",
        "t07_road_surface_status",
        "t07_road_surface_path_road_ids",
        "t07_road_surface_access",
        "t07_road_surface_surface_ids",
        "t07_road_surface_frontiers",
        "t07_road_surface_distance_audit",
        "automatic_equivalence_basis",
        "unexpected_direction",
        "unexpected_reverse_frcsd_status",
        "unexpected_reverse_frcsd_path_road_ids",
        "unexpected_reverse_swsd_status",
        "unexpected_reverse_swsd_path_road_ids",
        "unexpected_reverse_high_precision_anchor",
        "unexpected_reverse_anchor_interval_status",
        "unexpected_reverse_anchor_interval_audit",
        "unexpected_reverse_segment_ownership_status",
        "unexpected_reverse_owner_segment_ids",
        "unexpected_reverse_other_segment_ids",
        "unexpected_reverse_segment_ownership_audit",
    } <= fields
    assert "confidence" not in fields
    assert "probability" not in fields
