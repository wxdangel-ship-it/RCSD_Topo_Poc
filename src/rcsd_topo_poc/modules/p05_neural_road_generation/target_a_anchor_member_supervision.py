from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


AnchorKey = tuple[str, str]
MemberOption = tuple[str, ...]


def apply_anchor_member_supervision(
    examples: Sequence[AnchorPretrainExample],
    *,
    explicit_member_options: Mapping[
        AnchorKey,
        Sequence[MemberOption],
    ] = {},
) -> tuple[list[AnchorPretrainExample], Counter[str]]:
    """Add label-only exact member-set truth without changing candidates."""
    transformed = []
    counts: Counter[str] = Counter()
    seen_explicit: set[AnchorKey] = set()
    for row in examples:
        key = (row.case_key, row.anchor_id)
        member_index = {
            member_id: index
            for index, member_id in enumerate(row.structural_member_ids)
        }
        acceptable_sets = {
            option
            for candidate_index in row.candidate_acceptable_indices
            if (
                option := _candidate_member_indices(
                    row.candidate_ids[candidate_index],
                    member_index,
                )
            )
        }
        counts["candidate_derived_member_set"] += len(acceptable_sets)
        explicit = explicit_member_options.get(key, ())
        if explicit:
            seen_explicit.add(key)
        for option in explicit:
            normalized = tuple(dict.fromkeys(str(value) for value in option))
            if not normalized or any(
                member_id not in member_index
                for member_id in normalized
            ):
                counts["explicit_member_set_unreachable"] += 1
                continue
            prefixes = {
                member_id.partition(":")[0]
                for member_id in normalized
            }
            if prefixes - {"NODE", "ROAD"} or len(prefixes) != 1:
                raise ValueError(
                    f"Explicit anchor member option has mixed types: {key}"
                )
            acceptable_sets.add(
                tuple(sorted(member_index[member_id] for member_id in normalized))
            )
            counts["explicit_member_set_reachable"] += 1
        ordered = tuple(sorted(acceptable_sets))
        if (
            ordered
            and (
                not row.status_supervised
                or row.status_label
                != ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
            )
        ):
            raise ValueError(
                f"Member-set truth is attached to a non-success anchor: {key}"
            )
        result = replace(
            row,
            member_acceptable_sets=ordered,
            member_supervised=bool(ordered),
        )
        counts["member_supervised"] += int(result.member_supervised)
        counts["member_option"] += len(ordered)
        counts["member_only_supervised"] += int(
            result.member_supervised and not result.candidate_supervised
        )
        transformed.append(result)
    missing = sorted(set(explicit_member_options) - seen_explicit)
    if missing:
        raise ValueError(
            "Explicit anchor member truth is outside the source store: "
            + "|".join(f"{case_key}/{anchor_id}" for case_key, anchor_id in missing)
        )
    counts["example"] = len(transformed)
    return transformed, counts


def write_anchor_member_supervision_store(
    *,
    source_store_root: Path,
    explicit_member_options: Mapping[
        AnchorKey,
        Sequence[MemberOption],
    ],
    output_root: Path,
    run_id: str,
    truth_source_paths: Iterable[Path] = (),
) -> Path:
    """Materialize the label overlay and prove inference bytes are unchanged."""
    source_root = normalize_runtime_path(source_store_root).resolve(strict=True)
    root_parent = normalize_runtime_path(output_root).resolve()
    examples = read_anchor_pretraining_stores(source_root)
    transformed, counts = apply_anchor_member_supervision(
        examples,
        explicit_member_options=explicit_member_options,
    )
    root = write_anchor_pretraining_stores(
        transformed,
        output_root=root_parent,
        run_id=run_id,
    )
    source_feature = (
        source_root / "inference_feature_store" / "anchor_features.jsonl"
    )
    output_feature = root / "inference_feature_store" / "anchor_features.jsonl"
    byte_identical = sha256_file(source_feature) == sha256_file(output_feature)
    if not byte_identical:
        raise RuntimeError("anchor member supervision changed inference features")
    source_records = [
        {
            "path": str(path),
            "sha256": sha256_file(path),
        }
        for path in sorted(
            {
                normalize_runtime_path(path).resolve(strict=True)
                for path in truth_source_paths
            },
            key=str,
        )
    ]
    summary_path = root / "anchor_member_supervision_summary.json"
    _write_json(
        summary_path,
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ANCHOR_MEMBER_SET_SUPERVISION",
            "source_store": {
                "path": str(source_root),
                "manifest_sha256": sha256_file(source_root / "manifest.json"),
            },
            "truth_sources": source_records,
            "explicit_anchor_count": len(explicit_member_options),
            "counts": dict(sorted(counts.items())),
            "feature_store_byte_identical": byte_identical,
            "policy": (
                "The model may decode an exact typed subset of the frozen "
                "truth-free atomic Node/Road members. Label truth never adds "
                "an inference member."
            ),
        },
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"] = {
        "source_anchor_store_manifest": {
            "path": str((source_root / "manifest.json").resolve()),
            "sha256": sha256_file(source_root / "manifest.json"),
        },
        "anchor_member_supervision_summary": {
            "path": str(summary_path.resolve()),
            "sha256": sha256_file(summary_path),
        },
    }
    _write_json(manifest_path, manifest)
    return root


def _candidate_member_indices(
    candidate_id: str,
    member_index: Mapping[str, int],
) -> tuple[int, ...]:
    object_type, separator, payload = str(candidate_id).partition(":")
    if not separator or object_type not in {"NODE", "ROAD"}:
        return ()
    member_ids = tuple(
        f"{object_type}:{value}"
        for value in payload.split("|")
        if value
    )
    if not member_ids or any(value not in member_index for value in member_ids):
        return ()
    return tuple(sorted({member_index[value] for value in member_ids}))


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "AnchorKey",
    "MemberOption",
    "apply_anchor_member_supervision",
    "write_anchor_member_supervision_store",
]
