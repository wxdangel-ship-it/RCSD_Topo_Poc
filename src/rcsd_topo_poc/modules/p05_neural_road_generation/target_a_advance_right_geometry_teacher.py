from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyproj import CRS
from shapely.geometry import Point
from shapely.ops import nearest_points

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _read_crs,
    _read_roads,
    _resolve_case_paths,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    AUTOMATIC_PLAN_TYPES,
    read_advance_right_conditioned_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class GeometryRoad:
    road_id: str
    start_node_id: str
    end_node_id: str
    geometry: Any


def build_advance_right_geometry_teacher_labels(
    *,
    conditioned_store_root: Path,
    enriched_attachment_store_root: Path,
    target_label_root: Path,
    poc_data_root: Path,
    output_root: Path,
    max_teacher_gap_m: float = 5.0,
) -> Path:
    """Replay T06 geometry only as a low-weight conditional teacher."""
    if max_teacher_gap_m <= 0:
        raise ValueError("teacher gap must be positive")
    conditioned_root = normalize_runtime_path(
        conditioned_store_root
    ).resolve(strict=True)
    attachment_root = normalize_runtime_path(
        enriched_attachment_store_root
    ).resolve(strict=True)
    label_root = normalize_runtime_path(target_label_root).resolve(strict=True)
    data_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    examples = read_advance_right_conditioned_examples(conditioned_root)
    attachment_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in _read_jsonl(
            attachment_root / "advance_right_attachment_labels.jsonl"
        )
    }
    case_rows = {
        str(row["case_key"]): row
        for row in _read_jsonl(label_root / "case_inventory.jsonl")
    }
    road_stores: dict[str, dict[str, GeometryRoad]] = {}
    inference_inputs = []
    for case_key in sorted({str(row["case_key"]) for row in examples}):
        paths, _ = _resolve_case_paths(
            baseline_root=label_root,
            case_row=case_rows[case_key],
            poc_data_root=data_root,
        )
        crs_values = {
            _read_crs(paths.t01_roads),
            _read_crs(paths.raw_rcsd_roads),
        }
        if len(crs_values) != 1 or not _metric_projected(next(iter(crs_values))):
            raise ValueError(f"teacher CRS is not one metric CRS: {case_key}")
        records = [
            *_read_roads(paths.t01_roads),
            *_read_roads(paths.raw_rcsd_roads),
        ]
        roads: dict[str, GeometryRoad] = {}
        for road in records:
            value = GeometryRoad(
                road_id=road.road_id,
                start_node_id=road.snodeid,
                end_node_id=road.enodeid,
                geometry=road.geometry,
            )
            existing = roads.get(value.road_id)
            if existing is not None and not existing.geometry.equals(
                value.geometry
            ):
                raise ValueError(
                    f"teacher Road id has two geometries: {case_key}:{value.road_id}"
                )
            roads[value.road_id] = value
        road_stores[case_key] = roads
        for role, path in (
            ("T01_ROADS", paths.t01_roads),
            ("RAW_RCSD_ROADS", paths.raw_rcsd_roads),
        ):
            inference_inputs.append(
                {
                    "case_key": case_key,
                    "path": str(path.resolve()),
                    "role": role,
                    "sha256": sha256_file(path),
                }
            )

    counts: Counter[str] = Counter()
    labels = []
    for example in examples:
        case_key = str(example["case_key"])
        object_id = str(example["object_id"])
        key = (case_key, object_id)
        roads = road_stores[case_key]
        variants = []
        if (
            str(example["truth_plan_type"]) in AUTOMATIC_PLAN_TYPES
            and bool(example["candidate_supervised"])
        ):
            variants = _teacher_variants(
                example,
                roads=roads,
                max_gap_m=max_teacher_gap_m,
            )
        complete_variants = [
            row for row in variants if bool(row["teacher_complete"])
        ]
        formal_attachment = attachment_by_key[key]
        formal_matches = [
            _formal_attachment_match(
                variant,
                example=example,
                attachment=formal_attachment,
            )
            for variant in complete_variants
        ]
        formal_match = any(formal_matches)
        weight = 0.7 if formal_match else 0.3
        if str(example["truth_plan_type"]) not in AUTOMATIC_PLAN_TYPES:
            state = "FALLBACK_NOT_APPLICABLE"
        elif not bool(example["candidate_supervised"]):
            state = "AUTOMATIC_PLAN_UNSUPERVISED"
        elif complete_variants:
            state = "COMPLETE"
        else:
            state = "UNREACHABLE"
        counts[state] += 1
        counts["formal_match"] += int(formal_match)
        counts["variant"] += len(variants)
        counts["complete_variant"] += len(complete_variants)
        labels.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": case_key,
                "object_id": object_id,
                "fold": int(example["fold"]),
                "conditional_plan_type": str(example["truth_plan_type"]),
                "teacher_state": state,
                "teacher_task_mask": state == "COMPLETE",
                "teacher_label_weight": weight,
                "max_teacher_gap_m": max_teacher_gap_m,
                "formal_t06_action_match": formal_match,
                "variants": variants,
                "label_only": True,
                "inference_input_allowed": False,
                "terminal_feature_count": 0,
            }
        )
    labels.sort(key=lambda row: (row["case_key"], row["object_id"]))
    label_path = root / "advance_right_geometry_teacher_labels.jsonl"
    _write_jsonl(label_path, labels)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_CONDITIONAL_GEOMETRY_TEACHER",
        "scope": (
            "Label-only replay over the ordinary OOF locked Road plans. "
            "Inference never calls this teacher."
        ),
        "label_policy": {
            "formal_t06_action_match": 0.7,
            "conditional_geometry_replay": 0.3,
            "unreachable": 0.0,
        },
        "output_contract": (
            "RCSD_ONLY variants contain source and target endpoint-to-ordinary "
            "Road attachments. MIXED_SPLICE variants contain the RCSD-side "
            "attachment plus the closest RCSD/SWSD splice positions. "
            "SWSD_ONLY requires no new geometric action."
        ),
        "object_count": len(labels),
        "counts": dict(sorted(counts.items())),
        "max_teacher_gap_m": max_teacher_gap_m,
        "crs_consistent": True,
        "crs_metric": True,
        "silent_fix": False,
        "feature_uses_truth": False,
        "inference_terminal_feature_count": 0,
        "inputs": {
            "conditioned_summary": _input_record(
                conditioned_root / "summary.json"
            ),
            "enriched_attachment_summary": _input_record(
                attachment_root / "summary.json"
            ),
            "inference_road_inputs": inference_inputs,
            "label_only_attachment": _input_record(
                attachment_root / "advance_right_attachment_labels.jsonl"
            ),
        },
        "labels": _input_record(label_path),
        "gate_pass": len(labels) == 474,
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight geometry teacher coverage differs")
    return root


