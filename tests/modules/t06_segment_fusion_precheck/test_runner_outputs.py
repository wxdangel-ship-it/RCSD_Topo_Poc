from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_segment_fusion_precheck, run_t06_step2_extract_rcsd_segments


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
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr-unused", "snodeid": 30, "enodeid": 40, "direction": 0}, "geometry": LineString([(10, 0), (12, 0)])},
        ],
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
    assert artifacts.step1.stats_csv_path is not None
    assert artifacts.step1.stats_csv_path.exists()
    assert artifacts.step1.fusion_units_gpkg_path == artifacts.step1.final_fusion_units_gpkg_path
    assert artifacts.step2.candidates_gpkg_path.exists()
    assert artifacts.step2.replaceable_gpkg_path.exists()
    assert artifacts.step2.rejected_gpkg_path.exists()
    step1_summary = json.loads(artifacts.step1.summary_path.read_text(encoding="utf-8"))
    assert Path(step1_summary["outputs"]["swsd_candidates_json"]).exists()
    assert Path(step1_summary["outputs"]["swsd_final_fusion_units_json"]).exists()
    assert Path(step1_summary["outputs"]["segment_stats_csv"]).exists()
    assert "evd_candidates_json" not in step1_summary["outputs"]
    assert "fusion_units_json" not in step1_summary["outputs"]
    summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert summary["input_fusion_unit_count"] == 1
    assert summary["replaceable_count"] == 1
    assert summary["buffer_segment_count"] == 1
    assert summary["rcsd_road_total_count"] == 2
    assert summary["rcsd_road_total_length_m"] == 3.0
    assert summary["replaceable_rcsd_road_unique_count"] == 1
    assert summary["replaceable_rcsd_road_unique_length_m"] == 1.0
    assert summary["replaceable_rcsd_road_reference_count"] == 1
    assert summary["replaceable_rcsd_road_reference_length_m"] == 1.0
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


def test_step2_runner_uses_swsd_road_direction_for_single_segments(tmp_path: Path) -> None:
    segments = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_forward", "sgrade": "主单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_forward"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"id": "s_reverse", "sgrade": "主单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_reverse"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_forward", "sgrade": "主单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_forward"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"swsd_segment_id": "s_reverse", "sgrade": "主单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_reverse"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("sr_forward", 1, 2, 2),
            _road("sr_reverse", 2, 1, 2),
        ],
    )
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
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(50, 0)},
            {"properties": {"id": 40, "mainnodeid": 0}, "geometry": Point(50, 2)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "forward_a", "snodeid": 10, "enodeid": 30, "direction": 2}, "geometry": LineString([(0, 0), (50, 0)])},
            {"properties": {"id": "forward_b", "snodeid": 30, "enodeid": 20, "direction": 2}, "geometry": LineString([(50, 0), (100, 0)])},
            {"properties": {"id": "reverse_a", "snodeid": 20, "enodeid": 40, "direction": 2}, "geometry": LineString([(100, 2), (50, 2)])},
            {"properties": {"id": "reverse_b", "snodeid": 40, "enodeid": 10, "direction": 2}, "geometry": LineString([(50, 2), (0, 2)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segments,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    payload = json.loads(artifacts.replaceable_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    by_segment = {feature["properties"]["swsd_segment_id"]: feature["properties"] for feature in payload["features"]}
    assert by_segment["s_forward"]["directed_swsd_pair_nodes"] == ["1", "2"]
    assert by_segment["s_forward"]["directed_rcsd_pair_nodes"] == ["10", "20"]
    assert set(by_segment["s_forward"]["rcsd_road_ids"]) == {"forward_a", "forward_b"}
    assert by_segment["s_reverse"]["directed_swsd_pair_nodes"] == ["2", "1"]
    assert by_segment["s_reverse"]["directed_rcsd_pair_nodes"] == ["20", "10"]
    assert set(by_segment["s_reverse"]["rcsd_road_ids"]) == {"reverse_a", "reverse_b"}


def test_step2_blocks_whole_special_junction_group_when_one_segment_is_not_replaceable(tmp_path: Path) -> None:
    segments = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_ok", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr_ok"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"id": "s_fail", "sgrade": "主双", "pair_nodes": [4, 5], "junc_nodes": [3], "roads": ["sr_fail"]},
                "geometry": LineString([(0, 5), (100, 5)]),
            },
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_ok", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr_ok"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"swsd_segment_id": "s_fail", "sgrade": "主双", "pair_nodes": [4, 5], "junc_nodes": [3], "roads": ["sr_fail"]},
                "geometry": LineString([(0, 5), (100, 5)]),
            },
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "kind_2": 64}, "geometry": Point(50, 0)},
            {"properties": {"id": 4, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 5)},
            {"properties": {"id": 5, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 5)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [_road("sr_ok", 1, 2, 0), _road("sr_fail", 4, 5, 0)],
    )
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
            {"properties": {"target_id": 3, "base_id": 30, "status": 0}, "geometry": Point(50, 0)},
            {"properties": {"target_id": 4, "base_id": 40, "status": 0}, "geometry": Point(0, 5)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 30, "mainnodeid": 30, "subnodeid": [31, 32]}, "geometry": Point(50, 0)},
            {"properties": {"id": 31, "mainnodeid": 30}, "geometry": Point(45, 0)},
            {"properties": {"id": 32, "mainnodeid": 30}, "geometry": Point(55, 0)},
            {"properties": {"id": 40, "mainnodeid": 0}, "geometry": Point(0, 5)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_a", "snodeid": 10, "enodeid": 31, "direction": 0}, "geometry": LineString([(0, 0), (45, 0)])},
            {"properties": {"id": "rr_b", "snodeid": 32, "enodeid": 20, "direction": 0}, "geometry": LineString([(55, 0), (100, 0)])},
            {"properties": {"id": "rr_internal", "snodeid": 31, "enodeid": 32, "direction": 0}, "geometry": LineString([(45, 0), (55, 0)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segments,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["rcsd_candidate_count"] == 1
    assert summary["replaceable_count"] == 0
    assert summary["special_junction_group_blocked_count"] == 1
    assert summary["special_junction_gate_removed_replaceable_count"] == 1
    assert summary["reject_reason_counts"]["missing_pair_relation"] == 1
    assert summary["reject_reason_counts"]["special_junction_group_not_fully_replaceable"] == 1

    replaceable_payload = json.loads(artifacts.replaceable_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert replaceable_payload["row_count"] == 0

    candidate_payload = json.loads(artifacts.candidates_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    candidate_props = candidate_payload["features"][0]["properties"]
    assert candidate_props["swsd_segment_id"] == "s_ok"
    assert candidate_props["special_junction_group_ids"] == ["3"]
    assert candidate_props["special_junction_gate_status"] == "blocked"

    group_audit = json.loads(
        (artifacts.summary_path.parent / "t06_special_junction_group_audit.json").read_text(encoding="utf-8")
    )
    group_props = group_audit["features"][0]["properties"]
    assert group_props["special_junction_id"] == "3"
    assert group_props["special_junction_type"] == "roundabout"
    assert group_props["gate_status"] == "blocked"
    assert group_props["associated_segment_ids"] == ["s_ok", "s_fail"]
    assert group_props["missing_replaceable_segment_ids"] == ["s_fail"]
    assert group_props["removed_replaceable_segment_ids"] == ["s_ok"]
    assert group_props["rcsd_junction_node_ids"] == ["30", "31", "32"]
    assert group_props["rcsd_junction_road_ids"] == ["rr_internal"]


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
