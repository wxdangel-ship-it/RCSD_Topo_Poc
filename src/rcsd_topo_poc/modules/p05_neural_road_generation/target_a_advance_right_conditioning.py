from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _read_nodes,
    _read_roads,
    _resolve_case_paths,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p13_p0_dataset import (
    FEATURE_NAMES as P13_FEATURE_NAMES,
    _case_feature_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


RELATION_FEATURE_NAMES = (
    "candidate_snode_in_source_plan",
    "candidate_enode_in_source_plan",
    "candidate_endpoint_in_source_plan",
    "candidate_snode_in_target_plan",
    "candidate_enode_in_target_plan",
    "candidate_endpoint_in_target_plan",
    "candidate_snode_is_source_t01_access",
    "candidate_enode_is_source_t01_access",
    "candidate_snode_is_target_t01_access",
    "candidate_enode_is_target_t01_access",
)

SIDE_STATUS_FEATURE_NAMES = (
    "source_swsd",
    "source_rcsd",
    "source_unresolved",
    "selected_keep_swsd",
    "selected_use_rcsd",
    "raw_keep_swsd",
    "raw_use_rcsd",
    "raw_abstain",
    "effective_keep_swsd",
    "effective_use_rcsd",
    "effective_abstain",
    "release_fallback",
    "all_required_anchors_resolved",
    "all_required_anchors_success",
    "raw_plan_probability",
    "fallback_none_probability",
    "fallback_segment_probability",
    "fallback_junction_probability",
    "predicted_clue_probability",
    "required_anchor_count_log",
    "anchor_resolved_fraction",
    "anchor_success_fraction",
)


def build_advance_right_conditioned_store(
    *,
    advance_right_store_root: Path,
    target_label_root: Path,
    poc_data_root: Path,
    ordinary_candidate_root: Path,
    ordinary_oof_path: Path,
    output_root: Path,
) -> Path:
    """Lock OOF ordinary plans before attaching AdvanceRight label-only truth."""
    ar_root = normalize_runtime_path(advance_right_store_root).resolve(
        strict=True
    )
    label_root = normalize_runtime_path(target_label_root).resolve(strict=True)
    data_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    ordinary_root = normalize_runtime_path(ordinary_candidate_root).resolve(
        strict=True
    )
    oof_path = normalize_runtime_path(ordinary_oof_path).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    ar_objects = _read_jsonl(ar_root / "advance_right_objects.jsonl")
    ar_candidates = _read_jsonl(ar_root / "advance_right_candidates.jsonl")
    ar_evidence = _read_jsonl(ar_root / "endpoint_evidence.jsonl")
    case_rows = [
        row
        for row in _read_jsonl(label_root / "case_inventory.jsonl")
        if int(row.get("advance_right_count") or 0) > 0
    ]
    groups = _read_jsonl(ordinary_root / "inference_plan_groups.jsonl")
    predictions = _read_jsonl(oof_path)
    group_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in groups
        if str(row.get("segment_type")) == "STANDARD"
    }
    prediction_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in predictions
    }
    if len(prediction_by_key) != len(predictions):
        raise ValueError("ordinary OOF predictions contain duplicate Segments")

    candidates_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    objects_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ar_candidates:
        candidates_by_case[str(row["case_key"])].append(row)
    for row in ar_evidence:
        evidence_by_case[str(row["case_key"])].append(row)
    for row in ar_objects:
        objects_by_case[str(row["case_key"])].append(row)

    base_features: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    base_objects: dict[tuple[str, str], dict[str, Any]] = {}
    fold_by_case: dict[str, int] = {}
    fixed_swsd_by_key: dict[tuple[str, str], list[str]] = {}
    inference_inputs: list[dict[str, str]] = []
    for case_row in sorted(case_rows, key=lambda row: str(row["case_key"])):
        paths, skeleton = _resolve_case_paths(
            baseline_root=label_root,
            case_row=case_row,
            poc_data_root=data_root,
        )
        case_key = paths.case_key
        fold_by_case[case_key] = int(case_row["fold"])
        for segment in skeleton.get("segments") or ():
            if str(segment.get("segment_type")) != "ADVANCE_RIGHT":
                continue
            fixed_swsd_by_key[
                (case_key, str(segment["segment_id"]))
            ] = sorted(
                str(value)
                for value in segment.get("swsd_road_ids") or ()
            )
        feature_rows, object_rows = _case_feature_rows(
            case_key=case_key,
            skeleton=skeleton,
            t01_roads=_read_roads(paths.t01_roads),
            t01_nodes=_read_nodes(paths.t01_nodes),
            raw_roads=_read_roads(paths.raw_rcsd_roads),
            candidates=candidates_by_case[case_key],
            evidence_rows=evidence_by_case[case_key],
            object_rows=objects_by_case[case_key],
        )
        for row in feature_rows:
            base_features[
                (str(row["case_key"]), str(row["object_id"]))
            ].append(row)
        for row in object_rows:
            base_objects[
                (str(row["case_key"]), str(row["object_id"]))
            ] = row
        for role, path in (
            ("FROZEN_SKELETON", paths.frozen_skeleton),
            ("T01_ROADS", paths.t01_roads),
            ("T01_NODES", paths.t01_nodes),
            ("RAW_RCSD_ROADS", paths.raw_rcsd_roads),
            ("RAW_RCSD_NODES", paths.raw_rcsd_nodes),
        ):
            inference_inputs.append(_input_record(path, role, case_key))

    counts: Counter[str] = Counter()
    feature_rows = []
    for ar_object in sorted(
        ar_objects,
        key=lambda row: (str(row["case_key"]), str(row["object_id"])),
    ):
        case_key = str(ar_object["case_key"])
        object_id = str(ar_object["object_id"])
        key = (case_key, object_id)
        if not fixed_swsd_by_key.get(key):
            raise ValueError(
                f"AdvanceRight frozen SWSD Road plan is missing: {key}"
            )
        source = _lock_side_context(
            case_key=case_key,
            owner_segment_id=str(
                ar_object.get("source_owner_segment_id") or ""
            ),
            access_node_id=str(ar_object.get("source_access_node_id") or ""),
            group_by_key=group_by_key,
            prediction_by_key=prediction_by_key,
        )
        target = _lock_side_context(
            case_key=case_key,
            owner_segment_id=str(
                ar_object.get("target_owner_segment_id") or ""
            ),
            access_node_id=str(ar_object.get("target_access_node_id") or ""),
            group_by_key=group_by_key,
            prediction_by_key=prediction_by_key,
        )
        counts[f"source_{source['resolution']}"] += 1
        counts[f"target_{target['resolution']}"] += 1
        both_resolved = bool(source["resolved"] and target["resolved"])
        counts[
            "adjacent_context_resolved"
            if both_resolved
            else "adjacent_context_unresolved"
        ] += 1
        source_nodes = _plan_node_ids(source)
        target_nodes = _plan_node_ids(target)
        candidate_rows = []
        for row in sorted(
            base_features[key],
            key=lambda item: str(item["candidate_road_id"]),
        ):
            raw = next(
                candidate
                for candidate in candidates_by_case[case_key]
                if str(candidate["object_id"]) == object_id
                and str(candidate["candidate_road_id"])
                == str(row["candidate_road_id"])
            )
            snode = str(raw.get("raw_snodeid") or "")
            enode = str(raw.get("raw_enodeid") or "")
            relation_values = _candidate_relation_values(
                snode=snode,
                enode=enode,
                source_nodes=source_nodes,
                target_nodes=target_nodes,
                source_access=str(
                    ar_object.get("source_access_node_id") or ""
                ),
                target_access=str(
                    ar_object.get("target_access_node_id") or ""
                ),
            )
            candidate_rows.append(
                {
                    "bundle_id": str(row["bundle_id"]),
                    "candidate_road_id": str(row["candidate_road_id"]),
                    "feature_values": [
                        *[float(value) for value in row["feature_values"]],
                        *relation_values,
                    ],
                    "raw_snodeid": snode,
                    "raw_enodeid": enode,
                }
            )
        counts[
            "object_with_candidate"
            if candidate_rows
            else "object_without_candidate"
        ] += 1
        feature_rows.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "object_id": object_id,
                "fold": fold_by_case[case_key],
                "fixed_swsd_road_ids": fixed_swsd_by_key.get(key, []),
                "access_valid": bool(
                    base_objects[key]["access_valid"]
                ),
                "adjacent_context_resolved": both_resolved,
                "real_candidate_count": len(candidate_rows),
                "source_context": source,
                "target_context": target,
                "candidate_rows": candidate_rows,
                "feature_uses_truth": False,
                "terminal_input_count": 0,
                "raw_id_embedding_count": 0,
            }
        )
    feature_path = root / "advance_right_inference_features.jsonl"
    _write_jsonl(feature_path, feature_rows)
    frozen_feature_hash = sha256_file(feature_path)

    # Label-only files are opened only after the inference feature store is frozen.
    labels = _read_jsonl(ar_root / "advance_right_labels.jsonl")
    attachments = _read_jsonl(
        ar_root / "advance_right_attachment_labels.jsonl"
    )
    label_path = root / "advance_right_training_labels.jsonl"
    attachment_path = root / "advance_right_attachment_labels.jsonl"
    _write_jsonl(label_path, labels)
    _write_jsonl(attachment_path, attachments)
    if sha256_file(feature_path) != frozen_feature_hash:
        raise RuntimeError("AdvanceRight labels changed inference features")
    feature_keys = {
        (str(row["case_key"]), str(row["object_id"])) for row in feature_rows
    }
    label_keys = {
        (str(row["case_key"]), str(row["object_id"])) for row in labels
    }
    if feature_keys != label_keys:
        raise ValueError("AdvanceRight conditional feature/label scope differs")

    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_ORDINARY_OOF_CONDITIONING",
        "business_contract": {
            "adjacent_plan_source": (
                "strict OOF ordinary plan; release fallback resolves to the "
                "complete KEEP_SWSD plan"
            ),
            "access_contract": (
                "the complete locked adjacent Road set is encoded; no nearest "
                "Road is guessed when the T01 access Node is internal"
            ),
            "unresolved_contract": (
                "missing adjacent owner/group/OOF/plan forces only the "
                "AdvanceRight Segment to fallback"
            ),
        },
        "feature_names": [
            *P13_FEATURE_NAMES,
            *RELATION_FEATURE_NAMES,
        ],
        "side_status_feature_names": list(SIDE_STATUS_FEATURE_NAMES),
        "feature_dim": len(P13_FEATURE_NAMES) + len(RELATION_FEATURE_NAMES),
        "side_status_feature_dim": len(SIDE_STATUS_FEATURE_NAMES),
        "object_count": len(feature_rows),
        "counts": dict(sorted(counts.items())),
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": frozen_feature_hash,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "inputs": {
            "advance_right_objects": _input_record(
                ar_root / "advance_right_objects.jsonl",
                "ADVANCE_RIGHT_OBJECTS",
            ),
            "advance_right_candidates": _input_record(
                ar_root / "advance_right_candidates.jsonl",
                "ADVANCE_RIGHT_CANDIDATES",
            ),
            "endpoint_evidence": _input_record(
                ar_root / "endpoint_evidence.jsonl",
                "ADVANCE_RIGHT_ENDPOINT_EVIDENCE",
            ),
            "ordinary_candidates": _input_record(
                ordinary_root / "inference_plan_groups.jsonl",
                "ORDINARY_CANDIDATE_GROUPS",
            ),
            "ordinary_oof": _input_record(
                oof_path,
                "ORDINARY_STRICT_OOF_PREDICTIONS",
            ),
            "case_inference_inputs": inference_inputs,
            "label_only": [
                _input_record(
                    ar_root / "advance_right_labels.jsonl",
                    "ADVANCE_RIGHT_T06_LABELS",
                ),
                _input_record(
                    ar_root / "advance_right_attachment_labels.jsonl",
                    "ADVANCE_RIGHT_T06_ATTACHMENT_LABELS",
                ),
            ],
        },
        "outputs": {
            "features": _input_record(
                feature_path,
                "ADVANCE_RIGHT_CONDITIONED_INFERENCE_FEATURES",
            ),
            "labels": _input_record(
                label_path,
                "ADVANCE_RIGHT_TRAINING_LABELS",
            ),
            "attachments": _input_record(
                attachment_path,
                "ADVANCE_RIGHT_ATTACHMENT_LABELS",
            ),
        },
        "gate_pass": (
            len(feature_rows) == 474
            and len(feature_keys) == len(label_keys)
            and sha256_file(feature_path) == frozen_feature_hash
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight conditioning gate failed")
    return root


def lock_ordinary_plan(
    *,
    group: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, str]:
    if group is None:
        return None, "GROUP_MISSING"
    if prediction is None:
        return None, "OOF_MISSING"
    candidates = list(group.get("candidates") or ())
    if bool(prediction.get("release_fallback_required")):
        keep = [
            row
            for row in candidates
            if str(row.get("decision")) == "KEEP_SWSD"
        ]
        if len(keep) != 1:
            return None, "KEEP_FALLBACK_NOT_UNIQUE"
        return keep[0], "RELEASE_FALLBACK_KEEP_SWSD"
    plan_id = str(prediction.get("raw_predicted_plan_id") or "")
    selected = [
        row for row in candidates if str(row.get("plan_id")) == plan_id
    ]
    if len(selected) != 1:
        return None, "PREDICTED_PLAN_MISSING"
    if str(selected[0].get("decision")) not in {"KEEP_SWSD", "USE_RCSD"}:
        return None, "PREDICTED_PLAN_NOT_CARRIER"
    return selected[0], "OOF_PLAN_LOCKED"


def _lock_side_context(
    *,
    case_key: str,
    owner_segment_id: str,
    access_node_id: str,
    group_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    prediction_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    key = (case_key, owner_segment_id)
    group = group_by_key.get(key) if owner_segment_id else None
    prediction = prediction_by_key.get(key) if owner_segment_id else None
    selected, resolution = lock_ordinary_plan(
        group=group,
        prediction=prediction,
    )
    resolved = selected is not None and bool(access_node_id)
    if not owner_segment_id or not access_node_id:
        resolution = "ACCESS_RELATION_MISSING"
        resolved = False
    decision = str(selected.get("decision") or "") if selected else ""
    source = (
        "RCSD"
        if decision == "USE_RCSD"
        else "SWSD"
        if decision == "KEEP_SWSD"
        else "UNRESOLVED"
    )
    object_features = (
        [float(value) for value in group["object_features"]]
        if group is not None
        else [0.0] * 64
    )
    plan_features = (
        [float(value) for value in selected["features"]]
        if selected is not None
        else [0.0] * 64
    )
    road_members = list(selected.get("road_members") or ()) if selected else []
    arm_rows = list(selected.get("arm_rows") or ()) if selected else []
    context = {
        "owner_segment_id": owner_segment_id,
        "t01_access_node_id": access_node_id,
        "resolved": resolved,
        "resolution": resolution,
        "data_source": source,
        "selected_plan_id": (
            str(selected.get("plan_id") or "") if selected else ""
        ),
        "selected_decision": decision,
        "object_features": object_features,
        "plan_features": plan_features,
        "road_members": [
            {
                "road_id": str(row.get("road_id") or ""),
                "start_node_id": str(row.get("start_node_id") or ""),
                "end_node_id": str(row.get("end_node_id") or ""),
                "features": [
                    float(value) for value in row.get("features") or ()
                ],
            }
            for row in road_members
        ],
        "arm_rows": [
            {
                "nearest_road_id": str(row.get("nearest_road_id") or ""),
                "nearest_node_id": str(row.get("nearest_node_id") or ""),
                "features": [
                    float(value) for value in row.get("features") or ()
                ],
            }
            for row in arm_rows
        ],
    }
    context["status_features"] = _side_status_features(
        source=source,
        selected_decision=decision,
        prediction=prediction,
    )
    return context


def _side_status_features(
    *,
    source: str,
    selected_decision: str,
    prediction: Mapping[str, Any] | None,
) -> list[float]:
    row = prediction or {}
    raw = str(row.get("raw_predicted_decision") or "")
    effective = str(row.get("effective_decision") or "")
    required = int(row.get("required_anchor_count") or 0)
    resolved = int(row.get("anchor_resolved_count") or 0)
    success = int(row.get("anchor_success_count") or 0)
    denominator = max(required, 1)
    import math

    return [
        float(source == "SWSD"),
        float(source == "RCSD"),
        float(source == "UNRESOLVED"),
        float(selected_decision == "KEEP_SWSD"),
        float(selected_decision == "USE_RCSD"),
        float(raw == "KEEP_SWSD"),
        float(raw == "USE_RCSD"),
        float(raw == "ABSTAIN"),
        float(effective == "KEEP_SWSD"),
        float(effective == "USE_RCSD"),
        float(effective == "ABSTAIN"),
        float(bool(row.get("release_fallback_required"))),
        float(bool(row.get("all_required_anchors_resolved"))),
        float(bool(row.get("all_required_anchors_success"))),
        float(row.get("raw_predicted_probability") or 0.0),
        float(row.get("fallback_none_probability") or 0.0),
        float(row.get("fallback_segment_probability") or 0.0),
        float(row.get("fallback_junction_probability") or 0.0),
        float(row.get("predicted_clue_probability") or 0.0),
        math.log1p(required),
        resolved / denominator,
        success / denominator,
    ]


def _plan_node_ids(context: Mapping[str, Any]) -> set[str]:
    return {
        str(value)
        for row in context.get("road_members") or ()
        for value in (row.get("start_node_id"), row.get("end_node_id"))
        if str(value or "")
    }


def _candidate_relation_values(
    *,
    snode: str,
    enode: str,
    source_nodes: set[str],
    target_nodes: set[str],
    source_access: str,
    target_access: str,
) -> list[float]:
    return [
        float(snode in source_nodes),
        float(enode in source_nodes),
        float(bool({snode, enode} & source_nodes)),
        float(snode in target_nodes),
        float(enode in target_nodes),
        float(bool({snode, enode} & target_nodes)),
        float(bool(source_access) and snode == source_access),
        float(bool(source_access) and enode == source_access),
        float(bool(target_access) and snode == target_access),
        float(bool(target_access) and enode == target_access),
    ]


def _input_record(
    path: Path,
    role: str,
    case_key: str | None = None,
) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    result = {
        "path": str(resolved),
        "role": role,
        "sha256": sha256_file(resolved),
    }
    if case_key is not None:
        result["case_key"] = case_key
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "RELATION_FEATURE_NAMES",
    "SIDE_STATUS_FEATURE_NAMES",
    "build_advance_right_conditioned_store",
    "lock_ordinary_plan",
]
