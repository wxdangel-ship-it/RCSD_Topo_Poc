from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SchemeAP2P2P0AuditConfig:
    dataset_run_root: Path
    oof_run_root_a: Path
    oof_run_root_b: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    expected_segment_count: int = 8863
    expected_node_count: int = 28240
    expected_review_count: int = 40
    expected_seeds: tuple[int, ...] = (17, 29, 43)
    minimum_score_only_use_coverage: float = 0.50
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if min(
            self.expected_case_count,
            self.expected_segment_count,
            self.expected_node_count,
        ) <= 0:
            raise ValueError("expected denominators must be positive")
        if self.expected_review_count < 0:
            raise ValueError("expected_review_count must not be negative")
        if not self.expected_seeds or len(set(self.expected_seeds)) != len(
            self.expected_seeds
        ):
            raise ValueError("expected_seeds must be non-empty and unique")
        if not 0.0 <= self.minimum_score_only_use_coverage <= 1.0:
            raise ValueError("minimum_score_only_use_coverage must be in [0, 1]")


def build_scheme_a_p2_p2_p0_audit(config: SchemeAP2P2P0AuditConfig) -> Path:
    dataset = _load_verified_run(
        config.dataset_run_root,
        "scheme_a_p2_p1_dataset_manifest.json",
        ("features", "labels", "compatibility_edges", "summary"),
        strict_hashes=config.strict_hashes,
    )
    oof_a = _load_verified_run(
        config.oof_run_root_a,
        "scheme_a_p2_p1_oof_manifest.json",
        ("scores", "selections", "effective_selections", "roadgraphs", "summary"),
        strict_hashes=config.strict_hashes,
    )
    oof_b = _load_verified_run(
        config.oof_run_root_b,
        "scheme_a_p2_p1_oof_manifest.json",
        ("scores", "selections", "effective_selections", "roadgraphs", "summary"),
        strict_hashes=config.strict_hashes,
    )
    determinism = _determinism_audit(oof_a, oof_b)
    if not all(determinism.values()):
        raise ValueError(f"P2-P1 A/B evidence differs: {determinism}")

    labels = _load_labels(dataset["paths"]["labels"])
    segment_labels = {
        group_id: row
        for group_id, row in labels.items()
        if row["object_type"] == "SEGMENT"
    }
    node_labels = {
        group_id: row
        for group_id, row in labels.items()
        if row["object_type"] == "NODE"
    }
    review_groups = {
        group_id
        for group_id, row in segment_labels.items()
        if row["carrier_target"] == "REVIEW_FALLBACK"
    }
    _require_count("Segment", len(segment_labels), config.expected_segment_count)
    _require_count("Node", len(node_labels), config.expected_node_count)
    _require_count("Review", len(review_groups), config.expected_review_count)

    feature_signatures, feature_audit = _segment_feature_signatures(
        dataset["paths"]["features"], segment_labels
    )
    score_stats = _segment_score_stats(
        oof_a["paths"]["scores"], segment_labels, config.expected_seeds
    )
    selections = _load_effective_selections(
        oof_a["paths"]["effective_selections"], labels, config.expected_seeds
    )
    terminals = _load_terminals(
        oof_a["paths"]["roadgraphs"], config.expected_seeds
    )
    if any(len(rows) != config.expected_case_count for rows in terminals.values()):
        raise ValueError("P2-P1 RoadGraph Case denominator differs")
    edges_by_choice, edges_by_node = _load_compatibility_edges(
        dataset["paths"]["compatibility_edges"], labels
    )

    signal_rows = _safety_signal_rows(
        segment_labels,
        feature_signatures,
        score_stats,
        selections,
        config.expected_seeds,
    )
    collision_audit = _feature_collision_audit(
        segment_labels, feature_signatures
    )
    error_chains, error_summary = _error_chain_audit(
        labels,
        selections,
        terminals,
        edges_by_choice,
        edges_by_node,
        feature_signatures,
        config.expected_seeds,
    )
    review_rows, review_summary = _review_audit(
        review_groups,
        selections,
        score_stats,
        config.expected_seeds,
    )
    separability = _score_separability(
        signal_rows,
        segment_labels,
        minimum_coverage=config.minimum_score_only_use_coverage,
    )
    closure = _effective_constraint_closure(
        selections,
        terminals,
        edges_by_choice,
        config.expected_seeds,
    )
    prior_summary = _read_json(oof_a["paths"]["summary"])
    _validate_prior_error_counts(prior_summary, error_summary, config.expected_seeds)

    unresolved_segment_roots = sum(
        1
        for row in error_chains
        if row["classification"] == "SEGMENT_ACCEPTED_ROOT_ERROR"
        and not row["feature_signature"]
    )
    if collision_audit["mixed_truth_signature_count"] > 0 or unresolved_segment_roots:
        decision = "P05_SCHEME_A_P2_P2_P0_EVIDENCE_NO_GO"
    elif separability["gate_pass"]:
        decision = "P05_SCHEME_A_P2_P2_P0_CALIBRATION_EVIDENCE_GO"
    else:
        decision = (
            "P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO"
        )

    summary = {
        "schema_version": "p05-scheme-a-p2-p2-p0-audit-summary-v1",
        "decision": decision,
        "analysis_complete": True,
        "case_count": config.expected_case_count,
        "segment_count": len(segment_labels),
        "node_count": len(node_labels),
        "review_count": len(review_groups),
        "seeds": list(config.expected_seeds),
        "determinism": determinism,
        "feature_audit": feature_audit,
        "feature_collision_audit": collision_audit,
        "error_summary": error_summary,
        "review_summary": review_summary,
        "score_separability": separability,
        "effective_constraint_closure": closure,
        "unclassified_error_count": 0,
        "movement_candidate_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }

    run_root = Path(config.output_root).resolve() / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)
    signals_path = run_root / "safety_signals.jsonl"
    errors_path = run_root / "error_chains.jsonl"
    review_path = run_root / "review_audit.jsonl"
    collisions_path = run_root / "feature_collision_audit.json"
    summary_path = run_root / "scheme_a_p2_p2_p0_audit_summary.json"
    report_path = run_root / "validation_report.md"
    _write_jsonl(signals_path, signal_rows)
    _write_jsonl(errors_path, error_chains)
    _write_jsonl(review_path, review_rows)
    write_json(collisions_path, collision_audit)
    write_json(summary_path, summary)
    report_path.write_text(_validation_report(summary), encoding="utf-8")
    outputs = {
        "safety_signals": output_record(signals_path),
        "error_chains": output_record(errors_path),
        "review_audit": output_record(review_path),
        "feature_collision_audit": output_record(collisions_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-scheme-a-p2-p2-p0-audit-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "audit_completed",
        "decision": decision,
        "inputs": {
            "dataset": _input_record(dataset),
            "oof_a": _input_record(oof_a),
            "oof_b": _input_record(oof_b),
        },
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "expected_segment_count": config.expected_segment_count,
            "expected_node_count": config.expected_node_count,
            "expected_review_count": config.expected_review_count,
            "expected_seeds": list(config.expected_seeds),
            "minimum_score_only_use_coverage": config.minimum_score_only_use_coverage,
        },
        "outputs": outputs,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    manifest_path = run_root / "scheme_a_p2_p2_p0_audit_manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p2-p0-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def _load_verified_run(
    root: Path,
    manifest_name: str,
    required_roles: Sequence[str],
    *,
    strict_hashes: bool,
) -> dict[str, Any]:
    resolved = Path(root).resolve()
    manifest_path = resolved / manifest_name
    manifest = _read_json(manifest_path)
    outputs = manifest.get("outputs") or {}
    paths: dict[str, Path] = {}
    for role in required_roles:
        record = outputs.get(role)
        if not isinstance(record, Mapping):
            raise ValueError(f"missing output role {role}: {manifest_path}")
        path = Path(str(record.get("path") or "")).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"artifact hash differs: {path}")
        paths[role] = path
    return {
        "root": resolved,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest": manifest,
        "paths": paths,
        "outputs": outputs,
    }


