from __future__ import annotations

import json
import math
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
    compute_multitask_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    JunctionEvidenceExample,
    JunctionPredictionError,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t021_data import (
    EXPECTED_SPLIT_COUNTS,
    T021JoinedRecord,
    load_t021_shard,
)


@dataclass(frozen=True)
class T021TrainingConfig:
    cache_root: Path
    output_dir: Path
    seed: int = 20_260_821
    hidden_dim: int = 384
    learning_rate: float = 3.0e-4
    weight_decay: float = 1.0e-4
    maximum_epochs: int = 24
    early_stopping_patience: int = 4
    minimum_validation_improvement: float = 1.0e-4
    maximum_records_per_batch: int = 8
    maximum_geometry_tokens_per_batch: int = 12_000
    gradient_clip_norm: float = 1.0
    device: str = "auto"

    def validate(self) -> None:
        manifest = Path(self.cache_root) / "manifest.json"
        readiness = Path(self.cache_root) / "readiness-summary.json"
        if not manifest.is_file() or not readiness.is_file():
            raise FileNotFoundError("T021 cache and readiness summary are both required")
        if self.hidden_dim < 1 or self.maximum_epochs < 1:
            raise ValueError("T021 model dimensions/epochs must be positive")
        if self.early_stopping_patience < 1:
            raise ValueError("T021 early-stopping patience must be positive")
        if self.maximum_records_per_batch < 1:
            raise ValueError("T021 maximum_records_per_batch must be positive")
        if self.maximum_geometry_tokens_per_batch < 1:
            raise ValueError("T021 token budget must be positive")
        for name, value in (
            ("learning_rate", self.learning_rate),
            ("weight_decay", self.weight_decay),
            ("minimum_validation_improvement", self.minimum_validation_improvement),
            ("gradient_clip_norm", self.gradient_clip_norm),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"T021 {name} must be finite and non-negative")
        if self.learning_rate == 0.0 or self.gradient_clip_norm == 0.0:
            raise ValueError("T021 learning rate and gradient clip must be positive")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("T021 device must be auto, cpu, or cuda")


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise JunctionPredictionError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _select_device(requested: str) -> torch.device:
    if requested == "cpu":
        return torch.device("cpu")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise JunctionPredictionError("T021 training requested CUDA but it is absent")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def pack_record_indices(
    geometry_token_counts: Sequence[int],
    *,
    maximum_records: int,
    maximum_tokens: int,
) -> tuple[tuple[int, ...], ...]:
    if maximum_records < 1 or maximum_tokens < 1:
        raise ValueError("T021 batch budgets must be positive")
    batches: list[tuple[int, ...]] = []
    current: list[int] = []
    current_tokens = 0
    for index, value in enumerate(geometry_token_counts):
        token_count = int(value)
        if token_count < 0:
            raise ValueError("T021 token count cannot be negative")
        if current and (
            len(current) >= maximum_records
            or current_tokens + token_count > maximum_tokens
        ):
            batches.append(tuple(current))
            current = []
            current_tokens = 0
        current.append(index)
        current_tokens += token_count
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def iter_t021_batches(
    cache_root: Path,
    *,
    split: str,
    maximum_records: int,
    maximum_tokens: int,
    seed: int,
    epoch: int,
    shuffle: bool,
) -> Iterator[tuple[T021JoinedRecord, ...]]:
    if split not in {"train", "validation"}:
        raise ValueError("T021 split must be train or validation")
    manifest = _read_json(Path(cache_root) / "manifest.json")
    shards = [
        shard for shard in manifest["shards"] if str(shard.get("split")) == split
    ]
    if not shards:
        raise JunctionPredictionError(f"T021 cache has no {split} shards")
    generator = random.Random(seed + epoch * 1_000_003)
    if shuffle:
        generator.shuffle(shards)
    for shard in shards:
        records = [
            record
            for record in load_t021_shard(cache_root, shard)
            if record.label.split == split
        ]
        if shuffle:
            generator.shuffle(records)
        token_counts = tuple(
            int(record.feature.example.geometry_tokens.shape[0]) for record in records
        )
        for indices in pack_record_indices(
            token_counts,
            maximum_records=maximum_records,
            maximum_tokens=maximum_tokens,
        ):
            yield tuple(records[index] for index in indices)


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


