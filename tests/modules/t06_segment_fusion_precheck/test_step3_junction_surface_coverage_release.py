from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step3_segment_replacement


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _node(node_id: int, x: float) -> dict:
    return {"properties": {"id": node_id, "mainnodeid": node_id}, "geometry": Point(x, 0)}


def _run_case(tmp_path: Path, *, with_surface: bool, risk_flags: list[str] | None = None):
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {
                "properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0, "segmentid": "s1"},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    swsd_nodes = _write(tmp_path / "swsd_nodes.gpkg", [_node(1, 0), _node(2, 100)])
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {
                "properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0},
                "geometry": LineString([(0, 0), (60, 0)]),
            }
        ],
    )
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 0), _node(20, 60)])
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                    "risk_flags": risk_flags or [],
                },
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    surface = None
    if with_surface:
        surface = _write(
            tmp_path / "junction_anchor_surface.gpkg",
            [
                {
                    "properties": {"surface_id": "JAS:2", "mainnodeid": 2, "junction_type": "rcsd_intersection"},
                    "geometry": Polygon([(75, -10), (110, -10), (110, 10), (75, 10)]),
                }
            ],
        )
    return run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
        junction_surface_path=surface,
    )


def _rows(path: Path) -> list[dict]:
    payload = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return [item["properties"] for item in payload["features"]]


def test_step3_releases_formal_corridor_gap_inside_anchored_junction_surface(tmp_path: Path) -> None:
    artifacts = _run_case(tmp_path, with_surface=True)

    [unit] = _rows(artifacts.replacement_units_gpkg_path)
    [relation] = _rows(artifacts.swsd_frcsd_segment_relation_gpkg_path)

    assert unit["unit_status"] == "passed"
    assert unit["retained_detached_swsd_road_ids"] == []
    assert relation["relation_status"] == "replaced"
    assert relation["frcsd_road_ids"] == ["rr1"]
    assert "junction_surface_coverage_release" in relation["risk_flags"]
    assert "manual_review_required" in relation["risk_flags"]


def test_step3_records_formal_corridor_gap_without_junction_surface_as_review_risk(tmp_path: Path) -> None:
    artifacts = _run_case(tmp_path, with_surface=False)

    [unit] = _rows(artifacts.replacement_units_gpkg_path)
    [relation] = _rows(artifacts.swsd_frcsd_segment_relation_gpkg_path)

    assert unit["unit_status"] == "failed"
    assert unit["unit_reason"] == "retained_swsd_not_attached_side_road_only"
    assert relation["relation_status"] == "failed"
    assert "formal_replacement_corridor_coverage_review" in relation["risk_flags"]
    assert "formal_replacement_corridor_coverage_unavailable" in relation["risk_flags"]
    assert "manual_review_required" in relation["risk_flags"]


def test_step3_releases_buffer_corridor_controlled_gap_without_junction_surface(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        with_surface=False,
        risk_flags=[
            "swsd_buffer_corridor_controlled_release",
            "swsd_geometry_not_covered_by_retained_rcsd",
            "manual_review_required",
        ],
    )

    [unit] = _rows(artifacts.replacement_units_gpkg_path)
    [relation] = _rows(artifacts.swsd_frcsd_segment_relation_gpkg_path)

    assert unit["unit_status"] == "passed"
    assert unit["retained_detached_swsd_road_ids"] == []
    assert relation["relation_status"] == "replaced"
    assert "swsd_buffer_corridor_controlled_release" in relation["risk_flags"]
    assert "manual_review_required" in relation["risk_flags"]


def test_step3_releases_visual_consistency_controlled_gap_without_junction_surface(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        with_surface=False,
        risk_flags=[
            "visual_consistency_controlled_release",
            "manual_review_required",
            "no_formal_trunk_road_conflict",
        ],
    )

    [unit] = _rows(artifacts.replacement_units_gpkg_path)
    [relation] = _rows(artifacts.swsd_frcsd_segment_relation_gpkg_path)

    assert unit["unit_status"] == "failed"
    assert unit["unit_reason"] == "retained_swsd_not_attached_side_road_only"
    assert relation["relation_status"] == "failed"
    assert "visual_consistency_controlled_release" in relation["risk_flags"]
    assert "manual_review_required" in relation["risk_flags"]
