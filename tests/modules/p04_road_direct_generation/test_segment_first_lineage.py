from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_lineage import (
    attach_lineage_split_to_node_build,
    split_roads_at_stable_lineage_boundaries,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_nodes import (
    NodeBuildResult,
)


CRS = "EPSG:32650"


def _roads(source_keys: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": 100,
                "segment_id": "segment:1",
                "owner_type": "SEGMENT",
                "realization": "built",
                "carrier_role": "main_forward",
                "source_patch_road_keys": source_keys,
                "source_lane_ids": "lane:a,lane:b",
                "source_snodeid": "source:start",
                "source_enodeid": "source:end",
                "snodeid": 10,
                "enodeid": 20,
                "assembly_state": "observed",
                "geometry": LineString([(0, 0), (25, 1), (50, 0), (75, -1), (100, 0)]),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _sources(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)


def _base_sources() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "run_id": "old",
                "road_id": 100,
                "segment_id": "segment:1",
                "source_span_id": "100:0",
                "geometry_source": "hp_observed",
                "source_object_ids": "patch:a,patch:b",
                "start_fraction": 0.0,
                "end_fraction": 1.0,
                "length_m": 100.0,
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _split(
    roads: gpd.GeoDataFrame,
    sources: gpd.GeoDataFrame,
    protected_split_surface: object | None = None,
    lane_group_relations: gpd.GeoDataFrame | None = None,
):
    return split_roads_at_stable_lineage_boundaries(
        roads,
        _base_sources(),
        sources,
        run_id="run",
        minimum_part_length_m=10.0,
        maximum_handoff_gap_m=15.0,
        maximum_handoff_overlap_m=10.0,
        lane_group_relations=lane_group_relations,
        maximum_lane_group_distance_m=20.0,
        protected_split_surface=protected_split_surface,
    )


def test_stable_sequential_lane_groups_split_without_changing_geometry() -> None:
    parent = _roads("patch:a,patch:b")
    result = _split(
        parent,
        _sources(
            [
                {
                    "patch_road_key": "patch:a",
                    "source_patch_id": "patch",
                    "road_id": "road:a",
                    "center_lane_id": "lane:a",
                    "geometry": LineString([(0, 0), (48, 0)]),
                },
                {
                    "patch_road_key": "patch:b",
                    "source_patch_id": "patch",
                    "road_id": "road:b",
                    "center_lane_id": "lane:b",
                    "geometry": LineString([(52, 0), (100, 0)]),
                },
            ]
        ),
    )

    assert len(result.roads) == 2
    assert unary_union(result.roads.geometry).equals(parent.iloc[0].geometry)
    assert list(result.roads["source_patch_road_keys"]) == [
        "patch:a",
        "patch:b",
    ]
    assert list(result.roads["source_lane_ids"]) == ["lane:a", "lane:b"]
    assert result.roads.iloc[0]["source_enodeid"] == ""
    assert result.roads.iloc[1]["source_snodeid"] == ""
    assert result.roads.iloc[0]["end_patch_road_keys"] == ""
    assert result.roads.iloc[1]["start_patch_road_keys"] == ""
    assert bool(result.roads.iloc[0]["lineage_internal_end"])
    assert bool(result.roads.iloc[1]["lineage_internal_start"])
    assert list(result.roads["carrier_id"]) == [
        "lineage-road:100:part:0",
        "lineage-road:100:part:1",
    ]
    assert len(result.internal_nodes) == 1
    internal_node_id = result.internal_nodes.iloc[0]["id"]
    assert list(result.roads["snodeid"]) == [10, internal_node_id]
    assert list(result.roads["enodeid"]) == [internal_node_id, 20]
    assert result.summary["split_boundary_count"] == 1
    assert len(result.geometry_sources) == 2
    assert abs(result.geometry_sources["length_m"].sum() - parent.geometry.length.sum()) < 1e-6


def test_attach_split_preserves_existing_nodes_and_adds_internal_node() -> None:
    parent = _roads("patch:a,patch:b")
    split = _split(
        parent,
        _sources(
            [
                {
                    "patch_road_key": "patch:a",
                    "source_patch_id": "patch",
                    "road_id": "road:a",
                    "center_lane_id": "lane:a",
                    "geometry": LineString([(0, 0), (48, 0)]),
                },
                {
                    "patch_road_key": "patch:b",
                    "source_patch_id": "patch",
                    "road_id": "road:b",
                    "center_lane_id": "lane:b",
                    "geometry": LineString([(52, 0), (100, 0)]),
                },
            ]
        ),
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": 10, "mainnodeid": 10, "geometry": parent.geometry.iloc[0].boundary.geoms[0]},
            {"id": 20, "mainnodeid": 20, "geometry": parent.geometry.iloc[0].boundary.geoms[1]},
        ],
        geometry="geometry",
        crs=CRS,
    )
    endpoint_audit = gpd.GeoDataFrame(
        [
            {
                "run_id": "run",
                "road_id": 100,
                "endpoint": "start",
                "node_id": 10,
                "mainnodeid": 10,
                "endpoint_shift_m": 0.0,
                "geometry": nodes.geometry.iloc[0],
            },
            {
                "run_id": "run",
                "road_id": 100,
                "endpoint": "end",
                "node_id": 20,
                "mainnodeid": 20,
                "endpoint_shift_m": 0.0,
                "geometry": nodes.geometry.iloc[1],
            },
        ],
        geometry="geometry",
        crs=CRS,
    )
    empty = gpd.GeoDataFrame(
        {"geometry": gpd.GeoSeries([], crs=CRS)},
        geometry="geometry",
        crs=CRS,
    )
    attached = attach_lineage_split_to_node_build(
        NodeBuildResult(
            parent,
            nodes,
            endpoint_audit,
            empty,
            empty,
            {"node_count": 2},
        ),
        split,
        run_id="run",
    )

    assert list(attached.nodes.iloc[:2]["id"]) == [10, 20]
    assert attached.nodes.iloc[:2].geometry.equals(nodes.geometry)
    assert len(attached.nodes) == 3
    assert len(attached.endpoint_audit) == 4
    assert attached.summary["missing_node_reference_count"] == 0


def test_same_lane_group_does_not_split() -> None:
    result = _split(
        _roads("patch:a,patch:b"),
        _sources(
            [
                {
                    "patch_road_key": "patch:a",
                    "source_patch_id": "patch",
                    "road_id": "road:shared",
                    "center_lane_id": "lane:a",
                    "geometry": LineString([(0, 0), (48, 0)]),
                },
                {
                    "patch_road_key": "patch:b",
                    "source_patch_id": "patch",
                    "road_id": "road:shared",
                    "center_lane_id": "lane:b",
                    "geometry": LineString([(52, 0), (100, 0)]),
                },
            ]
        ),
    )

    assert len(result.roads) == 1
    assert result.summary["split_boundary_count"] == 0


def test_parallel_overlapping_lane_groups_do_not_split() -> None:
    result = _split(
        _roads("patch:a,patch:b"),
        _sources(
            [
                {
                    "patch_road_key": "patch:a",
                    "source_patch_id": "patch",
                    "road_id": "road:a",
                    "center_lane_id": "lane:a",
                    "geometry": LineString([(0, 1), (100, 1)]),
                },
                {
                    "patch_road_key": "patch:b",
                    "source_patch_id": "patch",
                    "road_id": "road:b",
                    "center_lane_id": "lane:b",
                    "geometry": LineString([(0, -1), (100, -1)]),
                },
            ]
        ),
    )

    assert len(result.roads) == 1
    assert result.summary["split_boundary_count"] == 0


def test_junction_relation_scope_protects_lineage_boundary() -> None:
    result = _split(
        _roads("patch:a,patch:b"),
        _sources(
            [
                {
                    "patch_road_key": "patch:a",
                    "source_patch_id": "patch",
                    "road_id": "road:a",
                    "center_lane_id": "lane:a",
                    "geometry": LineString([(0, 0), (48, 0)]),
                },
                {
                    "patch_road_key": "patch:b",
                    "source_patch_id": "patch",
                    "road_id": "road:b",
                    "center_lane_id": "lane:b",
                    "geometry": LineString([(52, 0), (100, 0)]),
                },
            ]
        ),
        box(45, -5, 55, 5),
    )

    assert len(result.roads) == 1
    assert result.summary["split_boundary_count"] == 0
    assert result.summary["protected_boundary_rejection_count"] == 1
    assert list(result.audit["split_decision"]) == ["rejected"]
    assert list(result.audit["reason_codes"]) == [
        "junction_relation_scope_protected"
    ]


def test_direct_lane_group_handoff_adds_a_fine_road_boundary() -> None:
    parent = _roads("patch:primary")
    result = _split(
        parent,
        _sources(
            [
                {
                    "patch_road_key": "patch:primary",
                    "source_patch_id": "patch",
                    "road_id": "road:primary",
                    "center_lane_id": "",
                    "geometry": LineString([(0, 0), (100, 0)]),
                }
            ]
        ),
        lane_group_relations=gpd.GeoDataFrame(
            [
                {
                    "patch_road_key": "group:a",
                    "lane_id": "lane:a",
                    "geometry": LineString([(0, 1), (48, 1)]),
                },
                {
                    "patch_road_key": "group:b",
                    "lane_id": "lane:b",
                    "geometry": LineString([(52, 1), (100, 1)]),
                },
            ],
            geometry="geometry",
            crs=CRS,
        ),
    )

    assert len(result.roads) == 2
    assert result.summary["lane_group_split_boundary_count"] == 1
    assert list(result.audit["reason_codes"]) == [
        "stable_lane_group_handoff"
    ]
    assert list(result.roads["source_lane_ids"]) == [
        "lane:a",
        "lane:b",
    ]
    assert all(
        "patch:primary" in value
        for value in result.roads["source_patch_road_keys"]
    )
