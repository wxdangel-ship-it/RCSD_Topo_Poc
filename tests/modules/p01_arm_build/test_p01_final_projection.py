from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p01_arm_build.final_road_next_road import build_frcsd_road_next_road, final_geojson
from rcsd_topo_poc.modules.p01_arm_build.road_next_road import read_road_next_road
from tests.modules.p01_arm_build.test_p01_arm_build import (
    _build_result,
    _frcsd_source_fixture,
    _renamed_source_fixture,
)


def test_frcsd_final_uses_alternate_source_role_ordinal_projection_when_primary_has_no_rule(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    rcsd_rnr = tmp_path / "rcsd_alternate_source_rnr.geojson"
    rcsd_rnr.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"id": "r_main", "road_id": "r_w_in", "next_road_id": "r_e_main"},
                    },
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"id": "r_branch", "road_id": "r_w_in", "next_road_id": "r_e_left_recv"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    rcsd_records = read_road_next_road(rcsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads, rcsd_records)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": rcsd_records, "FRCSD": tuple()},
    )

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in final_geojson(final)["features"]}
    assert ("f_w_in", "f_e_main") in pairs
    assert any(item.generation_rule == "alternate_source_role_ordinal_projection" for item in final.audit)
    assert final.metrics["frcsd_alternate_source_projected_count"] >= 1


def test_road_next_road_out_of_scope_records_are_skipped_from_case_mapping(tmp_path: Path) -> None:
    nodes_path, roads_path = _renamed_source_fixture(tmp_path, "s")
    road_next_road = tmp_path / "large_scope_rnr.json"
    road_next_road.write_text(
        json.dumps(
            [
                {"id": "case_evidence", "road_id": "s_w_in", "next_road_id": "s_e_main"},
                {"id": "noise_1", "road_id": "far_road_1", "next_road_id": "far_road_2"},
                {"id": "noise_2", "road_id": "far_road_3", "next_road_id": "far_road_4"},
            ]
        ),
        encoding="utf-8",
    )
    records = read_road_next_road(road_next_road)
    _, result = _build_result("SWSD", nodes_path, roads_path, records)

    assert result.metrics["road_movement_input_record_count"] == 3
    assert result.metrics["road_movement_case_scoped_record_count"] == 1
    assert result.metrics["road_movement_out_of_scope_skipped_count"] == 2
    assert "road_movement_cross_junction_or_out_of_scope" not in result.issue_report.issue_counts
