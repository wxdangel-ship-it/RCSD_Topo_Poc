from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg, write_json
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    RestorationResult,
    RoadPair,
    T09ArmMovement,
    T09EvidenceItem,
    T09RestoredFieldRule,
    T09SwsdArm,
    to_jsonable,
)


@dataclass(frozen=True)
class T09OutputArtifacts:
    output_dir: Path
    arms_gpkg: Path
    arms_csv: Path
    arms_json: Path
    movements_gpkg: Path
    movements_csv: Path
    movements_json: Path
    evidence_gpkg: Path
    evidence_csv: Path
    evidence_json: Path
    rules_gpkg: Path
    rules_csv: Path
    rules_json: Path
    summary_json: Path


ARM_FIELDS = [
    "junction_id",
    "arm_id",
    "member_node_ids",
    "internal_road_ids",
    "seed_road_ids",
    "segment_ids",
    "inbound_road_ids",
    "outbound_road_ids",
    "approach_road_ids",
    "exit_road_ids",
    "trunk_road_ids",
    "advance_left_road_ids",
    "angle_deg",
    "terminal_node_id",
    "terminal_kind",
    "build_status",
    "risk_flags",
    "audit_refs",
]

MOVEMENT_FIELDS = [
    "junction_id",
    "movement_id",
    "from_arm_id",
    "to_arm_id",
    "movement_type",
    "movement_applicability",
    "candidate_road_pair_count",
    "carrier_universe_status",
    "prohibition_status",
    "prohibition_reason",
    "prohibition_confidence",
    "evidence_item_ids",
    "risk_flags",
    "carrier_road_pairs",
]

EVIDENCE_FIELDS = [
    "evidence_id",
    "evidence_type",
    "junction_id",
    "movement_id",
    "road_pair",
    "evidence_status",
    "prohibition_reason",
    "inference_level",
    "confidence",
    "supports_prohibition",
    "risk_flags",
    "provenance",
]

RULE_FIELDS = [
    "junction_id",
    "from_arm_id",
    "to_arm_id",
    "movement_type",
    "field_rule_status",
    "rule_scope",
    "supporting_evidence_ids",
    "conflicting_evidence_ids",
    "inference_level",
    "confidence",
    "risk_flags",
]


def write_restoration_outputs(
    *,
    result: RestorationResult,
    output_dir: str | Path,
    road_geometries: dict[str, BaseGeometry],
    segment_geometries: dict[str, BaseGeometry] | None = None,
    crs_text: str = "EPSG:3857",
) -> T09OutputArtifacts:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = T09OutputArtifacts(
        output_dir=out_dir,
        arms_gpkg=out_dir / "t09_swsd_arms.gpkg",
        arms_csv=out_dir / "t09_swsd_arms.csv",
        arms_json=out_dir / "t09_swsd_arms.json",
        movements_gpkg=out_dir / "t09_arm_movements.gpkg",
        movements_csv=out_dir / "t09_arm_movements.csv",
        movements_json=out_dir / "t09_arm_movements.json",
        evidence_gpkg=out_dir / "t09_evidence_items.gpkg",
        evidence_csv=out_dir / "t09_evidence_items.csv",
        evidence_json=out_dir / "t09_evidence_items.json",
        rules_gpkg=out_dir / "t09_restored_field_rules.gpkg",
        rules_csv=out_dir / "t09_restored_field_rules.csv",
        rules_json=out_dir / "t09_restored_field_rules.json",
        summary_json=out_dir / "t09_swsd_field_rule_restoration_summary.json",
    )
    arms_by_id = {arm.arm_id: arm for arm in result.arms}
    movements_by_id = {movement.movement_id: movement for movement in result.movements}

    arm_rows = [_arm_row(arm) for arm in result.arms]
    movement_rows = [_movement_row(movement) for movement in result.movements]
    evidence_rows = [_evidence_row(item) for item in result.evidence_items]
    rule_rows = [_rule_row(rule) for rule in result.restored_rules]
    write_json(artifacts.arms_json, arm_rows)
    write_json(artifacts.movements_json, movement_rows)
    write_json(artifacts.evidence_json, evidence_rows)
    write_json(artifacts.rules_json, rule_rows)
    write_json(artifacts.summary_json, result.summary)
    _write_csv(artifacts.arms_csv, arm_rows, ARM_FIELDS)
    _write_csv(artifacts.movements_csv, movement_rows, MOVEMENT_FIELDS)
    _write_csv(artifacts.evidence_csv, evidence_rows, EVIDENCE_FIELDS)
    _write_csv(artifacts.rules_csv, rule_rows, RULE_FIELDS)
    write_gpkg(
        artifacts.arms_gpkg,
        _arm_features(result.arms, road_geometries, segment_geometries or {}),
        crs_text=crs_text,
        empty_fields=ARM_FIELDS,
        geometry_type="LineString",
    )
    write_gpkg(
        artifacts.movements_gpkg,
        _movement_features(result.movements, arms_by_id, road_geometries),
        crs_text=crs_text,
        empty_fields=MOVEMENT_FIELDS,
        geometry_type="LineString",
    )
    write_gpkg(
        artifacts.evidence_gpkg,
        _evidence_features(result.evidence_items, movements_by_id, arms_by_id, road_geometries),
        crs_text=crs_text,
        empty_fields=EVIDENCE_FIELDS,
        geometry_type="LineString",
    )
    write_gpkg(
        artifacts.rules_gpkg,
        _rule_features(result.restored_rules, result.movements, arms_by_id, road_geometries),
        crs_text=crs_text,
        empty_fields=RULE_FIELDS,
        geometry_type="LineString",
    )
    return artifacts


