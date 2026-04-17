from __future__ import annotations

from tests.modules.t03_virtual_junction_anchor._regression_utils import load_real_case_bundle


def test_case_698330_traces_both_inbound_and_outbound_branch_roads_to_adjacent_junctions() -> None:
    _context, _template_result, case_result = load_real_case_bundle("698330")
    audit_doc = case_result.audit_doc

    cut_road_ids = {item["road_id"] for item in audit_doc["adjacent_junction_cuts"]}
    selected_road_ids = set(audit_doc["selected_road_ids"])

    assert {"972225", "972227", "621944468"}.issubset(cut_road_ids)
    assert "511947045" not in cut_road_ids
    assert {"972225", "972227", "621944468"}.issubset(selected_road_ids)
