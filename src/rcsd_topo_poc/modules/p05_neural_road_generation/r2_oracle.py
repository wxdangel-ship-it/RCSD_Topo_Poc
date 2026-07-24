from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import (
    derive_node_edits,
    derive_road_edits,
    derive_t05_pointers,
    materialize_edit_payloads,
    read_vector_payloads,
    semantic_node_candidate_ids,
    write_vector_payloads,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2OracleConfig
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _resolved_output(run_root: Path, record: dict[str, Any], *, strict_hashes: bool) -> Path:
    configured = normalize_runtime_path(str(record.get("path") or ""))
    path = configured if configured.is_file() else run_root / configured.name
    path = path.resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"output hash mismatch: {path}")
    return path


def _dataset_lineage(config: R2OracleConfig) -> tuple[Path, dict[str, Any], list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    root = normalize_runtime_path(config.m2r_dataset_run_root).resolve(strict=True)
    manifest_path = root / "p05_m2r_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-m2r-dataset-manifest-v1":
        raise ValueError("invalid M2R dataset manifest")
    if manifest.get("silent_fix") is not False:
        raise ValueError("M2R dataset must declare silent_fix=false")
    outputs = dict(manifest.get("outputs") or {})
    graph_index_path = _resolved_output(root, outputs["graph_index"], strict_hashes=config.strict_hashes)
    artifact_path = _resolved_output(root, outputs["input_artifacts"], strict_hashes=config.strict_hashes)
    graph_index = _read_json(graph_index_path)
    graphs = list(graph_index.get("graphs") or [])
    if len(graphs) != 51:
        raise ValueError(f"R2 Gate 1 requires 51 RoadGraph cases, got {len(graphs)}")

    supervision_root = normalize_runtime_path(str(manifest.get("supervision_run_root") or "")).resolve(strict=True)
    supervision_manifest_path = supervision_root / "p05_m2r_supervision_manifest.json"
    if config.strict_hashes and sha256_file(supervision_manifest_path) != str(manifest.get("supervision_manifest_sha256") or ""):
        raise ValueError("supervision manifest differs from dataset lineage")
    supervision = _read_json(supervision_manifest_path)
    targets_path = _resolved_output(
        supervision_root,
        dict(supervision.get("outputs") or {})["targets"],
        strict_hashes=config.strict_hashes,
    )
    return manifest_path, manifest, graphs, _read_csv(artifact_path), _read_csv(targets_path)


def _roles_by_sample(rows: list[dict[str, str]]) -> dict[str, dict[str, Path]]:
    output: dict[str, dict[str, Path]] = defaultdict(dict)
    for row in rows:
        path = normalize_runtime_path(row["path"]).resolve(strict=True)
        if sha256_file(path) != row["sha256"]:
            raise ValueError(f"input artifact hash mismatch: {row['sample_id']}:{row['role']}")
        output[row["sample_id"]][row["role"]] = path
    return output


def _truth_by_sample(rows: list[dict[str, str]]) -> dict[str, dict[str, Path]]:
    output: dict[str, dict[str, Path]] = defaultdict(dict)
    for row in rows:
        if row.get("task_name") != "T06" or row.get("availability") != "available":
            continue
        if row.get("target_kind") not in {"road", "node"}:
            continue
        path = normalize_runtime_path(row["artifact_path"]).resolve(strict=True)
        if sha256_file(path) != row["artifact_sha256"]:
            raise ValueError(f"truth artifact hash mismatch: {row['sample_id']}:{row['target_kind']}")
        output[row["sample_id"]][row["target_kind"]] = path
    return output


def _merge_vectors(paths: list[tuple[str, Path]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    last_meta: dict[str, Any] = {}
    for role, path in paths:
        payloads, meta = read_vector_payloads(path, source_role=role)
        merged.update(payloads)
        last_meta = meta
    return merged, last_meta


def _relation_properties(path: Path) -> list[dict[str, Any]]:
    layers = fiona.listlayers(path)
    if len(layers) != 1:
        raise ValueError(f"expected one T05 relation layer: {path}")
    with fiona.open(path, layer=layers[0]) as source:
        return [dict(feature["properties"]) for feature in source]


def _case_key(sample_id: str) -> str:
    import hashlib

    return hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:20]


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("fiona", "shapely", "pyproj", "numpy", "torch"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "packages": packages,
    }


def _report(summary: dict[str, Any]) -> str:
    return f"""# P05-R2 Gate 1 Oracle 表示报告

## 结论

- Case：{summary['case_count']}；oracle passed：{summary['oracle_passed_case_count']}。
- Road edit coverage：{summary['road_edit_coverage']:.6%}；Node edit coverage：{summary['node_edit_coverage']:.6%}。
- SPLIT truth expressible：{summary['split_truth_coverage']:.6%}。
- T05 pointer coverage：{summary['t05_pointer_coverage']:.6%}；cardinality error：{summary['t05_pointer_cardinality_error_count']}。
- Road/Node semantic F1 均为 1.0 的 Case：{summary['semantic_exact_case_count']}。
- 有向拓扑完全一致 Case：{summary['directed_topology_exact_case_count']}。
- Gate 1：{'PASS' if summary['gate1_pass'] else 'FAIL'}。

## Road actions

{json.dumps(summary['road_action_counts'], ensure_ascii=False, sort_keys=True)}

## Node actions

{json.dumps(summary['node_action_counts'], ensure_ascii=False, sort_keys=True)}

## 边界

oracle payload 全部 `label_only=true`，只证明 edit language 能表达真值；它不证明模型已经学会生成这些动作。物化器未调用 T03-T06 业务规则，`silent_fix=false`。
"""


def build_r2_oracle_run(config: R2OracleConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    dataset_manifest_path, dataset_manifest, graph_rows, artifact_rows, target_rows = _dataset_lineage(config)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)

    road_edit_path = target_root / "p05_r2_road_edits.jsonl"
    node_edit_path = target_root / "p05_r2_node_edits.jsonl"
    t05_node_edit_path = target_root / "p05_r2_t05_node_edits.jsonl"
    road_edit_path.touch()
    node_edit_path.touch()
    t05_node_edit_path.touch()
    roles = _roles_by_sample(artifact_rows)
    truth = _truth_by_sample(target_rows)

    case_index: list[dict[str, Any]] = []
    pointer_rows: list[dict[str, Any]] = []
    case_metrics: list[dict[str, Any]] = []
    road_actions: Counter[str] = Counter()
    node_actions: Counter[str] = Counter()
    t05_node_actions: Counter[str] = Counter()
    road_truth = road_represented = node_truth = node_represented = 0
    t05_node_truth = t05_node_represented = 0
    split_truth = split_represented = 0
    pointer_targets = pointer_expressible = pointer_cardinality = pointer_missing = 0
    pointer_raw_selected = pointer_generated_selected = 0
    t05_node_lineage: list[dict[str, Any]] = []

    for graph in sorted(graph_rows, key=lambda item: str(item["sample_id"])):
        sample_id = str(graph["sample_id"])
        sample_roles = roles[sample_id]
        sample_truth = truth[sample_id]
        required_roles = {"t01_roads", "raw_rcsdroad", "raw_prepared_swsd_nodes", "raw_rcsdnode", "t05_relation_truth"}
        missing = sorted(required_roles - set(sample_roles))
        if missing or set(sample_truth) != {"road", "node"}:
            raise ValueError(f"{sample_id}: incomplete R2 lineage, missing={missing}, truth={sorted(sample_truth)}")

        base_roads, _ = _merge_vectors(
            [("t01_roads", sample_roles["t01_roads"]), ("raw_rcsdroad", sample_roles["raw_rcsdroad"])]
        )
        base_nodes, _ = _merge_vectors(
            [
                ("raw_prepared_swsd_nodes", sample_roles["raw_prepared_swsd_nodes"]),
                ("raw_rcsdnode", sample_roles["raw_rcsdnode"]),
            ]
        )
        truth_roads, road_meta = read_vector_payloads(sample_truth["road"], source_role="t06_frcsd_road_truth")
        truth_nodes, node_meta = read_vector_payloads(sample_truth["node"], source_role="t06_frcsd_node_truth")
        t05_node_truth_path = (sample_roles["t05_relation_truth"].parent / "rcsdnode_out.gpkg").resolve(strict=True)
        t05_truth_nodes, _ = read_vector_payloads(t05_node_truth_path, source_role="t05_rcsdnode_out_truth")

        road_edits, road_summary = derive_road_edits(base_roads, truth_roads)
        node_edits, node_summary = derive_node_edits(base_nodes, truth_nodes)
        for edit in road_edits:
            edit.update({"sample_id": sample_id, "fold": int(graph["fold"])})
        for edit in node_edits:
            edit.update({"sample_id": sample_id, "fold": int(graph["fold"])})
        t05_node_edits, t05_node_summary = derive_node_edits(base_nodes, t05_truth_nodes)
        for edit in t05_node_edits:
            edit.update({"sample_id": sample_id, "fold": int(graph["fold"]), "stage": "T05"})
        _append_jsonl(road_edit_path, road_edits)
        _append_jsonl(node_edit_path, node_edits)
        _append_jsonl(t05_node_edit_path, t05_node_edits)

        reconstructed_roads, reconstructed_nodes = materialize_edit_payloads(road_edits, node_edits)
        key = _case_key(sample_id)
        case_root = target_root / "cases" / key
        road_path = case_root / "reconstructed_road.gpkg"
        node_path = case_root / "reconstructed_node.gpkg"
        if config.emit_reconstructed_gpkg:
            write_vector_payloads(road_path, reconstructed_roads.values(), meta=road_meta)
            write_vector_payloads(node_path, reconstructed_nodes.values(), meta=node_meta)
            evaluation = evaluate_frcsd(road_path, node_path, sample_truth["road"], sample_truth["node"])
        else:
            evaluation = {}

        relation_rows = _relation_properties(sample_roles["t05_relation_truth"])
        _, reconstructed_t05_nodes = materialize_edit_payloads([], t05_node_edits)
        raw_candidate_ids = semantic_node_candidate_ids(base_nodes)
        t05_candidate_ids = semantic_node_candidate_ids(reconstructed_t05_nodes)
        pointers, pointer_summary = derive_t05_pointers(relation_rows, t05_candidate_ids)
        for pointer in pointers:
            selected_base_id = str(pointer.get("selected_base_id") or "")
            if not selected_base_id:
                pointer["candidate_source"] = "NO_MATCH"
            elif selected_base_id in raw_candidate_ids:
                pointer["candidate_source"] = "RAW_BASE"
                pointer_raw_selected += 1
            else:
                pointer["candidate_source"] = "GENERATED_T05_NODE"
                pointer_generated_selected += 1
            pointer.update({"sample_id": sample_id, "fold": int(graph["fold"])})
        pointer_rows.extend(pointers)
        t05_node_lineage.append(
            {
                "sample_id": sample_id,
                "fold": int(graph["fold"]),
                "path": str(t05_node_truth_path),
                "sha256": sha256_file(t05_node_truth_path),
                "size_bytes": t05_node_truth_path.stat().st_size,
                "label_only": True,
            }
        )

        split_ids = {
            str(payload["id"])
            for payload in truth_roads.values()
            if str(next((value for key, value in dict(payload["properties"]).items() if str(key).casefold() == "t06_split_original_road_id"), "") or "").strip()
        }
        reconstructed_ids = set(reconstructed_roads)
        road_actions.update(road_summary["action_counts"])
        node_actions.update(node_summary["action_counts"])
        t05_node_actions.update(t05_node_summary["action_counts"])
        road_truth += road_summary["truth_count"]
        road_represented += road_summary["represented_truth_count"]
        node_truth += node_summary["truth_count"]
        node_represented += node_summary["represented_truth_count"]
        t05_node_truth += t05_node_summary["truth_count"]
        t05_node_represented += t05_node_summary["represented_truth_count"]
        split_truth += len(split_ids)
        split_represented += len(split_ids & reconstructed_ids)
        pointer_targets += pointer_summary["target_count"]
        pointer_expressible += pointer_summary["expressible_target_count"]
        pointer_cardinality += pointer_summary["cardinality_error_count"]
        pointer_missing += pointer_summary["missing_selected_base_count"]

        metric_record = {
            "sample_id": sample_id,
            "fold": int(graph["fold"]),
            "road_summary": road_summary,
            "node_summary": node_summary,
            "t05_node_summary": t05_node_summary,
            "pointer_summary": pointer_summary,
            "split_truth_count": len(split_ids),
            "split_represented_count": len(split_ids & reconstructed_ids),
            "evaluation": evaluation,
        }
        case_metrics.append(metric_record)
        road_f1 = float(evaluation.get("road_object", {}).get("f1", 0.0)) if evaluation else 0.0
        node_f1 = float(evaluation.get("node_object", {}).get("f1", 0.0)) if evaluation else 0.0
        topology_f1 = float(evaluation.get("directed_topology", {}).get("f1", 0.0)) if evaluation else 0.0
        case_index.append(
            {
                "sample_id": sample_id,
                "family": graph["family"],
                "business_id": graph["business_id"],
                "fold": int(graph["fold"]),
                "road_truth_count": road_summary["truth_count"],
                "node_truth_count": node_summary["truth_count"],
                "road_edit_coverage": road_summary["coverage"],
                "node_edit_coverage": node_summary["coverage"],
                "t05_pointer_coverage": pointer_summary["coverage"],
                "road_f1": road_f1,
                "node_f1": node_f1,
                "directed_topology_f1": topology_f1,
                "hard_failure_count": len(evaluation.get("hard_failures", [])) if evaluation else 0,
                "reconstructed_road_path": str(road_path.resolve()) if config.emit_reconstructed_gpkg else "",
                "reconstructed_node_path": str(node_path.resolve()) if config.emit_reconstructed_gpkg else "",
                "truth_road_path": str(sample_truth["road"]),
                "truth_node_path": str(sample_truth["node"]),
                "t05_node_truth_path": str(t05_node_truth_path),
            }
        )

    semantic_exact = sum(row["road_f1"] == 1.0 and row["node_f1"] == 1.0 for row in case_index)
    topology_exact = sum(row["directed_topology_f1"] == 1.0 and row["hard_failure_count"] == 0 for row in case_index)
    road_coverage = road_represented / road_truth if road_truth else 1.0
    node_coverage = node_represented / node_truth if node_truth else 1.0
    t05_node_coverage = t05_node_represented / t05_node_truth if t05_node_truth else 1.0
    split_coverage = split_represented / split_truth if split_truth else 1.0
    pointer_coverage = pointer_expressible / pointer_targets if pointer_targets else 1.0
    gate1_pass = (
        road_coverage >= 0.999
        and node_coverage == 1.0
        and t05_node_coverage == 1.0
        and split_coverage == 1.0
        and pointer_coverage == 1.0
        and pointer_cardinality == 0
        and semantic_exact == len(case_index)
        and topology_exact == len(case_index)
    )
    summary = {
        "schema_version": "p05-r2-oracle-summary-v1",
        "case_count": len(case_index),
        "oracle_passed_case_count": sum(row["hard_failure_count"] == 0 for row in case_index),
        "road_truth_count": road_truth,
        "road_represented_truth_count": road_represented,
        "road_edit_coverage": road_coverage,
        "node_truth_count": node_truth,
        "node_represented_truth_count": node_represented,
        "node_edit_coverage": node_coverage,
        "t05_node_truth_count": t05_node_truth,
        "t05_node_represented_truth_count": t05_node_represented,
        "t05_node_edit_coverage": t05_node_coverage,
        "split_truth_count": split_truth,
        "split_represented_truth_count": split_represented,
        "split_truth_coverage": split_coverage,
        "t05_pointer_target_count": pointer_targets,
        "t05_pointer_expressible_count": pointer_expressible,
        "t05_pointer_coverage": pointer_coverage,
        "t05_pointer_cardinality_error_count": pointer_cardinality,
        "t05_pointer_missing_selected_base_count": pointer_missing,
        "t05_pointer_raw_selected_count": pointer_raw_selected,
        "t05_pointer_generated_selected_count": pointer_generated_selected,
        "semantic_exact_case_count": semantic_exact,
        "directed_topology_exact_case_count": topology_exact,
        "road_action_counts": dict(sorted(road_actions.items())),
        "node_action_counts": dict(sorted(node_actions.items())),
        "t05_node_action_counts": dict(sorted(t05_node_actions.items())),
        "gate1_pass": gate1_pass,
        "silent_fix": False,
        "duration_seconds": time.perf_counter() - started,
    }

    case_index_path = target_root / "p05_r2_case_index.csv"
    pointer_path = target_root / "p05_r2_t05_pointers.csv"
    t05_node_lineage_path = target_root / "p05_r2_t05_node_lineage.csv"
    coverage_path = target_root / "p05_r2_action_coverage.json"
    metrics_path = target_root / "p05_r2_oracle_case_metrics.json"
    summary_path = target_root / "p05_r2_oracle_summary.json"
    report_path = target_root / "p05_r2_oracle_report.md"
    write_csv(case_index_path, case_index, list(case_index[0]))
    write_csv(pointer_path, pointer_rows, list(pointer_rows[0]) if pointer_rows else ["sample_id", "target_id"])
    write_csv(t05_node_lineage_path, t05_node_lineage, list(t05_node_lineage[0]))
    write_json(coverage_path, {key: summary[key] for key in summary if "coverage" in key or "action_counts" in key or "truth_count" in key})
    write_json(metrics_path, {"schema_version": "p05-r2-oracle-case-metrics-v1", "cases": case_metrics})
    write_json(summary_path, summary)
    report_path.write_text(_report(summary), encoding="utf-8")

    outputs = {
        "case_index": output_record(case_index_path),
        "road_edits": output_record(road_edit_path),
        "node_edits": output_record(node_edit_path),
        "t05_node_edits": output_record(t05_node_edit_path),
        "t05_pointers": output_record(pointer_path),
        "t05_node_lineage": output_record(t05_node_lineage_path),
        "coverage": output_record(coverage_path),
        "case_metrics": output_record(metrics_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-r2-oracle-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "gate1_passed" if gate1_pass else "gate1_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "m2r_dataset_manifest_path": str(dataset_manifest_path),
        "m2r_dataset_manifest_sha256": sha256_file(dataset_manifest_path),
        "m2r_dataset_run_id": dataset_manifest.get("run_id"),
        "parameters": {
            "strict_hashes": config.strict_hashes,
            "emit_reconstructed_gpkg": config.emit_reconstructed_gpkg,
        },
        "environment": _environment(),
        "performance": {"duration_seconds": summary["duration_seconds"]},
        "outputs": outputs,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_r2_oracle_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = [
    "build_r2_oracle_run",
    "derive_node_edits",
    "derive_road_edits",
    "derive_t05_pointers",
    "materialize_edit_payloads",
    "semantic_node_candidate_ids",
]
