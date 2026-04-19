from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import write_case_outputs
from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_584253_keeps_final_allowed_space_inside_drivezone(tmp_path: Path) -> None:
    context, _template_result, case_result = load_real_case_bundle("584253")
    run_root = tmp_path / "run"
    write_case_outputs(run_root=run_root, context=context, case_result=case_result)

    status_doc = json.loads((run_root / "cases" / "584253" / "step3_status.json").read_text(encoding="utf-8"))
    audit_doc = json.loads((run_root / "cases" / "584253" / "step3_audit.json").read_text(encoding="utf-8"))

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert "rule_d_50m_cap_used" not in audit_doc["review_signals"]
    assert any(item["cap_hit"] is True for item in audit_doc["growth_limits"])
    assert audit_doc["rules"]["D"]["passed"] is True
    assert audit_doc["allowed_area_m2"] == status_doc["key_metrics"]["allowed_area_m2"]
    assert audit_doc["allowed_inside_drivezone_area_m2"] == status_doc["key_metrics"]["allowed_inside_drivezone_area_m2"]
    assert audit_doc["allowed_outside_drivezone_area_m2"] == 0.0
    assert audit_doc["allowed_outside_drivezone_ratio"] == 0.0
    assert audit_doc["drivezone_containment_passed"] is True
    assert status_doc["key_metrics"]["allowed_outside_drivezone_area_m2"] == 0.0
    assert status_doc["key_metrics"]["allowed_outside_drivezone_ratio"] == 0.0
    assert status_doc["key_metrics"]["drivezone_containment_passed"] is True
    assert case_result.allowed_space_geometry is not None
    assert case_result.allowed_space_geometry.difference(context.drivezone_geometry).area <= 1e-6
    assert case_result.allowed_drivezone_geometry is not None
    assert case_result.allowed_drivezone_geometry.difference(context.drivezone_geometry).area <= 1e-6
