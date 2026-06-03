from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, write_gpkg, write_json


FRCSDS_RESTRICTION_STEM = "frcsd_restriction"
FRCSDS_RESTRICTION_SUMMARY = "t09_step3_frcsd_restriction_summary.json"

FRCSDS_RESTRICTION_FIELDS = [
    "restriction_id",
    "CondType",
    "LinkID",
    "inLinkID",
    "outLinkID",
    "junction_id",
    "frcsd_junction_id",
    "from_arm_id",
    "to_arm_id",
    "from_frcsd_arm_id",
    "to_frcsd_arm_id",
    "movement_id",
    "movement_type",
    "restriction_source",
    "source_rule_status",
    "confidence",
    "supporting_evidence_ids",
    "from_road_source",
    "to_road_source",
    "from_arm_relation_status",
    "to_arm_relation_status",
    "arm_relation_status",
    "risk_flags",
]


@dataclass(frozen=True)
class T09FrcsdRestrictionArtifacts:
    output_dir: Path
    frcsd_restriction_gpkg: Path
    frcsd_restriction_csv: Path
    frcsd_restriction_json: Path
    summary_json: Path


@dataclass(frozen=True)
class T09FrcsdRestrictionRunResult:
    artifacts: T09FrcsdRestrictionArtifacts
    summary: dict[str, Any]
    restriction_count: int


@dataclass(frozen=True)
class _Record:
    properties: dict[str, Any]
    geometry: BaseGeometry | None = None


@dataclass(frozen=True, order=True)
class _RoadRef:
    source: str
    road_id: str


@dataclass(frozen=True)
class _FrcsdRoad:
    ref: _RoadRef
    snodeid: str
    enodeid: str
    direction: int | None
    geometry: BaseGeometry


@dataclass(frozen=True)
class _ArmCarrier:
    arm_id: str
    frcsd_arm_id: str
    junction_id: str
    relation_status: str
    approach_refs: tuple[_RoadRef, ...]
    exit_refs: tuple[_RoadRef, ...]
    segment_ids: tuple[str, ...]
    frcsd_junction_ids: tuple[str, ...]
    risk_flags: tuple[str, ...]


