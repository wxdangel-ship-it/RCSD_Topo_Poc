from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _node(properties: dict, x: float, y: float) -> dict:
    return {"properties": properties, "geometry": Point(x, y)}


def _road(properties: dict, coords: list[tuple[float, float]]) -> dict:
    return {"properties": properties, "geometry": LineString(coords)}


def _read_features(path: Path) -> dict[str, dict]:
    with fiona.open(path) as source:
        return {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in source}


def _read_features_by_field(path: Path, field_name: str) -> dict[str, dict]:
    with fiona.open(path) as source:
        return {str(feature["properties"][field_name]): dict(feature["properties"]) for feature in source}


def _read_ids(path: Path) -> set[str]:
    with fiona.open(path) as source:
        return {str(feature["properties"]["id"]) for feature in source}


def _read_epsg(path: Path) -> int | None:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        return CRS.from_user_input(crs_value).to_epsg() if crs_value else None


def test_tool5_builds_complex_junction_and_repairs_one_to_many(tmp_path: Path) -> None:
    nodes_gpkg = tmp_path / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / "input" / "roads.gpkg"
    intersection_gpkg = tmp_path / "input" / "RCSDIntersection.gpkg"
    nodes_output = tmp_path / "out" / "nodes_fix_tool5.gpkg"
    roads_output = tmp_path / "out" / "roads_fix_tool5.gpkg"
    audit_nodes_output = tmp_path / "out" / "audit_nodes_tool5.gpkg"
    summary_output = tmp_path / "out" / "summary_tool5.json"

    base_node = {"mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}
    write_gpkg(
        nodes_gpkg,
        [
            _node({"id": "100", "kind": 16, "grade": 2, "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "subnodeid": None}, 0.0, 0.0),
            _node({"id": "200", "kind": 8, "grade": 1, "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "subnodeid": None}, 60.0, 0.0),
            _node({"id": "101", "kind": 1, "grade": 0, **base_node}, 20.0, 0.0),
            _node({"id": "102", "kind": 1, "grade": 0, **base_node}, 40.0, 0.0),
            _node({"id": "110", "kind": 1, "grade": 0, **base_node}, 0.0, 10.0),
            _node({"id": "120", "kind": 1, "grade": 0, **base_node}, 0.0, -10.0),
            _node({"id": "210", "kind": 1, "grade": 0, **base_node}, 60.0, 10.0),
            _node({"id": "220", "kind": 1, "grade": 0, **base_node}, 60.0, -10.0),
            _node({"id": "10", "kind": 64, "grade": 2, "mainnodeid": "10", "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 0.0, 100.0),
            _node({"id": "20", "kind": 2048, "grade": 1, "mainnodeid": "20", "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 10.0, 100.0),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        roads_gpkg,
        [
            _road({"id": "r-main-1", "snodeid": "100", "enodeid": "101", "direction": 2}, [(0.0, 0.0), (20.0, 0.0)]),
            _road({"id": "r-main-2", "snodeid": "101", "enodeid": "102", "direction": 2}, [(20.0, 0.0), (40.0, 0.0)]),
            _road({"id": "r-main-3", "snodeid": "102", "enodeid": "200", "direction": 2}, [(40.0, 0.0), (60.0, 0.0)]),
            _road({"id": "r-100-out", "snodeid": "100", "enodeid": "110", "direction": 2}, [(0.0, 0.0), (0.0, 10.0)]),
            _road({"id": "r-100-in", "snodeid": "120", "enodeid": "100", "direction": 2}, [(0.0, -10.0), (0.0, 0.0)]),
            _road({"id": "r-200-out", "snodeid": "200", "enodeid": "210", "direction": 2}, [(60.0, 0.0), (60.0, 10.0)]),
            _road({"id": "r-200-in", "snodeid": "220", "enodeid": "200", "direction": 2}, [(60.0, -10.0), (60.0, 0.0)]),
            _road({"id": "r-10-20", "snodeid": "10", "enodeid": "20", "direction": 0}, [(0.0, 100.0), (10.0, 100.0)]),
            _road({"id": "r-20-keep", "snodeid": "20", "enodeid": "200", "direction": 0}, [(10.0, 100.0), (60.0, 0.0)]),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        intersection_gpkg,
        [
            {
                "properties": {"id": "A"},
                "geometry": Polygon([(-1.0, 99.0), (30.0, 99.0), (30.0, 101.0), (-1.0, 101.0), (-1.0, 99.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool5_complex_junction_preprocess.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--intersection-gpkg",
            str(intersection_gpkg),
            "--nodes-output",
            str(nodes_output),
            "--roads-output",
            str(roads_output),
            "--audit-nodes-output",
            str(audit_nodes_output),
            "--summary-output",
            str(summary_output),
            "--progress-interval",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[T08 Tool5]" in result.stderr
    assert "[T08 Tool5] node_error_2: checked 1 intersection feature(s)" in result.stderr
    assert "[T08 Tool5] one_to_many: running T02 node_error_2 repair" in result.stderr
    assert _read_epsg(nodes_output) == 3857
    assert _read_epsg(roads_output) == 3857
    assert _read_epsg(audit_nodes_output) == 3857
    nodes_fix = _read_features(nodes_output)
    roads_fix_ids = _read_ids(roads_output)
    audit_nodes = _read_features_by_field(audit_nodes_output, "audit_id")

    assert nodes_fix["200"]["kind"] == 8
    assert nodes_fix["200"]["kind_2"] == 128
    assert nodes_fix["200"]["mainnodeid"] == "200"
    assert nodes_fix["100"]["kind_2"] == 0
    assert nodes_fix["100"]["grade_2"] == 0
    assert nodes_fix["100"]["mainnodeid"] == "200"
    assert nodes_fix["10"]["kind_2"] == 4
    assert nodes_fix["10"]["grade_2"] == 1
    assert nodes_fix["10"]["subnodeid"] == "20"
    assert nodes_fix["20"]["mainnodeid"] == "10"
    assert nodes_fix["20"]["kind_2"] == 0

    assert "r-10-20" not in roads_fix_ids
    assert "r-20-keep" in roads_fix_ids
    assert "r-main-1" in roads_fix_ids
    assert set(audit_nodes) == {
        "complex_divmerge:chain_000:100",
        "complex_divmerge:chain_000:200",
        "one_to_many:id:A:10",
        "one_to_many:id:A:20",
    }
    assert audit_nodes["complex_divmerge:chain_000:200"]["audit_role"] == "main"
    assert audit_nodes["complex_divmerge:chain_000:100"]["audit_role"] == "member"
    assert audit_nodes["one_to_many:id:A:10"]["audit_role"] == "main"
    assert audit_nodes["one_to_many:id:A:20"]["audit_role"] == "member"

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["complex_junction_count"] == 1
    assert summary["counts"]["one_to_many_merged_intersection_count"] == 1
    assert summary["counts"]["one_to_many_deleted_road_count"] == 1
    assert summary["counts"]["node_error_2_detected_group_count"] == 2
    assert summary["counts"]["node_error_2_generated_feature_count"] == 2
    assert summary["counts"]["audit_node_feature_count"] == 4
    assert summary["output_paths"]["audit_nodes_output"] == str(audit_nodes_output.resolve())
    assert summary["complex_divmerge"]["complex_mainnodeids"] == ["200"]
    assert summary["node_error_2_detection"]["node_error2_source"] == "generated_from_intersection"
    assert summary["params"]["one_to_many_executed"] is True
    assert "one_to_many_generate_node_error2_seconds" in summary["performance"]["stage_timings"]
    assert "one_to_many_write_temp_inputs_seconds" in summary["performance"]["stage_timings"]


def test_tool5_detects_one_to_many_but_skips_disconnected_groups(tmp_path: Path) -> None:
    nodes_gpkg = tmp_path / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / "input" / "roads.gpkg"
    intersection_gpkg = tmp_path / "input" / "RCSDIntersection.gpkg"
    nodes_output = tmp_path / "out" / "nodes_fix_tool5.gpkg"
    roads_output = tmp_path / "out" / "roads_fix_tool5.gpkg"
    audit_nodes_output = tmp_path / "out" / "audit_nodes_tool5.gpkg"
    summary_output = tmp_path / "out" / "summary_tool5.json"

    write_gpkg(
        nodes_gpkg,
        [
            _node({"id": "10", "kind": 4, "grade": 1, "mainnodeid": "10", "subnodeid": None}, 0.0, 0.0),
            _node({"id": "20", "kind": 4, "grade": 1, "mainnodeid": "20", "subnodeid": None}, 10.0, 0.0),
            _node({"id": "30", "kind": 1, "grade": 1, "mainnodeid": "30", "subnodeid": None}, 20.0, 0.0),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        roads_gpkg,
        [
            _road({"id": "r-unrelated", "snodeid": "20", "enodeid": "30", "direction": 0}, [(10.0, 0.0), (20.0, 0.0)]),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        intersection_gpkg,
        [
            {
                "properties": {"id": "A"},
                "geometry": Polygon([(-1.0, -1.0), (12.0, -1.0), (12.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool5_complex_junction_preprocess.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--intersection-gpkg",
            str(intersection_gpkg),
            "--nodes-output",
            str(nodes_output),
            "--roads-output",
            str(roads_output),
            "--audit-nodes-output",
            str(audit_nodes_output),
            "--summary-output",
            str(summary_output),
            "--skip-complex-divmerge",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    nodes_fix = _read_features(nodes_output)
    summary = json.loads(summary_output.read_text(encoding="utf-8"))

    assert nodes_fix["10"]["mainnodeid"] == "10"
    assert nodes_fix["20"]["mainnodeid"] == "20"
    assert summary["counts"]["node_error_2_detected_group_count"] == 2
    assert summary["counts"]["one_to_many_merged_intersection_count"] == 0
    assert summary["one_to_many"]["rows"][0]["skip_reason"] == "not_all_groups_connected"
    assert summary["params"]["one_to_many_executed"] is True
