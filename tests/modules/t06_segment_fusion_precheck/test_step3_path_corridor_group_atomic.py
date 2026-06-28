from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step3_segment_replacement


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _road(road_id: str, snode: str, enode: str, coords: list[tuple[float, float]], *, segmentid: str) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": 0, "segmentid": segmentid},
        "geometry": LineString(coords),
    }


def _rcsd_road(road_id: str, snode: str, enode: str, coords: list[tuple[float, float]]) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": 0},
        "geometry": LineString(coords),
    }


def _node(node_id: str, x: float) -> dict:
    return {
        "properties": {"id": node_id, "mainnodeid": node_id, "kind": 0, "grade": 0, "kind_2": 0, "grade_2": 0},
        "geometry": Point(x, 0),
    }


def _props(path: Path) -> list[dict]:
    return [item["properties"] for item in json.loads(path.with_suffix(".json").read_text())["features"]]


def _write_common_inputs(tmp_path: Path, *, covered: bool) -> tuple[Path, Path, Path, Path, Path, Path]:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_src", "sgrade": "0-0双", "pair_nodes": ["a", "b"], "junc_nodes": [], "roads": ["sw_src"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {"id": "s_peer", "sgrade": "0-0双", "pair_nodes": ["b", "c"], "junc_nodes": [], "roads": ["sw_peer"]},
                "geometry": LineString([(20, 0), (100, 0)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("sw_src", "a", "b", [(0, 0), (100, 0)], segmentid="s_src"),
            _road("sw_peer", "b", "c", [(20, 0), (100, 0)], segmentid="s_peer"),
        ],
    )
    swsd_nodes = _write(tmp_path / "swsd_nodes.gpkg", [_node("a", 0), _node("b", 100), _node("c", 120)])
    rcsd_road_features = [_rcsd_road("rr1", "r1", "r2", [(0, 0), (20, 0)])]
    if covered:
        rcsd_road_features.append(_rcsd_road("rr2", "r2", "r3", [(20, 0), (100, 0)]))
    rcsd_roads = _write(tmp_path / "rcsdroad_out.gpkg", rcsd_road_features)
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node("r1", 0), _node("r2", 20), _node("r3", 100)])
    replaceable = _write(tmp_path / "t06_rcsd_segment_replaceable.gpkg", [])
    return segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable


def _write_group_plan(
    tmp_path: Path,
    road_ids: list[str],
    *,
    group_segment_ids: list[str] | None = None,
    extra_features: list[dict] | None = None,
    extra_props: dict | None = None,
) -> None:
    group_feature = {
        "properties": {
            "replacement_plan_id": "group_path_corridor:s_src",
            "swsd_segment_id": "s_src",
            "plan_status": "ready",
            "execution_action": "replace",
            "execution_scope": "path_corridor_group",
            "group_segment_ids": group_segment_ids or ["s_src", "s_peer"],
            "source_segment_ids": ["s_src"],
            "rcsd_road_ids": road_ids,
            "retained_node_ids": ["r1", "r2", "r3"],
            "rcsd_pair_nodes": ["r1", "r3"],
            "buffer_distances_m": [5.0],
            **(extra_props or {}),
        },
        "geometry": LineString([(0, 0), (100, 0)]),
    }
    _write(
        tmp_path / "t06_segment_replacement_plan.gpkg",
        [*(extra_features or []), group_feature],
    )


def test_path_corridor_group_source_keeps_full_group_corridor(tmp_path: Path) -> None:
    segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable = _write_common_inputs(tmp_path, covered=True)
    _write_group_plan(tmp_path, ["rr1", "rr2"])

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    units = {item["swsd_segment_id"]: item for item in _props(artifacts.replacement_units_gpkg_path)}
    assert units["s_src"]["unit_status"] == "passed"
    assert units["s_src"]["unit_reason"] == "group_path_corridor_replacement"
    assert units["s_src"]["rcsd_road_ids"] == ["rr1", "rr2"]
    assert units["s_src"]["retained_detached_swsd_road_ids"] == []

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_src"]["relation_status"] == "replaced"
    assert relations["s_src"]["relation_reason"] == "group_path_corridor_replacement"
    assert "group_path_corridor_replacement" in relations["s_src"]["risk_flags"]
    assert relations["s_src"]["group_replacement_segment_ids"] == ["s_src", "s_peer"]


