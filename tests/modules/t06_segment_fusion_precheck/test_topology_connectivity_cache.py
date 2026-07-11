from shapely.geometry import LineString
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_topology_connectivity_audit as audit
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_topology_connectivity_support as support


def test_buffered_road_union_reuses_explicit_shared_cache_only() -> None:
    roads = [
        {
            "properties": {"id": "r1", "source": 1},
            "geometry": LineString([(0, 0), (10, 0)]),
        }
    ]
    moved_roads = [
        {
            "properties": {"id": "r1", "source": 1},
            "geometry": LineString([(0, 10), (10, 10)]),
        }
    ]
    shared_cache = {}

    first = audit._buffered_road_union(roads, buffer_m=5.0, coverage_cache=shared_cache)
    second = audit._buffered_road_union(roads, buffer_m=5.0, coverage_cache=shared_cache)
    moved = audit._buffered_road_union(moved_roads, buffer_m=5.0, coverage_cache=shared_cache)

    assert first is second
    assert moved is not first
    assert len(shared_cache) == 2


def test_relation_coverage_prewarm_matches_scalar_buffer_exactly() -> None:
    roads = [
        {
            "properties": {"id": "r1", "source": 1, "snodeid": "n1", "enodeid": "n2"},
            "geometry": LineString([(0, 0), (10, 0)]),
        },
        {
            "properties": {"id": "r2", "source": 1, "snodeid": "n2", "enodeid": "n3"},
            "geometry": LineString([(10, 0), (20, 5)]),
        },
    ]
    relation_props = [
        {
            "frcsd_road_ids": ["r1", "r2"],
            "frcsd_road_source_values": ["1"],
        }
    ]
    road_index = audit._RoadIndex(roads, source_field_name="source")
    coverage_cache = {}
    signature_cache = {}

    audit._prewarm_relation_coverage_cache(
        relation_props,
        road_index=road_index,
        coverage_cache=coverage_cache,
        signature_cache=signature_cache,
    )

    road_union = unary_union([road["geometry"] for road in roads])
    for buffer_m in (2.0, 5.0, 15.0):
        expected = road_union.buffer(buffer_m)
        actual = audit._buffered_road_union(
            roads,
            buffer_m=buffer_m,
            coverage_cache=coverage_cache,
            road_signature_cache=signature_cache,
        )
        assert actual is not None
        assert actual.wkb == expected.wkb
    assert len(coverage_cache) == 3


def test_relation_coverage_prewarm_skips_union_when_all_buffers_are_cached(monkeypatch) -> None:
    roads = [
        {
            "properties": {"id": "r1", "source": 1, "snodeid": "n1", "enodeid": "n2"},
            "geometry": LineString([(0, 0), (10, 0)]),
        }
    ]
    relation_props = [{"frcsd_road_ids": ["r1"], "frcsd_road_source_values": ["1"]}]
    road_index = audit._RoadIndex(roads, source_field_name="source")
    coverage_cache = {}
    calls = 0
    original_unary_union = support.unary_union

    def _counted_unary_union(geometries):
        nonlocal calls
        calls += 1
        return original_unary_union(geometries)

    monkeypatch.setattr(support, "unary_union", _counted_unary_union)
    for _ in range(2):
        audit._prewarm_relation_coverage_cache(
            relation_props,
            road_index=road_index,
            coverage_cache=coverage_cache,
            signature_cache={},
        )

    assert calls == 1
    assert len(coverage_cache) == 3
