from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1CandidateExample,
    P1GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_training import (
    load_scheme_a_p2_p1_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_models import (
    SchemeAP2P2P1Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def load_segment_safety_groups(
    config: SchemeAP2P2P1Config,
) -> tuple[list[P1GroupExample], dict[str, Any]]:
    groups, dataset = load_scheme_a_p2_p1_groups(
        config.dataset_run_root, strict_hashes=config.strict_hashes
    )
    segment_groups = [group for group in groups if group.object_type == "SEGMENT"]
    if len(segment_groups) != config.expected_segment_group_count:
        raise ValueError("Segment safety denominator differs from frozen P2-P1 scope")
    case_folds = _case_folds(segment_groups)
    if len(case_folds) != config.expected_case_count or set(case_folds.values()) != set(
        range(config.expected_fold_count)
    ):
        raise ValueError("Case/fold denominator differs from frozen P2-P1 scope")

    oof_a = _load_oof(config.base_oof_run_a, config)
    oof_b = _load_oof(config.base_oof_run_b, config)
    compared_roles = ("scores", "selections", "effective_selections")
    comparison = {
        role: oof_a["output_hashes"][role] == oof_b["output_hashes"][role]
        for role in compared_roles
    }
    if not all(comparison.values()):
        raise ValueError("P2-P1 OOF Run A/B content differs")

    score_by_group: dict[str, dict[int, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    anomaly_by_group: dict[str, dict[int, float]] = defaultdict(dict)
    for row in _read_jsonl(oof_a["paths"]["scores"]):
        if row.get("object_type") != "SEGMENT":
            continue
        group_id = str(row["group_id"])
        seed = int(row["seed"])
        candidate_id = str(row["candidate_id"])
        score_by_group[group_id][seed][candidate_id] = {
            "score": float(row["score"]),
            "probability": float(row["probability"]),
        }
        anomaly_by_group[group_id][seed] = float(row["anomaly_probability"])
    selected_by_group: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in _read_jsonl(oof_a["paths"]["selections"]):
        if row.get("object_type") == "SEGMENT":
            selected_by_group[str(row["group_id"])][int(row["seed"])] = row

    augmented: list[P1GroupExample] = []
    proposals: dict[str, dict[str, Any]] = {}
    inference_rows: list[dict[str, Any]] = []
    for group in segment_groups:
        scores = score_by_group.get(group.group_id, {})
        selections = selected_by_group.get(group.group_id, {})
        if set(scores) != set(config.base_seeds) or set(selections) != set(config.base_seeds):
            raise ValueError(f"base OOF seed denominator differs: {group.group_id}")
        candidate_ids = {candidate.candidate_id for candidate in group.candidates}
        if any(set(scores[seed]) != candidate_ids for seed in config.base_seeds):
            raise ValueError(f"base OOF candidate denominator differs: {group.group_id}")
        selected_ids = tuple(str(selections[seed]["selected_candidate_id"]) for seed in config.base_seeds)
        selected_targets = tuple(str(selections[seed]["selected_target"]) for seed in config.base_seeds)
        proposal_id = selected_ids[0] if len(set(selected_ids)) == 1 else ""
        proposal_target = selected_targets[0] if len(set(selected_targets)) == 1 else ""
        proposals[group.group_id] = {
            "case_key": group.case_key,
            "fold": group.fold,
            "candidate_id": proposal_id,
            "candidate_target": proposal_target,
            "candidate_agreement": bool(proposal_id),
            "target_agreement": bool(proposal_target),
            "per_seed_candidate_ids": selected_ids,
            "per_seed_targets": selected_targets,
        }
        top_probabilities: list[float] = []
        top_margins: list[float] = []
        entropies: list[float] = []
        for seed in config.base_seeds:
            probabilities = sorted(
                (value["probability"] for value in scores[seed].values()), reverse=True
            )
            top_probabilities.append(probabilities[0])
            top_margins.append(probabilities[0] - (probabilities[1] if len(probabilities) > 1 else 0.0))
            entropies.append(-sum(value * math.log(max(value, 1e-12)) for value in probabilities))
        anomaly_values = [anomaly_by_group[group.group_id][seed] for seed in config.base_seeds]
        new_candidates: list[P1CandidateExample] = []
        for candidate in group.candidates:
            probabilities = [scores[seed][candidate.candidate_id]["probability"] for seed in config.base_seeds]
            mean_probability = sum(probabilities) / len(probabilities)
            variance = sum((value - mean_probability) ** 2 for value in probabilities) / len(probabilities)
            selected_count = sum(candidate.candidate_id == value for value in selected_ids)
            augmented_numeric = candidate.numeric_features + (
                *probabilities,
                mean_probability,
                min(probabilities),
                max(probabilities),
                math.sqrt(variance),
                selected_count / len(config.base_seeds),
                sum(anomaly_values) / len(anomaly_values),
                max(anomaly_values),
                min(top_probabilities),
                min(top_margins),
                max(entropies),
            )
            if len(augmented_numeric) != config.numeric_dim:
                raise ValueError("safety numeric feature dimension differs from contract")
            augmented_tokens = candidate.candidate_tokens + (
                f"BASE_SELECTED_COUNT:{selected_count}",
                f"BASE_SELECTED_ALL:{selected_count == len(config.base_seeds)}",
            )
            new_candidates.append(
                P1CandidateExample(
                    candidate_id=candidate.candidate_id,
                    candidate_target=candidate.candidate_target,
                    candidate_tokens=augmented_tokens,
                    numeric_features=augmented_numeric,
                )
            )
        object_tokens = group.object_tokens + (
            f"BASE_CANDIDATE_AGREEMENT:{bool(proposal_id)}",
            f"BASE_TARGET_AGREEMENT:{bool(proposal_target)}",
        )
        augmented.append(
            P1GroupExample(
                case_key=group.case_key,
                fold=group.fold,
                group_id=group.group_id,
                object_type=group.object_type,
                object_id=group.object_id,
                object_tokens=object_tokens,
                context_tokens=group.context_tokens,
                candidates=tuple(new_candidates),
                truth_index=group.truth_index,
                truth_target=group.truth_target,
                anomaly_target=group.anomaly_target,
                sample_weight=group.sample_weight,
                hard_unsafe=group.hard_unsafe,
            )
        )
        inference_rows.append(
            {
                "case_key": group.case_key,
                "group_id": group.group_id,
                "object_type": "SEGMENT",
                "fold": group.fold,
                "feature_uses_truth": False,
                "feature_uses_identifier": False,
                "absolute_coordinate_feature_count": 0,
                "identifier_role": "lineage_only",
                "candidate_count": len(group.candidates),
                "base_candidate_agreement": bool(proposal_id),
                "base_target_agreement": bool(proposal_target),
            }
        )

    review_count = sum(group.truth_target == "REVIEW_FALLBACK" for group in augmented)
    if review_count != config.expected_review_count:
        raise ValueError("Review denominator differs from frozen P2-P1 scope")
    stable_false_use = sorted(
        group.group_id
        for group in augmented
        if proposals[group.group_id]["candidate_target"] == "USE_RCSD"
        and proposals[group.group_id]["candidate_id"]
        and proposals[group.group_id]["candidate_id"]
        != group.candidates[group.truth_index].candidate_id
    )
    if len(stable_false_use) != config.expected_stable_false_use_count:
        raise ValueError("stable false-use denominator differs from P2-P2-P0 evidence")
    p0_root = normalize_runtime_path(config.p2_p2_p0_run_root).resolve(strict=True)
    p0_manifest_path = p0_root / "scheme_a_p2_p2_p0_audit_manifest.json"
    p0_manifest = _read_json(p0_manifest_path)
    if p0_manifest.get("decision") != "P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO":
        raise ValueError("P2-P2-P0 did not authorize the safety-head technical route")
    lineage = {
        "dataset_manifest_sha256": dataset["dataset_manifest_sha256"],
        "oof_run_a_manifest_sha256": oof_a["manifest_sha256"],
        "oof_run_b_manifest_sha256": oof_b["manifest_sha256"],
        "oof_compared_output_hashes": oof_a["output_hashes"],
        "p2_p2_p0_manifest_sha256": sha256_file(p0_manifest_path),
    }
    lineage["safety_dataset_signature"] = canonical_sha256(lineage)
    return augmented, {
        "all_groups": groups,
        "dataset": dataset,
        "case_folds": case_folds,
        "proposals": proposals,
        "inference_rows": inference_rows,
        "stable_false_use_group_ids": stable_false_use,
        "lineage": lineage,
        "oof_a": oof_a,
        "oof_ab_comparison": comparison,
    }


def _load_oof(root_value: Path, config: SchemeAP2P2P1Config) -> dict[str, Any]:
    root = normalize_runtime_path(root_value).resolve(strict=True)
    manifest_path = root / "scheme_a_p2_p1_oof_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("decision") != "P05_SCHEME_A_P2_P1_SAFETY_NO_GO":
        raise ValueError("base P2-P1 run does not have the frozen Safety NO-GO status")
    outputs = dict(manifest.get("outputs") or {})
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for role in ("scores", "selections", "effective_selections", "roadgraphs"):
        record = dict(outputs.get(role) or {})
        path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
        actual = sha256_file(path)
        if config.strict_hashes and actual != str(record.get("sha256") or ""):
            raise ValueError(f"base P2-P1 output hash mismatch: {role}")
        paths[role] = path
        hashes[role] = actual
    return {
        "root": root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "paths": paths,
        "output_hashes": hashes,
    }


def _case_folds(groups: Sequence[P1GroupExample]) -> dict[str, int]:
    result: dict[str, int] = {}
    for group in groups:
        previous = result.setdefault(group.case_key, group.fold)
        if previous != group.fold:
            raise ValueError("one Case spans multiple folds")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = ["load_segment_safety_groups"]
