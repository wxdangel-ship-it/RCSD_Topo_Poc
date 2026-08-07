from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, TextIO

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryAnchorRoadGraphDecoder,
    TargetAOrdinaryAnchorRoadRoleGraphDecoder,
    TargetAOrdinaryJointRoadGraphDecoder,
    TargetAOrdinaryRoadSetDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetExample,
    OrdinaryRoadSetTrainingConfig,
    score_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_ordinary_road_set_full_oof_inference(
    *,
    member_store_root: Path,
    trained_root: Path,
    output_root: Path,
    requested_device: str = "cuda",
) -> Path:
    """Score every ordinary Segment once with its Case-held-out checkpoint."""
    started = time.perf_counter()
    store = normalize_runtime_path(member_store_root).resolve(strict=True)
    trained = normalize_runtime_path(trained_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)

    label_path = store / "ordinary_road_member_labels.jsonl"
    labels = {
        _segment_key(row): row for row in _read_jsonl(label_path)
    }
    folds = sorted({int(row["fold"]) for row in labels.values()})
    models: dict[
        int,
        TargetAOrdinaryRoadSetDecoder
        | TargetAOrdinaryJointRoadGraphDecoder
        | TargetAOrdinaryAnchorRoadGraphDecoder
        | TargetAOrdinaryAnchorRoadRoleGraphDecoder,
    ] = {}
    configs: dict[int, OrdinaryRoadSetTrainingConfig] = {}
    checkpoint_records = {}
    for fold in folds:
        checkpoint_path = trained / f"fold_{fold}_checkpoint.pt"
        model, config = _load_checkpoint(checkpoint_path, device=device)
        models[fold] = model
        configs[fold] = config
        checkpoint_records[str(fold)] = _input_record(checkpoint_path)

    prediction_path = root / "ordinary_road_set_full_oof_predictions.jsonl"
    state_path = root / "ordinary_hierarchical_states.jsonl"
    feature_path = store / "ordinary_road_member_features.jsonl"
    batches: dict[int, list[OrdinaryRoadSetExample]] = {
        fold: [] for fold in folds
    }
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    with (
        feature_path.open("r", encoding="utf-8") as feature_stream,
        prediction_path.open("w", encoding="utf-8", newline="\n") as pred_stream,
        state_path.open("w", encoding="utf-8", newline="\n") as state_stream,
    ):
        for line in feature_stream:
            if not line.strip():
                continue
            feature = json.loads(line)
            key = _segment_key(feature)
            if key in seen:
                raise ValueError("ordinary full inference feature is duplicated")
            seen.add(key)
            label = labels.get(key)
            if label is None:
                raise ValueError("ordinary full inference lacks fold assignment")
            fold = int(label["fold"])
            candidates = feature.get("candidate_rows") or ()
            counts["feature"] += 1
            counts[f"fold_{fold}"] += 1
            if not candidates:
                counts["empty_candidate"] += 1
                prediction = _empty_prediction(key, fold)
                _write_row(pred_stream, prediction)
                _write_row(
                    state_stream,
                    ordinary_state_from_prediction(prediction),
                )
                counts["prediction"] += 1
                counts["state"] += 1
                counts["decision_ABSTAIN"] += 1
                continue
            batches[fold].append(
                _inference_example(
                    feature,
                    fold=fold,
                )
            )
            if len(batches[fold]) >= configs[fold].batch_size:
                _flush_batch(
                    batches[fold],
                    model=models[fold],
                    config=configs[fold],
                    device=device,
                    prediction_stream=pred_stream,
                    state_stream=state_stream,
                    counts=counts,
                )
                batches[fold].clear()
        for fold in folds:
            if batches[fold]:
                _flush_batch(
                    batches[fold],
                    model=models[fold],
                    config=configs[fold],
                    device=device,
                    prediction_stream=pred_stream,
                    state_stream=state_stream,
                    counts=counts,
                )
                batches[fold].clear()

    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ROAD_SET_FULL_STRICT_OOF_INFERENCE",
        "model_scope": (
            "one joint decoder emits KEEP_SWSD/USE_RCSD, cardinality, and the "
            "complete raw Road set for every ordinary Segment"
        ),
        "io_contract": (
            "the 228MB feature JSONL is streamed once; fold models are loaded "
            "once and batches are routed in memory without per-fold rereads"
        ),
        "fold_routing_contract": (
            "fold is evaluation routing metadata only and never enters model "
            "features; each Case uses the checkpoint that excluded that Case"
        ),
        "counts": dict(sorted(counts.items())),
        "segment_count": len(seen),
        "fold_count": len(folds),
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "inputs": {
            "features": _input_record(feature_path),
            "fold_routing": _input_record(label_path),
            "trained_summary": _input_record(trained / "summary.json"),
            "checkpoints": checkpoint_records,
        },
        "outputs": {
            "predictions": _input_record(prediction_path),
            "states": _input_record(state_path),
        },
        "feature_uses_truth": False,
        "fold_routing_enters_feature_count": 0,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "the trained diagnostic still has unsafe automatic Road sets; "
            "access, Node, AdvanceRight, and whole-graph gates remain open"
        ),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": bool(
            len(seen) == len(labels)
            and counts["prediction"] == len(seen)
            and counts["state"] == len(seen)
            and counts["forbidden_prediction_field"] == 0
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary Road-set full OOF inference gate failed")
    return root


