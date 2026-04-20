from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_synthetic_case_package(case_dir: Path) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    file_list = [
        "manifest.json",
        "size_report.json",
        "drivezone.gpkg",
        "divstripzone.gpkg",
        "nodes.gpkg",
        "roads.gpkg",
        "rcsdroad.gpkg",
        "rcsdnode.gpkg",
    ]
    _write_json(
        case_dir / "manifest.json",
        {
            "bundle_version": 1,
            "bundle_mode": "single_case",
            "mainnodeid": "1001",
            "epsg": 3857,
            "file_list": file_list,
            "decoded_output": {
                "vector_crs": "EPSG:3857",
            },
        },
    )
    _write_json(case_dir / "size_report.json", {"within_limit": True})

    drivezone = Polygon([(-70, -40), (70, -40), (70, 40), (-70, 40), (-70, -40)])
    divstrip = Polygon([(2, -5), (18, 0), (2, 5), (-2, 0), (2, -5)])

    write_vector(
        case_dir / "drivezone.gpkg",
        [{"properties": {"id": 1, "patchid": 1}, "geometry": drivezone}],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "divstripzone.gpkg",
        [{"properties": {"id": 1, "patchid": 1}, "geometry": divstrip}],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "nodes.gpkg",
        [
            {
                "properties": {
                    "id": 1001,
                    "mainnodeid": 1001,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 16,
                    "grade_2": 1,
                },
                "geometry": Point(0, 0),
            },
            {
                "properties": {
                    "id": 2001,
                    "mainnodeid": None,
                    "has_evd": "no",
                    "is_anchor": "no",
                    "kind_2": 0,
                    "grade_2": 0,
                },
                "geometry": Point(-45, 0),
            },
            {
                "properties": {
                    "id": 3001,
                    "mainnodeid": None,
                    "has_evd": "no",
                    "is_anchor": "no",
                    "kind_2": 0,
                    "grade_2": 0,
                },
                "geometry": Point(42, 22),
            },
            {
                "properties": {
                    "id": 3002,
                    "mainnodeid": None,
                    "has_evd": "no",
                    "is_anchor": "no",
                    "kind_2": 0,
                    "grade_2": 0,
                },
                "geometry": Point(42, -22),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "roads.gpkg",
        [
            {
                "properties": {"id": 1, "snodeid": 2001, "enodeid": 1001, "direction": 2, "patchid": 1},
                "geometry": LineString([(-45, 0), (0, 0)]),
            },
            {
                "properties": {"id": 2, "snodeid": 1001, "enodeid": 3001, "direction": 2, "patchid": 1},
                "geometry": LineString([(0, 0), (12, 8), (42, 22)]),
            },
            {
                "properties": {"id": 3, "snodeid": 1001, "enodeid": 3002, "direction": 2, "patchid": 1},
                "geometry": LineString([(0, 0), (12, -8), (42, -22)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "rcsdroad.gpkg",
        [
            {
                "properties": {"id": 11, "snodeid": 1001, "enodeid": 3001, "direction": 2},
                "geometry": LineString([(0, 0), (10, 6), (38, 20)]),
            },
            {
                "properties": {"id": 12, "snodeid": 1001, "enodeid": 3002, "direction": 2},
                "geometry": LineString([(0, 0), (10, -6), (38, -20)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "rcsdnode.gpkg",
        [
            {
                "properties": {"id": 9001, "mainnodeid": 1001},
                "geometry": Point(5, 0),
            },
        ],
        crs_text="EPSG:3857",
    )


def _build_multi_event_case_package(case_dir: Path) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    file_list = [
        "manifest.json",
        "size_report.json",
        "drivezone.gpkg",
        "divstripzone.gpkg",
        "nodes.gpkg",
        "roads.gpkg",
        "rcsdroad.gpkg",
        "rcsdnode.gpkg",
    ]
    _write_json(
        case_dir / "manifest.json",
        {
            "bundle_version": 1,
            "bundle_mode": "single_case",
            "mainnodeid": "2002",
            "epsg": 3857,
            "file_list": file_list,
            "decoded_output": {
                "vector_crs": "EPSG:3857",
            },
        },
    )
    _write_json(case_dir / "size_report.json", {"within_limit": True})

    write_vector(
        case_dir / "drivezone.gpkg",
        [{"properties": {"id": 1, "patchid": 1}, "geometry": Polygon([(-90, -60), (90, -60), (90, 60), (-90, 60), (-90, -60)])}],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "divstripzone.gpkg",
        [
            {"properties": {"id": 1, "patchid": 1}, "geometry": Polygon([(5, -6), (18, 0), (5, 6), (-2, 0), (5, -6)])},
            {"properties": {"id": 2, "patchid": 1}, "geometry": Polygon([(8, 12), (22, 18), (12, 28), (4, 18), (8, 12)])},
            {"properties": {"id": 3, "patchid": 1}, "geometry": Polygon([(8, -12), (22, -18), (12, -28), (4, -18), (8, -12)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "nodes.gpkg",
        [
            {"properties": {"id": 2002, "mainnodeid": 2002, "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1}, "geometry": Point(0, 0)},
            {"properties": {"id": 2101, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0}, "geometry": Point(-45, 0)},
            {"properties": {"id": 2201, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0}, "geometry": Point(38, 35)},
            {"properties": {"id": 2202, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0}, "geometry": Point(52, 12)},
            {"properties": {"id": 2203, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0}, "geometry": Point(52, -12)},
            {"properties": {"id": 2204, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0}, "geometry": Point(38, -35)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "roads.gpkg",
        [
            {"properties": {"id": 1, "snodeid": 2101, "enodeid": 2002, "direction": 2, "patchid": 1}, "geometry": LineString([(-45, 0), (0, 0)])},
            {"properties": {"id": 2, "snodeid": 2002, "enodeid": 2201, "direction": 2, "patchid": 1}, "geometry": LineString([(0, 0), (8, 10), (38, 35)])},
            {"properties": {"id": 3, "snodeid": 2002, "enodeid": 2202, "direction": 2, "patchid": 1}, "geometry": LineString([(0, 0), (18, 5), (52, 12)])},
            {"properties": {"id": 4, "snodeid": 2002, "enodeid": 2203, "direction": 2, "patchid": 1}, "geometry": LineString([(0, 0), (18, -5), (52, -12)])},
            {"properties": {"id": 5, "snodeid": 2002, "enodeid": 2204, "direction": 2, "patchid": 1}, "geometry": LineString([(0, 0), (8, -10), (38, -35)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "rcsdroad.gpkg",
        [
            {"properties": {"id": 11, "snodeid": 2002, "enodeid": 2201, "direction": 2}, "geometry": LineString([(0, 0), (7, 9), (35, 32)])},
            {"properties": {"id": 12, "snodeid": 2002, "enodeid": 2202, "direction": 2}, "geometry": LineString([(0, 0), (18, 5), (49, 12)])},
            {"properties": {"id": 13, "snodeid": 2002, "enodeid": 2203, "direction": 2}, "geometry": LineString([(0, 0), (18, -5), (49, -12)])},
            {"properties": {"id": 14, "snodeid": 2002, "enodeid": 2204, "direction": 2}, "geometry": LineString([(0, 0), (7, -9), (35, -32)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "rcsdnode.gpkg",
        [{"properties": {"id": 9902, "mainnodeid": 2002}, "geometry": Point(4, 0)}],
        crs_text="EPSG:3857",
    )


@pytest.mark.smoke
def test_t04_step14_batch_outputs_synthetic_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out",
        run_id="synthetic_t04",
    )

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))

    assert summary["total_case_count"] == 1
    assert summary["failed_case_ids"] == []
    assert review_summary["total_event_unit_count"] >= 1
    assert (run_root / "cases" / "1001" / "step4_review_overview.png").is_file()
    assert any((run_root / "step4_review_flat").glob("*.png"))
    assert any((run_root / "cases" / "1001" / "event_units").rglob("step4_review.png"))


@pytest.mark.smoke
def test_t04_step14_batch_outputs_multi_event_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "2002"
    _build_multi_event_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_multi",
        run_id="synthetic_t04_multi",
    )

    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))
    flat_pngs = sorted((run_root / "step4_review_flat").glob("*.png"))

    assert review_summary["total_event_unit_count"] == 3
    assert review_summary["cases_with_multiple_event_units"] == ["2002"]
    assert len(flat_pngs) == 3
    assert all("__2002__" in path.name for path in flat_pngs)
