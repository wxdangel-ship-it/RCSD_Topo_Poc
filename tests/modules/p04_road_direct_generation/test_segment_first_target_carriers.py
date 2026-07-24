from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carriers import (
    _select_directed_target_path,
    _target_access_support_carriers,
    plan_segment_carriers,
)


def test_target_segment_builds_main_roles_from_patch_fragments_not_swsd_length() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (1000, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (1000, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("p1:forward", [(0, 2), (40, 2)]),
            _fragment("p1:reverse", [(40, -2), (0, -2)]),
        ],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="target-carrier",
        minimum_member_coverage=0.60,
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert set(result.carriers["carrier_role"]) == {
        "main_forward",
        "main_reverse",
    }
    assert set(result.carriers["realization"]) == {"built"}
    assert set(result.carriers["geometry_source"]) == {"hp_observed"}
    assert max(result.carriers.geometry.length) == 40.0


def test_target_component_uses_spatial_endpoint_keys_not_lexical_key_order() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "advance_right",
                "target_class": "advance_right",
                "target_required": True,
                "sgrade": "0-0单",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 2,
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("z-start", [(0, 0), (10, 0)]),
            _fragment("m-middle", [(10, 0), (20, 0)]),
            _fragment("a-end", [(20, 0), (30, 0)]),
            _fragment("contaminant", [(0, 5), (30, 5)]),
        ],
        crs=segments.crs,
    )
    explicit_pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "z-start",
                "target_patch_road_key": "m-middle",
            },
            {
                "source_patch_road_key": "m-middle",
                "target_patch_road_key": "a-end",
            },
        ]
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="target-carrier-endpoints",
        explicit_pairs=explicit_pairs,
        minimum_member_coverage=0.60,
    )

    carrier = result.carriers.iloc[0]
    assert carrier["start_patch_road_keys"] == "z-start"
    assert carrier["end_patch_road_keys"] == "a-end"
    assert carrier["source_patch_road_keys"] == "a-end,m-middle,z-start"
    assert carrier["source_object_type"] == "PATCH_TARGET_SEGMENT_CORRIDOR"
    assert carrier["segment_type"] == "advance_right"
    assert carrier["target_class"] == "advance_right"
    assert carrier["observed_coverage_ratio"] == 1.0


def test_target_path_scores_all_fragments_for_the_same_patch_key() -> None:
    evidence = gpd.GeoDataFrame(
        [
            _fragment("dup", [(0, 0), (5, 0)]),
            _fragment("dup", [(25, 0), (30, 0)]),
            _fragment("middle", [(5, 0), (25, 0)]),
            _fragment("distractor", [(0, 2), (30, 2)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "dup",
                "target_patch_road_key": "middle",
            }
        ]
    )

    selected = _select_directed_target_path(
        evidence,
        LineString([(0, 0), (30, 0)]),
        pairs,
    )

    assert set(selected["patch_road_key"]) == {"dup", "middle"}
    assert len(selected) == 3


def test_target_reference_axis_controls_roles_without_becoming_output_geometry() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (0, 40)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (0, 40)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("forward", [(0, 2), (40, 2)]),
            _fragment("reverse", [(40, -2), (0, -2)]),
        ],
        crs=segments.crs,
    )
    axes = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="target-reference-axis",
        target_reference_axes=axes,
    )

    assert set(result.carriers["carrier_role"]) == {
        "main_forward",
        "main_reverse",
    }
    assert set(result.carriers.geometry.apply(lambda line: round(line.centroid.y))) == {
        -2,
        2,
    }


