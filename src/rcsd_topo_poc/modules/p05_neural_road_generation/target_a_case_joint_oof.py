from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_data import (
    CaseJointBatch,
    CaseJointExample,
    build_segment_joint_examples,
    collate_case_joint_batch,
    pack_case_joint_batches,
    segment_joint_anchor_repeat_counts,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_network import (
    TargetACaseJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
    TargetAJointNetwork,
    hierarchical_anchor_selection_logits,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
    read_ordinary_plan_training_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
    acceptable_set_nll,
    compute_target_a_loss,
    model_state_signature,
    move_training_batch,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class CaseJointCanaryConfig:
    outer_fold: int = 2
    inner_fold: int = 3
    max_batch_size: int = 16
    max_anchor_groups: int = 128
    requested_device: str = "cuda"
    anchor_plan_compatibility: bool = False
    compatibility_apply_to_plan_logits: bool = True
    compatibility_auxiliary_loss_weight: float = 0.0

    def validate(self) -> None:
        if self.outer_fold == self.inner_fold:
            raise ValueError("outer and inner folds must differ")
        if self.max_batch_size < 1 or self.max_anchor_groups < 1:
            raise ValueError("Case joint batch limits must be positive")
        if self.requested_device not in {"cpu", "cuda"}:
            raise ValueError("requested device must be cpu or cuda")
        if self.compatibility_auxiliary_loss_weight < 0:
            raise ValueError("compatibility loss weight must not be negative")
        if (
            self.compatibility_auxiliary_loss_weight
            and not self.anchor_plan_compatibility
        ):
            raise ValueError(
                "compatibility auxiliary loss requires the compatibility head"
            )


@dataclass
class _LazyStageResult:
    model: TargetAJointNetwork
    epoch_count: int
    best_validation_loss: float
    history: list[dict[str, float]]
    wall_seconds: float
    state_signature: str


def run_case_joint_fold_canary(
    *,
    anchor_store_root: Path,
    candidate_store_root: Path,
    preflight_root: Path,
    output_root: Path,
    run_id: str,
    model_config: TargetAConfig,
    canary_config: CaseJointCanaryConfig,
    seed: int,
    inner_initial_state_dict: Mapping[str, torch.Tensor] | None = None,
    outer_initial_state_dict: Mapping[str, torch.Tensor] | None = None,
) -> Path:
    """Train one strict inner/outer fold with a real shared anchor carrier forward."""
    started = time.perf_counter()
    canary_config.validate()
    model_config.validate()
    if model_config.stop_gradient_between_stages:
        raise ValueError(
            "Case joint training requires carrier gradients to reach the "
            "shared anchor evidence encoder"
        )
    anchor_root = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    label_root = normalize_runtime_path(preflight_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    progress_path = root / "progress.jsonl"

    anchors = read_anchor_pretraining_stores(anchor_root)
    ordinary = read_ordinary_plan_training_examples(
        candidate_store_root=candidate_root,
        preflight_root=label_root,
    )
    joint_examples = build_segment_joint_examples(anchors, ordinary)
    folds = sorted({row.fold for row in joint_examples})
    if (
        canary_config.outer_fold not in folds
        or canary_config.inner_fold not in folds
        or len(folds) < 3
    ):
        raise ValueError("Case joint strict split is undefined")
    repeat_counts = segment_joint_anchor_repeat_counts(joint_examples)
    (
        inner_training,
        inner_validation,
        outer_training,
        outer_validation,
    ) = _strict_split(
        joint_examples,
        outer_fold=canary_config.outer_fold,
        inner_fold=canary_config.inner_fold,
    )
    anchors_by_fold = _unique_anchors_by_fold(anchors)
    inner_config = replace(
        model_config,
        anchor_status_class_weights=_balanced_status_weights(
            anchors_by_fold,
            excluded_folds={
                canary_config.outer_fold,
                canary_config.inner_fold,
            },
        ),
        anchor_gate_class_weights=_balanced_gate_weights(
            anchors_by_fold,
            excluded_folds={
                canary_config.outer_fold,
                canary_config.inner_fold,
            },
        )
        if model_config.learned_anchor_gate
        else (),
    )
    outer_config = replace(
        model_config,
        anchor_status_class_weights=_balanced_status_weights(
            anchors_by_fold,
            excluded_folds={canary_config.outer_fold},
        ),
        anchor_gate_class_weights=_balanced_gate_weights(
            anchors_by_fold,
            excluded_folds={canary_config.outer_fold},
        )
        if model_config.learned_anchor_gate
        else (),
    )
    device = _resolve_device(canary_config.requested_device)
    tuning = _train_lazy_stage(
        inner_training,
        inner_validation,
        repeat_counts=repeat_counts,
        config=inner_config,
        seed=seed + 17,
        device=device,
        canary_config=canary_config,
        progress_path=progress_path,
        initial_state_dict=inner_initial_state_dict,
    )
    inner_free = predict_case_joint_examples(
        tuning.model,
        inner_validation,
        repeat_counts=repeat_counts,
        config=inner_config,
        device=device,
        canary_config=canary_config,
        teacher_forcing=False,
    )
    inner_teacher = predict_case_joint_examples(
        tuning.model,
        inner_validation,
        repeat_counts=repeat_counts,
        config=inner_config,
        device=device,
        canary_config=canary_config,
        teacher_forcing=True,
    )
    no_evidence_threshold = zero_false_no_evidence_threshold(
        inner_free["anchor_rows"]
    )
    inner_free = apply_case_joint_no_evidence_proof(
        inner_free,
        threshold=no_evidence_threshold,
    )
    inner_teacher = apply_case_joint_no_evidence_proof(
        inner_teacher,
        threshold=no_evidence_threshold,
    )
    threshold = zero_unsafe_joint_threshold(inner_free["ordinary_rows"])

    final = _train_lazy_fixed_epochs(
        outer_training,
        repeat_counts=repeat_counts,
        config=outer_config,
        seed=seed + 53,
        device=device,
        canary_config=canary_config,
        epoch_count=tuning.epoch_count,
        progress_path=progress_path,
        initial_state_dict=outer_initial_state_dict,
    )
    outer_free = predict_case_joint_examples(
        final.model,
        outer_validation,
        repeat_counts=repeat_counts,
        config=outer_config,
        device=device,
        canary_config=canary_config,
        teacher_forcing=False,
    )
    outer_teacher = predict_case_joint_examples(
        final.model,
        outer_validation,
        repeat_counts=repeat_counts,
        config=outer_config,
        device=device,
        canary_config=canary_config,
        teacher_forcing=True,
    )
    outer_free = apply_case_joint_no_evidence_proof(
        outer_free,
        threshold=no_evidence_threshold,
    )
    outer_teacher = apply_case_joint_no_evidence_proof(
        outer_teacher,
        threshold=no_evidence_threshold,
    )
    inner_metrics = case_joint_metrics(
        inner_free,
        teacher_rows=inner_teacher["ordinary_rows"],
        release_threshold=threshold,
    )
    outer_metrics = case_joint_metrics(
        outer_free,
        teacher_rows=outer_teacher["ordinary_rows"],
        release_threshold=threshold,
    )

    inner_checkpoint = root / "inner_checkpoint.pt"
    outer_checkpoint = root / "outer_checkpoint.pt"
    _save_checkpoint(
        inner_checkpoint,
        model=tuning.model,
        config=inner_config,
        stage="CASE_JOINT_INNER",
        seed=seed + 17,
        epoch_count=tuning.epoch_count,
    )
    _save_checkpoint(
        outer_checkpoint,
        model=final.model,
        config=outer_config,
        stage="CASE_JOINT_OUTER",
        seed=seed + 53,
        epoch_count=final.epoch_count,
    )
    _write_jsonl(root / "inner_anchor_predictions.jsonl", inner_free["anchor_rows"])
    _write_jsonl(
        root / "inner_ordinary_predictions.jsonl",
        inner_free["ordinary_rows"],
    )
    _write_jsonl(root / "outer_anchor_predictions.jsonl", outer_free["anchor_rows"])
    _write_jsonl(
        root / "outer_ordinary_predictions.jsonl",
        outer_free["ordinary_rows"],
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "CASE_JOINT_ANCHOR_CARRIER_FOLD_CANARY",
        "run_id": run_id,
        "seed": seed,
        "canary_config": asdict(canary_config),
        "model_config": asdict(model_config),
        "inner_model_config": asdict(inner_config),
        "outer_model_config": asdict(outer_config),
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "parameter_count": parameter_count(
            _build_model(model_config, canary_config)
        ),
        "source_store_read_count": 3,
        "anchor_store": str(anchor_root),
        "anchor_manifest_sha256": sha256_file(anchor_root / "manifest.json"),
        "candidate_store": str(candidate_root),
        "candidate_manifest_sha256": sha256_file(
            candidate_root / "manifest.json"
        ),
        "preflight_root": str(label_root),
        "joint_example_count": len(joint_examples),
        "missing_anchor_segment_count": len(ordinary) - len(joint_examples),
        "maximum_subgraph_object_count": max(
            len(row.anchors) + 1 for row in joint_examples
        ),
        "folds": folds,
        "split": {
            "inner_training_count": len(inner_training),
            "inner_validation_count": len(inner_validation),
            "outer_training_count": len(outer_training),
            "outer_validation_count": len(outer_validation),
            "outer_label_access_during_fit": 0,
            "threshold_source": "INNER_VALIDATION_ONLY",
        },
        "selected_epoch": tuning.epoch_count,
        "release_threshold": threshold,
        "no_evidence_proof_threshold": no_evidence_threshold,
        "inner_metrics": inner_metrics,
        "outer_metrics": outer_metrics,
        "inner_history": tuning.history,
        "outer_history": final.history,
        "inner_checkpoint": str(inner_checkpoint.resolve()),
        "inner_checkpoint_sha256": sha256_file(inner_checkpoint),
        "outer_checkpoint": str(outer_checkpoint.resolve()),
        "outer_checkpoint_sha256": sha256_file(outer_checkpoint),
        "anchor_decision_direction": (
            "anchor-to-anchor and ordinary-query-to-anchor only; carrier "
            "objects cannot send messages into anchor decisions"
        ),
        "teacher_forcing_contract": (
            "training carrier loss uses the label-selected unique anchor "
            "embedding; free-run evaluation removes all teacher choices"
        ),
        "no_evidence_keep_contract": (
            "A KEEP_SWSD plan may pass without a concrete RCSD anchor only "
            "when every required anchor is either uniquely released SUCCESS "
            "or passes the inner-only zero-false-positive NO_EVIDENCE proof."
        ),
        "disk_io_contract": (
            "each source store is read once; focal-Segment subgraphs are "
            "built and packed from in-memory examples"
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    summary["decision"] = (
        "CASE_JOINT_FOLD_CANARY_GO"
        if (
            outer_metrics["unsafe_auto_count"] == 0
            and outer_metrics["review_auto_count"] == 0
            and outer_metrics["anchor_prediction_inconsistency_count"] == 0
            and outer_metrics["automatic_correct_coverage"] >= 0.50
            and outer_metrics["anchor_object_exact"] >= 0.80
        )
        else "CASE_JOINT_FOLD_CANARY_NO_GO"
    )
    _write_json(root / "summary.json", summary)
    return root


def predict_case_joint_examples(
    model: TargetAJointNetwork,
    examples: Sequence[CaseJointExample],
    *,
    repeat_counts: Mapping[tuple[str, str], int],
    config: TargetAConfig,
    device: torch.device,
    canary_config: CaseJointCanaryConfig,
    teacher_forcing: bool,
) -> dict[str, list[dict[str, Any]]]:
    model.eval()
    ordinary_rows = []
    anchor_observations: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = {}
    with torch.no_grad():
        for group in _pack_examples(
            examples,
            max_batch_size=canary_config.max_batch_size,
            max_anchor_groups=canary_config.max_anchor_groups,
        ):
            members, training_batch = _collate_group(
                group,
                repeat_counts=repeat_counts,
                teacher_forcing=teacher_forcing,
                config=config,
                canary_config=canary_config,
            )
            moved = move_training_batch(training_batch, device)
            outputs = model(moved.tensors)
            selection_logits = (
                hierarchical_anchor_selection_logits(
                    outputs["anchor_candidate_logits"],
                    outputs.get("anchor_type_logits"),
                    moved.tensors,
                    cardinality_logits=(
                        outputs.get("anchor_cardinality_logits")
                        if config.anchor_cardinality_hard_lock
                        else None
                    ),
                    hard_type_lock=config.anchor_type_hard_lock,
                    type_prior_weight=config.anchor_type_prior_weight,
                )
                if config.hierarchical_anchor_decoder
                else outputs["anchor_candidate_logits"]
            )
            for batch_index, member in enumerate(members):
                ordinary_rows.append(
                    _ordinary_prediction_row(
                        member,
                        batch_index=batch_index,
                        outputs=outputs,
                        selection_logits=selection_logits,
                        config=config,
                        anchor_observations=anchor_observations,
                        teacher_forcing=teacher_forcing,
                    )
                )
    anchor_rows = _collapse_anchor_observations(anchor_observations)
    ordinary_rows.sort(key=lambda row: str(row["sample_id"]))
    return {
        "anchor_rows": anchor_rows,
        "ordinary_rows": ordinary_rows,
    }


def zero_unsafe_joint_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    unsafe_scores = [
        float(row["joint_score"])
        for row in rows
        if row["base_releasable"]
        and row["predicted_decision"] != "ABSTAIN"
        and (
            not _joint_truth_ready(row)
            or not row["joint_truth_correct"]
        )
    ]
    if not unsafe_scores:
        return 0.0
    maximum = max(unsafe_scores)
    return math.nextafter(maximum, math.inf)


def zero_false_no_evidence_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    false_scores = [
        float(row["no_evidence_joint_score"])
        for row in rows
        if (
            row["status_supervised"]
            and row["status_prediction"]
            == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
            and row["status_truth"]
            != ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
        )
    ]
    if not false_scores:
        return 0.5
    maximum = max(false_scores)
    return (
        1.0
        if maximum >= 1.0
        else math.nextafter(maximum, math.inf)
    )


def apply_case_joint_no_evidence_proof(
    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    threshold: float,
) -> dict[str, list[dict[str, Any]]]:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("NO_EVIDENCE proof threshold must be within [0, 1]")
    anchor_rows = []
    for source in predictions["anchor_rows"]:
        row = dict(source)
        row["no_evidence_proof_threshold"] = threshold
        row["no_evidence_proof_passed"] = bool(
            row["status_prediction"]
            == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
            and float(row["no_evidence_joint_score"]) >= threshold
        )
        anchor_rows.append(row)
    anchor_by_key = {
        (str(row["case_key"]), str(row["anchor_id"])): row
        for row in anchor_rows
    }
    ordinary_rows = []
    for source in predictions["ordinary_rows"]:
        row = dict(source)
        required = [
            anchor_by_key.get((str(row["case_key"]), str(anchor_id)))
            for anchor_id in row["required_anchor_ids"]
        ]
        required_complete = bool(required) and all(
            anchor is not None for anchor in required
        )
        required_rows = [
            anchor for anchor in required if anchor is not None
        ]
        keep_plan = row["predicted_decision"] == "KEEP_SWSD"
        release_modes = [
            _anchor_release_mode(anchor, allow_no_evidence=keep_plan)
            for anchor in required_rows
        ]
        base_releasable = (
            required_complete
            and row["predicted_decision"] != "ABSTAIN"
            and all(mode != "BLOCKED" for mode in release_modes)
        )
        anchor_truth_ready = required_complete and all(
            _anchor_release_truth_ready(anchor, mode)
            for anchor, mode in zip(
                required_rows,
                release_modes,
                strict=True,
            )
        )
        anchor_truth_correct = anchor_truth_ready and all(
            _anchor_release_truth_correct(anchor, mode)
            for anchor, mode in zip(
                required_rows,
                release_modes,
                strict=True,
            )
        )
        anchor_scores = [
            (
                float(anchor["no_evidence_joint_score"])
                if mode == "NO_EVIDENCE"
                else float(anchor["joint_score"])
            )
            for anchor, mode in zip(
                required_rows,
                release_modes,
                strict=True,
            )
        ]
        row["required_anchor_complete"] = required_complete
        row["required_anchor_truth_ready"] = anchor_truth_ready
        row["required_anchor_truth_correct"] = anchor_truth_correct
        row["base_releasable"] = base_releasable
        row["no_evidence_keep_exception"] = bool(
            keep_plan and "NO_EVIDENCE" in release_modes
        )
        row["joint_score"] = min(
            [float(row["plan_confidence"]), *anchor_scores]
        )
        row["joint_truth_ready"] = bool(
            row["truth_label_ready"] and anchor_truth_ready
        )
        row["joint_truth_correct"] = bool(
            row["joint_truth_ready"]
            and row["plan_correct"]
            and anchor_truth_correct
        )
        ordinary_rows.append(row)
    return {
        "anchor_rows": anchor_rows,
        "ordinary_rows": ordinary_rows,
    }


def _anchor_release_mode(
    row: Mapping[str, Any],
    *,
    allow_no_evidence: bool,
) -> str:
    if row["base_released"]:
        return "SUCCESS"
    if allow_no_evidence and row["no_evidence_proof_passed"]:
        return "NO_EVIDENCE"
    return "BLOCKED"


def _anchor_release_truth_correct(
    row: Mapping[str, Any],
    mode: str,
) -> bool:
    if mode == "SUCCESS":
        return bool(row["truth_success"] and row["candidate_correct"])
    if mode == "NO_EVIDENCE":
        return bool(
            row["status_supervised"]
            and row["status_truth"]
            == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
        )
    return False


def _anchor_release_truth_ready(
    row: Mapping[str, Any],
    mode: str,
) -> bool:
    if mode == "SUCCESS":
        if not row["status_supervised"]:
            return False
        if (
            row["status_truth"]
            != ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        ):
            return True
        return bool(row["candidate_supervised"])
    if mode == "NO_EVIDENCE":
        return bool(row["status_supervised"])
    return False


def _joint_truth_ready(row: Mapping[str, Any]) -> bool:
    return bool(
        row["truth_label_ready"]
        and row.get("required_anchor_truth_ready", True)
    )


def case_joint_metrics(
    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    teacher_rows: Sequence[Mapping[str, Any]],
    release_threshold: float,
) -> dict[str, Any]:
    ordinary_rows = list(predictions["ordinary_rows"])
    anchor_rows = list(predictions["anchor_rows"])
    teacher_by_id = {
        str(row["sample_id"]): row for row in teacher_rows
    }
    if set(teacher_by_id) != {
        str(row["sample_id"]) for row in ordinary_rows
    }:
        raise ValueError("teacher and free-run ordinary prediction scope differs")
    ready = [row for row in ordinary_rows if row["truth_label_ready"]]
    joint_ready = [row for row in ordinary_rows if _joint_truth_ready(row)]
    anchor_supervised = [
        row for row in anchor_rows if row["candidate_supervised"]
    ]
    auto_rows = [
        row
        for row in ordinary_rows
        if row["base_releasable"]
        and row["predicted_decision"] != "ABSTAIN"
        and float(row["joint_score"]) >= release_threshold
    ]
    correct_auto = [
        row
        for row in auto_rows
        if _joint_truth_ready(row) and row["joint_truth_correct"]
    ]
    unsafe_auto = [
        row
        for row in auto_rows
        if _joint_truth_ready(row) and not row["joint_truth_correct"]
    ]
    review_auto = [
        row for row in auto_rows if not _joint_truth_ready(row)
    ]
    denominator = max(len(ordinary_rows), 1)
    ready_denominator = max(len(ready), 1)
    anchor_denominator = max(len(anchor_supervised), 1)
    return {
        "ordinary_count": len(ordinary_rows),
        "ordinary_truth_ready_count": len(ready),
        "joint_truth_ready_count": len(joint_ready),
        "all_plan_exact_count": sum(
            bool(row["plan_correct"]) for row in ordinary_rows
        ),
        "all_plan_exact": sum(
            bool(row["plan_correct"]) for row in ordinary_rows
        )
        / denominator,
        "anchor_unique_count": len(anchor_rows),
        "anchor_candidate_supervised_count": len(anchor_supervised),
        "anchor_object_exact_count": sum(
            bool(row["candidate_correct"]) for row in anchor_supervised
        ),
        "anchor_object_exact": sum(
            bool(row["candidate_correct"]) for row in anchor_supervised
        )
        / anchor_denominator,
        "anchor_prediction_inconsistency_count": sum(
            int(row["prediction_inconsistent"]) for row in anchor_rows
        ),
        "teacher_forced_plan_exact_count": sum(
            bool(teacher_by_id[str(row["sample_id"])]["plan_correct"])
            for row in ready
        ),
        "teacher_forced_plan_exact": sum(
            bool(teacher_by_id[str(row["sample_id"])]["plan_correct"])
            for row in ready
        )
        / ready_denominator,
        "free_plan_exact_count": sum(
            bool(row["plan_correct"]) for row in ready
        ),
        "free_plan_exact": sum(
            bool(row["plan_correct"]) for row in ready
        )
        / ready_denominator,
        "base_releasable_count": sum(
            bool(row["base_releasable"]) for row in ordinary_rows
        ),
        "no_evidence_keep_exception_count": sum(
            bool(row.get("no_evidence_keep_exception"))
            for row in ordinary_rows
        ),
        "release_threshold": release_threshold,
        "automatic_count": len(auto_rows),
        "automatic_correct_count": len(correct_auto),
        "unsafe_auto_count": len(unsafe_auto),
        "automatic_unverified_count": len(review_auto),
        "review_auto_count": len(review_auto),
        "automatic_correct_coverage": len(correct_auto) / denominator,
        "automatic_correct_ready_coverage": (
            len(correct_auto) / ready_denominator
        ),
    }


def _ordinary_prediction_row(
    member: CaseJointBatch,
    *,
    batch_index: int,
    outputs: Mapping[str, torch.Tensor],
    selection_logits: torch.Tensor,
    config: TargetAConfig,
    anchor_observations: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ],
    teacher_forcing: bool,
) -> dict[str, Any]:
    example = member.example.ordinary_segments[0]
    anchor_index_by_id = {
        row.anchor_id: index
        for index, row in enumerate(member.example.anchors)
    }
    status_probabilities = torch.softmax(
        outputs["anchor_status_logits"][batch_index],
        dim=-1,
    )
    status_predictions = status_probabilities.argmax(dim=-1)
    gate_probabilities = (
        torch.softmax(
            outputs["anchor_gate_logits"][batch_index],
            dim=-1,
        )[..., 1]
        if config.learned_anchor_gate
        else torch.ones_like(status_predictions, dtype=torch.float32)
    )
    local_selection_logits = selection_logits[batch_index]
    candidate_probabilities = torch.softmax(local_selection_logits, dim=-1)
    candidate_predictions = local_selection_logits.argmax(dim=-1)
    required_observations = []
    for anchor_id in example.required_anchor_ids:
        local_index = anchor_index_by_id.get(anchor_id)
        if local_index is None:
            required_observations.append(None)
            continue
        anchor = member.example.anchors[local_index]
        candidate_index = int(candidate_predictions[local_index].item())
        status_prediction = int(status_predictions[local_index].item())
        candidate_count = len(anchor.candidate_ids)
        candidate_statistics = _probability_statistics(
            candidate_probabilities[local_index, :candidate_count]
        )
        status_statistics = _probability_statistics(
            status_probabilities[local_index]
        )
        candidate_correct = (
            anchor.candidate_supervised
            and candidate_index in anchor.candidate_acceptable_indices
        )
        truth_success = _anchor_truth_success(anchor)
        base_released = (
            status_prediction
            == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
            and float(gate_probabilities[local_index].item())
            >= config.anchor_gate_pass_threshold
        )
        joint_score = min(
            float(
                status_probabilities[
                    local_index,
                    ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
                ].item()
            ),
            float(gate_probabilities[local_index].item()),
            float(
                candidate_probabilities[
                    local_index,
                    candidate_index,
                ].item()
            ),
        )
        observation = {
            "case_key": member.metadata.case_key,
            "anchor_id": anchor_id,
            "sample_id": anchor.sample_id,
            "status_prediction": status_prediction,
            "status_truth": anchor.status_label,
            "status_supervised": anchor.status_supervised,
            "candidate_prediction": candidate_index,
            "candidate_predicted_id": anchor.candidate_ids[candidate_index],
            "candidate_count": candidate_count,
            "candidate_confidence": candidate_statistics["confidence"],
            "candidate_margin": candidate_statistics["margin"],
            "candidate_normalized_entropy": candidate_statistics[
                "normalized_entropy"
            ],
            "candidate_supervised": anchor.candidate_supervised,
            "candidate_correct": candidate_correct,
            "truth_success": truth_success,
            "status_confidence": status_statistics["confidence"],
            "status_margin": status_statistics["margin"],
            "status_normalized_entropy": status_statistics[
                "normalized_entropy"
            ],
            "no_evidence_probability": float(
                status_probabilities[
                    local_index,
                    ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
                ].item()
            ),
            "anchor_gate_success_probability": float(
                gate_probabilities[local_index].item()
            ),
            "anchor_gate_margin": (
                2.0 * float(gate_probabilities[local_index].item()) - 1.0
            ),
            "no_evidence_joint_score": min(
                float(
                    status_probabilities[
                        local_index,
                        ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
                    ].item()
                ),
                1.0 - float(gate_probabilities[local_index].item()),
            ),
            "base_released": base_released,
            "joint_score": joint_score,
            "teacher_forcing": teacher_forcing,
        }
        anchor_observations.setdefault(
            (member.metadata.case_key, anchor_id),
            [],
        ).append(observation)
        required_observations.append(observation)

    plan_logits = outputs["ordinary_plan_logits"][batch_index, 0]
    plan_count = len(example.candidate_ids)
    plan_probabilities = torch.softmax(plan_logits[:plan_count], dim=-1)
    plan_prediction = int(plan_logits[:plan_count].argmax().item())
    plan_statistics = _probability_statistics(plan_probabilities)
    plan_validity_logits = outputs.get("ordinary_plan_validity_logits")
    if plan_validity_logits is None:
        plan_validity_head_present = False
        selected_plan_validity_probability = 0.5
        selected_plan_validity_margin = 0.0
        selected_plan_validity_gap = 0.0
        plan_validity_positive_fraction = 0.0
    else:
        plan_validity_head_present = True
        local_plan_validity_probabilities = torch.sigmoid(
            plan_validity_logits[batch_index, 0, :plan_count]
        )
        selected_plan_validity_probability = float(
            local_plan_validity_probabilities[plan_prediction].item()
        )
        selected_plan_validity_margin = (
            selected_plan_validity_probability - 0.5
        )
        alternative_plan_validity_probability = max(
            (
                float(probability.item())
                for index, probability in enumerate(
                    local_plan_validity_probabilities
                )
                if index != plan_prediction
            ),
            default=0.0,
        )
        selected_plan_validity_gap = (
            selected_plan_validity_probability
            - alternative_plan_validity_probability
        )
        plan_validity_positive_fraction = float(
            (local_plan_validity_probabilities >= 0.5)
            .to(dtype=torch.float32)
            .mean()
            .item()
        )
    predicted_decision = example.candidate_decisions[plan_prediction]
    decision_groups = sorted(set(example.candidate_decisions))
    decision_probabilities = {
        decision: float(
            plan_probabilities[
                torch.tensor(
                    [
                        index
                        for index, value in enumerate(
                            example.candidate_decisions
                        )
                        if value == decision
                    ],
                    dtype=torch.long,
                    device=plan_probabilities.device,
                )
            ]
            .sum()
            .item()
        )
        for decision in decision_groups
    }
    predicted_decision_probability = decision_probabilities[
        predicted_decision
    ]
    alternative_decision_probability = max(
        (
            probability
            for decision, probability in decision_probabilities.items()
            if decision != predicted_decision
        ),
        default=0.0,
    )
    within_decision_indices = torch.tensor(
        [
            index
            for index, value in enumerate(example.candidate_decisions)
            if value == predicted_decision
        ],
        dtype=torch.long,
        device=plan_probabilities.device,
    )
    within_decision_probabilities = plan_probabilities[
        within_decision_indices
    ]
    within_decision_probabilities = (
        within_decision_probabilities
        / within_decision_probabilities.sum().clamp_min(1e-12)
    )
    within_decision_statistics = _probability_statistics(
        within_decision_probabilities
    )
    decision_index = _ordinary_decision_index(predicted_decision)
    decision_logits = outputs.get("ordinary_decision_logits")
    if decision_logits is None:
        decision_head_probability = predicted_decision_probability
        decision_head_prediction = decision_index
        decision_head_statistics = {
            "margin": (
                predicted_decision_probability
                - alternative_decision_probability
            ),
            "normalized_entropy": plan_statistics["normalized_entropy"],
        }
    else:
        local_decision_logits = decision_logits[batch_index, 0].clone()
        valid_decision_indices = {
            _ordinary_decision_index(value)
            for value in example.candidate_decisions
        }
        for index in range(local_decision_logits.numel()):
            if index not in valid_decision_indices:
                local_decision_logits[index] = -torch.inf
        decision_head_probabilities = torch.softmax(
            local_decision_logits,
            dim=-1,
        )
        decision_head_prediction = int(
            local_decision_logits.argmax().item()
        )
        decision_head_probability = float(
            decision_head_probabilities[decision_index].item()
        )
        decision_head_statistics = _probability_statistics(
            decision_head_probabilities[
                torch.tensor(
                    sorted(valid_decision_indices),
                    dtype=torch.long,
                    device=decision_head_probabilities.device,
                )
            ]
        )
    decision_validity_logits = outputs.get(
        "ordinary_decision_validity_logits"
    )
    if decision_validity_logits is None:
        decision_validity_head_present = False
        selected_decision_validity_probability = 0.5
        selected_decision_validity_margin = 0.0
        selected_decision_validity_gap = 0.0
        decision_validity_positive_fraction = 0.0
    else:
        decision_validity_head_present = True
        local_decision_validity_probabilities = torch.sigmoid(
            decision_validity_logits[batch_index, 0]
        )
        valid_decision_validity_probabilities = (
            local_decision_validity_probabilities[
                torch.tensor(
                    sorted(valid_decision_indices),
                    dtype=torch.long,
                    device=local_decision_validity_probabilities.device,
                )
            ]
        )
        selected_decision_validity_probability = float(
            local_decision_validity_probabilities[decision_index].item()
        )
        selected_decision_validity_margin = (
            selected_decision_validity_probability - 0.5
        )
        alternative_decision_validity_probability = max(
            (
                float(probability.item())
                for index, probability in enumerate(
                    local_decision_validity_probabilities
                )
                if (
                    index in valid_decision_indices
                    and index != decision_index
                )
            ),
            default=0.0,
        )
        selected_decision_validity_gap = (
            selected_decision_validity_probability
            - alternative_decision_validity_probability
        )
        decision_validity_positive_fraction = float(
            (valid_decision_validity_probabilities >= 0.5)
            .to(dtype=torch.float32)
            .mean()
            .item()
        )
    plan_correct = plan_prediction in example.acceptable_indices
    required_complete = bool(required_observations) and all(
        row is not None for row in required_observations
    )
    base_releasable = required_complete and all(
        bool(row["base_released"])
        for row in required_observations
        if row is not None
    )
    anchor_truth_correct = required_complete and all(
        bool(row["truth_success"]) and bool(row["candidate_correct"])
        for row in required_observations
        if row is not None
    )
    anchor_truth_ready = required_complete and all(
        _anchor_release_truth_ready(row, "SUCCESS")
        for row in required_observations
        if row is not None
    )
    anchor_truth_correct = anchor_truth_ready and anchor_truth_correct
    anchor_scores = [
        float(row["joint_score"])
        for row in required_observations
        if row is not None
    ]
    joint_score = min(
        [float(plan_probabilities[plan_prediction].item()), *anchor_scores]
    )
    return {
        "sample_id": example.sample_id,
        "case_key": example.case_key,
        "segment_id": example.segment_id,
        "fold": example.fold,
        "predicted_plan_index": plan_prediction,
        "predicted_plan_id": example.candidate_ids[plan_prediction],
        "predicted_decision": predicted_decision,
        "acceptable_decisions": sorted(
            {
                example.candidate_decisions[index]
                for index in example.acceptable_indices
            }
        ),
        "preferred_decision": example.preferred_decision,
        "plan_candidate_count": plan_count,
        "predicted_plan_road_count": len(
            example.candidate_road_ids[plan_prediction]
        ),
        "predicted_plan_member_count": len(
            example.candidate_member_ids[plan_prediction]
        ),
        "plan_confidence": float(
            plan_probabilities[plan_prediction].item()
        ),
        "plan_margin": plan_statistics["margin"],
        "plan_normalized_entropy": plan_statistics["normalized_entropy"],
        "plan_validity_head_present": plan_validity_head_present,
        "selected_plan_validity_probability": (
            selected_plan_validity_probability
        ),
        "selected_plan_validity_margin": selected_plan_validity_margin,
        "selected_plan_validity_gap": selected_plan_validity_gap,
        "plan_validity_positive_fraction": (
            plan_validity_positive_fraction
        ),
        "decision_confidence": predicted_decision_probability,
        "decision_margin": (
            predicted_decision_probability
            - alternative_decision_probability
        ),
        "decision_head_prediction": decision_head_prediction,
        "decision_head_agrees": (
            decision_head_prediction == decision_index
        ),
        "decision_head_confidence": decision_head_probability,
        "decision_head_margin": decision_head_statistics["margin"],
        "decision_head_normalized_entropy": decision_head_statistics[
            "normalized_entropy"
        ],
        "decision_validity_head_present": (
            decision_validity_head_present
        ),
        "selected_decision_validity_probability": (
            selected_decision_validity_probability
        ),
        "selected_decision_validity_margin": (
            selected_decision_validity_margin
        ),
        "selected_decision_validity_gap": (
            selected_decision_validity_gap
        ),
        "decision_validity_positive_fraction": (
            decision_validity_positive_fraction
        ),
        "within_decision_candidate_count": int(
            within_decision_indices.numel()
        ),
        "within_decision_confidence": within_decision_statistics[
            "confidence"
        ],
        "within_decision_margin": within_decision_statistics["margin"],
        "within_decision_normalized_entropy": (
            within_decision_statistics["normalized_entropy"]
        ),
        "plan_correct": plan_correct,
        "truth_label_ready": bool(
            member.metadata.ordinary_training_ready[0]
        ),
        "required_anchor_count": len(example.required_anchor_ids),
        "required_anchor_ids": list(example.required_anchor_ids),
        "required_anchor_complete": required_complete,
        "required_anchor_truth_ready": anchor_truth_ready,
        "required_anchor_truth_correct": anchor_truth_correct,
        "base_releasable": base_releasable,
        "joint_score": joint_score,
        "joint_truth_ready": bool(
            member.metadata.ordinary_training_ready[0]
            and anchor_truth_ready
        ),
        "joint_truth_correct": bool(
            member.metadata.ordinary_training_ready[0]
            and anchor_truth_ready
            and plan_correct
            and anchor_truth_correct
        ),
        "teacher_forcing": teacher_forcing,
    }


def _probability_statistics(
    probabilities: torch.Tensor,
) -> dict[str, float]:
    values = probabilities.reshape(-1)
    if values.numel() < 1:
        raise ValueError("probability statistics require a non-empty tensor")
    sorted_values = torch.sort(values, descending=True).values
    confidence = float(sorted_values[0].item())
    runner_up = (
        float(sorted_values[1].item())
        if sorted_values.numel() > 1
        else 0.0
    )
    if sorted_values.numel() == 1:
        normalized_entropy = 0.0
    else:
        entropy = -(
            values.clamp_min(1e-12) * values.clamp_min(1e-12).log()
        ).sum()
        normalized_entropy = float(
            (entropy / math.log(values.numel())).item()
        )
    return {
        "confidence": confidence,
        "margin": confidence - runner_up,
        "normalized_entropy": normalized_entropy,
    }


def _ordinary_decision_index(decision: str) -> int:
    if decision == "KEEP_SWSD":
        return ORDINARY_DECISION_KEEP_SWSD
    if decision in {"USE_RCSD", "T06_MAIN_RCSD_ATTACHED_SWSD"}:
        return ORDINARY_DECISION_USE_RCSD
    if decision == "ABSTAIN":
        return ORDINARY_DECISION_ABSTAIN
    raise ValueError(f"unsupported ordinary decision: {decision}")


def _collapse_anchor_observations(
    rows: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    result = []
    comparison_keys = (
        "status_prediction",
        "candidate_prediction",
        "candidate_predicted_id",
        "base_released",
    )
    for key, observations in sorted(rows.items()):
        first = dict(observations[0])
        inconsistent = any(
            any(row[name] != first[name] for name in comparison_keys)
            for row in observations[1:]
        )
        first["observation_count"] = len(observations)
        first["prediction_inconsistent"] = inconsistent
        first["case_key"] = key[0]
        first["anchor_id"] = key[1]
        result.append(first)
    return result


def _train_lazy_stage(
    train_examples: Sequence[CaseJointExample],
    validation_examples: Sequence[CaseJointExample],
    *,
    repeat_counts: Mapping[tuple[str, str], int],
    config: TargetAConfig,
    seed: int,
    device: torch.device,
    canary_config: CaseJointCanaryConfig,
    progress_path: Path | None = None,
    initial_state_dict: Mapping[str, torch.Tensor] | None = None,
) -> _LazyStageResult:
    model, optimizer = _new_model_and_optimizer(
        config,
        seed,
        device,
        canary_config=canary_config,
    )
    if initial_state_dict is not None:
        model.load_state_dict(initial_state_dict)
    train_groups = _pack_examples(
        train_examples,
        max_batch_size=canary_config.max_batch_size,
        max_anchor_groups=canary_config.max_anchor_groups,
    )
    validation_groups = _pack_examples(
        validation_examples,
        max_batch_size=canary_config.max_batch_size,
        max_anchor_groups=canary_config.max_anchor_groups,
    )
    best_state = None
    best_epoch = 0
    best_validation_loss = float("inf")
    no_improvement = 0
    history = []
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        order = list(range(len(train_groups)))
        random.Random(seed * 1000 + epoch).shuffle(order)
        train_total = 0.0
        train_count = 0
        for index in order:
            _, batch = _collate_group(
                train_groups[index],
                repeat_counts=repeat_counts,
                teacher_forcing=True,
                config=config,
                canary_config=canary_config,
            )
            moved = move_training_batch(batch, device)
            optimizer.zero_grad(set_to_none=True)
            outputs = model(moved.tensors)
            loss, _ = _compute_case_joint_loss(
                outputs,
                moved,
                config,
                canary_config,
            )
            if not torch.isfinite(loss):
                raise RuntimeError("Case joint training produced non-finite loss")
            loss.backward()
            _assert_finite_gradients(model, train_groups[index])
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            _assert_finite_parameters(model, train_groups[index])
            count = len(train_groups[index])
            train_total += float(loss.detach().item()) * count
            train_count += count
        validation_loss = _lazy_validation_loss(
            model,
            validation_groups,
            repeat_counts=repeat_counts,
            config=config,
            device=device,
            canary_config=canary_config,
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_total / max(train_count, 1),
                "validation_loss": validation_loss,
            }
        )
        _append_progress(
            progress_path,
            {
                "phase": "INNER",
                **history[-1],
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
        if validation_loss < best_validation_loss - 1e-6:
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            best_validation_loss = validation_loss
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("Case joint inner stage produced no checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    return _LazyStageResult(
        model=model,
        epoch_count=best_epoch,
        best_validation_loss=best_validation_loss,
        history=history,
        wall_seconds=time.perf_counter() - started,
        state_signature=model_state_signature(model),
    )


def _train_lazy_fixed_epochs(
    train_examples: Sequence[CaseJointExample],
    *,
    repeat_counts: Mapping[tuple[str, str], int],
    config: TargetAConfig,
    seed: int,
    device: torch.device,
    canary_config: CaseJointCanaryConfig,
    epoch_count: int,
    progress_path: Path | None = None,
    initial_state_dict: Mapping[str, torch.Tensor] | None = None,
) -> _LazyStageResult:
    if not 1 <= epoch_count <= config.max_epochs:
        raise ValueError("Case joint fixed epoch is outside config")
    model, optimizer = _new_model_and_optimizer(
        config,
        seed,
        device,
        canary_config=canary_config,
    )
    if initial_state_dict is not None:
        model.load_state_dict(initial_state_dict)
    groups = _pack_examples(
        train_examples,
        max_batch_size=canary_config.max_batch_size,
        max_anchor_groups=canary_config.max_anchor_groups,
    )
    history = []
    started = time.perf_counter()
    for epoch in range(1, epoch_count + 1):
        model.train()
        order = list(range(len(groups)))
        random.Random(seed * 1000 + epoch).shuffle(order)
        train_total = 0.0
        train_count = 0
        for index in order:
            _, batch = _collate_group(
                groups[index],
                repeat_counts=repeat_counts,
                teacher_forcing=True,
                config=config,
                canary_config=canary_config,
            )
            moved = move_training_batch(batch, device)
            optimizer.zero_grad(set_to_none=True)
            outputs = model(moved.tensors)
            loss, _ = _compute_case_joint_loss(
                outputs,
                moved,
                config,
                canary_config,
            )
            if not torch.isfinite(loss):
                raise RuntimeError("Case joint fixed fit produced non-finite loss")
            loss.backward()
            _assert_finite_gradients(model, groups[index])
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            _assert_finite_parameters(model, groups[index])
            count = len(groups[index])
            train_total += float(loss.detach().item()) * count
            train_count += count
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_total / max(train_count, 1),
            }
        )
        _append_progress(
            progress_path,
            {
                "phase": "OUTER",
                **history[-1],
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
    model.eval()
    return _LazyStageResult(
        model=model,
        epoch_count=epoch_count,
        best_validation_loss=float("nan"),
        history=history,
        wall_seconds=time.perf_counter() - started,
        state_signature=model_state_signature(model),
    )


def _lazy_validation_loss(
    model: TargetAJointNetwork,
    groups: Sequence[tuple[CaseJointExample, ...]],
    *,
    repeat_counts: Mapping[tuple[str, str], int],
    config: TargetAConfig,
    device: torch.device,
    canary_config: CaseJointCanaryConfig,
) -> float:
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for group in groups:
            _, batch = _collate_group(
                group,
                repeat_counts=repeat_counts,
                teacher_forcing=True,
                config=config,
                canary_config=canary_config,
            )
            moved = move_training_batch(batch, device)
            outputs = model(moved.tensors)
            loss, parts = _compute_case_joint_loss(
                outputs,
                moved,
                config,
                canary_config,
            )
            if not torch.isfinite(loss):
                sample_ids = [
                    row.ordinary_segments[0].sample_id for row in group
                ]
                raise RuntimeError(
                    "Case joint validation produced non-finite loss: "
                    f"samples={sample_ids}, parts={parts}, "
                    f"anchor_type={_tensor_diagnostics(outputs.get('anchor_type_logits'))}, "
                    f"anchor_candidate={_tensor_diagnostics(outputs.get('anchor_candidate_logits'))}"
                )
            group_count = len(group)
            total += float(loss.item()) * group_count
            count += group_count
    model.train()
    return total / max(count, 1)


def _new_model_and_optimizer(
    config: TargetAConfig,
    seed: int,
    device: torch.device,
    *,
    canary_config: CaseJointCanaryConfig,
) -> tuple[TargetAJointNetwork, torch.optim.Optimizer]:
    random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(config.torch_num_threads)
    model = _build_model(config, canary_config).to(device)
    count = parameter_count(model)
    if not config.min_parameter_count <= count <= config.max_parameter_count:
        raise ValueError(f"Case joint parameter count {count} is outside gate")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    return model, optimizer


def _build_model(
    config: TargetAConfig,
    canary_config: CaseJointCanaryConfig,
) -> TargetAJointNetwork:
    if canary_config.anchor_plan_compatibility:
        return TargetACaseJointNetwork(
            config,
            apply_compatibility_to_plan_logits=(
                canary_config.compatibility_apply_to_plan_logits
            ),
        )
    return TargetAJointNetwork(config)


def _compute_case_joint_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: TargetATrainingBatch,
    config: TargetAConfig,
    canary_config: CaseJointCanaryConfig,
) -> tuple[torch.Tensor, dict[str, float]]:
    total, parts = compute_target_a_loss(outputs, batch, config)
    weight = canary_config.compatibility_auxiliary_loss_weight
    if not weight:
        return total, parts
    logits = outputs.get("anchor_plan_compatibility_logits")
    if logits is None:
        raise ValueError("compatibility auxiliary loss lacks logits")
    raw = acceptable_set_nll(
        logits,
        batch.targets.ordinary_acceptable,
        batch.tensors.ordinary_plan_mask,
    )
    sample_weights = (
        batch.targets.ordinary_sample_weights
        if batch.targets.ordinary_sample_weights is not None
        else batch.targets.sample_weights
    )
    effective = (
        batch.targets.ordinary_task_mask.to(raw.dtype) * sample_weights
    )
    denominator = effective.sum()
    auxiliary = (
        (raw * effective).sum() / denominator
        if float(denominator.detach().item()) > 0
        else torch.where(
            torch.isfinite(raw),
            raw,
            torch.zeros_like(raw),
        ).sum()
        * 0.0
    )
    parts = dict(parts)
    parts["anchor_plan_compatibility"] = float(
        auxiliary.detach().item()
    )
    return total + weight * auxiliary, parts


def _assert_finite_gradients(
    model: TargetAJointNetwork,
    examples: Sequence[CaseJointExample],
) -> None:
    invalid = [
        name
        for name, parameter in model.named_parameters()
        if parameter.grad is not None
        and not bool(torch.isfinite(parameter.grad).all())
    ]
    if invalid:
        sample_ids = [
            row.ordinary_segments[0].sample_id for row in examples
        ]
        raise RuntimeError(
            "Case joint training produced non-finite gradients: "
            f"parameters={invalid[:12]}, samples={sample_ids}"
        )


def _assert_finite_parameters(
    model: TargetAJointNetwork,
    examples: Sequence[CaseJointExample],
) -> None:
    invalid = [
        name
        for name, parameter in model.named_parameters()
        if not bool(torch.isfinite(parameter).all())
    ]
    if invalid:
        sample_ids = [
            row.ordinary_segments[0].sample_id for row in examples
        ]
        raise RuntimeError(
            "Case joint optimizer produced non-finite parameters: "
            f"parameters={invalid[:12]}, samples={sample_ids}"
        )


def _tensor_diagnostics(
    values: torch.Tensor | None,
) -> dict[str, int]:
    if values is None:
        return {"missing": 1}
    return {
        "count": values.numel(),
        "finite": int(torch.isfinite(values).sum().item()),
        "nan": int(torch.isnan(values).sum().item()),
        "positive_inf": int(torch.isposinf(values).sum().item()),
        "negative_inf": int(torch.isneginf(values).sum().item()),
    }


def _pack_examples(
    examples: Sequence[CaseJointExample],
    *,
    max_batch_size: int,
    max_anchor_groups: int,
) -> tuple[tuple[CaseJointExample, ...], ...]:
    if not examples:
        raise ValueError("cannot pack empty Case joint example scope")
    ordered = sorted(
        examples,
        key=lambda row: (
            len(row.anchors),
            row.fold,
            row.case_key,
            row.ordinary_segments[0].segment_id,
        ),
    )
    result = []
    current = []
    anchor_count = 0
    for row in ordered:
        row_count = len(row.anchors)
        if current and (
            len(current) >= max_batch_size
            or anchor_count + row_count > max_anchor_groups
        ):
            result.append(tuple(current))
            current = []
            anchor_count = 0
        current.append(row)
        anchor_count += row_count
        if (
            len(current) >= max_batch_size
            or anchor_count >= max_anchor_groups
        ):
            result.append(tuple(current))
            current = []
            anchor_count = 0
    if current:
        result.append(tuple(current))
    return tuple(result)


def _collate_group(
    examples: Sequence[CaseJointExample],
    *,
    repeat_counts: Mapping[tuple[str, str], int],
    teacher_forcing: bool,
    config: TargetAConfig,
    canary_config: CaseJointCanaryConfig,
) -> tuple[tuple[CaseJointBatch, ...], TargetATrainingBatch]:
    members = tuple(
        collate_case_joint_batch(
            row,
            teacher_forcing=teacher_forcing,
            include_candidate_relations=(
                config.structured_anchor_object_decoder
            ),
            retain_anchor_structural_evidence=(
                config.anchor_structural_evidence_encoder
            ),
            retain_ordinary_member_evidence=(
                config.ordinary_plan_member_encoder
            ),
            retain_ordinary_arm_evidence=(
                config.ordinary_plan_arm_encoder
            ),
            anchor_repeat_counts=repeat_counts,
        )
        for row in examples
    )
    packed = pack_case_joint_batches(
        members,
        max_batch_size=canary_config.max_batch_size,
        max_anchor_groups=canary_config.max_anchor_groups,
    )
    if len(packed) != 1:
        raise AssertionError("prepacked Case joint group split during collation")
    return packed[0].members, packed[0].training_batch


def _strict_split(
    examples: Sequence[CaseJointExample],
    *,
    outer_fold: int,
    inner_fold: int,
) -> tuple[
    tuple[CaseJointExample, ...],
    tuple[CaseJointExample, ...],
    tuple[CaseJointExample, ...],
    tuple[CaseJointExample, ...],
]:
    if outer_fold == inner_fold:
        raise ValueError("outer and inner folds must differ")
    partitions = (
        tuple(
            row for row in examples if row.fold not in {outer_fold, inner_fold}
        ),
        tuple(row for row in examples if row.fold == inner_fold),
        tuple(row for row in examples if row.fold != outer_fold),
        tuple(row for row in examples if row.fold == outer_fold),
    )
    if not all(partitions):
        raise ValueError("Case joint strict split has an empty partition")
    train_case_keys = {row.case_key for row in partitions[2]}
    outer_case_keys = {row.case_key for row in partitions[3]}
    if train_case_keys & outer_case_keys:
        raise AssertionError("outer Case leaked into Case joint training")
    return partitions


def _unique_anchors_by_fold(
    anchors: Sequence[AnchorPretrainExample],
) -> dict[int, tuple[AnchorPretrainExample, ...]]:
    result = {}
    folds = sorted({row.fold for row in anchors})
    for fold in folds:
        rows = [row for row in anchors if row.fold == fold]
        keys = [(row.case_key, row.anchor_id) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("anchor store has duplicate Case/anchor truth")
        result[fold] = tuple(rows)
    return result


def _balanced_status_weights(
    anchors_by_fold: Mapping[int, Sequence[AnchorPretrainExample]],
    *,
    excluded_folds: set[int],
) -> tuple[float, ...]:
    count = len(AnchorStatus)
    counts = [0] * count
    for fold, rows in anchors_by_fold.items():
        if fold in excluded_folds:
            continue
        for row in rows:
            if row.status_supervised:
                counts[row.status_label] += 1
    total = sum(counts)
    return tuple(
        total / (count * value) if value else 0.0
        for value in counts
    )


def _balanced_gate_weights(
    anchors_by_fold: Mapping[int, Sequence[AnchorPretrainExample]],
    *,
    excluded_folds: set[int],
) -> tuple[float, float]:
    counts = [0, 0]
    for fold, rows in anchors_by_fold.items():
        if fold in excluded_folds:
            continue
        for row in rows:
            if row.gate_supervised:
                counts[row.gate_label] += 1
    total = sum(counts)
    return tuple(
        total / (2 * value) if value else 0.0
        for value in counts
    )


def _anchor_truth_success(row: AnchorPretrainExample) -> bool:
    return (
        row.status_supervised
        and row.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        and row.candidate_supervised
        and bool(row.candidate_acceptable_indices)
    )


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return torch.device(requested)


def _save_checkpoint(
    path: Path,
    *,
    model: TargetAJointNetwork,
    config: TargetAConfig,
    stage: str,
    seed: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": stage,
            "seed": seed,
            "epoch_count": epoch_count,
            "config": asdict(config),
            "state_dict": model.state_dict(),
            "state_signature": model_state_signature(model),
        },
        path,
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )


def _append_progress(
    path: Path | None,
    row: Mapping[str, Any],
) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        )


__all__ = [
    "CaseJointCanaryConfig",
    "case_joint_metrics",
    "predict_case_joint_examples",
    "run_case_joint_fold_canary",
    "zero_unsafe_joint_threshold",
]
