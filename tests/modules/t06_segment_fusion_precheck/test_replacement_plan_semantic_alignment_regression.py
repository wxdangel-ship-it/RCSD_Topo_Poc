from __future__ import annotations

from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import build_replacement_plan_rows


def _feature(props, geom=None):
    return {"type": "Feature", "properties": props, "geometry": geom}


def _node(node_id: str, x: float, y: float):
    return _feature({"id": node_id}, Point(x, y))


def test_same_canonical_rcsd_nodes_do_not_block_replacement_plan_alignment() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_alias", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "rcsd_pair_nodes": ["r_main", "r3"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({"r_alias": "r_main", "r_main": "r_main"}, frozenset({"r_main"})),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 0, 10), _node("n3", 0, 20)],
        rcsd_nodes=[
            _node("r_alias", 0, 0),
            _node("r_main", 20, 0),
            _node("r2", 0, 10),
            _node("r3", 0, 20),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "ready"
    assert by_segment["s2"]["plan_status"] == "ready"
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["s1"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["s2"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_semantic_group_aligned" in by_segment["s1"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_semantic_group_aligned" in by_segment["s2"]["risk_flags"]
