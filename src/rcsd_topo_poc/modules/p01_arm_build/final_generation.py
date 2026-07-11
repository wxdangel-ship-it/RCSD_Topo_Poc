from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as transform_geometry

from rcsd_topo_poc.modules.p01_arm_build.models import (
    DATASETS,
    ArmMovement,
    DatasetBuildResult,
    LoadedDataset,
    RawRoadNextRoad,
    RoadRecord,
    to_plain,
)


SOURCE_TO_DATASET = {"1": "RCSD", "2": "SWSD"}
DATASET_TO_SOURCE = {"RCSD": "1", "SWSD": "2"}
MOVEMENT_TURNTYPE = {"unknown": "0", "straight": "1", "left": "2", "right": "3", "uturn": "4"}
SOURCE_GEOMETRY_MATCH_DECIMALS = 7
GENERATABLE_RULE_STATUSES = {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}


from . import final_road_next_road as _facade


def ArmSourceProfile(*args: Any, **kwargs: Any) -> Any:
    return _facade.ArmSourceProfile(*args, **kwargs)


def FinalGenerationDecision(*args: Any, **kwargs: Any) -> Any:
    return _facade.FinalGenerationDecision(*args, **kwargs)


def FrcsdGenerationAudit(*args: Any, **kwargs: Any) -> Any:
    return _facade.FrcsdGenerationAudit(*args, **kwargs)


def FrcsdRoadNextRoadFinalResult(*args: Any, **kwargs: Any) -> Any:
    return _facade.FrcsdRoadNextRoadFinalResult(*args, **kwargs)


def RoadRole(*args: Any, **kwargs: Any) -> Any:
    return _facade.RoadRole(*args, **kwargs)


def SourceArmPassRule(*args: Any, **kwargs: Any) -> Any:
    return _facade.SourceArmPassRule(*args, **kwargs)


def _arm_entering_roles(*args: Any, **kwargs: Any) -> Any:
    return _facade._arm_entering_roles(*args, **kwargs)


def _arm_source_profiles(*args: Any, **kwargs: Any) -> Any:
    return _facade._arm_source_profiles(*args, **kwargs)


def _audit(*args: Any, **kwargs: Any) -> Any:
    return _facade._audit(*args, **kwargs)


def _choose_reference_source(*args: Any, **kwargs: Any) -> Any:
    return _facade._choose_reference_source(*args, **kwargs)


def _feature_properties(*args: Any, **kwargs: Any) -> Any:
    return _facade._feature_properties(*args, **kwargs)


def _generation_target_roles(*args: Any, **kwargs: Any) -> Any:
    return _facade._generation_target_roles(*args, **kwargs)


def _issues_from_audit(*args: Any, **kwargs: Any) -> Any:
    return _facade._issues_from_audit(*args, **kwargs)


def _matched_source_arm(*args: Any, **kwargs: Any) -> Any:
    return _facade._matched_source_arm(*args, **kwargs)


def _movement_type_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._movement_type_index(*args, **kwargs)


def _norm(*args: Any, **kwargs: Any) -> Any:
    return _facade._norm(*args, **kwargs)


def _parallel_branch_alignment(*args: Any, **kwargs: Any) -> Any:
    return _facade._parallel_branch_alignment(*args, **kwargs)


def _parallel_count_by_entering_arm(*args: Any, **kwargs: Any) -> Any:
    return _facade._parallel_count_by_entering_arm(*args, **kwargs)


def _policy_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._policy_index(*args, **kwargs)


def _raw_by_needed_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._raw_by_needed_id(*args, **kwargs)


