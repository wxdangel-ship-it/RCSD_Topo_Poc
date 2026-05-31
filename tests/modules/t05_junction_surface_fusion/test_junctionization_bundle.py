from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t05_junction_surface_fusion.junctionization_bundle import (
    decode_t05_junctionization_bundle,
    run_t05_export_junctionization_bundle,
)
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (
    run_t05_phase2_rcsd_junctionization_and_relation,
)


def _feature(properties: dict, geometry):
    return {"properties": properties, "geometry": geometry}


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def _inputs(tmp_path: Path) -> dict[str, Path]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    return {
        "surface": _write(
            inputs / "junction_anchor_surface.gpkg",
            [
                _feature({"surface_id": "JAS:100", "mainnodeid": "100", "junction_type": "center_junction"}, box(-5, -5, 5, 5)),
                _feature({"surface_id": "JAS:200", "mainnodeid": "200", "junction_type": "center_junction"}, box(95, -5, 105, 5)),
            ],
        ),
        "nodes": _write(
            inputs / "nodes.gpkg",
            [
                _feature({"id": 100, "mainnodeid": "100", "grade": 2, "closed_con": 2}, Point(0, 0)),
                _feature({"id": 200, "mainnodeid": "200", "grade": 1, "closed_con": 1}, Point(100, 0)),
            ],
        ),
        "rcsdroad": _write(
            inputs / "RCSDRoad.gpkg",
            [
                _feature({"id": 10, "snodeid": 1, "enodeid": 2, "direction": "B"}, LineString([(0, -20), (0, 20)])),
                _feature({"id": 20, "snodeid": 3, "enodeid": 4, "direction": "B"}, LineString([(100, -20), (100, 20)])),
            ],
        ),
        "rcsdnode": _write(
            inputs / "RCSDNode.gpkg",
            [
                _feature({"id": 1, "mainnodeid": None}, Point(0, -20)),
                _feature({"id": 2, "mainnodeid": None}, Point(0, 20)),
                _feature({"id": 3, "mainnodeid": None}, Point(100, -20)),
                _feature({"id": 4, "mainnodeid": None}, Point(100, 20)),
            ],
        ),
        "t03": _write_csv(
            inputs / "t03_swsd_rcsd_relation_evidence.csv",
            [
                {"target_id": "100", "case_id": "100", "relation_state": "rcsd_present_not_junction", "support_rcsdroad_ids": "10"},
                {"target_id": "200", "case_id": "200", "relation_state": "rcsd_present_not_junction", "support_rcsdroad_ids": "20"},
            ],
            ["target_id", "case_id", "relation_state", "support_rcsdroad_ids"],
        ),
    }


