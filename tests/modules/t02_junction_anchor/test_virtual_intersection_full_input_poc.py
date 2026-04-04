from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import fiona
import numpy as np
from shapely.geometry import LineString, Point, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
import rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_full_input_poc as full_input_module
import rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc as single_case_module
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


def _read_png_rgba(path: Path) -> np.ndarray:
    png_bytes = path.read_bytes()
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = None
    height = None
    idat_parts: list[bytes] = []
    while offset < len(png_bytes):
        chunk_length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        payload = png_bytes[offset + 8 : offset + 8 + chunk_length]
        offset += 12 + chunk_length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif chunk_type == b"IDAT":
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            break
    assert width is not None and height is not None
    raw_rows = zlib.decompress(b"".join(idat_parts))
    row_size = 1 + width * 4
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for row_index in range(height):
        row = raw_rows[row_index * row_size : (row_index + 1) * row_size]
        assert row[0] == 0
        image[row_index] = np.frombuffer(row[1:], dtype=np.uint8).reshape((width, 4))
    return image


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


def test_full_input_poc_reuses_case_outputs_for_summary_output(tmp_path: Path) -> None:
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

    with patch.object(full_input_module, "_read_polygon_feature", _counting_read_polygon_feature), patch.object(
        full_input_module, "_read_ids", _counting_read_ids
    ), patch.object(Path, "read_text", _guarded_read_text):
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


def test_full_input_poc_preloads_shared_layers_once_for_multi_case_runs(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=True)
    load_count = 0
    original_full_input_load = full_input_module._load_layer_filtered
    original_single_case_load = single_case_module._load_layer_filtered

    def _counting_load(*args, **kwargs):
        nonlocal load_count
        load_count += 1
        return original_full_input_load(*args, **kwargs)

    with patch.object(full_input_module, "_load_layer_filtered", _counting_load), patch.object(
        single_case_module, "_load_layer_filtered", _counting_load
    ):
        artifacts = run_t02_virtual_intersection_full_input_poc(
            out_root=tmp_path / "out",
            run_id="shared_preload",
            workers=2,
            **paths,
        )

    assert artifacts.success is True
    assert load_count == 5
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["shared_memory"]["enabled"] is True
    assert summary["shared_memory"]["shared_local_layer_query"] is True


def test_full_input_poc_multi_case_batch_skips_case_progress_and_perf_markers(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=True)
    artifacts = run_t02_virtual_intersection_full_input_poc(
        out_root=tmp_path / "out",
        run_id="batch_case_io_trimmed",
        workers=2,
        **paths,
    )

    assert artifacts.success is True
    case_root = artifacts.out_root / "cases" / "100"
    assert (case_root / "t02_virtual_intersection_poc_status.json").is_file()
    assert (case_root / "t02_virtual_intersection_poc_perf.json").is_file()
    assert not (case_root / "t02_virtual_intersection_poc_progress.json").exists()
    assert not (case_root / "t02_virtual_intersection_poc_perf_markers.jsonl").exists()


def test_full_input_poc_writes_exception_summary_and_case_events(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=True)
    original_run = full_input_module.run_t02_virtual_intersection_poc
    original_write_exception_summary = full_input_module._write_exception_summary
    exception_summary_write_count = 0

    def _patched_run(**kwargs):
        if str(kwargs["mainnodeid"]) == "200":
            raise RuntimeError("boom case 200")
        return original_run(**kwargs)

    def _counting_write_exception_summary(*args, **kwargs):
        nonlocal exception_summary_write_count
        exception_summary_write_count += 1
        return original_write_exception_summary(*args, **kwargs)

    with patch.object(full_input_module, "run_t02_virtual_intersection_poc", _patched_run), patch.object(
        full_input_module, "_write_exception_summary", _counting_write_exception_summary
    ):
        artifacts = run_t02_virtual_intersection_full_input_poc(
            out_root=tmp_path / "out",
            run_id="worker_exception",
            workers=2,
            **paths,
        )

    assert artifacts.success is False
    exception_summary = json.loads(artifacts.exception_summary_path.read_text(encoding="utf-8"))
    assert exception_summary["worker_exception_count"] == 1
    assert exception_summary["status_counts"]["worker_exception"] == 1
    assert any(item["case_id"] == "200" for item in exception_summary["failed_cases"])
    case_events = artifacts.case_events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(case_events) == 2
    assert exception_summary_write_count == 2


def test_full_input_poc_marks_unsuccessful_rendered_map_as_failure_style(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=False)

    def _fake_run_case_job(job: dict[str, object]) -> dict[str, object]:
        render_path = Path(str(job["debug_render_root"])) / "100.png"
        single_case_module._write_png_rgba(render_path, np.full((32, 32, 4), 255, dtype=np.uint8))
        return {
            "case_id": "100",
            "success": False,
            "flow_success": True,
            "acceptance_class": "review_required",
            "acceptance_reason": "synthetic_review_required",
            "status": "surface_only",
            "risks": ["surface_only"],
            "detail": None,
            "representative_node_id": "100",
            "kind_2": 2048,
            "grade_2": 1,
            "counts": {},
            "total_wall_time_sec": 0.1,
            "python_tracemalloc_current_bytes": None,
            "python_tracemalloc_peak_bytes": None,
            "case_dir": str(Path(str(job["out_root"])) / "100"),
            "rendered_map_png": str(render_path),
            "virtual_polygon_path": str(Path(str(job["out_root"])) / "100" / "virtual_intersection_polygon.gpkg"),
            "polygon_feature": None,
            "associated_rcsdroad_ids": [],
            "associated_rcsdnode_ids": [],
            "polygon_area_m2": None,
            "polygon_bounds": None,
        }

    with patch.object(full_input_module, "_run_case_job", _fake_run_case_job):
        artifacts = run_t02_virtual_intersection_full_input_poc(
            mainnodeid="100",
            out_root=tmp_path / "out",
            run_id="failure_render_overlay",
            debug=True,
            workers=1,
            **paths,
        )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["success_count"] == 0
    render_path = artifacts.rendered_maps_root / "100.png"
    assert render_path.is_file()
    image = _read_png_rgba(render_path)
    assert tuple(image[0, 0]) == (144, 0, 0, 255)


def test_full_input_poc_writes_crash_report_on_top_level_failure(tmp_path: Path) -> None:
    paths = _write_full_input_fixture(tmp_path, include_second_case=False)
    original_write_vector = full_input_module.write_vector

    def _patched_write_vector(path, *args, **kwargs):
        if Path(path).name == "virtual_intersection_polygons.gpkg":
            raise RuntimeError("boom aggregate write")
        return original_write_vector(path, *args, **kwargs)

    with patch.object(full_input_module, "write_vector", _patched_write_vector):
        artifacts = run_t02_virtual_intersection_full_input_poc(
            mainnodeid="100",
            out_root=tmp_path / "out",
            run_id="crash_report",
            **paths,
        )

    assert artifacts.success is False
    crash_report = json.loads(artifacts.crash_report_path.read_text(encoding="utf-8"))
    assert crash_report["error_type"] == "RuntimeError"
    assert "boom aggregate write" in crash_report["detail"]


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
