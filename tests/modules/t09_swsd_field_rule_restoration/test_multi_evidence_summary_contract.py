from __future__ import annotations

from collections import Counter
from pathlib import Path

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.frcsd_restriction import (
    _summary as _step3_summary,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restoration import (
    _decision_counts,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    DecisionSource,
    DecisionStatus,
    EvidencePriority,
    InferenceLevel,
    OverrideChainEntry,
    ProhibitionStatus,
    RestorationStrategy,
    RuleScope,
    T09ArmMovement,
    T09RestoredFieldRule,
    VerificationStatus,
)


V2 = RestorationStrategy.MULTI_EVIDENCE_V2


def test_step12_v2_summary_exposes_complete_decision_audit_counts() -> None:
    movement = T09ArmMovement(
        junction_id="junction:1",
        movement_id="movement:right",
        from_arm_id="arm:in",
        to_arm_id="arm:out",
        movement_type="right",
        strategy_version=V2,
        decision_status=DecisionStatus.PROHIBITED,
        decision_source=DecisionSource.RESTRICTION,
        decision_scope=RuleScope.ARM_TO_ARM,
        evidence_priority=EvidencePriority.RESTRICTION,
        verification_status=VerificationStatus.VERIFIED_SWSD,
    )
    rule = T09RestoredFieldRule(
        junction_id=movement.junction_id,
        from_arm_id=movement.from_arm_id,
        to_arm_id=movement.to_arm_id,
        movement_type=movement.movement_type,
        field_rule_status=ProhibitionStatus.FULLY_PROHIBITED,
        rule_scope=RuleScope.ARM_TO_ARM.value,
        conflicting_evidence_ids=("laneinfo:opposite",),
        inference_level=InferenceLevel.EXPLICIT,
        strategy_version=V2,
        decision_status=DecisionStatus.PROHIBITED,
        decision_source=DecisionSource.RESTRICTION,
        decision_scope=RuleScope.ARM_TO_ARM,
        evidence_priority=EvidencePriority.RESTRICTION,
        verification_status=VerificationStatus.VERIFIED_SWSD,
        override_chain=(
            OverrideChainEntry(
                winner_evidence_id="restriction:1",
                winner_source=DecisionSource.RESTRICTION,
                overridden_evidence_id="laneinfo:opposite",
                overridden_source=DecisionSource.LANEINFO,
                reason="restriction priority",
                decision_status=DecisionStatus.PROHIBITED,
            ),
        ),
        condition_identity="condition:am",
        condition_semantics_status="unknown",
        scope_promotion_status="arm_to_arm_confirmed",
        scope_promotion_audit={"promotion_allowed": True},
    )

    counts = _decision_counts(movements=(movement,), evidence=tuple(), rules=(rule,))

    assert counts["decision_status_counts"] == {
        "movement": {"prohibited": 1},
        "evidence": {},
        "rule": {"prohibited": 1},
    }
    assert counts["rule_scope_counts"] == {
        "movement": {"arm_to_arm": 1},
        "evidence": {},
        "rule": {"arm_to_arm": 1},
    }
    assert counts["evidence_priority_counts"] == {
        "movement": {"restriction": 1},
        "evidence": {},
        "rule": {"restriction": 1},
    }
    assert counts["verification_status_counts"] == {
        "movement": {"verified_swsd": 1},
        "evidence": {},
        "rule": {"verified_swsd": 1},
    }
    assert counts["condition_counts"] == {
        "evidence_with_condition_identity": 0,
        "rules_with_condition_identity": 1,
        "unique_condition_identity_count": 1,
        "condition_type_counts": {},
        "condition_semantics_status_counts": {"unknown": 1},
    }
    assert counts["scope_promotion_counts"] == {
        "status_counts": {"arm_to_arm_confirmed": 1},
        "promotion_allowed_rule_count": 1,
        "manual_review_rule_count": 0,
        "unexplained_carrier_count": 0,
    }
    assert counts["conflict_counts"] == {
        "movement_decision_conflict": 0,
        "evidence_type_conflict": 0,
        "rule_decision_conflict": 0,
        "rules_with_conflicting_evidence": 1,
        "conflicting_evidence_reference_count": 1,
    }
    assert counts["override_counts"] == {
        "rules_with_override": 1,
        "override_entry_count": 1,
    }


def test_step3_v2_summary_exposes_decision_condition_and_output_event_counts(
    tmp_path: Path,
) -> None:
    stable = {
        "properties": {
            "decision_status": "prohibited",
            "decision_scope": "arm_to_arm",
            "evidence_priority": "restriction",
            "verification_status": "verified_frcsd",
            "condition_identity": "condition:am",
            "condition_semantics_status": "unknown",
            "scope_promotion_status": "arm_to_arm_confirmed",
            "conflicting_evidence_ids": ["laneinfo:opposite"],
            "override_chain": [
                {
                    "winner_evidence_id": "restriction:1",
                    "overridden_evidence_id": "laneinfo:opposite",
                }
            ],
            "movement_type": "right",
            "risk_flags": ["stable_risk"],
        }
    }
    candidate = {
        "properties": {
            "decision_status": "unverified",
            "decision_scope": "road_to_arm",
            "evidence_priority": "laneinfo",
            "verification_status": "unverified_due_to_missing_frcsd_laneinfo",
            "condition_identity": "",
            "condition_semantics_status": "not_applicable",
            "scope_promotion_status": "not_applicable",
            "conflicting_evidence_ids": [],
            "override_chain": [],
            "candidate_reason": "derived_rule_requires_frcsd_laneinfo",
            "movement_type": "right",
            "risk_flags": ["candidate_risk"],
        }
    }
    skipped = Counter({"rule_strategy_mismatch:restriction_only_v1": 2})

    summary = _step3_summary(
        run_id="summary-contract",
        target_epsg=3857,
        elapsed_seconds=1.0,
        input_paths={"rules": tmp_path / "rules.json"},
        input_audit={
            "rules": {
                "requested_path": "rules.json",
                "resolved_path": str(tmp_path / "rules.json"),
                "requested_layer_name": "requested_rules",
                "resolved_layer_name": "resolved_rules",
                "field_names": ["decision_status", "decision_scope"],
                "feature_count": 3,
                "source_crs": "EPSG:4326",
                "output_crs": "EPSG:3857",
                "crs_source": "declared",
                "crs_transform_executed": True,
            }
        },
        input_counts={"rules": 3},
        carriers={},
        restrictions=[stable],
        candidates=[candidate],
        skipped=skipped,
        strategy=V2,
        stage_timings={
            "read_inputs_seconds": 0.1,
            "build_carriers_seconds": 0.2,
            "model_rules_seconds": 0.3,
            "write_artifacts_before_summary_seconds": 0.4,
            "run_before_summary_write_seconds": 1.0,
        },
        runtime_environment={"python_version": "test", "platform": "test"},
        output_paths={"summary": tmp_path / "summary.json"},
    )

    assert summary["decision_status_counts"] == {"prohibited": 1, "unverified": 1}
    assert summary["rule_scope_counts"] == {"arm_to_arm": 1, "road_to_arm": 1}
    assert summary["evidence_priority_counts"] == {"laneinfo": 1, "restriction": 1}
    assert summary["verification_status_counts"] == {
        "unverified_due_to_missing_frcsd_laneinfo": 1,
        "verified_frcsd": 1,
    }
    assert summary["condition_identity_counts"] == {"condition:am": 1}
    assert summary["condition_semantics_status_counts"] == {
        "not_applicable": 1,
        "unknown": 1,
    }
    assert summary["scope_promotion_status_counts"] == {
        "arm_to_arm_confirmed": 1,
        "not_applicable": 1,
    }
    assert summary["conflict_count"] == 1
    assert summary["override_count"] == 1
    assert summary["stable_count"] == 1
    assert summary["candidate_count"] == 1
    assert summary["skipped_count"] == 2
    assert summary["output_row_counts"] == {
        "stable_rows": 1,
        "candidate_rows": 1,
    }
    assert summary["processing_event_counts"]["skipped_events"] == 2
    assert "not a funnel denominator" in summary["processing_event_counts"]["count_semantics"]
    assert summary["skipped_counts"] == {
        "rule_strategy_mismatch:restriction_only_v1": 2,
    }
    assert summary["input_audit"]["rules"]["requested_layer_name"] == "requested_rules"
    assert summary["input_audit"]["rules"]["resolved_layer_name"] == "resolved_rules"
    assert summary["input_audit"]["rules"]["field_names"] == [
        "decision_status",
        "decision_scope",
    ]
    assert summary["input_audit"]["rules"]["source_crs"] == "EPSG:4326"
    assert summary["input_audit"]["rules"]["output_crs"] == "EPSG:3857"
    assert summary["runtime_environment"] == {
        "python_version": "test",
        "platform": "test",
    }
    assert summary["stage_durations_seconds"]["run_before_summary_write_seconds"] == 1.0
    assert summary["qa"]["crs_transform_executed"] is True
    assert summary["risk_counts"] == {
        "carrier": {},
        "output_rows": {"candidate_risk": 1, "stable_risk": 1},
        "combined": {"candidate_risk": 1, "stable_risk": 1},
        "combined_reference_count": 2,
    }