def test_export_junctionization_bundle_collects_split_inputs_by_target_id(tmp_path: Path) -> None:
    paths = _inputs(tmp_path)
    phase2_root = tmp_path / "phase2"
    phase2_root.mkdir()
    _write(
        phase2_root / "intersection_match_all.geojson",
        [_feature({"target_id": "100", "base_id": 210, "status": 0}, LineString([(0, 0), (1, 1)]))],
    )
    _write(
        phase2_root / "rcsdroad_split.gpkg",
        [
            _feature({"id": 110, "snodeid": 1, "enodeid": 210, "direction": "B"}, LineString([(0, -20), (0, 0)])),
            _feature({"id": 111, "snodeid": 210, "enodeid": 2, "direction": "B"}, LineString([(0, 0), (0, 20)])),
        ],
    )
    _write(phase2_root / "rcsdnode_generated.gpkg", [_feature({"id": 210, "mainnodeid": None}, Point(0, 0))])
    _write(phase2_root / "rcsdnode_grouped.gpkg", [_feature({"id": 210, "mainnodeid": None}, Point(0, 0))])
    _write(
        phase2_root / "rcsdroad_out.gpkg",
        [
            _feature({"id": 110, "snodeid": 1, "enodeid": 210, "direction": "B"}, LineString([(0, -20), (0, 0)])),
            _feature({"id": 111, "snodeid": 210, "enodeid": 2, "direction": "B"}, LineString([(0, 0), (0, 20)])),
        ],
    )
    _write(phase2_root / "rcsdnode_out.gpkg", [_feature({"id": 210, "mainnodeid": None}, Point(0, 0))])
    _write_csv(
        phase2_root / "rcsd_junctionization_audit.csv",
        [
            {
                "target_id": "100",
                "original_rcsdroad_ids": "10",
                "new_rcsdroad_ids": "110|111",
                "new_rcsdnode_ids": "210",
                "grouped_rcsdnode_ids": "210",
                "base_id": "210",
            }
        ],
        ["target_id", "original_rcsdroad_ids", "new_rcsdroad_ids", "new_rcsdnode_ids", "grouped_rcsdnode_ids", "base_id"],
    )

    artifacts = run_t05_export_junctionization_bundle(
        target_ids=["100"],
        out_dir=tmp_path / "bundle",
        junction_surface_path=paths["surface"],
        nodes_path=paths["nodes"],
        rcsdroad_path=paths["rcsdroad"],
        rcsdnode_path=paths["rcsdnode"],
        t03_relation_evidence_path=paths["t03"],
        phase2_root=phase2_root,
        max_text_size_bytes=250 * 1024,
    )

    assert artifacts.success
    assert [path.name for path in artifacts.bundle_paths] == ["100.txt"]
    decoded = decode_t05_junctionization_bundle(artifacts.bundle_paths[0], tmp_path / "decoded")
    manifest = json.loads((decoded / "100" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["target_id"] == "100"
    assert manifest["feature_counts"]["rcsdroad"] == 1
    assert manifest["feature_counts"]["rcsdnode"] == 2

    evidence = json.loads((decoded / "100" / "relation_evidence.json").read_text(encoding="utf-8"))
    assert evidence["rows"][0]["_bundle_source"] == "T03"
    rcsdroad_geojson = json.loads((decoded / "100" / "rcsdroad.geojson").read_text(encoding="utf-8"))
    assert rcsdroad_geojson["features"][0]["properties"]["id"] == 10
    local_config = json.loads((decoded / "100" / "local_test_config.json").read_text(encoding="utf-8"))
    assert local_config["expected"]["rcsdroad_split"] == "expected_rcsdroad_split.geojson"
    assert local_config["runner_kwargs"] == {"next_road_id_start": 110, "next_node_id_start": 210}
    expected_split = json.loads((decoded / "100" / "expected_rcsdroad_split.geojson").read_text(encoding="utf-8"))
    assert expected_split["features"][0]["properties"]["id"] == 110
    expected_nodes = json.loads((decoded / "100" / "expected_rcsdnode_generated.geojson").read_text(encoding="utf-8"))
    assert expected_nodes["features"][0]["properties"]["id"] == 210

    local_case = decoded / "100"
    runner_inputs = {key: local_case / value for key, value in local_config["inputs"].items()}
    runner_kwargs = {key: value for key, value in local_config["runner_kwargs"].items() if value is not None}
    local_artifacts = run_t05_phase2_rcsd_junctionization_and_relation(
        **runner_inputs,
        out_root=tmp_path / "local_run",
        run_id="case_100",
        **runner_kwargs,
    )
    local_generated_nodes = [
        feature.properties["id"]
        for feature in read_vector_layer(local_artifacts.rcsdnode_generated_path).features
    ]
    assert local_generated_nodes == [210]
    local_split_roads = sorted(
        feature.properties["id"]
        for feature in read_vector_layer(local_artifacts.rcsdroad_split_path).features
    )
    assert local_split_roads == [110, 111]


def test_export_junctionization_bundle_auto_splits_multiple_targets(tmp_path: Path) -> None:
    paths = _inputs(tmp_path)

    artifacts = run_t05_export_junctionization_bundle(
        target_ids=["100", "200"],
        out_dir=tmp_path / "bundle",
        junction_surface_path=paths["surface"],
        nodes_path=paths["nodes"],
        rcsdroad_path=paths["rcsdroad"],
        rcsdnode_path=paths["rcsdnode"],
        t03_relation_evidence_path=paths["t03"],
        max_text_size_bytes=1,
    )

    assert artifacts.success
    assert [path.name for path in artifacts.bundle_paths] == [
        "t05_junctionization_bundle_part001.txt",
        "t05_junctionization_bundle_part002.txt",
    ]
    index_payload = json.loads(artifacts.index_path.read_text(encoding="utf-8"))
    assert index_payload["successful_target_ids"] == ["100", "200"]
    assert index_payload["shards"][0]["target_ids"] == ["100"]
    assert index_payload["shards"][1]["target_ids"] == ["200"]
