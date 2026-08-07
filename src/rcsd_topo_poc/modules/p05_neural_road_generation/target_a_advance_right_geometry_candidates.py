from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from shapely.geometry import Point
from shapely.ops import nearest_points

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _read_crs,
    _read_roads,
    _resolve_case_paths,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_teacher import (
    GeometryRoad,
    _metric_projected,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    read_advance_right_conditioned_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ATTACHMENT_GEOMETRY_FEATURE_NAMES = (
    "gap_log_m",
    "gap_within_1m",
    "gap_within_3m",
    "gap_within_5m",
    "candidate_length_log_m",
    "target_length_log_m",
    "length_ratio_log",
    "selected_endpoint_is_start",
    "selected_endpoint_is_end",
    "side_is_source",
    "side_is_target",
    "target_fraction",
    "target_fraction_to_nearest_end",
    "target_is_endpoint",
    "target_is_interior",
    "candidate_endpoint_degree_one",
    "candidate_tangent_x",
    "candidate_tangent_y",
    "target_tangent_x",
    "target_tangent_y",
    "tangent_cosine",
    "tangent_abs_cosine",
    "cross_offset_signed_tanh",
    "candidate_to_target_distance_log_m",
    "parent_piece_is_source_part",
    "parent_piece_is_target_part",
)

SPLICE_GEOMETRY_FEATURE_NAMES = (
    "gap_log_m",
    "gap_within_1m",
    "gap_within_3m",
    "gap_within_5m",
    "candidate_length_log_m",
    "swsd_length_log_m",
    "length_ratio_log",
    "candidate_fraction",
    "swsd_fraction",
    "candidate_fraction_to_nearest_end",
    "swsd_fraction_to_nearest_end",
    "candidate_is_endpoint",
    "candidate_is_interior",
    "swsd_is_endpoint",
    "swsd_is_interior",
    "candidate_tangent_x",
    "candidate_tangent_y",
    "swsd_tangent_x",
    "swsd_tangent_y",
    "tangent_cosine",
    "tangent_abs_cosine",
    "cross_offset_signed_tanh",
    "candidate_to_swsd_distance_log_m",
    "both_points_are_endpoints",
    "parent_piece_is_source_part",
    "parent_piece_is_target_part",
)


def build_advance_right_geometry_candidates(
    *,
    conditioned_store_root: Path,
    geometry_teacher_root: Path,
    target_label_root: Path,
    poc_data_root: Path,
    output_root: Path,
    require_all_teacher_variants_reachable: bool = True,
) -> Path:
    """Build truth-free position candidates, then attach label-only targets."""
    conditioned_root = normalize_runtime_path(conditioned_store_root).resolve(
        strict=True
    )
    teacher_root = normalize_runtime_path(geometry_teacher_root).resolve(
        strict=True
    )
    label_root = normalize_runtime_path(target_label_root).resolve(strict=True)
    data_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    examples = read_advance_right_conditioned_examples(conditioned_root)
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
            raise ValueError(f"geometry candidate CRS invalid: {case_key}")
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
                    f"Road id has two geometries: {case_key}:{value.road_id}"
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

    proposal_rows = []
    counts: Counter[str] = Counter()
    for example in examples:
        case_key = str(example["case_key"])
        object_id = str(example["object_id"])
        roads = road_stores[case_key]
        candidates = [
            roads[str(row["candidate_road_id"])]
            for row in example["candidate_rows"]
        ]
        candidate_features = {
            str(row["candidate_road_id"]): list(row["feature_values"])
            for row in example["candidate_rows"]
        }
        for side in ("source", "target"):
            context = example[f"{side}_context"]
            if str(context["data_source"]) != "RCSD":
                continue
            for candidate in candidates:
                for endpoint_index in (0, 1):
                    for member in context["road_members"]:
                        target = roads[str(member["road_id"])]
                        rows = _attachment_proposals(
                            case_key=case_key,
                            object_id=object_id,
                            side=side,
                            candidate=candidate,
                            endpoint_index=endpoint_index,
                            target=target,
                            candidate_feature_values=candidate_features[
                                candidate.road_id
                            ],
                            target_member_feature_values=list(
                                member["features"]
                            ),
                        )
                        proposal_rows.extend(rows)
                        counts[f"{side}_attachment"] += len(rows)
        for candidate in candidates:
            for swsd_road_id in example["fixed_swsd_road_ids"]:
                swsd = roads[str(swsd_road_id)]
                proposal_rows.append(
                    _splice_proposal(
                        case_key=case_key,
                        object_id=object_id,
                        candidate=candidate,
                        swsd=swsd,
                        candidate_feature_values=candidate_features[
                            candidate.road_id
                        ],
                    )
                )
                counts["middle_splice"] += 1
    proposal_rows.sort(
        key=lambda row: (
            row["case_key"],
            row["object_id"],
            row["proposal_type"],
            row["proposal_id"],
        )
    )
    proposal_path = root / "advance_right_geometry_inference_candidates.jsonl"
    _write_jsonl(proposal_path, proposal_rows)
    feature_hash_before_label_read = sha256_file(proposal_path)

    proposals_by_object: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for row in proposal_rows:
        key = (str(row["case_key"]), str(row["object_id"]))
        proposals_by_object.setdefault(key, {})[str(row["proposal_id"])] = row
    teacher_rows = _read_jsonl(
        teacher_root / "advance_right_geometry_teacher_labels.jsonl"
    )
    label_rows = []
    label_counts: Counter[str] = Counter()
    for teacher in teacher_rows:
        key = (str(teacher["case_key"]), str(teacher["object_id"]))
        proposals = proposals_by_object.get(key, {})
        variants = []
        for variant in teacher["variants"]:
            if not bool(variant["teacher_complete"]):
                continue
            for option_index, proposal_ids in enumerate(
                _variant_proposal_id_sets(variant)
            ):
                reachable = all(
                    value in proposals for value in proposal_ids
                )
                label_counts["variant"] += 1
                label_counts["variant_reachable"] += int(reachable)
                variants.append(
                    {
                        "variant_id": (
                            f"{variant['variant_id']}:piece:{option_index}"
                        ),
                        "proposal_ids": proposal_ids,
                        "reachable": reachable,
                    }
                )
        task_mask = bool(teacher["teacher_task_mask"]) and any(
            row["reachable"] for row in variants
        )
        label_counts["task_mask"] += int(task_mask)
        label_counts[f"state_{teacher['teacher_state']}"] += 1
        label_rows.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": key[0],
                "object_id": key[1],
                "fold": int(teacher["fold"]),
                "conditional_plan_type": str(
                    teacher["conditional_plan_type"]
                ),
                "geometry_task_mask": task_mask,
                "geometry_safety_target": task_mask,
                "geometry_safety_weight": float(
                    teacher["teacher_label_weight"]
                ),
                "geometry_label_weight": (
                    float(teacher["teacher_label_weight"]) if task_mask else 0.0
                ),
                "acceptable_geometry_variants": variants,
                "label_only": True,
                "inference_input_allowed": False,
            }
        )
    label_rows.sort(key=lambda row: (row["case_key"], row["object_id"]))
    label_path = root / "advance_right_geometry_training_labels.jsonl"
    _write_jsonl(label_path, label_rows)

    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_CONDITIONAL_GEOMETRY_CANDIDATES",
        "business_contract": {
            "model_decision": (
                "select the AdvanceRight endpoint, adjacent Road and projected "
                "split position; for MIXED_SPLICE also select the RCSD/SWSD "
                "Road pair and splice positions"
            ),
            "deterministic_layer": (
                "execute the selected split/splice fractions and write Node ids"
            ),
            "fallback": (
                "no complete accepted proposal set falls back only the "
                "AdvanceRight Segment"
            ),
        },
        "feature_freeze_before_label_read": True,
        "feature_hash_before_label_read": feature_hash_before_label_read,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "attachment_geometry_feature_names": list(
            ATTACHMENT_GEOMETRY_FEATURE_NAMES
        ),
        "splice_geometry_feature_names": list(SPLICE_GEOMETRY_FEATURE_NAMES),
        "object_count": len(label_rows),
        "proposal_count": len(proposal_rows),
        "proposal_counts": dict(sorted(counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
        "require_all_teacher_variants_reachable": (
            require_all_teacher_variants_reachable
        ),
        "crs_consistent": True,
        "crs_metric": True,
        "silent_fix": False,
        "inputs": {
            "conditioned_summary": _input_record(
                conditioned_root / "summary.json"
            ),
            "teacher_summary": _input_record(teacher_root / "summary.json"),
            "inference_roads": inference_inputs,
        },
        "outputs": {
            "inference_candidates": _input_record(proposal_path),
            "training_labels": _input_record(label_path),
        },
        "gate_pass": (
            len(label_rows) == 474
            and (
                not require_all_teacher_variants_reachable
                or label_counts["variant"]
                == label_counts["variant_reachable"]
            )
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight geometry proposal coverage gate failed")
    return root


def _attachment_proposal(
    *,
    case_key: str,
    object_id: str,
    side: str,
    candidate: GeometryRoad,
    endpoint_index: int,
    target: GeometryRoad,
    candidate_feature_values: Sequence[float],
    target_member_feature_values: Sequence[float],
    parent_piece: str | None = None,
) -> dict[str, Any]:
    point = _endpoint_point(candidate, endpoint_index)
    target_distance = float(target.geometry.project(point))
    projected = target.geometry.interpolate(target_distance)
    target_fraction = _safe_fraction(target_distance, target.geometry.length)
    gap = float(point.distance(projected))
    candidate_tangent = _endpoint_tangent(candidate.geometry, endpoint_index)
    target_tangent = _local_tangent(target.geometry, target_distance)
    cross = _signed_cross(candidate_tangent, point, projected)
    features = _geometry_features(
        gap=gap,
        first_length=float(candidate.geometry.length),
        second_length=float(target.geometry.length),
        first_fraction=float(endpoint_index),
        second_fraction=target_fraction,
        first_tangent=candidate_tangent,
        second_tangent=target_tangent,
        cross_offset=cross,
        attachment_side=side,
        endpoint_index=endpoint_index,
    )
    operation = (
        "REUSE_ENDPOINT"
        if target_fraction <= 1e-6 or target_fraction >= 1.0 - 1e-6
        else "SPLIT_ROAD"
    )
    if operation == "REUSE_ENDPOINT" and parent_piece is not None:
        raise ValueError("endpoint attachment cannot select a parent piece")
    if parent_piece not in {None, "SOURCE_PART", "TARGET_PART"}:
        raise ValueError("attachment parent piece is unsupported")
    features.extend(
        [
            float(parent_piece == "SOURCE_PART"),
            float(parent_piece == "TARGET_PART"),
        ]
    )
    proposal_id = _stable_id(
        "attach",
        side,
        candidate.road_id,
        str(endpoint_index),
        target.road_id,
        parent_piece or "ENDPOINT",
    )
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": case_key,
        "object_id": object_id,
        "proposal_id": proposal_id,
        "proposal_type": f"{side.upper()}_ATTACHMENT",
        "side": side,
        "selected_rcsd_road_id": candidate.road_id,
        "selected_endpoint_index": endpoint_index,
        "target_ordinary_road_id": target.road_id,
        "target_fraction": target_fraction,
        "gap_m": gap,
        "operation": operation,
        "parent_piece": parent_piece,
        "projected_x": float(projected.x),
        "projected_y": float(projected.y),
        "candidate_feature_values": list(candidate_feature_values),
        "target_member_feature_values": list(target_member_feature_values),
        "geometry_feature_values": features,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _attachment_proposals(
    **kwargs: Any,
) -> tuple[dict[str, Any], ...]:
    unbound = _attachment_proposal(**kwargs)
    if unbound["operation"] == "REUSE_ENDPOINT":
        return (unbound,)
    return tuple(
        _attachment_proposal(**kwargs, parent_piece=piece)
        for piece in ("SOURCE_PART", "TARGET_PART")
    )


def _splice_proposal(
    *,
    case_key: str,
    object_id: str,
    candidate: GeometryRoad,
    swsd: GeometryRoad,
    candidate_feature_values: Sequence[float],
) -> dict[str, Any]:
    candidate_point, swsd_point = nearest_points(
        candidate.geometry,
        swsd.geometry,
    )
    candidate_distance = float(candidate.geometry.project(candidate_point))
    swsd_distance = float(swsd.geometry.project(swsd_point))
    candidate_fraction = _safe_fraction(
        candidate_distance,
        candidate.geometry.length,
    )
    swsd_fraction = _safe_fraction(swsd_distance, swsd.geometry.length)
    gap = float(candidate_point.distance(swsd_point))
    candidate_tangent = _local_tangent(
        candidate.geometry,
        candidate_distance,
    )
    swsd_tangent = _local_tangent(swsd.geometry, swsd_distance)
    cross = _signed_cross(candidate_tangent, candidate_point, swsd_point)
    features = _geometry_features(
        gap=gap,
        first_length=float(candidate.geometry.length),
        second_length=float(swsd.geometry.length),
        first_fraction=candidate_fraction,
        second_fraction=swsd_fraction,
        first_tangent=candidate_tangent,
        second_tangent=swsd_tangent,
        cross_offset=cross,
    )
    features.extend([0.0, 0.0])
    proposal_id = _stable_id(
        "splice",
        candidate.road_id,
        swsd.road_id,
    )
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": case_key,
        "object_id": object_id,
        "proposal_id": proposal_id,
        "proposal_type": "MIDDLE_SPLICE",
        "rcsd_road_id": candidate.road_id,
        "swsd_road_id": swsd.road_id,
        "rcsd_fraction": candidate_fraction,
        "swsd_fraction": swsd_fraction,
        "gap_m": gap,
        "rcsd_x": float(candidate_point.x),
        "rcsd_y": float(candidate_point.y),
        "swsd_x": float(swsd_point.x),
        "swsd_y": float(swsd_point.y),
        "candidate_feature_values": list(candidate_feature_values),
        "target_member_feature_values": [0.0] * 24,
        "geometry_feature_values": features,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
    }


def _variant_proposal_id_sets(
    variant: Mapping[str, Any],
) -> list[list[str]]:
    attachment_options: list[list[str]] = [[]]
    for side in ("source", "target"):
        value = variant.get(f"{side}_attachment")
        if value is None:
            continue
        pieces = (
            ("SOURCE_PART", "TARGET_PART")
            if str(value.get("operation") or "") == "SPLIT_ROAD"
            else (None,)
        )
        attachment_options = [
            [
                *existing,
                _stable_id(
                    "attach",
                    side,
                    str(value["selected_rcsd_road_id"]),
                    str(value["selected_endpoint_index"]),
                    str(value["target_ordinary_road_id"]),
                    piece or "ENDPOINT",
                ),
            ]
            for existing in attachment_options
            for piece in pieces
        ]
    splice = variant.get("middle_splice")
    splice_id = (
        _stable_id(
            "splice",
            str(splice["rcsd_road_id"]),
            str(splice["swsd_road_id"]),
        )
        if splice is not None
        else ""
    )
    return [
        [*values, *([splice_id] if splice_id else [])]
        for values in attachment_options
    ]


def _variant_proposal_ids(variant: Mapping[str, Any]) -> list[str]:
    """Compatibility helper returning the first acceptable parent-piece plan."""

    return _variant_proposal_id_sets(variant)[0]


def _stable_id(*values: str) -> str:
    parts = [str(value) for value in values]
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"arg:{digest}"


def _endpoint_point(road: GeometryRoad, endpoint_index: int) -> Point:
    coordinates = list(road.geometry.coords)
    return Point(coordinates[0 if endpoint_index == 0 else -1])


def _safe_fraction(distance: float, length: float) -> float:
    if length <= 0:
        return 0.0
    return min(max(float(distance) / float(length), 0.0), 1.0)


def _endpoint_tangent(geometry: Any, endpoint_index: int) -> tuple[float, float]:
    coordinates = list(geometry.coords)
    if endpoint_index == 0:
        return _unit_vector(coordinates[0], coordinates[min(1, len(coordinates) - 1)])
    return _unit_vector(coordinates[-1], coordinates[max(0, len(coordinates) - 2)])


def _local_tangent(geometry: Any, distance: float) -> tuple[float, float]:
    length = float(geometry.length)
    delta = min(max(length * 0.01, 0.1), 2.0)
    start = geometry.interpolate(max(0.0, distance - delta))
    end = geometry.interpolate(min(length, distance + delta))
    return _unit_vector((start.x, start.y), (end.x, end.y))


def _unit_vector(start: Sequence[float], end: Sequence[float]) -> tuple[float, float]:
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    norm = math.hypot(dx, dy)
    if norm <= 1e-9:
        return 0.0, 0.0
    return dx / norm, dy / norm


def _signed_cross(
    tangent: tuple[float, float],
    first: Point,
    second: Point,
) -> float:
    dx = float(second.x - first.x)
    dy = float(second.y - first.y)
    return tangent[0] * dy - tangent[1] * dx


def _geometry_features(
    *,
    gap: float,
    first_length: float,
    second_length: float,
    first_fraction: float,
    second_fraction: float,
    first_tangent: tuple[float, float],
    second_tangent: tuple[float, float],
    cross_offset: float,
    attachment_side: str | None = None,
    endpoint_index: int | None = None,
) -> list[float]:
    cosine = (
        first_tangent[0] * second_tangent[0]
        + first_tangent[1] * second_tangent[1]
    )
    ratio = math.log1p(first_length) - math.log1p(second_length)
    first_nearest = min(first_fraction, 1.0 - first_fraction)
    second_nearest = min(second_fraction, 1.0 - second_fraction)
    common = [
        math.tanh(math.log1p(max(gap, 0.0)) / 5.0),
        float(gap <= 1.0),
        float(gap <= 3.0),
        float(gap <= 5.0),
        math.tanh(math.log1p(max(first_length, 0.0)) / 8.0),
        math.tanh(math.log1p(max(second_length, 0.0)) / 8.0),
        math.tanh(ratio / 4.0),
    ]
    if attachment_side is not None:
        return [
            *common,
            float(endpoint_index == 0),
            float(endpoint_index == 1),
            float(attachment_side == "source"),
            float(attachment_side == "target"),
            second_fraction,
            second_nearest,
            float(second_nearest <= 1e-6),
            float(second_nearest > 1e-6),
            1.0,
            first_tangent[0],
            first_tangent[1],
            second_tangent[0],
            second_tangent[1],
            cosine,
            abs(cosine),
            math.tanh(cross_offset / 5.0),
            math.tanh(math.log1p(max(gap, 0.0)) / 5.0),
        ]
    return [
        *common,
        first_fraction,
        second_fraction,
        first_nearest,
        second_nearest,
        float(first_nearest <= 1e-6),
        float(first_nearest > 1e-6),
        float(second_nearest <= 1e-6),
        float(second_nearest > 1e-6),
        first_tangent[0],
        first_tangent[1],
        second_tangent[0],
        second_tangent[1],
        cosine,
        abs(cosine),
        math.tanh(cross_offset / 5.0),
        math.tanh(math.log1p(max(gap, 0.0)) / 5.0),
        float(first_nearest <= 1e-6 and second_nearest <= 1e-6),
    ]


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


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
    "ATTACHMENT_GEOMETRY_FEATURE_NAMES",
    "SPLICE_GEOMETRY_FEATURE_NAMES",
    "build_advance_right_geometry_candidates",
]