def test_target_path_prefers_formal_through_surface_coverage() -> None:
    evidence = gpd.GeoDataFrame(
        [
            _fragment("start", [(0, 0), (8, 0)]),
            _fragment("end", [(10, 0), (18, 0)]),
            _fragment("bypass", [(0, 5), (20, 5)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "start",
                "target_patch_road_key": "end",
            }
        ]
    )

    selected = _select_directed_target_path(
        evidence,
        LineString([(0, 0), (20, 0)]),
        pairs,
        required_surfaces=(box(7, -1, 11, 1),),
        surface_max_distance_m=0.0,
    )

    assert set(selected["patch_road_key"]) == {"start", "end"}


def test_target_path_keeps_disconnected_patch_evidence_for_surface_completion() -> None:
    evidence = gpd.GeoDataFrame(
        [
            _fragment("patch-a", [(0, 2), (15, 2)]),
            _fragment("patch-b", [(25, 2), (40, 2)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch-a",
                "target_patch_road_key": "patch-a",
            }
        ]
    )

    selected = _select_directed_target_path(
        evidence,
        LineString([(0, 0), (40, 0)]),
        pairs,
        required_surfaces=(
            box(-1, -3, 2, 4),
            box(38, -3, 41, 4),
        ),
        surface_max_distance_m=0.0,
    )

    assert set(selected["patch_road_key"]) == {"patch-a", "patch-b"}


def test_target_path_selection_does_not_expand_with_completion_distance() -> None:
    evidence = gpd.GeoDataFrame(
        [
            _fragment("long-observed", [(0, 0), (75, 0)]),
            _fragment("portal-start", [(0, 2), (20, 2)]),
            _fragment("portal-end", [(80, 2), (100, 2)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "portal-start",
                "target_patch_road_key": "portal-end",
            }
        ]
    )
    surfaces = (
        box(-2, -3, 2, 4),
        box(98, -3, 102, 4),
    )

    relation_scoped = _select_directed_target_path(
        evidence,
        LineString([(0, 0), (100, 0)]),
        pairs,
        required_surfaces=surfaces,
        surface_max_distance_m=20.0,
    )
    completion_scoped = _select_directed_target_path(
        evidence,
        LineString([(0, 0), (100, 0)]),
        pairs,
        required_surfaces=surfaces,
        surface_max_distance_m=50.0,
    )

    assert set(relation_scoped["patch_road_key"]) == {
        "portal-start",
        "portal-end",
    }
    assert set(completion_scoped["patch_road_key"]) == {"long-observed"}


def test_high_angle_fragment_cannot_mask_missing_main_direction() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-2双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )
    reverse = _fragment("observed-reverse", [(40, -2), (0, -2)])
    reverse["assignment_angle_deg"] = 0.0
    high_angle = _fragment("side-branch", [(0, 2), (0, 14)])
    high_angle["assignment_angle_deg"] = 68.0
    assignments = gpd.GeoDataFrame(
        [reverse, high_angle],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-5, -8, 45, 8)}],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="high-angle-main-filter",
        drivezones=drivezones,
        maximum_target_main_angle_deg=35.0,
    )

    assert set(result.carriers["carrier_role"]) == {
        "main_forward",
        "main_reverse",
    }
    assert set(result.carriers["geometry_source"]) == {
        "hp_observed",
        "hp_constrained_completion",
    }
    assert all(
        "side-branch" not in value
        for value in result.carriers["source_patch_road_keys"].astype(str)
    )


def test_dual_target_uses_isolated_baseline_candidate_only_for_missing_role() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-2双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )
    forward = _fragment("fragment-forward", [(0, 2), (40, 2)])
    reverse = _fragment("baseline-reverse", [(40, -2), (0, -2)])
    reverse["takeover_eligible"] = False
    reverse["assignment_source"] = "target_baseline_recovery_candidate"
    assignments = gpd.GeoDataFrame([forward, reverse], crs=segments.crs)

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="isolated-recovery",
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert set(result.carriers["carrier_role"]) == {"main_forward", "main_reverse"}
    assert result.summary["baseline_recovery_takeover_count"] == 1
    assert all(
        "baseline_role_recovery" in value
        for value in result.carriers["assembly_state"].astype(str)
    )


