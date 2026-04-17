from __future__ import annotations

from pathlib import Path

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
