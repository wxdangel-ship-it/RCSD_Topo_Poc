import csv
import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    EvidenceType,
    ProhibitionStatus,
    run_t09_swsd_field_rule_restoration,
)


def _node(node_id: str, x: float, y: float, *, kind_2: int = 1) -> dict:
    return {"properties": {"id": node_id, "mainnodeid": None, "kind_2": kind_2}, "geometry": Point(x, y)}


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    direction: int,
    coords: list[tuple[float, float]],
) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": 0,
            "kind": "0101",
        },
        "geometry": LineString(coords),
    }


def _write_runner_inputs(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    swnode_gpkg = root / "nodes.gpkg"
    swroad_gpkg = root / "roads.gpkg"
    segment_gpkg = root / "segment.gpkg"
    restriction_gpkg = root / "sw_restriction_tool7.gpkg"
    arrow_gpkg = root / "sw_arrow_tool8.gpkg"
    write_gpkg(
        swnode_gpkg,
        [
            _node("j1", 0.0, 0.0, kind_2=4),
            _node("n_w", -10.0, 0.0),
            _node("n_e", 10.0, 0.0),
            _node("n_n", 0.0, 10.0),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        swroad_gpkg,
        [
            _road("in_w", "n_w", "j1", 2, [(-10.0, 0.0), (0.0, 0.0)]),
            _road("out_e", "j1", "n_e", 2, [(0.0, 0.0), (10.0, 0.0)]),
            _road("out_n", "j1", "n_n", 2, [(0.0, 0.0), (0.0, 10.0)]),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        segment_gpkg,
        [
            {
                "properties": {
                    "id": "seg_1",
                    "sgrade": "0-2双",
                    "pair_nodes": "n_w,n_e",
                    "junc_nodes": "j1",
                    "roads": "in_w,out_e,out_n",
                },
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0), (10.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        restriction_gpkg,
        [
            {
                "properties": {"CondType": 1, "inLinkID": "raw_in_w", "outLinkID": "raw_out_n"},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0), (0.0, 10.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        arrow_gpkg,
        [
            {
                "properties": {
                    "linkid": "raw_in_w",
                    "lane_dir": 2,
                    "road_direction": 2,
                    "arrow": "b",
                    "lane_count": 1,
                    "seq_start": 1,
                    "seq_end": 1,
                    "source_arrow_dir": "b",
                },
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    return swnode_gpkg, swroad_gpkg, segment_gpkg, restriction_gpkg, arrow_gpkg


def test_runner_writes_gpkg_csv_json_outputs_from_t08_inputs(tmp_path: Path) -> None:
    swnode_gpkg, swroad_gpkg, segment_gpkg, restriction_gpkg, arrow_gpkg = _write_runner_inputs(tmp_path / "input")

    run = run_t09_swsd_field_rule_restoration(
        swnode_gpkg=swnode_gpkg,
        swroad_gpkg=swroad_gpkg,
        segment_gpkg=segment_gpkg,
        restriction_gpkg=restriction_gpkg,
        arrow_gpkg=arrow_gpkg,
        output_dir=tmp_path / "out",
        run_id="case_001",
    )

    artifacts = run.artifacts
    expected_paths = [
        artifacts.arms_gpkg,
        artifacts.arms_csv,
        artifacts.arms_json,
        artifacts.movements_gpkg,
        artifacts.movements_csv,
        artifacts.movements_json,
        artifacts.evidence_gpkg,
        artifacts.evidence_csv,
        artifacts.evidence_json,
        artifacts.rules_gpkg,
        artifacts.rules_csv,
        artifacts.rules_json,
        artifacts.summary_json,
    ]
    assert all(path.is_file() for path in expected_paths)

    left_movement = next(item for item in run.result.movements if item.movement_type == "left")
    assert left_movement.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert EvidenceType.CONFLICT in {item.evidence_type for item in run.result.evidence_items}
    assert run.result.restored_rules[0].supporting_evidence_ids

    with fiona.open(artifacts.arms_gpkg) as source:
        assert len(source) == len(run.result.arms)
    with fiona.open(artifacts.movements_gpkg) as source:
        assert len(source) == len(run.result.movements)
    with artifacts.movements_csv.open("r", encoding="utf-8", newline="") as fp:
        movement_rows = list(csv.DictReader(fp))
    assert any(row["movement_type"] == "left" for row in movement_rows)

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["run_id"] == "case_001"
    assert summary["input_audit"]["restrictions"]["restriction_count"] == 1
    assert summary["input_audit"]["arrows"]["arrow_count"] == 1
    assert summary["qa"]["topology_silent_fix"] is False
