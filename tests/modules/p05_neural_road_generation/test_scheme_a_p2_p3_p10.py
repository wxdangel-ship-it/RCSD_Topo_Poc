from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p10_adjudication import (
    DECISION_REBASELINE_NO_GAIN,
    SCHEMA_VERSION,
    HumanCarrierAdjudication,
    evaluate_frozen_p9_rows,
    run_scheme_a_p2_p3_p10_adjudication_audit,
)


_GROUPS = (
    (
        "SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080",
        "T10:609214532",
        "505101583_506183080",
        "USE_RCSD",
        True,
        False,
    ),
    (
        "SCHEME_A_P1:SEGMENT:T10:706247:706317_706319",
        "T10:706247",
        "706317_706319",
        "KEEP_SWSD",
        False,
        True,
    ),
    (
        "SCHEME_A_P1:SEGMENT:T10:706247:706346_706349",
        "T10:706247",
        "706346_706349",
        "KEEP_SWSD",
        False,
        True,
    ),
)


def test_adjudication_rejects_preferred_target_outside_allowed() -> None:
    with pytest.raises(ValueError, match="preferred_target"):
        HumanCarrierAdjudication.from_mapping(
            {
                "allowed_targets": ["KEEP_SWSD"],
                "case_key": "T10:1",
                "clue_target": False,
                "group_id": "group",
                "object_id": "object",
                "preferred_target": "USE_RCSD",
                "rationale": "test",
                "target_weight": 1.0,
            }
        )


def test_set_valued_truth_separates_validity_preference_and_clue() -> None:
    adjudication = HumanCarrierAdjudication.from_mapping(
        {
            "allowed_targets": ["KEEP_SWSD", "USE_RCSD"],
            "case_key": "T10:706247",
            "clue_target": False,
            "fallback_scope": "NONE",
            "group_id": _GROUPS[2][0],
            "object_id": _GROUPS[2][2],
            "preferred_target": "USE_RCSD",
            "rationale": "both are valid but USE_RCSD is preferred",
            "target_weight": 1.0,
        }
    )
    evaluation = _evaluation_row(seed=311, group=_GROUPS[2], arm="TREATMENT")
    decision = _decision_row(seed=311, group=_GROUPS[2], arm="TREATMENT")
    metrics, ledger = evaluate_frozen_p9_rows(
        arm="TREATMENT",
        evaluations=[evaluation],
        decisions=[decision],
        adjudications={adjudication.group_id: adjudication},
    )
    assert metrics["all_scope"]["wrong_accepted_count"] == 0
    assert metrics["pooled_source_applicable"]["valid_accuracy"] == 1.0
    assert metrics["pooled_source_applicable"]["preferred_accuracy"] == 0.0
    assert metrics["clue_metrics"]["false_positive"] == 1
    assert ledger[0]["carrier_valid"] is True
    assert ledger[0]["preference_hit"] is False
    assert ledger[0]["clue_exact"] is False


def test_p10_replays_frozen_p9_with_deterministic_result(tmp_path: Path) -> None:
    p9_root = tmp_path / "p9"
    p9_root.mkdir()
    adjudication_path = tmp_path / "human_adjudication.json"
    _write_adjudication_manifest(adjudication_path)
    _write_p9_fixture(p9_root)

    run_a = tmp_path / "p10_a"
    run_b = tmp_path / "p10_b"
    summary_a = run_scheme_a_p2_p3_p10_adjudication_audit(
        p9_run_root=p9_root,
        adjudication_manifest_path=adjudication_path,
        output_root=run_a,
    )
    summary_b = run_scheme_a_p2_p3_p10_adjudication_audit(
        p9_run_root=p9_root,
        adjudication_manifest_path=adjudication_path,
        output_root=run_b,
        reference_run_root=run_a,
    )
    assert summary_a["decision"] == DECISION_REBASELINE_NO_GAIN
    assert summary_a["carrier_safety_gate_pass"] is True
    assert summary_a["promotion_gate_pass"] is False
    assert summary_a["training_count"] == 0
    assert summary_b["reference_run_match"] is True
    assert summary_b["content_signature"] == summary_a["content_signature"]

    metrics = json.loads((run_b / "metrics.json").read_text(encoding="utf-8"))
    treatment = metrics["treatment"]
    assert treatment["pooled_source_applicable"]["valid_accuracy"] == 1.0
    assert treatment["pooled_source_applicable"]["preferred_accuracy"] == pytest.approx(
        2 / 3
    )
    assert treatment["clue_metrics"]["false_positive"] == 3
    assert metrics["comparison"]["pooled_strict_gain"] is False


