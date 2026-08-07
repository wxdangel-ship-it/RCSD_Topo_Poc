from __future__ import annotations

import json
import math
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


ACCESS_CARRIER_FEATURE_NAMES = (
    "condition_available",
    "decision_keep_swsd",
    "decision_use_rcsd",
    "road_in_complete_carrier",
    "road_source_matches_decision",
    "carrier_cardinality_log",
    "decision_confidence",
    "road_set_confidence",
    "upstream_release_ready",
    "road_is_swsd",
    "road_is_rcsd",
)


def build_carrier_conditioned_access_store(
    *,
    anchor_conditioned_access_root: Path,
    road_member_store_root: Path,
    ordinary_carrier_oof_root: Path,
    use_road_oof_root: Path,
    output_root: Path,
) -> Path:
    """Condition access proposals on teacher and OOF complete Road bundles."""
    started = time.perf_counter()
    access_root = normalize_runtime_path(
        anchor_conditioned_access_root
    ).resolve(strict=True)
    member_root = normalize_runtime_path(
        road_member_store_root
    ).resolve(strict=True)
    carrier_root = normalize_runtime_path(
        ordinary_carrier_oof_root
    ).resolve(strict=True)
    use_root = normalize_runtime_path(use_road_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    member_features = {
        (str(row["case_key"]), str(row["segment_id"])): {
            "swsd_road_ids": {
                str(candidate["road_id"])
                for candidate in row["candidate_rows"]
                if str(candidate["source"]) == "SWSD"
            }
        }
        for row in _read_jsonl(
            member_root / "ordinary_road_member_features.jsonl"
        )
    }
    member_labels = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(
            member_root / "ordinary_road_member_labels.jsonl"
        )
    }
    carrier_oof = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(carrier_root / "oof_predictions.jsonl")
    }
    use_oof = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(use_root / "oof_predictions.jsonl")
    }
    access_labels = {
        (
            str(row["case_key"]),
            str(row["segment_id"]),
            str(row["junc_node_id"]),
        ): row
        for row in _read_jsonl(
            access_root / "ordinary_access_training_labels.jsonl"
        )
    }
    feature_path = root / "ordinary_access_conditioned_candidates.jsonl"
    label_path = root / "ordinary_access_training_labels.jsonl"
    output = feature_path.open("w", encoding="utf-8")
    counts: Counter[str] = Counter()
    carrier_condition_by_segment: dict[tuple[str, str], dict[str, Any]] = {}
    proposal_path = (
        access_root / "ordinary_access_conditioned_candidates.jsonl"
    )
    with proposal_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            proposal = json.loads(line)
            segment_key = (
                str(proposal["case_key"]),
                str(proposal["segment_id"]),
            )
            member_label = member_labels[segment_key]
            member_feature = member_features[segment_key]
            teacher_ready = bool(member_label["task_mask"])
            teacher_decision = str(member_label["preferred_decision"])
            teacher_ids = {
                str(value)
                for value in member_label["acceptable_road_ids"]
            }
            carrier = carrier_oof.get(segment_key)
            oof_decision = (
                str(carrier.get("raw_predicted_decision") or "")
                if carrier is not None
                else ""
            )
            use = use_oof.get(segment_key)
            if oof_decision == "KEEP_SWSD":
                oof_ids = set(member_feature["swsd_road_ids"])
                set_confidence = 1.0
                release_ready = bool(
                    carrier
                    and carrier.get("automatic_decision")
                    and carrier.get("effective_decision") == "KEEP_SWSD"
                )
            elif oof_decision == "USE_RCSD" and use is not None:
                oof_ids = {
                    str(value) for value in use["selected_road_ids"]
                }
                set_confidence = float(use.get("confidence") or 0.0)
                release_ready = bool(
                    carrier
                    and carrier.get("automatic_decision")
                    and carrier.get("effective_decision") == "USE_RCSD"
                    and use.get("conditional_automatic")
                )
            else:
                oof_ids = set()
                set_confidence = 0.0
                release_ready = False
            teacher_values = carrier_condition_features(
                road_id=str(proposal["road_id"]),
                road_source=str(proposal["source"]),
                decision=teacher_decision,
                selected_road_ids=teacher_ids,
                condition_available=teacher_ready,
                decision_confidence=1.0 if teacher_ready else 0.0,
                road_set_confidence=1.0 if teacher_ready else 0.0,
                release_ready=False,
            )
            oof_values = carrier_condition_features(
                road_id=str(proposal["road_id"]),
                road_source=str(proposal["source"]),
                decision=oof_decision,
                selected_road_ids=oof_ids,
                condition_available=bool(carrier and oof_ids),
                decision_confidence=float(
                    carrier.get("raw_predicted_probability") or 0.0
                )
                if carrier
                else 0.0,
                road_set_confidence=set_confidence,
                release_ready=release_ready,
            )
            row = dict(proposal)
            row["teacher_carrier_feature_values"] = teacher_values
            row["oof_carrier_feature_values"] = oof_values
            row["feature_uses_truth"] = False
            row["terminal_input_count"] = 0
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            output.write("\n")
            counts["proposal"] += 1
            counts["teacher_carrier_condition_proposal"] += int(
                teacher_ready
            )
            counts["oof_carrier_condition_proposal"] += int(
                oof_values[0] > 0.5
            )
            counts["oof_complete_carrier_release_proposal"] += int(
                release_ready
            )
            carrier_condition_by_segment[segment_key] = {
                "teacher_carrier_ready": teacher_ready,
                "teacher_carrier_decision": teacher_decision,
                "oof_carrier_condition_available": bool(carrier and oof_ids),
                "oof_carrier_decision": oof_decision,
                "oof_complete_carrier_release_ready": release_ready,
            }
    output.close()
    feature_hash_before_label_read = sha256_file(feature_path)
    labels = []
    for key, label in sorted(access_labels.items()):
        condition = carrier_condition_by_segment[key[:2]]
        row = dict(label)
        row.update(condition)
        row["upstream_plan_release_blocked"] = not bool(
            condition["oof_complete_carrier_release_ready"]
        )
        labels.append(row)
        counts["access_object"] += 1
        counts["access_task"] += int(row["access_task_mask"])
        counts["teacher_anchor_and_carrier_ready"] += int(
            row["access_task_mask"]
            and row["teacher_condition_available"]
            and row["teacher_carrier_ready"]
        )
        counts["oof_anchor_and_carrier_release_ready"] += int(
            row["oof_anchor_release_ready"]
            and row["oof_complete_carrier_release_ready"]
        )
    _write_jsonl(label_path, labels)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ACCESS_COMPLETE_CARRIER_CONDITIONING",
        "business_contract": {
            "teacher": (
                "Access training requires both an independently supervised "
                "anchor and a reachable complete teacher Road bundle."
            ),
            "inference": (
                "Access OOF features use the ordinary carrier model decision, "
                "deterministic KEEP expansion, or the USE Road graph decoder."
            ),
            "release": (
                "Access cannot repair a wrong carrier. Automatic access "
                "requires both anchor and complete carrier release readiness."
            ),
        },
        "carrier_feature_names": list(ACCESS_CARRIER_FEATURE_NAMES),
        "carrier_feature_dim": len(ACCESS_CARRIER_FEATURE_NAMES),
        "counts": dict(sorted(counts.items())),
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": feature_hash_before_label_read,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "inputs": {
            "anchor_conditioned_access": _input_record(
                access_root / "summary.json"
            ),
            "road_member_store": _input_record(member_root / "summary.json"),
            "ordinary_carrier_oof": _input_record(
                carrier_root / "summary.json"
            ),
            "use_road_oof": _input_record(use_root / "summary.json"),
        },
        "outputs": {
            "features": _input_record(feature_path),
            "labels": _input_record(label_path),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(labels) == counts["access_object"]
            and counts["proposal"] > 0
            and sha256_file(feature_path) == feature_hash_before_label_read
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("access complete carrier conditioning gate failed")
    return root


def carrier_condition_features(
    *,
    road_id: str,
    road_source: str,
    decision: str,
    selected_road_ids: set[str],
    condition_available: bool,
    decision_confidence: float,
    road_set_confidence: float,
    release_ready: bool,
) -> list[float]:
    expected_source = (
        "SWSD"
        if decision == "KEEP_SWSD"
        else "RCSD"
        if decision == "USE_RCSD"
        else ""
    )
    values = [
        float(condition_available),
        float(decision == "KEEP_SWSD"),
        float(decision == "USE_RCSD"),
        float(road_id in selected_road_ids),
        float(bool(expected_source) and road_source == expected_source),
        math.tanh(math.log1p(len(selected_road_ids)) / 5.0),
        _probability(decision_confidence),
        _probability(road_set_confidence),
        float(release_ready),
        float(road_source == "SWSD"),
        float(road_source == "RCSD"),
    ]
    if len(values) != len(ACCESS_CARRIER_FEATURE_NAMES):
        raise AssertionError("access carrier feature dimension drifted")
    return values


def _probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


__all__ = [
    "ACCESS_CARRIER_FEATURE_NAMES",
    "build_carrier_conditioned_access_store",
    "carrier_condition_features",
]
