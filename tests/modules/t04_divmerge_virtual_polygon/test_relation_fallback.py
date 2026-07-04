from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import Point

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.final_publish import RELATION_EVIDENCE_FIELDNAMES
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.relation_fallback import (
    enrich_t04_relation_evidence_with_fallback,
)


def _write_relation_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RELATION_EVIDENCE_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in RELATION_EVIDENCE_FIELDNAMES})


def test_t04_relation_fallback_overwrites_evidence_and_covers_runtime_failed(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_relation_csv(
        run_root / "t04_swsd_rcsd_relation_evidence.csv",
        [
            {
                "target_id": "2002",
                "case_id": "2002",
                "junction_type": "diverge",
                "final_state": "rejected",
                "required_rcsd_node_ids": "22",
                "surface_candidate_present": 0,
                "base_id_candidate": -1,
                "status_suggested": 1,
                "relation_state": "geometry_not_accepted",
                "reason": "multi_component_result",
                "swsd_point_x": 2,
                "swsd_point_y": 0,
            }
        ],
    )
    runtime_unit_dir = run_root / "cases" / "3003" / "event_units" / "node_3003"
    runtime_unit_dir.mkdir(parents=True)
    (runtime_unit_dir / "step4_candidates.json").write_text(
        json.dumps({"case_id": "3003", "required_rcsd_node": "31"}),
        encoding="utf-8",
    )

    outputs = enrich_t04_relation_evidence_with_fallback(
        run_root=run_root,
        selected_cases=[
            {"case_id": "2002", "mainnodeid": "2002"},
            {"case_id": "3003", "mainnodeid": "3003"},
        ],
        source_node_features=[
            {"properties": {"id": "2002", "mainnodeid": "2002", "kind_2": 16}, "geometry": Point(2, 0)},
            {"properties": {"id": "3003", "mainnodeid": "3003", "kind_2": 16}, "geometry": Point(3, 0)},
        ],
        rcsdnode_features=[
            {"properties": {"id": "20", "mainnodeid": "20"}, "geometry": Point(20, 0)},
            {"properties": {"id": "22", "mainnodeid": "20"}, "geometry": Point(22, 0)},
            {"properties": {"id": "30", "mainnodeid": "30"}, "geometry": Point(30, 0)},
            {"properties": {"id": "31", "mainnodeid": "30"}, "geometry": Point(31, 0)},
        ],
        failure_status_by_case={"3003": {"step7_state": "runtime_failed", "reason": "runtime_failed"}},
        input_dataset_id="unit-test-input",
    )

    with (run_root / "t04_swsd_rcsd_relation_evidence.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {row["case_id"]: row for row in csv.DictReader(handle)}
    payload = json.loads((run_root / "t04_swsd_rcsd_relation_evidence.json").read_text(encoding="utf-8"))

    assert outputs["fallback_success_case_ids"] == ["2002", "3003"]
    assert payload["fallback_success_count"] == 2
    assert rows["2002"]["status_suggested"] == "0"
    assert rows["2002"]["base_id_candidate"] == "20"
    assert rows["2002"]["relation_state"] == "success_required_rcsd_junction"
    assert rows["2002"]["surface_candidate_present"] == "0"
    assert rows["3003"]["status_suggested"] == "0"
    assert rows["3003"]["base_id_candidate"] == "30"
    assert rows["3003"]["final_state"] == "runtime_failed"
    assert (run_root / "t04_relation_fallback_audit.csv").is_file()


def test_t04_relation_fallback_rejects_zero_mainnode_group(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_relation_csv(
        run_root / "t04_swsd_rcsd_relation_evidence.csv",
        [
            {
                "target_id": "987955",
                "case_id": "987955",
                "junction_type": "diverge",
                "final_state": "rejected",
                "required_rcsd_node_ids": "5396513947461929",
                "surface_candidate_present": 0,
                "base_id_candidate": -1,
                "status_suggested": 1,
                "relation_state": "geometry_not_accepted",
                "reason": "multi_component_result",
            }
        ],
    )

    outputs = enrich_t04_relation_evidence_with_fallback(
        run_root=run_root,
        selected_cases=[{"case_id": "987955", "mainnodeid": "987955"}],
        source_node_features=[
            {"properties": {"id": "987955", "mainnodeid": "987955", "kind_2": 16}, "geometry": Point(0, 0)},
        ],
        rcsdnode_features=[
            {"properties": {"id": "5396513947461929", "mainnodeid": 0}, "geometry": Point(10, 0)},
        ],
        input_dataset_id="unit-test-input",
    )

    with (run_root / "t04_swsd_rcsd_relation_evidence.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {row["case_id"]: row for row in csv.DictReader(handle)}
    with (run_root / "t04_relation_fallback_audit.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        audit_rows = {row["case_id"]: row for row in csv.DictReader(handle)}

    assert outputs["fallback_success_case_ids"] == []
    assert rows["987955"]["status_suggested"] == "1"
    assert rows["987955"]["base_id_candidate"] == "-1"
    assert rows["987955"]["relation_state"] == "geometry_not_accepted"
    assert audit_rows["987955"]["fallback_state"] == "failed"
    assert audit_rows["987955"]["reason"] == "invalid_rcsdnode_group_id:5396513947461929=0"


def test_t04_relation_fallback_accepts_zero_mainnode_singleton_with_strong_rcsd_profile(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_relation_csv(
        run_root / "t04_swsd_rcsd_relation_evidence.csv",
        [
            {
                "target_id": "1206756",
                "case_id": "1206756",
                "junction_type": "merge",
                "final_state": "rejected",
                "required_rcsd_node_ids": "5384381972227452",
                "selected_rcsdnode_ids": "5384381972227452",
                "rcsd_profile": "A=1|B=0|C=0",
                "surface_candidate_present": 0,
                "base_id_candidate": -1,
                "status_suggested": 1,
                "relation_state": "geometry_not_accepted",
                "reason": "multi_component_result",
            }
        ],
    )

    outputs = enrich_t04_relation_evidence_with_fallback(
        run_root=run_root,
        selected_cases=[{"case_id": "1206756", "mainnodeid": "1206756"}],
        source_node_features=[
            {"properties": {"id": "1206756", "mainnodeid": "1206756", "kind_2": 8}, "geometry": Point(0, 0)},
        ],
        rcsdnode_features=[
            {"properties": {"id": "5384381972227452", "mainnodeid": 0}, "geometry": Point(10, 0)},
        ],
        input_dataset_id="unit-test-input",
    )

    with (run_root / "t04_swsd_rcsd_relation_evidence.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {row["case_id"]: row for row in csv.DictReader(handle)}
    with (run_root / "t04_relation_fallback_audit.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        audit_rows = {row["case_id"]: row for row in csv.DictReader(handle)}

    assert outputs["fallback_success_case_ids"] == ["1206756"]
    assert rows["1206756"]["status_suggested"] == "0"
    assert rows["1206756"]["base_id_candidate"] == "5384381972227452"
    assert rows["1206756"]["relation_state"] == "success_required_rcsd_junction"
    assert audit_rows["1206756"]["fallback_state"] == "success"
    assert audit_rows["1206756"]["reason"] == "required_rcsd_singleton_node_resolved_from_strong_rcsd_profile"
