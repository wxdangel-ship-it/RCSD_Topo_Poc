from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
    _batch_tensors,
    _forward_model,
    _input_record,
    _write_json,
    _write_jsonl,
    read_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_network import (
    TargetAOrdinarySetExpansionDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_training import (
    SetExpansionTrainingConfig,
    _resolve_device,
    _row_access_seed_mask,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_ordinary_set_expansion_beam_audit(
    *,
    member_store_root: Path,
    expansion_checkpoint_root: Path,
    output_root: Path,
    outer_fold: int,
    beam_widths: Sequence[int] = (1, 4, 8, 16, 32),
    batch_size: int = 32,
    requested_device: str = "cuda",
) -> Path:
    """Audit truth-free complete-plan proposals from one strict OOF fold."""
    started = time.perf_counter()
    widths = tuple(sorted({int(value) for value in beam_widths}))
    if (
        not widths
        or widths[0] < 1
        or batch_size < 1
        or outer_fold < 0
    ):
        raise ValueError("ordinary beam audit config is invalid")
    member_root = normalize_runtime_path(member_store_root).resolve(
        strict=True
    )
    checkpoint_root = normalize_runtime_path(
        expansion_checkpoint_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    examples, read_summary = read_ordinary_road_set_examples(member_root)
    rows = [row for row in examples if row.fold == outer_fold]
    if not rows:
        raise ValueError("ordinary beam audit fold is empty")
    device = _resolve_device(requested_device)
    checkpoint_path = checkpoint_root / f"fold_{outer_fold}_checkpoint.pt"
    model, config = _load_model(
        checkpoint_path,
        rows=rows,
        device=device,
    )
    root.mkdir(parents=True)
    maximum_width = widths[-1]
    predictions = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start : start + batch_size]
            batch = _batch_tensors(
                batch_rows,
                feature_source="oof",
                device=device,
                cardinality_count=config.cardinality_count,
                road_relation_dim=config.road_relation_dim,
            )
            outputs = _forward_model(model, batch)
            decision_log_probabilities = torch.log_softmax(
                outputs["decision_logits"],
                dim=-1,
            )
            for index, row in enumerate(batch_rows):
                length = len(row.road_ids)
                encoded = {
                    "candidate_encoded": outputs["candidate_encoded"][
                        index : index + 1, :length
                    ],
                    "graph_context": outputs["graph_context"][
                        index : index + 1
                    ],
                }
                relations = batch["road_relations"][
                    index : index + 1, :length, :length
                ]
                access_seeds = _row_access_seed_mask(
                    row,
                    feature_source="oof",
                ).to(device).unsqueeze(0)
                proposals = []
                for decision_index, source in enumerate(("SWSD", "RCSD")):
                    allowed = torch.tensor(
                        [value == source for value in row.sources],
                        dtype=torch.bool,
                        device=device,
                    ).unsqueeze(0)
                    if not bool(allowed.any()):
                        continue
                    decision_score = float(
                        decision_log_probabilities[
                            index, decision_index
                        ].item()
                    )
                    for proposal in beam_decode_complete_sets(
                        model,
                        encoded_outputs=encoded,
                        candidate_mask=allowed,
                        road_relations=relations,
                        access_seed_masks=access_seeds,
                        beam_width=maximum_width,
                    ):
                        proposals.append(
                            {
                                **proposal,
                                "decision_index": decision_index,
                                "decision": DECISIONS[decision_index],
                                "log_probability": (
                                    decision_score
                                    + float(proposal["log_probability"])
                                ),
                            }
                        )
                proposals = _deduplicate_joint_proposals(
                    proposals,
                    beam_width=maximum_width,
                )
                predictions.append(
                    _prediction_row(
                        row,
                        proposals=proposals,
                        widths=widths,
                    )
                )
            del batch, outputs
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "beam_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = _beam_metrics(predictions, widths=widths)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_SET_EXPANSION_BEAM_PROPOSAL_AUDIT",
        "outer_fold": outer_fold,
        "beam_widths": list(widths),
        "requested_device": requested_device,
        "actual_device": str(device),
        "example_count": len(rows),
        "metrics": metrics,
        "feature_uses_truth": False,
        "proposal_generation_uses_truth": False,
        "label_use": (
            "Truth decision and complete Road set are read only after "
            "proposal generation to compute oracle reachability."
        ),
        "decision_contract": (
            "KEEP_SWSD and USE_RCSD complete sets are proposed jointly; "
            "the frozen decision log probability contributes to plan rank."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "Oracle proposal reachability is diagnostic and does not choose "
            "an inference plan or establish a safe automatic decision."
        ),
        "member_store_summary": _input_record(
            member_root / "summary.json"
        ),
        "checkpoint_summary": _input_record(
            checkpoint_root / "summary.json"
        ),
        "checkpoint": _input_record(checkpoint_path),
        "predictions": _input_record(prediction_path),
        "read_summary": read_summary,
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def _load_model(
    checkpoint_path: Path,
    *,
    rows: Sequence[OrdinaryRoadSetExample],
    device: torch.device,
) -> tuple[TargetAOrdinarySetExpansionDecoder, SetExpansionTrainingConfig]:
    payload = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )
    config = SetExpansionTrainingConfig(**payload["config"])
    object_dim = len(rows[0].object_features)
    candidate_dim = len(rows[0].oof_features[0])
    anchor_dim = max(
        (
            len(value)
            for row in rows
            for value in row.anchor_features
        ),
        default=3,
    )
    anchor_relation_dim = max(
        (
            len(values)
            for row in rows
            for candidate in row.oof_anchor_relations
            for values in candidate
        ),
        default=4,
    )
    model = TargetAOrdinarySetExpansionDecoder(
        object_feature_dim=object_dim,
        candidate_feature_dim=candidate_dim,
        anchor_feature_dim=anchor_dim,
        anchor_relation_dim=anchor_relation_dim,
        road_relation_dim=config.road_relation_dim,
        cardinality_count=config.cardinality_count,
        component_action_decoder=config.component_action_decoder,
    ).to(device)
    model.load_state_dict(payload["state_dict"], strict=True)
    model.eval()
    return model, config


def beam_decode_complete_sets(
    model: TargetAOrdinarySetExpansionDecoder,
    *,
    encoded_outputs: Mapping[str, torch.Tensor],
    candidate_mask: torch.Tensor,
    road_relations: torch.Tensor,
    access_seed_masks: torch.Tensor,
    beam_width: int,
) -> list[dict[str, Any]]:
    """Return ranked complete sets without reading labels or cardinality."""
    if beam_width < 1 or candidate_mask.shape[0] != 1:
        raise ValueError("ordinary beam decoder config differs")
    candidate_count = candidate_mask.shape[1]
    beams: list[tuple[tuple[int, ...], float, bool]] = [
        (tuple(), 0.0, False)
    ]
    for _ in range(int(candidate_mask.sum().item()) + 1):
        active = [value for value in beams if not value[2]]
        if not active:
            break
        selected_masks = torch.zeros(
            1,
            len(active),
            candidate_count,
            dtype=torch.bool,
            device=candidate_mask.device,
        )
        for state_index, (selected, _, _) in enumerate(active):
            if selected:
                selected_masks[0, state_index, list(selected)] = True
        step = model.decode_next(
            encoded_outputs=dict(encoded_outputs),
            candidate_mask=candidate_mask,
            road_relations=road_relations,
            selected_masks=selected_masks,
            access_seed_masks=access_seed_masks,
        )
        log_probabilities = torch.log_softmax(
            torch.cat(
                (
                    step["next_road_logits"][0],
                    step["stop_logits"][0].unsqueeze(-1),
                ),
                dim=-1,
            ),
            dim=-1,
        )
        expanded = [value for value in beams if value[2]]
        for state_index, (selected, score, _) in enumerate(active):
            count = min(beam_width, log_probabilities.shape[-1])
            values, actions = torch.topk(
                log_probabilities[state_index],
                count,
            )
            for value, action in zip(
                values.tolist(),
                actions.tolist(),
                strict=True,
            ):
                if not math.isfinite(value) or value < -1e20:
                    continue
                stopped = action == candidate_count
                next_selected = (
                    selected
                    if stopped
                    else tuple(sorted((*selected, int(action))))
                )
                expanded.append(
                    (next_selected, score + float(value), stopped)
                )
        beams = _deduplicate_beam_states(
            expanded,
            beam_width=beam_width,
        )
    completed = [value for value in beams if value[2]]
    return [
        {
            "selected_indices": list(selected),
            "log_probability": score,
        }
        for selected, score, _ in completed
    ]


def _deduplicate_beam_states(
    states: Sequence[tuple[tuple[int, ...], float, bool]],
    *,
    beam_width: int,
) -> list[tuple[tuple[int, ...], float, bool]]:
    best: dict[tuple[tuple[int, ...], bool], float] = {}
    for selected, score, stopped in states:
        key = (selected, stopped)
        best[key] = max(score, best.get(key, -math.inf))
    return sorted(
        (
            (selected, score, stopped)
            for (selected, stopped), score in best.items()
        ),
        key=lambda value: (-value[1], value[2], value[0]),
    )[:beam_width]


def _deduplicate_joint_proposals(
    proposals: Sequence[Mapping[str, Any]],
    *,
    beam_width: int,
) -> list[dict[str, Any]]:
    best: dict[tuple[int, tuple[int, ...]], dict[str, Any]] = {}
    for raw in proposals:
        value = dict(raw)
        key = (
            int(value["decision_index"]),
            tuple(int(item) for item in value["selected_indices"]),
        )
        if (
            key not in best
            or float(value["log_probability"])
            > float(best[key]["log_probability"])
        ):
            best[key] = value
    return sorted(
        best.values(),
        key=lambda value: (
            -float(value["log_probability"]),
            int(value["decision_index"]),
            tuple(value["selected_indices"]),
        ),
    )[:beam_width]


def _prediction_row(
    row: OrdinaryRoadSetExample,
    *,
    proposals: Sequence[Mapping[str, Any]],
    widths: Sequence[int],
) -> dict[str, Any]:
    target = tuple(sorted(row.target_indices))
    annotated = []
    for rank, raw in enumerate(proposals, start=1):
        value = dict(raw)
        selected = tuple(int(item) for item in value["selected_indices"])
        exact = (
            int(value["decision_index"]) == row.decision
            and selected == target
        )
        annotated.append(
            {
                "rank": rank,
                "decision": value["decision"],
                "road_ids": [row.road_ids[index] for index in selected],
                "cardinality": len(selected),
                "log_probability": float(value["log_probability"]),
                "oracle_exact": exact,
            }
        )
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": row.case_key,
        "segment_id": row.segment_id,
        "fold": row.fold,
        "truth_decision": DECISIONS[row.decision],
        "truth_cardinality": len(target),
        "target_road_ids": [row.road_ids[index] for index in target],
        "proposal_count": len(annotated),
        "top1_exact": bool(
            annotated and annotated[0]["oracle_exact"]
        ),
        "oracle_exact_at": {
            str(width): any(
                value["oracle_exact"] for value in annotated[:width]
            )
            for width in widths
        },
        "exact_rank": next(
            (
                value["rank"]
                for value in annotated
                if value["oracle_exact"]
            ),
            None,
        ),
        "proposals": annotated,
    }


