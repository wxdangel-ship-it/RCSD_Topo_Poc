from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_vector
from tests.modules.t10_e2e_orchestration.artifact_equivalence import (
    build_tree_manifest,
    compare_tree_manifests,
    semantic_fingerprint,
)


def test_semantic_fingerprint_ignores_runtime_metadata_and_root_paths(tmp_path: Path) -> None:
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    (left_root / "summary.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "duration_seconds": 10.0,
                "gc_collected_objects_after_stage": 99,
                "git_sha": "baseline-commit",
                "produced_at": "2026-07-10T00:00:01Z",
                "performance_verifiable": {"records_per_second": 10.0},
                "stage_durations_seconds": {"write": 9.0},
                "started_at_utc": "2026-07-10T00:00:00Z",
                "artifact": str(left_root / "result.gpkg"),
                "out_root": str(left_root.parent),
                "temporary_input": "/mnt/c/Users/admin/AppData/Local/Temp/t01_1885118_left/step5/roads.gpkg",
                "workers": 1,
            }
        ),
        encoding="utf-8",
    )
    (right_root / "summary.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "duration_seconds": 2.0,
                "gc_collected_objects_after_stage": 66,
                "git_sha": "current-commit",
                "produced_at": "2026-07-11T00:00:01Z",
                "performance_verifiable": {"records_per_second": 99.0},
                "stage_durations_seconds": {"write": 1.0},
                "started_at_utc": "2026-07-11T00:00:00Z",
                "artifact": str(right_root / "result.gpkg"),
                "out_root": str(right_root.parent.parent),
                "temporary_input": "/tmp/t01_1885118_right/step5/roads.gpkg",
                "workers": 4,
            }
        ),
        encoding="utf-8",
    )

    assert semantic_fingerprint(left_root / "summary.json", root=left_root)["sha256"] == semantic_fingerprint(
        right_root / "summary.json", root=right_root
    )["sha256"]


def test_semantic_fingerprint_detects_business_json_change(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"status":"passed","count":10}', encoding="utf-8")
    right.write_text('{"status":"passed","count":11}', encoding="utf-8")

    assert semantic_fingerprint(left)["sha256"] != semantic_fingerprint(right)["sha256"]