def run_t09_frcsd_restriction_modeling(
    *,
    arms_path: str | Path,
    movements_path: str | Path,
    restored_rules_path: str | Path,
    frcsd_road_path: str | Path,
    frcsd_node_path: str | Path,
    segment_relation_path: str | Path,
    output_dir: str | Path,
    run_id: str | None = None,
    arms_layer: str | None = None,
    movements_layer: str | None = None,
    restored_rules_layer: str | None = None,
    frcsd_road_layer: str | None = None,
    frcsd_node_layer: str | None = None,
    segment_relation_layer: str | None = None,
    target_epsg: int = 3857,
) -> T09FrcsdRestrictionRunResult:
    started = time.perf_counter()
    effective_run_id = run_id or _default_run_id()
    out_dir = Path(output_dir).expanduser().resolve() / effective_run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    arms = _read_records(arms_path, layer_name=arms_layer, target_epsg=target_epsg, geometry_optional=True)
    movements = _read_records(movements_path, layer_name=movements_layer, target_epsg=target_epsg, geometry_optional=True)
    rules = _read_records(restored_rules_path, layer_name=restored_rules_layer, target_epsg=target_epsg, geometry_optional=True)
    frcsd_road_records = _read_records(frcsd_road_path, layer_name=frcsd_road_layer, target_epsg=target_epsg)
    frcsd_node_records = _read_records(frcsd_node_path, layer_name=frcsd_node_layer, target_epsg=target_epsg)
    segment_relations = _read_records(segment_relation_path, layer_name=segment_relation_layer, target_epsg=target_epsg)

    frcsd_roads = _build_frcsd_roads(frcsd_road_records)
    road_by_ref = {road.ref: road for road in frcsd_roads}
    road_refs_by_id = _road_refs_by_id(frcsd_roads)
    node_aliases = _build_node_aliases(frcsd_node_records)
    carriers = _build_arm_carriers(
        arms=arms,
        segment_relations=segment_relations,
        road_by_ref=road_by_ref,
        road_refs_by_id=road_refs_by_id,
        node_aliases=node_aliases,
    )
    features, skipped = _build_restriction_features(
        rules=rules,
        movements=movements,
        carriers=carriers,
        road_by_ref=road_by_ref,
    )

    artifacts = T09FrcsdRestrictionArtifacts(
        output_dir=out_dir,
        frcsd_restriction_gpkg=out_dir / f"{FRCSDS_RESTRICTION_STEM}.gpkg",
        frcsd_restriction_csv=out_dir / f"{FRCSDS_RESTRICTION_STEM}.csv",
        frcsd_restriction_json=out_dir / f"{FRCSDS_RESTRICTION_STEM}.json",
        summary_json=out_dir / FRCSDS_RESTRICTION_SUMMARY,
    )
    write_gpkg(
        artifacts.frcsd_restriction_gpkg,
        features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=FRCSDS_RESTRICTION_FIELDS,
        geometry_type="LineString",
    )
    _write_csv(artifacts.frcsd_restriction_csv, (item["properties"] for item in features), FRCSDS_RESTRICTION_FIELDS)
    write_json(
        artifacts.frcsd_restriction_json,
        {
            "row_count": len(features),
            "features": [_feature_json(item) for item in features],
        },
    )

    elapsed_seconds = time.perf_counter() - started
    summary = _summary(
        run_id=effective_run_id,
        target_epsg=target_epsg,
        elapsed_seconds=elapsed_seconds,
        input_paths={
            "arms_path": arms_path,
            "movements_path": movements_path,
            "restored_rules_path": restored_rules_path,
            "frcsd_road_path": frcsd_road_path,
            "frcsd_node_path": frcsd_node_path,
            "segment_relation_path": segment_relation_path,
        },
        input_counts={
            "arms": len(arms),
            "movements": len(movements),
            "restored_rules": len(rules),
            "frcsd_roads": len(frcsd_road_records),
            "frcsd_nodes": len(frcsd_node_records),
            "segment_relations": len(segment_relations),
        },
        carriers=carriers,
        restrictions=features,
        skipped=skipped,
        output_paths={
            "frcsd_restriction_gpkg": artifacts.frcsd_restriction_gpkg,
            "frcsd_restriction_csv": artifacts.frcsd_restriction_csv,
            "frcsd_restriction_json": artifacts.frcsd_restriction_json,
            "summary_json": artifacts.summary_json,
        },
    )
    write_json(artifacts.summary_json, summary)
    return T09FrcsdRestrictionRunResult(
        artifacts=artifacts,
        summary=summary,
        restriction_count=len(features),
    )


def _read_records(
    path: str | Path,
    *,
    layer_name: str | None,
    target_epsg: int,
    geometry_optional: bool = False,
) -> list[_Record]:
    resolved = Path(path).expanduser().resolve()
    suffix = resolved.suffix.lower()
    if suffix == ".csv":
        with resolved.open("r", encoding="utf-8", newline="") as fp:
            return [_Record(properties=dict(row)) for row in csv.DictReader(fp)]
    if suffix == ".json":
        return _read_json_records(resolved, geometry_optional=geometry_optional)
    result = read_vector(resolved, layer_name=layer_name, target_epsg=target_epsg)
    return [_Record(properties=dict(item.properties), geometry=item.geometry) for item in result.features]


def _read_json_records(path: Path, *, geometry_optional: bool) -> list[_Record]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [_Record(properties=dict(item)) for item in payload]
    features = payload.get("features") if isinstance(payload, dict) else None
    if features is None:
        return []
    records: list[_Record] = []
    for index, feature in enumerate(features, start=1):
        props = dict(feature.get("properties") or {})
        geometry_payload = feature.get("geometry")
        geometry = shape(geometry_payload) if geometry_payload else None
        if geometry is None and not geometry_optional:
            raise ValueError(f"Feature {index} in {path} has no geometry")
        records.append(_Record(properties=props, geometry=geometry))
    return records


