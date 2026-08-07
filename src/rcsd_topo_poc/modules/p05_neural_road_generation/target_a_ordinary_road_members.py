from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_business_adjudications import (
    user_road_membership_adjudication,
    user_road_role_adjudication,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access import (
    _parse_id_list,
    normalized_final_road_id,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
    build_ordinary_plan_member_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_relations import (
    ROAD_RELATION_FEATURE_NAMES,
    build_sparse_road_relation_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_candidates import (
    _read_points,
    _read_roads,
    _read_segments,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ROAD_MEMBER_ANCHOR_RELATION_NAMES = (
    "road_is_selected_anchor_member",
    "start_is_selected_anchor_node",
    "end_is_selected_anchor_node",
    "touches_selected_anchor",
)
ROAD_MEMBER_EXTRA_FEATURE_NAMES = (
    "source_is_swsd",
    "source_is_rcsd",
    "existing_plan_frequency",
    "in_existing_plan_pool",
    *[f"all_candidate_{value}" for value in ROAD_MEMBER_ANCHOR_RELATION_NAMES],
)
ROAD_OWNERSHIP_LABELS = (
    "EXCLUDE_OR_OTHER_OWNER",
    "OWNER_CURRENT_SEGMENT",
    "NO_OWNER_JUNCTION_CONNECTIVITY",
)
ROAD_BUSINESS_ROLE_LABELS = (
    "NOT_SELECTED_FOR_CURRENT_SEGMENT",
    "MAIN",
    "INTERNAL_CONNECTOR",
    "ATTACHED_SWSD",
)


def build_anchor_conditioned_ordinary_road_member_store(
    *,
    plan_candidate_store_root: Path,
    plan_label_root: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    access_store_root: Path,
    output_root: Path,
) -> Path:
    """Build member-level Road pools without enumerating complete Road plans."""
    started = time.perf_counter()
    candidate_root = normalize_runtime_path(
        plan_candidate_store_root
    ).resolve(strict=True)
    label_root = normalize_runtime_path(plan_label_root).resolve(strict=True)
    anchor_root = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    oof_root = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    access_root = normalize_runtime_path(access_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    plan_labels = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(
            label_root / "training_plan_labels.jsonl"
        )
    }
    anchor_features = {
        (str(row["case_key"]), str(row["anchor_id"])): row
        for row in _read_jsonl(
            anchor_root
            / "inference_feature_store"
            / "anchor_features.jsonl"
        )
    }
    anchor_labels = {
        str(row["sample_id"]): row
        for row in _read_jsonl(
            anchor_root / "training_label_store" / "anchor_labels.jsonl"
        )
    }
    anchor_oof = {
        (str(row["case_key"]), str(row["anchor_id"])): row
        for row in _read_jsonl(oof_root / "oof_predictions.jsonl")
    }
    lineage_paths = _candidate_lineage_paths(candidate_root)
    final_paths = _final_road_paths(access_root / "summary.json")
    group_path = candidate_root / "inference_plan_groups.jsonl"
    feature_path = root / "ordinary_road_member_features.jsonl"
    label_path = root / "ordinary_road_member_labels.jsonl"
    feature_stream = feature_path.open("w", encoding="utf-8")
    labels = []
    counts: Counter[str] = Counter()
    input_records = []
    current_case = ""
    case_data: dict[str, Any] = {}
    with group_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            group = json.loads(line)
            if str(group["segment_type"]) != "STANDARD":
                continue
            case_key = str(group["case_key"])
            if case_key != current_case:
                current_case = case_key
                case_data, records = _load_case_data(
                    case_key,
                    lineage_paths[case_key],
                    final_paths[case_key],
                )
                input_records.extend(records)
            key = (case_key, str(group["segment_id"]))
            plan_label = plan_labels[key]
            segment = case_data["segment_by_id"].get(key[1])
            if segment is None:
                raise ValueError(f"ordinary Road member Segment missing: {key}")
            required_anchor_ids = tuple(
                sorted(str(value) for value in group["required_anchor_ids"])
            )
            all_road_ids, all_node_ids = _all_anchor_candidate_members(
                case_key,
                required_anchor_ids,
                anchor_features,
            )
            teacher = _teacher_anchor_members(
                case_key,
                required_anchor_ids,
                anchor_features,
                anchor_labels,
            )
            oof = _oof_anchor_members(
                case_key,
                required_anchor_ids,
                anchor_oof,
            )
            incident = case_data["incident_raw_roads"]
            anchor_pool = set(all_road_ids)
            for node_id in all_node_ids:
                anchor_pool.update(incident.get(node_id, ()))
            plan_frequency: Counter[str] = Counter(
                str(road_id)
                for candidate in group["candidates"]
                for road_id in candidate.get("road_ids") or ()
            )
            raw_pool = (
                set(plan_frequency)
                | anchor_pool
            ) & set(case_data["raw_road_by_id"])
            swsd_pool = set(segment["swsd_road_ids"]) & set(
                case_data["swsd_road_by_id"]
            )
            candidate_rows = _member_candidate_rows(
                group=group,
                segment=segment,
                raw_pool=raw_pool,
                swsd_pool=swsd_pool,
                plan_frequency=plan_frequency,
                all_anchor=(all_road_ids, all_node_ids),
                teacher_anchor=(teacher["road_ids"], teacher["node_ids"]),
                oof_anchor=(oof["road_ids"], oof["node_ids"]),
                teacher_anchor_selections=teacher["selections"],
                oof_anchor_selections=oof["selections"],
                case_data=case_data,
            )
            road_relation_rows = build_sparse_road_relation_rows(
                candidate_rows,
                raw_road_by_id=case_data["raw_road_by_id"],
                swsd_road_by_id=case_data["swsd_road_by_id"],
            )
            target_ids, target_state = _target_road_ids(
                plan_label,
                segment=segment,
                raw_road_ids=set(case_data["raw_road_by_id"]),
                swsd_road_ids=set(case_data["swsd_road_by_id"]),
                final_normalization=case_data["final_normalization"],
            )
            candidate_ids = {
                str(row["road_id"]) for row in candidate_rows
            }
            manual_membership = user_road_membership_adjudication(
                case_key,
                key[1],
            )
            manual_member_weights: dict[str, float] = {}
            if manual_membership is not None:
                for road_id, ownership in (
                    manual_membership.road_memberships
                ):
                    if road_id not in candidate_ids:
                        raise ValueError(
                            "manual Road member is absent from candidate "
                            f"pool: {case_key}/{key[1]}/{road_id}"
                        )
                    if ownership == "OWNER_CURRENT_SEGMENT":
                        target_ids.add(road_id)
                    elif ownership == "EXCLUDE_OR_OTHER_OWNER":
                        target_ids.discard(road_id)
                    else:
                        raise ValueError(
                            "manual Road membership status is unsupported: "
                            f"{ownership}"
                        )
                    manual_member_weights[road_id] = float(
                        manual_membership.sample_weight
                    )
            unreachable = sorted(target_ids - candidate_ids)
            label_task = bool(plan_label.get("label_task_mask"))
            teacher_ready = bool(teacher["ready"])
            task_mask = bool(
                label_task
                and teacher_ready
                and target_ids
                and not unreachable
            )
            business_targets = ordinary_road_business_role_targets(
                candidate_rows,
                case_key=case_key,
                segment_id=key[1],
                target_ids=target_ids,
                target_state=target_state,
                relation=case_data["relation_by_segment"].get(key[1]),
                candidate_plans=group.get("candidates") or (),
                final_normalization=case_data["final_normalization"],
            )
            base_sample_weight = (
                float(plan_label.get("label_weight") or 0.0)
                if task_mask
                else 0.0
            )
            ownership_sample_weight = (
                float(
                    business_targets[
                        "manual_ownership_adjudication_weight"
                    ]
                )
                if task_mask
                and float(
                    business_targets[
                        "manual_ownership_adjudication_weight"
                    ]
                )
                > 0.0
                else base_sample_weight
            )
            business_role_sample_weight = (
                float(business_targets["manual_role_adjudication_weight"])
                if task_mask
                and float(
                    business_targets["manual_role_adjudication_weight"]
                )
                > 0.0
                else base_sample_weight
            )
            member_sample_weights = [
                (
                    manual_member_weights.get(
                        str(row["road_id"]),
                        base_sample_weight,
                    )
                    if task_mask
                    else 0.0
                )
                for row in candidate_rows
            ]
            feature_row = {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "segment_id": key[1],
                "fold": int(plan_label["fold"]),
                "required_anchor_ids": list(required_anchor_ids),
                "anchor_role_feature_values": ordinary_anchor_role_features(
                    required_anchor_ids,
                    tuple(
                        str(value)
                        for value in group.get("arm_anchor_ids") or ()
                    ),
                ),
                "object_feature_values": [
                    float(value) for value in group["object_features"]
                ],
                "candidate_rows": candidate_rows,
                "road_relation_rows": road_relation_rows,
                "teacher_anchor_ready": teacher_ready,
                "oof_anchor_release_ready": bool(oof["release_ready"]),
                "feature_uses_truth": False,
                "terminal_input_count": 0,
            }
            feature_stream.write(
                json.dumps(feature_row, ensure_ascii=False, sort_keys=True)
            )
            feature_stream.write("\n")
            label_row = {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "segment_id": key[1],
                "fold": int(plan_label["fold"]),
                "preferred_decision": str(
                    plan_label.get("preferred_carrier_target") or ""
                ),
                "acceptable_road_ids": sorted(target_ids),
                "target_state": target_state,
                "task_mask": task_mask,
                "sample_weight": base_sample_weight,
                "road_member_sample_weights": member_sample_weights,
                "teacher_anchor_ready": teacher_ready,
                "oof_anchor_release_ready": bool(oof["release_ready"]),
                "unreachable_target_road_ids": unreachable,
                "road_ownership_targets": (
                    business_targets["ownership_targets"]
                ),
                "road_ownership_task_mask": (
                    business_targets["ownership_task_mask"]
                    if task_mask
                    else [False] * len(candidate_rows)
                ),
                "road_business_role_targets": (
                    business_targets["business_role_targets"]
                ),
                "road_business_role_task_mask": (
                    business_targets["business_role_task_mask"]
                    if task_mask
                    else [False] * len(candidate_rows)
                ),
                "road_ownership_sample_weight": ownership_sample_weight,
                "road_business_role_sample_weight": (
                    business_role_sample_weight
                ),
                "manual_road_membership_adjudication_count": len(
                    manual_member_weights
                ),
                "manual_road_role_adjudication_count": int(
                    business_targets[
                        "manual_role_adjudication_count"
                    ]
                ),
                "label_only": True,
                "inference_input_allowed": False,
            }
            labels.append(label_row)
            counts["segment"] += 1
            counts[f"decision_{label_row['preferred_decision']}"] += 1
            counts["label_task"] += int(label_task)
            counts["teacher_anchor_ready"] += int(teacher_ready)
            counts["oof_anchor_release_ready"] += int(oof["release_ready"])
            counts["member_task"] += int(task_mask)
            counts["manual_road_role_adjudication"] += int(
                label_row["manual_road_role_adjudication_count"]
            )
            counts["manual_road_membership_adjudication"] += int(
                label_row["manual_road_membership_adjudication_count"]
            )
            counts["candidate_road"] += len(candidate_rows)
            counts["road_relation_pair"] += len(road_relation_rows)
            counts["target_road"] += len(target_ids)
            counts["covered_target_road"] += len(target_ids) - len(unreachable)
            counts["candidate_unreachable_segment"] += int(bool(unreachable))
            for label_index, enabled in zip(
                label_row["road_ownership_targets"],
                label_row["road_ownership_task_mask"],
            ):
                if enabled:
                    counts[
                        "ownership_"
                        + ROAD_OWNERSHIP_LABELS[int(label_index)]
                    ] += 1
            for label_index, enabled in zip(
                label_row["road_business_role_targets"],
                label_row["road_business_role_task_mask"],
            ):
                if enabled:
                    counts[
                        "business_role_"
                        + ROAD_BUSINESS_ROLE_LABELS[int(label_index)]
                    ] += 1
    feature_stream.close()
    feature_hash_before_label_read = sha256_file(feature_path)
    _write_jsonl(label_path, labels)
    coverage = (
        counts["covered_target_road"] / counts["target_road"]
        if counts["target_road"]
        else 0.0
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ANCHOR_CONDITIONED_ROAD_MEMBER_STORE",
        "business_contract": {
            "candidate_pool": (
                "The pool is the union of truth-free legacy path candidates "
                "and Roads/incident Roads exposed by every anchor candidate. "
                "The selected anchor remains a separate hard condition."
            ),
            "output": (
                "Select the complete SWSD or raw RCSD Road member set. Final "
                "split IDs are normalized to their original raw RCSD Road."
            ),
            "teacher": (
                "Teacher forcing uses one independently preferred anchor "
                "object per required anchor, or explicitly proven "
                "NO_EVIDENCE; acceptable alternatives are never unioned."
            ),
            "inference": (
                "OOF selected-anchor relations and release state come only "
                "from the anchor model; Road membership cannot change anchor."
            ),
        },
        "base_member_feature_dim": ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
        "extra_feature_names": list(ROAD_MEMBER_EXTRA_FEATURE_NAMES),
        "selected_anchor_relation_names": list(
            ROAD_MEMBER_ANCHOR_RELATION_NAMES
        ),
        "road_ownership_labels": list(ROAD_OWNERSHIP_LABELS),
        "road_business_role_labels": list(ROAD_BUSINESS_ROLE_LABELS),
        "road_relation_feature_names": list(ROAD_RELATION_FEATURE_NAMES),
        "road_relation_feature_dim": len(ROAD_RELATION_FEATURE_NAMES),
        "road_relation_storage": (
            "sparse undirected pairs within 25m or sharing endpoint; "
            "dense tensors are reconstructed per batch"
        ),
        "anchor_role_feature_names": [
            "is_source_arm_anchor",
            "is_target_arm_anchor",
            "is_internal_anchor",
        ],
        "per_anchor_relation_names": list(
            ROAD_MEMBER_ANCHOR_RELATION_NAMES
        ),
        "candidate_feature_dim": (
            ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM
            + len(ROAD_MEMBER_EXTRA_FEATURE_NAMES)
            + 2 * len(ROAD_MEMBER_ANCHOR_RELATION_NAMES)
        ),
        "counts": dict(sorted(counts.items())),
        "target_road_candidate_coverage": coverage,
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": feature_hash_before_label_read,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "io_contract": (
            "Each Case raw/T01/final Road store is loaded once while Segment "
            "groups are streamed in Case order."
        ),
        "inputs": {
            "plan_candidate_manifest": _input_record(
                candidate_root / "manifest.json"
            ),
            "plan_labels": _input_record(
                label_root / "training_plan_labels.jsonl"
            ),
            "anchor_manifest": _input_record(anchor_root / "manifest.json"),
            "anchor_oof_summary": _input_record(oof_root / "summary.json"),
            "access_summary": _input_record(access_root / "summary.json"),
            "case_inputs": input_records,
        },
        "outputs": {
            "features": _input_record(feature_path),
            "labels": _input_record(label_path),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(labels) == counts["segment"]
            and counts["candidate_road"] > 0
            and sha256_file(feature_path) == feature_hash_before_label_read
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary Road member store gate failed")
    return root


def normalize_complete_target_ids(
    road_ids: Sequence[str],
    *,
    final_normalization: Mapping[str, str],
) -> set[str]:
    return {
        str(final_normalization.get(str(road_id), str(road_id)))
        for road_id in road_ids
        if str(road_id)
    }


def ordinary_road_business_role_targets(
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    case_key: str = "",
    segment_id: str = "",
    target_ids: set[str],
    target_state: str,
    relation: Mapping[str, Any] | None,
    candidate_plans: Sequence[Mapping[str, Any]],
    final_normalization: Mapping[str, str],
) -> dict[str, list[int] | list[bool] | float | int]:
    """Build label-only Road ownership and business-role supervision."""
    candidate_ids = [str(row["road_id"]) for row in candidate_rows]
    supported = target_state in {
        "KEEP_SWSD",
        "USE_RCSD_NORMALIZED_RAW",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
    }
    source_by_id = {
        str(row["road_id"]): str(row.get("source") or "")
        for row in candidate_rows
    }
    ownership_by_id = {
        road_id: "OWNER_CURRENT_SEGMENT"
        if road_id in target_ids
        else "EXCLUDE_OR_OTHER_OWNER"
        for road_id in candidate_ids
    }
    business_role_by_id = {
        road_id: "NOT_SELECTED_FOR_CURRENT_SEGMENT"
        for road_id in candidate_ids
    }
    business_role_known = {
        road_id: road_id not in target_ids for road_id in candidate_ids
    }
    if target_state == "KEEP_SWSD":
        for road_id in target_ids:
            business_role_by_id[road_id] = "MAIN"
            business_role_known[road_id] = True
    role_target_ids = target_ids
    role_target_state = target_state
    if target_state == "T06_MAIN_RCSD_ATTACHED_SWSD":
        attached_swsd_ids = {
            road_id
            for road_id in target_ids
            if source_by_id.get(road_id) == "SWSD"
        }
        for road_id in attached_swsd_ids:
            business_role_by_id[road_id] = "ATTACHED_SWSD"
            business_role_known[road_id] = True
        role_target_ids = {
            road_id
            for road_id in target_ids
            if source_by_id.get(road_id) == "RCSD"
        }
        role_target_state = "USE_RCSD_NORMALIZED_RAW"
    if relation is not None:
        connectivity_ids = _normalized_relation_ids(
            relation,
            (
                "related_special_junction_internal_road_ids",
                "related_connectivity_road_ids",
            ),
            final_normalization=final_normalization,
        ) - target_ids
        for road_id in connectivity_ids & set(candidate_ids):
            ownership_by_id[road_id] = "NO_OWNER_JUNCTION_CONNECTIVITY"
            business_role_known[road_id] = True
    preferred_roles = _preferred_candidate_roles(
        candidate_plans,
        target_ids=role_target_ids,
        target_state=role_target_state,
        final_normalization=final_normalization,
    )
    for road_id, role in preferred_roles.items():
        if road_id not in target_ids or role not in {
            "MAIN",
            "INTERNAL_CONNECTOR",
            "ATTACHED_SWSD",
        }:
            continue
        business_role_by_id[road_id] = role
        business_role_known[road_id] = True
    manual_role = (
        user_road_role_adjudication(case_key, segment_id)
        if case_key and segment_id
        else None
    )
    manual_membership = (
        user_road_membership_adjudication(case_key, segment_id)
        if case_key and segment_id
        else None
    )
    manual_role_ids: set[str] = set()
    manual_ownership_ids: set[str] = set()
    if manual_role is not None:
        for road_id, role in manual_role.road_roles:
            if road_id not in candidate_ids:
                raise ValueError(
                    "manual Road role object is absent from candidate pool: "
                    f"{case_key}/{segment_id}/{road_id}"
                )
            if road_id not in target_ids:
                raise ValueError(
                    "manual owner Road is absent from complete target: "
                    f"{case_key}/{segment_id}/{road_id}"
                )
            if role not in {"MAIN", "INTERNAL_CONNECTOR", "ATTACHED_SWSD"}:
                raise ValueError(
                    f"manual Road role is unsupported: {role}"
                )
            manual_role_ids.add(road_id)
            manual_ownership_ids.add(road_id)
            ownership_by_id[road_id] = "OWNER_CURRENT_SEGMENT"
            business_role_by_id[road_id] = role
            business_role_known[road_id] = True
    if manual_membership is not None:
        for road_id, ownership in manual_membership.road_memberships:
            if road_id not in candidate_ids:
                raise ValueError(
                    "manual Road member is absent from candidate pool: "
                    f"{case_key}/{segment_id}/{road_id}"
                )
            if ownership == "OWNER_CURRENT_SEGMENT":
                if road_id not in target_ids:
                    raise ValueError(
                        "manual owner Road is absent from complete target: "
                        f"{case_key}/{segment_id}/{road_id}"
                    )
            elif ownership == "EXCLUDE_OR_OTHER_OWNER":
                if road_id in target_ids:
                    raise ValueError(
                        "manual excluded Road remains in complete target: "
                        f"{case_key}/{segment_id}/{road_id}"
                    )
            else:
                raise ValueError(
                    "manual Road membership status is unsupported: "
                    f"{ownership}"
                )
            manual_ownership_ids.add(road_id)
            ownership_by_id[road_id] = ownership
    ownership_index = {
        value: index for index, value in enumerate(ROAD_OWNERSHIP_LABELS)
    }
    role_index = {
        value: index for index, value in enumerate(ROAD_BUSINESS_ROLE_LABELS)
    }
    return {
        "ownership_targets": [
            ownership_index[ownership_by_id[road_id]]
            for road_id in candidate_ids
        ],
        "ownership_task_mask": [
            supported and (
                road_id in manual_ownership_ids
                if manual_ownership_ids
                else True
            )
            for road_id in candidate_ids
        ],
        "business_role_targets": [
            role_index[business_role_by_id[road_id]]
            for road_id in candidate_ids
        ],
        "business_role_task_mask": [
            supported
            and business_role_known[road_id]
            and (
                road_id in manual_role_ids if manual_role_ids else True
            )
            for road_id in candidate_ids
        ],
        "manual_adjudication_weight": (
            max(
                float(manual_role.sample_weight)
                if manual_role is not None
                else 0.0,
                float(manual_membership.sample_weight)
                if manual_membership is not None
                else 0.0,
            )
        ),
        "manual_ownership_adjudication_weight": (
            max(
                float(manual_role.sample_weight)
                if manual_role is not None
                else 0.0,
                float(manual_membership.sample_weight)
                if manual_membership is not None
                else 0.0,
            )
        ),
        "manual_role_adjudication_weight": (
            float(manual_role.sample_weight)
            if manual_role is not None
            else 0.0
        ),
        "manual_adjudication_count": len(manual_ownership_ids),
        "manual_ownership_adjudication_count": len(
            manual_ownership_ids
        ),
        "manual_role_adjudication_count": len(manual_role_ids),
    }


def _normalized_relation_ids(
    relation: Mapping[str, Any],
    fields: Sequence[str],
    *,
    final_normalization: Mapping[str, str],
) -> set[str]:
    return normalize_complete_target_ids(
        sorted(
            {
                road_id
                for field in fields
                for road_id in _parse_id_list(relation.get(field))
            }
        ),
        final_normalization=final_normalization,
    )


def _preferred_candidate_roles(
    candidates: Sequence[Mapping[str, Any]],
    *,
    target_ids: set[str],
    target_state: str,
    final_normalization: Mapping[str, str],
) -> dict[str, str]:
    decision = (
        "KEEP_SWSD"
        if target_state == "KEEP_SWSD"
        else "USE_RCSD"
        if target_state == "USE_RCSD_NORMALIZED_RAW"
        else ""
    )
    role_values: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        if str(candidate.get("decision") or "") != decision:
            continue
        normalized_ids = normalize_complete_target_ids(
            candidate.get("road_ids") or (),
            final_normalization=final_normalization,
        )
        if normalized_ids != target_ids:
            continue
        for row in candidate.get("road_roles") or ():
            road_id = str(
                final_normalization.get(
                    str(row.get("road_id") or ""),
                    str(row.get("road_id") or ""),
                )
            )
            role = str(row.get("role") or "")
            if road_id and role:
                role_values[road_id].add(role)
    return {
        road_id: next(iter(values))
        for road_id, values in role_values.items()
        if len(values) == 1
    }


def selected_anchor_relation(
    *,
    road_id: str,
    start_node_id: str,
    end_node_id: str,
    selected_road_ids: set[str],
    selected_node_ids: set[str],
) -> list[float]:
    start = start_node_id in selected_node_ids
    end = end_node_id in selected_node_ids
    return [
        float(road_id in selected_road_ids),
        float(start),
        float(end),
        float(start or end or road_id in selected_road_ids),
    ]


def ordinary_anchor_role_features(
    required_anchor_ids: Sequence[str],
    arm_anchor_ids: Sequence[str],
) -> list[list[float]]:
    source = str(arm_anchor_ids[0]) if arm_anchor_ids else ""
    target = str(arm_anchor_ids[-1]) if arm_anchor_ids else ""
    return [
        [
            float(str(anchor_id) == source),
            float(str(anchor_id) == target),
            float(str(anchor_id) not in {source, target}),
        ]
        for anchor_id in required_anchor_ids
    ]


def _member_candidate_rows(
    *,
    group: Mapping[str, Any],
    segment: Mapping[str, Any],
    raw_pool: set[str],
    swsd_pool: set[str],
    plan_frequency: Mapping[str, int],
    all_anchor: tuple[set[str], set[str]],
    teacher_anchor: tuple[set[str], set[str]],
    oof_anchor: tuple[set[str], set[str]],
    teacher_anchor_selections: Sequence[tuple[set[str], set[str]]],
    oof_anchor_selections: Sequence[tuple[set[str], set[str]]],
    case_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    total_plans = max(len(group["candidates"]), 1)
    for source, pool, road_by_id, node_by_id in (
        (
            "RCSD",
            raw_pool,
            case_data["raw_road_by_id"],
            case_data["raw_nodes"],
        ),
        (
            "SWSD",
            swsd_pool,
            case_data["swsd_road_by_id"],
            case_data["swsd_nodes"],
        ),
    ):
        rows = build_ordinary_plan_member_rows(
            road_ids=sorted(pool),
            road_roles={},
            road_by_id=road_by_id,
            segment_geometry=segment["geometry"],
            raw_nodes=node_by_id,
            swsd_nodes=case_data["swsd_nodes"],
            pair_node_ids=segment["pair_node_ids"],
        )
        for row in rows:
            road_id = str(row["road_id"])
            start = str(row["start_node_id"])
            end = str(row["end_node_id"])
            base = [float(value) for value in row["features"]]
            base[:2] = [0.0, 0.0]
            frequency = int(plan_frequency.get(road_id, 0))
            common = [
                *base,
                float(source == "SWSD"),
                float(source == "RCSD"),
                math.tanh(frequency / max(total_plans, 1)),
                float(frequency > 0),
                *selected_anchor_relation(
                    road_id=road_id,
                    start_node_id=start,
                    end_node_id=end,
                    selected_road_ids=all_anchor[0],
                    selected_node_ids=all_anchor[1],
                ),
            ]
            result.append(
                {
                    "road_id": road_id,
                    "source": source,
                    "start_node_id": start,
                    "end_node_id": end,
                    "teacher_feature_values": [
                        *common,
                        *selected_anchor_relation(
                            road_id=road_id,
                            start_node_id=start,
                            end_node_id=end,
                            selected_road_ids=teacher_anchor[0],
                            selected_node_ids=teacher_anchor[1],
                        ),
                        *[0.0] * len(ROAD_MEMBER_ANCHOR_RELATION_NAMES),
                    ],
                    "oof_feature_values": [
                        *common,
                        *[0.0] * len(ROAD_MEMBER_ANCHOR_RELATION_NAMES),
                        *selected_anchor_relation(
                            road_id=road_id,
                            start_node_id=start,
                            end_node_id=end,
                            selected_road_ids=oof_anchor[0],
                            selected_node_ids=oof_anchor[1],
                        ),
                    ],
                    "teacher_anchor_relation_values": [
                        selected_anchor_relation(
                            road_id=road_id,
                            start_node_id=start,
                            end_node_id=end,
                            selected_road_ids=selected_roads,
                            selected_node_ids=selected_nodes,
                        )
                        for selected_roads, selected_nodes in (
                            teacher_anchor_selections
                        )
                    ],
                    "oof_anchor_relation_values": [
                        selected_anchor_relation(
                            road_id=road_id,
                            start_node_id=start,
                            end_node_id=end,
                            selected_road_ids=selected_roads,
                            selected_node_ids=selected_nodes,
                        )
                        for selected_roads, selected_nodes in (
                            oof_anchor_selections
                        )
                    ],
                }
            )
    return sorted(result, key=lambda row: (row["source"], row["road_id"]))


def _target_road_ids(
    label: Mapping[str, Any],
    *,
    segment: Mapping[str, Any],
    raw_road_ids: set[str],
    swsd_road_ids: set[str],
    final_normalization: Mapping[str, str],
) -> tuple[set[str], str]:
    decision = str(label.get("preferred_carrier_target") or "")
    if decision == "KEEP_SWSD":
        return set(segment["swsd_road_ids"]) & swsd_road_ids, "KEEP_SWSD"
    if decision not in {
        "USE_RCSD",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
    }:
        return set(), "UNSUPPORTED_DECISION"
    target_decision = decision
    targets = [
        row
        for row in label.get("acceptable_complete_road_targets") or ()
        if str(row.get("decision") or "") == target_decision
    ]
    normalized = set()
    for target in targets:
        normalized.update(
            normalize_complete_target_ids(
                target.get("road_ids") or (),
                final_normalization=final_normalization,
            )
        )
    if decision == "T06_MAIN_RCSD_ATTACHED_SWSD":
        return normalized, "T06_MAIN_RCSD_ATTACHED_SWSD"
    return normalized & raw_road_ids, "USE_RCSD_NORMALIZED_RAW"


def _all_anchor_candidate_members(
    case_key: str,
    anchor_ids: Sequence[str],
    features: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[set[str], set[str]]:
    candidate_ids = [
        str(candidate_id)
        for anchor_id in anchor_ids
        for candidate_id in (
            features.get((case_key, anchor_id), {}).get("candidate_ids") or ()
        )
    ]
    return _candidate_members(candidate_ids)


def _teacher_anchor_members(
    case_key: str,
    anchor_ids: Sequence[str],
    features: Mapping[tuple[str, str], Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_ids = []
    selections = []
    ready = True
    for anchor_id in anchor_ids:
        feature = features.get((case_key, anchor_id))
        if feature is None:
            ready = False
            selections.append((set(), set()))
            continue
        label = labels[str(feature["sample_id"])]
        acceptable = tuple(
            int(value)
            for value in label.get("candidate_acceptable_indices") or ()
        )
        preferred = int(label.get("preferred_candidate_index", -1))
        selected = (
            preferred
            if preferred >= 0
            else acceptable[0]
            if len(acceptable) == 1
            else -1
        )
        if selected >= 0:
            candidate_id = str(feature["candidate_ids"][selected])
            candidate_ids.append(candidate_id)
            selections.append(_candidate_members([candidate_id]))
        elif acceptable:
            ready = False
            selections.append((set(), set()))
        elif int(label.get("status_label", -1)) != 1:
            ready = False
            selections.append((set(), set()))
        else:
            selections.append((set(), set()))
    road_ids, node_ids = _candidate_members(candidate_ids)
    return {
        "road_ids": road_ids,
        "node_ids": node_ids,
        "selections": tuple(selections),
        "ready": ready,
    }


def _oof_anchor_members(
    case_key: str,
    anchor_ids: Sequence[str],
    predictions: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_ids = []
    selections = []
    ready = True
    for anchor_id in anchor_ids:
        row = predictions.get((case_key, anchor_id))
        if row is None:
            ready = False
            selections.append((set(), set()))
            continue
        candidate_id = str(row.get("candidate_predicted_id") or "")
        if candidate_id:
            candidate_ids.append(candidate_id)
            selections.append(_candidate_members([candidate_id]))
        elif not bool(row.get("no_evidence_proof_passed")):
            ready = False
            selections.append((set(), set()))
        else:
            selections.append((set(), set()))
        if not (
            bool(row.get("proven_safe_anchor"))
            or bool(row.get("no_evidence_proof_passed"))
        ):
            ready = False
    road_ids, node_ids = _candidate_members(candidate_ids)
    return {
        "road_ids": road_ids,
        "node_ids": node_ids,
        "selections": tuple(selections),
        "release_ready": ready,
    }


def _candidate_members(
    candidate_ids: Sequence[str],
) -> tuple[set[str], set[str]]:
    road_ids: set[str] = set()
    node_ids: set[str] = set()
    for value in candidate_ids:
        candidate_type, separator, payload = str(value).partition(":")
        if not separator:
            continue
        members = {member for member in payload.split("|") if member}
        if candidate_type == "ROAD":
            road_ids.update(members)
        elif candidate_type == "NODE":
            node_ids.update(members)
    return road_ids, node_ids


def _candidate_lineage_paths(
    root: Path,
) -> dict[str, dict[str, Path]]:
    result: dict[str, dict[str, Path]] = defaultdict(dict)
    for row in _read_jsonl(root / "input_lineage.jsonl"):
        result[str(row["case_key"])][str(row["role"])] = (
            normalize_runtime_path(Path(str(row["path"]))).resolve(strict=True)
        )
    return dict(result)


def _final_road_paths(path: Path) -> dict[str, Path]:
    summary = _read_json(path)
    result = {}
    for row in summary["inputs"]["case_inputs"]:
        candidate = normalize_runtime_path(Path(str(row["path"])))
        if candidate.name == "t06_frcsd_road.gpkg":
            result[str(row["case_key"])] = candidate.resolve(strict=True)
    return result


def _load_case_data(
    case_key: str,
    paths: Mapping[str, Path],
    final_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_roads, raw_crs = _read_roads(paths["raw_rcsd_roads"])
    raw_nodes, raw_node_crs, _ = _read_points(paths["raw_rcsd_nodes"])
    swsd_roads, swsd_crs = _read_roads(paths["t01_segment"].parent / "roads.gpkg")
    swsd_nodes, swsd_node_crs, _ = _read_points(paths["t01_nodes"])
    segments, segment_crs = _read_segments(paths["t01_segment"])
    if {
        raw_crs,
        raw_node_crs,
        swsd_crs,
        swsd_node_crs,
        segment_crs,
    } != {"EPSG:3857"}:
        raise ValueError(f"ordinary Road member CRS differs: {case_key}")
    raw_by_id = {str(row.road_id): row for row in raw_roads}
    swsd_by_id = {str(row.road_id): row for row in swsd_roads}
    incident: dict[str, set[str]] = defaultdict(set)
    for row in raw_roads:
        incident[str(row.start_node_id)].add(str(row.road_id))
        incident[str(row.end_node_id)].add(str(row.road_id))
    normalization = {}
    with fiona.open(final_path) as source:
        for feature in source:
            properties = dict(feature["properties"])
            normalization[str(properties.get("id") or "")] = (
                normalized_final_road_id(properties)
            )
    relation_path = (
        final_path.parent
        / "t06_step3_swsd_frcsd_segment_relation.csv"
    )
    with relation_path.open("r", encoding="utf-8-sig", newline="") as stream:
        relations = {
            str(row["swsd_segment_id"]): row for row in csv.DictReader(stream)
        }
    input_paths = (
        paths["raw_rcsd_roads"],
        paths["raw_rcsd_nodes"],
        paths["t01_segment"],
        paths["t01_nodes"],
        paths["t01_segment"].parent / "roads.gpkg",
        final_path,
        relation_path,
    )
    return (
        {
            "raw_road_by_id": raw_by_id,
            "swsd_road_by_id": swsd_by_id,
            "raw_nodes": raw_nodes,
            "swsd_nodes": swsd_nodes,
            "segment_by_id": {
                str(row["segment_id"]): row for row in segments
            },
            "incident_raw_roads": incident,
            "final_normalization": normalization,
            "relation_by_segment": relations,
        },
        [
            _input_record(path, case_key=case_key) for path in input_paths
        ],
    )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _input_record(
    path: Path,
    *,
    case_key: str = "",
) -> dict[str, Any]:
    row = {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    if case_key:
        row["case_key"] = case_key
    return row


__all__ = [
    "ROAD_MEMBER_ANCHOR_RELATION_NAMES",
    "ROAD_MEMBER_EXTRA_FEATURE_NAMES",
    "build_anchor_conditioned_ordinary_road_member_store",
    "normalize_complete_target_ids",
    "selected_anchor_relation",
]
