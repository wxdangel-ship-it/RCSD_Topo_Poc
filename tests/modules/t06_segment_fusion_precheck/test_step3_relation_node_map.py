from __future__ import annotations

from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_relation_node_map import (
    backfill_relation_node_maps_from_attachment_audit,
    sync_retained_swsd_carrier_mainnodes,
)


def test_backfill_relation_node_map_replaces_missing_mapping_from_attachment_audit() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "s1",
                "relation_status": "replaced",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "n1",
                        "frcsd_node_ids": [],
                        "node_role": "junc_node",
                        "mapping_status": "missing",
                    }
                ],
                "risk_flags": [],
            }
        }
    ]

    stats = backfill_relation_node_maps_from_attachment_audit(
        relation_rows,
        [
            {
                "properties": {
                    "action": "split_rcsd_road_for_swsd_advance",
                    "swsd_node_id": "n1",
                    "generated_rcsd_node_id": "r1",
                }
            }
        ],
    )

    props = relation_rows[0]["properties"]
    assert stats == {
        "relation_node_map_backfilled_entry_count": 1,
        "relation_node_map_backfilled_row_count": 1,
    }
    assert props["swsd_to_frcsd_node_map"][0]["frcsd_node_ids"] == ["r1"]
    assert props["swsd_to_frcsd_node_map"][0]["mapping_status"] == "attachment_mapped"
    assert props["risk_flags"] == ["attachment_backfilled_node_map"]


def test_backfill_relation_node_map_keeps_retained_identity_when_attachment_exists() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "retained",
                "relation_status": "retained_swsd",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "n1",
                        "frcsd_node_ids": ["n1"],
                        "node_role": "pair_node",
                        "mapping_status": "identity",
                    }
                ],
                "risk_flags": [],
            }
        }
    ]

    stats = backfill_relation_node_maps_from_attachment_audit(
        relation_rows,
        [
            {
                "properties": {
                    "action": "reuse_existing_rcsd_endpoint_node",
                    "swsd_node_id": "n1",
                    "rcsd_node_id": "r_existing",
                }
            }
        ],
    )

    entry = relation_rows[0]["properties"]["swsd_to_frcsd_node_map"][0]
    assert stats == {
        "relation_node_map_backfilled_entry_count": 0,
        "relation_node_map_backfilled_row_count": 0,
    }
    assert entry["frcsd_node_ids"] == ["n1"]
    assert entry["mapping_status"] == "identity"


def test_backfill_relation_node_map_keeps_mixed_relation_identity_carrier() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "mixed",
                "relation_status": "replaced+retained_swsd",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "n1",
                        "frcsd_node_ids": ["n1"],
                        "node_role": "junc_node",
                        "mapping_status": "identity_retained_swsd",
                    }
                ],
                "risk_flags": [],
            }
        }
    ]

    stats = backfill_relation_node_maps_from_attachment_audit(
        relation_rows,
        [
            {
                "properties": {
                    "action": "split_rcsd_road_for_retained_swsd_segment",
                    "swsd_node_id": "n1",
                    "generated_rcsd_node_id": "r1",
                }
            }
        ],
    )

    entry = relation_rows[0]["properties"]["swsd_to_frcsd_node_map"][0]
    assert stats["relation_node_map_backfilled_entry_count"] == 0
    assert entry["frcsd_node_ids"] == ["n1"]
    assert entry["mapping_status"] == "identity_retained_swsd"


def test_backfill_relation_node_map_replaces_peer_mapping_for_topology_supplement() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "mixed",
                "relation_status": "replaced+retained_swsd",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "n1",
                        "frcsd_node_ids": ["peer_node"],
                        "node_role": "junc_node",
                        "mapping_status": "peer_mapped",
                    }
                ],
                "risk_flags": ["retained_swsd_topology_supplement"],
            }
        }
    ]

    stats = backfill_relation_node_maps_from_attachment_audit(
        relation_rows,
        [
            {
                "properties": {
                    "action": "split_rcsd_road_for_retained_swsd_segment",
                    "swsd_node_id": "n1",
                    "generated_rcsd_node_id": "attachment_node",
                }
            }
        ],
    )

    entry = relation_rows[0]["properties"]["swsd_to_frcsd_node_map"][0]
    assert stats["relation_node_map_backfilled_entry_count"] == 1
    assert entry["frcsd_node_ids"] == ["attachment_node"]
    assert entry["mapping_status"] == "attachment_mapped_topology_supplement"


