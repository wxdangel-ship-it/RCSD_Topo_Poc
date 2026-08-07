from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    _input_record,
    _write_json,
    _write_jsonl,
    ordinary_road_set_metrics,
    read_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def compose_ordinary_anchor_release_gate(
    *,
    ordinary_predictions_path: Path,
    ordinary_feature_path: Path,
    anchor_gated_predictions_path: Path,
    output_root: Path,
) -> Path:
    """Require every neural required-anchor gate before Segment release."""
    ordinary_path = normalize_runtime_path(
        ordinary_predictions_path
    ).resolve(strict=True)
    feature_path = normalize_runtime_path(ordinary_feature_path).resolve(
        strict=True
    )
    anchor_path = normalize_runtime_path(
        anchor_gated_predictions_path
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    anchor_gate = _read_anchor_gate(anchor_path)
    required = _read_required_anchors(feature_path)
    ordinary_rows = list(_jsonl_rows(ordinary_path))
    result = []
    missing_anchor_refs = []
    fold_mismatches = []
    for row in ordinary_rows:
        key = (str(row["case_key"]), str(row["segment_id"]))
        anchor_ids = required.get(key)
        if anchor_ids is None:
            raise ValueError(
                f"ordinary required anchors are missing: {key}"
            )
        anchor_rows = []
        for anchor_id in anchor_ids:
            anchor_key = (key[0], anchor_id)
            anchor = anchor_gate.get(anchor_key)
            if anchor is None:
                missing_anchor_refs.append((*key, anchor_id))
                continue
            anchor_rows.append(anchor)
            if int(anchor["outer_fold"]) != int(row["fold"]):
                fold_mismatches.append(
                    (
                        *key,
                        anchor_id,
                        int(row["fold"]),
                        int(anchor["outer_fold"]),
                    )
                )
        anchor_gate_passed = (
            bool(anchor_ids)
            and len(anchor_rows) == len(anchor_ids)
            and all(
                bool(value["safety_accepted"]) for value in anchor_rows
            )
        )
        predicted_decision = str(row["predicted_decision"])
        inference_no_evidence_proof_passed = bool(
            row.get("inference_no_evidence_proof_passed")
        )
        no_evidence_keep_exception = bool(
            predicted_decision == "KEEP_SWSD"
            and inference_no_evidence_proof_passed
        )
        anchor_prerequisite_passed = bool(
            anchor_gate_passed or no_evidence_keep_exception
        )
        business_output_complete = _business_output_map(row) is not None
        combined = dict(row)
        combined["ordinary_decoder_automatic"] = bool(
            row.get("automatic")
        )
        combined["required_anchor_ids"] = list(anchor_ids)
        combined["required_anchor_gate_passed_count"] = sum(
            bool(value["safety_accepted"]) for value in anchor_rows
        )
        combined["required_anchor_gate_count"] = len(anchor_ids)
        combined["required_anchor_gate_passed"] = anchor_gate_passed
        combined["inference_no_evidence_proof_passed"] = (
            inference_no_evidence_proof_passed
        )
        combined["no_evidence_keep_exception"] = no_evidence_keep_exception
        combined["anchor_prerequisite_passed"] = (
            anchor_prerequisite_passed
        )
        combined["business_output_complete"] = business_output_complete
        combined["automatic"] = bool(
            row.get("automatic")
            and anchor_prerequisite_passed
            and business_output_complete
        )
        combined["unsafe_automatic"] = bool(
            combined["automatic"]
            and not _aggregate_complete_business_exact(row)
        )
        combined["effective_decision"] = (
            row["predicted_decision"]
            if combined["automatic"]
            else "ABSTAIN"
        )
        result.append(combined)
    if missing_anchor_refs:
        raise ValueError(
            "ordinary release gate has missing anchor refs: "
            f"{missing_anchor_refs[:3]}"
        )
    if fold_mismatches:
        raise ValueError(
            "ordinary and anchor gate folds differ: "
            f"{fold_mismatches[:3]}"
        )
    result.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "gated_oof_predictions.jsonl"
    _write_jsonl(prediction_path, result)
    metrics = ordinary_road_set_metrics(result)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_SET_EXPANSION_REQUIRED_ANCHOR_RELEASE_GATE",
        "prediction_count": len(result),
        "metrics": metrics,
        "ordinary_decoder_automatic_count": sum(
            bool(row["ordinary_decoder_automatic"]) for row in result
        ),
        "required_anchor_reference_count": sum(
            int(row["required_anchor_gate_count"]) for row in result
        ),
        "missing_anchor_reference_count": 0,
        "fold_mismatch_count": 0,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "release_contract": (
            "A Segment is automatic only when its ordinary decoder accepts "
            "and every required semantic anchor is independently accepted "
            "by the strict OOF neural evidence gate. The only exception is "
            "a positive KEEP_SWSD carrying an explicit inference-time "
            "NO_RCSD_EVIDENCE proof. A complete per-Road ownership/role "
            "output is mandatory. The gate never expands beyond that "
            "Segment."
        ),
        "release_gate": (
            "PASS"
            if int(metrics["unsafe_automatic_count"]) == 0
            else "NO_GO"
        ),
        "gate_pass": (
            len(result) == len(ordinary_rows)
            and int(metrics["unsafe_automatic_count"]) == 0
        ),
        "inputs": {
            "ordinary_predictions": _input_record(ordinary_path),
            "ordinary_features": _input_record(feature_path),
            "anchor_gated_predictions": _input_record(anchor_path),
        },
        "predictions": _input_record(prediction_path),
    }
    _write_json(root / "summary.json", summary)
    return root


