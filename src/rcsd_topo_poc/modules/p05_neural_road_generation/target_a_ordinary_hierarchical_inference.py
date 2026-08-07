from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_network import (
    TargetAOrdinaryAccessDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_training import (
    OrdinaryAccessExample,
    OrdinaryAccessTrainingConfig,
    score_ordinary_access_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryUseRoadGraphDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_use_road_training import (
    OrdinaryUseRoadExample,
    OrdinaryUseRoadTrainingConfig,
    score_ordinary_use_road_examples,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_ordinary_hierarchical_full_oof_inference(
    *,
    road_member_store_root: Path,
    use_road_model_root: Path,
    access_store_root: Path,
    access_model_root: Path,
    carrier_full_oof_root: Path,
    output_root: Path,
    requested_device: str = "cuda",
    batch_size: int = 32,
) -> Path:
    """Apply fold checkpoints to every ordinary Segment and access object."""
    started = time.perf_counter()
    if batch_size < 1:
        raise ValueError("ordinary hierarchical batch size is invalid")
    member_root = normalize_runtime_path(
        road_member_store_root
    ).resolve(strict=True)
    use_root = normalize_runtime_path(use_road_model_root).resolve(strict=True)
    access_root = normalize_runtime_path(access_store_root).resolve(strict=True)
    access_model_root = normalize_runtime_path(
        access_model_root
    ).resolve(strict=True)
    carrier_root = normalize_runtime_path(
        carrier_full_oof_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    device = _resolve_device(requested_device)
    use_models, use_thresholds = _load_use_models(use_root, device)
    access_models, access_thresholds = _load_access_models(
        access_model_root,
        device,
    )
    member_labels = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(
            member_root / "ordinary_road_member_labels.jsonl"
        )
    }
    carrier_predictions = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(
            carrier_root / "full_oof_predictions.jsonl"
        )
    }
    use_predictions, segment_metadata = _score_full_use_roads(
        member_root,
        member_labels=member_labels,
        models=use_models,
        thresholds=use_thresholds,
        device=device,
        batch_size=batch_size,
    )
    access_predictions = _score_full_access(
        access_root,
        models=access_models,
        thresholds=access_thresholds,
        device=device,
        batch_size=batch_size,
    )
    use_path = root / "use_road_full_oof_predictions.jsonl"
    access_path = root / "access_full_oof_predictions.jsonl"
    _write_jsonl(
        use_path,
        sorted(
            use_predictions.values(),
            key=lambda row: (row["case_key"], row["segment_id"]),
        ),
    )
    _write_jsonl(
        access_path,
        sorted(
            access_predictions.values(),
            key=lambda row: (
                row["case_key"],
                row["segment_id"],
                row["junc_node_id"],
            ),
        ),
    )
    access_by_segment: dict[
        tuple[str, str],
        list[Mapping[str, Any]],
    ] = defaultdict(list)
    for key, row in access_predictions.items():
        access_by_segment[key[:2]].append(row)
    states = []
    counts: Counter[str] = Counter()
    for key, metadata in sorted(segment_metadata.items()):
        carrier = carrier_predictions.get(key)
        raw_decision = (
            str(carrier.get("raw_predicted_decision") or "")
            if carrier
            else "ABSTAIN"
        )
        use = use_predictions.get(key)
        if raw_decision == "KEEP_SWSD":
            road_ids = list(metadata["swsd_road_ids"])
            road_source = "SWSD"
            road_set_available = bool(road_ids)
            road_set_release_ready = bool(
                carrier and carrier.get("automatic_decision")
            )
        elif raw_decision == "USE_RCSD" and use is not None:
            road_ids = list(use["selected_road_ids"])
            road_source = "RCSD"
            road_set_available = bool(road_ids)
            road_set_release_ready = bool(
                carrier
                and carrier.get("automatic_decision")
                and use["conditional_automatic"]
            )
        else:
            road_ids = []
            road_source = ""
            road_set_available = False
            road_set_release_ready = False
        access_rows = sorted(
            access_by_segment.get(key, ()),
            key=lambda row: row["junc_node_id"],
        )
        access_in_carrier = [
            str(row["selected_road_id"]) in set(road_ids)
            for row in access_rows
        ]
        state = {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "case_key": key[0],
            "segment_id": key[1],
            "fold": int(metadata["fold"]),
            "anchor_all_resolved": bool(
                carrier and carrier.get("all_required_anchors_resolved")
            ),
            "anchor_all_success": bool(
                carrier and carrier.get("all_required_anchors_success")
            ),
            "raw_carrier_decision": raw_decision,
            "raw_carrier_probability": (
                float(carrier.get("raw_predicted_probability") or 0.0)
                if carrier
                else 0.0
            ),
            "road_source": road_source,
            "complete_road_ids": sorted(road_ids),
            "road_set_available": road_set_available,
            "road_set_release_ready": road_set_release_ready,
            "access_predictions": [
                {
                    "junc_node_id": str(row["junc_node_id"]),
                    "road_id": str(row["selected_road_id"]),
                    "road_source": str(row["selected_road_source"]),
                    "operation": str(row["selected_operation"]),
                    "fraction": float(row["selected_fraction"]),
                    "confidence": float(row["confidence"]),
                    "automatic": bool(row["automatic"]),
                    "in_complete_carrier": bool(in_carrier),
                }
                for row, in_carrier in zip(access_rows, access_in_carrier)
            ],
            "access_prediction_count": len(access_rows),
            "access_in_complete_carrier_count": sum(access_in_carrier),
            "hierarchical_state_consistent": bool(
                road_set_available
                and all(access_in_carrier)
            ),
            "hierarchical_release_ready": bool(
                road_set_release_ready
                and all(access_in_carrier)
                and all(bool(row["automatic"]) for row in access_rows)
            ),
            "feature_uses_truth": False,
            "terminal_input_count": 0,
        }
        states.append(state)
        counts["segment"] += 1
        counts[f"raw_decision_{raw_decision}"] += 1
        counts["road_set_available"] += int(road_set_available)
        counts["road_set_release_ready"] += int(road_set_release_ready)
        counts["hierarchical_state_consistent"] += int(
            state["hierarchical_state_consistent"]
        )
        counts["hierarchical_release_ready"] += int(
            state["hierarchical_release_ready"]
        )
    state_path = root / "ordinary_hierarchical_states.jsonl"
    _write_jsonl(state_path, states)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_HIERARCHICAL_FULL_STRICT_OOF_INFERENCE",
        "business_contract": {
            "order": (
                "anchor -> carrier decision -> complete Road set -> access "
                "Road/position; no downstream head can change an upstream "
                "decision"
            ),
            "keep": (
                "KEEP_SWSD expands to the frozen T01 Segment Road list"
            ),
            "use": (
                "USE_RCSD uses the fold-specific Road graph decoder output"
            ),
            "release": (
                "A state is releasable only when upstream gates pass and every "
                "predicted access Road belongs to the complete carrier."
            ),
        },
        "counts": dict(sorted(counts.items())),
        "use_prediction_count": len(use_predictions),
        "access_prediction_count": len(access_predictions),
        "requested_device": requested_device,
        "actual_device": str(device),
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "inputs": {
            "road_member_store": _input_record(member_root / "summary.json"),
            "use_road_model": _input_record(use_root / "summary.json"),
            "access_store": _input_record(access_root / "summary.json"),
            "access_model": _input_record(
                access_model_root / "summary.json"
            ),
            "carrier_full_oof": _input_record(carrier_root / "summary.json"),
        },
        "outputs": {
            "use_roads": _input_record(use_path),
            "access": _input_record(access_path),
            "states": _input_record(state_path),
        },
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "Road role, Node recipe, ownership/global topology, AdvanceRight, "
            "and final RoadGraph exact remain downstream."
        ),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(states) == counts["segment"]
            and len(states) == len(segment_metadata)
            and len(access_predictions) > 0
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary hierarchical inference gate failed")
    return root


def hierarchical_access_consistent(
    complete_road_ids: Sequence[str],
    access_road_ids: Sequence[str],
) -> bool:
    road_ids = {str(value) for value in complete_road_ids}
    return bool(road_ids) and all(
        str(value) in road_ids for value in access_road_ids
    )


def _score_full_use_roads(
    root: Path,
    *,
    member_labels: Mapping[tuple[str, str], Mapping[str, Any]],
    models: Mapping[int, TargetAOrdinaryUseRoadGraphDecoder],
    thresholds: Mapping[int, float],
    device: torch.device,
    batch_size: int,
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    predictions: dict[tuple[str, str], dict[str, Any]] = {}
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    buffers: dict[int, list[OrdinaryUseRoadExample]] = defaultdict(list)

    def flush(fold: int) -> None:
        rows = buffers[fold]
        if not rows:
            return
        scores = score_ordinary_use_road_examples(
            models[fold],
            rows,
            feature_source="oof",
            batch_size=len(rows),
            device=device,
        )
        for score in scores:
            score["conditional_automatic"] = bool(
                score["release_eligible"]
                and int(score["selected_component_count"]) == 1
                and float(score["confidence"]) >= thresholds[fold]
            )
            for key in (
                "road_set_exact",
                "road_precision",
                "road_recall",
                "road_f1",
                "cardinality_exact",
                "target_road_ids",
                "truth_cardinality",
            ):
                score.pop(key, None)
            predictions[
                (str(score["case_key"]), str(score["segment_id"]))
            ] = score
        rows.clear()

    path = root / "ordinary_road_member_features.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            feature = json.loads(line)
            key = (str(feature["case_key"]), str(feature["segment_id"]))
            fold = int(feature["fold"])
            candidates = [
                row
                for row in feature["candidate_rows"]
                if str(row["source"]) == "RCSD"
            ]
            metadata[key] = {
                "fold": fold,
                "swsd_road_ids": sorted(
                    str(row["road_id"])
                    for row in feature["candidate_rows"]
                    if str(row["source"]) == "SWSD"
                ),
            }
            if not candidates:
                continue
            label = member_labels[key]
            example = OrdinaryUseRoadExample(
                case_key=key[0],
                segment_id=key[1],
                fold=fold,
                object_features=tuple(
                    float(value)
                    for value in feature["object_feature_values"]
                ),
                road_ids=tuple(str(row["road_id"]) for row in candidates),
                endpoint_ids=tuple(
                    (
                        str(row["start_node_id"]),
                        str(row["end_node_id"]),
                    )
                    for row in candidates
                ),
                teacher_features=tuple(
                    tuple(float(value) for value in row["oof_feature_values"])
                    for row in candidates
                ),
                oof_features=tuple(
                    tuple(float(value) for value in row["oof_feature_values"])
                    for row in candidates
                ),
                target_indices=(0,),
                sample_weight=1.0,
                oof_anchor_release_ready=bool(
                    label["oof_anchor_release_ready"]
                ),
            )
            buffers[fold].append(example)
            if len(buffers[fold]) >= batch_size:
                flush(fold)
    for fold in sorted(buffers):
        flush(fold)
    return predictions, metadata


def _score_full_access(
    root: Path,
    *,
    models: Mapping[int, TargetAOrdinaryAccessDecoder],
    thresholds: Mapping[int, float],
    device: torch.device,
    batch_size: int,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    labels = {
        (
            str(row["case_key"]),
            str(row["segment_id"]),
            str(row["junc_node_id"]),
        ): row
        for row in _read_jsonl(root / "ordinary_access_training_labels.jsonl")
    }
    predictions: dict[tuple[str, str, str], dict[str, Any]] = {}
    buffers: dict[
        int,
        list[tuple[OrdinaryAccessExample, tuple[str, ...]]],
    ] = defaultdict(list)

    def flush(fold: int) -> None:
        pairs = buffers[fold]
        if not pairs:
            return
        examples = [pair[0] for pair in pairs]
        scores = score_ordinary_access_examples(
            models[fold],
            examples,
            feature_source="oof",
            batch_size=len(examples),
            device=device,
        )
        for score, (_, sources) in zip(scores, pairs):
            selected = int(score["predicted_index"])
            score["selected_road_id"] = str(score.pop("predicted_road_id"))
            score["selected_road_source"] = sources[selected]
            score["selected_operation"] = str(
                score.pop("predicted_operation")
            )
            score["selected_fraction"] = float(
                score.pop("predicted_fraction")
            )
            score["automatic"] = bool(
                score["release_eligible"]
                and float(score["confidence"]) >= thresholds[fold]
            )
            for key in (
                "raw_exact",
                "acceptable_indices",
                "predicted_proposal_id",
            ):
                score.pop(key, None)
            predictions[
                (
                    str(score["case_key"]),
                    str(score["segment_id"]),
                    str(score["junc_node_id"]),
                )
            ] = score
        pairs.clear()

    current_key: tuple[str, str, str] | None = None
    rows: list[dict[str, Any]] = []
    path = root / "ordinary_access_conditioned_candidates.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (
                str(row["case_key"]),
                str(row["segment_id"]),
                str(row["junc_node_id"]),
            )
            if current_key is not None and key != current_key:
                _append_access_example(
                    current_key,
                    rows,
                    labels[current_key],
                    buffers,
                )
                fold = int(labels[current_key]["fold"])
                if len(buffers[fold]) >= batch_size:
                    flush(fold)
                rows = []
            current_key = key
            rows.append(row)
    if current_key is not None:
        _append_access_example(
            current_key,
            rows,
            labels[current_key],
            buffers,
        )
    for fold in sorted(buffers):
        flush(fold)
    return predictions


def _append_access_example(
    key: tuple[str, str, str],
    proposals: Sequence[Mapping[str, Any]],
    label: Mapping[str, Any],
    buffers: dict[
        int,
        list[tuple[OrdinaryAccessExample, tuple[str, ...]]],
    ],
) -> None:
    base = [
        [
            *[float(value) for value in row["object_feature_values"]],
            *[float(value) for value in row["plan_feature_values"]],
            *[float(value) for value in row["member_feature_values"]],
            *[float(value) for value in row["geometry_feature_values"]],
            *[float(value) for value in row["oof_anchor_feature_values"]],
            *[float(value) for value in row["oof_carrier_feature_values"]],
        ]
        for row in proposals
    ]
    fold = int(label["fold"])
    example = OrdinaryAccessExample(
        case_key=key[0],
        segment_id=key[1],
        junc_node_id=key[2],
        fold=fold,
        proposal_ids=tuple(str(row["proposal_id"]) for row in proposals),
        road_ids=tuple(str(row["road_id"]) for row in proposals),
        operations=tuple(str(row["operation"]) for row in proposals),
        fractions=tuple(float(row["projected_fraction"]) for row in proposals),
        teacher_features=tuple(tuple(values) for values in base),
        oof_features=tuple(tuple(values) for values in base),
        acceptable_indices=(0,),
        sample_weight=1.0,
        oof_anchor_release_ready=bool(label["oof_anchor_release_ready"]),
        upstream_plan_release_blocked=bool(
            label["upstream_plan_release_blocked"]
        ),
    )
    buffers[fold].append(
        (
            example,
            tuple(str(row["source"]) for row in proposals),
        )
    )


def _load_use_models(
    root: Path,
    device: torch.device,
) -> tuple[
    dict[int, TargetAOrdinaryUseRoadGraphDecoder],
    dict[int, float],
]:
    summary = _read_json(root / "summary.json")
    models = {}
    thresholds = {}
    for fold_row in summary["folds"]:
        fold = int(fold_row["outer_fold"])
        checkpoint = torch.load(
            root / f"fold_{fold}_checkpoint.pt",
            map_location=device,
            weights_only=False,
        )
        config = OrdinaryUseRoadTrainingConfig(**checkpoint["config"])
        model = TargetAOrdinaryUseRoadGraphDecoder(
            object_feature_dim=int(checkpoint["object_dim"]),
            candidate_feature_dim=int(checkpoint["candidate_dim"]),
            hidden_dim=config.hidden_dim,
            context_dim=config.context_dim,
            graph_layers=config.graph_layers,
            num_heads=config.num_heads,
            cardinality_count=config.cardinality_count,
            dropout=config.dropout,
        ).to(device)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        models[fold] = model
        thresholds[fold] = float(fold_row["acceptance_threshold"])
    return models, thresholds


def _load_access_models(
    root: Path,
    device: torch.device,
) -> tuple[dict[int, TargetAOrdinaryAccessDecoder], dict[int, float]]:
    summary = _read_json(root / "summary.json")
    models = {}
    thresholds = {}
    for fold_row in summary["folds"]:
        fold = int(fold_row["outer_fold"])
        checkpoint = torch.load(
            root / f"fold_{fold}_checkpoint.pt",
            map_location=device,
            weights_only=False,
        )
        config = OrdinaryAccessTrainingConfig(**checkpoint["config"])
        model = TargetAOrdinaryAccessDecoder(
            feature_dim=int(checkpoint["feature_dim"]),
            hidden_dim=config.hidden_dim,
            context_dim=config.context_dim,
            dropout=config.dropout,
        ).to(device)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        models[fold] = model
        thresholds[fold] = float(fold_row["acceptance_threshold"])
    return models, thresholds


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


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


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


__all__ = [
    "hierarchical_access_consistent",
    "run_ordinary_hierarchical_full_oof_inference",
]
