from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
    model_contract,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    ORDINARY_PLAN_ARM_COUNT,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_data import (
    _read_anchor_oof_predictions,
    _read_candidate_plan_node_ids,
    _read_selected_anchor_conditions,
    condition_ordinary_plan_example,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_oof import (
    _predict_conditioned_plans,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_INFERENCE_OUTPUT_FIELDS = (
    "sample_id",
    "case_key",
    "segment_id",
    "fold",
    "required_anchor_count",
    "anchor_resolved_count",
    "anchor_success_count",
    "all_required_anchors_resolved",
    "all_required_anchors_success",
    "missing_anchor_ids",
    "anchor_gate_fallback_required",
    "raw_predicted_plan_id",
    "raw_predicted_decision",
    "raw_predicted_probability",
    "predicted_clue",
    "predicted_clue_probability",
    "predicted_fallback_scope",
    "predicted_fallback_scope_probability",
    "fallback_none_probability",
    "fallback_segment_probability",
    "fallback_junction_probability",
    "release_fallback_scope",
    "release_fallback_required",
    "effective_decision",
    "automatic_decision",
    "enabled_plan_ids",
)


def run_full_ordinary_strict_oof_inference(
    *,
    candidate_store_root: Path,
    case_inventory_path: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    trained_ordinary_oof_root: Path,
    output_root: Path,
    batch_size: int = 128,
    requested_device: str = "cuda",
) -> Path:
    """Replay each held-out fold model over every ordinary Segment group."""
    started = time.perf_counter()
    if batch_size < 1:
        raise ValueError("full ordinary inference batch size must be positive")
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    inventory_path = normalize_runtime_path(case_inventory_path).resolve(
        strict=True
    )
    anchor_store = normalize_runtime_path(anchor_store_root).resolve(
        strict=True
    )
    anchor_oof = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    trained_root = normalize_runtime_path(trained_ordinary_oof_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    fold_by_case = {
        str(row["case_key"]): int(row["fold"])
        for row in _read_jsonl(inventory_path)
    }
    groups = [
        row
        for row in _read_jsonl(
            candidate_root / "inference_plan_groups.jsonl"
        )
        if str(row.get("segment_type")) == "STANDARD"
    ]
    missing_cases = sorted(
        {str(row["case_key"]) for row in groups} - set(fold_by_case)
    )
    if missing_cases:
        raise ValueError(
            f"ordinary inference groups lack fold assignment: {missing_cases}"
        )
    plans = [
        ordinary_inference_example_from_group(
            row,
            fold=fold_by_case[str(row["case_key"])],
        )
        for row in groups
    ]
    required_keys = {
        (plan.case_key, anchor_id)
        for plan in plans
        for anchor_id in plan.required_anchor_ids
    }
    anchor_predictions = _read_anchor_oof_predictions(
        anchor_oof / "oof_predictions.jsonl",
        required_keys,
    )
    anchor_conditions = _read_selected_anchor_conditions(
        anchor_store / "inference_feature_store" / "anchor_features.jsonl",
        anchor_predictions,
        required_keys,
    )
    candidate_node_ids = _read_candidate_plan_node_ids(
        candidate_root,
        plans,
    )
    conditioned = [
        condition_ordinary_plan_example(
            plan,
            {
                anchor_id: anchor_conditions[(plan.case_key, anchor_id)]
                for anchor_id in plan.required_anchor_ids
                if (plan.case_key, anchor_id) in anchor_conditions
            },
            include_anchor_plan_relations=True,
            include_plan_member_relations=True,
            include_plan_arm_relations=True,
            candidate_node_ids=candidate_node_ids[plan.sample_id],
        )
        for plan in plans
    ]
    by_fold: dict[int, list[Any]] = {}
    for example in conditioned:
        by_fold.setdefault(example.fold, []).append(example)

    device = _resolve_device(requested_device)
    run_summary = _read_json(trained_root / "summary.json")
    expected_contract = run_summary["model_contract"]
    predictions: list[dict[str, Any]] = []
    fold_rows = []
    for fold in sorted(by_fold):
        checkpoint_path = trained_root / f"fold_{fold}_checkpoint.pt"
        model, payload = _load_model(checkpoint_path, device=device)
        if payload["model_contract"] != expected_contract:
            raise ValueError("ordinary checkpoint model contract differs")
        raw_rows = _predict_conditioned_plans(
            model,
            by_fold[fold],
            batch_size=batch_size,
            device=device,
        )
        inference_rows = [
            {
                **{
                    field: row[field]
                    for field in _INFERENCE_OUTPUT_FIELDS
                },
                "outer_fold": fold,
                "label_evaluable": False,
                "training_truth_used": False,
            }
            for row in raw_rows
        ]
        predictions.extend(inference_rows)
        fold_rows.append(
            {
                "fold": fold,
                "case_keys": sorted(
                    {row["case_key"] for row in inference_rows}
                ),
                "segment_count": len(inference_rows),
                "checkpoint": str(checkpoint_path.resolve()),
                "checkpoint_sha256": sha256_file(checkpoint_path),
                "anchor_fallback_count": sum(
                    bool(row["anchor_gate_fallback_required"])
                    for row in inference_rows
                ),
                "release_fallback_count": sum(
                    bool(row["release_fallback_required"])
                    for row in inference_rows
                ),
            }
        )
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "full_oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    keys = {
        (str(row["case_key"]), str(row["segment_id"])) for row in predictions
    }
    group_keys = {
        (str(row["case_key"]), str(row["segment_id"])) for row in groups
    }
    counts = Counter(
        str(row["effective_decision"]) for row in predictions
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "FULL_ORDINARY_STRICT_OOF_INFERENCE",
        "scope": (
            "Every STANDARD Segment candidate group is scored by the model "
            "whose outer fold held out that entire Case."
        ),
        "label_contract": (
            "No synthetic supervision is evaluated or exported. Dummy "
            "ABSTAIN labels exist only to reuse tensor collation."
        ),
        "anchor_contract": (
            "Missing or unresolved required anchors force Segment fallback; "
            "zero required anchors pass the hard gate."
        ),
        "example_count": len(predictions),
        "case_count": len({row["case_key"] for row in predictions}),
        "fold_count": len(by_fold),
        "effective_decision_counts": dict(sorted(counts.items())),
        "anchor_fallback_count": sum(
            bool(row["anchor_gate_fallback_required"])
            for row in predictions
        ),
        "release_fallback_count": sum(
            bool(row["release_fallback_required"]) for row in predictions
        ),
        "missing_anchor_condition_segment_count": sum(
            bool(row["missing_anchor_ids"]) for row in predictions
        ),
        "coverage_exact": keys == group_keys and len(keys) == len(groups),
        "unsafe_anchor_bypass_count": sum(
            bool(row["anchor_gate_fallback_required"])
            and row["effective_decision"] != "ABSTAIN"
            for row in predictions
        ),
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "requested_device": requested_device,
        "actual_device": str(device),
        "model_contract": expected_contract,
        "folds": fold_rows,
        "inputs": {
            "candidate_manifest": _input_record(
                candidate_root / "manifest.json"
            ),
            "case_inventory": _input_record(inventory_path),
            "anchor_store_manifest": _input_record(
                anchor_store / "manifest.json"
            ),
            "anchor_oof_summary": _input_record(
                anchor_oof / "summary.json"
            ),
            "trained_ordinary_summary": _input_record(
                trained_root / "summary.json"
            ),
        },
        "predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            keys == group_keys
            and len(keys) == len(groups)
            and not any(
                bool(row["anchor_gate_fallback_required"])
                and row["effective_decision"] != "ABSTAIN"
                for row in predictions
            )
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("full ordinary OOF inference gate failed")
    return root


def ordinary_inference_example_from_group(
    group: Mapping[str, Any],
    *,
    fold: int,
) -> OrdinaryPlanTrainingExample:
    candidates = list(group.get("candidates") or ())
    if not candidates:
        raise ValueError("ordinary inference group has no plan candidates")
    member_rows = [
        list(candidate.get("road_members") or ()) for candidate in candidates
    ]
    arm_rows = [
        list(candidate.get("arm_rows") or ()) for candidate in candidates
    ]
    candidate_ids = tuple(str(row["plan_id"]) for row in candidates)
    abstain = [
        index
        for index, row in enumerate(candidates)
        if str(row.get("decision")) == "ABSTAIN"
    ]
    if len(abstain) != 1:
        raise ValueError("ordinary inference ABSTAIN plan is not unique")
    index = abstain[0]
    case_key = str(group["case_key"])
    segment_id = str(group["segment_id"])
    return OrdinaryPlanTrainingExample(
        sample_id=f"{case_key}:{segment_id}",
        case_key=case_key,
        segment_id=segment_id,
        fold=int(fold),
        object_features=tuple(
            float(value) for value in group["object_features"]
        ),
        required_anchor_ids=tuple(
            str(value) for value in group["required_anchor_ids"]
        ),
        arm_anchor_ids=tuple(
            str(value) for value in group.get("arm_anchor_ids") or ()
        ),
        candidate_ids=candidate_ids,
        candidate_decisions=tuple(
            str(row["decision"]) for row in candidates
        ),
        candidate_road_ids=tuple(
            tuple(str(value) for value in row["road_ids"])
            for row in candidates
        ),
        candidate_member_ids=tuple(
            tuple(str(member["road_id"]) for member in members)
            for members in member_rows
        ),
        candidate_member_endpoint_ids=tuple(
            tuple(
                (
                    str(member["start_node_id"]),
                    str(member["end_node_id"]),
                )
                for member in members
            )
            for members in member_rows
        ),
        candidate_member_features=tuple(
            tuple(
                tuple(float(value) for value in member["features"])
                for member in members
            )
            for members in member_rows
        ),
        candidate_arm_road_ids=tuple(
            tuple(str(arm["nearest_road_id"]) for arm in arms)
            for arms in arm_rows
        ),
        candidate_arm_node_ids=tuple(
            tuple(str(arm["nearest_node_id"]) for arm in arms)
            for arms in arm_rows
        ),
        candidate_arm_features=tuple(
            tuple(
                tuple(float(value) for value in arm["features"])
                for arm in arms
            )
            for arms in arm_rows
        ),
        candidate_features=tuple(
            tuple(float(value) for value in row["features"])
            for row in candidates
        ),
        acceptable_indices=(index,),
        preferred_index=index,
        preferred_decision="",
        sample_weight=0.0,
        clue_label=0,
        clue_task_mask=False,
        fallback_scope_label=0,
        fallback_scope_task_mask=False,
        carrier_task_mask=False,
    )


def validate_inference_group_dimensions(
    example: OrdinaryPlanTrainingExample,
) -> None:
    for rows in example.candidate_member_features:
        if any(
            len(values) != ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM
            for values in rows
        ):
            raise ValueError("ordinary inference member dimension differs")
    for rows in example.candidate_arm_features:
        if len(rows) not in {0, ORDINARY_PLAN_ARM_COUNT} or any(
            len(values) != ORDINARY_PLAN_ARM_BASE_FEATURE_DIM
            for values in rows
        ):
            raise ValueError("ordinary inference arm dimension differs")


def _load_model(
    path: Path,
    *,
    device: torch.device,
) -> tuple[TargetAJointNetwork, Mapping[str, Any]]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    config = TargetAConfig(**payload["config"])
    config.validate()
    model = TargetAJointNetwork(config)
    if model_contract(model) != payload["model_contract"]:
        raise ValueError("ordinary checkpoint architecture differs")
    model.load_state_dict(payload["model_state_dict"], strict=True)
    model.to(device)
    model.eval()
    return model, payload


def _resolve_device(requested: str) -> torch.device:
    normalized = requested.casefold()
    if normalized == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        return torch.device("cuda")
    if normalized == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported ordinary inference device: {requested}")


def _input_record(path: Path) -> dict[str, str | int]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
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
    "ordinary_inference_example_from_group",
    "run_full_ordinary_strict_oof_inference",
    "validate_inference_group_dimensions",
]