def _determinism_audit(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, bool]:
    result = {
        role: str(a["outputs"][role]["sha256"])
        == str(b["outputs"][role]["sha256"])
        for role in ("scores", "selections", "effective_selections")
    }
    result["roadgraphs"] = _roadgraph_index_signature(
        a["paths"]["roadgraphs"]
    ) == _roadgraph_index_signature(b["paths"]["roadgraphs"])
    return result


def _roadgraph_index_signature(path: Path) -> str:
    normalized: list[dict[str, Any]] = []
    for row in _read_jsonl(path):
        item = dict(row)
        output = dict(item.get("output") or {})
        output.pop("path", None)
        if output:
            item["output"] = output
        normalized.append(item)
    return canonical_sha256(
        sorted(normalized, key=lambda row: (int(row["seed"]), str(row["case_key"])))
    )


def _load_labels(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        group_id = str(row["group_id"])
        if group_id in result:
            raise ValueError(f"duplicate label group: {group_id}")
        result[group_id] = row
    return result


def _segment_feature_signatures(
    path: Path, labels: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, str], dict[str, Any]]:
    parts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    truth_hit_count = 0
    absolute_coordinate_hit_count = 0
    for row in _read_jsonl(path):
        if row.get("object_type") != "SEGMENT":
            continue
        group_id = str(row["group_id"])
        if group_id not in labels:
            raise ValueError(f"feature group has no Segment label: {group_id}")
        truth_hit_count += int(bool(row.get("feature_uses_truth")))
        absolute_coordinate_hit_count += int(
            int(row.get("absolute_coordinate_feature_count") or 0) != 0
        )
        parts[group_id].append(
            {
                "candidate_target": row["candidate_target"],
                "candidate_tokens": row["candidate_tokens"],
                "context_tokens": row["context_tokens"],
                "hard_unsafe": bool(row["hard_unsafe"]),
                "numeric_features": row["numeric_features"],
                "object_tokens": row["object_tokens"],
            }
        )
    if set(parts) != set(labels):
        raise ValueError("Segment feature/label denominator differs")
    if truth_hit_count or absolute_coordinate_hit_count:
        raise ValueError("truth or absolute coordinate leaked into safety features")
    signatures = {
        group_id: canonical_sha256(
            sorted(candidates, key=canonical_sha256)
        )
        for group_id, candidates in parts.items()
    }
    return signatures, {
        "truth_feature_hit_count": truth_hit_count,
        "absolute_coordinate_feature_hit_count": absolute_coordinate_hit_count,
        "identifier_feature_hit_count": 0,
        "feature_group_count": len(signatures),
    }


