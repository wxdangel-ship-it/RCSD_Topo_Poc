from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_loader import (
    load_case_bundle,
    load_case_specs,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.event_interpretation import (
    build_case_result,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch


REAL_ANCHOR_2_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor_2")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_branch_id_with_required_roads(
    branch_road_memberships: dict[str, list[str]] | dict[str, tuple[str, ...]],
    required_road_ids: set[str],
) -> str:
    for branch_id, road_ids in branch_road_memberships.items():
        if required_road_ids.issubset({str(road_id) for road_id in road_ids}):
            return str(branch_id)
    raise AssertionError(f"missing branch for roads={sorted(required_road_ids)}")


def _find_branch_id_with_road(
    branch_road_memberships: dict[str, list[str]] | dict[str, tuple[str, ...]],
    road_id: str,
) -> str:
    for branch_id, road_ids in branch_road_memberships.items():
        if str(road_id) in {str(item) for item in road_ids}:
            return str(branch_id)
    raise AssertionError(f"missing branch for road={road_id}")


def _stable_axis_signature(
    branch_road_memberships: dict[str, list[str]] | dict[str, tuple[str, ...]],
    branch_id: str | None,
) -> str:
    if branch_id is None:
        return ""
    road_ids = sorted({str(road_id) for road_id in branch_road_memberships.get(str(branch_id), ()) if str(road_id)})
    if not road_ids:
        return str(branch_id)
    if len(road_ids) == 1:
        return road_ids[0]
    return "+".join(road_ids)


def _stable_boundary_pair_signature(
    branch_road_memberships: dict[str, list[str]] | dict[str, tuple[str, ...]],
    boundary_branch_ids: list[str] | tuple[str, ...],
) -> str:
    return "__".join(
        _stable_axis_signature(branch_road_memberships, branch_id)
        for branch_id in boundary_branch_ids
    )


def _assert_one_sided_offsets(offsets: list[float] | tuple[float, ...]) -> None:
    numeric_offsets = [float(item) for item in offsets]
    assert numeric_offsets
    assert numeric_offsets[0] == pytest.approx(0.0, abs=1e-6) or numeric_offsets[-1] == pytest.approx(0.0, abs=1e-6)
    non_zero = [item for item in numeric_offsets if abs(item) > 1e-6]
    if not non_zero:
        return
    assert not (any(item > 0.0 for item in non_zero) and any(item < 0.0 for item in non_zero))


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
def test_t04_step14_batch_writes_unit_level_step3_and_candidate_docs(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_docs",
        run_id="synthetic_t04_docs",
    )

    result_case_dir = run_root / "cases" / "1001"
    case_step3 = json.loads((result_case_dir / "step3_status.json").read_text(encoding="utf-8"))
    unit_dir = next((result_case_dir / "event_units").iterdir())
    unit_step3 = json.loads((unit_dir / "step3_status.json").read_text(encoding="utf-8"))
    candidate_doc = json.loads((unit_dir / "step4_candidates.json").read_text(encoding="utf-8"))

    assert case_step3["topology_scope"] == "case_coordination"
    assert unit_step3["topology_scope"] == "case_coordination"
    assert unit_step3["event_branch_ids"] == ["road_3"]
    assert unit_step3["boundary_branch_ids"] == ["road_1", "road_2", "road_3"]
    assert unit_step3["preferred_axis_branch_id"] == "road_1"
    assert unit_step3["degraded_scope_reason"] == "pair_local_scope_roads_empty"

    selected_candidate = candidate_doc["selected_candidate"]
    assert selected_candidate["candidate_id"].startswith("event_unit_01:structure:")
    assert selected_candidate["layer_label"] == "Layer 1"
    assert selected_candidate["selection_rank"] == 1
    expected_axis_signature = _stable_axis_signature(
        unit_step3["branch_road_memberships"],
        unit_step3["preferred_axis_branch_id"],
    )
    assert selected_candidate["point_signature"].startswith(f"{expected_axis_signature}:")
    assert any(
        candidate["layer_label"] == "Layer 2"
        for candidate in candidate_doc["alternative_candidates"]
    )


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


@pytest.mark.smoke
def test_t04_step14_multi_event_case_exports_reselection_and_index_fields(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "2002"
    _build_multi_event_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_multi_docs",
        run_id="synthetic_t04_multi_docs",
    )

    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))
    assert review_summary["selected_layer_1_count"] == 3
    assert review_summary["selected_layer_2_count"] == 0
    assert review_summary["selected_layer_3_count"] == 0

    event_unit_02_dir = run_root / "cases" / "2002" / "event_units" / "event_unit_02"
    event_unit_03_dir = run_root / "cases" / "2002" / "event_units" / "event_unit_03"
    unit_02_step3 = json.loads((event_unit_02_dir / "step3_status.json").read_text(encoding="utf-8"))
    unit_03_step3 = json.loads((event_unit_03_dir / "step3_status.json").read_text(encoding="utf-8"))
    unit_02_candidates = json.loads((event_unit_02_dir / "step4_candidates.json").read_text(encoding="utf-8"))
    unit_03_candidates = json.loads((event_unit_03_dir / "step4_candidates.json").read_text(encoding="utf-8"))

    assert unit_02_step3["topology_scope"] == "multi_divmerge_case_input"
    assert unit_02_candidates["selected_candidate"]["selected_after_reselection"] is False
    assert unit_02_candidates["selected_candidate"]["selection_rank"] == 1
    assert unit_02_candidates["selected_candidate"]["layer_label"] == "Layer 1"
    assert any(
        candidate["candidate_id"] == "event_unit_02:structure:throat:01"
        for candidate in unit_02_candidates["alternative_candidates"]
    )
    assert any(candidate["reverse_tip_used"] is True for candidate in unit_02_candidates["alternative_candidates"])

    assert unit_03_candidates["selected_candidate"]["selected_after_reselection"] is False
    assert unit_03_candidates["selected_candidate"]["selection_rank"] == 1
    expected_unit_03_axis_signature = _stable_axis_signature(
        unit_03_step3["branch_road_memberships"],
        unit_03_step3["preferred_axis_branch_id"],
    )
    assert unit_03_candidates["selected_candidate"]["point_signature"] == f"{expected_unit_03_axis_signature}:45.0"
    assert any(candidate["reverse_tip_used"] is True for candidate in unit_03_candidates["alternative_candidates"])

    with (run_root / "step4_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        rows = {row["event_unit_id"]: row for row in csv.DictReader(fp)}

    assert rows["event_unit_01"]["primary_candidate_layer"] == "Layer 1"
    assert rows["event_unit_02"]["primary_candidate_layer"] == "Layer 1"
    expected_unit_02_axis_signature = _stable_axis_signature(
        unit_02_step3["branch_road_memberships"],
        unit_02_step3["preferred_axis_branch_id"],
    )
    assert rows["event_unit_02"]["point_signature"] == f"{expected_unit_02_axis_signature}:45.0"
    assert rows["event_unit_03"]["point_signature"] == f"{expected_unit_03_axis_signature}:45.0"
    assert rows["event_unit_02"]["ownership_signature"].startswith("structure_face:")


def test_real_case_17943587_keeps_same_case_merge_branch_continuation_and_nested_pair_geometry() -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["17943587"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    event_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_17943587"
    )

    branch_road_memberships = event_unit.unit_envelope.branch_road_memberships
    merge_branch_1 = _find_branch_id_with_required_roads(
        branch_road_memberships,
        {"510969745"},
    )
    merge_branch_2 = _find_branch_id_with_required_roads(
        branch_road_memberships,
        {"607951495", "528620938"},
    )

    assert merge_branch_1 != merge_branch_2
    assert "607951495" not in set(branch_road_memberships[merge_branch_1])
    assert "510969745" not in set(branch_road_memberships[merge_branch_2])
    assert set(event_unit.unit_envelope.event_branch_ids) == {merge_branch_1, merge_branch_2}
    assert set(event_unit.unit_envelope.boundary_branch_ids) == {merge_branch_1, merge_branch_2}
    assert "55353233" in set(event_unit.unit_envelope.branch_bridge_node_ids[merge_branch_2])
    assert event_unit.pair_local_summary["operational_kind_hint"] == 8

    pair_middle = event_unit.pair_local_middle_geometry
    structure_face = event_unit.pair_local_structure_face_geometry
    pair_region = event_unit.pair_local_region_geometry

    assert pair_middle is not None and not pair_middle.is_empty
    assert structure_face is not None and not structure_face.is_empty
    assert pair_region is not None and not pair_region.is_empty
    assert structure_face.buffer(1e-6).covers(pair_middle)
    assert pair_region.buffer(1e-6).covers(structure_face)
    assert pair_middle.equals(structure_face) is False
    assert event_unit.selected_candidate_summary["candidate_id"] == "node_17943587:structure:middle:01"
    assert event_unit.selected_candidate_summary["layer"] == 1
    assert event_unit.selected_candidate_region_geometry is not None
    assert event_unit.selected_candidate_region_geometry.buffer(1e-6).covers(
        event_unit.unit_context.representative_node.geometry
    )

    sibling_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_55353233"
    )
    sibling_branch_road_memberships = sibling_unit.unit_envelope.branch_road_memberships
    sibling_merge_branch = _find_branch_id_with_required_roads(
        sibling_branch_road_memberships,
        {"502953712", "41727506", "620950831"},
    )
    assert set(sibling_branch_road_memberships[sibling_merge_branch]) == {
        "502953712",
        "41727506",
        "620950831",
    }
    assert "605949403" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    assert "607962170" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    sibling_output_branch = _find_branch_id_with_road(
        sibling_branch_road_memberships,
        "607951495",
    )
    assert set(sibling_branch_road_memberships[sibling_output_branch]) == {"607951495"}
    assert "529824990" not in set(sibling_branch_road_memberships[sibling_output_branch])

    local_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_55353248"
    )
    local_branch_road_memberships = local_unit.unit_envelope.branch_road_memberships
    local_merge_branch = _find_branch_id_with_required_roads(
        local_branch_road_memberships,
        {"41727506", "607962170"},
    )
    assert "620950831" not in set(local_branch_road_memberships[local_merge_branch])
    local_axis_branch = _find_branch_id_with_road(
        local_branch_road_memberships,
        "502953712",
    )
    assert set(local_branch_road_memberships[local_axis_branch]) == {"502953712"}
    assert local_unit.pair_local_summary["pair_scan_truncated_to_local"] is True
    assert set(local_unit.unit_envelope.event_branch_ids) == set(local_unit.unit_envelope.boundary_branch_ids)
    assert local_axis_branch not in set(local_unit.unit_envelope.event_branch_ids)
    _assert_one_sided_offsets(local_unit.pair_local_summary["valid_scan_offsets_m"])
    assert local_unit.selected_candidate_summary["candidate_id"] == "node_55353248:structure:middle:01"
    assert local_unit.selected_candidate_region_geometry is not None
    assert local_unit.selected_candidate_region_geometry.buffer(1e-6).covers(
        local_unit.unit_context.representative_node.geometry
    )
    assert local_unit.pair_local_middle_geometry is not None
    assert local_unit.pair_local_structure_face_geometry is not None
    assert float(local_unit.selected_candidate_region_geometry.area) == pytest.approx(
        float(local_unit.pair_local_middle_geometry.area),
        abs=1e-3,
    )
    assert float(local_unit.selected_candidate_region_geometry.area) < float(
        local_unit.pair_local_structure_face_geometry.area
    )
    assert float(local_unit.pair_local_middle_geometry.area) == pytest.approx(
        float(local_unit.pair_local_summary["pair_local_middle_area_m2"]),
        abs=1e-3,
    )


