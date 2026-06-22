from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_audit import (
    build_topology_connectivity_audit_rows,
)


def _node(node_id: str, point: Point) -> dict:
    return {"properties": {"id": node_id, "source": 1, "mainnodeid": node_id}, "geometry": point}


def test_patch_attachment_passes_when_swsd_road_materialized_as_rcsd() -> None:
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        swsd_roads=[],
        frcsd_roads=[
            {
                "properties": {
                    "id": "sw1__t06toposupp_1",
                    "source": 1,
                    "snodeid": "10",
                    "enodeid": "20",
                    "direction": 2,
                    "source_road_id": "sw1",
                    "t06_split_original_road_id": "sw1",
                    "t06_split_reason": "topology_supplement_from_swsd",
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        frcsd_nodes=[_node("10", Point(0, 0)), _node("20", Point(10, 0))],
        segment_relation_rows=[
            {
                "properties": {
                    "swsd_segment_id": "seg1",
                    "relation_status": "replaced",
                    "frcsd_road_ids": ["sw1__t06toposupp_1"],
                    "frcsd_road_source_values": [1],
                    "source_mix": "source_1",
                },
                "geometry": None,
            }
        ],
        advance_right_audit_rows=[
            {
                "properties": {
                    "action": "reuse_generated_rcsd_node_for_retained_swsd_segment",
                    "swsd_advance_road_id": "sw1",
                    "swsd_node_id": "old_swsd_node",
                    "generated_rcsd_node_id": "10",
                    "replacement_segment_ids": ["seg1"],
                },
                "geometry": Point(0, 0),
            }
        ],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    patch_rows = [row for row in rows if row["properties"]["audit_layer"] == "patch_road_attachment"]
    assert len(patch_rows) == 1
    props = patch_rows[0]["properties"]
    assert props["audit_status"] == "pass"
    assert props["audit_reason"] == "patch_attachment_materialized_as_rcsd_topology_supplement"
    source_rows = [row for row in rows if row["properties"]["audit_layer"] == "formal_replacement_source_consistency"]
    assert len(source_rows) == 1
    source_props = source_rows[0]["properties"]
    assert source_props["audit_status"] == "fail"
    assert source_props["audit_reason"] == "formal_replacement_contains_swsd_topology_supplement"
