from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import (
    T06_TEXT_BUNDLE_BEGIN,
    run_t06_decode_text_bundle,
    run_t06_export_input_text_bundle_from_args,
    run_t06_export_text_bundle,
    run_t06_export_text_bundle_from_args,
)


def _write_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _build_t06_bundle_fixture(tmp_path: Path) -> dict[str, Path | str]:
    swsd_root = tmp_path / "first_layer_road_net_v0"
    t05_root = tmp_path / "t05_phase2_full"
    out_root = tmp_path / "t06_segment_fusion_precheck"
    run_id = "t06_innernet_precheck"
    run_root = out_root / run_id
    step1 = run_root / "step1_identify_fusion_units"
    step2 = run_root / "step2_extract_rcsd_segments"

    segment = _write_bytes(swsd_root / "T01" / "segment.gpkg", b"segment")
    roads = _write_bytes(swsd_root / "T01" / "roads.gpkg", b"roads")
    nodes = _write_bytes(swsd_root / "T04" / "nodes.gpkg", b"nodes")
    intersection = _write_bytes(t05_root / "intersection_match_all.geojson", b'{"type":"FeatureCollection"}')
    rcsdroad = _write_bytes(t05_root / "rcsdroad_out.gpkg", b"rcsdroad")
    rcsdnode = _write_bytes(t05_root / "rcsdnode_out.gpkg", b"rcsdnode")

    _write_json(
        step1 / "t06_step1_summary.json",
        {
            "input_segment_count": 2,
            "final_fusion_unit_count": 1,
            "outputs": {"fusion_units_gpkg": str(step1 / "t06_swsd_segment_fusion_units.gpkg")},
        },
    )
    _write_json(
        step2 / "t06_step2_summary.json",
        {
            "input_fusion_unit_count": 1,
            "replaceable_count": 1,
            "buffer_segment_count": 1,
            "outputs": {"buffer_segments_json": str(step2 / "t06_rcsd_buffer_segments.json")},
        },
    )
    for path in (
        step1 / "t06_swsd_segment_fusion_units.json",
        step1 / "t06_swsd_segment_rejected.json",
        step2 / "t06_rcsd_segment_candidates.json",
        step2 / "t06_rcsd_segment_replaceable.json",
        step2 / "t06_rcsd_segment_rejected.json",
        step2 / "t06_rcsd_buffer_segments.json",
        step2 / "t06_rcsd_buffer_segment_rejected.json",
    ):
        _write_json(path, {"row_count": 0, "features": []})
        _write_text(path.with_suffix(".csv"), "swsd_segment_id\n")
    _write_bytes(step2 / "t06_rcsd_buffer_segments.gpkg", b"buffer-gpkg")

    return {
        "segment": segment,
        "roads": roads,
        "nodes": nodes,
        "intersection": intersection,
        "rcsdroad": rcsdroad,
        "rcsdnode": rcsdnode,
        "t05_root": t05_root,
        "out_root": out_root,
        "run_id": run_id,
        "run_root": run_root,
    }


def test_t06_text_bundle_round_trips_compact_outputs_and_input_manifest(tmp_path: Path) -> None:
    fixture = _build_t06_bundle_fixture(tmp_path)

    artifacts = run_t06_export_text_bundle(
        swsd_segment_path=fixture["segment"],
        swsd_roads_path=fixture["roads"],
        swsd_nodes_path=fixture["nodes"],
        t05_phase2_root=fixture["t05_root"],
        out_root=fixture["out_root"],
        run_id=str(fixture["run_id"]),
    )

    assert artifacts.success is True
    assert artifacts.bundle_txt_path.read_text(encoding="utf-8").startswith(T06_TEXT_BUNDLE_BEGIN)
    assert artifacts.size_report_path is not None
    decoded = run_t06_decode_text_bundle(bundle_txt=artifacts.bundle_txt_path, out_dir=tmp_path / "decoded")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    input_manifest = json.loads((decoded.out_dir / "audit" / "t06_input_manifest.json").read_text(encoding="utf-8"))

    assert manifest["bundle_type"] == "t06_segment_fusion_precheck_evidence"
    assert input_manifest["input_paths"]["swsd_segment_path"] == str(fixture["segment"])
    assert input_manifest["input_files"]["rcsdroad_path"]["sha256"]
    assert (decoded.out_dir / "audit" / "replay_t06_run_innernet_precheck.sh").is_file()
    assert (decoded.out_dir / "run" / "step2_extract_rcsd_segments" / "t06_step2_summary.json").is_file()
    assert not (decoded.out_dir / "inputs" / "swsd" / "segment.gpkg").exists()


def test_t06_text_bundle_can_include_vectors_and_raw_inputs(tmp_path: Path) -> None:
    fixture = _build_t06_bundle_fixture(tmp_path)

    artifacts = run_t06_export_text_bundle(
        swsd_segment_path=fixture["segment"],
        swsd_roads_path=fixture["roads"],
        swsd_nodes_path=fixture["nodes"],
        t05_phase2_root=fixture["t05_root"],
        out_root=fixture["out_root"],
        run_id=str(fixture["run_id"]),
        include_output_vectors=True,
        include_input_files=True,
    )
    decoded = run_t06_decode_text_bundle(bundle_txt=artifacts.bundle_txt_path, out_dir=tmp_path / "decoded_full")

    assert artifacts.success is True
    assert (decoded.out_dir / "inputs" / "swsd" / "segment.gpkg").read_bytes() == b"segment"
    assert (
        decoded.out_dir
        / "run"
        / "step2_extract_rcsd_segments"
        / "t06_rcsd_buffer_segments.gpkg"
    ).read_bytes() == b"buffer-gpkg"


