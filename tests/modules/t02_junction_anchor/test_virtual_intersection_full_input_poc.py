from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
import rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_full_input_poc as full_input_module
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_full_input_poc import (
    run_t02_virtual_intersection_full_input_poc,
)


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _shift_xy(coords: list[tuple[float, float]], dx: float, dy: float = 0.0) -> list[tuple[float, float]]:
    return [(x + dx, y + dy) for x, y in coords]


def _append_case(
    *,
    features: dict[str, list[dict]],
    mainnodeid: str,
    dx: float,
) -> None:
    node_id = mainnodeid
    sibling_id = str(int(mainnodeid) + 1)
    north_tip = str(int(mainnodeid) + 100)
    south_tip = str(int(mainnodeid) + 200)
    east_tip = str(int(mainnodeid) + 300)

    features["nodes"].extend(
        [
            {
                "properties": {
                    "id": node_id,
                    "mainnodeid": node_id,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 2048,
                    "grade_2": 1,
                },
                "geometry": Point(dx, 0.0),
            },
            {
                "properties": {
                    "id": sibling_id,
                    "mainnodeid": node_id,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 2048,
                    "grade_2": 1,
                },
                "geometry": Point(dx + 6.0, 2.0),
            },
        ]
    )

    features["roads"].extend(
        [
            {
                "properties": {"id": f"road_north_{node_id}", "snodeid": node_id, "enodeid": north_tip, "direction": 2},
                "geometry": LineString(_shift_xy([(0.0, 0.0), (0.0, 60.0)], dx)),
            },
            {
                "properties": {"id": f"road_south_{node_id}", "snodeid": south_tip, "enodeid": node_id, "direction": 2},
                "geometry": LineString(_shift_xy([(0.0, -60.0), (0.0, 0.0)], dx)),
            },
            {
                "properties": {"id": f"road_east_{node_id}", "snodeid": node_id, "enodeid": east_tip, "direction": 2},
                "geometry": LineString(_shift_xy([(0.0, 0.0), (55.0, 0.0)], dx)),
            },
        ]
    )

    features["drivezone"].append(
        {
            "properties": {"name": f"dz_{node_id}"},
            "geometry": unary_union(
                [
                    box(dx - 12.0, -70.0, dx + 12.0, 70.0),
                    box(dx, -12.0, dx + 75.0, 12.0),
                    box(dx - 25.0, -8.0, dx, 8.0),
                ]
            ),
        }
    )

    features["rcsdroad"].extend(
        [
            {
                "properties": {"id": f"rc_north_{node_id}", "snodeid": node_id, "enodeid": f"{north_tip}1", "direction": 2},
                "geometry": LineString(_shift_xy([(0.0, 0.0), (0.0, 55.0)], dx)),
            },
            {
                "properties": {"id": f"rc_south_{node_id}", "snodeid": f"{south_tip}1", "enodeid": node_id, "direction": 2},
                "geometry": LineString(_shift_xy([(0.0, -55.0), (0.0, 0.0)], dx)),
            },
            {
                "properties": {"id": f"rc_east_{node_id}", "snodeid": node_id, "enodeid": f"{east_tip}1", "direction": 2},
                "geometry": LineString(_shift_xy([(0.0, 0.0), (45.0, 0.0)], dx)),
            },
            {
                "properties": {"id": f"rc_west_{node_id}", "snodeid": f"{node_id}4", "enodeid": node_id, "direction": 2},
                "geometry": LineString(_shift_xy([(-18.0, 0.0), (0.0, 0.0)], dx)),
            },
        ]
    )

    features["rcsdnode"].extend(
        [
            {"properties": {"id": node_id, "mainnodeid": node_id}, "geometry": Point(dx, 0.0)},
            {"properties": {"id": f"{north_tip}1", "mainnodeid": None}, "geometry": Point(dx, 55.0)},
            {"properties": {"id": f"{south_tip}1", "mainnodeid": None}, "geometry": Point(dx, -55.0)},
            {"properties": {"id": f"{east_tip}1", "mainnodeid": None}, "geometry": Point(dx + 45.0, 0.0)},
            {"properties": {"id": f"{node_id}4", "mainnodeid": None}, "geometry": Point(dx - 18.0, 0.0)},
        ]
    )


