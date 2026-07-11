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


from .frcsd_restriction_pipeline import (
    run_t09_frcsd_restriction_modeling,
    _build_arm_carriers,
    _add_retained_swsd_seed_refs,
    _build_restriction_features,
    _build_v2_restriction_features,
    _append_v2_stable,
    _append_v2_candidate,
    _has_logical_road_source_collision,
    _resolve_road_scope_ref,
    _source_road_pairs,
    _candidate_row,
    _v2_rule_audit_fields,
    _candidate_geometry,
    _as_line_string,
    _json_like,
    _condition_identity,
    _restriction_row,
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
