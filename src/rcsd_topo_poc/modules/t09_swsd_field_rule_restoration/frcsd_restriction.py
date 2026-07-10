from __future__ import annotations

import csv
import json
import math
import platform
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, write_gpkg, write_json
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration._json_crs import (
    declared_json_crs,
    parse_json_crs,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    RestorationStrategy,
    normalize_restoration_strategy,
)


FRCSDS_RESTRICTION_STEM = "frcsd_restriction"
FRCSDS_RESTRICTION_CANDIDATE_STEM = "frcsd_restriction_candidates"
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

FRCSDS_RESTRICTION_V2_FIELDS = FRCSDS_RESTRICTION_FIELDS + [
    "strategy_version",
    "decision_status",
    "decision_source",
    "decision_scope",
    "evidence_priority",
    "inference_level",
    "verification_status",
    "condition_type",
    "condition_payload",
    "condition_identity",
    "condition_semantics_status",
    "conflicting_evidence_ids",
    "override_chain",
    "source_restriction_ids",
    "source_rule_id",
    "source_from_road_ids",
    "source_to_road_ids",
    "source_road_pairs",
    "scope_promotion_status",
    "scope_promotion_reason",
    "scope_promotion_audit",
]

FRCSDS_RESTRICTION_CANDIDATE_FIELDS = FRCSDS_RESTRICTION_V2_FIELDS + [
    "candidate_reason",
    "geometry_semantics",
]


@dataclass(frozen=True)
class T09FrcsdRestrictionArtifacts:
    output_dir: Path
    frcsd_restriction_gpkg: Path
    frcsd_restriction_csv: Path
    frcsd_restriction_json: Path
    frcsd_restriction_candidates_gpkg: Path
    frcsd_restriction_candidates_csv: Path
    frcsd_restriction_candidates_json: Path
    summary_json: Path


@dataclass(frozen=True)
class T09FrcsdRestrictionRunResult:
    artifacts: T09FrcsdRestrictionArtifacts
    summary: dict[str, Any]
    restriction_count: int
    candidate_count: int


@dataclass(frozen=True)
class _Record:
    properties: dict[str, Any]
    geometry: BaseGeometry | None = None


@dataclass(frozen=True)
class _InputRead:
    records: list[_Record]
    audit: dict[str, Any]


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
    strategy_version: str | RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1,
) -> T09FrcsdRestrictionRunResult:
    started = time.perf_counter()
    strategy = normalize_restoration_strategy(strategy_version)
    effective_run_id = run_id or _default_run_id()
    out_dir = Path(output_dir).expanduser().resolve() / effective_run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    input_started = time.perf_counter()
    arms_read = _read_records_with_audit(
        arms_path,
        layer_name=arms_layer,
        target_epsg=target_epsg,
        geometry_optional=True,
    )
    movements_read = _read_records_with_audit(
        movements_path,
        layer_name=movements_layer,
        target_epsg=target_epsg,
        geometry_optional=True,
    )
    rules_read = _read_records_with_audit(
        restored_rules_path,
        layer_name=restored_rules_layer,
        target_epsg=target_epsg,
        geometry_optional=True,
    )
    road_read = _read_records_with_audit(
        frcsd_road_path,
        layer_name=frcsd_road_layer,
        target_epsg=target_epsg,
    )
    node_read = _read_records_with_audit(
        frcsd_node_path,
        layer_name=frcsd_node_layer,
        target_epsg=target_epsg,
    )
    relation_read = _read_records_with_audit(
        segment_relation_path,
        layer_name=segment_relation_layer,
        target_epsg=target_epsg,
    )
    input_read_seconds = time.perf_counter() - input_started
    arms = arms_read.records
    movements = movements_read.records
    loaded_rules = rules_read.records
    frcsd_road_records = road_read.records
    frcsd_node_records = node_read.records
    segment_relations = relation_read.records
    rules, strategy_skipped = _filter_rules_for_strategy(
        rules=loaded_rules,
        strategy=strategy,
    )

    carrier_started = time.perf_counter()
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
        strict_audit=strategy == RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    carrier_build_seconds = time.perf_counter() - carrier_started
    decision_started = time.perf_counter()
    candidates: list[dict[str, Any]] = []
    if strategy == RestorationStrategy.RESTRICTION_ONLY_V1:
        features, skipped = _build_restriction_features(
            rules=rules,
            movements=movements,
            carriers=carriers,
            road_by_ref=road_by_ref,
        )
        stable_fields = FRCSDS_RESTRICTION_FIELDS
    else:
        features, candidates, skipped = _build_v2_restriction_features(
            rules=rules,
            movements=movements,
            carriers=carriers,
            road_by_ref=road_by_ref,
            expected_strategy=strategy,
        )
        stable_fields = FRCSDS_RESTRICTION_V2_FIELDS
    skipped.update(strategy_skipped)
    decision_modeling_seconds = time.perf_counter() - decision_started

    artifacts = T09FrcsdRestrictionArtifacts(
        output_dir=out_dir,
        frcsd_restriction_gpkg=out_dir / f"{FRCSDS_RESTRICTION_STEM}.gpkg",
        frcsd_restriction_csv=out_dir / f"{FRCSDS_RESTRICTION_STEM}.csv",
        frcsd_restriction_json=out_dir / f"{FRCSDS_RESTRICTION_STEM}.json",
        frcsd_restriction_candidates_gpkg=out_dir / f"{FRCSDS_RESTRICTION_CANDIDATE_STEM}.gpkg",
        frcsd_restriction_candidates_csv=out_dir / f"{FRCSDS_RESTRICTION_CANDIDATE_STEM}.csv",
        frcsd_restriction_candidates_json=out_dir / f"{FRCSDS_RESTRICTION_CANDIDATE_STEM}.json",
        summary_json=out_dir / FRCSDS_RESTRICTION_SUMMARY,
    )
    output_started = time.perf_counter()
    write_gpkg(
        artifacts.frcsd_restriction_gpkg,
        features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=stable_fields,
        geometry_type="LineString",
    )
    _write_csv(artifacts.frcsd_restriction_csv, (item["properties"] for item in features), stable_fields)
    write_json(
        artifacts.frcsd_restriction_json,
        {
            "row_count": len(features),
            "features": [_feature_json(item, crs_text=f"EPSG:{target_epsg}") for item in features],
        },
    )
    if strategy == RestorationStrategy.MULTI_EVIDENCE_V2:
        write_gpkg(
            artifacts.frcsd_restriction_candidates_gpkg,
            (item for item in candidates if item.get("geometry") is not None),
            crs_text=f"EPSG:{target_epsg}",
            empty_fields=FRCSDS_RESTRICTION_CANDIDATE_FIELDS,
            geometry_type="LineString",
        )
        _write_csv(
            artifacts.frcsd_restriction_candidates_csv,
            (item["properties"] for item in candidates),
            FRCSDS_RESTRICTION_CANDIDATE_FIELDS,
        )
        write_json(
            artifacts.frcsd_restriction_candidates_json,
            {
                "row_count": len(candidates),
                "gpkg_geometry_row_count": sum(
                    1 for item in candidates if item.get("geometry") is not None
                ),
                "features": [
                    _feature_json(item, crs_text=f"EPSG:{target_epsg}")
                    for item in candidates
                ],
            },
        )

    output_write_seconds = time.perf_counter() - output_started
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
        input_audit={
            "arms": arms_read.audit,
            "movements": movements_read.audit,
            "restored_rules": rules_read.audit,
            "frcsd_roads": road_read.audit,
            "frcsd_nodes": node_read.audit,
            "segment_relations": relation_read.audit,
        },
        input_counts={
            "arms": len(arms),
            "movements": len(movements),
            "restored_rules": len(loaded_rules),
            "accepted_strategy_rules": len(rules),
            "frcsd_roads": len(frcsd_road_records),
            "frcsd_nodes": len(frcsd_node_records),
            "segment_relations": len(segment_relations),
        },
        carriers=carriers,
        restrictions=features,
        candidates=candidates,
        skipped=skipped,
        strategy=strategy,
        stage_timings={
            "read_inputs_seconds": input_read_seconds,
            "build_carriers_seconds": carrier_build_seconds,
            "model_rules_seconds": decision_modeling_seconds,
            "write_artifacts_before_summary_seconds": output_write_seconds,
            "run_before_summary_write_seconds": elapsed_seconds,
        },
        runtime_environment=_runtime_environment(),
        output_paths={
            "frcsd_restriction_gpkg": artifacts.frcsd_restriction_gpkg,
            "frcsd_restriction_csv": artifacts.frcsd_restriction_csv,
            "frcsd_restriction_json": artifacts.frcsd_restriction_json,
            **(
                {
                    "frcsd_restriction_candidates_gpkg": artifacts.frcsd_restriction_candidates_gpkg,
                    "frcsd_restriction_candidates_csv": artifacts.frcsd_restriction_candidates_csv,
                    "frcsd_restriction_candidates_json": artifacts.frcsd_restriction_candidates_json,
                }
                if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
                else {}
            ),
            "summary_json": artifacts.summary_json,
        },
    )
    write_json(artifacts.summary_json, summary)
    return T09FrcsdRestrictionRunResult(
        artifacts=artifacts,
        summary=summary,
        restriction_count=len(features),
        candidate_count=len(candidates),
    )


