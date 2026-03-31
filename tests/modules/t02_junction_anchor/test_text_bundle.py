from __future__ import annotations

import json
import os
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import (
    LEGACY_TEXT_BUNDLE_CHECKSUM,
    LEGACY_TEXT_BUNDLE_END_PAYLOAD,
    LEGACY_TEXT_BUNDLE_META,
    LEGACY_TEXT_BUNDLE_PAYLOAD,
    TEXT_BUNDLE_BEGIN,
    TEXT_BUNDLE_CHECKSUM,
    TEXT_BUNDLE_END,
    TEXT_BUNDLE_PAYLOAD,
    TEXT_BUNDLE_META,
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


def _write_multi_bundle_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": "101", "mainnodeid": "100", "has_evd": None, "is_anchor": None, "kind_2": 2048, "grade_2": 1},
                "geometry": Point(6.0, 0.0),
            },
            {
                "properties": {"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 2048, "grade_2": 1},
                "geometry": Point(220.0, 0.0),
            },
            {
                "properties": {"id": "201", "mainnodeid": "200", "has_evd": None, "is_anchor": None, "kind_2": 2048, "grade_2": 1},
                "geometry": Point(226.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north_100", "snodeid": "100", "enodeid": "2001", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south_100", "snodeid": "3001", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east_100", "snodeid": "100", "enodeid": "4001", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
            {"properties": {"id": "road_north_200", "snodeid": "200", "enodeid": "2002", "direction": 2}, "geometry": LineString([(220.0, 0.0), (220.0, 60.0)])},
            {"properties": {"id": "road_south_200", "snodeid": "3002", "enodeid": "200", "direction": 2}, "geometry": LineString([(220.0, -60.0), (220.0, 0.0)])},
            {"properties": {"id": "road_east_200", "snodeid": "200", "enodeid": "4002", "direction": 2}, "geometry": LineString([(220.0, 0.0), (275.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union(
                    [
                        box(-12.0, -70.0, 12.0, 70.0),
                        box(0.0, -12.0, 75.0, 12.0),
                        box(-25.0, -8.0, 0.0, 8.0),
                        box(208.0, -70.0, 232.0, 70.0),
                        box(220.0, -12.0, 295.0, 12.0),
                        box(195.0, -8.0, 220.0, 8.0),
                    ]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north_100", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south_100", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east_100", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
            {"properties": {"id": "rc_north_200", "snodeid": "200", "enodeid": "911", "direction": 2}, "geometry": LineString([(220.0, 0.0), (220.0, 55.0)])},
            {"properties": {"id": "rc_south_200", "snodeid": "912", "enodeid": "200", "direction": 2}, "geometry": LineString([(220.0, -55.0), (220.0, 0.0)])},
            {"properties": {"id": "rc_east_200", "snodeid": "200", "enodeid": "913", "direction": 2}, "geometry": LineString([(220.0, 0.0), (265.0, 0.0)])},
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
            {"properties": {"id": "200", "mainnodeid": "200"}, "geometry": Point(220.0, 0.0)},
            {"properties": {"id": "911", "mainnodeid": None}, "geometry": Point(220.0, 55.0)},
            {"properties": {"id": "912", "mainnodeid": None}, "geometry": Point(220.0, -55.0)},
            {"properties": {"id": "913", "mainnodeid": None}, "geometry": Point(265.0, 0.0)},
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
    assert f"\n{TEXT_BUNDLE_META}" in bundle_text
    assert f"\n{TEXT_BUNDLE_PAYLOAD}\n" in bundle_text
    assert f"\n{TEXT_BUNDLE_CHECKSUM}" in bundle_text
    assert "END_PAYLOAD" not in bundle_text

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
    assert _vector_feature_count(decode_dir / "drivezone.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "roads.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "rcsdroad.gpkg") >= 1
    assert _vector_feature_count(decode_dir / "rcsdnode.gpkg") >= 1


def test_decode_text_bundle_defaults_to_bundle_stem_directory(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "765003.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)
    assert artifacts.success is True

    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path)
    assert decode_artifacts.success is True
    assert decode_artifacts.out_dir == tmp_path / "765003"
    for name in REQUIRED_BUNDLE_FILES:
        assert (decode_artifacts.out_dir / name).is_file()


def test_export_text_bundle_roundtrip_supports_multiple_mainnodeids(tmp_path: Path) -> None:
    paths = _write_multi_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "multi_case.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid=["100", "200"], out_txt=bundle_path, **paths)
    assert artifacts.success is True
    assert bundle_path.is_file()

    decode_root = tmp_path / "decode_here"
    decode_root.mkdir(parents=True, exist_ok=True)
    current_dir = Path.cwd()
    try:
        os.chdir(decode_root)
        decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path)
    finally:
        os.chdir(current_dir)

    assert decode_artifacts.success is True
    assert decode_artifacts.out_dir == decode_root
    assert decode_artifacts.case_dirs == (decode_root / "100", decode_root / "200")

    bundle_manifest_path = decode_root / "multi_case.bundle_manifest.json"
    assert bundle_manifest_path.is_file()
    bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    assert bundle_manifest["bundle_mode"] == "multi_case"
    assert bundle_manifest["mainnodeids"] == ["100", "200"]

    for case_id in ("100", "200"):
        case_dir = decode_root / case_id
        for name in REQUIRED_BUNDLE_FILES:
            assert (case_dir / name).is_file()
        case_manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
        assert case_manifest["bundle_mode"] == "single_case"
        assert case_manifest["mainnodeid"] == case_id


def test_decode_text_bundle_accepts_legacy_wrapper_format(tmp_path: Path) -> None:
    paths = _write_bundle_inputs(tmp_path)
    bundle_path = tmp_path / "case.txt"
    artifacts = run_t02_export_text_bundle(mainnodeid="100", out_txt=bundle_path, **paths)
    assert artifacts.success is True

    bundle_lines = bundle_path.read_text(encoding="utf-8").splitlines()
    checksum_index = next(index for index, line in enumerate(bundle_lines) if line.startswith(TEXT_BUNDLE_CHECKSUM))

    legacy_lines = []
    for index, line in enumerate(bundle_lines):
        if index == 1 and line.startswith(TEXT_BUNDLE_META):
            legacy_lines.append(LEGACY_TEXT_BUNDLE_META + line[len(TEXT_BUNDLE_META) :])
        elif line == TEXT_BUNDLE_PAYLOAD:
            legacy_lines.append(LEGACY_TEXT_BUNDLE_PAYLOAD)
        elif line.startswith(TEXT_BUNDLE_CHECKSUM):
            legacy_lines.append(LEGACY_TEXT_BUNDLE_CHECKSUM + line[len(TEXT_BUNDLE_CHECKSUM) :])
        else:
            legacy_lines.append(line)
        if index == checksum_index - 1:
            legacy_lines.append(LEGACY_TEXT_BUNDLE_END_PAYLOAD)

    bundle_path.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
    decode_artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path)
    assert decode_artifacts.success is True
    assert (decode_artifacts.out_dir / "manifest.json").is_file()


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
