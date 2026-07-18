from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.anchor_portals import (
    AnchorRecord,
    build_anchor_map,
    portal_candidates,
    validate_t07_truth_anchors,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    build_node_context,
)


def test_t05_grouped_nodes_and_rcsd_intersection_truth_are_preserved() -> None:
    audit = pd.DataFrame(
        [
            {
                "target_id": "swsd_junction",
                "base_id": "main",
                "source_module": "T07",
                "status": "0",
                "reason": "truth",
                "scene": "",
                "grouped_rcsdnode_ids": "main|sub",
            }
        ]
    )
    anchors = build_anchor_map(audit)
    truth = gpd.GeoDataFrame(
        {"id": ["intersection"], "geometry": [box(-1, -1, 1, 1)]},
        crs="EPSG:3857",
    )
    nodes = gpd.GeoDataFrame(
        {"id": ["main", "sub"], "geometry": [Point(3, 0), Point(0, 0)]},
        crs="EPSG:3857",
    )

    assert anchors["swsd_junction"].grouped_node_ids == ("main", "sub")
    result = validate_t07_truth_anchors(
        anchors, truth, nodes, tolerance_m=50.0
    )
    assert result["status"] == "pass"
    assert result["truth_relation"] == (
        "frcsd_anchor_node_distance_to_rcsd_intersection_surface"
    )
    assert result["max_matched_distance_m"] == 0.0


def test_portals_use_group_and_50m_spatial_candidates_with_role_filter() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": ["main", "sub", "near", "outside"],
            "mainNodeId": ["100", "100", "", ""],
            "subNodeId": ["main|sub", "", "", ""],
            "geometry": [Point(0, 0), Point(2, 0), Point(40, 0), Point(60, 0)],
        },
        crs="EPSG:3857",
    )
    canonicalizer, groups, raw_points = build_node_context(nodes)
    anchor = AnchorRecord("target", "main", "T07", "", "", ("main", "sub"))

    portals = portal_candidates(
        anchor=anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_canonical_ids={"100", "near", "outside"},
        radius_m=50.0,
        direction_role="start",
    )

    assert [row["canonical_id"] for row in portals] == ["100", "near"]
    assert portals[0]["direction_role"] == "start"
    assert portals[0]["source"] == "truth_group"