def _filter_rules_for_strategy(
    *,
    rules: list[_Record],
    strategy: RestorationStrategy,
) -> tuple[list[_Record], Counter[str]]:
    accepted: list[_Record] = []
    skipped: Counter[str] = Counter()
    for rule in rules:
        raw = str(_case_get(rule.properties, ("strategy_version",), default="") or "").strip()
        if not raw:
            if strategy == RestorationStrategy.RESTRICTION_ONLY_V1:
                accepted.append(rule)
            else:
                skipped["rule_strategy_missing"] += 1
            continue
        try:
            rule_strategy = normalize_restoration_strategy(raw)
        except ValueError:
            skipped[f"rule_strategy_invalid:{raw}"] += 1
            continue
        if rule_strategy != strategy:
            skipped[f"rule_strategy_mismatch:{rule_strategy.value}"] += 1
            continue
        accepted.append(rule)
    return accepted, skipped


def _read_records(
    path: str | Path,
    *,
    layer_name: str | None,
    target_epsg: int,
    geometry_optional: bool = False,
) -> list[_Record]:
    return _read_records_with_audit(
        path,
        layer_name=layer_name,
        target_epsg=target_epsg,
        geometry_optional=geometry_optional,
    ).records


def _read_records_with_audit(
    path: str | Path,
    *,
    layer_name: str | None,
    target_epsg: int,
    geometry_optional: bool = False,
) -> _InputRead:
    read_started = time.perf_counter()
    resolved = Path(path).expanduser().resolve()
    suffix = resolved.suffix.lower()
    if suffix == ".csv":
        with resolved.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            records = [_Record(properties=dict(row)) for row in reader]
            field_names = tuple(str(name) for name in (reader.fieldnames or tuple()))
        return _InputRead(
            records=records,
            audit=_input_audit(
                requested_path=path,
                resolved_path=resolved,
                requested_layer_name=layer_name,
                resolved_layer_name=None,
                field_names=field_names,
                feature_count=len(records),
                source_crs=None,
                output_crs=None,
                crs_source="not_applicable_non_spatial_csv",
                crs_transform_executed=False,
                geometry_handling="non_spatial_tabular",
                read_elapsed_seconds=time.perf_counter() - read_started,
            ),
        )
    if suffix == ".json":
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        records = _read_json_payload(
            payload,
            path=resolved,
            geometry_optional=geometry_optional,
        )
        has_geometry = any(record.geometry is not None for record in records)
        declared_crs = declared_json_crs(payload, path=resolved)
        source_crs = parse_json_crs(declared_crs, path=resolved) if declared_crs else None
        target_crs = CRS.from_epsg(target_epsg)
        transform_executed = bool(
            has_geometry and source_crs is not None and source_crs != target_crs
        )
        if transform_executed and source_crs is not None:
            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
            records = [
                _Record(
                    properties=record.properties,
                    geometry=(
                        shapely_transform(transformer.transform, record.geometry)
                        if record.geometry is not None
                        else None
                    ),
                )
                for record in records
            ]
        return _InputRead(
            records=records,
            audit=_input_audit(
                requested_path=path,
                resolved_path=resolved,
                requested_layer_name=layer_name,
                resolved_layer_name=None,
                field_names=_record_field_names(records),
                feature_count=len(records),
                source_crs=source_crs.to_string() if source_crs is not None else None,
                output_crs=target_crs.to_string() if has_geometry else None,
                crs_source=(
                    "declared_json_crs"
                    if declared_crs
                    else (
                        "not_applicable_non_spatial_json"
                    )
                ),
                crs_transform_executed=transform_executed,
                geometry_handling=(
                    "transformed_declared_json_crs_to_target"
                    if transform_executed
                    else "validated_declared_json_crs_without_transform"
                    if has_geometry
                    else "non_spatial_json"
                ),
                read_elapsed_seconds=time.perf_counter() - read_started,
            ),
        )
    result = read_vector(resolved, layer_name=layer_name, target_epsg=target_epsg)
    records = [
        _Record(properties=dict(item.properties), geometry=item.geometry)
        for item in result.features
    ]
    return _InputRead(
        records=records,
        audit=_input_audit(
            requested_path=path,
            resolved_path=result.path,
            requested_layer_name=layer_name,
            resolved_layer_name=result.layer_name,
            field_names=result.field_names,
            feature_count=len(records),
            source_crs=result.source_crs.to_string(),
            output_crs=result.output_crs.to_string(),
            crs_source=result.crs_source,
            crs_transform_executed=result.source_crs != result.output_crs,
            geometry_handling="vector_io_read_and_transform_to_output_crs",
            read_elapsed_seconds=time.perf_counter() - read_started,
        ),
    )


def _read_json_records(path: Path, *, geometry_optional: bool) -> list[_Record]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _read_json_payload(payload, path=path, geometry_optional=geometry_optional)


def _read_json_payload(
    payload: Any,
    *,
    path: Path,
    geometry_optional: bool,
) -> list[_Record]:
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


def _input_audit(
    *,
    requested_path: str | Path,
    resolved_path: Path,
    requested_layer_name: str | None,
    resolved_layer_name: str | None,
    field_names: Iterable[str],
    feature_count: int,
    source_crs: str | None,
    output_crs: str | None,
    crs_source: str,
    crs_transform_executed: bool,
    geometry_handling: str,
    read_elapsed_seconds: float,
) -> dict[str, Any]:
    return {
        "requested_path": str(requested_path),
        "resolved_path": str(resolved_path),
        "requested_layer_name": requested_layer_name,
        "resolved_layer_name": resolved_layer_name,
        "field_names": sorted({str(name) for name in field_names}),
        "feature_count": feature_count,
        "source_crs": source_crs,
        "output_crs": output_crs,
        "crs_source": crs_source,
        "crs_transform_executed": bool(crs_transform_executed),
        "geometry_handling": geometry_handling,
        "read_elapsed_seconds": round(read_elapsed_seconds, 6),
    }