def _build_frcsd_roads(records: list[_Record]) -> tuple[_FrcsdRoad, ...]:
    roads: list[_FrcsdRoad] = []
    for record in records:
        props = record.properties
        road_id = _required_id(_case_get(props, ("id", "linkid", "LinkID")), "FRCSD road id")
        snodeid = _required_id(_case_get(props, ("snodeid", "snode_id", "startnodeid")), f"FRCSD road {road_id} snodeid")
        enodeid = _required_id(_case_get(props, ("enodeid", "enode_id", "endnodeid")), f"FRCSD road {road_id} enodeid")
        source = _normalize_id(_case_get(props, ("source",), default="")) or "unknown"
        direction = _parse_int(_case_get(props, ("direction", "Direction")))
        if record.geometry is None:
            raise ValueError(f"FRCSD road {road_id} has no geometry")
        roads.append(
            _FrcsdRoad(
                ref=_RoadRef(source=source, road_id=road_id),
                snodeid=snodeid,
                enodeid=enodeid,
                direction=direction,
                geometry=record.geometry,
            )
        )
    return tuple(roads)


def _road_refs_by_id(roads: tuple[_FrcsdRoad, ...]) -> dict[str, tuple[_RoadRef, ...]]:
    result: dict[str, list[_RoadRef]] = {}
    for road in roads:
        result.setdefault(road.ref.road_id, []).append(road.ref)
    return {road_id: tuple(sorted(refs)) for road_id, refs in result.items()}


def _build_node_aliases(records: list[_Record]) -> dict[str, set[str]]:
    alias_groups: dict[str, set[str]] = {}
    for record in records:
        props = record.properties
        node_id = _normalize_id(_case_get(props, ("id", "nodeid", "node_id")))
        if not node_id:
            continue
        aliases = {node_id}
        mainnodeid = _normalize_id(_case_get(props, ("mainnodeid", "main_node_id")))
        if _has_effective_node_id(mainnodeid):
            aliases.add(mainnodeid)
        for subnodeid in _as_id_list(_case_get(props, ("subnodeid", "sub_node_id"))):
            if _has_effective_node_id(subnodeid):
                aliases.add(subnodeid)
        for alias in aliases:
            alias_groups.setdefault(alias, set()).update(aliases)
    changed = True
    while changed:
        changed = False
        for alias, values in list(alias_groups.items()):
            merged = set(values)
            for value in list(values):
                merged.update(alias_groups.get(value, set()))
            if merged != values:
                alias_groups[alias] = merged
                changed = True
    return alias_groups


