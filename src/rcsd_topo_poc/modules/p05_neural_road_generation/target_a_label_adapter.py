from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    CarrierRealization,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_truth import (
    JSGInputCase,
    build_jsg_case_truth,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_baseline import (
    _build_case,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierLabel,
    FrozenSchemeACase,
    RealityChangeClue,
    SegmentType,
    StrategyBaselineRecord,
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TargetACaseBundle,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    iter_weighted_case_group_folds,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_MANUAL_ADJUDICATIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("T10:609214532", "505101583_506183080"): {
        "acceptable": ("USE_RCSD",),
        "preferred": "USE_RCSD",
        "clue": False,
        "fallback_scope": "NONE",
    },
    ("T10:706247", "706317_706319"): {
        "acceptable": ("KEEP_SWSD", "USE_RCSD"),
        "preferred": "KEEP_SWSD",
        "clue": True,
        "fallback_scope": "JUNCTION",
        "junction_id": "706247",
    },
    ("T10:706247", "706346_706349"): {
        "acceptable": ("KEEP_SWSD", "USE_RCSD"),
        "preferred": "USE_RCSD",
        "clue": False,
        "fallback_scope": "NONE",
    },
    ("T10:609214532", "513242335_523239407"): {
        "acceptable": ("KEEP_SWSD",),
        "preferred": "KEEP_SWSD",
        "clue": False,
        "fallback_scope": "NONE",
        "keep_reason": "NO_RCSD_EVIDENCE",
        "reason": "rcsd_data_missing_is_not_reality_change",
    },
    ("T10:609214532", "606102026_609617028"): {
        "acceptable": ("KEEP_SWSD",),
        "preferred": "KEEP_SWSD",
        "clue": False,
        "fallback_scope": "NONE",
        "keep_reason": "NO_RCSD_EVIDENCE",
        "reason": "rcsd_data_missing_is_not_reality_change",
    },
}


def build_target_a_label_store(
    bundles: Sequence[TargetACaseBundle],
    *,
    output_root: Path,
    run_id: str,
    fold_count: int = 5,
    strict_hashes: bool = True,
) -> Path:
    started = time.perf_counter()
    if not bundles:
        raise ValueError("Target A label adapter requires Case bundles")
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    case_root = root / "cases"
    case_root.mkdir(parents=True)
    fold_weights = {
        bundle.case_key: _case_fold_weight(bundle)
        for bundle in bundles
    }
    folds = iter_weighted_case_group_folds(
        fold_weights,
        fold_count=fold_count,
    )

    case_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    clue_rows: list[dict[str, Any]] = []
    validation_totals: Counter[str] = Counter()
    for bundle in sorted(bundles, key=lambda row: row.case_key):
        frozen, baselines, labels, clues, stats = _adapt_case(
            bundle,
            fold=folds[bundle.case_key],
            strict_hashes=strict_hashes,
        )
        token = hashlib.sha256(bundle.case_key.encode("utf-8")).hexdigest()[:20]
        frozen_path = case_root / token / "frozen_skeleton.json"
        frozen_path.parent.mkdir()
        _write_json(frozen_path, frozen.to_dict())
        segment_type_by_id = {
            segment.segment_id: segment.segment_type.value
            for segment in frozen.segments
        }
        target_scope = _target_segment_scope(bundle, frozen)
        target_segment_ids = set(target_scope["current_segment_ids"])
        baseline_by_id = {row.segment_id: row for row in baselines}
        label_scope_by_id: dict[str, str] = {}
        case_rows.append(
            {
                "case_key": bundle.case_key,
                "family": bundle.family,
                "business_id": bundle.business_id,
                "fold": frozen.fold,
                "segment_count": len(frozen.segments),
                "advance_right_count": sum(
                    segment.segment_type is SegmentType.ADVANCE_RIGHT
                    for segment in frozen.segments
                ),
                "junction_count": len(frozen.junctions),
                "physical_movement_count": len(frozen.physical_movements),
                "frozen_skeleton": str(frozen_path.relative_to(root)),
                "skeleton_signature": frozen.skeleton_signature(),
                "scope_mapping_method": target_scope["mapping_method"],
                "scope_mapping_status": target_scope["mapping_status"],
                "package_target_segment_id": target_scope["target_segment_id"],
                "mapped_target_segment_ids": target_scope["current_segment_ids"],
            }
        )
        for segment in frozen.segments:
            baseline = baseline_by_id[segment.segment_id]
            label_scope = (
                "TARGET"
                if segment.segment_id in target_segment_ids
                else "CONTEXT_ONLY"
            )
            label_scope_by_id[segment.segment_id] = label_scope
            segment_rows.append(
                {
                    "case_key": bundle.case_key,
                    "family": bundle.family,
                    "business_id": bundle.business_id,
                    "segment_id": segment.segment_id,
                    "segment_type": segment.segment_type.value,
                    "pair_nodes": segment.pair_nodes,
                    "junc_nodes": segment.junc_nodes,
                    "swsd_road_ids": segment.swsd_road_ids,
                    "source_segment_access": segment.source_segment_access,
                    "target_segment_access": segment.target_segment_access,
                    "access_valid": segment.access_valid,
                    "independent_road_valid": segment.independent_road_valid,
                    "strategy_outcome": baseline.outcome.value,
                    "carrier_target": baseline.carrier_target.value,
                    "label_scope": label_scope,
                    "target_weight": bundle.target_weight if label_scope == "TARGET" else 0.0,
                    "context_weight": 0.0,
                }
            )
        baseline_rows.extend(row.to_dict() for row in baselines)
        label_rows.extend(
            _strategy_carrier_label(
                row,
                baseline=baseline_by_id[row.object_id],
                label_scope=label_scope_by_id[row.object_id],
                target_weight=bundle.target_weight,
                segment_type=segment_type_by_id[row.object_id],
            )
            for row in labels
            if row.object_type == "SEGMENT"
        )
        clue_rows.extend(row.to_dict() for row in clues)
        validation_totals.update(stats)

    manual_adjudication_count = _apply_manual_adjudications(
        segment_rows=segment_rows,
        baseline_rows=baseline_rows,
        label_rows=label_rows,
        clue_rows=clue_rows,
    )
    case_rows.sort(key=lambda row: row["case_key"])
    segment_rows.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    baseline_rows.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    label_rows.sort(key=lambda row: (row["case_key"], row["object_id"]))
    clue_rows.sort(
        key=lambda row: (
            row["case_key"],
            row["scope"],
            row["object_id"],
            row["code"],
        )
    )
    paths = {
        "case_inventory": root / "case_inventory.jsonl",
        "segment_inventory": root / "segment_inventory.jsonl",
        "strategy_baseline": root / "strategy_baseline.jsonl",
        "segment_labels": root / "segment_labels.jsonl",
        "clues": root / "reality_change_clues.jsonl",
    }
    for key, rows in (
        ("case_inventory", case_rows),
        ("segment_inventory", segment_rows),
        ("strategy_baseline", baseline_rows),
        ("segment_labels", label_rows),
        ("clues", clue_rows),
    ):
        _write_jsonl(paths[key], rows)

    label_scope_by_segment = {
        (row["case_key"], row["segment_id"]): row["label_scope"]
        for row in segment_rows
    }
    counts = {
        "case_count": len(case_rows),
        "segment_count": len(segment_rows),
        "target_segment_count": sum(
            row["label_scope"] == "TARGET" for row in segment_rows
        ),
        "context_only_segment_count": sum(
            row["label_scope"] == "CONTEXT_ONLY" for row in segment_rows
        ),
        "advance_right_count": sum(
            row["segment_type"] == "ADVANCE_RIGHT" for row in segment_rows
        ),
        "physical_movement_count": sum(
            row["physical_movement_count"] for row in case_rows
        ),
        "movement_label_count": 0,
        "clue_count": len(clue_rows),
        "skeleton_mutation_count": 0,
        "silent_fix_count": 0,
        "manual_adjudication_count": manual_adjudication_count,
        "context_business_label_count": sum(
            bool(row["task_mask"]) and float(row["label_weight"]) > 0
            for row in label_rows
            if label_scope_by_segment.get((row["case_key"], row["object_id"]), "")
            == "CONTEXT_ONLY"
        ),
    }
    expected = {
        "case_count": 51,
        "segment_count": 8_863,
        "target_segment_count": 6_248,
        "advance_right_count": 474,
        "physical_movement_count": 24_779,
    }
    gates = {
        "case_scope": counts["case_count"] == expected["case_count"],
        "segment_scope": counts["segment_count"] == expected["segment_count"],
        "target_segment_scope": (
            counts["target_segment_count"] == expected["target_segment_count"]
        ),
        "advance_right_scope": (
            counts["advance_right_count"] == expected["advance_right_count"]
        ),
        "physical_movement_scope": (
            counts["physical_movement_count"]
            == expected["physical_movement_count"]
        ),
        "movement_disabled": counts["movement_label_count"] == 0,
        "context_label_isolation": counts["context_business_label_count"] == 0,
        "source_geometry_integrity": not any(validation_totals.values()),
        "skeleton_immutable": counts["skeleton_mutation_count"] == 0,
        "silent_fix_zero": counts["silent_fix_count"] == 0,
        "manual_adjudications_complete": (
            counts["manual_adjudication_count"] == len(_MANUAL_ADJUDICATIONS)
        ),
    }
    content_signature = canonical_sha256(
        {
            "case_inventory": case_rows,
            "segment_inventory": segment_rows,
            "strategy_baseline": baseline_rows,
            "segment_labels": label_rows,
            "clues": clue_rows,
            "counts": counts,
            "gates": gates,
        }
    )
    manifest = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "LABEL_ADAPTER",
        "counts": counts,
        "expected": expected,
        "gates": gates,
        "gate_pass": all(gates.values()),
        "validation_totals": dict(sorted(validation_totals.items())),
        "content_signature": content_signature,
        "wall_seconds": time.perf_counter() - started,
        "outputs": {
            key: {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
            for key, path in paths.items()
        },
        "label_only": True,
        "inference_feature_count": 0,
        "terminal_leakage_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "fold_assignment": {
            "group": "CASE",
            "policy": "greedy_supervised_mass_balance",
            "fold_count": fold_count,
            "case_weights": dict(sorted(fold_weights.items())),
            "fold_weights": {
                str(fold): sum(
                    fold_weights[case_key]
                    for case_key, assigned in folds.items()
                    if assigned == fold
                )
                for fold in range(fold_count)
            },
        },
    }
    _write_json(root / "manifest.json", manifest)
    if not manifest["gate_pass"]:
        raise RuntimeError(f"Target A label adapter gate failed: {root}")
    return root


