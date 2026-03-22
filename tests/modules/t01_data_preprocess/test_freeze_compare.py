from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.freeze_compare import compare_skill_v1_bundle
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json


def _write_hash(path: Path, sha256: str) -> None:
    write_json(
        path,
        {
            "file_name": path.name,
            "path": str(path.resolve()),
            "size_bytes": 1,
            "sha256": sha256,
        },
    )


def _to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":")
    if drive:
        tail = resolved.as_posix().split(":/", 1)[1]
        return f"/mnt/{drive.lower()}/{tail}"
    return resolved.as_posix()


def test_compare_skill_v1_bundle_treats_sgrade_schema_migration_as_non_regression(tmp_path: Path) -> None:
    current_dir = tmp_path / "current"
    freeze_dir = tmp_path / "freeze"
    out_dir = tmp_path / "compare"
    current_dir.mkdir()
    freeze_dir.mkdir()

    for bundle_dir, validated_name, segment_name, trunk_name in (
        (
            current_dir,
            "validated_pairs_skill_v1.csv",
            "segment_body_membership_skill_v1.csv",
            "trunk_membership_skill_v1.csv",
        ),
        (
            freeze_dir,
            "validated_pairs_baseline.csv",
            "segment_body_membership_baseline.csv",
            "trunk_membership_baseline.csv",
        ),
    ):
        write_csv(bundle_dir / validated_name, [], ["stage", "pair_id", "a_node_id", "b_node_id", "trunk_mode", "left_turn_excluded_mode", "segment_body_road_count", "residual_road_count"])
        write_csv(bundle_dir / segment_name, [], ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])
        write_csv(bundle_dir / trunk_name, [], ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])

    current_nodes = tmp_path / "current_nodes.geojson"
    current_roads = tmp_path / "current_roads.geojson"
    baseline_nodes = tmp_path / "baseline_nodes.geojson"
    baseline_roads = tmp_path / "baseline_roads.geojson"

    write_geojson(
        current_nodes,
        [{"properties": {"id": 1, "grade_2": 1, "kind_2": 4}, "geometry": Point(0.0, 0.0)}],
    )
    write_geojson(
        baseline_nodes,
        [{"properties": {"id": 1, "grade_2": 1, "kind_2": 4}, "geometry": Point(0.0, 0.0)}],
    )
    write_geojson(
        current_roads,
        [
            {
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 2,
                    "segmentid": "1_2",
                    "sgrade": "0-0双",
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            }
        ],
    )
    write_geojson(
        baseline_roads,
        [
            {
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 2,
                    "segmentid": "1_2",
                    "s_grade": "0-0双",
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            }
        ],
    )

    write_json(
        current_dir / "skill_v1_manifest.json",
        {
            "source_paths": {
                "refreshed_nodes_path": str(current_nodes.resolve()),
                "refreshed_roads_path": str(current_roads.resolve()),
            }
        },
    )
    write_json(
        freeze_dir / "FREEZE_MANIFEST.json",
        {
            "source_paths": {
                "refreshed_nodes_path": str(baseline_nodes.resolve()),
                "refreshed_roads_path": str(baseline_roads.resolve()),
            }
        },
    )
    write_json(current_dir / "skill_v1_summary.json", {"run_id": "current"})
    write_json(freeze_dir / "FREEZE_SUMMARY.json", {"freeze_label": "baseline"})

    _write_hash(current_dir / "refreshed_nodes_hash.json", "same-nodes")
    _write_hash(freeze_dir / "refreshed_nodes_hash.json", "same-nodes")
    _write_hash(current_dir / "refreshed_roads_hash.json", "current-roads-raw")
    _write_hash(freeze_dir / "refreshed_roads_hash.json", "baseline-roads-raw")

    report = compare_skill_v1_bundle(current_dir=current_dir, freeze_dir=freeze_dir, out_dir=out_dir)

    assert report["status"] == "PASS"
    assert report["schema_migration_only"] is True
    comparison_by_label = {item["label"]: item for item in report["comparisons"]}
    assert comparison_by_label["refreshed_roads_hash"]["status"] == "SCHEMA_MIGRATION_DIFFERENCE"
    assert comparison_by_label["refreshed_nodes_hash"]["status"] == "PASS"
    markdown = (out_dir / "freeze_compare_report.md").read_text(encoding="utf-8")
    assert "schema_migration_difference" in markdown


