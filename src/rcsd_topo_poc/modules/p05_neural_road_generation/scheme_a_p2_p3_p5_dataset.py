from __future__ import annotations

import json
import time
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
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_models import (
    SCHEME_A_P2_P1_DATASET_SCHEMA,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_models import (
    DECISION_DATASET_GO,
    DECISION_DATASET_NO_GO,
    SCHEME_A_P2_P3_P5_DATASET_SCHEMA,
    SchemeAP2P3P5DatasetConfig,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def build_scheme_a_p2_p3_p5_dataset(
    config: SchemeAP2P3P5DatasetConfig,
) -> Path:
    started = time.perf_counter()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    source = _load_sources(config)
    segment_rows = list(_read_jsonl(source["paths"]["p4_segment_labels"]))
    node_rows = list(_read_jsonl(source["paths"]["p4_node_labels"]))
    labels, audit = build_scope_first_overlay_labels(segment_rows, node_rows)
    _validate_truth_candidates(labels, source["paths"]["features"])
    target_counts = Counter(
        str(row["carrier_target"])
        for row in labels
        if row["object_type"] == "SEGMENT"
    )
    gate = (
        audit["segment_count"] == config.expected_segment_count
        and audit["eligible_count"] == config.expected_eligible_count
        and audit["context_count"] == config.expected_context_count
        and audit["node_count"] == config.expected_node_count
        and audit["eligible_anomaly_count"] == config.expected_anomaly_count
        and target_counts == Counter(dict(config.expected_target_counts))
        and audit["context_supervision_count"] == 0
        and audit["duplicate_group_count"] == 0
        and audit["truth_candidate_missing_count"] == 0
    )
    decision = DECISION_DATASET_GO if gate else DECISION_DATASET_NO_GO

    label_path = run_root / "labels.jsonl"
    summary_path = run_root / "scheme_a_p2_p3_p5_dataset_summary.json"
    _write_jsonl(label_path, labels)
    deterministic_payload = {
        "lineage": source["lineage"],
        "labels": labels,
        "audit": audit,
        "target_counts": dict(sorted(target_counts.items())),
    }
    signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, signature)
    if reference_match is False:
        gate = False
        decision = DECISION_DATASET_NO_GO
    summary = {
        "schema_version": SCHEME_A_P2_P3_P5_DATASET_SCHEMA,
        "decision": decision,
        "gate_pass": gate,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "audit": audit,
        "target_counts": dict(sorted(target_counts.items())),
        "lineage": source["lineage"],
        "wall_seconds": time.perf_counter() - started,
        "candidate_layer_rebuilt": False,
        "feature_layer_rebuilt": False,
        "payload_layer_rebuilt": False,
        "compatibility_layer_rebuilt": False,
        "label_layer_rebuilt": True,
        "model_training_count": 0,
        "truth_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_decision_count": 0,
        "geometry_read_count": 0,
        "geometry_write_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(summary_path, summary)

    outputs = {
        key: _normalized_record(record)
        for key, record in source["historical_outputs"].items()
    }
    outputs["labels"] = output_record(label_path)
    outputs["summary"] = output_record(summary_path)
    loader_manifest_path = run_root / "scheme_a_p2_p1_dataset_manifest.json"
    loader_manifest = {
        "schema_version": "p05-scheme-a-p2-p1-dataset-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_passed" if gate else "dataset_failed",
        "decision": decision,
        "candidate_first": True,
        "determinism_signature": signature,
        "reference_run_match": reference_match,
        "input_manifests": source["input_manifests"],
        "outputs": outputs,
        "truth_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "context_supervision_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
    }
    write_json(loader_manifest_path, loader_manifest)

    p5_outputs = {
        "labels": output_record(label_path),
        "summary": output_record(summary_path),
        "loader_manifest": output_record(loader_manifest_path),
    }
    p5_manifest_path = run_root / "scheme_a_p2_p3_p5_dataset_manifest.json"
    write_json(
        p5_manifest_path,
        {
            "schema_version": SCHEME_A_P2_P3_P5_DATASET_SCHEMA,
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "status": "scope_first_dataset_completed",
            "decision": decision,
            "determinism_signature": signature,
            "reference_run_match": reference_match,
            "lineage": source["lineage"],
            "outputs": p5_outputs,
            "counts": audit,
            "candidate_layer_rebuilt": False,
            "label_layer_rebuilt": True,
            "context_supervision_count": 0,
            "model_training_count": 0,
            "geometry_read_count": 0,
            "geometry_write_count": 0,
            "skeleton_mutation_count": 0,
            "content_repair": False,
            "silent_fix": False,
        },
    )
    write_json(
        run_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p3-p5-dataset-artifacts-v1",
            "artifacts": [p5_outputs[key] for key in sorted(p5_outputs)]
            + [output_record(p5_manifest_path)],
        },
    )
    return run_root


def build_scope_first_overlay_labels(
    segment_rows: Sequence[Mapping[str, Any]],
    node_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    labels: list[dict[str, Any]] = []
    groups: set[str] = set()
    duplicate_count = 0
    eligible_count = context_count = eligible_anomaly_count = 0
    for row in sorted(segment_rows, key=lambda value: str(value["group_id"])):
        group_id = str(row["group_id"])
        if group_id in groups:
            duplicate_count += 1
        groups.add(group_id)
        eligible = bool(row["label_eligible"])
        eligible_count += int(eligible)
        context_count += int(not eligible)
        anomaly = (
            bool(row["effective_anomaly_target"]) if eligible else False
        )
        eligible_anomaly_count += int(eligible and anomaly)
        labels.append(
            {
                "schema_version": SCHEME_A_P2_P1_DATASET_SCHEMA,
                "case_key": str(row["case_key"]),
                "object_type": "SEGMENT",
                "object_id": str(row["object_id"]),
                "group_id": group_id,
                "junction_key": "",
                "truth_candidate_id": str(
                    row["effective_truth_candidate_id"]
                ),
                "carrier_target": str(row["effective_carrier_target"]),
                "available": bool(row["effective_available"]),
                "anomaly_target": anomaly,
                "label_weight": (
                    float(row["label_weight"]) if eligible else 0.3
                ),
                "weight_role": "TARGET" if eligible else "CONTEXT",
                "fold": int(row["fold"]),
                "label_only": True,
                "scope_first_label_eligible": eligible,
                "safe_materialization_only": not eligible,
            }
        )
    for row in sorted(node_rows, key=lambda value: str(value["group_id"])):
        group_id = str(row["group_id"])
        if group_id in groups:
            duplicate_count += 1
        groups.add(group_id)
        converted = dict(row)
        converted["schema_version"] = SCHEME_A_P2_P1_DATASET_SCHEMA
        converted["label_only"] = True
        converted["scope_first_node_truth"] = True
        labels.append(converted)
    labels.sort(key=lambda row: str(row["group_id"]))
    return labels, {
        "segment_count": len(segment_rows),
        "eligible_count": eligible_count,
        "context_count": context_count,
        "node_count": len(node_rows),
        "label_count": len(labels),
        "eligible_anomaly_count": eligible_anomaly_count,
        "context_supervision_count": 0,
        "duplicate_group_count": duplicate_count,
        "truth_candidate_missing_count": 0,
    }


def _load_sources(config: SchemeAP2P3P5DatasetConfig) -> dict[str, Any]:
    p4_root = normalize_runtime_path(config.p4_truth_root).resolve(strict=True)
    historical_root = normalize_runtime_path(
        config.historical_p2_p1_dataset_root
    ).resolve(strict=True)
    p4_manifest_path = p4_root / "scheme_a_p2_p3_p4_manifest.json"
    historical_manifest_path = (
        historical_root / "scheme_a_p2_p1_dataset_manifest.json"
    )
    p4_manifest = _read_json(p4_manifest_path)
    historical_manifest = _read_json(historical_manifest_path)
    if p4_manifest.get("decision") != (
        "P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_"
        "NO_RESIDUAL_REPRESENTATION_REQUIRED"
    ):
        raise ValueError("P4 truth source decision differs")
    if historical_manifest.get("status") != "dataset_passed":
        raise ValueError("historical P2-P1 dataset status differs")
    p4_outputs = dict(p4_manifest.get("outputs") or {})
    historical_outputs = dict(historical_manifest.get("outputs") or {})
    paths = {
        "p4_segment_labels": _verified_output(
            p4_outputs, "segment_labels", config.strict_hashes
        ),
        "p4_node_labels": _verified_output(
            p4_outputs, "node_labels", config.strict_hashes
        ),
        "features": _verified_output(
            historical_outputs, "features", config.strict_hashes
        ),
    }
    required_historical = (
        "features",
        "payloads",
        "groups",
        "compatibility_edges",
        "compatibility_oracle",
        "leakage_audit",
    )
    normalized_outputs = {
        key: output_record(
            _verified_output(
                historical_outputs,
                key,
                config.strict_hashes,
            )
        )
        for key in required_historical
    }
    lineage = {
        "p4_manifest_sha256": sha256_file(p4_manifest_path),
        "p4_segment_labels_sha256": sha256_file(paths["p4_segment_labels"]),
        "p4_node_labels_sha256": sha256_file(paths["p4_node_labels"]),
        "historical_dataset_manifest_sha256": sha256_file(
            historical_manifest_path
        ),
        **{
            f"historical_{key}_sha256": record["sha256"]
            for key, record in normalized_outputs.items()
        },
    }
    lineage["scope_first_dataset_lineage_signature"] = canonical_sha256(lineage)
    return {
        "paths": paths,
        "historical_outputs": normalized_outputs,
        "lineage": lineage,
        "input_manifests": {
            "p4_truth": output_record(p4_manifest_path),
            "historical_p2_p1_dataset": output_record(
                historical_manifest_path
            ),
        },
    }


def _validate_truth_candidates(
    labels: Sequence[Mapping[str, Any]],
    feature_path: Path,
) -> None:
    remaining = {
        (str(row["group_id"]), str(row["truth_candidate_id"]))
        for row in labels
    }
    if len(remaining) != len(labels):
        raise ValueError("scope-first truth pair is duplicated")
    for row in _read_jsonl(feature_path):
        remaining.discard(
            (str(row["group_id"]), str(row["candidate_id"]))
        )
    if remaining:
        sample = sorted(remaining)[:3]
        raise ValueError(f"scope-first truth candidate is missing: {sample}")


def _reference_match(
    root_value: Path | None,
    signature: str,
) -> bool | None:
    if root_value is None:
        return None
    root = normalize_runtime_path(root_value).resolve(strict=True)
    manifest = _read_json(root / "scheme_a_p2_p3_p5_dataset_manifest.json")
    return str(manifest.get("determinism_signature")) == signature


def _verified_output(
    outputs: Mapping[str, Any],
    key: str,
    strict_hashes: bool,
) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(
        strict=True
    )
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"source output hash mismatch: {key}")
    return path


def _normalized_record(record: Mapping[str, Any]) -> dict[str, Any]:
    path = normalize_runtime_path(str(record["path"])).resolve(strict=True)
    return output_record(path)


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "build_scheme_a_p2_p3_p5_dataset",
    "build_scope_first_overlay_labels",
]
