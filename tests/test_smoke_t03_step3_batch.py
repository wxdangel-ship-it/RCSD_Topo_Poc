from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_batch_runner import (
    run_t03_step3_legal_space_batch,
)


def _write_case_package(case_root: Path, case_id: str) -> None:
    case_root.mkdir(parents=True, exist_ok=True)
    write_vector(
        case_root / "nodes.gpkg",
        [
            {
                "properties": {
                    "id": case_id,
                    "mainnodeid": case_id,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    write_vector(case_root / "roads.gpkg", [])
    write_vector(case_root / "rcsdroad.gpkg", [])
    write_vector(case_root / "rcsdnode.gpkg", [])
    write_vector(case_root / "drivezone.gpkg", [{"properties": {"id": "dz"}, "geometry": box(-60.0, -60.0, 60.0, 60.0)}])
    manifest = {
        "bundle_version": 1,
        "mainnodeid": case_id,
        "epsg": 3857,
        "file_list": [
            "manifest.json",
            "size_report.json",
            "drivezone.gpkg",
            "nodes.gpkg",
            "roads.gpkg",
            "rcsdroad.gpkg",
            "rcsdnode.gpkg",
        ],
        "decoded_output": {"vector_crs": "EPSG:3857"},
    }
    size_report = {
        "within_limit": True,
        "limit_bytes": 307200,
    }
    (case_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_root / "size_report.json").write_text(json.dumps(size_report, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.smoke
def test_smoke_t03_step3_batch_writes_flat_review_outputs(tmp_path: Path) -> None:
    case_root = tmp_path / "cases_root"
    out_root = tmp_path / "outputs_root"
    _write_case_package(case_root / "100001", "100001")

    run_root = run_t03_step3_legal_space_batch(case_root=case_root, out_root=out_root, run_id="smoke_t03", workers=1)

    assert run_root == out_root / "smoke_t03"
    assert (run_root / "preflight.json").is_file()
    assert (run_root / "summary.json").is_file()
    assert (run_root / "step3_review_index.csv").is_file()

    case_dir = run_root / "cases" / "100001"
    assert case_dir.is_dir()
    for rel_path in (
        "step3_allowed_space.gpkg",
        "step3_negative_mask_adjacent_junction.gpkg",
        "step3_negative_mask_foreign_objects.gpkg",
        "step3_negative_mask_foreign_mst.gpkg",
        "step3_status.json",
        "step3_audit.json",
        "step3_review.png",
    ):
        assert (case_dir / rel_path).is_file()

    flat_dir = run_root / "step3_review_flat"
    flat_entries = sorted(flat_dir.iterdir())
    assert flat_dir.is_dir()
    assert flat_entries
    assert all(entry.is_file() for entry in flat_entries)
    assert len([entry for entry in flat_entries if entry.suffix.lower() == ".png"]) == 1
    assert all(entry.name == "100001__" + entry.stem.split("__", 1)[1] + ".png" for entry in flat_entries)
    assert not any(entry.is_dir() for entry in flat_entries)

    summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary_doc["total_case_count"] == 1
    assert summary_doc["expected_case_count"] == 1
    assert summary_doc["actual_case_dir_count"] == 1
    assert summary_doc["flat_png_count"] == 1
    assert summary_doc["step3_established_count"] + summary_doc["step3_review_count"] + summary_doc["step3_not_established_count"] == 1
    assert summary_doc["tri_state_sum"] == 1
    assert summary_doc["tri_state_sum_matches_total"] is True
    assert summary_doc["excluded_case_count"] == 0
    assert summary_doc["excluded_case_ids"] == []
    assert summary_doc["missing_case_ids"] == []
    assert summary_doc["failed_case_ids"] == []
    assert summary_doc["rerun_cleaned_before_write"] is False
    assert summary_doc["run_root"] == str(run_root)
    assert summary_doc["step3_review_flat_dir"] == str(flat_dir)

    with (run_root / "step3_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "100001"
    assert rows[0]["image_name"].startswith("100001__")
    assert rows[0]["image_path"] == str(flat_dir / rows[0]["image_name"])
