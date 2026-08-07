from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def build_access_collection_label_store(
    *,
    ordinary_access_store_root: Path,
    output_root: Path,
    run_id: str,
    max_acceptable_collections: int = 256,
) -> Path:
    """Convert label-only access Road targets into complete set supervision."""
    if max_acceptable_collections <= 0:
        raise ValueError("max acceptable collection count must be positive")
    started = time.perf_counter()
    source_root = normalize_runtime_path(ordinary_access_store_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve(strict=False) / run_id
    root.mkdir(parents=True, exist_ok=False)
    source_label_path = source_root / "ordinary_access_training_labels.jsonl"
    source_summary_path = source_root / "summary.json"
    source_summary = json.loads(
        source_summary_path.read_text(encoding="utf-8-sig")
    )
    source_rows = _read_jsonl(source_label_path)

    counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for source in source_rows:
        row = derive_access_collection_label(
            source,
            max_acceptable_collections=max_acceptable_collections,
        )
        rows.append(row)
        counts["object"] += 1
        counts["source_task"] += int(bool(source.get("access_task_mask")))
        counts["collection_task"] += int(bool(row["collection_task_mask"]))
        counts["multi_element"] += int(
            len(row["required_final_road_ids"]) > 1
        )
        counts["multi_solution"] += int(
            len(row["acceptable_access_collections"]) > 1
        )
        counts[f"state_{row['collection_label_state']}"] += 1
        counts["required_final_road"] += len(
            row["required_final_road_ids"]
        )
        counts["acceptable_collection"] += len(
            row["acceptable_access_collections"]
        )

    label_path = root / "ordinary_access_collection_labels.jsonl"
    _write_jsonl(label_path, rows)
    referenced_feature_records = []
    for name in (
        "ordinary_access_conditioned_candidates.jsonl",
        "ordinary_access_inference_candidates.jsonl",
    ):
        source_path = source_root / name
        if source_path.exists():
            referenced_feature_records.append(
                _manifest_record_for_path(source_summary, source_path)
                or _input_record(source_path)
            )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ACCESS_COLLECTION_LABELS",
        "run_id": run_id,
        "business_contract": {
            "ordinary_access": (
                "one frozen Junction-Segment access outputs the complete "
                "Road/Node set; different final Roads are jointly required"
            ),
            "multi_solution": (
                "only alternative source explanations covering the same "
                "final Road are interchangeable"
            ),
            "advance_right": (
                "AdvanceRight may later select one parent Road/position only "
                "when an RCSD side attachment requires it"
            ),
            "leakage": (
                "collection labels are terminal truth and are never copied "
                "into inference features"
            ),
        },
        "max_acceptable_collections": max_acceptable_collections,
        "counts": dict(sorted(counts.items())),
        "gate_pass": (
            len(rows) == len(source_rows)
            and counts["collection_task"] <= counts["source_task"]
            and all(bool(row.get("label_only")) for row in rows)
            and all(
                not bool(row.get("inference_input_allowed")) for row in rows
            )
        ),
        "inputs": {
            "ordinary_access_labels": _input_record(source_label_path),
            "ordinary_access_summary": _input_record(source_summary_path),
        },
        "outputs": {
            "collection_labels": _input_record(label_path),
            "referenced_inference_features": referenced_feature_records,
        },
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary access collection label gate failed")
    return root


def derive_access_collection_label(
    source: Mapping[str, Any],
    *,
    max_acceptable_collections: int = 256,
) -> dict[str, Any]:
    targets = [
        _normalized_target(row)
        for row in source.get("acceptable_access_targets") or ()
    ]
    source_task = bool(source.get("access_task_mask"))
    collections: list[tuple[int, ...]] = []
    overflow = False
    state = str(source.get("label_state") or "")
    if targets:
        collections, overflow = _exact_cover_collections(
            targets,
            max_collection_count=max_acceptable_collections,
        )
        if overflow:
            state = "COLLECTION_ALTERNATIVE_OVERFLOW"
        elif collections:
            state = "RESOLVED_COMPLETE_ACCESS_COLLECTION"
        else:
            state = "COLLECTION_EXACT_COVER_UNREACHABLE"

    acceptable_collections = [
        _collection_payload(
            indices,
            targets=targets,
            case_key=str(source.get("case_key") or ""),
            segment_id=str(source.get("segment_id") or ""),
            junction_id=str(source.get("junc_node_id") or ""),
        )
        for indices in collections
    ]
    required_final_road_ids = sorted(
        {
            road_id
            for target in targets
            for road_id in target["final_road_ids"]
        }
    )
    required_final_node_ids = sorted(
        {
            node_id
            for target in targets
            for node_id in target["final_access_node_ids"]
        }
    )
    task_mask = (
        source_task
        and bool(acceptable_collections)
        and not overflow
    )
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": str(source.get("case_key") or ""),
        "segment_id": str(source.get("segment_id") or ""),
        "junction_id": str(source.get("junc_node_id") or ""),
        "fold": int(source.get("fold") or 0),
        "truth_decision": str(source.get("truth_decision") or ""),
        "collection_label_state": state,
        "collection_task_mask": task_mask,
        "collection_label_weight": (
            float(source.get("access_label_weight") or 0.0)
            if task_mask
            else 0.0
        ),
        "required_final_road_ids": required_final_road_ids,
        "required_final_access_node_ids": required_final_node_ids,
        "acceptable_access_collections": acceptable_collections,
        "source_target_count": len(targets),
        "acceptable_collection_count": len(acceptable_collections),
        "manual_review_required": bool(
            source.get("manual_review_required")
        )
        or (source_task and not task_mask),
        "source_label_state": str(source.get("label_state") or ""),
        "label_only": True,
        "inference_input_allowed": False,
    }


