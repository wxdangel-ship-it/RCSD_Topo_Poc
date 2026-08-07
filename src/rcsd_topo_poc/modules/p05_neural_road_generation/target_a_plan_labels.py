from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TargetACaseBundle,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def build_plan_candidate_preflight(
    bundles: Sequence[TargetACaseBundle],
    *,
    candidate_store_root: Path,
    label_store_root: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    """Join labels after truth-free generation and audit complete-plan reachability."""
    started = time.perf_counter()
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(strict=True)
    label_root = normalize_runtime_path(label_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    candidate_manifest = _read_json(candidate_root / "manifest.json")
    label_manifest = _read_json(label_root / "manifest.json")
    _validate_input_manifests(candidate_manifest, label_manifest)
    groups = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    }
    inventory = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(label_root / "segment_inventory.jsonl")
    }
    label_rows = _read_jsonl(label_root / "segment_labels.jsonl")
    bundle_by_case = {bundle.case_key: bundle for bundle in bundles}
    t05_split_source_maps: dict[str, dict[str, str]] = {}
    t05_split_mapping_counts: Counter[str] = Counter()
    for case_key, bundle in bundle_by_case.items():
        source_map, mapping_counts = _t05_split_road_source_map(
            bundle.t05_relation.parent / "rcsd_junctionization_audit.json"
        )
        t05_split_source_maps[case_key] = source_map
        t05_split_mapping_counts.update(mapping_counts)
    final_road_maps = {
        case_key: _final_road_source_map(
            bundle.t06_frcsd_road,
            t05_split_source_map=t05_split_source_maps[case_key],
        )
        for case_key, bundle in bundle_by_case.items()
    }
    training_rows: list[dict[str, Any]] = []
    scope_counts: Counter[str] = Counter()
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for label in label_rows:
        key = (str(label["case_key"]), str(label["object_id"]))
        segment = inventory.get(key)
        group = groups.get(key)
        if segment is None or group is None:
            raise ValueError(f"Target A plan label/group scope differs: {key}")
        label_task = bool(label.get("task_mask")) and float(
            label.get("label_weight") or 0.0
        ) > 0
        acceptable_targets = _acceptable_targets(
            label,
            final_road_maps[key[0]],
        )
        acceptable_plan_ids = []
        preferred_plan_id = ""
        preferred_target = str(
            label.get("preferred_carrier_target")
            or label.get("carrier_target")
            or ""
        )
        normalized_targets = {
            (
                str(target["decision"]),
                tuple(sorted(str(value) for value in target["road_ids"])),
            )
            for target in acceptable_targets
        }
        for plan in group["candidates"]:
            plan_key = (
                str(plan["decision"]),
                tuple(sorted(str(value) for value in plan["road_ids"])),
            )
            if plan_key not in normalized_targets:
                continue
            acceptable_plan_ids.append(str(plan["plan_id"]))
            if plan_key[0] == preferred_target and not preferred_plan_id:
                preferred_plan_id = str(plan["plan_id"])
        reachable = bool(acceptable_plan_ids)
        training_task = label_task and reachable
        if label_task:
            scope_counts["supervised"] += 1
            scope_counts[f"supervised:{preferred_target}"] += 1
            scope_counts[f"supervised:{segment['segment_type']}"] += 1
            family_counts[str(segment["family"])]["supervised"] += 1
            if reachable:
                scope_counts["reachable"] += 1
                scope_counts[f"reachable:{preferred_target}"] += 1
                scope_counts[f"reachable:{segment['segment_type']}"] += 1
                family_counts[str(segment["family"])]["reachable"] += 1
            else:
                scope_counts["unreachable"] += 1
        training_rows.append(
            {
                "case_key": key[0],
                "segment_id": key[1],
                "fold": int(label["fold"]),
                "family": segment["family"],
                "segment_type": segment["segment_type"],
                "label_weight": float(label.get("label_weight") or 0.0),
                "label_task_mask": label_task,
                "training_task_mask": training_task,
                "mask_reason": (
                    ""
                    if training_task
                    else (
                        "complete_plan_candidate_unreachable"
                        if label_task
                        else str(label.get("mask_reason") or "label_not_supervised")
                    )
                ),
                "acceptable_plan_ids": sorted(acceptable_plan_ids),
                "preferred_plan_id": preferred_plan_id,
                "acceptable_complete_road_targets": acceptable_targets,
                "preferred_carrier_target": preferred_target,
                "label_origin": label.get("label_origin") or "strategy_replay",
                "reality_change_clue": label.get("reality_change_clue"),
                "clue_task_mask": "reality_change_clue" in label,
                "fallback_scope": label.get("fallback_scope"),
                "fallback_scope_task_mask": "fallback_scope" in label,
                "keep_reason": label.get("keep_reason"),
                "keep_reason_task_mask": "keep_reason" in label,
                "feature_uses_truth": False,
                "label_only": True,
            }
        )
    training_rows.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    label_path = root / "training_plan_labels.jsonl"
    _write_jsonl(label_path, training_rows)
    supervised = scope_counts["supervised"]
    reachable = scope_counts["reachable"]
    coverage = reachable / supervised if supervised else 0.0
    carrier_coverage = {
        target: _ratio(
            scope_counts[f"reachable:{target}"],
            scope_counts[f"supervised:{target}"],
        )
        for target in (
            "KEEP_SWSD",
            "USE_RCSD",
            "T06_MAIN_RCSD_ATTACHED_SWSD",
        )
        if scope_counts[f"supervised:{target}"]
    }
    segment_type_coverage = {
        segment_type: _ratio(
            scope_counts[f"reachable:{segment_type}"],
            scope_counts[f"supervised:{segment_type}"],
        )
        for segment_type in ("STANDARD", "ADVANCE_RIGHT")
        if scope_counts[f"supervised:{segment_type}"]
    }
    family_coverage = {
        family: _ratio(counts["reachable"], counts["supervised"])
        for family, counts in sorted(family_counts.items())
    }
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "COMPLETE_PLAN_CANDIDATE_PREFLIGHT",
        "counts": dict(sorted(scope_counts.items())),
        "complete_plan_exact_coverage": coverage,
        "carrier_coverage": carrier_coverage,
        "segment_type_coverage": segment_type_coverage,
        "family_coverage": family_coverage,
        "label_store_manifest": {
            "path": str((label_root / "manifest.json").resolve()),
            "sha256": sha256_file(label_root / "manifest.json"),
        },
        "candidate_store_manifest": {
            "path": str((candidate_root / "manifest.json").resolve()),
            "sha256": sha256_file(candidate_root / "manifest.json"),
        },
        "training_labels": {
            "path": str(label_path.resolve()),
            "sha256": sha256_file(label_path),
        },
        "candidate_feature_uses_truth": False,
        "candidate_truth_derived_count": 0,
        "terminal_feature_count": 0,
        "label_store_physically_separate": candidate_root != label_root,
        "candidate_scope_exact": len(groups)
        == int(candidate_manifest["group_count"])
        == int(label_manifest["counts"]["segment_count"]),
        "t05_split_source_mapping": {
            **dict(sorted(t05_split_mapping_counts.items())),
            "mapped_new_road_id_count": sum(
                len(source_map)
                for source_map in t05_split_source_maps.values()
            ),
            "label_only": True,
            "inference_feature_count": 0,
        },
        "training_ready_for_full_scope": (
            supervised > 0
            and reachable == supervised
            and carrier_coverage.get("KEEP_SWSD") == 1.0
            and carrier_coverage.get("USE_RCSD") == 1.0
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def _acceptable_targets(
    label: Mapping[str, Any],
    final_road_map: Mapping[str, tuple[str, int]],
) -> list[dict[str, Any]]:
    explicit = label.get("acceptable_complete_road_targets")
    if isinstance(explicit, list) and explicit:
        raw_targets = [
            {
                "decision": str(row["carrier_target"]),
                "road_ids": list(row["road_ids"]),
            }
            for row in explicit
        ]
    else:
        raw_targets = [
            {
                "decision": str(label.get("carrier_target") or ""),
                "road_ids": list(label.get("target_payload") or []),
            }
        ]
    normalized = []
    for target in raw_targets:
        decision = target["decision"]
        if decision == "KEEP_SWSD":
            normalized_ids = tuple(
                sorted(
                    {
                        final_road_map.get(str(value), (str(value), 2))[0]
                        for value in target["road_ids"]
                    }
                )
            )
        elif decision == "USE_RCSD":
            normalized_ids = tuple(
                sorted(
                    {
                        final_road_map.get(str(value), (str(value), 1))[0]
                        for value in target["road_ids"]
                        if final_road_map.get(str(value), (str(value), 1))[1] == 1
                    }
                )
            )
        elif decision == "T06_MAIN_RCSD_ATTACHED_SWSD":
            normalized_ids = tuple(
                sorted(
                    {
                        final_road_map.get(str(value), (str(value), 0))[0]
                        for value in target["road_ids"]
                    }
                )
            )
        else:
            normalized_ids = ()
        normalized.append(
            {
                "decision": decision,
                "road_ids": list(normalized_ids),
            }
        )
    return normalized


def _final_road_source_map(
    path: Path,
    *,
    t05_split_source_map: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, int]]:
    split_source_map = t05_split_source_map or {}
    result: dict[str, tuple[str, int]] = {}
    with fiona.open(path) as source:
        for feature in source:
            properties = dict(feature["properties"])
            road_id = str(properties.get("id") or "")
            if not road_id:
                continue
            original = str(
                properties.get("t06_split_original_road_id")
                or properties.get("source_road_id")
                or road_id
            )
            original = split_source_map.get(original, original)
            try:
                source_kind = int(properties.get("source") or 0)
            except (TypeError, ValueError):
                source_kind = 0
            result[road_id] = (original, source_kind)
    return result


