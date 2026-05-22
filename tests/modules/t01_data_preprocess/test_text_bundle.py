from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.freeze_compare import write_skill_v1_bundle
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer, write_json, write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.text_bundle import (
    T01_TEXT_BUNDLE_BEGIN,
    run_t01_decode_text_bundle,
    run_t01_export_input_text_bundle,
    run_t01_export_text_bundle,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_input_layers(root: Path) -> tuple[Path, Path]:
    node_features = []
    road_features = []
    origin_x = 100_000.0
    origin_y = 200_000.0
    for index in range(120):
        x = origin_x + index * 10.0
        node_features.append(
            {
                "properties": {"id": str(index), "mainnodeid": "0"},
                "geometry": Point(x, origin_y),
            }
        )
    for index in range(119):
        road_features.append(
            {
                "properties": {
                    "id": str(index),
                    "snodeid": str(index),
                    "enodeid": str(index + 1),
                    "direction": "0",
                },
                "geometry": LineString(
                    [
                        (origin_x + index * 10.0, origin_y),
                        (origin_x + (index + 1) * 10.0, origin_y),
                    ]
                ),
            }
        )
    node_path = root / "nodes.gpkg"
    road_path = root / "roads.gpkg"
    write_vector(node_path, node_features, layer_name="nodes")
    write_vector(road_path, road_features, layer_name="roads")
    return node_path, road_path


def test_t01_text_bundle_round_trips_compact_evidence(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    required_files = {
        "skill_v1_manifest.json": {"source_paths": {}},
        "skill_v1_summary.json": {"validated_pair_count": 0},
        "refreshed_nodes_hash.json": {"sha256": "nodes"},
        "refreshed_roads_hash.json": {"sha256": "roads"},
    }
    for name, payload in required_files.items():
        write_json(bundle_root / name, payload)
    for name in (
        "validated_pairs_skill_v1.csv",
        "segment_body_membership_skill_v1.csv",
        "trunk_membership_skill_v1.csv",
    ):
        _write_text(bundle_root / name, "stage,pair_id\n")
    write_json(bundle_root / "unsegmented_roads_summary.json", {"unsegmented_road_count": 3})

    artifacts = run_t01_export_text_bundle(bundle_root=bundle_root)

    assert artifacts.success is True
    assert artifacts.bundle_txt_path.read_text(encoding="utf-8").startswith(T01_TEXT_BUNDLE_BEGIN)
    assert artifacts.size_report_path is not None
    assert artifacts.included_file_count == 8

    decoded = run_t01_decode_text_bundle(bundle_txt=artifacts.bundle_txt_path, out_dir=tmp_path / "decoded")
    decoded_manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    decoded_summary = json.loads((decoded.out_dir / "unsegmented_roads_summary.json").read_text(encoding="utf-8"))

    assert decoded.success is True
    assert decoded_manifest["bundle_type"] == "t01_data_preprocess_skill_v1_evidence"
    assert decoded_summary["unsegmented_road_count"] == 3


def test_write_skill_v1_bundle_exports_text_evidence(tmp_path: Path) -> None:
    step2_dir = tmp_path / "step2"
    step4_dir = tmp_path / "step4"
    step5_dir = tmp_path / "step5"
    out_dir = tmp_path / "out"
    for path in (step2_dir, step4_dir, step5_dir):
        path.mkdir(parents=True)
    nodes_path = tmp_path / "nodes.geojson"
    roads_path = tmp_path / "roads.geojson"
    _write_text(nodes_path, '{"type":"FeatureCollection","features":[]}')
    _write_text(roads_path, '{"type":"FeatureCollection","features":[]}')

    info = write_skill_v1_bundle(
        out_dir=out_dir,
        step2_dir=step2_dir,
        step4_dir=step4_dir,
        step5_dir=step5_dir,
        refreshed_nodes_path=nodes_path,
        refreshed_roads_path=roads_path,
    )

    text_bundle_path = Path(info["text_bundle_path"])
    size_report_path = Path(info["text_bundle_size_report_path"])
    decoded = run_t01_decode_text_bundle(bundle_txt=text_bundle_path, out_dir=tmp_path / "decoded_bundle")

    assert text_bundle_path.is_file()
    assert size_report_path.is_file()
    assert info["text_bundle_size_bytes"] == text_bundle_path.stat().st_size
    assert (decoded.out_dir / "skill_v1_manifest.json").is_file()
    assert (decoded.out_dir / "validated_pairs_skill_v1.csv").is_file()


def test_t01_input_text_bundle_uses_centered_profile_slice(tmp_path: Path) -> None:
    node_path, road_path = _write_input_layers(tmp_path / "input")

    artifacts = run_t01_export_input_text_bundle(
        node_path=node_path,
        road_path=road_path,
        out_txt=tmp_path / "input_bundle.txt",
        center_x=100_000.0,
        center_y=200_000.0,
        profile_id="XXXS",
        max_text_size_bytes=10_000_000,
    )

    assert artifacts.success is True
    assert artifacts.selected_profile_id == "XXXS"
    assert artifacts.selected_core_node_count == 100
    decoded = run_t01_decode_text_bundle(bundle_txt=artifacts.bundle_txt_path, out_dir=tmp_path / "decoded_input")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    decoded_nodes = read_vector_layer(decoded.out_dir / "nodes.gpkg", layer_name="nodes").features
    decoded_node_ids = {str(feature.properties["id"]) for feature in decoded_nodes}
    node_zero = next(feature for feature in decoded_nodes if str(feature.properties["id"]) == "0")

    assert manifest["bundle_type"] == "t01_data_preprocess_input_nodes_roads_context"
    assert manifest["selection"]["profile_id"] == "XXXS"
    assert manifest["selection"]["center_x"] == 100_000.0
    assert "0" in decoded_node_ids
    assert "119" not in decoded_node_ids
    assert node_zero.geometry.x == pytest.approx(100_000.0)
    assert node_zero.geometry.y == pytest.approx(200_000.0)
    assert (decoded.out_dir / "slice_summary.json").is_file()


def test_t01_input_text_bundle_splits_and_decodes_from_part(tmp_path: Path) -> None:
    node_path, road_path = _write_input_layers(tmp_path / "input")

    artifacts = run_t01_export_input_text_bundle(
        node_path=node_path,
        road_path=road_path,
        out_txt=tmp_path / "input_bundle.txt",
        center_x=100_000.0,
        center_y=200_000.0,
        profile_id="XXXS",
        max_text_size_bytes=25_000,
    )

    assert artifacts.success is True
    assert len(artifacts.part_txt_paths) > 1
    assert all(path.stat().st_size <= 25_000 for path in artifacts.part_txt_paths)

    decoded = run_t01_decode_text_bundle(bundle_txt=artifacts.part_txt_paths[-1], out_dir=tmp_path / "decoded_split")
    decoded_nodes = read_vector_layer(decoded.out_dir / "nodes.gpkg", layer_name="nodes").features
    size_report = json.loads((decoded.out_dir / "text_bundle_size_report.json").read_text(encoding="utf-8"))

    assert decoded.success is True
    assert decoded_nodes
    assert size_report["split_bundle"]["enabled"] is True
