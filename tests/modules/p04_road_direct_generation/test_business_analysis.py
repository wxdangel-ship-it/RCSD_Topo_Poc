import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.business_analysis import (
    build_business_analysis,
)


def test_lane_topo_readiness_uses_lane_direction_and_swsd_nodes() -> None:
    decisions = gpd.GeoDataFrame(
        [
            {
                "lane_id": "l1",
                "source_patch_ids": "p1",
                "swsd_unit_id": "r1",
                "decision": "accepted",
                "reason_codes": "owner_unique_supported;width_nominal",
                "owner_distance_p90_m": 5.0,
                "owner_score_margin": 20.0,
                "owner_direction_delta_deg": 2.0,
                "inferred_lane_width_m": 3.5,
                "drivezone_coverage": 1.0,
                "width_state": "nominal",
                "is_intersection_in_lane": False,
                "is_intersection_out_lane": True,
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "lane_id": "l2",
                "source_patch_ids": "p1",
                "swsd_unit_id": "r2",
                "decision": "accepted",
                "reason_codes": "owner_unique_supported;width_nominal",
                "owner_distance_p90_m": 4.0,
                "owner_score_margin": 18.0,
                "owner_direction_delta_deg": 1.0,
                "inferred_lane_width_m": 3.4,
                "drivezone_coverage": 1.0,
                "width_state": "nominal",
                "is_intersection_in_lane": True,
                "is_intersection_out_lane": False,
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "snode_id": "n1",
                "enode_id": "n2",
                "segmentid": "s1",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "swsd_unit_id": "r2",
                "snode_id": "n2",
                "enode_id": "n3",
                "segmentid": None,
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    lane_next = pd.DataFrame(
        [{"Id": "x1", "LaneId": "l1", "NextLaneId": "l2", "IsMeet": True, "patch_id": "p1"}]
    )

    result = build_business_analysis(lane_next, decisions, roads, run_id="run")

    assert result.summary["lane_direction_evidence"]["end_to_start_closest_ratio"] == 1.0
    assert result.summary["lane_topo_readiness"]["accepted_cross_owner_link_count"] == 1
    assert result.topology_links.iloc[0]["semantic_relation"] == "directed_end_to_start"
    assert result.topology_links.geometry.is_valid.all()
    assert (result.topology_links.geometry.length > 0).all()
    assert result.summary["swsd_evidence_coverage"]["t01_segment_unjoined_road_ids"] == ["r2"]