def _record_field_names(records: list[_Record]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(field_name)
                for record in records
                for field_name in record.properties
            }
        )
    )


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
    strict_audit: bool,
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
        blocked_fallback_seed_ids: set[str] = set()
        fallback_blocked_by_relation_gap = False
        declared_relation_road_ids: set[str] = set()
        if not segment_ids:
            risk_flags.append("arm_segment_ids_missing")
        for segment_id in segment_ids:
            relation = relation_by_segment.get(segment_id)
            if relation is None:
                risk_flags.append(f"segment_relation_missing:{segment_id}")
                if strict_audit:
                    fallback_blocked_by_relation_gap = True
                continue
            relation_props = relation.properties
            status = str(_case_get(relation_props, ("relation_status",), default="unknown") or "unknown")
            statuses.append(status)
            if status == "failed":
                risk_flags.append(f"segment_relation_failed:{segment_id}")
                if strict_audit:
                    fallback_blocked_by_relation_gap = True
                continue
            if strict_audit and status not in {
                "replaced",
                "retained_swsd",
                "replaced+retained_swsd",
            }:
                risk_flags.append(f"segment_relation_status_unsupported:{segment_id}:{status}")
                fallback_blocked_by_relation_gap = True
                continue
            if strict_audit:
                declared_relation_road_ids.update(
                    _as_id_list(_case_get(relation_props, ("frcsd_road_ids",)))
                )
                source_gate_risks = _relation_source_gate_risks(
                    segment_id=segment_id,
                    relation_status=status,
                    relation_props=relation_props,
                )
                if source_gate_risks:
                    risk_flags.extend(source_gate_risks)
                    fallback_blocked_by_relation_gap = True
                    continue
            central_aliases, central_ids, missing_central_ids = _central_node_aliases(
                relation_props=relation_props,
                junction_node_ids=junction_node_ids,
                node_aliases=node_aliases,
                relation_status=status,
            )
            if not strict_audit and missing_central_ids:
                central_aliases.update(missing_central_ids)
                central_ids.update(missing_central_ids)
            frcsd_junction_ids.update(central_ids)
            if strict_audit:
                for node_id in missing_central_ids:
                    risk_flags.append(f"frcsd_junction_node_missing:{node_id}")
                if missing_central_ids:
                    fallback_blocked_by_relation_gap = True
            relation_refs, missing_road_ids, source_mismatches = _relation_road_refs(
                relation_props,
                road_refs_by_id,
            )
            if strict_audit:
                for road_id in missing_road_ids:
                    risk_flags.append(f"frcsd_road_missing:relation:{road_id}")
                if missing_road_ids:
                    fallback_blocked_by_relation_gap = True
                for mismatch in source_mismatches:
                    risk_flags.append(
                        f"segment_relation_road_source_mismatch:{segment_id}:{mismatch}"
                    )
                if source_mismatches:
                    fallback_blocked_by_relation_gap = True
                    continue
            for ref in relation_refs:
                road = road_by_ref.get(ref)
                if road is None:
                    risk_flags.append(f"frcsd_road_missing:{ref.source}:{ref.road_id}")
                    continue
                retained_status = status in {
                    "retained_swsd",
                    "replaced+retained_swsd",
                }
                retained_swsd_ref = retained_status and ref.source == "2"
                if strict_audit and ref.source == "2":
                    if not retained_status:
                        blocked_fallback_seed_ids.add(ref.road_id)
                        risk_flags.append(
                            f"source2_relation_status_not_retained:{status}:{ref.road_id}"
                        )
                        continue
                    if ref.road_id not in approach_seed_ids | exit_seed_ids:
                        risk_flags.append(
                            f"source2_not_declared_arm_seed:{status}:{ref.road_id}"
                        )
                        continue
                if strict_audit:
                    missing_endpoints = _missing_registered_road_endpoints(
                        road,
                        node_aliases,
                    )
                    if missing_endpoints:
                        risk_flags.extend(
                            f"frcsd_road_endpoint_node_missing:{ref.source}:{ref.road_id}:{endpoint}"
                            for endpoint in missing_endpoints
                        )
                        continue
                if strict_audit and road.direction not in {0, 1, 2, 3}:
                    risk_flags.append(
                        f"frcsd_road_direction_uninterpretable:{ref.source}:{ref.road_id}:{road.direction}"
                    )
                    continue
                road_roles = _road_roles_at_junction(road, central_aliases)
                if road_roles is None:
                    if strict_audit:
                        risk_flags.append(
                            f"frcsd_road_junction_direction_unresolved:{ref.source}:{ref.road_id}"
                        )
                    if ref.source == "2" and not strict_audit:
                        if ref.road_id in approach_seed_ids:
                            approach_refs.add(ref)
                        if ref.road_id in exit_seed_ids:
                            exit_refs.add(ref)
                    continue
                inbound, outbound = road_roles
                if inbound and (not retained_swsd_ref or ref.road_id in approach_seed_ids):
                    approach_refs.add(ref)
                if outbound and (not retained_swsd_ref or ref.road_id in exit_seed_ids):
                    exit_refs.add(ref)
                if strict_audit and retained_swsd_ref:
                    if ref.road_id in approach_seed_ids and not inbound:
                        risk_flags.append(
                            f"source2_seed_direction_mismatch:approach:{ref.road_id}"
                        )
                    if ref.road_id in exit_seed_ids and not outbound:
                        risk_flags.append(
                            f"source2_seed_direction_mismatch:exit:{ref.road_id}"
                        )
        if strict_audit:
            blocked_fallback_seed_ids.update(
                declared_relation_road_ids & (approach_seed_ids | exit_seed_ids)
            )
            if fallback_blocked_by_relation_gap:
                risk_flags.append(
                    "retained_swsd_seed_fallback_blocked_by_relation_gap"
                )
        fallback_refs, fallback_risk_flags = _add_retained_swsd_seed_refs(
            approach_refs=approach_refs,
            exit_refs=exit_refs,
            approach_seed_ids=approach_seed_ids,
            exit_seed_ids=exit_seed_ids,
            junction_node_ids=junction_node_ids,
            road_by_ref=road_by_ref,
            road_refs_by_id=road_refs_by_id,
            node_aliases=node_aliases,
            strict_audit=strict_audit,
            blocked_seed_ids=blocked_fallback_seed_ids,
            fallback_allowed=not (
                strict_audit and fallback_blocked_by_relation_gap
            ),
        )
        risk_flags.extend(fallback_risk_flags)
        if fallback_refs:
            statuses.append("retained_swsd_seed_fallback")
            risk_flags.append("retained_swsd_seed_carrier_fallback")
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


def _add_retained_swsd_seed_refs(
    *,
    approach_refs: set[_RoadRef],
    exit_refs: set[_RoadRef],
    approach_seed_ids: set[str],
    exit_seed_ids: set[str],
    junction_node_ids: set[str],
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
    road_refs_by_id: dict[str, tuple[_RoadRef, ...]],
    node_aliases: dict[str, set[str]],
    strict_audit: bool,
    blocked_seed_ids: set[str],
    fallback_allowed: bool,
) -> tuple[set[_RoadRef], tuple[str, ...]]:
    central_aliases = _junction_node_aliases(
        junction_node_ids,
        node_aliases,
        require_registered=strict_audit,
    )
    added: set[_RoadRef] = set()
    risk_flags: set[str] = set()
    if not fallback_allowed:
        return added, tuple()
    if strict_audit and not central_aliases:
        risk_flags.add(
            "retained_swsd_seed_fallback_node_alias_missing:"
            + "+".join(sorted(junction_node_ids, key=_sort_key))
        )
    for road_id in sorted(approach_seed_ids | exit_seed_ids, key=_sort_key):
        if strict_audit and road_id in blocked_seed_ids:
            approach_satisfied = road_id not in approach_seed_ids or any(
                ref.source == "2" and ref.road_id == road_id
                for ref in approach_refs
            )
            exit_satisfied = road_id not in exit_seed_ids or any(
                ref.source == "2" and ref.road_id == road_id
                for ref in exit_refs
            )
            has_global_source2 = any(
                ref.source == "2" for ref in road_refs_by_id.get(road_id, tuple())
            )
            if has_global_source2 and not (approach_satisfied and exit_satisfied):
                risk_flags.add(
                    f"retained_swsd_seed_fallback_blocked_by_declared_relation_road:{road_id}"
                )
            continue
        for ref in road_refs_by_id.get(road_id, tuple()):
            if ref.source != "2":
                continue
            road = road_by_ref.get(ref)
            if road is None:
                continue
            if strict_audit:
                missing_endpoints = _missing_registered_road_endpoints(
                    road,
                    node_aliases,
                )
                if missing_endpoints:
                    risk_flags.update(
                        f"retained_swsd_seed_fallback_endpoint_node_missing:"
                        f"{ref.source}:{ref.road_id}:{endpoint}"
                        for endpoint in missing_endpoints
                    )
                    continue
            if strict_audit and road.direction not in {0, 1, 2, 3}:
                risk_flags.add(
                    f"retained_swsd_seed_fallback_direction_uninterpretable:"
                    f"{ref.source}:{ref.road_id}:{road.direction}"
                )
                continue
            road_roles = _road_roles_at_junction(road, central_aliases)
            if road_roles is None:
                if strict_audit:
                    risk_flags.add(
                        f"retained_swsd_seed_fallback_junction_direction_unresolved:"
                        f"{ref.source}:{ref.road_id}"
                    )
                continue
            inbound, outbound = road_roles
            if inbound and road_id in approach_seed_ids and ref not in approach_refs:
                approach_refs.add(ref)
                added.add(ref)
            if outbound and road_id in exit_seed_ids and ref not in exit_refs:
                exit_refs.add(ref)
                added.add(ref)
            if strict_audit and road_id in approach_seed_ids and not inbound:
                risk_flags.add(
                    f"retained_swsd_seed_fallback_direction_mismatch:approach:{road_id}"
                )
            if strict_audit and road_id in exit_seed_ids and not outbound:
                risk_flags.add(
                    f"retained_swsd_seed_fallback_direction_mismatch:exit:{road_id}"
                )
    return added, tuple(sorted(risk_flags))