def _write_full_input_fixture(tmp_path: Path, *, include_second_case: bool) -> dict[str, Path]:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    features: dict[str, list[dict]] = {
        "nodes": [],
        "roads": [],
        "drivezone": [],
        "rcsdroad": [],
        "rcsdnode": [],
    }
    _append_case(features=features, mainnodeid="100", dx=0.0)
    if include_second_case:
        _append_case(features=features, mainnodeid="200", dx=300.0)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    drivezone_path = inputs_dir / "drivezone.gpkg"
    rcsdroad_path = inputs_dir / "rcsdroad.gpkg"
    rcsdnode_path = inputs_dir / "rcsdnode.gpkg"

    write_vector(nodes_path, features["nodes"], crs_text="EPSG:3857")
    write_vector(roads_path, features["roads"], crs_text="EPSG:3857")
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz_all"}, "geometry": unary_union([item["geometry"] for item in features["drivezone"]])}],
        crs_text="EPSG:3857",
    )
    write_vector(rcsdroad_path, features["rcsdroad"], crs_text="EPSG:3857")
    write_vector(rcsdnode_path, features["rcsdnode"], crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def test_full_input_poc_explicit_mainnodeid_writes_unified_outputs(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=False)
    artifacts = run_t02_virtual_intersection_full_input_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="batch_run",
        debug=True,
        workers=2,
        **paths,
    )

    assert artifacts.success is True
    assert artifacts.out_root == tmp_path / "out" / "batch_run"
    assert artifacts.preflight_path.is_file()
    assert artifacts.summary_path.is_file()
    assert artifacts.perf_summary_path.is_file()
    assert artifacts.polygons_path.is_file()
    assert (artifacts.out_root / "cases" / "100" / "virtual_intersection_polygon.gpkg").is_file()
    assert (artifacts.out_root / "_rendered_maps" / "100.png").is_file()

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["mode"] == "specified_mainnodeid"
    assert summary["selected_case_ids"] == ["100"]
    assert summary["success_count"] == 1

    polygon_doc = _load_vector_doc(artifacts.polygons_path)
    assert len(polygon_doc["features"]) == 1
    feature = polygon_doc["features"][0]
    assert feature["properties"]["mainnodeid"] == "100"
    assert feature["properties"]["status"] == "stable"
    assert Path(feature["properties"]["source_case_dir"]).name == "100"


def test_full_input_poc_reuses_case_outputs_for_summary_output(tmp_path: Path, monkeypatch) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=False)
    polygon_read_count = 0
    id_read_count = 0
    original_read_polygon_feature = full_input_module._read_polygon_feature
    original_read_ids = full_input_module._read_ids
    original_path_read_text = Path.read_text

    def _counting_read_polygon_feature(path: Path):
        nonlocal polygon_read_count
        polygon_read_count += 1
        return original_read_polygon_feature(path)

    def _counting_read_ids(path: Path):
        nonlocal id_read_count
        id_read_count += 1
        return original_read_ids(path)

    def _guarded_read_text(self: Path, *args, **kwargs):
        if self.name in {"t02_virtual_intersection_poc_status.json", "t02_virtual_intersection_poc_perf.json"}:
            raise AssertionError(f"unexpected case-level JSON read: {self}")
        return original_path_read_text(self, *args, **kwargs)

    monkeypatch.setattr(full_input_module, "_read_polygon_feature", _counting_read_polygon_feature)
    monkeypatch.setattr(full_input_module, "_read_ids", _counting_read_ids)
    monkeypatch.setattr(Path, "read_text", _guarded_read_text)

    artifacts = run_t02_virtual_intersection_full_input_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="read_once",
        **paths,
    )

    assert artifacts.success is True
    assert polygon_read_count == 0
    assert id_read_count == 0
    polygon_doc = _load_vector_doc(artifacts.polygons_path)
    assert len(polygon_doc["features"]) == 1
    assert polygon_doc["features"][0]["properties"]["mainnodeid"] == "100"


def test_full_input_poc_auto_discovers_candidates_and_applies_max_cases(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=True)
    artifacts = run_t02_virtual_intersection_full_input_poc(
        out_root=tmp_path / "out",
        run_id="auto_run",
        max_cases=1,
        **paths,
    )

    assert artifacts.success is True
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["mode"] == "auto_discovery"
    assert summary["discovered_case_ids"] == ["100", "200"]
    assert summary["selected_case_ids"] == ["100"]
    assert summary["skipped_case_ids"] == ["200"]
    assert summary["case_count"] == 1
    assert (artifacts.out_root / "cases" / "100" / "virtual_intersection_polygon.gpkg").is_file()
    assert not (artifacts.out_root / "cases" / "200").exists()


def test_full_input_poc_parallel_results_are_deterministic(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=True)
    serial = run_t02_virtual_intersection_full_input_poc(
        out_root=tmp_path / "serial",
        run_id="serial",
        workers=1,
        **paths,
    )
    parallel = run_t02_virtual_intersection_full_input_poc(
        out_root=tmp_path / "parallel",
        run_id="parallel",
        workers=2,
        **paths,
    )

    assert serial.success is True
    assert parallel.success is True

    serial_summary = json.loads(serial.summary_path.read_text(encoding="utf-8"))
    parallel_summary = json.loads(parallel.summary_path.read_text(encoding="utf-8"))
    assert serial_summary["selected_case_ids"] == ["100", "200"]
    assert parallel_summary["selected_case_ids"] == ["100", "200"]
    assert [(row["case_id"], row["status"]) for row in serial_summary["rows"]] == [
        (row["case_id"], row["status"]) for row in parallel_summary["rows"]
    ]

    serial_polygon_doc = _load_vector_doc(serial.polygons_path)
    parallel_polygon_doc = _load_vector_doc(parallel.polygons_path)
    assert [feature["properties"]["mainnodeid"] for feature in serial_polygon_doc["features"]] == ["100", "200"]
    assert [feature["properties"]["mainnodeid"] for feature in parallel_polygon_doc["features"]] == ["100", "200"]

    serial_shapes = [shape(feature["geometry"]) for feature in serial_polygon_doc["features"]]
    parallel_shapes = [shape(feature["geometry"]) for feature in parallel_polygon_doc["features"]]
    assert [round(item.area, 3) for item in serial_shapes] == [round(item.area, 3) for item in parallel_shapes]
