from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_FAMILIES,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def select_anchor_store_for_plan_label_scope(
    *,
    source_anchor_store_root: Path,
    candidate_store_root: Path,
    plan_label_root: Path,
    output_root: Path,
    run_id: str,
    plan_label_mask_field: str = "label_task_mask",
) -> Path:
    """Select every labeled ordinary Segment anchor, independent of plan reachability."""
    source_root = normalize_runtime_path(source_anchor_store_root).resolve(
        strict=True
    )
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    label_root = normalize_runtime_path(plan_label_root).resolve(strict=True)
    examples = read_anchor_pretraining_stores(source_root)
    groups = _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    labels = _read_jsonl(label_root / "training_plan_labels.jsonl")
    selected, summary = select_anchor_examples_for_plan_scope(
        examples,
        groups=groups,
        plan_labels=labels,
        plan_label_mask_field=plan_label_mask_field,
    )
    root = write_anchor_pretraining_stores(
        selected,
        output_root=output_root,
        run_id=run_id,
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"] = {
        "source_anchor_manifest": _input_record(source_root / "manifest.json"),
        "candidate_manifest": _input_record(candidate_root / "manifest.json"),
        "plan_labels": _input_record(
            label_root / "training_plan_labels.jsonl"
        ),
        "selection_contract": (
            "Retain all single-point anchors and every required anchor of a "
            f"STANDARD Segment whose {plan_label_mask_field}=true; complete-plan "
            "candidate reachability never narrows anchor scope."
        ),
        **summary,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def select_anchor_examples_for_plan_scope(
    examples: Sequence[AnchorPretrainExample],
    *,
    groups: Sequence[Mapping[str, Any]],
    plan_labels: Sequence[Mapping[str, Any]],
    plan_label_mask_field: str = "label_task_mask",
) -> tuple[list[AnchorPretrainExample], dict[str, Any]]:
    group_by_key = {
        (str(row["case_key"]), str(row["segment_id"])): row for row in groups
    }
    target_segments: list[tuple[str, str, tuple[str, ...]]] = []
    for label in plan_labels:
        if not bool(label.get(plan_label_mask_field)):
            continue
        key = (str(label["case_key"]), str(label["segment_id"]))
        group = group_by_key.get(key)
        if group is None:
            raise ValueError(f"anchor scope plan group is missing: {key}")
        if str(group.get("segment_type")) != "STANDARD":
            continue
        required = tuple(str(value) for value in group["required_anchor_ids"])
        target_segments.append((key[0], key[1], required))

    target_anchor_keys = {
        (case_key, anchor_id)
        for case_key, _, required in target_segments
        for anchor_id in required
    }
    source_by_key = {
        (row.case_key, row.anchor_id): row for row in examples
    }
    if len(source_by_key) != len(examples):
        raise ValueError("anchor scope source has duplicate Case anchors")
    missing = sorted(target_anchor_keys - set(source_by_key))
    if missing:
        raise ValueError(
            f"anchor scope lacks required ordinary anchors: {missing}"
        )

    dependencies: dict[tuple[str, str], set[str]] = defaultdict(set)
    for case_key, _, required in target_segments:
        for anchor_id in required:
            dependencies[(case_key, anchor_id)].update(required)
    selected: list[AnchorPretrainExample] = []
    counts: Counter[str] = Counter()
    for row in examples:
        family = row.case_key.split(":", 1)[0]
        key = (row.case_key, row.anchor_id)
        if family in ANCHOR_FAMILIES:
            selected.append(row)
            counts["single_point_anchor"] += 1
        elif key in target_anchor_keys:
            selected.append(
                replace(
                    row,
                    dependency_anchor_ids=tuple(
                        sorted(dependencies[key])
                    ),
                )
            )
            counts["ordinary_target_anchor"] += 1
        else:
            counts["excluded_context_anchor"] += 1
    selected.sort(key=lambda row: (row.case_key, row.anchor_id, row.sample_id))
    selected_keys = {(row.case_key, row.anchor_id) for row in selected}
    if not target_anchor_keys <= selected_keys:
        raise AssertionError("anchor scope selection lost a target anchor")
    return selected, {
        "source_example_count": len(examples),
        "selected_example_count": len(selected),
        "target_segment_count": len(target_segments),
        "target_anchor_count": len(target_anchor_keys),
        "zero_required_anchor_segment_count": sum(
            not required for _, _, required in target_segments
        ),
        "single_point_anchor_count": counts["single_point_anchor"],
        "excluded_context_anchor_count": counts["excluded_context_anchor"],
        "feature_rows_recomputed": 0,
        "dependency_scope_recomputed": True,
        "required_anchor_coverage": 1.0,
        "plan_label_mask_field": plan_label_mask_field,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _input_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


__all__ = [
    "select_anchor_examples_for_plan_scope",
    "select_anchor_store_for_plan_label_scope",
]
