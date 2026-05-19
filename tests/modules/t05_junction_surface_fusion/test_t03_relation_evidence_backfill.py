from __future__ import annotations

import csv
import json
from pathlib import Path

from rcsd_topo_poc.modules.t05_junction_surface_fusion.t03_relation_evidence_backfill import (
    backfill_t03_relation_evidence,
)

from tests.modules.t05_junction_surface_fusion.test_phase2_rcsd_junctionization import (
    _T03_FIELDS,
    _layer_props,
    _node,
    _relation_features,
    _road,
    _run_phase2,
    _summary,
    _surface,
)


def test_t03_backfill_reads_step6_status_and_enables_phase2_grouping_and_split(tmp_path: Path) -> None:
    t03_root = tmp_path / "t03_run"
    _write_t03_relation_evidence(
        t03_root / "t03_swsd_rcsd_relation_evidence.csv",
        [
            {
                "target_id": "100",
                "case_id": "100",
                "junction_type": "center_junction",
                "association_class": "A",
                "step7_state": "accepted",
                "surface_candidate_present": "1",
                "base_id_candidate": "-1",
                "status_suggested": "1",
                "relation_state": "ambiguous_review",
                "reason": "step7_accepted",
            },
            {
                "target_id": "200",
                "case_id": "200",
                "junction_type": "center_junction",
                "association_class": "B",
                "step7_state": "accepted",
                "surface_candidate_present": "1",
                "base_id_candidate": "-1",
                "status_suggested": "1",
                "relation_state": "ambiguous_review",
                "reason": "step7_accepted",
            },
        ],
    )
    _write_json(
        t03_root / "cases" / "100" / "step6_status.json",
        {
            "case_id": "100",
            "association_class": "A",
            "required_rcsdnode_ids": ["10", "11"],
            "required_rcsdroad_ids": ["1"],
            "support_rcsdroad_ids": [],
        },
    )
    _write_json(
        t03_root / "cases" / "200" / "step6_status.json",
        {
            "case_id": "200",
            "association_class": "B",
            "required_rcsdnode_ids": [],
            "support_rcsdnode_ids": ["20"],
            "support_rcsdroad_ids": ["1"],
        },
    )

    backfilled = backfill_t03_relation_evidence(
        t03_run_root=t03_root,
        out_root=tmp_path / "handoff",
        accepted_only=True,
    )
    rows = _read_csv(backfilled.evidence_csv_path)

    assert rows["100"]["required_rcsdnode_ids"] == "10|11"
    assert rows["100"]["base_id_candidate"] == "10|11"
    assert rows["100"]["status_suggested"] == "0"
    assert rows["100"]["relation_state"] == "success_required_rcsd_junction"
    assert rows["200"]["support_rcsdroad_ids"] == "1"
    assert rows["200"]["relation_state"] == "rcsd_present_not_junction"

    phase2_root = tmp_path / "phase2"
    phase2_root.mkdir()
    artifacts = _run_phase2(
        phase2_root,
        surface_features=[_surface("100"), _surface("200")],
        swsd_nodes=[
            _node(100, 0, 0, mainnodeid="100", grade=2, closed_con=1),
            _node(200, -3, 1, mainnodeid="200", kind_2=4),
            _node(201, 3, 1, mainnodeid="200", kind_2=4),
        ],
        rcsd_roads=[_road(1, (-10, 0), (10, 0))],
        rcsd_nodes=[
            _node(1, -10, 0),
            _node(2, 10, 0),
            _node(10, 1, 0),
            _node(11, 6, 0),
        ],
        t03_rows=list(rows.values()),
    )

    relations = _relation_features(artifacts.relation_geojson_path)
    assert len(relations) == 2
    assert {item["properties"]["target_id"] for item in relations} == {"100", "200"}
    assert all(item["properties"]["status"] == 0 for item in relations)
    summary = _summary(artifacts)
    assert summary["status_0_count"] == 2
    assert summary["status_1_count"] == 0
    assert summary["rcsdnode_generated_count"] == 2
    assert summary["rcsdnode_grouped_count"] == 4
    out_nodes = {row["id"]: row for row in _layer_props(artifacts.rcsdnode_out_path)}
    assert out_nodes[10]["mainnodeid"] == 10
    assert out_nodes[11]["mainnodeid"] == 10


def _write_t03_relation_evidence(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=_T03_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in _T03_FIELDS})


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_csv(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fp:
        return {row["target_id"]: dict(row) for row in csv.DictReader(fp)}