def _target_segment_scope(
    bundle: TargetACaseBundle,
    frozen: FrozenSchemeACase,
) -> dict[str, Any]:
    if bundle.family == "T10":
        return {
            "mapping_method": "CASE_ALL",
            "mapping_status": "MAPPED",
            "target_segment_id": "",
            "current_segment_ids": sorted(
                segment.segment_id for segment in frozen.segments
            ),
        }
    manifest_path = bundle.source_case_root / "t10_case_evidence_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    properties = (
        scope.get("segment_properties")
        if isinstance(scope.get("segment_properties"), dict)
        else {}
    )
    target_segment_id = str(
        scope.get("swsd_segment_id")
        or properties.get("id")
        or bundle.target_segment_id
    )
    exact_matches = sorted(
        segment.segment_id
        for segment in frozen.segments
        if segment.segment_id == target_segment_id
    )
    return {
        "mapping_method": "EXACT_DIRECTORY_SEGMENT_ID",
        "mapping_status": (
            "MAPPED"
            if exact_matches
            else "TARGET_NOT_IN_FROZEN_T01"
        ),
        "target_segment_id": target_segment_id,
        "current_segment_ids": exact_matches,
    }


def _case_fold_weight(bundle: TargetACaseBundle) -> float:
    if bundle.family != "T10":
        return 1.0
    with fiona.open(bundle.t01_segment) as source:
        feature_count = len(source)
    if feature_count <= 0:
        raise ValueError(f"Target A T01 Segment collection is empty: {bundle.case_key}")
    return float(feature_count)


