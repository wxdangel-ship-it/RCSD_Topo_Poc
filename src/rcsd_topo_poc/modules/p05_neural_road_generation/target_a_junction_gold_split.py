from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file


SPLIT_RATIOS: Mapping[str, float] = {
    "train": 0.70,
    "validation": 0.15,
    "test": 0.15,
}


@dataclass(frozen=True)
class JunctionGoldSplitGroup:
    sample_group_id: str
    case_id: str
    split: str
    stratum: str
    source_version_count: int
    sample_ids: tuple[str, ...]
    terminal_business_signature: str


@dataclass(frozen=True)
class JunctionGoldSplitSample:
    sample_id: str
    sample_group_id: str
    case_id: str
    split: str
    source_index: int
    case_root: str
    input_fingerprint: str
    family: str
    source_scope: str
    original_label_weight: float
    effective_label_weight: float
    terminal_business_signature: str


@dataclass(frozen=True)
class JunctionGoldSplitExclusion:
    case_id: str
    reason: str
    sample_ids: tuple[str, ...]


def build_junction_gold_split(
    *,
    labels_path: Path,
    version_reviews_path: Path,
    seed: int = 20260804,
) -> tuple[
    tuple[JunctionGoldSplitGroup, ...],
    tuple[JunctionGoldSplitSample, ...],
    tuple[JunctionGoldSplitExclusion, ...],
    dict[str, Any],
]:
    labels = tuple(_read_jsonl(Path(labels_path)))
    reviews = {
        str(row["case_id"]): row
        for row in _read_jsonl(Path(version_reviews_path))
    }
    by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    exclusions: list[JunctionGoldSplitExclusion] = []
    for label in labels:
        if str(label.get("label_status")) != "READY":
            exclusions.append(
                JunctionGoldSplitExclusion(
                    case_id=str(label.get("case_id") or ""),
                    reason="label_not_ready",
                    sample_ids=(str(label.get("sample_id") or ""),),
                )
            )
            continue
        by_group[str(label["sample_group_id"])].append(label)

    ready_groups: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for group_id, rows in sorted(by_group.items()):
        case_id = str(rows[0]["case_id"])
        review = reviews.get(case_id)
        if review and str(review.get("status")) == "TERMINAL_BUSINESS_CONFLICT":
            exclusions.append(
                JunctionGoldSplitExclusion(
                    case_id=case_id,
                    reason="terminal_business_conflict_across_input_versions",
                    sample_ids=tuple(sorted(str(row["sample_id"]) for row in rows)),
                )
            )
            continue
        deduplicated = _deduplicate_exact_inputs(rows)
        signatures = {
            str(row.get("terminal_business_signature") or "")
            for row in deduplicated
        }
        if len(signatures) != 1 or "" in signatures:
            exclusions.append(
                JunctionGoldSplitExclusion(
                    case_id=case_id,
                    reason="terminal_business_signature_not_unique",
                    sample_ids=tuple(
                        sorted(str(row["sample_id"]) for row in deduplicated)
                    ),
                )
            )
            continue
        ready_groups[group_id] = tuple(deduplicated)

    assignments = _assign_groups(ready_groups, seed=seed)
    group_rows: list[JunctionGoldSplitGroup] = []
    sample_rows: list[JunctionGoldSplitSample] = []
    for group_id, rows in sorted(ready_groups.items()):
        split = assignments[group_id]
        first = rows[0]
        signature = str(first["terminal_business_signature"])
        group_rows.append(
            JunctionGoldSplitGroup(
                sample_group_id=group_id,
                case_id=str(first["case_id"]),
                split=split,
                stratum=_stratum(first),
                source_version_count=len(rows),
                sample_ids=tuple(sorted(str(row["sample_id"]) for row in rows)),
                terminal_business_signature=signature,
            )
        )
        version_divisor = float(len(rows))
        for row in sorted(rows, key=lambda item: int(item["source_index"])):
            original_weight = float(row.get("label_weight") or 1.0)
            sample_rows.append(
                JunctionGoldSplitSample(
                    sample_id=str(row["sample_id"]),
                    sample_group_id=group_id,
                    case_id=str(row["case_id"]),
                    split=split,
                    source_index=int(row["source_index"]),
                    case_root=str(row["case_root"]),
                    input_fingerprint=str(row["input_fingerprint"]),
                    family=str(row["family"]),
                    source_scope=str(row["source_scope"]),
                    original_label_weight=original_weight,
                    effective_label_weight=round(
                        original_weight / version_divisor,
                        12,
                    ),
                    terminal_business_signature=signature,
                )
            )

    group_rows.sort(key=lambda row: (row.split, row.case_id))
    sample_rows.sort(key=lambda row: (row.split, row.case_id, row.source_index))
    exclusions.sort(key=lambda row: (row.case_id, row.reason))
    _validate_no_leakage(group_rows, sample_rows)
    summary = {
        "schema_version": "p05-target-a-junction-gold-split-v1",
        "status": "JUNCTION_GOLD_SPLIT_GO",
        "seed": seed,
        "split_ratios": dict(SPLIT_RATIOS),
        "input_label_record_count": len(labels),
        "included_group_count": len(group_rows),
        "included_sample_version_count": len(sample_rows),
        "excluded_group_count": len({row.case_id for row in exclusions}),
        "split_group_counts": dict(
            sorted(Counter(row.split for row in group_rows).items())
        ),
        "split_sample_counts": dict(
            sorted(Counter(row.split for row in sample_rows).items())
        ),
        "split_effective_weight": {
            split: round(
                sum(
                    row.effective_label_weight
                    for row in sample_rows
                    if row.split == split
                ),
                6,
            )
            for split in SPLIT_RATIOS
        },
        "source_version_group_counts": dict(
            sorted(Counter(row.source_version_count for row in group_rows).items())
        ),
        "exclusion_reason_counts": dict(
            sorted(Counter(row.reason for row in exclusions).items())
        ),
        "stratum_split_counts": _stratum_split_counts(group_rows),
        "train_missing_stratum_count": sum(
            counts.get("train", 0) == 0
            for counts in _stratum_split_counts(group_rows).values()
        ),
        "case_group_leakage_count": 0,
        "input_fingerprint_leakage_count": 0,
        "test_split_locked": True,
    }
    return (
        tuple(group_rows),
        tuple(sample_rows),
        tuple(exclusions),
        summary,
    )


