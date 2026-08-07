from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    _batch_tensors,
    _forward_model,
    _input_record,
    _write_json,
    _write_jsonl,
    read_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_beam_audit import (
    _load_model,
    beam_decode_complete_sets,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_training import (
    _resolve_device,
    _row_access_seed_mask,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


PREFIX_GENERATORS = (
    "MEMBERSHIP_PREFIX",
    "OWNERSHIP_PREFIX",
    "ROLE_PREFIX",
    "COMBINED_PREFIX",
)


def run_ordinary_multi_view_plan_oracle_audit(
    *,
    member_store_root: Path,
    expansion_checkpoint_root: Path,
    output_root: Path,
    outer_fold: int,
    beam_width: int = 16,
    batch_size: int = 32,
    requested_device: str = "cuda",
) -> Path:
    """Audit beam plus model-score prefix complete-plan reachability."""
    started = time.perf_counter()
    if beam_width < 1 or batch_size < 1 or outer_fold < 0:
        raise ValueError("ordinary multi-view plan audit config differs")
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
        raise ValueError("ordinary multi-view plan fold is empty")
    device = _resolve_device(requested_device)
    checkpoint_path = checkpoint_root / f"fold_{outer_fold}_checkpoint.pt"
    model, config = _load_model(
        checkpoint_path,
        rows=rows,
        device=device,
    )
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
            member = torch.sigmoid(outputs["member_logits"])
            ownership = torch.softmax(
                outputs["ownership_logits"],
                dim=-1,
            )
            roles = torch.softmax(
                outputs["business_role_logits"],
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
                proposals: dict[
                    tuple[int, tuple[int, ...]],
                    set[str],
                ] = defaultdict(set)
                for decision_index, source in enumerate(("SWSD", "RCSD")):
                    source_indices = [
                        candidate
                        for candidate, value in enumerate(row.sources)
                        if value == source
                    ]
                    if not source_indices:
                        continue
                    allowed = torch.zeros(
                        1,
                        length,
                        dtype=torch.bool,
                        device=device,
                    )
                    allowed[0, source_indices] = True
                    for proposal in beam_decode_complete_sets(
                        model,
                        encoded_outputs=encoded,
                        candidate_mask=allowed,
                        road_relations=relations,
                        access_seed_masks=access_seeds,
                        beam_width=beam_width,
                    ):
                        selected = tuple(
                            int(value)
                            for value in proposal["selected_indices"]
                        )
                        proposals[(decision_index, selected)].add("BEAM")
                    score_views = {
                        "MEMBERSHIP_PREFIX": member[
                            index, :length
                        ],
                        "OWNERSHIP_PREFIX": (
                            1.0 - ownership[index, :length, 0]
                        ),
                        "ROLE_PREFIX": (
                            1.0 - roles[index, :length, 0]
                        ),
                    }
                    score_views["COMBINED_PREFIX"] = (
                        score_views["MEMBERSHIP_PREFIX"]
                        * score_views["OWNERSHIP_PREFIX"]
                        * score_views["ROLE_PREFIX"]
                    ).pow(1.0 / 3.0)
                    for generator, scores in score_views.items():
                        for selected in build_ranked_prefix_sets(
                            source_indices,
                            scores=scores,
                        ):
                            proposals[(decision_index, selected)].add(
                                generator
                            )
                target = tuple(sorted(row.target_indices))
                generator_reachable = {
                    generator: any(
                        decision == row.decision
                        and selected == target
                        and generator in generators
                        for (decision, selected), generators
                        in proposals.items()
                    )
                    for generator in ("BEAM", *PREFIX_GENERATORS)
                }
                union_reachable = any(
                    decision == row.decision and selected == target
                    for decision, selected in proposals
                )
                predictions.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "segment_id": row.segment_id,
                        "fold": row.fold,
                        "truth_decision": DECISIONS[row.decision],
                        "truth_cardinality": len(target),
                        "proposal_count": len(proposals),
                        "beam_reachable": generator_reachable["BEAM"],
                        "generator_reachable": generator_reachable,
                        "union_reachable": union_reachable,
                    }
                )
            del batch, outputs
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    root.mkdir(parents=True)
    prediction_path = root / "oracle_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_MULTI_VIEW_PLAN_ORACLE_AUDIT",
        "outer_fold": outer_fold,
        "beam_width": beam_width,
        "example_count": len(predictions),
        "metrics": _oracle_metrics(predictions),
        "feature_uses_truth": False,
        "proposal_generation_uses_truth": False,
        "label_use": (
            "Truth decision and Road set are read only after beam and all "
            "model-score prefixes are frozen for oracle evaluation."
        ),
        "proposal_contract": (
            "For each KEEP/USE source, generate beam sets and every "
            "cardinality prefix under membership, ownership-inclusion, "
            "business-role-inclusion and their geometric-mean score."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "Oracle reachability does not choose a plan or establish a safe "
            "automatic business decision."
        ),
        "read_summary": read_summary,
        "member_store_summary": _input_record(
            member_root / "summary.json"
        ),
        "expansion_summary": _input_record(
            checkpoint_root / "summary.json"
        ),
        "checkpoint": _input_record(checkpoint_path),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def build_ranked_prefix_sets(
    candidate_indices: Sequence[int],
    *,
    scores: torch.Tensor,
) -> tuple[tuple[int, ...], ...]:
    if scores.ndim != 1 or any(
        index < 0 or index >= scores.shape[0]
        for index in candidate_indices
    ):
        raise ValueError("ordinary plan prefix scores differ")
    ranked = sorted(
        (int(index) for index in candidate_indices),
        key=lambda index: (-float(scores[index]), index),
    )
    return tuple(
        tuple(sorted(ranked[:cardinality]))
        for cardinality in range(1, len(ranked) + 1)
    )


def _oracle_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    long_rows = [
        row for row in rows if int(row["truth_cardinality"]) >= 10
    ]
    generators = ("BEAM", *PREFIX_GENERATORS)
    return {
        "count": len(rows),
        "average_proposal_count": (
            sum(int(row["proposal_count"]) for row in rows) / len(rows)
        ),
        "union_reachable_count": sum(
            bool(row["union_reachable"]) for row in rows
        ),
        "union_reachable_coverage": sum(
            bool(row["union_reachable"]) for row in rows
        )
        / len(rows),
        "long_10_plus_count": len(long_rows),
        "long_10_plus_union_reachable_count": sum(
            bool(row["union_reachable"]) for row in long_rows
        ),
        "by_generator": {
            generator: {
                "reachable_count": sum(
                    bool(row["generator_reachable"][generator])
                    for row in rows
                ),
                "long_10_plus_reachable_count": sum(
                    bool(row["generator_reachable"][generator])
                    for row in long_rows
                ),
            }
            for generator in generators
        },
    }


__all__ = [
    "PREFIX_GENERATORS",
    "build_ranked_prefix_sets",
    "run_ordinary_multi_view_plan_oracle_audit",
]
