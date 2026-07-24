from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_training import (
    load_scheme_a_p2_p1_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    AUXILIARY_TARGET_NAMES,
    HierarchicalTrainingExample,
    SchemeAP2P3P0Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_AUXILIARY_ROLES = (
    "t01_segment",
    "t03_nodes",
    "t04_nodes",
    "t05_intersection_match_all",
)


def load_hierarchical_training_examples(
    config: SchemeAP2P3P0Config,
) -> tuple[list[HierarchicalTrainingExample], dict[str, Any]]:
    all_groups, dataset_metadata = load_scheme_a_p2_p1_groups(
        config.dataset_run_root, strict_hashes=config.strict_hashes
    )
    segment_groups = [group for group in all_groups if group.object_type == "SEGMENT"]
    evidence_by_id, evidence_metadata = _load_frozen_structural_evidence(config)
    group_by_id = {group.group_id: group for group in segment_groups}
    if set(group_by_id) != set(evidence_by_id):
        raise ValueError("candidate group and structural evidence scopes differ")
    if len(evidence_metadata["feature_names"]) != config.expected_evidence_dim:
        raise ValueError("structural evidence dimension differs from frozen contract")
    if any(len(values) != config.expected_evidence_dim for values in evidence_by_id.values()):
        raise ValueError("one or more structural evidence vectors differ")

    role_contract = _load_role_contract(config)
    auxiliary_by_id, auxiliary_rows, auxiliary_metadata = _load_auxiliary_labels(
        config,
        segment_groups,
        role_contract,
    )
    if set(auxiliary_by_id) != set(group_by_id):
        raise ValueError("auxiliary label and candidate group scopes differ")
    examples = [
        HierarchicalTrainingExample(
            group=group_by_id[group_id],
            evidence_features=evidence_by_id[group_id],
            auxiliary_targets=auxiliary_by_id[group_id],
        )
        for group_id in sorted(group_by_id)
    ]
    _validate_denominators(config, examples)
    lineage = {
        "p2_p1_dataset_manifest_sha256": dataset_metadata["dataset_manifest_sha256"],
        **evidence_metadata["lineage"],
        "p2_p2_p2_p0_manifest_sha256": _validated_manifest(
            config.p2_p2_p2_p0_run_root,
            "scheme_a_p2_p2_p2_p0_manifest.json",
            "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO",
        ),
        "p2_p2_p2_p2_manifest_sha256": _validated_manifest(
            config.p2_p2_p2_p2_run_root,
            "scheme_a_p2_p2_p2_p2_manifest.json",
            "P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO",
        ),
        "auxiliary_label_signature": auxiliary_metadata["auxiliary_label_signature"],
    }
    lineage["hierarchical_dataset_signature"] = canonical_sha256(lineage)
    clue_only_group_ids = _load_clue_only_group_ids(config)
    if len(clue_only_group_ids) != config.expected_clue_only_count:
        raise ValueError("known clue-only denominator differs from frozen audit")
    if not clue_only_group_ids <= set(group_by_id):
        raise ValueError("known clue-only object is absent from training scope")

    inference_feature_audit = {
        "feature_count": config.expected_evidence_dim,
        "candidate_numeric_dim": config.numeric_dim,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "t03_inference_feature_count": 0,
        "t04_inference_feature_count": 0,
        "t05_inference_feature_count": 0,
        "t06_inference_feature_count": 0,
        "label_only_auxiliary_target_count": len(AUXILIARY_TARGET_NAMES),
    }
    return examples, {
        "all_groups": all_groups,
        "segment_groups": segment_groups,
        "dataset": dataset_metadata,
        "case_folds": _case_folds(segment_groups),
        "evidence_metadata": evidence_metadata,
        "role_contract": role_contract,
        "auxiliary_label_rows": auxiliary_rows,
        "auxiliary_metadata": auxiliary_metadata,
        "clue_only_group_ids": sorted(clue_only_group_ids),
        "lineage": lineage,
        "inference_feature_audit": inference_feature_audit,
    }


def _load_frozen_structural_evidence(
    config: SchemeAP2P3P0Config,
) -> tuple[dict[str, tuple[float, ...]], dict[str, Any]]:
    root = normalize_runtime_path(config.p2_p2_p2_p0_run_root).resolve(strict=True)
    manifest_path = root / "scheme_a_p2_p2_p2_p0_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("decision") != "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO":
        raise ValueError("frozen structural evidence decision differs")
    outputs = dict(manifest.get("outputs") or {})
    evidence_record = dict(outputs.get("evidence") or {})
    contract_record = dict(outputs.get("evidence_contract") or {})
    evidence_path = normalize_runtime_path(str(evidence_record.get("path") or "")).resolve(
        strict=True
    )
    contract_path = normalize_runtime_path(str(contract_record.get("path") or "")).resolve(
        strict=True
    )
    if config.strict_hashes:
        if sha256_file(evidence_path) != str(evidence_record.get("sha256") or ""):
            raise ValueError("frozen structural evidence hash mismatch")
        if sha256_file(contract_path) != str(contract_record.get("sha256") or ""):
            raise ValueError("frozen structural evidence contract hash mismatch")
    contract = _read_json(contract_path)
    required_zero = (
        "truth_feature_count",
        "identifier_feature_count",
        "absolute_coordinate_feature_count",
        "movement_feature_count",
    )
    if any(int(contract.get(key) or 0) != 0 for key in required_zero):
        raise ValueError("forbidden feature reached frozen structural evidence")
    if set(contract.get("allowed_modules") or []) != {"T01", "T07"}:
        raise ValueError("frozen structural evidence module scope differs")
    if contract.get("t07_evidence_mode") != "DRIVEZONE_ONLY":
        raise ValueError("frozen structural evidence is not DriveZone-only")
    result: dict[str, tuple[float, ...]] = {}
    for row in _read_jsonl(evidence_path):
        group_id = str(row["group_id"])
        if (
            row.get("feature_uses_truth")
            or row.get("feature_uses_identifier")
            or int(row.get("absolute_coordinate_feature_count") or 0)
        ):
            raise ValueError(f"forbidden feature marker in frozen evidence: {group_id}")
        values = tuple(float(value) for value in row["features"])
        if group_id in result:
            raise ValueError(f"duplicate frozen evidence group: {group_id}")
        result[group_id] = values
    return result, {
        "feature_names": list(contract.get("feature_names") or []),
        "evidence_signature": str(contract.get("evidence_signature") or ""),
        "evidence_path": evidence_path,
        "evidence_sha256": sha256_file(evidence_path),
        "contract_path": contract_path,
        "contract_sha256": sha256_file(contract_path),
        "lineage": {
            "p2_p2_p2_p0_manifest_sha256": sha256_file(manifest_path),
            "p2_p2_p2_p0_evidence_sha256": sha256_file(evidence_path),
            "p2_p2_p2_p0_contract_sha256": sha256_file(contract_path),
        },
    }


def _load_role_contract(config: SchemeAP2P3P0Config) -> list[dict[str, Any]]:
    root = normalize_runtime_path(config.dataset_p0_root).resolve(strict=True)
    manifest = _read_json(root / "dataset_p0_manifest.json")
    if manifest.get("decision") != "P05_SCHEME_A_DATASET_P0_GO":
        raise ValueError("Dataset-P0 source-role gate did not pass")
    if (manifest.get("parameters") or {}).get("t07_evidence_mode") != "DRIVEZONE_ONLY":
        raise ValueError("Dataset-P0 is not DriveZone-only")
    path = root / "module_role_contract.json"
    return list(json.loads(path.read_text(encoding="utf-8")))


def _load_auxiliary_labels(
    config: SchemeAP2P3P0Config,
    segment_groups: Sequence[Any],
    role_contract: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, tuple[bool, ...]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    by_module = {str(row["module"]): dict(row) for row in role_contract}
    for module in ("T03", "T04", "T05"):
        row = by_module.get(module) or {}
        if row.get("model_input") or not row.get("label_only"):
            raise ValueError(f"{module} auxiliary source role differs from label-only contract")
    if not (by_module.get("T01") or {}).get("model_input"):
        raise ValueError("T01 frozen skeleton is not enabled as model input")

    root = normalize_runtime_path(config.dataset_p0_root).resolve(strict=True)
    manifest = _read_json(root / "dataset_p0_manifest.json")
    inventory_record = dict((manifest.get("outputs") or {}).get("module_artifact_inventory") or {})
    inventory_path = normalize_runtime_path(str(inventory_record.get("path") or "")).resolve(
        strict=True
    )
    if config.strict_hashes and sha256_file(inventory_path) != str(
        inventory_record.get("sha256") or ""
    ):
        raise ValueError("Dataset-P0 module artifact inventory hash mismatch")
    expected_cases = {group.case_key for group in segment_groups}
    artifacts: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            case_key = f"{row['family']}:{row['business_id']}"
            role = str(row["artifact_role"])
            if case_key not in expected_cases or role not in _AUXILIARY_ROLES:
                continue
            if row.get("hash_status") != "ok":
                raise ValueError(f"auxiliary artifact is not hash-clean: {case_key}/{role}")
            if role == "t01_segment":
                if row.get("module") != "T01" or row.get("model_input") != "True":
                    raise ValueError("T01 inventory source role differs")
            elif row.get("model_input") != "False" or row.get("label_only") != "True":
                raise ValueError(f"label-only inventory source was promoted: {case_key}/{role}")
            artifacts[case_key][role] = dict(row)
    if set(artifacts) != expected_cases or any(
        set(rows) != set(_AUXILIARY_ROLES) for rows in artifacts.values()
    ):
        raise ValueError("auxiliary artifact Case/role denominator differs")

    groups_by_case: dict[str, list[Any]] = defaultdict(list)
    for group in segment_groups:
        groups_by_case[group.case_key].append(group)
    result: dict[str, tuple[bool, ...]] = {}
    rows: list[dict[str, Any]] = []
    crs_counts: Counter[str] = Counter()
    verified_hash_count = 0
    for case_key in sorted(groups_by_case):
        case_artifacts = artifacts[case_key]
        resolved: dict[str, Path] = {}
        for role in _AUXILIARY_ROLES:
            record = case_artifacts[role]
            path = normalize_runtime_path(record["path"]).resolve(strict=True)
            if config.strict_hashes and sha256_file(path) != record["sha256"]:
                raise ValueError(f"auxiliary artifact hash mismatch: {case_key}/{role}")
            verified_hash_count += 1
            resolved[role] = path
        segments, segment_crs = _read_properties(resolved["t01_segment"], "id")
        t03_nodes, t03_crs = _read_properties(resolved["t03_nodes"], "id")
        t04_nodes, t04_crs = _read_properties(resolved["t04_nodes"], "id")
        relations, relation_crs = _read_properties(
            resolved["t05_intersection_match_all"], "target_id"
        )
        for label, value in (
            ("t01_segment", segment_crs),
            ("t03_nodes", t03_crs),
            ("t04_nodes", t04_crs),
            ("t05_intersection_match_all", relation_crs),
        ):
            crs_counts[f"{label}:{value}"] += 1
        for group in groups_by_case[case_key]:
            segment = segments.get(str(group.object_id))
            if segment is None:
                raise ValueError(f"T01 Segment missing for auxiliary join: {group.group_id}")
            required_nodes = _csv_values(segment.get("pair_nodes")) | _csv_values(
                segment.get("junc_nodes")
            )
            t03_anchor = {
                node_id: _text((t03_nodes.get(node_id) or {}).get("is_anchor")).lower()
                for node_id in required_nodes
            }
            t04_anchor = {
                node_id: _text((t04_nodes.get(node_id) or {}).get("is_anchor")).lower()
                for node_id in required_nodes
            }
            relation_success = {
                node_id: _relation_success(relations.get(node_id)) for node_id in required_nodes
            }
            targets = (
                any(
                    _text((t03_nodes.get(node_id) or {}).get("has_evd")).lower() == "yes"
                    for node_id in required_nodes
                ),
                any(value == "yes" for value in t03_anchor.values()),
                any(value == "fail3" for value in t03_anchor.values()),
                any(
                    t03_anchor[node_id] != "yes"
                    and t04_anchor[node_id] in {"yes", "fail4_fallback"}
                    for node_id in required_nodes
                ),
                any(value == "fail4" for value in t04_anchor.values()),
                any(relation_success.values()),
                bool(required_nodes) and all(relation_success.values()),
            )
            if group.group_id in result:
                raise ValueError(f"duplicate auxiliary label group: {group.group_id}")
            result[group.group_id] = targets
            rows.append(
                {
                    "case_key": group.case_key,
                    "group_id": group.group_id,
                    "object_id": group.object_id,
                    "fold": group.fold,
                    "required_node_count": len(required_nodes),
                    "target_names": list(AUXILIARY_TARGET_NAMES),
                    "targets": [bool(value) for value in targets],
                    "source_modules": ["T03", "T04", "T05"],
                    "label_only": True,
                    "model_input": False,
                    "feature_uses_truth": False,
                    "feature_uses_identifier": False,
                    "absolute_coordinate_feature_count": 0,
                }
            )
    positive_counts = {
        name: sum(row["targets"][index] for row in rows)
        for index, name in enumerate(AUXILIARY_TARGET_NAMES)
    }
    if any(count <= 0 or count >= len(rows) for count in positive_counts.values()):
        raise ValueError("one or more auxiliary targets lack positive/negative examples")
    signature = canonical_sha256(
        {
            "target_names": AUXILIARY_TARGET_NAMES,
            "rows": rows,
            "inventory_sha256": sha256_file(inventory_path),
        }
    )
    return result, rows, {
        "target_names": list(AUXILIARY_TARGET_NAMES),
        "positive_counts": positive_counts,
        "negative_counts": {
            name: len(rows) - count for name, count in positive_counts.items()
        },
        "verified_artifact_hash_count": verified_hash_count,
        "crs_counts": dict(sorted(crs_counts.items())),
        "coordinate_transform_performed": False,
        "geometry_modified": False,
        "auxiliary_label_signature": signature,
        "inventory_path": inventory_path,
        "inventory_sha256": sha256_file(inventory_path),
    }


def _read_properties(path: Path, key: str) -> tuple[dict[str, dict[str, Any]], str]:
    result: dict[str, dict[str, Any]] = {}
    with fiona.open(path) as source:
        crs = source.crs.to_string() if source.crs else ""
        for feature in source:
            properties = dict(feature.get("properties") or {})
            object_id = _text(properties.get(key))
            if not object_id:
                continue
            if object_id in result:
                raise ValueError(f"duplicate {key} in auxiliary artifact: {path}/{object_id}")
            result[object_id] = properties
    return result, crs


def _relation_success(relation: Mapping[str, Any] | None) -> bool:
    if relation is None:
        return False
    status = relation.get("status")
    return int(status if status is not None else 1) == 0 and int(
        relation.get("base_id") or 0
    ) > 0


def _validate_denominators(
    config: SchemeAP2P3P0Config, examples: Sequence[HierarchicalTrainingExample]
) -> None:
    if len(examples) != config.expected_segment_group_count:
        raise ValueError("hierarchical Segment denominator differs")
    case_folds: dict[str, int] = {}
    for example in examples:
        group = example.group
        previous = case_folds.setdefault(group.case_key, group.fold)
        if previous != group.fold:
            raise ValueError("one Case spans multiple held-out folds")
        if len(group.candidates) < 2:
            raise ValueError("carrier candidate group lacks fallback choice")
        if group.candidates[group.truth_index].candidate_target != group.truth_target:
            raise ValueError("truth candidate target differs")
        if any(not math.isfinite(value) for value in example.evidence_features):
            raise ValueError("non-finite hierarchical evidence")
    if len(case_folds) != config.expected_case_count:
        raise ValueError("hierarchical Case denominator differs")
    if set(case_folds.values()) != set(range(config.expected_fold_count)):
        raise ValueError("hierarchical fold denominator differs")
    if sum(example.group.truth_target == "REVIEW_FALLBACK" for example in examples) != (
        config.expected_review_count
    ):
        raise ValueError("hierarchical Review denominator differs")


def _load_clue_only_group_ids(config: SchemeAP2P3P0Config) -> set[str]:
    root = normalize_runtime_path(config.p2_p2_p2_p2_run_root).resolve(strict=True)
    path = root / "object_source_routes.jsonl"
    result = {
        str(row["group_id"])
        for row in _read_jsonl(path)
        if row.get("business_class") == "CLUE_MISS_ONLY"
    }
    return result


def _validated_manifest(root_value: Path, filename: str, expected_decision: str) -> str:
    root = normalize_runtime_path(root_value).resolve(strict=True)
    path = root / filename
    manifest = _read_json(path)
    if manifest.get("decision") != expected_decision:
        raise ValueError(f"frozen input decision differs: {filename}")
    return sha256_file(path)


def _case_folds(groups: Sequence[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for group in groups:
        previous = result.setdefault(group.case_key, group.fold)
        if previous != group.fold:
            raise ValueError("one Case spans multiple folds")
    return result


def _csv_values(value: Any) -> set[str]:
    return {item.strip() for item in _text(value).split(",") if item.strip()}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = ["load_hierarchical_training_examples"]