def _junction_node_aliases(
    junction_node_ids: set[str],
    node_aliases: dict[str, set[str]],
    *,
    require_registered: bool = False,
) -> set[str]:
    aliases: set[str] = set()
    for node_id in junction_node_ids:
        aliases.update(
            node_aliases.get(node_id, set() if require_registered else {node_id})
        )
    return aliases


def _central_node_aliases(
    *,
    relation_props: dict[str, Any],
    junction_node_ids: set[str],
    node_aliases: dict[str, set[str]],
    relation_status: str,
) -> tuple[set[str], set[str], set[str]]:
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
    valid_ids = {node_id for node_id in mapped_ids if node_id in node_aliases}
    missing_ids = mapped_ids - valid_ids
    for node_id in valid_ids:
        aliases.update(node_aliases[node_id])
    return aliases, valid_ids, missing_ids


def _relation_road_refs(
    relation_props: dict[str, Any],
    road_refs_by_id: dict[str, tuple[_RoadRef, ...]],
) -> tuple[tuple[_RoadRef, ...], tuple[str, ...], tuple[str, ...]]:
    source_values = {_normalize_id(value) for value in _as_list(_case_get(relation_props, ("frcsd_road_source_values",)))}
    refs: list[_RoadRef] = []
    missing_road_ids: list[str] = []
    source_mismatches: list[str] = []
    for road_id in _as_id_list(_case_get(relation_props, ("frcsd_road_ids",))):
        all_candidates = road_refs_by_id.get(road_id, tuple())
        candidates = all_candidates
        if source_values:
            candidates = tuple(ref for ref in candidates if ref.source in source_values)
        if not candidates:
            if all_candidates:
                actual = "+".join(sorted({ref.source for ref in all_candidates}))
                declared = "+".join(sorted(source_values)) or "missing"
                source_mismatches.append(f"{road_id}:actual={actual}:declared={declared}")
            else:
                missing_road_ids.append(road_id)
        refs.extend(candidates)
    return (
        tuple(sorted(set(refs))),
        tuple(sorted(set(missing_road_ids), key=_sort_key)),
        tuple(sorted(set(source_mismatches))),
    )


def _relation_source_gate_risks(
    *,
    segment_id: str,
    relation_status: str,
    relation_props: dict[str, Any],
) -> tuple[str, ...]:
    if not _as_id_list(_case_get(relation_props, ("frcsd_road_ids",))):
        return tuple()
    allowed = {
        "replaced": {"1"},
        "retained_swsd": {"2"},
        "replaced+retained_swsd": {"1", "2"},
    }[relation_status]
    declared = set(
        _as_id_list(_case_get(relation_props, ("frcsd_road_source_values",)))
    )
    if not declared:
        return (
            f"segment_relation_source_values_missing:{segment_id}:{relation_status}",
        )
    invalid = declared - allowed
    if invalid:
        return (
            f"segment_relation_source_values_invalid:{segment_id}:{relation_status}:"
            f"{'+'.join(sorted(invalid))}",
        )
    return tuple()


def _missing_registered_road_endpoints(
    road: _FrcsdRoad,
    node_aliases: dict[str, set[str]],
) -> tuple[str, ...]:
    return tuple(
        label
        for label, node_id in (
            (f"snodeid={road.snodeid}", road.snodeid),
            (f"enodeid={road.enodeid}", road.enodeid),
        )
        if node_id not in node_aliases
    )


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


