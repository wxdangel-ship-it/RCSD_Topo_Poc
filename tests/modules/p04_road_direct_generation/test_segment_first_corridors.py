from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, box

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    segment_first_corridors as corridor_module,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carriers import (
    plan_segment_carriers,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_corridors import (
    _max_sample_turn,
    assemble_directional_corridor,
    corridor_assembly_cache_stats,
    reset_corridor_assembly_cache,
)


def _evidence(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32650")


def test_member_fragments_are_assembled_as_one_directional_road() -> None:
    reference = LineString([(0, 0), (100, 0)])
    evidence = _evidence(
        [
            {
                "patch_road_key": "p:1",
                "source_patch_id": "p",
                "center_lane_id": "l1",
                "geometry": LineString([(0, 2), (60, 2)]),
            },
            {
                "patch_road_key": "p:2",
                "source_patch_id": "p",
                "center_lane_id": "l2",
                "geometry": LineString([(40, 4), (100, 4)]),
            },
        ]
    )
    result = assemble_directional_corridor(
        evidence,
        reference,
        direction_role="forward",
        drivezone_surface=box(-5, -5, 105, 10),
        minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )
    assert result is not None
    assert result.source_patch_road_keys == ("p:1", "p:2")
    assert result.geometry.length > 95.0
    assert 2.0 <= result.geometry.interpolate(0.5, normalized=True).y <= 4.0


def test_corridor_assembly_cache_reuses_value_equivalent_evidence() -> None:
    reset_corridor_assembly_cache()
    reference = LineString([(0, 0), (100, 0)])
    surface = box(-5, -5, 105, 10)
    evidence = _evidence(
        [
            {
                "patch_road_key": "p:1",
                "source_patch_id": "p",
                "center_lane_id": "l1",
                "geometry": LineString([(0, 2), (60, 2)]),
            },
            {
                "patch_road_key": "p:2",
                "source_patch_id": "p",
                "center_lane_id": "l2",
                "geometry": LineString([(40, 4), (100, 4)]),
            },
        ]
    )
    first = assemble_directional_corridor(
        evidence,
        reference,
        direction_role="forward",
        drivezone_surface=surface,
        minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )
    second = assemble_directional_corridor(
        evidence.copy(),
        reference,
        direction_role="forward",
        drivezone_surface=surface,
        minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )
    changed_parameter = assemble_directional_corridor(
        evidence.copy(),
        reference,
        direction_role="forward",
        drivezone_surface=surface,
        minimum_coverage=0.60,
        sample_spacing_m=1.5,
        completion_min_coverage=0.90,
    )
    stats = corridor_assembly_cache_stats()

    assert first is not None
    assert second is first
    assert changed_parameter is not None
    assert stats["query_count"] == 3
    assert stats["hit_count"] == 1
    assert stats["miss_count"] == 2
    assert stats["entry_count"] == 2
    assert stats["key_bytes"] > 0
    reset_corridor_assembly_cache()


def test_corridor_assembly_cache_evicts_at_configured_entry_bound(
    monkeypatch,
) -> None:
    reset_corridor_assembly_cache()
    monkeypatch.setattr(corridor_module, "_CORRIDOR_ASSEMBLY_CACHE_MAXSIZE", 1)
    reference = LineString([(0, 0), (100, 0)])
    surface = box(-5, -5, 105, 10)
    evidence = _evidence(
        [
            {
                "patch_road_key": "p:1",
                "source_patch_id": "p",
                "center_lane_id": "l1",
                "geometry": LineString([(0, 2), (100, 2)]),
            }
        ]
    )

    assemble_directional_corridor(
        evidence,
        reference,
        direction_role="forward",
        drivezone_surface=surface,
        minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )
    assemble_directional_corridor(
        evidence,
        reference,
        direction_role="forward",
        drivezone_surface=surface,
        minimum_coverage=0.60,
        sample_spacing_m=1.5,
        completion_min_coverage=0.90,
    )
    stats = corridor_assembly_cache_stats()

    assert stats["entry_count"] == 1
    assert stats["entry_count_max"] == 1
    assert stats["eviction_count"] == 1
    reset_corridor_assembly_cache()


def test_bidirectional_member_requires_both_observed_roles() -> None:
    segments = _evidence(
        [{"segment_id": "s", "swsd_road_ids": "r", "geometry": LineString([(0, 0), (100, 0)])}]
    )
    swsd = _evidence(
        [{"id": "r", "segmentid": "s", "direction": 1, "geometry": LineString([(0, 0), (100, 0)])}]
    )
    forward_only = _evidence(
        [
            {
                "patch_road_key": "p:1",
                "source_patch_id": "p",
                "assigned_segment_id": "s",
                "target_swsd_road_id": "r",
                "carrier_role": "directional_corridor",
                "takeover_eligible": True,
                "geometry": LineString([(0, 2), (100, 2)]),
            }
        ]
    )
    retained = plan_segment_carriers(segments, swsd, forward_only, run_id="run")
    assert retained.segment_plans.iloc[0]["segment_state"] == "swsd_retained"
    assert set(retained.carriers["realization"]) == {"retained"}

    both = pd.concat(
        [
            forward_only,
            _evidence(
                [
                    {
                        "patch_road_key": "p:2",
                        "source_patch_id": "p",
                        "assigned_segment_id": "s",
                        "target_swsd_road_id": "r",
                        "carrier_role": "directional_corridor",
                        "takeover_eligible": True,
                        "geometry": LineString([(100, -2), (0, -2)]),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    both = gpd.GeoDataFrame(both, geometry="geometry", crs="EPSG:32650")
    built = plan_segment_carriers(segments, swsd, both, run_id="run")
    assert built.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert len(built.carriers) == 2
    assert set(built.carriers["carrier_role"]) == {"main_forward", "main_reverse"}


def test_internal_gap_outside_drivezone_cannot_be_completed() -> None:
    reference = LineString([(0, 0), (100, 0)])
    evidence = _evidence(
        [
            {"patch_road_key": "p:1", "source_patch_id": "p", "geometry": LineString([(0, 0), (40, 0)])},
            {"patch_road_key": "p:2", "source_patch_id": "p", "geometry": LineString([(60, 0), (100, 0)])},
        ]
    )
    result = assemble_directional_corridor(
        evidence,
        reference,
        direction_role="forward",
        drivezone_surface=box(-5, -5, 45, 5),
        minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )
    assert result is None


def test_single_reverse_observation_keeps_lane_travel_orientation() -> None:
    reference = LineString([(0, 0), (100, 0)])
    source = LineString([(100, -2), (0, -2)])
    result = assemble_directional_corridor(
        _evidence(
            [{"patch_road_key": "p:reverse", "source_patch_id": "p", "geometry": source}]
        ),
        reference,
        direction_role="reverse",
        drivezone_surface=box(-5, -5, 105, 5),
        minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )
    assert result is not None
    assert result.geometry.coords[0] == source.coords[0]
    assert result.geometry.coords[-1] == source.coords[-1]


def test_bad_semantic_axis_cannot_fold_continuous_patch_evidence_back() -> None:
    reference = LineString(
        [
            (0.069, 1.699),
            (75.226, -15.679),
            (82.900, -16.027),
            (90.766, -4.578),
            (90.018, 0.090),
            (83.546, 4.395),
            (43.004, 15.820),
            (13.295, 29.298),
        ]
    )
    evidence = _evidence(
        [
            {
                "patch_road_key": "p:road:1",
                "road_id": "road-1",
                "source_patch_id": "p",
                "geometry": LineString(
                    [(-10.368, -30.802), (-2.106, -14.458), (0.0, 0.0)]
                ),
            },
            {
                "patch_road_key": "p:lane:1",
                "road_id": "road-1",
                "source_patch_id": "p",
                "geometry": LineString([(-8.233, -21.163), (0.0, 0.0)]),
            },
            {
                "patch_road_key": "p:road:2",
                "road_id": "road-2",
                "source_patch_id": "p",
                "geometry": LineString(
                    [(3.645, 10.602), (7.722, 21.643), (16.842, 41.200)]
                ),
            },
        ]
    )

    result = assemble_directional_corridor(
        evidence,
        reference,
        direction_role="forward",
        drivezone_surface=box(-20, -40, 30, 50),
        minimum_coverage=0.0,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
    )

    assert result is not None
    assert result.assembly_state == "observed_chain_with_constrained_completion"
    assert result.geometry.coords[0] == (-10.368, -30.802)
    assert result.geometry.coords[-1] == (16.842, 41.2)
    assert _max_sample_turn(result.geometry, 2.0) <= 75.0
