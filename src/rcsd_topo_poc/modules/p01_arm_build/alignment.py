from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.alignment_io import CaseA1Artifacts
from rcsd_topo_poc.modules.p01_arm_build.alignment_models import (
    ALIGNMENT_DATASETS,
    PAIR_DEFINITIONS,
    SOURCE_DATASETS,
    ArmAlignmentCandidate,
    ArmBuildFeedback,
    ArmProfile,
    CaseAlignmentResult,
    LogicalArmGroup,
    RawArmAlignment,
    SourceExtraArm,
    confidence_from_score,
    priority_min,
)
from rcsd_topo_poc.modules.p01_arm_build.models import LoadedDataset


SOURCE_CANDIDATE_MIN_SCORE = 60.0
SOURCE_CANDIDATE_SELECTION_MARGIN = 20.0
SOURCE_ASSIGNMENT_EXHAUSTIVE_LIMIT = 12


def build_case_alignment(case: CaseA1Artifacts, loaded_by_dataset: dict[str, LoadedDataset]) -> CaseAlignmentResult:
    profiles_by_dataset = {
        dataset: tuple(build_arm_profiles(case.group_id, dataset, case.datasets[dataset], loaded_by_dataset.get(dataset)))
        for dataset in ALIGNMENT_DATASETS
    }
    candidates = _rank_candidates(_build_candidates(case.group_id, profiles_by_dataset))
    groups, selected_candidates, feedback = _build_logical_groups(case.group_id, profiles_by_dataset, candidates)
    raw_by_source = _build_raw_alignments(case.group_id, profiles_by_dataset, groups, selected_candidates)
    source_extra = _build_source_extra(case.group_id, profiles_by_dataset, selected_candidates, candidates)
    issue_reports = _build_issue_reports(raw_by_source, source_extra)
    metrics = _case_metrics(groups, candidates, raw_by_source, feedback, source_extra)
    priority = "P3"
    for group in groups:
        priority = priority_min(priority, group.review_priority)
    for item in source_extra:
        priority = priority_min(priority, item.review_priority)
    for item in feedback:
        priority = priority_min(priority, item.review_priority)
    return CaseAlignmentResult(
        group_id=case.group_id,
        profiles_by_dataset=profiles_by_dataset,
        candidates=tuple(selected_candidates),
        logical_arm_groups=tuple(groups),
        raw_alignments_by_source=raw_by_source,
        feedback=tuple(feedback),
        source_extra_arms=tuple(source_extra),
        issue_reports_by_source=issue_reports,
        metrics=metrics,
        review_priority=priority,
    )


def build_arm_profiles(
    group_id: str,
    dataset: str,
    artifacts: Any,
    loaded: LoadedDataset | None,
) -> list[ArmProfile]:
    initial_by_id = {str(item.get("initial_arm_id")): item for item in artifacts.initial_arms}
    traces_by_initial: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in artifacts.arm_traces:
        initial_id = trace.get("assigned_initial_arm_id")
        if initial_id:
            traces_by_initial[str(initial_id)].append(trace)

    decisions_by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in artifacts.through_decisions:
        decisions_by_trace[str(decision.get("trace_id"))].append(decision)

    local_by_initial: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in artifacts.local_arm_candidates:
        for initial_id in candidate.get("source_initial_arm_ids", []) or []:
            local_by_initial[str(initial_id)].append(candidate)

    profiles: list[ArmProfile] = []
    for final in artifacts.final_arms:
        source_initial_ids = tuple(str(item) for item in final.get("source_initial_arm_ids", []) or [])
        initial_items = [initial_by_id[item] for item in source_initial_ids if item in initial_by_id]
        if not initial_items and final.get("initial_arm"):
            initial_items = [final["initial_arm"]]
        member_roads = _sorted_union(item.get("member_road_ids", []) for item in initial_items)
        seed_roads = _sorted_union(item.get("seed_road_ids", []) for item in initial_items)
        connector_roads = _sorted_union(item.get("connector_road_ids", []) for item in initial_items)
        inbound_roads = _sorted_union(item.get("inbound_member_road_ids", []) for item in initial_items)
        outbound_roads = _sorted_union(item.get("outbound_member_road_ids", []) for item in initial_items)
        bidirectional_roads = _sorted_union(item.get("bidirectional_member_road_ids", []) for item in initial_items)
        terminal_types = tuple(sorted({str(item.get("terminal_type", "unknown")) for item in initial_items if item}))
        terminal_ids = tuple(sorted({str(item.get("terminal_junction_id")) for item in initial_items if item.get("terminal_junction_id")}))
        terminal_members = _sorted_union(item.get("terminal_member_node_ids", []) for item in initial_items)
        risk_flags = _sorted_union(item.get("risk_flags", []) for item in initial_items)
        build_status = _status_summary(item.get("build_status", "unknown") for item in initial_items)

        trace_items = [trace for initial_id in source_initial_ids for trace in traces_by_initial.get(initial_id, [])]
        trace_ids = tuple(sorted(str(trace.get("trace_id")) for trace in trace_items if trace.get("trace_id")))
        trace_stop_types = tuple(sorted(str(trace.get("stop_type", "unknown")) for trace in trace_items))
        decision_summary: Counter[str] = Counter()
        for trace in trace_items:
            for status in trace.get("through_decisions", []) or []:
                decision_summary[str(status)] += 1
            for decision in decisions_by_trace.get(str(trace.get("trace_id")), []):
                decision_summary[str(decision.get("status", "unknown"))] += 1

        local_candidates = []
        for initial_id in source_initial_ids:
            local_candidates.extend(local_by_initial.get(initial_id, []))
        local_candidate_ids = tuple(sorted({str(item.get("local_arm_candidate_id")) for item in local_candidates}))
        local_stub_roads = _sorted_union(item.get("local_stub_road_ids", []) for item in local_candidates)
        local_angles = [
            float(item["trend_angle_deg"])
            for item in local_candidates
            if item.get("trend_angle_deg") is not None
        ]
        profiles.append(
            ArmProfile(
                dataset=dataset,
                junction_group_id=group_id,
                current_junction_id=str(artifacts.context.get("junction_id", "")),
                arm_id=str(final.get("final_arm_id", "")),
                source_final_arm_id=str(final.get("final_arm_id", "")),
                source_initial_arm_ids=source_initial_ids,
                member_road_ids=member_roads,
                seed_road_ids=seed_roads,
                connector_road_ids=connector_roads,
                inbound_seed_road_ids=tuple(sorted(set(inbound_roads) & set(seed_roads))),
                outbound_seed_road_ids=tuple(sorted(set(outbound_roads) & set(seed_roads))),
                bidirectional_seed_road_ids=tuple(sorted(set(bidirectional_roads) & set(seed_roads))),
                terminal_type=terminal_types[0] if len(terminal_types) == 1 else ("mixed" if terminal_types else "unknown"),
                terminal_junction_id=terminal_ids[0] if len(terminal_ids) == 1 else None,
                terminal_member_node_ids=terminal_members,
                build_status=build_status,
                risk_flags=risk_flags,
                merge_status=str(final.get("merge_status", "unknown")),
                merge_reason=str(final.get("merge_reason", "")),
                local_candidate_ids=local_candidate_ids,
                local_trend_angle_deg=_mean_angle(local_angles) if local_angles else None,
                local_stub_road_ids=local_stub_roads,
                trace_ids=trace_ids,
                trace_stop_types=trace_stop_types,
                through_decision_summary=dict(sorted(decision_summary.items())),
                geometry_summary=_geometry_summary(member_roads or seed_roads, loaded),
                lineage_summary={},
            )
        )
    return sorted(profiles, key=lambda item: item.arm_id)


