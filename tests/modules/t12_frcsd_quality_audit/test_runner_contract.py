from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import (
    load_t06_cross_evidence,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import T12ContractError
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.runner import (
    run_t12_frcsd_quality_audit,
)


def _write_t06_evidence(root: Path, relation_path: Path) -> None:
    step2 = root / "step2_extract_rcsd_segments"
    step2.mkdir(parents=True)
    (step2 / "t06_step2_summary.json").write_text(
        json.dumps({"input_paths": {"intersection_match_path": str(relation_path)}}),
        encoding="utf-8",
    )
    pd.DataFrame(
        [{"swsd_segment_id": "segment", "reject_reason": "directed_missing"}]
    ).to_csv(step2 / "t06_rcsd_buffer_segment_rejected.csv", index=False)
    pd.DataFrame(
        [{"swsd_segment_id": "segment", "probe_status": "completed"}]
    ).to_csv(step2 / "t06_rcsd_buffer_only_probe.csv", index=False)
    pd.DataFrame(
        [{"swsd_segment_id": "segment", "failure_business_category": "gap"}]
    ).to_csv(step2 / "t06_rcsd_segment_failure_business_audit.csv", index=False)
    pd.DataFrame(
        [{"swsd_segment_id": "segment", "root_cause_category": "T05"}]
    ).to_csv(step2 / "t06_segment_replacement_problem_registry.csv", index=False)
    pd.DataFrame(
        [{"swsd_segment_id": "segment", "plan_status": "blocked"}]
    ).to_csv(step2 / "t06_segment_replacement_plan.csv", index=False)


def test_t06_cross_evidence_requires_same_t05_derived_run(tmp_path: Path) -> None:
    t05 = tmp_path / "expected_t05" / "intersection_match_all_audit.csv"
    t05.parent.mkdir()
    t05.write_text("target_id\n", encoding="utf-8")
    t06 = tmp_path / "t06"
    _write_t06_evidence(
        t06, tmp_path / "different_t05" / "intersection_match_all.geojson"
    )

    with pytest.raises(T12ContractError, match="cannot be tied"):
        load_t06_cross_evidence(
            t06_run_root=t06,
            t05_anchor_audit_path=t05,
            allow_unverified=False,
        )


def test_legacy_cross_evidence_override_is_explicit_and_audited(
    tmp_path: Path,
) -> None:
    t05 = tmp_path / "expected_t05" / "intersection_match_all_audit.csv"
    t05.parent.mkdir()
    t05.write_text("target_id\n", encoding="utf-8")
    t06 = tmp_path / "t06"
    _write_t06_evidence(
        t06, tmp_path / "different_t05" / "intersection_match_all.geojson"
    )

    rows, audit = load_t06_cross_evidence(
        t06_run_root=t06,
        t05_anchor_audit_path=t05,
        allow_unverified=True,
    )

    assert rows["segment"]["t06_reject_reason"] == "directed_missing"
    assert rows["segment"]["probe_probe_status"] == "completed"
    assert rows["segment"]["failure_failure_business_category"] == "gap"
    assert rows["segment"]["problem_root_cause_category"] == "T05"
    assert rows["segment"]["plan_plan_status"] == "blocked"
    assert audit["evidence_relation"] == "unverified_legacy"
    assert set(audit["cross_evidence_artifacts"]) == {
        "summary",
        "rejected",
        "buffer_only_probe",
        "failure_business_audit",
        "problem_registry",
        "replacement_plan",
    }
    assert all(
        evidence["sha256"]
        for evidence in audit["cross_evidence_artifacts"].values()
    )


def test_existing_output_run_root_is_blocked_before_input_processing(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "outputs"
    (out_root / "existing_run").mkdir(parents=True)

    with pytest.raises(T12ContractError, match="avoid overwrite"):
        run_t12_frcsd_quality_audit(
            swsd_segment_path="missing-segment",
            swsd_roads_path="missing-swsd-roads",
            swsd_nodes_path="missing-swsd-nodes",
            frcsd_roads_path="missing-frcsd-roads",
            frcsd_nodes_path="missing-frcsd-nodes",
            t05_anchor_audit_path="missing-t05",
            rcsd_intersection_path="missing-intersection",
            t06_run_root="missing-t06",
            out_root=out_root,
            run_id="existing_run",
        )
