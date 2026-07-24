from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p11_clue_fp_audit import (
    DECISION_REVIEW_ACCEPTED,
    DECISION_REVIEW_REQUIRED,
    build_attribution_rows,
    compile_p11_manual_review_adjudications,
    extract_stable_clue_errors,
    run_scheme_a_p2_p3_p11_clue_fp_audit,
)


_GROUPS = (
    (
        "SCHEME_A_P1:SEGMENT:T10:1:100_101",
        "T10:1",
        "100_101",
        0.9,
    ),
    (
        "SCHEME_A_P1:SEGMENT:T10:2:200_201",
        "T10:2",
        "200_201",
        0.8,
    ),
    (
        "SCHEME_A_P1:SEGMENT:T10:3:300_301",
        "T10:3",
        "300_301",
        0.05,
    ),
)


def test_extract_stable_errors_applies_object_override() -> None:
    group = _GROUPS[0]
    evaluations = [
        _evaluation(seed=seed, group=group, arm="CONTROL", old_clue=True)
        for seed in (311, 313, 317)
    ]
    decisions = [
        _decision(seed=seed, group=group, arm="CONTROL")
        for seed in (311, 313, 317)
    ]
    errors = extract_stable_clue_errors(
        evaluations=evaluations,
        decisions=decisions,
        clue_overrides={group[0]: False},
    )
    assert list(errors["false_positive"]) == [group[0]]
    assert errors["false_negative"] == {}


def test_attribution_separates_manual_and_review_required(
    tmp_path: Path,
) -> None:
    manual_group = _GROUPS[0]
    review_group = _GROUPS[1]
    for group in (manual_group, review_group):
        case_id = group[1].split(":")[1]
        project = tmp_path / "T10" / case_id / f"case_{case_id}_qgis.qgs"
        project.parent.mkdir(parents=True)
        project.write_text("fixture", encoding="utf-8")
    roads = (
        tmp_path
        / "T10"
        / "2"
        / "external_inputs"
        / "prepared_swsd_roads"
        / "prepared_swsd_roads_slice.gpkg"
    )
    roads.parent.mkdir(parents=True)
    roads.write_bytes(b"fixture")

    control = {
        group[0]: [
            {
                **_evaluation(
                    seed=seed,
                    group=group,
                    arm="CONTROL",
                    old_clue=False,
                ),
                **_decision(seed=seed, group=group, arm="CONTROL"),
            }
            for seed in (311, 313, 317)
        ]
        for group in (manual_group, review_group)
    }
    treatment = {
        group_id: [
            {**row, "arm": "TREATMENT"}
            for row in rows
        ]
        for group_id, rows in control.items()
    }
    labels = {
        group[0]: _label_scope(group)
        for group in (manual_group, review_group)
    }
    sources = {
        group[0]: _applicability(group)
        for group in (manual_group, review_group)
    }
    rows = build_attribution_rows(
        control_fp=control,
        treatment_fp=treatment,
        manual_adjudications={
            manual_group[0]: {
                "rationale": "confirmed",
                "target_weight": 1.0,
            }
        },
        label_scope=labels,
        applicability=sources,
        segment_inventory={
            (manual_group[1], manual_group[2]): _segment_inventory(
                manual_group
            ),
            (review_group[1], review_group[2]): _segment_inventory(
                review_group,
                segment_type="ADVANCE_RIGHT",
            ),
        },
        poc_data_root=tmp_path,
    )
    by_group = {row["group_id"]: row for row in rows}
    assert by_group[manual_group[0]]["manual_review_required"] is False
    assert (
        by_group[manual_group[0]]["attribution"]
        == "CONFIRMED_MODEL_FALSE_POSITIVE"
    )
    assert by_group[review_group[0]]["manual_review_required"] is True
    assert by_group[review_group[0]]["manual_review_priority"] == "P0"
    assert (
        by_group[review_group[0]]["locator_method"]
        == "SWSD_ROAD_AND_ACCESS"
    )
    assert by_group[review_group[0]]["locator_expression"] == "id IN (42)"


