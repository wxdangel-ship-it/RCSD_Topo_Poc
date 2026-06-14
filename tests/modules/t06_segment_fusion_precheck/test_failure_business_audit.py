from __future__ import annotations

from types import SimpleNamespace

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.failure_business_audit import (
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
