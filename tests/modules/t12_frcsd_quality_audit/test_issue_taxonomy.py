from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.issue_taxonomy import (
    QUALITY_ISSUES,
    enrich_quality_result,
    normalize_issue_type,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError


def test_taxonomy_has_exactly_three_groups_and_seven_types() -> None:
    assert len(QUALITY_ISSUES) == 7
    assert {item.issue_group for item in QUALITY_ISSUES.values()} == {
        "segment_passability",
        "junction_topology",
        "junction_anchor_relation",
    }
    assert {item.issue_code for item in QUALITY_ISSUES.values()} == {
        "S01",
        "S02",
        "S03",
        "J01",
        "J02",
        "J03",
        "J04",
    }


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        (
            "directed_carrier_missing",
            "segment_required_direction_unavailable",
        ),
        (
            "required_local_connectivity_missing",
            "segment_required_connection_missing",
        ),
        (
            "unexpected_reverse_carrier",
            "segment_unexpected_reverse_passability",
        ),
        (
            "junction_required_topology_missing",
            "junction_required_topology_missing",
        ),
        (
            "junction_reality_or_precision_gap",
            "junction_unmatched_support_topology",
        ),
    ],
)
def test_legacy_issue_types_have_one_release_mapping(
    legacy: str,
    expected: str,
) -> None:
    assert normalize_issue_type(legacy) == expected


def test_confirmed_result_is_enriched_with_repairable_taxonomy() -> None:
    row = enrich_quality_result(
        {
            "object_type": "segment",
            "review_status": "confirmed_frcsd_quality_issue",
            "issue_type": "directed_carrier_missing",
            "decision_rule": "raw_carrier_missing_trusted_anchor",
            "source_module": "T12",
            "silent_fix": False,
        }
    )

    assert row["result_status"] == "confirmed"
    assert row["issue_type"] == "segment_required_direction_unavailable"
    assert row["legacy_issue_type"] == "directed_carrier_missing"
    assert row["issue_group"] == "segment_passability"
    assert row["issue_code"] == "S01"
    assert row["issue_name_zh"]
    assert row["issue_description_zh"]
    assert row["root_cause_type"]
    assert row["repair_domain"]
    assert row["repair_hint_zh"]


def test_excluded_result_has_authoritative_result_status_without_issue_type() -> None:
    row = enrich_quality_result(
        {
            "object_type": "junction",
            "review_status": "excluded_false_positive",
            "issue_type": "",
            "detection_rule": "t03_rejected_insufficient_junction_evidence",
            "decision_rule": "insufficient_junction_evidence",
            "source_module": "T03",
            "silent_fix": False,
        }
    )

    assert row["result_status"] == "excluded"
    assert row["issue_type"] == ""
    assert row["issue_group"] == ""
    assert row["root_cause_type"] == "t03_rejected_insufficient_junction_evidence"


def test_generic_junction_cardinality_type_cannot_be_migrated_silently() -> None:
    with pytest.raises(T12ContractError, match="must be regenerated from T07 Step2"):
        normalize_issue_type("junction_relation_cardinality_mismatch")