def test_dual_target_can_infer_missing_direction_inside_drivezone() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-2双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [_fragment("observed-forward", [(0, 2), (40, 2)])],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-5, -5, 45, 8)}],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="surface-inferred",
        drivezones=drivezones,
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert set(result.carriers["carrier_role"]) == {"main_forward", "main_reverse"}
    assert set(result.carriers["geometry_source"]) == {
        "hp_observed",
        "hp_constrained_completion",
    }
    inferred = result.carriers[
        result.carriers["surface_inferred_fraction"].fillna(0.0).gt(0.0)
    ].iloc[0]
    assert inferred.geometry.within(drivezones.geometry.union_all().buffer(1.0))
    assert inferred.evidence_quality_state == "surface_inferred_review"
    assert set(result.carriers["carrier_id"]) == {
        "target-corridor:s1:main_forward",
        "target-corridor:s1:main_reverse",
    }
    assert result.summary["member_surface_inference_takeover_count"] == 0


def test_dual_target_uses_member_surface_inference_only_after_segment_path_fails() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-2双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignment = _fragment("member-observed-forward", [(8, 2), (32, 2)])
    assignment["assignment_source"] = "member_assignment"
    assignments = gpd.GeoDataFrame([assignment], crs=segments.crs)
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-5, -5, 45, 8)}],
        crs=segments.crs,
    )
    endpoint_surfaces = gpd.GeoDataFrame(
        [
            {"segment_id": "s1", "geometry": box(-1, -4, 1, 4)},
            {"segment_id": "s1", "geometry": box(39, -4, 41, 4)},
        ],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="member-surface-inferred-recovery",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
        endpoint_surface_segment_ids={"s1"},
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert set(result.carriers["carrier_role"]) == {"main_forward", "main_reverse"}
    assert all(
        str(carrier_id).startswith("built:s1:m1:")
        for carrier_id in result.carriers["carrier_id"]
    )
    assert result.summary["member_surface_inference_takeover_count"] == 1
    assert set(result.carriers["geometry_source"]) == {
        "hp_observed+hp_constrained_completion",
        "hp_constrained_completion",
    }
    assert (
        result.carriers["surface_inferred_fraction"].fillna(0.0).gt(0.0).sum()
        == 1
    )
    for geometry in result.carriers.geometry:
        endpoints = [Point(geometry.coords[0]), Point(geometry.coords[-1])]
        assert all(
            min(point.distance(surface) for point in endpoints) <= 1e-9
            for surface in endpoint_surfaces.geometry
        )
    assert (
        result.segment_plans.iloc[0]["reason_codes"]
        == "member_missing_direction_surface_inference_recovered"
    )


def test_non_target_member_does_not_infer_missing_direction_from_surface() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "not_target",
                "target_required": False,
                "sgrade": "0-2双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignment = _fragment("observed-forward", [(0, 2), (40, 2)])
    assignment["assignment_source"] = "member_assignment"
    assignments = gpd.GeoDataFrame([assignment], crs=segments.crs)
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-5, -5, 45, 8)}],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="non-target-no-surface-inference",
        drivezones=drivezones,
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "swsd_retained"
    assert set(result.carriers["realization"]) == {"retained"}


def test_endpoint_surfaces_only_replan_explicitly_scoped_segment() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-2双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (1000, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("observed-complete", [(0, 2), (40, 2)]),
            _fragment("reverse-partial", [(30, -2), (0, -2)]),
        ],
        crs=segments.crs,
    )
    endpoint_surfaces = gpd.GeoDataFrame(
        [
            {"segment_id": "s1", "geometry": box(-2, -4, 2, 4)},
            {"segment_id": "s1", "geometry": box(38, -4, 42, 4)},
        ],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-5, -8, 45, 8)}],
        crs=segments.crs,
    )

    baseline = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="endpoint-surface-unscoped",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
    )
    assert set(baseline.carriers["geometry_source"]) == {"hp_observed"}
    assert any(
        "reverse-partial" in value
        for value in baseline.carriers["source_patch_road_keys"].astype(str)
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="endpoint-surface-inference",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
        endpoint_surface_segment_ids={"s1"},
    )
    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert set(result.carriers["carrier_role"]) == {
        "main_forward",
        "main_reverse",
    }
    assert set(result.carriers["geometry_source"]) == {
        "hp_observed",
        "hp_observed+hp_constrained_completion",
    }
    reverse = result.carriers[
        result.carriers["carrier_role"].eq("main_reverse")
    ].iloc[0]
    assert "reverse-partial" in str(reverse["source_patch_road_keys"])
    for geometry in result.carriers.geometry:
        endpoints = [Point(geometry.coords[0]), Point(geometry.coords[-1])]
        assert all(
            min(float(endpoint.distance(surface)) for endpoint in endpoints)
            <= 1e-9
            for surface in endpoint_surfaces.geometry
        )


