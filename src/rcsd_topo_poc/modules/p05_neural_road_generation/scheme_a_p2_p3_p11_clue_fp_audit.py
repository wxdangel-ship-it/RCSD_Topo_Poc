from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)


SCHEMA_VERSION = "p05-scheme-a-p2-p3-p11-stable-clue-fp-attribution-v1"
REVIEW_ACCEPTANCE_SCHEMA_VERSION = (
    "p05-scheme-a-p2-p3-p11-manual-review-acceptance-v1"
)
P10_ADJUDICATION_SCHEMA_VERSION = (
    "p05-scheme-a-p2-p3-p10-human-adjudication-v1"
)
EXPECTED_P9_DECISION = "P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO"
EXPECTED_P10_DECISION = (
    "P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN"
)
EXPECTED_P8_DECISION = (
    "P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED"
)
EXPECTED_DATASET_P1_DECISION = "P05_SCHEME_A_DATASET_P1_GO"
DECISION_REVIEW_REQUIRED = "P05_SCHEME_A_P2_P3_P11_REVIEW_REQUIRED"
DECISION_GO_NO_REVIEW = "P05_SCHEME_A_P2_P3_P11_ATTRIBUTION_GO_NO_REVIEW"
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P11_AUDIT_NO_GO"
DECISION_REVIEW_ACCEPTED = (
    "P05_SCHEME_A_P2_P3_P11_MANUAL_REVIEW_ACCEPTED"
)
DECISION_REVIEW_ACCEPTANCE_NO_GO = (
    "P05_SCHEME_A_P2_P3_P11_MANUAL_REVIEW_ACCEPTANCE_NO_GO"
)
EXPECTED_SEEDS = (311, 313, 317)
_REVIEW_INPUT_FIELDS = (
    "reviewed_clue_target",
    "reviewed_allowed_targets",
    "reviewed_preferred_target",
    "review_reason",
)
_HUMAN_CARRIER_TARGETS = frozenset(
    {"KEEP_SWSD", "REVIEW_FALLBACK", "USE_RCSD"}
)

_REQUIRED_INPUTS = {
    "p9": (
        "control_eligible_decisions.jsonl",
        "control_evaluation.jsonl",
        "scheme_a_p2_p3_p9_summary.json",
        "treatment_eligible_decisions.jsonl",
        "treatment_evaluation.jsonl",
    ),
    "p10": (
        "human_adjudication_snapshot.json",
        "scheme_a_p2_p3_p10_summary.json",
    ),
    "p8": (
        "scheme_a_p2_p3_p8_summary.json",
        "segment_applicability.jsonl",
    ),
    "dataset_p1": (
        "dataset_p1_summary.json",
        "segment_label_scope.jsonl",
    ),
    "scheme_a_baseline": (
        "scheme_a_summary.json",
        "segment_inventory.csv",
    ),
}
_REVIEW_RISK_TAGS = frozenset(
    {
        "ADVANCE_RIGHT",
        "CARRIER_SELECTION_MISMATCH",
        "HIGH_SCORE_ALL_SEEDS",
        "T03_T04_SOURCE",
    }
)


