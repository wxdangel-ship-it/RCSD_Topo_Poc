from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.anchor_portals import (
    AnchorRecord,
    associate_t07_surfaces,
    build_anchor_map,
    portal_candidates,
    raw_portal_candidates,
    validate_t07_truth_anchors,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    build_graph,
    build_node_context,
    build_raw_node_context,
    shortest_path_between_sets,
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


def test_t07_raw_portals_are_limited_to_explicit_group_and_standard_surface() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": ["base", "grouped", "inside", "near_outside", "ineligible"],
            "geometry": [
                Point(0, 0),
                Point(1, 0),
                Point(4, 0),
                Point(20, 0),
                Point(3, 0),
            ],
        },
        crs="EPSG:3857",
    )
    raw_points = dict(zip(nodes["id"], nodes.geometry, strict=True))
    canonicalizer, groups, _ = build_node_context(nodes)
    anchor = AnchorRecord("junction", "base", "T07", "", "", ("base", "grouped"))

    portals = raw_portal_candidates(
        anchor=anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids={"base", "grouped", "inside", "near_outside"},
        radius_m=50.0,
        direction_role="start",
        truth_surface=box(-2, -2, 5, 2),
    )

    assert [row["raw_id"] for row in portals] == ["base", "grouped", "inside"]
    assert {row["source"] for row in portals} == {
        "truth_group",
        "rcsdintersection_surface",
    }


def test_non_t07_raw_portals_keep_spatial_access_side() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": ["base", "near", "outside"],
            "geometry": [Point(0, 0), Point(40, 0), Point(60, 0)],
        },
        crs="EPSG:3857",
    )
    raw_points = dict(zip(nodes["id"], nodes.geometry, strict=True))
    canonicalizer, groups, _ = build_node_context(nodes)
    anchor = AnchorRecord("junction", "base", "T04", "", "", ("base",))

    portals = raw_portal_candidates(
        anchor=anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids={"base", "near", "outside"},
        radius_m=50.0,
        direction_role="end",
        truth_surface=None,
    )

    assert [row["raw_id"] for row in portals] == ["base", "near"]
    assert portals[1]["source"] == "spatial_portal"


def test_anchored_alias_group_is_distance_audit_only_and_direction_filtered() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": [
                "main",
                "forward_alias",
                "reverse_alias",
                "nearby_spatial",
                "outside_spatial",
            ],
            "mainNodeId": ["100", "100", "100", "", ""],
            "subNodeId": ["main|forward_alias|reverse_alias", "", "", "", ""],
            "geometry": [
                Point(0, 0),
                Point(80, 0),
                Point(70, 0),
                Point(10, 0),
                Point(80, 10),
            ],
        },
        crs="EPSG:3857",
    )
    canonicalizer, groups, raw_points = build_node_context(nodes)
    anchor = AnchorRecord("junction", "main", "T03", "", "", ("main",))

    portals = raw_portal_candidates(
        anchor=anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids={"forward_alias", "nearby_spatial", "outside_spatial"},
        radius_m=50.0,
        direction_role="start",
        truth_surface=None,
    )

    assert [row["raw_id"] for row in portals] == [
        "nearby_spatial",
        "forward_alias",
    ]
    by_id = {row["raw_id"]: row for row in portals}
    assert by_id["forward_alias"] == {
        "canonical_id": "forward_alias",
        "raw_id": "forward_alias",
        "distance_m": 80.0,
        "source": "anchored_canonical_alias",
        "direction_role": "start",
        "anchor_canonical_id": "100",
        "distance_gate_role": "audit_only",
    }
    assert by_id["nearby_spatial"]["source"] == "spatial_portal"
    assert by_id["nearby_spatial"]["distance_gate_role"] == "hard_radius"
    assert "reverse_alias" not in by_id
    assert "outside_spatial" not in by_id


def test_only_selected_base_mainnode_group_is_expanded() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": [
                "selected_main",
                "selected_alias",
                "explicit_other",
                "other_alias",
            ],
            "mainNodeId": ["100", "100", "200", "200"],
            "subNodeId": [
                "selected_main|selected_alias",
                "",
                "explicit_other|other_alias",
                "",
            ],
            "geometry": [
                Point(0, 0),
                Point(80, 0),
                Point(5, 0),
                Point(80, 10),
            ],
        },
        crs="EPSG:3857",
    )
    canonicalizer, groups, raw_points = build_node_context(nodes)
    anchor = AnchorRecord(
        "junction",
        "selected_main",
        "T07",
        "",
        "",
        ("selected_main", "explicit_other"),
    )

    portals = raw_portal_candidates(
        anchor=anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids={"selected_alias", "other_alias"},
        radius_m=50.0,
        direction_role="start",
        truth_surface=None,
    )

    assert [row["raw_id"] for row in portals] == ["selected_alias"]
    assert portals[0]["source"] == "anchored_canonical_alias"


