from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_ledger import (
    build_ordinary_joint_ledger_store,
)


def test_build_ordinary_joint_ledger_keeps_partial_truth_masked(
    tmp_path: Path,
) -> None:
    candidates = tmp_path / "candidates"
    plans = tmp_path / "plans"
    roads = tmp_path / "roads"
    access = tmp_path / "access"
    breaks = tmp_path / "breaks"
    for root in (candidates, plans, roads, access, breaks):
        root.mkdir()
    _write_jsonl(
        candidates / "inference_plan_groups.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "segment_type": "STANDARD",
                "fold": 1,
                "required_anchor_ids": ["a", "b"],
                "junc_node_ids": ["a", "b"],
                "candidates": [
                    {
                        "plan_id": "keep",
                        "decision": "KEEP_SWSD",
                        "road_ids": ["swsd"],
                        "road_roles": [{"road_id": "swsd", "role": "MAIN"}],
                        "owned_road_ids": ["swsd"],
                        "arm_rows": [
                            {"nearest_road_id": "swsd", "nearest_node_id": "n1"},
                            {"nearest_road_id": "swsd", "nearest_node_id": "n2"},
                        ],
                        "hard_valid": True,
                    },
                    {
                        "plan_id": "abstain",
                        "decision": "ABSTAIN",
                        "road_ids": [],
                        "road_roles": [],
                        "owned_road_ids": [],
                        "arm_rows": [],
                        "hard_valid": True,
                    },
                ],
            }
        ],
    )
    _write_jsonl(
        plans / "training_plan_labels.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "segment_type": "STANDARD",
                "fold": 1,
                "training_task_mask": True,
                "carrier_task_mask": True,
                "label_weight": 0.7,
                "acceptable_plan_ids": ["keep"],
                "preferred_plan_id": "keep",
                "preferred_carrier_target": "KEEP_SWSD",
                "reality_change_clue": False,
                "clue_task_mask": True,
                "fallback_scope": "NONE",
                "fallback_scope_task_mask": True,
            }
        ],
    )
    _write_jsonl(
        roads / "ordinary_road_member_features.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "fold": 1,
                "candidate_rows": [{"road_id": "swsd"}],
            }
        ],
    )
    _write_jsonl(
        roads / "ordinary_road_member_labels.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "fold": 1,
                "task_mask": True,
                "sample_weight": 0.7,
                "acceptable_road_ids": ["swsd"],
                "road_member_sample_weights": [0.7],
                "road_business_role_targets": [0],
                "road_business_role_task_mask": [True],
                "road_business_role_sample_weight": 0.7,
                "road_ownership_targets": [1],
                "road_ownership_task_mask": [False],
                "road_ownership_sample_weight": 0.0,
                "unreachable_target_road_ids": [],
            }
        ],
    )
    _write_jsonl(
        access / "ordinary_access_collection_labels.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "junction_id": "a",
                "fold": 1,
                "collection_task_mask": True,
                "collection_label_weight": 0.7,
                "collection_label_state": "RESOLVED_COMPLETE_ACCESS_COLLECTION",
                "required_final_road_ids": ["swsd"],
                "required_final_access_node_ids": ["n1"],
                "acceptable_access_collections": [{"collection_id": "c1"}],
            },
            {
                "case_key": "T10:case",
                "segment_id": "s1",
                "junction_id": "b",
                "fold": 1,
                "collection_task_mask": False,
                "collection_label_weight": 0.0,
                "collection_label_state": "EXEMPT_JUNC_NODE_NO_REQUIRED_ACCESS",
                "required_final_road_ids": [],
                "required_final_access_node_ids": [],
                "acceptable_access_collections": [],
            },
        ],
    )
    _write_jsonl(breaks / "parent_road_break_tasks.jsonl", [])

    root = build_ordinary_joint_ledger_store(
        candidate_store_root=candidates,
        plan_label_root=plans,
        road_member_store_root=roads,
        access_collection_store_root=access,
        break_task_store_root=breaks,
        output_root=tmp_path,
        run_id="ledger",
    )
    row = json.loads(
        (root / "ordinary_joint_ledger.jsonl").read_text(encoding="utf-8")
    )
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))

    assert row["plan_label"]["preferred_decision"] == "KEEP_SWSD"
    assert row["candidate_plans"][1]["decision"] == "ABSTAIN"
    assert row["field_coverage"]["role_complete_for_truth_roads"] is True
    assert row["field_coverage"]["ownership_complete_for_truth_roads"] is False
    assert row["field_coverage"]["access_complete_for_required_junctions"] is True
    assert row["field_coverage"]["break_complete_for_required_parent_roads"] is True
    assert row["field_coverage"]["full_business_evaluable"] is False
    assert row["label_only"] is True
    assert row["inference_input_allowed"] is False
    assert summary["gate_pass"] is True
    assert summary["io_contract"]["candidate_store_reads"] == 1


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