def test_endpoint_surface_retry_forces_real_geometry_completion_for_existing_roles() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("forward", [(5, 2), (35, 2)]),
            _fragment("reverse", [(35, -2), (5, -2)]),
        ],
        crs=segments.crs,
    )
    endpoint_surfaces = gpd.GeoDataFrame(
        [
            {"segment_id": "s1", "geometry": box(0, -4, 2, 4)},
            {"segment_id": "s1", "geometry": box(38, -4, 40, 4)},
        ],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-1, -6, 41, 6)}],
        crs=segments.crs,
    )

    baseline = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="endpoint-existing-roles-baseline",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
    )
    assert all(
        not all(
            Point(point).distance(surface) <= 1e-9
            for point, surface in zip(
                (carrier.geometry.coords[0], carrier.geometry.coords[-1]),
                endpoint_surfaces.geometry,
            )
        )
        for carrier in baseline.carriers.itertuples()
        if str(carrier.realization) == "built"
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="endpoint-existing-roles-retry",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
        endpoint_surface_segment_ids={"s1"},
    )

    built = result.carriers[result.carriers["realization"].eq("built")]
    assert set(built["carrier_role"]) == {"main_forward", "main_reverse"}
    assert set(built["geometry_source"]) == {
        "hp_observed+hp_constrained_completion"
    }
    for geometry in built.geometry:
        endpoints = [Point(geometry.coords[0]), Point(geometry.coords[-1])]
        assert all(
            min(float(endpoint.distance(surface)) for endpoint in endpoints)
            <= 1e-9
            for surface in endpoint_surfaces.geometry
        )
    assert all(
        "endpoint_surface_constrained_completion" in value
        for value in built["assembly_state"].astype(str)
    )


def test_endpoint_completion_limit_follows_observed_coverage_not_relation_radius() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("forward-observed", [(30, 2), (100, 2)]),
            _fragment("reverse-observed", [(100, -2), (30, -2)]),
        ],
        crs=segments.crs,
    )
    endpoint_surfaces = gpd.GeoDataFrame(
        [
            {"segment_id": "s1", "geometry": box(-2, -4, 2, 4)},
            {"segment_id": "s1", "geometry": box(98, -4, 102, 4)},
        ],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-5, -6, 105, 6)}],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="endpoint-observed-coverage",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
        endpoint_surface_segment_ids={"s1"},
        through_surface_max_distance_m=20.0,
        minimum_member_coverage=0.60,
    )

    built = result.carriers[result.carriers["realization"].eq("built")]
    assert set(built["carrier_role"]) == {"main_forward", "main_reverse"}
    assert set(built["geometry_source"]) == {
        "hp_observed+hp_constrained_completion"
    }
    assert all(float(geometry.length) > 90.0 for geometry in built.geometry)
    assert all(
        float(row.internal_completion_fraction) < 0.50
        for row in built.itertuples()
    )