def test_path_corridor_group_member_inherits_pair_nodes_from_blocked_standard_plan(tmp_path: Path) -> None:
    segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable = _write_common_inputs(tmp_path, covered=True)
    _write_group_plan(
        tmp_path,
        ["rr1", "rr2"],
        group_segment_ids=["s_peer"],
        extra_features=[
            {
                "properties": {
                    "replacement_plan_id": "standard:s_peer",
                    "swsd_segment_id": "s_peer",
                    "plan_status": "blocked",
                    "execution_action": "hold",
                    "execution_scope": "standard_segment",
                    "rcsd_pair_nodes": ["r2", "r3"],
                    "rcsd_junc_nodes": ["r2"],
                },
                "geometry": LineString([(20, 0), (100, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    units = {item["swsd_segment_id"]: item for item in _props(artifacts.replacement_units_gpkg_path)}
    assert units["s_peer"]["unit_status"] == "passed"
    assert units["s_peer"]["unit_reason"] == "group_path_corridor_replacement"
    assert units["s_peer"]["rcsd_pair_nodes"] == ["r2", "r3"]
    assert units["s_peer"]["rcsd_junc_nodes"] == ["r2"]


def test_path_corridor_group_source_not_replaced_when_group_ids_omit_source(tmp_path: Path) -> None:
    segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable = _write_common_inputs(tmp_path, covered=True)
    _write_group_plan(tmp_path, ["rr1", "rr2"], group_segment_ids=["s_peer"])

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    units = {item["swsd_segment_id"]: item for item in _props(artifacts.replacement_units_gpkg_path)}
    assert "s_src" not in units
    assert units["s_peer"]["unit_status"] == "passed"
    assert units["s_peer"]["unit_reason"] == "group_path_corridor_replacement"

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_src"]["relation_status"] == "retained_swsd"
    assert relations["s_src"]["group_replacement_segment_ids"] == []
    assert relations["s_peer"]["relation_status"] == "replaced"
    assert relations["s_peer"]["group_replacement_segment_ids"] == ["s_peer"]


def test_blocked_path_corridor_group_does_not_deactivate_standard_member(tmp_path: Path) -> None:
    segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable = _write_common_inputs(tmp_path, covered=True)
    _write_group_plan(
        tmp_path,
        ["rr1", "rr2"],
        group_segment_ids=["s_peer"],
        extra_props={
            "plan_status": "blocked",
            "execution_action": "hold",
            "source_reason": "path_corridor_source_segment_blocked",
            "risk_flags": ["group_path_corridor_replacement", "path_corridor_source_segment_blocked"],
        },
        extra_features=[
            {
                "properties": {
                    "replacement_plan_id": "standard:s_peer",
                    "swsd_segment_id": "s_peer",
                    "plan_status": "ready",
                    "execution_action": "replace",
                    "execution_scope": "standard_segment",
                    "swsd_pair_nodes": ["b", "c"],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": ["r2", "r3"],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr2"],
                    "retained_node_ids": ["r2", "r3"],
                },
                "geometry": LineString([(20, 0), (100, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    units = {item["swsd_segment_id"]: item for item in _props(artifacts.replacement_units_gpkg_path)}
    assert "s_src" not in units
    assert units["s_peer"]["unit_status"] == "passed"
    assert units["s_peer"]["unit_reason"] == "replaceable"

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_src"]["relation_status"] == "retained_swsd"
    assert relations["s_peer"]["relation_status"] == "replaced"
    assert relations["s_peer"]["relation_reason"] == "replacement_unit_passed"
    assert relations["s_peer"]["group_replacement_plan_ids"] == []


def test_path_corridor_group_source_not_replaced_when_junction_mapping_missing(tmp_path: Path) -> None:
    segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable = _write_common_inputs(tmp_path, covered=True)
    _write_group_plan(
        tmp_path,
        ["rr1", "rr2"],
        group_segment_ids=["s_peer"],
        extra_props={"swsd_junc_nodes": ["j_missing"], "optional_junc_nodes": [], "optional_junc_rcsd_nodes": []},
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    units = {item["swsd_segment_id"]: item for item in _props(artifacts.replacement_units_gpkg_path)}
    assert "s_src" not in units
    assert units["s_peer"]["unit_status"] == "passed"

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_src"]["relation_status"] == "retained_swsd"
    assert relations["s_peer"]["relation_status"] == "replaced"


def test_path_corridor_group_coverage_failure_keeps_group_for_manual_review(tmp_path: Path) -> None:
    segment, swsd_roads, swsd_nodes, rcsd_roads, rcsd_nodes, replaceable = _write_common_inputs(tmp_path, covered=False)
    _write_group_plan(tmp_path, ["rr1"])

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    units = {item["swsd_segment_id"]: item for item in _props(artifacts.replacement_units_gpkg_path)}
    assert units["s_src"]["unit_status"] == "passed"
    assert units["s_peer"]["unit_status"] == "passed"
    assert units["s_src"]["unit_reason"] == "group_path_corridor_replacement"
    assert units["s_peer"]["unit_reason"] == "group_path_corridor_replacement"

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_src"]["relation_status"] == "replaced"
    assert relations["s_peer"]["relation_status"] == "replaced"
    assert relations["s_peer"]["relation_reason"] == "group_path_corridor_replacement"
    assert "group_path_corridor_replacement" in relations["s_peer"]["risk_flags"]