def _road_roles(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_roles(*args, **kwargs)


def _rule_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._rule_index(*args, **kwargs)


def _source_arm_pass_rules(*args: Any, **kwargs: Any) -> Any:
    return _facade._source_arm_pass_rules(*args, **kwargs)


def _source_policy(*args: Any, **kwargs: Any) -> Any:
    return _facade._source_policy(*args, **kwargs)


def _source_road_map(*args: Any, **kwargs: Any) -> Any:
    return _facade._source_road_map(*args, **kwargs)


def build_frcsd_road_next_road(
    *,
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
    road_next_road_by_dataset: dict[str, tuple[RawRoadNextRoad, ...]],
    junction_group_id: str = "",
    progress: Callable[[str], None] | None = None,
) -> FrcsdRoadNextRoadFinalResult:
    def _phase(message: str) -> None:
        if progress is not None:
            progress(message)

    _phase("roles start")
    roles = {dataset: _road_roles(result_by_dataset[dataset]) for dataset in DATASETS}
    _phase(
        "roles done "
        + " ".join(f"{dataset}={len(roles[dataset])}" for dataset in DATASETS)
    )
    source_map = _source_road_map(
        loaded_by_dataset=loaded_by_dataset,
        f_roles=roles["FRCSD"],
        progress=lambda message: _phase(message),
    )
    _phase(f"source map done records={len(source_map)}")
    arm_source_profiles = _arm_source_profiles(
        loaded_frcsd=loaded_by_dataset["FRCSD"],
        result_frcsd=result_by_dataset["FRCSD"],
        f_roles=roles["FRCSD"],
    )
    _phase(f"arm source profiles done records={len(arm_source_profiles)}")
    parallel_alignment = _parallel_branch_alignment(
        junction_group_id=junction_group_id,
        loaded_by_dataset=loaded_by_dataset,
        result_by_dataset=result_by_dataset,
        roles=roles,
        source_map=source_map,
    )
    _phase(f"parallel branch alignment done records={len(parallel_alignment)}")
    source_map_by_f = {item.f_road_id: item for item in source_map}
    _phase("source policy start")
    policies = {
        "SWSD": _source_policy(source_dataset="SWSD", result=result_by_dataset["SWSD"], roles=roles["SWSD"]),
        "RCSD": _source_policy(source_dataset="RCSD", result=result_by_dataset["RCSD"], roles=roles["RCSD"]),
    }
    source_arm_pass_rules = {
        "SWSD": _source_arm_pass_rules(source_dataset="SWSD", result=result_by_dataset["SWSD"], roles=roles["SWSD"]),
        "RCSD": _source_arm_pass_rules(source_dataset="RCSD", result=result_by_dataset["RCSD"], roles=roles["RCSD"]),
    }
    _phase(
        "source policy done "
        f"swsd_policy={len(policies['SWSD'])} rcsd_policy={len(policies['RCSD'])} "
        f"swsd_rules={len(source_arm_pass_rules['SWSD'])} rcsd_rules={len(source_arm_pass_rules['RCSD'])}"
    )
    needed_raw_ids = {
        dataset: {
            evidence_id
            for rule in source_arm_pass_rules[dataset]
            for evidence_id in rule.source_evidence_ids
        }
        for dataset in ("SWSD", "RCSD")
    }
    raw_by_source = {
        dataset: _raw_by_needed_id(road_next_road_by_dataset.get(dataset, tuple()), needed_raw_ids[dataset])
        for dataset in ("SWSD", "RCSD")
    }
    rule_indexes = {dataset: _rule_index(source_arm_pass_rules[dataset]) for dataset in ("SWSD", "RCSD")}
    movement_type_indexes = {dataset: _movement_type_index(result_by_dataset[dataset]) for dataset in ("SWSD", "RCSD")}
    policy_indexes = {dataset: _policy_index(policies[dataset]) for dataset in ("SWSD", "RCSD")}
    source_parallel_counts = {
        dataset: _parallel_count_by_entering_arm(result_by_dataset[dataset], roles[dataset]) for dataset in ("SWSD", "RCSD")
    }
    f_parallel_counts = _parallel_count_by_entering_arm(result_by_dataset["FRCSD"], roles["FRCSD"])
    validation_status_by_arm = {arm.final_arm_id: arm.validation_status for arm in result_by_dataset["FRCSD"].final_arms}
    profile_by_arm = {profile.arm_id: profile for profile in arm_source_profiles}
    source_arm_matches = {
        arm.final_arm_id: {
            dataset: _matched_source_arm(
                f_arm_id=arm.final_arm_id,
                source_dataset=dataset,
                result_by_dataset=result_by_dataset,
                roles=roles,
                source_map_by_f=source_map_by_f,
            )
            for dataset in ("SWSD", "RCSD")
        }
        for arm in result_by_dataset["FRCSD"].final_arms
    }
    _phase(f"source arm matches done arms={len(source_arm_matches)}")
    advance_right_pairs = {
        (relation.from_arm_id, relation.to_arm_id)
        for relation in result_by_dataset["FRCSD"].advance_right_turn_relations
        if relation.from_arm_id and relation.to_arm_id
    }
    features: list[dict[str, Any]] = []
    audit_rows: list[FrcsdGenerationAudit] = []
    decisions: list[FinalGenerationDecision] = []
    generated_pairs: set[tuple[str, str]] = set()
    duplicate_count = 0

    def append_feature(f_from: str, f_to: str, movement: ArmMovement, reference_source: str, evidence_ids: tuple[str, ...]) -> bool:
        nonlocal duplicate_count
        pair = (f_from, f_to)
        if pair in generated_pairs:
            duplicate_count += 1
            return False
        generated_pairs.add(pair)
        props = _feature_properties(
            index=len(features) + 1,
            f_road_id=f_from,
            f_next_road_id=f_to,
            movement_type=movement.movement_type,
            reference_source=reference_source,
            evidence_ids=evidence_ids,
            raw_by_source=raw_by_source,
        )
        features.append({"type": "Feature", "properties": props, "geometry": None})
        return True

    def right_turn_carrier_issues(movement: ArmMovement, from_role: RoadRole) -> tuple[str, ...]:
        if movement.movement_type != "right" or from_role.road_role != "trunk":
            return tuple()
        has_parallel_carrier = f_parallel_counts[movement.from_arm_id] > 0
        has_advance_right_carrier = (movement.from_arm_id, movement.to_arm_id) in advance_right_pairs
        if has_parallel_carrier or has_advance_right_carrier:
            return tuple()
        return ("data_error_or_missing_right_turn_carrier", "data_error")

    def final_arm_validation_issues(movement: ArmMovement) -> tuple[str, ...]:
        flags: list[str] = []
        for arm_id in (movement.from_arm_id, movement.to_arm_id):
            status = validation_status_by_arm.get(arm_id)
            if status == "conflict":
                flags.append("final_arm_validation_conflict")
            elif status == "unvalidated":
                flags.append("final_arm_validation_unvalidated")
            elif status == "weak_validated":
                flags.append("final_arm_validation_weak")
        return tuple(sorted(set(flags)))

    def with_validation_issues(movement: ArmMovement, issue_flags: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(issue_flags).union(final_arm_validation_issues(movement))))

    def has_blocking_issue(issue_flags: tuple[str, ...]) -> bool:
        blocking = {
            "data_error",
            "manual_review_required",
            "parallel_branch_count_mismatch_manual_review_required",
            "data_error_partial_target_coverage",
            "target_arm_exit_roads_missing",
        }
        return any(flag in blocking for flag in issue_flags)

    def resolve_source_movement_type(
        movement: ArmMovement,
        reference_source: str,
        source_from_arm: str | None,
        source_to_arm: str | None,
    ) -> tuple[str, tuple[str, ...]]:
        if movement.movement_type != "unknown" or not source_from_arm or not source_to_arm:
            return movement.movement_type, tuple()
        candidates = movement_type_indexes[reference_source].get((source_from_arm, source_to_arm), tuple())
        if len(candidates) == 1:
            return candidates[0], (
                "movement_type_resolved_from_reference_source",
                f"movement_type_resolved_from_{reference_source.lower()}",
            )
        if len(candidates) > 1:
            return movement.movement_type, ("source_movement_type_conflict", "manual_review_required")
        return movement.movement_type, tuple()

    def output_movement(movement: ArmMovement, source_rule: SourceArmPassRule | None) -> ArmMovement:
        if source_rule is None or source_rule.movement_type == movement.movement_type:
            return movement
        return replace(
            movement,
            movement_type=source_rule.movement_type,
            movement_type_source="reference_source_arm_movement",
            movement_type_confidence="medium",
            movement_type_reason="resolved_from_reference_source_rule",
        )

    def basic_swsd_rule(movement_type: str, from_road_role: str) -> SourceArmPassRule | None:
        if from_road_role == "parallel_branch":
            return None
        candidates = [
            rule
            for rule in source_arm_pass_rules["SWSD"]
            if rule.movement_type == movement_type
            and rule.from_road_role == from_road_role
            and rule.rule_status in {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}
        ]
        candidates.sort(
            key=lambda item: (
                {"full_allowed": 0, "trunk_only_allowed": 1, "left_receiving_only_allowed": 2}.get(item.rule_status, 9),
                item.from_arm_id,
                item.to_arm_id,
            )
        )
        return candidates[0] if candidates else None

    def rule_for(
        *,
        movement: ArmMovement,
        from_road_role: str,
        reference_source: str,
        reference_reason: str,
    ) -> tuple[SourceArmPassRule | None, str, str, tuple[str, ...]]:
        issues: list[str] = []
        source_from_arm, from_match_reason = source_arm_matches[movement.from_arm_id][reference_source]
        source_to_arm, to_match_reason = source_arm_matches[movement.to_arm_id][reference_source]
        effective_source = reference_source
        generation_rule = "structure_matched_source_rule"
        if reference_reason in {"single_source_rcsd", "single_source_swsd"}:
            generation_rule = "same_source_inherited"
        primary_rule: SourceArmPassRule | None = None
        primary_movement_type = movement.movement_type
        if source_from_arm and source_to_arm:
            primary_movement_type, movement_type_issues = resolve_source_movement_type(
                movement, reference_source, source_from_arm, source_to_arm
            )
            issues.extend(movement_type_issues)
            primary_rule = rule_indexes[reference_source].get((source_from_arm, source_to_arm, primary_movement_type, from_road_role))
            if primary_rule and primary_rule.rule_status in GENERATABLE_RULE_STATUSES:
                return primary_rule, effective_source, generation_rule, tuple(sorted(set(movement_type_issues)))
            if primary_rule:
                issues.append(f"{reference_source.lower()}_primary_source_rule_{primary_rule.rule_status}")

        if reference_source == "RCSD" and source_from_arm and not source_to_arm:
            issues.extend(("rcsd_target_arm_missing", "fallback_to_swsd_basic_rule"))
            fallback = basic_swsd_rule(primary_movement_type, from_road_role)
            if fallback:
                return fallback, "SWSD", "rcsd_to_swsd_fallback", tuple(sorted(set(issues)))
        alternate_source = "RCSD" if reference_source == "SWSD" else "SWSD"
        alternate_from_arm, alternate_from_reason = source_arm_matches[movement.from_arm_id][alternate_source]
        alternate_to_arm, alternate_to_reason = source_arm_matches[movement.to_arm_id][alternate_source]
        if alternate_from_arm and alternate_to_arm:
            alternate_movement_type, alternate_movement_type_issues = resolve_source_movement_type(
                movement, alternate_source, alternate_from_arm, alternate_to_arm
            )
            alternate_rule = rule_indexes[alternate_source].get(
                (alternate_from_arm, alternate_to_arm, alternate_movement_type, from_road_role)
            )
            if alternate_rule and alternate_rule.rule_status in GENERATABLE_RULE_STATUSES:
                alternate_issues = set(issues)
                alternate_issues.update(alternate_movement_type_issues)
                alternate_issues.add("alternate_source_role_ordinal_projection")
                if "corridor_ordinal_matched" in {alternate_from_reason, alternate_to_reason}:
                    alternate_issues.add("corridor_ordinal_source_arm_projection")
                if not source_from_arm:
                    alternate_issues.add(f"{reference_source.lower()}_from_arm_unmatched")
                if not source_to_arm:
                    alternate_issues.add(f"{reference_source.lower()}_to_arm_unmatched")
                if not issues:
                    alternate_issues.add(f"{reference_source.lower()}_source_rule_unavailable")
                return (
                    alternate_rule,
                    alternate_source,
                    "alternate_source_role_ordinal_projection",
                    tuple(sorted(alternate_issues)),
                )
        if reference_reason == "mixed_source_swsd_basic_rule_fallback" or not source_from_arm or not source_to_arm:
            issues.append("low_confidence_swsd_basic_rule")
            fallback = basic_swsd_rule(primary_movement_type, from_road_role)
            if fallback:
                return fallback, "SWSD", "swsd_basic_rule", tuple(sorted(set(issues)))
        if primary_rule:
            return primary_rule, effective_source, generation_rule, tuple(sorted(set(issues)))
        issues.append(f"{reference_source.lower()}_source_arm_rule_missing")
        if not source_from_arm:
            issues.append(f"{reference_source.lower()}_from_arm_unmatched")
        if not source_to_arm:
            issues.append(f"{reference_source.lower()}_to_arm_unmatched")
        return None, effective_source, generation_rule, tuple(sorted(set(issues)))

    def source_parallel_missing_decisions(movement: ArmMovement, reference_source: str) -> None:
        if f_parallel_counts[movement.from_arm_id] != 0:
            return
        source_from_arm, _ = source_arm_matches[movement.from_arm_id][reference_source]
        source_to_arm, _ = source_arm_matches[movement.to_arm_id][reference_source]
        if not source_from_arm or not source_to_arm:
            return
        source_movement_type, movement_type_issues = resolve_source_movement_type(
            movement, reference_source, source_from_arm, source_to_arm
        )
        rule = rule_indexes[reference_source].get((source_from_arm, source_to_arm, source_movement_type, "parallel_branch"))
        if rule and rule.rule_status in {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}:
            issues = with_validation_issues(
                movement,
                tuple(sorted(set(movement_type_issues).union({"source_parallel_branch_missing_in_frcsd"}))),
            )
            decisions.append(
                FinalGenerationDecision(
                    from_arm_id=movement.from_arm_id,
                    to_arm_id=movement.to_arm_id,
                    movement_type=rule.movement_type,
                    from_road_role="parallel_branch",
                    reference_source=reference_source,
                    rule_status=rule.rule_status,
                    generation_scope="none",
                    generated_road_ids=tuple(),
                    generated_next_road_ids=tuple(),
                    issue_flags=issues,
                )
            )

    movements = result_by_dataset["FRCSD"].arm_movements
    _phase(f"generation loop start movements={len(movements)}")
    for movement_index, movement in enumerate(movements, start=1):
        if movement_index == 1 or movement_index == len(movements) or movement_index % 10 == 0:
            _phase(f"generation loop progress {movement_index}/{len(movements)}")
        profile = profile_by_arm.get(
            movement.from_arm_id,
            ArmSourceProfile("FRCSD", movement.from_arm_id, {}, {}, {}, {}, False, ("empty_arm_source_profile",)),
        )
        reference_source, reference_reason, reference_issues = _choose_reference_source(
            profile, source_arm_matches[movement.from_arm_id]
        )
        source_parallel_missing_decisions(movement, reference_source)
        from_roles = _arm_entering_roles(result_by_dataset["FRCSD"], roles["FRCSD"], movement.from_arm_id)
        from_role_types = sorted({role.road_role for role in from_roles})
        for from_road_role in from_role_types:
            source_rule, effective_source, generation_rule, rule_lookup_issues = rule_for(
                movement=movement,
                from_road_role=from_road_role,
                reference_source=reference_source,
                reference_reason=reference_reason,
            )
            issue_flags = tuple(sorted(set(reference_issues).union(rule_lookup_issues)))
            if source_rule is None:
                rule_status = "insufficient"
                generation_scope = "none"
                evidence_ids: tuple[str, ...] = tuple()
            else:
                rule_status = source_rule.rule_status
                generation_scope = source_rule.generation_scope
                evidence_ids = source_rule.source_evidence_ids
                issue_flags = tuple(sorted(set(issue_flags).union(source_rule.issue_flags)))
            movement_for_output = output_movement(movement, source_rule)
            role_from_roads = tuple(role for role in from_roles if role.road_role == from_road_role)
            target_roles = _generation_target_roles(
                result_frcsd=result_by_dataset["FRCSD"],
                f_roles=roles["FRCSD"],
                to_arm_id=movement.to_arm_id,
                generation_scope=generation_scope,
            )
            if from_road_role == "parallel_branch" and source_rule is not None and rule_status != "prohibited":
                source_from_arm = source_rule.from_arm_id
                if source_parallel_counts[effective_source][source_from_arm] != f_parallel_counts[movement.from_arm_id]:
                    issue_flags = tuple(
                        sorted(set(issue_flags).union({"parallel_branch_count_mismatch_manual_review_required", "data_error"}))
                    )
                    rule_status = "data_error_partial_target_coverage"
                    generation_scope = "none"
                    target_roles = tuple()
            permission = (
                "allowed"
                if rule_status in {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}
                and not has_blocking_issue(issue_flags)
                else "prohibited"
            )
            if rule_status in {"data_error_partial_target_coverage", "insufficient", "conflict"}:
                permission = "manual_review_required"
            generated_from_ids: list[str] = []
            generated_to_ids: list[str] = []
            if permission in {"prohibited", "manual_review_required"}:
                for from_role in role_from_roads:
                    carrier_issues = right_turn_carrier_issues(movement_for_output, from_role)
                    if carrier_issues:
                        issue_flags = tuple(sorted(set(issue_flags).union(carrier_issues)))
                        permission = "manual_review_required"
                        rule_status = "data_error_partial_target_coverage" if "data_error" in carrier_issues else rule_status
                        break
            if permission == "allowed":
                for from_role in role_from_roads:
                    for to_role in target_roles:
                        if from_role.road_id == to_role.road_id:
                            continue
                        from_map = source_map_by_f.get(from_role.road_id)
                        to_map = source_map_by_f.get(to_role.road_id)
                        from_source = _norm((loaded_by_dataset["FRCSD"].roads.get(from_role.road_id).properties or {}).get("source")) if from_role.road_id in loaded_by_dataset["FRCSD"].roads else ""
                        to_source = _norm((loaded_by_dataset["FRCSD"].roads.get(to_role.road_id).properties or {}).get("source")) if to_role.road_id in loaded_by_dataset["FRCSD"].roads else ""
                        pair_rule = generation_rule
                        if generation_rule == "same_source_inherited" and from_source != to_source:
                            pair_rule = "cross_source_primary_source_policy"
                        if generation_rule == "structure_matched_source_rule" and reference_reason.startswith("mixed_source"):
                            pair_rule = "structure_matched_source_rule"
                        source_match_status = ",".join(
                            item
                            for item in (
                                from_map.match_status if from_map else "from_source_map_missing",
                                to_map.match_status if to_map else "to_source_map_missing",
                            )
                            if item
                        )
                        appended = append_feature(from_role.road_id, to_role.road_id, movement_for_output, effective_source, evidence_ids)
                        if appended:
                            generated_from_ids.append(from_role.road_id)
                            generated_to_ids.append(to_role.road_id)
                        audit_rows.append(
                            _audit(
                                f_road_id=from_role.road_id,
                                f_next_road_id=to_role.road_id,
                                movement=movement_for_output,
                                from_role=from_role,
                                to_role=to_role,
                                from_source=from_source,
                                to_source=to_source,
                                primary_source=reference_source,
                                reference_source=effective_source,
                                generation_rule=pair_rule,
                                permission_status="allowed",
                                evidence_ids=evidence_ids,
                                confidence=(
                                    "high"
                                    if source_match_status == "matched,matched"
                                    else (
                                        "low"
                                        if generation_rule in {"swsd_basic_rule", "alternate_source_role_ordinal_projection"}
                                        else "medium"
                                    )
                                ),
                                issue_flags=with_validation_issues(movement_for_output, issue_flags),
                                rule_status=rule_status,
                                generation_scope=generation_scope,
                                generation_basis="rule_projected",
                                source_match_status=source_match_status,
                            )
                        )
            else:
                for from_role in role_from_roads:
                    from_map = source_map_by_f.get(from_role.road_id)
                    from_source = _norm((loaded_by_dataset["FRCSD"].roads.get(from_role.road_id).properties or {}).get("source")) if from_role.road_id in loaded_by_dataset["FRCSD"].roads else ""
                    audit_rows.append(
                        _audit(
                            f_road_id=from_role.road_id,
                            f_next_road_id="",
                            movement=movement_for_output,
                            from_role=from_role,
                            to_role=RoadRole("FRCSD", movement.to_arm_id, "", "", ""),
                            from_source=from_source,
                            to_source="",
                            primary_source=reference_source,
                            reference_source=effective_source if permission == "manual_review_required" else "",
                            generation_rule=generation_rule,
                            permission_status=permission,
                            evidence_ids=evidence_ids,
                            confidence="none" if permission == "manual_review_required" else "medium",
                            issue_flags=with_validation_issues(movement_for_output, issue_flags),
                            rule_status=rule_status,
                            generation_scope=generation_scope,
                            generation_basis="rule_projected",
                            source_match_status=from_map.match_status if from_map else "from_source_map_missing",
                        )
                    )
            decisions.append(
                FinalGenerationDecision(
                    from_arm_id=movement.from_arm_id,
                    to_arm_id=movement.to_arm_id,
                    movement_type=movement_for_output.movement_type,
                    from_road_role=from_road_role,
                    reference_source=effective_source if source_rule is not None else reference_source,
                    rule_status=rule_status,
                    generation_scope=generation_scope,
                    generated_road_ids=tuple(sorted(set(generated_from_ids))),
                    generated_next_road_ids=tuple(sorted(set(generated_to_ids))),
                    issue_flags=with_validation_issues(movement_for_output, issue_flags),
                )
            )
    _phase(f"generation loop done features={len(features)} audit={len(audit_rows)} decisions={len(decisions)}")
    issue_report = _issues_from_audit(source_map, parallel_alignment, audit_rows, duplicate_count)
    source_counts = Counter(item.match_status for item in source_map)
    audit_counts = Counter(item.generation_rule for item in audit_rows if item.permission_status == "allowed")
    parallel_counts = Counter(item.alignment_status for item in parallel_alignment)
    rule_status_counts = Counter(item.rule_status for item in decisions)
    metrics = {
        "frcsd_generated_road_next_road_count": len(features),
        "frcsd_source_geometry_match_missing_count": source_counts.get("source_geometry_match_missing", 0),
        "frcsd_source_geometry_match_ambiguous_count": source_counts.get("ambiguous_source_geometry_match", 0),
        "frcsd_same_source_inherited_count": audit_counts.get("same_source_inherited", 0),
        "frcsd_cross_source_generated_count": audit_counts.get("cross_source_primary_source_policy", 0),
        "frcsd_fallback_to_swsd_count": audit_counts.get("rcsd_to_swsd_fallback", 0),
        "frcsd_alternate_source_projected_count": audit_counts.get("alternate_source_role_ordinal_projection", 0),
        "frcsd_swsd_basic_rule_count": audit_counts.get("swsd_basic_rule", 0),
        "frcsd_rule_projected_count": sum(1 for item in audit_rows if item.permission_status == "allowed"),
        "frcsd_data_error_partial_target_coverage_count": rule_status_counts.get("data_error_partial_target_coverage", 0),
        "frcsd_manual_review_required_count": sum(1 for item in audit_rows if item.permission_status == "manual_review_required"),
        "frcsd_parallel_branch_alignment_count": len(parallel_alignment),
        "frcsd_parallel_branch_count_matched_ordered_count": parallel_counts.get("count_matched_ordered", 0),
        "frcsd_parallel_branch_manual_review_required_count": sum(
            parallel_counts.get(status, 0)
            for status in (
                "source_missing_in_frcsd",
                "count_mismatch_manual_review_required",
                "insufficient_geometry_for_ordering",
            )
        ),
    }
    return FrcsdRoadNextRoadFinalResult(
        features=tuple(features),
        source_road_map=source_map,
        source_movement_policy_swsd=policies["SWSD"],
        source_movement_policy_rcsd=policies["RCSD"],
        arm_source_profiles=arm_source_profiles,
        source_arm_pass_rules_swsd=source_arm_pass_rules["SWSD"],
        source_arm_pass_rules_rcsd=source_arm_pass_rules["RCSD"],
        final_generation_decisions=tuple(decisions),
        parallel_branch_alignment=parallel_alignment,
        audit=tuple(audit_rows),
        issue_report=issue_report,
        metrics=metrics,
    )
