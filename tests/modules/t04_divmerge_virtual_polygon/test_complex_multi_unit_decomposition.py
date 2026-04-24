from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


def test_real_case_505078921_splits_complex_three_merge_and_keeps_internal_cuts_out(
    tmp_path: Path,
) -> None:
    if not (REAL_ANCHOR_2_ROOT / "505078921").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '505078921'}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["505078921"],
        out_root=tmp_path / "anchor2_505078921_complex_multi_unit",
        run_id="anchor2_505078921_complex_multi_unit",
    )

    step4_doc = json.loads(
        (run_root / "cases" / "505078921" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    units = {unit["event_unit_id"]: unit for unit in step4_doc["event_units"]}
    assert set(units) == {
        "node_505078921",
        "node_510222629",
        "node_510222629__pair_02",
    }
    assert units["node_510222629"]["unit_envelope"]["boundary_branch_ids"] == ["road_1", "road_2"]
    assert units["node_510222629__pair_02"]["unit_envelope"]["boundary_branch_ids"] == [
        "road_2",
        "road_3",
    ]
    assert units["node_505078921"]["selected_evidence_state"] != "none"
    assert units["node_505078921"]["required_rcsd_node"] == "5385438602535104"
    assert units["node_505078921"]["local_rcsd_unit_id"] == "node_505078921:node:5385438602535104"
    assert set(units["node_505078921"]["selected_rcsdroad_ids"]) == {
        "5385458768741628",
        "5385458768741632",
        "5385458768741665",
    }
    assert units["node_510222629"]["selected_evidence_state"] == "found"
    assert units["node_510222629__pair_02"]["selected_evidence_state"] == "found"
    assert units["node_510222629__pair_02"]["evidence_source"] == "road_surface_fork"
    assert units["node_510222629__pair_02"]["selected_evidence"]["candidate_scope"] == "road_surface_fork"

    step5_doc = json.loads(
        (run_root / "cases" / "505078921" / "step5_status.json").read_text(encoding="utf-8")
    )
    assert step5_doc["unit_count"] == 3
    assert step5_doc["case_terminal_cut_constraints"]["length_m"] < 50.0

    step6_doc = json.loads(
        (run_root / "cases" / "505078921" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_doc["hole_count"] == 0
    assert step6_doc["cut_violation"] is False
    assert step6_doc["final_case_polygon"]["area_m2"] > 2500.0

    step7_doc = json.loads(
        (run_root / "cases" / "505078921" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert step7_doc["final_state"] == "accepted"