def _forward_batch(
    model: JunctionGraphSetModel,
    records: Sequence[T021JoinedRecord],
    *,
    device: torch.device,
    teacher_conditioned: bool,
) -> Mapping[str, torch.Tensor]:
    examples = tuple(
        _move_example(record.teacher_example, device) for record in records
    )
    overlays = tuple(record.label.overlay for record in records)
    step1 = (
        torch.tensor(
            tuple(record.label.teacher_step1_index for record in records),
            dtype=torch.long,
            device=device,
        )
        if teacher_conditioned
        else None
    )
    surface = (
        torch.tensor(
            tuple(record.label.teacher_surface_index for record in records),
            dtype=torch.long,
            device=device,
        )
        if teacher_conditioned
        else None
    )
    output = model(
        examples,
        step1_state_indices=step1,
        surface_mode_indices=surface,
    )
    return compute_multitask_loss(output, overlays)


def _run_epoch(
    model: JunctionGraphSetModel,
    config: T021TrainingConfig,
    *,
    split: str,
    epoch: int,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None,
    teacher_conditioned: bool,
) -> Mapping[str, float]:
    training = optimizer is not None
    model.train(training)
    totals: defaultdict[str, float] = defaultdict(float)
    sample_count = 0
    batch_count = 0
    batches = iter_t021_batches(
        config.cache_root,
        split=split,
        maximum_records=config.maximum_records_per_batch,
        maximum_tokens=config.maximum_geometry_tokens_per_batch,
        seed=config.seed,
        epoch=epoch,
        shuffle=training,
    )
    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for records in batches:
            if not records:
                continue
            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)
            losses = _forward_batch(
                model,
                records,
                device=device,
                teacher_conditioned=teacher_conditioned,
            )
            if not all(torch.isfinite(value).item() for value in losses.values()):
                raise JunctionPredictionError("T021 training loss became non-finite")
            if optimizer is not None:
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
    expected = EXPECTED_SPLIT_COUNTS[split]
    if sample_count != expected:
        raise JunctionPredictionError(
            f"T021 {split} epoch saw {sample_count} records instead of {expected}"
        )
    return {
        **{key: value / sample_count for key, value in sorted(totals.items())},
        "sample_count": float(sample_count),
        "batch_count": float(batch_count),
    }


def _run_validation_pair(
    model: JunctionGraphSetModel,
    config: T021TrainingConfig,
    *,
    epoch: int,
    device: torch.device,
) -> tuple[Mapping[str, float], Mapping[str, float]]:
    model.eval()
    teacher_totals: defaultdict[str, float] = defaultdict(float)
    free_totals: defaultdict[str, float] = defaultdict(float)
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
            teacher_losses = _forward_batch(
                model,
                records,
                device=device,
                teacher_conditioned=True,
            )
            free_losses = _forward_batch(
                model,
                records,
                device=device,
                teacher_conditioned=False,
            )
            if not all(
                torch.isfinite(value).item()
                for value in (*teacher_losses.values(), *free_losses.values())
            ):
                raise JunctionPredictionError(
                    "T021 validation loss became non-finite"
                )
            local_count = len(records)
            for key, value in teacher_losses.items():
                teacher_totals[key] += float(value.detach().cpu()) * local_count
            for key, value in free_losses.items():
                free_totals[key] += float(value.detach().cpu()) * local_count
            sample_count += local_count
            batch_count += 1
    if sample_count != EXPECTED_SPLIT_COUNTS["validation"]:
        raise JunctionPredictionError("T021 validation epoch coverage changed")

    def normalized(values: Mapping[str, float]) -> Mapping[str, float]:
        return {
            **{key: value / sample_count for key, value in sorted(values.items())},
            "sample_count": float(sample_count),
            "batch_count": float(batch_count),
        }

    return normalized(teacher_totals), normalized(free_totals)


