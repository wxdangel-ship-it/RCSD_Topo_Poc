from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step2_extract_rcsd_segments
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationCheck
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.single_direction_semantic_retry import (
    semantic_endpoint_local_undirected_single_retry,
)


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def test_semantic_endpoint_retry_rejects_plain_reverse_rcsd_road() -> None:
    rcsd_roads = [
        {"properties": {"id": "rr_reverse", "snodeid": 20, "enodeid": 10, "direction": 2}, "geometry": LineString([(100, 0), (0, 0)])}
    ]
    rcsd_nodes = [
        {"properties": {"id": 10, "mainnodeid": 0}, "geometry": Point(0, 0)},
        {"properties": {"id": 20, "mainnodeid": 0}, "geometry": Point(100, 0)},
    ]
    swsd_roads = {
        "sr1": {"properties": {"id": "sr1", "snodeid": 11, "enodeid": 22, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])}
    }
    extractor = BufferSegmentExtractor(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_nodes)

    applies, result, source_reason = semantic_endpoint_local_undirected_single_retry(
        buffer_extractor=extractor,
        segment_geometry=LineString([(0, 0), (100, 0)]),
        relation=RelationCheck(True, ["10", "20"], []),
        optional_allowed_rcsd_nodes=[],
        all_relation_base_ids={"10", "20"},
        unexpected_relation_base_ids=set(),
        directed_swsd_pair_nodes=["1", "2"],
        directed_rcsd_pair_nodes=["10", "20"],
        pair_nodes=["1", "2"],
        road_ids=["sr1"],
        swsd_roads=swsd_roads,
        swsd_node_canonicalizer=BufferSegmentExtractor(
            rcsd_road_features=[],
            rcsd_node_features=[
                {"properties": {"id": 1, "mainnodeid": 1, "subnodeid": "[11]", "kind_2": 4}, "geometry": Point(0, 0)},
                {"properties": {"id": 11, "mainnodeid": 1, "kind_2": 0}, "geometry": Point(0, 0)},
                {"properties": {"id": 2, "mainnodeid": 2, "subnodeid": "[22]", "kind_2": 128}, "geometry": Point(100, 0)},
                {"properties": {"id": 22, "mainnodeid": 2, "kind_2": 0}, "geometry": Point(100, 0)},
            ],
        ).node_canonicalizer,
        special_swsd_junction_types={"2": "complex"},
        config=BufferExtractionConfig(),
    )

    assert applies is True
    assert result is None
    assert source_reason == ""


def test_step2_releases_local_corridor_with_only_advance_right_direction_gap(tmp_path: Path) -> None:
    artifacts = _run_semantic_endpoint_case(
        tmp_path,
        rcsd_roads=[
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 30, "direction": 2, "formway": 1}, "geometry": LineString([(0, 0), (50, 0)])},
            {"properties": {"id": "rr_connector", "snodeid": 20, "enodeid": 30, "direction": 2, "formway": 129}, "geometry": LineString([(100, 0), (50, 0)])},
        ],
        extra_rcsd_nodes=[{"properties": {"id": 30, "mainnodeid": 0}, "geometry": Point(50, 0)}],
    )

    payload = json.loads(artifacts.replaceable_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    props = payload["features"][0]["properties"]
    assert props["directed_swsd_pair_nodes"] == ["1", "2"]
    assert props["directed_rcsd_pair_nodes"] == ["10", "20"]
    assert props["rcsd_road_ids"] == ["rr_main", "rr_connector"]
    assert props["adaptive_buffer_status"] == "applied"
    assert props["adaptive_buffer_source_reason"] == "semantic_endpoint_local_undirected_corridor_release:rcsd_directed_path_missing"


def _run_semantic_endpoint_case(
    tmp_path: Path,
    *,
    rcsd_roads: list[dict],
    extra_rcsd_nodes: list[dict] | None = None,
):
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1_s2", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    fusion_units = _write(
        tmp_path / "fusion_units.gpkg",
        [
            {
                "properties": {"swsd_segment_id": "s1_s2", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
    )
    swsd_nodes = _write(
        tmp_path / "nodes.gpkg",
        [
            {"properties": {"id": 1, "mainnodeid": 1, "subnodeid": "[11]", "kind_2": 4}, "geometry": Point(0, 0)},
            {"properties": {"id": 11, "mainnodeid": 1, "kind_2": 0}, "geometry": Point(0, 0)},
            {"properties": {"id": 2, "mainnodeid": 2, "subnodeid": "[22]", "kind_2": 128}, "geometry": Point(100, 0)},
            {"properties": {"id": 22, "mainnodeid": 2, "kind_2": 0}, "geometry": Point(100, 0)},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [{"properties": {"id": "sr1", "snodeid": 11, "enodeid": 22, "direction": 2}, "geometry": LineString([(0, 0), (100, 0)])}],
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
            *(extra_rcsd_nodes or []),
        ],
    )
    rcsd_roads_path = _write(tmp_path / "rcsdroad_out.gpkg", rcsd_roads)

    return run_t06_step2_extract_rcsd_segments(
        swsd_fusion_units_path=fusion_units,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        intersection_match_path=relation,
        rcsdroad_path=rcsd_roads_path,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )
