from __future__ import annotations

import inspect

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_topology import (
    compile_road_next_road,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_lane_topo import (
    rejected_lane_topo_pairs,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_fallback import (
    direct_build_rescue_segment_ids,
    with_direct_build_rescue_reference_axes,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_pipeline import (
    _nodes_for_road_endpoints,
    _orphan_junction_carrier_ids,
    _project_lane_topo,
    _road_lane_relation,
    _same_segment_rejected_mask,
    run_segment_first_road_direct,
)


def test_only_failed_junction_surface_carrier_is_suppressed_as_orphan() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": "segment-road",
                "owner_type": "SEGMENT",
                "carrier_role": "main_oneway",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": "junction-road",
                "owner_type": "JUNCTION_UNIT",
                "carrier_role": "junction_surface_carrier",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    failures = gpd.GeoDataFrame(
        [
            {"road_id": "segment-road", "geometry": Point(0, 0)},
            {"road_id": "junction-road", "geometry": Point(2, 0)},
        ],
        crs=roads.crs,
    )

    assert _orphan_junction_carrier_ids(failures, roads) == {"junction-road"}


def test_roadnextroad_is_compiled_only_from_shared_node() -> None:
    roads = gpd.GeoDataFrame(
        [
            {"id": 1, "snodeid": 10, "enodeid": 20, "direction": 2, "geometry": LineString([(0, 0), (1, 0)])},
            {"id": 2, "snodeid": 20, "enodeid": 30, "direction": 2, "geometry": LineString([(1, 0), (2, 0)])},
            {"id": 3, "snodeid": 40, "enodeid": 50, "direction": 2, "geometry": LineString([(1, 1), (2, 1)])},
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": 10, "mainnodeid": 100, "geometry": Point(0, 0)},
            {"id": 20, "mainnodeid": 100, "geometry": Point(1, 0)},
            {"id": 30, "mainnodeid": 300, "geometry": Point(2, 0)},
            {"id": 40, "mainnodeid": 100, "geometry": Point(1, 1)},
            {"id": 50, "mainnodeid": 500, "geometry": Point(2, 1)},
        ],
        crs="EPSG:32650",
    )
    result = compile_road_next_road(roads, nodes, explicit_pairs=None, run_id="run")
    pairs = set(zip(result.road_next_road["RoadId"], result.road_next_road["NextRoadId"]))
    assert (1, 2) in pairs
    assert (1, 3) not in pairs


def test_complex_junction_shared_node_requires_explicit_physical_pair() -> None:
    roads = gpd.GeoDataFrame(
        [
            {"id": 1, "patch_road_key": "p:1", "snodeid": 10, "enodeid": 20, "direction": 2, "geometry": LineString([(0, 0), (1, 0)])},
            {"id": 2, "patch_road_key": "p:2", "snodeid": 20, "enodeid": 30, "direction": 2, "geometry": LineString([(1, 0), (2, 0)])},
            {"id": 3, "patch_road_key": "p:3", "snodeid": 20, "enodeid": 40, "direction": 2, "geometry": LineString([(1, 0), (1, 1)])},
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": 10, "junction_kind": "", "geometry": Point(0, 0)},
            {"id": 20, "junction_kind": "complex_divmerge", "geometry": Point(1, 0)},
            {"id": 30, "junction_kind": "", "geometry": Point(2, 0)},
            {"id": 40, "junction_kind": "", "geometry": Point(1, 1)},
        ],
        crs="EPSG:32650",
    )
    explicit = pd.DataFrame(
        [{"source_patch_road_key": "p:1", "target_patch_road_key": "p:2"}]
    )
    result = compile_road_next_road(roads, nodes, explicit_pairs=explicit, run_id="run")
    pairs = set(zip(result.road_next_road["RoadId"], result.road_next_road["NextRoadId"]))
    assert (1, 2) in pairs
    assert (1, 3) not in pairs


def test_comparison_nodes_are_scoped_to_loaded_road_endpoints() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": "10.0",
                "enodeid": 20,
                "geometry": LineString([(0, 0), (1, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": 10, "geometry": Point(0, 0)},
            {"id": "20", "geometry": Point(1, 0)},
            {"id": 30, "geometry": Point(2, 0)},
        ],
        crs="EPSG:32650",
    )

    scoped = _nodes_for_road_endpoints(nodes, roads)

    assert set(scoped["id"].astype(str)) == {"10", "20"}


def test_road_lane_relation_preserves_fragmented_many_to_many_lineage() -> None:
    relations = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:road",
                "road_id": "source-road",
                "lane_id": "lane-1",
                "geometry": LineString([(0, 0), (2, 0)]),
            },
            {
                "patch_road_key": "patch:road",
                "road_id": "source-road",
                "lane_id": "lane-2",
                "geometry": LineString([(0, 1), (2, 1)]),
            },
            {
                "patch_road_key": "patch:other",
                "road_id": "other-source-road",
                "lane_id": "lane-3",
                "geometry": LineString([(0, 2), (2, 2)]),
            },
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": "built-a",
                "patch_road_key": "patch:road",
                "source_patch_road_keys": "patch:road",
                "geometry": LineString([(0, 0.5), (1, 0.5)]),
            },
            {
                "id": "built-b",
                "patch_road_key": "patch:road",
                "source_patch_road_keys": "patch:road,patch:lane:lane-1",
                "source_lane_ids": "lane-3",
                "geometry": LineString([(1, 0.5), (2, 0.5)]),
            },
        ],
        crs=relations.crs,
    )

    result = _road_lane_relation(relations, roads)

    assert set(zip(result["road_id"], result["lane_id"])) == {
        ("built-a", "lane-1"),
        ("built-a", "lane-2"),
        ("built-b", "lane-1"),
        ("built-b", "lane-2"),
        ("built-b", "lane-3"),
    }


def test_lane_topo_projection_selects_realized_fragment_pair() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "source_lane_carrier_key": "patch:lane:source",
                "target_lane_carrier_key": "patch:lane:target",
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 7_484_763_311_632_813,
                "carrier_role": "main_forward",
                "patch_road_key": "patch:source",
                "source_patch_road_keys": "patch:source,patch:lane:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": 7_345_209_896_466_591,
                "carrier_role": "main_forward",
                "patch_road_key": "patch:target",
                "source_patch_road_keys": "patch:target,patch:lane:target",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "id": 7_568_315_000_000_009,
                "carrier_role": "main_reverse",
                "patch_road_key": "patch:target",
                "source_patch_road_keys": "patch:target,patch:lane:target",
                "geometry": LineString([(3, 0), (4, 0)]),
            },
        ],
        crs=audit.crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {
                "RoadId": 7_484_763_311_632_813,
                "NextRoadId": 7_345_209_896_466_591,
                "geometry": Point(1, 0),
            }
        ],
        crs=audit.crs,
    )

    result = _project_lane_topo(
        audit,
        roads,
        road_next_road,
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
    )

    assert result.iloc[0]["projection_state"] == "mapped_roadnextroad"
    assert result.iloc[0]["source_road_id"] == "7484763311632813"
    assert result.iloc[0]["target_road_id"] == "7345209896466591"


def test_lane_topo_projection_follows_stable_lineage_road_chain() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "source_lane_carrier_key": "",
                "target_lane_carrier_key": "",
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "segment",
                "carrier_role": "main_oneway",
                "lineage_parent_road_id": 1,
                "source_patch_road_keys": "patch:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": 2,
                "segment_id": "segment",
                "carrier_role": "main_oneway",
                "lineage_parent_road_id": 1,
                "source_patch_road_keys": "patch:bridge",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "id": 3,
                "segment_id": "advance-right",
                "carrier_role": "main_oneway",
                "lineage_parent_road_id": None,
                "source_patch_road_keys": "patch:target",
                "geometry": LineString([(2, 0), (3, 0)]),
            },
        ],
        crs=audit.crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {"RoadId": 1, "NextRoadId": 2, "geometry": Point(1, 0)},
            {"RoadId": 2, "NextRoadId": 3, "geometry": Point(2, 0)},
        ],
        crs=audit.crs,
    )

    result = _project_lane_topo(
        audit,
        roads,
        road_next_road,
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
    )

    assert result.iloc[0]["projection_state"] == "mapped_roadnextroad_chain"
    assert result.iloc[0]["source_road_id"] == "1"
    assert result.iloc[0]["target_road_id"] == "3"
    assert result.iloc[0]["carrier_path_road_ids"] == "1,2,3"