def _segment_score_stats(
    path: Path,
    labels: Mapping[str, Mapping[str, Any]],
    expected_seeds: Sequence[int],
) -> dict[tuple[int, str], dict[str, Any]]:
    rows_by_group: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        if row.get("object_type") != "SEGMENT":
            continue
        seed = int(row["seed"])
        group_id = str(row["group_id"])
        if seed not in expected_seeds or group_id not in labels:
            raise ValueError("unexpected Segment score seed/group")
        rows_by_group[(seed, group_id)].append(row)
    expected_keys = {
        (seed, group_id) for seed in expected_seeds for group_id in labels
    }
    if set(rows_by_group) != expected_keys:
        raise ValueError("Segment score denominator differs")
    result: dict[tuple[int, str], dict[str, Any]] = {}
    for key, rows in rows_by_group.items():
        ranked = sorted(
            rows,
            key=lambda row: (-float(row["probability"]), str(row["candidate_id"])),
        )
        probabilities = [float(row["probability"]) for row in ranked]
        result[key] = {
            "top_candidate_id": str(ranked[0]["candidate_id"]),
            "top_target": str(ranked[0]["candidate_target"]),
            "top_probability": probabilities[0],
            "margin": probabilities[0]
            - (probabilities[1] if len(probabilities) > 1 else 0.0),
            "entropy": -sum(
                probability * math.log(max(probability, 1e-15))
                for probability in probabilities
            ),
            "anomaly_probability": float(ranked[0]["anomaly_probability"]),
        }
    return result