def extract_stable_clue_errors(
    *,
    evaluations: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    clue_overrides: Mapping[str, bool],
    expected_seeds: Sequence[int] = EXPECTED_SEEDS,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    decision_by_key = {
        _seed_group_key(row): row
        for row in decisions
    }
    if len(decision_by_key) != len(decisions):
        raise ValueError("P9 decision seed/group keys are not unique")
    evaluation_by_key = {
        _seed_group_key(row): row
        for row in evaluations
    }
    if len(evaluation_by_key) != len(evaluations):
        raise ValueError("P9 evaluation seed/group keys are not unique")
    if set(decision_by_key) != set(evaluation_by_key):
        raise ValueError("P9 decision/evaluation scopes differ")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(evaluation_by_key):
        evaluation = evaluation_by_key[key]
        decision = decision_by_key[key]
        group_id = str(evaluation["group_id"])
        target = bool(
            clue_overrides.get(group_id, bool(evaluation["clue_target"]))
        )
        grouped.setdefault(group_id, []).append(
            {
                "accepted": bool(decision["accepted"]),
                "anomaly_probability": float(decision["anomaly_probability"]),
                "case_key": str(evaluation["case_key"]),
                "clue_predicted": bool(decision["clue_predicted"]),
                "clue_target": target,
                "clue_threshold": float(decision["clue_threshold"]),
                "fold": int(evaluation["fold"]),
                "group_id": group_id,
                "reason": str(decision["reason"]),
                "seed": int(evaluation["seed"]),
                "selected_target": str(evaluation["selected_target"]),
                "source_applicable": bool(evaluation["source_applicable"]),
                "truth_target": str(evaluation["truth_target"]),
            }
        )

    required_seeds = tuple(sorted(int(seed) for seed in expected_seeds))
    stable_fp: dict[str, list[dict[str, Any]]] = {}
    stable_fn: dict[str, list[dict[str, Any]]] = {}
    for group_id, rows in grouped.items():
        observed_seeds = tuple(sorted(int(row["seed"]) for row in rows))
        if observed_seeds != required_seeds:
            raise ValueError(
                f"stable clue audit seed scope differs for {group_id}"
            )
        if all(
            not bool(row["clue_target"])
            and bool(row["clue_predicted"])
            for row in rows
        ):
            stable_fp[group_id] = sorted(rows, key=lambda row: row["seed"])
        if all(
            bool(row["clue_target"])
            and not bool(row["clue_predicted"])
            for row in rows
        ):
            stable_fn[group_id] = sorted(rows, key=lambda row: row["seed"])
    return {
        "false_negative": stable_fn,
        "false_positive": stable_fp,
    }


def build_attribution_rows(
    *,
    control_fp: Mapping[str, Sequence[Mapping[str, Any]]],
    treatment_fp: Mapping[str, Sequence[Mapping[str, Any]]],
    manual_adjudications: Mapping[str, Mapping[str, Any]],
    label_scope: Mapping[str, Mapping[str, Any]],
    applicability: Mapping[str, Mapping[str, Any]],
    segment_inventory: Mapping[tuple[str, str], Mapping[str, Any]],
    poc_data_root: Path,
) -> list[dict[str, Any]]:
    if set(control_fp) != set(treatment_fp):
        raise ValueError("Control/Treatment stable FP group sets differ")
    rows: list[dict[str, Any]] = []
    for group_id in sorted(control_fp):
        control = list(control_fp[group_id])
        treatment = list(treatment_fp[group_id])
        scope = label_scope.get(group_id)
        source = applicability.get(group_id)
        if scope is None or source is None:
            raise ValueError(f"stable FP lineage is incomplete: {group_id}")
        if not bool(scope["label_eligible"]):
            raise ValueError(f"stable FP is not label eligible: {group_id}")
        _validate_arm_alignment(group_id, control, treatment)

        first = control[0]
        case_key = str(first["case_key"])
        if not case_key.startswith("T10:"):
            raise ValueError(f"stable FP is outside T10 Case scope: {group_id}")
        case_id = case_key.split(":", maxsplit=1)[1]
        object_id = group_id.rsplit(":", maxsplit=1)[-1]
        inventory = segment_inventory.get((case_key, object_id))
        if inventory is None:
            raise ValueError(
                f"stable FP Scheme-A inventory is incomplete: {group_id}"
            )
        segment_type = str(inventory["segment_type"])
        swsd_road_ids = _json_string_list(
            inventory["swsd_road_ids"],
            field_name=f"{group_id}.swsd_road_ids",
        )
        source_segment_access = str(inventory["source_segment_access"])
        target_segment_access = str(inventory["target_segment_access"])
        access_valid = _csv_bool(inventory["access_valid"])
        qgis_path = (
            poc_data_root
            / "T10"
            / case_id
            / f"case_{case_id}_qgis.qgs"
        )
        if not qgis_path.is_file():
            raise ValueError(f"QGIS project is missing: {qgis_path}")
        locator = _manual_locator(
            case_root=qgis_path.parent,
            object_id=object_id,
            segment_type=segment_type,
            swsd_road_ids=swsd_road_ids,
            source_segment_access=source_segment_access,
            target_segment_access=target_segment_access,
            access_valid=access_valid,
        )

        manual = manual_adjudications.get(group_id)
        manual_confirmed = manual is not None
        risk_tags = _risk_tags(
            segment_type=segment_type,
            control=control,
            treatment=treatment,
            source=source,
            manual_confirmed=manual_confirmed,
        )
        needs_review = (
            not manual_confirmed
            and bool(_REVIEW_RISK_TAGS.intersection(risk_tags))
        )
        priority = _review_priority(risk_tags, needs_review=needs_review)
        truth_targets = sorted(
            {
                str(row["truth_target"])
                for row in (*control, *treatment)
            }
        )
        selected_targets = sorted(
            {
                str(row["selected_target"])
                for row in (*control, *treatment)
            }
        )
        if len(truth_targets) != 1:
            raise ValueError(f"truth target drifts across arms: {group_id}")
        effective_label_weight = (
            float(manual["target_weight"])
            if manual_confirmed
            else float(scope["label_weight"])
        )
        rows.append(
            {
                "attribution": (
                    "CONFIRMED_MODEL_FALSE_POSITIVE"
                    if manual_confirmed
                    else "OBJECT_TRUTH_REVIEW_REQUIRED"
                ),
                "case_key": case_key,
                "control": _arm_rows(control),
                "effective_label_weight": effective_label_weight,
                "fold": int(first["fold"]),
                "group_id": group_id,
                "label_weight": float(scope["label_weight"]),
                "lineage_method": str(scope["lineage_method"]),
                "manual_adjudicated": manual_confirmed,
                "manual_rationale": (
                    "" if manual is None else str(manual["rationale"])
                ),
                "manual_review_priority": priority,
                "manual_review_required": needs_review,
                "object_id": object_id,
                "qgis_project_path": _display_path(qgis_path.resolve()),
                "risk_tags": risk_tags,
                "schema_version": SCHEMA_VERSION,
                "segment_type": segment_type,
                "selected_targets": selected_targets,
                "source_applicable": bool(source["source_applicable"]),
                "source_modules": sorted(
                    str(value) for value in source["source_modules"]
                ),
                "swsd_road_ids": swsd_road_ids,
                "source_segment_access": source_segment_access,
                "treatment": _arm_rows(treatment),
                "target_segment_access": target_segment_access,
                "truth_basis": (
                    "OBJECT_MANUAL_1_0"
                    if manual_confirmed
                    else "T10_CASE_LEVEL_0_7"
                ),
                "truth_target": truth_targets[0],
                **locator,
            }
        )
    return rows


def run_scheme_a_p2_p3_p11_clue_fp_audit(
    *,
    p9_run_root: Path,
    p10_run_root: Path,
    p8_run_root: Path,
    dataset_p1_root: Path,
    scheme_a_baseline_root: Path,
    poc_data_root: Path,
    output_root: Path,
    reference_run_root: Path | None = None,
    expected_stable_fp_count: int = 50,
    enforce_poc_scope: bool = True,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    if enforce_poc_scope and _display_path(poc_data_root.resolve()).lower() != (
        r"e:\testdata\poc_data"
    ):
        raise ValueError("formal P11 poc_data_root must be E:\\TestData\\POC_Data")

    roots = {
        "dataset_p1": dataset_p1_root,
        "p10": p10_run_root,
        "p8": p8_run_root,
        "p9": p9_run_root,
        "scheme_a_baseline": scheme_a_baseline_root,
    }
    input_hashes = {
        name: _verify_artifacts(root, _REQUIRED_INPUTS[name])
        for name, root in roots.items()
    }
    upstream_gate = _upstream_contract_gate(
        p9_run_root=p9_run_root,
        p10_run_root=p10_run_root,
        p8_run_root=p8_run_root,
        dataset_p1_root=dataset_p1_root,
        scheme_a_baseline_root=scheme_a_baseline_root,
    )
    p10_snapshot = _read_json(
        p10_run_root / "human_adjudication_snapshot.json"
    )
    expected_seeds = tuple(
        int(seed) for seed in p10_snapshot["expected_seeds"]
    )
    if expected_seeds != EXPECTED_SEEDS:
        raise ValueError("P10 expected seeds differ from P11 contract")
    manual_by_group = {
        str(row["group_id"]): row
        for row in p10_snapshot["adjudications"]
    }
    if len(manual_by_group) != len(p10_snapshot["adjudications"]):
        raise ValueError("P10 manual adjudication group IDs are not unique")
    overrides = {
        group_id: bool(row["clue_target"])
        for group_id, row in manual_by_group.items()
    }

    arm_errors: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    for arm in ("control", "treatment"):
        arm_errors[arm] = extract_stable_clue_errors(
            evaluations=list(
                _read_jsonl(p9_run_root / f"{arm}_evaluation.jsonl")
            ),
            decisions=list(
                _read_jsonl(
                    p9_run_root / f"{arm}_eligible_decisions.jsonl"
                )
            ),
            clue_overrides=overrides,
            expected_seeds=expected_seeds,
        )

    control_fp = arm_errors["control"]["false_positive"]
    treatment_fp = arm_errors["treatment"]["false_positive"]
    control_fn = arm_errors["control"]["false_negative"]
    treatment_fn = arm_errors["treatment"]["false_negative"]
    stable_set_gate = (
        set(control_fp) == set(treatment_fp)
        and len(control_fp) == int(expected_stable_fp_count)
        and not control_fn
        and not treatment_fn
    )

    label_scope = _unique_by_group(
        _read_jsonl(dataset_p1_root / "segment_label_scope.jsonl"),
        source_name="Dataset-P1 label scope",
    )
    applicability = _unique_by_group(
        _read_jsonl(p8_run_root / "segment_applicability.jsonl"),
        source_name="P8 applicability",
    )
    segment_inventory = _unique_segment_inventory(
        _read_csv(scheme_a_baseline_root / "segment_inventory.csv")
    )
    attribution_rows = build_attribution_rows(
        control_fp=control_fp,
        treatment_fp=treatment_fp,
        manual_adjudications=manual_by_group,
        label_scope=label_scope,
        applicability=applicability,
        segment_inventory=segment_inventory,
        poc_data_root=poc_data_root,
    )
    review_rows = [
        row for row in attribution_rows if row["manual_review_required"]
    ]
    unresolved_count = sum(
        row["attribution"] == "OBJECT_TRUTH_REVIEW_REQUIRED"
        for row in attribution_rows
    )
    manual_confirmed_count = len(attribution_rows) - unresolved_count
    lineage_gate = (
        len(attribution_rows) == len(control_fp)
        and len({row["group_id"] for row in attribution_rows})
        == len(attribution_rows)
        and all(row["qgis_project_path"] for row in attribution_rows)
        and all(row["locator_expression"] for row in attribution_rows)
    )
    arm_probability_drift = _arm_probability_drift_count(
        control_fp,
        treatment_fp,
    )
    arm_prediction_drift = _arm_prediction_drift_count(
        control_fp,
        treatment_fp,
    )
    isolation = {
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "model_weight_change_count": 0,
        "movement_decision_count": 0,
        "t01_t12_modification_count": 0,
        "threshold_tuning_count": 0,
        "training_count": 0,
    }
    audit_gate = (
        upstream_gate
        and stable_set_gate
        and lineage_gate
        and arm_probability_drift == 0
        and arm_prediction_drift == 0
    )
    decision = (
        DECISION_AUDIT_NO_GO
        if not audit_gate
        else (
            DECISION_REVIEW_REQUIRED
            if unresolved_count
            else DECISION_GO_NO_REVIEW
        )
    )

    risk_counts = Counter(
        tag
        for row in attribution_rows
        for tag in row["risk_tags"]
    )
    case_counts = Counter(row["case_key"] for row in attribution_rows)
    attribution_counts = Counter(
        row["attribution"] for row in attribution_rows
    )
    metrics = {
        "arm_prediction_drift_count": arm_prediction_drift,
        "arm_probability_drift_count": arm_probability_drift,
        "attribution_counts": dict(sorted(attribution_counts.items())),
        "case_counts": dict(sorted(case_counts.items())),
        "control_stable_fn_count": len(control_fn),
        "control_stable_fp_count": len(control_fp),
        "lineage_gate_pass": lineage_gate,
        "manual_confirmed_count": manual_confirmed_count,
        "manual_review_case_count": len(
            {row["case_key"] for row in review_rows}
        ),
        "manual_review_count": len(review_rows),
        "risk_tag_counts": dict(sorted(risk_counts.items())),
        "stable_set_gate_pass": stable_set_gate,
        "treatment_stable_fn_count": len(treatment_fn),
        "treatment_stable_fp_count": len(treatment_fp),
        "unresolved_object_truth_count": unresolved_count,
        "upstream_contract_gate_pass": upstream_gate,
    }
    content_signature = canonical_sha256(
        {
            "attribution_rows": attribution_rows,
            "decision": decision,
            "input_hashes": input_hashes,
            "isolation": isolation,
            "metrics": metrics,
        }
    )
    reference_match = None
    if reference_run_root is not None:
        reference_summary = _read_json(
            reference_run_root / "scheme_a_p2_p3_p11_summary.json"
        )
        reference_match = (
            reference_summary.get("content_signature")
            == content_signature
        )
        if not reference_match:
            audit_gate = False
            decision = DECISION_AUDIT_NO_GO

    ledger_path = output_root / "stable_clue_fp_ledger.jsonl"
    review_path = output_root / "manual_review_queue.csv"
    guide_path = output_root / "manual_review_guide.md"
    metrics_path = output_root / "metrics.json"
    summary_path = output_root / "scheme_a_p2_p3_p11_summary.json"
    report_path = output_root / "validation_report.md"
    manifest_path = output_root / "scheme_a_p2_p3_p11_manifest.json"
    artifact_manifest_path = output_root / "artifact_manifest.json"

    _write_jsonl(ledger_path, attribution_rows)
    _write_review_csv(review_path, review_rows)
    guide_path.write_text(
        _manual_review_guide(review_rows, attribution_rows),
        encoding="utf-8",
    )
    write_json(metrics_path, metrics)
    summary = {
        "audit_gate_pass": audit_gate,
        "content_signature": content_signature,
        "decision": decision,
        "expected_seeds": list(expected_seeds),
        **isolation,
        "manual_review_count": len(review_rows),
        "reference_run_match": reference_match,
        "schema_version": SCHEMA_VERSION,
        "stable_fn_count": len(treatment_fn),
        "stable_fp_count": len(treatment_fp),
        "unresolved_object_truth_count": unresolved_count,
    }
    write_json(summary_path, summary)
    report_path.write_text(
        _validation_report(summary, metrics),
        encoding="utf-8",
    )
    write_json(
        manifest_path,
        {
            "decision": decision,
            "input_hashes": input_hashes,
            "input_roots": {
                name: _display_path(path.resolve())
                for name, path in sorted(roots.items())
            },
            "outputs": {
                "ledger": output_record(ledger_path),
                "manual_review_guide": output_record(guide_path),
                "manual_review_queue": output_record(review_path),
                "metrics": output_record(metrics_path),
                "summary": output_record(summary_path),
                "validation_report": output_record(report_path),
            },
            "poc_data_root": _display_path(poc_data_root.resolve()),
            "reference_run_root": (
                None
                if reference_run_root is None
                else _display_path(reference_run_root.resolve())
            ),
            "schema_version": SCHEMA_VERSION,
        },
    )
    write_json(
        artifact_manifest_path,
        {
            "artifacts": [
                output_record(path)
                for path in sorted(output_root.iterdir())
                if path.is_file() and path.name != artifact_manifest_path.name
            ],
            "schema_version": SCHEMA_VERSION,
        },
    )
    return summary


def compile_p11_manual_review_adjudications(
    *,
    reference_p11_run_root: Path,
    reviewed_queue_path: Path,
    prior_p10_run_root: Path,
    output_root: Path,
    reference_run_root: Path | None = None,
    expected_review_count: int = 19,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    reference_hashes = _verify_artifacts(
        reference_p11_run_root,
        (
            "manual_review_queue.csv",
            "scheme_a_p2_p3_p11_summary.json",
            "stable_clue_fp_ledger.jsonl",
        ),
    )
    prior_hashes = _verify_artifacts(
        prior_p10_run_root,
        (
            "human_adjudication_snapshot.json",
            "scheme_a_p2_p3_p10_summary.json",
        ),
    )
    if not reviewed_queue_path.is_file():
        raise ValueError(f"reviewed queue is missing: {reviewed_queue_path}")

    reference_fields, reference_rows = _read_csv_table(
        reference_p11_run_root / "manual_review_queue.csv"
    )
    reviewed_fields, reviewed_rows = _read_csv_table(reviewed_queue_path)
    if reference_fields != reviewed_fields:
        raise ValueError("reviewed queue CSV fields differ from reference")
    if not set(_REVIEW_INPUT_FIELDS).issubset(reference_fields):
        raise ValueError("reviewed queue is missing adjudication fields")
    if (
        len(reference_rows) != expected_review_count
        or len(reviewed_rows) != expected_review_count
    ):
        raise ValueError("reviewed queue row count differs from contract")

    immutable_fields = tuple(
        field
        for field in reference_fields
        if field not in _REVIEW_INPUT_FIELDS
    )
    reference_by_key = _review_rows_by_key(
        reference_rows,
        source_name="reference review queue",
    )
    reviewed_by_key = _review_rows_by_key(
        reviewed_rows,
        source_name="user reviewed queue",
    )
    if set(reference_by_key) != set(reviewed_by_key):
        raise ValueError("reviewed queue object scope differs from reference")

    stable_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in _read_jsonl(
        reference_p11_run_root / "stable_clue_fp_ledger.jsonl"
    ):
        key = (str(row["case_key"]), str(row["object_id"]))
        if key in stable_by_key:
            raise ValueError("reference stable ledger object keys are not unique")
        stable_by_key[key] = row

    accepted_rows: list[dict[str, Any]] = []
    immutable_drift_count = 0
    for key in sorted(
        reviewed_by_key,
        key=lambda value: int(reviewed_by_key[value]["review_order"]),
    ):
        reference = reference_by_key[key]
        reviewed = reviewed_by_key[key]
        drift_fields = [
            field
            for field in immutable_fields
            if _immutable_csv_value(field, reference.get(field, ""))
            != _immutable_csv_value(field, reviewed.get(field, ""))
        ]
        if drift_fields:
            immutable_drift_count += 1
            raise ValueError(
                f"reviewed queue immutable fields drift for {key}: "
                + ",".join(drift_fields)
            )
        if any(not str(reviewed[field]).strip() for field in _REVIEW_INPUT_FIELDS):
            raise ValueError(f"reviewed queue row is incomplete: {key}")
        clue_target = _strict_csv_bool(reviewed["reviewed_clue_target"])
        allowed_targets = tuple(
            value.strip()
            for value in str(reviewed["reviewed_allowed_targets"]).split("|")
        )
        if (
            not allowed_targets
            or any(not value for value in allowed_targets)
            or len(set(allowed_targets)) != len(allowed_targets)
            or not set(allowed_targets).issubset(_HUMAN_CARRIER_TARGETS)
        ):
            raise ValueError(f"reviewed allowed targets are invalid: {key}")
        preferred_target = str(
            reviewed["reviewed_preferred_target"]
        ).strip()
        if preferred_target not in allowed_targets:
            raise ValueError(
                f"reviewed preferred target is outside allowed set: {key}"
            )
        if clue_target:
            raise ValueError(
                "clue=true needs an explicit Segment/Junction fallback scope"
            )
        if "REVIEW_FALLBACK" in allowed_targets:
            raise ValueError(
                "REVIEW_FALLBACK needs a separate unresolved review contract"
            )
        stable = stable_by_key.get(key)
        if stable is None:
            raise ValueError(f"reviewed object is absent from stable ledger: {key}")
        keep_only = allowed_targets == ("KEEP_SWSD",)
        use_allowed = "USE_RCSD" in allowed_targets
        accepted_rows.append(
            {
                "allowed_targets": list(allowed_targets),
                "anchor_confirmation": (
                    "BOTH_ENDPOINT_JUNCTIONS_CORRECT_AND_REPLACEMENT_CONNECTED"
                    if use_allowed
                    else "NOT_APPLICABLE"
                ),
                "case_key": key[0],
                "clue_target": clue_target,
                "fallback_scope": "SEGMENT" if keep_only else "NONE",
                "group_id": str(stable["group_id"]),
                "object_id": key[1],
                "preferred_target": preferred_target,
                "rationale": str(reviewed["review_reason"]).strip(),
                "rcsd_candidate_role": (
                    "UNAVAILABLE" if keep_only else "FINAL_ALLOWED"
                ),
                "review_order": int(reviewed["review_order"]),
                "schema_version": REVIEW_ACCEPTANCE_SCHEMA_VERSION,
                "target_weight": 1.0,
            }
        )

    prior_snapshot = _read_json(
        prior_p10_run_root / "human_adjudication_snapshot.json"
    )
    if (
        prior_snapshot.get("schema_version")
        != P10_ADJUDICATION_SCHEMA_VERSION
        or prior_snapshot.get("truth_precedence")
        != "OBJECT_MANUAL_OVERRIDES_CASE"
    ):
        raise ValueError("prior P10 adjudication snapshot contract differs")
    prior_rows = [
        dict(row) for row in prior_snapshot.get("adjudications", [])
    ]
    prior_group_ids = {str(row["group_id"]) for row in prior_rows}
    accepted_group_ids = {str(row["group_id"]) for row in accepted_rows}
    if (
        len(prior_group_ids) != len(prior_rows)
        or len(accepted_group_ids) != len(accepted_rows)
        or prior_group_ids.intersection(accepted_group_ids)
    ):
        raise ValueError("prior and P11 adjudication scopes overlap or duplicate")

    combined_rows = sorted(
        [
            *prior_rows,
            *[
                {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "anchor_confirmation",
                        "review_order",
                        "schema_version",
                    }
                }
                for row in accepted_rows
            ],
        ],
        key=lambda row: str(row["group_id"]),
    )
    combined_manifest = {
        "adjudications": combined_rows,
        "business_assumptions": {
            "use_rcsd_requires_both_endpoint_junctions_correctly_anchored": True,
            "use_rcsd_requires_correct_replacement_connectivity": True,
        },
        "expected_seeds": list(EXPECTED_SEEDS),
        "reviewed_queue_sha256": sha256_file(reviewed_queue_path),
        "schema_version": P10_ADJUDICATION_SCHEMA_VERSION,
        "truth_precedence": "OBJECT_MANUAL_OVERRIDES_CASE",
        "user_confirmation_date": "2026-07-24",
    }
    target_counts = Counter(
        row["preferred_target"] for row in accepted_rows
    )
    clue_counts = Counter(
        str(row["clue_target"]).lower() for row in accepted_rows
    )
    metrics = {
        "accepted_review_count": len(accepted_rows),
        "anchor_confirmed_use_rcsd_count": sum(
            row["anchor_confirmation"]
            == "BOTH_ENDPOINT_JUNCTIONS_CORRECT_AND_REPLACEMENT_CONNECTED"
            for row in accepted_rows
        ),
        "clue_target_counts": dict(sorted(clue_counts.items())),
        "combined_adjudication_count": len(combined_rows),
        "immutable_drift_count": immutable_drift_count,
        "preferred_target_counts": dict(sorted(target_counts.items())),
        "prior_adjudication_count": len(prior_rows),
    }
    input_hashes = {
        "prior_p10": prior_hashes,
        "reference_p11": reference_hashes,
        "reviewed_queue": sha256_file(reviewed_queue_path),
    }
    content_signature = canonical_sha256(
        {
            "accepted_rows": accepted_rows,
            "combined_manifest": combined_manifest,
            "input_hashes": input_hashes,
            "metrics": metrics,
        }
    )
    reference_match = None
    decision = DECISION_REVIEW_ACCEPTED
    if reference_run_root is not None:
        reference_summary = _read_json(
            reference_run_root / "p11_review_acceptance_summary.json"
        )
        reference_match = (
            reference_summary.get("content_signature")
            == content_signature
        )
        if not reference_match:
            decision = DECISION_REVIEW_ACCEPTANCE_NO_GO

    accepted_path = output_root / "accepted_manual_review.jsonl"
    combined_path = output_root / "combined_human_adjudication.json"
    metrics_path = output_root / "metrics.json"
    summary_path = output_root / "p11_review_acceptance_summary.json"
    manifest_path = output_root / "p11_review_acceptance_manifest.json"
    artifact_manifest_path = output_root / "artifact_manifest.json"
    _write_jsonl(accepted_path, accepted_rows)
    write_json(combined_path, combined_manifest)
    write_json(metrics_path, metrics)
    summary = {
        "audit_gate_pass": decision == DECISION_REVIEW_ACCEPTED,
        "content_signature": content_signature,
        "decision": decision,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "model_weight_change_count": 0,
        "reference_run_match": reference_match,
        "schema_version": REVIEW_ACCEPTANCE_SCHEMA_VERSION,
        "threshold_tuning_count": 0,
        "training_count": 0,
        **metrics,
    }
    write_json(summary_path, summary)
    write_json(
        manifest_path,
        {
            "decision": decision,
            "input_hashes": input_hashes,
            "input_paths": {
                "prior_p10_run_root": _display_path(
                    prior_p10_run_root.resolve()
                ),
                "reference_p11_run_root": _display_path(
                    reference_p11_run_root.resolve()
                ),
                "reviewed_queue_path": _display_path(
                    reviewed_queue_path.resolve()
                ),
            },
            "outputs": {
                "accepted_manual_review": output_record(accepted_path),
                "combined_human_adjudication": output_record(combined_path),
                "metrics": output_record(metrics_path),
                "summary": output_record(summary_path),
            },
            "reference_run_root": (
                None
                if reference_run_root is None
                else _display_path(reference_run_root.resolve())
            ),
            "schema_version": REVIEW_ACCEPTANCE_SCHEMA_VERSION,
        },
    )
    write_json(
        artifact_manifest_path,
        {
            "artifacts": [
                output_record(path)
                for path in sorted(output_root.iterdir())
                if path.is_file() and path.name != artifact_manifest_path.name
            ],
            "schema_version": REVIEW_ACCEPTANCE_SCHEMA_VERSION,
        },
    )
    return summary


def _risk_tags(
    *,
    segment_type: str,
    control: Sequence[Mapping[str, Any]],
    treatment: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    manual_confirmed: bool,
) -> list[str]:
    combined = [*control, *treatment]
    tags: list[str] = []
    if segment_type == "ADVANCE_RIGHT":
        tags.append("ADVANCE_RIGHT")
    if any(
        row["selected_target"] != row["truth_target"]
        for row in combined
    ):
        tags.append("CARRIER_SELECTION_MISMATCH")
    if all(float(row["anomaly_probability"]) >= 0.5 for row in combined):
        tags.append("HIGH_SCORE_ALL_SEEDS")
    if all(float(row["anomaly_probability"]) < 0.1 for row in combined):
        tags.append("LOW_SCORE_THRESHOLD_ONLY")
    if manual_confirmed:
        tags.append("MANUAL_CONFIRMED")
    if bool(source["source_applicable"]):
        tags.append("T03_T04_SOURCE")
    return sorted(tags)


def _review_priority(risk_tags: Sequence[str], *, needs_review: bool) -> str:
    if not needs_review:
        return "DEFERRED"
    tags = set(risk_tags)
    if tags.intersection(
        {"CARRIER_SELECTION_MISMATCH", "HIGH_SCORE_ALL_SEEDS"}
    ):
        return "P0"
    return "P1"


def _arm_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "accepted": bool(row["accepted"]),
            "anomaly_probability": float(row["anomaly_probability"]),
            "clue_predicted": bool(row["clue_predicted"]),
            "clue_threshold": float(row["clue_threshold"]),
            "reason": str(row["reason"]),
            "seed": int(row["seed"]),
            "selected_target": str(row["selected_target"]),
        }
        for row in sorted(rows, key=lambda row: int(row["seed"]))
    ]


