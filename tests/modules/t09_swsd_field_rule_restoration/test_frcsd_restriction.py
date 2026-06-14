from __future__ import annotations

import csv
import json
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg, write_json
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import run_t09_frcsd_restriction_modeling


def test_step3_generates_frcsd_restriction_from_t06_segment_relation(tmp_path: Path) -> None:
    arms_path = tmp_path / "t09_swsd_arms.json"
    movements_path = tmp_path / "t09_arm_movements.json"
    rules_path = tmp_path / "t09_restored_field_rules.json"
    frcsd_road_path = tmp_path / "t06_frcsd_road.gpkg"
    frcsd_node_path = tmp_path / "t06_frcsd_node.gpkg"
    relation_path = tmp_path / "t06_step3_swsd_frcsd_segment_relation.gpkg"

    write_json(
        arms_path,
        [
            {
                "junction_id": "j1",
                "arm_id": "arm_w",
                "member_node_ids": ["j1"],
                "segment_ids": ["seg_w"],
                "approach_road_ids": ["sw_in_w"],
                "exit_road_ids": [],
            },
            {
                "junction_id": "j1",
                "arm_id": "arm_e",
                "member_node_ids": ["j1"],
                "segment_ids": ["seg_e"],
                "approach_road_ids": [],
                "exit_road_ids": ["sw_out_e"],
            },
        ],
    )
    write_json(
        movements_path,
        [
            {
                "junction_id": "j1",
                "movement_id": "movement_1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "straight",
                "prohibition_reason": "explicit_restriction",
                "prohibition_confidence": 1.0,
                "risk_flags": [],
            },
            {
                "junction_id": "j1",
                "movement_id": "movement_arrow_only",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "uturn",
                "prohibition_reason": "complete_arrow_exclusion",
                "prohibition_confidence": 0.75,
                "risk_flags": [],
            }
        ],
    )
    write_json(
        rules_path,
        [
            {
                "junction_id": "j1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "straight",
                "field_rule_status": "fully_prohibited",
                "confidence": 1.0,
                "supporting_evidence_ids": ["restriction:1"],
                "risk_flags": [],
            },
            {
                "junction_id": "j1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "straight",
                "field_rule_status": "fully_prohibited",
                "confidence": 1.0,
                "supporting_evidence_ids": ["restriction:duplicate"],
            },
            {
                "junction_id": "j1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "uturn",
                "field_rule_status": "fully_prohibited",
                "confidence": 0.75,
                "supporting_evidence_ids": ["arrow:exclusion"],
            },
            {
                "junction_id": "j1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "right",
                "field_rule_status": "partially_prohibited",
                "confidence": 0.5,
            },
            {
                "junction_id": "j1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "left",
                "field_rule_status": "unknown",
            },
        ],
    )
    write_gpkg(
        frcsd_node_path,
        [
            {"properties": {"id": "fw", "mainnodeid": 0, "source": 1}, "geometry": Point(-10.0, 0.0)},
            {"properties": {"id": "fj", "mainnodeid": "j1", "source": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "j1", "mainnodeid": 0, "source": 2}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "fe", "mainnodeid": 0, "source": 2}, "geometry": Point(10.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        frcsd_road_path,
        [
            {
                "properties": {"id": "fr_in_w", "snodeid": "fw", "enodeid": "fj", "direction": 2, "source": 1},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "sw_out_e", "snodeid": "j1", "enodeid": "fe", "direction": 2, "source": 2},
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        relation_path,
        [
            {
                "properties": {
                    "swsd_segment_id": "seg_w",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["fr_in_w"],
                    "frcsd_road_source_values": [1],
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "j1", "frcsd_node_ids": ["fj"], "node_role": "junc_node"}
                    ],
                },
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {
                    "swsd_segment_id": "seg_e",
                    "relation_status": "retained_swsd",
                    "frcsd_road_ids": ["sw_out_e"],
                    "frcsd_road_source_values": [2],
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "j1", "frcsd_node_ids": ["j1"], "node_role": "junc_node"}
                    ],
                },
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    result = run_t09_frcsd_restriction_modeling(
        arms_path=arms_path,
        movements_path=movements_path,
        restored_rules_path=rules_path,
        frcsd_road_path=frcsd_road_path,
        frcsd_node_path=frcsd_node_path,
        segment_relation_path=relation_path,
        output_dir=tmp_path / "out",
        run_id="case_001",
    )

    assert result.restriction_count == 1
    assert result.summary["skipped_counts"] == {
        "duplicate_link_pair": 1,
        "rule_reason:complete_arrow_exclusion": 1,
        "rule_status:partially_prohibited": 1,
        "rule_status:unknown": 1,
    }
    with fiona.open(result.artifacts.frcsd_restriction_gpkg) as source:
        rows = [dict(feature["properties"]) for feature in source]
    assert rows[0]["LinkID"] == "fr_in_w"
    assert rows[0]["outLinkID"] == "sw_out_e"
    assert rows[0]["from_road_source"] == "1"
    assert rows[0]["to_road_source"] == "2"
    assert rows[0]["restriction_source"] == "explicit_restriction"

    with result.artifacts.frcsd_restriction_csv.open("r", encoding="utf-8", newline="") as fp:
        csv_rows = list(csv.DictReader(fp))
    assert csv_rows[0]["supporting_evidence_ids"] == '["restriction:1"]'
    payload = json.loads(result.artifacts.frcsd_restriction_json.read_text(encoding="utf-8"))
    assert payload["row_count"] == 1


def test_step3_uses_retained_swsd_seed_road_still_present_in_frcsd(tmp_path: Path) -> None:
    arms_path = tmp_path / "t09_swsd_arms.json"
    movements_path = tmp_path / "t09_arm_movements.json"
    rules_path = tmp_path / "t09_restored_field_rules.json"
    frcsd_road_path = tmp_path / "t06_frcsd_road.gpkg"
    frcsd_node_path = tmp_path / "t06_frcsd_node.gpkg"
    relation_path = tmp_path / "t06_step3_swsd_frcsd_segment_relation.gpkg"

    write_json(
        arms_path,
        [
            {
                "junction_id": "j1",
                "arm_id": "arm_w",
                "member_node_ids": ["j1"],
                "segment_ids": [],
                "approach_road_ids": ["sw_in_w"],
                "exit_road_ids": [],
            },
            {
                "junction_id": "j1",
                "arm_id": "arm_e",
                "member_node_ids": ["j1"],
                "segment_ids": ["seg_e"],
                "approach_road_ids": [],
                "exit_road_ids": ["sw_out_e"],
            },
        ],
    )
    write_json(
        movements_path,
        [
            {
                "junction_id": "j1",
                "movement_id": "movement_seed_fallback",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "straight",
                "prohibition_reason": "explicit_restriction",
                "prohibition_confidence": 1.0,
            }
        ],
    )
    write_json(
        rules_path,
        [
            {
                "junction_id": "j1",
                "from_arm_id": "arm_w",
                "to_arm_id": "arm_e",
                "movement_type": "straight",
                "field_rule_status": "fully_prohibited",
                "confidence": 1.0,
                "supporting_evidence_ids": ["restriction:seed-fallback"],
            }
        ],
    )
    write_gpkg(
        frcsd_node_path,
        [
            {"properties": {"id": "fw", "mainnodeid": 0, "source": 2}, "geometry": Point(-10.0, 0.0)},
            {"properties": {"id": "j1", "mainnodeid": 0, "source": 2}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "fe", "mainnodeid": 0, "source": 2}, "geometry": Point(10.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        frcsd_road_path,
        [
            {
                "properties": {"id": "sw_in_w", "snodeid": "fw", "enodeid": "j1", "direction": 2, "source": 2},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "sw_out_e", "snodeid": "j1", "enodeid": "fe", "direction": 2, "source": 2},
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        relation_path,
        [
            {
                "properties": {
                    "swsd_segment_id": "seg_e",
                    "relation_status": "retained_swsd",
                    "frcsd_road_ids": ["sw_out_e"],
                    "frcsd_road_source_values": [2],
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "j1", "frcsd_node_ids": ["j1"], "node_role": "junc_node"}
                    ],
                },
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    result = run_t09_frcsd_restriction_modeling(
        arms_path=arms_path,
        movements_path=movements_path,
        restored_rules_path=rules_path,
        frcsd_road_path=frcsd_road_path,
        frcsd_node_path=frcsd_node_path,
        segment_relation_path=relation_path,
        output_dir=tmp_path / "out",
        run_id="case_seed_fallback",
    )

    assert result.restriction_count == 1
    assert result.summary["skipped_counts"] == {}
    assert result.summary["arm_carrier_relation_status_counts"]["retained_swsd_seed_fallback"] == 1
    assert result.summary["arm_carrier_risk_flag_counts"]["retained_swsd_seed_carrier_fallback"] == 1
    with fiona.open(result.artifacts.frcsd_restriction_gpkg) as source:
        rows = [dict(feature["properties"]) for feature in source]
    assert rows[0]["LinkID"] == "sw_in_w"
    assert rows[0]["outLinkID"] == "sw_out_e"
    assert rows[0]["from_arm_relation_status"] == "retained_swsd_seed_fallback"
    assert "retained_swsd_seed_carrier_fallback" in rows[0]["risk_flags"]


@pytest.mark.parametrize("relation_status", ["retained_swsd", "replaced+retained_swsd"])
def test_step3_retained_swsd_relation_keeps_carrier_within_arm_seed_roads(
    tmp_path: Path, relation_status: str
) -> None:
    arms_path = tmp_path / "t09_swsd_arms.json"
    movements_path = tmp_path / "t09_arm_movements.json"
    rules_path = tmp_path / "t09_restored_field_rules.json"
    frcsd_road_path = tmp_path / "t06_frcsd_road.gpkg"
    frcsd_node_path = tmp_path / "t06_frcsd_node.gpkg"
    relation_path = tmp_path / "t06_step3_swsd_frcsd_segment_relation.gpkg"

    write_json(
        arms_path,
        [
            {
                "junction_id": "j_main",
                "arm_id": "arm_other",
                "member_node_ids": ["j_main", "j_sub"],
                "segment_ids": ["seg_shared"],
                "approach_road_ids": ["other_in"],
                "exit_road_ids": ["other_out"],
            },
            {
                "junction_id": "j_main",
                "arm_id": "arm_seed",
                "member_node_ids": ["j_main", "j_sub"],
                "segment_ids": ["seg_shared"],
                "approach_road_ids": ["seed_in"],
                "exit_road_ids": ["seed_out"],
            },
        ],
    )
    write_json(
        movements_path,
        [
            {
                "junction_id": "j_main",
                "movement_id": "movement_seed_uturn",
                "from_arm_id": "arm_seed",
                "to_arm_id": "arm_seed",
                "movement_type": "uturn",
                "prohibition_reason": "explicit_restriction",
                "prohibition_confidence": 1.0,
            }
        ],
    )
    write_json(
        rules_path,
        [
            {
                "junction_id": "j_main",
                "from_arm_id": "arm_seed",
                "to_arm_id": "arm_seed",
                "movement_type": "uturn",
                "field_rule_status": "fully_prohibited",
                "confidence": 1.0,
                "supporting_evidence_ids": ["restriction:seed-uturn"],
            }
        ],
    )
    write_gpkg(
        frcsd_node_path,
        [
            {
                "properties": {"id": "j_main", "mainnodeid": "j_main", "subnodeid": ["j_sub"], "source": 2},
                "geometry": Point(0.0, 0.0),
            },
            {"properties": {"id": "j_sub", "mainnodeid": "j_main", "source": 2}, "geometry": Point(1.0, 0.0)},
            {"properties": {"id": "seed_outer_in", "mainnodeid": 0, "source": 2}, "geometry": Point(-10.0, 0.0)},
            {"properties": {"id": "seed_outer_out", "mainnodeid": 0, "source": 2}, "geometry": Point(10.0, 0.0)},
            {"properties": {"id": "other_outer_in", "mainnodeid": 0, "source": 2}, "geometry": Point(-10.0, 1.0)},
            {"properties": {"id": "other_outer_out", "mainnodeid": 0, "source": 2}, "geometry": Point(10.0, 1.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        frcsd_road_path,
        [
            {
                "properties": {"id": "seed_in", "snodeid": "seed_outer_in", "enodeid": "j_main", "direction": 2, "source": 2},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "seed_out", "snodeid": "j_main", "enodeid": "seed_outer_out", "direction": 2, "source": 2},
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
            {
                "properties": {"id": "other_in", "snodeid": "other_outer_in", "enodeid": "j_sub", "direction": 2, "source": 2},
                "geometry": LineString([(-10.0, 1.0), (1.0, 0.0)]),
            },
            {
                "properties": {"id": "other_out", "snodeid": "j_sub", "enodeid": "other_outer_out", "direction": 2, "source": 2},
                "geometry": LineString([(1.0, 0.0), (10.0, 1.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        relation_path,
        [
            {
                "properties": {
                    "swsd_segment_id": "seg_shared",
                    "relation_status": relation_status,
                    "frcsd_road_ids": ["seed_in", "seed_out", "other_in", "other_out"],
                    "frcsd_road_source_values": [2],
                    "swsd_to_frcsd_node_map": [
                        {"swsd_node_id": "j_main", "frcsd_node_ids": ["j_main"], "node_role": "junc_node"}
                    ],
                },
                "geometry": LineString([(-10.0, 0.0), (10.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    result = run_t09_frcsd_restriction_modeling(
        arms_path=arms_path,
        movements_path=movements_path,
        restored_rules_path=rules_path,
        frcsd_road_path=frcsd_road_path,
        frcsd_node_path=frcsd_node_path,
        segment_relation_path=relation_path,
        output_dir=tmp_path / "out",
        run_id="case_retained_seed_scope",
    )

    assert result.restriction_count == 1
    with fiona.open(result.artifacts.frcsd_restriction_gpkg) as source:
        rows = [dict(feature["properties"]) for feature in source]
    assert rows[0]["LinkID"] == "seed_in"
    assert rows[0]["outLinkID"] == "seed_out"
