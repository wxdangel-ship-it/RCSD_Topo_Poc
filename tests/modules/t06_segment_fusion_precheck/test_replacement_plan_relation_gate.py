from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import RelationRecord
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import build_replacement_plan_rows


def test_relation_backed_retained_junction_gap_is_ready_risk_not_blocker() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["100", "200"],
                    "rcsd_road_ids": ["rr1"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s_replace", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s_retained", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("100", 35, 0), _node("200", 10, 0)],
        relation_map={"n1": RelationRecord(target_id="n1", base_id=100, status=0, properties={})},
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["source_reason"] == "buffer_segment_extraction"
    assert "junction_alignment_to_retained_swsd_exceeds_topology_gate" in props["risk_flags"]
    assert "junction_alignment_t05_relation_release" in props["risk_flags"]
    assert "manual_review_required" in props["risk_flags"]


def _feature(properties: dict, geometry: LineString | None = None) -> dict:
    return {"properties": properties, "geometry": geometry or LineString([(0, 0), (1, 0)])}


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}