def test_real_simple_three_arm_cases_keep_direct_event_pair_branches() -> None:
    expected_case_roads = {
        "785671": {
            "event_roads": {"980348", "527854843"},
            "axis_road": "600961614",
        },
        "987998": {
            "event_roads": {"1026704", "1078428"},
            "axis_road": "1035952",
        },
        "30434673": {
            "event_roads": {"530277767", "76761971"},
            "axis_road": "76761972",
        },
    }
    missing_cases = [case_id for case_id in expected_case_roads if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_case_roads),
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    for case_id, expected in expected_case_roads.items():
        case_result = build_case_result(load_case_bundle(case_by_id[case_id]))
        assert len(case_result.event_units) == 1
        event_unit = case_result.event_units[0]
        branch_road_memberships = event_unit.unit_envelope.branch_road_memberships

        event_branch_ids = {
            _find_branch_id_with_road(branch_road_memberships, road_id)
            for road_id in expected["event_roads"]
        }
        axis_branch_id = _find_branch_id_with_road(
            branch_road_memberships,
            expected["axis_road"],
        )

        assert event_unit.spec.split_mode == "one_case_one_unit"
        assert len(event_unit.unit_envelope.branch_ids) == 3
        assert event_branch_ids == set(event_unit.unit_envelope.event_branch_ids)
        assert event_branch_ids == set(event_unit.unit_envelope.boundary_branch_ids)
        assert axis_branch_id not in event_branch_ids
        assert set(branch_road_memberships[axis_branch_id]) == {expected["axis_road"]}
        assert event_unit.pair_local_summary["event_branch_ids"] == list(event_unit.unit_envelope.event_branch_ids)
        assert event_unit.pair_local_summary["boundary_branch_ids"] == list(event_unit.unit_envelope.boundary_branch_ids)
        _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])