def _validate_arm_alignment(
    group_id: str,
    control: Sequence[Mapping[str, Any]],
    treatment: Sequence[Mapping[str, Any]],
) -> None:
    control_by_seed = {int(row["seed"]): row for row in control}
    treatment_by_seed = {int(row["seed"]): row for row in treatment}
    if set(control_by_seed) != set(treatment_by_seed):
        raise ValueError(f"arm seed scope differs for {group_id}")
    for seed in control_by_seed:
        left = control_by_seed[seed]
        right = treatment_by_seed[seed]
        for key in (
            "case_key",
            "clue_predicted",
            "clue_target",
            "fold",
            "group_id",
            "truth_target",
        ):
            if left[key] != right[key]:
                raise ValueError(
                    f"arm field {key} differs for {group_id} seed {seed}"
                )


def _arm_probability_drift_count(
    control: Mapping[str, Sequence[Mapping[str, Any]]],
    treatment: Mapping[str, Sequence[Mapping[str, Any]]],
) -> int:
    count = 0
    for group_id in sorted(set(control).intersection(treatment)):
        treatment_by_seed = {
            int(row["seed"]): row for row in treatment[group_id]
        }
        for row in control[group_id]:
            other = treatment_by_seed[int(row["seed"])]
            if (
                abs(
                    float(row["anomaly_probability"])
                    - float(other["anomaly_probability"])
                )
                > 1e-12
                or abs(
                    float(row["clue_threshold"])
                    - float(other["clue_threshold"])
                )
                > 1e-12
            ):
                count += 1
    return count


