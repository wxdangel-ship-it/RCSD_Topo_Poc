from __future__ import annotations

from pathlib import Path

from tests.modules.t03_virtual_junction_anchor._case_helpers import (
    node_feature,
    road_feature,
    run_case_bundle,
    write_case_package,
)


def test_rule_d_traces_junction_branch_bidirectionally_from_target(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100001"
    write_case_package(
        suite_root / case_id,
        case_id,
        roads=[
            road_feature("road_wrong_way", case_id, "200001", [(0.0, 0.0), (30.0, 0.0)], direction=3),
            road_feature("road_downstream", "200001", "300001", [(30.0, 0.0), (60.0, 0.0)], direction=2),
        ],
        extra_nodes=[
            node_feature("200001", 30.0, 0.0, mainnodeid="200001"),
            node_feature("300001", 60.0, 0.0, mainnodeid="300001"),
        ],
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)

    assert case_result.audit_doc["direction_mode"] == "t02_direction_plus_bidirectional_junction_trace"
    assert case_result.audit_doc["rules"]["D"]["direction_mode"] == "t02_direction_plus_bidirectional_junction_trace"
    assert "road_wrong_way" in case_result.audit_doc["selected_road_ids"]
    assert "road_downstream" not in case_result.audit_doc["selected_road_ids"]
    assert case_result.key_metrics["selected_road_count"] == 1


def test_rule_d_50m_cap_stays_in_audit_but_does_not_force_review(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100002"
    write_case_package(
        suite_root / case_id,
        case_id,
        roads=[
            road_feature("road_long", case_id, "200001", [(0.0, 0.0), (120.0, 0.0)], direction=2),
        ],
        extra_nodes=[node_feature("200001", 120.0, 0.0, mainnodeid="200001")],
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)

    assert case_result.step3_state == "established"
    assert case_result.reason == "step3_established"
    assert "rule_d_50m_cap_used" not in case_result.audit_doc["review_signals"]
    assert "rule_d_50m_cap_used" not in case_result.review_signals
    assert any(item["cap_hit"] is True for item in case_result.audit_doc["growth_limits"])
    assert case_result.audit_doc["rules"]["D"]["growth_limit_count"] == len(case_result.audit_doc["growth_limits"])