def _arm_row(arm: T09SwsdArm) -> dict[str, Any]:
    return {field: _csv_jsonable(getattr(arm, field)) for field in ARM_FIELDS}


def _movement_row(movement: T09ArmMovement) -> dict[str, Any]:
    return {field: _csv_jsonable(getattr(movement, field)) for field in MOVEMENT_FIELDS}


def _evidence_row(item: T09EvidenceItem) -> dict[str, Any]:
    return {field: _csv_jsonable(getattr(item, field)) for field in EVIDENCE_FIELDS}


def _rule_row(rule: T09RestoredFieldRule) -> dict[str, Any]:
    return {field: _csv_jsonable(getattr(rule, field)) for field in RULE_FIELDS}


def _arm_features(
    arms: Iterable[T09SwsdArm],
    road_geometries: dict[str, BaseGeometry],
    segment_geometries: dict[str, BaseGeometry],
) -> list[dict[str, Any]]:
    return [
        {"properties": _arm_row(arm), "geometry": _geometry_for_arm(arm, road_geometries, segment_geometries)}
        for arm in arms
    ]


def _movement_features(
    movements: Iterable[T09ArmMovement],
    arms_by_id: dict[str, T09SwsdArm],
    road_geometries: dict[str, BaseGeometry],
) -> list[dict[str, Any]]:
    return [
        {
            "properties": _movement_row(movement),
            "geometry": _geometry_for_movement(movement, arms_by_id, road_geometries),
        }
        for movement in movements
    ]


def _evidence_features(
    evidence_items: Iterable[T09EvidenceItem],
    movements_by_id: dict[str, T09ArmMovement],
    arms_by_id: dict[str, T09SwsdArm],
    road_geometries: dict[str, BaseGeometry],
) -> list[dict[str, Any]]:
    return [
        {
            "properties": _evidence_row(item),
            "geometry": _geometry_for_evidence(item, movements_by_id, arms_by_id, road_geometries),
        }
        for item in evidence_items
    ]


def _rule_features(
    rules: Iterable[T09RestoredFieldRule],
    movements: tuple[T09ArmMovement, ...],
    arms_by_id: dict[str, T09SwsdArm],
    road_geometries: dict[str, BaseGeometry],
) -> list[dict[str, Any]]:
    movement_by_key = {
        (movement.from_arm_id, movement.to_arm_id, movement.movement_type): movement for movement in movements
    }
    return [
        {
            "properties": _rule_row(rule),
            "geometry": _geometry_for_movement(
                movement_by_key.get((rule.from_arm_id, rule.to_arm_id, rule.movement_type)),
                arms_by_id,
                road_geometries,
            ),
        }
        for rule in rules
    ]


def _geometry_for_arm(
    arm: T09SwsdArm,
    road_geometries: dict[str, BaseGeometry],
    segment_geometries: dict[str, BaseGeometry] | None = None,
) -> BaseGeometry:
    segment_geometry = _geometry_for_segments(arm.segment_ids, segment_geometries or {})
    if segment_geometry is not None:
        return segment_geometry
    for road_id in arm.seed_road_ids + arm.trunk_road_ids + arm.connector_road_ids:
        geometry = road_geometries.get(road_id)
        if geometry is not None:
            return _line_geometry(geometry)
    return _fallback_geometry(road_geometries)


