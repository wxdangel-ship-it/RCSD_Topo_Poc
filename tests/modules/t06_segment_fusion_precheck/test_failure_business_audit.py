from __future__ import annotations

from types import SimpleNamespace

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.failure_business_audit import (
    failure_business_audit_row,
    failure_business_category,
    upstream_issue_owner,
)


def test_directionality_reject_reason_takes_precedence_over_dropped_junc_audit() -> None:
    probe_result = SimpleNamespace(status="corridor_found")
    relation = SimpleNamespace(rcsd_pair_nodes=["10", "20"])
    category = failure_business_category(
        "rcsd_not_bidirectional_for_swsd_dual",
        probe_result=probe_result,
        relation=relation,
        junc_audit={
            "dropped_junc_nodes": ["987955"],
            "junc_attach_loss_reason": "junc_relation_missing_or_invalid",
        },
        diagnostic={"root_cause_category": "buffer_candidate_missing_bidirectional_corridor"},
    )

    assert category == "directionality_mismatch_fixable"
    assert upstream_issue_owner(category) == "T06"
    assert (
        upstream_issue_owner(
            category,
            segment_outcome="rejected",
            reject_reason="rcsd_not_bidirectional_for_swsd_dual",
            root_cause_category="buffer_candidate_missing_bidirectional_corridor",
        )
        == "T03/T04/T05_or_T06_group_replacement"
    )


def test_directed_missing_with_ambiguous_probe_is_multi_anchor_issue() -> None:
    probe_result = SimpleNamespace(status="ambiguous_corridor")
    relation = SimpleNamespace(rcsd_pair_nodes=["10", "20"])
    category = failure_business_category(
        "rcsd_directed_path_missing",
        probe_result=probe_result,
        relation=relation,
        junc_audit={},
        diagnostic={
            "root_cause_category": "buffer_candidate_missing_directed_corridor",
            "full_graph_status": "required_nodes_connected",
            "directional_status": "full=directed_path_present;candidate=directed_path_missing",
        },
    )

    assert category == "multi_anchor_ambiguous"
    assert upstream_issue_owner(category, segment_outcome="rejected") == "T05"


def test_rejected_directionality_mismatch_requires_upstream_or_grouping_review() -> None:
    probe_result = SimpleNamespace(
        status="corridor_found",
        manual_review_required=False,
        repair_recommendation="high_confidence_pair_anchor_candidate",
        candidate_pair_sets=[["10", "20"]],
        candidate_score=0.9,
        geometry_overlap_ratio=0.8,
        directionality_score=0.5,
        connectivity_score=1.0,
        shape_similarity_score=1.0,
    )
    relation = SimpleNamespace(
        rcsd_pair_nodes=["10", "20"],
        rcsd_junc_nodes=[],
        failed_junc_nodes=[],
    )

    row = failure_business_audit_row(
        segment_id="1_2",
        segment_outcome="rejected",
        reject_reason="rcsd_not_bidirectional_for_swsd_dual",
        scenario_type="B",
        failure_business_category="directionality_mismatch_fixable",
        pair_nodes=["1", "2"],
        junc_nodes=[],
        relation=relation,
        junc_audit=None,
        probe_result=probe_result,
        root_cause_category="buffer_candidate_missing_bidirectional_corridor",
    )

    assert row["manual_review_required"] is True
    assert row["repair_recommendation"] == "upstream_anchor_or_segment_grouping_required"
    assert row["upstream_issue_owner"] == "T03/T04/T05_or_T06_group_replacement"
