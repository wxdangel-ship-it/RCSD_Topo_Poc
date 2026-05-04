from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._step4_arbiter import (
    apply_step4_arbitration_to_case_result,
    arbitrate_step4_unit,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._step4_arbiter_models import (
    T04ArbiterCaseContext,
    ARBITER_FINAL_FIELD_NAMES,
    T04Step4Candidate,
    T04Step4CandidateLedger,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_loader import (
    load_case_bundle,
    load_case_specs,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.event_interpretation import build_case_result
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.outputs import (
    write_case_outputs,
    write_review_index,
    write_review_summary,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.rcsd_alignment import (
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_ROAD_ONLY,
    RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_final_conflict_resolver import (
    resolve_step4_final_conflicts,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_road_surface_fork_binding import (
    apply_road_surface_fork_binding,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.surface_scenario import (
    SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
)
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


REPO_ROOT = Path(__file__).resolve().parents[3]
T04_SRC_ROOT = REPO_ROOT / "src" / "rcsd_topo_poc" / "modules" / "t04_divmerge_virtual_polygon"


def _case_after_surface_binding(case_id: str):
    case_dir = REAL_ANCHOR_2_ROOT / case_id
    if not case_dir.is_dir():
        pytest.skip(f"missing real case package: {case_dir}")
    specs, _preflight = load_case_specs(case_root=REAL_ANCHOR_2_ROOT, case_ids=[case_id])
    case_result = build_case_result(load_case_bundle(specs[0]))
    resolved, _resolution_doc = resolve_step4_final_conflicts([case_result])
    surface_results, _surface_doc = apply_road_surface_fork_binding(resolved)
    return surface_results[0]


def _ledger_for(unit, case_id: str, *candidates: T04Step4Candidate) -> T04Step4CandidateLedger:
    ledger = T04Step4CandidateLedger(unit_id=unit.spec.event_unit_id, case_id=case_id)
    return ledger.extend(candidates)


def _context_for(unit, case_id: str) -> T04ArbiterCaseContext:
    return T04ArbiterCaseContext(
        case_id=case_id,
        unit_id=unit.spec.event_unit_id,
        mainnodeid=unit.spec.representative_node_id,
        shadow_mode=True,
    )


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
    assert "arbitration_decision_trace" in audit
    assert "arbitration_decision_shadow" in audit


def test_ledger_append_only_no_writeback() -> None:
    final_field_names = set(ARBITER_FINAL_FIELD_NAMES)
    offenders: list[str] = []
    for path in T04_SRC_ROOT.rglob("*.py"):
        if path.name == "_step4_arbiter.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name != "replace":
                continue
            written = sorted({keyword.arg for keyword in node.keywords if keyword.arg} & final_field_names)
            if written:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}:{','.join(written)}")
    assert offenders == []


def test_arbiter_writes_final_fields_once() -> None:
    arbiter_source = (T04_SRC_ROOT / "_step4_arbiter.py").read_text(encoding="utf-8")
    assert "return replace(unit, **field_kwargs)" in arbiter_source
    assert "apply_step4_arbitration_to_unit" in arbiter_source


def test_destructive_downgrade_guard_whitelist() -> None:
    case_result = _case_after_surface_binding("724067")
    unit = case_result.event_units[0]
    assert unit.positive_rcsd_present
    assert unit.required_rcsd_node
    assert unit.surface_scenario_doc()["rcsd_alignment_type"] == RCSD_ALIGNMENT_SEMANTIC_JUNCTION

    blocked_candidate = T04Step4Candidate(
        candidate_id="blocked-road-only",
        source_stage="cleanup",
        rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
        rcsdroad_ids=("road-a",),
        support_level="secondary_support",
        consistency_level="B",
        aggregate_consistency_score=0.75,
        replacement_reason="cleanup_clear",
    )
    blocked_decision = arbitrate_step4_unit(
        unit,
        _ledger_for(unit, case_result.case_spec.case_id, blocked_candidate),
        case_context=_context_for(unit, case_result.case_spec.case_id),
    )
    assert blocked_decision.downgrade_reason == "rcsd_destructive_downgrade_blocked"
    assert blocked_decision.required_rcsd_node == unit.required_rcsd_node
    assert blocked_decision.selected_rcsdroad_ids == unit.selected_rcsdroad_ids

    allowed_candidate = T04Step4Candidate(
        candidate_id="allowed-road-only",
        source_stage="cleanup",
        rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
        rcsdroad_ids=("road-a",),
        support_level="secondary_support",
        consistency_level="B",
        aggregate_consistency_score=0.75,
        replacement_reason="explicit_role_conflict",
    )
    allowed_decision = arbitrate_step4_unit(
        unit,
        _ledger_for(unit, case_result.case_spec.case_id, allowed_candidate),
        case_context=_context_for(unit, case_result.case_spec.case_id),
    )
    assert allowed_decision.downgrade_reason == "explicit_role_conflict"
    assert allowed_decision.required_rcsd_node is None
    assert allowed_decision.selected_rcsdroad_ids == ("road-a",)


def test_best_so_far_score_tiebreak() -> None:
    case_result = _case_after_surface_binding("724067")
    unit = case_result.event_units[0]
    recovery_candidate = T04Step4Candidate(
        candidate_id="recovery-candidate",
        source_stage="recovery",
        rcsd_alignment_type=RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
        rcsdroad_ids=("recovery-road",),
        rcsdnode_ids=("recovery-node",),
        required_rcsd_node="recovery-node",
        support_level="primary_support",
        consistency_level="A",
        aggregate_consistency_score=0.7,
    )
    forward_candidate = T04Step4Candidate(
        candidate_id="forward-candidate",
        source_stage="forward_bind",
        rcsd_alignment_type=RCSD_ALIGNMENT_SEMANTIC_JUNCTION,
        rcsdroad_ids=("forward-road",),
        rcsdnode_ids=("forward-node",),
        required_rcsd_node="forward-node",
        support_level="primary_support",
        consistency_level="A",
        aggregate_consistency_score=0.7,
    )

    decision = arbitrate_step4_unit(
        unit,
        _ledger_for(unit, case_result.case_spec.case_id, recovery_candidate, forward_candidate),
        case_context=_context_for(unit, case_result.case_spec.case_id),
    )

    assert decision.required_rcsd_node == "forward-node"
    selected_trace = [item for item in decision.decision_trace if item.get("selected")]
    assert selected_trace[0]["candidate"]["candidate_id"] == "forward-candidate"


def test_main_evidence_replacement_triggers_rearbitration_698389(tmp_path) -> None:
    case_result = _case_after_surface_binding("698389")
    unit = case_result.event_units[0]
    assert unit.step4_candidate_ledger is not None
    assert unit.step4_candidate_ledger.candidates

    write_case_outputs(run_root=tmp_path, case_result=case_result)
    audit = json.loads(
        (tmp_path / "cases" / case_result.case_spec.case_id / "step4_audit.json").read_text(encoding="utf-8")
    )
    shadows = audit["arbitration_decision_shadow"]
    assert len(shadows) == len(case_result.event_units)
    shadow = shadows[0]["arbitration_decision_shadow"]
    assert shadow["decision_trace"]
    selected = [item for item in shadow["decision_trace"] if item.get("selected")]
    assert selected[0]["candidate"]["source_stage"] == "divstrip"
    assert shadow["rcsd_replacement_due_to_main_evidence"] is True
    assert "aggregate_rcsd_consistency_score" in shadow
    assert shadows[0]["unit_actual"]["required_rcsd_node"] == "5396318492905216"


def test_arbiter_preserves_trimmed_swsd_rcsdroad_fallback_706347() -> None:
    pre_arbitration = _case_after_surface_binding("706347")
    pre_unit = pre_arbitration.event_units[0]
    assert pre_unit.surface_scenario_doc()["rcsd_alignment_type"] == RCSD_ALIGNMENT_ROAD_ONLY
    assert pre_unit.surface_scenario_doc()["fallback_rcsdroad_ids"] == ["5384371838321302"]

    case_result = apply_step4_arbitration_to_case_result(pre_arbitration)
    unit = case_result.event_units[0]
    scenario_doc = unit.surface_scenario_doc()

    assert unit.rcsd_alignment_type == RCSD_ALIGNMENT_ROAD_ONLY
    assert unit.fallback_rcsdroad_ids == ("5384371838321302",)
    assert unit.rcsd_alignment_result_doc()["positive_rcsdroad_ids"] == ["5384371838321302"]
    assert scenario_doc["surface_scenario_type"] == SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD
    assert scenario_doc["rcsd_alignment_type"] == RCSD_ALIGNMENT_ROAD_ONLY
    assert scenario_doc["fallback_rcsdroad_ids"] == ["5384371838321302"]


def test_scenario_reads_from_arbiter_not_derives(tmp_path) -> None:
    case_result = apply_step4_arbitration_to_case_result(_case_after_surface_binding("724067"))
    unit = case_result.event_units[0]
    assert unit.surface_scenario_published is True
    mutated_unit = replace(
        unit,
        evidence_source="none",
        selected_evidence_summary={},
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        required_rcsd_node=None,
        positive_rcsd_present=False,
        rcsd_alignment_type=RCSD_ALIGNMENT_NONE,
    )
    scenario_doc = mutated_unit.surface_scenario_doc()
    assert scenario_doc["surface_scenario_type"] == unit.surface_scenario_type
    assert scenario_doc["section_reference_source"] == unit.section_reference_source
    assert scenario_doc["rcsd_match_type"] == unit.rcsd_match_type
    rows, _artifact = write_case_outputs(run_root=tmp_path, case_result=case_result)
    review_index_path = write_review_index(tmp_path, rows)
    review_summary_path = write_review_summary(tmp_path, rows)
    audit = json.loads(
        (tmp_path / "cases" / case_result.case_spec.case_id / "step4_audit.json").read_text(encoding="utf-8")
    )
    shadow = audit["arbitration_decision_shadow"][0]
    final_fields = shadow["arbitration_decision_shadow"]["final_fields"]
    assert final_fields["surface_scenario_type"]
    assert final_fields["section_reference_source"]
    assert final_fields["rcsd_match_type"] in {"rcsd_junction", "rcsdroad_fallback", "none"}
    assert final_fields["rcsd_alignment_type"] != RCSD_ALIGNMENT_NONE
    review_index_text = review_index_path.read_text(encoding="utf-8-sig")
    assert "rcsd_decision_history_count" in review_index_text.splitlines()[0]
    assert "rcsd_replacement_due_to_main_evidence" in review_index_text.splitlines()[0]
    assert "aggregate_rcsd_consistency_score" in review_index_text.splitlines()[0]
    for row in rows:
        csv_row = row.to_csv_row()
        assert csv_row["rcsd_decision_history_count"] >= 1
        assert csv_row["aggregate_rcsd_consistency_score"]
    review_summary = json.loads(review_summary_path.read_text(encoding="utf-8"))
    assert "rcsd_decision_history_total_count" in review_summary
    assert "rcsd_replacement_due_to_main_evidence_count" in review_summary
    assert "aggregate_rcsd_consistency_score_filled_count" in review_summary
