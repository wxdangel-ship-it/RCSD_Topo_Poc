from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    segment_first_movements as movement_module,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_movements import (
    split_carriers_at_movement_anchors,
    split_carriers_at_segment_accesses,
)


def test_segment_access_and_junction_contexts_are_reused_by_identity() -> None:
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "access_type": "ENDPOINT",
                "junction_group_id": "j1",
                "access_id": "a1",
                "geometry": Point(0, 0),
            },
            {
                "segment_id": "s1",
                "access_type": "ENDPOINT",
                "junction_group_id": "j1",
                "access_id": "a1-duplicate",
                "geometry": Point(0, 0),
            },
            {
                "segment_id": "s1",
                "access_type": "THROUGH",
                "junction_group_id": "j2",
                "access_id": "a2",
                "geometry": Point(5, 0),
            },
        ],
        geometry="geometry",
        crs="EPSG:32650",
    )
    endpoint_first, through_first, first_hit = (
        movement_module._segment_access_groups(accesses)
    )
    endpoint_second, through_second, second_hit = (
        movement_module._segment_access_groups(accesses)
    )
    assert not first_hit
    assert second_hit
    assert endpoint_second is endpoint_first
    assert through_second is through_first
    assert list(endpoint_first) == ["s1"]
    assert endpoint_first["s1"]["access_id"].tolist() == ["a1"]
    assert through_first["s1"]["access_id"].tolist() == ["a2"]

    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j1",
                "junction_source": "t07_accepted",
                "geometry": box(-1, -1, 1, 1),
            },
            {
                "junction_group_id": "j1",
                "junction_source": "t03_accepted",
                "geometry": box(1, -1, 2, 1),
            },
        ],
        geometry="geometry",
        crs="EPSG:32650",
    )
    surfaces_first, sources_first, first_hit = (
        movement_module._junction_surface_context(junctions)
    )
    surfaces_second, sources_second, second_hit = (
        movement_module._junction_surface_context(junctions)
    )
    assert not first_hit
    assert second_hit
    assert surfaces_second is surfaces_first
    assert sources_second is sources_first
    assert sources_first == {"j1": "t07_accepted"}
    assert surfaces_first["j1"].equals(box(-1, -1, 2, 1))


def test_movement_selection_reuses_static_patch_endpoint_tangent(
    monkeypatch,
) -> None:
    patch_line = LineString([(0, 0), (10, 0)])
    carrier_line = LineString([(0, 1), (10, 1)])
    carrier_rows = {
        0: pd.Series(
            {
                "carrier_id": "carrier-0",
                "geometry": carrier_line,
            }
        )
    }
    endpoint_contexts: dict[tuple[str, str], object] = {}
    original = movement_module._line_tangent
    patch_tangent_calls = 0

    def counted_tangent(geometry, measure):
        nonlocal patch_tangent_calls
        if geometry is patch_line:
            patch_tangent_calls += 1
        return original(geometry, measure)

    monkeypatch.setattr(movement_module, "_line_tangent", counted_tangent)
    for _ in range(2):
        selected = movement_module._select_movement_carrier(
            "patch-0",
            "end",
            carrier_rows,
            {"patch-0": patch_line},
            endpoint_contexts,
            {"patch-0": [0]},
            {"segment-0": [0]},
            {"patch-0": {"segment-0"}},
        )
        assert selected == 0
    assert patch_tangent_calls == 1
    assert list(endpoint_contexts) == [("patch-0", "end")]