def build_rcsd_only_geometry_variant(
    selected_road_ids: Sequence[str],
    *,
    source_plan_road_ids: Sequence[str],
    target_plan_road_ids: Sequence[str],
    roads: Mapping[str, GeometryRoad],
    max_gap_m: float,
) -> dict[str, Any]:
    boundaries = _boundary_endpoints(selected_road_ids, roads)
    source_targets = _roads(source_plan_road_ids, roads)
    target_targets = _roads(target_plan_road_ids, roads)
    choices = []
    for source_endpoint in boundaries:
        source_attachment = _endpoint_attachment(
            source_endpoint,
            source_targets,
        )
        for target_endpoint in boundaries:
            if target_endpoint[:2] == source_endpoint[:2]:
                continue
            target_attachment = _endpoint_attachment(
                target_endpoint,
                target_targets,
            )
            choices.append(
                (
                    source_attachment["gap_m"]
                    + target_attachment["gap_m"],
                    source_attachment,
                    target_attachment,
                )
            )
    if not choices:
        return {"teacher_complete": False, "reason": "BOUNDARY_ASSIGNMENT_MISSING"}
    _, source, target = min(
        choices,
        key=lambda row: (
            row[0],
            row[1]["selected_rcsd_road_id"],
            row[1]["selected_endpoint_index"],
            row[2]["selected_rcsd_road_id"],
            row[2]["selected_endpoint_index"],
        ),
    )
    complete = max(source["gap_m"], target["gap_m"]) <= max_gap_m
    return {
        "teacher_complete": complete,
        "reason": "OK" if complete else "ATTACHMENT_GAP_EXCEEDS_LIMIT",
        "source_attachment": source,
        "target_attachment": target,
        "middle_splice": None,
    }