def _write_adjudication_manifest(path: Path) -> None:
    write_json(
        path,
        {
            "adjudications": [
                {
                    "allowed_targets": ["USE_RCSD"],
                    "case_key": _GROUPS[0][1],
                    "clue_target": False,
                    "fallback_scope": "NONE",
                    "group_id": _GROUPS[0][0],
                    "object_id": _GROUPS[0][2],
                    "preferred_target": "USE_RCSD",
                    "rationale": "manual review",
                    "target_weight": 1.0,
                },
                {
                    "allowed_targets": ["KEEP_SWSD"],
                    "case_key": _GROUPS[1][1],
                    "clue_target": True,
                    "fallback_scope": "JUNCTION",
                    "group_id": _GROUPS[1][0],
                    "object_id": _GROUPS[1][2],
                    "preferred_target": "KEEP_SWSD",
                    "rationale": "junction fallback",
                    "rcsd_candidate_role": "CANDIDATE_ONLY_NOT_PUBLISHABLE",
                    "target_weight": 1.0,
                },
                {
                    "allowed_targets": ["KEEP_SWSD", "USE_RCSD"],
                    "case_key": _GROUPS[2][1],
                    "clue_target": False,
                    "fallback_scope": "NONE",
                    "group_id": _GROUPS[2][0],
                    "object_id": _GROUPS[2][2],
                    "preferred_target": "USE_RCSD",
                    "rationale": "both are valid",
                    "target_weight": 1.0,
                },
            ],
            "expected_seeds": [311, 313, 317],
            "schema_version": SCHEMA_VERSION,
            "truth_precedence": "OBJECT_MANUAL_OVERRIDES_CASE",
        },
    )


def _write_p9_fixture(root: Path) -> None:
    for arm in ("CONTROL", "TREATMENT"):
        evaluations = [
            _evaluation_row(seed=seed, group=group, arm=arm)
            for seed in (311, 313, 317)
            for group in _GROUPS
        ]
        decisions = [
            _decision_row(seed=seed, group=group, arm=arm)
            for seed in (311, 313, 317)
            for group in _GROUPS
        ]
        _write_jsonl(root / f"{arm.lower()}_evaluation.jsonl", evaluations)
        _write_jsonl(
            root / f"{arm.lower()}_eligible_decisions.jsonl",
            decisions,
        )
    write_json(
        root / "scheme_a_p2_p3_p9_summary.json",
        {
            "architecture_gate_pass": True,
            "audit_gate_pass": True,
            "decision": "P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO",
            "geometry_write_count": 0,
            "movement_decision_count": 0,
            "roadgraph_gate_pass": True,
        },
    )
    paths = [
        path
        for path in root.iterdir()
        if path.name != "artifact_manifest.json"
    ]
    write_json(
        root / "artifact_manifest.json",
        {
            "artifacts": [output_record(path) for path in sorted(paths)],
        },
    )


def _evaluation_row(
    *,
    seed: int,
    group: tuple[str, str, str, str, bool, bool],
    arm: str,
) -> dict[str, object]:
    group_id, case_key, _, selected_target, _, _ = group
    return {
        "arm": arm,
        "case_key": case_key,
        "clue_target": True,
        "fold": 1,
        "group_id": group_id,
        "label_eligible": True,
        "seed": seed,
        "selected_candidate_id": f"selected:{selected_target}",
        "selected_target": selected_target,
        "source_applicable": True,
        "truth_candidate_id": "selected:KEEP_SWSD",
        "truth_target": "KEEP_SWSD",
    }


def _decision_row(
    *,
    seed: int,
    group: tuple[str, str, str, str, bool, bool],
    arm: str,
) -> dict[str, object]:
    group_id, case_key, _, _, accepted, clue_predicted = group
    return {
        "accepted": accepted,
        "arm": arm,
        "case_key": case_key,
        "clue_predicted": clue_predicted,
        "group_id": group_id,
        "seed": seed,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