def test_compare_skill_v1_bundle_resolves_wsl_paths_from_freeze_manifest(tmp_path: Path) -> None:
    current_dir = tmp_path / "current"
    freeze_dir = tmp_path / "freeze"
    out_dir = tmp_path / "compare"
    current_dir.mkdir()
    freeze_dir.mkdir()

    for bundle_dir, validated_name, segment_name, trunk_name in (
        (
            current_dir,
            "validated_pairs_skill_v1.csv",
            "segment_body_membership_skill_v1.csv",
            "trunk_membership_skill_v1.csv",
        ),
        (
            freeze_dir,
            "validated_pairs_baseline.csv",
            "segment_body_membership_baseline.csv",
            "trunk_membership_baseline.csv",
        ),
    ):
        write_csv(bundle_dir / validated_name, [], ["stage", "pair_id", "a_node_id", "b_node_id", "trunk_mode", "left_turn_excluded_mode", "segment_body_road_count", "residual_road_count"])
        write_csv(bundle_dir / segment_name, [], ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])
        write_csv(bundle_dir / trunk_name, [], ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])

    current_nodes = tmp_path / "current_nodes.geojson"
    current_roads = tmp_path / "current_roads.geojson"
    baseline_nodes = tmp_path / "baseline_nodes.geojson"
    baseline_roads = tmp_path / "baseline_roads.geojson"

    write_geojson(
        current_nodes,
        [{"properties": {"id": 1, "grade_2": 1, "kind_2": 4, "segmentid": None, "sgrade": None}, "geometry": Point(0.0, 0.0)}],
    )
    write_geojson(baseline_nodes, [{"properties": {"id": 1, "grade_2": 1, "kind_2": 4}, "geometry": Point(0.0, 0.0)}])
    write_geojson(
        current_roads,
        [{"properties": {"id": "r1", "segmentid": "1_2", "sgrade": "0-0双"}, "geometry": LineString([(0.0, 0.0), (1.0, 0.0)])}],
    )
    write_geojson(
        baseline_roads,
        [{"properties": {"id": "r1", "segmentid": "1_2", "s_grade": "0-0双"}, "geometry": LineString([(0.0, 0.0), (1.0, 0.0)])}],
    )

    write_json(
        current_dir / "skill_v1_manifest.json",
        {
            "source_paths": {
                "refreshed_nodes_path": str(current_nodes.resolve()),
                "refreshed_roads_path": str(current_roads.resolve()),
            }
        },
    )
    write_json(
        freeze_dir / "FREEZE_MANIFEST.json",
        {
            "source_paths": {
                "refreshed_nodes_path": _to_wsl_path(baseline_nodes),
                "refreshed_roads_path": _to_wsl_path(baseline_roads),
            }
        },
    )
    write_json(current_dir / "skill_v1_summary.json", {"run_id": "current"})
    write_json(freeze_dir / "FREEZE_SUMMARY.json", {"freeze_label": "baseline"})

    _write_hash(current_dir / "refreshed_nodes_hash.json", "current-nodes-raw")
    _write_hash(freeze_dir / "refreshed_nodes_hash.json", "baseline-nodes-raw")
    _write_hash(current_dir / "refreshed_roads_hash.json", "current-roads-raw")
    _write_hash(freeze_dir / "refreshed_roads_hash.json", "baseline-roads-raw")

    report = compare_skill_v1_bundle(current_dir=current_dir, freeze_dir=freeze_dir, out_dir=out_dir)
    comparison_by_label = {item["label"]: item for item in report["comparisons"]}

    assert report["status"] == "PASS"
    assert comparison_by_label["refreshed_nodes_hash"]["semantic_compare_available"] is True
    assert comparison_by_label["refreshed_nodes_hash"]["status"] == "SCHEMA_MIGRATION_DIFFERENCE"
    assert comparison_by_label["refreshed_roads_hash"]["status"] == "SCHEMA_MIGRATION_DIFFERENCE"


