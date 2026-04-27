from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import Point

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.nodes_publish import (
    T04_NODES_FAILED_VALUE,
    augment_step7_consistency_report,
    write_t04_nodes_outputs,
)


def _node_rows_by_id(path: Path) -> dict[str, dict]:
    fiona = pytest.importorskip("fiona")
    with fiona.open(path) as src:
        return {str(row["properties"]["id"]): dict(row["properties"]) for row in src}


def test_t04_nodes_publish_copy_on_write_and_audit_consistency(tmp_path: Path) -> None:
    pytest.importorskip("fiona")
    run_root = tmp_path / "run"
    run_root.mkdir()
    consistency_report_path = run_root / "step7_consistency_report.json"
    consistency_report_path.write_text(json.dumps({"passed": True}), encoding="utf-8")

    artifacts = [
        SimpleNamespace(case_id="1001", final_state="accepted", reject_reasons=()),
        SimpleNamespace(case_id="2002", final_state="rejected", reject_reasons=("multi_component_result",)),
    ]
    source_features = [
        {
            "properties": {
                "id": "1001",
                "mainnodeid": "1001",
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 16,
                "grade_2": 1,
            },
            "geometry": Point(0, 0),
        },
        {
            "properties": {
                "id": "1101",
                "mainnodeid": "1001",
                "has_evd": "no",
                "is_anchor": "no",
                "kind_2": 0,
                "grade_2": 0,
            },
            "geometry": Point(1, 0),
        },
        {
            "properties": {
                "id": "2002",
                "mainnodeid": "2002",
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 16,
                "grade_2": 1,
            },
            "geometry": Point(2, 0),
        },
        {
            "properties": {
                "id": "3003",
                "mainnodeid": "3003",
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 16,
                "grade_2": 1,
            },
            "geometry": Point(3, 0),
        },
        {
            "properties": {
                "id": "9999",
                "mainnodeid": "9999",
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 16,
                "grade_2": 1,
            },
            "geometry": Point(9, 0),
        },
    ]

    nodes_outputs = write_t04_nodes_outputs(
        run_root=run_root,
        source_node_features=source_features,
        selected_cases=[
            {"case_id": "1001", "mainnodeid": "1001"},
            {"case_id": "2002", "mainnodeid": "2002"},
            {"case_id": "3003", "mainnodeid": "3003"},
        ],
        artifacts=artifacts,
        failure_status_by_case={"3003": {"step7_state": "runtime_failed", "reason": "runtime_failed"}},
        input_dataset_id="unit-test-input",
    )
    consistency = augment_step7_consistency_report(
        consistency_report_path=consistency_report_path,
        nodes_outputs=nodes_outputs,
    )

    rows_by_id = _node_rows_by_id(run_root / "nodes.gpkg")
    assert rows_by_id["1001"]["is_anchor"] == "yes"
    assert rows_by_id["1101"]["is_anchor"] == "no"
    assert rows_by_id["2002"]["is_anchor"] == T04_NODES_FAILED_VALUE
    assert rows_by_id["3003"]["is_anchor"] == T04_NODES_FAILED_VALUE
    assert rows_by_id["9999"]["is_anchor"] == "no"

    with (run_root / "nodes_anchor_update_audit.csv").open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    audit_json = json.loads((run_root / "nodes_anchor_update_audit.json").read_text(encoding="utf-8"))
    rows_by_case = {row["case_id"]: row for row in audit_json["rows"]}

    assert len(csv_rows) == 3
    assert audit_json["input_dataset_id"] == "unit-test-input"
    assert audit_json["total_update_count"] == 3
    assert audit_json["updated_to_yes_count"] == 1
    assert audit_json["updated_to_fail4_count"] == 2
    assert rows_by_case["1001"]["new_is_anchor"] == "yes"
    assert rows_by_case["1001"]["reason"] == "accepted_divmerge_virtual_anchor_surface"
    assert rows_by_case["2002"]["new_is_anchor"] == T04_NODES_FAILED_VALUE
    assert rows_by_case["2002"]["reason"] == "multi_component_result"
    assert rows_by_case["3003"]["step7_state"] == "runtime_failed"
    assert rows_by_case["3003"]["new_is_anchor"] == T04_NODES_FAILED_VALUE

    assert nodes_outputs["nodes_consistency_passed"] is True
    assert consistency["passed"] is True
    assert consistency["nodes_consistency_passed"] is True
    assert consistency["nodes_total_update_count"] == 3
