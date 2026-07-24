from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_execution import (
    _semantic_payload_signature,
    materialize_case_roadgraph,
)


def load_p2_p1_payloads(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        candidate_id = str(row["candidate_id"])
        group_id = str(row["group_id"])
        key = _candidate_key(group_id, candidate_id)
        if key in by_id:
            raise ValueError(f"duplicate P2-P1 group/candidate payload: {group_id}/{candidate_id}")
        by_id[key] = row
        by_group[group_id].append(row)
    return by_id, dict(by_group)


def materialize_p2_p1_seed(
    run_root: Path,
    *,
    seed: int,
    selections: Sequence[Mapping[str, Any]],
    payloads_by_id: Mapping[str, Mapping[str, Any]],
    payloads_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
    expected_failure_manifest: Mapping[str, frozenset[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selections:
        by_case[str(row["case_key"])].append(dict(row))
    records: list[dict[str, Any]] = []
    effective_rows: list[dict[str, Any]] = []
    for case_key in sorted(by_case):
        case_rows = by_case[case_key]
        expected_failures = expected_failure_manifest.get(case_key)
        if expected_failures is not None:
            for row in case_rows:
                row["accepted"] = False
                row["decision"] = "FALLBACK"
                row["reason"] = "expected_swsd_baseline_failure"
                if row["object_type"] == "NODE":
                    row["joint_constraint_applied"] = False
        node_rows = [row for row in case_rows if row["object_type"] == "NODE"]
        segment_rows = [row for row in case_rows if row["object_type"] == "SEGMENT"]
        effective_node_candidates, node_overrides, node_conflicts = _effective_nodes(
            node_rows, payloads_by_id, payloads_by_group
        )
        if node_conflicts:
            conflict_groups = {
                group_id for groups in node_conflicts.values() for group_id in groups
            }
            for row in node_rows:
                if str(row["group_id"]) in conflict_groups:
                    row["accepted"] = False
                    row["decision"] = "FALLBACK"
                    row["reason"] = "shared_node_payload_conflict"
            effective_node_candidates, node_overrides, remaining = _effective_nodes(
                node_rows, payloads_by_id, payloads_by_group
            )
            if remaining:
                raise ValueError(f"SWSD Node fallback remains conflicting: {case_key}")
        predictions = _segment_predictions(segment_rows, payloads_by_id, payloads_by_group)
        candidates_by_id = {
            str(candidate["candidate_id"]): dict(candidate)
            for candidate in payloads_by_id.values()
            if candidate.get("object_type") == "SEGMENT"
        }
        candidates_by_group = {
            group_id: [dict(candidate) for candidate in candidates]
            for group_id, candidates in payloads_by_group.items()
            if candidates and candidates[0].get("object_type") == "SEGMENT"
        }
        vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
        signature_cache: dict[int, str] = {}
        roadgraph = materialize_case_roadgraph(
            case_key,
            predictions,
            candidates_by_id,
            {},
            vector_cache=vector_cache,
            payload_signature_cache=signature_cache,
            node_payload_overrides=node_overrides,
            node_source_overrides={key: "p2_p1_effective_node" for key in node_overrides},
        )
        iterations: list[dict[str, Any]] = []
        if expected_failures is None:
            for iteration in range(len(predictions) + 1):
                if roadgraph["audit"]["legal"]:
                    break
                failure_groups = set(str(value) for value in roadgraph["audit"]["failure_group_ids"])
                changed = 0
                for row in predictions:
                    if str(row["group_id"]) not in failure_groups:
                        continue
                    changed += int(_fallback_segment_prediction(row, candidates_by_group[str(row["group_id"])]))
                iterations.append(
                    {
                        "iteration": iteration + 1,
                        "failure_group_count": len(failure_groups),
                        "changed_group_count": changed,
                    }
                )
                if changed == 0:
                    break
                roadgraph = materialize_case_roadgraph(
                    case_key,
                    predictions,
                    candidates_by_id,
                    {},
                    vector_cache=vector_cache,
                    payload_signature_cache=signature_cache,
                    node_payload_overrides=node_overrides,
                    node_source_overrides={key: "p2_p1_effective_node" for key in node_overrides},
                )
        actual_failures = frozenset(str(value) for value in roadgraph["audit"]["failures"])
        if expected_failures is not None:
            expected_match = actual_failures == expected_failures
            terminal_state = "EXPECTED_FAIL" if expected_match else "FAIL"
        else:
            expected_match = False
            terminal_state = "LEGAL" if roadgraph["audit"]["legal"] else "FAIL"
        roadgraph["audit"].update(
            {
                "terminal_state": terminal_state,
                "publish": terminal_state == "LEGAL",
                "expected_failure_match": expected_match,
                "hard_gate_iterations": iterations,
                "node_carrier_selection_count": len(effective_node_candidates),
                "node_payload_override_count": len(node_overrides),
                "node_conflict_count": len(node_conflicts),
                "movement_candidate_count": 0,
            }
        )
        roadgraph.pop("roadgraph_signature", None)
        roadgraph["roadgraph_signature"] = canonical_sha256(roadgraph)
        token = canonical_sha256({"case_key": case_key})[:20]
        output_path = run_root / "cases" / str(seed) / token / "roadgraph.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, roadgraph)
        records.append(
            {
                "case_key": case_key,
                "legal": bool(roadgraph["audit"]["legal"]),
                "terminal_state": terminal_state,
                "publish": terminal_state == "LEGAL",
                "expected_failure_match": expected_match,
                "failure_count": int(roadgraph["audit"]["failure_count"]),
                "roadgraph_signature": roadgraph["roadgraph_signature"],
                "output": output_record(output_path),
            }
        )
        effective_by_group = {str(row["group_id"]): row for row in predictions}
        for row in case_rows:
            updated = dict(row)
            if row["object_type"] == "SEGMENT":
                prediction = effective_by_group[str(row["group_id"])]
                updated["effective_candidate_id"] = prediction["effective_candidate_id"]
                updated["effective_target"] = prediction["effective_candidate_target"]
                if prediction["decision"] != "PUBLISH_CANDIDATE":
                    updated["accepted"] = False
                    updated["decision"] = "FALLBACK"
                    updated["reason"] = prediction["fallback_reason"]
            else:
                updated["effective_candidate_id"] = effective_node_candidates[str(row["group_id"])]
                effective_key = _candidate_key(
                    str(row["group_id"]), str(updated["effective_candidate_id"])
                )
                effective_payload = payloads_by_id.get(effective_key)
                updated["effective_target"] = (
                    effective_payload["candidate_target"] if effective_payload else "DROP"
                )
            effective_rows.append(updated)
    return records, sorted(effective_rows, key=lambda row: (int(row["seed"]), str(row["group_id"])))


def _effective_nodes(
    rows: Sequence[Mapping[str, Any]],
    payloads_by_id: Mapping[str, Mapping[str, Any]],
    payloads_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, set[str]]]:
    chosen: dict[str, str] = {}
    node_payloads: dict[str, dict[str, Any]] = {}
    owners: dict[str, set[str]] = defaultdict(set)
    signatures: dict[str, str] = {}
    conflicts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group_id = str(row["group_id"])
        selected_candidate_id = str(
            row.get("structural_candidate_id")
            if row.get("joint_constraint_applied")
            else row["selected_candidate_id"]
        )
        candidate = dict(
            _candidate(payloads_by_id, group_id, selected_candidate_id)
        )
        if not bool(row["accepted"]) and not row.get("joint_constraint_applied"):
            candidate = _safe_node_candidate(payloads_by_group[group_id])
        candidate_id = str(candidate["candidate_id"])
        chosen[group_id] = candidate_id
        for index, payload in enumerate(candidate.get("output_payloads") or []):
            output_ids = list(candidate.get("output_object_ids") or [])
            raw_node_id = (
                output_ids[index]
                if index < len(output_ids)
                else (payload.get("properties") or {}).get("id")
            )
            if raw_node_id in (None, ""):
                raise ValueError(f"Node carrier payload has no identifier: {candidate_id}")
            node_id = str(raw_node_id)
            signature = _semantic_payload_signature(payload)
            if node_id in signatures and signatures[node_id] != signature:
                conflicts[node_id].update(owners[node_id])
                conflicts[node_id].add(group_id)
                continue
            signatures[node_id] = signature
            node_payloads[node_id] = dict(payload)
            owners[node_id].add(group_id)
    return chosen, node_payloads, dict(conflicts)


def _safe_node_candidate(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    t01 = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("candidate_target") == "T01_NODE"
        and candidate.get("output_payloads")
    ]
    if t01:
        return min(t01, key=lambda row: str(row["candidate_id"]))
    omit = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("candidate_target") == "OMIT"
    ]
    if omit:
        return min(omit, key=lambda row: str(row["candidate_id"]))
    identity = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("candidate_target") == "COPY"
        and any(str(source.get("source_kind")) == "BASE_IDENTITY" for source in candidate.get("sources") or [])
    ]
    if identity:
        return min(identity, key=lambda row: str(row["candidate_id"]))
    drops = [dict(candidate) for candidate in candidates if candidate.get("candidate_target") == "DROP"]
    if drops:
        return min(drops, key=lambda row: str(row["candidate_id"]))
    group_id = str(candidates[0]["group_id"])
    return {
        "group_id": group_id,
        "candidate_id": "fallback:omit:" + canonical_sha256({"group_id": group_id})[:24],
        "candidate_target": "DROP",
        "output_payloads": [],
        "sources": [],
        "structural_fallback": True,
    }


def _segment_predictions(
    rows: Sequence[Mapping[str, Any]],
    payloads_by_id: Mapping[str, Mapping[str, Any]],
    payloads_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        candidate = dict(
            _candidate(
                payloads_by_id,
                str(row["group_id"]),
                str(row["selected_candidate_id"]),
            )
        )
        publish = bool(row["accepted"])
        if not publish:
            candidate = _safe_segment_candidate(payloads_by_group[str(row["group_id"])])
        result.append(
            {
                **dict(row),
                "decision": "PUBLISH_CANDIDATE" if publish else "HARD_FALLBACK",
                "fallback_reason": "" if publish else str(row["reason"]),
                "effective_candidate_id": str(candidate["candidate_id"]),
                "effective_candidate_target": str(candidate["candidate_target"]),
                "effective_source_kind": "SWSD_IDENTITY"
                if candidate["candidate_target"] == "KEEP_SWSD"
                else "REGISTERED_STRATEGY_PROPOSAL",
                "effective_target_kind": str(candidate["target_kind"]),
                "effective_target_payload": list(candidate.get("target_payload") or []),
            }
        )
    return result


def _safe_segment_candidate(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    safe = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("candidate_target") == "KEEP_SWSD" and candidate.get("target_payload")
    ]
    if not safe:
        raise ValueError(f"Segment group has no SWSD fallback: {candidates[0]['group_id']}")
    return min(safe, key=lambda row: str(row["candidate_id"]))


def _fallback_segment_prediction(
    row: dict[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> bool:
    safe = _safe_segment_candidate(candidates)
    before = str(row["effective_candidate_id"])
    row.update(
        {
            "decision": "HARD_FALLBACK",
            "fallback_reason": "roadgraph_hard_gate_conflict",
            "effective_candidate_id": str(safe["candidate_id"]),
            "effective_candidate_target": "KEEP_SWSD",
            "effective_source_kind": "SWSD_IDENTITY",
            "effective_target_kind": str(safe["target_kind"]),
            "effective_target_payload": list(safe.get("target_payload") or []),
        }
    )
    return before != str(safe["candidate_id"])


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _candidate_key(group_id: str, candidate_id: str) -> str:
    return f"{group_id}\x1f{candidate_id}"


def _candidate(
    payloads_by_id: Mapping[str, Mapping[str, Any]], group_id: str, candidate_id: str
) -> Mapping[str, Any]:
    key = _candidate_key(group_id, candidate_id)
    if key not in payloads_by_id:
        raise ValueError(f"candidate is outside frozen group: {group_id}/{candidate_id}")
    return payloads_by_id[key]


__all__ = ["load_p2_p1_payloads", "materialize_p2_p1_seed"]
