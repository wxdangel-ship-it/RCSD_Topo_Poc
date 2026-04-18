from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import (
    DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
    load_case_specs,
)


def _write_case_package(case_root: Path, case_id: str, *, file_list: list[str] | None = None) -> None:
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
    write_vector(case_root / "drivezone.gpkg", [{"properties": {"id": "dz"}, "geometry": box(-50.0, -50.0, 50.0, 50.0)}])
    manifest = {
        "bundle_version": 1,
        "mainnodeid": case_id,
        "epsg": 3857,
        "file_list": file_list
        or [
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


def test_case_loader_ignores_out_and_renders_dirs(tmp_path: Path) -> None:
    _write_case_package(tmp_path / "100001", "100001")
    (tmp_path / "out").mkdir()
    (tmp_path / "renders").mkdir()
    (tmp_path / "out" / "junk.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "renders" / "junk.txt").write_text("ignored", encoding="utf-8")

    specs, preflight = load_case_specs(case_root=tmp_path)

    assert [spec.case_id for spec in specs] == ["100001"]
    assert preflight["raw_case_count"] == 1
    assert preflight["default_formal_case_count"] == 1
    assert preflight["effective_case_count"] == 1
    assert preflight["selected_case_count"] == 1
    assert preflight["selected_case_ids"] == ["100001"]
    assert preflight["effective_case_ids"] == ["100001"]
    assert all(row["case_id"] == "100001" for row in preflight["rows"])
    assert preflight["applied_excluded_case_ids"] == []


def test_case_loader_rejects_manifest_missing_required_file_list_entry(tmp_path: Path) -> None:
    _write_case_package(
        tmp_path / "200001",
        "200001",
        file_list=[
            "manifest.json",
            "size_report.json",
            "drivezone.gpkg",
            "nodes.gpkg",
            "rcsdroad.gpkg",
            "rcsdnode.gpkg",
        ],
    )

    with pytest.raises(ValueError, match=r"manifest_missing_files=roads\.gpkg"):
        load_case_specs(case_root=tmp_path)


def test_case_loader_excludes_confirmed_input_gate_cases_from_default_full_batch(tmp_path: Path) -> None:
    _write_case_package(tmp_path / "922217", "922217")
    _write_case_package(tmp_path / "54265667", "54265667")
    _write_case_package(tmp_path / "502058682", "502058682")
    _write_case_package(tmp_path / "100001", "100001")

    specs, preflight = load_case_specs(case_root=tmp_path, exclude_case_ids=DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS)

    assert [spec.case_id for spec in specs] == ["100001"]
    assert preflight["raw_case_count"] == 4
    assert preflight["default_formal_case_count"] == 1
    assert preflight["effective_case_count"] == 1
    assert preflight["selected_case_ids"] == ["100001"]
    assert preflight["effective_case_ids"] == ["100001"]
    assert preflight["applied_excluded_case_ids"] == ["922217", "54265667", "502058682"]


def test_case_loader_keeps_explicitly_selected_excluded_case_available(tmp_path: Path) -> None:
    _write_case_package(tmp_path / "922217", "922217")

    specs, preflight = load_case_specs(
        case_root=tmp_path,
        case_ids=["922217"],
        exclude_case_ids=DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
    )

    assert [spec.case_id for spec in specs] == ["922217"]
    assert preflight["explicit_case_selection"] is True
    assert preflight["raw_case_count"] == 1
    assert preflight["default_formal_case_count"] == 0
    assert preflight["effective_case_count"] == 1
    assert preflight["effective_case_ids"] == ["922217"]
    assert preflight["applied_excluded_case_ids"] == []
