from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
    JunctionGraphSetRawOutput,
    compute_multitask_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    JunctionEvidenceExample,
    JunctionPredictionError,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t021_data import (
    EXPECTED_SPLIT_COUNTS,
    T021JoinedRecord,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t021_training import (
    _read_json,
    _select_device,
    _write_json,
    iter_t021_batches,
)


_LOSS_STAGE_KEYS: Mapping[str, tuple[str, ...]] = {
    "step1": ("step1",),
    "surface": (
        "surface_mode",
        "existing_surface_object",
        "virtual_surface_member",
        "virtual_surface_cardinality",
        "virtual_surface_required_coverage",
    ),
    "anchor_state_quality": ("anchor_state", "quality"),
    "anchor_structure": (
        "anchor_member",
        "anchor_member_cardinality",
        "main_anchor",
        "node_equivalence",
    ),
    "road_break": (
        "road_break_presence",
        "road_break_fraction",
        "road_break_count",
        "road_break_set_fraction",
    ),
    "complete_plan": ("complete_plan",),
}


@dataclass(frozen=True)
class T022TrainingConfig:
    cache_root: Path
    t021_output_dir: Path
    output_dir: Path
    expected_t021_checkpoint_sha256: str
    expected_t021_summary_sha256: str
    seed: int = 20_260_821
    hidden_dim: int = 384
    learning_rate: float = 1.0e-4
    weight_decay: float = 1.0e-4
    maximum_epochs: int = 12
    full_free_epoch: int = 8
    early_stopping_patience: int = 4
    minimum_validation_improvement: float = 1.0e-4
    maximum_records_per_batch: int = 8
    maximum_geometry_tokens_per_batch: int = 12_000
    gradient_clip_norm: float = 1.0
    device: str = "auto"

    @property
    def t021_checkpoint(self) -> Path:
        return Path(self.t021_output_dir) / "best-checkpoint.pt"

    @property
    def t021_summary(self) -> Path:
        return Path(self.t021_output_dir) / "summary.json"

    def validate(self) -> None:
        required = (
            Path(self.cache_root) / "manifest.json",
            Path(self.cache_root) / "readiness-summary.json",
            self.t021_checkpoint,
            self.t021_summary,
        )
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(path)
        if self.hidden_dim < 1 or self.maximum_epochs < 1:
            raise ValueError("T022 model dimensions/epochs must be positive")
        if not 1 <= self.full_free_epoch <= self.maximum_epochs:
            raise ValueError("T022 full_free_epoch must be within the training schedule")
        if self.early_stopping_patience < 1:
            raise ValueError("T022 early-stopping patience must be positive")
        if self.maximum_records_per_batch < 1:
            raise ValueError("T022 maximum_records_per_batch must be positive")
        if self.maximum_geometry_tokens_per_batch < 1:
            raise ValueError("T022 token budget must be positive")
        for name, value in (
            ("learning_rate", self.learning_rate),
            ("weight_decay", self.weight_decay),
            ("minimum_validation_improvement", self.minimum_validation_improvement),
            ("gradient_clip_norm", self.gradient_clip_norm),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"T022 {name} must be finite and non-negative")
        if self.learning_rate == 0.0 or self.gradient_clip_norm == 0.0:
            raise ValueError("T022 learning rate and gradient clip must be positive")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("T022 device must be auto, cpu, or cuda")
        for name, value in (
            ("checkpoint", self.expected_t021_checkpoint_sha256),
            ("summary", self.expected_t021_summary_sha256),
        ):
            normalized = value.strip().lower()
            if len(normalized) != 64 or any(
                character not in "0123456789abcdef" for character in normalized
            ):
                raise ValueError(f"T022 expected {name} SHA256 is invalid")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def teacher_forcing_ratio(epoch: int, full_free_epoch: int) -> float:
    """Fixed T022 schedule: 7 descending mixed epochs, then full free conditions."""

    if epoch < 1 or full_free_epoch < 1:
        raise ValueError("T022 schedule epochs must be positive")
    return max(0.0, float(full_free_epoch - epoch) / float(full_free_epoch))


def deterministic_teacher_masks(
    batch_size: int,
    *,
    ratio: float,
    seed: int,
    epoch: int,
    batch_index: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
    if batch_size < 0:
        raise ValueError("T022 batch size cannot be negative")
    if not math.isfinite(ratio) or not 0.0 <= ratio <= 1.0:
        raise ValueError("T022 teacher-forcing ratio must be in [0, 1]")
    if epoch < 1 or batch_index < 0:
        raise ValueError("T022 epoch/batch index is invalid")
    generator = random.Random(seed + epoch * 1_000_003 + batch_index * 10_007)
    step1 = tuple(generator.random() < ratio for _ in range(batch_size))
    surface = tuple(generator.random() < ratio for _ in range(batch_size))
    return (
        torch.tensor(step1, dtype=torch.bool, device=device),
        torch.tensor(surface, dtype=torch.bool, device=device),
    )


def _move_example(
    example: JunctionEvidenceExample,
    device: torch.device,
) -> JunctionEvidenceExample:
    return replace(
        example,
        geometry_tokens=example.geometry_tokens.to(device=device),
        topology_edge_indices=example.topology_edge_indices.to(device=device),
        topology_edge_features=example.topology_edge_features.to(device=device),
    )


def _examples_and_labels(
    records: Sequence[T021JoinedRecord],
    *,
    device: torch.device,
) -> tuple[
    tuple[JunctionEvidenceExample, ...],
    tuple[Any, ...],
    torch.Tensor,
    torch.Tensor,
]:
    examples = tuple(
        _move_example(record.teacher_example, device) for record in records
    )
    overlays = tuple(record.label.overlay for record in records)
    step1 = torch.tensor(
        tuple(record.label.teacher_step1_index for record in records),
        dtype=torch.long,
        device=device,
    )
    surface = torch.tensor(
        tuple(record.label.teacher_surface_index for record in records),
        dtype=torch.long,
        device=device,
    )
    return examples, overlays, step1, surface


def _run_scheduled_epoch(
    model: JunctionGraphSetModel,
    config: T022TrainingConfig,
    *,
    epoch: int,
    device: torch.device,
    optimizer: torch.optim.Optimizer,
) -> Mapping[str, float]:
    model.train()
    ratio = teacher_forcing_ratio(epoch, config.full_free_epoch)
    totals: defaultdict[str, float] = defaultdict(float)
    sample_count = 0
    batch_count = 0
    step1_teacher_count = 0
    surface_teacher_count = 0
    batches = iter_t021_batches(
        config.cache_root,
        split="train",
        maximum_records=config.maximum_records_per_batch,
        maximum_tokens=config.maximum_geometry_tokens_per_batch,
        seed=config.seed,
        epoch=epoch,
        shuffle=True,
    )
    for batch_index, records in enumerate(batches):
        if not records:
            continue
        examples, overlays, step1, surface = _examples_and_labels(
            records,
            device=device,
        )
        step1_mask, surface_mask = deterministic_teacher_masks(
            len(records),
            ratio=ratio,
            seed=config.seed,
            epoch=epoch,
            batch_index=batch_index,
            device=device,
        )
        optimizer.zero_grad(set_to_none=True)
        output = model(
            examples,
            step1_state_indices=step1,
            surface_mode_indices=surface,
            step1_teacher_mask=step1_mask,
            surface_teacher_mask=surface_mask,
        )
        losses = compute_multitask_loss(output, overlays)
        if not all(torch.isfinite(value).item() for value in losses.values()):
            raise JunctionPredictionError("T022 scheduled loss became non-finite")
        losses["total"].backward()
        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            max_norm=config.gradient_clip_norm,
        )
        optimizer.step()
        local_count = len(records)
        for key, value in losses.items():
            totals[key] += float(value.detach().cpu()) * local_count
        sample_count += local_count
        batch_count += 1
        step1_teacher_count += int(step1_mask.sum().detach().cpu())
        surface_teacher_count += int(surface_mask.sum().detach().cpu())
    if sample_count != EXPECTED_SPLIT_COUNTS["train"]:
        raise JunctionPredictionError(
            f"T022 train epoch saw {sample_count} records instead of "
            f"{EXPECTED_SPLIT_COUNTS['train']}"
        )
    return {
        **{key: value / sample_count for key, value in sorted(totals.items())},
        "sample_count": float(sample_count),
        "batch_count": float(batch_count),
        "scheduled_teacher_ratio": ratio,
        "realized_step1_teacher_ratio": step1_teacher_count / sample_count,
        "realized_surface_teacher_ratio": surface_teacher_count / sample_count,
    }


def _stage_totals(losses: Mapping[str, float]) -> Mapping[str, float]:
    return {
        stage: sum(float(losses[key]) for key in keys)
        for stage, keys in _LOSS_STAGE_KEYS.items()
    }


def _stage_diagnostics(
    teacher: Mapping[str, float],
    step1_teacher_surface_free: Mapping[str, float],
    full_free: Mapping[str, float],
) -> Mapping[str, Any]:
    teacher_stage = _stage_totals(teacher)
    surface_free_stage = _stage_totals(step1_teacher_surface_free)
    full_free_stage = _stage_totals(full_free)
    return {
        "loss_by_condition_mode": {
            "teacher": teacher_stage,
            "step1_teacher_surface_free": surface_free_stage,
            "full_free": full_free_stage,
        },
        "teacher_to_full_free_gap": {
            stage: full_free_stage[stage] - teacher_stage[stage]
            for stage in _LOSS_STAGE_KEYS
        },
        "surface_prediction_gap_with_teacher_step1": {
            stage: surface_free_stage[stage] - teacher_stage[stage]
            for stage in _LOSS_STAGE_KEYS
        },
        "additional_step1_propagation_gap": {
            stage: full_free_stage[stage] - surface_free_stage[stage]
            for stage in _LOSS_STAGE_KEYS
        },
    }


def _accumulate_losses(
    target: defaultdict[str, float],
    losses: Mapping[str, torch.Tensor],
    count: int,
) -> None:
    for key, value in losses.items():
        target[key] += float(value.detach().cpu()) * count


def _normalize_losses(
    values: Mapping[str, float],
    *,
    sample_count: int,
    batch_count: int,
) -> Mapping[str, float]:
    return {
        **{key: value / sample_count for key, value in sorted(values.items())},
        "sample_count": float(sample_count),
        "batch_count": float(batch_count),
    }


def _run_validation_diagnostics(
    model: JunctionGraphSetModel,
    config: T022TrainingConfig,
    *,
    epoch: int,
    device: torch.device,
) -> Mapping[str, Any]:
    model.eval()
    modes = ("teacher", "step1_teacher_surface_free", "full_free")
    totals = {mode: defaultdict(float) for mode in modes}
    source_totals: dict[str, dict[str, defaultdict[str, float]]] = {}
    source_counts: defaultdict[str, int] = defaultdict(int)
    source_batches: defaultdict[str, int] = defaultdict(int)
    mismatch_counts: defaultdict[str, int] = defaultdict(int)
    sample_count = 0
    batch_count = 0
    batches = iter_t021_batches(
        config.cache_root,
        split="validation",
        maximum_records=config.maximum_records_per_batch,
        maximum_tokens=config.maximum_geometry_tokens_per_batch,
        seed=config.seed,
        epoch=epoch,
        shuffle=False,
    )
    with torch.no_grad():
        for records in batches:
            if not records:
                continue
            sources = {record.label.source for record in records}
            if len(sources) != 1:
                raise JunctionPredictionError(
                    "T022 validation batch crossed source partitions"
                )
            source = next(iter(sources))
            if source not in source_totals:
                source_totals[source] = {
                    mode: defaultdict(float) for mode in modes
                }
            examples, overlays, step1, surface = _examples_and_labels(
                records,
                device=device,
            )
            teacher_output = model(
                examples,
                step1_state_indices=step1,
                surface_mode_indices=surface,
            )
            surface_free_output = model(
                examples,
                step1_state_indices=step1,
            )
            full_free_output = model(examples)
            outputs: Mapping[str, JunctionGraphSetRawOutput] = {
                "teacher": teacher_output,
                "step1_teacher_surface_free": surface_free_output,
                "full_free": full_free_output,
            }
            local_count = len(records)
            for mode, output in outputs.items():
                losses = compute_multitask_loss(output, overlays)
                if not all(torch.isfinite(value).item() for value in losses.values()):
                    raise JunctionPredictionError(
                        f"T022 {mode} validation loss became non-finite"
                    )
                _accumulate_losses(totals[mode], losses, local_count)
                _accumulate_losses(
                    source_totals[source][mode],
                    losses,
                    local_count,
                )
            if not torch.equal(teacher_output.conditioned_step1_indices, step1):
                raise JunctionPredictionError("T022 teacher Step1 condition changed")
            if not torch.equal(teacher_output.conditioned_surface_mode_indices, surface):
                raise JunctionPredictionError("T022 teacher Surface condition changed")
            mismatch_counts["full_free_step1"] += int(
                (full_free_output.conditioned_step1_indices != step1).sum().cpu()
            )
            mismatch_counts["surface_free_with_teacher_step1"] += int(
                (
                    surface_free_output.conditioned_surface_mode_indices
                    != surface
                ).sum().cpu()
            )
            mismatch_counts["full_free_surface"] += int(
                (
                    full_free_output.conditioned_surface_mode_indices
                    != surface
                ).sum().cpu()
            )
            sample_count += local_count
            batch_count += 1
            source_counts[source] += local_count
            source_batches[source] += 1
    if sample_count != EXPECTED_SPLIT_COUNTS["validation"]:
        raise JunctionPredictionError("T022 validation epoch coverage changed")
    normalized = {
        mode: _normalize_losses(
            totals[mode],
            sample_count=sample_count,
            batch_count=batch_count,
        )
        for mode in modes
    }
    normalized_sources = {
        source: {
            mode: _normalize_losses(
                by_mode[mode],
                sample_count=source_counts[source],
                batch_count=source_batches[source],
            )
            for mode in modes
        }
        for source, by_mode in sorted(source_totals.items())
    }
    return {
        **normalized,
        "source": normalized_sources,
        "condition_mismatch_counts": dict(sorted(mismatch_counts.items())),
        "condition_mismatch_rates": {
            key: value / sample_count
            for key, value in sorted(mismatch_counts.items())
        },
        "stage_diagnostics": _stage_diagnostics(
            normalized["teacher"],
            normalized["step1_teacher_surface_free"],
            normalized["full_free"],
        ),
    }


def _load_t021_checkpoint(path: Path) -> Mapping[str, Any]:
    value = torch.load(Path(path), map_location="cpu", weights_only=False)
    if not isinstance(value, Mapping):
        raise JunctionPredictionError("T021 checkpoint must contain a mapping")
    return value


def preflight_t022_training(config: T022TrainingConfig) -> Mapping[str, Any]:
    config.validate()
    cache = _read_json(Path(config.cache_root) / "manifest.json")
    t021_summary = _read_json(config.t021_summary)
    checkpoint_hash = _sha256_file(config.t021_checkpoint)
    summary_hash = _sha256_file(config.t021_summary)
    if checkpoint_hash != config.expected_t021_checkpoint_sha256.strip().lower():
        raise JunctionPredictionError("T021 checkpoint SHA256 changed")
    if summary_hash != config.expected_t021_summary_sha256.strip().lower():
        raise JunctionPredictionError("T021 summary SHA256 changed")
    if cache.get("status") != "T021_NON_BLIND_CACHE_READY":
        raise JunctionPredictionError("T022 requires the frozen T021 non-blind cache")
    if cache.get("candidate_catalog_mode") != "T021_TEACHER_ORACLE_ONLY":
        raise JunctionPredictionError("T022 candidate catalog mode changed")
    if t021_summary.get("status") != "T021_TRAINING_COMPLETE_AWAITING_T022_DECISION":
        raise JunctionPredictionError("T021 summary does not authorize T022 initialization")
    if int(t021_summary.get("blind_test_access_count", -1)) != 0 or bool(
        t021_summary.get("blind_test_labels_read")
    ):
        raise JunctionPredictionError("T021 initialization violated blind isolation")
    if bool(t021_summary.get("formal_free_run_evaluation_executed")):
        raise JunctionPredictionError("T021 unexpectedly executed formal free-run")
    checkpoint = _load_t021_checkpoint(config.t021_checkpoint)
    if checkpoint.get("schema_version") != "p05-junction-graphset-v1-t021-checkpoint-v1":
        raise JunctionPredictionError("T021 checkpoint schema changed")
    if checkpoint.get("checkpoint_scope") != "T021_TEACHER_FORCED_COMPONENT_ONLY":
        raise JunctionPredictionError("T021 checkpoint scope changed")
    if bool(checkpoint.get("formal_release_eligible")):
        raise JunctionPredictionError("T021 checkpoint cannot be release eligible")
    if int(checkpoint.get("epoch", -1)) != int(t021_summary.get("best_epoch", -2)):
        raise JunctionPredictionError("T021 checkpoint/summary best epoch differs")
    checkpoint_config = checkpoint.get("config")
    if not isinstance(checkpoint_config, Mapping):
        raise JunctionPredictionError("T021 checkpoint config is missing")
    if int(checkpoint_config.get("seed", -1)) != config.seed or int(
        checkpoint_config.get("hidden_dim", -1)
    ) != config.hidden_dim:
        raise JunctionPredictionError("T022 seed/hidden_dim differs from T021")
    device = _select_device(config.device)
    return {
        "schema_version": "p05-junction-graphset-v1-t022-preflight-v1",
        "status": "T022_SCHEDULED_SAMPLING_CONFIG_READY",
        "training_executed": False,
        "optimizer_created": False,
        "backward_executed": False,
        "blind_test_access_count": 0,
        "blind_test_labels_read": False,
        "candidate_catalog_mode": "T021_TEACHER_ORACLE_ONLY",
        "formal_free_run_evaluation_executed": False,
        "selection_metric": "validation_full_free_total",
        "optimizer_initialization": "FRESH_ADAMW_FROM_FIXED_T021_MODEL",
        "t021_best_epoch": int(t021_summary["best_epoch"]),
        "t021_checkpoint_sha256": checkpoint_hash,
        "t021_summary_sha256": summary_hash,
        "split_counts": cache["split_counts"],
        "source_counts": cache["source_counts"],
        "device": device.type,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else ""
        ),
        "teacher_forcing_schedule": [
            {
                "epoch": epoch,
                "ratio": teacher_forcing_ratio(epoch, config.full_free_epoch),
            }
            for epoch in range(1, config.maximum_epochs + 1)
        ],
        "config": {
            **asdict(config),
            "cache_root": str(config.cache_root),
            "t021_output_dir": str(config.t021_output_dir),
            "output_dir": str(config.output_dir),
        },
    }


