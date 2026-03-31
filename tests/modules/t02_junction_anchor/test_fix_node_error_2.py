from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.fix_node_error_2 import run_t02_fix_node_error_2


INTERSECTION_GEOMETRY = Polygon([(-1.0, -1.0), (30.0, -1.0), (30.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)])
OUTSIDE_GEOMETRY = Polygon([(40.0, -1.0), (50.0, -1.0), (50.0, 1.0), (40.0, 1.0), (40.0, -1.0)])


def _node(
    node_id: str,
    x: float,
    y: float,
    *,
    mainnodeid: str | None,
    kind_2: int | None,
    grade_2: int | None,
    subnodeid: str | None = None,
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "subnodeid": subnodeid,
        },
        "geometry": Point(x, y),
    }


def _road(road_id: str, snodeid: str, enodeid: str, coords: list[tuple[float, float]]) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": 0,
        },
        "geometry": LineString(coords),
    }


def _error_node(node_id: str, junction_id: str, x: float, y: float) -> dict:
    return {
        "properties": {
            "id": node_id,
            "junction_id": junction_id,
            "error_type": "node_error_2",
        },
        "geometry": Point(x, y),
    }


def _intersection(intersection_id: str, geometry=INTERSECTION_GEOMETRY) -> dict:
    return {
        "properties": {"id": intersection_id},
        "geometry": geometry,
    }


def _write_inputs(
    root: Path,
    *,
    nodes: list[dict],
    roads: list[dict],
    error_nodes: list[dict],
    intersections: list[dict],
) -> tuple[Path, Path, Path, Path]:
    node_error2_path = root / "node_error_2.gpkg"
    nodes_path = root / "nodes.gpkg"
    roads_path = root / "roads.gpkg"
    intersection_path = root / "RCSDIntersection.gpkg"
    write_vector(node_error2_path, error_nodes, crs_text="EPSG:3857")
    write_vector(nodes_path, nodes, crs_text="EPSG:3857")
    write_vector(roads_path, roads, crs_text="EPSG:3857")
    write_vector(intersection_path, intersections, crs_text="EPSG:3857")
    return node_error2_path, nodes_path, roads_path, intersection_path


def _load_properties_by_id(path: Path) -> dict[str, dict]:
    with fiona.open(path) as src:
        return {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in src}


def _load_ids(path: Path) -> list[str]:
    with fiona.open(path) as src:
        return [str(feature["properties"]["id"]) for feature in src]


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_tool(tmp_path: Path, *, nodes: list[dict], roads: list[dict], error_nodes: list[dict], intersections: list[dict]):
    node_error2_path, nodes_path, roads_path, intersection_path = _write_inputs(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )
    nodes_fix_path = tmp_path / "nodes_fix.gpkg"
    roads_fix_path = tmp_path / "roads_fix.gpkg"
    report_path = tmp_path / "fix_report.json"
    artifacts = run_t02_fix_node_error_2(
        node_error2_path=node_error2_path,
        nodes_path=nodes_path,
        roads_path=roads_path,
        intersection_path=intersection_path,
        nodes_fix_path=nodes_fix_path,
        roads_fix_path=roads_fix_path,
        report_path=report_path,
    )
    return artifacts, nodes_path, roads_path, nodes_fix_path, roads_fix_path, report_path