def test_cross_road_internal_movement_splits_both_physical_roads() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "a",
                "realization": "built",
                "source_patch_road_keys": "p:a0,p:a1,p:a2",
                "start_patch_road_keys": "p:a0",
                "end_patch_road_keys": "p:a2",
                "patch_road_key": "p:a0",
                "geometry_source": "hp_observed",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "carrier_id": "b",
                "realization": "built",
                "source_patch_road_keys": "p:b0,p:b1,p:b2",
                "start_patch_road_keys": "p:b0",
                "end_patch_road_keys": "p:b2",
                "patch_road_key": "p:b0",
                "geometry_source": "hp_observed",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 5), (100, 5)]),
            },
        ],
        crs="EPSG:32650",
    )
    assignments = gpd.GeoDataFrame(
        [
            {"patch_road_key": "p:a0", "geometry": LineString([(0, 0), (30, 0)])},
            {"patch_road_key": "p:a1", "geometry": LineString([(30, 0), (50, 0)])},
            {"patch_road_key": "p:a2", "geometry": LineString([(50, 0), (100, 0)])},
            {"patch_road_key": "p:b0", "geometry": LineString([(0, 5), (30, 5)])},
            {"patch_road_key": "p:b1", "geometry": LineString([(50, 5), (70, 5)])},
            {"patch_road_key": "p:b2", "geometry": LineString([(70, 5), (100, 5)])},
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "p:a1",
                "target_patch_road_key": "p:b1",
                "source_relation_id": "lane:1",
                "pair_source": "lane_topo",
            }
        ]
    )
    result = split_carriers_at_movement_anchors(
        carriers,
        assignments,
        pairs,
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    assert len(result.carriers) == 4
    assert result.summary["split_parent_count"] == 2
    assert result.summary["rejected_anchor_count"] == 0
    assert "p:a1" in set(result.carriers["end_patch_road_keys"])
    assert "p:b1" in set(result.carriers["start_patch_road_keys"])


def test_movement_carrier_selection_is_cached_per_patch_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "a",
                "realization": "built",
                "source_patch_road_keys": "p:a0,p:a1,p:a2",
                "start_patch_road_keys": "p:a0",
                "end_patch_road_keys": "p:a2",
                "patch_road_key": "p:a0",
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "carrier_id": "b",
                "realization": "built",
                "source_patch_road_keys": "p:b0,p:b1,p:b2",
                "start_patch_road_keys": "p:b0",
                "end_patch_road_keys": "p:b2",
                "patch_road_key": "p:b0",
                "geometry": LineString([(0, 5), (100, 5)]),
            },
        ],
        crs="EPSG:32650",
    )
    assignments = gpd.GeoDataFrame(
        [
            {"patch_road_key": "p:a1", "geometry": LineString([(30, 0), (50, 0)])},
            {"patch_road_key": "p:b1", "geometry": LineString([(50, 5), (70, 5)])},
        ],
        crs=carriers.crs,
    )
    pair = {
        "source_patch_road_key": "p:a1",
        "target_patch_road_key": "p:b1",
        "source_relation_id": "lane:1",
        "pair_source": "lane_topo",
    }
    calls: list[tuple[str, str]] = []
    original = movement_module._select_movement_carrier

    def counted_select(patch_key: str, endpoint_name: str, *args, **kwargs):
        calls.append((patch_key, endpoint_name))
        return original(patch_key, endpoint_name, *args, **kwargs)

    monkeypatch.setattr(
        movement_module,
        "_select_movement_carrier",
        counted_select,
    )
    result = split_carriers_at_movement_anchors(
        carriers,
        assignments,
        pd.DataFrame([pair, pair]),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )

    assert calls == [("p:a1", "end"), ("p:b1", "start")]
    assert len(result.carriers) == 4

    calls.clear()
    completion_counters: dict[str, object] = {}
    monkeypatch.setattr(
        movement_module,
        "_MOVEMENT_CARRIER_SELECTION_CACHE_MAX_ENTRIES",
        1,
    )
    monkeypatch.setattr(
        movement_module,
        "finish_progress_stage",
        lambda _stage, *, counters=None: completion_counters.update(
            counters or {}
        ),
    )
    bounded = split_carriers_at_movement_anchors(
        carriers,
        assignments,
        pd.DataFrame([pair, pair]),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )

    assert calls == [
        ("p:a1", "end"),
        ("p:b1", "start"),
        ("p:a1", "end"),
        ("p:b1", "start"),
    ]
    assert completion_counters["carrier_selection_cache_entries"] == 1
    assert completion_counters["carrier_selection_cache_entries_max"] == 1
    assert completion_counters["carrier_selection_cache_evictions"] == 3
    assert bounded.carriers.geometry.to_wkb().tolist() == (
        result.carriers.geometry.to_wkb().tolist()
    )


