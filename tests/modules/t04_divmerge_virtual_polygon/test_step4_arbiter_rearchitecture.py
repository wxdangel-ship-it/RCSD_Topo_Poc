from __future__ import annotations

import json

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_loader import (
    load_case_bundle,
    load_case_specs,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.event_interpretation import build_case_result
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.outputs import write_case_outputs
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_final_conflict_resolver import (
    resolve_step4_final_conflicts,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_road_surface_fork_binding import (
    apply_road_surface_fork_binding,
)
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


def _case_after_surface_binding(case_id: str):
    case_dir = REAL_ANCHOR_2_ROOT / case_id
    if not case_dir.is_dir():
        pytest.skip(f"missing real case package: {case_dir}")
    specs, _preflight = load_case_specs(case_root=REAL_ANCHOR_2_ROOT, case_ids=[case_id])
    case_result = build_case_result(load_case_bundle(specs[0]))
    resolved, _resolution_doc = resolve_step4_final_conflicts([case_result])
    surface_results, _surface_doc = apply_road_surface_fork_binding(resolved)
    return surface_results[0]


def test_ledger_dual_write_parity(tmp_path) -> None:
    case_result = _case_after_surface_binding("724067")
    units_with_ledger = [
        unit
        for unit in case_result.event_units
        if unit.step4_candidate_ledger is not None and unit.step4_candidate_ledger.candidates
    ]
    assert units_with_ledger

    for unit in units_with_ledger:
        assert unit.step4_candidate_ledger is not None
        candidates = unit.step4_candidate_ledger.candidates
        assert len(candidates) == len(unit.dual_write_manifest)
        for candidate, manifest in zip(candidates, unit.dual_write_manifest):
            assert manifest["source_stage"] == candidate.source_stage
            assert manifest["candidate_id"] == candidate.candidate_id
            assert manifest["fields_written"]
            snapshot = candidate.source_audit_blob["unit_snapshot"]
            assert snapshot["selected_rcsdroad_ids"] == list(candidate.rcsdroad_ids)
            assert snapshot["selected_rcsdnode_ids"] == list(candidate.rcsdnode_ids)
            assert snapshot["required_rcsd_node"] == candidate.required_rcsd_node
            assert snapshot["positive_rcsd_present"] == bool(candidate.required_rcsd_node or candidate.rcsdroad_ids or candidate.rcsdnode_ids) or snapshot["positive_rcsd_present"] is False

    write_case_outputs(run_root=tmp_path, case_result=case_result)
    audit = json.loads(
        (tmp_path / "cases" / case_result.case_spec.case_id / "step4_audit.json").read_text(encoding="utf-8")
    )
    assert "step4_candidate_ledger" in audit
    assert "dual_write_manifest" in audit
    assert len(audit["step4_candidate_ledger"]) == len(case_result.event_units)
    assert audit["dual_write_manifest"]
