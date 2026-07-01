from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_segment_fusion_precheck,
    run_t06_step1_identify_fusion_units,
    run_t06_step2_extract_rcsd_segments,
)


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


def test_step1_excludes_self_pair_segments_from_step2_fusion_units(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_main", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_main"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "s_self", "sgrade": "0-2单", "pair_nodes": [3, 3], "junc_nodes": [], "roads": ["sr_self"]},
                "geometry": LineString([(3, 0), (4, 0)]),
            },
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(1, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(2, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes"}, "geometry": Point(3, 0)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("sr_main", 1, 2, 0),
            _road("sr_self", 3, 3, 2),
        ],
    )
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(1, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(2, 0)},
            {"properties": {"target_id": 3, "base_id": 30, "status": 0}, "geometry": Point(3, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(1, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(2, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(3, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
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

    step1_summary = json.loads(artifacts.step1.summary_path.read_text(encoding="utf-8"))
    assert step1_summary["final_fusion_unit_count"] == 1
    assert step1_summary["reject_reason_counts"] == {"swsd_pair_nodes_not_distinct": 1}

    final_units = json.loads(artifacts.step1.final_fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert [item["properties"]["swsd_segment_id"] for item in final_units["features"]] == ["s_main"]

    rejected = json.loads(artifacts.step1.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_props = rejected["features"][0]["properties"]
    assert rejected_props["swsd_segment_id"] == "s_self"
    assert rejected_props["reject_stage"] == "before_evd"
    assert rejected_props["reject_reason"] == "swsd_pair_nodes_not_distinct"

    step2_summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert step2_summary["input_fusion_unit_count"] == 1
    assert step2_summary["replaceable_count"] == 1
    assert step2_summary["rejected_count"] == 0


def test_step1_allows_high_grade_deferred_anchor_nodes_for_step2_probe(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_high", "sgrade": "0-1双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"id": "s_low", "sgrade": "2-0双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "no", "kind_2": 2048}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(100, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "no", "kind_2": 16}, "geometry": Point(50, 0)},
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment,
        swsd_nodes_path=nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["evd_candidate_count"] == 2
    assert summary["final_fusion_unit_count"] == 1
    final_units = json.loads(artifacts.final_fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    final_props = final_units["features"][0]["properties"]
    assert final_props["swsd_segment_id"] == "s_high"
    assert final_props["junc_kind2_exempt_nodes"] == []
    rejected = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_props = rejected["features"][0]["properties"]
    assert rejected_props["swsd_segment_id"] == "s_low"
    assert rejected_props["reject_reason"] == "is_anchor_not_eligible"


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


def test_step2_special_junction_gate_ignores_self_pair_internal_segments(tmp_path: Path) -> None:
    segments = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_main", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr_main"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"id": "s_self", "sgrade": "主单", "pair_nodes": [3, 3], "junc_nodes": [], "roads": ["sr_self"]},
                "geometry": LineString([(50, 0), (55, 0)]),
            },
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_main", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr_main"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "properties": {"swsd_segment_id": "s_self", "sgrade": "主单", "pair_nodes": [3, 3], "junc_nodes": [], "roads": ["sr_self"]},
                "geometry": LineString([(50, 0), (55, 0)]),
            },
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(100, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 128}, "geometry": Point(50, 0)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("sr_main", 1, 2, 0),
            _road("sr_self", 3, 3, 0),
        ],
    )
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
            {"properties": {"target_id": 3, "base_id": 30, "status": 0}, "geometry": Point(50, 0)},
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

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["reject_reason_counts"] == {"swsd_pair_nodes_not_distinct": 1}

    replaceable_payload = json.loads(artifacts.replaceable_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    replaceable_props = replaceable_payload["features"][0]["properties"]
    assert replaceable_props["swsd_segment_id"] == "s_main"
    assert replaceable_props["special_junction_group_ids"] == ["3"]
    assert replaceable_props["special_junction_gate_status"] == "passed"


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


def test_step2_rejects_swsd_pair_nodes_that_are_not_distinct(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_loop", "sgrade": "主单", "pair_nodes": [1, 1], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_loop", "sgrade": "主单", "pair_nodes": [1, 1], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [{"properties": {"id": 1, "mainnodeid": 0, "has_evd": "yes", "is_anchor": "yes", "kind_2": 4}, "geometry": Point(0, 0)}],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 1, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
        ],
    )
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [{"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)}])
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr_far", "snodeid": 30, "enodeid": 40, "direction": 0}, "geometry": LineString([(1000, 0), (1010, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    props = payload["features"][0]["properties"]
    assert props["reject_reason"] == "swsd_pair_nodes_not_distinct"
    assert props["swsd_sgrade"] == "主单"
    assert props["swsd_directionality"] == "single"


def test_step2_rejects_rcsd_pair_nodes_that_collapse_to_one_semantic_node(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_collapse", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_collapse", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
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
            {"properties": {"target_id": 2, "base_id": 11, "status": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 100}, "geometry": Point(0, 0)},
            {"properties": {"id": 11, "mainnodeid": 100}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 11, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    props = payload["features"][0]["properties"]
    assert props["reject_reason"] == "rcsd_pair_nodes_not_distinct"
    assert props["failed_metric_value"]["canonical_rcsd_pair_nodes"] == ["100"]


def test_step2_missing_junc_relation_is_optional_and_audited_as_auto_lift(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_junc", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_junc", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(50, 10)},
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
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["junc_required_blocked_count"] == 1
    assert summary["scenario_b_auto_lift_count"] == 1
    assert Path(summary["outputs"]["failure_business_audit_json"]).exists()

    replaceable_payload = json.loads(artifacts.replaceable_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    replaceable_props = replaceable_payload["features"][0]["properties"]
    assert replaceable_props["required_rcsd_nodes"] == ["10", "20"]
    assert replaceable_props["dropped_junc_nodes"] == ["3"]
    assert replaceable_props["junc_attach_loss_reason"] == "junc_relation_missing_or_invalid"

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["failure_business_category"] == "junc_required_blocked"
    assert audit_props["auto_fix_candidate"] is True


def test_step2_promotes_non_conflicting_isolated_attach_roads(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_attach", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_attach", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 20)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
            {"properties": {"target_id": 3, "base_id": 30, "status": 0}, "geometry": Point(0, 20)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(0, 20)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])},
            {"properties": {"id": "rr_attach", "snodeid": 10, "enodeid": 30, "direction": 0}, "geometry": LineString([(0, 0), (0, 20)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["isolated_attach_promoted_segment_count"] == 1
    assert summary["isolated_attach_promoted_road_unique_count"] == 1

    candidate = json.loads((artifacts.step_root / "t06_rcsd_segment_candidates.json").read_text(encoding="utf-8"))
    candidate_props = candidate["features"][0]["properties"]
    assert candidate_props["retained_rcsd_road_ids"] == ["rr_main"]
    assert candidate_props["lost_attach_road_ids"] == ["rr_attach"]
    assert candidate_props["promoted_attach_road_ids"] == ["rr_attach"]

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["rcsd_road_ids"] == ["rr_main", "rr_attach"]
    assert replaceable_props["attach_promotion_status"] == "promoted"
    assert replaceable_props["attach_promotion_reason"] == "global_unique_attach_roads"


def test_step2_blocks_isolated_attach_promotion_when_requested_by_multiple_segments(tmp_path: Path) -> None:
    segment_rows = [
        {
            "properties": {"id": segment_id, "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": [road_id]},
            "geometry": LineString([(0, 0), (100, 0)]),
        }
        for segment_id, road_id in (("s_a", "sr_a"), ("s_b", "sr_b"))
    ]
    segment = _write(tmp_path / "segment.gpkg", segment_rows)
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": row["properties"]["id"],
                    "sgrade": "主双",
                    "pair_nodes": [1, 2],
                    "junc_nodes": [3],
                    "roads": row["properties"]["roads"],
                },
                "geometry": row["geometry"],
            }
            for row in segment_rows
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
            {"properties": {"id": 3, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 20)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr_a", 1, 2, 0), _road("sr_b", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
            {"properties": {"target_id": 3, "base_id": 30, "status": 0}, "geometry": Point(0, 20)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(0, 20)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])},
            {"properties": {"id": "rr_attach", "snodeid": 10, "enodeid": 30, "direction": 0}, "geometry": LineString([(0, 0), (0, 20)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 2
    assert summary["isolated_attach_promoted_road_unique_count"] == 0
    assert summary["isolated_attach_blocked_road_unique_count"] == 1
    assert summary["isolated_attach_blocked_road_reference_count"] == 2

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    by_segment = {item["properties"]["swsd_segment_id"]: item["properties"] for item in replaceable["features"]}
    for props in by_segment.values():
        assert props["rcsd_road_ids"] == ["rr_main"]
        assert props["promoted_attach_road_ids"] == []
        assert props["blocked_attach_road_ids"] == ["rr_attach"]
        assert props["attach_promotion_status"] == "blocked_conflict"


def test_step2_pair_relation_failure_outputs_buffer_only_repair_candidate(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_pair", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_pair", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 0, "status": 1}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["repair_candidate_count"] == 1
    assert summary["pair_anchor_suspected_error_count"] == 1
    assert summary["pair_anchor_error_located_count"] == 1
    assert summary["scenario_b_auto_lift_count"] == 1
    assert summary["scenario_b_manual_review_count"] == 0
    assert Path(summary["outputs"]["buffer_only_probe_json"]).exists()
    assert Path(summary["outputs"]["repair_candidates_json"]).exists()

    probe = json.loads((artifacts.step_root / "t06_rcsd_buffer_only_probe.json").read_text(encoding="utf-8"))
    probe_props = probe["features"][0]["properties"]
    assert probe_props["buffer_only_candidate_status"] == "corridor_found"
    assert probe_props["failure_business_category"] == "pair_anchor_mismatch"

    repair = json.loads((artifacts.step_root / "t06_rcsd_repair_candidates.json").read_text(encoding="utf-8"))
    repair_props = repair["features"][0]["properties"]
    assert repair_props["candidate_rcsd_pair_node_sets"][0] == ["10", "20"]
    assert repair_props["manual_review_required"] is False
    assert repair_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert repair_props["pair_anchor_error_swsd_nodes"] == ["2"]
    assert repair_props["pair_anchor_error_original_rcsd_nodes"] == [""]
    assert repair_props["pair_anchor_error_candidate_rcsd_nodes"] == ["20"]

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["10"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_road_ids"] == ["rr1"]

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["reject_reason"] == "invalid_pair_relation_status"
    assert audit_props["auto_fix_candidate"] is True
    assert audit_props["manual_review_required"] is False
    assert audit_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert audit_props["original_rcsd_pair_nodes"] == ["10"]
    assert audit_props["rcsd_pair_nodes"] == ["10", "20"]
    assert audit_props["pair_anchor_error_swsd_nodes"] == ["2"]
    assert audit_props["pair_anchor_error_candidate_rcsd_nodes"] == ["20"]


def test_step2_autofills_fully_missing_pair_from_high_confidence_buffer_probe(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_pair", "sgrade": "0-1双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_pair", "sgrade": "0-1双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 2048}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 2048}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 0, "status": 1}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 0, "status": 1}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["scenario_b_auto_lift_count"] == 1

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == []
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_road_ids"] == ["rr1"]

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert audit_props["manual_review_required"] is False
    assert audit_props["pair_anchor_error_swsd_nodes"] == ["1", "2"]
    assert audit_props["pair_anchor_error_candidate_rcsd_nodes"] == ["10", "20"]


def test_step2_retries_high_confidence_candidate_anchor_mismatch(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 2)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 110, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 220, "status": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 110, "mainnodeid": 0}, "geometry": Point(-500, 0)},
            {"properties": {"id": 220, "mainnodeid": 0}, "geometry": Point(600, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["scenario_b_auto_lift_count"] == 1
    assert summary["scenario_b_manual_review_count"] == 0

    repair = json.loads((artifacts.step_root / "t06_rcsd_repair_candidates.json").read_text(encoding="utf-8"))
    repair_props = repair["features"][0]["properties"]
    assert repair_props["original_rcsd_pair_nodes"] == ["110", "220"]
    assert repair_props["candidate_rcsd_pair_node_sets"][0] == ["10", "20"]
    assert repair_props["pair_anchor_diagnostic_source"] == "buffer_only_candidate_pair"
    assert repair_props["pair_anchor_diagnostic_reason"] == "candidate_anchor_mismatch"

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["110", "220"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["directed_rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_road_ids"] == ["rr1"]

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["auto_fix_candidate"] is True
    assert audit_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert audit_props["pair_anchor_error_original_rcsd_nodes"] == ["110", "220"]
    assert audit_props["pair_anchor_error_candidate_rcsd_nodes"] == ["10", "20"]


def test_step2_retries_missing_pair_with_known_anchor_mismatch(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 2)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 110, "status": 0}, "geometry": Point(-500, 0)},
            {"properties": {"target_id": 2, "base_id": 0, "status": 1}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 110, "mainnodeid": 0}, "geometry": Point(-500, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["scenario_b_auto_lift_count"] == 1

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["110"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["directed_rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_road_ids"] == ["rr1"]

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert audit_props["manual_review_required"] is False
    assert audit_props["pair_anchor_error_swsd_nodes"] == ["1", "2"]
    assert audit_props["pair_anchor_error_original_rcsd_nodes"] == ["110", ""]
    assert audit_props["pair_anchor_error_candidate_rcsd_nodes"] == ["10", "20"]


def test_step2_formal_retry_reverses_single_candidate_pair_when_direction_requires(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 2)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 110, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 220, "status": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 110, "mainnodeid": 0}, "geometry": Point(0, 20)},
            {"properties": {"id": 111, "mainnodeid": 0}, "geometry": Point(0, 30)},
            {"properties": {"id": 220, "mainnodeid": 0}, "geometry": Point(100, 20)},
            {"properties": {"id": 221, "mainnodeid": 0}, "geometry": Point(100, 30)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_reverse", "snodeid": 20, "enodeid": 10, "direction": 2}, "geometry": LineString([(100, 0), (0, 0)])},
            {"properties": {"id": "rr_left_stub", "snodeid": 110, "enodeid": 111, "direction": 2}, "geometry": LineString([(0, 20), (0, 30)])},
            {"properties": {"id": "rr_right_stub", "snodeid": 220, "enodeid": 221, "direction": 2}, "geometry": LineString([(100, 20), (100, 30)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["scenario_b_auto_lift_count"] == 1

    repair = json.loads((artifacts.step_root / "t06_rcsd_repair_candidates.json").read_text(encoding="utf-8"))
    repair_props = repair["features"][0]["properties"]
    assert repair_props["candidate_rcsd_pair_node_sets"][0] == ["10", "20"]
    assert repair_props["pair_anchor_diagnostic_source"] == "buffer_only_candidate_pair"

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["110", "220"]
    assert replaceable_props["rcsd_pair_nodes"] == ["20", "10"]
    assert replaceable_props["directed_rcsd_pair_nodes"] == ["20", "10"]
    assert replaceable_props["rcsd_road_ids"] == ["rr_reverse"]

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert audit_props["manual_review_required"] is False


def test_step2_retries_single_endpoint_candidate_anchor_mismatch(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_pair", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 2)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 110, "status": 0}, "geometry": Point(0, 0)},
            {"properties": {"target_id": 2, "base_id": 20, "status": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 110, "mainnodeid": 0}, "geometry": Point(-500, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])}],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["scenario_b_auto_lift_count"] == 1

    repair = json.loads((artifacts.step_root / "t06_rcsd_repair_candidates.json").read_text(encoding="utf-8"))
    repair_props = repair["features"][0]["properties"]
    assert repair_props["original_rcsd_pair_nodes"] == ["110", "20"]
    assert repair_props["candidate_rcsd_pair_node_sets"] == [["10", "20"]]
    assert repair_props["pair_anchor_error_swsd_nodes"] == ["1"]
    assert repair_props["pair_anchor_error_original_rcsd_nodes"] == ["110"]
    assert repair_props["pair_anchor_error_candidate_rcsd_nodes"] == ["10"]

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["110", "20"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["directed_rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_road_ids"] == ["rr1"]


def test_step2_missing_pair_completion_preserves_known_side_for_single_segment(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_single", "sgrade": "主单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(100, 0), (0, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_single", "sgrade": "主单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(100, 0), (0, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 2)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [{"properties": {"target_id": 1, "base_id": 10, "status": 0}, "geometry": Point(0, 0)}],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(1000, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])},
            {"properties": {"id": "rr_side", "snodeid": 20, "enodeid": 30, "direction": 2}, "geometry": LineString([(100, 0), (1000, 0)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["scenario_b_auto_lift_count"] == 1

    repair = json.loads((artifacts.step_root / "t06_rcsd_repair_candidates.json").read_text(encoding="utf-8"))
    repair_props = repair["features"][0]["properties"]
    assert repair_props["manual_review_required"] is False
    assert repair_props["repair_recommendation"] == "side_preserving_missing_pair_anchor_completion"

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["10"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["directed_swsd_pair_nodes"] == ["1", "2"]
    assert replaceable_props["directed_rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_road_ids"] == ["rr1"]

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["auto_fix_candidate"] is True
    assert audit_props["manual_review_required"] is False
    assert audit_props["repair_recommendation"] == "side_preserving_missing_pair_anchor_completion"


def test_step2_high_grade_single_retries_graph_first_without_anchor_change(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_high_single", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_high_single", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 2)])
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
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 80)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 80)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["adaptive_high_grade_single_buffer_retry_count"] == 1

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["adaptive_buffer_status"] == "applied"
    assert replaceable_props["adaptive_buffer_distance_m"] == 75.0
    assert (
        replaceable_props["adaptive_buffer_source_reason"]
        == "single_graph_first_longitudinal_retry:retained_geometry_outside_swsd_buffer_scope"
    )

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["failure_business_category"] == "geometry_shape_mismatch"
    assert audit_props["auto_fix_candidate"] is True
    assert audit_props["manual_review_required"] is False
    assert audit_props["repair_recommendation"] == "single_graph_first_longitudinal_retry"


def test_step2_high_grade_dual_retries_adaptive_buffer_without_anchor_change(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_high_dual", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_high_dual", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
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
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_forward", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])},
            {"properties": {"id": "rr_reverse", "snodeid": 20, "enodeid": 10, "direction": 2}, "geometry": LineString([(100, 110), (0, 110)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["adaptive_high_grade_buffer_retry_count"] == 1
    assert summary["adaptive_high_grade_single_buffer_retry_count"] == 0
    assert summary["adaptive_high_grade_dual_buffer_retry_count"] == 1

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert replaceable_props["adaptive_buffer_status"] == "applied"
    assert replaceable_props["adaptive_buffer_distance_m"] == 125.0
    assert replaceable_props["adaptive_buffer_source_reason"] == "rcsd_not_bidirectional_for_swsd_dual"
    assert set(replaceable_props["rcsd_road_ids"]) == {"rr_forward", "rr_reverse"}

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["failure_business_category"] == "rcsd_graph_break_inside_buffer"
    assert audit_props["auto_fix_candidate"] is True
    assert audit_props["manual_review_required"] is False
    assert audit_props["repair_recommendation"] == "adaptive_high_grade_dual_buffer_retry"


def test_step2_pair_anchor_diagnostic_outputs_short_connected_endpoint_cluster(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_cluster", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s_cluster", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 0, "kind_2": 4}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2, 0)])
    relation = _write(
        tmp_path / "intersection_match_all.geojson",
        [
            {"properties": {"target_id": 1, "base_id": 11, "status": 0}, "geometry": Point(5, 0)},
            {"properties": {"target_id": 2, "base_id": 11, "status": 0}, "geometry": Point(5, 0)},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 11, "mainnodeid": 0}, "geometry": Point(5, 0)},
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_bridge", "snodeid": 10, "enodeid": 11, "direction": 0}, "geometry": LineString([(0, 0), (5, 0)])},
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (100, 0)])},
        ],
    )

    artifacts = run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["replaceable_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["pair_anchor_suspected_error_count"] == 1
    assert summary["pair_anchor_error_located_count"] == 1
    assert summary["scenario_b_auto_lift_count"] == 1
    assert summary["scenario_b_manual_review_count"] == 0

    repair = json.loads((artifacts.step_root / "t06_rcsd_repair_candidates.json").read_text(encoding="utf-8"))
    repair_props = repair["features"][0]["properties"]
    assert repair_props["original_rcsd_pair_nodes"] == ["11", "11"]
    assert repair_props["candidate_rcsd_pair_node_sets"] == [["10", "20"]]
    assert repair_props["pair_anchor_error_swsd_nodes"] == ["1", "2"]
    assert repair_props["pair_anchor_error_original_rcsd_nodes"] == ["11", "11"]
    assert repair_props["pair_anchor_error_candidate_rcsd_nodes"] == ["10", "20"]
    assert repair_props["pair_anchor_diagnostic_source"] == "buffer_only_endpoint_cluster"
    assert repair_props["pair_anchor_diagnostic_reason"] == "short_connected_endpoint_cluster"
    assert repair_props["pair_anchor_endpoint_cluster_nodes"] == [["10", "11"], ["20"]]
    assert repair_props["pair_anchor_bridge_road_ids"] == ["rr_bridge"]
    assert repair_props["pair_anchor_bridge_length_m"] == 5.0

    replaceable = json.loads((artifacts.step_root / "t06_rcsd_segment_replaceable.json").read_text(encoding="utf-8"))
    replaceable_props = replaceable["features"][0]["properties"]
    assert replaceable_props["original_rcsd_pair_nodes"] == ["11", "11"]
    assert replaceable_props["rcsd_pair_nodes"] == ["10", "20"]
    assert set(replaceable_props["rcsd_road_ids"]) == {"rr_main"}

    audit = json.loads((artifacts.step_root / "t06_rcsd_segment_failure_business_audit.json").read_text(encoding="utf-8"))
    audit_props = audit["features"][0]["properties"]
    assert audit_props["segment_outcome"] == "replaceable"
    assert audit_props["auto_fix_candidate"] is True
    assert audit_props["repair_recommendation"] == "high_confidence_pair_anchor_candidate"
    assert audit_props["original_rcsd_pair_nodes"] == ["11", "11"]
    assert audit_props["rcsd_pair_nodes"] == ["10", "20"]
    assert audit_props["pair_anchor_error_swsd_nodes"] == ["1", "2"]
    assert audit_props["pair_anchor_endpoint_cluster_nodes"] == [["10", "11"], ["20"]]


def test_step2_allows_partial_roundabout_group_when_one_segment_is_not_replaceable(tmp_path: Path) -> None:
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
    assert summary["replaceable_count"] == 1
    assert summary["special_junction_group_partial_count"] == 1
    assert summary["special_junction_group_blocked_count"] == 0
    assert summary["special_junction_gate_removed_replaceable_count"] == 0
    assert summary["reject_reason_counts"]["missing_pair_relation"] == 1
    assert "special_junction_group_not_fully_replaceable" not in summary["reject_reason_counts"]

    replaceable_payload = json.loads(artifacts.replaceable_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert replaceable_payload["row_count"] == 1

    candidate_payload = json.loads(artifacts.candidates_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    candidate_props = candidate_payload["features"][0]["properties"]
    assert candidate_props["swsd_segment_id"] == "s_ok"
    assert candidate_props["special_junction_group_ids"] == ["3"]
    assert candidate_props["special_junction_gate_status"] == "partial"

    group_audit = json.loads(
        (artifacts.summary_path.parent / "t06_special_junction_group_audit.json").read_text(encoding="utf-8")
    )
    group_props = group_audit["features"][0]["properties"]
    assert group_props["special_junction_id"] == "3"
    assert group_props["special_junction_type"] == "roundabout"
    assert group_props["gate_status"] == "partial"
    assert group_props["associated_segment_ids"] == ["s_ok", "s_fail"]
    assert group_props["replaceable_segment_ids"] == ["s_ok"]
    assert group_props["missing_replaceable_segment_ids"] == ["s_fail"]
    assert group_props["removed_replaceable_segment_ids"] == []
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


def test_step2_rejected_rows_explain_buffer_missing_bidirectional_corridor(tmp_path: Path) -> None:
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
            {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
            {"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(100, 80)},
            {"properties": {"id": 40, "mainnodeid": 0}, "geometry": Point(0, 80)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "forward", "snodeid": 10, "enodeid": 20, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])},
            {"properties": {"id": "reverse_a", "snodeid": 20, "enodeid": 30, "direction": 2}, "geometry": LineString([(100, 0), (100, 80)])},
            {"properties": {"id": "reverse_b", "snodeid": 30, "enodeid": 40, "direction": 2}, "geometry": LineString([(100, 80), (0, 80)])},
            {"properties": {"id": "reverse_c", "snodeid": 40, "enodeid": 10, "direction": 2}, "geometry": LineString([(0, 80), (0, 0)])},
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
    assert summary["replaceable_count"] == 0
    assert summary["reject_reason_counts"]["rcsd_not_bidirectional_for_swsd_dual"] == 1

    rejected_payload = json.loads(artifacts.step2.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_props = rejected_payload["features"][0]["properties"]
    assert rejected_props["root_cause_category"] == "buffer_candidate_missing_bidirectional_corridor"
    assert rejected_props["full_graph_status"] == "required_nodes_connected"
    assert rejected_props["candidate_graph_status"] == "required_nodes_connected"
    assert rejected_props["directional_status"] == "full=bidirectional;candidate=forward_only"

    buffer_rejected = json.loads(
        (artifacts.step2.summary_path.parent / "t06_rcsd_buffer_segment_rejected.json").read_text(encoding="utf-8")
    )
    buffer_props = buffer_rejected["features"][0]["properties"]
    assert buffer_props["notes"] == "full RCSD graph is bidirectional, but the 50m buffer candidate graph misses at least one direction corridor"
