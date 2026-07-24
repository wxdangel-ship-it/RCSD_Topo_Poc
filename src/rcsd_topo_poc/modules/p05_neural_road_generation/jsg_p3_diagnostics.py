from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_training import (
    P3GroupExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import write_json


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield row


def _choice(tokens: Sequence[str]) -> tuple[str, ...]:
    prefixes = (
        "action:",
        "payload:direction_role=",
        "payload:direction_structure=",
        "payload:junction_type=",
        "payload:outcome=",
        "payload:state=",
        "payload:structural_role=",
        "pointer_state:",
    )
    return tuple(sorted(token for token in tokens if token.startswith(prefixes)))


def _signatures(group: P3GroupExample) -> tuple[list[str], list[str]]:
    candidate_only = [
        canonical_sha256(
            {
                "object_type": group.object_type,
                "candidate_tokens": list(tokens),
            }
        )
        for tokens in group.candidate_tokens
    ]
    contextual = [
        canonical_sha256(
            {
                "object_type": group.object_type,
                "candidate_tokens": list(tokens),
                "context_tokens": list(group.context_tokens),
            }
        )
        for tokens in group.candidate_tokens
    ]
    return candidate_only, contextual


def _lookup_oof_accuracy(
    groups: Sequence[P3GroupExample],
    signatures: Sequence[Sequence[str]],
    *,
    fold_count: int,
) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    positives: Counter[str] = Counter()
    fold_totals: dict[str, Counter[int]] = defaultdict(Counter)
    fold_positives: dict[str, Counter[int]] = defaultdict(Counter)
    for group, values in zip(groups, signatures, strict=True):
        for index, signature in enumerate(values):
            totals[signature] += 1
            fold_totals[signature][group.fold] += 1
            if index == group.truth_index:
                positives[signature] += 1
                fold_positives[signature][group.fold] += 1
    correct = 0
    correct_by_type: Counter[str] = Counter()
    counts_by_type: Counter[str] = Counter()
    seen_candidates = 0
    seen_groups = 0
    for group, values in zip(groups, signatures, strict=True):
        rates: list[float] = []
        all_seen = True
        for signature in values:
            train_total = totals[signature] - fold_totals[signature][group.fold]
            train_positive = positives[signature] - fold_positives[signature][group.fold]
            all_seen = all_seen and train_total > 0
            seen_candidates += train_total > 0
            rates.append((train_positive + 1.0) / (train_total + 2.0))
        seen_groups += all_seen
        selected = max(
            range(len(values)),
            key=lambda index: (rates[index], group.candidate_ids[index]),
        )
        is_correct = selected == group.truth_index
        correct += is_correct
        counts_by_type[group.object_type] += 1
        correct_by_type[group.object_type] += is_correct
    collision_signatures = sum(
        0 < positives[signature] < totals[signature] for signature in totals
    )
    collision_occurrences = sum(
        totals[signature]
        for signature in totals
        if 0 < positives[signature] < totals[signature]
    )
    return {
        "oof_lookup_top1_accuracy": correct / max(1, len(groups)),
        "oof_lookup_type_accuracy": {
            key: correct_by_type[key] / counts_by_type[key]
            for key in sorted(counts_by_type)
        },
        "signature_count": len(totals),
        "collision_signature_count": collision_signatures,
        "collision_candidate_occurrence_count": collision_occurrences,
        "held_out_seen_candidate_ratio": seen_candidates
        / max(1, sum(len(values) for values in signatures)),
        "held_out_all_candidates_seen_group_ratio": seen_groups / max(1, len(groups)),
        "fold_count": fold_count,
    }


def analyze_p3_dev_predictions(
    groups: Sequence[P3GroupExample],
    score_path: Path,
    output_path: Path,
    *,
    fold_count: int = 5,
) -> dict[str, Any]:
    score_rows = _read_jsonl(score_path)
    correct_by_fold: Counter[int] = Counter()
    groups_by_fold: Counter[int] = Counter()
    jsg_correct_by_fold: Counter[int] = Counter()
    jsg_groups_by_fold: Counter[int] = Counter()
    confusion: Counter[tuple[str, tuple[str, ...], tuple[str, ...]]] = Counter()
    errors_by_case: Counter[str] = Counter()
    candidate_signatures: list[list[str]] = []
    context_signatures: list[list[str]] = []
    for group in groups:
        rows = [next(score_rows) for _ in group.candidate_ids]
        if tuple(str(row["candidate_id"]) for row in rows) != group.candidate_ids:
            raise ValueError(f"P3 score/group candidate order differs: {group.group_id}")
        selected = [index for index, row in enumerate(rows) if bool(row["selected"])]
        if len(selected) != 1:
            raise ValueError(f"P3 score selection cardinality differs: {group.group_id}")
        is_correct = selected[0] == group.truth_index
        groups_by_fold[group.fold] += 1
        correct_by_fold[group.fold] += is_correct
        if group.domain == "JSG":
            jsg_groups_by_fold[group.fold] += 1
            jsg_correct_by_fold[group.fold] += is_correct
        errors_by_case[group.case_key] += not is_correct
        confusion[
            (
                group.object_type,
                _choice(group.candidate_tokens[group.truth_index]),
                _choice(group.candidate_tokens[selected[0]]),
            )
        ] += 1
        candidate_only, contextual = _signatures(group)
        candidate_signatures.append(candidate_only)
        context_signatures.append(contextual)
    try:
        next(score_rows)
    except StopIteration:
        pass
    else:
        raise ValueError("P3 score file has rows after final group")
    result = {
        "schema_version": "p05-jsg-p3-dev-diagnostic-v1",
        "group_count": len(groups),
        "candidate_count": sum(len(group.candidate_ids) for group in groups),
        "observed_fold_accuracy": {
            str(fold): correct_by_fold[fold] / groups_by_fold[fold]
            for fold in range(fold_count)
        },
        "observed_jsg_fold_accuracy": {
            str(fold): jsg_correct_by_fold[fold] / max(1, jsg_groups_by_fold[fold])
            for fold in range(fold_count)
        },
        "candidate_only_signature_lookup": _lookup_oof_accuracy(
            groups, candidate_signatures, fold_count=fold_count
        ),
        "contextual_signature_lookup": _lookup_oof_accuracy(
            groups, context_signatures, fold_count=fold_count
        ),
        "jsg_candidate_only_signature_lookup": _lookup_oof_accuracy(
            [group for group in groups if group.domain == "JSG"],
            [
                signatures
                for group, signatures in zip(groups, candidate_signatures, strict=True)
                if group.domain == "JSG"
            ],
            fold_count=fold_count,
        ),
        "jsg_contextual_signature_lookup": _lookup_oof_accuracy(
            [group for group in groups if group.domain == "JSG"],
            [
                signatures
                for group, signatures in zip(groups, context_signatures, strict=True)
                if group.domain == "JSG"
            ],
            fold_count=fold_count,
        ),
        "largest_case_error_counts": dict(errors_by_case.most_common(15)),
        "largest_choice_confusions": [
            {
                "object_type": key[0],
                "truth_choice": list(key[1]),
                "selected_choice": list(key[2]),
                "count": count,
            }
            for key, count in confusion.most_common(50)
        ],
        "feature_uses_truth": False,
    }
    write_json(output_path, result)
    return result


__all__ = ["analyze_p3_dev_predictions"]
