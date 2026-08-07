from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    MaterializationError,
    RoadSource,
    SegmentDecision,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
    materialize_target_a_roadgraph,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer_audit import (
    _load_source_graph,
    _single_evidence_path,
    _validate_source_hashes,
    build_t01_fallback_materialization_instructions,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_final_state_materializer_audit(
    *,
    label_store_root: Path,
    ordinary_release_prediction_root: Path,
    advance_right_prediction_root: Path,
    output_root: Path,
    expected_crs: str = "EPSG:3857",
    coordinate_tolerance_m: float = 0.05,
    strict_hashes: bool = True,
) -> Path:
    """Execute the final SWSD-positive subset without changing T01 content."""
    started = time.perf_counter()
    labels = normalize_runtime_path(label_store_root).resolve(strict=True)
    ordinary_root = normalize_runtime_path(
        ordinary_release_prediction_root
    ).resolve(strict=True)
    advance_root = normalize_runtime_path(
        advance_right_prediction_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    ordinary_path = (
        ordinary_root / "ensemble_gated_oof_predictions.jsonl"
    )
    advance_path = advance_root / "oof_predictions.jsonl"
    ordinary_by_case = _predictions_by_case(
        _jsonl_rows(ordinary_path),
        id_field="segment_id",
    )
    advance_by_case = _predictions_by_case(
        _jsonl_rows(advance_path),
        id_field="object_id",
    )
    inventory = list(_jsonl_rows(labels / "case_inventory.jsonl"))
    case_rows = []
    counts: Counter[str] = Counter()
    hard_failures = []
    for inventory_row in sorted(
        inventory,
        key=lambda row: str(row["case_key"]),
    ):
        case_started = time.perf_counter()
        skeleton_path = labels / str(inventory_row["frozen_skeleton"])
        skeleton = _read_json(skeleton_path)
        case_key = str(skeleton["case_key"])
        frozen_segment_ids = {
            str(row["segment_id"])
            for row in skeleton.get("segments") or ()
        }
        roads_path = _single_evidence_path(skeleton, "t01_roads")
        nodes_path = roads_path.with_name("nodes.gpkg")
        _validate_source_hashes(
            skeleton,
            roads_path=roads_path,
            nodes_path=nodes_path,
            strict_hashes=strict_hashes,
        )
        source_roads, source_nodes, unusable_roads = _load_source_graph(
            roads_path,
            nodes_path,
        )
        (
            fallback_plans,
            access_contracts,
            blockers,
        ) = build_t01_fallback_materialization_instructions(
            skeleton,
            source_roads=source_roads,
            source_nodes=source_nodes,
        )
        fallback_by_segment = {
            row.segment_id: row for row in fallback_plans
        }
        ordinary_predictions = ordinary_by_case.get(case_key, {})
        advance_predictions = advance_by_case.get(case_key, {})
        plans = []
        positive_ordinary = []
        positive_advance = []
        preflight = []
        for segment_id, fallback in sorted(fallback_by_segment.items()):
            if fallback.segment_type is SegmentMaterializationType.STANDARD:
                prediction = ordinary_predictions.get(segment_id)
                instruction, status = _ordinary_instruction(
                    fallback,
                    prediction=prediction,
                )
                if status == "POSITIVE_KEEP_SWSD":
                    positive_ordinary.append(segment_id)
                elif status.startswith("PREFLIGHT_"):
                    preflight.append((segment_id, status))
            else:
                prediction = advance_predictions.get(segment_id)
                instruction, status = _advance_right_instruction(
                    fallback,
                    prediction=prediction,
                )
                if status == "POSITIVE_ADVANCE_RIGHT_SWSD":
                    positive_advance.append(segment_id)
                elif status.startswith("PREFLIGHT_"):
                    preflight.append((segment_id, status))
            plans.append(instruction)

        materializable_ids = set(fallback_by_segment)
        for segment_id, prediction in ordinary_predictions.items():
            if bool(prediction.get("automatic")) and (
                segment_id not in materializable_ids
            ):
                preflight.append(
                    (segment_id, "PREFLIGHT_FROZEN_PLAN_UNMATERIALIZABLE")
                )
        for segment_id, prediction in advance_predictions.items():
            if bool(prediction.get("automatic_decision")) and (
                segment_id not in materializable_ids
            ):
                preflight.append(
                    (segment_id, "PREFLIGHT_FROZEN_PLAN_UNMATERIALIZABLE")
                )

        try:
            graph = materialize_target_a_roadgraph(
                frozen_segment_ids=sorted(materializable_ids),
                frozen_access_contracts=access_contracts,
                segment_instructions=plans,
                source_roads=source_roads,
                source_nodes=source_nodes,
                expected_crs=expected_crs,
                coordinate_tolerance_m=coordinate_tolerance_m,
            )
            hard_failure = ""
        except (MaterializationError, KeyError, ValueError) as exc:
            graph = None
            hard_failure = str(exc)
            hard_failures.append((case_key, hard_failure))

        automatic_advance_requested = sum(
            bool(row.get("automatic_decision"))
            for row in advance_predictions.values()
        )
        counts["case"] += 1
        counts["frozen_segment"] += len(frozen_segment_ids)
        counts["materializable_segment"] += len(materializable_ids)
        counts["blocked_segment"] += len(blockers)
        counts["source_unusable_road"] += len(unusable_roads)
        counts["positive_ordinary_keep"] += len(positive_ordinary)
        counts["positive_advance_right_swsd"] += len(positive_advance)
        counts[
            "automatic_advance_right_requested"
        ] += automatic_advance_requested
        counts["preflight_fallback"] += len(preflight)
        counts["hard_failure_case"] += int(bool(hard_failure))
        if graph is not None:
            counts["materialized_road"] += len(graph.roads)
            counts["materialized_node"] += len(graph.nodes)
            counts["materialized_attachment"] += len(graph.attachments)
            counts["skeleton_mutation"] += graph.skeleton_mutation_count
            counts["silent_fix"] += int(graph.silent_fix)
            counts["content_repair"] += int(graph.content_repair)
        case_rows.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "frozen_segment_count": len(frozen_segment_ids),
                "materializable_segment_count": len(materializable_ids),
                "blocked_segments": [
                    {
                        "segment_id": row.segment_id,
                        "code": row.code,
                        "detail": row.detail,
                    }
                    for row in blockers
                ],
                "source_unusable_road_ids": sorted(unusable_roads),
                "automatic_advance_right_requested_count": (
                    automatic_advance_requested
                ),
                "positive_advance_right_swsd_ids": sorted(
                    positive_advance
                ),
                "positive_ordinary_keep_ids": sorted(positive_ordinary),
                "preflight_fallbacks": [
                    {"segment_id": segment_id, "reason": reason}
                    for segment_id, reason in sorted(set(preflight))
                ],
                "materialized_road_count": (
                    len(graph.roads) if graph is not None else 0
                ),
                "materialized_node_count": (
                    len(graph.nodes) if graph is not None else 0
                ),
                "materialized_attachment_count": (
                    len(graph.attachments) if graph is not None else 0
                ),
                "skeleton_mutation_count": (
                    graph.skeleton_mutation_count
                    if graph is not None
                    else 0
                ),
                "silent_fix": bool(graph and graph.silent_fix),
                "content_repair": bool(graph and graph.content_repair),
                "hard_failure": hard_failure,
                "input_sha256": {
                    "frozen_skeleton": sha256_file(skeleton_path),
                    "t01_roads": sha256_file(roads_path),
                    "t01_nodes": sha256_file(nodes_path),
                },
                "wall_seconds": time.perf_counter() - case_started,
            }
        )

    requested = counts["automatic_advance_right_requested"]
    released = counts["positive_advance_right_swsd"]
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "TARGET_A_FINAL_STATE_MATERIALIZER_AUDIT",
        "business_contract": {
            "automatic_swsd": (
                "An accepted SWSD_ONLY prediction reclassifies the exact "
                "validated T01 AdvanceRight fallback recipe as positive KEEP; "
                "Road, Node, attachment and geometry content are unchanged."
            ),
            "ordinary_use": (
                "An ordinary USE_RCSD prediction without a complete executable "
                "Road/access/Node recipe is preflight-rejected to Segment "
                "fallback and is not reported as automatic materialization."
            ),
            "blocker_scope": (
                "A frozen source blocker remains local to its Segment or "
                "directly dependent AdvanceRight; no T01 transitive closure is "
                "used."
            ),
        },
        "counts": dict(sorted(counts.items())),
        "automatic_advance_right_materialization_coverage": (
            released / requested if requested else 0.0
        ),
        "hard_failures": [
            {"case_key": case_key, "detail": detail}
            for case_key, detail in hard_failures
        ],
        "crs": expected_crs,
        "coordinate_tolerance_m": coordinate_tolerance_m,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "silent_fix_count": counts["silent_fix"],
        "content_repair_count": counts["content_repair"],
        "skeleton_mutation_count": counts["skeleton_mutation"],
        "inputs": {
            "label_store_inventory": _input_record(
                labels / "case_inventory.jsonl"
            ),
            "ordinary_predictions": _input_record(ordinary_path),
            "advance_right_predictions": _input_record(advance_path),
        },
        "outputs": {
            "case_audit": _input_record_after_write(
                root / "case_audit.jsonl",
                case_rows,
            )
        },
        "wall_seconds": time.perf_counter() - started,
    }
    summary["gate_pass"] = bool(
        not hard_failures
        and counts["skeleton_mutation"] == 0
        and counts["silent_fix"] == 0
        and counts["content_repair"] == 0
        and released
        + sum(
            1
            for row in case_rows
            for item in row["preflight_fallbacks"]
            if item["segment_id"]
            in advance_by_case.get(row["case_key"], {})
            and bool(
                advance_by_case[row["case_key"]][
                    item["segment_id"]
                ].get("automatic_decision")
            )
        )
        >= requested
    )
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("Target A final-state materializer audit failed")
    return root


