from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_completion_surfaces import (
    IndexedCompletionSurface,
    build_completion_surfaces,
    completion_surface_local_geometry,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_metrics import (
    surface_coverage,
    surface_coverage_at_least,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_progress import (
    configure_progress,
    reset_progress,
)


def _inputs():
    drivezone = Polygon([(0, -2), (20, -2), (20, 2), (0, 2)])
    accepted = Polygon([(20, -3), (25, -3), (25, 3), (20, 3)])
    rejected = Polygon([(30, -3), (35, -3), (35, 3), (30, 3)])
    drivezones = gpd.GeoDataFrame(
        {"id": ["dz"], "geometry": [drivezone]},
        geometry="geometry",
        crs="EPSG:32650",
    )
    surfaces = {"accepted": accepted, "rejected": rejected}
    contexts = {
        "accepted": {"junction_source": "t07_accepted"},
        "rejected": {"junction_source": "retained"},
    }
    return drivezones, surfaces, contexts, drivezone, accepted


def test_indexed_completion_surface_matches_materialized_union() -> None:
    drivezones, surfaces, contexts, drivezone, accepted = _inputs()
    drivezone_surface, indexed = build_completion_surfaces(
        drivezones,
        surfaces,
        contexts,
        buffer_m=1.0,
    )
    expected = unary_union([drivezone.buffer(1.0), accepted.buffer(1.0)])

    assert isinstance(indexed, IndexedCompletionSurface)
    assert drivezone_surface.equals(drivezone.buffer(1.0))
    assert len(indexed.junction_surfaces) == 1
    for line in (
        LineString([(1, 0), (24, 0)]),
        LineString([(23, 2.8), (27, 2.8)]),
        LineString([(26.5, 0), (34, 0)]),
    ):
        assert surface_coverage(line, indexed) == pytest.approx(
            surface_coverage(line, expected),
            abs=1e-12,
        )
        for threshold in (0.0, 0.25, 0.5, 0.9, 1.0):
            assert surface_coverage_at_least(
                line,
                indexed,
                threshold,
                epsilon=1e-9,
            ) == surface_coverage_at_least(
                line,
                expected,
                threshold,
                epsilon=1e-9,
            )


def test_indexed_completion_surface_local_geometry_is_exact() -> None:
    drivezones, surfaces, contexts, drivezone, accepted = _inputs()
    _, indexed = build_completion_surfaces(
        drivezones,
        surfaces,
        contexts,
        buffer_m=1.0,
    )
    scope = Polygon([(18, -4), (28, -4), (28, 4), (18, 4)])
    extra = Polygon([(24, -1), (27, -1), (27, 1), (24, 1)])
    actual = completion_surface_local_geometry(
        indexed,
        scope,
        extra_surfaces=(extra,),
    )
    expected = unary_union(
        [drivezone.buffer(1.0), accepted.buffer(1.0), extra]
    ).intersection(scope)

    assert actual.symmetric_difference(expected).area == pytest.approx(
        0.0,
        abs=1e-9,
    )
    assert indexed.covers_point(extra.representative_point())
    assert not indexed.covers_point(Polygon([(40, 0), (41, 0), (41, 1)]).centroid)


def test_completion_surface_progress_reports_real_node_stage(tmp_path) -> None:
    drivezones, surfaces, contexts, _, _ = _inputs()
    event_path = tmp_path / "progress.jsonl"
    configure_progress("completion-test", event_path)
    try:
        build_completion_surfaces(
            drivezones,
            surfaces,
            contexts,
            buffer_m=1.0,
        )
    finally:
        reset_progress()

    events = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
    ]
    completed = [
        event
        for event in events
        if event["event_type"] == "stage_completed"
        and event["stage"] == "node_completion_surface"
    ]
    assert len(completed) == 1
    assert completed[0]["completed"] == completed[0]["total"] == 3
    assert completed[0]["counters"]["indexed_junction_count"] == 1