def _arm_prediction_drift_count(
    control: Mapping[str, Sequence[Mapping[str, Any]]],
    treatment: Mapping[str, Sequence[Mapping[str, Any]]],
) -> int:
    count = 0
    for group_id in sorted(set(control).intersection(treatment)):
        treatment_by_seed = {
            int(row["seed"]): row for row in treatment[group_id]
        }
        for row in control[group_id]:
            other = treatment_by_seed[int(row["seed"])]
            if bool(row["clue_predicted"]) != bool(
                other["clue_predicted"]
            ):
                count += 1
    return count


def _upstream_contract_gate(
    *,
    p9_run_root: Path,
    p10_run_root: Path,
    p8_run_root: Path,
    dataset_p1_root: Path,
    scheme_a_baseline_root: Path,
) -> bool:
    p9 = _read_json(p9_run_root / "scheme_a_p2_p3_p9_summary.json")
    p10 = _read_json(p10_run_root / "scheme_a_p2_p3_p10_summary.json")
    p8 = _read_json(p8_run_root / "scheme_a_p2_p3_p8_summary.json")
    dataset_p1 = _read_json(dataset_p1_root / "dataset_p1_summary.json")
    scheme_a = _read_json(
        scheme_a_baseline_root / "scheme_a_summary.json"
    )
    dataset_gates = dataset_p1.get("gates", {})
    scheme_counts = scheme_a.get("counts", {})
    return bool(
        p9.get("decision") == EXPECTED_P9_DECISION
        and p9.get("audit_gate_pass")
        and p9.get("architecture_gate_pass")
        and p9.get("roadgraph_gate_pass")
        and p10.get("decision") == EXPECTED_P10_DECISION
        and p10.get("audit_gate_pass")
        and p10.get("carrier_safety_gate_pass")
        and p10.get("reference_run_match")
        and p10.get("p9_frozen")
        and p8.get("decision") == EXPECTED_P8_DECISION
        and p8.get("audit_gate_pass")
        and p8.get("reference_run_match")
        and dataset_p1.get("decision") == EXPECTED_DATASET_P1_DECISION
        and dataset_p1.get("reference_run_match")
        and dataset_gates
        and all(bool(value) for value in dataset_gates.values())
        and scheme_a.get("gate_pass")
        and scheme_a.get("label_only")
        and not scheme_a.get("content_repair")
        and not scheme_a.get("silent_fix")
        and scheme_counts.get("skeleton_mutation_count") == 0
        and scheme_counts.get("legacy_connector_object_count") == 0
    )