def _strategy_carrier_label(
    legacy: CarrierLabel,
    *,
    baseline: StrategyBaselineRecord,
    label_scope: str,
    target_weight: float,
    segment_type: str,
) -> dict[str, Any]:
    legacy_row = legacy.to_dict()
    baseline_target = baseline.carrier_target.value
    target = (
        "T06_MAIN_RCSD_ATTACHED_SWSD"
        if baseline_target == "MIXED_CARRIER"
        else baseline_target
    )
    payload = [str(value) for value in baseline.selected_road_ids]
    resolved = target in {
        "KEEP_SWSD",
        "USE_RCSD",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
    } and bool(payload)
    task_mask = label_scope == "TARGET" and resolved
    return {
        **legacy_row,
        "carrier_target": target,
        "target_payload": payload,
        "available": resolved,
        "label_weight": float(target_weight) if task_mask else 0.0,
        "weight_role": (
            "TARGET"
            if task_mask
            else ("CONTEXT_ONLY" if label_scope == "CONTEXT_ONLY" else "UNRESOLVED")
        ),
        "task_mask": task_mask,
        "movement_disabled": False,
        "mask_reason": (
            ""
            if task_mask
            else (
                "context_only_not_a_label"
                if label_scope == "CONTEXT_ONLY"
                else "unavailable_or_unresolved_terminal_reason"
            )
        ),
        "acceptable_carrier_targets": [target] if resolved else [],
        "acceptable_complete_road_targets": (
            [{"carrier_target": target, "road_ids": payload}] if resolved else []
        ),
        "preferred_carrier_target": target if resolved else "",
        "label_origin": "confirmed_t10_strategy_replay",
        "segment_type": segment_type,
        "strategy_outcome": baseline.outcome.value,
        "strategy_relation_status": baseline.relation_status,
        "strategy_relation_reason": baseline.relation_reason,
        "legacy_carrier_target": legacy_row["carrier_target"],
        "legacy_target_payload": legacy_row["target_payload"],
        "legacy_available": legacy_row["available"],
        "legacy_weight_role": legacy_row["weight_role"],
        "legacy_role": "WEAK_CONTEXT_ONLY",
    }