def _exact_cover_collections(
    targets: Sequence[Mapping[str, Any]],
    *,
    max_collection_count: int,
) -> tuple[list[tuple[int, ...]], bool]:
    cover_sets = [
        frozenset(str(value) for value in row["final_road_ids"])
        for row in targets
    ]
    if any(not values for values in cover_sets):
        return [], False
    universe = frozenset().union(*cover_sets)
    by_final_road = {
        road_id: tuple(
            index
            for index, covered in enumerate(cover_sets)
            if road_id in covered
        )
        for road_id in universe
    }
    results: list[tuple[int, ...]] = []
    overflow = False

    def search(
        covered: frozenset[str],
        selected: tuple[int, ...],
    ) -> None:
        nonlocal overflow
        if overflow:
            return
        if covered == universe:
            results.append(tuple(sorted(selected)))
            if len(results) > max_collection_count:
                overflow = True
            return
        uncovered = universe - covered
        pivot = min(
            uncovered,
            key=lambda value: (len(by_final_road[value]), value),
        )
        for index in by_final_road[pivot]:
            target_cover = cover_sets[index]
            if target_cover & covered:
                continue
            search(covered | target_cover, selected + (index,))

    search(frozenset(), ())
    if overflow:
        return [], True
    return sorted(set(results)), False


def _normalized_target(source: Mapping[str, Any]) -> dict[str, Any]:
    proposal_id = str(source.get("proposal_id") or "")
    road_id = str(source.get("road_id") or "")
    final_road_ids = sorted(
        {str(value) for value in source.get("final_road_ids") or () if str(value)}
    )
    if not proposal_id or not road_id or not final_road_ids:
        raise ValueError("access collection target identity/coverage is incomplete")
    return {
        "proposal_id": proposal_id,
        "road_id": road_id,
        "target_fraction": float(source.get("target_fraction") or 0.0),
        "target_operation": str(source.get("target_operation") or ""),
        "access_business_role": str(
            source.get("access_business_role") or ""
        ),
        "source_lineage": str(source.get("source_lineage") or ""),
        "final_road_ids": final_road_ids,
        "final_access_node_ids": sorted(
            {
                str(value)
                for value in source.get("final_access_node_ids") or ()
                if str(value)
            }
        ),
    }


def _collection_payload(
    indices: Sequence[int],
    *,
    targets: Sequence[Mapping[str, Any]],
    case_key: str,
    segment_id: str,
    junction_id: str,
) -> dict[str, Any]:
    selected = [targets[index] for index in indices]
    proposal_ids = sorted(str(row["proposal_id"]) for row in selected)
    final_road_ids = sorted(
        {
            value
            for row in selected
            for value in row["final_road_ids"]
        }
    )
    final_node_ids = sorted(
        {
            value
            for row in selected
            for value in row["final_access_node_ids"]
        }
    )
    return {
        "collection_id": _stable_id(
            case_key,
            segment_id,
            junction_id,
            *proposal_ids,
        ),
        "proposal_ids": proposal_ids,
        "road_ids": sorted(str(row["road_id"]) for row in selected),
        "final_road_ids": final_road_ids,
        "final_access_node_ids": final_node_ids,
        "targets": selected,
    }


def _stable_id(*values: str) -> str:
    payload = json.dumps(
        list(values),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "toa-set:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve(strict=True).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _manifest_record_for_path(
    manifest: Any,
    path: Path,
) -> dict[str, Any] | None:
    expected = path.resolve(strict=True).as_posix()
    if isinstance(manifest, Mapping):
        if (
            str(manifest.get("path") or "") == expected
            and manifest.get("sha256")
            and manifest.get("size_bytes") is not None
        ):
            return {
                "path": expected,
                "sha256": str(manifest["sha256"]),
                "size_bytes": int(manifest["size_bytes"]),
                "integrity_record_reused": True,
            }
        for value in manifest.values():
            found = _manifest_record_for_path(value, path)
            if found is not None:
                return found
    elif isinstance(manifest, Sequence) and not isinstance(
        manifest, (str, bytes)
    ):
        for value in manifest:
            found = _manifest_record_for_path(value, path)
            if found is not None:
                return found
    return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


__all__ = [
    "build_access_collection_label_store",
    "derive_access_collection_label",
]
