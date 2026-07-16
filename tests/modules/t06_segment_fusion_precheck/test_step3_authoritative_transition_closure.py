from __future__ import annotations

import json

from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_authoritative_transition_closure import (
    _hard_gate_cascade_node_ids,
    sync_authoritative_transition_mainnodes,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_replacement_plan_reader import (
    defer_replacement_plan_writes,
    write_replacement_plan_json,
)


def _node(node_id: str, source: int, x: float, *, mainnodeid=0) -> dict:
    return {
        "properties": {"id": node_id, "source": source, "mainnodeid": mainnodeid},
        "geometry": Point(x, 0),
    }


def _relation(segment_id: str, status: str, node_id: str, mapped_node_id: str, mapping_status: str) -> dict:
    return {
        "properties": {
            "swsd_segment_id": segment_id,
            "relation_status": status,
            "swsd_to_frcsd_node_map": [
                {
                    "swsd_node_id": node_id,
                    "frcsd_node_ids": [mapped_node_id],
                    "mapping_status": mapping_status,
                }
            ],
            "risk_flags": [],
        }
    }


def test_syncs_cascade_transition_when_remaining_replaced_mapping_matches_t05() -> None:
    relations = [
        _relation("s_replaced", "replaced", "n1", "r1", "mapped"),
        _relation("s_retained", "retained_swsd", "n1", "n1", "identity"),
    ]
    nodes = [_node("r1", 1, 6), _node("n1", 2, 0)]

    stats = sync_authoritative_transition_mainnodes(
        relation_rows=relations,
        frcsd_nodes=nodes,
        transition_node_ids={"n1"},
        patch_blocked_node_ids=set(),
        t05_targets={"n1": "r1"},
    )

    assert stats["applied_node_count"] == 1
    assert nodes[0]["properties"]["mainnodeid"] == "r1"
    assert nodes[1]["properties"]["mainnodeid"] == "r1"
    retained_entry = relations[1]["properties"]["swsd_to_frcsd_node_map"][0]
    assert retained_entry["mapping_status"] == "identity_authoritative_t05_mainnode_synced"


def test_does_not_sync_patch_blocked_transition() -> None:
    relations = [
        _relation("s_replaced", "replaced", "n1", "r1", "mapped"),
        _relation("s_retained", "retained_swsd", "n1", "n1", "identity"),
    ]
    nodes = [_node("r1", 1, 6), _node("n1", 2, 0)]

    stats = sync_authoritative_transition_mainnodes(
        relation_rows=relations,
        frcsd_nodes=nodes,
        transition_node_ids={"n1"},
        patch_blocked_node_ids={"n1"},
        t05_targets={"n1": "r1"},
    )

    assert stats["applied_node_count"] == 0
    assert nodes[0]["properties"]["mainnodeid"] == 0
    assert nodes[1]["properties"]["mainnodeid"] == 0
    assert (
        stats["audit_rows"][0]["properties"]["action_reason"]
        == "surface_patch_or_t04_conflict_blocks_authoritative_closure"
    )


def test_does_not_sync_when_remaining_replaced_mapping_disagrees_with_t05() -> None:
    relations = [
        _relation("s_replaced", "replaced", "n1", "r_wrong", "mapped"),
        _relation("s_retained", "retained_swsd", "n1", "n1", "identity"),
    ]
    nodes = [_node("r1", 1, 6), _node("r_wrong", 1, 5), _node("n1", 2, 0)]

    stats = sync_authoritative_transition_mainnodes(
        relation_rows=relations,
        frcsd_nodes=nodes,
        transition_node_ids={"n1"},
        patch_blocked_node_ids=set(),
        t05_targets={"n1": "r1"},
    )

    assert stats["applied_node_count"] == 0
    assert nodes[2]["properties"]["mainnodeid"] == 0
    assert (
        stats["audit_rows"][0]["properties"]["action_reason"]
        == "remaining_replaced_mappings_disagree_with_t05_authoritative_root"
    )


def test_hard_gate_candidate_nodes_only_come_from_current_rollback_plan(tmp_path) -> None:
    plan_path = tmp_path / "t06_step3_surface_aware_replacement_plan_final_topology_hard_gate_1.json"
    plan_path.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "properties": {
                            "source_reason": "final_frcsd_topology_hard_gate_failed",
                            "swsd_pair_nodes": ["n1", "n2"],
                            "swsd_junc_nodes": ["j1"],
                            "final_topology_hard_gate_failure_node_ids": ["n1"],
                        }
                    },
                    {
                        "properties": {
                            "source_reason": "buffer_segment_extraction",
                            "swsd_pair_nodes": ["unrelated1", "unrelated2"],
                        }
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "t06_step3_summary.json").write_text(
        json.dumps({"input_paths": {"step2_replacement_plan_path": str(plan_path)}}),
        encoding="utf-8",
    )

    assert _hard_gate_cascade_node_ids(tmp_path) == {"n2", "j1"}


def test_hard_gate_candidate_nodes_read_deferred_plan(tmp_path) -> None:
    plan_path = tmp_path / "t06_step3_surface_aware_replacement_plan_final_topology_hard_gate_1.json"
    rows = [
        {
            "properties": {
                "source_reason": "final_frcsd_topology_hard_gate_failed",
                "swsd_pair_nodes": ["n1", "n2"],
                "swsd_junc_nodes": ["j1"],
                "final_topology_hard_gate_failure_node_ids": ["n1"],
            },
            "geometry": None,
        }
    ]
    (tmp_path / "t06_step3_summary.json").write_text(
        json.dumps({"input_paths": {"step2_replacement_plan_path": str(plan_path)}}),
        encoding="utf-8",
    )

    with defer_replacement_plan_writes():
        write_replacement_plan_json(plan_path, rows)
        assert not plan_path.exists()
        assert _hard_gate_cascade_node_ids(tmp_path) == {"n2", "j1"}