def test_access_support_uses_distinct_patch_fragment_for_uncovered_through_surface() -> None:
    duplicate = _fragment("duplicate-main", [(0, 0), (40, 0)])
    duplicate["assignment_fragment_id"] = "fragment:duplicate"
    support = _fragment("support-road", [(80, 5), (120, 5)])
    support["assignment_fragment_id"] = "fragment:support"
    evidence = gpd.GeoDataFrame(
        [duplicate, support],
        crs="EPSG:32650",
    )
    rows = _target_access_support_carriers(
        "s1",
        ("m1",),
        evidence,
        [
            {
                "realization": "built",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        (
            ("access:covered", box(15, -2, 25, 2)),
            ("access:missing", box(95, 0, 105, 10)),
        ),
        LineString([(0, 0), (120, 0)]),
        "access-support",
        surface_max_distance_m=20.0,
    )

    assert len(rows) == 1
    assert rows[0]["carrier_role"] == "access_support"
    assert rows[0]["geometry_source"] == "hp_observed"
    assert rows[0]["patch_road_key"] == "support-road"
    assert rows[0]["access_support_access_ids"] == "access:missing"
    assert rows[0]["carrier_id"] == "target-access:s1:fragment:support"
    assert rows[0]["inherit_source_snodeid"] is True
    assert rows[0]["inherit_source_enodeid"] is True


def test_access_support_does_not_reuse_geometry_reserved_for_another_segment() -> None:
    support = _fragment("shared-road", [(80, 5), (120, 5)])
    support["assignment_fragment_id"] = "fragment:shared"
    evidence = gpd.GeoDataFrame([support], crs="EPSG:32650")
    reservation = gpd.GeoDataFrame(
        [
            {
                "assigned_segment_id": "s2",
                "assignment_source": "target_access_surface_candidate",
                "geometry": LineString([(80, 5), (120, 5)]),
            }
        ],
        crs=evidence.crs,
    )

    rows = _target_access_support_carriers(
        "s1",
        ("m1",),
        evidence,
        [{"realization": "built", "geometry": LineString([(0, 0), (40, 0)])}],
        (("access:missing", box(95, 0, 105, 10)),),
        LineString([(0, 0), (120, 0)]),
        "access-support-reservation",
        surface_max_distance_m=20.0,
        reserved_access_candidates=reservation,
    )

    assert rows == []


def test_forced_through_support_uses_drivezone_constrained_completion() -> None:
    support = _fragment("terminal-support", [(0, 0), (40, 0)])
    support["assignment_fragment_id"] = "fragment:terminal"
    evidence = gpd.GeoDataFrame([support], crs="EPSG:32650")

    rows = _target_access_support_carriers(
        "s1",
        ("m1",),
        evidence,
        [{"realization": "built", "geometry": LineString([(0, 10), (40, 10)])}],
        (("access:forced", box(45, -2, 50, 2)),),
        LineString([(0, 0), (50, 0)]),
        "forced-through-support",
        surface_max_distance_m=20.0,
        forced_access_ids={"access:forced"},
        completion_surface=box(-5, -5, 55, 5),
        completion_min_coverage=0.90,
    )

    assert len(rows) == 1
    assert rows[0]["geometry"].bounds == (0.0, 0.0, 45.0, 0.0)
    assert rows[0]["geometry_source"] == "hp_observed+hp_constrained_completion"
    assert rows[0]["constrained_completion_access_ids"] == "access:forced"
    assert rows[0]["inherit_source_snodeid"] is False
    assert rows[0]["inherit_source_enodeid"] is False
    assert 0.0 < rows[0]["internal_completion_fraction"] < 1.0
    assert "hp_constrained_completion" in rows[0]["evidence_spans_json"]


def test_forced_suppression_removes_only_the_incomplete_local_connector() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "not_target",
                "target_required": False,
                "sgrade": "0-0双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs=segments.crs,
    )
    connector = _fragment("p1:local", [(10, 0), (10, 5)])
    connector["carrier_role"] = "local_connector"
    assignments = gpd.GeoDataFrame([connector], crs=segments.crs)
    explicit_pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "p1:before",
                "target_patch_road_key": "p1:local",
            },
            {
                "source_patch_road_key": "p1:local",
                "target_patch_road_key": "p1:after",
            },
        ]
    )

    published = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="local-connector-published",
        explicit_pairs=explicit_pairs,
    )
    suppressed = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="local-connector-suppressed",
        explicit_pairs=explicit_pairs,
        forced_suppressed_local_connector_keys={"p1:local"},
    )

    assert "local_connector" in set(published.carriers["carrier_role"])
    assert "local_connector" not in set(suppressed.carriers["carrier_role"])
    assert suppressed.summary["forced_suppressed_local_connector_count"] == 1
    assert suppressed.segment_plans.iloc[0]["segment_state"] == "swsd_retained"