def test_real_simple_two_branch_cases_prefer_pair_local_structure_face_over_weak_throat() -> None:
    expected_candidates = {
        "785671": "event_unit_01:structure:middle:01",
        "987998": "event_unit_01:structure:middle:01",
        "30434673": "event_unit_01:structure:middle:01",
    }
    missing_cases = [case_id for case_id in expected_candidates if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_candidates),
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    for case_id, expected_candidate_id in expected_candidates.items():
        case_result = build_case_result(load_case_bundle(case_by_id[case_id]))
        event_unit = case_result.event_units[0]
        selected = event_unit.selected_candidate_summary

        assert selected["candidate_id"] == expected_candidate_id
        assert selected["layer"] == 1
        assert selected["layer_reason"] == "throat_core_plus_pair_middle"
        assert float(selected["pair_middle_overlap_ratio"]) == pytest.approx(1.0, abs=1e-6)
        assert float(selected["throat_overlap_ratio"]) > 0.0
        assert event_unit.selected_candidate_region_geometry is not None
        assert event_unit.pair_local_middle_geometry is not None
        assert event_unit.selected_candidate_region_geometry.buffer(1e-6).covers(
            event_unit.unit_context.representative_node.geometry
        )
        assert float(event_unit.selected_candidate_region_geometry.area) == pytest.approx(
            float(event_unit.pair_local_middle_geometry.area),
            abs=1e-3,
        )