def _verify_artifacts(
    root: Path,
    required_names: Sequence[str],
) -> dict[str, str]:
    artifact_manifest_path = root / "artifact_manifest.json"
    artifact_manifest = _read_json(artifact_manifest_path)
    raw_records: list[Mapping[str, Any]]
    if isinstance(artifact_manifest.get("artifacts"), list):
        raw_records = artifact_manifest["artifacts"]
    else:
        raw_records = [
            value
            for value in artifact_manifest.values()
            if isinstance(value, Mapping)
            and {"path", "sha256", "size_bytes"}.issubset(value)
        ]
    records = {
        str(row["path"]).replace("\\", "/").rsplit("/", maxsplit=1)[-1]: row
        for row in raw_records
    }
    verified = {
        "artifact_manifest.json": sha256_file(artifact_manifest_path)
    }
    for name in required_names:
        path = root / name
        record = records.get(name)
        if record is None or not path.is_file():
            raise ValueError(f"required artifact is missing: {path}")
        digest = sha256_file(path)
        if digest != record.get("sha256"):
            raise ValueError(f"artifact hash differs: {path}")
        if path.stat().st_size != int(record.get("size_bytes", -1)):
            raise ValueError(f"artifact size differs: {path}")
        verified[name] = digest
    return verified


def _unique_by_group(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_name: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        group_id = str(row["group_id"])
        if group_id in result:
            raise ValueError(f"{source_name} group IDs are not unique")
        result[group_id] = row
    return result


def _unique_segment_inventory(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["segment_id"]))
        if key in result:
            raise ValueError("Scheme-A segment inventory keys are not unique")
        result[key] = row
    return result


