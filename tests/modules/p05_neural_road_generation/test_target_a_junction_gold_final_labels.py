from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_gold_final_labels import (
    write_junction_gold_final_labels,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _base_label(
    *,
    sample_id: str,
    case_id: str,
    surface_state: str,
    fingerprint: str,
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "sample_group_id": f"junction:{case_id}",
        "case_id": case_id,
        "family": "T03",
        "source_scope": "POC_Data",
        "source_index": 1,
        "case_root": f"/case/{case_id}",
        "input_fingerprint": fingerprint,
        "label_weight": 1.0,
        "label_status": "READY",
        "t07_step1_has_evd": "yes",
        "t07_step2_is_anchor": "no",
        "surface_state": surface_state,
        "surface_geometry_sha256": f"surface-{fingerprint}",
        "relation_state": "rcsd_present_not_junction",
        "anchor_business_state": "QUALITY_ISSUE",
        "selected_rcsd_node_ids": [],
        "selected_rcsd_road_ids": [],
        "support_rcsd_node_ids": [],
        "support_rcsd_road_ids": ["10"],
        "route_class": "T03",
        "terminal_business_signature": "pre-t05",
    }


def _replay(
    *,
    tmp_path: Path,
    sample_id: str,
    status: str,
    consistency_passed: bool,
) -> dict[str, object]:
    run_root = tmp_path / sample_id
    run_root.mkdir()
    audit_path = run_root / "rcsd_junctionization_audit.json"
    audit_path.write_text('{"rows": []}', encoding="utf-8")
    (run_root / "summary.json").write_text(
        json.dumps(
            {
                "consistency": {
                    "passed": consistency_passed,
                    "split_road_endpoints_exist": consistency_passed,
                }
            }
        ),
        encoding="utf-8",
    )
    return {
        "sample_id": sample_id,
        "status": status,
        "scene": "road_only_split",
        "action": "split_rcsdroad_generate_rcsdnode",
        "selected_main_rcsdnode_id": "20",
        "original_rcsdroad_ids": ["10"],
        "new_rcsdroad_ids": ["11", "12"],
        "original_rcsdnode_ids": [],
        "new_rcsdnode_ids": ["20"],
        "grouped_rcsdnode_ids": ["20"],
        "phase2_audit_path": str(audit_path),
        "phase2_relation_path": str(run_root / "relation.geojson"),
        "phase2_rcsdroad_path": str(run_root / "road.gpkg"),
        "phase2_rcsdnode_path": str(run_root / "node.gpkg"),
    }


def test_final_labels_separate_complete_safety_and_not_applicable(
    tmp_path: Path,
) -> None:
    labels_path = tmp_path / "labels.jsonl"
    replay_path = tmp_path / "replay.jsonl"
    output = tmp_path / "out"
    labels = [
        _base_label(
            sample_id="success",
            case_id="100",
            surface_state="accepted",
            fingerprint="a",
        ),
        _base_label(
            sample_id="quality",
            case_id="200",
            surface_state="accepted",
            fingerprint="b",
        ),
        _base_label(
            sample_id="rejected",
            case_id="300",
            surface_state="rejected",
            fingerprint="c",
        ),
    ]
    replays = [
        _replay(
            tmp_path=tmp_path,
            sample_id="success",
            status="SUCCESS",
            consistency_passed=True,
        ),
        _replay(
            tmp_path=tmp_path,
            sample_id="quality",
            status="QUALITY_ISSUE",
            consistency_passed=False,
        ),
    ]
    _write_jsonl(labels_path, labels)
    _write_jsonl(replay_path, replays)

    summary = write_junction_gold_final_labels(
        base_labels_path=labels_path,
        t05_replay_path=replay_path,
        output_root=output,
    )

    assert summary["status"] == "JUNCTION_GOLD_FINAL_LABELS_GO"
    assert summary["complete_junction_gold_status_counts"] == {
        "READY": 2,
        "SAFETY_ONLY": 1,
    }
    rows = {
        row["sample_id"]: row
        for row in (
            json.loads(line)
            for line in (output / "junction_gold_final_labels.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    }
    assert rows["success"]["anchor_business_state"] == "SUCCESS"
    assert rows["success"]["junctionization_action_gold_status"] == "READY"
    assert rows["quality"]["complete_junction_gold_status"] == "SAFETY_ONLY"
    assert rows["quality"]["junctionization_action_gold_status"] == "ACTION_ONLY"
    assert rows["quality"]["t05_consistency_failures"] == [
        "split_road_endpoints_exist"
    ]
    assert rows["rejected"]["t05_replay_status"] == "NOT_APPLICABLE"


def test_final_signatures_recompute_multiversion_conflict(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    replay_path = tmp_path / "replay.jsonl"
    labels = [
        _base_label(
            sample_id="v1",
            case_id="100",
            surface_state="accepted",
            fingerprint="a",
        ),
        _base_label(
            sample_id="v2",
            case_id="100",
            surface_state="accepted",
            fingerprint="b",
        ),
    ]
    labels[1]["source_index"] = 2
    replays = [
        _replay(
            tmp_path=tmp_path,
            sample_id="v1",
            status="SUCCESS",
            consistency_passed=True,
        ),
        _replay(
            tmp_path=tmp_path,
            sample_id="v2",
            status="QUALITY_ISSUE",
            consistency_passed=False,
        ),
    ]
    _write_jsonl(labels_path, labels)
    _write_jsonl(replay_path, replays)

    summary = write_junction_gold_final_labels(
        base_labels_path=labels_path,
        t05_replay_path=replay_path,
        output_root=tmp_path / "out",
    )

    assert summary["source_version_conflicting_terminal_count"] == 1