def test_lane_topo_projection_allows_retained_semantic_bridge_chain() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "source_lane_carrier_key": "",
                "target_lane_carrier_key": "",
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "source-segment",
                "carrier_role": "main_oneway",
                "realization": "built",
                "lineage_parent_road_id": 1,
                "source_patch_road_keys": "patch:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": 2,
                "segment_id": "bridge-segment",
                "carrier_role": "semantic_carrier",
                "realization": "retained",
                "lineage_parent_road_id": 2,
                "source_patch_road_keys": "patch:bridge",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "id": 3,
                "segment_id": "target-segment",
                "carrier_role": "main_oneway",
                "realization": "built",
                "lineage_parent_road_id": 3,
                "source_patch_road_keys": "patch:target",
                "geometry": LineString([(2, 0), (3, 0)]),
            },
        ],
        crs=audit.crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {"RoadId": 1, "NextRoadId": 2, "geometry": Point(1, 0)},
            {"RoadId": 2, "NextRoadId": 3, "geometry": Point(2, 0)},
        ],
        crs=audit.crs,
    )

    result = _project_lane_topo(
        audit,
        roads,
        road_next_road,
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
    )

    assert result.iloc[0]["projection_state"] == "mapped_roadnextroad_chain"
    assert result.iloc[0]["source_road_id"] == "1"
    assert result.iloc[0]["target_road_id"] == "3"
    assert result.iloc[0]["carrier_path_road_ids"] == "1,2,3"


def test_lane_topo_projection_rejects_unscoped_cross_lineage_bridge() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "source_lane_carrier_key": "",
                "target_lane_carrier_key": "",
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "source-segment",
                "carrier_role": "main_oneway",
                "realization": "built",
                "lineage_parent_road_id": 1,
                "source_patch_road_keys": "patch:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": 2,
                "segment_id": "other-segment",
                "carrier_role": "main_oneway",
                "realization": "built",
                "lineage_parent_road_id": 2,
                "source_patch_road_keys": "patch:other",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "id": 3,
                "segment_id": "target-segment",
                "carrier_role": "main_oneway",
                "realization": "built",
                "lineage_parent_road_id": 3,
                "source_patch_road_keys": "patch:target",
                "geometry": LineString([(2, 0), (3, 0)]),
            },
        ],
        crs=audit.crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {"RoadId": 1, "NextRoadId": 2, "geometry": Point(1, 0)},
            {"RoadId": 2, "NextRoadId": 3, "geometry": Point(2, 0)},
        ],
        crs=audit.crs,
    )

    result = _project_lane_topo(
        audit,
        roads,
        road_next_road,
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
    )

    assert (
        result.iloc[0]["projection_state"]
        == "review_shared_node_relation_missing"
    )
    assert result.iloc[0]["carrier_path_road_ids"] == ""


def test_lane_relation_selects_directional_movement_part_chain() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "source_lane_carrier_key": "patch:lane:source",
                "target_lane_carrier_key": "patch:lane:target",
                "source_patch_road_key": "patch:parent:source",
                "target_patch_road_key": "patch:parent:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "main",
                "carrier_role": "main_forward",
                "movement_parent_carrier_id": "main-forward",
                "source_patch_road_keys": "patch:parent:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": 2,
                "segment_id": "main",
                "carrier_role": "main_forward",
                "movement_parent_carrier_id": "main-forward",
                "source_patch_road_keys": "patch:bridge",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "id": 3,
                "segment_id": "right",
                "carrier_role": "main_oneway",
                "movement_parent_carrier_id": "",
                "source_patch_road_keys": "patch:parent:target",
                "geometry": LineString([(2, 0), (3, 0)]),
            },
            {
                "id": 9,
                "segment_id": "main",
                "carrier_role": "main_reverse",
                "movement_parent_carrier_id": "main-reverse",
                "source_patch_road_keys": "patch:parent:source",
                "geometry": LineString([(1, 1), (0, 1)]),
            },
        ],
        crs=audit.crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {"RoadId": 1, "NextRoadId": 2, "geometry": Point(1, 0)},
            {"RoadId": 2, "NextRoadId": 3, "geometry": Point(2, 0)},
            {"RoadId": 9, "NextRoadId": 3, "geometry": Point(2, 1)},
        ],
        crs=audit.crs,
    )
    relation = gpd.GeoDataFrame(
        [
            {
                "source_patch_id": "patch",
                "lane_id": "source",
                "lane_key": "patch:source",
                "road_id": 1,
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "source_patch_id": "patch",
                "lane_id": "target",
                "lane_key": "patch:target",
                "road_id": 3,
                "geometry": LineString([(2, 0), (3, 0)]),
            },
        ],
        crs=audit.crs,
    )

    result = _project_lane_topo(
        audit,
        roads,
        road_next_road,
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
        road_lane_relation=relation,
    )

    assert result.iloc[0]["projection_state"] == (
        "mapped_roadnextroad_chain"
    )
    assert result.iloc[0]["carrier_path_road_ids"] == "1,2,3"


