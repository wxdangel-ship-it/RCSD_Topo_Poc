from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_dataset import (
    load_segment_safety_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_models import (
    SchemeAP2P2P1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_models import (
    SafetyEvidenceExample,
    SchemeAP2P2P2P0Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


BASE_FEATURE_NAMES = tuple(f"base_numeric_{index:02d}" for index in range(21))
KEEP_FEATURE_NAMES = tuple(f"keep_numeric_{index:02d}" for index in range(8))
DELTA_FEATURE_NAMES = tuple(f"proposal_minus_keep_{index:02d}" for index in range(8))
PAYLOAD_FEATURE_NAMES = (
    "payload_added_log_count",
    "payload_removed_log_count",
    "payload_symmetric_difference_log_count",
    "payload_intersection_log_count",
    "payload_jaccard",
    "payload_exact_match",
)
ROAD_STAT_NAMES = (
    "road_log_count",
    "node_log_count",
    "component_log_count",
    "max_degree_log",
    "boundary_node_share",
    "branch_node_share",
    "self_loop_share",
    "duplicate_edge_share",
    "degree_imbalance_share",
    "reciprocal_edge_share",
)
COMPAT_STAT_NAMES = (
    "edge_log_count",
    "node_log_count",
    "t01_target_share",
    "proposal_target_share",
    "shared_node_share",
    "max_segment_fanout_log",
    "opposite_target_exposure_share",
    "multi_target_node_share",
)
T07_FEATURE_NAMES = (
    "t07_anchor_log_count",
    "t07_evidence_log_count",
    "proposal_anchor_endpoint_share",
    "keep_anchor_endpoint_share",
    "proposal_evidence_endpoint_share",
    "keep_evidence_endpoint_share",
    "anchor_share_delta",
    "evidence_share_delta",
)


def load_safety_evidence(
    config: SchemeAP2P2P2P0Config,
) -> tuple[list[SafetyEvidenceExample], dict[str, Any]]:
    groups, base = load_segment_safety_groups(_base_config(config))
    lineage = _validate_lineage(config, base)
    role_contract, t07_by_case = _load_allowed_t07(config, {group.case_key for group in groups})
    payload_rows = _load_payload_rows(base["dataset"]["dataset_manifest"], config.strict_hashes)
    compatibility = _compatibility_index(base["dataset"]["compatibility_edges"])

    prepared: list[dict[str, Any]] = []
    token_vocabulary: set[str] = set()
    road_cache: dict[str, dict[str, dict[str, Any]]] = {}
    verified_artifacts: set[tuple[str, str]] = set()
    for group in groups:
        proposal = base["proposals"][group.group_id]
        candidate_by_id = {candidate.candidate_id: candidate for candidate in group.candidates}
        keep = _single_target(group.candidates, "KEEP_SWSD")
        proposal_candidate = candidate_by_id.get(str(proposal.get("candidate_id") or ""), keep)
        proposal_payload = payload_rows[(group.group_id, proposal_candidate.candidate_id)]
        keep_payload = payload_rows[(group.group_id, keep.candidate_id)]
        proposal_graph = _candidate_road_graph(
            proposal_payload,
            road_cache=road_cache,
            verified_artifacts=verified_artifacts,
            strict_hashes=config.strict_hashes,
        )
        keep_graph = _candidate_road_graph(
            keep_payload,
            road_cache=road_cache,
            verified_artifacts=verified_artifacts,
            strict_hashes=config.strict_hashes,
        )
        tokens = set(group.object_tokens) | set(group.context_tokens) | set(
            proposal_candidate.candidate_tokens
        )
        token_vocabulary.update(tokens)
        prepared.append(
            {
                "group": group,
                "proposal": proposal,
                "proposal_candidate": proposal_candidate,
                "keep": keep,
                "proposal_payload": proposal_payload,
                "keep_payload": keep_payload,
                "proposal_graph": proposal_graph,
                "keep_graph": keep_graph,
                "tokens": tokens,
            }
        )

    token_names = tuple(f"TOKEN:{token}" for token in sorted(token_vocabulary))
    feature_names = (
        BASE_FEATURE_NAMES
        + KEEP_FEATURE_NAMES
        + DELTA_FEATURE_NAMES
        + PAYLOAD_FEATURE_NAMES
        + tuple(f"proposal_{name}" for name in ROAD_STAT_NAMES)
        + tuple(f"keep_{name}" for name in ROAD_STAT_NAMES)
        + tuple(f"road_delta_{name}" for name in ROAD_STAT_NAMES)
        + tuple(f"proposal_compat_{name}" for name in COMPAT_STAT_NAMES)
        + tuple(f"keep_compat_{name}" for name in COMPAT_STAT_NAMES)
        + tuple(f"compat_delta_{name}" for name in COMPAT_STAT_NAMES)
        + T07_FEATURE_NAMES
        + token_names
    )
    token_index = {name.removeprefix("TOKEN:"): index for index, name in enumerate(token_names)}
    examples: list[SafetyEvidenceExample] = []
    feature_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    for item in prepared:
        group = item["group"]
        proposal = item["proposal"]
        proposal_candidate = item["proposal_candidate"]
        keep = item["keep"]
        proposal_graph = item["proposal_graph"]
        keep_graph = item["keep_graph"]
        proposal_ids = set(str(value) for value in item["proposal_payload"]["target_payload"])
        keep_ids = set(str(value) for value in item["keep_payload"]["target_payload"])
        proposal_compat = _compatibility_stats(
            compatibility, group.group_id, proposal_candidate.candidate_id
        )
        keep_compat = _compatibility_stats(compatibility, group.group_id, keep.candidate_id)
        t07 = t07_by_case[group.case_key]
        values = (
            tuple(float(value) for value in proposal_candidate.numeric_features)
            + tuple(float(value) for value in keep.numeric_features[:8])
            + tuple(
                float(left) - float(right)
                for left, right in zip(
                    proposal_candidate.numeric_features[:8], keep.numeric_features[:8], strict=True
                )
            )
            + _payload_stats(proposal_ids, keep_ids)
            + proposal_graph["stats"]
            + keep_graph["stats"]
            + _delta(proposal_graph["stats"], keep_graph["stats"])
            + proposal_compat
            + keep_compat
            + _delta(proposal_compat, keep_compat)
            + _t07_stats(t07, proposal_graph["nodes"], keep_graph["nodes"])
            + tuple(float(token in item["tokens"]) for token in sorted(token_index))
        )
        if len(values) != len(feature_names) or any(not math.isfinite(value) for value in values):
            raise ValueError(f"invalid evidence vector: {group.group_id}")
        truth_candidate = group.candidates[group.truth_index]
        proposal_id = str(proposal.get("candidate_id") or "")
        example = SafetyEvidenceExample(
            case_key=group.case_key,
            fold=group.fold,
            group_id=group.group_id,
            object_id=group.object_id,
            proposal_candidate_id=proposal_id,
            proposal_target=str(proposal.get("candidate_target") or ""),
            truth_candidate_id=truth_candidate.candidate_id,
            truth_target=group.truth_target,
            features=values,
            candidate_agreement=bool(proposal_id),
            hard_unsafe=group.hard_unsafe,
            proposal_correct=proposal_id == truth_candidate.candidate_id,
            anomaly_target=group.anomaly_target,
            review_target=group.truth_target == "REVIEW_FALLBACK",
        )
        examples.append(example)
        feature_rows.append(
            {
                "case_key": group.case_key,
                "group_id": group.group_id,
                "object_id": group.object_id,
                "proposal_candidate_id": proposal_id,
                "proposal_target": example.proposal_target,
                "fold": group.fold,
                "features": list(values),
                "feature_uses_truth": False,
                "feature_uses_identifier": False,
                "absolute_coordinate_feature_count": 0,
                "identifier_role": "lineage_only",
            }
        )
        label_rows.append(
            {
                "case_key": group.case_key,
                "group_id": group.group_id,
                "truth_candidate_id": truth_candidate.candidate_id,
                "truth_target": group.truth_target,
                "proposal_correct": example.proposal_correct,
                "anomaly_target": group.anomaly_target,
                "review_target": example.review_target,
                "unsafe": example.unsafe,
                "label_only": True,
            }
        )

    wrong = [example for example in examples if example.candidate_agreement and not example.proposal_correct]
    review = [example for example in examples if example.review_target]
    if len(examples) != config.expected_segment_group_count:
        raise ValueError("Segment evidence denominator differs")
    if len(wrong) != config.expected_agreed_wrong_count:
        raise ValueError("agreed wrong proposal denominator differs")
    if len(review) != config.expected_review_count:
        raise ValueError("Review evidence denominator differs")
    if len({example.case_key for example in examples}) != config.expected_case_count:
        raise ValueError("Case evidence denominator differs")
    evidence_signature = canonical_sha256(
        {"feature_names": feature_names, "rows": feature_rows, "lineage": lineage}
    )
    metadata = {
        "all_groups": base["all_groups"],
        "dataset": base["dataset"],
        "oof_a": base["oof_a"],
        "case_folds": base["case_folds"],
        "proposals": base["proposals"],
        "stable_false_use_group_ids": base["stable_false_use_group_ids"],
        "agreed_wrong_group_ids": sorted(example.group_id for example in wrong),
        "feature_names": feature_names,
        "feature_rows": feature_rows,
        "label_rows": label_rows,
        "role_contract": role_contract,
        "lineage": lineage,
        "evidence_signature": evidence_signature,
        "verified_road_artifact_count": len(verified_artifacts),
        "t07_case_count": len(t07_by_case),
    }
    return examples, metadata


def _base_config(config: SchemeAP2P2P2P0Config) -> SchemeAP2P2P1Config:
    return SchemeAP2P2P1Config(
        dataset_run_root=config.dataset_run_root,
        base_oof_run_a=config.base_oof_run_a,
        base_oof_run_b=config.base_oof_run_b,
        p2_p2_p0_run_root=config.p2_p2_p0_run_root,
        output_root=config.output_root,
        run_id="p2_p2_p2_p0_read_only",
        base_seeds=config.base_seeds,
        expected_case_count=config.expected_case_count,
        expected_fold_count=config.expected_fold_count,
        expected_segment_group_count=config.expected_segment_group_count,
        expected_review_count=config.expected_review_count,
        expected_stable_false_use_count=config.expected_stable_false_use_count,
        strict_hashes=config.strict_hashes,
    )


def _validate_lineage(config: SchemeAP2P2P2P0Config, base: Mapping[str, Any]) -> dict[str, Any]:
    records: dict[str, Any] = {
        "p2_p1_dataset": base["dataset"]["dataset_manifest_sha256"],
        "base_oof_a": base["oof_a"]["manifest_sha256"],
    }
    p1_signatures: list[str] = []
    for role, root_value in (
        ("p2_p2_p1_run_a", config.p2_p2_p1_run_a),
        ("p2_p2_p1_run_b", config.p2_p2_p1_run_b),
    ):
        root = normalize_runtime_path(root_value).resolve(strict=True)
        path = root / "scheme_a_p2_p2_p1_manifest.json"
        manifest = _read_json(path)
        if manifest.get("decision") != "P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO":
            raise ValueError(f"{role} does not have the frozen MODEL_NO_GO status")
        p1_signatures.append(str(manifest.get("determinism_signature") or ""))
        records[role] = sha256_file(path)
    if not p1_signatures[0] or len(set(p1_signatures)) != 1:
        raise ValueError("P2-P2-P1 Run A/B determinism signature differs")
    records["p2_p2_p1_determinism_signature"] = p1_signatures[0]
    records["p2_p2_p0"] = base["lineage"]["p2_p2_p0_manifest_sha256"]
    return records


def _load_allowed_t07(
    config: SchemeAP2P2P2P0Config, expected_cases: set[str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, set[str]]]]:
    root = normalize_runtime_path(config.dataset_p0_root).resolve(strict=True)
    manifest_path = root / "dataset_p0_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("decision") != "P05_SCHEME_A_DATASET_P0_GO":
        raise ValueError("Dataset-P0 source-role gate did not pass")
    if (manifest.get("parameters") or {}).get("t07_evidence_mode") != "DRIVEZONE_ONLY":
        raise ValueError("T07 evidence mode is not DRIVEZONE_ONLY")
    role_path = root / "module_role_contract.json"
    roles = json.loads(role_path.read_text(encoding="utf-8"))
    by_module = {str(row["module"]): row for row in roles}
    if not by_module["T01"].get("model_input") or not by_module["T07"].get("model_input"):
        raise ValueError("T01/T07 model-input contract is not enabled")
    if any(by_module[module].get("model_input") for module in ("T03", "T04", "T05", "T06")):
        raise ValueError("label-only module was promoted to model input")
    output = dict(manifest.get("outputs") or {}).get("module_artifact_inventory") or {}
    inventory_path = normalize_runtime_path(str(output.get("path") or "")).resolve(strict=True)
    if config.strict_hashes and sha256_file(inventory_path) != str(output.get("sha256") or ""):
        raise ValueError("Dataset-P0 artifact inventory hash mismatch")
    result: dict[str, dict[str, set[str]]] = {}
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("artifact_role") != "t07_nodes":
                continue
            case_key = f"{row['family']}:{row['business_id']}"
            if case_key not in expected_cases:
                continue
            if row.get("module") != "T07" or row.get("model_input") != "True":
                raise ValueError("T07 inventory role differs from source contract")
            path = normalize_runtime_path(row["path"]).resolve(strict=True)
            if config.strict_hashes and sha256_file(path) != row["sha256"]:
                raise ValueError(f"T07 artifact hash mismatch: {case_key}")
            anchor: set[str] = set()
            evidence: set[str] = set()
            with fiona.open(path) as source:
                for feature in source:
                    properties = dict(feature.get("properties") or {})
                    node_id = _property_text(properties, "id")
                    if not node_id:
                        continue
                    if _yes(_property_text(properties, "is_anchor")):
                        anchor.add(node_id)
                    if _yes(_property_text(properties, "has_evd")):
                        evidence.add(node_id)
            result[case_key] = {"anchor": anchor, "evidence": evidence}
    if set(result) != expected_cases:
        raise ValueError("T07 Case denominator differs from frozen Segment scope")
    return roles, result


def _load_payload_rows(
    dataset_manifest: Mapping[str, Any], strict_hashes: bool
) -> dict[tuple[str, str], dict[str, Any]]:
    output = dict(dataset_manifest.get("outputs") or {}).get("payloads") or {}
    path = normalize_runtime_path(str(output.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(output.get("sha256") or ""):
        raise ValueError("P2-P1 candidate payload hash mismatch")
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(path):
        if row.get("object_type") != "SEGMENT":
            continue
        key = str(row["group_id"]), str(row["candidate_id"])
        if key in rows:
            raise ValueError(f"duplicate Segment payload: {key}")
        rows[key] = row
    return rows


def _candidate_road_graph(
    payload: Mapping[str, Any],
    *,
    road_cache: dict[str, dict[str, dict[str, Any]]],
    verified_artifacts: set[tuple[str, str]],
    strict_hashes: bool,
) -> dict[str, Any]:
    artifact_by_id = {
        str(row[0]): (str(row[1]), str(row[2]), str(row[3]))
        for row in payload.get("payload_artifact_by_id") or []
    }
    edges: list[tuple[str, str]] = []
    for road_id in (str(value) for value in payload.get("target_payload") or []):
        artifact = artifact_by_id.get(road_id)
        if artifact is None:
            continue
        _role, raw_path, expected_hash = artifact
        path = normalize_runtime_path(raw_path).resolve(strict=True)
        key = str(path)
        verification = (key, expected_hash)
        if verification not in verified_artifacts:
            if strict_hashes and sha256_file(path) != expected_hash:
                raise ValueError(f"candidate road artifact hash mismatch: {path}")
            verified_artifacts.add(verification)
        if key not in road_cache:
            road_cache[key] = _read_road_endpoint_properties(path)
        properties = road_cache[key].get(road_id)
        if properties is None:
            raise ValueError(f"candidate Road payload missing from artifact: {road_id}")
        start = _property_text(properties, "snodeid")
        end = _property_text(properties, "enodeid")
        if start and end:
            edges.append((start, end))
    return _road_stats(edges)


def _read_road_endpoint_properties(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(str(path)) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name"
            )
        ]
        selected: tuple[str, dict[str, str]] | None = None
        for table in tables:
            quoted_table = table.replace('"', '""')
            columns = {
                str(row[1]).lower(): str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{quoted_table}")')
            }
            if {"id", "snodeid", "enodeid"} <= set(columns):
                selected = table, columns
                break
        if selected is None:
            raise ValueError(f"Road GPKG has no id/snodeid/enodeid feature table: {path}")
        table, columns = selected
        quoted_table = table.replace('"', '""')
        names = [columns[key].replace('"', '""') for key in ("id", "snodeid", "enodeid")]
        query = f'SELECT "{names[0]}", "{names[1]}", "{names[2]}" FROM "{quoted_table}"'
        for road_id, start, end in connection.execute(query):
            if road_id in (None, ""):
                continue
            records[str(road_id)] = {"snodeid": start, "enodeid": end}
    return records


def _road_stats(edges: Sequence[tuple[str, str]]) -> dict[str, Any]:
    nodes = {value for edge in edges for value in edge}
    undirected: dict[str, set[str]] = defaultdict(set)
    indegree: Counter[str] = Counter()
    outdegree: Counter[str] = Counter()
    for start, end in edges:
        undirected[start].add(end)
        undirected[end].add(start)
        outdegree[start] += 1
        indegree[end] += 1
    components = _component_count(nodes, undirected)
    degree = {node: len(undirected[node]) for node in nodes}
    edge_counter = Counter(edges)
    reciprocal = sum((end, start) in edge_counter for start, end in edge_counter)
    stats = (
        math.log1p(len(edges)),
        math.log1p(len(nodes)),
        math.log1p(components),
        math.log1p(max(degree.values(), default=0)),
        sum(value == 1 for value in degree.values()) / max(1, len(nodes)),
        sum(value > 2 for value in degree.values()) / max(1, len(nodes)),
        sum(start == end for start, end in edges) / max(1, len(edges)),
        sum(value - 1 for value in edge_counter.values()) / max(1, len(edges)),
        sum(indegree[node] != outdegree[node] for node in nodes) / max(1, len(nodes)),
        reciprocal / max(1, len(edge_counter)),
    )
    return {"stats": stats, "nodes": nodes}


def _compatibility_index(edges: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_choice: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    node_segments: dict[str, set[str]] = defaultdict(set)
    node_targets: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        group_id = str(edge["segment_group_id"])
        candidate_id = str(edge["segment_candidate_id"])
        node_id = str(edge["node_group_id"])
        target = str(edge["required_node_target"])
        by_choice[(group_id, candidate_id)].add((node_id, target))
        node_segments[node_id].add(group_id)
        node_targets[node_id].add(target)
    return {
        "by_choice": dict(by_choice),
        "node_segments": dict(node_segments),
        "node_targets": dict(node_targets),
    }


def _compatibility_stats(index: Mapping[str, Any], group_id: str, candidate_id: str) -> tuple[float, ...]:
    relations = set(index["by_choice"].get((group_id, candidate_id), set()))
    nodes = {node for node, _target in relations}
    count = len(relations)
    shared = sum(len(index["node_segments"].get(node, set())) > 1 for node in nodes)
    opposite = sum(len(index["node_targets"].get(node, set())) > 1 for node in nodes)
    return (
        math.log1p(count),
        math.log1p(len(nodes)),
        sum(target == "T01_NODE" for _node, target in relations) / max(1, count),
        sum(target == "PROPOSAL_NODE" for _node, target in relations) / max(1, count),
        shared / max(1, len(nodes)),
        math.log1p(max((len(index["node_segments"].get(node, set())) for node in nodes), default=0)),
        opposite / max(1, len(nodes)),
        opposite / max(1, len(nodes)),
    )


def _payload_stats(proposal: set[str], keep: set[str]) -> tuple[float, ...]:
    union = proposal | keep
    intersection = proposal & keep
    return (
        math.log1p(len(proposal - keep)),
        math.log1p(len(keep - proposal)),
        math.log1p(len(proposal ^ keep)),
        math.log1p(len(intersection)),
        len(intersection) / max(1, len(union)),
        float(proposal == keep),
    )


def _t07_stats(
    t07: Mapping[str, set[str]], proposal_nodes: set[str], keep_nodes: set[str]
) -> tuple[float, ...]:
    proposal_anchor = len(proposal_nodes & t07["anchor"]) / max(1, len(proposal_nodes))
    keep_anchor = len(keep_nodes & t07["anchor"]) / max(1, len(keep_nodes))
    proposal_evidence = len(proposal_nodes & t07["evidence"]) / max(1, len(proposal_nodes))
    keep_evidence = len(keep_nodes & t07["evidence"]) / max(1, len(keep_nodes))
    return (
        math.log1p(len(t07["anchor"])),
        math.log1p(len(t07["evidence"])),
        proposal_anchor,
        keep_anchor,
        proposal_evidence,
        keep_evidence,
        proposal_anchor - keep_anchor,
        proposal_evidence - keep_evidence,
    )


def _single_target(candidates: Sequence[Any], target: str) -> Any:
    rows = [candidate for candidate in candidates if candidate.candidate_target == target]
    if len(rows) != 1:
        raise ValueError(f"candidate target is not unique: {target}")
    return rows[0]


def _component_count(nodes: set[str], adjacency: Mapping[str, set[str]]) -> int:
    remaining = set(nodes)
    count = 0
    while remaining:
        count += 1
        stack = [remaining.pop()]
        while stack:
            current = stack.pop()
            unseen = adjacency.get(current, set()) & remaining
            remaining.difference_update(unseen)
            stack.extend(unseen)
    return count


def _delta(left: Sequence[float], right: Sequence[float]) -> tuple[float, ...]:
    return tuple(float(a) - float(b) for a, b in zip(left, right, strict=True))


def _property_text(properties: Mapping[str, Any], key: str) -> str:
    for candidate, value in properties.items():
        if str(candidate).lower() == key.lower() and value not in (None, ""):
            return str(value)
    return ""


def _yes(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = ["load_safety_evidence"]
