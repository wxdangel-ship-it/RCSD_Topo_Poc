from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    expected_calibration_error,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
    encode_groups,
    score_encoded_groups,
    train_scheme_a_p1_fold,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_models import (
    SchemeAP2P1OOFConfig,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def load_scheme_a_p2_p1_groups(
    dataset_run_root: Path, *, strict_hashes: bool = True
) -> tuple[list[P1GroupExample], dict[str, Any]]:
    root = normalize_runtime_path(dataset_run_root).resolve(strict=True)
    manifest_path = root / "scheme_a_p2_p1_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "dataset_passed":
        raise ValueError("Scheme A P2-P1 dataset gate did not pass")
    if not manifest.get("candidate_first"):
        raise ValueError("P2-P1 dataset did not preserve candidate-first isolation")
    if int(manifest.get("truth_feature_count", -1)) != 0 or int(
        manifest.get("absolute_coordinate_feature_count", -1)
    ) != 0:
        raise ValueError("P2-P1 dataset contains forbidden model features")
    outputs = dict(manifest.get("outputs") or {})
    feature_path = _verified_output(outputs, "features", strict_hashes)
    label_path = _verified_output(outputs, "labels", strict_hashes)
    compatibility_edge_path = _verified_output(outputs, "compatibility_edges", strict_hashes)
    labels: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(label_path):
        group_id = str(row["group_id"])
        if group_id in labels:
            raise ValueError(f"duplicate P2-P1 label group: {group_id}")
        labels[group_id] = row
    feature_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(feature_path):
        if row.get("feature_uses_truth") or int(row.get("absolute_coordinate_feature_count") or 0):
            raise ValueError("truth or absolute-coordinate feature reached P2-P1 loader")
        if row.get("object_type") not in {"SEGMENT", "NODE"}:
            raise ValueError("Movement or unknown object reached P2-P1 loader")
        feature_groups[str(row["group_id"])].append(row)
    if set(feature_groups) != set(labels):
        raise ValueError("P2-P1 feature/label group scope differs")
    groups: list[P1GroupExample] = []
    for group_id in sorted(labels):
        label = labels[group_id]
        rows = sorted(feature_groups[group_id], key=lambda item: str(item["candidate_id"]))
        matches = [
            index
            for index, row in enumerate(rows)
            if str(row["candidate_id"]) == str(label["truth_candidate_id"])
        ]
        if len(matches) != 1:
            raise ValueError(f"P2-P1 truth candidate is not unique: {group_id}")
        object_tokens = {tuple(str(value) for value in row["object_tokens"]) for row in rows}
        context_tokens = {tuple(str(value) for value in row["context_tokens"]) for row in rows}
        hard_unsafe = {bool(row["hard_unsafe"]) for row in rows}
        if len(object_tokens) != 1 or len(context_tokens) != 1 or len(hard_unsafe) != 1:
            raise ValueError(f"P2-P1 group-level feature mismatch: {group_id}")
        groups.append(
            P1GroupExample(
                case_key=str(label["case_key"]),
                fold=int(label["fold"]),
                group_id=group_id,
                object_type=str(label["object_type"]),
                object_id=str(label["object_id"]),
                object_tokens=next(iter(object_tokens)),
                context_tokens=next(iter(context_tokens)),
                candidates=tuple(
                    P1CandidateExample(
                        candidate_id=str(row["candidate_id"]),
                        candidate_target=str(row["candidate_target"]),
                        candidate_tokens=tuple(str(value) for value in row["candidate_tokens"]),
                        numeric_features=tuple(float(value) for value in row["numeric_features"]),
                    )
                    for row in rows
                ),
                truth_index=matches[0],
                truth_target=str(label["carrier_target"]),
                anomaly_target=bool(label["anomaly_target"]),
                sample_weight=float(label["label_weight"]),
                hard_unsafe=next(iter(hard_unsafe)),
            )
        )
    group_by_id = {group.group_id: group for group in groups}
    compatibility_edges = list(_read_jsonl(compatibility_edge_path))
    for edge in compatibility_edges:
        if edge.get("feature_uses_truth"):
            raise ValueError("truth-derived compatibility edge reached P2-P1 loader")
        segment_group = group_by_id.get(str(edge["segment_group_id"]))
        node_group = group_by_id.get(str(edge["node_group_id"]))
        if segment_group is None or segment_group.object_type != "SEGMENT":
            raise ValueError("compatibility edge references unknown Segment group")
        if node_group is None or node_group.object_type != "NODE":
            raise ValueError("compatibility edge references unknown Node group")
        if str(edge["required_node_target"]) not in {"T01_NODE", "PROPOSAL_NODE"}:
            raise ValueError("compatibility edge has unsupported Node target")
        if str(edge["segment_candidate_id"]) not in {
            candidate.candidate_id for candidate in segment_group.candidates
        }:
            raise ValueError("compatibility edge references unknown Segment candidate")
    return groups, {
        "dataset_root": root,
        "dataset_manifest": manifest,
        "dataset_manifest_path": manifest_path,
        "dataset_manifest_sha256": sha256_file(manifest_path),
        "feature_path": feature_path,
        "label_path": label_path,
        "compatibility_edge_path": compatibility_edge_path,
        "compatibility_edges": compatibility_edges,
        "labels": labels,
    }


def train_scheme_a_p2_p1_fold(
    groups: Sequence[P1GroupExample],
    *,
    case_folds: Mapping[str, int],
    held_out_fold: int,
    seed: int,
    dataset_manifest_sha256: str,
    config: SchemeAP2P1OOFConfig,
    compatibility_edges: Sequence[Mapping[str, Any]],
    junction_by_group: Mapping[str, str],
) -> dict[str, Any]:
    result = train_scheme_a_p1_fold(
        groups,
        case_folds=case_folds,
        held_out_fold=held_out_fold,
        seed=seed,
        dataset_manifest_sha256=dataset_manifest_sha256,
        config=config,
    )
    encoded_inner = encode_groups(result["inner_groups"], result["vocabulary"])
    inner_scores, inner_probabilities, inner_anomaly = score_encoded_groups(
        result["model"],
        encoded_inner,
        batch_group_count=config.batch_group_count,
        device=result["device"],
    )
    result["thresholds"] = select_p2_p1_thresholds(
        result["inner_groups"],
        inner_scores,
        inner_probabilities,
        inner_anomaly,
        compatibility_edges=compatibility_edges,
        junction_by_group=junction_by_group,
    )
    result["summary"].update(result["thresholds"])
    return result


def select_p2_p1_thresholds(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    *,
    compatibility_edges: Sequence[Mapping[str, Any]],
    junction_by_group: Mapping[str, str],
) -> dict[str, float]:
    raw_selected = _selected_records(groups, scores, probabilities, anomaly_probabilities)
    anomaly_values = sorted(
        {0.0, 1.0, *(float(row["anomaly_probability"]) for row in raw_selected)}
    )
    anomaly_options: list[tuple[tuple[float, ...], float, float, float]] = []
    for threshold in anomaly_values:
        predicted = [
            bool(row["hard_unsafe"])
            or float(row["anomaly_probability"]) >= threshold
            for row in raw_selected
        ]
        truth = [bool(row["anomaly_target"]) for row in raw_selected]
        tp = sum(a and b for a, b in zip(predicted, truth, strict=True))
        fp = sum(a and not b for a, b in zip(predicted, truth, strict=True))
        fn = sum((not a) and b for a, b in zip(predicted, truth, strict=True))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        satisfies = precision >= 0.80 and recall == 1.0
        anomaly_options.append(((float(satisfies), recall, precision, -threshold), threshold, precision, recall))
    _, anomaly_threshold, anomaly_precision, anomaly_recall = max(anomaly_options)
    segment_eligible = [
        row
        for row in raw_selected
        if row["object_type"] == "SEGMENT"
        and not row["hard_unsafe"]
        and row["selected_target"] != "REVIEW_FALLBACK"
        and float(row["anomaly_probability"]) < anomaly_threshold
    ]
    segment_threshold = _zero_error_confidence_threshold(segment_eligible)
    thresholds: dict[str, float] = {
        "anomaly_threshold": anomaly_threshold,
        "segment_confidence_threshold": segment_threshold,
        "node_confidence_threshold": 0.0,
    }
    provisional = _joint_selected_records(
        groups,
        scores,
        probabilities,
        anomaly_probabilities,
        thresholds,
        compatibility_edges=compatibility_edges,
        junction_by_group=junction_by_group,
        apply_node_threshold=False,
    )
    node_eligible = [
        row
        for row in provisional
        if row["object_type"] == "NODE"
        and not row["hard_unsafe"]
        and not row["constraint_conflict"]
        and float(row["anomaly_probability"]) < anomaly_threshold
    ]
    thresholds["node_confidence_threshold"] = _zero_error_confidence_threshold(
        node_eligible
    )
    selected = _joint_selected_records(
        groups,
        scores,
        probabilities,
        anomaly_probabilities,
        thresholds,
        compatibility_edges=compatibility_edges,
        junction_by_group=junction_by_group,
        apply_node_threshold=True,
    )
    for object_type in ("SEGMENT", "NODE"):
        rows = [row for row in selected if row["object_type"] == object_type]
        accepted = [row for row in rows if row["accepted"]]
        thresholds[f"inner_{object_type.lower()}_accepted_precision"] = sum(
            bool(row["correct"]) for row in accepted
        ) / max(1, len(accepted))
        thresholds[f"inner_{object_type.lower()}_accepted_coverage"] = len(accepted) / max(
            1, len(rows)
        )
    thresholds.update(
        {
            "inner_anomaly_precision": anomaly_precision,
            "inner_anomaly_recall": anomaly_recall,
            "inner_joint_junction_fallback_count": len(
                {
                    row["junction_key"]
                    for row in selected
                    if row["junction_fallback_applied"]
                }
            ),
        }
    )
    return thresholds


def score_selection_rows(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    thresholds: Mapping[str, float],
    *,
    seed: int,
    fold: int,
    model_signature: str,
    compatibility_edges: Sequence[Mapping[str, Any]],
    junction_by_group: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    score_rows: list[dict[str, Any]] = []
    for group, group_scores, group_probabilities, anomaly_probability in zip(
        groups, scores, probabilities, anomaly_probabilities, strict=True
    ):
        for candidate, score, probability in zip(
            group.candidates, group_scores, group_probabilities, strict=True
        ):
            score_rows.append(
                {
                    "case_key": group.case_key,
                    "group_id": group.group_id,
                    "object_type": group.object_type,
                    "candidate_id": candidate.candidate_id,
                    "candidate_target": candidate.candidate_target,
                    "score": float(score),
                    "probability": float(probability),
                    "anomaly_probability": float(anomaly_probability),
                    "seed": seed,
                    "fold": fold,
                    "model_signature": model_signature,
                }
            )
    selected_records = _joint_selected_records(
        groups,
        scores,
        probabilities,
        anomaly_probabilities,
        thresholds,
        compatibility_edges=compatibility_edges,
        junction_by_group=junction_by_group,
        apply_node_threshold=True,
    )
    selection_rows: list[dict[str, Any]] = []
    for row in selected_records:
        selection_rows.append(
            {
                "case_key": row["case_key"],
                "group_id": row["group_id"],
                "object_type": row["object_type"],
                "object_id": row["object_id"],
                "selected_candidate_id": row["selected_candidate_id"],
                "selected_target": row["selected_target"],
                "confidence": row["confidence"],
                "raw_selected_candidate_id": row["raw_selected_candidate_id"],
                "raw_selected_target": row["raw_selected_target"],
                "raw_confidence": row["raw_confidence"],
                "constraint_required_target": row["constraint_required_target"],
                "constraint_conflict": row["constraint_conflict"],
                "joint_constraint_applied": row["object_type"] == "NODE",
                "structural_candidate_id": row.get(
                    "structural_candidate_id", row["selected_candidate_id"]
                ),
                "structural_target": row.get(
                    "structural_target", row["selected_target"]
                ),
                "junction_key": row["junction_key"],
                "junction_fallback_applied": row["junction_fallback_applied"],
                "anomaly_probability": row["anomaly_probability"],
                "accepted": row["accepted"],
                "decision": "ACCEPT" if row["accepted"] else "FALLBACK",
                "fallback_unit": "JUNCTION" if row["object_type"] == "NODE" else "SEGMENT",
                "reason": row["reason"],
                "seed": seed,
                "fold": fold,
                "model_signature": model_signature,
            }
        )
    return score_rows, selection_rows


def _zero_error_confidence_threshold(rows: Sequence[Mapping[str, Any]]) -> float:
    bad = [float(row["confidence"]) for row in rows if not row["correct"]]
    return 0.0 if not bad else math.nextafter(max(bad), math.inf)


def _joint_selected_records(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    thresholds: Mapping[str, float],
    *,
    compatibility_edges: Sequence[Mapping[str, Any]],
    junction_by_group: Mapping[str, str],
    apply_node_threshold: bool,
) -> list[dict[str, Any]]:
    records = _selected_records(groups, scores, probabilities, anomaly_probabilities)
    record_by_group = {str(row["group_id"]): row for row in records}
    group_by_id = {group.group_id: group for group in groups}
    score_by_group = {
        group.group_id: tuple(float(value) for value in group_scores)
        for group, group_scores in zip(groups, scores, strict=True)
    }
    probability_by_choice = {
        (group.group_id, candidate.candidate_id): float(probability)
        for group, group_probabilities in zip(groups, probabilities, strict=True)
        for candidate, probability in zip(
            group.candidates, group_probabilities, strict=True
        )
    }
    edge_by_choice: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    segment_junctions: dict[str, set[str]] = defaultdict(set)
    node_segment_candidate_targets: dict[
        str, dict[str, dict[str, set[str]]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for edge in compatibility_edges:
        segment_group_id = str(edge["segment_group_id"])
        node_group_id = str(edge["node_group_id"])
        if segment_group_id not in group_by_id or node_group_id not in group_by_id:
            continue
        segment_candidate_id = str(edge["segment_candidate_id"])
        required_target = str(edge["required_node_target"])
        relation = (node_group_id, required_target)
        if relation not in edge_by_choice[(segment_group_id, segment_candidate_id)]:
            edge_by_choice[(segment_group_id, segment_candidate_id)].append(relation)
        node_segment_candidate_targets[node_group_id][segment_group_id][
            segment_candidate_id
        ].add(required_target)
        segment_junctions[segment_group_id].add(
            str(junction_by_group.get(node_group_id) or node_group_id)
        )

    anomaly_threshold = float(thresholds["anomaly_threshold"])
    segment_threshold = float(thresholds["segment_confidence_threshold"])
    node_threshold = float(thresholds.get("node_confidence_threshold", 0.0))
    forced_junctions: set[str] = set()
    forced_reasons: dict[str, str] = {}
    junction_scope = {
        str(junction_by_group.get(group.group_id) or group.group_id)
        for group in groups
        if group.object_type == "NODE"
    }
    node_structure_probabilities = _node_structure_probabilities(
        node_segment_candidate_targets,
        group_by_id,
        probability_by_choice,
    )
    model_requirements: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        if group.object_type != "SEGMENT":
            continue
        row = record_by_group[group.group_id]
        candidate = group.candidates[int(row["raw_selected_index"])]
        for node_group_id, required_target in edge_by_choice.get(
            (group.group_id, candidate.candidate_id), []
        ):
            model_requirements[node_group_id].add(required_target)
    for group in groups:
        if group.object_type != "NODE":
            continue
        row = record_by_group[group.group_id]
        required_targets = model_requirements.get(group.group_id, set())
        junction_key = str(junction_by_group.get(group.group_id) or group.group_id)
        allowed_target, conflict_reason = _required_node_target(required_targets)
        allowed_indices = [
            index
            for index, candidate in enumerate(group.candidates)
            if candidate.candidate_target == allowed_target
        ]
        if not allowed_indices:
            conflict_reason = "required_node_candidate_missing"
            allowed_indices = [
                index
                for index, candidate in enumerate(group.candidates)
                if candidate.candidate_target == "OMIT"
            ]
        if not allowed_indices:
            allowed_indices = [int(row["raw_selected_index"])]
        selected_index = max(
            allowed_indices,
            key=lambda index: (
                score_by_group[group.group_id][index],
                group.candidates[index].candidate_id,
            ),
        )
        local_confidence = _conditional_confidence(
            score_by_group[group.group_id], allowed_indices, selected_index
        )
        structure_target = "CONFLICT" if conflict_reason == "shared_node_source_conflict" else allowed_target
        confidence = local_confidence * float(
            node_structure_probabilities.get(group.group_id, {}).get(
                structure_target, 0.0
            )
        )
        selected_candidate = group.candidates[selected_index]
        accepted = (
            not group.hard_unsafe
            and not conflict_reason
            and float(row["anomaly_probability"]) < anomaly_threshold
            and (not apply_node_threshold or confidence >= node_threshold)
        )
        if accepted:
            reason = "model_score_and_joint_constraint_passed"
        elif conflict_reason:
            reason = conflict_reason
        elif group.hard_unsafe:
            reason = "hard_unsafe"
        elif float(row["anomaly_probability"]) >= anomaly_threshold:
            reason = "anomaly_threshold"
        else:
            reason = "confidence_threshold"
        row.update(
            {
                "model_joint_selected_candidate_id": selected_candidate.candidate_id,
                "model_joint_selected_target": selected_candidate.candidate_target,
                "model_joint_confidence": confidence,
                "model_joint_correct": selected_index == group.truth_index,
                "model_joint_accepted": accepted,
                "model_joint_reason": reason,
                "model_joint_required_target": allowed_target,
                "model_joint_constraint_conflict": bool(conflict_reason),
            }
        )
        if required_targets and not accepted:
            forced_junctions.add(junction_key)
            forced_reasons[junction_key] = (
                conflict_reason or "joint_node_confidence_junction_fallback"
            )

    for _ in range(len(junction_scope) + 2):
        requirements: dict[str, set[str]] = defaultdict(set)
        for group in groups:
            row = record_by_group[group.group_id]
            row["junction_key"] = ""
            row["junction_fallback_applied"] = False
            row["constraint_conflict"] = False
            row["constraint_required_target"] = ""
            if group.object_type != "SEGMENT":
                continue
            raw_index = int(row["raw_selected_index"])
            candidate = group.candidates[raw_index]
            base_accepted = (
                not group.hard_unsafe
                and candidate.candidate_target != "REVIEW_FALLBACK"
                and float(row["raw_confidence"]) >= segment_threshold
                and float(row["anomaly_probability"]) < anomaly_threshold
            )
            affected = sorted(segment_junctions.get(group.group_id, set()) & forced_junctions)
            if affected:
                accepted = False
                effective_index = _safe_segment_index(group)
                reason = forced_reasons.get(affected[0], "joint_node_junction_fallback")
                row["junction_key"] = affected[0]
                row["junction_fallback_applied"] = True
            else:
                accepted = base_accepted
                effective_index = raw_index if accepted else _safe_segment_index(group)
                reason = (
                    "model_score_passed"
                    if accepted
                    else _fallback_reason(
                        group,
                        raw_index,
                        float(row["raw_confidence"]),
                        float(row["anomaly_probability"]),
                        segment_threshold,
                        thresholds,
                    )
                )
            effective_candidate = group.candidates[effective_index]
            row.update(
                {
                    "selected_candidate_id": candidate.candidate_id,
                    "selected_target": candidate.candidate_target,
                    "confidence": float(row["raw_confidence"]),
                    "correct": raw_index == group.truth_index,
                    "accepted": accepted,
                    "reason": reason,
                    "effective_constraint_candidate_id": effective_candidate.candidate_id,
                    "effective_constraint_target": effective_candidate.candidate_target,
                }
            )
            for node_group_id, required_target in edge_by_choice.get(
                (group.group_id, effective_candidate.candidate_id), []
            ):
                requirements[node_group_id].add(required_target)

        new_forced: dict[str, str] = {}
        for group in groups:
            if group.object_type != "NODE":
                continue
            row = record_by_group[group.group_id]
            required_targets = requirements.get(group.group_id, set())
            junction_key = str(junction_by_group.get(group.group_id) or group.group_id)
            allowed_target, conflict_reason = _required_node_target(required_targets)
            allowed_indices = [
                index
                for index, candidate in enumerate(group.candidates)
                if candidate.candidate_target == allowed_target
            ]
            if not allowed_indices:
                conflict_reason = "required_node_candidate_missing"
                allowed_indices = [
                    index
                    for index, candidate in enumerate(group.candidates)
                    if candidate.candidate_target == "OMIT"
                ]
            if not allowed_indices:
                allowed_indices = [int(row["raw_selected_index"])]
            selected_index = max(
                allowed_indices,
                key=lambda index: (
                    score_by_group[group.group_id][index],
                    group.candidates[index].candidate_id,
                ),
            )
            confidence = _conditional_confidence(
                score_by_group[group.group_id], allowed_indices, selected_index
            )
            selected_candidate = group.candidates[selected_index]
            threshold_passed = not apply_node_threshold or confidence >= node_threshold
            accepted = (
                not group.hard_unsafe
                and not conflict_reason
                and float(row["anomaly_probability"]) < anomaly_threshold
                and threshold_passed
            )
            if accepted:
                reason = "model_score_and_joint_constraint_passed"
            elif conflict_reason:
                reason = conflict_reason
            elif group.hard_unsafe:
                reason = "hard_unsafe"
            elif float(row["anomaly_probability"]) >= anomaly_threshold:
                reason = "anomaly_threshold"
            else:
                reason = "confidence_threshold"
            row.update(
                {
                    "junction_key": junction_key,
                    "junction_fallback_applied": junction_key in forced_junctions,
                    "constraint_required_target": allowed_target,
                    "constraint_conflict": bool(conflict_reason),
                    "selected_candidate_id": selected_candidate.candidate_id,
                    "selected_target": selected_candidate.candidate_target,
                    "confidence": confidence,
                    "correct": selected_index == group.truth_index,
                    "accepted": accepted,
                    "reason": reason,
                    "effective_constraint_candidate_id": selected_candidate.candidate_id,
                    "effective_constraint_target": selected_candidate.candidate_target,
                }
            )
            if required_targets and not accepted and junction_key not in forced_junctions:
                new_forced[junction_key] = (
                    conflict_reason or "joint_node_confidence_junction_fallback"
                )
        if not new_forced:
            break
        forced_junctions.update(new_forced)
        forced_reasons.update(new_forced)
    else:
        raise ValueError("P2-P1 joint compatibility fallback did not converge")
    for group in groups:
        if group.object_type != "NODE":
            continue
        row = record_by_group[group.group_id]
        structural_candidate_id = str(row["effective_constraint_candidate_id"])
        structural_target = str(row["effective_constraint_target"])
        junction_key = str(row["junction_key"])
        junction_fallback = junction_key in forced_junctions
        row.update(
            {
                "structural_candidate_id": structural_candidate_id,
                "structural_target": structural_target,
                "selected_candidate_id": row["model_joint_selected_candidate_id"],
                "selected_target": row["model_joint_selected_target"],
                "confidence": row["model_joint_confidence"],
                "correct": row["model_joint_correct"],
                "constraint_required_target": row["model_joint_required_target"],
                "constraint_conflict": row["model_joint_constraint_conflict"],
                "junction_fallback_applied": junction_fallback,
                "accepted": bool(row["model_joint_accepted"]) and not junction_fallback,
                "reason": (
                    forced_reasons.get(junction_key, "joint_node_junction_fallback")
                    if junction_fallback
                    else row["model_joint_reason"]
                ),
            }
        )
    return records


def _required_node_target(required_targets: set[str]) -> tuple[str, str]:
    if not required_targets:
        return "OMIT", ""
    if len(required_targets) == 1:
        return next(iter(required_targets)), ""
    return "OMIT", "shared_node_source_conflict"


def _node_structure_probabilities(
    node_segment_candidate_targets: Mapping[
        str, Mapping[str, Mapping[str, set[str]]]
    ],
    group_by_id: Mapping[str, P1GroupExample],
    probability_by_choice: Mapping[tuple[str, str], float],
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for node_group_id, segment_rows in node_segment_candidate_targets.items():
        probability_none = 1.0
        probability_no_t01 = 1.0
        probability_no_proposal = 1.0
        for segment_group_id, targets_by_candidate in segment_rows.items():
            group = group_by_id[segment_group_id]
            bins = {
                "NONE": 0.0,
                "T01_NODE": 0.0,
                "PROPOSAL_NODE": 0.0,
                "CONFLICT": 0.0,
            }
            for candidate in group.candidates:
                targets = targets_by_candidate.get(candidate.candidate_id, set())
                if not targets:
                    key = "NONE"
                elif targets == {"T01_NODE"}:
                    key = "T01_NODE"
                elif targets == {"PROPOSAL_NODE"}:
                    key = "PROPOSAL_NODE"
                else:
                    key = "CONFLICT"
                bins[key] += float(
                    probability_by_choice[(segment_group_id, candidate.candidate_id)]
                )
            probability_none *= bins["NONE"]
            probability_no_t01 *= bins["NONE"] + bins["PROPOSAL_NODE"]
            probability_no_proposal *= bins["NONE"] + bins["T01_NODE"]
        t01_only = max(0.0, probability_no_proposal - probability_none)
        proposal_only = max(0.0, probability_no_t01 - probability_none)
        conflict = max(
            0.0,
            1.0 - probability_none - t01_only - proposal_only,
        )
        result[node_group_id] = {
            "OMIT": min(1.0, probability_none),
            "T01_NODE": min(1.0, t01_only),
            "PROPOSAL_NODE": min(1.0, proposal_only),
            "CONFLICT": min(1.0, conflict),
        }
    return result


def _safe_segment_index(group: P1GroupExample) -> int:
    safe = [
        index
        for index, candidate in enumerate(group.candidates)
        if candidate.candidate_target == "KEEP_SWSD"
    ]
    if len(safe) != 1:
        raise ValueError(f"Segment group has no unique SWSD fallback: {group.group_id}")
    return safe[0]


def _conditional_confidence(
    scores: Sequence[float], allowed_indices: Sequence[int], selected_index: int
) -> float:
    peak = max(float(scores[index]) for index in allowed_indices)
    weights = {
        index: math.exp(float(scores[index]) - peak) for index in allowed_indices
    }
    return weights[selected_index] / sum(weights.values())


def p2_p1_metrics(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    thresholds: Mapping[str, float],
    junction_by_group: Mapping[str, str],
) -> dict[str, Any]:
    selected = _selected_records(groups, scores, probabilities, anomaly_probabilities)
    for row in selected:
        threshold = float(thresholds[f"{str(row['object_type']).lower()}_confidence_threshold"])
        row["accepted"] = (
            not row["hard_unsafe"]
            and row["selected_target"] != "REVIEW_FALLBACK"
            and float(row["confidence"]) >= threshold
            and float(row["anomaly_probability"]) < float(thresholds["anomaly_threshold"])
        )
    segment = [row for row in selected if row["object_type"] == "SEGMENT"]
    node = [row for row in selected if row["object_type"] == "NODE"]
    labels = ("KEEP_SWSD", "REVIEW_FALLBACK", "USE_RCSD")
    macro = _macro_f1(
        [str(row["truth_target"]) for row in segment],
        [str(row["selected_target"]) for row in segment],
        labels,
    )
    use_rcsd = [row for row in segment if row["truth_target"] == "USE_RCSD"]
    confidences = torch.tensor([float(row["confidence"]) for row in selected], dtype=torch.float32)
    correctness = torch.tensor([bool(row["correct"]) for row in selected], dtype=torch.bool)
    anomaly_predicted = [
        bool(row["hard_unsafe"])
        or float(row["anomaly_probability"]) >= float(thresholds["anomaly_threshold"])
        for row in selected
    ]
    anomaly_truth = [bool(row["anomaly_target"]) for row in selected]
    tp = sum(a and b for a, b in zip(anomaly_predicted, anomaly_truth, strict=True))
    fp = sum(a and not b for a, b in zip(anomaly_predicted, anomaly_truth, strict=True))
    fn = sum((not a) and b for a, b in zip(anomaly_predicted, anomaly_truth, strict=True))
    junction_rows: dict[str, list[bool]] = defaultdict(list)
    for row in node:
        junction_rows[junction_by_group.get(str(row["group_id"]), str(row["group_id"]))].append(
            bool(row["correct"])
        )
    accepted = [row for row in segment if row["accepted"]]
    accepted_use_rcsd = [row for row in use_rcsd if row["accepted"]]
    return {
        "segment_macro_f1": macro,
        "use_rcsd_recall": sum(bool(row["correct"]) for row in use_rcsd) / max(1, len(use_rcsd)),
        "node_candidate_exact": sum(bool(row["correct"]) for row in node) / max(1, len(node)),
        "junction_node_exact": sum(all(values) for values in junction_rows.values()) / max(1, len(junction_rows)),
        "ece": expected_calibration_error(confidences, correctness),
        "accepted_count": len(accepted),
        "accepted_wrong_replacement_count": sum(not bool(row["correct"]) for row in accepted),
        "accepted_precision": sum(bool(row["correct"]) for row in accepted) / max(1, len(accepted)),
        "safe_accepted_coverage": len(accepted) / max(1, len(segment)),
        "use_rcsd_safe_accepted_coverage": len(accepted_use_rcsd) / max(1, len(use_rcsd)),
        "hard_conflict_recall": tp / max(1, tp + fn),
        "anomaly_precision": tp / max(1, tp + fp),
        "segment_count": len(segment),
        "node_group_count": len(node),
        "junction_unit_count": len(junction_rows),
    }


def _selected_records(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group, group_scores, group_probabilities, anomaly_probability in zip(
        groups, scores, probabilities, anomaly_probabilities, strict=True
    ):
        index = max(
            range(len(group_scores)),
            key=lambda value: (float(group_scores[value]), group.candidates[value].candidate_id),
        )
        result.append(
            {
                "case_key": group.case_key,
                "group_id": group.group_id,
                "object_type": group.object_type,
                "object_id": group.object_id,
                "raw_selected_index": index,
                "raw_selected_candidate_id": group.candidates[index].candidate_id,
                "raw_selected_target": group.candidates[index].candidate_target,
                "raw_confidence": float(group_probabilities[index]),
                "selected_candidate_id": group.candidates[index].candidate_id,
                "selected_target": group.candidates[index].candidate_target,
                "truth_target": group.truth_target,
                "correct": index == group.truth_index,
                "confidence": float(group_probabilities[index]),
                "anomaly_probability": float(anomaly_probability),
                "anomaly_target": group.anomaly_target,
                "hard_unsafe": group.hard_unsafe,
            }
        )
    return result


def _fallback_reason(
    group: P1GroupExample,
    selected: int,
    confidence: float,
    anomaly_probability: float,
    confidence_threshold: float,
    thresholds: Mapping[str, float],
) -> str:
    if group.hard_unsafe:
        return "hard_unsafe"
    if group.candidates[selected].candidate_target == "REVIEW_FALLBACK":
        return "review_candidate"
    if anomaly_probability >= float(thresholds["anomaly_threshold"]):
        return "anomaly_threshold"
    if confidence < confidence_threshold:
        return "confidence_threshold"
    return "generic_constraint"


def _macro_f1(truth: Sequence[str], predicted: Sequence[str], labels: Sequence[str]) -> float:
    values: list[float] = []
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(truth, predicted, strict=True))
        fp = sum(a != label and b == label for a, b in zip(truth, predicted, strict=True))
        fn = sum(a == label and b != label for a, b in zip(truth, predicted, strict=True))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        values.append(2 * precision * recall / max(1e-12, precision + recall))
    return sum(values) / len(values)


def _verified_output(outputs: Mapping[str, Any], role: str, strict_hashes: bool) -> Path:
    record = outputs.get(role)
    if not record:
        raise ValueError(f"P2-P1 dataset output missing: {role}")
    path = normalize_runtime_path(str(record["path"])).resolve(strict=True)
    if strict_hashes and sha256_file(path) != record["sha256"]:
        raise ValueError(f"P2-P1 dataset output hash mismatch: {role}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "load_scheme_a_p2_p1_groups",
    "p2_p1_metrics",
    "score_selection_rows",
    "select_p2_p1_thresholds",
    "train_scheme_a_p2_p1_fold",
]