def test_backfill_relation_node_map_keeps_mapped_topology_endpoint_without_attachment() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "mixed",
                "relation_status": "replaced+retained_swsd",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "n2",
                        "frcsd_node_ids": ["stale_rcsd_node"],
                        "node_role": "pair_node",
                        "mapping_status": "mapped",
                    }
                ],
                "risk_flags": ["retained_swsd_topology_supplement"],
            }
        }
    ]

    stats = backfill_relation_node_maps_from_attachment_audit(
        relation_rows,
        [],
        frcsd_roads=[
            {
                "properties": {
                    "id": "retained_road",
                    "snodeid": "n1",
                    "enodeid": "n2",
                    "segmentid": "mixed",
                    "source": 2,
                }
            }
        ],
    )

    entry = relation_rows[0]["properties"]["swsd_to_frcsd_node_map"][0]
    assert stats == {
        "relation_node_map_backfilled_entry_count": 0,
        "relation_node_map_backfilled_row_count": 0,
    }
    assert entry["frcsd_node_ids"] == ["stale_rcsd_node"]
    assert entry["mapping_status"] == "mapped"


def test_backfill_relation_node_map_uses_identity_for_missing_retained_topology_endpoint() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "mixed",
                "relation_status": "replaced+retained_swsd",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "n2",
                        "frcsd_node_ids": [],
                        "node_role": "pair_node",
                        "mapping_status": "missing",
                    }
                ],
                "risk_flags": ["retained_swsd_topology_supplement"],
            }
        }
    ]

    stats = backfill_relation_node_maps_from_attachment_audit(
        relation_rows,
        [],
        frcsd_roads=[
            {
                "properties": {
                    "id": "retained_road",
                    "snodeid": "n1",
                    "enodeid": "n2",
                    "segmentid": "mixed",
                    "source": 2,
                }
            }
        ],
    )

    entry = relation_rows[0]["properties"]["swsd_to_frcsd_node_map"][0]
    assert stats == {
        "relation_node_map_backfilled_entry_count": 1,
        "relation_node_map_backfilled_row_count": 1,
    }
    assert entry["frcsd_node_ids"] == ["n2"]
    assert entry["mapping_status"] == "identity_topology_supplement"


def test_sync_retained_swsd_carrier_mainnodes_uses_mapped_rcsd_node_mainnode() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "mixed",
                "relation_status": "replaced+retained_swsd",
                "retained_detached_swsd_road_ids": ["side"],
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "s1",
                        "frcsd_node_ids": ["r1"],
                        "node_role": "junc_node",
                        "mapping_status": "mapped",
                    },
                    {
                        "swsd_node_id": "detached",
                        "frcsd_node_ids": ["detached"],
                        "node_role": "detached_junc_retained_swsd_node",
                        "mapping_status": "identity_retained_swsd",
                    },
                ],
                "risk_flags": ["retained_swsd_topology_supplement"],
            }
        }
    ]
    roads = [
        {
            "properties": {
                "id": "side",
                "snodeid": "s1",
                "enodeid": "detached",
                "source": 2,
            }
        }
    ]
    nodes = [
        {"properties": {"id": "s1", "source": 2, "mainnodeid": "s1"}},
        {"properties": {"id": "detached", "source": 2, "mainnodeid": ""}},
        {"properties": {"id": "r1", "source": 1, "mainnodeid": "r_main"}},
    ]

    stats = sync_retained_swsd_carrier_mainnodes(relation_rows, roads, nodes)

    assert stats == {
        "retained_swsd_carrier_mainnode_candidate_count": 1,
        "retained_swsd_carrier_mainnode_synced_count": 1,
        "retained_swsd_carrier_rcsd_mainnode_filled_count": 0,
        "retained_swsd_carrier_mainnode_row_count": 1,
    }
    assert nodes[0]["properties"]["mainnodeid"] == "r_main"
    assert nodes[1]["properties"]["mainnodeid"] == ""
    assert relation_rows[0]["properties"]["risk_flags"] == [
        "retained_swsd_topology_supplement",
        "retained_swsd_carrier_mainnode_synced",
    ]