def _build_candidates(
    group_id: str,
    profiles_by_dataset: dict[str, tuple[ArmProfile, ...]],
) -> list[ArmAlignmentCandidate]:
    candidates: list[ArmAlignmentCandidate] = []
    index = 1
    for left_dataset, right_dataset in PAIR_DEFINITIONS:
        for left in profiles_by_dataset[left_dataset]:
            for right in profiles_by_dataset[right_dataset]:
                if not _has_structural_evidence(left) and not _has_structural_evidence(right):
                    continue
                candidate = _score_candidate(
                    group_id=group_id,
                    candidate_id=f"{group_id}_cand_{index:04d}",
                    left=left,
                    right=right,
                )
                candidates.append(candidate)
                index += 1
    return candidates


def _score_candidate(*, group_id: str, candidate_id: str, left: ArmProfile, right: ArmProfile) -> ArmAlignmentCandidate:
    seed_score, seed_flags, seed_conflicts = _seed_role_score(left, right)
    local_score, local_flags = _local_candidate_score(left, right)
    trace_score, trace_flags, trace_conflicts = _trace_terminal_score(left, right)
    coverage_score, coverage_flags = _road_coverage_score(left, right)
    geometry_score, geometry_flags = _geometry_score(left, right)
    evidence_flags = tuple(sorted(set(seed_flags + local_flags + trace_flags + coverage_flags + geometry_flags)))
    conflict_flags = tuple(sorted(set(seed_conflicts + trace_conflicts)))
    score = round(seed_score + local_score + trace_score + coverage_score + geometry_score, 2)
    confidence = confidence_from_score(score, conflict_flags, non_geometry_score=seed_score + local_score + trace_score + coverage_score)
    return ArmAlignmentCandidate(
        candidate_id=candidate_id,
        junction_group_id=group_id,
        left_dataset=left.dataset,
        right_dataset=right.dataset,
        left_arm_id=left.arm_id,
        right_arm_id=right.arm_id,
        score=score,
        confidence=confidence,
        seed_role_score=seed_score,
        local_candidate_score=local_score,
        trace_terminal_score=trace_score,
        road_coverage_score=coverage_score,
        geometry_score=geometry_score,
        evidence_flags=evidence_flags,
        conflict_flags=conflict_flags,
    )