def _build_arm_carriers(
    *,
    arms: list[_Record],
    segment_relations: list[_Record],
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
    road_refs_by_id: dict[str, tuple[_RoadRef, ...]],
    node_aliases: dict[str, set[str]],
) -> dict[str, _ArmCarrier]:
    relation_by_segment = {
        _normalize_id(_case_get(record.properties, ("swsd_segment_id", "segment_id", "id"))): record
        for record in segment_relations
    }
    carriers: dict[str, _ArmCarrier] = {}
    for arm in arms:
        props = arm.properties
        arm_id = _required_id(_case_get(props, ("arm_id",)), "T09 arm_id")
        junction_id = _required_id(_case_get(props, ("junction_id",)), f"T09 arm {arm_id} junction_id")
        segment_ids = tuple(_as_id_list(_case_get(props, ("segment_ids",))))
        member_node_ids = set(_as_id_list(_case_get(props, ("member_node_ids",))))
        junction_node_ids = {junction_id, *member_node_ids}
        approach_seed_ids = set(_as_id_list(_case_get(props, ("approach_road_ids",))))
        exit_seed_ids = set(_as_id_list(_case_get(props, ("exit_road_ids",))))
        approach_refs: set[_RoadRef] = set()
        exit_refs: set[_RoadRef] = set()
        frcsd_junction_ids: set[str] = set()
        statuses: list[str] = []
        risk_flags: list[str] = []
        if not segment_ids:
            risk_flags.append("arm_segment_ids_missing")
        for segment_id in segment_ids:
            relation = relation_by_segment.get(segment_id)
            if relation is None:
                risk_flags.append(f"segment_relation_missing:{segment_id}")
                continue
            relation_props = relation.properties
            status = str(_case_get(relation_props, ("relation_status",), default="unknown") or "unknown")
            statuses.append(status)
            if status == "failed":
                risk_flags.append(f"segment_relation_failed:{segment_id}")
                continue
            central_aliases, central_ids = _central_node_aliases(
                relation_props=relation_props,
                junction_node_ids=junction_node_ids,
                node_aliases=node_aliases,
                relation_status=status,
            )
            frcsd_junction_ids.update(central_ids)
            relation_refs = _relation_road_refs(relation_props, road_refs_by_id)
            for ref in relation_refs:
                road = road_by_ref.get(ref)
                if road is None:
                    risk_flags.append(f"frcsd_road_missing:{ref.source}:{ref.road_id}")
                    continue
                road_roles = _road_roles_at_junction(road, central_aliases)
                if road_roles is None:
                    if ref.source == "2":
                        if ref.road_id in approach_seed_ids:
                            approach_refs.add(ref)
                        if ref.road_id in exit_seed_ids:
                            exit_refs.add(ref)
                    continue
                inbound, outbound = road_roles
                if inbound:
                    approach_refs.add(ref)
                if outbound:
                    exit_refs.add(ref)
        carriers[arm_id] = _ArmCarrier(
            arm_id=arm_id,
            frcsd_arm_id=f"frcsd:{arm_id}",
            junction_id=junction_id,
            relation_status=_status_mix(statuses),
            approach_refs=tuple(sorted(approach_refs)),
            exit_refs=tuple(sorted(exit_refs)),
            segment_ids=segment_ids,
            frcsd_junction_ids=tuple(sorted(frcsd_junction_ids, key=_sort_key)),
            risk_flags=tuple(sorted(set(risk_flags))),
        )
    return carriers


def _central_node_aliases(
    *,
    relation_props: dict[str, Any],
    junction_node_ids: set[str],
    node_aliases: dict[str, set[str]],
    relation_status: str,
) -> tuple[set[str], set[str]]:
    mapped_ids: set[str] = set()
    for item in _as_list(_case_get(relation_props, ("swsd_to_frcsd_node_map",))):
        if not isinstance(item, dict):
            continue
        swsd_node_id = _normalize_id(item.get("swsd_node_id"))
        if swsd_node_id in junction_node_ids:
            mapped_ids.update(_as_id_list(item.get("frcsd_node_ids")))
    if not mapped_ids and relation_status == "retained_swsd":
        mapped_ids.update(junction_node_ids)
    aliases: set[str] = set()
    for node_id in mapped_ids:
        aliases.update(node_aliases.get(node_id, {node_id}))
    return aliases, mapped_ids


def _relation_road_refs(
    relation_props: dict[str, Any],
    road_refs_by_id: dict[str, tuple[_RoadRef, ...]],
) -> tuple[_RoadRef, ...]:
    source_values = {_normalize_id(value) for value in _as_list(_case_get(relation_props, ("frcsd_road_source_values",)))}
    refs: list[_RoadRef] = []
    for road_id in _as_id_list(_case_get(relation_props, ("frcsd_road_ids",))):
        candidates = road_refs_by_id.get(road_id, tuple())
        if source_values:
            candidates = tuple(ref for ref in candidates if ref.source in source_values)
        refs.extend(candidates)
    return tuple(sorted(set(refs)))


def _road_roles_at_junction(road: _FrcsdRoad, central_aliases: set[str]) -> tuple[bool, bool] | None:
    snode_inside = road.snodeid in central_aliases
    enode_inside = road.enodeid in central_aliases
    if snode_inside == enode_inside:
        return None
    if road.direction in {0, 1}:
        return True, True
    if road.direction == 2:
        return (not snode_inside, snode_inside)
    if road.direction == 3:
        return (snode_inside, not snode_inside)
    return None