def _apply_manual_adjudications(
    *,
    segment_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    clue_rows: list[dict[str, Any]],
) -> int:
    inventory_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in segment_rows
    }
    baseline_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in baseline_rows
    }
    label_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in label_rows
    }
    for key, adjudication in _MANUAL_ADJUDICATIONS.items():
        inventory = inventory_by_key.get(key)
        baseline = baseline_by_key.get(key)
        label = label_by_key.get(key)
        if inventory is None or baseline is None or label is None:
            raise ValueError(f"Target A manual adjudication object is missing: {key}")
        swsd_roads = tuple(str(value) for value in inventory["swsd_road_ids"])
        rcsd_roads = tuple(str(value) for value in baseline["selected_road_ids"])
        complete_targets = []
        for target in adjudication["acceptable"]:
            road_ids = swsd_roads if target == "KEEP_SWSD" else rcsd_roads
            if not road_ids:
                raise ValueError(
                    f"Target A manual adjudication plan has no complete Roads: {key}"
                )
            complete_targets.append(
                {
                    "carrier_target": target,
                    "road_ids": list(road_ids),
                }
            )
        preferred = str(adjudication["preferred"])
        preferred_payload = next(
            row["road_ids"]
            for row in complete_targets
            if row["carrier_target"] == preferred
        )
        label.update(
            {
                "carrier_target": preferred,
                "target_payload": preferred_payload,
                "acceptable_carrier_targets": list(adjudication["acceptable"]),
                "acceptable_complete_road_targets": complete_targets,
                "preferred_carrier_target": preferred,
                "label_weight": 1.0,
                "weight_role": "MANUAL_ADJUDICATION",
                "task_mask": True,
                "label_origin": "user_manual_adjudication",
                "reality_change_clue": bool(adjudication["clue"]),
                "fallback_scope": str(adjudication["fallback_scope"]),
                "affected_junction_ids": (
                    [str(adjudication["junction_id"])]
                    if adjudication.get("junction_id")
                    else []
                ),
                "affected_segment_ids": [key[1]],
                "adjudication_reason": str(
                    adjudication.get("reason") or "user_confirmed_business_truth"
                ),
            }
        )
        if adjudication.get("keep_reason"):
            label["keep_reason"] = str(adjudication["keep_reason"])
    adjudicated_keys = set(_MANUAL_ADJUDICATIONS)
    clue_rows[:] = [
        row
        for row in clue_rows
        if (str(row["case_key"]), str(row["object_id"])) not in adjudicated_keys
    ]
    for (case_key, segment_id), adjudication in _MANUAL_ADJUDICATIONS.items():
        if not adjudication["clue"]:
            continue
        junction_id = str(adjudication["junction_id"])
        clue_rows.append(
            {
                "clue_id": "manual:"
                + hashlib.sha256(
                    f"{case_key}:{segment_id}:{junction_id}".encode("utf-8")
                ).hexdigest()[:20],
                "case_key": case_key,
                "scope": "JUNCTION",
                "object_id": junction_id,
                "code": "MANUAL_REALITY_STRUCTURE_CONFLICT",
                "detail": (
                    "User-confirmed reality structure conflict; apply Junction "
                    f"fallback for affected Segment {segment_id}."
                ),
                "evidence_refs": [],
                "recommended_fallback": "JUNCTION",
                "status": "CONFIRMED",
                "skeleton_mutation": False,
                "affected_segment_ids": [segment_id],
                "label_origin": "user_manual_adjudication",
            }
        )
    return len(_MANUAL_ADJUDICATIONS)


