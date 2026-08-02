from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, box

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    segment_first_target_path_cache as cache_module,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_target_path_cache import (
    reset_target_path_cache,
    select_directed_target_path,
    target_path_cache_stats,
)


def _evidence() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p:1",
                "assignment_score": 1.0,
                "full_rcsd_anchor_supported": True,
                "geometry": LineString([(0, 0), (40, 0)]),
            },
            {
                "patch_road_key": "p:2",
                "assignment_score": 1.0,
                "full_rcsd_anchor_supported": True,
                "geometry": LineString([(40, 0), (75, 0)]),
            },
            {
                "patch_road_key": "p:3",
                "assignment_score": 20.0,
                "full_rcsd_anchor_supported": False,
                "geometry": LineString([(80, 0), (100, 0)]),
            },
        ],
        geometry="geometry",
        crs="EPSG:32650",
    )


def _pairs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_patch_road_key": "p:1",
                "target_patch_road_key": "p:2",
            }
        ]
    )


def test_target_path_cache_reuses_value_equivalent_evidence() -> None:
    reset_target_path_cache()
    evidence = _evidence()
    pairs = _pairs()
    reference = LineString([(0, 0), (100, 0)])

    first = select_directed_target_path(evidence, reference, pairs)
    second = select_directed_target_path(evidence.copy(), reference, pairs)
    stats = target_path_cache_stats()

    assert set(first["patch_road_key"]) == {"p:1", "p:2"}
    assert list(second["patch_road_key"]) == list(first["patch_road_key"])
    assert stats["query_count"] == 2
    assert stats["hit_count"] == 1
    assert stats["miss_count"] == 1
    assert stats["entry_count"] == 1
    assert stats["pair_signature_count"] == 1
    reset_target_path_cache()


def test_target_path_cache_preserves_required_surface_fallback() -> None:
    reset_target_path_cache()
    evidence = _evidence()
    selected = select_directed_target_path(
        evidence,
        LineString([(0, 0), (100, 0)]),
        _pairs(),
        required_surfaces=(
            box(-2, -1, 2, 1),
            box(98, -1, 102, 1),
        ),
        surface_max_distance_m=1.0,
    )

    assert set(selected["patch_road_key"]) == {"p:1", "p:2", "p:3"}
    reset_target_path_cache()


def test_target_path_cache_evicts_at_configured_bound(monkeypatch) -> None:
    reset_target_path_cache()
    monkeypatch.setattr(cache_module, "_MAX_ENTRIES", 1)
    evidence = _evidence()
    pairs = _pairs()
    reference = LineString([(0, 0), (100, 0)])

    select_directed_target_path(evidence, reference, pairs)
    select_directed_target_path(
        evidence,
        reference,
        pairs,
        surface_max_distance_m=19.0,
    )
    stats = target_path_cache_stats()

    assert stats["entry_count"] == 1
    assert stats["entry_count_max"] == 1
    assert stats["eviction_count"] == 1
    reset_target_path_cache()


def test_target_path_cache_evicts_when_one_key_exceeds_byte_bound(
    monkeypatch,
) -> None:
    reset_target_path_cache()
    monkeypatch.setattr(cache_module, "_MAX_KEY_BYTES", 1)

    select_directed_target_path(
        _evidence(),
        LineString([(0, 0), (100, 0)]),
        _pairs(),
    )
    stats = target_path_cache_stats()

    assert stats["entry_count"] == 0
    assert stats["key_bytes"] == 0
    assert stats["eviction_count"] == 1
    reset_target_path_cache()
