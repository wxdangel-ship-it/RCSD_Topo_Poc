from __future__ import annotations

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.outputs import (
    _candidate_fields,
    _report,
)


def test_candidate_contract_has_review_layers_without_probability_fields() -> None:
    fields = set(_candidate_fields())

    assert {
        "object_type",
        "candidate_status",
        "review_status",
        "result_status",
        "issue_group",
        "issue_code",
        "issue_type",
        "issue_name_zh",
        "issue_description_zh",
        "root_cause_type",
        "source_module",
        "source_failure_type",
        "repair_domain",
        "repair_hint_zh",
        "legacy_issue_type",
        "silent_fix",
    } <= fields
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


def test_report_uses_aligned_business_taxonomy_and_repair_columns() -> None:
    common = {
        "issue_code": "S01",
        "issue_name_zh": "路段必需方向不可通行",
        "issue_type": "segment_required_direction_unavailable",
        "issue_description_zh": "SWSD 必需方向缺少等价载体。",
        "root_cause_type": "raw_carrier_missing_trusted_anchor",
        "repair_domain": "frcsd_segment_direction",
        "repair_hint_zh": "复核方向或缺失载体。",
        "source_module": "T12",
        "decision_source": "automatic_high_confidence",
        "review_reason": "legacy evidence wording",
    }
    text = _report(
        {
            "run_id": "run",
            "counts": {
                "candidate_count": 1,
                "confirmed_quality_issue_count": 1,
                "review_exclusion_count": 0,
                "manual_review_required_count": 0,
            },
        },
        [{**common, "segment_id": "s"}],
        [],
        [],
        [],
        [],
    )

    assert (
        "| Segment | 编码 | 中文类型 | issue_type | 业务说明 | 根因 | 来源 | "
        "修复域 | 修复建议 |"
    ) in text
    assert "SWSD 必需方向缺少等价载体。" in text
    assert "raw_carrier_missing_trusted_anchor" in text
    assert "复核方向或缺失载体。" in text