def test_oneway_target_uses_swsd_travel_role_not_patch_coordinate_order() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0单",
                "pair_node_ids": "n0,n1",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "snodeid": "n0",
                "enodeid": "n1",
                "direction": 2,
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [_fragment("patch-reverse", [(30, 2), (0, 2)])],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="oneway-swsd-direction",
    )

    carrier = result.carriers.iloc[0]
    assert carrier["carrier_role"] == "main_oneway"
    assert carrier["direction_role"] == "forward"
    assert carrier.geometry.coords[0][0] == 0.0
    assert carrier.geometry.coords[-1][0] == 30.0
    assert "swsd_direction_normalized" in carrier["assembly_state"]


def test_oneway_target_retains_unrealized_bidirectional_endpoint_function() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0单",
                "pair_node_ids": "n0,n2",
                "swsd_road_ids": "m1,m2",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "snodeid": "n0",
                "enodeid": "nx",
                "direction": 2,
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "id": "m2",
                "segmentid": "s1",
                "snodeid": "nx",
                "enodeid": "n2",
                "direction": 1,
                "geometry": LineString([(20, 0), (30, 0)]),
            },
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [_fragment("patch-main", [(0, 2), (30, 2)])],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="oneway-endpoint-function",
        endpoint_surface_segment_ids={"s1"},
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_partial"
    assert result.segment_plans.iloc[0]["built_road_count"] == 1
    assert result.segment_plans.iloc[0]["retained_road_count"] == 1
    assert set(result.carriers["realization"]) == {"built", "retained"}
    retained = result.carriers[result.carriers["realization"].eq("retained")].iloc[0]
    assert retained["member_swsd_road_id"] == "m2"
    assert retained["endpoint_function_retained"]
    assert (
        retained["reason_codes"]
        == "swsd_bidirectional_endpoint_function_not_realized_by_oneway_hp_main"
    )


def test_forced_through_function_retains_only_local_swsd_members() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "pair_node_ids": "n0,n2",
                "junc_node_ids": "nx",
                "swsd_road_ids": "m1,m2",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "snodeid": "n0",
                "enodeid": "nx",
                "direction": 2,
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "id": "m2",
                "segmentid": "s1",
                "snodeid": "nx",
                "enodeid": "n2",
                "direction": 2,
                "geometry": LineString([(20, 0), (40, 0)]),
            },
        ],
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [
            _fragment("patch-forward", [(0, 2), (40, 2)]),
            _fragment("patch-reverse", [(40, -2), (0, -2)]),
        ],
        crs=segments.crs,
    )
    access_id = "s1:through:0:nx"
    through_surfaces = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "access_id": access_id,
                "junction_group_id": "nx",
                "geometry": box(18, -4, 22, 4),
            }
        ],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="forced-through-retained-function",
        required_through_surfaces=through_surfaces,
        forced_through_access_ids={access_id},
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_partial"
    built = result.carriers[result.carriers["realization"].eq("built")]
    retained = result.carriers[result.carriers["realization"].eq("retained")]
    assert set(built["carrier_role"]) == {"main_forward", "main_reverse"}
    assert "access_support" not in set(built["carrier_role"])
    assert set(retained["member_swsd_road_id"]) == {"m1", "m2"}
    assert retained["through_function_retained"].all()
    assert set(retained["through_function_access_ids"]) == {access_id}
    assert retained["reason_codes"].str.contains(
        "swsd_through_function_retained_after_hp_split_unresolved"
    ).all()