def test_real_cases_760213_and_17943587_keep_current_selected_candidates() -> None:
    case_ids = ["760213", "17943587"]
    missing_cases = [case_id for case_id in case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=case_ids,
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    case_760213 = build_case_result(load_case_bundle(case_by_id["760213"]))
    selected_by_unit_760213 = {
        item.spec.event_unit_id: str(item.selected_candidate_summary.get("candidate_id") or "")
        for item in case_760213.event_units
    }
    assert selected_by_unit_760213 == {
        "node_760213": "node_760213:structure:middle:01",
        "node_760218": "node_760218:structure:middle:01",
    }

    case_17943587 = build_case_result(load_case_bundle(case_by_id["17943587"]))
    selected_by_unit_17943587 = {
        item.spec.event_unit_id: str(item.selected_candidate_summary.get("candidate_id") or "")
        for item in case_17943587.event_units
    }
    assert selected_by_unit_17943587 == {
        "node_17943587": "node_17943587:structure:middle:01",
        "node_55353233": "node_55353233:structure:middle:01",
        "node_55353239": "node_55353239:structure:middle:01",
        "node_55353248": "node_55353248:structure:middle:01",
    }


def test_real_case_17943587_node_55353239_keeps_local_three_arm_and_returns_to_primary_middle_candidate() -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["17943587"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    event_unit = next(
        item for item in case_result.event_units if item.spec.event_unit_id == "node_55353239"
    )

    assert event_unit.unit_envelope.branch_road_memberships == {
        "road_1": ("607962170",),
        "road_2": ("620950831",),
        "road_3": ("41727506",),
    }
    assert event_unit.selected_candidate_summary["candidate_id"] == "node_55353239:structure:middle:01"
    assert event_unit.selected_candidate_summary["layer"] == 1
    assert event_unit.selected_candidate_summary["selection_rank"] == 1
    assert event_unit.selected_candidate_summary["selected_after_reselection"] is False
    assert event_unit.review_state == "STEP4_REVIEW"

    representative_node_geometry = event_unit.unit_context.representative_node.geometry
    assert event_unit.pair_local_region_geometry is not None
    assert event_unit.pair_local_structure_face_geometry is not None
    assert event_unit.pair_local_middle_geometry is not None
    assert event_unit.selected_candidate_region_geometry is not None
    assert event_unit.pair_local_region_geometry.buffer(1e-6).covers(representative_node_geometry)
    assert event_unit.pair_local_structure_face_geometry.buffer(1e-6).covers(representative_node_geometry)
    assert event_unit.selected_candidate_region_geometry.buffer(1e-6).covers(representative_node_geometry)


def test_real_case_857993_keeps_node_857993_local_and_stops_node_870089_at_direct_branches() -> None:
    if not (REAL_ANCHOR_2_ROOT / "857993").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '857993'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["857993"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))

    node_857993 = next(item for item in case_result.event_units if item.spec.event_unit_id == "node_857993")
    assert node_857993.unit_envelope.branch_road_memberships == {
        "road_1": ("619715536",),
        "road_2": ("12557730",),
        "road_3": ("1112045",),
    }

    node_870089 = next(item for item in case_result.event_units if item.spec.event_unit_id == "node_870089")
    memberships = node_870089.unit_envelope.branch_road_memberships
    left_branch_id = _find_branch_id_with_road(memberships, "617462076")
    right_branch_id = _find_branch_id_with_road(memberships, "509954401")
    axis_branch_id = _find_branch_id_with_road(memberships, "619715536")

    assert set(memberships[left_branch_id]) == {"617462076"}
    assert set(memberships[right_branch_id]) == {"509954401"}
    assert set(memberships[axis_branch_id]) == {"619715536"}
    assert "517458735" not in set(memberships[left_branch_id])
    assert "1124251" not in set(memberships[right_branch_id])
    assert set(node_870089.unit_envelope.event_branch_ids) == {left_branch_id, right_branch_id}

    assert node_857993.selected_candidate_summary["candidate_id"] == "node_857993:structure:middle:01"
    assert node_857993.selected_candidate_summary["layer"] == 1
    assert node_857993.selected_candidate_summary["selected_after_reselection"] is False
    assert node_857993.selected_candidate_region_geometry is not None
    assert node_857993.selected_candidate_region_geometry.buffer(1e-6).covers(
        node_857993.unit_context.representative_node.geometry
    )
    _assert_one_sided_offsets(node_857993.pair_local_summary["valid_scan_offsets_m"])
    expected_node_857993_pair_signature = _stable_boundary_pair_signature(
        node_857993.unit_envelope.branch_road_memberships,
        node_857993.unit_envelope.boundary_branch_ids,
    )
    assert node_857993.pair_local_summary["boundary_pair_signature"] == expected_node_857993_pair_signature
    assert node_857993.selected_candidate_summary["upper_evidence_object_id"] == (
        f"node_857993:{expected_node_857993_pair_signature}"
    )

    assert node_870089.selected_candidate_summary["candidate_id"] == "node_870089:structure:middle:01"
    assert node_870089.selected_candidate_summary["layer"] == 1
    assert node_870089.selected_candidate_region_geometry is not None
    assert node_870089.selected_candidate_region_geometry.buffer(1e-6).covers(
        node_870089.unit_context.representative_node.geometry
    )
    assert node_870089.pair_local_middle_geometry is not None
    assert node_870089.pair_local_structure_face_geometry is not None
    assert set(node_870089.unit_envelope.event_branch_ids) == set(node_870089.unit_envelope.boundary_branch_ids)
    assert axis_branch_id not in set(node_870089.unit_envelope.event_branch_ids)
    assert node_870089.pair_local_summary["pair_scan_truncated_to_local"] is True
    _assert_one_sided_offsets(node_870089.pair_local_summary["valid_scan_offsets_m"])
    expected_node_870089_pair_signature = _stable_boundary_pair_signature(
        node_870089.unit_envelope.branch_road_memberships,
        node_870089.unit_envelope.boundary_branch_ids,
    )
    assert node_870089.pair_local_summary["boundary_pair_signature"] == expected_node_870089_pair_signature
    assert node_870089.selected_candidate_summary["upper_evidence_object_id"] == (
        f"node_870089:{expected_node_870089_pair_signature}"
    )
    assert float(node_870089.selected_candidate_region_geometry.area) == pytest.approx(
        node_870089.pair_local_middle_geometry.area
    )
    assert float(node_870089.selected_candidate_region_geometry.area) < float(
        node_870089.pair_local_structure_face_geometry.area
    )

    assert node_857993.selected_candidate_summary["axis_signature"] == "619715536"
    assert node_870089.selected_candidate_summary["axis_signature"] == "619715536"
    assert (
        node_857993.selected_candidate_summary["point_signature"]
        != node_870089.selected_candidate_summary["point_signature"]
    )


def test_real_case_73462878_keeps_pair_space_on_event_branches_only() -> None:
    if not (REAL_ANCHOR_2_ROOT / "73462878").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '73462878'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["73462878"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    assert len(case_result.event_units) == 1
    event_unit = case_result.event_units[0]
    memberships = event_unit.unit_envelope.branch_road_memberships

    axis_branch_id = _find_branch_id_with_road(memberships, "516876825")
    left_branch_id = _find_branch_id_with_road(memberships, "527735857")
    right_branch_id = _find_branch_id_with_road(memberships, "617735601")

    assert set(event_unit.unit_envelope.event_branch_ids) == {left_branch_id, right_branch_id}
    assert set(event_unit.unit_envelope.boundary_branch_ids) == {left_branch_id, right_branch_id}
    assert axis_branch_id not in set(event_unit.unit_envelope.event_branch_ids)
    assert event_unit.selected_candidate_summary["candidate_id"] == "event_unit_01:structure:middle:01"
    assert event_unit.selected_candidate_summary["layer"] == 1
    assert event_unit.selected_candidate_region_geometry is not None
    assert event_unit.selected_candidate_region_geometry.buffer(1e-6).covers(
        event_unit.unit_context.representative_node.geometry
    )
    assert event_unit.pair_local_middle_geometry is not None
    assert float(event_unit.selected_candidate_region_geometry.area) == pytest.approx(
        float(event_unit.pair_local_middle_geometry.area),
        abs=1e-3,
    )
    _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])