def _beam_metrics(
    predictions: Sequence[Mapping[str, Any]],
    *,
    widths: Sequence[int],
) -> dict[str, Any]:
    long_rows = [
        row for row in predictions if int(row["truth_cardinality"]) >= 10
    ]
    by_width = {}
    for width in widths:
        key = str(width)
        exact_count = sum(
            bool(row["oracle_exact_at"][key]) for row in predictions
        )
        long_exact_count = sum(
            bool(row["oracle_exact_at"][key]) for row in long_rows
        )
        by_width[key] = {
            "exact_count": exact_count,
            "exact_coverage": exact_count / len(predictions),
            "long_10_plus_exact_count": long_exact_count,
            "long_10_plus_count": len(long_rows),
            "long_10_plus_exact_coverage": (
                long_exact_count / len(long_rows) if long_rows else 0.0
            ),
        }
    return {
        "count": len(predictions),
        "top1_exact_count": sum(
            bool(row["top1_exact"]) for row in predictions
        ),
        "top1_exact": (
            sum(bool(row["top1_exact"]) for row in predictions)
            / len(predictions)
        ),
        "average_proposal_count": (
            sum(int(row["proposal_count"]) for row in predictions)
            / len(predictions)
        ),
        "by_width": by_width,
    }


__all__ = [
    "beam_decode_complete_sets",
    "run_ordinary_set_expansion_beam_audit",
]
