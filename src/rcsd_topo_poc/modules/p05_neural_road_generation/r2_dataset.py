from __future__ import annotations

import json
import platform
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import NODE_ACTIONS, ROAD_ACTIONS, read_vector_payloads
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_gate2 import (
    _action_targets,
    _frame,
    _jsonl_for_sample,
    _merge_payloads,
    _node_targets,
    _oracle_lineage,
    _pointer_targets,
    _read_csv,
    _read_json,
    _resolve_output,
    _road_targets,
    _slot_limits,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2DatasetConfig
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _case_key(sample_id: str) -> str:
    import hashlib

    return hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:20]


def _group_rows(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return grouped


def _target_cross_fold_audit(case_arrays: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    samples: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in case_arrays:
        for kind, values in (("Road", item["truth_road_ids"]), ("Node", item["truth_node_ids"])):
            for identifier in values:
                key = (kind, str(identifier))
                occurrences[key].add(int(item["fold"]))
                samples[key].add(str(item["sample_id"]))
    rows = []
    for key, folds in sorted(occurrences.items()):
        if len(folds) <= 1:
            continue
        rows.append(
            {
                "object_kind": key[0],
                "object_id": key[1],
                "folds": "|".join(str(value) for value in sorted(folds)),
                "sample_ids": "|".join(sorted(samples[key])),
            }
        )
    return rows, {
        "cross_fold_target_entity_count": len(rows),
        "road_count": sum(row["object_kind"] == "Road" for row in rows),
        "node_count": sum(row["object_kind"] == "Node" for row in rows),
        "passed": not rows,
    }


def build_r2_dataset(config: R2DatasetConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    oracle_root = normalize_runtime_path(config.oracle_run_root).resolve(strict=True)
    oracle_manifest, outputs, m2r_root, m2r_manifest = _oracle_lineage(oracle_root)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    case_root = target_root / "cases"
    case_root.mkdir()

    input_artifact_path = _resolve_output(m2r_root, dict(m2r_manifest["outputs"])["input_artifacts"])
    graph_index_path = _resolve_output(m2r_root, dict(m2r_manifest["outputs"])["graph_index"])
    scene_path = _resolve_output(m2r_root, dict(m2r_manifest["outputs"])["scenes"])
    artifacts_by_sample = _group_rows(_read_csv(input_artifact_path), "sample_id")
    pointers_by_sample = _group_rows(_read_csv(outputs["t05_pointers"]), "sample_id")
    graphs_by_sample = {str(row["sample_id"]): row for row in list(_read_json(graph_index_path)["graphs"])}
    case_rows = _read_csv(outputs["case_index"])
    limits = _slot_limits(outputs)
    index_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    cross_fold_inputs: dict[str, set[int]] = defaultdict(set)
    case_arrays: list[dict[str, Any]] = []

    for case_row in sorted(case_rows, key=lambda row: str(row["sample_id"])):
        sample_id = str(case_row["sample_id"])
        fold = int(case_row["fold"])
        role_rows = {row["role"]: row for row in artifacts_by_sample[sample_id]}
        required = {"t01_roads", "raw_rcsdroad", "raw_prepared_swsd_nodes", "raw_rcsdnode"}
        if not required <= set(role_rows):
            raise ValueError(f"{sample_id}: missing R2 input roles {sorted(required - set(role_rows))}")
        roles = {role: normalize_runtime_path(role_rows[role]["path"]).resolve(strict=True) for role in required}
        if config.strict_hashes:
            for role, path in roles.items():
                if sha256_file(path) != role_rows[role]["sha256"]:
                    raise ValueError(f"{sample_id}: input hash mismatch for {role}")
        base_roads = _merge_payloads((roles["t01_roads"], roles["raw_rcsdroad"]), "input")
        base_nodes = _merge_payloads(
            (roles["raw_prepared_swsd_nodes"], roles["raw_rcsdnode"]), "input"
        )
        coordinate_frame = _frame((base_roads, base_nodes))
        truth_roads, _ = read_vector_payloads(Path(case_row["truth_road_path"]), source_role="truth")
        truth_nodes, _ = read_vector_payloads(Path(case_row["truth_node_path"]), source_role="truth")
        t05_nodes, _ = read_vector_payloads(Path(case_row["t05_node_truth_path"]), source_role="truth")
        ordered_nodes, node_xy, node_slots = _node_targets(truth_nodes, coordinate_frame)
        ordered_roads, road_targets = _road_targets(
            truth_roads, coordinate_frame, node_slots, config.polyline_points
        )
        ordered_t05_nodes, t05_node_xy, _ = _node_targets(t05_nodes, coordinate_frame)
        ordered_pointers, pointer_targets = _pointer_targets(
            pointers_by_sample[sample_id], ordered_t05_nodes
        )
        road_edits = _jsonl_for_sample(outputs["road_edits"], sample_id)
        node_edits = _jsonl_for_sample(outputs["node_edits"], sample_id)
        t05_edits = _jsonl_for_sample(outputs["t05_node_edits"], sample_id)

        graph_row = graphs_by_sample[sample_id]
        graph_path = normalize_runtime_path(graph_row["graph_path"]).resolve(strict=True)
        if config.strict_hashes and sha256_file(graph_path) != graph_row["graph_sha256"]:
            raise ValueError(f"{sample_id}: graph hash mismatch")
        with np.load(graph_path, allow_pickle=False) as graph:
            input_x = graph["x"].astype(np.float32)
            edge_index = graph["edge_index"].astype(np.int64)
            input_road_ids = graph["road_ids"].astype(str)
        for identifier in input_road_ids:
            cross_fold_inputs[str(identifier)].add(fold)

        counts = (
            len(ordered_roads),
            len(ordered_nodes),
            len(ordered_t05_nodes),
            len(ordered_pointers),
        )
        count_targets = np.asarray(
            [
                np.log1p(value) / np.log1p(limit)
                for value, limit in zip(
                    counts,
                    (limits.road_slots, limits.node_slots, limits.t05_node_slots, limits.pointer_queries),
                    strict=True,
                )
            ],
            dtype=np.float32,
        )
        arrays = {
            "input_x": input_x,
            "edge_index": edge_index,
            "input_road_ids": input_road_ids,
            **road_targets,
            "node_xy": node_xy,
            "t05_node_xy": t05_node_xy,
            "pointer": pointer_targets,
            "road_action": _action_targets(road_edits, ROAD_ACTIONS),
            "node_action": _action_targets(node_edits, NODE_ACTIONS),
            "t05_action": _action_targets(t05_edits, NODE_ACTIONS),
            "counts": count_targets,
            "truth_road_ids": np.asarray([str(item["id"]) for item in ordered_roads]),
            "truth_node_ids": np.asarray([str(item["id"]) for item in ordered_nodes]),
            "t05_node_ids": np.asarray([str(item["id"]) for item in ordered_t05_nodes]),
            "pointer_target_ids": np.asarray([str(item["target_id"]) for item in ordered_pointers]),
        }
        case_path = case_root / f"{_case_key(sample_id)}.npz"
        np.savez_compressed(case_path, **arrays)
        if any(float(np.abs(arrays[name]).max(initial=0.0)) > 0.500001 for name in ("road_geometry", "node_xy", "t05_node_xy")):
            raise ValueError(f"{sample_id}: label geometry is outside the input-derived frame")
        index_rows.append(
            {
                "sample_id": sample_id,
                "family": case_row["family"],
                "business_id": case_row["business_id"],
                "fold": fold,
                "case_path": str(case_path.resolve()),
                "case_sha256": sha256_file(case_path),
                "road_count": counts[0],
                "node_count": counts[1],
                "t05_node_count": counts[2],
                "pointer_count": counts[3],
                "road_action_count": len(road_edits),
                "node_action_count": len(node_edits),
                "t05_action_count": len(t05_edits),
                "frame_center_x": coordinate_frame.center_x,
                "frame_center_y": coordinate_frame.center_y,
                "frame_scale": coordinate_frame.scale,
                "truth_road_path": case_row["truth_road_path"],
                "truth_node_path": case_row["truth_node_path"],
            }
        )
        case_arrays.append(
            {
                "sample_id": sample_id,
                "fold": fold,
                "truth_road_ids": arrays["truth_road_ids"],
                "truth_node_ids": arrays["truth_node_ids"],
            }
        )
        for role, path in sorted(roles.items()):
            lineage_rows.append(
                {
                    "sample_id": sample_id,
                    "fold": fold,
                    "role": role,
                    "path": str(path),
                    "sha256": role_rows[role]["sha256"],
                    "input_feature": True,
                    "label_only": False,
                }
            )
        for role, path in (
            ("t06_road_truth", Path(case_row["truth_road_path"])),
            ("t06_node_truth", Path(case_row["truth_node_path"])),
            ("t05_node_truth", Path(case_row["t05_node_truth_path"])),
        ):
            lineage_rows.append(
                {
                    "sample_id": sample_id,
                    "fold": fold,
                    "role": role,
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "input_feature": False,
                    "label_only": True,
                }
            )

    cross_fold_target_rows, target_guard = _target_cross_fold_audit(case_arrays)
    cross_fold_input_rows = [
        {"road_id": identifier, "folds": "|".join(str(value) for value in sorted(folds))}
        for identifier, folds in sorted(cross_fold_inputs.items())
        if len(folds) > 1
    ]
    index_path = target_root / "p05_r2_dataset_index.json"
    lineage_path = target_root / "p05_r2_dataset_lineage.csv"
    target_guard_path = target_root / "p05_r2_target_entity_guard.csv"
    input_guard_path = target_root / "p05_r2_input_entity_guard.csv"
    schema_path = target_root / "p05_r2_dataset_schema.json"
    summary_path = target_root / "p05_r2_dataset_summary.json"
    write_json(index_path, {"schema_version": "p05-r2-dataset-index-v1", "cases": index_rows})
    write_csv(lineage_path, lineage_rows, list(lineage_rows[0]))
    write_csv(
        target_guard_path,
        cross_fold_target_rows,
        list(cross_fold_target_rows[0]) if cross_fold_target_rows else ["object_kind", "object_id", "folds", "sample_ids"],
    )
    write_csv(
        input_guard_path,
        cross_fold_input_rows,
        list(cross_fold_input_rows[0]) if cross_fold_input_rows else ["road_id", "folds"],
    )
    write_json(
        schema_path,
        {
            "schema_version": "p05-r2-dataset-schema-v1",
            "input_arrays": ["input_x", "edge_index", "input_road_ids"],
            "label_only_arrays": [
                "road_geometry",
                "road_direction",
                "road_source",
                "road_endpoint",
                "node_xy",
                "t05_node_xy",
                "pointer",
                "road_action",
                "node_action",
                "t05_action",
                "counts",
            ],
            "polyline_points": config.polyline_points,
            "slot_limits": asdict(limits),
            "oracle_payload_entered_input": False,
        },
    )
    fold_counts = Counter(int(row["fold"]) for row in index_rows)
    summary = {
        "schema_version": "p05-r2-dataset-summary-v1",
        "case_count": len(index_rows),
        "fold_counts": {str(key): fold_counts[key] for key in sorted(fold_counts)},
        "slot_limits": asdict(limits),
        "cross_fold_input_road_count": len(cross_fold_input_rows),
        "target_entity_guard": target_guard,
        "polyline_points": config.polyline_points,
        "silent_fix": False,
        "duration_seconds": time.perf_counter() - started,
    }
    write_json(summary_path, summary)
    output_paths = {
        "index": index_path,
        "lineage": lineage_path,
        "target_entity_guard": target_guard_path,
        "input_entity_guard": input_guard_path,
        "schema": schema_path,
        "summary": summary_path,
    }
    manifest = {
        "schema_version": "p05-r2-dataset-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "completed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "oracle_manifest_path": str(oracle_root / "p05_r2_oracle_manifest.json"),
        "oracle_manifest_sha256": sha256_file(oracle_root / "p05_r2_oracle_manifest.json"),
        "m2r_scene_path": str(scene_path),
        "m2r_scene_sha256": sha256_file(scene_path),
        "parameters": {
            name: str(value) if isinstance(value, Path) else value
            for name, value in asdict(config).items()
        },
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "outputs": {name: output_record(path) for name, path in output_paths.items()},
        "case_outputs": {
            row["sample_id"]: {"path": row["case_path"], "sha256": row["case_sha256"]}
            for row in index_rows
        },
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_r2_dataset_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["build_r2_dataset"]