def _geometry_for_segments(
    segment_ids: tuple[str, ...],
    segment_geometries: dict[str, BaseGeometry],
) -> BaseGeometry | None:
    lines: list[LineString] = []
    for segment_id in segment_ids:
        geometry = segment_geometries.get(segment_id)
        if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
            lines.append(geometry)
        elif isinstance(geometry, MultiLineString):
            lines.extend(part for part in geometry.geoms if not part.is_empty and len(part.coords) >= 2)
    if len(lines) == 1:
        return lines[0]
    if len(lines) > 1:
        return MultiLineString(lines)
    return None


def _geometry_for_movement(
    movement: T09ArmMovement | None,
    arms_by_id: dict[str, T09SwsdArm],
    road_geometries: dict[str, BaseGeometry],
) -> BaseGeometry:
    if movement is None:
        return _fallback_geometry(road_geometries)
    if movement.carrier_road_pairs:
        return _geometry_for_pair(movement.carrier_road_pairs[0], road_geometries)
    arm = arms_by_id.get(movement.from_arm_id) or arms_by_id.get(movement.to_arm_id)
    if arm is not None:
        return _geometry_for_arm(arm, road_geometries)
    return _fallback_geometry(road_geometries)


def _geometry_for_evidence(
    item: T09EvidenceItem,
    movements_by_id: dict[str, T09ArmMovement],
    arms_by_id: dict[str, T09SwsdArm],
    road_geometries: dict[str, BaseGeometry],
) -> BaseGeometry:
    if item.road_pair is not None:
        return _geometry_for_pair(item.road_pair, road_geometries)
    for token in str(item.provenance.source_id or "").split(","):
        geometry = road_geometries.get(token.strip())
        if geometry is not None:
            return _line_geometry(geometry)
    if item.movement_id and item.movement_id in movements_by_id:
        return _geometry_for_movement(movements_by_id[item.movement_id], arms_by_id, road_geometries)
    for object_id in item.provenance.matched_object_ids:
        geometry = road_geometries.get(str(object_id))
        if geometry is not None:
            return _line_geometry(geometry)
    return _fallback_geometry(road_geometries)


def _geometry_for_pair(pair: RoadPair, road_geometries: dict[str, BaseGeometry]) -> BaseGeometry:
    from_coords = _line_coords(road_geometries.get(pair.from_road_id))
    to_coords = _line_coords(road_geometries.get(pair.to_road_id))
    if len(from_coords) >= 2 and len(to_coords) >= 2:
        coords = list(from_coords)
        if _point_distance(coords[-1], to_coords[0]) <= _point_distance(coords[-1], to_coords[-1]):
            coords.extend(to_coords[1:] if _point_distance(coords[-1], to_coords[0]) <= 1e-8 else to_coords)
        else:
            reversed_to = list(reversed(to_coords))
            coords.extend(reversed_to[1:] if _point_distance(coords[-1], reversed_to[0]) <= 1e-8 else reversed_to)
        return LineString(coords)
    if len(from_coords) >= 2:
        return LineString(from_coords)
    if len(to_coords) >= 2:
        return LineString(to_coords)
    return _fallback_geometry(road_geometries)


def _line_geometry(geometry: BaseGeometry) -> BaseGeometry:
    coords = _line_coords(geometry)
    return LineString(coords) if len(coords) >= 2 else geometry


def _line_coords(geometry: BaseGeometry | None) -> list[tuple[float, float]]:
    if isinstance(geometry, LineString):
        return [(float(x), float(y)) for x, y, *_rest in geometry.coords]
    if isinstance(geometry, MultiLineString):
        parts = [part for part in geometry.geoms if not part.is_empty]
        if not parts:
            return []
        longest = max(parts, key=lambda part: float(part.length))
        return [(float(x), float(y)) for x, y, *_rest in longest.coords]
    return []


def _fallback_geometry(road_geometries: dict[str, BaseGeometry]) -> BaseGeometry:
    for geometry in road_geometries.values():
        coords = _line_coords(geometry)
        if len(coords) >= 2:
            return LineString(coords)
    return LineString([(0.0, 0.0), (1.0, 0.0)])


def _point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_jsonable(value: Any) -> Any:
    value = to_jsonable(value)
    if isinstance(value, dict) and set(value) == {"from_road_id", "to_road_id"}:
        return f"{value['from_road_id']}->{value['to_road_id']}"
    return value


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(to_jsonable(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return str(value)