def build_mixed_geometry_variant(
    selected_road_ids: Sequence[str],
    *,
    rcsd_side: str,
    rcsd_plan_road_ids: Sequence[str],
    fixed_swsd_road_ids: Sequence[str],
    roads: Mapping[str, GeometryRoad],
    max_gap_m: float,
) -> dict[str, Any]:
    boundaries = _boundary_endpoints(selected_road_ids, roads)
    target_roads = _roads(rcsd_plan_road_ids, roads)
    attachments = [
        _endpoint_attachment(endpoint, target_roads)
        for endpoint in boundaries
    ]
    if not attachments:
        return {"teacher_complete": False, "reason": "RCSD_ATTACHMENT_MISSING"}
    attachment = min(
        attachments,
        key=lambda row: (
            row["gap_m"],
            row["selected_rcsd_road_id"],
            row["selected_endpoint_index"],
        ),
    )
    splice = _closest_splice(
        _roads(selected_road_ids, roads),
        _roads(fixed_swsd_road_ids, roads),
    )
    complete = (
        attachment["gap_m"] <= max_gap_m
        and splice["gap_m"] <= max_gap_m
    )
    return {
        "teacher_complete": complete,
        "reason": "OK" if complete else "MIXED_GEOMETRY_GAP_EXCEEDS_LIMIT",
        "rcsd_attachment_side": rcsd_side,
        "source_attachment": attachment if rcsd_side == "source" else None,
        "target_attachment": attachment if rcsd_side == "target" else None,
        "middle_splice": splice,
    }


def _teacher_variants(
    example: Mapping[str, Any],
    *,
    roads: Mapping[str, GeometryRoad],
    max_gap_m: float,
) -> list[dict[str, Any]]:
    plan_type = str(example["truth_plan_type"])
    groups = [
        list(values) for values in example["acceptable_candidate_groups"]
    ]
    combinations = (
        list(itertools.product(*groups)) if groups else [()]
    )
    source = example["source_context"]
    target = example["target_context"]
    fixed_swsd = list(example["fixed_swsd_road_ids"])
    result = []
    for selected in combinations:
        selected_ids = tuple(sorted(str(value) for value in selected))
        if plan_type == "SWSD_ONLY":
            geometry = {
                "teacher_complete": bool(fixed_swsd),
                "reason": "OK" if fixed_swsd else "FROZEN_SWSD_PLAN_MISSING",
                "source_attachment": None,
                "target_attachment": None,
                "middle_splice": None,
            }
        elif plan_type == "RCSD_ONLY":
            geometry = build_rcsd_only_geometry_variant(
                selected_ids,
                source_plan_road_ids=[
                    row["road_id"] for row in source["road_members"]
                ],
                target_plan_road_ids=[
                    row["road_id"] for row in target["road_members"]
                ],
                roads=roads,
                max_gap_m=max_gap_m,
            )
        elif plan_type == "MIXED_SPLICE":
            rcsd_side = (
                "source"
                if str(source["data_source"]) == "RCSD"
                else "target"
            )
            rcsd_context = source if rcsd_side == "source" else target
            geometry = build_mixed_geometry_variant(
                selected_ids,
                rcsd_side=rcsd_side,
                rcsd_plan_road_ids=[
                    row["road_id"] for row in rcsd_context["road_members"]
                ],
                fixed_swsd_road_ids=fixed_swsd,
                roads=roads,
                max_gap_m=max_gap_m,
            )
        else:
            continue
        result.append(
            {
                "variant_id": _variant_id(selected_ids, geometry),
                "selected_rcsd_candidate_road_ids": list(selected_ids),
                "fixed_swsd_road_ids": sorted(fixed_swsd),
                **geometry,
            }
        )
    return result


def _boundary_endpoints(
    selected_road_ids: Sequence[str],
    roads: Mapping[str, GeometryRoad],
) -> list[tuple[str, int, Point]]:
    selected = _roads(selected_road_ids, roads)
    degrees: Counter[str] = Counter()
    for road in selected:
        degrees[road.start_node_id] += 1
        degrees[road.end_node_id] += 1
    endpoints = [
        (
            road.road_id,
            index,
            Point(
                list(road.geometry.coords)[0 if index == 0 else -1]
            ),
        )
        for road in selected
        for index, node_id in (
            (0, road.start_node_id),
            (1, road.end_node_id),
        )
        if degrees[node_id] == 1
    ]
    if endpoints:
        return endpoints
    return [
        (
            road.road_id,
            index,
            Point(list(road.geometry.coords)[0 if index == 0 else -1]),
        )
        for road in selected
        for index in (0, 1)
    ]