def test_compare_skill_v1_bundle_treats_working_mainnodeid_hidden_as_schema_migration(tmp_path: Path) -> None:
    current_dir = tmp_path / "current"
    freeze_dir = tmp_path / "freeze"
    out_dir = tmp_path / "compare"
    current_dir.mkdir()
    freeze_dir.mkdir()

    for bundle_dir, validated_name, segment_name, trunk_name in (
        (
            current_dir,
            "validated_pairs_skill_v1.csv",
            "segment_body_membership_skill_v1.csv",
            "trunk_membership_skill_v1.csv",
        ),
        (
            freeze_dir,
            "validated_pairs_baseline.csv",
            "segment_body_membership_baseline.csv",
            "trunk_membership_baseline.csv",
        ),
    ):
        write_csv(bundle_dir / validated_name, [], ["stage", "pair_id", "a_node_id", "b_node_id", "trunk_mode", "left_turn_excluded_mode", "segment_body_road_count", "residual_road_count"])
        write_csv(bundle_dir / segment_name, [], ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])
        write_csv(bundle_dir / trunk_name, [], ["stage", "pair_id", "road_id", "layer_role", "trunk_mode"])

    current_nodes = tmp_path / "current_nodes.geojson"
    baseline_nodes = tmp_path / "baseline_nodes.geojson"
    shared_roads = tmp_path / "roads.geojson"

    write_geojson(
        current_nodes,
        [{"properties": {"id": 1, "grade_2": 1, "kind_2": 64, "mainnodeid": 1}, "geometry": Point(0.0, 0.0)}],
    )
    write_geojson(
        baseline_nodes,
        [
            {
                "properties": {
                    "id": 1,
                    "grade_2": 1,
                    "kind_2": 64,
                    "mainnodeid": 1,
                    "working_mainnodeid": 1,
                },
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    write_geojson(
        shared_roads,
        [{"properties": {"id": "r1", "segmentid": None, "sgrade": None}, "geometry": LineString([(0.0, 0.0), (1.0, 0.0)])}],
    )

    write_json(
        current_dir / "skill_v1_manifest.json",
        {
            "source_paths": {
                "refreshed_nodes_path": str(current_nodes.resolve()),
                "refreshed_roads_path": str(shared_roads.resolve()),
            }
        },
    )
    write_json(
        freeze_dir / "FREEZE_MANIFEST.json",
        {
            "source_paths": {
                "refreshed_nodes_path": str(baseline_nodes.resolve()),
                "refreshed_roads_path": str(shared_roads.resolve()),
            }
        },
    )
    write_json(current_dir / "skill_v1_summary.json", {"run_id": "current"})
    write_json(freeze_dir / "FREEZE_SUMMARY.json", {"freeze_label": "baseline"})

    _write_hash(current_dir / "refreshed_nodes_hash.json", "current-nodes-raw")
    _write_hash(freeze_dir / "refreshed_nodes_hash.json", "baseline-nodes-raw")
    _write_hash(current_dir / "refreshed_roads_hash.json", "shared-roads")
    _write_hash(freeze_dir / "refreshed_roads_hash.json", "shared-roads")

    report = compare_skill_v1_bundle(current_dir=current_dir, freeze_dir=freeze_dir, out_dir=out_dir)
    comparison_by_label = {item["label"]: item for item in report["comparisons"]}

    assert report["status"] == "PASS"
    assert report["schema_migration_only"] is True
    assert comparison_by_label["refreshed_nodes_hash"]["status"] == "SCHEMA_MIGRATION_DIFFERENCE"
    assert comparison_by_label["refreshed_roads_hash"]["status"] == "PASS"
