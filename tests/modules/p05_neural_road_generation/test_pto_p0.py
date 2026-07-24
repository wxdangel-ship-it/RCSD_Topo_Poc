from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from pyproj import CRS

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_candidates import canonical_edit_payload
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_models import PTOOracleSolveConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_p0 import _split_lineage_child_count, solve_pto_oracle_run
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_solver import truth_group_id
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import write_vector_payloads


def _payload(identifier: str, geometry: dict[str, Any], **properties: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "geometry": geometry,
        "properties": {"id": int(identifier), **properties},
        "source_role": "fixture",
    }


def _edit(kind: str, base_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_kind": kind,
        "action": "COPY",
        "base_object_id": base_id,
        "output_object_ids": [payload["id"]],
        "output_payloads": [payload],
        "lineage_kind": "fixture",
        "label_only": True,
        "sample_id": "oracle:fixture",
    }


def _candidate(stage: str, edit: dict[str, Any]) -> dict[str, Any]:
    group_id = truth_group_id(stage, edit)
    canonical = canonical_edit_payload(
        stage=stage,
        object_kind=edit["object_kind"],
        group_id=group_id,
        action=edit["action"],
        base_object_id=edit["base_object_id"],
        output_payloads=edit["output_payloads"],
    )
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    signature = hashlib.sha256(raw).hexdigest()
    return {
        "candidate_id": f"pto:{signature[:24]}",
        "sample_id": "t10:fixture",
        "family": "T10",
        "business_id": "fixture",
        "stage": stage,
        "object_kind": edit["object_kind"],
        "group_id": group_id,
        "group_mode": "EXACTLY_ONE",
        "action": edit["action"],
        "base_object_id": edit["base_object_id"],
        "output_object_ids": edit["output_object_ids"],
        "output_payloads": edit["output_payloads"],
        "lineage_kind": "fixture",
        "pointer_value": "",
        "canonical_payload_sha256": signature,
        "sources": [{"source_kind": "STRATEGY_REPLAY"}],
        "label_only": False,
        "truth_derived": False,
    }


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _vector_meta(kind: str) -> dict[str, Any]:
    if kind == "Road":
        properties = {"id": "int64", "snodeid": "int64", "enodeid": "int64", "direction": "int", "source": "int"}
        geometry = "LineString"
    else:
        properties = {"id": "int64"}
        geometry = "Point"
    return {
        "layer": kind.casefold(),
        "schema": {"geometry": geometry, "properties": properties},
        "crs_wkt": CRS.from_epsg(3857).to_wkt(),
    }


def test_split_lineage_child_count_is_action_independent() -> None:
    split_child = _payload(
        "10",
        {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 0.0]]},
        t06_split_original_road_id=1,
    )
    created_child = _payload(
        "11",
        {"type": "LineString", "coordinates": [[0.0, 1.0], [1.0, 1.0]]},
        t06_split_original_road_id=2,
    )
    ordinary = _payload("12", {"type": "LineString", "coordinates": [[0.0, 2.0], [1.0, 2.0]]})
    edits = [
        {"action": "SPLIT", "output_payloads": [split_child]},
        {"action": "CREATE", "output_payloads": [created_child, ordinary]},
    ]

    assert _split_lineage_child_count(edits) == 2


def test_pto_p0_end_to_end_fixture(tmp_path: Path) -> None:
    node1 = _payload("1", {"type": "Point", "coordinates": [0.0, 0.0]})
    node2 = _payload("2", {"type": "Point", "coordinates": [1.0, 0.0]})
    road = _payload(
        "3",
        {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 0.0]]},
        snodeid=1,
        enodeid=2,
        direction=1,
        source=1,
    )
    road_edit = _edit("Road", "3", road)
    node_edits = [_edit("Node", "1", node1), _edit("Node", "2", node2)]

    truth_root = tmp_path / "truth"
    truth_road = truth_root / "road.gpkg"
    truth_node = truth_root / "node.gpkg"
    truth_t05 = truth_root / "t05_node.gpkg"
    write_vector_payloads(truth_road, [road], meta=_vector_meta("Road"))
    write_vector_payloads(truth_node, [node1, node2], meta=_vector_meta("Node"))
    write_vector_payloads(truth_t05, [node1, node2], meta=_vector_meta("Node"))

    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidates = [_candidate("FINAL_ROAD", road_edit)]
    candidates.extend(_candidate("FINAL_NODE", edit) for edit in node_edits)
    candidates.extend(_candidate("T05_NODE", edit) for edit in node_edits)
    candidate_path = candidate_root / "p05_pto_candidates.jsonl"
    _jsonl(candidate_path, candidates)
    case_index_path = candidate_root / "p05_pto_candidate_case_index.csv"
    write_csv(
        case_index_path,
        [{"family": "T10", "business_id": "fixture", "candidate_signature": "fixture", "candidate_build_seconds": 0.01, "replay_duration_seconds": 0.02}],
        ["family", "business_id", "candidate_signature", "candidate_build_seconds", "replay_duration_seconds"],
    )
    candidate_manifest = {
        "status": "candidate_scope_passed",
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "silent_fix": False,
        "outputs": {"candidates": output_record(candidate_path), "case_index": output_record(case_index_path)},
    }
    write_json(candidate_root / "p05_pto_candidate_manifest.json", candidate_manifest)

    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    road_edit_path = oracle_root / "p05_r2_road_edits.jsonl"
    node_edit_path = oracle_root / "p05_r2_node_edits.jsonl"
    t05_edit_path = oracle_root / "p05_r2_t05_node_edits.jsonl"
    _jsonl(road_edit_path, [road_edit])
    _jsonl(node_edit_path, node_edits)
    _jsonl(t05_edit_path, node_edits)
    pointer_path = oracle_root / "p05_r2_t05_pointers.csv"
    with pointer_path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.DictWriter(stream, fieldnames=["sample_id", "target_id", "selected_base_id", "label_only"]).writeheader()
    oracle_case_index = oracle_root / "p05_r2_case_index.csv"
    write_csv(
        oracle_case_index,
        [{"sample_id": "oracle:fixture", "family": "T10", "business_id": "fixture", "truth_road_path": str(truth_road), "truth_node_path": str(truth_node), "t05_node_truth_path": str(truth_t05)}],
        ["sample_id", "family", "business_id", "truth_road_path", "truth_node_path", "t05_node_truth_path"],
    )
    oracle_manifest = {
        "status": "gate1_passed",
        "silent_fix": False,
        "outputs": {
            "case_index": output_record(oracle_case_index),
            "road_edits": output_record(road_edit_path),
            "node_edits": output_record(node_edit_path),
            "t05_node_edits": output_record(t05_edit_path),
            "t05_pointers": output_record(pointer_path),
        },
    }
    write_json(oracle_root / "p05_r2_oracle_manifest.json", oracle_manifest)

    summary = solve_pto_oracle_run(
        PTOOracleSolveConfig(
            candidate_run_root=candidate_root,
            r2_oracle_run_root=oracle_root,
            output_root=tmp_path,
            run_id="solve",
            expected_case_count=1,
        )
    )
    assert summary["optimal_case_count"] == 1
    assert summary["semantic_exact_case_count"] == 1
    assert summary["hard_failure_count"] == 0
    assert summary["relaxation"] is False
    assert (tmp_path / "solve" / "cases").is_dir()
