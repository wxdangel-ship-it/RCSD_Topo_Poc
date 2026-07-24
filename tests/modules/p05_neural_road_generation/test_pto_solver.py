from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.pto_candidates import canonical_edit_payload
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_solver import solve_oracle_case, truth_group_id


def _payload(identifier: str, geometry: dict[str, Any], **properties: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "geometry": geometry,
        "properties": {"id": int(identifier), **properties},
        "source_role": "fixture",
    }


def _edit(kind: str, action: str, base_id: str, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object_kind": kind,
        "action": action,
        "base_object_id": base_id,
        "output_object_ids": [item["id"] for item in outputs],
        "output_payloads": outputs,
        "lineage_kind": "fixture",
        "label_only": True,
    }


def _candidate(stage: str, edit: dict[str, Any], suffix: str = "") -> dict[str, Any]:
    group_id = truth_group_id(stage, edit)
    canonical = canonical_edit_payload(
        stage=stage,
        object_kind=edit["object_kind"],
        group_id=group_id,
        action=edit["action"],
        base_object_id=edit["base_object_id"],
        output_payloads=edit["output_payloads"],
    )
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    signature = hashlib.sha256(raw).hexdigest()
    return {
        "candidate_id": f"candidate:{signature[:12]}{suffix}",
        "stage": stage,
        "object_kind": edit["object_kind"],
        "group_id": group_id,
        "group_mode": "EXACTLY_ONE" if edit["base_object_id"] else "OPTIONAL_AT_MOST_ONE",
        "action": edit["action"],
        "base_object_id": edit["base_object_id"],
        "output_object_ids": edit["output_object_ids"],
        "output_payloads": edit["output_payloads"],
        "canonical_payload_sha256": signature,
        "pointer_value": "",
        "label_only": False,
        "truth_derived": False,
    }


def _fixture() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
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
    road_edit = _edit("Road", "COPY", "3", [road])
    node_edits = [_edit("Node", "COPY", "1", [node1]), _edit("Node", "COPY", "2", [node2])]
    t05_edits = [_edit("Node", "COPY", "1", [node1]), _edit("Node", "COPY", "2", [node2])]
    truth = {"FINAL_ROAD": [road_edit], "FINAL_NODE": node_edits, "T05_NODE": t05_edits}
    candidates = [_candidate("FINAL_ROAD", road_edit)]
    candidates.extend(_candidate("FINAL_NODE", edit) for edit in node_edits)
    candidates.extend(_candidate("T05_NODE", edit) for edit in t05_edits)
    return candidates, truth


def test_oracle_solver_returns_zero_gap_legal_graph() -> None:
    candidates, truth = _fixture()
    result = solve_oracle_case(candidates, truth, [])
    assert result["status"] == "OPTIMAL"
    assert result["objective"] == result["lower_bound"] == 0.0
    assert result["optimality_gap"] == 0.0
    assert result["hard_failures"] == []
    assert len(result["costs"]) == len(candidates)
    assert set(result["roads"]) == {"3"}
    assert set(result["nodes"]) == {"1", "2"}
    assert all(value == 1.0 for value in result["coverage_by_action"].values())


def test_oracle_solver_reports_missing_candidate_without_relaxation() -> None:
    candidates, truth = _fixture()
    result = solve_oracle_case(candidates[1:], truth, [])
    assert result["status"] == "INFEASIBLE"
    assert result["missing_groups"] == ["FINAL_ROAD:BASE:3"]
    assert result["relaxation"] is False
    assert result["content_repair"] is False
    assert result["silent_fix"] is False


def test_oracle_solver_rejects_missing_endpoint_reference() -> None:
    candidates, truth = _fixture()
    truth["FINAL_NODE"] = truth["FINAL_NODE"][:1]
    candidates = [item for item in candidates if not (item["stage"] == "FINAL_NODE" and item["base_object_id"] == "2")]
    result = solve_oracle_case(candidates, truth, [])
    assert result["status"] == "INFEASIBLE"
    assert any("missing enodeid=2" in failure for failure in result["hard_failures"])


def test_oracle_solver_is_deterministic() -> None:
    candidates, truth = _fixture()
    first = solve_oracle_case(list(reversed(candidates)), truth, [])
    second = solve_oracle_case(candidates, truth, [])
    assert [item["candidate_id"] for item in first["selected"]] == [
        item["candidate_id"] for item in second["selected"]
    ]


def test_oracle_solver_rejects_truth_derived_candidate() -> None:
    candidates, truth = _fixture()
    candidates[0]["truth_derived"] = True
    with pytest.raises(ValueError, match="leakage flag"):
        solve_oracle_case(candidates, truth, [])