def write_junction_gold_split(
    *,
    labels_path: Path,
    version_reviews_path: Path,
    output_root: Path,
    seed: int = 20260804,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    groups, samples, exclusions, summary = build_junction_gold_split(
        labels_path=labels_path,
        version_reviews_path=version_reviews_path,
        seed=seed,
    )
    paths = {
        "groups": output / "junction_gold_split_groups.jsonl",
        "samples": output / "junction_gold_split_samples.jsonl",
        "exclusions": output / "junction_gold_split_exclusions.jsonl",
    }
    _write_jsonl(paths["groups"], (asdict(row) for row in groups))
    _write_jsonl(paths["samples"], (asdict(row) for row in samples))
    _write_jsonl(paths["exclusions"], (asdict(row) for row in exclusions))
    result = {
        **summary,
        "artifacts": {role: _artifact(path) for role, path in paths.items()},
    }
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _assign_groups(
    ready_groups: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    seed: int,
) -> Mapping[str, str]:
    target_counts = _target_counts(len(ready_groups))
    strata: dict[str, list[str]] = defaultdict(list)
    for group_id, rows in ready_groups.items():
        strata[_stratum(rows[0])].append(group_id)
    stratum_totals = {key: len(value) for key, value in strata.items()}
    assigned_total = Counter()
    assigned_stratum: dict[str, Counter[str]] = defaultdict(Counter)
    assignments: dict[str, str] = {}
    order: list[tuple[str, str]] = []
    for stratum, group_ids in sorted(strata.items()):
        sorted_ids = sorted(
            group_ids,
            key=lambda group_id: _stable_hash(
                f"{seed}:{stratum}:{group_id}"
            ),
        )
        first = sorted_ids[0]
        assignments[first] = "train"
        assigned_total["train"] += 1
        assigned_stratum[stratum]["train"] += 1
        for group_id in sorted_ids[1:]:
            order.append((stratum, group_id))
    order.sort(
        key=lambda item: (
            stratum_totals[item[0]],
            _stable_hash(f"{seed}:{item[0]}:{item[1]}"),
        )
    )
    split_order = tuple(SPLIT_RATIOS)
    for stratum, group_id in order:
        available = [
            split
            for split in split_order
            if assigned_total[split] < target_counts[split]
        ]
        if not available:
            raise RuntimeError("junction Gold split exhausted all capacities")

        def score(split: str) -> tuple[float, float, str]:
            desired_stratum = max(
                stratum_totals[stratum] * SPLIT_RATIOS[split],
                0.25,
            )
            stratum_fill = assigned_stratum[stratum][split] / desired_stratum
            total_fill = assigned_total[split] / max(target_counts[split], 1)
            tie = _stable_hash(f"{seed}:{group_id}:{split}")
            return stratum_fill, total_fill, tie

        selected = min(available, key=score)
        assignments[group_id] = selected
        assigned_total[selected] += 1
        assigned_stratum[stratum][selected] += 1
    if dict(assigned_total) != target_counts:
        raise RuntimeError(
            f"junction Gold split counts differ: {dict(assigned_total)} != {target_counts}"
        )
    return assignments


def _target_counts(total: int) -> dict[str, int]:
    exact = {split: total * ratio for split, ratio in SPLIT_RATIOS.items()}
    counts = {split: int(value) for split, value in exact.items()}
    remaining = total - sum(counts.values())
    order = sorted(
        SPLIT_RATIOS,
        key=lambda split: (-(exact[split] - counts[split]), split),
    )
    for split in order[:remaining]:
        counts[split] += 1
    return counts


def _deduplicate_exact_inputs(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    selected: dict[str, Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(item["source_index"])):
        fingerprint = str(row.get("input_fingerprint") or "")
        key = fingerprint or f"source-index:{row['source_index']}"
        selected.setdefault(key, row)
    return tuple(selected.values())


def _stratum(row: Mapping[str, Any]) -> str:
    return "|".join(
        (
            str(row.get("route_class") or ""),
            str(row.get("surface_state") or ""),
            str(row.get("anchor_business_state") or ""),
            str(row.get("t07_step2_is_anchor") or ""),
        )
    )


def _validate_no_leakage(
    groups: Sequence[JunctionGoldSplitGroup],
    samples: Sequence[JunctionGoldSplitSample],
) -> None:
    split_by_group: dict[str, set[str]] = defaultdict(set)
    split_by_fingerprint: dict[str, set[str]] = defaultdict(set)
    for row in groups:
        split_by_group[row.sample_group_id].add(row.split)
    for row in samples:
        split_by_group[row.sample_group_id].add(row.split)
        split_by_fingerprint[row.input_fingerprint].add(row.split)
    leaking_groups = [key for key, values in split_by_group.items() if len(values) > 1]
    leaking_inputs = [
        key for key, values in split_by_fingerprint.items() if key and len(values) > 1
    ]
    if leaking_groups or leaking_inputs:
        raise ValueError(
            "junction Gold split leakage detected: "
            f"groups={leaking_groups[:5]}, inputs={leaking_inputs[:5]}"
        )


def _stratum_split_counts(
    groups: Sequence[JunctionGoldSplitGroup],
) -> Mapping[str, Mapping[str, int]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in groups:
        result[row.stratum][row.split] += 1
    return {
        stratum: {split: counts.get(split, 0) for split in SPLIT_RATIOS}
        for stratum, counts in sorted(result.items())
    }


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> Iterable[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield dict(json.loads(line))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


__all__ = [
    "JunctionGoldSplitExclusion",
    "JunctionGoldSplitGroup",
    "JunctionGoldSplitSample",
    "SPLIT_RATIOS",
    "build_junction_gold_split",
    "write_junction_gold_split",
]