def test_p11_formal_audit_is_deterministic(tmp_path: Path) -> None:
    p9 = tmp_path / "p9"
    p10 = tmp_path / "p10"
    p8 = tmp_path / "p8"
    dataset_p1 = tmp_path / "dataset_p1"
    scheme_a_baseline = tmp_path / "scheme_a_baseline"
    poc_data = tmp_path / "poc_data"
    for root in (p9, p10, p8, dataset_p1, scheme_a_baseline):
        root.mkdir()
    _write_p9(p9)
    _write_p10(p10)
    _write_p8(p8)
    _write_dataset_p1(dataset_p1)
    _write_scheme_a_baseline(scheme_a_baseline)
    for group in _GROUPS:
        case_id = group[1].split(":")[1]
        project = (
            poc_data / "T10" / case_id / f"case_{case_id}_qgis.qgs"
        )
        project.parent.mkdir(parents=True)
        project.write_text("fixture", encoding="utf-8")

    run_a = tmp_path / "p11_a"
    run_b = tmp_path / "p11_b"
    summary_a = run_scheme_a_p2_p3_p11_clue_fp_audit(
        p9_run_root=p9,
        p10_run_root=p10,
        p8_run_root=p8,
        dataset_p1_root=dataset_p1,
        scheme_a_baseline_root=scheme_a_baseline,
        poc_data_root=poc_data,
        output_root=run_a,
        expected_stable_fp_count=3,
        enforce_poc_scope=False,
    )
    summary_b = run_scheme_a_p2_p3_p11_clue_fp_audit(
        p9_run_root=p9,
        p10_run_root=p10,
        p8_run_root=p8,
        dataset_p1_root=dataset_p1,
        scheme_a_baseline_root=scheme_a_baseline,
        poc_data_root=poc_data,
        output_root=run_b,
        reference_run_root=run_a,
        expected_stable_fp_count=3,
        enforce_poc_scope=False,
    )
    assert summary_a["decision"] == DECISION_REVIEW_REQUIRED
    assert summary_a["stable_fp_count"] == 3
    assert summary_a["stable_fn_count"] == 0
    assert summary_a["unresolved_object_truth_count"] == 2
    assert summary_a["manual_review_count"] == 1
    assert summary_b["reference_run_match"] is True
    assert summary_b["content_signature"] == summary_a["content_signature"]

    ledger = _read_jsonl(run_b / "stable_clue_fp_ledger.jsonl")
    assert len(ledger) == 3
    with (run_b / "manual_review_queue.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as stream:
        review = list(csv.DictReader(stream))
    assert len(review) == 1
    assert review[0]["object_id"] == _GROUPS[1][2]
    assert review[0]["reviewed_clue_target"] == ""

    reviewed_path = tmp_path / "reviewed.csv"
    review[0]["access_valid"] = review[0]["access_valid"].upper()
    review[0]["current_clue_target"] = review[0][
        "current_clue_target"
    ].upper()
    review[0]["reviewed_clue_target"] = "false"
    review[0]["reviewed_allowed_targets"] = "USE_RCSD"
    review[0]["reviewed_preferred_target"] = "USE_RCSD"
    review[0]["review_reason"] = "anchors and replacement are correct"
    with reviewed_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(review[0]))
        writer.writeheader()
        writer.writerows(review)

    acceptance_a = tmp_path / "acceptance_a"
    acceptance_b = tmp_path / "acceptance_b"
    accepted_a = compile_p11_manual_review_adjudications(
        reference_p11_run_root=run_a,
        reviewed_queue_path=reviewed_path,
        prior_p10_run_root=p10,
        output_root=acceptance_a,
        expected_review_count=1,
    )
    accepted_b = compile_p11_manual_review_adjudications(
        reference_p11_run_root=run_a,
        reviewed_queue_path=reviewed_path,
        prior_p10_run_root=p10,
        output_root=acceptance_b,
        reference_run_root=acceptance_a,
        expected_review_count=1,
    )
    assert accepted_a["decision"] == DECISION_REVIEW_ACCEPTED
    assert accepted_a["accepted_review_count"] == 1
    assert accepted_a["combined_adjudication_count"] == 2
    assert accepted_a["anchor_confirmed_use_rcsd_count"] == 1
    assert accepted_b["reference_run_match"] is True

    combined = json.loads(
        (acceptance_b / "combined_human_adjudication.json").read_text(
            encoding="utf-8"
        )
    )
    new_row = next(
        row
        for row in combined["adjudications"]
        if row["object_id"] == _GROUPS[1][2]
    )
    assert new_row["allowed_targets"] == ["USE_RCSD"]
    assert new_row["target_weight"] == 1.0

    drift_path = tmp_path / "reviewed_drift.csv"
    review[0]["object_id"] = "unexpected"
    with drift_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(review[0]))
        writer.writeheader()
        writer.writerows(review)
    with pytest.raises(ValueError, match="object scope differs"):
        compile_p11_manual_review_adjudications(
            reference_p11_run_root=run_a,
            reviewed_queue_path=drift_path,
            prior_p10_run_root=p10,
            output_root=tmp_path / "acceptance_drift",
            expected_review_count=1,
        )


def _write_p9(root: Path) -> None:
    for arm in ("CONTROL", "TREATMENT"):
        evaluations = [
            _evaluation(
                seed=seed,
                group=group,
                arm=arm,
                old_clue=group == _GROUPS[0],
            )
            for seed in (311, 313, 317)
            for group in _GROUPS
        ]
        decisions = [
            _decision(seed=seed, group=group, arm=arm)
            for seed in (311, 313, 317)
            for group in _GROUPS
        ]
        _write_jsonl(
            root / f"{arm.lower()}_evaluation.jsonl",
            evaluations,
        )
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
            "roadgraph_gate_pass": True,
        },
    )
    _write_artifact_manifest(root)