def prepare_positive_swsd_instruction(
    fallback: SegmentMaterializationInstruction,
    *,
    selected_road_ids: Sequence[str],
) -> SegmentMaterializationInstruction:
    if not fallback.fallback_applied:
        raise ValueError("positive SWSD requires an executed fallback recipe")
    selected = {str(value) for value in selected_road_ids}
    source_ids = {
        geometry.source_road_id
        for road in fallback.roads
        for geometry in road.geometry_slices
        if geometry.source_kind is RoadSource.SWSD
    }
    if not selected or selected != source_ids:
        raise ValueError("selected SWSD Roads differ from frozen T01 recipe")
    return replace(
        fallback,
        decision=SegmentDecision.KEEP_SWSD,
        fallback_applied=False,
    )


def _ordinary_instruction(
    fallback: SegmentMaterializationInstruction,
    *,
    prediction: Mapping[str, Any] | None,
) -> tuple[SegmentMaterializationInstruction, str]:
    if not prediction or not bool(prediction.get("automatic")):
        return fallback, "FALLBACK"
    decision = str(prediction.get("predicted_decision") or "")
    if decision != "KEEP_SWSD":
        return fallback, "PREFLIGHT_ORDINARY_EXECUTABLE_RECIPE_MISSING"
    try:
        return (
            prepare_positive_swsd_instruction(
                fallback,
                selected_road_ids=prediction.get("selected_road_ids") or (),
            ),
            "POSITIVE_KEEP_SWSD",
        )
    except ValueError:
        return fallback, "PREFLIGHT_ORDINARY_SWSD_PLAN_MISMATCH"


