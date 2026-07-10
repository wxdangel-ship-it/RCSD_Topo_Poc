from __future__ import annotations

from pathlib import Path

import rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.runner as runner_module
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.io import T09LoadedInputs
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RestorationStrategy,
    T09ArmMovement,
    T09SwsdArm,
)


def test_runner_callable_records_step12_runtime_input_timing_and_outcome_audit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_audit = {
        "target_epsg": 3857,
        "nodes": {
            "path": "/frozen/input/swnode.gpkg",
            "layer_name": "nodes",
            "field_names": ["id", "kind_2"],
            "feature_count": 1,
            "source_crs": "EPSG:4326",
            "output_crs": "EPSG:3857",
            "crs_source": "dataset",
        },
        "roads": {},
        "segments": {},
        "restrictions": {},
        "arrows": {},
    }
    loaded = T09LoadedInputs(
        junction_member_node_ids={},
        roads=tuple(),
        road_attributes=tuple(),
        segments=tuple(),
        segment_geometries={},
        restrictions=tuple(),
        arrows=tuple(),
        road_geometries={},
        input_audit=input_audit,
        crs_transform_executed=True,
    )
    arm = T09SwsdArm(
        junction_id="junction:1",
        arm_id="arm:1",
        risk_flags=("arm_runtime_test_risk",),
    )
    movement = T09ArmMovement(
        junction_id="junction:1",
        movement_id="movement:1",
        from_arm_id=arm.arm_id,
        to_arm_id=arm.arm_id,
        movement_type="unknown",
        movement_applicability=MovementApplicability.NOT_APPLICABLE,
        carrier_universe_status="empty",
        prohibition_status=ProhibitionStatus.NOT_A_TRAFFIC_RULE,
        prohibition_reason=ProhibitionReason.TOPOLOGY_NOT_APPLICABLE,
        risk_flags=("movement_runtime_test_risk",),
    )
    clock = iter((10.0, 11.0, 13.0, 16.0))
    artifacts = object()
    arm_build_strategies = []

    def build_arm_universe(_loaded, *, strategy_version):
        arm_build_strategies.append(strategy_version)
        return (arm,), (movement,)

    monkeypatch.setattr(runner_module, "load_t09_inputs", lambda **_kwargs: loaded)
    monkeypatch.setattr(
        runner_module,
        "build_t09_arm_universe",
        build_arm_universe,
    )
    monkeypatch.setattr(
        runner_module,
        "write_restoration_outputs",
        lambda **_kwargs: artifacts,
    )
    monkeypatch.setattr(runner_module.time, "perf_counter", lambda: next(clock))

    run = runner_module.run_t09_swsd_field_rule_restoration(
        swnode_gpkg="swnode.gpkg",
        swroad_gpkg="swroad.gpkg",
        segment_gpkg=None,
        output_dir=tmp_path,
        run_id="runtime-summary",
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    summary = run.result.summary

    assert run.artifacts is artifacts
    assert arm_build_strategies == [RestorationStrategy.MULTI_EVIDENCE_V2]
    assert summary["strategy_version"] == "multi_evidence_v2"
    assert summary["input_audit"] == input_audit
    assert summary["input_audit"]["nodes"] == {
        "path": "/frozen/input/swnode.gpkg",
        "layer_name": "nodes",
        "field_names": ["id", "kind_2"],
        "feature_count": 1,
        "source_crs": "EPSG:4326",
        "output_crs": "EPSG:3857",
        "crs_source": "dataset",
    }

    runtime = summary["runtime_environment"]
    assert all(
        isinstance(runtime[key], str) and runtime[key]
        for key in (
            "python_version",
            "python_implementation",
            "python_executable",
            "platform",
        )
    )
    stage_durations = summary["performance"]["stage_durations_seconds"]
    assert stage_durations == {
        "input_load": 1.0,
        "arm_movement_build": 2.0,
        "decision_restore": 3.0,
    }
    assert all(isinstance(value, float) and value >= 0.0 for value in stage_durations.values())
    assert summary["performance"]["elapsed_seconds"] == 6.0
    assert summary["qa"]["crs_transform_executed"] is True

    decision_counts = summary["decision_counts"]
    for key in (
        "decision_status_counts",
        "rule_scope_counts",
        "evidence_priority_counts",
        "verification_status_counts",
        "condition_counts",
        "scope_promotion_counts",
        "conflict_counts",
        "override_counts",
    ):
        assert isinstance(decision_counts[key], dict)

    risks = summary["risk_flag_counts"]
    assert set(risks) == {"arms", "movements", "evidence", "rules", "combined"}
    assert risks["arms"] == {"arm_runtime_test_risk": 1}
    assert risks["movements"] == {"movement_runtime_test_risk": 1}
    assert risks["combined"] == {
        "arm_runtime_test_risk": 1,
        "movement_runtime_test_risk": 1,
    }
    assert summary["skipped_counts"] == {}
    assert summary["skipped_reason_counts"] == {}
    assert summary["input_usage_counts"] == {
        "restriction_input_row_count": 0,
        "restriction_input_identity_count": 0,
        "restriction_matched_identity_count": 0,
        "restriction_unmatched_identity_count": 0,
        "laneinfo_input_row_count": 0,
        "laneinfo_referenced_row_count": 0,
        "laneinfo_unreferenced_row_count": 0,
    }
    outcomes = summary["outcome_reason_counts"]
    assert outcomes["movement_applicability"] == {"not_applicable": 1}
    assert outcomes["movement_prohibition_reason"] == {"topology_not_applicable": 1}
    assert outcomes["evidence_status"] == {"topology_not_applicable": 1}
    assert outcomes["rule_field_rule_status"] == {"not_a_traffic_rule": 1}