def _write_p10(root: Path) -> None:
    write_json(
        root / "human_adjudication_snapshot.json",
        {
            "adjudications": [
                {
                    "allowed_targets": ["KEEP_SWSD"],
                    "case_key": _GROUPS[0][1],
                    "clue_target": False,
                    "fallback_scope": "SEGMENT",
                    "group_id": _GROUPS[0][0],
                    "object_id": _GROUPS[0][2],
                    "preferred_target": "KEEP_SWSD",
                    "rationale": "manual confirmation",
                    "rcsd_candidate_role": "UNAVAILABLE",
                    "target_weight": 1.0,
                }
            ],
            "expected_seeds": [311, 313, 317],
            "schema_version": (
                "p05-scheme-a-p2-p3-p10-human-adjudication-v1"
            ),
            "truth_precedence": "OBJECT_MANUAL_OVERRIDES_CASE",
        },
    )
    write_json(
        root / "scheme_a_p2_p3_p10_summary.json",
        {
            "audit_gate_pass": True,
            "carrier_safety_gate_pass": True,
            "decision": (
                "P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_"
                "P9_PROMOTION_NO_GAIN"
            ),
            "p9_frozen": True,
            "reference_run_match": True,
        },
    )
    _write_artifact_manifest(root)


def _write_p8(root: Path) -> None:
    _write_jsonl(
        root / "segment_applicability.jsonl",
        [_applicability(group) for group in _GROUPS],
    )
    write_json(
        root / "scheme_a_p2_p3_p8_summary.json",
        {
            "audit_gate_pass": True,
            "decision": (
                "P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_"
                "CLUE_SOURCE_BLOCKED"
            ),
            "reference_run_match": True,
        },
    )
    _write_artifact_manifest(root)


def _write_dataset_p1(root: Path) -> None:
    _write_jsonl(
        root / "segment_label_scope.jsonl",
        [_label_scope(group) for group in _GROUPS],
    )
    write_json(
        root / "dataset_p1_summary.json",
        {
            "decision": "P05_SCHEME_A_DATASET_P1_GO",
            "gates": {
                "gate0_scope": True,
                "gate1_mapping": True,
            },
            "reference_run_match": True,
        },
    )
    _write_artifact_manifest(root)


def _write_scheme_a_baseline(root: Path) -> None:
    fieldnames = (
        "case_key",
        "segment_id",
        "segment_type",
        "swsd_road_ids",
        "source_segment_access",
        "target_segment_access",
        "access_valid",
    )
    with (root / "segment_inventory.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for group in _GROUPS:
            writer.writerow(_segment_inventory(group))
    write_json(
        root / "scheme_a_summary.json",
        {
            "content_repair": False,
            "counts": {
                "legacy_connector_object_count": 0,
                "skeleton_mutation_count": 0,
            },
            "gate_pass": True,
            "label_only": True,
            "silent_fix": False,
        },
    )
    _write_artifact_manifest(root)


def _evaluation(
    *,
    seed: int,
    group: tuple[str, str, str, float],
    arm: str,
    old_clue: bool,
) -> dict[str, object]:
    group_id, case_key, _, _ = group
    return {
        "arm": arm,
        "case_key": case_key,
        "clue_target": old_clue,
        "fold": 1,
        "group_id": group_id,
        "seed": seed,
        "selected_target": "KEEP_SWSD",
        "source_applicable": False,
        "truth_target": "KEEP_SWSD",
    }


def _decision(
    *,
    seed: int,
    group: tuple[str, str, str, float],
    arm: str,
) -> dict[str, object]:
    group_id, case_key, _, probability = group
    return {
        "accepted": False,
        "anomaly_probability": probability,
        "arm": arm,
        "case_key": case_key,
        "clue_predicted": True,
        "clue_threshold": 0.01,
        "group_id": group_id,
        "reason": "reality_change_clue",
        "seed": seed,
    }


def _label_scope(
    group: tuple[str, str, str, float],
) -> dict[str, object]:
    group_id, case_key, object_id, _ = group
    return {
        "case_key": case_key,
        "group_id": group_id,
        "label_eligible": True,
        "label_weight": 0.7,
        "lineage_method": "CASE_LEVEL_TRUTH",
        "object_id": object_id,
    }


def _applicability(
    group: tuple[str, str, str, float],
) -> dict[str, object]:
    group_id, case_key, object_id, _ = group
    return {
        "case_key": case_key,
        "group_id": group_id,
        "object_id": object_id,
        "source_applicable": False,
        "source_modules": [],
    }


def _segment_inventory(
    group: tuple[str, str, str, float],
    *,
    segment_type: str = "STANDARD",
) -> dict[str, object]:
    _, case_key, object_id, _ = group
    is_advance_right = segment_type == "ADVANCE_RIGHT"
    return {
        "access_valid": is_advance_right,
        "case_key": case_key,
        "segment_id": object_id,
        "segment_type": segment_type,
        "source_segment_access": "source@node" if is_advance_right else "",
        "swsd_road_ids": json.dumps(["42"] if is_advance_right else []),
        "target_segment_access": "target@node" if is_advance_right else "",
    }


def _write_artifact_manifest(root: Path) -> None:
    write_json(
        root / "artifact_manifest.json",
        {
            "artifacts": [
                output_record(path)
                for path in sorted(root.iterdir())
                if path.name != "artifact_manifest.json"
            ]
        },
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
