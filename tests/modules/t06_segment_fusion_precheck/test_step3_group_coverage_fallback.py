from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import feature
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_group_coverage_fallback import (
    GROUP_COVERAGE_FALLBACK_RISK,
    retain_group_coverage_fallback,
)


@dataclass
class _Unit:
    segment_id: str
    swsd_road_ids: list[str]
    retained_detached_swsd_road_ids: list[str] = field(default_factory=list)
    removed_swsd_node_ids: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=lambda: ["group_path_corridor_replacement"])


def test_group_path_corridor_local_coverage_gap_retains_swsd_carrier() -> None:
    segment_id = "A_B"
    units = [_Unit(segment_id=segment_id, swsd_road_ids=["S1"], removed_swsd_node_ids=["A", "B"])]
    swsd_segments = [
        feature(
            {
                "id": segment_id,
                "swsd_segment_id": segment_id,
                "pair_nodes": ["A", "B"],
                "junc_nodes": [],
                "roads": ["S1"],
                "sgrade": 2,
            },
            LineString([(0, 0), (100, 0)]),
        )
    ]
    swsd_roads = [feature({"id": "S1", "snodeid": "A", "enodeid": "B", "direction": 0}, LineString([(0, 0), (100, 0)]))]
    swsd_nodes = [feature({"id": "A", "mainnodeid": "A"}, Point(0, 0)), feature({"id": "B", "mainnodeid": "B"}, Point(100, 0))]
    frcsd_roads = [
        feature(
            {"id": "R1", "snodeid": "RA", "enodeid": "RB", "source": 1, "t06_swsd_segment_ids": [segment_id]},
            LineString([(0, 100), (100, 100)]),
        )
    ]
    frcsd_nodes = [feature({"id": "RA", "mainnodeid": "RA", "source": 1}, Point(0, 100)), feature({"id": "RB", "mainnodeid": "RB", "source": 1}, Point(100, 100))]
    relation_rows = [
        feature(
            {
                "swsd_segment_id": segment_id,
                "relation_status": "replaced",
                "relation_reason": "group_path_corridor_replacement",
                "swsd_pair_nodes": ["A", "B"],
                "swsd_junc_nodes": [],
                "swsd_road_ids": ["S1"],
                "removed_swsd_road_ids": ["S1"],
                "retained_detached_swsd_road_ids": [],
                "frcsd_road_ids": ["R1"],
                "frcsd_road_source_values": [1],
                "rcsd_pair_nodes": ["RA", "RB"],
                "rcsd_junc_nodes": [],
                "swsd_to_frcsd_node_map": [
                    {"swsd_node_id": "A", "frcsd_node_ids": ["RA"], "node_role": "pair_node", "mapping_status": "mapped"},
                    {"swsd_node_id": "B", "frcsd_node_ids": ["RB"], "node_role": "pair_node", "mapping_status": "mapped"},
                ],
                "source_mix": "source_1",
                "risk_flags": ["group_path_corridor_replacement"],
            },
            None,
        )
    ]
    removed_roads = {"S1": [segment_id]}
    removed_nodes = {"A": [segment_id], "B": [segment_id]}

    stats = retain_group_coverage_fallback(
        units=units,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=relation_rows,
        advance_right_audit_rows=[],
        removed_road_to_segments=removed_roads,
        removed_node_to_segments=removed_nodes,
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    relation = relation_rows[0]["properties"]
    swsd_carriers = [row for row in frcsd_roads if (row["properties"].get("source"), row["properties"].get("id")) == (2, "S1")]
    assert stats["group_path_corridor_coverage_fallback_segment_count"] == 1
    assert stats["group_path_corridor_coverage_fallback_swsd_road_count"] == 1
    assert len(swsd_carriers) == 1
    assert relation["relation_status"] == "replaced+retained_swsd"
    assert relation["retained_detached_swsd_road_ids"] == ["S1"]
    assert relation["removed_swsd_road_ids"] == []
    assert relation["source_mix"] == "source_1+source_2"
    assert GROUP_COVERAGE_FALLBACK_RISK in relation["risk_flags"]
    assert removed_roads == {}
    assert removed_nodes == {}
    assert units[0].swsd_road_ids == []
    assert units[0].retained_detached_swsd_road_ids == ["S1"]
    retained_nodes = {
        row["properties"]["id"]: row["properties"]
        for row in frcsd_nodes
        if row["properties"].get("source") == 2
    }
    assert retained_nodes["A"]["mainnodeid"] == "RA"
    assert retained_nodes["B"]["mainnodeid"] == "RB"
    assert "retained_swsd_carrier_mainnode_synced" in relation["risk_flags"]


def test_split_original_road_refs_are_synced_to_final_materialized_roads() -> None:
    segment_id = "A_B"
    units = [_Unit(segment_id=segment_id, swsd_road_ids=["S1"])]
    units[0].rcsd_road_ids = ["R1"]
    swsd_segments = [
        feature(
            {
                "id": segment_id,
                "swsd_segment_id": segment_id,
                "pair_nodes": ["A", "B"],
                "junc_nodes": [],
                "roads": ["S1"],
                "sgrade": 2,
            },
            LineString([(0, 0), (100, 0)]),
        )
    ]
    swsd_roads = [feature({"id": "S1", "snodeid": "A", "enodeid": "B", "direction": 0}, LineString([(0, 0), (100, 0)]))]
    frcsd_roads = [
        feature(
            {
                "id": "R1__t06surfmid_1",
                "snodeid": "RA",
                "enodeid": "RM",
                "source": 1,
                "direction": 0,
                "t06_split_original_road_id": "R1",
            },
            LineString([(0, 0), (50, 0)]),
        ),
        feature(
            {
                "id": "R1__t06surfmid_2",
                "snodeid": "RM",
                "enodeid": "RB",
                "source": 1,
                "direction": 0,
                "t06_split_original_road_id": "R1",
            },
            LineString([(50, 0), (100, 0)]),
        ),
    ]
    frcsd_nodes = [
        feature({"id": "RA", "source": 1}, Point(0, 0)),
        feature({"id": "RM", "source": 1}, Point(50, 0)),
        feature({"id": "RB", "source": 1}, Point(100, 0)),
    ]
    relation_rows = [
        feature(
            {
                "swsd_segment_id": segment_id,
                "relation_status": "replaced",
                "relation_reason": "group_path_corridor_replacement",
                "swsd_pair_nodes": ["A", "B"],
                "swsd_junc_nodes": [],
                "swsd_road_ids": ["S1"],
                "removed_swsd_road_ids": ["S1"],
                "retained_detached_swsd_road_ids": [],
                "frcsd_road_ids": ["R1"],
                "frcsd_road_source_values": [1],
                "rcsd_pair_nodes": ["RA", "RB"],
                "rcsd_junc_nodes": [],
                "swsd_to_frcsd_node_map": [
                    {"swsd_node_id": "A", "frcsd_node_ids": ["RA"], "node_role": "pair_node", "mapping_status": "mapped"},
                    {"swsd_node_id": "B", "frcsd_node_ids": ["RB"], "node_role": "pair_node", "mapping_status": "mapped"},
                ],
                "source_mix": "source_1",
                "risk_flags": ["group_path_corridor_replacement"],
            },
            None,
        )
    ]

    stats = retain_group_coverage_fallback(
        units=units,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        swsd_nodes=[],
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=relation_rows,
        advance_right_audit_rows=[],
        removed_road_to_segments={},
        removed_node_to_segments={},
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )

    expected = ["R1__t06surfmid_1", "R1__t06surfmid_2"]
    assert relation_rows[0]["properties"]["frcsd_road_ids"] == expected
    assert units[0].rcsd_road_ids == expected
    assert stats["split_relation_road_reference_sync_count"] == 1
    assert stats["split_unit_road_reference_sync_count"] == 1
