from __future__ import annotations

import pytest
from dataclasses import replace

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_loader import load_case_bundle, load_case_specs
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_models import T04CaseResult, T04EventUnitResult
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.event_interpretation import build_case_result
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_final_conflict_resolver import (
    resolve_step4_final_conflicts,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_rcsd_anchored_reverse import (
    apply_rcsd_anchored_reverse_lookup,
)
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


def _case_699870() -> T04CaseResult:
    if not (REAL_ANCHOR_2_ROOT / "699870").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '699870'}")
    specs, _preflight = load_case_specs(case_root=REAL_ANCHOR_2_ROOT, case_ids=["699870"])
    case_result = build_case_result(load_case_bundle(specs[0]))
    resolved, _doc = resolve_step4_final_conflicts([case_result])
    return resolved[0]


def _case_724067() -> T04CaseResult:
    if not (REAL_ANCHOR_2_ROOT / "724067").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '724067'}")
    specs, _preflight = load_case_specs(case_root=REAL_ANCHOR_2_ROOT, case_ids=["724067"])
    case_result = build_case_result(load_case_bundle(specs[0]))
    resolved, _doc = resolve_step4_final_conflicts([case_result])
    return resolved[0]


def _target(case_result: T04CaseResult) -> T04EventUnitResult:
    return case_result.event_units[0]


def _with_unit(case_result: T04CaseResult, *units: T04EventUnitResult) -> T04CaseResult:
    return replace(case_result, event_units=list(units))


def _entry_without_rcsd(entry):
    summary = dict(entry.candidate_summary)
    summary.update(
        {
            "positive_rcsd_present": False,
            "aggregated_rcsd_unit_id": "",
            "first_hit_rcsdroad_ids": [],
        }
    )
    return replace(
        entry,
        candidate_summary=summary,
        positive_rcsd_present=False,
        aggregated_rcsd_unit_id=None,
        first_hit_rcsdroad_ids=(),
    )


def _only_node_fallback_trigger(unit: T04EventUnitResult) -> T04EventUnitResult:
    updated_entries = []
    for entry in unit.candidate_audit_entries:
        if bool(entry.candidate_summary.get("node_fallback_only")):
            updated_entries.append(entry)
        else:
            updated_entries.append(_entry_without_rcsd(entry))
    return replace(unit, candidate_audit_entries=tuple(updated_entries))


def _with_sparse_rcsd_samples(unit: T04EventUnitResult) -> T04EventUnitResult:
    first_entry = unit.candidate_audit_entries[0]
    node_id = str(first_entry.selected_rcsdnode_ids[0])
    summary = dict(first_entry.candidate_summary)
    summary.update(
        {
            "selected_rcsdroad_ids": [],
            "selected_rcsdnode_ids": [node_id],
            "first_hit_rcsdroad_ids": ["sparse_first_hit"],
        }
    )
    sparse_entry = replace(
        first_entry,
        candidate_summary=summary,
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(node_id,),
        first_hit_rcsdroad_ids=("sparse_first_hit",),
        positive_rcsd_audit={
            "aggregated_rcsd_units": [
                {
                    "unit_id": str(first_entry.aggregated_rcsd_unit_id),
                    "road_ids": [],
                    "node_ids": [node_id],
                    "required_node_id": node_id,
                }
            ]
        },
    )
    return replace(unit, candidate_audit_entries=(sparse_entry,))


def _without_axis(unit: T04EventUnitResult) -> T04EventUnitResult:
    bridge = replace(
        unit.interpretation.legacy_step5_bridge,
        event_axis_branch_id=None,
        event_axis_centerline=None,
    )
    interpretation = replace(unit.interpretation, legacy_step5_bridge=bridge)
    envelope = replace(
        unit.unit_envelope,
        preferred_axis_branch_id=None,
        branch_road_memberships={},
    )
    return replace(
        unit,
        interpretation=interpretation,
        unit_envelope=envelope,
        event_axis_branch_id=None,
    )


def _selected_other(unit: T04EventUnitResult, *, summary: dict, **overrides) -> T04EventUnitResult:
    return replace(
        unit,
        spec=replace(unit.spec, event_unit_id="other_unit"),
        selected_evidence_summary={"candidate_id": "other:selected", **summary},
        selected_candidate_summary={"candidate_id": "other:selected", **summary},
        **overrides,
    )


def test_rcsd_anchored_reverse_triggers_successfully() -> None:
    case_result = _case_699870()

    updated, doc = apply_rcsd_anchored_reverse_lookup([case_result])

    unit = _target(updated[0])
    record = doc["records"][0]
    assert doc["triggered_count"] == 1
    assert record["pre_state"] == "none"
    assert record["post_state"] != "none"
    assert unit.selected_evidence_state != "none"
    assert unit.evidence_source == "rcsd_anchored_reverse"
    assert unit.position_source == "rcsd_anchored_axis_projection"
    assert unit.event_chosen_s_m is not None
    assert record["reference_point_mode"] == "selected_divstrip_branch_tip"
    assert record["reference_point_axis_s"] == pytest.approx(33.72, abs=1e-3)
    assert unit.fact_reference_point is not None
    assert unit.required_rcsd_node_geometry is not None
    assert unit.fact_reference_point.distance(unit.required_rcsd_node_geometry) == pytest.approx(24.026, abs=1e-3)


def test_699870_prefers_merge_convergence_rcsd_node_before_reverse() -> None:
    case_result = _case_699870()

    mother = _target(case_result).candidate_audit_entries[0]

    assert mother.candidate_id == "event_unit_01:divstrip:1:01"
    assert mother.required_rcsd_node == "5396472305684570"
    assert mother.required_rcsd_node_source == "aggregated_structural_required"