def test_lane_topo_projection_prefers_common_parent_road() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "source_lane_carrier_key": "patch:lane:source",
                "target_lane_carrier_key": "patch:lane:target",
                "source_patch_road_key": "patch:parent:source",
                "target_patch_road_key": "patch:parent:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": "lane-source-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": "patch:lane:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": "lane-target-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": "patch:lane:target",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "id": "assembled-parent-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": (
                    "patch:parent:source,patch:parent:target"
                ),
                "geometry": LineString([(0, 1), (2, 1)]),
            },
        ],
        crs=audit.crs,
    )
    result = _project_lane_topo(
        audit,
        roads,
        gpd.GeoDataFrame(
            columns=["RoadId", "NextRoadId", "geometry"],
            geometry="geometry",
            crs=audit.crs,
        ),
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
    )

    assert result.iloc[0]["projection_state"] == "mapped_within_road"
    assert result.iloc[0]["source_road_id"] == "assembled-parent-road"
    assert result.iloc[0]["target_road_id"] == "assembled-parent-road"


def test_lane_specific_rejection_is_part_of_lane_topo_audit() -> None:
    connection_evidence = pd.DataFrame(
        [
            {
                "connection_decision": "rejected",
                "pair_source": "lane_topo_lane",
                "source_patch_road_key": "patch:lane:source",
                "target_patch_road_key": "patch:lane:target",
            },
            {
                "connection_decision": "rejected",
                "pair_source": "patch_road_next_road",
                "source_patch_road_key": "patch:road:source",
                "target_patch_road_key": "patch:road:target",
            },
        ]
    )

    assert rejected_lane_topo_pairs(connection_evidence) == {
        ("patch:lane:source", "patch:lane:target")
    }


def test_lane_topo_projection_reuses_accepted_parent_road_pair() -> None:
    audit = gpd.GeoDataFrame(
        [
            {
                "lane_topo_id": "lane-topo-1",
                "source_lane_carrier_key": "patch:lane:source",
                "target_lane_carrier_key": "patch:lane:target",
                "source_patch_road_key": "patch:parent:source",
                "target_patch_road_key": "patch:parent:target",
                "geometry": Point(1, 0),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": "lane-source-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": "patch:lane:source",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "id": "lane-target-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": "patch:lane:target",
                "geometry": LineString([(1, 1), (2, 1)]),
            },
            {
                "id": "parent-source-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": "patch:parent:source",
                "geometry": LineString([(0, 2), (1, 2)]),
            },
            {
                "id": "parent-target-road",
                "carrier_role": "main_forward",
                "source_patch_road_keys": "patch:parent:target",
                "geometry": LineString([(1, 2), (2, 2)]),
            },
        ],
        crs=audit.crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {
                "RoadId": "parent-source-road",
                "NextRoadId": "parent-target-road",
                "geometry": Point(1, 2),
            }
        ],
        crs=audit.crs,
    )
    connection_evidence = pd.DataFrame(
        [
            {
                "connection_decision": "accepted",
                "pair_source": "lane_topo",
                "source_relation_id": "lane-topo-1",
                "source_road_id": "parent-source-road",
                "target_road_id": "parent-target-road",
            }
        ]
    )

    result = _project_lane_topo(
        audit,
        roads,
        road_next_road,
        fallback_patch_road_keys=set(),
        rejected_patch_road_pairs=set(),
        connection_evidence=connection_evidence,
    )

    assert result.iloc[0]["projection_state"] == "mapped_roadnextroad"
    assert result.iloc[0]["source_road_id"] == "parent-source-road"
    assert result.iloc[0]["target_road_id"] == "parent-target-road"