def _load_effective_selections(
    path: Path,
    labels: Mapping[str, Mapping[str, Any]],
    expected_seeds: Sequence[int],
) -> dict[int, dict[str, dict[str, Any]]]:
    result: dict[int, dict[str, dict[str, Any]]] = {
        seed: {} for seed in expected_seeds
    }
    for row in _read_jsonl(path):
        seed = int(row["seed"])
        group_id = str(row["group_id"])
        if seed not in result or group_id not in labels:
            raise ValueError("unexpected effective selection seed/group")
        if group_id in result[seed]:
            raise ValueError(f"duplicate effective selection: {seed}/{group_id}")
        result[seed][group_id] = row
    for seed, rows in result.items():
        if set(rows) != set(labels):
            raise ValueError(f"effective selection denominator differs: {seed}")
    return result


def _load_terminals(
    path: Path, expected_seeds: Sequence[int]
) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {seed: {} for seed in expected_seeds}
    for row in _read_jsonl(path):
        seed = int(row["seed"])
        if seed not in result:
            raise ValueError(f"unexpected RoadGraph seed: {seed}")
        case_key = str(row["case_key"])
        result[seed][case_key] = str(row["terminal_state"])
    return result


def _load_compatibility_edges(
    path: Path, labels: Mapping[str, Mapping[str, Any]]
) -> tuple[
    dict[tuple[str, str], list[tuple[str, str]]],
    dict[str, list[tuple[str, str, str]]],
]:
    by_choice: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    by_node: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in _read_jsonl(path):
        segment_group = str(row["segment_group_id"])
        node_group = str(row["node_group_id"])
        if segment_group not in labels or node_group not in labels:
            raise ValueError("compatibility edge has unknown group")
        if bool(row.get("feature_uses_truth")):
            raise ValueError("compatibility edge must remain truth-free")
        candidate_id = str(row["segment_candidate_id"])
        target = str(row["required_node_target"])
        by_choice[(segment_group, candidate_id)].append((node_group, target))
        by_node[node_group].append((segment_group, candidate_id, target))
    return dict(by_choice), dict(by_node)


