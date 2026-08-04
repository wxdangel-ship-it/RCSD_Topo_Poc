from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carrier_context import (
    carrier_context_cache_stats,
    prepare_assignment_context,
    reservation_overlap_fraction,
    reset_carrier_context_cache,
)


def _assignments() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "assigned_segment_id": "segment-1",
                "target_swsd_road_id": "road-1",
                "assignment_source": "target_access_surface_candidate",
                "takeover_eligible": False,
                "carrier_role": "directional_corridor",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "assigned_segment_id": "segment-2",
                "target_swsd_road_id": "road-2",
                "assignment_source": "target_access_surface_candidate",
                "takeover_eligible": False,
                "carrier_role": "directional_corridor",
                "geometry": LineString([(0, 0.5), (10, 0.5)]),
            },
        ],
        crs="EPSG:32650",
    )


def test_assignment_context_reuses_same_live_frame() -> None:
    reset_carrier_context_cache()
    assignments = _assignments()

    first = prepare_assignment_context(assignments)
    second = prepare_assignment_context(assignments)
    stats = carrier_context_cache_stats()

    assert second is first
    assert stats["carrier_context_cache_hit_count"] == 1
    assert stats["carrier_context_cache_miss_count"] == 1
    assert stats["carrier_context_cache_entry_count"] == 1


def test_prebuffered_reservation_index_preserves_exclusion_overlap() -> None:
    reset_carrier_context_cache()
    assignments = _assignments()
    context = prepare_assignment_context(assignments)
    candidate = LineString([(0, 0), (10, 0)])
    expected = max(
        (
            float(candidate.intersection(row.geometry.buffer(1.0)).length)
            / float(candidate.length)
            for row in assignments.itertuples(index=False)
            if str(row.assigned_segment_id) != "segment-1"
        ),
        default=0.0,
    )

    actual = reservation_overlap_fraction(
        candidate,
        context.access_reservation_buffers,
        excluded_segment_id="segment-1",
        prebuffered=True,
    )

    assert actual == expected


def test_raw_reservation_index_matches_original_full_scan() -> None:
    reservations = _assignments()
    candidate = LineString([(0, 0), (10, 0)])
    expected = max(
        float(candidate.intersection(geometry.buffer(1.0)).length)
        / float(candidate.length)
        for geometry in reservations.geometry
    )

    assert reservation_overlap_fraction(candidate, reservations) == expected