def test_lane_geometry_selects_directional_carrier_when_lane_key_is_not_lineage() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "forward",
                "segment_id": "main",
                "realization": "built",
                "source_patch_road_keys": "p:parent",
                "start_patch_road_keys": "p:parent",
                "end_patch_road_keys": "p:parent",
                "patch_road_key": "p:parent",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (100, 0)]),
            },
            {
                "carrier_id": "reverse",
                "segment_id": "main",
                "realization": "built",
                "source_patch_road_keys": "p:parent",
                "start_patch_road_keys": "p:parent",
                "end_patch_road_keys": "p:parent",
                "patch_road_key": "p:parent",
                "evidence_spans_json": "",
                "geometry": LineString([(100, 4), (0, 4)]),
            },
            {
                "carrier_id": "advance-right",
                "segment_id": "right",
                "realization": "built",
                "source_patch_road_keys": "p:lane:target",
                "start_patch_road_keys": "p:lane:target",
                "end_patch_road_keys": "p:lane:target",
                "patch_road_key": "p:lane:target",
                "evidence_spans_json": "",
                "geometry": LineString([(50, 10), (50, 30)]),
            },
        ],
        crs="EPSG:32650",
    )
    assignments = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p:lane:source",
                "assigned_segment_id": "main",
                "geometry": LineString([(20, 0), (50, 0)]),
            },
            {
                "patch_road_key": "p:lane:target",
                "assigned_segment_id": "right",
                "geometry": LineString([(50, 10), (50, 30)]),
            },
        ],
        crs=carriers.crs,
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "p:lane:source",
                "target_patch_road_key": "p:lane:target",
                "source_relation_id": "lane:movement",
                "pair_source": "lane_topo_lane",
            }
        ]
    )

    result = split_carriers_at_movement_anchors(
        carriers,
        assignments,
        pairs,
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )

    assert result.summary["split_parent_count"] == 1
    assert len(result.carriers[result.carriers["carrier_id"].str.startswith("forward")]) == 2
    assert len(result.carriers[result.carriers["carrier_id"].eq("reverse")]) == 1
    accepted = result.audit[result.audit["split_decision"].eq("accepted")]
    assert accepted["carrier_id"].tolist() == ["forward"]


def test_movement_stage_preserves_disabled_source_node_inheritance() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "support",
                "realization": "built",
                "patch_road_key": "p:support",
                "source_patch_road_keys": "p:support",
                "start_patch_road_keys": "p:support",
                "end_patch_road_keys": "p:support",
                "inherit_source_snodeid": False,
                "inherit_source_enodeid": False,
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )

    result = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )

    assert not bool(result.carriers.iloc[0]["inherit_source_snodeid"])
    assert not bool(result.carriers.iloc[0]["inherit_source_enodeid"])


def test_segment_road_splits_at_through_junction_surface() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "through-road",
                "segment_id": "segment-1",
                "realization": "built",
                "source_patch_road_keys": "p:1",
                "start_patch_road_keys": "p:1",
                "end_patch_road_keys": "p:1",
                "patch_road_key": "p:1",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    base = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:through:0",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "junction_group_id": "junction-1",
                "geometry": Point(50, 0),
            }
        ],
        crs=carriers.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "junction-1",
                "geometry": box(48, -5, 52, 5),
            }
        ],
        crs=carriers.crs,
    )

    result = split_carriers_at_segment_accesses(
        base,
        accesses,
        junctions,
        carriers[["patch_road_key", "geometry"]],
        run_id="run",
        maximum_access_distance_m=20.0,
    )

    assert len(result.carriers) == 2
    assert (
        result.carriers.iloc[0]["end_junction_group_ids"]
        == "junction-1"
    )
    assert (
        result.carriers.iloc[1]["start_junction_group_ids"]
        == "junction-1"
    )
    assert (
        result.carriers.iloc[0]["end_access_ids"]
        == "segment-1:through:0"
    )
    assert (
        result.carriers.iloc[1]["start_access_ids"]
        == "segment-1:through:0"
    )
    assert result.summary["through_accepted_anchor_count"] == 1
    assert result.summary["through_rejected_anchor_count"] == 0