def test_sync_retained_swsd_segment_endpoint_mainnodes_from_peer_replaced_segment() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "left_replaced",
                "relation_status": "replaced",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "j1",
                        "frcsd_node_ids": ["r_j1"],
                        "node_role": "junc_node",
                        "mapping_status": "mapped",
                    }
                ],
                "risk_flags": [],
            }
        },
        {
            "properties": {
                "swsd_segment_id": "retained",
                "relation_status": "retained_swsd",
                "frcsd_road_ids": ["s_road"],
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "j1",
                        "frcsd_node_ids": ["j1"],
                        "node_role": "pair_node",
                        "mapping_status": "identity",
                    },
                    {
                        "swsd_node_id": "j2",
                        "frcsd_node_ids": ["j2"],
                        "node_role": "pair_node",
                        "mapping_status": "identity",
                    },
                ],
                "risk_flags": [],
            }
        },
    ]
    roads = [
        {
            "properties": {
                "id": "s_road",
                "snodeid": "j1",
                "enodeid": "j2",
                "source": 2,
            }
        }
    ]
    nodes = [
        {"properties": {"id": "j1", "source": 2, "mainnodeid": "j1"}, "geometry": Point(0, 0)},
        {"properties": {"id": "j2", "source": 2, "mainnodeid": "j2"}, "geometry": Point(10, 0)},
        {"properties": {"id": "r_j1", "source": 1, "mainnodeid": "r_main"}, "geometry": Point(2, 0)},
    ]

    stats = sync_retained_swsd_carrier_mainnodes(relation_rows, roads, nodes)

    retained_props = relation_rows[1]["properties"]
    retained_entry = retained_props["swsd_to_frcsd_node_map"][0]
    assert stats == {
        "retained_swsd_carrier_mainnode_candidate_count": 1,
        "retained_swsd_carrier_mainnode_synced_count": 1,
        "retained_swsd_carrier_rcsd_mainnode_filled_count": 0,
        "retained_swsd_carrier_mainnode_row_count": 1,
    }
    assert nodes[0]["properties"]["mainnodeid"] == "r_main"
    assert nodes[1]["properties"]["mainnodeid"] == "j2"
    assert retained_entry["frcsd_node_ids"] == ["j1"]
    assert retained_entry["mapping_status"] == "identity_semantic_mainnode_synced"
    assert retained_props["risk_flags"] == ["retained_swsd_carrier_mainnode_synced"]


def test_sync_retained_swsd_segment_fills_missing_peer_rcsd_mainnode() -> None:
    relation_rows = [
        {
            "properties": {
                "swsd_segment_id": "left_replaced",
                "relation_status": "replaced",
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "j1",
                        "frcsd_node_ids": ["r_j1"],
                        "node_role": "junc_node",
                        "mapping_status": "mapped",
                    }
                ],
                "risk_flags": [],
            }
        },
        {
            "properties": {
                "swsd_segment_id": "retained",
                "relation_status": "retained_swsd",
                "frcsd_road_ids": ["s_road"],
                "swsd_to_frcsd_node_map": [
                    {
                        "swsd_node_id": "j1",
                        "frcsd_node_ids": ["j1"],
                        "node_role": "pair_node",
                        "mapping_status": "identity",
                    }
                ],
                "risk_flags": [],
            }
        },
    ]
    roads = [
        {
            "properties": {
                "id": "s_road",
                "snodeid": "j1",
                "enodeid": "j2",
                "source": 2,
            }
        }
    ]
    nodes = [
        {"properties": {"id": "j1", "source": 2, "mainnodeid": "j1"}, "geometry": Point(0, 0)},
        {"properties": {"id": "r_j1", "source": 1, "mainnodeid": ""}, "geometry": Point(2, 0)},
    ]

    stats = sync_retained_swsd_carrier_mainnodes(relation_rows, roads, nodes)

    retained_props = relation_rows[1]["properties"]
    retained_entry = retained_props["swsd_to_frcsd_node_map"][0]
    assert stats == {
        "retained_swsd_carrier_mainnode_candidate_count": 1,
        "retained_swsd_carrier_mainnode_synced_count": 1,
        "retained_swsd_carrier_rcsd_mainnode_filled_count": 1,
        "retained_swsd_carrier_mainnode_row_count": 1,
    }
    assert nodes[0]["properties"]["mainnodeid"] == "r_j1"
    assert nodes[1]["properties"]["mainnodeid"] == "r_j1"
    assert retained_entry["mapping_status"] == "identity_semantic_mainnode_synced"
    assert retained_props["risk_flags"] == [
        "retained_swsd_carrier_mainnode_synced",
        "retained_swsd_carrier_rcsd_mainnode_filled",
    ]
