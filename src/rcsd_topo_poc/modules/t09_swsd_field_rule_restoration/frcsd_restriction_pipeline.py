from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from . import frcsd_restriction as _facade


def T09FrcsdRestrictionArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T09FrcsdRestrictionArtifacts(*args, **kwargs)


def T09FrcsdRestrictionRunResult(*args: Any, **kwargs: Any) -> Any:
    return _facade.T09FrcsdRestrictionRunResult(*args, **kwargs)


def _ArmCarrier(*args: Any, **kwargs: Any) -> Any:
    return _facade._ArmCarrier(*args, **kwargs)


def _Record(*args: Any, **kwargs: Any) -> Any:
    return _facade._Record(*args, **kwargs)


def _RoadRef(*args: Any, **kwargs: Any) -> Any:
    return _facade._RoadRef(*args, **kwargs)


def _as_id_list(*args: Any, **kwargs: Any) -> Any:
    return _facade._as_id_list(*args, **kwargs)


def _as_list(*args: Any, **kwargs: Any) -> Any:
    return _facade._as_list(*args, **kwargs)


def _build_frcsd_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_frcsd_roads(*args, **kwargs)


def _build_node_aliases(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_node_aliases(*args, **kwargs)


def _case_get(*args: Any, **kwargs: Any) -> Any:
    return _facade._case_get(*args, **kwargs)


def _central_node_aliases(*args: Any, **kwargs: Any) -> Any:
    return _facade._central_node_aliases(*args, **kwargs)


def _default_run_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._default_run_id(*args, **kwargs)


def _feature_json(*args: Any, **kwargs: Any) -> Any:
    return _facade._feature_json(*args, **kwargs)


def _filter_rules_for_strategy(*args: Any, **kwargs: Any) -> Any:
    return _facade._filter_rules_for_strategy(*args, **kwargs)


def _frcsd_junction_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._frcsd_junction_id(*args, **kwargs)


def _junction_node_aliases(*args: Any, **kwargs: Any) -> Any:
    return _facade._junction_node_aliases(*args, **kwargs)


def _line_coords(*args: Any, **kwargs: Any) -> Any:
    return _facade._line_coords(*args, **kwargs)


def _missing_registered_road_endpoints(*args: Any, **kwargs: Any) -> Any:
    return _facade._missing_registered_road_endpoints(*args, **kwargs)


def _normalize_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._normalize_id(*args, **kwargs)


def _parse_float(*args: Any, **kwargs: Any) -> Any:
    return _facade._parse_float(*args, **kwargs)


def _read_records_with_audit(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_records_with_audit(*args, **kwargs)


def _relation_road_refs(*args: Any, **kwargs: Any) -> Any:
    return _facade._relation_road_refs(*args, **kwargs)


def _relation_source_gate_risks(*args: Any, **kwargs: Any) -> Any:
    return _facade._relation_source_gate_risks(*args, **kwargs)


def _required_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._required_id(*args, **kwargs)


def _restriction_geometry(*args: Any, **kwargs: Any) -> Any:
    return _facade._restriction_geometry(*args, **kwargs)


def _restriction_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._restriction_id(*args, **kwargs)


def _restriction_source(*args: Any, **kwargs: Any) -> Any:
    return _facade._restriction_source(*args, **kwargs)


def _road_refs_by_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_refs_by_id(*args, **kwargs)


def _road_roles_at_junction(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_roles_at_junction(*args, **kwargs)


def _runtime_environment(*args: Any, **kwargs: Any) -> Any:
    return _facade._runtime_environment(*args, **kwargs)


def _sort_key(*args: Any, **kwargs: Any) -> Any:
    return _facade._sort_key(*args, **kwargs)


def _status_mix(*args: Any, **kwargs: Any) -> Any:
    return _facade._status_mix(*args, **kwargs)


def _summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._summary(*args, **kwargs)


def _write_csv(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_csv(*args, **kwargs)


def normalize_restoration_strategy(*args: Any, **kwargs: Any) -> Any:
    return _facade.normalize_restoration_strategy(*args, **kwargs)


def write_gpkg(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_gpkg(*args, **kwargs)


def write_json(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_json(*args, **kwargs)


from .frcsd_restriction_runner import run_t09_frcsd_restriction_modeling

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
    expected_strategy: _facade.RestorationStrategy,
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