def compose_ordinary_ensemble_release_gate(
    *,
    primary_anchor_gated_predictions_path: Path,
    confirmation_predictions_path: Path,
    output_root: Path,
    ordinary_member_store_root: Path | None = None,
) -> Path:
    """Require two complete carrier seeds after the neural anchor gate."""
    primary_path = normalize_runtime_path(
        primary_anchor_gated_predictions_path
    ).resolve(strict=True)
    confirmation_path = normalize_runtime_path(
        confirmation_predictions_path
    ).resolve(strict=True)
    member_store = (
        normalize_runtime_path(ordinary_member_store_root).resolve(
            strict=True
        )
        if ordinary_member_store_root is not None
        else None
    )
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    primary_rows = list(_jsonl_rows(primary_path))
    confirmation = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _jsonl_rows(confirmation_path)
    }
    business_truth = (
        _read_selected_business_truth(member_store)
        if member_store is not None
        else {}
    )
    result = []
    missing = []
    fold_mismatches = []
    for primary in primary_rows:
        key = (
            str(primary["case_key"]),
            str(primary["segment_id"]),
        )
        other = confirmation.get(key)
        if other is None:
            missing.append(key)
            continue
        if int(primary["fold"]) != int(other["fold"]):
            fold_mismatches.append(
                (*key, int(primary["fold"]), int(other["fold"]))
            )
        same_decision = (
            str(primary["predicted_decision"])
            == str(other["predicted_decision"])
        )
        same_road_set = set(primary["selected_road_ids"]) == set(
            other["selected_road_ids"]
        )
        primary_business_output = _business_output_map(primary)
        confirmation_business_output = _business_output_map(other)
        business_outputs_complete = bool(
            primary_business_output is not None
            and confirmation_business_output is not None
        )
        same_business_output = bool(
            business_outputs_complete
            and primary_business_output == confirmation_business_output
        )
        ensemble_accepted = bool(
            primary["automatic"]
            and other["automatic"]
            and same_decision
            and same_road_set
            and same_business_output
        )
        predicted_decision = str(primary["predicted_decision"])
        selected_business_evaluable, selected_business_exact = (
            _selected_business_truth_result(
                primary_business_output,
                business_truth.get(key),
            )
            if member_store is not None
            else (
                True,
                bool(
                    _aggregate_complete_business_exact(primary)
                    and _aggregate_complete_business_exact(other)
                ),
            )
        )
        row = dict(primary)
        row["confirmation_decoder_automatic"] = bool(other["automatic"])
        row["ensemble_decision_consistent"] = same_decision
        row["ensemble_road_set_consistent"] = same_road_set
        row["ensemble_business_outputs_complete"] = (
            business_outputs_complete
        )
        row["ensemble_business_output_consistent"] = same_business_output
        row["ensemble_accepted"] = ensemble_accepted
        row["selected_business_truth_evaluable"] = (
            selected_business_evaluable
        )
        row["selected_business_truth_exact"] = selected_business_exact
        row["automatic"] = ensemble_accepted
        row["unsafe_automatic"] = bool(
            row["automatic"]
            and (
                not primary["complete_exact"]
                or not other["complete_exact"]
                or (
                    selected_business_evaluable
                    and not selected_business_exact
                )
            )
        )
        row["unverifiable_automatic"] = bool(
            row["automatic"] and not selected_business_evaluable
        )
        row["effective_decision"] = (
            predicted_decision if row["automatic"] else "ABSTAIN"
        )
        result.append(row)
    if missing:
        raise ValueError(
            f"ordinary ensemble prediction is missing: {missing[:3]}"
        )
    if fold_mismatches:
        raise ValueError(
            f"ordinary ensemble folds differ: {fold_mismatches[:3]}"
        )
    if len(confirmation) != len(primary_rows):
        raise ValueError("ordinary ensemble prediction counts differ")
    result.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "ensemble_gated_oof_predictions.jsonl"
    _write_jsonl(prediction_path, result)
    metrics = ordinary_road_set_metrics(result)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_SET_EXPANSION_TWO_SEED_RELEASE_GATE",
        "prediction_count": len(result),
        "metrics": metrics,
        "automatic_KEEP_SWSD_count": sum(
            bool(row["automatic"])
            and row["predicted_decision"] == "KEEP_SWSD"
            for row in result
        ),
        "automatic_USE_RCSD_count": sum(
            bool(row["automatic"])
            and row["predicted_decision"] == "USE_RCSD"
            for row in result
        ),
        "ensemble_road_set_disagreement_count": sum(
            not bool(row["ensemble_road_set_consistent"]) for row in result
        ),
        "ensemble_business_output_disagreement_count": sum(
            not bool(row["ensemble_business_output_consistent"])
            for row in result
        ),
        "unverifiable_automatic_count": sum(
            bool(row["unverifiable_automatic"]) for row in result
        ),
        "missing_prediction_count": 0,
        "fold_mismatch_count": 0,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "release_contract": (
            "Both strict OOF expansion seeds must independently accept the "
            "same business decision, complete Road set and complete per-Road "
            "ownership/business-role output. The primary prediction must "
            "already pass the independent neural anchor prerequisite; KEEP "
            "without anchors is allowed only through an explicit "
            "inference-time NO_RCSD_EVIDENCE proof. Truth is used only for "
            "unsafe/unverifiable evaluation, never release selection."
        ),
        "release_gate": (
            "PASS"
            if int(metrics["unsafe_automatic_count"]) == 0
            and not any(
                bool(row["unverifiable_automatic"]) for row in result
            )
            else "NO_GO"
        ),
        "gate_pass": (
            len(result) == len(primary_rows)
            and int(metrics["unsafe_automatic_count"]) == 0
            and not any(
                bool(row["unverifiable_automatic"]) for row in result
            )
        ),
        "inputs": {
            "primary_anchor_gated_predictions": _input_record(primary_path),
            "confirmation_predictions": _input_record(confirmation_path),
            **(
                {
                    "ordinary_member_store_summary": _input_record(
                        member_store / "summary.json"
                    )
                }
                if member_store is not None
                else {}
            ),
        },
        "predictions": _input_record(prediction_path),
    }
    _write_json(root / "summary.json", summary)
    return root


