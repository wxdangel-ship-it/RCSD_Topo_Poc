from __future__ import annotations

import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def build_advance_right_final_state_condition_store(
    *,
    base_access_set_store_root: Path,
    ordinary_release_prediction_root: Path,
    output_root: Path,
) -> Path:
    """Condition AdvanceRight on the final ordinary state after fallback."""
    started = time.perf_counter()
    base = normalize_runtime_path(base_access_set_store_root).resolve(
        strict=True
    )
    ordinary = normalize_runtime_path(
        ordinary_release_prediction_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    prediction_path = ordinary / "ensemble_gated_oof_predictions.jsonl"
    predictions = _unique_predictions(_jsonl_rows(prediction_path))
    feature_input = base / "advance_right_access_set_features.jsonl"
    teacher_input = base / "advance_right_teacher_conditions.jsonl"
    label_input = base / "advance_right_training_labels.jsonl"
    reused = {}
    for source in (feature_input, teacher_input, label_input):
        target = root / source.name
        reused[source.name] = _link_or_copy(source, target)

    counts: Counter[str] = Counter()
    conditions = []
    fold_mismatches = []
    selected_member_missing = []
    for feature in _jsonl_rows(feature_input):
        case_key = str(feature["case_key"])
        fold = int(feature["fold"])
        sides = {}
        for side_name in ("source", "target"):
            side = feature[f"{side_name}_side"]
            segment_id = str(side.get("owner_segment_id") or "")
            prediction = predictions.get((case_key, segment_id))
            if prediction is not None and int(prediction["fold"]) != fold:
                fold_mismatches.append(
                    (
                        case_key,
                        str(feature["object_id"]),
                        side_name,
                        segment_id,
                        fold,
                        int(prediction["fold"]),
                    )
                )
                prediction = None
            condition = final_ordinary_side_condition(
                side,
                prediction=prediction,
            )
            sides[side_name] = condition
            counts["side"] += 1
            counts[
                f"outcome_{condition['final_outcome_kind']}"
            ] += 1
            counts[
                "side_final_state_ready"
                if condition["final_state_ready"]
                else "side_final_state_unresolved"
            ] += 1
            counts[
                "side_prediction_joined"
                if prediction is not None
                else "side_prediction_missing"
            ] += 1
            if condition["resolution"] == "SELECTED_ROAD_MEMBER_MISSING":
                selected_member_missing.append(
                    (
                        case_key,
                        str(feature["object_id"]),
                        side_name,
                        segment_id,
                    )
                )
        row = {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "case_key": case_key,
            "object_id": str(feature["object_id"]),
            "fold": fold,
            "source_condition": sides["source"],
            "target_condition": sides["target"],
            "both_access_source_resolved": all(
                bool(sides[name]["access_source_resolved"])
                for name in ("source", "target")
            ),
            "both_access_road_resolved": all(
                bool(sides[name]["access_road_resolved"])
                for name in ("source", "target")
            ),
            "both_final_state_ready": all(
                bool(sides[name]["final_state_ready"])
                for name in ("source", "target")
            ),
            "condition_kind": "STRICT_OOF_FINAL_ORDINARY_STATE",
            "condition_uses_truth": False,
            "feature_uses_truth": False,
            "terminal_input_count": 0,
        }
        conditions.append(row)
        counts["object"] += 1
        counts["object_final_state_ready"] += int(
            row["both_final_state_ready"]
        )

    condition_path = root / "advance_right_oof_conditions.jsonl"
    _write_jsonl(condition_path, conditions)
    forbidden = _forbidden_field_count(conditions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_FINAL_ORDINARY_STATE_CONDITIONING",
        "business_contract": {
            "ordinary_order": (
                "Anchor and complete ordinary Road decisions are locked before "
                "AdvanceRight; AdvanceRight cannot change them."
            ),
            "positive_keep": (
                "A released KEEP_SWSD remains a positive neural business "
                "decision and is not counted as fallback."
            ),
            "fallback": (
                "A missing or rejected ordinary prediction restores the "
                "complete T01 Segment SWSD Road set and is recorded as "
                "ABSTAIN -> FALLBACK_SWSD."
            ),
            "swsd_candidate_source": (
                "SWSD side candidates were built from the owning T01 "
                "Segment.swsd_road_ids, not from a spatial neighborhood."
            ),
            "access": (
                "For final SWSD state, access Roads are the selected T01 "
                "Roads incident to the frozen T01 access node. RCSD access "
                "remains unresolved until the neural attachment stage."
            ),
        },
        "counts": dict(sorted(counts.items())),
        "fold_mismatch_count": len(fold_mismatches),
        "selected_member_missing_count": len(selected_member_missing),
        "feature_uses_truth": False,
        "oof_condition_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "oof_forbidden_field_count": forbidden,
        "io_contract": (
            "Index ordinary predictions once, stream the AdvanceRight feature "
            "store once, and hard-link unchanged large inputs when supported."
        ),
        "reused_file_modes": reused,
        "inputs": {
            "base_features": _input_record(feature_input),
            "teacher_conditions": _input_record(teacher_input),
            "labels": _input_record(label_input),
            "ordinary_release_predictions": _input_record(prediction_path),
        },
        "outputs": {
            "features": _input_record(
                root / "advance_right_access_set_features.jsonl"
            ),
            "teacher_conditions": _input_record(
                root / "advance_right_teacher_conditions.jsonl"
            ),
            "oof_conditions": _input_record(condition_path),
            "labels": _input_record(
                root / "advance_right_training_labels.jsonl"
            ),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": bool(
            len(conditions) == 474
            and counts["side"] == 948
            and not fold_mismatches
            and not selected_member_missing
            and forbidden == 0
            and sha256_file(feature_input)
            == sha256_file(
                root / "advance_right_access_set_features.jsonl"
            )
            and sha256_file(teacher_input)
            == sha256_file(
                root / "advance_right_teacher_conditions.jsonl"
            )
            and sha256_file(label_input)
            == sha256_file(
                root / "advance_right_training_labels.jsonl"
            )
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight final-state conditioning gate failed")
    return root


def final_ordinary_side_condition(
    side: Mapping[str, Any],
    *,
    prediction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    segment_id = str(side.get("owner_segment_id") or "")
    rows = list(side.get("road_candidates") or ())
    source_by_id = {
        str(row["road_id"]): str(row.get("source") or "")
        for row in rows
    }
    swsd_ids = sorted(
        road_id
        for road_id, source in source_by_id.items()
        if source == "SWSD"
    )
    automatic = bool(prediction and prediction.get("automatic"))
    if automatic:
        decision = str(prediction.get("predicted_decision") or "")
        if decision not in {"KEEP_SWSD", "USE_RCSD"}:
            raise ValueError("released ordinary decision is unsupported")
        selected = sorted(
            {str(value) for value in prediction.get("selected_road_ids") or ()}
        )
        expected_source = "SWSD" if decision == "KEEP_SWSD" else "RCSD"
        outcome = (
            "POSITIVE_KEEP_SWSD"
            if decision == "KEEP_SWSD"
            else "AUTO_USE_RCSD"
        )
        carrier_probability = float(
            prediction.get("confidence")
            or prediction.get("decision_confidence")
            or 0.0
        )
    else:
        decision = "ABSTAIN"
        selected = swsd_ids
        expected_source = "SWSD"
        outcome = "FALLBACK_SWSD"
        carrier_probability = 0.0

    if not segment_id or not rows or not selected:
        return _unresolved_side(
            decision=decision,
            outcome=outcome,
            resolution=(
                "OWNER_SEGMENT_MISSING"
                if not segment_id
                else "T01_FALLBACK_ROAD_SET_MISSING"
            ),
        )
    if set(selected) - set(source_by_id):
        return _unresolved_side(
            decision=decision,
            outcome=outcome,
            resolution="SELECTED_ROAD_MEMBER_MISSING",
        )
    selected_sources = {source_by_id[value] for value in selected}
    if selected_sources != {expected_source}:
        raise ValueError("released ordinary Road source differs from decision")

    access_ids = _incident_access_road_ids(
        side,
        selected_road_ids=selected,
    )
    access_resolved = bool(access_ids) if expected_source == "SWSD" else False
    resolution = {
        "POSITIVE_KEEP_SWSD": "POSITIVE_KEEP_SWSD_LOCKED",
        "FALLBACK_SWSD": "FALLBACK_SWSD_LOCKED",
        "AUTO_USE_RCSD": "AUTO_USE_RCSD_ACCESS_PENDING",
    }[outcome]
    if expected_source == "SWSD" and not access_resolved:
        resolution = f"{outcome}_ACCESS_ROAD_MISSING"
    return {
        "selected_road_ids": selected,
        "selected_decision": decision,
        "access_source": expected_source,
        "access_source_resolved": True,
        "access_road_ids": access_ids,
        "access_proposal_ids": [],
        "access_road_resolved": access_resolved,
        "carrier_probability": carrier_probability,
        "ordinary_release_ready": automatic,
        "access_release_ready": access_resolved,
        "complete_release_ready": bool(automatic and access_resolved),
        "final_state_ready": bool(
            expected_source == "SWSD" and access_resolved
        ),
        "final_outcome_kind": outcome,
        "fallback_applied": outcome == "FALLBACK_SWSD",
        "ordinary_automatic": automatic,
        "resolution": resolution,
        "condition_uses_truth": False,
    }


def _incident_access_road_ids(
    side: Mapping[str, Any],
    *,
    selected_road_ids: Sequence[str],
) -> list[str]:
    selected = {str(value) for value in selected_road_ids}
    access_node = str(side.get("t01_access_node_id") or "")
    if not access_node:
        return []
    return sorted(
        {
            str(row["road_id"])
            for row in side.get("road_candidates") or ()
            if str(row["road_id"]) in selected
            and access_node
            in {
                str(row.get("start_node_id") or ""),
                str(row.get("end_node_id") or ""),
            }
        }
    )


def _unresolved_side(
    *,
    decision: str,
    outcome: str,
    resolution: str,
) -> dict[str, Any]:
    return {
        "selected_road_ids": [],
        "selected_decision": decision,
        "access_source": "UNRESOLVED",
        "access_source_resolved": False,
        "access_road_ids": [],
        "access_proposal_ids": [],
        "access_road_resolved": False,
        "carrier_probability": 0.0,
        "ordinary_release_ready": False,
        "access_release_ready": False,
        "complete_release_ready": False,
        "final_state_ready": False,
        "final_outcome_kind": outcome,
        "fallback_applied": outcome == "FALLBACK_SWSD",
        "ordinary_automatic": False,
        "resolution": resolution,
        "condition_uses_truth": False,
    }


def _unique_predictions(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["segment_id"]))
        if key in result:
            raise ValueError("ordinary release predictions contain duplicates")
        result[key] = row
    return result


def _link_or_copy(source: Path, target: Path) -> str:
    try:
        os.link(source, target)
        return "HARDLINK"
    except OSError:
        shutil.copyfile(source, target)
        return "COPY"


def _forbidden_field_count(rows: Sequence[Mapping[str, Any]]) -> int:
    allowed_metadata = {
        "condition_uses_truth",
        "feature_uses_truth",
        "source_condition",
        "target_condition",
    }
    forbidden = 0
    stack: list[Any] = list(rows)
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            for key, child in value.items():
                lowered = str(key).lower()
                forbidden += int(
                    lowered not in allowed_metadata
                    and (
                        "truth" in lowered
                        or lowered.startswith("target_")
                        or lowered.startswith("formal_")
                    )
                )
                stack.append(child)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes)
        ):
            stack.extend(value)
    return forbidden


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True)
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "build_advance_right_final_state_condition_store",
    "final_ordinary_side_condition",
]