def _rank_candidates(candidates: list[ArmAlignmentCandidate]) -> tuple[ArmAlignmentCandidate, ...]:
    by_left: dict[tuple[str, str], list[ArmAlignmentCandidate]] = defaultdict(list)
    by_right: dict[tuple[str, str], list[ArmAlignmentCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_left[(candidate.left_dataset, candidate.left_arm_id)].append(candidate)
        by_right[(candidate.right_dataset, candidate.right_arm_id)].append(candidate)

    left_ranks: dict[str, int] = {}
    right_ranks: dict[str, int] = {}
    for items in by_left.values():
        for rank, candidate in enumerate(sorted(items, key=lambda item: item.score, reverse=True), start=1):
            left_ranks[candidate.candidate_id] = rank
    for items in by_right.values():
        for rank, candidate in enumerate(sorted(items, key=lambda item: item.score, reverse=True), start=1):
            right_ranks[candidate.candidate_id] = rank
    return tuple(
        replace(
            candidate,
            rank_for_left_arm=left_ranks.get(candidate.candidate_id, 0),
            rank_for_right_arm=right_ranks.get(candidate.candidate_id, 0),
        )
        for candidate in candidates
    )


def _build_logical_groups(
    group_id: str,
    profiles_by_dataset: dict[str, tuple[ArmProfile, ...]],
    candidates: tuple[ArmAlignmentCandidate, ...],
) -> tuple[list[LogicalArmGroup], list[ArmAlignmentCandidate], list[ArmBuildFeedback]]:
    provisional: list[dict[str, Any]] = []
    for index, f_profile in enumerate(profiles_by_dataset["FRCSD"], start=1):
        selected_by_source = {
            source_dataset: _select_source_candidates(f_profile, source_dataset, candidates)
            for source_dataset in SOURCE_DATASETS
        }
        provisional.append({"index": index, "f": f_profile, "selected": selected_by_source})

    _resolve_source_candidate_reuse(provisional)

    selected_ids: set[str] = set()
    source_selection: dict[str, dict[str, list[str]]] = {dataset: defaultdict(list) for dataset in SOURCE_DATASETS}
    for item in provisional:
        f_profile: ArmProfile = item["f"]
        selected_by_source: dict[str, tuple[ArmAlignmentCandidate, ...]] = item["selected"]
        for source_dataset, items in selected_by_source.items():
            for candidate in items:
                selected_ids.add(candidate.candidate_id)
                source_selection[source_dataset][candidate.arm_id_for(source_dataset)].append(f_profile.arm_id)

    over_merged_by_dataset = {
        dataset: {
            arm_id: sorted(set(f_arm_ids))
            for arm_id, f_arm_ids in usage.items()
            if len(set(f_arm_ids)) > 1
        }
        for dataset, usage in source_selection.items()
    }

    groups: list[LogicalArmGroup] = []
    feedback: list[ArmBuildFeedback] = []
    for item in provisional:
        logical_id = f"LAG_{item['index']:03d}"
        f_profile: ArmProfile = item["f"]
        selected_by_source: dict[str, tuple[ArmAlignmentCandidate, ...]] = item["selected"]
        group, group_feedback = _logical_group_from_selection(
            group_id=group_id,
            logical_id=logical_id,
            f_profile=f_profile,
            selected_by_source=selected_by_source,
            over_merged_by_dataset=over_merged_by_dataset,
        )
        groups.append(group)
        feedback.extend(group_feedback)

    selected_candidates = [
        replace(candidate, selected=True, selection_reason="selected_for_logical_arm_group")
        if candidate.candidate_id in selected_ids
        else candidate
        for candidate in candidates
    ]
    return groups, selected_candidates, feedback


def _select_source_candidates(
    f_profile: ArmProfile,
    source_dataset: str,
    candidates: tuple[ArmAlignmentCandidate, ...],
) -> tuple[ArmAlignmentCandidate, ...]:
    pool = [
        candidate
        for candidate in candidates
        if {candidate.left_dataset, candidate.right_dataset} == {"FRCSD", source_dataset}
        and candidate.arm_id_for("FRCSD") == f_profile.arm_id
        and candidate.confidence != "reject"
    ]
    if not pool:
        return tuple()
    pool = sorted(pool, key=lambda item: item.score, reverse=True)
    top = pool[0]
    if top.confidence == "conflict" or top.score < SOURCE_CANDIDATE_MIN_SCORE:
        return (top,)
    selected = [
        candidate
        for candidate in pool
        if candidate.score >= SOURCE_CANDIDATE_MIN_SCORE
        and top.score - candidate.score <= SOURCE_CANDIDATE_SELECTION_MARGIN
    ]
    return tuple(selected or [top])


def _resolve_source_candidate_reuse(provisional: list[dict[str, Any]]) -> None:
    for source_dataset in SOURCE_DATASETS:
        assigned_by_f = _exclusive_source_assignments(provisional, source_dataset)
        assigned_owner_by_source = {
            candidate.arm_id_for(source_dataset): f_arm_id for f_arm_id, candidate in assigned_by_f.items()
        }
        for item in provisional:
            f_profile: ArmProfile = item["f"]
            selected_by_source: dict[str, tuple[ArmAlignmentCandidate, ...]] = item["selected"]
            selected = selected_by_source[source_dataset]
            assigned = assigned_by_f.get(f_profile.arm_id)
            if assigned is None:
                continue
            resolved = [assigned]
            for candidate in selected:
                if candidate.candidate_id == assigned.candidate_id:
                    continue
                source_arm_id = candidate.arm_id_for(source_dataset)
                owner_f_arm_id = assigned_owner_by_source.get(source_arm_id)
                if owner_f_arm_id is not None and owner_f_arm_id != f_profile.arm_id:
                    continue
                if _candidate_can_resolve_source_reuse(candidate):
                    resolved.append(candidate)
            selected_by_source[source_dataset] = tuple(_dedupe_candidates(resolved))


def _exclusive_source_assignments(
    provisional: list[dict[str, Any]],
    source_dataset: str,
) -> dict[str, ArmAlignmentCandidate]:
    candidates_by_f = [
        (
            item["f"].arm_id,
            tuple(
                sorted(
                    (
                        candidate
                        for candidate in item["selected"][source_dataset]
                        if _candidate_can_resolve_source_reuse(candidate)
                    ),
                    key=lambda candidate: _candidate_assignment_sort_key(candidate, source_dataset),
                    reverse=True,
                )
            ),
        )
        for item in provisional
    ]
    if not any(items for _, items in candidates_by_f):
        return {}
    source_count = len({candidate.arm_id_for(source_dataset) for _, items in candidates_by_f for candidate in items})
    if len(candidates_by_f) <= SOURCE_ASSIGNMENT_EXHAUSTIVE_LIMIT and source_count <= SOURCE_ASSIGNMENT_EXHAUSTIVE_LIMIT:
        return _best_exclusive_source_assignment(candidates_by_f, source_dataset)
    return _greedy_exclusive_source_assignment(candidates_by_f, source_dataset)


def _best_exclusive_source_assignment(
    candidates_by_f: list[tuple[str, tuple[ArmAlignmentCandidate, ...]]],
    source_dataset: str,
) -> dict[str, ArmAlignmentCandidate]:
    best_score = -1.0
    best_count = -1
    best_assignment: dict[str, ArmAlignmentCandidate] = {}

    def visit(
        index: int,
        used_source_arm_ids: set[str],
        assignment: dict[str, ArmAlignmentCandidate],
        score: float,
    ) -> None:
        nonlocal best_count, best_score, best_assignment
        if len(assignment) + len(candidates_by_f) - index < best_count:
            return
        if index == len(candidates_by_f):
            count = len(assignment)
            rounded_score = round(score, 2)
            if count > best_count or (count == best_count and rounded_score > best_score):
                best_count = count
                best_score = rounded_score
                best_assignment = dict(assignment)
            return

        f_arm_id, candidates = candidates_by_f[index]
        visit(index + 1, used_source_arm_ids, assignment, score)
        for candidate in candidates:
            source_arm_id = candidate.arm_id_for(source_dataset)
            if source_arm_id in used_source_arm_ids:
                continue
            used_source_arm_ids.add(source_arm_id)
            assignment[f_arm_id] = candidate
            visit(index + 1, used_source_arm_ids, assignment, score + candidate.score)
            assignment.pop(f_arm_id, None)
            used_source_arm_ids.remove(source_arm_id)

    visit(0, set(), {}, 0.0)
    return best_assignment


def _greedy_exclusive_source_assignment(
    candidates_by_f: list[tuple[str, tuple[ArmAlignmentCandidate, ...]]],
    source_dataset: str,
) -> dict[str, ArmAlignmentCandidate]:
    assignment: dict[str, ArmAlignmentCandidate] = {}
    used_source_arm_ids: set[str] = set()
    ordered = sorted(
        candidates_by_f,
        key=lambda item: _candidate_assignment_sort_key(item[1][0], source_dataset) if item[1] else (-1.0, 0, 0, ""),
        reverse=True,
    )
    for f_arm_id, candidates in ordered:
        for candidate in candidates:
            source_arm_id = candidate.arm_id_for(source_dataset)
            if source_arm_id in used_source_arm_ids:
                continue
            assignment[f_arm_id] = candidate
            used_source_arm_ids.add(source_arm_id)
            break
    return assignment


def _candidate_can_resolve_source_reuse(candidate: ArmAlignmentCandidate) -> bool:
    return candidate.score >= SOURCE_CANDIDATE_MIN_SCORE and candidate.confidence != "conflict" and not candidate.conflict_flags


def _candidate_assignment_sort_key(candidate: ArmAlignmentCandidate, source_dataset: str) -> tuple[float, int, int, str]:
    return (
        candidate.score,
        -_candidate_rank_for_dataset(candidate, "FRCSD"),
        -_candidate_rank_for_dataset(candidate, source_dataset),
        candidate.candidate_id,
    )


def _candidate_rank_for_dataset(candidate: ArmAlignmentCandidate, dataset: str) -> int:
    if dataset == candidate.left_dataset:
        return candidate.rank_for_left_arm or 9999
    if dataset == candidate.right_dataset:
        return candidate.rank_for_right_arm or 9999
    return 9999


def _dedupe_candidates(candidates: list[ArmAlignmentCandidate]) -> list[ArmAlignmentCandidate]:
    result: list[ArmAlignmentCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in seen:
            continue
        seen.add(candidate.candidate_id)
        result.append(candidate)
    return result


def _logical_group_from_selection(
    *,
    group_id: str,
    logical_id: str,
    f_profile: ArmProfile,
    selected_by_source: dict[str, tuple[ArmAlignmentCandidate, ...]],
    over_merged_by_dataset: dict[str, dict[str, list[str]]],
) -> tuple[LogicalArmGroup, list[ArmBuildFeedback]]:
    missing: list[str] = []
    partial: list[str] = []
    over_split: list[str] = []
    over_merged: list[str] = []
    risk_flags: list[str] = []
    feedback: list[ArmBuildFeedback] = []
    status = "stable"
    priority = "P2"

    source_arm_ids = {
        dataset: tuple(sorted(candidate.arm_id_for(dataset) for candidate in selected_by_source[dataset]))
        for dataset in SOURCE_DATASETS
    }
    for dataset, items in selected_by_source.items():
        if not items:
            missing.append(dataset)
            priority = priority_min(priority, "P0" if dataset == "SWSD" else "P1")
            continue
        if any(candidate.confidence == "conflict" or candidate.conflict_flags for candidate in items):
            status = "conflict"
            priority = "P0"
            risk_flags.append(f"{dataset.lower()}_candidate_conflict")
        if any("coverage_partial" in candidate.evidence_flags for candidate in items):
            partial.append(dataset)
            priority = priority_min(priority, "P1")
        if len(items) > 1:
            if _selected_candidates_resolve_over_split(items):
                over_split.append(dataset)
                priority = priority_min(priority, "P1")
                feedback.append(
                    _feedback(
                        group_id,
                        dataset,
                        "recommended_merge",
                        source_arm_ids[dataset],
                        (logical_id,),
                        "multiple source arms align to one FRCSD logical arm with compatible evidence",
                        "medium",
                    )
                )
            else:
                status = "source_over_split_unresolved"
                over_split.append(dataset)
                priority = "P0"
                risk_flags.append(f"{dataset.lower()}_over_split_unresolved")
        for source_arm_id in source_arm_ids[dataset]:
            if source_arm_id in over_merged_by_dataset.get(dataset, {}):
                status = "source_over_merged_unresolved"
                over_merged.append(dataset)
                priority = "P0"
                risk_flags.append(f"{dataset.lower()}_over_merged_unresolved")
                feedback.append(
                    _feedback(
                        group_id,
                        dataset,
                        "recommended_split",
                        (source_arm_id,),
                        (logical_id,),
                        "one source arm aligns to multiple FRCSD arms; A2 does not split it automatically",
                        "medium",
                    )
                )

    if status == "stable":
        if over_split:
            status = "source_over_split_resolved"
        elif missing:
            status = "source_missing"
        elif partial:
            status = "source_partial"
        elif any(candidate.confidence == "low" for items in selected_by_source.values() for candidate in items):
            status = "uncertain"
            priority = priority_min(priority, "P0")

    acceptable = status in {"stable", "source_missing", "source_partial", "source_over_split_resolved"}
    if not acceptable:
        priority = "P0"
    if f_profile.merge_status == "local_candidate_fallback":
        priority = priority_min(priority, "P1")
        risk_flags.append("frcsd_local_candidate_fallback")

    evidence_summary = {
        "frcsd_merge_status": f_profile.merge_status,
        "selected_candidates": {
            dataset: [candidate.candidate_id for candidate in items]
            for dataset, items in selected_by_source.items()
        },
        "candidate_scores": {
            dataset: [candidate.score for candidate in items]
            for dataset, items in selected_by_source.items()
        },
    }
    return (
        LogicalArmGroup(
            logical_arm_group_id=logical_id,
            junction_group_id=group_id,
            frcsd_arm_ids=(f_profile.arm_id,),
            swsd_arm_ids=source_arm_ids["SWSD"],
            rcsd_arm_ids=source_arm_ids["RCSD"],
            group_status=status,
            acceptable_for_downstream=acceptable,
            missing_datasets=tuple(sorted(set(missing))),
            partial_datasets=tuple(sorted(set(partial))),
            over_split_datasets=tuple(sorted(set(over_split))),
            over_merged_datasets=tuple(sorted(set(over_merged))),
            evidence_summary=evidence_summary,
            risk_flags=tuple(sorted(set(risk_flags))),
            review_priority=priority,
        ),
        feedback,
    )


def _build_raw_alignments(
    group_id: str,
    profiles_by_dataset: dict[str, tuple[ArmProfile, ...]],
    groups: list[LogicalArmGroup],
    candidates: list[ArmAlignmentCandidate],
) -> dict[str, tuple[RawArmAlignment, ...]]:
    profile_by_dataset = {
        dataset: {profile.arm_id: profile for profile in profiles}
        for dataset, profiles in profiles_by_dataset.items()
    }
    selected_by_pair = {
        (candidate.arm_id_for("FRCSD"), dataset): candidate
        for candidate in candidates
        if candidate.selected
        for dataset in SOURCE_DATASETS
        if dataset in {candidate.left_dataset, candidate.right_dataset}
    }
    source_usage: dict[tuple[str, str], set[str]] = defaultdict(set)
    for group in groups:
        for dataset, arm_ids in (("SWSD", group.swsd_arm_ids), ("RCSD", group.rcsd_arm_ids)):
            for arm_id in arm_ids:
                source_usage[(dataset, arm_id)].update(group.frcsd_arm_ids)

    result: dict[str, list[RawArmAlignment]] = {dataset: [] for dataset in SOURCE_DATASETS}
    for group in groups:
        f_arm_id = group.frcsd_arm_ids[0]
        f_profile = profile_by_dataset["FRCSD"][f_arm_id]
        for dataset, arm_ids in (("SWSD", group.swsd_arm_ids), ("RCSD", group.rcsd_arm_ids)):
            source_profiles = [profile_by_dataset[dataset][arm_id] for arm_id in arm_ids if arm_id in profile_by_dataset[dataset]]
            selected_candidates = [selected_by_pair.get((f_arm_id, dataset))] if arm_ids else []
            selected_candidates = [candidate for candidate in selected_candidates if candidate is not None]
            score = max((candidate.score for candidate in selected_candidates), default=0.0)
            confidence = _alignment_confidence(group, selected_candidates)
            match_type = _match_type(group, dataset, arm_ids, source_usage)
            result[dataset].append(
                RawArmAlignment(
                    alignment_id=f"{group.logical_arm_group_id}_{dataset}",
                    junction_group_id=group_id,
                    source_dataset=dataset,
                    target_dataset="FRCSD",
                    f_arm_id=f_arm_id,
                    source_arm_ids=arm_ids,
                    match_type=match_type,
                    coverage_status=_coverage_status(group, dataset, match_type),
                    confidence=confidence,
                    candidate_score=score,
                    source_initial_arm_ids=tuple(sorted({item for profile in source_profiles for item in profile.source_initial_arm_ids})),
                    f_source_initial_arm_ids=f_profile.source_initial_arm_ids,
                    evidence_summary={"logical_group_status": group.group_status, "selected_candidate_scores": [score]},
                    reason_codes=group.risk_flags or (group.group_status,),
                    conflict_flags=tuple(sorted({flag for candidate in selected_candidates for flag in candidate.conflict_flags})),
                    review_priority=group.review_priority,
                    logical_arm_group_id=group.logical_arm_group_id,
                )
            )
    return {dataset: tuple(items) for dataset, items in result.items()}


def _build_source_extra(
    group_id: str,
    profiles_by_dataset: dict[str, tuple[ArmProfile, ...]],
    candidates: list[ArmAlignmentCandidate],
    all_candidates: tuple[ArmAlignmentCandidate, ...],
) -> tuple[SourceExtraArm, ...]:
    used: dict[str, set[str]] = {dataset: set() for dataset in SOURCE_DATASETS}
    for candidate in candidates:
        if not candidate.selected:
            continue
        for dataset in SOURCE_DATASETS:
            if dataset in {candidate.left_dataset, candidate.right_dataset}:
                used[dataset].add(candidate.arm_id_for(dataset))

    extras: list[SourceExtraArm] = []
    for dataset in SOURCE_DATASETS:
        for profile in profiles_by_dataset[dataset]:
            if profile.arm_id in used[dataset]:
                continue
            nearest = [
                {
                    "f_arm_id": candidate.arm_id_for("FRCSD"),
                    "candidate_score": candidate.score,
                    "confidence": candidate.confidence,
                }
                for candidate in sorted(
                    [
                        item
                        for item in all_candidates
                        if {item.left_dataset, item.right_dataset} == {"FRCSD", dataset}
                        and item.arm_id_for(dataset) == profile.arm_id
                    ],
                    key=lambda item: item.score,
                    reverse=True,
                )[:3]
            ]
            extras.append(
                SourceExtraArm(
                    dataset=dataset,
                    source_arm_id=profile.arm_id,
                    reason="source_arm_not_used_by_any_logical_arm_group",
                    nearest_f_arm_candidates=tuple(nearest),
                    review_priority="P0" if dataset == "SWSD" else "P1",
                )
            )
    return tuple(extras)


def _build_issue_reports(
    raw_by_source: dict[str, tuple[RawArmAlignment, ...]],
    source_extra: tuple[SourceExtraArm, ...],
) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for dataset in SOURCE_DATASETS:
        issues: list[dict[str, Any]] = []
        for alignment in raw_by_source[dataset]:
            if alignment.match_type in {"missing", "uncertain", "conflict", "N:M"}:
                issues.append({"issue_type": alignment.match_type, "f_arm_id": alignment.f_arm_id, "priority": alignment.review_priority})
            if alignment.coverage_status in {"partial", "over_split", "over_merged"}:
                issues.append(
                    {
                        "issue_type": alignment.coverage_status,
                        "f_arm_id": alignment.f_arm_id,
                        "source_arm_ids": alignment.source_arm_ids,
                        "priority": alignment.review_priority,
                    }
                )
        for extra in source_extra:
            if extra.dataset == dataset:
                issues.append({"issue_type": "source_extra", "source_arm_id": extra.source_arm_id, "priority": extra.review_priority})
        reports[dataset] = {
            "dataset": dataset,
            "issues": issues,
            "issue_counts": dict(Counter(str(item["issue_type"]) for item in issues)),
        }
    return reports


def _case_metrics(
    groups: list[LogicalArmGroup],
    candidates: tuple[ArmAlignmentCandidate, ...],
    raw_by_source: dict[str, tuple[RawArmAlignment, ...]],
    feedback: list[ArmBuildFeedback],
    source_extra: tuple[SourceExtraArm, ...],
) -> dict[str, Any]:
    statuses = Counter(group.group_status for group in groups)
    raw_statuses = Counter(alignment.match_type for rows in raw_by_source.values() for alignment in rows)
    return {
        "logical_arm_group_count": len(groups),
        "acceptable_logical_arm_group_count": sum(1 for group in groups if group.acceptable_for_downstream),
        "candidate_count": len(candidates),
        "high_candidate_count": sum(1 for item in candidates if item.confidence == "high"),
        "medium_candidate_count": sum(1 for item in candidates if item.confidence == "medium"),
        "feedback_count": len(feedback),
        "source_extra_count": len(source_extra),
        "status_counts": dict(statuses),
        "match_type_counts": dict(raw_statuses),
    }


def _seed_role_score(left: ArmProfile, right: ArmProfile) -> tuple[float, list[str], list[str]]:
    left_roles = _role_set(left)
    right_roles = _role_set(right)
    if not left_roles or not right_roles:
        return 10.0, ["role_missing"], []
    if left_roles == right_roles:
        return 25.0, ["role_consistent"], []
    if "bidirectional" in left_roles or "bidirectional" in right_roles:
        return 22.0, ["role_bidirectional_compatible"], []
    if left_roles == {"inbound"} and right_roles == {"outbound"} or left_roles == {"outbound"} and right_roles == {"inbound"}:
        return 18.0, ["role_complementary"], []
    if left_roles & right_roles:
        return 16.0, ["role_partial_overlap"], []
    return 8.0, ["role_conflict_risk"], []


def _local_candidate_score(left: ArmProfile, right: ArmProfile) -> tuple[float, list[str]]:
    if left.local_trend_angle_deg is None or right.local_trend_angle_deg is None:
        return 8.0, ["local_trend_missing"]
    delta = _angular_distance(left.local_trend_angle_deg, right.local_trend_angle_deg)
    if delta <= 20.0:
        return 25.0, ["local_trend_strong"]
    if delta <= 45.0:
        return 18.0, ["local_trend_medium"]
    if delta <= 90.0:
        return 10.0, ["local_trend_weak"]
    return 4.0, ["local_trend_opposed"]


def _trace_terminal_score(left: ArmProfile, right: ArmProfile) -> tuple[float, list[str], list[str]]:
    conflicts: list[str] = []
    left_statuses = set(left.through_decision_summary) | set(left.trace_stop_types)
    right_statuses = set(right.through_decision_summary) | set(right.trace_stop_types)
    if ("t_side_terminal" in left_statuses and "t_mainline_through" in right_statuses) or (
        "t_side_terminal" in right_statuses and "t_mainline_through" in left_statuses
    ):
        conflicts.append("mixed_mainline_and_side")
    if left.terminal_type == right.terminal_type and left.terminal_type not in {"unknown", "mixed"}:
        return 20.0 + _terminal_id_bonus(left, right), ["terminal_type_consistent"], conflicts
    types = {left.terminal_type, right.terminal_type}
    if "semantic_boundary" in types and ("neighbor_junction" in types or len(types) == 1):
        return 17.0, ["terminal_semantic_compatible"], conflicts
    if "patch_boundary" in types or "dead_end" in types:
        return 12.0, ["terminal_partial"], conflicts
    if "ambiguous_boundary" in types:
        return 8.0, ["terminal_ambiguous"], conflicts
    return 10.0, ["terminal_weak"], conflicts


def _road_coverage_score(left: ArmProfile, right: ArmProfile) -> tuple[float, list[str]]:
    left_count = max(len(left.member_road_ids), len(left.seed_road_ids))
    right_count = max(len(right.member_road_ids), len(right.seed_road_ids))
    if left_count == 0 or right_count == 0:
        return 6.0, ["coverage_missing"]
    ratio = min(left_count, right_count) / max(left_count, right_count)
    if ratio >= 0.65:
        return 20.0, ["coverage_full"]
    if ratio >= 0.35:
        return 14.0, ["coverage_partial"]
    return 8.0, ["coverage_partial"]


def _geometry_score(left: ArmProfile, right: ArmProfile) -> tuple[float, list[str]]:
    left_xy = left.geometry_summary.get("centroid_xy")
    right_xy = right.geometry_summary.get("centroid_xy")
    score = 0.0
    flags: list[str] = []
    if left.local_trend_angle_deg is not None and right.local_trend_angle_deg is not None:
        delta = _angular_distance(left.local_trend_angle_deg, right.local_trend_angle_deg)
        score += max(0.0, 15.0 * (1.0 - min(delta, 90.0) / 90.0))
        flags.append("geometry_trend_aux")
    if left_xy and right_xy:
        distance = math.dist(left_xy, right_xy)
        score += max(0.0, 10.0 * (1.0 - min(distance, 120.0) / 120.0))
        flags.append("geometry_distance_aux")
    return round(min(score, 25.0), 2), flags or ["geometry_missing"]


def _feedback(
    group_id: str,
    dataset: str,
    feedback_type: str,
    arm_ids: tuple[str, ...],
    logical_ids: tuple[str, ...],
    reason: str,
    confidence: str,
) -> ArmBuildFeedback:
    return ArmBuildFeedback(
        feedback_id=f"{group_id}_{dataset}_{feedback_type}_{'_'.join(arm_ids) or 'none'}",
        junction_group_id=group_id,
        dataset=dataset,
        feedback_type=feedback_type,
        source_arm_ids=arm_ids,
        supporting_datasets=tuple(sorted(set(ALIGNMENT_DATASETS) - {dataset})),
        supporting_logical_arm_group_ids=logical_ids,
        reason=reason,
        confidence=confidence,
        review_priority="P0" if feedback_type == "recommended_split" else "P1",
        evidence_summary={"reason": reason},
    )


def _selected_candidates_resolve_over_split(items: tuple[ArmAlignmentCandidate, ...]) -> bool:
    return bool(items) and all(item.score >= 60.0 and not item.conflict_flags for item in items)


def _alignment_confidence(group: LogicalArmGroup, candidates: list[ArmAlignmentCandidate]) -> str:
    if group.group_status == "conflict":
        return "conflict"
    if not candidates:
        return "missing"
    order = {"high": 3, "medium": 2, "low": 1, "reject": 0, "conflict": -1}
    return max((candidate.confidence for candidate in candidates), key=lambda item: order.get(item, 0))


def _match_type(group: LogicalArmGroup, dataset: str, arm_ids: tuple[str, ...], usage: dict[tuple[str, str], set[str]]) -> str:
    if not arm_ids:
        return "missing"
    if group.group_status == "conflict":
        return "conflict"
    if group.group_status == "uncertain":
        return "uncertain"
    many_source = len(arm_ids) > 1
    many_f = any(len(usage[(dataset, arm_id)]) > 1 for arm_id in arm_ids)
    if many_source and many_f:
        return "N:M"
    if many_source:
        return "1:N"
    if many_f:
        return "N:1"
    return "1:1"


def _coverage_status(group: LogicalArmGroup, dataset: str, match_type: str) -> str:
    if match_type == "missing":
        return "none"
    if dataset in group.partial_datasets:
        return "partial"
    if dataset in group.over_split_datasets:
        return "over_split"
    if dataset in group.over_merged_datasets:
        return "over_merged"
    if match_type in {"conflict", "uncertain"}:
        return "unknown"
    return "full"


def _has_structural_evidence(profile: ArmProfile) -> bool:
    return bool(profile.member_road_ids or profile.seed_road_ids or profile.trace_ids or profile.local_candidate_ids)


def _role_set(profile: ArmProfile) -> set[str]:
    roles: set[str] = set()
    if profile.inbound_seed_road_ids:
        roles.add("inbound")
    if profile.outbound_seed_road_ids:
        roles.add("outbound")
    if profile.bidirectional_seed_road_ids:
        roles.add("bidirectional")
    return roles


def _terminal_id_bonus(left: ArmProfile, right: ArmProfile) -> float:
    if not left.terminal_junction_id or not right.terminal_junction_id:
        return 0.0
    return 5.0 if _bare_id(left.terminal_junction_id) == _bare_id(right.terminal_junction_id) else 0.0


def _bare_id(value: str) -> str:
    text = str(value)
    if len(text) > 1 and text[0] in {"R", "F"}:
        return text[1:]
    return text


def _sorted_union(values: Any) -> tuple[str, ...]:
    result: set[str] = set()
    for items in values:
        result.update(str(item) for item in (items or []) if item is not None)
    return tuple(sorted(result))


def _status_summary(values: Any) -> str:
    statuses = tuple(sorted({str(item) for item in values if item}))
    if not statuses:
        return "unknown"
    return statuses[0] if len(statuses) == 1 else "mixed"


def _mean_angle(angles: list[float]) -> float:
    x = sum(math.cos(math.radians(angle)) for angle in angles)
    y = sum(math.sin(math.radians(angle)) for angle in angles)
    return round(math.degrees(math.atan2(y, x)) % 360.0, 2)


def _angular_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _geometry_summary(road_ids: tuple[str, ...], loaded: LoadedDataset | None) -> dict[str, Any]:
    if loaded is None:
        return {"road_count": len(road_ids), "geometry_available": False}
    geometries: list[BaseGeometry] = []
    for road_id in road_ids:
        road = loaded.roads.get(road_id)
        if road is not None and road.geometry is not None and not road.geometry.is_empty:
            geometries.append(road.geometry)
    if not geometries:
        return {"road_count": len(road_ids), "geometry_available": False}
    minx = min(geom.bounds[0] for geom in geometries)
    miny = min(geom.bounds[1] for geom in geometries)
    maxx = max(geom.bounds[2] for geom in geometries)
    maxy = max(geom.bounds[3] for geom in geometries)
    length = sum(float(geom.length) for geom in geometries)
    centroid_x = sum(float(geom.centroid.x) for geom in geometries) / len(geometries)
    centroid_y = sum(float(geom.centroid.y) for geom in geometries) / len(geometries)
    return {
        "road_count": len(road_ids),
        "geometry_available": True,
        "length": round(length, 3),
        "bounds": [round(minx, 3), round(miny, 3), round(maxx, 3), round(maxy, 3)],
        "centroid_xy": [round(centroid_x, 3), round(centroid_y, 3)],
    }