def test_member_level_forced_through_falls_back_only_incident_road() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0单",
                "pair_node_ids": "n0,n2",
                "junc_node_ids": "nx",
                "swsd_road_ids": "m1,m2",
                "geometry": LineString([(0, 0), (40, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "snodeid": "n0",
                "enodeid": "nx",
                "direction": 2,
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "id": "m2",
                "segmentid": "s1",
                "snodeid": "nx",
                "enodeid": "n2",
                "direction": 2,
                "geometry": LineString([(10, 0), (40, 0)]),
            },
        ],
        crs=segments.crs,
    )
    first = _fragment("patch-first", [(0, 1), (10, 1)])
    second = _fragment("patch-second", [(10, 1), (40, 1)])
    second["target_swsd_road_id"] = "m2"
    assignments = gpd.GeoDataFrame([first, second], crs=segments.crs)
    access_id = "s1:through:0:nx"
    through_surfaces = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "access_id": access_id,
                "junction_group_id": "nx",
                "geometry": box(8, -3, 12, 3),
            }
        ],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="member-level-through-retained-function",
        required_through_surfaces=through_surfaces,
        forced_through_access_ids={access_id},
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_partial"
    built = result.carriers[result.carriers["realization"].eq("built")]
    retained = result.carriers[result.carriers["realization"].eq("retained")]
    assert set(built["member_swsd_road_id"]) == {"m2"}
    assert "access_support" not in set(built["carrier_role"])
    assert set(retained["member_swsd_road_id"]) == {"m1"}
    assert retained.iloc[0]["through_function_access_ids"] == access_id
    assert retained.iloc[0]["reason_codes"] == (
        "swsd_through_function_retained_after_hp_split_unresolved"
    )


def test_dual_segment_oneway_members_inherit_swsd_path_roles() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "swsd_road_ids": "f1,f2,r1,r2",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "f1",
                "segmentid": "s1",
                "direction": 2,
                "geometry": LineString([(0, 1), (10, 1)]),
            },
            {
                "id": "f2",
                "segmentid": "s1",
                "direction": 2,
                "geometry": LineString([(10, 1), (20, 1)]),
            },
            {
                "id": "r1",
                "segmentid": "s1",
                "direction": 2,
                "geometry": LineString([(20, -1), (10, -1)]),
            },
            {
                "id": "r2",
                "segmentid": "s1",
                "direction": 2,
                "geometry": LineString([(10, -1), (0, -1)]),
            },
        ],
        crs=segments.crs,
    )
    assignments = []
    for member_id, coords in (
        ("f1", [(0, 1), (10, 1)]),
        ("f2", [(10, 1), (20, 1)]),
        ("r1", [(20, -1), (10, -1)]),
        ("r2", [(10, -1), (0, -1)]),
    ):
        fragment = _fragment(f"patch:{member_id}", coords)
        fragment["target_swsd_road_id"] = member_id
        assignments.append(fragment)
    directional_member_roles = {
        ("s1", "f1", "forward"): "main_forward",
        ("s1", "f2", "forward"): "main_forward",
        ("s1", "r1", "forward"): "main_reverse",
        ("s1", "r2", "forward"): "main_reverse",
    }

    result = plan_segment_carriers(
        segments,
        swsd,
        gpd.GeoDataFrame(assignments, crs=segments.crs),
        run_id="member-path-roles",
        directional_member_roles=directional_member_roles,
    )

    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    built = result.carriers[result.carriers["realization"].eq("built")]
    assert set(built["member_swsd_road_id"]) == {"f1", "f2", "r1", "r2"}
    assert set(built.loc[built["member_swsd_road_id"].isin({"f1", "f2"}), "carrier_role"]) == {
        "main_forward"
    }
    assert set(built.loc[built["member_swsd_road_id"].isin({"r1", "r2"}), "carrier_role"]) == {
        "main_reverse"
    }