def _save_checkpoint(
    path: Path,
    *,
    model: JunctionGraphSetModel,
    optimizer: torch.optim.Optimizer,
    config: T022TrainingConfig,
    epoch: int,
    teacher_ratio: float,
    validation_full_free_total: float,
) -> None:
    torch.save(
        {
            "schema_version": "p05-junction-graphset-v1-t022-checkpoint-v1",
            "checkpoint_scope": "T022_SCHEDULED_SAMPLING_COMPONENT_ONLY",
            "formal_release_eligible": False,
            "epoch": epoch,
            "teacher_forcing_ratio": teacher_ratio,
            "validation_full_free_total": validation_full_free_total,
            "t021_checkpoint_sha256": config.expected_t021_checkpoint_sha256.lower(),
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "config": asdict(config),
        },
        Path(path),
    )


def run_t022_training(config: T022TrainingConfig) -> Mapping[str, Any]:
    """Run the authorized fixed T022 schedule without blind/canary access."""

    preflight = preflight_t022_training(config)
    output_dir = Path(config.output_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "preflight.json", preflight)
    device = _select_device(config.device)
    torch.manual_seed(config.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(config.seed)
        torch.cuda.reset_peak_memory_stats(device)
    checkpoint = _load_t021_checkpoint(config.t021_checkpoint)
    model = JunctionGraphSetModel(hidden_dim=config.hidden_dim).to(device=device)
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    started = time.perf_counter()
    baseline = _run_validation_diagnostics(
        model,
        config,
        epoch=0,
        device=device,
    )
    best_validation = float(baseline["full_free"]["total"])
    best_epoch = 0
    best_diagnostics: Mapping[str, Any] = baseline
    _save_checkpoint(
        output_dir / "best-checkpoint.pt",
        model=model,
        optimizer=optimizer,
        config=config,
        epoch=0,
        teacher_ratio=1.0,
        validation_full_free_total=best_validation,
    )
    history: list[Mapping[str, Any]] = []
    full_free_stale_epochs = 0
    _write_json(output_dir / "history.json", {"baseline": baseline, "epochs": history})
    for epoch in range(1, config.maximum_epochs + 1):
        train = _run_scheduled_epoch(
            model,
            config,
            epoch=epoch,
            device=device,
            optimizer=optimizer,
        )
        validation = _run_validation_diagnostics(
            model,
            config,
            epoch=epoch,
            device=device,
        )
        ratio = teacher_forcing_ratio(epoch, config.full_free_epoch)
        validation_total = float(validation["full_free"]["total"])
        improved = (
            validation_total
            < best_validation - config.minimum_validation_improvement
        )
        if improved:
            best_validation = validation_total
            best_epoch = epoch
            best_diagnostics = validation
            full_free_stale_epochs = 0
            _save_checkpoint(
                output_dir / "best-checkpoint.pt",
                model=model,
                optimizer=optimizer,
                config=config,
                epoch=epoch,
                teacher_ratio=ratio,
                validation_full_free_total=validation_total,
            )
        elif ratio == 0.0:
            full_free_stale_epochs += 1
        row = {
            "epoch": epoch,
            "teacher_forcing_ratio": ratio,
            "train_scheduled": train,
            "validation": validation,
            "selection_metric": validation_total,
            "improved_best": improved,
            "full_free_stale_epochs": full_free_stale_epochs,
        }
        history.append(row)
        _write_json(
            output_dir / "history.json",
            {"baseline": baseline, "epochs": history},
        )
        if (
            ratio == 0.0
            and full_free_stale_epochs >= config.early_stopping_patience
        ):
            break
    summary = {
        "schema_version": "p05-junction-graphset-v1-t022-training-v1",
        "status": "T022_SCHEDULED_SAMPLING_COMPLETE_AWAITING_T024_AUDIT",
        "training_executed": True,
        "optimizer_created": True,
        "backward_executed": True,
        "blind_test_access_count": 0,
        "blind_test_labels_read": False,
        "candidate_catalog_mode": "T021_TEACHER_ORACLE_ONLY",
        "formal_free_run_evaluation_executed": False,
        "formal_release_eligible": False,
        "selection_metric": "validation_full_free_total",
        "completed_epochs": len(history),
        "best_epoch": best_epoch,
        "baseline_validation_teacher_total": float(baseline["teacher"]["total"]),
        "baseline_validation_full_free_total": float(
            baseline["full_free"]["total"]
        ),
        "best_validation_teacher_total": float(
            best_diagnostics["teacher"]["total"]
        ),
        "best_validation_full_free_total": best_validation,
        "best_teacher_to_free_gap": best_validation
        - float(best_diagnostics["teacher"]["total"]),
        "best_condition_mismatch_counts": best_diagnostics[
            "condition_mismatch_counts"
        ],
        "best_condition_mismatch_rates": best_diagnostics[
            "condition_mismatch_rates"
        ],
        "best_stage_diagnostics": best_diagnostics["stage_diagnostics"],
        "best_source_diagnostics": best_diagnostics["source"],
        "model_parameter_count": model.parameter_count,
        "device": device.type,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else ""
        ),
        "peak_cuda_memory_bytes": (
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
        ),
        "elapsed_seconds": time.perf_counter() - started,
        "t021_checkpoint_sha256": preflight["t021_checkpoint_sha256"],
        "t021_summary_sha256": preflight["t021_summary_sha256"],
        "next_step": "RUN_T024_REGRESSION_AND_DETERMINISM_AUDIT",
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


__all__ = [
    "T022TrainingConfig",
    "deterministic_teacher_masks",
    "preflight_t022_training",
    "run_t022_training",
    "teacher_forcing_ratio",
]
