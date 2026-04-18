from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import load_step45_case_specs, load_step45_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import build_step45_case_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_writer import write_case_outputs
from tests.modules.t03_virtual_junction_anchor._step45_helpers import (
    build_center_case_a,
    build_center_case_b,
    write_step3_prerequisite,
    write_step45_case_package,
)


def _write_case(run_root: Path, case_root: Path, step3_root: Path, case_id: str) -> tuple[dict, dict]:
    specs, _ = load_step45_case_specs(case_root=case_root, case_ids=[case_id], exclude_case_ids=["922217", "54265667", "502058682"])
    context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    case_result = build_step45_case_result(context)
    write_case_outputs(run_root=run_root, context=context, case_result=case_result)
    case_dir = run_root / "cases" / case_id
    status_doc = json.loads((case_dir / "step45_status.json").read_text(encoding="utf-8"))
    audit_doc = json.loads((case_dir / "step45_audit.json").read_text(encoding="utf-8"))
    return status_doc, audit_doc


def test_step45_status_and_audit_contract_for_review_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    run_root = tmp_path / "run"
    build_center_case_b(case_root, step3_root, case_id="100002")

    status_doc, audit_doc = _write_case(run_root, case_root, step3_root, "100002")

    assert status_doc["association_class"] in {"A", "B", "C"}
    assert status_doc["association_class"] == "B"
    assert status_doc["step45_state"] == "review"
    assert status_doc["association_executed"] is True
    assert status_doc["association_reason"] == "support_only_hook_zone"
    assert status_doc["association_blocker"] is None
    assert status_doc["rcsd_semantic_core_missing"] is True
    assert set(audit_doc) >= {"step3_prerequisite", "step4", "step5", "joint_phase"}
    assert audit_doc["joint_phase"]["association_reason"] == "support_only_hook_zone"
    assert audit_doc["joint_phase"]["association_blocker"] is None


def test_step45_status_and_audit_contract_for_blocked_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    run_root = tmp_path / "run"
    build_center_case_a(case_root, step3_root, case_id="100003")
    write_step3_prerequisite(
        step3_root,
        "100003",
        template_class="center_junction",
        selected_road_ids=[],
    )

    status_doc, audit_doc = _write_case(run_root, case_root, step3_root, "100003")

    assert status_doc["association_class"] in {"A", "B", "C"}
    assert status_doc["association_class"] == "C"
    assert status_doc["step45_state"] == "not_established"
    assert status_doc["association_executed"] is False
    assert status_doc["association_reason"] is None
    assert status_doc["association_blocker"] == "step45_missing_selected_road_ids"
    assert "step45_missing_selected_road_ids" in status_doc["step45_prerequisite_issues"]
    assert set(audit_doc) >= {"step3_prerequisite", "step4", "step5", "joint_phase"}
    assert audit_doc["step4"]["association_executed"] is False
    assert status_doc["degree2_merged_rcsdroad_groups"] == {}
    assert audit_doc["step4"]["degree2_merged_rcsdroad_groups"] == {}
    assert audit_doc["joint_phase"]["association_blocker"] == "step45_missing_selected_road_ids"


def test_step45_status_contract_keeps_association_class_in_enum_for_unsupported_template(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    run_root = tmp_path / "run"
    write_step45_case_package(case_root / "100004", "100004", kind_2=999)
    write_step3_prerequisite(
        step3_root,
        "100004",
        template_class="center_junction",
        selected_road_ids=["road_1"],
    )

    status_doc, audit_doc = _write_case(run_root, case_root, step3_root, "100004")

    assert status_doc["association_class"] in {"A", "B", "C"}
    assert status_doc["association_class"] == "C"
    assert status_doc["association_executed"] is False
    assert status_doc["association_blocker"] == "unsupported_template"
    assert audit_doc["step3_prerequisite"]["supported_template"] is False
