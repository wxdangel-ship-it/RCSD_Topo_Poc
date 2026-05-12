from __future__ import annotations

from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput
from rcsd_topo_poc.modules.p01_arm_build.topology import build_dataset_arm_result


def _write_nodes(path: Path) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for node_id, mainnodeid, x, y, kind in [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 30.0, "1"),
            ("A", None, -15.0, 20.0, "1"),
            ("E", None, 30.0, 0.0, "1"),
        ]:
            sink.write(
                {
                    "geometry": mapping(Point(x, y)),
                    "properties": {"id": node_id, "mainnodeid": mainnodeid, "kind": kind},
                }
            )


def _write_roads(path: Path) -> None:
    schema = {
        "geometry": "LineString",
        "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "formway": "str"},
    }
    roads = [
        ("main_in", "N", "C", 2, "0", [(0.0, 30.0), (0.0, 0.0)]),
        ("inside_adv_right", "A", "C", 2, "128", [(-15.0, 20.0), (0.0, 0.0)]),
        ("main_out", "C", "E", 2, "0", [(0.0, 0.0), (30.0, 0.0)]),
    ]
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, direction, formway, coords in roads:
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": {
                        "id": road_id,
                        "snodeid": snodeid,
                        "enodeid": enodeid,
                        "direction": direction,
                        "formway": formway,
                    },
                }
            )


def test_inside_advance_right_turn_enters_arm_but_not_relation_or_trunk(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(nodes_path)
    _write_roads(roads_path)

    loaded = load_dataset(DatasetInput(dataset="FRCSD", nodes_path=nodes_path, roads_path=roads_path))
    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values=set())

    assert result.context.advance_right_turn_road_ids == ("inside_adv_right",)
    assert "inside_adv_right" in result.context.inbound_seed_road_ids
    assert result.advance_right_turn_relations == tuple()

    arm = next(arm for arm in result.initial_arms if "inside_adv_right" in arm.member_road_ids)
    assert "inside_adv_right" in arm.seed_road_ids
    assert "inside_adv_right" in arm.inbound_member_road_ids
    assert "inside_adv_right" in arm.non_trunk_member_road_ids
    assert "inside_adv_right" not in arm.trunk_road_ids
    assert all(
        issue.get("issue_type") != "advance_right_turn_in_arm_member_error"
        for issue in result.issue_report.issues
    )
