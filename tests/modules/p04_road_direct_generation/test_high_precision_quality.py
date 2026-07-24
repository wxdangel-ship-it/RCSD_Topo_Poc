from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_quality import (
    run_high_precision_independent_quality,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.io import write_gpkg_layers


def test_independent_quality_accepts_traceable_high_precision_package(
    tmp_path: Path,
) -> None:
    _write_package(tmp_path)

    result = run_high_precision_independent_quality(tmp_path)

    assert result["gate_pass"]
    assert result["geometry_source"]["partition_violation_count"] == 0
    assert result["geometry_source"]["declaration_mismatch_count"] == 0
    assert result["geometry_source"]["unbacked_observed_segment_count"] == 0
    assert result["physical_node"]["violation_count"] == 0
    assert result["movement"]["violation_count"] == 0


def test_independent_quality_rejects_inflated_observation_and_low_coverage(
    tmp_path: Path,
) -> None:
    _write_package(tmp_path, observed_fraction=0.5, inflate_observed=True)

    result = run_high_precision_independent_quality(tmp_path)

    assert not result["gate_pass"]
    assert result["geometry_source"]["declaration_mismatch_count"] > 0
    assert not result["gates"]["evidence_road_control_ratio"]
    assert not result["gates"]["network_swsd_fallback_ratio"]


def test_independent_quality_rejects_unproven_reversed_duplicate_pair(
    tmp_path: Path,
) -> None:
    _write_package(tmp_path, add_collapsed_split=True)

    result = run_high_precision_independent_quality(tmp_path)

    assert not result["gate_pass"]
    assert result["corridor"]["split_violation_count"] == 1
    assert not result["gates"]["physical_directional_split_evidence"]


def _write_package(
    root: Path,
    *,
    observed_fraction: float = 0.8,
    inflate_observed: bool = False,
    add_collapsed_split: bool = False,
) -> None:
    crs = "EPSG:32650"
    road_rows = []
    parent_rows = []
    decision_rows = []
    observation_rows = []
    station_rows = []
    segment_rows = []
    portal_rows = []
    arm_rows = []
    for index, (road_id, parent_id, start, end, snode, enode) in enumerate(
        (
            ("v1", "p1", 0.0, 10.0, "n1", "n2"),
            ("v2", "p2", 10.0, 20.0, "n2", "n3"),
        )
    ):
        geometry = LineString([(start, 0), (end, 0)])
        observed_end = start + (end - start) * observed_fraction
        observed_length = geometry.length * observed_fraction
        declared_observed = observed_length + (1.0 if inflate_observed and index == 0 else 0.0)
        fallback_length = geometry.length - observed_length
        road_rows.append(
            {
                "run_id": "quality-v3",
                "v3_road_id": road_id,
                "parent_swsd_unit_id": parent_id,
                "travel_side": "shared",
                "support_state": "partial_hp_supported",
                "snode_id": snode,
                "enode_id": enode,
                "observed_length_m": declared_observed,
                "constrained_length_m": 0.0,
                "swsd_fallback_length_m": fallback_length,
                "geometry": geometry,
            }
        )
        parent_rows.append({"swsd_unit_id": parent_id, "geometry": geometry})
        decision_rows.append(
            {
                "parent_swsd_unit_id": parent_id,
                "decision": "shared",
                "separation_gate_pass": False,
                "continuity_gate_pass": False,
                "required_min_separation_m": 1.5,
                "anchor_median_separation_m": 0.0,
                "geometry": geometry,
            }
        )
        observation_rows.append(
            {
                "v3_road_id": road_id,
                "station_fraction": observed_fraction / 2.0,
                "observation_quality_state": "usable",
                "geometry": Point(start + observed_length / 2.0, 0),
            }
        )
        station_rows.extend(
            [
                {
                    "v3_road_id": road_id,
                    "station_fraction": 0.0,
                    "direct_observation": True,
                    "geometry_source": "hp_observed",
                    "geometry": Point(start, 0),
                },
                {
                    "v3_road_id": road_id,
                    "station_fraction": observed_fraction,
                    "direct_observation": True,
                    "geometry_source": "hp_observed",
                    "geometry": Point(observed_end, 0),
                },
                {
                    "v3_road_id": road_id,
                    "station_fraction": 1.0,
                    "direct_observation": False,
                    "geometry_source": "swsd_fallback",
                    "geometry": Point(end, 0),
                },
            ]
        )
        segment_rows.extend(
            [
                {
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": parent_id,
                    "segment_id": f"{road_id}:0",
                    "start_fraction": 0.0,
                    "end_fraction": observed_fraction,
                    "length_m": observed_length,
                    "geometry_source": "hp_observed",
                    "geometry": LineString([(start, 0), (observed_end, 0)]),
                },
                {
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": parent_id,
                    "segment_id": f"{road_id}:1",
                    "start_fraction": observed_fraction,
                    "end_fraction": 1.0,
                    "length_m": fallback_length,
                    "geometry_source": "swsd_fallback",
                    "geometry": LineString([(observed_end, 0), (end, 0)]),
                },
            ]
        )
        for endpoint, x, node in (("s", start, snode), ("e", end, enode)):
            portal_rows.append(
                {
                    "v3_portal_id": f"{road_id}:{endpoint}",
                    "v3_road_id": road_id,
                    "endpoint": endpoint,
                    "parent_physical_node_id": node,
                    "geometry": Point(x, 0),
                }
            )
            arm_rows.append(
                {
                    "v3_arm_id": f"{road_id}:{endpoint}",
                    "v3_portal_id": f"{road_id}:{endpoint}",
                    "v3_road_id": road_id,
                    "endpoint": endpoint,
                    "geometry": LineString([(x, 0), (x + (1 if endpoint == "s" else -1), 0)]),
                }
            )

    if add_collapsed_split:
        parent_rows.append(
            {"swsd_unit_id": "pc", "geometry": LineString([(0, 5), (10, 5)])}
        )
        decision_rows.append(
            {
                "parent_swsd_unit_id": "pc",
                "decision": "split",
                "separation_gate_pass": False,
                "continuity_gate_pass": True,
                "required_min_separation_m": 1.5,
                "anchor_median_separation_m": 0.1,
                "geometry": LineString([(0, 5), (10, 5)]),
            }
        )
        for side, geometry, snode, enode in (
            ("forward", LineString([(0, 5), (10, 5)]), "c1", "c2"),
            ("reverse", LineString([(10, 5), (0, 5)]), "c2", "c1"),
        ):
            road_id = f"pc:{side}"
            road_rows.append(
                {
                    "run_id": "quality-v3",
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": "pc",
                    "travel_side": side,
                    "support_state": "hp_supported",
                    "snode_id": snode,
                    "enode_id": enode,
                    "observed_length_m": 10.0,
                    "constrained_length_m": 0.0,
                    "swsd_fallback_length_m": 0.0,
                    "geometry": geometry,
                }
            )
            observation_rows.append(
                {
                    "v3_road_id": road_id,
                    "station_fraction": 0.5,
                    "observation_quality_state": "usable",
                    "geometry": geometry.interpolate(0.5, normalized=True),
                }
            )
            station_rows.append(
                {
                    "v3_road_id": road_id,
                    "station_fraction": 0.5,
                    "direct_observation": True,
                    "geometry_source": "hp_observed",
                    "geometry": geometry.interpolate(0.5, normalized=True),
                }
            )
            segment_rows.append(
                {
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": "pc",
                    "segment_id": f"{road_id}:0",
                    "start_fraction": 0.0,
                    "end_fraction": 1.0,
                    "length_m": 10.0,
                    "geometry_source": "hp_observed",
                    "geometry": geometry,
                }
            )
            for endpoint, point, node in (
                ("s", Point(geometry.coords[0]), snode),
                ("e", Point(geometry.coords[-1]), enode),
            ):
                portal_rows.append(
                    {
                        "v3_portal_id": f"{road_id}:{endpoint}",
                        "v3_road_id": road_id,
                        "endpoint": endpoint,
                        "parent_physical_node_id": node,
                        "geometry": point,
                    }
                )
                arm_rows.append(
                    {
                        "v3_arm_id": f"{road_id}:{endpoint}",
                        "v3_portal_id": f"{road_id}:{endpoint}",
                        "v3_road_id": road_id,
                        "endpoint": endpoint,
                        "geometry": LineString([point, geometry.interpolate(1.0)]),
                    }
                )

    roads = gpd.GeoDataFrame(road_rows, crs=crs)
    parents = gpd.GeoDataFrame(parent_rows, crs=crs)
    decisions = gpd.GeoDataFrame(decision_rows, crs=crs)
    observations = gpd.GeoDataFrame(observation_rows, crs=crs)
    stations = gpd.GeoDataFrame(station_rows, crs=crs)
    segments = gpd.GeoDataFrame(segment_rows, crs=crs)
    portals = gpd.GeoDataFrame(portal_rows, crs=crs)
    arms = gpd.GeoDataFrame(arm_rows, crs=crs)
    movements = gpd.GeoDataFrame(
        [
            {
                "run_id": "quality-v3",
                "v3_movement_id": "m1",
                "source_v3_road_id": "v1",
                "target_v3_road_id": "v2",
                "junction_relation": "same_physical_node",
                "geometry_source": "lane_topo_projected",
                "geometry": LineString([(9.5, 0), (10, 0), (10.5, 0)]),
            }
        ],
        crs=crs,
    )
    evidence_links = gpd.GeoDataFrame(
        [
            {
                "link_id": "lt1",
                "source_v3_road_id": "v1",
                "target_v3_road_id": "v2",
                "projection_state": "confirmed",
                "geometry": LineString([(9, 0), (11, 0)]),
            }
        ],
        crs=crs,
    )
    write_gpkg_layers(root / "p04_hp_v3_roads.gpkg", {"high_precision_roads": roads})
    write_gpkg_layers(
        root / "p04_hp_v3_corridors.gpkg",
        {
            "physical_corridor_decisions": decisions,
            "center_observations": observations,
        },
    )
    write_gpkg_layers(
        root / "p04_hp_v3_geometry_sources.gpkg",
        {"geometry_segments": segments, "fit_stations": stations},
    )
    write_gpkg_layers(
        root / "p04_hp_v3_road_graph.gpkg",
        {
            "parent_swsd_roads": parents,
            "high_precision_portals": portals,
            "high_precision_arms": arms,
            "high_precision_movements": movements,
            "movement_evidence_links": evidence_links,
        },
    )