def test_t06_text_bundle_from_args_keeps_innernet_run_argument_shape(tmp_path: Path) -> None:
    fixture = _build_t06_bundle_fixture(tmp_path)
    out_txt = tmp_path / "bundle" / "t06_bundle.txt"

    exit_code = run_t06_export_text_bundle_from_args(
        [
            "--swsd-segment",
            str(fixture["segment"]),
            "--swsd-roads",
            str(fixture["roads"]),
            "--swsd-nodes",
            str(fixture["nodes"]),
            "--t05-phase2-root",
            str(fixture["t05_root"]),
            "--intersection-match",
            str(fixture["intersection"]),
            "--rcsdroad",
            str(fixture["rcsdroad"]),
            "--rcsdnode",
            str(fixture["rcsdnode"]),
            "--out-root",
            str(fixture["out_root"]),
            "--run-id",
            str(fixture["run_id"]),
            "--out-txt",
            str(out_txt),
        ]
    )

    assert exit_code == 0
    decoded = run_t06_decode_text_bundle(bundle_txt=out_txt, out_dir=tmp_path / "decoded_args")
    replay = (decoded.out_dir / "audit" / "replay_t06_run_innernet_precheck.sh").read_text(encoding="utf-8")

    assert "--swsd-segment" in replay
    assert "--t05-phase2-root" in replay
    assert "--intersection-match" in replay
    assert str(fixture["rcsdroad"]) in replay
    assert str(fixture["out_root"]) in replay


def test_t06_input_text_bundle_slices_by_center_and_keeps_segment_dependencies(tmp_path: Path) -> None:
    swsd_root = tmp_path / "first_layer_road_net_v0"
    t05_root = tmp_path / "t05_phase2_full"
    out_txt = tmp_path / "slice_bundle.txt"

    segment_path = swsd_root / "T01" / "segment.gpkg"
    roads_path = swsd_root / "T01" / "roads.gpkg"
    nodes_path = swsd_root / "T04" / "nodes.gpkg"
    relation_path = t05_root / "intersection_match_all.geojson"
    rcsdroad_path = t05_root / "rcsdroad_out.gpkg"
    rcsdnode_path = t05_root / "rcsdnode_out.gpkg"

    write_vector(
        segment_path,
        [
            {
                "properties": {"id": "s-near", "pair_nodes": "1,2", "junc_nodes": "3", "roads": "r-near"},
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {"id": "s-far", "pair_nodes": "10,11", "junc_nodes": "", "roads": "r-far"},
                "geometry": LineString([(1000, 0), (1010, 0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "r-near", "snodeid": 1, "enodeid": 2}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "r-far", "snodeid": 10, "enodeid": 11}, "geometry": LineString([(1000, 0), (1010, 0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        nodes_path,
        [
            {"properties": {"id": 1, "mainnodeid": 1}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 2}, "geometry": Point(10, 0)},
            {"properties": {"id": 3, "mainnodeid": 3}, "geometry": Point(5, 1)},
            {"properties": {"id": 10, "mainnodeid": 10}, "geometry": Point(1000, 0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        relation_path,
        [
            {"properties": {"target_id": 1, "base_id": 101, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 102, "status": 0}, "geometry": Point(10, 0)},
            {"properties": {"target_id": 3, "base_id": 103, "status": 0}, "geometry": Point(5, 1)},
            {"properties": {"target_id": 10, "base_id": 110, "status": 0}, "geometry": Point(1000, 0)},
        ],
        crs_text="CRS84",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": 101, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 102, "mainnodeid": 0}, "geometry": Point(10, 0)},
            {"properties": {"id": 103, "mainnodeid": 0}, "geometry": Point(5, 1)},
            {"properties": {"id": 110, "mainnodeid": 0}, "geometry": Point(1000, 0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rr-near", "snodeid": 101, "enodeid": 102}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "rr-far", "snodeid": 110, "enodeid": 111}, "geometry": LineString([(1000, 0), (1010, 0)])},
        ],
        crs_text="EPSG:3857",
    )

    exit_code = run_t06_export_input_text_bundle_from_args(
        [
            "--swsd-segment",
            str(segment_path),
            "--swsd-roads",
            str(roads_path),
            "--swsd-nodes",
            str(nodes_path),
            "--t05-phase2-root",
            str(t05_root),
            "--out-root",
            str(tmp_path / "out"),
            "--out-txt",
            str(out_txt),
            "--center-x",
            "0",
            "--center-y",
            "0",
            "--radius-m",
            "50",
        ]
    )

    assert exit_code == 0
    decoded = run_t06_decode_text_bundle(bundle_txt=out_txt, out_dir=tmp_path / "decoded_slice")
    segment_doc = json.loads((decoded.out_dir / "slice" / "swsd" / "segment.geojson").read_text(encoding="utf-8"))
    relation_doc = json.loads(
        (decoded.out_dir / "slice" / "t05_phase2" / "intersection_match_all.geojson").read_text(encoding="utf-8")
    )
    summary = json.loads((decoded.out_dir / "slice" / "t06_input_slice_summary.json").read_text(encoding="utf-8"))

    assert [item["properties"]["id"] for item in segment_doc["features"]] == ["s-near"]
    assert {item["properties"]["target_id"] for item in relation_doc["features"]} == {1, 2, 3}
    assert summary["selected_swsd_segment_count"] == 1
    assert summary["crs_normalized_to"] == "EPSG:3857"
    assert summary["required_swsd_road_ids"] == ["r-near"]
    assert summary["mapped_rcsd_semantic_node_ids"] == ["101", "102", "103"]