def _build_v2_restriction_features(
    *,
    rules: list[_Record],
    movements: list[_Record],
    carriers: dict[str, _ArmCarrier],
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
    expected_strategy: RestorationStrategy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    movement_by_key = {
        (
            _normalize_id(_case_get(item.properties, ("from_arm_id",))),
            _normalize_id(_case_get(item.properties, ("to_arm_id",))),
            str(_case_get(item.properties, ("movement_type",), default="")),
        ): item.properties
        for item in movements
    }
    stable: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    stable_keys: set[tuple[str, str, str, str, str, str]] = set()
    candidate_keys: set[tuple[str, ...]] = set()

    for rule in rules:
        rule_props = rule.properties
        raw_rule_strategy = str(_case_get(rule_props, ("strategy_version",), default="") or "").strip()
        try:
            rule_strategy = normalize_restoration_strategy(raw_rule_strategy)
        except ValueError:
            skipped[f"rule_strategy_invalid:{raw_rule_strategy or 'missing'}"] += 1
            continue
        if rule_strategy != expected_strategy:
            skipped[f"rule_strategy_mismatch:{rule_strategy.value}"] += 1
            continue

        from_arm_id = _required_id(_case_get(rule_props, ("from_arm_id",)), "restored rule from_arm_id")
        to_arm_id = _required_id(_case_get(rule_props, ("to_arm_id",)), "restored rule to_arm_id")
        movement_type = str(_case_get(rule_props, ("movement_type",), default="unknown") or "unknown")
        junction_id = _required_id(_case_get(rule_props, ("junction_id",)), "restored rule junction_id")
        movement_props = movement_by_key.get((from_arm_id, to_arm_id, movement_type), {})
        decision_status = str(_case_get(rule_props, ("decision_status",), default="") or "").strip()
        decision_source = str(_case_get(rule_props, ("decision_source",), default="") or "").strip()
        decision_scope = str(
            _case_get(rule_props, ("decision_scope",), default=_case_get(rule_props, ("rule_scope",), default=""))
            or ""
        ).strip()
        from_carrier = carriers.get(from_arm_id)
        to_carrier = carriers.get(to_arm_id)

        if decision_status != "prohibited":
            if decision_status in {"conflict", "manual_review_required", "unverified"}:
                _append_v2_candidate(
                    candidates=candidates,
                    candidate_keys=candidate_keys,
                    skipped=skipped,
                    rule=rule,
                    movement_props=movement_props,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    candidate_reason=f"decision_status_not_stable:{decision_status}",
                    verification_status="manual_review_required",
                )
            else:
                skipped[f"decision_status:{decision_status or 'missing'}"] += 1
            continue

        if decision_source != "restriction":
            _append_v2_candidate(
                candidates=candidates,
                candidate_keys=candidate_keys,
                skipped=skipped,
                rule=rule,
                movement_props=movement_props,
                from_carrier=from_carrier,
                to_carrier=to_carrier,
                road_by_ref=road_by_ref,
                candidate_reason="derived_rule_requires_frcsd_laneinfo",
                verification_status="unverified_due_to_missing_frcsd_laneinfo",
            )
            continue

        source_verification_status = str(
            _case_get(rule_props, ("verification_status",), default="") or ""
        ).strip()
        if source_verification_status != "verified_swsd":
            _append_v2_candidate(
                candidates=candidates,
                candidate_keys=candidate_keys,
                skipped=skipped,
                rule=rule,
                movement_props=movement_props,
                from_carrier=from_carrier,
                to_carrier=to_carrier,
                road_by_ref=road_by_ref,
                candidate_reason=(
                    "restriction_verification_not_stable:"
                    f"{source_verification_status or 'missing'}"
                ),
                verification_status="manual_review_required",
            )
            continue

        if decision_scope == "arm_to_arm":
            promotion_status = str(
                _case_get(rule_props, ("scope_promotion_status",), default="") or ""
            ).strip()
            promotion_audit = _json_like(
                _case_get(rule_props, ("scope_promotion_audit",), default={})
            )
            promotion_allowed = (
                isinstance(promotion_audit, dict)
                and promotion_audit.get("promotion_allowed") is True
            )
            if promotion_status != "arm_to_arm_confirmed" or not promotion_allowed:
                reason = (
                    f"status={promotion_status or 'missing'}"
                    if promotion_status != "arm_to_arm_confirmed"
                    else "promotion_allowed_not_true"
                )
                _append_v2_candidate(
                    candidates=candidates,
                    candidate_keys=candidate_keys,
                    skipped=skipped,
                    rule=rule,
                    movement_props=movement_props,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    candidate_reason=f"arm_scope_promotion_not_confirmed:{reason}",
                    verification_status="manual_review_required",
                )
                continue
            if from_carrier is None or to_carrier is None:
                _append_v2_candidate(
                    candidates=candidates,
                    candidate_keys=candidate_keys,
                    skipped=skipped,
                    rule=rule,
                    movement_props=movement_props,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    candidate_reason="arm_to_arm_carrier_missing",
                    verification_status="manual_review_required",
                )
                continue
            if not from_carrier.approach_refs or not to_carrier.exit_refs:
                reason = (
                    "from_arm_approach_missing"
                    if not from_carrier.approach_refs
                    else "to_arm_exit_missing"
                )
                _append_v2_candidate(
                    candidates=candidates,
                    candidate_keys=candidate_keys,
                    skipped=skipped,
                    rule=rule,
                    movement_props=movement_props,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    candidate_reason=reason,
                    verification_status="manual_review_required",
                )
                continue
            if _has_logical_road_source_collision(
                from_carrier.approach_refs
            ) or _has_logical_road_source_collision(to_carrier.exit_refs):
                _append_v2_candidate(
                    candidates=candidates,
                    candidate_keys=candidate_keys,
                    skipped=skipped,
                    rule=rule,
                    movement_props=movement_props,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    candidate_reason="arm_carrier_logical_road_source_collision",
                    verification_status="manual_review_required",
                )
                continue
            for from_ref in from_carrier.approach_refs:
                for to_ref in to_carrier.exit_refs:
                    _append_v2_stable(
                        stable=stable,
                        stable_keys=stable_keys,
                        skipped=skipped,
                        rule_props=rule_props,
                        movement_props=movement_props,
                        from_ref=from_ref,
                        to_ref=to_ref,
                        from_carrier=from_carrier,
                        to_carrier=to_carrier,
                        road_by_ref=road_by_ref,
                        junction_id=junction_id,
                        movement_type=movement_type,
                        decision_scope=decision_scope,
                    )
            continue

        if decision_scope == "road_to_road":
            road_pairs = _source_road_pairs(rule_props)
            if not road_pairs:
                _append_v2_candidate(
                    candidates=candidates,
                    candidate_keys=candidate_keys,
                    skipped=skipped,
                    rule=rule,
                    movement_props=movement_props,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    candidate_reason="road_to_road_explicit_pair_missing",
                    verification_status="manual_review_required",
                )
                continue
            resolved_pairs: list[
                tuple[str, str, _RoadRef | None, _RoadRef | None, str]
            ] = []
            for source_from_road_id, source_to_road_id in road_pairs:
                from_ref, from_reason = _resolve_road_scope_ref(
                    source_road_id=source_from_road_id,
                    refs=from_carrier.approach_refs if from_carrier is not None else tuple(),
                    role="from_arm_approach",
                )
                to_ref, to_reason = _resolve_road_scope_ref(
                    source_road_id=source_to_road_id,
                    refs=to_carrier.exit_refs if to_carrier is not None else tuple(),
                    role="to_arm_exit",
                )
                mapping_reason = ";".join(
                    reason for reason in (from_reason, to_reason) if reason
                )
                if from_carrier is None or to_carrier is None:
                    mapping_reason = mapping_reason or "arm_carrier_missing"
                resolved_pairs.append(
                    (
                        source_from_road_id,
                        source_to_road_id,
                        from_ref,
                        to_ref,
                        mapping_reason,
                    )
                )
            proposal_has_failure = any(
                from_ref is None or to_ref is None or mapping_reason
                for _, _, from_ref, to_ref, mapping_reason in resolved_pairs
            )
            if proposal_has_failure:
                for (
                    source_from_road_id,
                    source_to_road_id,
                    from_ref,
                    to_ref,
                    mapping_reason,
                ) in resolved_pairs:
                    _append_v2_candidate(
                        candidates=candidates,
                        candidate_keys=candidate_keys,
                        skipped=skipped,
                        rule=rule,
                        movement_props=movement_props,
                        from_carrier=from_carrier,
                        to_carrier=to_carrier,
                        road_by_ref=road_by_ref,
                        candidate_reason=(
                            f"road_to_road_mapping_not_exact:{mapping_reason}"
                            if mapping_reason
                            else "road_to_road_proposal_not_atomic"
                        ),
                        verification_status="manual_review_required",
                        source_road_pair=(source_from_road_id, source_to_road_id),
                        from_ref=from_ref,
                        to_ref=to_ref,
                    )
                continue
            for (
                _source_from_road_id,
                _source_to_road_id,
                from_ref,
                to_ref,
                _mapping_reason,
            ) in resolved_pairs:
                assert from_ref is not None and to_ref is not None
                assert from_carrier is not None and to_carrier is not None
                _append_v2_stable(
                    stable=stable,
                    stable_keys=stable_keys,
                    skipped=skipped,
                    rule_props=rule_props,
                    movement_props=movement_props,
                    from_ref=from_ref,
                    to_ref=to_ref,
                    from_carrier=from_carrier,
                    to_carrier=to_carrier,
                    road_by_ref=road_by_ref,
                    junction_id=junction_id,
                    movement_type=movement_type,
                    decision_scope=decision_scope,
                )
            continue

        _append_v2_candidate(
            candidates=candidates,
            candidate_keys=candidate_keys,
            skipped=skipped,
            rule=rule,
            movement_props=movement_props,
            from_carrier=from_carrier,
            to_carrier=to_carrier,
            road_by_ref=road_by_ref,
            candidate_reason=f"restriction_scope_not_stable:{decision_scope or 'missing'}",
            verification_status="manual_review_required",
        )

    return stable, candidates, skipped


def _append_v2_stable(
    *,
    stable: list[dict[str, Any]],
    stable_keys: set[tuple[str, str, str, str, str, str]],
    skipped: Counter[str],
    rule_props: dict[str, Any],
    movement_props: dict[str, Any],
    from_ref: _RoadRef,
    to_ref: _RoadRef,
    from_carrier: _ArmCarrier,
    to_carrier: _ArmCarrier,
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
    junction_id: str,
    movement_type: str,
    decision_scope: str,
) -> None:
    condition_identity = _condition_identity(rule_props)
    output_key = (
        from_ref.road_id,
        to_ref.road_id,
        junction_id,
        movement_type,
        condition_identity,
        decision_scope,
    )
    if output_key in stable_keys:
        skipped["duplicate_link_pair_condition_scope"] += 1
        return
    from_road = road_by_ref.get(from_ref)
    to_road = road_by_ref.get(to_ref)
    if from_road is None or to_road is None:
        skipped["frcsd_road_missing"] += 1
        return
    try:
        geometry = _restriction_geometry(from_road.geometry, to_road.geometry)
    except ValueError:
        skipped["invalid_restriction_geometry"] += 1
        return
    stable_keys.add(output_key)
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
    row.update(_v2_rule_audit_fields(rule_props, verification_status="verified_frcsd"))
    row["CondType"] = row["condition_type"]
    row["restriction_source"] = "restriction"
    row["movement_id"] = str(
        _case_get(rule_props, ("movement_id",), default=row.get("movement_id", "")) or row.get("movement_id", "")
    )
    stable.append({"properties": row, "geometry": geometry})


def _append_v2_candidate(
    *,
    candidates: list[dict[str, Any]],
    candidate_keys: set[tuple[str, ...]],
    skipped: Counter[str],
    rule: _Record,
    movement_props: dict[str, Any],
    from_carrier: _ArmCarrier | None,
    to_carrier: _ArmCarrier | None,
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
    candidate_reason: str,
    verification_status: str,
    source_road_pair: tuple[str, str] | None = None,
    from_ref: _RoadRef | None = None,
    to_ref: _RoadRef | None = None,
) -> None:
    rule_props = rule.properties
    junction_id = _required_id(_case_get(rule_props, ("junction_id",)), "restored rule junction_id")
    movement_type = str(_case_get(rule_props, ("movement_type",), default="unknown") or "unknown")
    rule_id = str(_case_get(rule_props, ("rule_id",), default="") or "")
    condition_identity = _condition_identity(rule_props)

    if source_road_pair is None:
        road_pairs = _source_road_pairs(rule_props)
        source_road_pair = road_pairs[0] if len(road_pairs) == 1 else None
        if source_road_pair is not None:
            if from_ref is None and from_carrier is not None:
                from_ref, _reason = _resolve_road_scope_ref(
                    source_road_id=source_road_pair[0],
                    refs=from_carrier.approach_refs,
                    role="from_arm_approach",
                )
            if to_ref is None and to_carrier is not None:
                to_ref, _reason = _resolve_road_scope_ref(
                    source_road_id=source_road_pair[1],
                    refs=to_carrier.exit_refs,
                    role="to_arm_exit",
                )

    source_from_road_id = source_road_pair[0] if source_road_pair else ""
    source_to_road_id = source_road_pair[1] if source_road_pair else ""
    decision_scope = str(
        _case_get(
            rule_props,
            ("decision_scope",),
            default=_case_get(rule_props, ("rule_scope",), default=""),
        )
        or ""
    )
    candidate_key = (
        source_from_road_id,
        source_to_road_id,
        junction_id,
        movement_type,
        condition_identity,
        decision_scope,
        rule_id,
        candidate_reason,
    )
    if candidate_key in candidate_keys:
        skipped["duplicate_candidate"] += 1
        return

    geometry, geometry_semantics = _candidate_geometry(
        rule_geometry=rule.geometry,
        from_ref=from_ref,
        to_ref=to_ref,
        from_carrier=from_carrier,
        to_carrier=to_carrier,
        road_by_ref=road_by_ref,
    )
    if geometry is None:
        skipped[f"candidate_geometry_missing:{candidate_reason}"] += 1

    row = _candidate_row(
        junction_id=junction_id,
        movement_type=movement_type,
        rule_props=rule_props,
        movement_props=movement_props,
        from_carrier=from_carrier,
        to_carrier=to_carrier,
        source_road_pair=source_road_pair,
        from_ref=from_ref,
        to_ref=to_ref,
        candidate_reason=candidate_reason,
        verification_status=verification_status,
        geometry_semantics=geometry_semantics,
    )
    candidate_keys.add(candidate_key)
    candidates.append({"properties": row, "geometry": geometry})


def _has_logical_road_source_collision(refs: tuple[_RoadRef, ...]) -> bool:
    sources_by_id: dict[str, set[str]] = {}
    for ref in refs:
        sources_by_id.setdefault(ref.road_id, set()).add(ref.source)
    return any(len(sources) > 1 for sources in sources_by_id.values())


def _resolve_road_scope_ref(
    *, source_road_id: str, refs: tuple[_RoadRef, ...], role: str
) -> tuple[_RoadRef | None, str]:
    exact_retained = tuple(ref for ref in refs if ref.source == "2" and ref.road_id == source_road_id)
    if len(exact_retained) == 1:
        return exact_retained[0], ""
    if len(exact_retained) > 1:
        return None, f"{role}_source2_same_id_ambiguous"
    if len(refs) == 1:
        return refs[0], ""
    if not refs:
        return None, f"{role}_missing"
    return None, f"{role}_not_unique"


def _source_road_pairs(rule_props: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in _as_list(_case_get(rule_props, ("road_pairs", "source_road_pairs"))):
        if not isinstance(item, dict):
            continue
        from_road_id = _normalize_id(_case_get(item, ("from_road_id", "in_link_id", "inLinkID")))
        to_road_id = _normalize_id(_case_get(item, ("to_road_id", "out_link_id", "outLinkID")))
        if from_road_id and to_road_id:
            pairs.append((from_road_id, to_road_id))
    if pairs:
        return tuple(dict.fromkeys(pairs))
    from_road_ids = _as_id_list(_case_get(rule_props, ("from_road_ids",)))
    to_road_ids = _as_id_list(_case_get(rule_props, ("to_road_ids",)))
    if len(from_road_ids) == 1 and len(to_road_ids) == 1:
        return ((from_road_ids[0], to_road_ids[0]),)
    return tuple()


def _candidate_row(
    *,
    junction_id: str,
    movement_type: str,
    rule_props: dict[str, Any],
    movement_props: dict[str, Any],
    from_carrier: _ArmCarrier | None,
    to_carrier: _ArmCarrier | None,
    source_road_pair: tuple[str, str] | None,
    from_ref: _RoadRef | None,
    to_ref: _RoadRef | None,
    candidate_reason: str,
    verification_status: str,
    geometry_semantics: str,
) -> dict[str, Any]:
    source_from_ids = _as_id_list(_case_get(rule_props, ("from_road_ids",)))
    source_to_ids = _as_id_list(_case_get(rule_props, ("to_road_ids",)))
    source_from_road_id = source_road_pair[0] if source_road_pair else (source_from_ids[0] if len(source_from_ids) == 1 else "")
    source_to_road_id = source_road_pair[1] if source_road_pair else (source_to_ids[0] if len(source_to_ids) == 1 else "")
    from_link_id = from_ref.road_id if from_ref is not None else source_from_road_id
    to_link_id = to_ref.road_id if to_ref is not None else source_to_road_id
    from_arm_id = _required_id(_case_get(rule_props, ("from_arm_id",)), "restored rule from_arm_id")
    to_arm_id = _required_id(_case_get(rule_props, ("to_arm_id",)), "restored rule to_arm_id")
    movement_id = str(
        _case_get(
            rule_props,
            ("movement_id",),
            default=_case_get(movement_props, ("movement_id",), default=""),
        )
        or ""
    )
    supporting_ids = _as_id_list(_case_get(rule_props, ("supporting_evidence_ids", "evidence_item_ids")))
    risk_flags = set(_as_id_list(_case_get(rule_props, ("risk_flags",))))
    risk_flags.update(_as_id_list(_case_get(movement_props, ("risk_flags",))))
    if from_carrier is not None:
        risk_flags.update(from_carrier.risk_flags)
    if to_carrier is not None:
        risk_flags.update(to_carrier.risk_flags)
    risk_flags.add("frcsd_restriction_candidate")
    if verification_status == "unverified_due_to_missing_frcsd_laneinfo":
        risk_flags.add("unverified_due_to_missing_frcsd_laneinfo")
    if geometry_semantics == "candidate_geometry_unavailable":
        risk_flags.add("candidate_geometry_unavailable")

    from_junction_ids = from_carrier.frcsd_junction_ids if from_carrier is not None else tuple()
    to_junction_ids = to_carrier.frcsd_junction_ids if to_carrier is not None else tuple()
    rule_id = str(_case_get(rule_props, ("rule_id",), default="") or "")
    candidate_id = rule_id or (
        f"{junction_id}:frcsd_restriction_candidate:{movement_type}:"
        f"{source_from_road_id or 'unknown'}->{source_to_road_id or 'unknown'}"
    )
    row = {
        "restriction_id": candidate_id,
        "CondType": "",
        "LinkID": from_link_id,
        "inLinkID": from_link_id,
        "outLinkID": to_link_id,
        "junction_id": junction_id,
        "frcsd_junction_id": _frcsd_junction_id(from_junction_ids, to_junction_ids),
        "from_arm_id": from_arm_id,
        "to_arm_id": to_arm_id,
        "from_frcsd_arm_id": from_carrier.frcsd_arm_id if from_carrier is not None else "",
        "to_frcsd_arm_id": to_carrier.frcsd_arm_id if to_carrier is not None else "",
        "movement_id": movement_id,
        "movement_type": movement_type,
        "restriction_source": str(_case_get(rule_props, ("decision_source",), default="unknown") or "unknown"),
        "source_rule_status": str(
            _case_get(rule_props, ("field_rule_status", "decision_status"), default="unknown") or "unknown"
        ),
        "confidence": _parse_float(_case_get(rule_props, ("confidence",), default=0.0)),
        "supporting_evidence_ids": supporting_ids,
        "from_road_source": from_ref.source if from_ref is not None else "",
        "to_road_source": to_ref.source if to_ref is not None else "",
        "from_arm_relation_status": from_carrier.relation_status if from_carrier is not None else "missing_relation",
        "to_arm_relation_status": to_carrier.relation_status if to_carrier is not None else "missing_relation",
        "arm_relation_status": (
            f"from:{from_carrier.relation_status if from_carrier is not None else 'missing_relation'};"
            f"to:{to_carrier.relation_status if to_carrier is not None else 'missing_relation'}"
        ),
        "risk_flags": sorted(risk_flags),
        "candidate_reason": candidate_reason,
        "geometry_semantics": geometry_semantics,
    }
    row.update(_v2_rule_audit_fields(rule_props, verification_status=verification_status))
    row["CondType"] = row["condition_type"]
    return row


def _v2_rule_audit_fields(rule_props: dict[str, Any], *, verification_status: str) -> dict[str, Any]:
    decision_scope = _case_get(rule_props, ("decision_scope",))
    if decision_scope in {None, ""}:
        decision_scope = _case_get(rule_props, ("rule_scope",), default="")
    condition_type = _case_get(rule_props, ("condition_type", "CondType"), default="")
    source_road_pairs = [
        {"from_road_id": from_road_id, "to_road_id": to_road_id}
        for from_road_id, to_road_id in _source_road_pairs(rule_props)
    ]
    return {
        "strategy_version": str(_case_get(rule_props, ("strategy_version",), default="") or ""),
        "decision_status": str(_case_get(rule_props, ("decision_status",), default="") or ""),
        "decision_source": str(_case_get(rule_props, ("decision_source",), default="") or ""),
        "decision_scope": str(decision_scope or ""),
        "evidence_priority": str(_case_get(rule_props, ("evidence_priority",), default="") or ""),
        "inference_level": str(_case_get(rule_props, ("inference_level",), default="") or ""),
        "verification_status": verification_status,
        "condition_type": "" if condition_type is None else str(condition_type),
        "condition_payload": _json_like(_case_get(rule_props, ("condition_payload",), default=[])),
        "condition_identity": _condition_identity(rule_props),
        "condition_semantics_status": str(
            _case_get(rule_props, ("condition_semantics_status",), default="unknown") or "unknown"
        ),
        "conflicting_evidence_ids": _as_id_list(_case_get(rule_props, ("conflicting_evidence_ids",))),
        "override_chain": _json_like(_case_get(rule_props, ("override_chain",), default=[])),
        "source_restriction_ids": _as_id_list(_case_get(rule_props, ("source_restriction_ids",))),
        "source_rule_id": str(_case_get(rule_props, ("rule_id",), default="") or ""),
        "source_from_road_ids": _as_id_list(_case_get(rule_props, ("from_road_ids",))),
        "source_to_road_ids": _as_id_list(_case_get(rule_props, ("to_road_ids",))),
        "source_road_pairs": source_road_pairs,
        "scope_promotion_status": str(
            _case_get(rule_props, ("scope_promotion_status",), default="") or ""
        ),
        "scope_promotion_reason": str(
            _case_get(rule_props, ("scope_promotion_reason",), default="") or ""
        ),
        "scope_promotion_audit": _json_like(
            _case_get(rule_props, ("scope_promotion_audit",), default={})
        ),
    }


def _candidate_geometry(
    *,
    rule_geometry: BaseGeometry | None,
    from_ref: _RoadRef | None,
    to_ref: _RoadRef | None,
    from_carrier: _ArmCarrier | None,
    to_carrier: _ArmCarrier | None,
    road_by_ref: dict[_RoadRef, _FrcsdRoad],
) -> tuple[LineString | None, str]:
    if from_ref is not None and to_ref is not None:
        from_road = road_by_ref.get(from_ref)
        to_road = road_by_ref.get(to_ref)
        if from_road is not None and to_road is not None:
            try:
                return _restriction_geometry(from_road.geometry, to_road.geometry), "exact_mapped_pair_candidate"
            except ValueError:
                pass
    source_line = _as_line_string(rule_geometry)
    if source_line is not None:
        return source_line, "source_rule_geometry"
    for ref, semantics in (
        (from_ref, "mapped_from_carrier_context"),
        (to_ref, "mapped_to_carrier_context"),
    ):
        road = road_by_ref.get(ref) if ref is not None else None
        line = _as_line_string(road.geometry if road is not None else None)
        if line is not None:
            return line, semantics
    context_refs: set[_RoadRef] = set()
    if from_carrier is not None:
        context_refs.update(from_carrier.approach_refs)
    if to_carrier is not None:
        context_refs.update(to_carrier.exit_refs)
    context_roads = [road_by_ref[ref] for ref in context_refs if ref in road_by_ref]
    context_roads.sort(key=lambda road: (-float(road.geometry.length), road.ref.source, road.ref.road_id))
    for road in context_roads:
        line = _as_line_string(road.geometry)
        if line is not None:
            return line, "arm_carrier_context_only_not_a_verified_mapping"
    return None, "candidate_geometry_unavailable"


def _as_line_string(geometry: BaseGeometry | None) -> LineString | None:
    coords = _line_coords(geometry)
    if len(coords) < 2:
        return None
    return LineString(coords)


def _json_like(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _condition_identity(rule_props: dict[str, Any]) -> str:
    explicit = str(_case_get(rule_props, ("condition_identity",), default="") or "").strip()
    if explicit:
        return explicit
    condition_type = _case_get(rule_props, ("condition_type", "CondType"), default="")
    payload = _json_like(_case_get(rule_props, ("condition_payload",), default=[]))
    if condition_type in {None, ""} and (payload is None or payload == ""):
        return ""
    if condition_type in {None, ""} and payload in ([], {}):
        return ""
    return json.dumps(
        {"condition_type": condition_type, "condition_payload": payload},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


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
    input_audit: dict[str, dict[str, Any]] | None = None,
    input_counts: dict[str, int],
    carriers: dict[str, _ArmCarrier],
    restrictions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    skipped: Counter[str],
    strategy: RestorationStrategy,
    stage_timings: dict[str, float] | None = None,
    runtime_environment: dict[str, Any] | None = None,
    output_paths: dict[str, Path],
) -> dict[str, Any]:
    audited_inputs = input_audit or {
        key: {
            "requested_path": str(value),
            "resolved_path": str(Path(value).expanduser().resolve()),
            "requested_layer_name": None,
            "resolved_layer_name": None,
            "field_names": [],
            "feature_count": input_counts.get(key),
            "source_crs": None,
            "output_crs": None,
            "crs_source": "not_recorded",
            "crs_transform_executed": False,
        }
        for key, value in input_paths.items()
    }
    timings = {
        key: round(float(value), 6)
        for key, value in (
            stage_timings
            or {"run_before_summary_write_seconds": elapsed_seconds}
        ).items()
    }
    runtime = runtime_environment or _runtime_environment()
    crs_transform_executed = any(
        bool(audit.get("crs_transform_executed"))
        for audit in audited_inputs.values()
    )
    relation_status_counts = Counter(carrier.relation_status for carrier in carriers.values())
    risk_counts = Counter(flag for carrier in carriers.values() for flag in carrier.risk_flags)
    movement_type_counts = Counter(item["properties"].get("movement_type") for item in restrictions)
    rows = restrictions + candidates
    row_properties = [item["properties"] for item in rows]

    def property_counts(name: str) -> Counter[str]:
        return Counter(
            str(properties[name])
            for properties in row_properties
            if properties.get(name) not in {None, ""}
        )

    decision_status_counts = property_counts("decision_status")
    decision_source_counts = property_counts("decision_source")
    decision_scope_counts = property_counts("decision_scope")
    evidence_priority_counts = property_counts("evidence_priority")
    inference_level_counts = property_counts("inference_level")
    verification_status_counts = property_counts("verification_status")
    condition_identity_counts = property_counts("condition_identity")
    condition_type_counts = property_counts("condition_type")
    condition_semantics_status_counts = property_counts("condition_semantics_status")
    scope_promotion_status_counts = property_counts("scope_promotion_status")

    conflicting_reference_count = sum(
        len(_as_id_list(properties.get("conflicting_evidence_ids")))
        for properties in row_properties
    )
    conflicting_row_count = sum(
        bool(_as_id_list(properties.get("conflicting_evidence_ids")))
        for properties in row_properties
    )
    override_chains = [
        parsed
        for properties in row_properties
        for parsed in [_json_like(properties.get("override_chain", []))]
    ]
    override_entry_count = sum(
        len(chain) if isinstance(chain, (list, tuple)) else int(bool(chain))
        for chain in override_chains
    )
    override_row_count = sum(bool(chain) for chain in override_chains)
    output_risk_counts = Counter(
        flag
        for properties in row_properties
        for flag in _as_id_list(properties.get("risk_flags"))
    )
    promotion_audits = [
        parsed if isinstance(parsed, dict) else {}
        for properties in row_properties
        for parsed in [_json_like(properties.get("scope_promotion_audit", {}))]
    ]
    candidate_reason_counts = Counter(
        item["properties"].get("candidate_reason")
        for item in candidates
        if item["properties"].get("candidate_reason")
    )
    combined_risk_counts = risk_counts + output_risk_counts
    skipped_count = sum(skipped.values())
    return {
        "tool": "T09 Step3",
        "stage": "frcsd_restriction_modeling",
        "strategy_version": strategy.value,
        "run_id": run_id,
        "produced_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_epsg": target_epsg,
        "output_crs": f"EPSG:{target_epsg}",
        "input_paths": {key: str(Path(value).expanduser().resolve()) for key, value in input_paths.items()},
        "input_audit": audited_inputs,
        "input_counts": input_counts,
        "runtime_environment": runtime,
        "stage_durations_seconds": timings,
        "stage_duration_scope": (
            "independent wall-clock spans; summary assembly/write is excluded, and "
            "run_before_summary_write includes orchestration overhead"
        ),
        "arm_carrier_count": len(carriers),
        "arm_carrier_relation_status_counts": dict(sorted(relation_status_counts.items())),
        "arm_carrier_risk_flag_counts": dict(sorted(risk_counts.items())),
        "stable_count": len(restrictions),
        "restriction_count": len(restrictions),
        "candidate_count": len(candidates),
        "skipped_count": skipped_count,
        "output_row_counts": {
            "stable_rows": len(restrictions),
            "candidate_rows": len(candidates),
        },
        "processing_event_counts": {
            "skipped_events": skipped_count,
            "count_semantics": (
                "skip counters are non-exclusive processing events and are not a funnel denominator"
            ),
        },
        "restriction_movement_type_counts": dict(sorted(movement_type_counts.items())),
        "decision_status_counts": dict(sorted(decision_status_counts.items())),
        "decision_source_counts": dict(sorted(decision_source_counts.items())),
        "rule_scope_counts": dict(sorted(decision_scope_counts.items())),
        "decision_scope_counts": dict(sorted(decision_scope_counts.items())),
        "evidence_priority_counts": dict(sorted(evidence_priority_counts.items())),
        "inference_level_counts": dict(sorted(inference_level_counts.items())),
        "verification_status_counts": dict(sorted(verification_status_counts.items())),
        "condition_identity_counts": dict(sorted(condition_identity_counts.items())),
        "condition_type_counts": dict(sorted(condition_type_counts.items())),
        "condition_semantics_status_counts": dict(
            sorted(condition_semantics_status_counts.items())
        ),
        "condition_counts": {
            "rows_with_condition_identity": sum(condition_identity_counts.values()),
            "unique_condition_identity_count": len(condition_identity_counts),
            "condition_identity_counts": dict(sorted(condition_identity_counts.items())),
            "condition_type_counts": dict(sorted(condition_type_counts.items())),
            "condition_semantics_status_counts": dict(
                sorted(condition_semantics_status_counts.items())
            ),
        },
        "scope_promotion_status_counts": dict(sorted(scope_promotion_status_counts.items())),
        "scope_promotion_counts": {
            "status_counts": dict(sorted(scope_promotion_status_counts.items())),
            "promotion_allowed_row_count": sum(
                bool(audit.get("promotion_allowed")) for audit in promotion_audits
            ),
            "manual_review_row_count": scope_promotion_status_counts.get(
                "manual_review_required", 0
            ),
            "unexplained_carrier_count": sum(
                int(audit.get("unexplained_carrier_count", 0) or 0)
                for audit in promotion_audits
            ),
        },
        "conflict_count": conflicting_reference_count,
        "conflict_counts": {
            "decision_conflict_row_count": decision_status_counts.get("conflict", 0),
            "rows_with_conflicting_evidence": conflicting_row_count,
            "conflicting_evidence_reference_count": conflicting_reference_count,
        },
        "override_count": override_entry_count,
        "override_counts": {
            "rows_with_override": override_row_count,
            "override_entry_count": override_entry_count,
        },
        "risk_flag_counts": dict(sorted(output_risk_counts.items())),
        "risk_counts": {
            "carrier": dict(sorted(risk_counts.items())),
            "output_rows": dict(sorted(output_risk_counts.items())),
            "combined": dict(sorted(combined_risk_counts.items())),
            "combined_reference_count": sum(combined_risk_counts.values()),
        },
        "candidate_reason_counts": dict(sorted(candidate_reason_counts.items())),
        "skipped_counts": dict(sorted(skipped.items())),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "elapsed_seconds_scope": "run_before_summary_assembly_and_write",
        "outputs": {key: str(path) for key, path in output_paths.items()},
        "business_policy": {
            "generated_rule_status": "fully_prohibited" if strategy == RestorationStrategy.RESTRICTION_ONLY_V1 else "prohibited",
            "prohibition_source": "explicit_restriction_only" if strategy == RestorationStrategy.RESTRICTION_ONLY_V1 else "restriction_prohibited_only_for_stable",
            "partial_rule_policy": "do_not_expand_to_frcsd_restriction",
            "non_restriction_evidence_policy": (
                "arrow and special carrier evidence never generate FRCSD restriction alone"
                if strategy == RestorationStrategy.RESTRICTION_ONLY_V1
                else "laneinfo and special carrier road-level decisions are emitted only as unverified candidates while FRCSD Laneinfo is unavailable"
            ),
            "road_to_road_policy": (
                "legacy arm carrier expansion for fully_prohibited explicit restriction"
                if strategy == RestorationStrategy.RESTRICTION_ONLY_V1
                else "map each explicit source road pair only through a same-id source=2 carrier or a unique Arm-role carrier; never expand ambiguous road scope"
            ),
            "condition_policy": (
                "legacy CondType compatibility"
                if strategy == RestorationStrategy.RESTRICTION_ONLY_V1
                else "preserve condition type, raw payload and condition identity; deduplicate stable rows by condition identity and scope"
            ),
            "carrier_mapping_source": "T06 swsd_frcsd_segment_relation plus retained source=2 SWSD seed roads still present in T06 F-RCSD output",
            "frcsd_link_fields": ["LinkID", "outLinkID"],
        },
        "qa": {
            "crs_transform_executed": crs_transform_executed,
            "crs_transform_fact": (
                f"vector inputs use vector_io output EPSG:{target_epsg}; "
                "spatial JSON with one valid declared CRS is transformed to target when required; "
                "mixed or invalid JSON CRS is rejected; CSV is non-spatial"
            ),
            "topology_silent_fix": False,
            "topology_consistency": "FRCSD carrier roads are selected through T06 segment relation; retained source=2 SWSD seed fallback requires the road to remain in T06 F-RCSD output and pass endpoint direction at the SWSD junction aliases",
            "geometry_semantics": "restriction geometry connects the selected FRCSD incoming carrier road to the outgoing carrier road without repairing source geometry",
            "audit_traceability": "each output row retains source arm ids, movement id, supporting and conflicting evidence ids, strategy, scope, condition, override chain, source values and relation status",
            "performance_verifiable": {
                "elapsed_seconds": round(elapsed_seconds, 6),
                "elapsed_seconds_scope": "run_before_summary_assembly_and_write",
                "restrictions_per_second": _items_per_second(len(restrictions), elapsed_seconds),
                "stable_and_candidates_per_second": _items_per_second(len(restrictions) + len(candidates), elapsed_seconds),
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


def _feature_json(feature: dict[str, Any], *, crs_text: str) -> dict[str, Any]:
    geometry = feature.get("geometry")
    return {
        "properties": feature.get("properties") or {},
        "geometry": mapping(geometry) if isinstance(geometry, BaseGeometry) else geometry,
        "crs": crs_text,
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
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


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


def _runtime_environment() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "working_directory": str(Path.cwd()),
    }


def _default_run_id() -> str:
    return "t09_frcsd_restriction_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