def test_opposite_directions_use_separate_anchored_alias_road_chains() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": [
                "source_main",
                "source_forward",
                "source_reverse",
                "target_main",
                "target_forward",
                "target_reverse",
            ],
            "mainNodeId": ["100", "100", "100", "200", "200", "200"],
            "subNodeId": [
                "source_main|source_forward|source_reverse",
                "",
                "",
                "target_main|target_forward|target_reverse",
                "",
                "",
            ],
            "geometry": [
                Point(0, 0),
                Point(80, 0),
                Point(80, 10),
                Point(100, 0),
                Point(180, 0),
                Point(180, 10),
            ],
        },
        crs="EPSG:3857",
    )
    roads = gpd.GeoDataFrame(
        {
            "id": ["forward_road", "reverse_road"],
            "snodeid": ["source_forward", "source_reverse"],
            "enodeid": ["target_forward", "target_reverse"],
            "direction": [2, 3],
            "geometry": [
                LineString([(80, 0), (180, 0)]),
                LineString([(80, 10), (180, 10)]),
            ],
        },
        crs="EPSG:3857",
    )
    canonicalizer, groups, raw_points = build_node_context(nodes)
    raw_canonicalizer, _, _ = build_raw_node_context(nodes)
    graph = build_graph(roads, raw_canonicalizer)
    source_anchor = AnchorRecord(
        "source",
        "source_main",
        "T03",
        "",
        "",
        ("source_main",),
    )
    target_anchor = AnchorRecord(
        "target",
        "target_main",
        "T03",
        "",
        "",
        ("target_main",),
    )

    forward_starts = raw_portal_candidates(
        anchor=source_anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids=graph.outgoing_nodes,
        radius_m=50.0,
        direction_role="start",
        truth_surface=None,
    )
    forward_ends = raw_portal_candidates(
        anchor=target_anchor,
        portal_point=Point(100, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids=graph.incoming_nodes,
        radius_m=50.0,
        direction_role="end",
        truth_surface=None,
    )
    forward_path = shortest_path_between_sets(
        graph.directed,
        {row["raw_id"] for row in forward_starts},
        {row["raw_id"] for row in forward_ends},
    )

    reverse_starts = raw_portal_candidates(
        anchor=target_anchor,
        portal_point=Point(100, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids=graph.outgoing_nodes,
        radius_m=50.0,
        direction_role="start",
        truth_surface=None,
    )
    reverse_ends = raw_portal_candidates(
        anchor=source_anchor,
        portal_point=Point(0, 0),
        frcsd_nodes=nodes,
        canonicalizer=canonicalizer,
        canonical_groups=groups,
        raw_node_points=raw_points,
        eligible_raw_ids=graph.incoming_nodes,
        radius_m=50.0,
        direction_role="end",
        truth_surface=None,
    )
    reverse_path = shortest_path_between_sets(
        graph.directed,
        {row["raw_id"] for row in reverse_starts},
        {row["raw_id"] for row in reverse_ends},
    )

    assert forward_path is not None
    assert forward_path.road_ids == ("forward_road",)
    assert forward_path.node_ids == ("source_forward", "target_forward")
    assert reverse_path is not None
    assert reverse_path.road_ids == ("reverse_road",)
    assert reverse_path.node_ids == ("target_reverse", "source_reverse")


def test_t07_surface_association_is_unique_and_audited() -> None:
    anchors = {
        "junction": AnchorRecord(
            "junction", "base", "T07", "", "", ("base",)
        )
    }
    surfaces = gpd.GeoDataFrame(
        {
            "id": ["selected", "far"],
            "geometry": [box(-2, -2, 2, 2), box(20, 20, 30, 30)],
        },
        crs="EPSG:3857",
    )

    mapped, audit = associate_t07_surfaces(
        anchors,
        {"junction": Point(0, 0)},
        surfaces,
        tolerance_m=50.0,
    )

    assert mapped["junction"].equals(surfaces.iloc[0].geometry)
    assert audit["status"] == "pass"
    assert audit["unique_surface_count"] == 1
    assert audit["missing_target_ids"] == []
    assert audit["ambiguous_target_ids"] == []
