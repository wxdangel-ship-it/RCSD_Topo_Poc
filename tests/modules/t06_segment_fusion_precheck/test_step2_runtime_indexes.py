from __future__ import annotations

from types import SimpleNamespace

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationRecord
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step2_runtime_indexes import (
    RelationBaseIndex,
    lost_attach_road_ids,
)


def test_relation_base_index_preserves_shared_base_semantics():
    relation_map = {
        "a": RelationRecord("a", 10, 0, {}),
        "b": RelationRecord("b", 10, 0, {}),
        "c": RelationRecord("c", 20, 0, {}),
        "bad": RelationRecord("bad", 30, 1, {}),
    }
    index = RelationBaseIndex.from_relation_map(relation_map)

    assert index.unexpected_for(["a"]) == {"10", "20"}
    assert index.unexpected_for(["a", "b"]) == {"20"}


def test_lost_attach_road_ids_uses_incident_index_and_preserves_road_order():
    canonicalizer = NodeCanonicalizer.from_node_features(
        [
            {"properties": {"id": "n1", "mainnodeid": 100, "subnodeid": ["n1a"]}},
            {"properties": {"id": "n2", "mainnodeid": 0}},
            {"properties": {"id": "n3", "mainnodeid": 0}},
        ]
    )
    roads = [
        {"properties": {"id": "r1", "snodeid": "n2", "enodeid": "n3"}},
        {"properties": {"id": "r2", "snodeid": "n1a", "enodeid": "n2"}},
        {"properties": {"id": "r3", "snodeid": "n3", "enodeid": "n1"}},
    ]
    buffer_result = SimpleNamespace(candidate_road_ids=["r3", "r2"], retained_road_ids=["r3"])

    assert lost_attach_road_ids(
        dropped_relation_nodes=["100"],
        buffer_result=buffer_result,
        rcsd_roads=roads,
        rcsd_node_canonicalizer=canonicalizer,
    ) == ["r2"]
