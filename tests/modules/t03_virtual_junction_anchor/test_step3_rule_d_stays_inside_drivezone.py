from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import step3_engine
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import write_case_outputs
from tests.modules.t03_virtual_junction_anchor._case_helpers import node_feature, run_case_bundle, write_case_package


def test_rule_d_forces_final_allowed_space_back_inside_drivezone(tmp_path: Path, monkeypatch) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100001"
    drivezone = box(0.0, 0.0, 20.0, 10.0)
    write_case_package(
        suite_root / case_id,
        case_id,
        drivezone_geometry=drivezone,
        extra_nodes=[node_feature("foreign_1", 50.0, 50.0, mainnodeid="foreign_1")],
    )

    def _fake_build_reachable_road_support(
        context,
        *,
        allowed_road_ids=None,
        blocker_geometry=None,
        force_bidirectional_road_ids=None,
        cap_m=50.0,
        case_cache=None,
    ):
        return box(-5.0, -5.0, 25.0, 5.0), [{"road_id": "road_1", "cap_hit": True}], {"road_1"}, []

    monkeypatch.setattr(step3_engine, "_build_reachable_road_support", _fake_build_reachable_road_support)

    context, _template_result, case_result = run_case_bundle(suite_root, case_id)

    assert case_result.step3_state == "not_established"
    assert case_result.reason == "outside_drivezone_intrusion"
    assert case_result.root_cause_type == "outside_drivezone_intrusion"
    assert case_result.audit_doc["rules"]["D"]["passed"] is False
    assert case_result.audit_doc["drivezone_containment_passed"] is False
    assert case_result.audit_doc["allowed_area_m2"] == 300.0
    assert case_result.audit_doc["allowed_inside_drivezone_area_m2"] == 100.0
    assert case_result.audit_doc["allowed_outside_drivezone_area_m2"] == 200.0
    assert case_result.audit_doc["allowed_outside_drivezone_ratio"] == pytest.approx(2 / 3, abs=1e-9)
    assert case_result.allowed_space_geometry is not None
    assert case_result.allowed_drivezone_geometry is not None
    assert case_result.allowed_space_geometry.difference(context.drivezone_geometry).area > 0.0
    assert case_result.allowed_drivezone_geometry.difference(context.drivezone_geometry).area > 0.0

    run_root = tmp_path / "run"
    write_case_outputs(run_root=run_root, context=context, case_result=case_result)
    status_doc = json.loads((run_root / "cases" / case_id / "step3_status.json").read_text(encoding="utf-8"))
    audit_doc = json.loads((run_root / "cases" / case_id / "step3_audit.json").read_text(encoding="utf-8"))

    assert status_doc["step3_state"] == "not_established"
    assert status_doc["reason"] == "outside_drivezone_intrusion"
    assert status_doc["key_metrics"]["allowed_area_m2"] == 300.0
    assert status_doc["key_metrics"]["allowed_inside_drivezone_area_m2"] == 100.0
    assert status_doc["key_metrics"]["allowed_outside_drivezone_area_m2"] == 200.0
    assert status_doc["key_metrics"]["allowed_outside_drivezone_ratio"] == pytest.approx(2 / 3, abs=1e-9)
    assert status_doc["key_metrics"]["drivezone_containment_passed"] is False
    assert audit_doc["allowed_area_m2"] == 300.0
    assert audit_doc["allowed_inside_drivezone_area_m2"] == 100.0
    assert audit_doc["allowed_outside_drivezone_area_m2"] == 200.0
    assert audit_doc["allowed_outside_drivezone_ratio"] == pytest.approx(2 / 3, abs=1e-9)
    assert audit_doc["drivezone_containment_passed"] is False