def test_access_candidate_bridging_endpoint_surfaces_can_replace_short_swsd_axis() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "swsd_road_ids": "m1",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "m1",
                "segmentid": "s1",
                "direction": 1,
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs=segments.crs,
    )
    access_candidate = _fragment(
        "p1:surface-bridge",
        [(18.5, -2), (15, -2), (11.5, -2)],
    )
    access_candidate.update(
        {
            "takeover_eligible": False,
            "assignment_source": "target_access_surface_candidate",
            "recovery_eligible": True,
            "access_surface_coverage": 1.0,
        }
    )
    endpoint_surfaces = gpd.GeoDataFrame(
        [
            {"segment_id": "s1", "geometry": box(9, -5, 11, 5)},
            {"segment_id": "s1", "geometry": box(19, -5, 21, 5)},
        ],
        crs=segments.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(8, -8, 22, 8)}],
        crs=segments.crs,
    )

    result = plan_segment_carriers(
        segments,
        swsd,
        gpd.GeoDataFrame([access_candidate], crs=segments.crs),
        run_id="endpoint-surface-bridge",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
        endpoint_surface_segment_ids={"s1"},
        minimum_member_coverage=0.60,
    )

    built = result.carriers[result.carriers["realization"].eq("built")]
    assert result.segment_plans.iloc[0]["segment_state"] == "hp_full"
    assert set(built["carrier_role"]) == {"main_forward", "main_reverse"}
    assert built.geometry.map(
        lambda geometry: geometry.distance(endpoint_surfaces.geometry.iloc[0])
        <= 1e-9
        and geometry.distance(endpoint_surfaces.geometry.iloc[1]) <= 1e-9
    ).all()
    assert built["assembly_state"].str.contains(
        "endpoint_surface_bridge"
    ).all()
    assert built["internal_completion_fraction"].max() < 0.50
    assert built["surface_inferred_fraction"].max() == 1.0

    access_candidate["recovery_eligible"] = False
    rejected = plan_segment_carriers(
        segments,
        swsd,
        gpd.GeoDataFrame([access_candidate], crs=segments.crs),
        run_id="endpoint-surface-bridge-rejected",
        drivezones=drivezones,
        required_endpoint_surfaces=endpoint_surfaces,
        endpoint_surface_segment_ids={"s1"},
        minimum_member_coverage=0.60,
    )
    assert rejected.segment_plans.iloc[0]["segment_state"] == "swsd_retained"
    assert set(rejected.carriers["realization"]) == {"retained"}

    access_candidate["recovery_eligible"] = True
    overlapping_surfaces = endpoint_surfaces.copy()
    overlapping_surfaces.geometry = [
        box(9, -5, 16, 5),
        box(14, -5, 21, 5),
    ]
    ambiguous = plan_segment_carriers(
        segments,
        swsd,
        gpd.GeoDataFrame([access_candidate], crs=segments.crs),
        run_id="endpoint-surface-bridge-ambiguous",
        drivezones=drivezones,
        required_endpoint_surfaces=overlapping_surfaces,
        endpoint_surface_segment_ids={"s1"},
        minimum_member_coverage=0.60,
    )
    assert ambiguous.segment_plans.iloc[0]["segment_state"] == "swsd_retained"
    assert set(ambiguous.carriers["realization"]) == {"retained"}


def _fragment(key: str, coords: list[tuple[float, float]]) -> dict[str, object]:
    return {
        "patch_road_key": key,
        "source_patch_id": "p1",
        "source_patch_ids": "p1",
        "road_id": key,
        "center_lane_id": f"lane:{key}",
        "lane_count": 1,
        "median_lane_width_m": 3.5,
        "evidence_quality_state": "usable",
        "assigned_segment_id": "s1",
        "target_swsd_road_id": "m1",
        "carrier_role": "directional_corridor",
        "takeover_eligible": True,
        "assignment_source": "target_segment_fragment",
        "geometry": LineString(coords),
    }