def test_semantic_fingerprint_treats_relation_road_id_collections_as_unordered(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(
        json.dumps(
            {
                "rcsd_road_ids": ["road-b", "road-a"],
                "frcsd_road_ids": "['road-2', 'road-1']",
            }
        ),
        encoding="utf-8",
    )
    right.write_text(
        json.dumps(
            {
                "rcsd_road_ids": ["road-a", "road-b"],
                "frcsd_road_ids": '["road-1", "road-2"]',
            }
        ),
        encoding="utf-8",
    )

    assert semantic_fingerprint(left)["sha256"] == semantic_fingerprint(right)["sha256"]


def test_semantic_fingerprint_ignores_dual_write_implementation_location(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(
        json.dumps(
            {
                "dual_write_manifest": [
                    {"file": "legacy.py", "line": 1439, "function": "_build_result"}
                ],
                "business_file": "formal.gpkg",
            }
        ),
        encoding="utf-8",
    )
    right.write_text(
        json.dumps(
            {
                "dual_write_manifest": [
                    {"file": "split_results.py", "line": 510, "function": "_build_result"}
                ],
                "business_file": "formal.gpkg",
            }
        ),
        encoding="utf-8",
    )

    assert semantic_fingerprint(left)["sha256"] == semantic_fingerprint(right)["sha256"]

    right.write_text(
        right.read_text(encoding="utf-8").replace("formal.gpkg", "changed.gpkg"),
        encoding="utf-8",
    )
    assert semantic_fingerprint(left)["sha256"] != semantic_fingerprint(right)["sha256"]


def test_semantic_fingerprint_compares_csv_as_business_row_set(tmp_path: Path) -> None:
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    fieldnames = ["id", "status"]
    write_csv(left, [{"id": "1", "status": "ok"}, {"id": "2", "status": "review"}], fieldnames)
    write_csv(right, [{"id": "2", "status": "review"}, {"id": "1", "status": "ok"}], fieldnames)

    assert semantic_fingerprint(left)["sha256"] == semantic_fingerprint(right)["sha256"]


def test_semantic_fingerprint_ignores_gpkg_container_metadata(tmp_path: Path) -> None:
    left = tmp_path / "left" / "result.gpkg"
    right = tmp_path / "right" / "result.gpkg"
    features = [{"properties": {"id": "1", "status": "accepted"}, "geometry": Point(1.0, 2.0)}]
    write_vector(left, features)
    write_vector(right, features)

    left_fingerprint = semantic_fingerprint(left)
    right_fingerprint = semantic_fingerprint(right)
    assert left_fingerprint["sha256"] == right_fingerprint["sha256"]


def test_semantic_fingerprint_normalizes_submicron_geometry_noise(tmp_path: Path) -> None:
    left = tmp_path / "left" / "result.gpkg"
    right = tmp_path / "right" / "result.gpkg"
    write_vector(
        left,
        [{"properties": {"id": "1"}, "geometry": Point(12699422.572541665, 2596670.791593415)}],
    )
    write_vector(
        right,
        [{"properties": {"id": "1"}, "geometry": Point(12699422.572541665, 2596670.7915934147)}],
    )

    assert semantic_fingerprint(left)["sha256"] == semantic_fingerprint(right)["sha256"]

    meaningful_change = tmp_path / "meaningful" / "result.gpkg"
    write_vector(
        meaningful_change,
        [{"properties": {"id": "1"}, "geometry": Point(12699422.572551665, 2596670.791593415)}],
    )
    assert semantic_fingerprint(left)["sha256"] != semantic_fingerprint(meaningful_change)["sha256"]


def test_tree_manifest_reports_missing_extra_and_changed_artifacts(tmp_path: Path) -> None:
    reference_root = tmp_path / "reference"
    candidate_root = tmp_path / "candidate"
    reference_root.mkdir()
    candidate_root.mkdir()
    (reference_root / "same.json").write_text('{"status":"passed"}', encoding="utf-8")
    (candidate_root / "same.json").write_text('{"status":"passed"}', encoding="utf-8")
    (reference_root / "changed.json").write_text('{"count":1}', encoding="utf-8")
    (candidate_root / "changed.json").write_text('{"count":2}', encoding="utf-8")
    (reference_root / "missing.json").write_text('{"count":1}', encoding="utf-8")
    (candidate_root / "extra.json").write_text('{"count":1}', encoding="utf-8")
    (reference_root / "runtime_performance.json").write_text('{"elapsed_seconds":9}', encoding="utf-8")
    (candidate_root / "runtime_performance.json").write_text('{"elapsed_seconds":1}', encoding="utf-8")
    (reference_root / "cli_stdout.json").write_text("plain text log", encoding="utf-8")
    (candidate_root / "cli_stdout.json").write_text("different plain text log", encoding="utf-8")

    comparison = compare_tree_manifests(
        build_tree_manifest(reference_root),
        build_tree_manifest(candidate_root),
    )

    assert comparison["passed"] is False
    assert comparison["missing_in_candidate"] == ["missing.json"]
    assert comparison["extra_in_candidate"] == ["extra.json"]
    assert comparison["changed"] == ["changed.json"]


def test_tree_manifest_can_normalize_paths_from_a_separate_source_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    local_copy_root = tmp_path / "local-copy"
    source_root.mkdir()
    local_copy_root.mkdir()
    payload = {"artifact": str(source_root / "result.gpkg"), "status": "passed"}
    (source_root / "summary.json").write_text(json.dumps(payload), encoding="utf-8")
    (local_copy_root / "summary.json").write_text(json.dumps(payload), encoding="utf-8")

    assert build_tree_manifest(source_root) == build_tree_manifest(
        local_copy_root,
        normalization_root=source_root,
    )
