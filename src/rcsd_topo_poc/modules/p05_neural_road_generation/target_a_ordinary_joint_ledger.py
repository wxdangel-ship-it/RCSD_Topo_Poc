from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_RESOLVED_NO_ACCESS_STATES = frozenset(
    {
        "DETACHED_JUNC_NODE_NO_ACCESS_REQUIRED",
        "EXEMPT_JUNC_NODE_NO_REQUIRED_ACCESS",
    }
)
_ALLOWED_PLAN_DECISIONS = frozenset(
    {
        "KEEP_SWSD",
        "USE_RCSD",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
        "ABSTAIN",
    }
)


def build_ordinary_joint_ledger_store(
    *,
    candidate_store_root: Path,
    plan_label_root: Path,
    road_member_store_root: Path,
    access_collection_store_root: Path,
    break_task_store_root: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    """Join all ordinary Segment supervision once without copying truth to inputs.

    The ledger is label-side metadata. Inference evidence remains in the source
    feature stores referenced by the manifest and is never augmented with any
    terminal label. Missing field supervision is represented by an explicit
    task mask; it is never converted to a negative target.
    """

    started = time.perf_counter()
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    plan_root = normalize_runtime_path(plan_label_root).resolve(strict=True)
    road_root = normalize_runtime_path(road_member_store_root).resolve(
        strict=True
    )
    access_root = normalize_runtime_path(access_collection_store_root).resolve(
        strict=True
    )
    break_root = normalize_runtime_path(break_task_store_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve(strict=False) / run_id
    root.mkdir(parents=True, exist_ok=False)

    candidate_path = candidate_root / "inference_plan_groups.jsonl"
    plan_path = plan_root / "training_plan_labels.jsonl"
    road_feature_path = road_root / "ordinary_road_member_features.jsonl"
    road_label_path = road_root / "ordinary_road_member_labels.jsonl"
    access_path = access_root / "ordinary_access_collection_labels.jsonl"
    break_path = break_root / "parent_road_break_tasks.jsonl"

    candidates = _unique_index(
        (
            row
            for row in _read_jsonl(candidate_path)
            if str(row.get("segment_type")) == "STANDARD"
        ),
        label="ordinary candidate group",
    )
    plans = _unique_index(
        (
            row
            for row in _read_jsonl(plan_path)
            if str(row.get("segment_type")) == "STANDARD"
        ),
        label="ordinary plan label",
    )
    road_labels = _unique_index(
        _read_jsonl(road_label_path),
        label="ordinary Road label",
    )
    road_ids = _road_candidate_ids(road_feature_path)
    access_by_segment = _group_by_segment(
        _read_jsonl(access_path),
        identity_name="junction_id",
        identity_field="junction_id",
    )
    breaks_by_segment = _group_by_segment(
        _read_jsonl(break_path),
        identity_name="raw_parent_road_id",
        identity_field="raw_parent_road_id",
    )

    missing_plan = sorted(set(candidates) - set(plans))
    missing_road_label = sorted(set(candidates) - set(road_labels))
    missing_road_ids = sorted(set(candidates) - set(road_ids))
    if missing_plan or missing_road_label or missing_road_ids:
        raise ValueError(
            "ordinary joint ledger lacks required source rows: "
            f"plan={missing_plan[:3]}, road_label={missing_road_label[:3]}, "
            f"road_feature={missing_road_ids[:3]}"
        )

    counts: Counter[str] = Counter()
    field_counts: dict[str, Counter[str]] = defaultdict(Counter)
    rows = []
    for key in sorted(candidates):
        group = candidates[key]
        plan = plans[key]
        road_label = road_labels[key]
        candidate_road_ids = road_ids[key]
        access_rows = access_by_segment.get(key, ())
        break_rows = breaks_by_segment.get(key, ())
        _validate_shared_identity(
            key,
            group=group,
            plan=plan,
            road_label=road_label,
            access_rows=access_rows,
            break_rows=break_rows,
        )
        if len(candidate_road_ids) != len(
            road_label.get("road_business_role_targets") or ()
        ):
            raise ValueError(f"Road role label width differs: {key}")
        if len(candidate_road_ids) != len(
            road_label.get("road_ownership_targets") or ()
        ):
            raise ValueError(f"Road ownership label width differs: {key}")

        candidate_semantics = _candidate_plan_semantics(group)
        plan_label = _plan_label_payload(plan)
        road_payload = _road_label_payload(
            road_label,
            candidate_road_ids=candidate_road_ids,
        )
        access_payload = tuple(_access_label_payload(row) for row in access_rows)
        break_payload = tuple(_break_label_payload(row) for row in break_rows)
        coverage = _field_coverage(
            group=group,
            plan=plan_label,
            road=road_payload,
            access=access_payload,
            breaks=break_payload,
        )
        row = {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "case_key": key[0],
            "segment_id": key[1],
            "fold": int(plan["fold"]),
            "required_anchor_ids": [
                str(value) for value in group.get("required_anchor_ids") or ()
            ],
            "junc_node_ids": [
                str(value) for value in group.get("junc_node_ids") or ()
            ],
            "candidate_plans": candidate_semantics,
            "plan_label": plan_label,
            "road_label": road_payload,
            "access_labels": access_payload,
            "break_labels": break_payload,
            "field_coverage": coverage,
            "label_only": True,
            "inference_input_allowed": False,
            "feature_uses_truth": False,
            "terminal_input_count": 0,
        }
        rows.append(row)
        counts["ordinary_segment"] += 1
        counts[f"plan_decision_{plan_label['preferred_decision'] or 'UNKNOWN'}"] += 1
        for field, value in coverage.items():
            if isinstance(value, bool):
                field_counts[field]["true" if value else "false"] += 1
        counts["access_object"] += len(access_payload)
        counts["break_parent"] += len(break_payload)

    ledger_path = root / "ordinary_joint_ledger.jsonl"
    _write_jsonl(ledger_path, rows)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "TARGET_A_ORDINARY_JOINT_LEDGER",
        "run_id": run_id,
        "scope": "STANDARD Segment only; AdvanceRight and Movement are excluded",
        "business_contract": {
            "anchor": (
                "required SWSD semantic anchors remain the model-internal hard "
                "predecessor of ordinary carrier output"
            ),
            "positive_keep": (
                "KEEP_SWSD is a positive plan decision and remains distinct "
                "from ABSTAIN fallback"
            ),
            "mixed": (
                "only T06_MAIN_RCSD_ATTACHED_SWSD is admitted; no generic HYBRID"
            ),
            "partial_labels": (
                "missing role, ownership, access, or break truth is masked and "
                "never converted to a negative label"
            ),
            "leakage": (
                "the ledger is label-only; all terminal fields are forbidden "
                "as inference inputs"
            ),
        },
        "counts": dict(sorted(counts.items())),
        "field_coverage": {
            field: dict(sorted(values.items()))
            for field, values in sorted(field_counts.items())
        },
        "io_contract": {
            "candidate_store_reads": 1,
            "plan_label_store_reads": 1,
            "road_feature_store_reads": 1,
            "road_label_store_reads": 1,
            "access_label_store_reads": 1,
            "break_task_store_reads": 1,
            "join": "in-memory key join; no per-Segment source-file reread",
        },
        "inputs": {
            "candidate_groups": _input_record(candidate_path),
            "plan_labels": _input_record(plan_path),
            "road_features": _input_record(road_feature_path),
            "road_labels": _input_record(road_label_path),
            "access_labels": _input_record(access_path),
            "break_tasks": _input_record(break_path),
        },
        "outputs": {"ledger": _input_record(ledger_path)},
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "gate_pass": (
            len(rows) == len(candidates)
            and all(row["label_only"] for row in rows)
            and not any(row["inference_input_allowed"] for row in rows)
            and not any(row["feature_uses_truth"] for row in rows)
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    summary_path = root / "summary.json"
    _write_json(summary_path, summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary joint ledger gate failed")
    return root


def _candidate_plan_semantics(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    ids: set[str] = set()
    for candidate in group.get("candidates") or ():
        plan_id = str(candidate.get("plan_id") or "")
        decision = str(candidate.get("decision") or "")
        if not plan_id or plan_id in ids:
            raise ValueError("ordinary candidate plan identity is empty or repeated")
        if decision not in _ALLOWED_PLAN_DECISIONS:
            raise ValueError(f"ordinary candidate decision is unsupported: {decision}")
        ids.add(plan_id)
        road_ids = tuple(str(value) for value in candidate.get("road_ids") or ())
        role_by_road = {
            str(row["road_id"]): str(row["role"])
            for row in candidate.get("road_roles") or ()
        }
        if set(role_by_road) != set(road_ids):
            if decision != "ABSTAIN" or road_ids or role_by_road:
                raise ValueError("candidate Road roles differ from its complete Road set")
        arms = list(candidate.get("arm_rows") or ())
        rows.append(
            {
                "plan_id": plan_id,
                "decision": decision,
                "road_ids": list(road_ids),
                "road_roles": [
                    {"road_id": road_id, "role": role_by_road[road_id]}
                    for road_id in road_ids
                ],
                "owned_road_ids": [
                    str(value) for value in candidate.get("owned_road_ids") or ()
                ],
                "access_road_ids": [
                    str(row.get("nearest_road_id") or "") for row in arms
                ],
                "access_node_ids": [
                    str(row.get("nearest_node_id") or "") for row in arms
                ],
                "internal_connector_road_ids": [
                    str(value)
                    for value in candidate.get("internal_connector_road_ids") or ()
                ],
                "hard_valid": bool(candidate.get("hard_valid")),
            }
        )
    if not rows:
        raise ValueError("ordinary Segment has no plan candidates")
    return rows


def _plan_label_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_mask": bool(row.get("training_task_mask")),
        "carrier_task_mask": bool(row.get("carrier_task_mask", True)),
        "label_weight": float(row.get("label_weight") or 0.0),
        "acceptable_plan_ids": [
            str(value) for value in row.get("acceptable_plan_ids") or ()
        ],
        "preferred_plan_id": str(row.get("preferred_plan_id") or ""),
        "preferred_decision": str(row.get("preferred_carrier_target") or ""),
        "clue": row.get("reality_change_clue"),
        "clue_task_mask": bool(row.get("clue_task_mask")),
        "fallback_scope": row.get("fallback_scope"),
        "fallback_scope_task_mask": bool(row.get("fallback_scope_task_mask")),
        "mask_reason": str(row.get("mask_reason") or ""),
        "label_origin": str(row.get("label_origin") or ""),
    }


def _road_label_payload(
    row: Mapping[str, Any],
    *,
    candidate_road_ids: Sequence[str],
) -> dict[str, Any]:
    role_targets = list(row.get("road_business_role_targets") or ())
    role_masks = list(row.get("road_business_role_task_mask") or ())
    ownership_targets = list(row.get("road_ownership_targets") or ())
    ownership_masks = list(row.get("road_ownership_task_mask") or ())
    member_weights = list(row.get("road_member_sample_weights") or ())
    expected = len(candidate_road_ids)
    if any(
        len(values) != expected
        for values in (role_targets, role_masks, ownership_targets, ownership_masks, member_weights)
    ):
        raise ValueError("ordinary Road label arrays differ from candidates")
    return {
        "task_mask": bool(row.get("task_mask")),
        "sample_weight": float(row.get("sample_weight") or 0.0),
        "acceptable_road_ids": [
            str(value) for value in row.get("acceptable_road_ids") or ()
        ],
        "candidate_road_ids": list(candidate_road_ids),
        "member_sample_weights": [float(value) for value in member_weights],
        "role_targets": [int(value) for value in role_targets],
        "role_task_mask": [bool(value) for value in role_masks],
        "role_sample_weight": float(
            row.get("road_business_role_sample_weight") or 0.0
        ),
        "ownership_targets": [int(value) for value in ownership_targets],
        "ownership_task_mask": [bool(value) for value in ownership_masks],
        "ownership_sample_weight": float(
            row.get("road_ownership_sample_weight") or 0.0
        ),
        "unreachable_target_road_ids": [
            str(value) for value in row.get("unreachable_target_road_ids") or ()
        ],
    }


def _access_label_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "junction_id": str(row.get("junction_id") or ""),
        "task_mask": bool(row.get("collection_task_mask")),
        "label_weight": float(row.get("collection_label_weight") or 0.0),
        "label_state": str(row.get("collection_label_state") or ""),
        "required_final_road_ids": [
            str(value) for value in row.get("required_final_road_ids") or ()
        ],
        "required_final_access_node_ids": [
            str(value)
            for value in row.get("required_final_access_node_ids") or ()
        ],
        "acceptable_access_collections": list(
            row.get("acceptable_access_collections") or ()
        ),
        "manual_review_required": bool(row.get("manual_review_required")),
    }


def _break_label_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "raw_parent_road_id": str(row.get("raw_parent_road_id") or ""),
        "task_mask": bool(row.get("task_mask")),
        "sample_weight": float(row.get("sample_weight") or 0.0),
        "target_state": str(row.get("target_state") or ""),
        "truth_break_count": int(row.get("truth_break_count") or 0),
        "truth_break_fractions": [
            float(value) for value in row.get("truth_break_fractions") or ()
        ],
        "truth_ownership": str(row.get("truth_ownership") or ""),
    }


def _field_coverage(
    *,
    group: Mapping[str, Any],
    plan: Mapping[str, Any],
    road: Mapping[str, Any],
    access: Sequence[Mapping[str, Any]],
    breaks: Sequence[Mapping[str, Any]],
) -> dict[str, bool | int]:
    acceptable_roads = set(str(value) for value in road["acceptable_road_ids"])
    candidate_road_ids = list(str(value) for value in road["candidate_road_ids"])
    role_by_id = {
        road_id: bool(mask)
        for road_id, mask in zip(
            candidate_road_ids, road["role_task_mask"], strict=True
        )
    }
    owner_by_id = {
        road_id: bool(mask)
        for road_id, mask in zip(
            candidate_road_ids, road["ownership_task_mask"], strict=True
        )
    }
    role_complete = bool(acceptable_roads) and all(
        role_by_id.get(road_id, False) for road_id in acceptable_roads
    )
    ownership_complete = bool(acceptable_roads) and all(
        owner_by_id.get(road_id, False) for road_id in acceptable_roads
    )
    expected_junctions = {
        str(value) for value in group.get("junc_node_ids") or ()
    }
    access_by_junction = {
        str(row["junction_id"]): row for row in access
    }
    access_complete = bool(expected_junctions) and all(
        junction_id in access_by_junction
        and (
            bool(access_by_junction[junction_id]["task_mask"])
            or str(access_by_junction[junction_id]["label_state"])
            in _RESOLVED_NO_ACCESS_STATES
        )
        for junction_id in expected_junctions
    )
    preferred = str(plan.get("preferred_decision") or "")
    break_needed = preferred in {
        "USE_RCSD",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
    }
    break_complete = (
        not break_needed
        or (bool(breaks) and all(bool(row["task_mask"]) for row in breaks))
    )
    plan_supervised = bool(plan.get("task_mask"))
    road_member_supervised = bool(road.get("task_mask"))
    return {
        "plan_supervised": plan_supervised,
        "road_member_supervised": road_member_supervised,
        "role_complete_for_truth_roads": role_complete,
        "ownership_complete_for_truth_roads": ownership_complete,
        "access_complete_for_required_junctions": access_complete,
        "break_complete_for_required_parent_roads": break_complete,
        "clue_supervised": bool(plan.get("clue_task_mask")),
        "fallback_scope_supervised": bool(
            plan.get("fallback_scope_task_mask")
        ),
        "full_business_evaluable": (
            plan_supervised
            and road_member_supervised
            and role_complete
            and ownership_complete
            and access_complete
            and break_complete
        ),
        "access_label_count": len(access),
        "break_label_count": len(breaks),
    }


def _road_candidate_ids(path: Path) -> dict[tuple[str, str], tuple[str, ...]]:
    result: dict[tuple[str, str], tuple[str, ...]] = {}
    for row in _read_jsonl(path):
        key = _key(row)
        if key in result:
            raise ValueError(f"duplicate ordinary Road feature row: {key}")
        result[key] = tuple(
            str(candidate["road_id"])
            for candidate in row.get("candidate_rows") or ()
        )
    return result


def _unique_index(
    rows: Iterable[Mapping[str, Any]],
    *,
    label: str,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = _key(row)
        if key in result:
            raise ValueError(f"duplicate {label}: {key}")
        result[key] = row
    return result


def _group_by_segment(
    rows: Iterable[Mapping[str, Any]],
    *,
    identity_name: str,
    identity_field: str,
) -> dict[tuple[str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = _key(row)
        identity = str(row.get(identity_field) or "")
        unique = (*key, identity)
        if not identity or unique in seen:
            raise ValueError(f"empty or duplicate {identity_name}: {unique}")
        seen.add(unique)
        grouped[key].append(row)
    return {
        key: tuple(sorted(values, key=lambda row: str(row[identity_field])))
        for key, values in grouped.items()
    }


def _validate_shared_identity(
    key: tuple[str, str],
    *,
    group: Mapping[str, Any],
    plan: Mapping[str, Any],
    road_label: Mapping[str, Any],
    access_rows: Sequence[Mapping[str, Any]],
    break_rows: Sequence[Mapping[str, Any]],
) -> None:
    folds = {
        int(row["fold"])
        for row in (group, plan, road_label, *access_rows, *break_rows)
        if row.get("fold") is not None
    }
    if len(folds) != 1:
        raise ValueError(f"ordinary joint ledger fold differs: {key}/{folds}")


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["segment_id"])


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _input_record(path: Path) -> dict[str, str | int]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


__all__ = ["build_ordinary_joint_ledger_store"]