def _endpoint_attachment(
    endpoint: tuple[str, int, Point],
    target_roads: Sequence[GeometryRoad],
) -> dict[str, Any]:
    if not target_roads:
        raise ValueError("attachment target Road set is empty")
    selected_road_id, endpoint_index, point = endpoint
    choices = []
    for target in target_roads:
        projected = target.geometry.interpolate(target.geometry.project(point))
        gap = float(point.distance(projected))
        fraction = (
            float(target.geometry.project(point)) / float(target.geometry.length)
            if float(target.geometry.length) > 0
            else 0.0
        )
        choices.append((gap, target.road_id, fraction, projected))
    gap, target_id, fraction, projected = min(
        choices,
        key=lambda row: (row[0], row[1]),
    )
    return {
        "selected_rcsd_road_id": selected_road_id,
        "selected_endpoint_index": endpoint_index,
        "target_ordinary_road_id": target_id,
        "target_fraction": min(max(fraction, 0.0), 1.0),
        "gap_m": gap,
        "operation": (
            "REUSE_ENDPOINT"
            if fraction <= 1e-6 or fraction >= 1.0 - 1e-6
            else "SPLIT_ROAD"
        ),
        "projected_x": float(projected.x),
        "projected_y": float(projected.y),
    }


def _closest_splice(
    rcsd_roads: Sequence[GeometryRoad],
    swsd_roads: Sequence[GeometryRoad],
) -> dict[str, Any]:
    if not rcsd_roads or not swsd_roads:
        raise ValueError("splice Road sets must be nonempty")
    choices = []
    for rcsd in rcsd_roads:
        for swsd in swsd_roads:
            rcsd_point, swsd_point = nearest_points(
                rcsd.geometry,
                swsd.geometry,
            )
            gap = float(rcsd_point.distance(swsd_point))
            rcsd_fraction = _fraction(rcsd.geometry, rcsd_point)
            swsd_fraction = _fraction(swsd.geometry, swsd_point)
            choices.append(
                (
                    gap,
                    rcsd.road_id,
                    swsd.road_id,
                    rcsd_fraction,
                    swsd_fraction,
                    rcsd_point,
                    swsd_point,
                )
            )
    (
        gap,
        rcsd_id,
        swsd_id,
        rcsd_fraction,
        swsd_fraction,
        rcsd_point,
        swsd_point,
    ) = min(choices, key=lambda row: (row[0], row[1], row[2]))
    return {
        "rcsd_road_id": rcsd_id,
        "swsd_road_id": swsd_id,
        "rcsd_fraction": rcsd_fraction,
        "swsd_fraction": swsd_fraction,
        "gap_m": gap,
        "rcsd_x": float(rcsd_point.x),
        "rcsd_y": float(rcsd_point.y),
        "swsd_x": float(swsd_point.x),
        "swsd_y": float(swsd_point.y),
    }


def _formal_attachment_match(
    variant: Mapping[str, Any],
    *,
    example: Mapping[str, Any],
    attachment: Mapping[str, Any],
) -> bool:
    matches = []
    for side in ("source", "target"):
        teacher = variant.get(f"{side}_attachment")
        context = example[f"{side}_context"]
        if teacher is None or str(context["data_source"]) != "RCSD":
            continue
        actions = [
            row
            for row in attachment["attachment_actions"]
            if str(row.get("swsd_node_id") or "")
            == str(context["t01_access_node_id"])
            and str(row.get("rcsd_road_id") or "")
        ]
        matches.append(
            len(actions) == 1
            and str(actions[0]["rcsd_road_id"])
            == str(teacher["target_ordinary_road_id"])
        )
    return bool(matches) and all(matches)


def _roads(
    road_ids: Sequence[str],
    store: Mapping[str, GeometryRoad],
) -> list[GeometryRoad]:
    result = []
    for road_id in road_ids:
        value = store.get(str(road_id))
        if value is None:
            raise ValueError(f"teacher Road geometry is missing: {road_id}")
        result.append(value)
    return result


def _fraction(geometry: Any, point: Point) -> float:
    length = float(geometry.length)
    if length <= 0:
        return 0.0
    return min(max(float(geometry.project(point)) / length, 0.0), 1.0)


def _variant_id(
    selected_ids: Sequence[str],
    geometry: Mapping[str, Any],
) -> str:
    payload = json.dumps(
        {
            "selected_ids": list(selected_ids),
            "geometry": geometry,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "arg:" + hashlib.sha256(payload).hexdigest()[:20]


def _metric_projected(value: str) -> bool:
    crs = CRS.from_user_input(value)
    return crs.is_projected and all(
        str(axis.unit_name or "").lower() in {"metre", "meter"}
        for axis in crs.axis_info[:2]
    )


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "GeometryRoad",
    "build_advance_right_geometry_teacher_labels",
    "build_mixed_geometry_variant",
    "build_rcsd_only_geometry_variant",
]