def test_pre_access_failure_geometry_is_preserved_for_root_cause_audit() -> None:
    source = inspect.getsource(run_segment_first_road_direct)

    assert '"pre_access_roads": pre_access_roads' in source
    assert '"pre_access_nodes": pre_access_nodes' in source
    assert '"pre_access_carriers": pre_access_carriers' in source
    assert '"pre_access_realization": pre_access_realization' in source


def test_internal_lane_topo_relation_does_not_force_segment_fallback() -> None:
    assignments = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:source",
                "assigned_segment_id": "segment-1",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "patch_road_key": "patch:target",
                "assigned_segment_id": "segment-1",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    rejected = gpd.GeoDataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "reason_codes": "relation_endpoint_orientation_conflict",
                "geometry": Point(),
            },
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "reason_codes": "completion_surface_insufficient",
                "geometry": Point(1, 0),
            },
        ],
        crs=assignments.crs,
    )

    mask = _same_segment_rejected_mask(rejected, assignments)

    assert mask.tolist() == [False, True]


def test_selected_cross_segment_movement_does_not_fallback_shared_candidate_owner() -> None:
    assignments = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:source",
                "assigned_segment_id": "advance-right-a",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "patch_road_key": "patch:shared",
                "assigned_segment_id": "advance-right-a",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "patch_road_key": "patch:shared",
                "assigned_segment_id": "advance-right-b",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    rejected = gpd.GeoDataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:shared",
                "source_segment_id": "advance-right-a",
                "target_segment_id": "advance-right-b",
                "reason_codes": "junction_group_or_same_road_cycle_rejected",
                "geometry": Point(1, 0),
            }
        ],
        crs=assignments.crs,
    )

    mask = _same_segment_rejected_mask(rejected, assignments)

    assert mask.tolist() == [False]


def test_direct_build_core_retries_endpoint_surface_before_fallback() -> None:
    assignments = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:source",
                "assigned_segment_id": "core-1",
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "patch_road_key": "patch:target",
                "assigned_segment_id": "core-1",
                "geometry": LineString([(1, 0), (2, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    triggers = gpd.GeoDataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_segment_id": "core-1",
                "target_segment_id": "core-1",
                "geometry": Point(1, 0),
            }
        ],
        crs=assignments.crs,
    )

    selected = direct_build_rescue_segment_ids(
        triggers,
        assignments,
        direct_build_core_segment_ids={"core-1", "core-2"},
        already_rescued_segment_ids=set(),
    )
    repeated = direct_build_rescue_segment_ids(
        triggers,
        assignments,
        direct_build_core_segment_ids={"core-1", "core-2"},
        already_rescued_segment_ids={"core-1"},
    )

    assert selected == {"core-1"}
    assert repeated == set()


def test_direct_build_rescue_adds_only_selected_semantic_reference_axis() -> None:
    axes = gpd.GeoDataFrame(
        [
            {
                "segment_id": "exact",
                "reference_state": "resolved",
                "carrier_guidance_eligible": True,
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "segment_id": "rescue",
                "reference_state": "resolved",
                "carrier_guidance_eligible": False,
                "geometry": LineString([(0, 1), (10, 1)]),
            },
            {
                "segment_id": "not-selected",
                "reference_state": "resolved",
                "carrier_guidance_eligible": False,
                "geometry": LineString([(0, 2), (10, 2)]),
            },
        ],
        crs="EPSG:32650",
    )

    result = with_direct_build_rescue_reference_axes(
        axes[axes["carrier_guidance_eligible"]].copy(),
        axes,
        {"rescue"},
    )

    assert set(result["segment_id"]) == {"exact", "rescue"}
    assert not bool(
        result.set_index("segment_id")
        .loc["rescue", "carrier_guidance_eligible"]
    )