def preflight_t021_training(config: T021TrainingConfig) -> Mapping[str, Any]:
    config.validate()
    cache = _read_json(Path(config.cache_root) / "manifest.json")
    readiness = _read_json(Path(config.cache_root) / "readiness-summary.json")
    if cache.get("status") != "T021_NON_BLIND_CACHE_READY" or readiness.get(
        "status"
    ) != "T021_READY_FOR_TRAINING_AUTHORIZATION":
        raise JunctionPredictionError("T021 cache/readiness status does not authorize setup")
    if bool(cache.get("training_executed")) or bool(readiness.get("training_executed")):
        raise JunctionPredictionError("T021 preflight source is not training-free")
    device = _select_device(config.device)
    return {
        "status": "T021_TRAINING_CONFIG_READY",
        "training_executed": False,
        "optimizer_created": False,
        "backward_executed": False,
        "sample_count": cache["sample_count"],
        "split_counts": cache["split_counts"],
        "source_counts": cache["source_counts"],
        "candidate_catalog_mode": cache["candidate_catalog_mode"],
        "formal_free_run_evaluation": False,
        "device": device.type,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else ""
        ),
        "config": {
            **asdict(config),
            "cache_root": str(config.cache_root),
            "output_dir": str(config.output_dir),
        },
    }


def run_t021_training(config: T021TrainingConfig) -> Mapping[str, Any]:
    """Run the authorized P1 teacher-forced fit; never call this as readiness."""

    preflight = preflight_t021_training(config)
    output_dir = Path(config.output_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    device = _select_device(config.device)
    torch.manual_seed(config.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(config.seed)
        torch.cuda.reset_peak_memory_stats(device)
    model = JunctionGraphSetModel(hidden_dim=config.hidden_dim).to(device=device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history: list[Mapping[str, Any]] = []
    best_validation = math.inf
    best_epoch = 0
    stale_epochs = 0
    started = time.perf_counter()
    for epoch in range(1, config.maximum_epochs + 1):
        train_losses = _run_epoch(
            model,
            config,
            split="train",
            epoch=epoch,
            device=device,
            optimizer=optimizer,
            teacher_conditioned=True,
        )
        validation_teacher, validation_free_condition = _run_validation_pair(
            model,
            config,
            epoch=epoch,
            device=device,
        )
        row = {
            "epoch": epoch,
            "train_teacher": train_losses,
            "validation_teacher": validation_teacher,
            "validation_free_condition_diagnostic": validation_free_condition,
        }
        history.append(row)
        validation_total = validation_teacher["total"]
        if validation_total < best_validation - config.minimum_validation_improvement:
            best_validation = validation_total
            best_epoch = epoch
            stale_epochs = 0
            torch.save(
                {
                    "schema_version": "p05-junction-graphset-v1-t021-checkpoint-v1",
                    "checkpoint_scope": "T021_TEACHER_FORCED_COMPONENT_ONLY",
                    "formal_release_eligible": False,
                    "epoch": epoch,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "config": asdict(config),
                },
                output_dir / "best-checkpoint.pt",
            )
        else:
            stale_epochs += 1
        _write_json(output_dir / "history.json", {"epochs": history})
        if stale_epochs >= config.early_stopping_patience:
            break
    summary = {
        "schema_version": "p05-junction-graphset-v1-t021-training-v1",
        "status": "T021_TRAINING_COMPLETE_AWAITING_T022_DECISION",
        "training_executed": True,
        "optimizer_created": True,
        "backward_executed": True,
        "blind_test_access_count": 0,
        "blind_test_labels_read": False,
        "candidate_catalog_mode": "T021_TEACHER_ORACLE_ONLY",
        "formal_free_run_evaluation_executed": False,
        "preflight": preflight,
        "completed_epochs": len(history),
        "best_epoch": best_epoch,
        "best_validation_teacher_total": best_validation,
        "model_parameter_count": model.parameter_count,
        "device": device.type,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else ""
        ),
        "peak_cuda_memory_bytes": (
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
        ),
        "elapsed_seconds": time.perf_counter() - started,
        "next_step_authorized": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary

__all__ = [
    "T021TrainingConfig",
    "iter_t021_batches",
    "pack_record_indices",
    "preflight_t021_training",
    "run_t021_training",
]