def _advance_right_instruction(
    fallback: SegmentMaterializationInstruction,
    *,
    prediction: Mapping[str, Any] | None,
) -> tuple[SegmentMaterializationInstruction, str]:
    if not prediction or not bool(prediction.get("automatic_decision")):
        return fallback, "FALLBACK"
    if str(prediction.get("predicted_plan_type") or "") != "SWSD_ONLY":
        return fallback, "PREFLIGHT_ADVANCE_RIGHT_RECIPE_MISSING"
    try:
        return (
            prepare_positive_swsd_instruction(
                fallback,
                selected_road_ids=(
                    prediction.get("raw_selected_fixed_swsd_road_ids") or ()
                ),
            ),
            "POSITIVE_ADVANCE_RIGHT_SWSD",
        )
    except ValueError:
        return fallback, "PREFLIGHT_ADVANCE_RIGHT_SWSD_PLAN_MISMATCH"


def _predictions_by_case(
    rows: Iterable[Mapping[str, Any]],
    *,
    id_field: str,
) -> dict[str, dict[str, Mapping[str, Any]]]:
    result: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        case_key = str(row["case_key"])
        object_id = str(row[id_field])
        if object_id in result[case_key]:
            raise ValueError("final-state predictions contain duplicates")
        result[case_key][object_id] = row
    return dict(result)


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _input_record_after_write(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _write_jsonl(path, rows)
    return _input_record(path)


def _jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True)
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "prepare_positive_swsd_instruction",
    "run_final_state_materializer_audit",
]
