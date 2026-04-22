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
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.rcsd_selection import (
    _normalize_geometry,
    _union_geometry,
    resolve_positive_rcsd_selection,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    ParsedNode,
    ParsedRoad,
)


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


def _assert_selected_candidate_region_is_pair_local_container(event_unit) -> None:
    assert event_unit.selected_candidate_region_geometry is not None
    assert event_unit.pair_local_region_geometry is not None
    assert event_unit.selected_candidate_region == event_unit.pair_local_summary["region_id"]
    assert event_unit.selected_candidate_region_geometry.buffer(1e-6).covers(
        event_unit.unit_context.representative_node.geometry
    )
    assert float(event_unit.selected_candidate_region_geometry.area) == pytest.approx(
        float(event_unit.pair_local_region_geometry.area),
        abs=1e-3,
    )


def _parsed_node(
    node_id: str,
    x: float,
    y: float,
    *,
    mainnodeid: str | None = None,
    has_evd: str | None = "no",
    is_anchor: str | None = "no",
    kind_2: int | None = 0,
    grade_2: int | None = 0,
) -> ParsedNode:
    return ParsedNode(
        feature_index=0,
        properties={"id": node_id, "mainnodeid": mainnodeid},
        geometry=Point(x, y),
        node_id=str(node_id),
        mainnodeid=None if mainnodeid is None else str(mainnodeid),
        has_evd=has_evd,
        is_anchor=is_anchor,
        kind_2=kind_2,
        grade_2=grade_2,
        kind=None,
    )


def _parsed_road(
    road_id: str,
    coords: list[tuple[float, float]],
    *,
    snodeid: str,
    enodeid: str,
    direction: int = 2,
) -> ParsedRoad:
    return ParsedRoad(
        feature_index=0,
        properties={"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": direction},
        geometry=LineString(coords),
        road_id=str(road_id),
        snodeid=str(snodeid),
        enodeid=str(enodeid),
        direction=direction,
    )


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


def _build_pair_local_empty_rcsd_case_package(case_dir: Path) -> None:
    _build_synthetic_case_package(case_dir)
    write_vector(
        case_dir / "rcsdroad.gpkg",
        [
            {
                "properties": {"id": 21, "snodeid": 9101, "enodeid": 9102, "direction": 2},
                "geometry": LineString([(-68, 34), (-56, 38)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "rcsdnode.gpkg",
        [
            {
                "properties": {"id": 9101, "mainnodeid": 9999},
                "geometry": Point(-68, 34),
            },
            {
                "properties": {"id": 9102, "mainnodeid": 9999},
                "geometry": Point(-56, 38),
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


__all__ = [name for name in globals() if not name.startswith("__")]