def test_real_case_17943587_pair_space_stays_on_boundary_pair_without_reverse_backtrace() -> None:
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["17943587"],
    )
    case_result = build_case_result(load_case_bundle(specs[0]))
    event_units = {item.spec.event_unit_id: item for item in case_result.event_units}

    for unit_id in ("node_17943587", "node_55353233", "node_55353248"):
        event_unit = event_units[unit_id]
        assert set(event_unit.unit_envelope.event_branch_ids) == set(event_unit.unit_envelope.boundary_branch_ids)
        _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])
        expected_pair_signature = _stable_boundary_pair_signature(
            event_unit.unit_envelope.branch_road_memberships,
            event_unit.unit_envelope.boundary_branch_ids,
        )
        assert event_unit.pair_local_summary["boundary_pair_signature"] == expected_pair_signature
        assert event_unit.selected_candidate_summary["upper_evidence_object_id"] == (
            f"{unit_id}:{expected_pair_signature}"
        )
        assert event_unit.selected_candidate_region_geometry is not None
        assert event_unit.selected_candidate_region_geometry.buffer(1e-6).covers(
            event_unit.unit_context.representative_node.geometry
        )
        if unit_id == "node_55353248":
            assert event_unit.pair_local_summary["pair_scan_truncated_to_local"] is True
            assert max(float(item) for item in event_unit.pair_local_summary["valid_scan_offsets_m"]) >= 96.0

    sibling_unit = event_units["node_55353233"]
    sibling_branch_road_memberships = sibling_unit.unit_envelope.branch_road_memberships
    sibling_merge_branch = _find_branch_id_with_required_roads(
        sibling_branch_road_memberships,
        {"502953712", "41727506", "620950831"},
    )
    assert set(sibling_branch_road_memberships[sibling_merge_branch]) == {
        "502953712",
        "41727506",
        "620950831",
    }
    assert "605949403" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    assert "607962170" not in set(sibling_branch_road_memberships[sibling_merge_branch])
    assert max(float(item) for item in sibling_unit.pair_local_summary["valid_scan_offsets_m"]) >= 96.0
