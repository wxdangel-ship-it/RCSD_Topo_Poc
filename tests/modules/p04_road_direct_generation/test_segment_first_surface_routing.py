from __future__ import annotations

import json

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carriers import (
    _complete_target_assembly_to_endpoint_surfaces,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_corridors import (
    CorridorAssembly,
    _max_sample_turn,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry import (
    _smooth_centerline,
)
from rcsd_topo_poc.modules.p04_road_direct_generation import (
    segment_first_surface_routing as surface_routing,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_surface_routing import (
    interior_surface_target,
    interior_target_cache_stats,
    reset_interior_target_cache,
    route_endpoint_to_surface,
    route_tangent_endpoint_to_surface,
)


def _bent_support() -> object:
    return unary_union(
        [
            box(-6, -2, 10, 2),
            box(6, -2, 10, 12),
            box(6, 8, 15, 12),
        ]
    )


def test_interior_surface_target_reuses_exact_buffered_geometry() -> None:
    reset_interior_target_cache()
    surface = box(0, 0, 20, 20)

    first = interior_surface_target(surface, inset_m=1.0)
    second = interior_surface_target(surface, inset_m=1.0)

    assert second is first
    assert first.equals_exact(surface.buffer(-1.0), tolerance=0.0)
    assert interior_target_cache_stats() == {
        "query_count": 2,
        "hit_count": 1,
        "hit_ratio": 0.5,
        "eviction_count": 0,
        "entry_count": 1,
        "entry_count_max": 8192,
        "key_bytes": len(surface.wkb) + 8,
        "key_bytes_max": 32 * 1024 * 1024,
    }


def test_interior_surface_target_cache_evicts_within_entry_bound(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        surface_routing,
        "_INTERIOR_TARGET_CACHE_ENTRY_MAX",
        2,
    )
    reset_interior_target_cache()

    for offset in range(3):
        interior_surface_target(box(offset, 0, offset + 10, 10), inset_m=1.0)

    stats = interior_target_cache_stats()
    assert stats["entry_count"] == 2
    assert stats["entry_count_max"] == 2
    assert stats["eviction_count"] == 1
    reset_interior_target_cache()


def test_endpoint_route_follows_local_road_surface_when_direct_line_leaves_it() -> None:
    endpoint = Point(0, 0)
    target = box(14, 9, 16, 11)
    support = _bent_support()
    direct = LineString([endpoint, Point(14, 9)])
    assert direct.intersection(support.union(target)).length / direct.length < 0.90

    routed = route_endpoint_to_surface(
        endpoint,
        target,
        support,
        maximum_distance_m=30.0,
        minimum_coverage=0.90,
    )

    assert routed is not None
    assert routed.is_simple
    assert Point(routed.coords[0]).equals(endpoint)
    assert Point(routed.coords[-1]).distance(target) <= 1e-9
    assert routed.intersection(support.union(target)).length / routed.length >= 0.90


def test_endpoint_route_rejects_disconnected_or_excessive_detour() -> None:
    endpoint = Point(0, 0)
    target = box(14, 9, 16, 11)
    disconnected = unary_union([box(-1, -1, 2, 1), target])
    assert (
        route_endpoint_to_surface(
            endpoint,
            target,
            disconnected,
            maximum_distance_m=30.0,
            minimum_coverage=0.90,
        )
        is None
    )

    long_detour = unary_union(
        [
            box(-1, -1, 21, 1),
            box(19, -1, 21, 21),
            box(0, 19, 21, 21),
        ]
    )
    close_target = box(-1, 19, 1, 21)
    assert (
        route_endpoint_to_surface(
            endpoint,
            close_target,
            long_detour,
            maximum_distance_m=25.0,
            minimum_coverage=0.90,
        )
        is None
    )


def test_tangent_endpoint_route_uses_independent_portal_inside_surface() -> None:
    geometry = LineString([(0, 0), (10, 0), (20, 0)])
    target = box(29, -5, 35, 5)
    support = box(-1, -2, 36, 2)

    routed = route_tangent_endpoint_to_surface(
        geometry,
        "end",
        target,
        support,
        maximum_distance_m=20.0,
        minimum_coverage=0.90,
    )

    assert routed is not None
    assert list(routed.coords) == [(20.0, 0.0), (29.0, 0.0)]
    assert Point(routed.coords[-1]).distance(target) <= 1e-9


def test_corridor_completion_records_surface_routing_without_swsd_splice() -> None:
    observed = LineString([(-5, 0), (0, 0)])
    assembly = CorridorAssembly(
        geometry=observed,
        direction_role="forward",
        observed_coverage_ratio=1.0,
        completion_fraction=0.0,
        source_patch_road_keys=("patch:road",),
        start_patch_road_keys=("patch:road",),
        end_patch_road_keys=("patch:road",),
        source_patch_ids=("patch",),
        source_lane_ids=("lane",),
        evidence_spans_json=json.dumps(
            [
                {
                    "geometry_source": "hp_observed",
                    "source_object_ids": "patch:road",
                    "start_fraction": 0.0,
                    "end_fraction": 1.0,
                }
            ]
        ),
        assembly_state="single_patch_observation",
    )
    target = box(14, 9, 16, 11)

    completed = _complete_target_assembly_to_endpoint_surfaces(
        assembly,
        (target,),
        completion_surface=_bent_support(),
        maximum_distance_m=30.0,
        minimum_surface_coverage=0.90,
    )

    assert completed is not None
    assert completed.geometry.is_simple
    assert Point(completed.geometry.coords[-1]).distance(target) <= 1e-9
    assert "endpoint_surface_constrained_routing" in completed.assembly_state
    assert _max_sample_turn(completed.geometry, 2.0) <= 75.0
    spans = json.loads(completed.evidence_spans_json)
    assert {span["geometry_source"] for span in spans} == {
        "hp_observed",
        "hp_constrained_completion",
    }
    assert all("swsd" not in span["geometry_source"].lower() for span in spans)
    smoothed, _ = _smooth_centerline(
        completed.geometry,
        spacing=2.0,
        max_deviation=1.5,
    )
    support = _bent_support().union(target)
    assert smoothed.intersection(support).length / smoothed.length >= 0.90