def _manual_locator(
    *,
    case_root: Path,
    object_id: str,
    segment_type: str,
    swsd_road_ids: Sequence[str],
    source_segment_access: str,
    target_segment_access: str,
    access_valid: bool,
) -> dict[str, Any]:
    if segment_type == "ADVANCE_RIGHT":
        roads_path = (
            case_root
            / "external_inputs"
            / "prepared_swsd_roads"
            / "prepared_swsd_roads_slice.gpkg"
        )
        if not roads_path.is_file():
            raise ValueError(
                f"ADVANCE_RIGHT SWSD locator is missing: {roads_path}"
            )
        if (
            not swsd_road_ids
            or not all(value.isdigit() for value in swsd_road_ids)
            or not source_segment_access
            or not target_segment_access
            or not access_valid
        ):
            raise ValueError(
                f"ADVANCE_RIGHT locator evidence is incomplete: {object_id}"
            )
        return {
            "access_valid": True,
            "locator_expression": (
                "id IN (" + ",".join(swsd_road_ids) + ")"
            ),
            "locator_layer": "prepared_swsd_roads",
            "locator_method": "SWSD_ROAD_AND_ACCESS",
            "locator_source_path": _display_path(roads_path.resolve()),
        }
    return {
        "access_valid": access_valid,
        "locator_expression": f"id = '{object_id}'",
        "locator_layer": "segment",
        "locator_method": "T01_SEGMENT_ID",
        "locator_source_path": "",
    }


