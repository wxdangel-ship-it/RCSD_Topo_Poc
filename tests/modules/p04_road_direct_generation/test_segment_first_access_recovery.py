from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_access_recovery import (
    annotate_recovery_carrier_conflicts,
    build_access_surface_recovery_candidates,
    build_required_endpoint_surfaces,
    build_required_through_surfaces,
    recoordinate_access_recovery_assignments,
)


def test_patch_road_connecting_both_endpoint_surfaces_becomes_isolated_candidate() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "target_required": True,
                "target_class": "core_trunk",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    centers = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p:through",
                "source_patch_id": "p",
                "road_id": "through",
                "geometry": LineString([(-10, 2), (110, 2)]),
            },
            {
                "patch_road_key": "p:one-end-only",
                "source_patch_id": "p",
                "road_id": "one-end-only",
                "geometry": LineString([(-10, 6), (30, 6)]),
            },
        ],
        crs=segments.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            _access("start", 0, "j1", Point(0, 0)),
            _access("end", 1, "j2", Point(100, 0)),
        ],
        crs=segments.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {"junction_group_id": "j1", "geometry": box(-2, -4, 2, 4)},
            {"junction_group_id": "j2", "geometry": box(98, -4, 102, 4)},
        ],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-20, -10, 120, 10)}],
        crs=segments.crs,
    )

    result = build_access_surface_recovery_candidates(
        segments,
        centers,
        accesses,
        junctions,
        drivezones,
        run_id="run",
        maximum_surface_distance_m=5.0,
        minimum_drivezone_coverage=0.90,
    )

    assert list(result["patch_road_key"]) == ["p:through"]
    assert result.iloc[0]["takeover_eligible"] == False
    assert result.iloc[0]["assignment_source"] == "target_access_surface_candidate"
    assert 95.0 <= result.iloc[0].geometry.length <= 105.0