def _business_output_map(
    row: Mapping[str, Any],
) -> dict[str, tuple[str, str]] | None:
    selected = {str(value) for value in row.get("selected_road_ids") or ()}
    records = row.get("selected_road_business_roles") or ()
    result: dict[str, tuple[str, str]] = {}
    for record in records:
        road_id = str(record.get("road_id") or "")
        ownership = str(record.get("ownership") or "")
        business_role = str(record.get("business_role") or "")
        if (
            not road_id
            or not ownership
            or not business_role
            or road_id in result
        ):
            return None
        result[road_id] = (ownership, business_role)
    return result if set(result) == selected else None


def _aggregate_complete_business_exact(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("complete_exact")
        and row.get("ownership_exact")
        and row.get("business_role_exact")
    )


def _read_selected_business_truth(
    member_store: Path,
) -> dict[
    tuple[str, str],
    tuple[dict[str, tuple[str, str]], bool],
]:
    examples, _ = read_ordinary_road_set_examples(member_store)
    result = {}
    for row in examples:
        values: dict[str, tuple[str, str]] = {}
        evaluable = True
        for index in row.target_indices:
            if (
                index >= len(row.road_ids)
                or index >= len(row.ownership_targets)
                or index >= len(row.business_role_targets)
                or index >= len(row.ownership_task_mask)
                or index >= len(row.business_role_task_mask)
            ):
                raise ValueError("ordinary business truth shape differs")
            if not (
                row.ownership_task_mask[index]
                and row.business_role_task_mask[index]
            ):
                evaluable = False
                continue
            values[str(row.road_ids[index])] = (
                ROAD_OWNERSHIP_LABELS[row.ownership_targets[index]],
                ROAD_BUSINESS_ROLE_LABELS[
                    row.business_role_targets[index]
                ],
            )
        result[(row.case_key, row.segment_id)] = (values, evaluable)
    return result


def _selected_business_truth_result(
    predicted: Mapping[str, tuple[str, str]] | None,
    truth: tuple[Mapping[str, tuple[str, str]], bool] | None,
) -> tuple[bool, bool]:
    if predicted is None or truth is None:
        return False, False
    expected, evaluable = truth
    if not evaluable:
        return False, False
    return True, dict(predicted) == dict(expected)


def _read_anchor_gate(
    path: Path,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in _jsonl_rows(path):
        key = (str(row["case_key"]), str(row["anchor_id"]))
        existing = result.get(key)
        if existing is not None and (
            bool(existing["safety_accepted"])
            != bool(row["safety_accepted"])
            or int(existing["outer_fold"]) != int(row["outer_fold"])
        ):
            raise ValueError(f"anchor release gate conflicts: {key}")
        result[key] = row
    return result


def _read_required_anchors(
    path: Path,
) -> dict[tuple[str, str], tuple[str, ...]]:
    result = {}
    for row in _jsonl_rows(path):
        key = (str(row["case_key"]), str(row["segment_id"]))
        anchor_ids = tuple(
            str(value) for value in row.get("required_anchor_ids") or ()
        )
        if key in result and result[key] != anchor_ids:
            raise ValueError(f"ordinary required anchors conflict: {key}")
        result[key] = anchor_ids
    return result


def _jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "compose_ordinary_anchor_release_gate",
    "compose_ordinary_ensemble_release_gate",
]