def _write_review_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    fieldnames = (
        "review_order",
        "priority",
        "case_key",
        "object_id",
        "segment_type",
        "qgis_project_path",
        "locator_method",
        "locator_layer",
        "locator_expression",
        "swsd_road_ids",
        "source_segment_access",
        "target_segment_access",
        "access_valid",
        "current_clue_target",
        "truth_basis",
        "effective_label_weight",
        "truth_target",
        "selected_targets",
        "risk_tags",
        "source_modules",
        "control_probabilities",
        "treatment_probabilities",
        "reviewed_clue_target",
        "reviewed_allowed_targets",
        "reviewed_preferred_target",
        "review_reason",
    )
    ordered = sorted(
        rows,
        key=lambda row: (
            row["manual_review_priority"],
            row["case_key"],
            row["object_id"],
        ),
    )
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(ordered, start=1):
            writer.writerow(
                {
                    "review_order": index,
                    "priority": row["manual_review_priority"],
                    "case_key": row["case_key"],
                    "object_id": row["object_id"],
                    "segment_type": row["segment_type"],
                    "qgis_project_path": row["qgis_project_path"],
                    "locator_method": row["locator_method"],
                    "locator_layer": row["locator_layer"],
                    "locator_expression": row["locator_expression"],
                    "swsd_road_ids": "|".join(row["swsd_road_ids"]),
                    "source_segment_access": row[
                        "source_segment_access"
                    ],
                    "target_segment_access": row[
                        "target_segment_access"
                    ],
                    "access_valid": str(row["access_valid"]).lower(),
                    "current_clue_target": "false",
                    "truth_basis": row["truth_basis"],
                    "effective_label_weight": row[
                        "effective_label_weight"
                    ],
                    "truth_target": row["truth_target"],
                    "selected_targets": "|".join(row["selected_targets"]),
                    "risk_tags": "|".join(row["risk_tags"]),
                    "source_modules": "|".join(row["source_modules"]),
                    "control_probabilities": "|".join(
                        f"{item['seed']}:{item['anomaly_probability']:.9f}"
                        for item in row["control"]
                    ),
                    "treatment_probabilities": "|".join(
                        f"{item['seed']}:{item['anomaly_probability']:.9f}"
                        for item in row["treatment"]
                    ),
                    "reviewed_clue_target": "",
                    "reviewed_allowed_targets": "",
                    "reviewed_preferred_target": "",
                    "review_reason": "",
                }
            )