def test_fix_node_error_2_skips_when_intersection_has_single_group(tmp_path: Path) -> None:
    nodes = [
        _node("10", 0.0, 0.0, mainnodeid="10", kind_2=4, grade_2=2),
        _node("900", 40.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
        _node("901", 41.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
    ]
    roads = [_road("r-out", "900", "901", [(40.0, 0.0), (41.0, 0.0)])]
    error_nodes = [_error_node("10", "10", 0.0, 0.0)]
    intersections = [_intersection("A")]

    _, _, _, nodes_fix_path, roads_fix_path, report_path = _run_tool(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )

    assert _load_properties_by_id(nodes_fix_path)["10"]["mainnodeid"] == "10"
    assert _load_ids(roads_fix_path) == ["r-out"]
    report = _load_report(report_path)
    assert report["counts"]["merged_intersection_count"] == 0
    assert report["rows"][0]["skip_reason"] == "single_group_in_intersection"


def test_fix_node_error_2_ignores_kind1_groups(tmp_path: Path) -> None:
    nodes = [
        _node("10", 0.0, 0.0, mainnodeid="10", kind_2=1, grade_2=1),
        _node("20", 10.0, 0.0, mainnodeid="20", kind_2=4, grade_2=2),
    ]
    roads = [_road("r-1", "10", "20", [(0.0, 0.0), (10.0, 0.0)])]
    error_nodes = [
        _error_node("10", "10", 0.0, 0.0),
        _error_node("20", "20", 10.0, 0.0),
    ]
    intersections = [_intersection("A")]

    _, _, _, nodes_fix_path, roads_fix_path, report_path = _run_tool(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )

    report = _load_report(report_path)
    assert report["counts"]["merged_intersection_count"] == 0
    assert report["rows"][0]["ignored_kind1_group_ids"] == ["10"]
    assert report["rows"][0]["skip_reason"] == "single_group_after_kind1_filter"
    assert _load_properties_by_id(nodes_fix_path)["20"]["mainnodeid"] == "20"
    assert _load_ids(roads_fix_path) == ["r-1"]


def test_fix_node_error_2_merges_connected_groups_and_updates_nodes_and_roads(tmp_path: Path) -> None:
    nodes = [
        _node("10", 0.0, 0.0, mainnodeid="10", kind_2=64, grade_2=2),
        _node("11", 2.0, 0.0, mainnodeid="10", kind_2=0, grade_2=0),
        _node("20", 10.0, 0.0, mainnodeid="20", kind_2=2048, grade_2=1),
        _node("21", 12.0, 0.0, mainnodeid="20", kind_2=0, grade_2=0),
        _node("300", 60.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
    ]
    roads = [
        _road("r-in-1", "10", "20", [(0.0, 0.0), (10.0, 0.0)]),
        _road("r-in-2", "11", "21", [(2.0, 0.0), (12.0, 0.0)]),
        _road("r-keep", "20", "300", [(10.0, 0.0), (60.0, 0.0)]),
        _road("r-outside", "10", "20", [(40.0, 0.0), (50.0, 0.0)]),
    ]
    error_nodes = [
        _error_node("10", "10", 0.0, 0.0),
        _error_node("20", "20", 10.0, 0.0),
    ]
    intersections = [_intersection("A")]

    _, nodes_path, roads_path, nodes_fix_path, roads_fix_path, report_path = _run_tool(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )

    nodes_fix = _load_properties_by_id(nodes_fix_path)
    assert nodes_fix["10"]["mainnodeid"] == "10"
    assert nodes_fix["10"]["kind_2"] == 4
    assert nodes_fix["10"]["grade_2"] == 1
    assert nodes_fix["10"]["subnodeid"] == "11,20,21"
    for node_id in ("11", "20", "21"):
        assert nodes_fix[node_id]["mainnodeid"] == "10"
        assert nodes_fix[node_id]["kind_2"] == 0
        assert nodes_fix[node_id]["grade_2"] == 0
        assert nodes_fix[node_id]["subnodeid"] is None

    roads_fix_ids = set(_load_ids(roads_fix_path))
    assert "r-in-1" not in roads_fix_ids
    assert "r-in-2" not in roads_fix_ids
    assert "r-keep" in roads_fix_ids
    assert "r-outside" in roads_fix_ids

    report = _load_report(report_path)
    assert report["counts"]["merged_intersection_count"] == 1
    assert report["rows"][0]["status"] == "merged"
    assert report["rows"][0]["chosen_mainnodeid"] == "10"
    assert report["rows"][0]["deleted_road_ids"] == ["r-in-1", "r-in-2"]

    original_nodes = _load_properties_by_id(nodes_path)
    original_roads = set(_load_ids(roads_path))
    assert original_nodes["20"]["mainnodeid"] == "20"
    assert original_nodes["20"]["kind_2"] == 2048
    assert original_roads == {"r-in-1", "r-in-2", "r-keep", "r-outside"}


def test_fix_node_error_2_blocks_path_through_other_semantic_group(tmp_path: Path) -> None:
    nodes = [
        _node("10", 0.0, 0.0, mainnodeid="10", kind_2=4, grade_2=2),
        _node("20", 20.0, 0.0, mainnodeid="20", kind_2=4, grade_2=2),
        _node("30", 10.0, 0.0, mainnodeid="30", kind_2=4, grade_2=1),
        _node("100", 5.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
        _node("101", 15.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
        _node("102", 10.0, 0.5, mainnodeid=None, kind_2=None, grade_2=None),
    ]
    roads = [
        _road("r-1", "10", "100", [(0.0, 0.0), (5.0, 0.0)]),
        _road("r-2", "100", "30", [(5.0, 0.0), (10.0, 0.0)]),
        _road("r-3", "30", "101", [(10.0, 0.0), (15.0, 0.0)]),
        _road("r-4", "101", "20", [(15.0, 0.0), (20.0, 0.0)]),
        _road("r-5", "30", "102", [(10.0, 0.0), (10.0, 0.5)]),
    ]
    error_nodes = [
        _error_node("10", "10", 0.0, 0.0),
        _error_node("20", "20", 20.0, 0.0),
    ]
    intersections = [_intersection("A")]

    _, _, _, nodes_fix_path, roads_fix_path, report_path = _run_tool(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )

    report = _load_report(report_path)
    assert report["counts"]["merged_intersection_count"] == 0
    assert report["rows"][0]["skip_reason"] == "not_all_groups_connected"
    assert _load_properties_by_id(nodes_fix_path)["20"]["mainnodeid"] == "20"
    assert set(_load_ids(roads_fix_path)) == {"r-1", "r-2", "r-3", "r-4", "r-5"}


def test_fix_node_error_2_allows_degree2_transition_nodes(tmp_path: Path) -> None:
    nodes = [
        _node("10", 0.0, 0.0, mainnodeid="10", kind_2=4, grade_2=2),
        _node("20", 20.0, 0.0, mainnodeid="20", kind_2=4, grade_2=2),
        _node("100", 5.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
        _node("101", 15.0, 0.0, mainnodeid=None, kind_2=None, grade_2=None),
    ]
    roads = [
        _road("r-1", "10", "100", [(0.0, 0.0), (5.0, 0.0)]),
        _road("r-2", "100", "101", [(5.0, 0.0), (15.0, 0.0)]),
        _road("r-3", "101", "20", [(15.0, 0.0), (20.0, 0.0)]),
    ]
    error_nodes = [
        _error_node("10", "10", 0.0, 0.0),
        _error_node("20", "20", 20.0, 0.0),
    ]
    intersections = [_intersection("A")]

    _, _, _, nodes_fix_path, roads_fix_path, report_path = _run_tool(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )

    report = _load_report(report_path)
    assert report["counts"]["merged_intersection_count"] == 1
    assert report["rows"][0]["status"] == "merged"
    assert _load_properties_by_id(nodes_fix_path)["20"]["mainnodeid"] == "10"
    assert set(_load_ids(roads_fix_path)) == {"r-1", "r-2", "r-3"}


def test_fix_node_error_2_supports_nodes_kind_grade_schema(tmp_path: Path) -> None:
    nodes = [
        {
            "properties": {"id": "10", "mainnodeid": "10", "kind": 64, "grade": 2, "subnodeid": None},
            "geometry": Point(0.0, 0.0),
        },
        {
            "properties": {"id": "20", "mainnodeid": "20", "kind": 2048, "grade": 1, "subnodeid": None},
            "geometry": Point(10.0, 0.0),
        },
    ]
    roads = [_road("r-1", "10", "20", [(0.0, 0.0), (10.0, 0.0)])]
    error_nodes = [
        _error_node("10", "10", 0.0, 0.0),
        _error_node("20", "20", 10.0, 0.0),
    ]
    intersections = [_intersection("A")]

    _, _, _, nodes_fix_path, roads_fix_path, report_path = _run_tool(
        tmp_path,
        nodes=nodes,
        roads=roads,
        error_nodes=error_nodes,
        intersections=intersections,
    )

    nodes_fix = _load_properties_by_id(nodes_fix_path)
    assert nodes_fix["10"]["kind"] == 4
    assert nodes_fix["10"]["grade"] == 1
    assert nodes_fix["20"]["mainnodeid"] == "10"
    assert _load_ids(roads_fix_path) == []
    report = _load_report(report_path)
    assert report["schema"]["nodes_kind_field"] == "kind"
    assert report["schema"]["nodes_grade_field"] == "grade"
