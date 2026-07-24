from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_lineage import load_strategy_replay_cases, resolved_path
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_models import PTOCandidateConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import (
    derive_node_edits,
    derive_road_edits,
    derive_t05_pointers,
    read_vector_payloads,
    semantic_node_candidate_ids,
)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(payload: Any) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(payload.get("id") or ""),
        "geometry": payload.get("geometry"),
        "properties": dict(payload.get("properties") or {}),
    }


def canonical_edit_payload(
    *,
    stage: str,
    object_kind: str,
    group_id: str,
    action: str,
    base_object_id: str,
    output_payloads: Iterable[dict[str, Any]],
    pointer_value: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "object_kind": object_kind,
        "group_id": group_id,
        "action": action,
        "base_object_id": str(base_object_id or ""),
        "output_payloads": [_clean_payload(payload) for payload in output_payloads],
        "pointer_value": str(pointer_value or ""),
    }


def _base_edit(kind: str, action: str, base_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "object_kind": kind,
        "action": action,
        "base_object_id": base_id,
        "output_object_ids": [base_id] if payload is not None else [],
        "output_payloads": [payload] if payload is not None else [],
        "lineage_kind": "base_identity" if payload is not None else "base_drop",
        "label_only": False,
    }


def _merge_vectors(items: list[tuple[str, Path]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    last_meta: dict[str, Any] = {}
    for role, path in items:
        payloads, meta = read_vector_payloads(path, source_role=role)
        merged.update(payloads)
        last_meta = meta
    return merged, last_meta


def _relation_rows(path: Path) -> list[dict[str, Any]]:
    layers = fiona.listlayers(path)
    if len(layers) != 1:
        raise ValueError(f"expected one T05 relation layer: {path}")
    with fiona.open(path, layer=layers[0]) as source:
        return [dict(feature["properties"]) for feature in source]


def _candidate_source(case: dict[str, Any], *, source_kind: str, role: str) -> dict[str, Any]:
    artifact = dict(case["artifacts"][role])
    return {
        "source_kind": source_kind,
        "role": role,
        "code_commit": case["code_commit"],
        "replay_run_root": case["replay_run_root"],
        "artifact_path": artifact["path"],
        "artifact_sha256": artifact["sha256"],
    }


def _create_group(stage: str, edit: dict[str, Any]) -> tuple[str, str]:
    base_id = str(edit.get("base_object_id") or "")
    if base_id:
        return f"{stage}:BASE:{base_id}", "EXACTLY_ONE"
    output_ids = [str(item) for item in list(edit.get("output_object_ids") or [])]
    if not output_ids:
        raise ValueError(f"candidate edit without base or outputs: {edit}")
    return f"{stage}:CREATE:{','.join(output_ids)}", "OPTIONAL_AT_MOST_ONE"


def _add_candidate(
    store: dict[tuple[str, str], dict[str, Any]],
    *,
    case: dict[str, Any],
    stage: str,
    edit: dict[str, Any],
    source: dict[str, Any],
    group_id: str | None = None,
    group_mode: str | None = None,
    pointer_value: str = "",
) -> None:
    resolved_group, resolved_mode = _create_group(stage, edit) if group_id is None else (group_id, str(group_mode))
    canonical = canonical_edit_payload(
        stage=stage,
        object_kind=str(edit["object_kind"]),
        group_id=resolved_group,
        action=str(edit["action"]),
        base_object_id=str(edit.get("base_object_id") or ""),
        output_payloads=list(edit.get("output_payloads") or []),
        pointer_value=pointer_value,
    )
    signature = _sha(canonical)
    key = (resolved_group, signature)
    if key in store:
        sources = list(store[key]["sources"])
        if source not in sources:
            sources.append(source)
            sources.sort(key=lambda item: _sha(item))
            store[key]["sources"] = sources
        return
    candidate_id = f"pto:{signature[:24]}"
    store[key] = {
        "candidate_id": candidate_id,
        "sample_id": case["sample_id"],
        "family": case["family"],
        "business_id": case["business_id"],
        "stage": stage,
        "object_kind": str(edit["object_kind"]),
        "group_id": resolved_group,
        "group_mode": resolved_mode,
        "action": str(edit["action"]),
        "base_object_id": str(edit.get("base_object_id") or ""),
        "output_object_ids": [str(value) for value in list(edit.get("output_object_ids") or [])],
        "output_payloads": list(edit.get("output_payloads") or []),
        "lineage_kind": str(edit.get("lineage_kind") or ""),
        "pointer_value": pointer_value,
        "canonical_payload_sha256": signature,
        "sources": [source],
        "label_only": False,
        "truth_derived": False,
    }


def _add_base_groups(
    store: dict[tuple[str, str], dict[str, Any]],
    *,
    case: dict[str, Any],
    stage: str,
    kind: str,
    base: dict[str, dict[str, Any]],
    source_role_map: dict[str, str],
) -> None:
    for base_id in sorted(base):
        payload_role = str(base[base_id].get("source_role") or "")
        source_role = source_role_map.get(payload_role)
        if source_role is None:
            raise ValueError(f"unknown base candidate source role: {payload_role}")
        source = _candidate_source(case, source_kind="BASE_IDENTITY", role=source_role)
        _add_candidate(store, case=case, stage=stage, edit=_base_edit(kind, "COPY", base_id, base[base_id]), source=source)
        _add_candidate(store, case=case, stage=stage, edit=_base_edit(kind, "DROP", base_id, None), source=source)


def _case_candidates(case: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    artifacts = {role: resolved_path(record["path"]) for role, record in dict(case["artifacts"]).items()}
    for role, path in artifacts.items():
        expected = str(dict(case["artifacts"])[role]["sha256"])
        if sha256_file(path) != expected:
            raise ValueError(f"strategy artifact changed after lineage freeze: {case['sample_id']}:{role}")
    base_roads, _ = _merge_vectors(
        [("t01_roads", artifacts["t01_roads"]), ("raw_rcsdroad", artifacts["rcsdroad"])]
    )
    base_nodes, _ = _merge_vectors(
        [("raw_prepared_swsd_nodes", artifacts["prepared_swsd_nodes"]), ("raw_rcsdnode", artifacts["rcsdnode"])]
    )
    strategy_roads, _ = read_vector_payloads(artifacts["t06_frcsd_road"], source_role="strategy_t06_frcsd_road")
    strategy_nodes, _ = read_vector_payloads(artifacts["t06_frcsd_node"], source_role="strategy_t06_frcsd_node")
    strategy_t05_nodes, _ = read_vector_payloads(artifacts["t05_rcsdnode_out"], source_role="strategy_t05_rcsdnode_out")
    strategy_road_edits, _ = derive_road_edits(base_roads, strategy_roads)
    strategy_node_edits, _ = derive_node_edits(base_nodes, strategy_nodes)
    strategy_t05_edits, _ = derive_node_edits(base_nodes, strategy_t05_nodes)

    store: dict[tuple[str, str], dict[str, Any]] = {}
    _add_base_groups(
        store,
        case=case,
        stage="FINAL_ROAD",
        kind="Road",
        base=base_roads,
        source_role_map={"t01_roads": "t01_roads", "raw_rcsdroad": "rcsdroad"},
    )
    node_source_roles = {
        "raw_prepared_swsd_nodes": "prepared_swsd_nodes",
        "raw_rcsdnode": "rcsdnode",
    }
    _add_base_groups(
        store,
        case=case,
        stage="FINAL_NODE",
        kind="Node",
        base=base_nodes,
        source_role_map=node_source_roles,
    )
    _add_base_groups(
        store,
        case=case,
        stage="T05_NODE",
        kind="Node",
        base=base_nodes,
        source_role_map=node_source_roles,
    )
    strategy_sources = {
        "FINAL_ROAD": _candidate_source(case, source_kind="STRATEGY_REPLAY", role="t06_frcsd_road"),
        "FINAL_NODE": _candidate_source(case, source_kind="STRATEGY_REPLAY", role="t06_frcsd_node"),
        "T05_NODE": _candidate_source(case, source_kind="STRATEGY_REPLAY", role="t05_rcsdnode_out"),
    }
    for stage, edits in (
        ("FINAL_ROAD", strategy_road_edits),
        ("FINAL_NODE", strategy_node_edits),
        ("T05_NODE", strategy_t05_edits),
    ):
        for edit in edits:
            candidate_edit = dict(edit)
            candidate_edit["label_only"] = False
            _add_candidate(store, case=case, stage=stage, edit=candidate_edit, source=strategy_sources[stage])

    t05_ids = semantic_node_candidate_ids(strategy_t05_nodes)
    pointer_rows, _ = derive_t05_pointers(_relation_rows(artifacts["t05_intersection_match_all"]), t05_ids)
    pointer_source = _candidate_source(case, source_kind="STRATEGY_REPLAY", role="t05_intersection_match_all")
    for pointer in pointer_rows:
        target_id = str(pointer["target_id"])
        values = {""}
        selected = str(pointer.get("selected_base_id") or "")
        if selected:
            values.add(selected)
        for value in sorted(values):
            edit = {
                "object_kind": "Pointer",
                "action": "SELECT" if value else "NO_MATCH",
                "base_object_id": target_id,
                "output_object_ids": [],
                "output_payloads": [],
                "lineage_kind": "strategy_pointer" if value else "generic_no_match",
            }
            _add_candidate(
                store,
                case=case,
                stage="T05_POINTER",
                edit=edit,
                source=pointer_source,
                group_id=f"T05_POINTER:TARGET:{target_id}",
                group_mode="EXACTLY_ONE",
                pointer_value=value,
            )

    candidates = sorted(store.values(), key=lambda item: (item["stage"], item["group_id"], item["candidate_id"]))
    group_modes: dict[str, str] = {}
    for candidate in candidates:
        previous = group_modes.setdefault(str(candidate["group_id"]), str(candidate["group_mode"]))
        if previous != candidate["group_mode"]:
            raise ValueError(f"candidate group mode conflict: {candidate['group_id']}")
    counts = Counter(f"{item['stage']}:{item['action']}" for item in candidates)
    summary = {
        "sample_id": case["sample_id"],
        "family": case["family"],
        "business_id": case["business_id"],
        "base_road_count": len(base_roads),
        "base_node_count": len(base_nodes),
        "candidate_count": len(candidates),
        "variable_count": len(candidates),
        "group_count": len(group_modes),
        "constraint_count": len(group_modes),
        "action_counts": dict(sorted(counts.items())),
        "replay_duration_seconds": case["replay_duration_seconds"],
    }
    return candidates, summary


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def build_pto_candidate_run(config: PTOCandidateConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    target_root = resolved_path(config.output_root, strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    cases = load_strategy_replay_cases(config)
    target_root.mkdir(parents=True)
    candidate_path = target_root / "p05_pto_candidates.jsonl"
    candidate_path.touch()
    case_index: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    candidate_count = variable_count = group_count = constraint_count = 0
    replay_seconds = 0.0
    for case in cases:
        case_started = time.perf_counter()
        candidates, summary = _case_candidates(case)
        summary["candidate_build_seconds"] = time.perf_counter() - case_started
        summary["candidate_signature"] = _sha(
            [item["canonical_payload_sha256"] for item in candidates]
        )
        _append_jsonl(candidate_path, candidates)
        case_index.append(summary)
        by_group: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            by_group.setdefault(str(candidate["group_id"]), []).append(candidate)
        for group_id, options in sorted(by_group.items()):
            group_rows.append(
                {
                    "sample_id": case["sample_id"],
                    "family": case["family"],
                    "business_id": case["business_id"],
                    "corridor_id": "",
                    "component_id": group_id,
                    "partition_kind": "optimization_candidate_group",
                    "stage": options[0]["stage"],
                    "group_mode": options[0]["group_mode"],
                    "candidate_count": len(options),
                    "variable_count": len(options),
                    "constraint_count": 1,
                    "unbounded_enumeration": False,
                }
            )
        action_counts.update(summary["action_counts"])
        candidate_count += int(summary["candidate_count"])
        variable_count += int(summary["variable_count"])
        group_count += int(summary["group_count"])
        constraint_count += int(summary["constraint_count"])
        replay_seconds += float(summary["replay_duration_seconds"])
        for role, record in sorted(dict(case["artifacts"]).items()):
            lineage_rows.append(
                {
                    "sample_id": case["sample_id"],
                    "family": case["family"],
                    "business_id": case["business_id"],
                    "role": role,
                    "path": record["path"],
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                    "code_commit": case["code_commit"],
                    "label_only": False,
                    "truth_derived": False,
                }
            )
        for role in ("aggregate_manifest", "case_manifest"):
            record = dict(case[role])
            lineage_rows.append(
                {
                    "sample_id": case["sample_id"],
                    "family": case["family"],
                    "business_id": case["business_id"],
                    "role": role,
                    "path": record["path"],
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                    "code_commit": case["code_commit"],
                    "label_only": False,
                    "truth_derived": False,
                }
            )

    excluded_occurrences = sum(row["business_id"] in set(config.excluded_business_ids) for row in case_index)
    summary = {
        "schema_version": "p05-pto-candidate-summary-v1",
        "case_count": len(case_index),
        "family_counts": dict(sorted(Counter(row["family"] for row in case_index).items())),
        "excluded_business_ids": list(config.excluded_business_ids),
        "excluded_occurrence_count": excluded_occurrences,
        "candidate_count": candidate_count,
        "variable_count": variable_count,
        "group_count": group_count,
        "constraint_count": constraint_count,
        "action_counts": dict(sorted(action_counts.items())),
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "unbounded_enumeration": False,
        "replay_duration_seconds": replay_seconds,
        "candidate_build_duration_seconds": time.perf_counter() - started,
        "silent_fix": False,
        "candidate_gate_scope_pass": len(case_index) == config.expected_case_count and excluded_occurrences == 0,
    }
    case_index_path = target_root / "p05_pto_candidate_case_index.csv"
    group_index_path = target_root / "p05_pto_candidate_group_index.csv"
    lineage_path = target_root / "p05_pto_candidate_lineage.csv"
    summary_path = target_root / "p05_pto_candidate_summary.json"
    write_csv(case_index_path, case_index, list(case_index[0]))
    write_csv(group_index_path, group_rows, list(group_rows[0]))
    write_csv(lineage_path, lineage_rows, list(lineage_rows[0]))
    write_json(summary_path, summary)
    outputs = {
        "candidates": output_record(candidate_path),
        "case_index": output_record(case_index_path),
        "group_index": output_record(group_index_path),
        "lineage": output_record(lineage_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": "p05-pto-candidate-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "candidate_scope_passed" if summary["candidate_gate_scope_pass"] else "candidate_scope_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "allowed_data_root": str(resolved_path(config.allowed_data_root)),
        "strategy_replays": [
            {
                "family": replay.family,
                "code_commit": replay.code_commit,
                "run_root": str(resolved_path(replay.run_root)),
                "run_manifest_sha256": sha256_file(resolved_path(replay.run_root) / "t10_e2e_run_manifest.json"),
                "expected_case_ids": list(replay.expected_case_ids),
            }
            for replay in config.strategy_replays
        ],
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "excluded_business_ids": list(config.excluded_business_ids),
            "strict_hashes": config.strict_hashes,
            "verify_git_commit": config.verify_git_commit,
        },
        "environment": {"python": sys.version, "platform": platform.platform()},
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "unbounded_enumeration": False,
        "outputs": outputs,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_pto_candidate_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["build_pto_candidate_run", "canonical_edit_payload"]
