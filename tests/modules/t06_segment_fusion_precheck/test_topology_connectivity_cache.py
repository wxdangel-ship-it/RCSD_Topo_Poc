from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_topology_connectivity_audit as audit


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