def test_recovery_candidate_cannot_reuse_published_carrier_in_another_segment() -> None:
    candidates = gpd.GeoDataFrame(
        [
            {
                "assigned_segment_id": "candidate",
                "patch_road_key": "p:r1",
                "assignment_state": "access_surface_recovery_candidate",
                "reason_codes": "candidate",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    carriers = gpd.GeoDataFrame(
        [
            {
                "segment_id": "published",
                "realization": "built",
                "source_patch_road_keys": "p:r1",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs=candidates.crs,
    )

    result = annotate_recovery_carrier_conflicts(candidates, carriers)

    assert result.iloc[0]["recovery_eligible"] == False
    assert result.iloc[0]["recovery_conflict_segment_ids"] == "published"
    assert result.iloc[0]["assignment_state"] == "access_surface_recovery_conflict"


def test_recovery_candidate_allows_only_short_endpoint_handoff_overlap() -> None:
    candidates = gpd.GeoDataFrame(
        [
            {
                "assigned_segment_id": "candidate",
                "patch_road_key": "p:r1",
                "assignment_state": "access_surface_recovery_candidate",
                "reason_codes": "candidate",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    carriers = gpd.GeoDataFrame(
        [
            {
                "segment_id": "published",
                "realization": "built",
                "source_patch_road_keys": "p:r1",
                "geometry": LineString([(-20, 0), (2, 0)]),
            }
        ],
        crs=candidates.crs,
    )

    result = annotate_recovery_carrier_conflicts(candidates, carriers)

    assert result.iloc[0]["recovery_eligible"] == True
    assert result.iloc[0]["recovery_conflict_segment_ids"] == ""


def test_fallback_recoordination_releases_only_retained_segment_conflict() -> None:
    candidates = gpd.GeoDataFrame(
        [
            {
                "assigned_segment_id": "candidate",
                "assignment_fragment_id": "candidate:r1",
                "patch_road_key": "p:r1",
                "assignment_state": "access_surface_recovery_conflict",
                "assignment_source": "target_access_surface_candidate",
                "reason_codes": (
                    "candidate;published_carrier_source_overlap"
                ),
                "recovery_eligible": False,
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "assigned_segment_id": "candidate",
                "assignment_fragment_id": "candidate:r2",
                "patch_road_key": "p:r2",
                "assignment_state": "access_surface_recovery_conflict",
                "assignment_source": "target_access_surface_candidate",
                "reason_codes": (
                    "candidate;published_carrier_source_overlap"
                ),
                "recovery_eligible": False,
                "geometry": LineString([(0, 5), (20, 5)]),
            },
        ],
        crs="EPSG:32650",
    )
    base_assignments = candidates.iloc[0:0].copy()
    carriers = gpd.GeoDataFrame(
        [
            {
                "segment_id": "retained",
                "realization": "built",
                "source_patch_road_keys": "p:r1",
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "segment_id": "active",
                "realization": "built",
                "source_patch_road_keys": "p:r2",
                "geometry": LineString([(0, 5), (20, 5)]),
            },
        ],
        crs=candidates.crs,
    )

    coordinated, planning, newly_eligible = (
        recoordinate_access_recovery_assignments(
            candidates,
            base_assignments,
            carriers,
            forced_retained_segment_ids={"retained"},
        )
    )

    by_key = coordinated.set_index("patch_road_key")
    assert by_key.loc["p:r1", "recovery_eligible"] == True
    assert (
        by_key.loc["p:r1", "recovery_released_conflict_segment_ids"]
        == "retained"
    )
    assert (
        "recovery_conflict_released_after_segment_fallback"
        in by_key.loc["p:r1", "reason_codes"]
    )
    assert by_key.loc["p:r2", "recovery_eligible"] == False
    assert by_key.loc["p:r2", "recovery_conflict_segment_ids"] == "active"
    assert set(planning["assignment_fragment_id"]) == {"candidate:r1"}
    assert newly_eligible == frozenset({"candidate:r1"})

    coordinated_again, _, newly_eligible_again = (
        recoordinate_access_recovery_assignments(
            coordinated,
            base_assignments,
            carriers[carriers["segment_id"].eq("active")],
            forced_retained_segment_ids={"retained"},
        )
    )
    persisted = coordinated_again.set_index("patch_road_key").loc["p:r1"]
    assert persisted["recovery_released_conflict_segment_ids"] == "retained"
    assert (
        "recovery_conflict_released_after_segment_fallback"
        in persisted["reason_codes"]
    )
    assert newly_eligible_again == frozenset()


def test_required_through_surfaces_preserve_access_identity() -> None:
    accesses = gpd.GeoDataFrame(
        [
            _access("endpoint", 0, "j1", Point(0, 0))
            | {"access_type": "ENDPOINT"},
            _access("through", 1, "j2", Point(10, 0))
            | {"access_type": "THROUGH"},
        ],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [
            {"junction_group_id": "j1", "geometry": box(-1, -1, 1, 1)},
            {"junction_group_id": "j2", "geometry": box(9, -1, 11, 1)},
        ],
        crs=accesses.crs,
    )

    result = build_required_through_surfaces(
        accesses,
        junctions,
        endpoint_inset_m=0.5,
    )

    assert list(result["access_id"]) == ["through"]
    assert list(result["junction_group_id"]) == ["j2"]
    assert junctions.iloc[1].geometry.contains(result.iloc[0].geometry)


def test_required_endpoint_surfaces_use_only_accepted_physical_boundaries() -> None:
    accesses = gpd.GeoDataFrame(
        [
            _access("endpoint-a", 0, "j1", Point(0, 0)),
            _access("endpoint-b", 1, "j2", Point(20, 0)),
            _access("endpoint-swsd", 2, "j3", Point(40, 0)),
        ],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j1",
                "junction_source": "t07_accepted",
                "geometry": box(-2, -2, 2, 2),
            },
            {
                "junction_group_id": "j2",
                "junction_source": "t03_accepted",
                "geometry": box(18, -2, 22, 2),
            },
            {
                "junction_group_id": "j3",
                "junction_source": "swsd_retained",
                "geometry": Point(40, 0),
            },
        ],
        crs=accesses.crs,
    )

    result = build_required_endpoint_surfaces(
        accesses,
        junctions,
        endpoint_inset_m=1.0,
    )

    assert list(result["access_id"]) == ["endpoint-a", "endpoint-b"]
    assert list(result["junction_group_id"]) == ["j1", "j2"]
    assert all(result.geometry.area == 4.0)
    assert junctions.iloc[0].geometry.contains(result.iloc[0].geometry)
    assert junctions.iloc[1].geometry.contains(result.iloc[1].geometry)


def _access(
    access_id: str,
    ordinal: int,
    group_id: str,
    geometry: Point,
) -> dict[str, object]:
    return {
        "access_id": access_id,
        "segment_id": "s1",
        "access_type": "ENDPOINT",
        "access_ordinal": ordinal,
        "junction_group_id": group_id,
        "geometry": geometry,
    }
