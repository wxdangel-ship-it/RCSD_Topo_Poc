from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.p01_arm_build.alignment_io import load_datasets_from_a1_preflight
from rcsd_topo_poc.modules.p01_arm_build.case_scope import load_case_scoped_dataset
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput
from rcsd_topo_poc.modules.p01_arm_build.road_next_road import read_road_next_road


def _write_nodes(path: Path) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for node_id, mainnodeid, x, y, kind in [
            ("C", "C", 0.0, 0.0, "4"),
            ("N1", "", 10.0, 0.0, "1"),
            ("N2", "N2", 20.0, 0.0, "4"),
            ("FAR1", "", 1000.0, 0.0, "1"),
            ("FAR2", "", 1010.0, 0.0, "1"),
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
        "properties": {
            "id": "str",
            "snodeid": "str",
            "enodeid": "str",
            "direction": "int",
            "formway": "str",
            "Source": "str",
        },
    }
    roads = [
        ("r1", "C", "N1", [(0.0, 0.0), (10.0, 0.0)]),
        ("r2", "N1", "N2", [(10.0, 0.0), (20.0, 0.0)]),
        ("far", "FAR1", "FAR2", [(1000.0, 0.0), (1010.0, 0.0)]),
    ]
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, coords in roads:
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": {
                        "id": road_id,
                        "snodeid": snodeid,
                        "enodeid": enodeid,
                        "direction": 2,
                        "formway": "0",
                        "Source": "2",
                    },
                }
            )


def test_case_scope_bfs_loads_nearby_subgraph_and_preserves_fields(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(nodes_path)
    _write_roads(roads_path)

    scoped = load_case_scoped_dataset(
        DatasetInput("SWSD", nodes_path, roads_path),
        junction_id="C",
        bfs_depth=1,
    )

    assert set(scoped.loaded.nodes) == {"C", "N1", "N2"}
    assert set(scoped.loaded.roads) == {"r1", "r2"}
    assert scoped.loaded.roads["r1"].properties["source"] == "2"
    assert scoped.audit["bfs_depth"] == 1
    assert scoped.audit["source_road_feature_count"] == 3


def test_road_next_road_stream_filter_keeps_only_case_scoped_records(tmp_path: Path) -> None:
    road_next_road = tmp_path / "RoadNextRoad.geojson"
    road_next_road.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"id": "keep", "road_id": "r1", "next_road_id": "r2"}},
                    {"type": "Feature", "properties": {"id": "drop", "road_id": "far", "next_road_id": "far2"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    records = read_road_next_road(road_next_road, selected_road_ids={"r1", "r2"})

    assert [record.raw_id for record in records] == ["keep"]


def test_a2_geometry_loader_reuses_single_case_scope_from_preflight(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(nodes_path)
    _write_roads(roads_path)
    preflight = {
        "input_paths": {
            dataset: {"nodes": str(nodes_path), "roads": str(roads_path)}
            for dataset in ("SWSD", "RCSD", "FRCSD")
        },
        "junction_groups": [
            {
                "group_id": "group_0001",
                "swsd_junction_id": "C",
                "rcsd_junction_id": "C",
                "frcsd_junction_id": "C",
            }
        ],
        "case_scope": {"enabled": True, "bfs_depth": 1},
    }

    loaded, errors = load_datasets_from_a1_preflight(preflight)

    assert errors == {}
    assert set(loaded) == {"SWSD", "RCSD", "FRCSD"}
    assert set(loaded["SWSD"].roads) == {"r1", "r2"}