def _build_restriction_features(
    *,
    rules: list[_Record],
    movements: list[_Record],
    carriers: dict[str, _ArmCarrier],
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    movement_by_key = {
        (
            _normalize_id(_case_get(item.properties, ("from_arm_id",))),
            _normalize_id(_case_get(item.properties, ("to_arm_id",))),
            str(_case_get(item.properties, ("movement_type",), default="")),
        ): item.properties
        for item in movements
    }
    features: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    emitted_keys: set[tuple[str, str, str, str]] = set()
    for rule in rules:
        rule_props = rule.properties
        status = str(_case_get(rule_props, ("field_rule_status", "prohibition_status"), default="unknown"))
        if status != "fully_prohibited":
            skipped[f"rule_status:{status}"] += 1
            continue
        from_arm_id = _required_id(_case_get(rule_props, ("from_arm_id",)), "restored rule from_arm_id")
        to_arm_id = _required_id(_case_get(rule_props, ("to_arm_id",)), "restored rule to_arm_id")
        movement_type = str(_case_get(rule_props, ("movement_type",), default="unknown") or "unknown")
        junction_id = _required_id(_case_get(rule_props, ("junction_id",)), "restored rule junction_id")
        movement_props = movement_by_key.get((from_arm_id, to_arm_id, movement_type), {})
        reason = str(_case_get(movement_props, ("prohibition_reason",), default="missing") or "missing")
        if reason != "explicit_restriction":
            skipped[f"rule_reason:{reason}"] += 1
            continue
        from_carrier = carriers.get(from_arm_id)
        to_carrier = carriers.get(to_arm_id)
        if from_carrier is None or to_carrier is None:
            skipped["arm_carrier_missing"] += 1
            continue
        if not from_carrier.approach_refs:
            skipped["from_arm_approach_missing"] += 1
            continue
        if not to_carrier.exit_refs:
            skipped["to_arm_exit_missing"] += 1
            continue
        for from_ref in from_carrier.approach_refs:
            for to_ref in to_carrier.exit_refs:
                output_key = (from_ref.road_id, to_ref.road_id, junction_id, movement_type)
                if output_key in emitted_keys:
                    skipped["duplicate_link_pair"] += 1
                    continue
                emitted_keys.add(output_key)
                from_road = road_by_ref.get(from_ref)
                to_road = road_by_ref.get(to_ref)
                if from_road is None or to_road is None:
                    skipped["frcsd_road_missing"] += 1
                    continue
                try:
                    geometry = _restriction_geometry(from_road.geometry, to_road.geometry)
                except ValueError:
                    skipped["invalid_restriction_geometry"] += 1
                    continue
                row = _restriction_row(
                    junction_id=junction_id,
                    movement_type=movement_type,
                    rule_props=rule_props,
                    movement_props=movement_props,
                    from_ref=from_ref,
                    to_ref=to_ref,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                )
                features.append({"properties": row, "geometry": geometry})
    return features, skipped


def _restriction_row(
    *,
    junction_id: str,
    movement_type: str,
    rule_props: dict[str, Any],
    movement_props: dict[str, Any],
    from_ref: _RoadRef,
    to_ref: _RoadRef,
    from_carrier: _ArmCarrier,
    to_carrier: _ArmCarrier,
) -> dict[str, Any]:
    movement_id = str(_case_get(movement_props, ("movement_id",), default="") or "")
    reason = str(_case_get(movement_props, ("prohibition_reason",), default="inherited_swsd_movement"))
    supporting_ids = _as_id_list(_case_get(rule_props, ("supporting_evidence_ids", "evidence_item_ids")))
    risk_flags = sorted(
        set(
            _as_id_list(_case_get(rule_props, ("risk_flags",)))
            + _as_id_list(_case_get(movement_props, ("risk_flags",)))
            + list(from_carrier.risk_flags)
            + list(to_carrier.risk_flags)
        )
    )
    frcsd_junction_id = _frcsd_junction_id(from_carrier.frcsd_junction_ids, to_carrier.frcsd_junction_ids)
    return {
        "restriction_id": _restriction_id(junction_id, movement_type, from_ref, to_ref),
        "CondType": 1,
        "LinkID": from_ref.road_id,
        "inLinkID": from_ref.road_id,
        "outLinkID": to_ref.road_id,
        "junction_id": junction_id,
        "frcsd_junction_id": frcsd_junction_id,
        "from_arm_id": from_carrier.arm_id,
        "to_arm_id": to_carrier.arm_id,
        "from_frcsd_arm_id": from_carrier.frcsd_arm_id,
        "to_frcsd_arm_id": to_carrier.frcsd_arm_id,
        "movement_id": movement_id,
        "movement_type": movement_type,
        "restriction_source": _restriction_source(reason),
        "source_rule_status": str(_case_get(rule_props, ("field_rule_status",), default="fully_prohibited")),
        "confidence": _parse_float(_case_get(rule_props, ("confidence",), default=_case_get(movement_props, ("prohibition_confidence",), default=0.0))),
        "supporting_evidence_ids": supporting_ids,
        "from_road_source": from_ref.source,
        "to_road_source": to_ref.source,
        "from_arm_relation_status": from_carrier.relation_status,
        "to_arm_relation_status": to_carrier.relation_status,
        "arm_relation_status": f"from:{from_carrier.relation_status};to:{to_carrier.relation_status}",
        "risk_flags": risk_flags,
    }


def _summary(
    *,
    run_id: str,
    target_epsg: int,
    elapsed_seconds: float,
    input_paths: dict[str, str | Path],
    input_counts: dict[str, int],
    carriers: dict[str, _ArmCarrier],
    restrictions: list[dict[str, Any]],
    skipped: Counter[str],
    output_paths: dict[str, Path],
) -> dict[str, Any]:
    relation_status_counts = Counter(carrier.relation_status for carrier in carriers.values())
    risk_counts = Counter(flag for carrier in carriers.values() for flag in carrier.risk_flags)
    movement_type_counts = Counter(item["properties"].get("movement_type") for item in restrictions)
    return {
        "tool": "T09 Step3",
        "stage": "frcsd_restriction_modeling",
        "run_id": run_id,
        "produced_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_epsg": target_epsg,
        "input_paths": {key: str(Path(value).expanduser().resolve()) for key, value in input_paths.items()},
        "input_counts": input_counts,
        "arm_carrier_count": len(carriers),
        "arm_carrier_relation_status_counts": dict(sorted(relation_status_counts.items())),
        "arm_carrier_risk_flag_counts": dict(sorted(risk_counts.items())),
        "restriction_count": len(restrictions),
        "restriction_movement_type_counts": dict(sorted(movement_type_counts.items())),
        "skipped_counts": dict(sorted(skipped.items())),
        "outputs": {key: str(path) for key, path in output_paths.items()},
        "business_policy": {
            "generated_rule_status": "fully_prohibited",
            "prohibition_source": "explicit_restriction_only",
            "partial_rule_policy": "do_not_expand_to_frcsd_restriction",
            "non_restriction_evidence_policy": "arrow and special carrier evidence never generate FRCSD restriction alone",
            "carrier_mapping_source": "T06 swsd_frcsd_segment_relation",
            "frcsd_link_fields": ["LinkID", "outLinkID"],
        },
        "qa": {
            "crs_transform_executed": f"vector inputs are read through vector_io target EPSG:{target_epsg}; T09 JSON/CSV evidence is treated as already-normalized module output",
            "topology_silent_fix": False,
            "topology_consistency": "FRCSD carrier roads are selected only through T06 segment relation and endpoint direction at mapped junction aliases",
            "geometry_semantics": "restriction geometry connects the selected FRCSD incoming carrier road to the outgoing carrier road without repairing source geometry",
            "audit_traceability": "each output row retains source arm ids, movement id, supporting evidence ids, source values and relation status",
            "performance_verifiable": {
                "elapsed_seconds": round(elapsed_seconds, 6),
                "restrictions_per_second": _items_per_second(len(restrictions), elapsed_seconds),
            },
        },
    }


def _restriction_source(reason: str) -> str:
    if reason == "explicit_restriction":
        return "explicit_restriction"
    return "non_restriction_evidence"


def _frcsd_junction_id(from_ids: tuple[str, ...], to_ids: tuple[str, ...]) -> str:
    common = sorted(set(from_ids).intersection(to_ids), key=_sort_key)
    if common:
        return "+".join(common)
    return "+".join(sorted(set(from_ids).union(to_ids), key=_sort_key))


def _restriction_id(junction_id: str, movement_type: str, from_ref: _RoadRef, to_ref: _RoadRef) -> str:
    return f"{junction_id}:frcsd_restriction:{movement_type}:{from_ref.source}:{from_ref.road_id}->{to_ref.source}:{to_ref.road_id}"


def _restriction_geometry(in_geometry: BaseGeometry, out_geometry: BaseGeometry) -> LineString:
    in_coords = _line_coords(in_geometry)
    out_coords = _line_coords(out_geometry)
    if len(in_coords) < 2 or len(out_coords) < 2:
        raise ValueError("Road geometry must contain at least two coordinates")
    best: tuple[float, bool, bool] | None = None
    for in_at_start in (False, True):
        in_point = in_coords[0] if in_at_start else in_coords[-1]
        for out_at_start in (True, False):
            out_point = out_coords[0] if out_at_start else out_coords[-1]
            candidate = (_point_distance(in_point, out_point), in_at_start, out_at_start)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise ValueError("Could not connect road geometries")
    _distance, in_at_start, out_at_start = best
    oriented_in = list(reversed(in_coords)) if in_at_start else list(in_coords)
    oriented_out = list(out_coords) if out_at_start else list(reversed(out_coords))
    coords = list(oriented_in)
    coords.extend(oriented_out[1:] if _point_distance(coords[-1], oriented_out[0]) <= 1e-8 else oriented_out)
    if len(coords) < 2:
        raise ValueError("Restriction geometry contains fewer than two coordinates")
    return LineString(coords)


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


def _feature_json(feature: dict[str, Any]) -> dict[str, Any]:
    geometry = feature.get("geometry")
    return {
        "properties": feature.get("properties") or {},
        "geometry": mapping(geometry) if isinstance(geometry, BaseGeometry) else geometry,
        "crs": "EPSG:3857",
    }


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]
    return [value]