def _manual_review_guide(
    review_rows: Sequence[Mapping[str, Any]],
    all_rows: Sequence[Mapping[str, Any]],
) -> str:
    case_counts = Counter(row["case_key"] for row in review_rows)
    lines = [
        "# P05 P11 人工目视审计说明",
        "",
        f"- 完整稳定FP对象：`{len(all_rows)}`",
        f"- 首轮需要人工目视对象：`{len(review_rows)}`",
        "- 已有对象级1.0裁决的对象不重复审核。",
        "",
        "## 操作",
        "",
        "1. 按CSV的`qgis_project_path`打开Case QGIS工程；",
        "2. 普通Segment：在`segment`图层直接粘贴"
        "`locator_expression`定位；",
        "3. `ADVANCE_RIGHT`：打开`prepared_swsd_roads`图层，粘贴"
        "`locator_expression`定位，并用source/target access核对两端；",
        "4. 对照SWSD、RCSD、F-RCSD Road/Node与路口范围；",
        "5. 填写Clue、allowed carrier、preferred carrier和简短原因。",
        "",
        "RCSD数据缺失本身不构成RealityChangeClue。只有事实道路结构与冻结认知",
        "冲突时才填写`reviewed_clue_target=true`。",
        "",
        "## Case分布",
        "",
    ]
    for case_key, count in sorted(case_counts.items()):
        lines.append(f"- `{case_key}`：`{count}`")
    lines.extend(
        [
            "",
            "## 返回字段",
            "",
            "- `reviewed_clue_target`：`true`或`false`；",
            "- `reviewed_allowed_targets`：以`|`分隔；",
            "- `reviewed_preferred_target`：单个carrier目标；",
            "- `review_reason`：说明道路结构冲突或无冲突的可见依据。",
            "",
        ]
    )
    return "\n".join(lines)


def _validation_report(
    summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> str:
    return (
        "# P05 Scheme-A P2-P3-P11 Validation\n\n"
        f"- decision: `{summary['decision']}`\n"
        f"- stable FP/FN: `{summary['stable_fp_count']}` / "
        f"`{summary['stable_fn_count']}`\n"
        f"- unresolved object truth: "
        f"`{summary['unresolved_object_truth_count']}`\n"
        f"- manual review queue: `{summary['manual_review_count']}`\n"
        f"- arm probability drift: "
        f"`{metrics['arm_probability_drift_count']}`\n"
        f"- training / threshold tuning: `{summary['training_count']}` / "
        f"`{summary['threshold_tuning_count']}`\n"
        f"- reference run match: `{summary['reference_run_match']}`\n"
    )


def _display_path(path: Path) -> str:
    value = str(path)
    normalized = value.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 7:
        drive = normalized[5].upper()
        rest = normalized[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return value.replace("/", "\\")


def _seed_group_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["group_id"])


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _read_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def _read_csv_table(
    path: Path,
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"CSV header is missing: {path}")
        return tuple(reader.fieldnames), list(reader)


def _review_rows_by_key(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_name: str,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["object_id"]))
        if key in result:
            raise ValueError(f"{source_name} object keys are not unique")
        result[key] = row
    return result


def _json_string_list(value: Any, *, field_name: str) -> list[str]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be a JSON list")
    return [str(item) for item in parsed]


def _csv_bool(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false", ""}:
        return False
    raise ValueError(f"invalid CSV boolean: {value}")


def _strict_csv_bool(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"reviewed clue target must be true or false: {value}")


def _immutable_csv_value(field: str, value: Any) -> str:
    normalized = str(value)
    if field in {"access_valid", "current_clue_target"}:
        return str(_strict_csv_bool(normalized)).lower()
    return normalized


def _write_jsonl(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_GO_NO_REVIEW",
    "DECISION_REVIEW_ACCEPTED",
    "DECISION_REVIEW_ACCEPTANCE_NO_GO",
    "DECISION_REVIEW_REQUIRED",
    "REVIEW_ACCEPTANCE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "build_attribution_rows",
    "compile_p11_manual_review_adjudications",
    "extract_stable_clue_errors",
    "run_scheme_a_p2_p3_p11_clue_fp_audit",
]
