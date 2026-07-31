from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    build_graph,
    shortest_path_between_sets,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.reverse_segment_scope import (
    SegmentScopeIndex,
    evaluate_reverse_segment_scope,
)


def _graph(geometry: LineString):
    roads = gpd.GeoDataFrame(
        {
            "id": ["reverse"],
            "snodeid": ["a"],
            "enodeid": ["b"],
            "direction": [1],
            "geometry": [geometry],
        },
        crs="EPSG:3857",
    )
    graph = build_graph(roads, NodeCanonicalizer({}, frozenset()))
    path = shortest_path_between_sets(graph.directed, ["a"], ["b"])
    assert path is not None
    return graph, path


def _segments(*rows: tuple[str, LineString]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "id": [row[0] for row in rows],
            "geometry": [row[1] for row in rows],
        },
        crs="EPSG:3857",
    )


def _evaluate(
    segments: gpd.GeoDataFrame,
    *,
    road_geometry: LineString = LineString([(0, 0), (100, 0)]),
):
    graph, path = _graph(road_geometry)
    return evaluate_reverse_segment_scope(
        candidate_id="current",
        current_segment_id="current",
        direction="pair1_to_pair0",
        path=path,
        graph=graph,
        source_surface=box(-2, -2, 2, 2),
        target_surface=box(98, -2, 102, 2),
        segment_index=SegmentScopeIndex(segments),
    )


def test_reverse_scope_accepts_inter_anchor_road_uniquely_owned_by_current() -> None:
    interval, ownership, evidence = _evaluate(
        _segments(("current", LineString([(0, 0), (100, 0)])))
    )

    assert interval["accepted_anchor_interval"] is True
    assert interval["source_road_surface_gap_m"] == 0.0
    assert interval["target_road_surface_gap_m"] == 0.0
    assert ownership["accepted_current_segment_owner"] is True
    assert ownership["other_segment_ids"] == []
    assert evidence[0]["scope_status"] == "owned_by_current_segment"


def test_reverse_scope_rejects_road_more_strongly_covered_by_other_segment() -> None:
    current = LineString([(0, 0), (50, 25), (100, 0)])
    other = LineString([(0, 0), (100, 0)])

    interval, ownership, evidence = _evaluate(
        _segments(("current", current), ("other", other))
    )

    assert interval["accepted_anchor_interval"] is True
    assert ownership["accepted_current_segment_owner"] is False
    assert ownership["other_segment_ids"] == ["other"]
    assert evidence[0]["scope_status"] == "owned_by_other_segment"
    assert evidence[0]["owner_segment_id"] == "other"


def test_reverse_scope_rejects_ambiguous_equal_segment_coverage() -> None:
    geometry = LineString([(0, 0), (100, 0)])

    _, ownership, evidence = _evaluate(
        _segments(("current", geometry), ("same_corridor", geometry))
    )

    assert ownership["accepted_current_segment_owner"] is False
    assert ownership["rejection_reason"] == "segment_ownership_ambiguous"
    assert ownership["ambiguous_road_ids"] == ["reverse"]
    assert evidence[0]["scope_status"] == "ambiguous_segment_ownership"


def test_reverse_scope_rejects_path_not_contacting_both_anchor_surfaces() -> None:
    interval, ownership, _ = _evaluate(
        _segments(("current", LineString([(0, 4), (100, 4)]))),
        road_geometry=LineString([(0, 4), (100, 4)]),
    )

    assert interval["accepted_anchor_interval"] is False
    assert interval["rejection_reason"] == "endpoint_road_surface_contact_missing"
    assert interval["source_road_surface_gap_m"] == 2.0
    assert interval["target_road_surface_gap_m"] == 2.0
    assert ownership["accepted_current_segment_owner"] is True
