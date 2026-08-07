from __future__ import annotations

import json
import math
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


AR_LOCAL_FEATURE_DIM = 50
SIDE_OBJECT_FEATURE_DIM = 64
SIDE_ROAD_FEATURE_DIM = 40
SIDE_ACCESS_FEATURE_DIM = 64


def materialize_advance_right_condition_view(
    *,
    access_set_store_root: Path,
    condition_kind: str,
    output_root: Path,
) -> Path:
    """Write a stage-specific compatibility view for downstream P05 heads."""
    store = normalize_runtime_path(access_set_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    condition_files = {
        "TEACHER": "advance_right_teacher_conditions.jsonl",
        "STRICT_OOF": "advance_right_oof_conditions.jsonl",
    }
    if condition_kind not in condition_files:
        raise ValueError("unsupported AdvanceRight condition view")
    feature_path = store / "advance_right_access_set_features.jsonl"
    condition_path = store / condition_files[condition_kind]
    features = {
        _object_key(row): row for row in _read_jsonl(feature_path)
    }
    conditions = {
        _object_key(row): row for row in _read_jsonl(condition_path)
    }
    if set(features) != set(conditions):
        raise ValueError("AdvanceRight feature/condition view scopes differ")
    rows = [
        conditioned_feature_view(features[key], conditions[key])
        for key in sorted(features)
    ]
    terminal_condition = condition_kind == "TEACHER"
    output_feature_path = root / "advance_right_inference_features.jsonl"
    _write_jsonl(output_feature_path, rows)
    label_path = root / "advance_right_training_labels.jsonl"
    _copy_jsonl(store / "advance_right_training_labels.jsonl", label_path)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_STAGE_CONDITION_VIEW",
        "condition_kind": condition_kind,
        "scope": (
            "Training-only teacher forcing view"
            if terminal_condition
            else "Strict OOF inference-equivalent stage view"
        ),
        "object_count": len(rows),
        "base_feature_uses_truth": False,
        "stage_condition_uses_truth": terminal_condition,
        "inference_input_allowed": not terminal_condition,
        "terminal_condition_count": (
            len(rows) if terminal_condition else 0
        ),
        "inputs": {
            "features": _input_record(feature_path),
            "conditions": _input_record(condition_path),
            "labels": _input_record(
                store / "advance_right_training_labels.jsonl"
            ),
        },
        "outputs": {
            "conditioned_features": _input_record(output_feature_path),
            "labels": _input_record(label_path),
        },
        "gate_pass": len(rows) == 474,
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight condition view coverage differs")
    return root


def build_advance_right_access_set_store(
    *,
    base_conditioned_store_root: Path,
    ordinary_member_store_root: Path,
    ordinary_access_store_root: Path,
    ordinary_hierarchical_state_root: Path,
    enriched_attachment_store_root: Path,
    output_root: Path,
) -> Path:
    """Build truth-free side Road/access sets and isolated stage conditions."""
    base_root = normalize_runtime_path(base_conditioned_store_root).resolve(
        strict=True
    )
    member_root = normalize_runtime_path(ordinary_member_store_root).resolve(
        strict=True
    )
    access_root = normalize_runtime_path(ordinary_access_store_root).resolve(
        strict=True
    )
    state_root = normalize_runtime_path(
        ordinary_hierarchical_state_root
    ).resolve(strict=True)
    attachment_root = normalize_runtime_path(
        enriched_attachment_store_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    base_path = base_root / "advance_right_inference_features.jsonl"
    member_feature_path = member_root / "ordinary_road_member_features.jsonl"
    access_feature_path = (
        access_root / "ordinary_access_inference_candidates.jsonl"
    )
    state_path = state_root / "ordinary_hierarchical_states.jsonl"
    base_rows = _read_jsonl(base_path)
    needed_side_keys = _needed_side_keys(base_rows)
    member_features = _read_needed_member_features(
        member_feature_path,
        needed_side_keys,
    )
    access_features = _read_needed_access_features(
        access_feature_path,
        needed_side_keys,
    )
    states = {
        _segment_key(row): row for row in _read_jsonl(state_path)
    }

    counts: Counter[str] = Counter()
    feature_rows = []
    oof_conditions = []
    for base in sorted(
        base_rows,
        key=lambda row: (str(row["case_key"]), str(row["object_id"])),
    ):
        case_key = str(base["case_key"])
        object_id = str(base["object_id"])
        sides = {}
        conditions = {}
        for side_name in ("source", "target"):
            old_context = base[f"{side_name}_context"]
            side = _side_feature_row(
                case_key=case_key,
                old_context=old_context,
                member_features=member_features,
                access_features=access_features,
            )
            condition = oof_side_condition(
                side=side,
                state=states.get(
                    (
                        case_key,
                        str(old_context.get("owner_segment_id") or ""),
                    )
                ),
            )
            sides[side_name] = side
            conditions[side_name] = condition
            counts[f"{side_name}_{condition['resolution']}"] += 1
            counts[
                f"{side_name}_access_road_resolved"
                if condition["access_road_resolved"]
                else f"{side_name}_access_road_unresolved"
            ] += 1
        source_nodes = _selected_plan_node_ids(
            sides["source"],
            conditions["source"]["selected_road_ids"],
        )
        target_nodes = _selected_plan_node_ids(
            sides["target"],
            conditions["target"]["selected_road_ids"],
        )
        source_access_nodes = _selected_access_node_ids(
            sides["source"],
            conditions["source"]["access_road_ids"],
        )
        target_access_nodes = _selected_access_node_ids(
            sides["target"],
            conditions["target"]["access_road_ids"],
        )
        candidates = [
            _candidate_feature_row(
                row,
                source_nodes=source_nodes,
                target_nodes=target_nodes,
                source_access_nodes=source_access_nodes,
                target_access_nodes=target_access_nodes,
            )
            for row in base.get("candidate_rows") or ()
        ]
        both_source_resolved = all(
            bool(conditions[name]["access_source_resolved"])
            for name in ("source", "target")
        )
        both_access_resolved = all(
            bool(conditions[name]["access_road_resolved"])
            for name in ("source", "target")
        )
        counts[
            "oof_both_source_resolved"
            if both_source_resolved
            else "oof_source_unresolved"
        ] += 1
        counts[
            "oof_both_access_road_resolved"
            if both_access_resolved
            else "oof_access_road_unresolved"
        ] += 1
        feature_rows.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "object_id": object_id,
                "fold": int(base["fold"]),
                "fixed_swsd_road_ids": [
                    str(value)
                    for value in base.get("fixed_swsd_road_ids") or ()
                ],
                "access_valid": bool(base.get("access_valid")),
                "source_side": sides["source"],
                "target_side": sides["target"],
                "candidate_rows": candidates,
                "feature_uses_truth": False,
                "terminal_input_count": 0,
                "raw_id_embedding_count": 0,
            }
        )
        oof_conditions.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "object_id": object_id,
                "fold": int(base["fold"]),
                "source_condition": conditions["source"],
                "target_condition": conditions["target"],
                "both_access_source_resolved": both_source_resolved,
                "both_access_road_resolved": both_access_resolved,
                "condition_kind": "STRICT_OOF_ORDINARY_FINAL_STATE",
                "feature_uses_truth": False,
                "terminal_input_count": 0,
            }
        )

    feature_path = root / "advance_right_access_set_features.jsonl"
    oof_path = root / "advance_right_oof_conditions.jsonl"
    _write_jsonl(feature_path, feature_rows)
    _write_jsonl(oof_path, oof_conditions)
    feature_hash = sha256_file(feature_path)
    oof_hash = sha256_file(oof_path)

    # Label-only inputs are opened only after truth-free features are frozen.
    member_labels = {
        _segment_key(row): row
        for row in _read_jsonl(
            member_root / "ordinary_road_member_labels.jsonl"
        )
        if _segment_key(row) in needed_side_keys
    }
    access_labels = {
        _access_key(row): row
        for row in _read_jsonl(
            access_root / "ordinary_access_training_labels.jsonl"
        )
    }
    attachments = {
        _object_key(row): row
        for row in _read_jsonl(
            attachment_root / "advance_right_attachment_labels.jsonl"
        )
    }
    teacher_conditions = []
    feature_by_key = {
        _object_key(row): row for row in feature_rows
    }
    for key, feature in sorted(feature_by_key.items()):
        attachment = attachments.get(key, {})
        side_conditions = {}
        for side_name in ("source", "target"):
            side = feature[f"{side_name}_side"]
            condition = teacher_side_condition(
                side=side,
                member_label=member_labels.get(
                    (
                        str(feature["case_key"]),
                        str(side["owner_segment_id"]),
                    )
                ),
                access_label=access_labels.get(
                    (
                        str(feature["case_key"]),
                        str(side["owner_segment_id"]),
                        str(side["t01_access_node_id"]),
                    )
                ),
                attachment=attachment,
            )
            side_conditions[side_name] = condition
            counts[f"teacher_{side_name}_{condition['resolution']}"] += 1
        source_ready = bool(
            side_conditions["source"]["access_source_resolved"]
        )
        target_ready = bool(
            side_conditions["target"]["access_source_resolved"]
        )
        access_ready = bool(
            side_conditions["source"]["access_road_resolved"]
            and side_conditions["target"]["access_road_resolved"]
        )
        counts[
            "teacher_both_source_resolved"
            if source_ready and target_ready
            else "teacher_source_unresolved"
        ] += 1
        counts[
            "teacher_both_access_road_resolved"
            if access_ready
            else "teacher_access_road_unresolved"
        ] += 1
        teacher_conditions.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": key[0],
                "object_id": key[1],
                "fold": int(feature["fold"]),
                "source_condition": side_conditions["source"],
                "target_condition": side_conditions["target"],
                "both_access_source_resolved": source_ready and target_ready,
                "both_access_road_resolved": access_ready,
                "condition_kind": "TEACHER_ORDINARY_FINAL_STATE",
                "label_only": True,
                "inference_input_allowed": False,
            }
        )
    teacher_path = root / "advance_right_teacher_conditions.jsonl"
    _write_jsonl(teacher_path, teacher_conditions)

    label_path = root / "advance_right_training_labels.jsonl"
    attachment_path = root / "advance_right_attachment_labels.jsonl"
    _copy_jsonl(
        base_root / "advance_right_training_labels.jsonl",
        label_path,
    )
    _copy_jsonl(
        attachment_root / "advance_right_attachment_labels.jsonl",
        attachment_path,
    )
    if (
        sha256_file(feature_path) != feature_hash
        or sha256_file(oof_path) != oof_hash
    ):
        raise RuntimeError("label reads changed AdvanceRight inference inputs")

    feature_keys = set(feature_by_key)
    oof_keys = {_object_key(row) for row in oof_conditions}
    teacher_keys = {_object_key(row) for row in teacher_conditions}
    label_keys = {
        _object_key(row) for row in _read_jsonl(label_path)
    }
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_LOCKED_ORDINARY_ACCESS_SET_CONDITIONING",
        "business_contract": {
            "ordinary_lock": (
                "ordinary complete Road set and access are locked before "
                "AdvanceRight; the AdvanceRight head cannot change them"
            ),
            "access_unknown": (
                "a unique Road source may supervise carrier conditioning, "
                "but an unknown exact access Road stays masked and blocks "
                "complete automatic release"
            ),
            "candidate_relation": (
                "relation features are recomputed from the locked complete "
                "Road/access condition; nearest Road is never selected here"
            ),
        },
        "dimensions": {
            "advance_right_local": AR_LOCAL_FEATURE_DIM,
            "advance_right_conditioned": AR_LOCAL_FEATURE_DIM + 10,
            "side_object": SIDE_OBJECT_FEATURE_DIM,
            "side_road": SIDE_ROAD_FEATURE_DIM,
            "side_access": SIDE_ACCESS_FEATURE_DIM,
        },
        "object_count": len(feature_rows),
        "counts": dict(sorted(counts.items())),
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": feature_hash,
        "oof_hash_before_label_read": oof_hash,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "inputs": {
            "base_features": _input_record(base_path),
            "member_features": _input_record(member_feature_path),
            "access_features": _input_record(access_feature_path),
            "ordinary_oof_states": _input_record(state_path),
            "label_only": [
                _input_record(
                    member_root / "ordinary_road_member_labels.jsonl"
                ),
                _input_record(
                    access_root / "ordinary_access_training_labels.jsonl"
                ),
                _input_record(
                    attachment_root
                    / "advance_right_attachment_labels.jsonl"
                ),
                _input_record(
                    base_root / "advance_right_training_labels.jsonl"
                ),
            ],
        },
        "outputs": {
            "features": _input_record(feature_path),
            "oof_conditions": _input_record(oof_path),
            "teacher_conditions": _input_record(teacher_path),
            "training_labels": _input_record(label_path),
            "attachment_labels": _input_record(attachment_path),
        },
        "gate_pass": (
            len(feature_rows) == 474
            and feature_keys == oof_keys == teacher_keys == label_keys
            and sha256_file(feature_path) == feature_hash
            and sha256_file(oof_path) == oof_hash
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight access-set conditioning gate failed")
    return root


def oof_side_condition(
    *,
    side: Mapping[str, Any],
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if state is None:
        return _empty_condition("OOF_OWNER_STATE_MISSING")
    selected = sorted(
        {str(value) for value in state.get("complete_road_ids") or ()}
    )
    source, source_state = selected_road_source(
        selected,
        side.get("road_candidates") or (),
    )
    available = {
        str(row["road_id"])
        for row in side.get("road_candidates") or ()
    }
    missing = sorted(set(selected) - available)
    access_rows = [
        row
        for row in state.get("access_predictions") or ()
        if str(row.get("junc_node_id") or "")
        == str(side.get("t01_access_node_id") or "")
        and bool(row.get("in_complete_carrier"))
        and str(row.get("road_id") or "") in selected
    ]
    access_ids = sorted(
        {str(row["road_id"]) for row in access_rows}
    )
    access_sources = sorted(
        {str(row.get("road_source") or "") for row in access_rows}
        - {""}
    )
    access_road_resolved = len(access_ids) == 1
    if access_sources:
        source = access_sources[0] if len(access_sources) == 1 else "UNRESOLVED"
        source_state = (
            "OOF_ACCESS_ROAD_SOURCE"
            if len(access_sources) == 1
            else "OOF_ACCESS_SOURCE_MIXED"
        )
    resolution = "OOF_LOCKED"
    if not selected:
        resolution = "OOF_COMPLETE_ROAD_SET_MISSING"
    elif missing:
        resolution = "OOF_COMPLETE_ROAD_MEMBER_MISSING"
    elif source == "UNRESOLVED":
        resolution = source_state
    elif not access_road_resolved:
        resolution = "OOF_ACCESS_ROAD_UNRESOLVED"
    automatic = bool(
        access_rows
        and all(bool(row.get("automatic")) for row in access_rows)
    )
    return {
        "selected_road_ids": selected,
        "selected_decision": str(
            state.get("raw_carrier_decision") or ""
        ),
        "access_source": source,
        "access_source_resolved": source in {"SWSD", "RCSD"},
        "access_road_ids": access_ids,
        "access_proposal_ids": sorted(
            {
                str(row.get("proposal_id") or "")
                for row in access_rows
                if str(row.get("proposal_id") or "")
            }
        ),
        "access_road_resolved": access_road_resolved,
        "carrier_probability": float(
            state.get("raw_carrier_probability") or 0.0
        ),
        "ordinary_release_ready": bool(
            state.get("hierarchical_release_ready")
        ),
        "access_release_ready": automatic,
        "complete_release_ready": bool(
            state.get("hierarchical_release_ready")
            and access_road_resolved
            and automatic
        ),
        "resolution": resolution,
        "condition_uses_truth": False,
    }


def teacher_side_condition(
    *,
    side: Mapping[str, Any],
    member_label: Mapping[str, Any] | None,
    access_label: Mapping[str, Any] | None,
    attachment: Mapping[str, Any],
) -> dict[str, Any]:
    if member_label is None:
        return _empty_condition(
            "TEACHER_COMPLETE_ROAD_LABEL_MISSING",
            uses_truth=True,
        )
    selected = sorted(
        {
            str(value)
            for value in member_label.get("acceptable_road_ids") or ()
        }
    )
    source, source_state = selected_road_source(
        selected,
        side.get("road_candidates") or (),
    )
    access_ids = teacher_access_road_ids(
        side=side,
        selected_road_ids=selected,
        access_label=access_label,
        attachment=attachment,
    )
    access_sources = {
        str(row["source"])
        for row in side.get("road_candidates") or ()
        if str(row["road_id"]) in access_ids
    }
    if len(access_sources) == 1:
        source = next(iter(access_sources))
        source_state = "TEACHER_ACCESS_ROAD_SOURCE"
    elif len(access_sources) > 1:
        source = "UNRESOLVED"
        source_state = "TEACHER_ACCESS_SOURCE_MIXED"
    available = {
        str(row["road_id"])
        for row in side.get("road_candidates") or ()
    }
    missing = sorted(set(selected) - available)
    access_resolved = bool(access_ids)
    resolution = "TEACHER_LOCKED"
    if not selected:
        resolution = "TEACHER_COMPLETE_ROAD_SET_MISSING"
    elif missing:
        resolution = "TEACHER_COMPLETE_ROAD_MEMBER_MISSING"
    elif source == "UNRESOLVED":
        resolution = source_state
    elif not access_resolved:
        resolution = "TEACHER_ACCESS_ROAD_UNKNOWN"
    return {
        "selected_road_ids": selected,
        "selected_decision": str(
            member_label.get("preferred_decision") or ""
        ),
        "access_source": source,
        "access_source_resolved": source in {"SWSD", "RCSD"},
        "access_road_ids": access_ids,
        "access_proposal_ids": [],
        "access_road_resolved": access_resolved,
        "carrier_probability": 1.0,
        "ordinary_release_ready": True,
        "access_release_ready": access_resolved,
        "complete_release_ready": access_resolved,
        "resolution": resolution,
        "condition_uses_truth": True,
    }


def selected_road_source(
    selected_road_ids: Sequence[str],
    road_candidates: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    source_by_id = {
        str(row["road_id"]): str(row.get("source") or "")
        for row in road_candidates
    }
    selected = {str(value) for value in selected_road_ids}
    if not selected:
        return "UNRESOLVED", "COMPLETE_ROAD_SET_EMPTY"
    if selected - set(source_by_id):
        return "UNRESOLVED", "COMPLETE_ROAD_MEMBER_MISSING"
    sources = {source_by_id[value] for value in selected} - {""}
    if sources == {"SWSD"}:
        return "SWSD", "COMPLETE_ROAD_SOURCE_UNIQUE"
    if sources == {"RCSD"}:
        return "RCSD", "COMPLETE_ROAD_SOURCE_UNIQUE"
    if len(sources) > 1:
        return "UNRESOLVED", "COMPLETE_ROAD_SOURCE_MIXED"
    return "UNRESOLVED", "COMPLETE_ROAD_SOURCE_UNKNOWN"


def teacher_access_road_ids(
    *,
    side: Mapping[str, Any],
    selected_road_ids: Sequence[str],
    access_label: Mapping[str, Any] | None,
    attachment: Mapping[str, Any],
) -> list[str]:
    selected = {str(value) for value in selected_road_ids}
    access_node_id = str(side.get("t01_access_node_id") or "")
    action_ids = {
        str(row.get("rcsd_road_id") or "")
        for row in attachment.get("attachment_actions") or ()
        if str(row.get("swsd_node_id") or "") == access_node_id
        and str(row.get("rcsd_road_id") or "") in selected
    } - {""}
    if action_ids:
        return sorted(action_ids)
    label_ids = {
        str(row.get("road_id") or "")
        for row in (access_label or {}).get(
            "acceptable_access_targets"
        )
        or ()
        if str(row.get("road_id") or "") in selected
    } - {""}
    return sorted(label_ids)


def conditioned_candidate_features(
    row: Mapping[str, Any],
    *,
    source_nodes: set[str],
    target_nodes: set[str],
    source_access_nodes: set[str],
    target_access_nodes: set[str],
) -> list[float]:
    local = [float(value) for value in row.get("local_feature_values") or ()]
    if len(local) != AR_LOCAL_FEATURE_DIM:
        raise ValueError("AdvanceRight local feature dimension differs")
    snode = str(row.get("raw_snodeid") or "")
    enode = str(row.get("raw_enodeid") or "")
    return [
        *local,
        float(snode in source_nodes),
        float(enode in source_nodes),
        float(bool({snode, enode} & source_nodes)),
        float(snode in target_nodes),
        float(enode in target_nodes),
        float(bool({snode, enode} & target_nodes)),
        float(snode in source_access_nodes),
        float(enode in source_access_nodes),
        float(snode in target_access_nodes),
        float(enode in target_access_nodes),
    ]


def conditioned_feature_view(
    feature: Mapping[str, Any],
    condition: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize one stage-specific condition without changing base features."""
    contexts = {}
    for side_name in ("source", "target"):
        side = feature[f"{side_name}_side"]
        locked = condition[f"{side_name}_condition"]
        selected = {str(value) for value in locked["selected_road_ids"]}
        access = {str(value) for value in locked["access_road_ids"]}
        access_proposals = {
            str(value)
            for value in locked.get("access_proposal_ids") or ()
        }
        road_rows = [
            row
            for row in side.get("road_candidates") or ()
            if str(row["road_id"]) in selected
        ]
        access_rows = [
            row
            for row in side.get("access_candidates") or ()
            if str(row["road_id"]) in access
            and (
                not access_proposals
                or str(row["proposal_id"]) in access_proposals
            )
        ]
        contexts[side_name] = {
            "owner_segment_id": str(side["owner_segment_id"]),
            "t01_access_node_id": str(side["t01_access_node_id"]),
            "resolved": bool(locked["access_source_resolved"]),
            "access_road_resolved": bool(locked["access_road_resolved"]),
            "required_access_resolved": bool(
                locked["access_source"] == "SWSD"
                or locked["access_road_resolved"]
            ),
            "resolution": str(locked["resolution"]),
            "data_source": str(locked["access_source"]),
            "selected_plan_id": (
                f"{condition['condition_kind']}:{side_name}"
            ),
            "selected_decision": str(locked["selected_decision"]),
            "object_features": [
                float(value)
                for value in side["object_feature_values"]
            ],
            "plan_features": _complete_plan_features(road_rows),
            "road_members": [
                {
                    "road_id": str(row["road_id"]),
                    "start_node_id": str(row["start_node_id"]),
                    "end_node_id": str(row["end_node_id"]),
                    "features": [
                        float(value)
                        for value in row["feature_values"][
                            : SIDE_ACCESS_FEATURE_DIM
                            - SIDE_ROAD_FEATURE_DIM
                        ]
                    ],
                }
                for row in road_rows
            ],
            "access_rows": [
                {
                    "road_id": str(row["road_id"]),
                    "proposal_id": str(row["proposal_id"]),
                    "features": [
                        float(value) for value in row["feature_values"]
                    ],
                    "projected_fraction": float(
                        row["projected_fraction"]
                    ),
                    "operation": str(row["operation"]),
                }
                for row in access_rows
            ],
            "arm_rows": [],
            "status_features": _locked_status_features(locked),
            "condition_uses_truth": bool(
                locked.get("condition_uses_truth")
            ),
        }
    source_nodes = _selected_plan_node_ids(
        feature["source_side"],
        condition["source_condition"]["selected_road_ids"],
    )
    target_nodes = _selected_plan_node_ids(
        feature["target_side"],
        condition["target_condition"]["selected_road_ids"],
    )
    source_access_nodes = _selected_access_node_ids(
        feature["source_side"],
        condition["source_condition"]["access_road_ids"],
    )
    target_access_nodes = _selected_access_node_ids(
        feature["target_side"],
        condition["target_condition"]["access_road_ids"],
    )
    candidate_rows = [
        {
            "bundle_id": str(row["bundle_id"]),
            "candidate_road_id": str(row["candidate_road_id"]),
            "feature_values": conditioned_candidate_features(
                row,
                source_nodes=source_nodes,
                target_nodes=target_nodes,
                source_access_nodes=source_access_nodes,
                target_access_nodes=target_access_nodes,
            ),
            "raw_snodeid": str(row["raw_snodeid"]),
            "raw_enodeid": str(row["raw_enodeid"]),
        }
        for row in feature.get("candidate_rows") or ()
    ]
    return {
        "schema_version": str(feature["schema_version"]),
        "case_key": str(feature["case_key"]),
        "object_id": str(feature["object_id"]),
        "fold": int(feature["fold"]),
        "fixed_swsd_road_ids": [
            str(value) for value in feature["fixed_swsd_road_ids"]
        ],
        "access_valid": bool(feature["access_valid"]),
        "adjacent_context_resolved": bool(
            condition["both_access_source_resolved"]
        ),
        "adjacent_access_road_resolved": bool(
            condition["both_access_road_resolved"]
        ),
        "required_rcsd_access_resolved": all(
            bool(context["required_access_resolved"])
            for context in contexts.values()
        ),
        "source_context": contexts["source"],
        "target_context": contexts["target"],
        "candidate_rows": candidate_rows,
        "condition_kind": str(condition["condition_kind"]),
        "condition_uses_truth": any(
            bool(context["condition_uses_truth"])
            for context in contexts.values()
        ),
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
    }


def _complete_plan_features(
    road_rows: Sequence[Mapping[str, Any]],
) -> list[float]:
    if not road_rows:
        return [0.0] * SIDE_OBJECT_FEATURE_DIM
    values = [
        [float(value) for value in row["feature_values"]]
        for row in road_rows
    ]
    means = [
        sum(row[index] for row in values) / len(values)
        for index in range(SIDE_ROAD_FEATURE_DIM)
    ]
    maxima = [
        max(row[index] for row in values)
        for index in range(
            SIDE_ACCESS_FEATURE_DIM - SIDE_ROAD_FEATURE_DIM
        )
    ]
    result = [*means, *maxima]
    if len(result) != SIDE_OBJECT_FEATURE_DIM:
        raise RuntimeError("complete ordinary plan summary dimension differs")
    return result


def _locked_status_features(locked: Mapping[str, Any]) -> list[float]:
    source = str(locked["access_source"])
    decision = str(locked["selected_decision"])
    source_ready = bool(locked["access_source_resolved"])
    access_ready = bool(locked["access_road_resolved"])
    release_ready = bool(locked["complete_release_ready"])
    cardinality = len(locked["selected_road_ids"])
    return [
        float(source == "SWSD"),
        float(source == "RCSD"),
        float(not source_ready),
        float(decision == "KEEP_SWSD"),
        float(decision == "USE_RCSD"),
        float(decision == "KEEP_SWSD"),
        float(decision == "USE_RCSD"),
        float(decision == "ABSTAIN"),
        float(release_ready and decision == "KEEP_SWSD"),
        float(release_ready and decision == "USE_RCSD"),
        float(not release_ready),
        float(not release_ready),
        float(source_ready),
        float(source_ready and access_ready),
        float(locked.get("carrier_probability") or 0.0),
        0.0,
        float(not release_ready),
        0.0,
        0.0,
        math.log1p(cardinality),
        float(source_ready),
        float(access_ready),
    ]


def _side_feature_row(
    *,
    case_key: str,
    old_context: Mapping[str, Any],
    member_features: Mapping[
        tuple[str, str], Mapping[str, Any]
    ],
    access_features: Mapping[
        tuple[str, str, str], Sequence[Mapping[str, Any]]
    ],
) -> dict[str, Any]:
    owner_segment_id = str(
        old_context.get("owner_segment_id") or ""
    )
    access_node_id = str(old_context.get("t01_access_node_id") or "")
    member = member_features.get((case_key, owner_segment_id))
    road_rows = []
    if member is not None:
        for row in member.get("candidate_rows") or ():
            values = [
                float(value)
                for value in row.get("oof_feature_values") or ()
            ]
            if len(values) != SIDE_ROAD_FEATURE_DIM:
                raise ValueError("ordinary side Road feature dimension differs")
            road_rows.append(
                {
                    "road_id": str(row["road_id"]),
                    "source": str(row["source"]),
                    "start_node_id": str(row.get("start_node_id") or ""),
                    "end_node_id": str(row.get("end_node_id") or ""),
                    "feature_values": values,
                }
            )
    road_by_id = {str(row["road_id"]): row for row in road_rows}
    access_rows = []
    for proposal in access_features.get(
        (case_key, owner_segment_id, access_node_id),
        (),
    ):
        road = road_by_id.get(str(proposal["road_id"]))
        if road is None:
            continue
        geometry = [
            float(value)
            for value in proposal.get("geometry_feature_values") or ()
        ]
        if len(geometry) != SIDE_ACCESS_FEATURE_DIM - SIDE_ROAD_FEATURE_DIM:
            raise ValueError("ordinary access geometry dimension differs")
        access_rows.append(
            {
                "proposal_id": str(proposal["proposal_id"]),
                "road_id": str(proposal["road_id"]),
                "source": str(proposal["source"]),
                "projected_fraction": float(
                    proposal.get("projected_fraction") or 0.0
                ),
                "operation": str(proposal.get("operation") or ""),
                "distance_m": float(proposal.get("distance_m") or 0.0),
                "feature_values": [
                    *road["feature_values"],
                    *geometry,
                ],
            }
        )
    object_values = (
        [
            float(value)
            for value in member.get("object_feature_values") or ()
        ]
        if member is not None
        else [0.0] * SIDE_OBJECT_FEATURE_DIM
    )
    if len(object_values) != SIDE_OBJECT_FEATURE_DIM:
        raise ValueError("ordinary side object feature dimension differs")
    return {
        "owner_segment_id": owner_segment_id,
        "t01_access_node_id": access_node_id,
        "object_feature_values": object_values,
        "road_candidates": sorted(
            road_rows,
            key=lambda row: str(row["road_id"]),
        ),
        "access_candidates": sorted(
            access_rows,
            key=lambda row: (
                str(row["road_id"]),
                str(row["proposal_id"]),
            ),
        ),
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _candidate_feature_row(
    row: Mapping[str, Any],
    *,
    source_nodes: set[str],
    target_nodes: set[str],
    source_access_nodes: set[str],
    target_access_nodes: set[str],
) -> dict[str, Any]:
    values = [float(value) for value in row.get("feature_values") or ()]
    if len(values) < AR_LOCAL_FEATURE_DIM:
        raise ValueError("AdvanceRight candidate local evidence is incomplete")
    result = {
        "bundle_id": str(row["bundle_id"]),
        "candidate_road_id": str(row["candidate_road_id"]),
        "local_feature_values": values[:AR_LOCAL_FEATURE_DIM],
        "raw_snodeid": str(row.get("raw_snodeid") or ""),
        "raw_enodeid": str(row.get("raw_enodeid") or ""),
    }
    result["oof_conditioned_feature_values"] = conditioned_candidate_features(
        result,
        source_nodes=source_nodes,
        target_nodes=target_nodes,
        source_access_nodes=source_access_nodes,
        target_access_nodes=target_access_nodes,
    )
    return result


def _selected_plan_node_ids(
    side: Mapping[str, Any],
    selected_road_ids: Sequence[str],
) -> set[str]:
    selected = {str(value) for value in selected_road_ids}
    return {
        str(value)
        for row in side.get("road_candidates") or ()
        if str(row["road_id"]) in selected
        for value in (row.get("start_node_id"), row.get("end_node_id"))
        if str(value or "")
    }


def _selected_access_node_ids(
    side: Mapping[str, Any],
    access_road_ids: Sequence[str],
) -> set[str]:
    selected = {str(value) for value in access_road_ids}
    return {
        str(value)
        for row in side.get("road_candidates") or ()
        if str(row["road_id"]) in selected
        for value in (row.get("start_node_id"), row.get("end_node_id"))
        if str(value or "")
    }


def _empty_condition(
    reason: str,
    *,
    uses_truth: bool = False,
) -> dict[str, Any]:
    return {
        "selected_road_ids": [],
        "selected_decision": "",
        "access_source": "UNRESOLVED",
        "access_source_resolved": False,
        "access_road_ids": [],
        "access_proposal_ids": [],
        "access_road_resolved": False,
        "carrier_probability": 0.0,
        "ordinary_release_ready": False,
        "access_release_ready": False,
        "complete_release_ready": False,
        "resolution": reason,
        "condition_uses_truth": uses_truth,
    }


def _needed_side_keys(
    rows: Sequence[Mapping[str, Any]],
) -> set[tuple[str, str]]:
    return {
        (
            str(row["case_key"]),
            str(row[f"{side}_context"].get("owner_segment_id") or ""),
        )
        for row in rows
        for side in ("source", "target")
        if str(row[f"{side}_context"].get("owner_segment_id") or "")
    }


def _read_needed_member_features(
    path: Path,
    needed: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in _iter_jsonl(path):
        key = _segment_key(row)
        if key in needed:
            result[key] = row
    return result


def _read_needed_access_features(
    path: Path,
    needed: set[tuple[str, str]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    result: dict[
        tuple[str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for row in _iter_jsonl(path):
        key = _access_key(row)
        if key[:2] in needed:
            result[key].append(row)
    return result


def _segment_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["segment_id"])


def _access_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["segment_id"]),
        str(row["junc_node_id"]),
    )


def _object_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _input_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
    }


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line:
                yield json.loads(line)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl(path))


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _copy_jsonl(source: Path, target: Path) -> None:
    _write_jsonl(target, _iter_jsonl(source))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "AR_LOCAL_FEATURE_DIM",
    "SIDE_ACCESS_FEATURE_DIM",
    "SIDE_OBJECT_FEATURE_DIM",
    "SIDE_ROAD_FEATURE_DIM",
    "build_advance_right_access_set_store",
    "conditioned_candidate_features",
    "conditioned_feature_view",
    "materialize_advance_right_condition_view",
    "oof_side_condition",
    "selected_road_source",
    "teacher_access_road_ids",
    "teacher_side_condition",
]