def test_through_junction_does_not_split_nearby_nonintersecting_road() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "nearby-road",
                "segment_id": "segment-1",
                "realization": "built",
                "source_patch_road_keys": "p:1",
                "start_patch_road_keys": "p:1",
                "end_patch_road_keys": "p:1",
                "patch_road_key": "p:1",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    base = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:through:0",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "junction_group_id": "junction-1",
                "geometry": Point(50, 7),
            }
        ],
        crs=carriers.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "junction-1",
                "geometry": box(48, 5, 52, 9),
            }
        ],
        crs=carriers.crs,
    )

    result = split_carriers_at_segment_accesses(
        base,
        accesses,
        junctions,
        carriers[["patch_road_key", "geometry"]],
        run_id="run",
        maximum_access_distance_m=20.0,
        endpoint_surface_buffer_m=1.0,
    )

    assert len(result.carriers) == 1
    assert result.audit.iloc[-1]["split_decision"] == "rejected"
    assert (
        result.audit.iloc[-1]["reason_codes"]
        == "segment_through_surface_not_intersected"
    )


def test_through_retained_access_point_splits_by_t01_lineage_projection() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "retained-point-road",
                "segment_id": "segment-1",
                "realization": "built",
                "source_patch_road_keys": "p:1",
                "start_patch_road_keys": "p:1",
                "end_patch_road_keys": "p:1",
                "patch_road_key": "p:1",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    base = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:through:0",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "junction_group_id": "junction-1",
                "geometry": Point(50, 7),
            }
        ],
        crs=carriers.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "junction-1",
                "junction_source": "swsd_retained",
                "geometry": Point(50, 7),
            }
        ],
        crs=carriers.crs,
    )

    result = split_carriers_at_segment_accesses(
        base,
        accesses,
        junctions,
        carriers[["patch_road_key", "geometry"]],
        run_id="run",
        maximum_access_distance_m=20.0,
        endpoint_surface_buffer_m=1.0,
    )

    assert len(result.carriers) == 2
    assert result.audit.iloc[-1]["split_decision"] == "accepted"
    assert result.audit.iloc[-1]["reason_codes"] == (
        "segment_through_retained_lineage_anchor"
    )


def test_through_surface_near_terminal_reuses_terminal_without_short_road() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "through-road",
                "segment_id": "segment-1",
                "realization": "built",
                "source_patch_road_keys": "p:1",
                "start_patch_road_keys": "p:1",
                "end_patch_road_keys": "p:1",
                "patch_road_key": "p:1",
                "evidence_spans_json": "",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    base = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:through:0",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "junction_group_id": "junction-1",
                "geometry": Point(99, 0),
            }
        ],
        crs=carriers.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "junction-1",
                "geometry": box(98.5, -5, 99.5, 5),
            }
        ],
        crs=carriers.crs,
    )

    result = split_carriers_at_segment_accesses(
        base,
        accesses,
        junctions,
        carriers[["patch_road_key", "geometry"]],
        run_id="run",
        maximum_access_distance_m=20.0,
    )

    assert len(result.carriers) == 1
    assert result.audit.iloc[-1]["split_decision"] == "not_required"
    assert result.summary["through_terminal_equivalent_count"] == 1
    assert result.summary["through_rejected_anchor_count"] == 0


