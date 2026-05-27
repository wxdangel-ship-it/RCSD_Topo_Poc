from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_segment_fusion_precheck


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _road(road_id: str, snode: int, enode: int, direction: int, **props):
    payload = {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": direction}
    payload.update(props)
    return {"properties": payload, "geometry": LineString([(snode, 0), (enode, 0)])}


def test_combined_runner_outputs_all_files_and_keeps_inputs_readonly(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(1, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(2, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0, "level": 1, "is_highway": 0}, "geometry": Point(1, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0, "level": 1, "is_highway": 0}, "geometry": Point(2, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(2, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in [segment, nodes, swsd_roads, relation, rcsd_nodes, rcsd_roads]}

    artifacts = run_t06_segment_fusion_precheck(
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in [segment, nodes, swsd_roads, relation, rcsd_nodes, rcsd_roads]}
    assert after == before
    assert artifacts.step1.fusion_units_gpkg_path.exists()
    assert artifacts.step1.swsd_candidates_gpkg_path is not None
    assert artifacts.step1.swsd_candidates_gpkg_path.exists()
    assert artifacts.step1.final_fusion_units_gpkg_path is not None
    assert artifacts.step1.final_fusion_units_gpkg_path.exists()
    assert artifacts.step2.candidates_gpkg_path.exists()
    assert artifacts.step2.replaceable_gpkg_path.exists()
    assert artifacts.step2.rejected_gpkg_path.exists()
    step1_summary = json.loads(artifacts.step1.summary_path.read_text(encoding="utf-8"))
    assert Path(step1_summary["outputs"]["swsd_candidates_json"]).exists()
    assert Path(step1_summary["outputs"]["swsd_final_fusion_units_json"]).exists()
    summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert summary["input_fusion_unit_count"] == 1
    assert summary["replaceable_count"] == 1
    assert summary["buffer_segment_count"] == 1
    assert Path(summary["outputs"]["buffer_segments_json"]).exists()


def test_step2_runner_canonicalizes_rcsd_subnode_road_endpoints(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 10, "subnodeid": [101]}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 20, "subnodeid": []}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 101, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])},
        ],
    )

    artifacts = run_t06_segment_fusion_precheck(
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["buffer_segment_count"] == 1

    candidate_payload = json.loads(artifacts.step2.candidates_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    candidate_props = candidate_payload["features"][0]["properties"]
    assert candidate_props["candidate_strategy"] == "buffer_segment_extraction"
    assert candidate_props["retained_node_ids"] == ["10", "20"]
    assert candidate_props["retained_rcsd_road_ids"] == ["rr1"]


def test_step2_runner_excludes_advance_right_turn_from_rcsd_candidate_graph(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
            [
                {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
                {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(50, 0)},
                {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
                {"properties": {"id": 99, "mainnodeid": 0}, "geometry": Point(0, 20)},
            ],
        )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
                {"properties": {"id": "main_a", "snodeid": 10, "enodeid": 30, "direction": 0}, "geometry": LineString([(0, 0), (50, 0)])},
                {"properties": {"id": "main_b", "snodeid": 30, "enodeid": 20, "direction": 0}, "geometry": LineString([(50, 0), (100, 0)])},
                {"properties": {"id": "advance_right", "snodeid": 10, "enodeid": 99, "direction": 0, "formway": 129}, "geometry": LineString([(0, 0), (0, 20)])},
            ],
        )

    artifacts = run_t06_segment_fusion_precheck(
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["deprecated_pair_path_search_enabled"] is False
    assert summary["buffer_excluded_advance_right_turn_road_count_total"] == 1

    candidate_payload = json.loads(artifacts.step2.candidates_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    candidate_props = candidate_payload["features"][0]["properties"]
    assert candidate_props["retained_rcsd_road_ids"] == ["main_a", "main_b"]


def test_step2_skips_junc_kind2_exempt_nodes_when_mapping_relations(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3, 5, 4], "roads": ["sr1"]},
                "geometry": LineString([(1, 0), (6, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(1, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(2, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "no", "kind_2": 1}, "geometry": Point(3, 0)},
            {"properties": {"id": 5, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "no", "kind_2": 4096}, "geometry": Point(5, 0)},
            {"properties": {"id": 4, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 2048}, "geometry": Point(4, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0, "level": 1, "is_highway": 0}, "geometry": Point(1, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0, "level": 1, "is_highway": 0}, "geometry": Point(2, 0)},
            {"properties": {"target_id": 5, "base_id": 30, "status": 0, "level": 1, "is_highway": 0}, "geometry": Point(5, 0)},
            {"properties": {"target_id": 4, "base_id": 40, "status": 0, "level": 1, "is_highway": 0}, "geometry": Point(4, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(2, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(5, 0)},
            {"properties": {"id": 40, "mainnodeid": 0}, "geometry": Point(4, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 30, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr2", "snodeid": 30, "enodeid": 40, "direction": 0}, "geometry": LineString([(2, 0), (4, 0)])},
            {"properties": {"id": "rr3", "snodeid": 40, "enodeid": 20, "direction": 0}, "geometry": LineString([(4, 0), (6, 0)])},
        ],
    )

    artifacts = run_t06_segment_fusion_precheck(
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["reject_reason_counts"] == {}

    candidate_payload = json.loads(artifacts.step2.candidates_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    candidate_props = candidate_payload["features"][0]["properties"]
    assert candidate_props["swsd_junc_nodes"] == ["3", "5", "4"]
    assert candidate_props["junc_kind2_exempt_nodes"] == ["3", "5"]
    assert candidate_props["rcsd_junc_nodes"] == ["40"]
