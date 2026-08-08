from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_firewall import (
    EvidenceStage,
    STEP1_ALLOWED_ROLES,
    StageFirewall,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
    JunctionGraphSetRawOutput,
    compute_multitask_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorState,
    JunctionEvidenceExample,
    JunctionPredictionError,
    SurfaceMode,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t021_data import (
    EXPECTED_DEVELOPMENT_COUNT,
    EXPECTED_SOURCE_COUNTS,
    EXPECTED_SPLIT_COUNTS,
    T021JoinedRecord,
    iter_t021_cache,
)


@dataclass(frozen=True)
class T021ReadinessConfig:
    cache_root: Path
    summary_path: Path
    hidden_dim: int = 64
    probe_record_limit: int = 16
    seed: int = 20_260_808
    device: str = "auto"

    def validate(self) -> None:
        if self.hidden_dim < 1 or self.probe_record_limit < 1:
            raise ValueError("T021 readiness dimensions must be positive")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("T021 readiness device must be auto, cpu, or cuda")
        if not (Path(self.cache_root) / "manifest.json").is_file():
            raise FileNotFoundError(Path(self.cache_root) / "manifest.json")


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
            raise JunctionPredictionError("T021 readiness requested CUDA but it is absent")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


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


def _tensor_digest(tensor: torch.Tensor) -> bytes:
    return tensor.detach().cpu().contiguous().numpy().tobytes()


def _output_tensors(output: JunctionGraphSetRawOutput) -> tuple[torch.Tensor, ...]:
    return (
        output.step1_logits,
        output.surface.mode_logits,
        output.surface.existing_object_logits,
        output.surface.virtual_member_logits,
        output.surface.virtual_cardinality_logits,
        output.anchor_state_logits,
        output.quality_logits,
        output.anchor_member_logits,
        output.anchor_member_cardinality_logits,
        output.main_anchor_logits,
        output.node_equivalence.logits,
        output.road_break.presence_logits,
        output.road_break.fractions,
        output.road_break.count_logits,
        output.road_break.fraction_slots,
        output.complete_plan.logits,
    )


def _output_digest(output: JunctionGraphSetRawOutput) -> str:
    digest = hashlib.sha256()
    for tensor in _output_tensors(output):
        digest.update(_tensor_digest(tensor))
    for values in (
        output.junction_keys,
        output.complete_plan.plan_ids,
        tuple(ref.key for ref in output.surface.existing_object_refs),
        tuple(ref.key for ref in output.surface.virtual_member_refs),
        tuple(ref.key for ref in output.anchor_member_refs),
    ):
        digest.update(json.dumps(values, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def _maximum_output_difference(
    first: JunctionGraphSetRawOutput,
    second: JunctionGraphSetRawOutput,
) -> float:
    differences = [
        float((left - right).abs().max().detach().cpu())
        for left, right in zip(_output_tensors(first), _output_tensors(second))
        if left.numel()
    ]
    return max(differences, default=0.0)


def _probe_predicates() -> Mapping[str, Callable[[T021JoinedRecord], bool]]:
    return {
        "strong_train": lambda row: row.label.source == "STRONG_GOLD"
        and row.label.split == "train",
        "strong_validation": lambda row: row.label.source == "STRONG_GOLD"
        and row.label.split == "validation",
        "t10_train": lambda row: row.label.source == "T10_WEAK"
        and row.label.split == "train",
        "t10_validation": lambda row: row.label.source == "T10_WEAK"
        and row.label.split == "validation",
        "existing_surface": lambda row: bool(
            row.label.overlay.existing_surface_constraints
        ),
        "virtual_surface_unknown_range": lambda row: len(
            row.label.overlay.virtual_surface_acceptable_cardinalities
        )
        > 1,
        "virtual_surface_fixed": lambda row: len(
            row.label.overlay.virtual_surface_acceptable_cardinalities
        )
        == 1,
        "anchor_object_set": lambda row: bool(
            row.label.overlay.anchor_member_acceptable_cardinalities
        ),
        "node_equivalence": lambda row: bool(row.label.overlay.pair_constraints),
        "road_break": lambda row: any(
            target.fractions for target in row.label.overlay.road_break_set_targets
        ),
        "masked_complete_plan": lambda row: not row.label.complete_plan_supervised,
        "legacy_multi_candidate": lambda row: (
            row.label.legacy_candidate_acceptable_count > 1
        ),
        "no_evidence": lambda row: row.label.overlay.anchor_state_acceptable_indices
        == (tuple(AnchorState).index(AnchorState.NO_RCSD_EVIDENCE),),
        "quality_issue": lambda row: row.label.overlay.anchor_state_acceptable_indices
        == (tuple(AnchorState).index(AnchorState.QUALITY_ISSUE),),
    }


def _update_probe_candidates(
    record: T021JoinedRecord,
    selected: dict[str, T021JoinedRecord],
) -> None:
    token_count = int(record.feature.example.geometry_tokens.shape[0])
    for name, predicate in _probe_predicates().items():
        if not predicate(record):
            continue
        current = selected.get(name)
        if current is None or token_count < int(
            current.feature.example.geometry_tokens.shape[0]
        ):
            selected[name] = record


def _unique_probe_records(
    selected: Mapping[str, T021JoinedRecord],
    limit: int,
) -> tuple[T021JoinedRecord, ...]:
    by_id: dict[str, T021JoinedRecord] = {}
    for name in _probe_predicates():
        record = selected.get(name)
        if record is not None:
            by_id.setdefault(record.feature.sample_id, record)
    normalized = tuple(
        sorted(
            by_id.values(),
            key=lambda row: (
                int(row.feature.example.geometry_tokens.shape[0]),
                row.feature.sample_id,
            ),
        )
    )
    return normalized[:limit]


def _validate_cache(
    cache_root: Path,
) -> tuple[Mapping[str, Any], tuple[T021JoinedRecord, ...]]:
    manifest = _read_json(Path(cache_root) / "manifest.json")
    if manifest.get("status") != "T021_NON_BLIND_CACHE_READY":
        raise JunctionPredictionError("T021 cache is not ready")
    if bool(manifest.get("training_executed")) or bool(
        manifest.get("blind_test_labels_read")
    ):
        raise JunctionPredictionError("T021 cache isolation status changed")

    counters: Counter[str] = Counter()
    sample_ids: set[str] = set()
    junction_keys: set[str] = set()
    train_cases: set[str] = set()
    validation_cases: set[str] = set()
    probe_candidates: dict[str, T021JoinedRecord] = {}
    firewall = StageFirewall()
    identity_digest = hashlib.sha256()
    for record in iter_t021_cache(cache_root):
        feature = record.feature
        label = record.label
        if feature.sample_id in sample_ids or feature.example.junction_key in junction_keys:
            raise JunctionPredictionError("T021 cache identity is duplicated")
        sample_ids.add(feature.sample_id)
        junction_keys.add(feature.example.junction_key)
        identity_digest.update(f"{feature.sample_id}\n".encode("utf-8"))
        feature.example.validate()
        if tuple(plan.plan_id for plan in feature.example.candidate_binding.plans) != (
            "safe:abstain",
        ):
            raise JunctionPredictionError("T021 feature shard contains teacher truth")
        if label.overlay.junction_key != feature.example.junction_key:
            raise JunctionPredictionError("T021 cache overlay identity differs")
        if label.overlay.source_weight != (
            1.0 if label.source == "STRONG_GOLD" else 0.7
        ):
            raise JunctionPredictionError("T021 cache source weight changed")
        if label.complete_plan_supervised != bool(
            label.overlay.acceptable_complete_plan_ids
        ):
            raise JunctionPredictionError("T021 complete-plan mask differs")
        if label.complete_plan_supervised:
            label.teacher_candidate_binding.plan("gold")
        step1_view = firewall.build_view(feature.example, EvidenceStage.STEP1)
        if any(role not in STEP1_ALLOWED_ROLES for role in step1_view.object_roles):
            raise JunctionPredictionError("T021 Step1 physical firewall failed")
        counters["sample_count"] += 1
        counters[f"source:{label.source}"] += 1
        counters[f"split:{label.split}"] += 1
        counters["step1_view_count"] += 1
        counters["step1_forbidden_role_count"] += sum(
            role not in STEP1_ALLOWED_ROLES for role in step1_view.object_roles
        )
        cases = train_cases if label.split == "train" else validation_cases
        cases.add(label.case_group_key)
        _update_probe_candidates(record, probe_candidates)

    if counters["sample_count"] != EXPECTED_DEVELOPMENT_COUNT:
        raise JunctionPredictionError("T021 readiness sample count changed")
    if {
        source: counters[f"source:{source}"] for source in EXPECTED_SOURCE_COUNTS
    } != EXPECTED_SOURCE_COUNTS:
        raise JunctionPredictionError("T021 readiness source counts changed")
    if {
        split: counters[f"split:{split}"] for split in EXPECTED_SPLIT_COUNTS
    } != EXPECTED_SPLIT_COUNTS:
        raise JunctionPredictionError("T021 readiness split counts changed")
    if train_cases.intersection(validation_cases):
        raise JunctionPredictionError("T021 readiness Case-disjoint split failed")
    missing_probe = sorted(set(_probe_predicates()) - set(probe_candidates))
    if missing_probe:
        raise JunctionPredictionError(f"T021 readiness probe gaps: {missing_probe}")
    return (
        {
            "sample_count": counters["sample_count"],
            "source_counts": {
                source: counters[f"source:{source}"]
                for source in EXPECTED_SOURCE_COUNTS
            },
            "split_counts": {
                split: counters[f"split:{split}"] for split in EXPECTED_SPLIT_COUNTS
            },
            "train_case_group_count": len(train_cases),
            "validation_case_group_count": len(validation_cases),
            "case_group_overlap_count": 0,
            "step1_view_count": counters["step1_view_count"],
            "step1_forbidden_role_count": counters[
                "step1_forbidden_role_count"
            ],
            "identity_scan_sha256": identity_digest.hexdigest(),
            "probe_criteria": sorted(probe_candidates),
        },
        _unique_probe_records(probe_candidates, 16),
    )


def _run_probe(
    records: Sequence[T021JoinedRecord],
    *,
    hidden_dim: int,
    seed: int,
    device: torch.device,
) -> Mapping[str, Any]:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats(device)
    model = JunctionGraphSetModel(hidden_dim=hidden_dim, dropout=0.0).to(device=device)
    model.eval()
    teacher_examples = tuple(
        _move_example(record.teacher_example, device) for record in records
    )
    free_examples = tuple(
        _move_example(record.feature.example, device) for record in records
    )
    overlays = tuple(record.label.overlay for record in records)
    teacher_step1 = torch.tensor(
        tuple(record.label.teacher_step1_index for record in records),
        dtype=torch.long,
        device=device,
    )
    teacher_surface = torch.tensor(
        tuple(record.label.teacher_surface_index for record in records),
        dtype=torch.long,
        device=device,
    )
    with torch.no_grad():
        teacher_first = model(
            teacher_examples,
            step1_state_indices=teacher_step1,
            surface_mode_indices=teacher_surface,
        )
        teacher_losses = compute_multitask_loss(teacher_first, overlays)
        teacher_second = model(
            teacher_examples,
            step1_state_indices=teacher_step1,
            surface_mode_indices=teacher_surface,
        )
        free_output = model(free_examples)
    first_digest = _output_digest(teacher_first)
    second_digest = _output_digest(teacher_second)
    maximum_difference = _maximum_output_difference(teacher_first, teacher_second)
    if maximum_difference > 1.0e-6:
        raise JunctionPredictionError(
            "T021 readiness teacher forward exceeds numeric repeatability tolerance"
        )
    if not all(torch.isfinite(value).item() for value in teacher_losses.values()):
        raise JunctionPredictionError("T021 readiness loss contains a non-finite value")
    if set(free_output.complete_plan.plan_ids) != {"safe:abstain"}:
        raise JunctionPredictionError("T021 free-run probe contains teacher candidates")
    return {
        "record_count": len(records),
        "sample_ids": [record.feature.sample_id for record in records],
        "geometry_token_count": sum(
            int(record.feature.example.geometry_tokens.shape[0]) for record in records
        ),
        "teacher_output_sha256": first_digest,
        "teacher_repeat_output_sha256": second_digest,
        "double_forward_max_abs_difference": maximum_difference,
        "numeric_repeatability_tolerance": 1.0e-6,
        "deterministic_double_forward": maximum_difference == 0.0,
        "numerically_repeatable_double_forward": True,
        "teacher_losses": {
            key: float(value.detach().cpu()) for key, value in teacher_losses.items()
        },
        "all_losses_finite": True,
        "free_run_candidate_plan_ids": sorted(set(free_output.complete_plan.plan_ids)),
        "feature_candidate_truth_leakage_count": 0,
        "model_parameter_count": model.parameter_count,
        "encoder_parameter_count": model.encoder.parameter_count,
        "peak_cuda_memory_bytes": (
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
        ),
        "optimizer_created": False,
        "backward_executed": False,
    }


def run_t021_readiness(config: T021ReadinessConfig) -> Mapping[str, Any]:
    """Validate the complete non-blind P1 chain without any parameter update."""

    config.validate()
    started = time.perf_counter()
    cache_manifest = _read_json(Path(config.cache_root) / "manifest.json")
    cache_audit, probe_records = _validate_cache(config.cache_root)
    if len(probe_records) > config.probe_record_limit:
        probe_records = probe_records[: config.probe_record_limit]
    device = _select_device(config.device)
    probe = _run_probe(
        probe_records,
        hidden_dim=config.hidden_dim,
        seed=config.seed,
        device=device,
    )
    summary = {
        "schema_version": "p05-junction-graphset-v1-t021-readiness-v1",
        "status": "T021_READY_FOR_TRAINING_AUTHORIZATION",
        "task": "T021_P1_FULL_NON_BLIND_TEACHER_FORCING_READINESS",
        "training_executed": False,
        "optimizer_created": False,
        "backward_executed": False,
        "checkpoint_written": False,
        "canary_executed": False,
        "blind_test_access_count": 0,
        "blind_test_labels_read": False,
        "candidate_catalog_mode": "T021_TEACHER_ORACLE_ONLY",
        "candidate_catalog_inference_eligible": False,
        "formal_free_run_evaluation_executed": False,
        "cache_manifest_status": cache_manifest["status"],
        "cache_manifest_sha256": hashlib.sha256(
            (Path(config.cache_root) / "manifest.json").read_bytes()
        ).hexdigest(),
        "cache_audit": cache_audit,
        "frozen_counts": {
            "sample_count": cache_manifest["sample_count"],
            "source_counts": cache_manifest["source_counts"],
            "split_counts": cache_manifest["split_counts"],
            "strong_legacy_half_weight_normalized_count": cache_manifest[
                "strong_legacy_half_weight_normalized_count"
            ],
            "complete_plan_supervised_count": cache_manifest[
                "complete_plan_supervised_count"
            ],
            "existing_surface_supervised_count": cache_manifest[
                "existing_surface_supervised_count"
            ],
            "virtual_surface_supervised_count": cache_manifest[
                "virtual_surface_supervised_count"
            ],
            "anchor_object_set_supervised_count": cache_manifest[
                "anchor_object_set_supervised_count"
            ],
            "legacy_multi_candidate_label_count": cache_manifest[
                "legacy_multi_candidate_label_count"
            ],
        },
        "io_contract": {
            "raw_gis_reopened": False,
            "feature_label_physical_separation": cache_manifest[
                "feature_label_physical_separation"
            ],
            "source_store_read_policy": cache_manifest["source_store_read_policy"],
            "source_file_read_counts": cache_manifest["source_file_read_counts"],
            "cache_shard_count": len(cache_manifest["shards"]),
            "cache_feature_bytes": sum(
                int(row["feature_size_bytes"]) for row in cache_manifest["shards"]
            ),
            "cache_label_bytes": sum(
                int(row["label_size_bytes"]) for row in cache_manifest["shards"]
            ),
        },
        "probe": probe,
        "runtime": {
            "python_version": sys.version.split()[0],
            "torch_version": torch.__version__,
            "platform": platform.platform(),
            "device": device.type,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_name": (
                torch.cuda.get_device_name(device) if device.type == "cuda" else ""
            ),
        },
        "elapsed_seconds": time.perf_counter() - started,
        "next_step_authorized": False,
        "next_step": "AWAIT_EXPLICIT_T021_TRAINING_AUTHORIZATION",
    }
    _write_json(config.summary_path, summary)
    return summary


__all__ = ["T021ReadinessConfig", "run_t021_readiness"]
