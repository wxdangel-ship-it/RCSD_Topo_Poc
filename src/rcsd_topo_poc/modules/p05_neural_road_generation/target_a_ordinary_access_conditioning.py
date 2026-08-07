from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _read_roads,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ACCESS_ANCHOR_FEATURE_NAMES = (
    "condition_available",
    "anchor_status_success",
    "anchor_gate_passed",
    "anchor_proven_safe",
    "anchor_type_node",
    "anchor_type_road",
    "anchor_member_count_log",
    "road_is_anchor_member",
    "road_incident_anchor_node",
    "road_shares_anchor_road_endpoint",
    "road_within_0_5m_anchor_road",
    "candidate_confidence",
    "candidate_probability",
    "success_probability",
    "gate_pass_probability",
    "road_source_swsd",
    "road_source_rcsd",
)


@dataclass(frozen=True)
class ConditioningRoad:
    road_id: str
    source: str
    start_node_id: str
    end_node_id: str
    geometry: Any


def build_anchor_conditioned_access_store(
    *,
    access_store_root: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    output_root: Path,
) -> Path:
    """Join teacher-forced and OOF anchor conditions onto access proposals."""
    started = time.perf_counter()
    access_root = normalize_runtime_path(access_store_root).resolve(strict=True)
    anchor_root = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    oof_root = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    access_summary = _read_json(access_root / "summary.json")
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
    case_paths = _case_road_paths(access_summary)
    label_by_key = {
        (
            str(row["case_key"]),
            str(row["segment_id"]),
            str(row["junc_node_id"]),
        ): row
        for row in _read_jsonl(
            access_root / "ordinary_access_training_labels.jsonl"
        )
    }
    proposal_path = (
        access_root / "ordinary_access_inference_candidates.jsonl"
    )
    conditioned_path = root / "ordinary_access_conditioned_candidates.jsonl"
    label_path = root / "ordinary_access_training_labels.jsonl"
    counts: Counter[str] = Counter()
    case_inputs: list[dict[str, Any]] = []
    current_case = ""
    case_roads: dict[str, ConditioningRoad] = {}
    condition_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    conditioned_stream = conditioned_path.open("w", encoding="utf-8")
    with proposal_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            proposal = json.loads(line)
            case_key = str(proposal["case_key"])
            if case_key != current_case:
                current_case = case_key
                case_roads, records = _load_case_roads(
                    case_key,
                    case_paths[case_key],
                )
                case_inputs.extend(records)
            key = (
                case_key,
                str(proposal["segment_id"]),
                str(proposal["junc_node_id"]),
            )
            anchor_key = (case_key, key[2])
            feature = anchor_features.get(anchor_key)
            prediction = anchor_oof.get(anchor_key, {})
            if feature is None:
                label: Mapping[str, Any] = {}
                teacher_ids: list[str] = []
                counts["anchor_out_of_scope_proposal"] += 1
            else:
                if not prediction:
                    raise ValueError(
                        f"access anchor OOF prediction missing: {anchor_key}"
                    )
                label = anchor_labels.get(str(feature["sample_id"])) or {}
                if not label:
                    raise ValueError(
                        f"access anchor teacher label missing: {anchor_key}"
                    )
                teacher_ids = [
                    str(feature["candidate_ids"][index])
                    for index in (
                        label.get("candidate_acceptable_indices") or ()
                    )
                ]
            oof_id = str(prediction.get("candidate_predicted_id") or "")
            road = case_roads.get(str(proposal["road_id"]))
            if road is None:
                raise ValueError(
                    f"access proposal Road missing from Case: {key}"
                )
            teacher_values = anchor_condition_features(
                road=road,
                candidate_ids=teacher_ids,
                roads=case_roads,
                status_success=int(label.get("status_label", -1)) == 0,
                gate_passed=int(label.get("gate_label") or 0) == 1,
                proven_safe=bool(teacher_ids),
                candidate_confidence=1.0 if teacher_ids else 0.0,
                candidate_probability=1.0 if teacher_ids else 0.0,
                success_probability=(
                    1.0
                    if int(label.get("status_label", -1)) == 0
                    else 0.0
                ),
                gate_pass_probability=float(
                    int(label.get("gate_label") or 0) == 1
                ),
            )
            oof_values = anchor_condition_features(
                road=road,
                candidate_ids=[oof_id] if oof_id else [],
                roads=case_roads,
                status_success=str(
                    prediction.get("raw_status_predicted") or ""
                )
                == "SUCCESS",
                gate_passed=bool(prediction.get("gate_passed")),
                proven_safe=bool(prediction.get("proven_safe_anchor")),
                candidate_confidence=float(
                    prediction.get("candidate_confidence_score") or 0.0
                ),
                candidate_probability=float(
                    prediction.get("candidate_probability") or 0.0
                ),
                success_probability=float(
                    prediction.get("success_probability") or 0.0
                ),
                gate_pass_probability=float(
                    prediction.get("gate_pass_probability") or 0.0
                ),
            )
            conditioned = dict(proposal)
            conditioned["teacher_anchor_feature_values"] = teacher_values
            conditioned["oof_anchor_feature_values"] = oof_values
            conditioned["teacher_anchor_candidate_ids"] = teacher_ids
            conditioned["oof_anchor_candidate_id"] = oof_id
            conditioned["feature_uses_truth"] = False
            conditioned["terminal_input_count"] = 0
            conditioned_stream.write(
                json.dumps(conditioned, ensure_ascii=False, sort_keys=True)
            )
            conditioned_stream.write("\n")
            counts["proposal"] += 1
            counts["teacher_condition_available"] += int(
                teacher_values[0] > 0.5
            )
            counts["oof_condition_available"] += int(
                oof_values[0] > 0.5
            )
            counts["oof_anchor_release_ready_proposal"] += int(
                oof_values[3] > 0.5
            )
            condition_by_key[key] = {
                "teacher_anchor_candidate_ids": teacher_ids,
                "oof_anchor_candidate_id": oof_id,
                "teacher_condition_available": bool(teacher_ids),
                "oof_condition_available": bool(oof_id),
                "oof_anchor_release_ready": bool(
                    prediction.get("proven_safe_anchor")
                ),
                "anchor_status_predicted": str(
                    prediction.get("predicted") or ""
                ),
            }
    conditioned_stream.close()
    feature_hash_before_label_read = sha256_file(conditioned_path)
    conditioned_labels = []
    for key, label in sorted(label_by_key.items()):
        condition = condition_by_key.get(key)
        if condition is None:
            raise ValueError(f"access condition object missing: {key}")
        row = dict(label)
        row.update(condition)
        conditioned_labels.append(row)
        counts["access_object"] += 1
        counts["task_mask"] += int(row["access_task_mask"])
        counts["task_with_teacher_condition"] += int(
            row["access_task_mask"]
            and row["teacher_condition_available"]
        )
        counts["task_with_oof_release_anchor"] += int(
            row["access_task_mask"]
            and row["oof_anchor_release_ready"]
        )
    _write_jsonl(label_path, conditioned_labels)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ACCESS_ANCHOR_CONDITIONING",
        "business_contract": {
            "teacher": (
                "Training uses only the independently supervised anchor "
                "candidate set. Candidate-unspecified SUCCESS rows do not "
                "invent an anchor object and therefore have no access target."
            ),
            "inference": (
                "OOF access features use only the anchor model prediction. "
                "The access head cannot change, bypass, or repair the anchor."
            ),
            "release": (
                "An access prediction is never releasable unless the upstream "
                "anchor is independently proven safe."
            ),
        },
        "anchor_feature_names": list(ACCESS_ANCHOR_FEATURE_NAMES),
        "anchor_feature_dim": len(ACCESS_ANCHOR_FEATURE_NAMES),
        "counts": dict(sorted(counts.items())),
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": feature_hash_before_label_read,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "io_contract": (
            "Each Case Road store is loaded once while proposals are streamed "
            "in Case order; no per-Segment GPKG reread is performed."
        ),
        "inputs": {
            "access_summary": _input_record(access_root / "summary.json"),
            "anchor_manifest": _input_record(anchor_root / "manifest.json"),
            "anchor_oof_summary": _input_record(oof_root / "summary.json"),
            "case_roads": case_inputs,
        },
        "outputs": {
            "conditioned_candidates": _input_record(conditioned_path),
            "training_labels": _input_record(label_path),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(conditioned_labels) == len(label_by_key)
            and counts["proposal"] > 0
            and sha256_file(conditioned_path) == feature_hash_before_label_read
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary access anchor conditioning gate failed")
    return root


def anchor_condition_features(
    *,
    road: ConditioningRoad,
    candidate_ids: Sequence[str],
    roads: Mapping[str, ConditioningRoad],
    status_success: bool,
    gate_passed: bool,
    proven_safe: bool,
    candidate_confidence: float,
    candidate_probability: float,
    success_probability: float,
    gate_pass_probability: float,
) -> list[float]:
    parsed = [_parse_candidate_id(value) for value in candidate_ids if value]
    node_ids = {
        member
        for candidate_type, members in parsed
        if candidate_type == "NODE"
        for member in members
    }
    anchor_road_ids = {
        member
        for candidate_type, members in parsed
        if candidate_type == "ROAD"
        for member in members
    }
    anchor_roads = [
        roads[road_id]
        for road_id in sorted(anchor_road_ids)
        if road_id in roads
    ]
    anchor_endpoints = {
        value
        for anchor_road in anchor_roads
        for value in (
            anchor_road.start_node_id,
            anchor_road.end_node_id,
        )
        if value
    }
    candidate_types = {candidate_type for candidate_type, _ in parsed}
    minimum_gap = min(
        (
            float(road.geometry.distance(anchor_road.geometry))
            for anchor_road in anchor_roads
        ),
        default=math.inf,
    )
    member_count = len(node_ids | anchor_road_ids)
    values = [
        float(bool(parsed)),
        float(status_success),
        float(gate_passed),
        float(proven_safe),
        float("NODE" in candidate_types),
        float("ROAD" in candidate_types),
        math.tanh(math.log1p(member_count) / 4.0),
        float(road.road_id in anchor_road_ids),
        float(
            bool(node_ids)
            and bool(
                {road.start_node_id, road.end_node_id} & node_ids
            )
        ),
        float(
            bool(anchor_endpoints)
            and bool(
                {road.start_node_id, road.end_node_id}
                & anchor_endpoints
            )
        ),
        float(minimum_gap <= 0.5),
        _probability(candidate_confidence),
        _probability(candidate_probability),
        _probability(success_probability),
        _probability(gate_pass_probability),
        float(road.source == "SWSD"),
        float(road.source == "RCSD"),
    ]
    if len(values) != len(ACCESS_ANCHOR_FEATURE_NAMES):
        raise AssertionError("access anchor condition feature dimension drifted")
    return values


def _parse_candidate_id(value: str) -> tuple[str, tuple[str, ...]]:
    candidate_type, separator, payload = value.partition(":")
    if not separator or candidate_type not in {"NODE", "ROAD"}:
        return "", ()
    return candidate_type, tuple(
        sorted(member for member in payload.split("|") if member)
    )


def _case_road_paths(
    summary: Mapping[str, Any],
) -> dict[str, tuple[Path, Path]]:
    values: dict[str, dict[str, Path]] = {}
    for record in summary["inputs"]["case_inputs"]:
        case_key = str(record["case_key"])
        path = normalize_runtime_path(Path(str(record["path"])))
        normalized = path.as_posix().casefold()
        if normalized.endswith("/t01/roads.gpkg"):
            values.setdefault(case_key, {})["SWSD"] = path
        elif (
            "/external_inputs/rcsdroad/" in normalized
            and normalized.endswith(".gpkg")
        ):
            values.setdefault(case_key, {})["RCSD"] = path
    missing = [
        case_key
        for case_key, paths in values.items()
        if set(paths) != {"SWSD", "RCSD"}
    ]
    if missing:
        raise ValueError(f"access conditioning Case Road paths missing: {missing}")
    return {
        case_key: (paths["SWSD"], paths["RCSD"])
        for case_key, paths in values.items()
    }


def _load_case_roads(
    case_key: str,
    paths: tuple[Path, Path],
) -> tuple[dict[str, ConditioningRoad], list[dict[str, Any]]]:
    roads: dict[str, ConditioningRoad] = {}
    records = []
    for source, path in zip(("SWSD", "RCSD"), paths):
        resolved = path.resolve(strict=True)
        records.append(_input_record(resolved, case_key=case_key))
        for value in _read_roads(resolved):
            row = ConditioningRoad(
                road_id=value.road_id,
                source=source,
                start_node_id=value.snodeid,
                end_node_id=value.enodeid,
                geometry=value.geometry,
            )
            existing = roads.get(row.road_id)
            if existing is not None and not existing.geometry.equals(
                row.geometry
            ):
                raise ValueError(
                    f"access conditioning Road collision: {case_key}:{row.road_id}"
                )
            roads[row.road_id] = row
    return roads, records


def _probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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
    record = {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    if case_key:
        record["case_key"] = case_key
    return record


__all__ = [
    "ACCESS_ANCHOR_FEATURE_NAMES",
    "ConditioningRoad",
    "anchor_condition_features",
    "build_anchor_conditioned_access_store",
]
