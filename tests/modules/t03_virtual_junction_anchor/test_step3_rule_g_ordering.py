from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import step3_engine
from tests.modules.t03_virtual_junction_anchor._case_helpers import (
    node_feature,
    run_case_bundle,
    write_case_package,
)


def test_rule_g_keeps_hard_bound_first_even_if_preview_can_rescue(tmp_path: Path, monkeypatch) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100001"
    write_case_package(
        suite_root / case_id,
        case_id,
        extra_nodes=[node_feature("foreign_1", 50.0, 50.0, mainnodeid="foreign_1")],
    )

    def _fake_build_reachable_road_support(context, *, allowed_road_ids=None, blocker_geometry=None, cap_m=50.0):
        if blocker_geometry is not None:
            return None, [], set(), ["hard_blocker_applied"]
        return box(-6.0, -6.0, 6.0, 6.0), [], set(), []

    monkeypatch.setattr(step3_engine, "_build_reachable_road_support", _fake_build_reachable_road_support)

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)

    assert case_result.step3_state == "not_established"
    assert case_result.audit_doc["growth_order"] == "hard_bound_first"
    assert case_result.audit_doc["hard_bound_first"] is True
    assert case_result.audit_doc["post_growth_safety_only"] is True
    assert case_result.audit_doc["rules"]["G"]["passed"] is False
    assert case_result.allowed_space_geometry is None