def test_target_main_road_is_trimmed_between_both_endpoint_surfaces() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "target-main",
                "segment_id": "segment-1",
                "target_class": "core_trunk",
                "carrier_role": "main_forward",
                "realization": "built",
                "source_patch_road_keys": "p:1",
                "start_patch_road_keys": "p:1",
                "end_patch_road_keys": "p:1",
                "patch_road_key": "p:1",
                "evidence_spans_json": "",
                "assembly_state": "observed",
                "geometry": LineString([(-20, 0), (120, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    base = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:endpoint:0",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "junction_group_id": "junction-a",
                "geometry": Point(0, 0),
            },
            {
                "access_id": "segment-1:endpoint:1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "junction_group_id": "junction-b",
                "geometry": Point(100, 0),
            },
        ],
        crs=carriers.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {"junction_group_id": "junction-a", "geometry": box(-5, -5, 5, 5)},
            {"junction_group_id": "junction-b", "geometry": box(95, -5, 105, 5)},
        ],
        crs=carriers.crs,
    )

    result = split_carriers_at_segment_accesses(
        base,
        accesses,
        junctions,
        carriers[["patch_road_key", "geometry"]],
        run_id="run",
        maximum_access_distance_m=20.0,
        endpoint_trim_segment_ids={"segment-1"},
    )

    assert len(result.carriers) == 1
    assert result.summary["endpoint_trimmed_carrier_count"] == 1
    assert result.carriers.geometry.iloc[0].bounds == (5.0, 0.0, 95.0, 0.0)
    assert not bool(result.carriers.iloc[0]["inherit_source_snodeid"])
    assert not bool(result.carriers.iloc[0]["inherit_source_enodeid"])
    assert result.audit.iloc[-1]["anchor_role"] == "segment_endpoint_surface_trim"


def test_endpoint_trim_suppresses_movement_tail_outside_segment_corridor() -> None:
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "target-main:part:0",
                "movement_parent_carrier_id": "target-main",
                "segment_id": "segment-1",
                "target_class": "core_trunk",
                "carrier_role": "main_forward",
                "realization": "built",
                "source_patch_road_keys": "p:1",
                "start_patch_road_keys": "p:1",
                "end_patch_road_keys": "p:1",
                "patch_road_key": "p:1",
                "evidence_spans_json": "",
                "assembly_state": "observed+movement_split",
                "endpoint_surface_routing_movement_split": False,
                "geometry": LineString([(-20, 0), (94.8, 0)]),
            },
            {
                "carrier_id": "target-main:part:1",
                "movement_parent_carrier_id": "target-main",
                "segment_id": "segment-1",
                "target_class": "core_trunk",
                "carrier_role": "main_forward",
                "realization": "built",
                "source_patch_road_keys": "p:2",
                "start_patch_road_keys": "p:2",
                "end_patch_road_keys": "p:2",
                "patch_road_key": "p:2",
                "evidence_spans_json": "",
                "assembly_state": "observed+movement_split",
                "endpoint_surface_routing_movement_split": False,
                "geometry": LineString([(94.8, 0), (110, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    base = split_carriers_at_movement_anchors(
        carriers,
        carriers[["patch_road_key", "geometry"]],
        pd.DataFrame(),
        run_id="run",
        maximum_anchor_distance_m=20.0,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "segment-1:endpoint:0",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "junction_group_id": "junction-a",
                "geometry": Point(0, 0),
            },
            {
                "access_id": "segment-1:endpoint:1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "junction_group_id": "junction-b",
                "geometry": Point(100, 0),
            },
        ],
        crs=carriers.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {"junction_group_id": "junction-a", "geometry": box(-5, -5, 5, 5)},
            {"junction_group_id": "junction-b", "geometry": box(95, -5, 105, 5)},
        ],
        crs=carriers.crs,
    )

    result = split_carriers_at_segment_accesses(
        base,
        accesses,
        junctions,
        carriers[["patch_road_key", "geometry"]],
        run_id="run",
        maximum_access_distance_m=20.0,
        endpoint_trim_segment_ids={"segment-1"},
        endpoint_surface_buffer_m=1.0,
    )

    assert len(result.carriers) == 1
    assert result.carriers.geometry.iloc[0].bounds == pytest.approx(
        (6.0, 0.0, 94.0, 0.0)
    )
    assert result.audit["reason_codes"].eq(
        "segment_main_tail_outside_endpoint_corridor_suppressed"
    ).sum() == 1
