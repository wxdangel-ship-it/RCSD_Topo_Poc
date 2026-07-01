from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import build_replacement_plan_rows


def test_partial_roundabout_group_keeps_internal_rcsd_roads_out_of_plan() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_entry",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "roundabout"],
                    "rcsd_pair_nodes": ["10", "20"],
                    "rcsd_road_ids": ["rr_entry"],
                    "retained_node_ids": ["10", "20"],
                }
            )
        ],
        special_group_rows=[
            _feature(
                {
                    "special_junction_id": "roundabout",
                    "special_junction_type": "roundabout",
                    "gate_status": "partial",
                    "associated_segment_ids": ["s_entry", "s_missing"],
                    "replaceable_segment_ids": ["s_entry"],
                    "missing_replaceable_segment_ids": ["s_missing"],
                    "rcsd_junction_id": "20",
                    "rcsd_junction_node_ids": ["20", "21"],
                    "rcsd_junction_road_ids": ["rr_internal"],
                }
            )
        ],
        group_replacement_audit_rows=[],
        rcsd_roads=[
            _road("rr_entry", "10", "20"),
            _road("rr_internal", "20", "21"),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "21"})),
    )

    scopes = [row["properties"]["execution_scope"] for row in rows]
    assert scopes == ["standard_segment"]
    assert rows[0]["properties"]["rcsd_road_ids"] == ["rr_entry"]


def _feature(props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": LineString([(0, 0), (1, 0)])}


def _road(road_id: str, source: str, target: str) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": road_id, "snodeid": source, "enodeid": target, "direction": 0},
        "geometry": LineString([(float(source), 0), (float(target), 0)]),
    }