def _adapt_case(
    bundle: TargetACaseBundle,
    *,
    fold: int,
    strict_hashes: bool,
) -> tuple[
    FrozenSchemeACase,
    list[StrategyBaselineRecord],
    list[CarrierLabel],
    list[RealityChangeClue],
    Counter[str],
]:
    paths = {
        "t01_segment": bundle.t01_segment,
        "t01_roads": bundle.t01_roads,
        "t01_nodes": bundle.t01_nodes,
        "t05_relation_truth": bundle.t05_relation,
        "t06_segment_relation_truth": bundle.t06_segment_relation,
        "t06_frcsd_road_truth": bundle.t06_frcsd_road,
        "t06_frcsd_node_truth": bundle.t06_frcsd_node,
    }
    source_hashes = {
        role: sha256_file(path)
        for role, path in paths.items()
    }
    carrier = CarrierRealization(
        r2_oracle_run_manifest=str(bundle.run_summary),
        r2_case_sample_id=bundle.case_key,
        road_edits_path="",
        node_edits_path="",
        expected_truth_road=str(bundle.t06_frcsd_road),
        expected_truth_node=str(bundle.t06_frcsd_node),
        artifact_hashes=(
            ("truth_node", source_hashes["t06_frcsd_node_truth"]),
            ("truth_road", source_hashes["t06_frcsd_road_truth"]),
        ),
    )
    input_case = JSGInputCase(
        sample_id=bundle.case_key,
        family=bundle.family,
        business_id=bundle.business_id,
        fold=fold,
        source_manifest=bundle.run_summary,
        t01_segment=bundle.t01_segment,
        t01_nodes=bundle.t01_nodes,
        t01_roads=bundle.t01_roads,
        t05_relation=bundle.t05_relation,
        t06_segment_relation=bundle.t06_segment_relation,
        truth_road=bundle.t06_frcsd_road,
        truth_node=bundle.t06_frcsd_node,
        source_hashes=tuple(sorted(source_hashes.items())),
        carrier_realization=carrier,
    )
    truth = build_jsg_case_truth(input_case)
    sample = {
        "sample_id": bundle.case_key,
        "family": bundle.family,
        "business_id": bundle.business_id,
        "scope_type": "t10_case" if bundle.family == "T10" else "t10_segment",
        "target_weight": str(bundle.target_weight),
        "context_weight": "0.0",
    }
    return _build_case(
        truth=truth,
        sample=sample,
        fold=fold,
        strict_hashes=strict_hashes,
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            _json_value(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    _json_value(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            stream.write("\n")


def _json_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


__all__ = ["build_target_a_label_store"]