def _t05_split_road_source_map(
    path: Path,
) -> tuple[dict[str, str], dict[str, int]]:
    payload = _read_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("T05 junctionization audit rows are missing")
    result: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("T05 junctionization audit row is not an object")
        original_ids = _pipe_ids(row.get("original_rcsdroad_ids"))
        new_ids = _pipe_ids(row.get("new_rcsdroad_ids"))
        if not new_ids:
            continue
        counts["row_with_new_road_ids"] += 1
        if len(original_ids) != 1:
            counts["ambiguous_source_row_count"] += 1
            counts["ambiguous_new_road_id_count"] += len(new_ids)
            continue
        original_id = original_ids[0]
        counts["single_source_row_count"] += 1
        for new_id in new_ids:
            previous = result.get(new_id)
            if previous is not None and previous != original_id:
                raise ValueError(
                    "T05 generated Road maps to conflicting source Roads: "
                    f"{new_id}"
                )
            result[new_id] = original_id
    return result, dict(counts)


def _pipe_ids(value: Any) -> tuple[str, ...]:
    return tuple(
        item
        for item in (part.strip() for part in str(value or "").split("|"))
        if item
    )


def _validate_input_manifests(
    candidate: Mapping[str, Any],
    label: Mapping[str, Any],
) -> None:
    if candidate.get("schema_version") != TARGET_A_SCHEMA_VERSION:
        raise ValueError("Target A candidate schema differs")
    if label.get("schema_version") != TARGET_A_SCHEMA_VERSION:
        raise ValueError("Target A label schema differs")
    if not candidate.get("gate_pass") or not label.get("gate_pass"):
        raise ValueError("Target A candidate/label input gate is not passed")
    for key in (
        "truth_input_count",
        "truth_derived_candidate_count",
        "terminal_feature_count",
        "absolute_coordinate_feature_count",
        "raw_id_embedding_count",
    ):
        if int(candidate.get(key) or 0):
            raise ValueError(f"Target A candidate leakage is non-zero: {key}")
    if not label.get("label_only") or int(label.get("inference_feature_count") or 0):
        raise ValueError("Target A label store is not physically label-only")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row is not an object: {path}:{line_number}")
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = ["build_plan_candidate_preflight"]