def ordinary_state_from_prediction(
    prediction: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the in-memory state consumed by downstream P05 heads."""
    selected = [
        str(value) for value in prediction.get("selected_road_ids") or ()
    ]
    decision = str(prediction.get("predicted_decision") or "")
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": str(prediction["case_key"]),
        "segment_id": str(prediction["segment_id"]),
        "fold": int(prediction["fold"]),
        "raw_carrier_decision": decision,
        "raw_carrier_probability": float(
            prediction.get("decision_confidence") or 0.0
        ),
        "complete_road_ids": selected,
        "road_set_available": bool(selected),
        "road_set_confidence": float(
            prediction.get("confidence") or 0.0
        ),
        "hierarchical_release_ready": False,
        "access_predictions": [],
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _flush_batch(
    rows: list[OrdinaryRoadSetExample],
    *,
    model: TargetAOrdinaryRoadSetDecoder
    | TargetAOrdinaryJointRoadGraphDecoder
    | TargetAOrdinaryAnchorRoadGraphDecoder,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    prediction_stream: TextIO,
    state_stream: TextIO,
    counts: Counter[str],
) -> None:
    scored = score_ordinary_road_set_examples(
        model,
        rows,
        feature_source="oof",
        batch_size=config.batch_size,
        device=device,
    )
    for raw in scored:
        prediction = _inference_prediction(raw)
        counts["prediction"] += 1
        counts["selected_road"] += len(prediction["selected_road_ids"])
        counts[f"decision_{prediction['predicted_decision']}"] += 1
        counts["empty_selected"] += int(
            not bool(prediction["selected_road_ids"])
        )
        counts["forbidden_prediction_field"] += _forbidden_field_count(
            prediction
        )
        _write_row(prediction_stream, prediction)
        _write_row(state_stream, ordinary_state_from_prediction(prediction))
        counts["state"] += 1


def _inference_prediction(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": str(raw["case_key"]),
        "segment_id": str(raw["segment_id"]),
        "fold": int(raw["fold"]),
        "feature_source": "oof",
        "predicted_decision": str(raw["predicted_decision"]),
        "predicted_cardinality": int(raw["predicted_cardinality"]),
        "selected_road_ids": [
            str(value) for value in raw["selected_road_ids"]
        ],
        "decision_confidence": float(raw["decision_confidence"]),
        "cardinality_confidence": float(raw["cardinality_confidence"]),
        "set_margin": float(raw["set_margin"]),
        "confidence": float(raw["confidence"]),
        "candidate_count": int(raw["candidate_count"]),
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _empty_prediction(
    key: tuple[str, str],
    fold: int,
) -> dict[str, Any]:
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": key[0],
        "segment_id": key[1],
        "fold": fold,
        "feature_source": "oof",
        "predicted_decision": "ABSTAIN",
        "predicted_cardinality": 0,
        "selected_road_ids": [],
        "decision_confidence": 0.0,
        "cardinality_confidence": 0.0,
        "set_margin": 0.0,
        "confidence": 0.0,
        "candidate_count": 0,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _inference_example(
    feature: Mapping[str, Any],
    *,
    fold: int,
) -> OrdinaryRoadSetExample:
    candidates = feature["candidate_rows"]
    anchor_features = tuple(
        tuple(float(value) for value in row)
        for row in feature.get("anchor_role_feature_values") or ()
    )
    empty_anchor_relations = [
        [0.0] * 4 for _ in anchor_features
    ]
    oof_features = tuple(
        tuple(float(value) for value in row["oof_feature_values"])
        for row in candidates
    )
    return OrdinaryRoadSetExample(
        case_key=str(feature["case_key"]),
        segment_id=str(feature["segment_id"]),
        fold=fold,
        object_features=tuple(
            float(value) for value in feature["object_feature_values"]
        ),
        road_ids=tuple(str(row["road_id"]) for row in candidates),
        sources=tuple(str(row["source"]) for row in candidates),
        start_node_ids=tuple(
            str(row["start_node_id"]) for row in candidates
        ),
        end_node_ids=tuple(str(row["end_node_id"]) for row in candidates),
        anchor_features=anchor_features,
        teacher_anchor_relations=tuple(
            tuple(
                tuple(float(value) for value in relation)
                for relation in (
                    row.get("oof_anchor_relation_values")
                    or empty_anchor_relations
                )
            )
            for row in candidates
        ),
        oof_anchor_relations=tuple(
            tuple(
                tuple(float(value) for value in relation)
                for relation in (
                    row.get("oof_anchor_relation_values")
                    or empty_anchor_relations
                )
            )
            for row in candidates
        ),
        teacher_features=oof_features,
        oof_features=oof_features,
        decision=0,
        target_indices=(0,),
        ownership_targets=(0,) * len(candidates),
        ownership_task_mask=(False,) * len(candidates),
        business_role_targets=(0,) * len(candidates),
        business_role_task_mask=(False,) * len(candidates),
        sample_weight=0.0,
        oof_anchor_release_ready=False,
        road_relations=tuple(
            (
                int(row["left_index"]),
                int(row["right_index"]),
                tuple(float(value) for value in row["feature_values"]),
            )
            for row in feature.get("road_relation_rows") or ()
        ),
    )


def _load_checkpoint(
    path: Path,
    *,
    device: torch.device,
) -> tuple[
    TargetAOrdinaryRoadSetDecoder
    | TargetAOrdinaryJointRoadGraphDecoder
    | TargetAOrdinaryAnchorRoadGraphDecoder
    | TargetAOrdinaryAnchorRoadRoleGraphDecoder,
    OrdinaryRoadSetTrainingConfig,
]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    config = OrdinaryRoadSetTrainingConfig(**payload["config"])
    model_class = (
        TargetAOrdinaryAnchorRoadRoleGraphDecoder
        if config.ownership_role_decoder
        else TargetAOrdinaryAnchorRoadGraphDecoder
        if config.anchor_relation_decoder
        else TargetAOrdinaryJointRoadGraphDecoder
        if config.structured_graph_decoder
        else TargetAOrdinaryRoadSetDecoder
    )
    model = model_class(
        object_feature_dim=int(payload["object_dim"]),
        candidate_feature_dim=int(payload["candidate_dim"]),
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        **(
            {
                "graph_layers": config.graph_layers,
                "num_heads": config.graph_heads,
                "attention_scope": config.graph_attention_scope,
                "road_relation_dim": config.road_relation_dim,
            }
            if config.structured_graph_decoder
            else {}
        ),
        **(
            {
                "ownership_count": len(ROAD_OWNERSHIP_LABELS),
                "business_role_count": len(ROAD_BUSINESS_ROLE_LABELS),
                "fuse_business_into_membership": (
                    config.business_member_fusion
                ),
            }
            if config.ownership_role_decoder
            else {}
        ),
        cardinality_count=config.cardinality_count,
        dropout=config.dropout,
    ).to(device)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return model, config


def _forbidden_field_count(value: Any) -> int:
    forbidden = {
        "truth_decision",
        "target_road_ids",
        "decision_exact",
        "road_set_exact",
        "complete_exact",
        "teacher_exact",
    }
    if isinstance(value, Mapping):
        return sum(
            int(str(key) in forbidden) + _forbidden_field_count(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(_forbidden_field_count(item) for item in value)
    return 0


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if requested not in {"cuda", "cpu"}:
        raise ValueError("ordinary full inference device is invalid")
    return torch.device("cpu")


def _segment_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["segment_id"])


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_row(stream: TextIO, row: Mapping[str, Any]) -> None:
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
    "ordinary_state_from_prediction",
    "run_ordinary_road_set_full_oof_inference",
]