def _safety_signal_rows(
    labels: Mapping[str, Mapping[str, Any]],
    signatures: Mapping[str, str],
    score_stats: Mapping[tuple[int, str], Mapping[str, Any]],
    selections: Mapping[int, Mapping[str, Mapping[str, Any]]],
    seeds: Sequence[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_id in sorted(labels):
        per_seed: list[dict[str, Any]] = []
        for seed in seeds:
            score = score_stats[(seed, group_id)]
            selection = selections[seed][group_id]
            per_seed.append(
                {
                    "seed": seed,
                    **dict(score),
                    "accepted": bool(selection["accepted"]),
                    "effective_target": str(selection["effective_target"]),
                    "fallback_reason": str(selection["reason"]),
                }
            )
        targets = [str(row["top_target"]) for row in per_seed]
        rows.append(
            {
                "schema_version": "p05-scheme-a-p2-p2-p0-safety-signal-v1",
                "case_key": str(labels[group_id]["case_key"]),
                "group_id": group_id,
                "object_id": str(labels[group_id]["object_id"]),
                "object_type": "SEGMENT",
                "identifier_role": "lineage_only",
                "feature_uses_identifier": False,
                "feature_uses_truth": False,
                "signal_features": {
                    "feature_signature": signatures[group_id],
                    "all_seed_target_agreement": len(set(targets)) == 1,
                    "all_seed_use_rcsd": set(targets) == {"USE_RCSD"},
                    "minimum_top_probability": min(
                        float(row["top_probability"]) for row in per_seed
                    ),
                    "minimum_margin": min(float(row["margin"]) for row in per_seed),
                    "maximum_entropy": max(float(row["entropy"]) for row in per_seed),
                    "maximum_anomaly_probability": max(
                        float(row["anomaly_probability"]) for row in per_seed
                    ),
                    "per_seed": per_seed,
                },
            }
        )
    return rows


def _feature_collision_audit(
    labels: Mapping[str, Mapping[str, Any]], signatures: Mapping[str, str]
) -> dict[str, Any]:
    groups_by_signature: dict[str, list[str]] = defaultdict(list)
    for group_id, signature in signatures.items():
        groups_by_signature[signature].append(group_id)
    collisions: list[dict[str, Any]] = []
    for signature, group_ids in sorted(groups_by_signature.items()):
        targets = sorted({str(labels[group_id]["carrier_target"]) for group_id in group_ids})
        if len(targets) > 1:
            collisions.append(
                {
                    "feature_signature": signature,
                    "group_count": len(group_ids),
                    "truth_targets": targets,
                    "group_ids": sorted(group_ids),
                }
            )
    return {
        "unique_feature_signature_count": len(groups_by_signature),
        "mixed_truth_signature_count": len(collisions),
        "groups_in_mixed_truth_signatures": sum(
            int(row["group_count"]) for row in collisions
        ),
        "collisions": collisions,
    }


def _error_chain_audit(
    labels: Mapping[str, Mapping[str, Any]],
    selections: Mapping[int, Mapping[str, Mapping[str, Any]]],
    terminals: Mapping[int, Mapping[str, str]],
    edges_by_choice: Mapping[tuple[str, str], Sequence[tuple[str, str]]],
    edges_by_node: Mapping[str, Sequence[tuple[str, str, str]]],
    feature_signatures: Mapping[str, str],
    seeds: Sequence[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prior_counts: dict[int, int] = {}
    segment_root_counts: dict[int, int] = {}
    raw_segment_error_counts: dict[int, int] = {}
    false_use_counts: dict[int, int] = {}
    false_use_sets: list[set[str]] = []
    for seed in seeds:
        selected = selections[seed]
        raw_segment_errors = {
            group_id
            for group_id, row in selected.items()
            if row["object_type"] == "SEGMENT"
            and str(row["selected_candidate_id"])
            != str(labels[group_id]["truth_candidate_id"])
        }
        false_use = {
            group_id
            for group_id in raw_segment_errors
            if str(selected[group_id]["selected_target"]) == "USE_RCSD"
            and str(labels[group_id]["carrier_target"]) != "USE_RCSD"
        }
        false_use_sets.append(false_use)
        raw_segment_error_counts[seed] = len(raw_segment_errors)
        false_use_counts[seed] = len(false_use)
        seed_rows: list[dict[str, Any]] = []
        for group_id, selection in selected.items():
            label = labels[group_id]
            wrong = str(selection["selected_candidate_id"]) != str(
                label["truth_candidate_id"]
            )
            if not bool(selection["accepted"]) or not wrong:
                continue
            terminal = str(terminals[seed][str(selection["case_key"])])
            if selection["object_type"] == "SEGMENT":
                affected_nodes = {
                    node_group
                    for node_group, _ in edges_by_choice.get(
                        (group_id, str(selection["selected_candidate_id"])), ()
                    )
                }
                classification = "SEGMENT_ACCEPTED_ROOT_ERROR"
                contributors: list[dict[str, Any]] = []
            else:
                contributors = _wrong_segment_contributors(
                    group_id, selected, labels, edges_by_node
                )
                affected_nodes = set()
                if terminal != "LEGAL":
                    classification = "NODE_EXPECTED_FAILURE_NOT_PUBLISHED"
                elif any(bool(row["accepted"]) for row in contributors):
                    classification = "NODE_PROPAGATED_ACCEPTED_SEGMENT_ERROR"
                elif str(selection["effective_target"]) == str(
                    label["carrier_target"]
                ):
                    classification = "NODE_STRUCTURAL_FALLBACK_CORRECTED"
                elif contributors:
                    classification = "NODE_PROPAGATED_REJECTED_SEGMENT_SIGNAL"
                else:
                    classification = "NODE_INDEPENDENT_OR_UNREFERENCED_ERROR"
            seed_rows.append(
                {
                    "schema_version": "p05-scheme-a-p2-p2-p0-error-chain-v1",
                    "seed": seed,
                    "case_key": str(selection["case_key"]),
                    "group_id": group_id,
                    "object_id": str(selection["object_id"]),
                    "object_type": str(selection["object_type"]),
                    "truth_candidate_id": str(label["truth_candidate_id"]),
                    "truth_target": str(label["carrier_target"]),
                    "selected_candidate_id": str(selection["selected_candidate_id"]),
                    "selected_target": str(selection["selected_target"]),
                    "effective_candidate_id": str(selection["effective_candidate_id"]),
                    "effective_target": str(selection["effective_target"]),
                    "raw_selected_candidate_id": str(
                        selection.get("raw_selected_candidate_id") or ""
                    ),
                    "raw_selected_target": str(
                        selection.get("raw_selected_target") or ""
                    ),
                    "confidence": float(selection["confidence"]),
                    "anomaly_probability": float(selection["anomaly_probability"]),
                    "reason": str(selection["reason"]),
                    "terminal_state": terminal,
                    "published": terminal == "LEGAL",
                    "classification": classification,
                    "feature_signature": feature_signatures.get(group_id, ""),
                    "affected_node_group_count": len(affected_nodes),
                    "segment_contributors": contributors,
                }
            )
        prior_counts[seed] = len(seed_rows)
        segment_root_counts[seed] = sum(
            row["classification"] == "SEGMENT_ACCEPTED_ROOT_ERROR"
            for row in seed_rows
        )
        rows.extend(seed_rows)
    stable_false_use = sorted(set.intersection(*false_use_sets))
    return sorted(rows, key=lambda row: (int(row["seed"]), str(row["group_id"]))), {
        "prior_accepted_wrong_counts": _string_keyed(prior_counts),
        "raw_segment_error_counts": _string_keyed(raw_segment_error_counts),
        "accepted_segment_root_error_counts": _string_keyed(segment_root_counts),
        "false_use_prediction_counts": _string_keyed(false_use_counts),
        "stable_false_use_count": len(stable_false_use),
        "stable_false_use_group_ids": stable_false_use,
        "classification_counts": dict(
            sorted(Counter(str(row["classification"]) for row in rows).items())
        ),
    }


def _wrong_segment_contributors(
    node_group_id: str,
    selections: Mapping[str, Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
    edges_by_node: Mapping[str, Sequence[tuple[str, str, str]]],
) -> list[dict[str, Any]]:
    contributors: list[dict[str, Any]] = []
    for segment_group, candidate_id, required_target in edges_by_node.get(
        node_group_id, ()
    ):
        selection = selections.get(segment_group)
        if selection is None or str(selection["selected_candidate_id"]) != candidate_id:
            continue
        wrong = candidate_id != str(labels[segment_group]["truth_candidate_id"])
        if not wrong:
            continue
        contributors.append(
            {
                "segment_group_id": segment_group,
                "segment_truth_target": str(labels[segment_group]["carrier_target"]),
                "selected_target": str(selection["selected_target"]),
                "required_node_target": required_target,
                "accepted": bool(selection["accepted"]),
            }
        )
    return sorted(contributors, key=lambda row: str(row["segment_group_id"]))


def _review_audit(
    review_groups: set[str],
    selections: Mapping[int, Mapping[str, Mapping[str, Any]]],
    score_stats: Mapping[tuple[int, str], Mapping[str, Any]],
    seeds: Sequence[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prediction_counts: dict[str, dict[str, int]] = {}
    auto_publish_counts: dict[str, int] = {}
    for seed in seeds:
        counter: Counter[str] = Counter()
        auto_publish = 0
        for group_id in sorted(review_groups):
            selection = selections[seed][group_id]
            score = score_stats[(seed, group_id)]
            counter[str(selection["selected_target"])] += 1
            auto_publish += int(bool(selection["accepted"]))
            rows.append(
                {
                    "schema_version": "p05-scheme-a-p2-p2-p0-review-audit-v1",
                    "seed": seed,
                    "case_key": str(selection["case_key"]),
                    "group_id": group_id,
                    "object_id": str(selection["object_id"]),
                    "selected_target": str(selection["selected_target"]),
                    "effective_target": str(selection["effective_target"]),
                    "accepted": bool(selection["accepted"]),
                    "reason": str(selection["reason"]),
                    "top_probability": float(score["top_probability"]),
                    "margin": float(score["margin"]),
                    "entropy": float(score["entropy"]),
                    "anomaly_probability": float(score["anomaly_probability"]),
                }
            )
        prediction_counts[str(seed)] = dict(sorted(counter.items()))
        auto_publish_counts[str(seed)] = auto_publish
    return rows, {
        "prediction_counts": prediction_counts,
        "auto_publish_counts": auto_publish_counts,
    }


def _score_separability(
    signal_rows: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
    *,
    minimum_coverage: float,
) -> dict[str, Any]:
    by_group = {str(row["group_id"]): row for row in signal_rows}
    truth_use = [
        by_group[group_id]
        for group_id, label in labels.items()
        if label["carrier_target"] == "USE_RCSD"
    ]
    false_unanimous_use = [
        row
        for group_id, row in by_group.items()
        if labels[group_id]["carrier_target"] != "USE_RCSD"
        and bool(row["signal_features"]["all_seed_use_rcsd"])
    ]
    metrics = {
        "minimum_top_probability": _zero_error_upper_tail(
            truth_use, false_unanimous_use, "minimum_top_probability"
        ),
        "minimum_margin": _zero_error_upper_tail(
            truth_use, false_unanimous_use, "minimum_margin"
        ),
        "maximum_entropy": _zero_error_lower_tail(
            truth_use, false_unanimous_use, "maximum_entropy"
        ),
        "maximum_anomaly_probability": _zero_error_lower_tail(
            truth_use, false_unanimous_use, "maximum_anomaly_probability"
        ),
    }
    best_coverage = max(
        float(row["zero_error_use_coverage"]) for row in metrics.values()
    )
    return {
        "truth_use_count": len(truth_use),
        "false_unanimous_use_count": len(false_unanimous_use),
        "signals": metrics,
        "best_zero_error_use_coverage": best_coverage,
        "minimum_required_coverage": minimum_coverage,
        "gate_pass": best_coverage >= minimum_coverage,
    }


def _zero_error_upper_tail(
    truth_rows: Sequence[Mapping[str, Any]],
    false_rows: Sequence[Mapping[str, Any]],
    field: str,
) -> dict[str, Any]:
    threshold = max(
        (float(row["signal_features"][field]) for row in false_rows),
        default=float("-inf"),
    )
    accepted = sum(
        bool(row["signal_features"]["all_seed_use_rcsd"])
        and float(row["signal_features"][field]) > threshold
        for row in truth_rows
    )
    return {
        "direction": "greater_than",
        "strict_zero_error_threshold": threshold,
        "accepted_truth_use_count": accepted,
        "zero_error_use_coverage": accepted / max(1, len(truth_rows)),
    }


def _zero_error_lower_tail(
    truth_rows: Sequence[Mapping[str, Any]],
    false_rows: Sequence[Mapping[str, Any]],
    field: str,
) -> dict[str, Any]:
    threshold = min(
        (float(row["signal_features"][field]) for row in false_rows),
        default=float("inf"),
    )
    accepted = sum(
        bool(row["signal_features"]["all_seed_use_rcsd"])
        and float(row["signal_features"][field]) < threshold
        for row in truth_rows
    )
    return {
        "direction": "less_than",
        "strict_zero_error_threshold": threshold,
        "accepted_truth_use_count": accepted,
        "zero_error_use_coverage": accepted / max(1, len(truth_rows)),
    }


def _effective_constraint_closure(
    selections: Mapping[int, Mapping[str, Mapping[str, Any]]],
    terminals: Mapping[int, Mapping[str, str]],
    edges_by_choice: Mapping[tuple[str, str], Sequence[tuple[str, str]]],
    seeds: Sequence[int],
) -> dict[str, Any]:
    rows: dict[str, dict[str, int]] = {}
    for seed in seeds:
        requirements: dict[str, set[str]] = defaultdict(set)
        for group_id, selection in selections[seed].items():
            if selection["object_type"] != "SEGMENT":
                continue
            for node_group, target in edges_by_choice.get(
                (group_id, str(selection["effective_candidate_id"])), ()
            ):
                requirements[node_group].add(target)
        counts: Counter[str] = Counter()
        for node_group, targets in requirements.items():
            selection = selections[seed][node_group]
            terminal = terminals[seed][str(selection["case_key"])]
            if terminal != "LEGAL":
                counts["non_published_requirement_count"] += 1
                continue
            counts["published_requirement_count"] += 1
            if len(targets) != 1:
                counts["published_requirement_conflict_count"] += 1
            elif str(selection["effective_target"]) != next(iter(targets)):
                counts["published_effective_target_mismatch_count"] += 1
        rows[str(seed)] = dict(counts)
    return rows


def _validate_prior_error_counts(
    summary: Mapping[str, Any],
    error_summary: Mapping[str, Any],
    seeds: Sequence[int],
) -> None:
    expected = {
        str(int(row["seed"])): int(row["accepted_wrong_replacement_count"])
        for row in summary.get("seed_metrics") or []
    }
    actual = error_summary["prior_accepted_wrong_counts"]
    if expected != {str(seed): int(actual[str(seed)]) for seed in seeds}:
        raise ValueError(f"accepted wrong denominator differs: {expected} != {actual}")


def _validation_report(summary: Mapping[str, Any]) -> str:
    errors = summary["error_summary"]
    separability = summary["score_separability"]
    return "\n".join(
        (
            "# P05-Scheme-A-P2-P2-P0 审计报告",
            "",
            f"- decision: `{summary['decision']}`",
            f"- prior accepted wrong: `{errors['prior_accepted_wrong_counts']}`",
            f"- accepted Segment root errors: `{errors['accepted_segment_root_error_counts']}`",
            f"- stable false USE: `{errors['stable_false_use_count']}`",
            f"- best score-only zero-error USE coverage: `{separability['best_zero_error_use_coverage']:.6f}`",
            f"- mixed-truth feature collisions: `{summary['feature_collision_audit']['mixed_truth_signature_count']}`",
            f"- Review predictions: `{summary['review_summary']['prediction_counts']}`",
            "",
        )
    )


def _input_record(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(run["manifest_path"]),
        "sha256": str(run["manifest_sha256"]),
    }


def _require_count(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise ValueError(f"{name} denominator differs: {actual} != {expected}")


def _string_keyed(values: Mapping[int, int]) -> dict[str, int]:
    return {str(key): int(values[key]) for key in sorted(values)}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


__all__ = ["SchemeAP2P2P0AuditConfig", "build_scheme_a_p2_p2_p0_audit"]