def test_724067_uses_road_surface_fork_primary_evidence_before_reverse() -> None:
    case_result = _case_724067()

    _updated, doc = apply_rcsd_anchored_reverse_lookup([case_result])

    unit = _target(case_result)
    record = doc["records"][0]
    selected_summary = unit.selected_evidence_summary or {}
    assert doc["triggered_count"] == 0
    assert record["case_id"] == "724067"
    assert record["skip_reason"] == "skipped_selected_evidence_present"
    assert record["post_state"] == "found"
    assert unit.selected_evidence_state == "found"
    assert unit.evidence_source == "road_surface_fork"
    assert unit.position_source == "road_surface_fork"
    assert unit.event_chosen_s_m == 0.0
    assert selected_summary["candidate_id"] == "event_unit_01:structure:road_surface_fork:01"
    assert selected_summary["source_mode"] == "pair_local_structure_mode"
    assert selected_summary["upper_evidence_kind"] == "structure_face"
    assert selected_summary["candidate_scope"] == "road_surface_fork"
    assert selected_summary["primary_eligible"] is True
    assert selected_summary["node_fallback_only"] is False
    assert unit.required_rcsd_node is None
    assert unit.positive_rcsd_present is False
    assert unit.rcsd_selection_mode == "road_surface_fork_without_bound_target_rcsd"
    assert unit.fact_reference_point is not None
    assert unit.selected_evidence_region_geometry.buffer(1e-6).covers(unit.fact_reference_point)
    assert unit.pair_local_structure_face_geometry.buffer(1e-6).covers(unit.fact_reference_point)
    assert unit.pair_local_throat_core_geometry.buffer(1e-6).covers(unit.fact_reference_point)


def test_rcsd_anchored_reverse_skips_without_aggregated_unit() -> None:
    case_result = _case_699870()
    unit = replace(
        _target(case_result),
        candidate_audit_entries=tuple(_entry_without_rcsd(entry) for entry in _target(case_result).candidate_audit_entries),
    )

    _updated, doc = apply_rcsd_anchored_reverse_lookup([_with_unit(case_result, unit)])

    assert doc["triggered_count"] == 0
    assert doc["records"][0]["skip_reason"] == "skipped_missing_aggregated_rcsd_unit"


def test_rcsd_anchored_reverse_skips_when_evidence_already_selected() -> None:
    case_result = _case_699870()
    updated, _doc = apply_rcsd_anchored_reverse_lookup([case_result])

    _again, again_doc = apply_rcsd_anchored_reverse_lookup(updated)

    assert again_doc["triggered_count"] == 0
    assert again_doc["records"][0]["skip_reason"] == "skipped_selected_evidence_present"


def test_rcsd_anchored_reverse_allows_node_fallback_mother_candidate() -> None:
    case_result = _case_699870()
    unit = _only_node_fallback_trigger(_target(case_result))

    _updated, doc = apply_rcsd_anchored_reverse_lookup([_with_unit(case_result, unit)])

    assert doc["triggered_count"] == 1
    assert doc["records"][0]["mother_candidate_node_fallback_only"] is True


def test_rcsd_anchored_reverse_skips_when_sample_count_is_insufficient() -> None:
    case_result = _case_699870()
    unit = _with_sparse_rcsd_samples(_target(case_result))

    _updated, doc = apply_rcsd_anchored_reverse_lookup([_with_unit(case_result, unit)])

    assert doc["triggered_count"] == 0
    assert doc["records"][0]["skip_reason"] == "skipped_insufficient_rcsd_samples"


def test_rcsd_anchored_reverse_skips_when_axis_is_missing() -> None:
    case_result = _case_699870()
    unit = _without_axis(_target(case_result))

    _updated, doc = apply_rcsd_anchored_reverse_lookup([_with_unit(case_result, unit)])

    assert doc["triggered_count"] == 0
    assert doc["records"][0]["skip_reason"] == "skipped_missing_axis_branch"


def test_rcsd_anchored_reverse_skips_same_case_rcsd_claim_conflict() -> None:
    case_result = _case_699870()
    unit = _target(case_result)
    mother = unit.candidate_audit_entries[0]
    other = _selected_other(
        unit,
        summary={"point_signature": "other:point"},
        required_rcsd_node=mother.required_rcsd_node,
        aggregated_rcsd_unit_id=mother.aggregated_rcsd_unit_id,
        selected_rcsdroad_ids=mother.selected_rcsdroad_ids,
    )

    _updated, doc = apply_rcsd_anchored_reverse_lookup([_with_unit(case_result, unit, other)])

    assert doc["triggered_count"] == 0
    assert doc["records"][0]["skip_reason"] == "skipped_same_case_rcsd_claim_conflict"


def test_rcsd_anchored_reverse_skips_same_case_evidence_ownership_conflict() -> None:
    case_result = _case_699870()
    unit = _target(case_result)
    other = _selected_other(
        unit,
        summary={
            "axis_signature": "628735996",
            "axis_position_basis": "628735996",
            "axis_position_m": 0.0,
            "point_signature": "628735996:0.0",
        },
        required_rcsd_node=None,
        aggregated_rcsd_unit_id=None,
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
    )

    _updated, doc = apply_rcsd_anchored_reverse_lookup([_with_unit(case_result, unit, other)])

    assert doc["triggered_count"] == 0
    assert doc["records"][0]["skip_reason"] == "skipped_same_case_evidence_conflict"
