from __future__ import annotations

import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def build_advance_right_attachment_condition_store(
    *,
    base_access_set_store_root: Path,
    attachment_supervision_root: Path,
    attachment_prediction_root: Path,
    output_root: Path,
) -> Path:
    """Lock teacher/OOF side attachments without changing base features."""
    started = time.perf_counter()
    base = normalize_runtime_path(base_access_set_store_root).resolve(
        strict=True
    )
    supervision = normalize_runtime_path(
        attachment_supervision_root
    ).resolve(strict=True)
    predictions = normalize_runtime_path(
        attachment_prediction_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    feature_input = base / "advance_right_access_set_features.jsonl"
    feature_output = root / feature_input.name
    shutil.copyfile(feature_input, feature_output)
    frozen_feature_hash = sha256_file(feature_output)
    features = {
        _object_key(row): row for row in _read_jsonl(feature_input)
    }
    if len(features) != 474:
        raise ValueError("AdvanceRight attachment conditioning scope differs")

    teacher_base = _unique_by_object(
        _read_jsonl(base / "advance_right_teacher_conditions.jsonl")
    )
    oof_base = _unique_by_object(
        _read_jsonl(base / "advance_right_oof_conditions.jsonl")
    )
    if set(features) != set(teacher_base) or set(features) != set(oof_base):
        raise ValueError("AdvanceRight attachment condition scopes differ")

    action_rows = _read_jsonl(
        supervision / "advance_right_attachment_supervision.jsonl"
    )
    explicit_action_keys = {
        _side_key(row)
        for row in action_rows
        if str(row.get("side") or "") in {"SOURCE", "TARGET"}
    }
    prediction_rows = _read_jsonl(
        predictions / "oof_predictions.jsonl"
    )
    prediction_by_side = _unique_by_side(prediction_rows)
    if set(prediction_by_side) - explicit_action_keys:
        raise ValueError("attachment prediction lacks T06 action supervision")

    counts: Counter[str] = Counter()
    teacher_conditions = []
    oof_conditions = []
    for key in sorted(features):
        feature = features[key]
        teacher = teacher_base[key]
        oof = oof_base[key]
        teacher_sides = {}
        oof_sides = {}
        for side_name in ("SOURCE", "TARGET"):
            side_key = (key[0], key[1], side_name)
            side_feature = feature[f"{side_name.lower()}_side"]
            prediction = prediction_by_side.get(side_key)
            teacher_side = attachment_side_condition(
                teacher[f"{side_name.lower()}_condition"],
                side_feature=side_feature,
                prediction=prediction,
                condition_view="TEACHER",
                explicit_rcsd_action=side_key in explicit_action_keys,
            )
            oof_side = attachment_side_condition(
                oof[f"{side_name.lower()}_condition"],
                side_feature=side_feature,
                prediction=prediction,
                condition_view="STRICT_OOF",
                explicit_rcsd_action=side_key in explicit_action_keys,
            )
            teacher_sides[side_name.lower()] = teacher_side
            oof_sides[side_name.lower()] = oof_side
            counts[
                f"teacher_{side_name.lower()}_{teacher_side['resolution']}"
            ] += 1
            counts[f"oof_{side_name.lower()}_{oof_side['resolution']}"] += 1
            if prediction is not None:
                counts["teacher_target_proposal_available"] += 1
                counts["oof_selected_proposal_available"] += 1
                counts["oof_selected_proposal_exact"] += int(
                    bool(prediction["raw_exact"])
                )
                counts["oof_prediction_used"] += int(
                    bool(oof_side["access_proposal_ids"])
                )
                counts["oof_prediction_suppressed"] += int(
                    not bool(oof_side["access_proposal_ids"])
                )
        teacher_conditions.append(
            _condition_row(
                teacher,
                teacher_sides,
                condition_kind="TEACHER_T06_SIDE_ATTACHMENT_STATE",
                uses_truth=True,
            )
        )
        oof_conditions.append(
            _condition_row(
                oof,
                oof_sides,
                condition_kind="STRICT_OOF_T06_SIDE_ATTACHMENT_STATE",
                uses_truth=False,
            )
        )

    teacher_path = root / "advance_right_teacher_conditions.jsonl"
    oof_path = root / "advance_right_oof_conditions.jsonl"
    label_input = base / "advance_right_training_labels.jsonl"
    label_output = root / label_input.name
    _write_jsonl(teacher_path, teacher_conditions)
    _write_jsonl(oof_path, oof_conditions)
    shutil.copyfile(label_input, label_output)
    oof_forbidden_field_count = sum(
        _count_forbidden_oof_fields(row) for row in oof_conditions
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_T06_SIDE_ATTACHMENT_CONDITIONING",
        "business_contract": {
            "order": (
                "ordinary Segment final decision locks each side source; an "
                "RCSD side then selects one parent Road and attachment position"
            ),
            "teacher": (
                "teacher conditions use only the exact reachable T06 side "
                "attachment proposal"
            ),
            "strict_oof": (
                "strict OOF conditions use only the held-out Case prediction; "
                "a KEEP_SWSD side suppresses an RCSD attachment prediction"
            ),
            "fallback": (
                "an RCSD side without a reachable unique proposal stays "
                "unresolved and cannot become an automatic plan"
            ),
        },
        "object_count": len(features),
        "side_count": len(features) * 2,
        "prediction_count": len(prediction_by_side),
        "explicit_t06_action_side_count": len(explicit_action_keys),
        "counts": dict(sorted(counts.items())),
        "inputs": {
            "base_features": _input_record(feature_input),
            "base_teacher_conditions": _input_record(
                base / "advance_right_teacher_conditions.jsonl"
            ),
            "base_oof_conditions": _input_record(
                base / "advance_right_oof_conditions.jsonl"
            ),
            "attachment_supervision": _input_record(
                supervision
                / "advance_right_attachment_supervision.jsonl"
            ),
            "attachment_predictions": _input_record(
                predictions / "oof_predictions.jsonl"
            ),
            "labels": _input_record(label_input),
        },
        "outputs": {
            "features": _input_record(feature_output),
            "teacher_conditions": _input_record(teacher_path),
            "oof_conditions": _input_record(oof_path),
            "labels": _input_record(label_output),
        },
        "feature_uses_truth": False,
        "oof_condition_uses_truth": False,
        "teacher_condition_uses_truth": True,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "oof_forbidden_field_count": oof_forbidden_field_count,
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": bool(
            len(teacher_conditions) == len(features)
            and len(oof_conditions) == len(features)
            and len(prediction_by_side) == 563
            and frozen_feature_hash == sha256_file(feature_input)
            and frozen_feature_hash == sha256_file(feature_output)
            and sha256_file(label_input) == sha256_file(label_output)
            and oof_forbidden_field_count == 0
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight attachment conditioning gate failed")
    return root


def attachment_side_condition(
    base_condition: Mapping[str, Any],
    *,
    side_feature: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    condition_view: str,
    explicit_rcsd_action: bool,
) -> dict[str, Any]:
    """Replace legacy single-Road access evidence with a staged attachment."""
    if condition_view not in {"TEACHER", "STRICT_OOF"}:
        raise ValueError("unsupported attachment condition view")
    condition = dict(base_condition)
    condition.update(
        {
            "access_road_ids": [],
            "access_proposal_ids": [],
            "access_road_resolved": False,
            "access_release_ready": False,
            "complete_release_ready": False,
        }
    )
    decision = str(condition.get("selected_decision") or "")
    if condition_view == "STRICT_OOF" and decision == "KEEP_SWSD":
        return _resolved_swsd_condition(
            condition,
            resolution="OOF_SWSD_ACCESS_DETERMINISTIC",
            uses_truth=False,
        )
    if condition_view == "TEACHER" and prediction is None:
        if decision == "KEEP_SWSD" and not explicit_rcsd_action:
            return _resolved_swsd_condition(
                condition,
                resolution="TEACHER_SWSD_ACCESS_DETERMINISTIC",
                uses_truth=True,
            )
        return _unresolved_rcsd_condition(
            condition,
            resolution=(
                "TEACHER_RCSD_ATTACHMENT_UNREACHABLE"
                if explicit_rcsd_action
                else "TEACHER_SIDE_SOURCE_UNRESOLVED"
            ),
            uses_truth=True,
            source_known=explicit_rcsd_action or decision == "USE_RCSD",
        )
    if condition_view == "STRICT_OOF" and decision != "USE_RCSD":
        return _unresolved_rcsd_condition(
            condition,
            resolution="OOF_SIDE_SOURCE_UNRESOLVED",
            uses_truth=False,
            source_known=False,
        )
    if prediction is None:
        return _unresolved_rcsd_condition(
            condition,
            resolution="OOF_RCSD_ATTACHMENT_UNREACHABLE",
            uses_truth=False,
            source_known=True,
        )
    proposal_field = (
        "target_proposal_id"
        if condition_view == "TEACHER"
        else "selected_proposal_id"
    )
    proposal_id = str(prediction[proposal_field])
    candidate = _unique_proposal(side_feature, proposal_id)
    if str(candidate.get("source") or "") != "RCSD":
        raise ValueError("T06 side attachment proposal is not RCSD")
    condition.update(
        {
            "access_source": "RCSD",
            "access_source_resolved": True,
            "access_road_ids": [str(candidate["road_id"])],
            "access_proposal_ids": [proposal_id],
            "access_road_resolved": True,
            "access_release_ready": bool(
                condition_view == "TEACHER" or prediction.get("automatic")
            ),
            "complete_release_ready": bool(
                condition.get("ordinary_release_ready")
                and (
                    condition_view == "TEACHER"
                    or prediction.get("automatic")
                )
            ),
            "resolution": (
                "TEACHER_T06_ATTACHMENT_LOCKED"
                if condition_view == "TEACHER"
                else "OOF_T06_ATTACHMENT_SELECTED"
            ),
            "condition_uses_truth": condition_view == "TEACHER",
        }
    )
    return condition


def _resolved_swsd_condition(
    condition: Mapping[str, Any],
    *,
    resolution: str,
    uses_truth: bool,
) -> dict[str, Any]:
    result = dict(condition)
    result.update(
        {
            "access_source": "SWSD",
            "access_source_resolved": True,
            "access_road_ids": [],
            "access_proposal_ids": [],
            "access_road_resolved": True,
            "access_release_ready": True,
            "complete_release_ready": bool(
                result.get("ordinary_release_ready")
            ),
            "resolution": resolution,
            "condition_uses_truth": uses_truth,
        }
    )
    return result


def _unresolved_rcsd_condition(
    condition: Mapping[str, Any],
    *,
    resolution: str,
    uses_truth: bool,
    source_known: bool,
) -> dict[str, Any]:
    result = dict(condition)
    result.update(
        {
            "access_source": "RCSD" if source_known else "UNRESOLVED",
            "access_source_resolved": source_known,
            "access_road_ids": [],
            "access_proposal_ids": [],
            "access_road_resolved": False,
            "access_release_ready": False,
            "complete_release_ready": False,
            "resolution": resolution,
            "condition_uses_truth": uses_truth,
        }
    )
    return result


def _condition_row(
    base: Mapping[str, Any],
    sides: Mapping[str, Mapping[str, Any]],
    *,
    condition_kind: str,
    uses_truth: bool,
) -> dict[str, Any]:
    source = dict(sides["source"])
    target = dict(sides["target"])
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": str(base["case_key"]),
        "object_id": str(base["object_id"]),
        "fold": int(base["fold"]),
        "source_condition": source,
        "target_condition": target,
        "both_access_source_resolved": bool(
            source["access_source_resolved"]
            and target["access_source_resolved"]
        ),
        "both_access_road_resolved": bool(
            source["access_road_resolved"]
            and target["access_road_resolved"]
        ),
        "condition_kind": condition_kind,
        "condition_uses_truth": uses_truth,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _unique_proposal(
    side_feature: Mapping[str, Any],
    proposal_id: str,
) -> Mapping[str, Any]:
    matches = [
        row
        for row in side_feature.get("access_candidates") or ()
        if str(row["proposal_id"]) == proposal_id
    ]
    if len(matches) != 1:
        raise ValueError("attachment proposal is missing or duplicated")
    return matches[0]


def _count_forbidden_oof_fields(value: Any) -> int:
    forbidden = {
        "target_proposal_id",
        "teacher_selected_proposal_id",
        "raw_exact",
        "teacher_exact",
        "attachment_task_mask",
    }
    if isinstance(value, Mapping):
        return sum(
            int(str(key) in forbidden) + _count_forbidden_oof_fields(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return sum(_count_forbidden_oof_fields(item) for item in value)
    return 0


def _unique_by_object(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {_object_key(row): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("AdvanceRight object rows contain duplicates")
    return result


def _unique_by_side(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    result = {_side_key(row): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("AdvanceRight side rows contain duplicates")
    if any(key[2] not in {"SOURCE", "TARGET"} for key in result):
        raise ValueError("AdvanceRight prediction side is invalid")
    return result


def _object_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _side_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["object_id"]),
        str(row["side"]),
    )


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            stream.write("\n")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


__all__ = [
    "attachment_side_condition",
    "build_advance_right_attachment_condition_store",
]
