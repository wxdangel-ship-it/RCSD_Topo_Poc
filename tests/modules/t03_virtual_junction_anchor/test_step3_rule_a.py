from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from tests.modules.t03_virtual_junction_anchor._case_helpers import (
    node_feature,
    road_feature,
    run_case_bundle,
    write_case_package,
)


def test_rule_a_records_adjacent_junction_cut(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100001"
    write_case_package(
        suite_root / case_id,
        case_id,
        roads=[
            road_feature("road_adj", case_id, "200001", [(0.0, 0.0), (30.0, 0.0)], direction=0),
        ],
        extra_nodes=[node_feature("200001", 30.0, 0.0, mainnodeid="200001")],
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)

    assert case_result.audit_doc["rules"]["A"]["passed"] is True
    assert case_result.audit_doc["rules"]["A"]["count"] == 1
    assert case_result.audit_doc["adjacent_junction_cuts"][0]["road_id"] == "road_adj"
    assert case_result.negative_masks.adjacent_junction_geometry is not None


def test_rule_a_only_cuts_branch_entering_next_junction(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100002"
    write_case_package(
        suite_root / case_id,
        case_id,
        roads=[
            road_feature("road_to_next", case_id, "200001", [(0.0, 0.0), (30.0, 0.0)], direction=0),
            road_feature("road_foreign_foreign", "200001", "300001", [(30.0, 0.0), (60.0, 0.0)], direction=0),
        ],
        extra_nodes=[
            node_feature("200001", 30.0, 0.0, mainnodeid="200001"),
            node_feature("300001", 60.0, 0.0, mainnodeid="300001"),
        ],
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)
    cut_road_ids = {item["road_id"] for item in case_result.audit_doc["adjacent_junction_cuts"]}

    assert cut_road_ids == {"road_to_next"}


def test_rule_a_skips_cut_that_would_block_current_target_core(tmp_path: Path) -> None:
    suite_root = tmp_path / "suite"
    case_id = "100003"
    write_case_package(
        suite_root / case_id,
        case_id,
        kind_2=2048,
        roads=[
            road_feature("road_short_to_foreign", case_id, "200001", [(0.0, 0.0), (12.0, 0.0)], direction=0),
        ],
        extra_nodes=[node_feature("200001", 12.0, 0.0, mainnodeid="200001")],
        drivezone_geometry=box(-5.0, -5.0, 2.5, 5.0),
    )

    _context, _template_result, case_result = run_case_bundle(suite_root, case_id)
    cut_road_ids = {item["road_id"] for item in case_result.audit_doc["adjacent_junction_cuts"]}

    assert cut_road_ids == set()
    assert case_result.audit_doc["rules"]["A"]["count"] == 0
    assert case_result.audit_doc["rules"]["A"]["suppressed_count"] == 1
    assert case_result.audit_doc["rules"]["A"]["target_core_protection_applied"] is True
    assert case_result.audit_doc["rules"]["A"]["target_core_protection_reason"] == "target_core_or_bridge_overlap"
    assert case_result.audit_doc["adjacent_junction_cut_suppressed"][0]["road_id"] == "road_short_to_foreign"
    assert case_result.audit_doc["adjacent_junction_cut_suppressed"][0]["suppress_reason"] in {
        "overlaps_target_core_or_bridge",
        "emptied_by_target_core_or_bridge_protection",
    }
    assert case_result.audit_doc["adjacent_junction_cut_protection_applied"] is True
    assert case_result.audit_doc["adjacent_junction_cut_protection_reason"] == "target_core_or_bridge_overlap"
    assert case_result.key_metrics["selected_road_count"] == 1
    assert case_result.reason == "step3_established"
