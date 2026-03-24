from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import (
    TEXT_BUNDLE_BEGIN,
    TEXT_BUNDLE_END,
    REQUIRED_BUNDLE_FILES,
    run_t02_decode_text_bundle,
    run_t02_export_text_bundle,
)


def _vector_feature_count(path: Path) -> int:
    with fiona.open(path) as src:
        return len(src)


def _write_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 2048,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": None,
                    "is_anchor": None,
                    "kind_2": 2048,
                    "grade_2": 1,
                },
                "geometry": Point(6.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def test_export_text_bundle_fails_when_mainnodeid_missing(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    artifacts = run_t02_export_text_bundle(mainnodeid="missing", out_txt=tmp_path / "case.txt", **paths)
    assert artifacts.success is False
    assert artifacts.failure_reason == "mainnodeid_not_found"
    assert not artifacts.bundle_txt_path.exists()


def test_export_text_bundle_roundtrip_restores_required_files(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)
    assert artifacts.success is True
    assert bundle_path.is_file()
    assert artifacts.bundle_size_bytes <= 300 * 1024

    bundle_text = bundle_path.read_text(encoding="utf-8")
    assert bundle_text.startswith(TEXT_BUNDLE_BEGIN)
    assert TEXT_BUNDLE_END in bundle_text

    decode_dir = tmp_path / "decoded"
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=decode_dir)
    assert decode_artifacts.success is True
    for name in REQUIRED_BUNDLE_FILES:
        assert (decode_dir / name).is_file()

    manifest = json.loads((decode_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mainnodeid"] == "100"
    assert manifest["bundle_version"] == "1"
    assert set(REQUIRED_BUNDLE_FILES) <= set(manifest["file_list"])

    size_report = json.loads((decode_dir / "size_report.json").read_text(encoding="utf-8"))
    assert size_report["within_limit"] is True
    assert size_report["total_text_size_bytes"] <= 300 * 1024

    png_header = (decode_dir / "drivezone_mask.png").read_bytes()[:8]
    assert png_header == b"\x89PNG\r\n\x1a\n"

    assert _vector_feature_count(decode_dir / "nodes.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "roads.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "rcsdroad.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "rcsdnode.gpkg") >= 1


def test_export_text_bundle_fails_with_size_report_when_limit_exceeded(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"
    artifacts = run_t02_export_text_bundle(
        mainnodeid="100",
        out_txt=bundle_path,
        max_text_size_bytes=200,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.failure_reason == "bundle_too_large"
    assert artifacts.size_report_path is not None
    assert artifacts.size_report_path.is_file()
    report = json.loads(artifacts.size_report_path.read_text(encoding="utf-8"))
    assert report["within_limit"] is False
    assert report["total_text_size_bytes"] > 200
    assert report["dominant_size_source"] in REQUIRED_BUNDLE_FILES