def _as_id_list(value: Any) -> list[str]:
    return [_normalize_id(item) for item in _as_list(value) if _normalize_id(item)]


def _case_get(props: dict[str, Any], candidates: tuple[str, ...], default: Any = None) -> Any:
    for candidate in candidates:
        if candidate in props:
            return props.get(candidate)
    lowered = {str(key).lower(): key for key in props}
    for candidate in candidates:
        key = lowered.get(candidate.lower())
        if key is not None:
            return props.get(key)
    return default


def _required_id(value: Any, label: str) -> str:
    result = _normalize_id(value)
    if not result:
        raise ValueError(f"{label} is required")
    return result


def _normalize_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if math.isfinite(number) and number.is_integer() and text.replace(".", "", 1).replace("-", "", 1).isdigit():
        return str(int(number))
    return text


def _has_effective_node_id(value: str) -> bool:
    return bool(value and value != "0" and value.lower() not in {"none", "null", "nan"})


def _parse_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _status_mix(statuses: list[str]) -> str:
    values = sorted(set(statuses))
    if not values:
        return "missing_relation"
    if len(values) == 1:
        return values[0]
    return "+".join(values)


def _sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _items_per_second(count: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return float(count)
    return round(count / elapsed_seconds, 6)


def _default_run_id() -> str:
    return "t09_frcsd_restriction_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
